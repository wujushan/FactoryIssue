"""多轮与交互（设计 §4.2 第 3 步、§4.3 质疑与换图两行、§4.4 第二条、§9.3 导出、§9.5、§10；任务单 S5）。

同一个假 `ctx` 连跑几轮：工作区（`FakeWorkspace`）与会话历史（`FakeSession`）跨轮保留，每轮结束把问答追加进历史
（`conversation_messages` 从它取最近几轮）。计划照对照集里模型的实际写法。
"""

from __future__ import annotations

import copy
import io
from datetime import date, timedelta

import cn_data
import pandas as pd
import pytest
import s3_data
import s4_data
import scopes
from fakes import data_queries, make_harness, run
from forge_core.events import EventType
from openpyxl import load_workbook

from factory_issue_module.domains import base
from factory_issue_module.plan import timespan
from factory_issue_module.plan.normalize import Inferred
from factory_issue_module.present import export, suggestions
from factory_issue_module.turn import orchestrator, workspace

CN = {"value": ["国内"], "from": "user"}
CN_PREV = {"value": ["国内"], "from": "previous"}
T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
NARR = "共 4 张，硬件问题最多。最需要关注的是 ZC9901001。"
SITES = 'issue = "info.test.local"'


def plan(*steps: dict, alternatives: list[str] | None = None, understanding: str = "按条件查") -> dict:
    return {"understanding": understanding, "alternatives": alternatives or [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _types(events) -> list[EventType]:
    return [e.type for e in events]


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


def _buttons(events) -> list[dict]:
    for e in events:
        if e.type in (EventType.SUGGESTIONS, EventType.CLARIFY):
            return e.data.get("recommendations") or []
    return []


def _planner_calls(h) -> int:
    return sum(1 for m in h.llm.calls if "的规划器" in str(m[0].get("content") or ""))


class Conversation:
    """同一会话连问几轮：每轮的问答追加进历史。"""

    def __init__(self, privileges=None, *, data=cn_data, config: dict | None = None, ws: bool = True, **kw):
        self.h = make_harness(scopes.GREEN if privileges is None else privileges, history=[], workspace=ws,
                              config_files={"link_sites.toml": SITES, **(config or {})}, **kw)
        data.load(self.h)
        self.n = 0

    async def ask(self, query: str, *replies) -> list:
        self.h.llm.replies += list(replies)
        events = await run(self.h, query)
        self.n += 1
        if self.h.ctx.session is not None:
            self.h.ctx.session.rows += [
                {"role": "user", "content": query, "message_id": f"t{self.n}"},
                {"role": "assistant", "content": _text(events) or "（追问）", "message_id": f"t{self.n}"}]
        return events

    def ws(self, key: str) -> dict | None:
        return self.h.workspace.store.get(key) if self.h.workspace is not None else None


# ---------------------------------------------------------------------------- 写工作区（§10）


async def test_fetched_round_writes_turn_results_last_and_plan_reaches_planner():
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    turn, results, last = c.ws(workspace.TURN), c.ws(workspace.RESULTS), c.ws(workspace.LAST)
    assert turn["v"] == results["v"] == last["v"] == workspace.VERSION
    assert turn["plan"]["steps"][0]["skill"] == "list_issues"
    info = turn["steps"]["s1"]
    assert info["domains"] == ["国内"] and info["found"] == {"国内": 4}
    assert info["times"][0]["said"] == "近 30 天" and info["times"][0]["start"] == (
        date.today() - timedelta(days=29)).isoformat()
    assert results["steps"]["s1"]["国内"]["numbers"][:2] == ["ZC9901001", "ZC9901002"]
    assert last["outcome"] == workspace.OUTCOME_FOUND and last["earlier_query"] == "近 30 天国内的问题有哪些"
    # 下一轮规划器拿到的「上一轮计划」就是执行计划里的那份计划（与对照集同一形状）
    await c.ask("那今年呢", plan(step("list_issues", domains=CN_PREV,
                                     time=[{"said": "今年", "basis": "建单", "from": "user"}])), NARR)
    user = c.h.llm.calls[-2][-1]["content"]
    assert "【上一轮计划】" in user and '"skill": "list_issues"' in user and "近 30 天" in user


async def test_only_fetched_rounds_overwrite_turn():
    """追问、能力介绍的轮次不覆盖 `turn`；追问的轮次记 `last`（结局「追问」），能力介绍不记。"""
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    first = c.ws(workspace.TURN)
    odd = {"field": "问题类型", "op": "是", "value": "外观问题", "from": "user"}
    events = await c.ask("国内外观问题有哪些", plan(step("list_issues", domains=CN, filters=[odd])))
    assert _types(events) == [EventType.CLARIFY]
    assert c.ws(workspace.TURN) == first
    assert c.ws(workspace.LAST)["outcome"] == workspace.OUTCOME_CLARIFY
    assert c.ws(workspace.LAST)["earlier_query"] == "近 30 天国内的问题有哪些"
    await c.ask("你好，你能做什么", plan(step("introduce", kind="能力")))
    assert c.ws(workspace.LAST)["query"] == "国内外观问题有哪些"


async def test_empty_round_writes_turn_and_outcome_empty():
    c = Conversation(scopes.account_jia())
    c.h.connectors["info"].frames["ZCTracking_ProblemList"] = pd.DataFrame(columns=list(cn_data.main_rows()[0]))
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)))
    assert c.ws(workspace.LAST)["outcome"] == workspace.OUTCOME_EMPTY
    assert c.ws(workspace.TURN)["steps"]["s1"]["found"] == {"国内": 0}


async def test_no_workspace_or_quota_still_answers():
    c = Conversation(scopes.account_jia(), ws=False)
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    assert EventType.TABLE in _types(events)
    c = Conversation(scopes.account_jia())
    c.h.ctx.workspace.quota_bytes = 10
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    assert EventType.TABLE in _types(events) and c.ws(workspace.TURN) is None


async def test_old_version_values_count_as_no_previous():
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    for key in (workspace.TURN, workspace.LAST, workspace.RESULTS):
        c.h.workspace.store[key] = {**c.h.workspace.store[key], "v": workspace.VERSION + 1}
    previous = await workspace.read_previous(c.h.ctx, [{"role": "user", "content": "近 30 天国内的问题有哪些"}])
    assert previous == workspace.NOTHING
    assert await workspace.read(c.h.ctx, workspace.RESULTS) is None


