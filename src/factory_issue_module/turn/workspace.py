"""会话工作区（设计 §10、§4.4 第二条）。S1 写了读 `last`、`turn` 的一半；S5 补上写入、直填与重放要用的几样。

- 每个键的值都是 `{"v": 版本, …}`；读到的版本与 `VERSION` 不同，按没有上文处理并记日志。
- `ctx.workspace` 为 None（没有会话号）或读不到时按没有上文处理；写不进去（`WorkspaceQuotaExceeded` 等）时
  不存、记日志，本轮照常回答（§14）。
- 隔了很多轮：`last` 里的问句原话不在最近几轮的用户发言里，就不给规划器上一轮计划。
- 各键（§10 的表）：
  - `last`：每轮都写（寒暄、能力介绍、没看懂的轮次除外）：问句原话、结局、本轮计划（追问轮为待填参数之前的
    计划）、最近一次查到结果的问句原话。
  - `turn`：只有取过数的轮次覆盖：问句原话、执行计划（`plan` 是规整后、并过之后、直填过的计划，与对照集里
    「上一轮计划」同一形状，交给规划器；`steps` 是每步实际查了哪些域、换算出的起止日期连同原话、各域张数，
    只给执行层用：质疑重查、换图、沿用上一轮的时间；临时统计的步骤另记要算什么与模型写的那份脚本（`custom`，
    S7，版本号随之为 3），质疑、换图时照它重算，不调模型）、时间。
  - `results`：每步每域的结果单 ID 与问题编号（每域至多 `ID_CAP` 个），与 `turn` 一起写；文字查找的步骤另记
    找的是什么与用的说法（`texts`，S6b 加，版本号随之为 2）。
  - `charts`：本轮各段图的数据行（沙箱产出，原样），换图用。
  - `focus`：最近一张被单独说到的单（域、问题编号、单 ID），「这单」「它」用；本轮没有就留着上一张。
  - `pending_clarify`：代码追问时的计划、问话与每个选项怎么填回计划；下一轮问句与某个选项的 `query` 完全相同
    时直接填、不重新规划（`fill`），填好的计划照常过 §4.2 第 6 步。写进去了按钮的 `query` 就是选项本身，问句
    全文（原话加这一项）存在选项的 `full` 里，本轮按它理解；写不进去时按钮发问句全文（`plan/clarify.py`）。
    模型自己写的追问与规整改成的追问（第 17、18 条）计划本身就是追问，没有可填的计划，按钮的问句已说全，照常
    规划。
- 点了追问按钮直填的轮次：`last.query` 记用户发来的原话（隔了很多轮的判断要拿它和会话历史比），`turn.query`
  与 `last.earlier_query` 记问句全文（重放、第 18 条拼「按更早那次的条件查」要一句说全的问句）。
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import structlog
from forge_core.errors import WorkspaceQuotaExceeded

from factory_issue_module.domains import base
from factory_issue_module.domains.base import Ask
from factory_issue_module.plan import names, schema
from factory_issue_module.plan.normalize import Inferred
from factory_issue_module.plan.timespan import Span

logger = structlog.get_logger(__name__)

#: 计划格式（`plan/schema.py`）或下面几个键的结构改了就加一（2：`results` 加 `texts`，S6b；3：`turn.steps` 的临时
#: 统计步骤加 `custom`（要算什么与那份脚本），S7）
VERSION = 3

TURN = "turn"
LAST = "last"
RESULTS = "results"
CHARTS = "charts"
FOCUS = "focus"
PENDING = "pending_clarify"
#: 每步每域存的单 ID 上限（§10）
ID_CAP = 5000

#: `last.outcome` 的取值（§10）
OUTCOME_FOUND = "查到结果"
OUTCOME_EMPTY = "查出 0 张"
OUTCOME_CLARIFY = "追问"
OUTCOME_FAILED = "出错"
NO_RESULT_OUTCOMES = (OUTCOME_EMPTY, OUTCOME_CLARIFY, OUTCOME_FAILED)
#: 上一轮取过数（`turn` 就是那一轮的，或那一轮是换图、重查，`turn` 是它所依据的那一轮）
FETCHED_OUTCOMES = (OUTCOME_FOUND, OUTCOME_EMPTY)


@dataclass(frozen=True)
class Previous:
    """规划要用的上一轮信息；读不到时各项为 None。"""

    #: 上一轮的计划：上一轮查到结果时取 `turn` 里的执行计划，其余结局取 `last` 里的计划
    plan: dict | None = None
    #: 上一轮没有查到结果时的结局（追问、查出 0 张、出错），交给规划器与第 18 条
    outcome: str | None = None
    #: 最近一次查到结果的问句原话（第 18 条拼「按更早那次的条件查」）
    earlier_query: str | None = None
    #: 上一轮取过数时 `turn` 的整条记录（质疑重查、换图、沿用上一轮的时间用）；其余为 None
    turn: dict | None = None


NOTHING = Previous()


# ---------------------------------------------------------------------------- 读写


async def read(ctx: Any, key: str) -> dict | None:
    """读一个键；没有、读不出、版本不对都返回 None。返回的是副本，改它不影响存储。"""
    port = getattr(ctx, "workspace", None)
    if port is None:
        return None
    try:
        value = await port.get(key)
    except Exception as exc:  # noqa: BLE001 —— 工作区读不到按没有上文处理（§14）
        logger.warning("factory_issue_workspace_unreadable", key=key, error=type(exc).__name__)
        return None
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("v") != VERSION:
        logger.info("factory_issue_workspace_version_mismatch", key=key,
                    got=value.get("v") if isinstance(value, Mapping) else type(value).__name__)
        return None
    return copy.deepcopy(dict(value))


async def write(ctx: Any, key: str, value: Mapping[str, Any]) -> bool:
    """覆盖写一个键（带版本号）；写不进去只记日志，返回 False。"""
    port = getattr(ctx, "workspace", None)
    if port is None:
        return False
    try:
        await port.put(key, {"v": VERSION, **value})
        return True
    except WorkspaceQuotaExceeded:
        logger.warning("factory_issue_workspace_quota", key=key)
    except Exception as exc:  # noqa: BLE001 —— 写不进去 = 下一轮缓存未命中，本轮照常回答
        logger.warning("factory_issue_workspace_unwritable", key=key, error=type(exc).__name__)
    return False


async def drop(ctx: Any, key: str) -> None:
    port = getattr(ctx, "workspace", None)
    if port is None:
        return
    try:
        await port.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("factory_issue_workspace_unwritable", key=key, error=type(exc).__name__)


def _user_said(history: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(m.get("content") or "").strip() for m in history if m.get("role") == "user"}


async def read_previous(ctx: Any, history: Sequence[Mapping[str, Any]]) -> Previous:
    last = await read(ctx, LAST)
    if last is None:
        return NOTHING
    query = str(last.get("query") or "").strip()
    if not query or query not in _user_said(history):
        return NOTHING  # 隔了很多轮
    outcome = last.get("outcome")
    earlier = last.get("earlier_query") or None
    turn = await read(ctx, TURN) if outcome in FETCHED_OUTCOMES else None
    if outcome == OUTCOME_FOUND:
        plan = turn.get("plan") if turn else None
        return Previous(plan=plan if isinstance(plan, dict) else None, outcome=None, earlier_query=earlier,
                        turn=turn)
    plan = last.get("plan")
    return Previous(
        plan=plan if isinstance(plan, dict) else None,
        outcome=outcome if outcome in NO_RESULT_OUTCOMES else None,
        earlier_query=earlier,
        turn=turn,
    )


async def write_last(ctx: Any, query: str, outcome: str, plan: dict | None, *, asked: str | None = None) -> None:
    """`last`：最近一次查到结果的问句原话，本轮查到结果就是本轮，否则照抄上一份 `last` 的。`asked` 是本轮按什么
    问句理解（点了追问按钮直填时是原话加选定的一项），记作最近一次查到结果的问句。"""
    if outcome == OUTCOME_FOUND:
        earlier = asked or query
    else:
        before = await read(ctx, LAST)
        earlier = (before or {}).get("earlier_query")
    await write(ctx, LAST, {"query": query, "outcome": outcome, "plan": plan, "earlier_query": earlier})


@dataclass
class TurnRecord:
    """一轮取数的执行记录（`turn/execute.py` 边执行边填，编排在本轮结束时写进工作区）。"""

    #: 步骤编号 → {"skill", "domains": [查了的域], "times": [换算后的时间], "found": {域: 张数}}
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: 步骤编号 → {域: {"ids", "numbers"}}
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: 文字查找的步骤编号 → {"key": 找的是什么（`text/terms.py::key`）, "terms": 用的说法}（递进筛选，S6b）
    texts: dict[str, dict[str, Any]] = field(default_factory=dict)
    charts: list[dict[str, Any]] = field(default_factory=list)
    focus: dict[str, Any] | None = None
    #: 本轮有没有真的取过数（只有取过数的轮次覆盖 `turn`）
    fetched: bool = False
    #: 执行时才产生的追问（手填订单号的候选）：编排发 `clarify` 并写 `pending_clarify`
    ask: Ask | None = None
    #: 导出链接那几句（统计口径之后发）
    exports: list[str] = field(default_factory=list)
    #: 本轮的结局：有没有查到结果、是不是整轮都失败（`last.outcome`）
    found: bool = False
    failed: bool = False


def _capped(results: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sid, by_dom in results.items():
        out[sid] = {}
        for dom, item in (by_dom or {}).items():
            item = item if isinstance(item, Mapping) else {}
            out[sid][str(dom)] = {"ids": [int(x) for x in list(item.get("ids") or [])[:ID_CAP]],
                                  "numbers": [str(x) for x in list(item.get("numbers") or [])[:ID_CAP]]}
    return out


async def write_turn(ctx: Any, query: str, plan: dict, record: TurnRecord) -> None:
    """取过数的轮次：覆盖 `turn`、`results`、`charts`；有新的单独说到的单时覆盖 `focus`。"""
    await write(ctx, TURN, {"query": query, "plan": plan, "steps": record.steps,
                            "at": datetime.now().isoformat(timespec="seconds")})
    await write(ctx, RESULTS, {"steps": _capped(record.results), "texts": record.texts})
    await write(ctx, CHARTS, {"items": record.charts})
    if record.focus:
        await write(ctx, FOCUS, record.focus)


# ---------------------------------------------------------------------------- 换算后的时间


def span_dict(span: Span, basis: str | None = None) -> dict[str, Any]:
    def iso(d: date | None) -> str | None:
        return d.isoformat() if d is not None else None

    return {"said": span.said, "basis": basis, "start": iso(span.start), "end": iso(span.end),
            "rolling_days": span.rolling_days, "to_today": span.to_today, "unlimited": span.unlimited,
            "future": span.future, "period_end": iso(span.period_end)}


def span_from(item: Mapping[str, Any], *, fixed: bool = True) -> Span | None:
    """存下的时间 → `Span`。`fixed` 时滚动窗口按存下的起止日期取（重放、沿用都按当时换算出的日期，§10）。"""
    def day(x: Any) -> date | None:
        try:
            return date.fromisoformat(str(x)) if x else None
        except ValueError:
            return None

    if not isinstance(item, Mapping) or "said" not in item:
        return None
    rolling = item.get("rolling_days")
    return Span(said=str(item.get("said") or ""), start=day(item.get("start")), end=day(item.get("end")),
                rolling_days=None if fixed else (int(rolling) if isinstance(rolling, int) else None),
                to_today=bool(item.get("to_today")), unlimited=bool(item.get("unlimited")),
                future=bool(item.get("future")), period_end=day(item.get("period_end")))


def decided(turn: Mapping[str, Any] | None) -> dict[str, str]:
    """上一轮执行时看原话才定下来的判据（各步 `decided` 的并集，如巴西「涉及费用」按标记还是按明细）。"""
    out: dict[str, str] = {}
    for info in ((turn or {}).get("steps") or {}).values():
        for k, v in ((info or {}).get("decided") or {}).items():
            out.setdefault(str(k), str(v))
    return out


def stored_scripts(turn: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """`turn` 里各步临时统计存下的（要算什么、脚本）：质疑重查、换图、「那上个月呢」要算的一样时照它重算（§5.5）。"""
    out: list[dict[str, str]] = []
    for info in ((turn or {}).get("steps") or {}).values():
        custom = (info or {}).get("custom")
        if isinstance(custom, Mapping) and custom.get("script") and custom.get("describe"):
            out.append({"describe": str(custom["describe"]), "script": str(custom["script"])})
    return out


def stored_spans(turn: Mapping[str, Any] | None) -> dict[str, list[Span]]:
    """`turn` 里每步换算好的时间（按步骤编号），重放用。"""
    out: dict[str, list[Span]] = {}
    for sid, info in ((turn or {}).get("steps") or {}).items():
        spans = [span_from(t) for t in (info or {}).get("times") or []]
        out[str(sid)] = [s for s in spans if s is not None]
    return out


def follow_spans(plan: dict, spans: dict[str, list[Span]], turn: Mapping[str, Any] | None) -> dict[str, list[Span]]:
    """沿用上一轮的时间（`from: previous`）以执行计划为准：原话与日期依据都和上一轮某一项相同时，用上一轮换算出
    的起止日期（§10「沿用以执行计划为准」），隔了一夜「最近 30 天」也还是当时那 30 天。本轮重新说了的照本轮换算。"""
    stored: dict[tuple[str, str], Span] = {}
    for info in ((turn or {}).get("steps") or {}).values():
        for t in (info or {}).get("times") or []:
            got = span_from(t)
            if got is not None:
                stored.setdefault((got.said.strip(), str(t.get("basis") or "建单")), got)
    if not stored:
        return spans
    out = dict(spans)
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id"))
        items = [t for t in schema.as_list((step.get("params") or {}).get("time")) if isinstance(t, dict)
                 and t.get("said")]
        mine = list(out.get(sid) or [])
        for i, t in enumerate(items):
            if i >= len(mine) or t.get("from") != "previous" or mine[i].said != t["said"]:
                continue  # 合成过的几项（`timespan._intersect_same_basis`）不替换
            got = stored.get((str(t["said"]).strip(), str(t.get("basis") or "建单")))
            if got is not None:
                mine[i] = got
        out[sid] = mine
    return out


# ---------------------------------------------------------------------------- 追问选项直填（§4.4 第二条）

#: 「名称：类别」选项里的类别 → 条件名（`domains/shared.py` 的类别叫法）
_KIND_FIELDS = {"机型": "机型", "系列": "系列", "部门": "跟进部门", "人员": "跟进人", "供应商": "供应商",
                "国内的加工厂": "加工厂", "巴西的加工厂": "加工厂", "海外的加工厂": "加工厂"}


@dataclass(frozen=True)
class Filled:
    """直填好的计划：跳过规划，照常过第 6 步。"""

    plan: dict
    #: 追问那一轮的问句原话
    query: str
    question: str
    inferred: list[Inferred]
    check_errors: list[str]
    #: 本轮按什么问句理解：追问那一轮的原话加选定的这一项（按钮只写了选项；对库、写分析、答后按钮、
    #: 填不进去时重新规划都按它，§4.4）
    asked: str = ""
    #: 按地区说法追问、选了其中几家时：[{field, said, candidates, chosen}]，本轮写进 `turn.steps`（`rest_scopes`）
    scopes: tuple[dict[str, Any], ...] = ()


def _patch(ask: Ask, option: str) -> dict[str, Any] | None:
    if not ask.fill or ask.said is None:
        return None
    patch: dict[str, Any] = {"kind": ask.fill, "sid": ask.sid, "said": ask.said, "option": option}
    if ask.scope:
        patch["scope"] = {"field": str(ask.scope.get("field") or ""),
                          "candidates": [str(c) for c in ask.scope.get("candidates") or []]}
    return patch


def rest_scopes(turn: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """上一轮 `turn.steps` 里记下的地区候选与选定的几家：条件名 → {said, candidates, chosen}（后一步覆盖前一步）。"""
    out: dict[str, dict[str, Any]] = {}
    for info in ((turn or {}).get("steps") or {}).values():
        for s in (info or {}).get("scopes") or []:
            if isinstance(s, Mapping) and s.get("field") and s.get("candidates"):
                out[str(s["field"])] = {"said": str(s.get("said") or ""),
                                        "candidates": [str(c) for c in s.get("candidates") or []],
                                        "chosen": [str(c) for c in s.get("chosen") or []]}
    return out


async def write_pending(ctx: Any, *, query: str, plan: dict, ask: Ask, recommendations: Sequence[Mapping[str, Any]],
                        full: Sequence[Mapping[str, Any]] = (), inferred: Sequence[Inferred] = (),
                        check_errors: Sequence[str] = ()) -> bool:
    """代码追问的轮次：把计划、问话与每个按钮怎么填写进 `pending_clarify`。没有可填的（位数不对）不写。

    `recommendations` 是发出去的按钮（`query` 用来认下一轮点的是哪个）；`full` 是同一顺序的问句全文（原话加
    这一项，`clarify.recommendations`），点了之后本轮按它理解。返回写没写进去：写进去了按钮才能只写选项（§4.4）。
    """
    options = []
    shown = [str(o).strip() for o in ask.options if str(o).strip()]  # 与 `clarify.recommendations` 同一顺序
    fulls = [str(r.get("query") or "") for r in full]
    for i, (option, rec) in enumerate(zip(shown, recommendations, strict=False)):
        patch = _patch(ask, str(option))
        if patch is not None:
            options.append({"query": str(rec.get("query") or ""), "full": fulls[i] if i < len(fulls) else "",
                            "patch": patch})
    if not options:
        await drop(ctx, PENDING)
        return False
    return await write(ctx, PENDING, {"query": query, "plan": plan, "question": ask.question, "reason": ask.reason,
                                      "options": options,
                                      "inferred": [{"step": x.step, "field": x.field, "values": list(x.values)}
                                                   for x in inferred],
                                      "check_errors": list(check_errors)})


def fill(pending: Mapping[str, Any] | None, query: str) -> Filled | None:
    """本轮问句与上一轮某个追问选项的 `query` 完全相同：把选项填进上一轮的计划。填不进去（计划里找不到那个取值）
    返回 None，照常规划。"""
    if not pending or not isinstance(pending.get("plan"), dict):
        return None
    said = (query or "").strip()
    option = next((o for o in pending.get("options") or [] if str(o.get("query") or "").strip() == said), None)
    if option is None:
        return None
    plan = apply_fill(pending["plan"], option.get("patch") or {})
    if plan is None:
        logger.info("factory_issue_fill_missed", kind=(option.get("patch") or {}).get("kind"))
        return None
    logger.info("factory_issue_fill", kind=option["patch"].get("kind"), reason=pending.get("reason"))
    inferred = [Inferred(step=str(x.get("step")), field=str(x.get("field")), values=tuple(x.get("values") or ()))
                for x in pending.get("inferred") or [] if isinstance(x, Mapping)]
    patch = option["patch"]
    scopes: tuple[dict[str, Any], ...] = ()
    scope = patch.get("scope")
    if isinstance(scope, Mapping) and scope.get("field") and scope.get("candidates"):
        chosen = [x.strip() for x in str(patch.get("option") or "").split("、") if x.strip()]
        scopes = ({"field": str(scope["field"]), "said": str(patch.get("said") or ""),
                   "candidates": [str(c) for c in scope["candidates"]], "chosen": chosen},)
    return Filled(plan=plan, query=str(pending.get("query") or ""), question=str(pending.get("question") or ""),
                  inferred=inferred, check_errors=[str(x) for x in pending.get("check_errors") or []],
                  asked=str(option.get("full") or "").strip() or said, scopes=scopes)


def _same(a: Any, b: str) -> bool:
    return isinstance(a, str | int | float) and not isinstance(a, bool) and (
        str(a).strip() == b.strip() or names.key(a) == names.key(b))


def _steps(plan: dict, sid: str | None) -> list[dict]:
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    mine = [s for s in steps if sid is not None and str(s.get("id")) == sid]
    return mine + [s for s in steps if s not in mine]


def apply_fill(plan: dict, patch: Mapping[str, Any]) -> dict | None:
    """按 `patch` 改计划的副本；找不到要改的那一处返回 None。只在一步里改（先找追问那一步，再找其余各步）。"""
    out = copy.deepcopy(plan)
    kind, said, option = patch.get("kind"), str(patch.get("said") or ""), str(patch.get("option") or "")
    sid = str(patch["sid"]) if patch.get("sid") is not None else None
    if not said or not option:
        return None
    if kind == base.FILL_TIME:
        hit = False
        for step in out.get("steps") or []:
            for t in schema.as_list(((step or {}).get("params") or {}).get("time")):
                if isinstance(t, dict) and _same(t.get("said"), said):
                    t["said"], hit = option, True
        return out if hit else None
    for step in _steps(out, sid):
        p = step.get("params") or {}
        if kind in (base.FILL_KIND_SAID, base.FILL_NUMBER):
            for item in schema.as_list(p.get("numbers")):
                if isinstance(item, dict) and _same(item.get("raw"), said):
                    item["kind_said" if kind == base.FILL_KIND_SAID else "raw"] = option
                    return out
            continue
        for f in schema.as_list(p.get("filters")):
            if not isinstance(f, dict):
                continue
            values = f.get("value")
            items = values if isinstance(values, list) else [values]
            at = next((i for i, v in enumerate(items) if _same(v, said)), None)
            if at is None:
                continue
            if kind == base.FILL_KIND:
                name, _, cls = option.partition("：")
                field_name = _KIND_FIELDS.get(cls.strip())
                if field_name is None:
                    return None
                f["field"] = field_name
                f.pop("column", None)
                if name.strip() and not _same(items[at], name):
                    items[at] = name.strip()
            elif kind == base.FILL_APPEND:
                items[at] = f"{items[at]} {option}"
            else:
                chosen = [x.strip() for x in option.split("、") if x.strip()] or [option]
                items[at:at + 1] = chosen
            f["value"] = items if isinstance(values, list) or len(items) > 1 else items[0]
            return out
    return None
