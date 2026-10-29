"""一轮的编排（设计 §4.2）。S1 接上第 1–7 步；S2 接上国内清单与统计的第 6、8、9 步（`turn/execute.py`），
其余技能随 S3–S6，写工作区随 S5。

1. 权限前置（`gate.resolve`）；拿不到可用的权限判断时按「没拿到权限」答，三个域都不出数。
2. 代码先接住的两种，都不调模型、不取数：
   - 问句去掉标点与空白后为空：答「没能理解这个问题，可以换个说法」，有可查的域时附能力介绍的
     3 个按钮；三域都无权时同样这一句，不当寒暄，也不答请先申请。
   - 三域都无权：代码规则判断是不是寒暄或问能力，是就做能力介绍，不是就只答请先申请。
3. 读最近几轮对话与工作区（`turn/workspace.py`）：上一轮的计划与结局交给规划器。
4–5. 号码直通、规划、规整与校验（`plan/planner.py`）；规划失败按 §14「没能理解这个问题」答。
4 之前：按可查的域取一次主数据（`domains/shared.py`），交规划器作第 7 条的 `classes`、第 15 条的 `entities` 与
   号码直通的机型清单。
6. 对库与换算：时间换算，换算不了的说法产生追问；名字对库（§6.5），对不上、对上多个、重名时追问。
7. 追问：计划本身是追问，或第 6 步产生了追问 → 发 `Event.clarify`，本轮结束（§4.4）。
8–9. 执行与呈现（`turn/execute.py`）：清单与统计；其余技能先答「暂时还答不了」。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import structlog
from forge_core.conversation import conversation_messages
from forge_core.events import Event
from forge_core.module import ModuleManifest, ModuleRequest

from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import (
    ANSWER_PARAMS,
    DEPT_ALIASES,
    FACTORY_REGIONS,
    LINK_SITES,
    TOPIC_TERMS,
)
from factory_issue_module.domains import domestic, shared
from factory_issue_module.domains.base import Ask
from factory_issue_module.plan import clarify, timespan
from factory_issue_module.plan.planner import PlanInputs, Planner
from factory_issue_module.skills import introduce
from factory_issue_module.turn import errors, execute, gate, greeting, workspace

logger = structlog.get_logger(__name__)

#: 规划输入里的「最近几轮」（§10）
HISTORY_TURNS = 3


async def _history(ctx: Any, request: ModuleRequest) -> list[dict[str, str]]:
    try:
        return await conversation_messages(ctx, request, turns=HISTORY_TURNS)
    except Exception as exc:  # noqa: BLE001 —— 读不到历史按没有上文处理（§14）
        logger.warning("factory_issue_history_unreadable", error=type(exc).__name__)
        return []


def _not_ready(access: gate.DomainAccess) -> list[Event]:
    events = [Event.delta(f"{errors.NOT_READY}。")]
    recs = greeting.buttons(access)
    if recs:
        events.append(Event.suggestions(recs))
    return events


async def run_turn(
    manifest: ModuleManifest, request: ModuleRequest, ctx: Any
) -> AsyncIterator[Event]:
    access = gate.resolve(ctx)
    if access is None:
        yield Event.error(errors.ACCESS_UNAVAILABLE_CODE, errors.ACCESS_UNAVAILABLE, fatal=True)
        return

    if greeting.is_blank(request.query):
        for event in greeting.not_understood(access):
            yield event
        return

    if access.none:
        if greeting.is_greeting(request.query):
            for event in greeting.introduce(manifest, access):
                yield event
        else:
            yield Event.delta(f"{errors.NO_DOMAIN}。")
        return

    today = date.today()
    history = await _history(ctx, request)
    previous = await workspace.read_previous(ctx, history)
    topics = await config_files.load(ctx, TOPIC_TERMS)
    dept_aliases = await config_files.load(ctx, DEPT_ALIASES)
    regions = await config_files.load(ctx, FACTORY_REGIONS)
    master = await shared.load(ctx, access.allowed(), request.query)
    entities = master.entities(dept_aliases, regions)
    result = await Planner(manifest, topics).plan(getattr(ctx, "llm", None), PlanInputs(
        query=request.query, history=history, previous_plan=previous.plan,
        previous_outcome=previous.outcome, earlier_query=previous.earlier_query, today=today,
        classes=master.classes(dept_aliases, regions), entities=entities, machines=master.machines or None))
    if result.plan is None:
        for event in greeting.not_understood(access):
            yield event
        return

    steps = [s for s in result.plan.get("steps") or [] if isinstance(s, dict)]
    first = steps[0] if steps else {}
    if first.get("skill") == "clarify":
        yield clarify.event(first.get("params") or {}, request.query)
        return
    if first.get("skill") == "introduce":
        for event in introduce.run(first.get("params") or {}, manifest, access):
            yield event
        return

    spans, unknown = timespan.plan_spans(result.plan, today)
    if unknown is not None:
        yield clarify.event(clarify.time_unknown_step(unknown)["params"], request.query)
        return

    if not any(s.get("skill") in execute.EXECUTABLE for s in steps):
        # 详情、按号查单、文字查找等随 S3–S6 各片接上
        logger.info("factory_issue_skill_not_ready", skills=[str(s.get("skill")) for s in steps])
        for event in _not_ready(access):
            yield event
        return

    # 第 6 步：名字对库（人员按姓名另取）；对不上、对上多个、重名时追问，本轮不取数
    missing = [n for n in execute.person_names(result.plan) if n not in {p.name for p in master.people}]
    if missing:
        master.people += await shared.people_by_name(ctx, missing, dict(master.departments), master.failed)
    answer = await config_files.load(ctx, ANSWER_PARAMS)
    sites = await config_files.load(ctx, LINK_SITES)
    turn = execute.Turn(ctx=ctx, manifest=manifest, access=access, master=master, answer=answer,
                        resolver=domestic.Resolver(master=master, dept_aliases=dept_aliases, regions=regions,
                                                   entities=entities, today=today),
                        query=request.query, today=today, result=result, entities=entities, sites=sites)
    prepared = execute.prepare(result.plan, spans, turn)
    if isinstance(prepared, Ask):
        yield clarify.event({"reason": prepared.reason, "question": prepared.question,
                             "options": prepared.options}, request.query)
        return
    async for event in execute.run(result.plan, prepared, turn):
        yield event