async def test_many_rounds_later_the_previous_plan_is_not_given():
    """隔了很多轮：`last` 的问句不在最近 3 轮里，不给规划器上一轮计划。"""
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    c.h.ctx.session.rows = c.h.ctx.session.rows[:0] + [
        {"role": "user", "content": f"别的问题{i}", "message_id": f"x{i}"} for i in range(3)]
    previous = await workspace.read_previous(c.h.ctx, [{"role": "user", "content": "别的问题0"}])
    assert previous == workspace.NOTHING


# ---------------------------------------------------------------------------- 沿用上一轮（§10「沿用以执行计划为准」）


async def test_previous_time_uses_the_stored_dates_and_answer_says_what_is_carried():
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    turn = c.h.workspace.store[workspace.TURN]
    turn["steps"]["s1"]["times"][0].update({"start": "2099-01-01", "end": "2099-01-31", "rolling_days": None})
    keep = [{"said": "近 30 天", "basis": "建单", "from": "previous"}]
    hw = {"field": "问题类型", "op": "是", "value": "硬件问题", "from": "user"}
    c.h.queries.clear()
    events = await c.ask("其中硬件问题呢", plan(step("list_issues", domains=CN_PREV, time=keep, filters=[hw])), NARR)
    main = next(q for q in data_queries(c.h) if q.tables[0] == "ZCTracking_ProblemList")
    assert any(str(v).startswith("2099-01-01") for v in main.params.values())  # 按上一轮存下的起止日期
    text = _text(events)
    assert "沿用上一轮的条件：国内、时间「近 30 天」；本轮换成：问题类型 硬件问题" in text


# ---------------------------------------------------------------------------- 追问选项直填（§4.4 第二条）


_ODD_TYPE = {"field": "问题类型", "op": "是", "value": "外观问题", "from": "user"}
_ASK_TYPE = "近 30 天国内外观问题有哪些"


async def test_type_button_fills_the_plan_without_replanning():
    c = Conversation(scopes.account_jia())
    events = await c.ask(_ASK_TYPE, plan(step("list_issues", domains=CN, time=T30, filters=[_ODD_TYPE])))
    rec = next(r for r in _buttons(events) if r["label"] == "硬件问题")
    # 工作区写进去了：按钮只写选项（INFO 网页前端把 `query` 当按钮文字），问句全文存在 `pending_clarify` 里
    assert rec["query"] == "硬件问题"
    pending = c.ws(workspace.PENDING)
    assert pending["options"][0]["patch"]["kind"] == base.FILL_VALUE and pending["plan"]["steps"][0]["skill"] == \
        "list_issues"
    option = next(o for o in pending["options"] if o["query"] == "硬件问题")
    assert option["full"] == f"{_ASK_TYPE}（硬件问题）"
    before = _planner_calls(c.h)
    c.h.queries.clear()
    events = await c.ask(rec["query"], NARR)
    assert _planner_calls(c.h) == before  # 不重新规划
    assert EventType.CLARIFY not in _types(events) and EventType.TABLE in _types(events)
    main = next(q for q in data_queries(c.h) if q.tables[0] == "ZCTracking_ProblemList")
    assert "[ProblemType] IN" in main.sql and 1 in main.params.values()  # 硬件问题的代码
    assert c.ws(workspace.PENDING) is None
    assert c.ws(workspace.TURN)["plan"]["steps"][0]["params"]["filters"][0]["value"] == "硬件问题"


async def test_click_round_is_understood_as_the_full_question():
    """点了只写选项的按钮：`last.query` 记用户发来的原话（隔了很多轮要拿它比会话历史），`turn.query` 与
    `last.earlier_query` 记问句全文；写分析的模型拿到的也是问句全文；下一轮照常拿到上一轮计划。"""
    c = Conversation(scopes.account_jia())
    events = await c.ask(_ASK_TYPE, plan(step("list_issues", domains=CN, time=T30, filters=[_ODD_TYPE])))
    await c.ask(next(r for r in _buttons(events) if r["label"] == "硬件问题")["query"], NARR)
    full = f"{_ASK_TYPE}（硬件问题）"
    last = c.ws(workspace.LAST)
    assert last["query"] == "硬件问题" and last["earlier_query"] == full
    assert c.ws(workspace.TURN)["query"] == full
    assert full in str(c.h.llm.calls[-1])  # 分析段的提示里是问句全文
    previous = await workspace.read_previous(c.h.ctx, c.h.ctx.session.rows)
    assert previous.plan is not None and previous.plan["steps"][0]["skill"] == "list_issues"


async def test_code_ask_buttons_send_the_full_question_when_pending_cannot_be_written():
    """工作区没有或写不进去：按钮发问句全文（原话加选项），点了照常规划也说得全。"""
    for c in (Conversation(scopes.account_jia(), ws=False), Conversation(scopes.account_jia())):
        if c.h.workspace is not None:
            c.h.ctx.workspace.quota_bytes = 10
        events = await c.ask(_ASK_TYPE, plan(step("list_issues", domains=CN, time=T30, filters=[_ODD_TYPE])))
        rec = next(r for r in _buttons(events) if r["label"] == "硬件问题")
        assert rec["query"] == f"{_ASK_TYPE}（硬件问题）"


async def test_fill_without_effect_replans_with_the_full_question(monkeypatch):
    """填进去之后第 6 步又问出同一句：按问句全文规划一次（不是只拿「硬件问题」这几个字去规划）。"""
    c = Conversation(scopes.account_jia())
    events = await c.ask(_ASK_TYPE, plan(step("list_issues", domains=CN, time=T30, filters=[_ODD_TYPE])))
    rec = next(r for r in _buttons(events) if r["label"] == "硬件问题")
    monkeypatch.setattr(workspace, "apply_fill", lambda p, _patch: copy.deepcopy(p))  # 填了等于没填
    hw = {**_ODD_TYPE, "value": "硬件问题"}
    events = await c.ask(rec["query"], plan(step("list_issues", domains=CN, time=T30, filters=[hw])), NARR)
    planned = [m for m in c.h.llm.calls if "的规划器" in str(m[0].get("content") or "")][-1]
    assert f"{_ASK_TYPE}（硬件问题）" in planned[-1]["content"]
    assert EventType.CLARIFY not in _types(events) and EventType.TABLE in _types(events)


