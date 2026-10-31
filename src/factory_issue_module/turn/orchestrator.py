"""一轮的编排（设计 §4.2）。S1 接上第 1–7 步；S2 接上国内清单与统计的第 6、8、9 步（`turn/execute.py`），
S3 接上巴西、海外与跨域合并；S4 接上详情与按号查单（含号码直通的执行）；S5 接上工作区的写入、追问选项直填、
质疑重查与换图；S6b 接上文字查找；临时统计随 S7。

1. 权限前置（`gate.resolve`）；拿不到可用的权限判断时按「没拿到权限」答，三个域都不出数。
2. 代码先接住的两种，都不调模型、不取数：
   - 问句去掉标点与空白后为空：答「没能理解这个问题，可以换个说法」，有可查的域时附能力介绍的
     3 个按钮；三域都无权时同样这一句，不当寒暄，也不答请先申请。
   - 三域都无权：代码规则判断是不是寒暄或问能力，是就做能力介绍，不是就只答请先申请。
3. 读最近几轮对话与工作区（`turn/workspace.py`）：上一轮的计划与结局交给规划器。本轮问句与上一轮代码追问的某个
   选项的 `query` 完全相同时，把选项直接填进上一轮的计划，跳过第 4、5 步（§4.4）；填好的计划照常过第 6 步。
   这种轮次按钮只写了选项（「惠州百富」），本轮按存下的问句全文（原话加这一项）理解。
4–5. 号码直通、规划、规整与校验（`plan/planner.py`）；规划失败按 §14「没能理解这个问题」答。
4 之前：按可查的域取一次主数据（`domains/shared.py`），交规划器作第 7 条的 `classes`、第 15 条的 `entities` 与
   号码直通的机型清单。
6. 对库与换算：时间换算（沿用上一轮的时间按上一轮换算出的日期），换算不了的说法产生追问；名字对库（§6.5），
   对不上、对上多个、重名时追问。
7. 追问：计划本身是追问，或第 6 步产生了追问 → 发 `Event.clarify`，本轮结束（§4.4）；代码追问先写
   `pending_clarify`，写进去了按钮的 `query` 就是选项本身，写不进去时是问句全文。
8–9. 执行与呈现（`turn/execute.py`）：清单、统计、单张单详情、按号查单、按文字找单；质疑重查（`skills/verify_previous.py`）、
   换图（`skills/rerender.py`）按工作区里上一轮的执行计划重放；其余技能先答「暂时还答不了」。
10. 写工作区（§10）：`last` 每轮写（寒暄、能力介绍、没看懂的轮次除外）；只有取过数的轮次覆盖 `turn`、`results`、
    `charts`。
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
    SEGMENTATION,
    TOPIC_TERMS,
)
from factory_issue_module.domains import base, shared
from factory_issue_module.domains.base import Ask
from factory_issue_module.plan import clarify, timespan
from factory_issue_module.plan.planner import PlanInputs, Planner, PlanResult
from factory_issue_module.skills import introduce, rerender, verify_previous
from factory_issue_module.turn import errors, execute, gate, greeting, workspace

logger = structlog.get_logger(__name__)

#: 规划输入里的「最近几轮」（§10）
HISTORY_TURNS = 3
#: 质疑、换图却读不到上一轮时的追问（总述「接着上一轮问」：没有上文时追问，不猜）
NO_PREVIOUS = {"reason": "接不上上一轮", "question": "没有找到上一轮的结果，请把要查的条件说完整一些。", "options": []}
REPLAY_SKILLS = ("verify_previous", "rerender")


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


def _ask_params(ask: Ask) -> dict[str, Any]:
    params: dict[str, Any] = {"reason": ask.reason, "question": ask.question, "options": ask.options}
    if ask.fill == base.FILL_TIME:  # 时间认不出：按钮把原话里那段说法换成选定的时间（§4.4）
        params["said"] = ask.said
    return params


async def _clarify_with_pending(ctx: Any, query: str, plan: dict, ask: Ask, result: PlanResult | None = None,
                               *, button_query: str | None = None) -> Event:
    """代码追问：把计划与每个按钮怎么填写进 `pending_clarify`，`last` 记追问，返回 `clarify`。

    写进去了，按钮的 `query` 就是选项本身（INFO 网页前端把 `query` 当按钮文字，§19「S5 提交后 INFO 前端按钮显示
    问题的处理」），点了按工作区直填；写不进去（没有会话号、超限）时按钮发问句全文，点了照常规划也说得全。
    `button_query` 是问句全文的底子（默认本轮问句）：重放上一轮时是上一轮的问句，点直填的轮次是原话加选定的一项。"""
    base_query = button_query or query
    params = _ask_params(ask)
    full = clarify.recommendations(params, base_query)
    short = clarify.short_recommendations(params)
    written = await workspace.write_pending(ctx, query=base_query, plan=plan, ask=ask, recommendations=short,
                                            full=full, inferred=result.inferred if result else (),
                                            check_errors=result.check_errors if result else ())
    await workspace.write_last(ctx, query, workspace.OUTCOME_CLARIFY, plan)
    return clarify.event(params, base_query, short if written else full)


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

    query = request.query
    today = date.today()
    history = await _history(ctx, request)
    previous = await workspace.read_previous(ctx, history)
    pending = await workspace.read(ctx, workspace.PENDING)
    if pending is not None:
        await workspace.drop(ctx, workspace.PENDING)
    filled = workspace.fill(pending, query)
    # 本轮按什么问句理解：点了代码追问的按钮时按钮只写了选项，取存下的问句全文（原话加这一项，§4.4）；
    # 取人、对库、写分析、答后按钮、填不进去时重新规划都按它。`last.query` 仍记用户发来的原话
    asked = (filled.asked or query) if filled is not None else query
    topics = await config_files.load(ctx, TOPIC_TERMS)
    dept_aliases = await config_files.load(ctx, DEPT_ALIASES)
    regions = await config_files.load(ctx, FACTORY_REGIONS)
    master = await shared.load(ctx, access.allowed(), asked)
    entities = master.entities(dept_aliases, regions)
    planner = Planner(manifest, topics)
    inputs = PlanInputs(
        query=asked, history=history, previous_plan=previous.plan, previous_outcome=previous.outcome,
        earlier_query=previous.earlier_query, today=today, classes=master.classes(dept_aliases, regions),
        entities=entities, machines=master.machines or None)
    llm = getattr(ctx, "llm", None)
    if filled is not None:
        result = PlanResult(plan=filled.plan, source="filled", inferred=list(filled.inferred),
                            check_errors=list(filled.check_errors))
    else:
        result = await planner.plan(llm, inputs)
    if result.plan is None:
        for event in greeting.not_understood(access):
            yield event
        return

    steps = [s for s in result.plan.get("steps") or [] if isinstance(s, dict)]
    first = steps[0] if steps else {}
    if first.get("skill") == "clarify":
        yield clarify.event(first.get("params") or {}, asked)
        await workspace.write_last(ctx, query, workspace.OUTCOME_CLARIFY, result.plan)
        return
    if first.get("skill") == "introduce":
        for event in introduce.run(first.get("params") or {}, manifest, access):
            yield event
        return

    answer = await config_files.load(ctx, ANSWER_PARAMS)
    sites = await config_files.load(ctx, LINK_SITES)
    seg = await config_files.load(ctx, SEGMENTATION)
    results = await workspace.read(ctx, workspace.RESULTS) if previous.turn else None
    focus = await workspace.read(ctx, workspace.FOCUS) if (previous.plan or previous.turn) else None

    carried = workspace.decided(previous.turn)

    def make_turn(result: PlanResult) -> execute.Turn:
        return execute.Turn(ctx=ctx, manifest=manifest, access=access, master=master, answer=answer,
                            resolver=base.Resolver(master=master, dept_aliases=dept_aliases, regions=regions,
                                                   entities=entities, today=today, query=asked, carried=carried),
                            query=asked, today=today, result=result, entities=entities, sites=sites,
                            previous_turn=previous.turn, previous_results=results, focus=focus,
                            topics=topics, seg=seg)

    if first.get("skill") in REPLAY_SKILLS:
        async for event in _replay(ctx, query, result, first, previous, make_turn(result), results):
            yield event
        return

    spans, unknown = timespan.plan_spans(result.plan, today)
    if unknown is not None:
        params = clarify.time_unknown_step(unknown)["params"]
        ask = Ask(params["question"], list(params["options"]), reason=params["reason"], said=unknown,
                  fill=base.FILL_TIME)
        yield await _clarify_with_pending(ctx, query, result.plan, ask, result, button_query=asked)
        return
    spans = workspace.follow_spans(result.plan, spans, previous.turn)

    if not any(s.get("skill") in execute.EXECUTABLE for s in steps):
        # 临时统计随 S7 接上
        logger.info("factory_issue_skill_not_ready", skills=[str(s.get("skill")) for s in steps])
        for event in _not_ready(access):
            yield event
        return

    # 第 6 步：名字对库（人员按姓名另取）；对不上、对上多个、重名时追问，本轮不取数
    turn = make_turn(result)
    await execute.add_people(result.plan, turn)
    prepared = execute.prepare(result.plan, spans, turn)
    if isinstance(prepared, Ask) and filled is not None and prepared.question == filled.question:
        # 填进去的值没起作用（同一句追问又来了）：不再循环，按问句全文规划一次（`asked` 带着选定的那一项）
        logger.info("factory_issue_fill_no_effect", reason=prepared.reason)
        result = await planner.plan(llm, inputs)
        if result.plan is None:
            for event in greeting.not_understood(access):
                yield event
            return
        spans, unknown = timespan.plan_spans(result.plan, today)
        if unknown is not None:
            yield clarify.event(clarify.time_unknown_step(unknown)["params"], asked)
            await workspace.write_last(ctx, query, workspace.OUTCOME_CLARIFY, result.plan)
            return
        turn = make_turn(result)
        await execute.add_people(result.plan, turn)
        prepared = execute.prepare(result.plan, spans, turn)
    if isinstance(prepared, Ask):
        yield await _clarify_with_pending(ctx, query, result.plan, prepared, result, button_query=asked)
        return
    async for event in execute.run(result.plan, prepared, turn):
        yield event
    ask_event = await _write_after(ctx, query, execute.merge_details(result.plan), turn, result)
    if ask_event is not None:
        yield ask_event


async def _write_after(ctx: Any, query: str, plan: dict, turn: execute.Turn, result: PlanResult) -> Event | None:
    """本轮结束：执行中追问的写 `pending_clarify`，返回要发的 `clarify`（写进去了按钮才只写选项，所以在写之后
    发）；取过数的覆盖 `turn`；`last` 记结局。`turn.query` 是本轮按什么问句理解（`asked`）。"""
    record = turn.record
    if record.ask is not None:
        return await _clarify_with_pending(ctx, query, plan, record.ask, result, button_query=turn.query)
    if record.failed:  # 整轮都失败的轮次不覆盖 `turn`、`results`、`charts`（§10）
        outcome = workspace.OUTCOME_FAILED
    else:
        outcome = workspace.OUTCOME_FOUND if record.found else workspace.OUTCOME_EMPTY
        if record.fetched:
            await workspace.write_turn(ctx, turn.query, plan, record)
    await workspace.write_last(ctx, query, outcome, plan, asked=turn.query)
    return None


async def _replay(ctx: Any, query: str, result: PlanResult, step: dict, previous: workspace.Previous,
                  turn: execute.Turn, results: dict | None) -> AsyncIterator[Event]:
    """质疑重查与换图：按工作区里上一轮的执行计划重放（§4.3）。读不到上一轮时按「接不上上一轮」追问。

    重放时要追问（如上一轮的名字这次对上了几个人）：问句全文是上一轮问句加选项，写 `pending_clarify`，点了直接
    填进上一轮的计划；`last` 记「追问」。重放每步都没查成记「出错」、不覆盖 `turn`（S5 评审 A3）。"""
    if previous.turn is None or not isinstance(previous.turn.get("plan"), dict):
        yield clarify.event(NO_PREVIOUS, query)
        await workspace.write_last(ctx, query, workspace.OUTCOME_CLARIFY, result.plan)
        return
    plan = previous.turn["plan"]
    turn.previous_turn = turn.previous_results = None  # 重放的就是上一轮那份计划，按号查单照常重查
    if step.get("skill") == "verify_previous":
        events, outcome, ask = await verify_previous.run(turn, previous.turn, results)
    else:
        stored = await workspace.read(ctx, workspace.CHARTS)
        events, outcome, ask = await rerender.run(turn, step, previous.turn, stored)
    if ask is not None:
        yield await _clarify_with_pending(ctx, query, plan, ask,
                                          button_query=str(previous.turn.get("query") or "") or None)
        return
    for event in events:
        yield event
    if turn.record.fetched and outcome != workspace.OUTCOME_FAILED:
        await workspace.write_turn(ctx, query, plan, turn.record)
    await workspace.write_last(ctx, query, outcome, plan)
