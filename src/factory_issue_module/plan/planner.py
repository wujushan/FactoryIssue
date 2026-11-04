"""规划（设计 §4.2 第 4、5 步、§5.3、§5.6）。顺序同 spike 的 `run_plan`，§1.3 的分数按它得出。

1. 号码直通：问句只剩号码、号的种类词与固定套话时不调模型，直接生成计划，不经第 5 步。
2. 一次模型调用写计划（`[system, user]`，temperature 0，要 JSON）。先查格式（第 12 条）；格式合格后规整，
   再对规整后的计划做其余校验（第 7 条的校验一半、第 13–15 条）。
3. 格式或校验不过时带着错处修一次（`[system, user, assistant, user]`，前两条原样沿用），两者合计只修一次，
   修后的计划再规整一遍。修后格式仍不合格：第一次只是校验被打回的，用第一次的计划，否则规划失败（§14）。
   只是校验仍不过，按修后的计划执行，`check_errors` 带回去（第 13 条：开头写明按什么理解）。
4. 每次改写、打回各打一条 `factory_issue_plan_rule`（规则编号、技能、改前改后的条件名，不含问句与取值）；
   第 16 条只记日志。模型调用出错或超时同样是规划失败。

主数据按需取（决策 2026-11-01「寒暄不取主数据与追问用例的取数断言」）：给了 `enrich` 时，`inputs` 里先没有
主数据，只在用得到时调 `enrich` 补上。号码直通先不带机型清单判断（机型清单只会多拒几种直通），会直通时才补上
主数据再判断一遍；模型第一次写的计划只有不带条件的 `introduce` 时不补（`introduce_only`），其余计划都先补再
规整、校验、修一次。第一次格式不合格的也在修一次之前补，修后才写成介绍的照样取过主数据。
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from forge_core.module import ModuleManifest

from factory_issue_module.config.files import TopicTerms
from factory_issue_module.plan import normalize, prematch, prompt, schema
from factory_issue_module.plan.normalize import Inferred, RuleHit

logger = structlog.get_logger(__name__)

#: 规划要 JSON；temperature 0 与规划器实测相同（§1.3）
_CHAT_KW: dict[str, Any] = {"temperature": 0.0, "response_format": {"type": "json_object"}}


@dataclass
class PlanResult:
    #: 规整后的计划；None 表示规划失败，按 §14「没能理解这个问题」答
    plan: dict | None
    #: "shortcut"（号码直通）、"model"，或 "filled"（追问选项直填进上一轮的计划，S5，`turn/workspace.py::fill`）
    source: str
    #: 修一次之后仍不过的校验（按模型的计划执行）。执行与呈现（S2 起）要用它：第 13 条仍不一致时开头写明按
    #: 什么日期理解，并给另一种理解的按钮
    check_errors: list[str] = field(default_factory=list)
    hits: list[RuleHit] = field(default_factory=list)
    #: 第 7 条按库里的取值定的类、第 20 条助手按意思定的取值与张数。呈现在开头写「按 X 理解」，模型本来就放对了
    #: 类时同样要写
    inferred: list[Inferred] = field(default_factory=list)
    calls: int = 0


@dataclass(frozen=True)
class PlanInputs:
    query: str
    history: Sequence[Mapping[str, Any]] = ()
    previous_plan: dict | None = None
    previous_outcome: str | None = None
    earlier_query: str | None = None
    #: 第 7 条名字归类用的「类 → 库里的名字」（可查的域的主数据）
    classes: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: 第 15 条与预匹配用的「名字 → 在库里属于哪几类」
    entities: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: 可查的域的机型名称：号码直通不把写了连字符的机型当 PN / PO（S2 起由主数据给）
    machines: Collection[str] | None = None
    today: date | None = None
    #: 第 20 条：没说要几张时列几张（模块配置 `top_n`）；None 用内置默认
    default_limit: int | None = None


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


def _parse(text: str) -> tuple[dict | None, list[str]]:
    try:
        plan = schema.parse_reply(text)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, [f"不是合格的 JSON：{exc}"]
    return plan, schema.check_format(plan)


def _log_hits(hits: Sequence[RuleHit]) -> None:
    for h in hits:
        logger.info("factory_issue_plan_rule", rule=h.rule, action=h.action, skill=h.skill,
                    before=list(h.before), after=list(h.after))


@dataclass
class _Normalized:
    plan: dict
    hits: list[RuleHit] = field(default_factory=list)
    inferred: list[Inferred] = field(default_factory=list)


#: 给 `inputs` 补上主数据（`classes`、`entities`、`machines`）
Enrich = Callable[["PlanInputs"], Awaitable["PlanInputs"]]


#: 规整时会读主数据的参数：第 7 条按 `classes` 给 `filters` 归类；第 4 条把对象写法的 `compare` 改成 `filters`
_MASTER_READ_PARAMS = ("filters", "compare")


def introduce_only(plan: dict | None) -> bool:
    """计划的每一步都是 `introduce`（寒暄、问能力、只读之外的请求、管不着的事），而且都不带条件。

    只有这种计划不取主数据就规整：不带条件时规整出来与带主数据时一样。带了 `filters`、`compare` 的介绍
    （格式校验允许任何技能带）按普通计划先取主数据（评审 2026-11-01 A2）。

    判据与编排不同：编排看第一步是 `introduce` 就按介绍答（`turn/orchestrator.py::run_turn`），这里要每一步都是。
    `[introduce, list_issues]` 这种计划因此会先取主数据、最后照样只答介绍，只是多发几条主数据 SQL。不改成按第一步
    判：后面那步带条件时，规整第 7 条有主数据时可能把整份改成追问，没有时照答介绍，两种结果不同（评审 A4）。
    """
    steps = (plan or {}).get("steps")
    return bool(steps) and isinstance(steps, list) and all(
        isinstance(s, dict) and s.get("skill") == "introduce"
        and not any((s.get("params") or {}).get(k) for k in _MASTER_READ_PARAMS)
        for s in steps)


def with_master(inputs: PlanInputs, *, classes: Mapping[str, Sequence[str]],
                entities: Mapping[str, Sequence[str]], machines: Collection[str] | None) -> PlanInputs:
    return dataclasses.replace(inputs, classes=classes, entities=entities, machines=machines)


def _log_bounce(rules: Sequence[int], plan: dict | None) -> None:
    skill = "+".join(str(s.get("skill")) for s in (plan or {}).get("steps") or [] if isinstance(s, dict))
    for rule in sorted(set(rules)):
        logger.info("factory_issue_plan_rule", rule=rule, action="打回", skill=skill)


class Planner:
    def __init__(self, manifest: ModuleManifest, topics: TopicTerms) -> None:
        self.manifest = manifest
        self.topics = topics

    def _normalize(self, plan: dict, inputs: PlanInputs) -> _Normalized:
        schema.drop_ignored_keys(plan)
        done = _Normalized(plan=plan)
        out = normalize.apply(plan, normalize.Context(
            query=inputs.query, previous=inputs.previous_plan, previous_outcome=inputs.previous_outcome,
            earlier_query=inputs.earlier_query, classes=inputs.classes, topics=self.topics,
            today=inputs.today, hits=done.hits, inferred=done.inferred, default_limit=inputs.default_limit))
        if out is not None:
            done.plan = out
        return done

    def _checks(self, plan: dict, inputs: PlanInputs) -> list[tuple[int, str]]:
        last_user = next((str(m.get("content") or "") for m in reversed(inputs.history) if m.get("role") == "user"),
                         None)
        return normalize.tagged_checks(plan, inputs.query, inputs.entities, inputs.today,
                                       normalize.previous_issue(inputs.previous_plan, last_user))

    def messages(self, inputs: PlanInputs) -> list[dict[str, str]]:
        system = prompt.planner_system(self.manifest, self.topics)
        user = prompt.planner_user(inputs.query, inputs.history, inputs.previous_plan, inputs.previous_outcome)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def plan(self, llm: Any, inputs: PlanInputs, enrich: Enrich | None = None) -> PlanResult:
        """`enrich` 为 None 时 `inputs` 已带主数据；给了时按需补（见文件头末段）。"""
        shortcut = prematch.number_shortcut(inputs.query, inputs.machines)
        if shortcut is not None and enrich is not None:
            # 不带机型清单时会直通：补上机型清单再判断一遍（对得上机型的串不直通）
            inputs, enrich = await enrich(inputs), None
            shortcut = prematch.number_shortcut(inputs.query, inputs.machines)
        if shortcut is not None:
            logger.info("factory_issue_plan_shortcut", skill=shortcut["steps"][0]["skill"])
            return PlanResult(plan=shortcut, source="shortcut")
        if llm is None:
            logger.error("factory_issue_plan_no_llm")
            return PlanResult(plan=None, source="model")

        messages = self.messages(inputs)
        result = PlanResult(plan=None, source="model")
        try:
            first = _content(await llm.chat(messages, **_CHAT_KW))
        except Exception as exc:  # noqa: BLE001 —— 超时或服务出错：按 §14 答，异常只进日志
            logger.warning("factory_issue_plan_call_failed", attempt=1, error=type(exc).__name__)
            result.calls = 1
            return result
        result.calls = 1

        plan, errors = _parse(first)
        # 只有不带条件的介绍时不取主数据：规整第 7 条只看 filters、校验遇到 introduce 在第 13 条之后就返回，
        # 不带条件时带不带主数据规整出来一样。其余计划先补主数据（`introduce_only`）
        light = enrich is not None and not errors and introduce_only(plan)
        if enrich is not None and not light:
            inputs, enrich = await enrich(inputs), None
        first_done: _Normalized | None = None
        checks: list[tuple[int, str]] = []
        if plan is not None and not errors:
            first_done = self._normalize(plan, inputs)
            checks = self._checks(first_done.plan, inputs)
            if enrich is not None and (checks or not introduce_only(first_done.plan)):
                # 规整后不再只是介绍（如第 18 条把沿用上一轮的介绍改成追问）、或被打回（如第 13 条）：补上主数据
                # 按原来的路走
                inputs, enrich = await enrich(inputs), None
                first_done = self._normalize(plan, inputs)
                checks = self._checks(first_done.plan, inputs)
            if not checks:
                return self._done(result, first_done, inputs)
        _log_bounce([12] if errors else [r for r, _ in checks], plan)

        repair = [*messages, {"role": "assistant", "content": first},
                  {"role": "user", "content": prompt.repair_user(errors or [m for _, m in checks])}]
        try:
            second = _content(await llm.chat(repair, **_CHAT_KW))
        except Exception as exc:  # noqa: BLE001
            logger.warning("factory_issue_plan_call_failed", attempt=2, error=type(exc).__name__)
            second = None
        result.calls = 2
        plan2, errors2 = _parse(second) if second is not None else (None, ["修正那次调用出错"])
        if plan2 is None or errors2:
            if first_done is not None:
                # 第一次只是校验被打回、修的那次又不合格：照用第一次的计划
                result.check_errors = [m for _, m in checks]
                return self._done(result, first_done, inputs)
            logger.info("factory_issue_plan_failed", errors=len(errors2))
            return result
        fixed = self._normalize(plan2, inputs)
        still = self._checks(fixed.plan, inputs)
        if still:
            _log_bounce([r for r, _ in still], fixed.plan)
            result.check_errors = [m for _, m in still]
        return self._done(result, fixed, inputs)

    def _done(self, result: PlanResult, done: _Normalized, inputs: PlanInputs) -> PlanResult:
        _log_hits(done.hits)
        missed = normalize.values_not_in_query(done.plan, inputs.query)
        if missed:
            logger.info("factory_issue_plan_rule", rule=16, action="只记日志", fields=missed)
        if done.plan.get("alternatives") and not done.inferred:
            # 规划器给了其他理解，开头却没有可写的「按 X 理解」（每一项在原话里都有依据）：只记日志，看日志再定
            # （开发者 2026-11-04 定，决策 2026-11-04「按什么理解写在开头」）
            logger.info("factory_issue_plan_rule", rule=20, action="只记日志", reason="有其他理解、开头没写")
        result.plan, result.hits, result.inferred = done.plan, done.hits, done.inferred
        return result