async def test_yes_no_button_fills_and_never_loops():
    """BR-004 那一类：点「是」直接填进计划，不再问同一句；工作区读不到时按钮发「原话（是）」，模型照旧抄回认不出
    的取值也按问句末尾选定的那一项（S3 的做法）。"""
    c = Conversation(data=s3_data)
    odd = {"field": "是否需要回复8D", "op": "是", "value": "要回 8D 的", "from": "user"}
    reply = plan(step("list_issues", domains={"value": ["巴西"], "from": "user"}, filters=[odd]))
    events = await c.ask("巴西要回 8D 的单", reply)
    rec = _buttons(events)[0]
    assert rec["label"] == "是" and rec["query"] == "是"
    events = await c.ask(rec["query"], "共 1 张。最需要关注的是 BR9901001。")
    assert EventType.CLARIFY not in _types(events)
    assert [r[0] for r in _tables(events)[0]["rows"]][0].startswith("[BR9901001]")
    # 没有工作区：按钮发问句全文，模型照旧抄回认不出的取值，按问句末尾选定的那一项
    c = Conversation(data=s3_data, ws=False)
    events = await c.ask("巴西要回 8D 的单", reply)
    rec = _buttons(events)[0]
    assert rec["query"] == "巴西要回 8D 的单（是）"
    events = await c.ask(rec["query"], reply, "共 1 张。")
    assert EventType.CLARIFY not in _types(events)


async def test_unknown_number_button_fills_kind_said():
    c = Conversation(data=s4_data)
    reply = plan(step("lookup_numbers", numbers=[{"raw": "202501011234", "kind_said": None}]))
    events = await c.ask("202501011234 是什么单？", reply)
    c.h.llm.replies.clear()  # 号码直通时用不上这份回复
    rec = next(r for r in _buttons(events) if r["label"] == "订单号")
    assert rec["query"] == "订单号"
    assert c.ws(workspace.PENDING)["options"][0]["patch"]["kind"] == base.FILL_KIND_SAID
    before = _planner_calls(c.h)
    events = await c.ask(rec["query"])
    assert _planner_calls(c.h) == before and EventType.CLARIFY not in _types(events)
    assert "按生产订单号、小板订单号、发货单号、PO 查过" in _text(events)


async def test_hand_filled_order_button_fills_the_number():
    c = Conversation(data=s4_data)
    events = await c.ask("订单 990002 关联了哪张单？",
                         plan(step("lookup_numbers", numbers=[{"raw": "990002", "kind_said": "订单号"}])))
    c.h.llm.replies.clear()  # 号码直通时用不上这份回复
    assert _types(events) == [EventType.CLARIFY]
    # 执行时才知道的候选：编排先写 `pending_clarify` 再发 `clarify`，按钮同样只写选项
    assert _buttons(events)[0]["query"] == "990002-1"
    assert c.ws(workspace.PENDING)["options"][0]["patch"]["kind"] == base.FILL_NUMBER
    assert c.ws(workspace.PENDING)["options"][0]["full"] == "订单 990002 关联了哪张单（990002-1）"
    assert c.ws(workspace.LAST)["outcome"] == workspace.OUTCOME_CLARIFY
    events = await c.ask(_buttons(events)[0]["query"])
    assert EventType.CLARIFY not in _types(events)
    assert _tables(events)[0]["rows"][0][0].startswith("[ZC9901001]")
    assert c.ws(workspace.TURN)["plan"]["steps"][0]["params"]["numbers"][0]["raw"] == "990002-1"


async def test_time_button_fills_the_time_and_goes_through_step_six():
    c = Conversation(scopes.account_jia())
    reply = plan(step("list_issues", domains=CN, time=[{"said": "国庆以来", "basis": "建单", "from": "user"}]))
    events = await c.ask("国庆以来国内的问题有哪些", reply)
    rec = next(r for r in _buttons(events) if r["label"] == "近 30 天")
    assert rec["query"] == "近 30 天"
    # 问句全文把认不出的那段说法换成选定的时间（不在句末追加）
    assert next(o for o in c.ws(workspace.PENDING)["options"] if o["query"] == "近 30 天")["full"] == \
        "近 30 天国内的问题有哪些"
    events = await c.ask(rec["query"], NARR)
    assert EventType.TABLE in _types(events) and "近 30 天" in c.ws(workspace.TURN)["steps"]["s1"]["times"][0]["said"]
    assert c.ws(workspace.TURN)["query"] == "近 30 天国内的问题有哪些"


async def test_filled_plan_still_goes_through_this_rounds_access():
    """直填后照常过第 6 步：域取本轮可查的域（上一轮能查巴西、这一轮不能，就不查巴西）。"""
    c = Conversation(data=s3_data)
    odd = {"field": "问题类型", "op": "是", "value": "外观问题", "from": "user"}
    events = await c.ask("近 30 天外观问题有哪些", plan(step("list_issues", time=T30, filters=[odd])))
    rec = next(r for r in _buttons(events) if r["label"] == "硬件问题")
    narrow = make_harness(scopes.account_jia(), history=[], config_files={"link_sites.toml": SITES})
    s3_data.load(narrow)
    narrow.workspace.store.update(c.h.workspace.store)
    events = await run(narrow, rec["query"])
    assert "BrazilProblemList" not in {q.tables[0] for q in data_queries(narrow)}
    assert "巴西、海外无权限，未计入" in _text(events)


def test_apply_fill_returns_none_when_the_value_is_gone():
    p = plan(step("list_issues", filters=[{"field": "加工厂", "op": "是", "value": "惠州", "from": "user"}]))
    assert workspace.apply_fill(p, {"kind": base.FILL_VALUE, "sid": "s1", "said": "深圳", "option": "x"}) is None
    got = workspace.apply_fill(p, {"kind": base.FILL_VALUE, "sid": "s1", "said": "惠州", "option": "惠州百富、惠州二厂"})
    assert got["steps"][0]["params"]["filters"][0]["value"] == ["惠州百富", "惠州二厂"]
    got = workspace.apply_fill(p, {"kind": base.FILL_KIND, "sid": "s1", "said": "惠州", "option": "惠州：部门"})
    assert got["steps"][0]["params"]["filters"][0]["field"] == "跟进部门"
    assert p["steps"][0]["params"]["filters"][0]["value"] == "惠州"  # 不改原计划


def test_pending_keeps_inferred_and_check_errors():
    pending = {"plan": plan(step("list_issues", filters=[{"field": "加工厂", "op": "是", "value": "亮", "from": "user"}])),
               "question": "q", "query": "原话", "options": [{"query": "亮亮", "full": "原话（亮亮）", "patch": {
                   "kind": base.FILL_VALUE, "sid": "s1", "said": "亮", "option": "亮亮"}}],
               "inferred": [{"step": "s1", "field": "加工厂", "values": ["亮"]}], "check_errors": ["e"]}
    got = workspace.fill(pending, "亮亮")
    assert got.inferred == [Inferred(step="s1", field="加工厂", values=("亮",))] and got.check_errors == ["e"]
    assert got.asked == "原话（亮亮）"
    assert workspace.fill(pending, "别的") is None
    # 没有 `full` 的（按钮发的就是问句全文）：本轮按按钮的问句理解
    del pending["options"][0]["full"]
    assert workspace.fill(pending, "亮亮").asked == "亮亮"


# ---------------------------------------------------------------------------- 质疑重查（§4.3 `verify_previous`）


async def test_verify_replays_the_plan_and_says_it_matches():
    c = Conversation(scopes.account_jia())
    a920 = {"field": "机型", "op": "是", "value": "A920", "from": "user"}
    await c.ask("近 30 天国内 A920 的问题", plan(step("list_issues", domains=CN, time=T30, filters=[a920]),
                                             alternatives=["A920 系列"]), NARR)
    c.h.llm.replies.clear()  # 只有两张单时不写分析，这份回复用不上
    c.h.queries.clear()
    before = len(c.h.llm.calls)
    events = await c.ask("你确定吗？", plan(step("verify_previous")))
    assert len(c.h.llm.calls) == before + 1  # 只有规划那一次，不写分析
    text = _text(events)
    assert "按上一轮的条件重新查了一遍" in text and "国内：与上一轮一致" in text and "结果与上一轮一致" in text
    assert "机型：A920" in text and "上一轮按「按条件查」理解" in text
    assert any(q.tables[0] == "ZCTracking_ProblemList" for q in data_queries(c.h))
    recs = _buttons(events)
    assert recs and recs[0]["query"] == "换个理解：A920 系列" and recs[0]["label"] == "A920 系列"
    assert c.ws(workspace.LAST)["outcome"] == workspace.OUTCOME_FOUND


async def test_verify_lists_issues_that_changed():
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    rows = [r for r in cn_data.main_rows() if r["Numbers"] != "ZC9901003"]
    rows.append({**cn_data.main_rows()[0], "ID": 9, "Numbers": "ZC9901009"})
    c.h.connectors["info"].frames["ZCTracking_ProblemList"] = pd.DataFrame(rows)
    events = await c.ask("好像不对吧", plan(step("verify_previous")))
    text = _text(events)
    assert "上一轮 4 张，这次 4 张，新查到 1 张，1 张这次没查到" in text
    table = _tables(events)[0]
    assert table["columns"] == ["问题编号", "所属域", "变化"]
    assert {(r[0].split("]")[0].strip("["), r[2]) for r in table["rows"]} == {
        ("ZC9901009", "这次新查到"), ("ZC9901003", "这次没查到")}
    # 有「这次没查到」的单时表格下面说可能的原因，不替用户猜（开发者 2026-10-30 定）
    assert "这次没查到的单可能已删除，或这期间改了状态、类型等，已不符合上一轮的条件" in text
    assert "不再符合条件。" not in text.split("已不符合上一轮的条件")[0]


async def test_verify_only_rechecks_domains_still_permitted():
    c = Conversation(data=s3_data)
    await c.ask("近 30 天的问题有哪些", plan(step("list_issues", time=T30)), NARR)
    narrow = make_harness(scopes.account_jia(), history=[], config_files={"link_sites.toml": SITES})
    s3_data.load(narrow)
    narrow.workspace.store.update(c.h.workspace.store)
    narrow.ctx.session.rows = list(c.h.ctx.session.rows)
    narrow.llm.replies = [plan(step("verify_previous"))]
    events = await run(narrow, "你确定吗")
    text = _text(events)
    assert "巴西、海外现在没有查看权限，这次没有重查" in text and "国内：与上一轮一致" in text
    assert not {"BrazilProblemList", "OverseasProblemDetail"} & {q.tables[0] for q in data_queries(narrow)}


async def test_verify_detail_shows_the_ticket_again():
    c = Conversation(data=s4_data)
    await c.ask("ZC9901001")
    events = await c.ask("你确定吗", plan(step("verify_previous")))
    assert "单张单详情按这张单现在的情况重新给出" in _text(events) and "ZC9901001" in _text(events)


async def test_verify_without_previous_asks_to_restate():
    c = Conversation(scopes.account_jia())
    events = await c.ask("你确定吗", plan(step("verify_previous")))
    assert _types(events) == [EventType.CLARIFY] and data_queries(c.h) == []


# ---------------------------------------------------------------------------- 换图（§4.3 `rerender`）


async def test_rerender_redraws_from_stored_chart_without_fetching():
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内按问题类型统计",
                plan(step("aggregate", domains=CN, time=T30, group_by=["问题类型"])), NARR)
    assert c.ws(workspace.CHARTS)["items"][0]["rows"]
    c.h.queries.clear()
    events = await c.ask("换成柱状图", plan(step("rerender", chart="柱状")))
    chart = next(e.data for e in events if e.type is EventType.CHART)
    assert chart["chart_type"] == "bar" and chart["series"][0]["data"] == [2, 1, 1]
    assert data_queries(c.h) == []


async def test_rerender_reruns_when_a_domain_is_no_longer_permitted():
    c = Conversation(data=s3_data)
    await c.ask("近 30 天按问题类型统计", plan(step("aggregate", time=T30, group_by=["问题类型"])), NARR)
    narrow = make_harness(scopes.account_jia(), history=[], config_files={"link_sites.toml": SITES})
    s3_data.load(narrow)
    narrow.workspace.store.update(c.h.workspace.store)
    narrow.ctx.session.rows = list(c.h.ctx.session.rows)
    narrow.llm.replies = [plan(step("rerender", chart="饼图"))]
    events = await run(narrow, "换成饼图")
    assert "不再包含巴西、海外" in _text(events)
    assert next(e.data for e in events if e.type is EventType.CHART)["chart_type"] == "pie"
    assert not {"BrazilProblemList", "OverseasProblemDetail"} & {q.tables[0] for q in data_queries(narrow)}


async def test_rerender_after_a_list_or_detail_says_there_is_no_chart():
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    events = await c.ask("换成饼图", plan(step("rerender", chart="饼图")))
    assert "没有可以换图的统计" in _text(events) and EventType.CHART not in _types(events)


# ---------------------------------------------------------------------------- 导出（§9.3）


def _sheets(h) -> dict[str, list[list]]:
    (_name, data), = h.files.saved.items()
    wb = load_workbook(io.BytesIO(data))
    return {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets}


async def test_export_when_asked_one_sheet_per_domain_with_display_headers():
    c = Conversation(data=s3_data)
    events = await c.ask("把近 30 天的问题全部导出给我", plan(step("list_issues", time=T30, export=True)), NARR)
    text = _text(events)
    assert "完整清单见附件（每域一页：国内 4 张、巴西 4 张、海外 2 张）" in text and "24 小时内有效" in text
    sheets = _sheets(c.h)
    assert list(sheets) == ["国内", "巴西", "海外"]
    assert sheets["国内"][0] == _tables(events)[0]["columns"]
    assert len(sheets["国内"]) == 5 and sheets["国内"][1][0] == "ZC9901001"  # 编号给文字，不带链接
    caliber_at = text.index("统计口径")
    assert text.index("附件") > caliber_at  # 链接在统计口径之后
    labels = [r["label"] for r in _buttons(events)]
    assert suggestions.EXPORT_ALL not in labels


async def test_export_over_threshold_and_table_keeps_the_first_rows():
    c = Conversation(scopes.account_jia(), config={"answer_params.toml": "export_threshold = 2\ntable_rows = 2"})
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    assert len(_tables(events)[0]["rows"]) == 2
    assert "完整 4 张见附件" in _text(events)
    assert len(_sheets(c.h)["国内"]) == 5


async def test_export_failure_keeps_the_table():
    c = Conversation(scopes.account_jia())

    async def boom(*_a, **_k):
        raise OSError("磁盘满")

    c.h.files.save_bytes = boom
    events = await c.ask("把近 30 天国内的问题导出", plan(step("list_issues", domains=CN, time=T30, export=True)), NARR)
    assert EventType.TABLE in _types(events) and "完整清单导出失败，请稍后再试" in _text(events)


async def test_many_issue_numbers_listed_by_domain_and_exported():
    """总述「按编号查单」：超过约 20 个（`table_rows`）时按清单呈现、全量导出：每域一张表、域内按建单时间从新到旧，
    开头给各域张数与合计、没找到与无权的号；链接在统计口径之后（S5 评审 A4）。"""
    c = Conversation(scopes.account_jia(), data=s4_data, config={"answer_params.toml": "table_rows = 1"})
    events = await c.ask("ZC9901006、ZC9901001、ZC9909999、BR9901001")
    tables = _tables(events)
    assert [t["title"] for t in tables] == ["国内问题单"] and len(tables[0]["rows"]) == 1
    assert tables[0]["rows"][0][0].startswith("[ZC9901001]")  # 建单时间最新的在前
    text = _text(events)
    assert "按问题编号逐个查，共找到 2 张" in text and "表格每域按建单时间从新到旧列出前 1 张" in text
    assert "没有找到这些号（已删除的单查不到）：ZC9909999" in text
    assert "这些号所在的域您没有查看权限，未查：BR9901001" in text
    assert text.index("附件") > text.index("统计口径") and "完整 2 张见附件" in text
    sheets = _sheets(c.h)
    assert list(sheets) == ["国内"] and [r[0] for r in sheets["国内"][1:]] == ["ZC9901001", "ZC9901006"]
    assert sheets["国内"][0] == tables[0]["columns"]


async def test_few_issue_numbers_keep_one_row_per_number():
    c = Conversation(data=s4_data)
    events = await c.ask("ZC9901001、BR9901001")
    assert [t["title"] for t in _tables(events)] == ["问题单当前状态"] and not c.h.files.saved


def test_workbook_cells_are_plain_values():
    data = export.workbook_bytes([("国内", ["问题编号", "不良数量"], [["ZC9901001", pd.NA], ["ZC9901002", 3]])])
    ws = load_workbook(io.BytesIO(data)).active
    assert [[c.value for c in r] for r in ws.iter_rows()] == [["问题编号", "不良数量"], ["ZC9901001", "未填"],
                                                             ["ZC9901002", 3]]


# ---------------------------------------------------------------------------- 答后按钮（§9.5）


async def test_alternatives_first_then_templates_at_most_four():
    c = Conversation(scopes.account_jia())
    events = await c.ask("近 30 天国内 A920 的问题", plan(step("list_issues", domains=CN, time=T30),
                                                     alternatives=["A920 系列", "A920 各款"]), NARR)
    recs = _buttons(events)
    assert [r["label"] for r in recs] == ["A920 系列", "A920 各款", suggestions.STAT_BY_TYPE]
    # 不再拼本轮原话（INFO 网页前端把 `query` 当按钮文字显示，§19）：短的、动作在前
    assert [r["query"] for r in recs] == ["换个理解：A920 系列", "换个理解：A920 各款", "按问题类型统计这些单"]
    assert [r["id"] for r in recs] == ["1", "2", "3"] and all(len(r["label"]) <= 15 for r in recs)


async def test_export_all_template_when_the_table_is_cut():
    c = Conversation(scopes.account_jia(), config={"answer_params.toml": "table_rows = 2"})
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    rec = next(r for r in _buttons(events) if r["label"] == suggestions.EXPORT_ALL)
    assert rec["query"] == "把这些单全部导出"


async def test_detail_templates_and_focus_for_this_issue():
    c = Conversation(data=s4_data)
    events = await c.ask("ZC9901001")
    by_label = {r["label"]: r["query"] for r in _buttons(events)}
    assert by_label[suggestions.FULL_PROCESS] == "ZC9901001 的完整处理过程"
    assert by_label[suggestions.REASONS] == "ZC9901001 的原因与措施"
    assert c.ws(workspace.FOCUS)["number"] == "ZC9901001"
    events = await c.ask("这单的原因是什么", plan(step("issue_detail", issue={"value": "这单", "from": "previous"},
                                                       aspects=["原因"])))
    assert "ZC9901001" in _text(events) and EventType.CLARIFY not in _types(events)
    # 看过原因：只剩「看完整处理过程」
    labels = [r["label"] for r in _buttons(events)]
    assert suggestions.FULL_PROCESS in labels and suggestions.REASONS not in labels


async def test_detail_templates_only_for_a_single_issue():
    """几张单的详情、按号查单找到几张：说不清是哪一张，不给「看完整处理过程」「看原因与措施」。"""
    c = Conversation(data=s4_data)
    events = await c.ask("ZC9901001、ZC9901002")
    labels = [r["label"] for r in _buttons(events)]
    assert suggestions.FULL_PROCESS not in labels and suggestions.REASONS not in labels


async def test_aggregate_template_lists_the_first():
    c = Conversation(scopes.account_jia())
    events = await c.ask("近 30 天国内哪个工厂问题最多",
                         plan(step("aggregate", domains=CN, time=T30, group_by=["加工厂"], ranking=True)), NARR)
    rec = next(r for r in _buttons(events) if r["label"].startswith("列出"))
    assert rec["label"] == rec["query"] == "列出柯洱斯的单"


@pytest.mark.parametrize(("group_by", "top1", "want"), [
    (["加工厂"], ["柯洱斯", "亮亮"], "列出柯洱斯、亮亮的单"),
    (["问题等级"], ["A"], "列出 A 级的单"),
    (["月"], ["2026-10"], None),  # 按时间分组不给
    (["加工厂", "问题类型"], ["柯洱斯", "硬件问题"], None),  # 两个维度说不清
    (["问题类型"], ["未填"], None),
    (["加工厂"], ["a", "b", "c", "d"], None),  # 并列第一太多
])
def test_aggregate_template_shapes(group_by, top1, want):
    got = suggestions.aggregate_templates(step("aggregate", group_by=group_by), top1=top1)
    assert [r["query"] for r in got] == ([want] if want else [])


def _fix_today(monkeypatch, day: date) -> None:
    """把编排拿的「今天」定在某一天（时间换算、本月截至今天都按它）。"""
    class Fixed(date):
        @classmethod
        def today(cls) -> date:
            return day

    monkeypatch.setattr(orchestrator, "date", Fixed)


_THIS_VS_LAST = plan(step("aggregate", domains=CN, compare="时段", time=[
    {"said": "这个月", "basis": "建单", "from": "user"}, {"said": "上个月", "basis": "建单", "from": "user"}]))


async def test_this_month_vs_last_month_says_to_date_and_offers_same_period(monkeypatch):
    _fix_today(monkeypatch, date(2026, 10, 15))
    c = Conversation(scopes.account_jia())
    events = await c.ask("国内这个月比上个月多了吗", _THIS_VS_LAST, NARR)
    text = _text(events)
    assert "「这个月」按本月截至今天（2026-10-01 至 2026-10-15）" in text and "没有换成同期" in text
    rec = next(r for r in _buttons(events) if r["label"] == suggestions.SAME_PERIOD)
    assert rec["query"] == "国内这个月比上月同期多了吗"


@pytest.mark.parametrize("today", [date(2026, 10, 30), date(2026, 10, 31), date(2026, 3, 28)])
async def test_same_period_button_is_dropped_when_it_equals_last_month(monkeypatch, today):
    """今天的日子已到或超过上月的天数：上月同期就是上月整月，与原来的比法一样，不给按钮，开头写明
    （开发者 2026-10-30 定）。2026 年 2 月 28 天，3 月 28 日起即是。"""
    _fix_today(monkeypatch, today)
    c = Conversation(scopes.account_jia())
    events = await c.ask("国内这个月比上个月多了吗", _THIS_VS_LAST, NARR)
    text = _text(events)
    assert "按本月截至今天" in text and "今天已到上月月底这一天，上月同期就是上月整月" in text
    assert "没有换成同期" not in text
    assert suggestions.SAME_PERIOD not in [r["label"] for r in _buttons(events)]


async def test_same_period_button_kept_the_day_before_month_end(monkeypatch):
    _fix_today(monkeypatch, date(2026, 10, 29))  # 9 月有 30 天，29 日还不是整月
    c = Conversation(scopes.account_jia())
    events = await c.ask("国内这个月比上个月多了吗", _THIS_VS_LAST, NARR)
    assert suggestions.SAME_PERIOD in [r["label"] for r in _buttons(events)]


def test_last_month_same_period_conversion():
    span = timespan.convert("上月同期", date(2026, 10, 30))
    assert (span.start, span.end) == (date(2026, 9, 1), date(2026, 9, 30))
    span = timespan.convert("上个月同期", date(2026, 3, 31))
    assert (span.start, span.end) == (date(2026, 2, 1), date(2026, 2, 28))
    span = timespan.convert("上月同期", date(2026, 1, 15))
    assert (span.start, span.end) == (date(2025, 12, 1), date(2025, 12, 15))


# ---------------------------------------------------------------------------- 递进筛选（§10）


async def test_within_previous_lookup_uses_stored_ids_without_relisting():
    c = Conversation(data=s4_data)
    await c.ask("ZC9901001、ZC9901002、ZC9901006")
    assert set(c.ws(workspace.RESULTS)["steps"]["s1"]["国内"]["numbers"]) == {"ZC9901001", "ZC9901002", "ZC9901006"}
    nums = [{"raw": x, "kind_said": None} for x in ("ZC9901001", "ZC9901002", "ZC9901006")]
    reply = plan(step("lookup_numbers", numbers=nums),
                 step("aggregate", "s2", within={"ref": "s1.issues"}, group_by=["状态"]))
    events = await c.ask("其中各状态多少", reply, "共 3 张。")
    assert "问题单当前状态" not in {t["title"] for t in _tables(events)}
    assert "共 3 张" in _text(events)


@pytest.mark.parametrize("value", ["", "这单"])
async def test_focus_is_not_used_without_previous_detail(value):
    c = Conversation(data=s4_data)
    events = await c.ask("这单现在到哪了", plan(step("issue_detail", issue={"value": value, "from": "previous"})))
    assert "ZC99" not in _text(events)


# ---------------------------------------------------------------------------- S5 评审（`docs/reviews/2026-10-30-G4b-S5多轮与交互评审.md`）


BR = {"value": ["巴西"], "from": "user"}


def _cost(src: str = "user") -> dict:
    return {"field": "其他", "column": "是否涉及费用", "op": "是", "value": "是", "from": src}


def _main_sql(h, table: str) -> str:
    return " ".join(q.sql for q in data_queries(h) if q.tables[0] == table)


async def test_m1_cost_flag_survives_verify_and_follow_up():
    """M1：上一轮明说「是否涉及费用为是」按单上标记查；「你确定吗」「那上个月呢」照上一轮的判据，仍按标记查，
    不因本轮问句里没有「是否涉及费用」换成按费用明细。"""
    c = Conversation(data=s3_data)
    await c.ask("近 30 天巴西是否涉及费用为是的单有哪些", plan(step("list_issues", domains=BR, time=T30,
                                                                  filters=[_cost()])), NARR)
    assert "[IsCost] =" in _main_sql(c.h, "BrazilProblemList")
    assert c.ws(workspace.TURN)["steps"]["s1"]["decided"]["涉及费用"] == "标记"
    c.h.llm.replies.clear()
    c.h.queries.clear()
    events = await c.ask("你确定吗", plan(step("verify_previous")))
    assert "[IsCost] =" in _main_sql(c.h, "BrazilProblemList")
    assert "按费用明细认定" not in _text(events) and "结果与上一轮一致" in _text(events)
    c.h.queries.clear()
    keep = plan(step("list_issues", domains={"value": ["巴西"], "from": "previous"},
                     time=[{"said": "上个月", "basis": "建单", "from": "user"}], filters=[_cost("previous")]))
    events = await c.ask("那上个月呢", keep, NARR)
    assert "[IsCost] =" in _main_sql(c.h, "BrazilProblemList") and "按费用明细认定" not in _text(events)
    # 本轮自己说的「涉及费用的单」照旧按费用明细
    c.h.queries.clear()
    fresh = plan(step("list_issues", domains=BR, time=T30, filters=[
        {"field": "其他", "column": "费用明细合计大于 0", "op": "是", "value": "涉及费用", "from": "user"}]))
    events = await c.ask("近 30 天巴西涉及费用的单子", fresh, NARR)
    assert "按费用明细认定" in _text(events)


def _only_named(frame: pd.DataFrame):
    """人员表按 SQL 里的姓名条件返回（假连接器本来不执行 WHERE，这里照姓名过滤，才测得出没按姓名补取）。"""
    def get(_sql: str, params: dict) -> pd.DataFrame:
        names = {str(v) for v in params.values()}
        return frame[frame["Name"].isin(names)].copy()
    return get


async def test_m2_verify_refetches_people_named_in_the_previous_plan():
    """M2：上一轮按跟进人筛过；「你确定吗」问句里没有这个名字，重放前照样按计划里的姓名取人，不答成没有这个人。"""
    c = Conversation(scopes.account_jia())
    c.h.connectors["info"].frames["Employee"] = _only_named(cn_data.FRAMES["Employee"])
    who = {"field": "跟进人", "op": "是", "value": "测试甲", "from": "user"}
    await c.ask("近 30 天测试甲跟进的国内问题", plan(step("list_issues", domains=CN, time=T30, filters=[who])), NARR)
    c.h.llm.replies.clear()
    events = await c.ask("你确定吗", plan(step("verify_previous")))
    assert EventType.CLARIFY not in _types(events)
    assert "国内：与上一轮一致" in _text(events) and "没有找到人员" not in _text(events)


async def test_a3_replay_that_asks_writes_pending_and_last_clarify():
    """A3：重放时又要追问（上一轮的名字这次对上了两个人）：记「追问」、写 `pending_clarify`（问句全文是上一轮问句
    加选项，按钮只写选项），点了直接填进上一轮的计划。"""
    c = Conversation(scopes.account_jia())
    staff = cn_data.FRAMES["Employee"]
    c.h.connectors["info"].frames["Employee"] = _only_named(staff)
    who = {"field": "跟进人", "op": "是", "value": "测试甲", "from": "user"}
    first = "近 30 天测试甲跟进的国内问题"
    await c.ask(first, plan(step("list_issues", domains=CN, time=T30, filters=[who])), NARR)
    before = c.ws(workspace.TURN)
    twins = pd.concat([staff, pd.DataFrame([{"ID": 13, "Name": "测试甲", "Unit": 8}])], ignore_index=True)
    c.h.connectors["info"].frames["Employee"] = _only_named(twins)
    c.h.llm.replies.clear()
    events = await c.ask("你确定吗", plan(step("verify_previous")))
    assert _types(events) == [EventType.CLARIFY]
    rec = _buttons(events)[0]
    assert "测试甲" in rec["label"] and not rec["query"].startswith(first)
    assert c.ws(workspace.LAST)["outcome"] == workspace.OUTCOME_CLARIFY
    assert c.ws(workspace.TURN) == before and c.ws(workspace.PENDING)["options"]
    option = next(o for o in c.ws(workspace.PENDING)["options"] if o["query"] == rec["query"])
    assert option["full"].startswith(first + "（")
    events = await c.ask(rec["query"], NARR)
    assert EventType.CLARIFY not in _types(events) and EventType.TABLE in _types(events)
    assert c.ws(workspace.TURN)["query"] == option["full"]


async def test_a3_failed_rounds_do_not_overwrite_turn():
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    before = c.ws(workspace.TURN)
    c.h.connectors["info"].errors["ZCTracking_ProblemList"] = RuntimeError("连不上")
    events = await c.ask("那今年呢", plan(step("list_issues", domains=CN_PREV, time=[
        {"said": "今年", "basis": "建单", "from": "user"}])))
    assert any(e.type is EventType.ERROR for e in events)
    assert c.ws(workspace.TURN) == before and c.ws(workspace.LAST)["outcome"] == workspace.OUTCOME_FAILED
    # 质疑重查每步都没查成：同样记「出错」、不覆盖
    c = Conversation(scopes.account_jia())
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    before = c.ws(workspace.TURN)
    c.h.connectors["info"].errors["ZCTracking_ProblemList"] = RuntimeError("连不上")
    c.h.llm.replies.clear()
    await c.ask("你确定吗", plan(step("verify_previous")))
    assert c.ws(workspace.TURN) == before and c.ws(workspace.LAST)["outcome"] == workspace.OUTCOME_FAILED


async def test_a3_rerender_rerun_failure_is_not_found():
    c = Conversation(data=s3_data)
    await c.ask("近 30 天按问题类型统计", plan(step("aggregate", time=T30, group_by=["问题类型"])), NARR)
    narrow = make_harness(scopes.account_jia(), history=[], config_files={"link_sites.toml": SITES})
    s3_data.load(narrow)
    narrow.workspace.store.update(c.h.workspace.store)
    narrow.ctx.session.rows = list(c.h.ctx.session.rows)
    narrow.connectors["info"].errors["ZCTracking_ProblemList"] = RuntimeError("连不上")
    narrow.llm.replies = [plan(step("rerender", chart="饼图"))]
    await run(narrow, "换成饼图")
    assert narrow.workspace.store[workspace.LAST]["outcome"] == workspace.OUTCOME_FAILED
    assert narrow.workspace.store[workspace.TURN] == c.ws(workspace.TURN)


async def test_a2_named_months_do_not_get_the_same_period_button():
    """A2：「本月截至今天」「按上月同期比」只管「这个月比上个月」；写明了年月的对比照常比，不出这句和这个按钮。"""
    today = date.today()
    prev = (today.replace(day=1) - timedelta(days=1))
    this_said, prev_said = f"{today.year}年{today.month}月", f"{prev.year}年{prev.month}月"
    c = Conversation(scopes.account_jia())
    reply = plan(step("aggregate", domains=CN, compare="时段", time=[
        {"said": this_said, "basis": "建单", "from": "user"}, {"said": prev_said, "basis": "建单", "from": "user"}]))
    events = await c.ask(f"国内{this_said}和{prev_said}比", reply, NARR)
    assert "本月截至今天" not in _text(events)
    assert suggestions.SAME_PERIOD not in [r["label"] for r in _buttons(events)]
    assert timespan.is_this_month("这个月") and timespan.is_last_month("上月") and not timespan.is_last_month("上上月")
    assert not timespan.is_this_month(this_said) and not timespan.is_last_month(prev_said)


async def test_a1_verify_compares_counts_only_when_stored_ids_are_capped():
    """A1：工作区每域只存前 `cap` 张；存满了时只比张数，不把截掉的那截报成新查到。"""
    from factory_issue_module.stats import runner

    h = make_harness(scopes.GREEN)
    P = {"steps": ["s1"], "domains": {"s1": ["国内"]}, "cap": 2, "table_rows": 20,
         "texts": {"added": "这次新查到", "removed": "这次没查到"},
         "old": {"s1": {"国内": {"ids": [1, 2], "numbers": ["ZC1", "ZC2"], "found": 3}}},
         "new": {"s1": {"国内": {"ids": [1, 2, 3], "numbers": ["ZC1", "ZC2", "ZC3"], "found": 3}}}}
    res = (await runner.run(h.ctx, "verify", {}, P)).result
    item = res["steps"][0]["domains"][0]
    assert item["partial"] and item["same"] and item["added"] == [] and res["rows"] == [] and not res["changed"]
    P["cap"] = 5
    res = (await runner.run(h.ctx, "verify", {}, P)).result
    assert res["steps"][0]["domains"][0]["added"] == ["ZC3"] and res["changed"]


async def test_list_issue_ids_come_back_as_frames_not_in_result():
    """A1：清单与统计的结果单经数据帧通道回传，不放进 result（几千张单会撑满 20 万字符，设计 §8.1）。"""
    c = Conversation(scopes.account_jia())
    seen = []
    original = c.h.stats.run

    async def spy(script, datasets=None, **kw):
        out = await original(script, datasets, **kw)
        seen.append((kw.get("return_frames"), out))
        return out

    c.h.stats.run = spy
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    await c.ask("近 30 天国内按问题类型统计", plan(step("aggregate", domains=CN, time=T30, group_by=["问题类型"])), NARR)
    for frames_on, out in seen:
        if isinstance(out.result, dict) and "segments" in out.result:
            assert frames_on and "issues" not in (out.result.get("refs") or {}) and "ids_国内" in out.frames
    assert c.ws(workspace.RESULTS)["steps"]["s1"]["国内"]["ids"]


async def test_currency_button_appends_to_the_amount():
    """币种直填：「费用超过 200」点了「美元」，取值改成「200 美元」，按美元合计比，不再追问。"""
    c = Conversation(data=s3_data)
    amount = {"field": "其他", "column": "费用", "op": "大于", "value": "200", "from": "user"}
    events = await c.ask("近 30 天巴西费用超过 200 的单", plan(step("list_issues", domains=BR, time=T30,
                                                                     filters=[amount])))
    rec = next(r for r in _buttons(events) if r["label"] == "美元")
    assert c.ws(workspace.PENDING)["options"][0]["patch"]["kind"] == base.FILL_APPEND
    events = await c.ask(rec["query"], NARR)
    assert EventType.CLARIFY not in _types(events)
    value = c.ws(workspace.TURN)["plan"]["steps"][0]["params"]["filters"][0]["value"]
    assert value == "200 美元" and "费用（美元）" in _text(events)


async def test_duplicate_name_button_fills_department_and_person():
    """重名直填：两位「测试甲」，点了「研发一部的测试甲」，取值换成这一位，不再追问。"""
    c = Conversation(scopes.account_jia())
    twins = pd.concat([cn_data.FRAMES["Employee"], pd.DataFrame([{"ID": 13, "Name": "测试甲", "Unit": 8}])],
                      ignore_index=True)
    c.h.connectors["info"].frames["Employee"] = _only_named(twins)
    who = {"field": "跟进人", "op": "是", "value": "测试甲", "from": "user"}
    events = await c.ask("近 30 天测试甲跟进的国内问题", plan(step("list_issues", domains=CN, time=T30, filters=[who])))
    rec = next(r for r in _buttons(events) if r["label"] == "研发一部的测试甲")
    c.h.queries.clear()
    events = await c.ask(rec["query"], NARR)
    assert EventType.CLARIFY not in _types(events)
    main = next(q for q in data_queries(c.h) if q.tables[0] == "ZCTracking_ProblemList")
    assert "13" in [str(v) for v in main.params.values()]
