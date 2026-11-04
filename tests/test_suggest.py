"""答后建议改由模型挑（设计 §9.5、§10 `suggest`、§11；决策 2026-11-02「答后建议改由模型挑」）。

- 去重：会话里问过的、推荐过的不再推（意图键按计划算，与用户怎么说无关）。
- 点了接着问按钮：不调规划，直接执行存下的计划；更早几轮的按钮照常规划。
- 模型的选择逐条核对；出错、超时、关掉、全被丢掉时按代码的默认顺序取；挑了 0 条时不给接着问。
- 候选的几种动作：叠加、下一张、找类似。

假模型的答后建议那次调用走 `FakeLLM.suggest_reply`（默认照默认问句挑前两条），不占 `calls` 与顺序回放。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import cn_data
import fakes
import pandas as pd
import pytest
import s4_data
import scopes
from fakes import make_harness, run
from forge_core.events import EventType

from factory_issue_module.config import files as config_files
from factory_issue_module.config.files import ConfigFormatError
from factory_issue_module.plan import timespan
from factory_issue_module.present import moves, suggest, suggestions
from factory_issue_module.turn import workspace

CN = {"value": ["国内"], "from": "user"}
T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
NARR = "共 4 张，硬件问题最多。最需要关注的是 ZC9901001。"
SITES = 'issue = "info.test.local"'


def plan(*steps: dict) -> dict:
    return {"understanding": "按条件查", "alternatives": [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _buttons(events) -> list[dict]:
    for e in events:
        if e.type in (EventType.SUGGESTIONS, EventType.CLARIFY):
            return e.data.get("recommendations") or []
    return []


def _queries(events) -> list[str]:
    return [r["query"] for r in _buttons(events)]


def _planner_calls(h) -> int:
    return sum(1 for m in h.llm.calls if "的规划器" in str(m[0].get("content") or ""))


def pick(*wanted: str, query: str | None = None, phenomenon: str | None = None):
    """答后建议的回放：挑默认问句是这几句的候选；给了 `query` 时把这几条合成一条、问句用它。"""
    def reply(messages):
        got = dict((q, cid) for cid, q in fakes.candidates_in(messages))
        ids = [got[w] for w in wanted if w in got]
        if query is not None:
            item = {"ids": ids, "query": query}
            if phenomenon is not None:
                item["phenomenon"] = phenomenon
            return {"suggestions": [item] if ids else []}
        return {"suggestions": [{"ids": [cid], "query": w} for w, cid in zip(wanted, ids, strict=False)]}
    return reply


class Conversation:
    def __init__(self, privileges=None, *, data=cn_data, config: dict | None = None):
        self.h = make_harness(scopes.GREEN if privileges is None else privileges, history=[],
                              config_files={"link_sites.toml": SITES, **(config or {})})
        data.load(self.h)
        self.n = 0

    async def ask(self, query: str, *replies) -> list:
        self.h.llm.replies += list(replies)
        events = await run(self.h, query)
        self.n += 1
        self.h.ctx.session.rows += [
            {"role": "user", "content": query, "message_id": f"t{self.n}"},
            {"role": "assistant", "content": _text(events) or "（追问）", "message_id": f"t{self.n}"}]
        return events

    def ws(self, key: str) -> dict | None:
        return self.h.workspace.store.get(key)

    def prompt(self) -> str:
        return str(self.h.llm.suggest_calls[-1][-1]["content"])


# ---------------------------------------------------------------------------- 去重（开发者 2026-11-02 的实测例子）


async def test_reported_case_never_offers_what_was_asked_or_offered():
    """「ZC… 的详情」→ 点「完整处理过程」→ 问「原因与措施」：之后不再推「完整处理过程」（原先第 3 轮又推了它）。"""
    c = Conversation(data=s4_data)
    asked: list[str] = []
    offered: list[str] = []

    async def turn(query: str, *replies) -> list[str]:
        events = await c.ask(query, *replies)
        got = _queries(events)
        assert not set(got) & set(asked + offered), (query, got)
        asked.append(query)
        offered.extend(got)
        return got

    first = await turn("ZC9901001")
    assert "ZC9901001 的完整处理过程" in first and "ZC9901001 的原因与措施" not in first
    planned = _planner_calls(c.h)
    second = await turn("ZC9901001 的完整处理过程")  # 点了按钮：直接执行存下的计划
    assert _planner_calls(c.h) == planned and "操作记录" not in second
    third = await turn("ZC9901001 的原因与措施", plan(step("issue_detail", issue={"value": "ZC9901001", "from": "user"},
                                                           aspects=["原因", "措施"])))
    assert not any(q.endswith("的完整处理过程") for q in third)
    seen = c.ws(workspace.SUGGEST)["seen"]
    assert moves.detail_key("ZC9901001", "process") in seen and moves.detail_key("ZC9901001", "reasons") in seen


async def test_full_detail_with_car_report_content_still_offers_reasons():
    """单上有 CAR 报告内容时，整张详情只给了 CAR 编号：照推「原因与措施」（决策 2026-11-02 第 3 条）。"""
    c = Conversation(data=s4_data)
    c.h.llm.suggest_reply = pick("ZC9901002 的原因与措施")
    events = await c.ask("ZC9901002")
    assert "ZC9901002 的原因与措施" in _queries(events)
    assert "关联了 CAR 报告" in c.prompt()


# ---------------------------------------------------------------------------- 点了之后


async def test_click_runs_the_stored_plan_and_says_what_was_carried():
    c = Conversation(scopes.account_jia())
    c.h.llm.suggest_reply = pick("只看还没结案的")
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    assert _queries(events) == ["只看还没结案的"]
    offered = c.ws(workspace.SUGGEST)["offered"]
    assert offered[0]["move"] == moves.NARROW and offered[0]["plan"]["steps"][0]["params"]["filters"][-1]["value"] == "未结案"
    planned = _planner_calls(c.h)
    events = await c.ask("只看还没结案的", NARR)
    assert _planner_calls(c.h) == planned
    text = _text(events)
    assert "沿用上一轮的条件：国内、时间「近 30 天」；本轮换成：状态 未结案" in text
    turn = c.ws(workspace.TURN)
    assert turn["query"] == "只看还没结案的" and turn["plan"]["steps"][0]["params"]["filters"][-1]["value"] == "未结案"
    # 沿用的时间按上一轮换算出的日期（§10）
    assert turn["steps"]["s1"]["times"][0]["said"] == "近 30 天"


async def test_button_from_an_earlier_turn_is_planned_as_usual():
    c = Conversation(scopes.account_jia())
    c.h.llm.suggest_reply = pick("只看还没结案的")
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    c.h.llm.suggest_reply = {"suggestions": []}
    await c.ask("近 30 天国内按问题类型统计", plan(step("aggregate", domains=CN, time=T30, group_by=["问题类型"])), NARR)
    planned = _planner_calls(c.h)
    reply = plan(step("list_issues", domains=CN, time=T30,
                      filters=[{"field": "状态", "op": "是", "value": "未结案", "from": "user"}]))
    await c.ask("只看还没结案的", reply, NARR)
    assert _planner_calls(c.h) == planned + 1


async def test_two_candidates_on_the_same_base_compose_into_one():
    c = Conversation(scopes.account_jia())
    c.h.llm.suggest_reply = pick("只看还没结案的", "按问题类型统计这些单", query="没结案的按问题类型统计")
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    assert _queries(events) == ["没结案的按问题类型统计"]
    stored = c.ws(workspace.SUGGEST)["offered"][0]["plan"]["steps"][0]
    assert stored["skill"] == "aggregate" and stored["params"]["group_by"] == ["问题类型"]
    assert stored["params"]["filters"][-1]["value"] == "未结案"
    events = await c.ask("没结案的按问题类型统计", "未结案的单里硬件问题最多。软件问题 1 张。")
    heads = [e.data["text"] for e in events if e.type is EventType.DELTA and e.data["text"].strip().startswith("**")]
    assert any("按问题类型统计" in t for t in heads)  # 小标题写在正文里（决策 2026-11-03「回答骨架与排版」）


# ---------------------------------------------------------------------------- 模型的选择怎么核对


def _pool() -> moves.Pool:
    base = {"id": "s1", "skill": "list_issues", "when": None,
            "params": {"domains": {"value": ["国内"], "from": "previous"},
                       "time": [{"said": "近 30 天", "basis": "建单", "from": "previous"}]}}
    pool = moves.Pool(bases={"b": base})
    add = moves._Adder(pool, moves.Context(today=date.today(), access=["国内"], text_access=["国内"], seen=set()))
    add.patched(moves.NARROW, "b", {"filters": [moves._eq("状态", "未结案")]}, ["filter:状态"], "只看还没结案的",
                ["结案"], "其中未结案 3 张")
    add.patched(moves.NARROW, "b", {"filters": [moves._eq("状态", "停线中")]}, ["filter:状态"], "只看还在停线的",
                ["停线"], "其中停线中 1 张")
    add.patched(moves.ANGLE, "b", {"group_by": ["问题类型"]}, ["group"], "按问题类型统计这些单", ["问题类型"])
    add(moves._drill_issue("ZC9901001", "停线中"))
    add(moves.Candidate(move=moves.SIMILAR, key="类似|ZC9901001", query="和 ZC9901001 类似的问题",
                        plan=moves.similar_plan(""), slot=True, source="按键手感差，弹片 2 片偏软"))
    return pool


@pytest.mark.parametrize(("item", "why"), [
    ({"ids": ["c9"], "query": "只看还没结案的"}, "编号"),
    ({"ids": ["c1"], "query": "只看在处理中的"}, "必带"),
    ({"ids": ["c1"], "query": "只看还没结案的 5 张"}, "数字"),
    ({"ids": ["c4"], "query": "ZC9901009 的详情"}, "必带"),
    ({"ids": ["c4"], "query": "ZC9901001 和 BR9901001 的详情"}, "单号"),  # 数字一样、单号不是候选里的
    ({"ids": ["c1"], "query": "只看 Rate_value 没结案的"}, "字段名"),
    ({"ids": ["c1"], "query": "只看还没结案的，按建单时间从新到旧再列一遍，顺便看看都是哪些工厂的"}, "长度"),
    ({"ids": ["c1", "c2"], "query": "没结案又停线的"}, "叠加"),  # 两条都加状态这一个条件
    ({"ids": ["c3"], "query": "按问题类型统计这些单"}, "重复"),
    ({"ids": ["c5"], "query": "有没有类似的问题"}, "现象"),  # 没写现象、也没有默认的
    ({"ids": ["c5"], "query": "有没有类似的问题", "phenomenon": "按键 3 片偏软"}, "现象"),  # 数不在问题描述里
])
def test_bad_picks_are_dropped_with_a_reason(item, why):
    pool = _pool()
    by_id = {f"c{i}": c for i, c in enumerate(pool.items, start=1)}
    taken = {moves.question_key("按问题类型统计这些单")}
    assert suggest.check(item, by_id, pool, taken) == why


def test_ellipsis_label_falls_back_to_the_whole_query():
    """模型用省略号把按钮文字切短：这条标签作废，按钮改用问句全文。"""
    pool = _pool()
    by_id = {f"c{i}": c for i, c in enumerate(pool.items, start=1)}
    got = suggest.check({"ids": ["c1"], "query": "只看还没结案的", "label": "只看还没结案…"}, by_id, pool, set())
    assert isinstance(got, suggest.Chosen) and got.label == ""
    button = suggestions.follow_up(got.query, got.label)
    assert button["label"] == "只看还没结案的" and not button["label"].endswith("…")


def test_label_between_16_and_30_is_kept():
    pool = _pool()
    by_id = {f"c{i}": c for i, c in enumerate(pool.items, start=1)}
    label = "只看还没结案的单子，先看看这一批"
    assert 16 <= len(label) <= 30
    got = suggest.check({"ids": ["c1"], "query": "只看还没结案的", "label": label}, by_id, pool, set())
    assert isinstance(got, suggest.Chosen) and got.label == label


def test_long_relax_label_keeps_the_count():
    """16–30 字的放宽标签整句保留，张数还在。"""
    what = "问题跟进部门名称"
    label = f"不限{what}（12 张）"
    assert 16 <= len(label) <= 30
    done = moves.Done(sid="s1", skill="list_issues", step=step("list_issues"), relax=[{
        "kind": "drop", "what": what, "value": "质量部", "count": 12, "key": "drop|部门",
        "plan": plan(step("list_issues"))}])
    pool = moves.Pool()
    moves._relax_candidates(done, moves._Adder(pool, moves.Context(
        today=date.today(), access=["国内"], text_access=[], seen=set())))
    assert pool.items[0].label == label and "12" in pool.items[0].label


def test_query_over_30_uses_a_complete_short_label():
    query = "只看" + "甲" * 29
    assert len(query) > 30
    assert moves._short_label(query, "只看该加工厂") == "只看该加工厂"
    assert suggestions.follow_up("ZC9901001 的完整处理过程")["label"] == "ZC9901001 的完整处理过程"


def test_good_picks_build_the_plan_to_run():
    pool = _pool()
    by_id = {f"c{i}": c for i, c in enumerate(pool.items, start=1)}
    got = suggest.check({"ids": ["c2", "c3"], "query": "停线的按问题类型看看"}, by_id, pool, set())
    assert isinstance(got, suggest.Chosen)
    s = got.plan["steps"][0]
    assert s["skill"] == "aggregate" and s["params"]["group_by"] == ["问题类型"]
    assert s["params"]["filters"] == [moves._eq("状态", "停线中")]
    got = suggest.check({"ids": ["c5"], "query": "有没有类似按键手感差的问题", "phenomenon": "按键手感差"},
                        by_id, pool, set())
    assert isinstance(got, suggest.Chosen) and got.plan["steps"][0]["params"]["phenomenon"] == "按键手感差"
    got = suggest.check({"ids": ["c1"], "query": "没结案的那 3 张有哪些"}, by_id, pool, set())  # 依据里有 3
    assert isinstance(got, suggest.Chosen)


# ---------------------------------------------------------------------------- 退路


@pytest.mark.parametrize("reply", [
    TimeoutError("超时"), RuntimeError("服务出错"), "不是 JSON",
    {"suggestions": [{"ids": ["c99"], "query": "随便问问"}]},  # 挑的全被丢掉
])
async def test_model_trouble_falls_back_to_the_default_order(reply):
    c = Conversation(scopes.account_jia())
    c.h.llm.suggest_reply = reply
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    defaults = [q for _cid, q in fakes.candidates_in(c.h.llm.suggest_calls[-1])][:suggestions.MODEL_MAX]
    assert _queries(events) == defaults and len(defaults) == suggestions.MODEL_MAX


async def test_slow_model_times_out_to_the_defaults():
    class Slow:
        async def chat(self, *_a, **_k):
            await asyncio.sleep(5)

    pool = _pool()
    got = await suggest.choose(Slow(), pool, query="q", history=[], answer="", n=2, seconds=0.05, seen=set())
    assert [c.query for c in got] == [c.query for c in pool.items[:2]]


async def test_model_picking_nothing_gives_no_follow_ups():
    c = Conversation(scopes.account_jia())
    c.h.llm.suggest_reply = {"suggestions": []}
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    assert EventType.SUGGESTIONS not in [e.type for e in events]
    assert c.ws(workspace.SUGGEST)["offered"] == []


async def test_switched_off_uses_the_default_order_without_calling_the_model():
    c = Conversation(scopes.account_jia(), config={"answer_params.toml": "suggest_model = false"})
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    assert c.h.llm.suggest_calls == [] and len(_queries(events)) == suggestions.MODEL_MAX
    assert all(r["name"] == suggestions.TEMPLATE_NAME for r in _buttons(events))


@pytest.mark.parametrize(("text", "ok"), [
    ("suggest_model = false\nsuggest_seconds = 10", True),
    ("suggest_seconds = 0", False), ("suggest_seconds = 31", False), ("suggest_seconds = 2.5", False),
    ("suggest_model = 1", False),
])
def test_answer_params_suggest_keys(text, ok):
    if ok:
        got = config_files.parse_answer_params(text)
        assert got.suggest_model is False and got.suggest_seconds == 10
    else:
        with pytest.raises(ConfigFormatError):
            config_files.parse_answer_params(text)
    got = config_files.parse_answer_params("")
    assert got.suggest_model is True and got.suggest_seconds == 5


# ---------------------------------------------------------------------------- 结果为空时放宽一个条件（决策 2026-11-03）

A920 = {"field": "机型", "op": "是", "value": "A920", "from": "user"}
KES = {"field": "加工厂", "op": "是", "value": "柯洱斯", "from": "user"}


def _main_empty_for(cutoff_days: int = 40, factory: str | None = "04"):
    """假主表：近 `cutoff_days` 天以内、又按 `factory` 这家工厂筛时一张都没有（`factory=None` 时只看时间）。
    假连接器不执行 WHERE，机型在沙箱里筛，加工厂与建单时间是 SQL 参数。"""
    cutoff = datetime.combine(date.today() - timedelta(days=cutoff_days), datetime.min.time())

    def main(_sql: str, params: dict) -> pd.DataFrame:
        starts = [v for v in params.values() if isinstance(v, datetime)]
        recent = bool(starts) and min(starts) > cutoff
        if recent and (factory is None or factory in params.values()):
            return pd.DataFrame()
        return pd.DataFrame(cn_data.main_rows())
    return main


async def test_reported_empty_turn_says_where_it_is_stuck_and_offers_relaxed_buttons():
    """开发者实测：上一轮查国内 A920、柯洱斯，「那近 30 天呢」查出 0 张，原先一个选项都没有。"""
    c = Conversation(scopes.account_jia())
    cn_data.load(c.h, main=_main_empty_for())
    c.h.llm.suggest_reply = {"suggestions": []}
    await c.ask("近 90 天国内 A920 柯洱斯的问题", plan(step("list_issues", domains=CN, filters=[A920, KES],
                                                           time=[{"said": "近 90 天", "basis": "建单", "from": "user"}])),
                NARR)
    c.h.llm.suggest_reply = fakes.pick_first_two
    prev = {**CN, "from": "previous"}
    carried = [{**A920, "from": "previous"}, {**KES, "from": "previous"}]
    events = await c.ask("那近 30 天呢", plan(step("list_issues", domains=prev, filters=carried, time=T30)))
    text = _text(events)
    assert "没有查到单" in text
    # 近 90 天上一轮查过，不再试，改试近半年；不限机型是 0 张，不写；不限时间另写最近建单的一张
    assert "只放宽一个条件时：时间放到近半年有 2 张；不限加工厂有 2 张；不限时间有 2 张，最近建单的一张是 [ZC9901001]" in text
    assert "近 90 天" not in text.split("没有查到单")[1] and "不限机型" not in text
    recs = _buttons(events)
    assert [r["query"] for r in recs] == ["那近半年呢", "不限加工厂呢"]
    assert [r["label"] for r in recs] == ["看近半年（2 张）", "不限加工厂（2 张）"]  # 张数写在按钮上（前端显示 label）
    # 点了：不调规划，按放宽后的计划查，开头写明沿用了哪些
    planned = _planner_calls(c.h)
    events = await c.ask("不限加工厂呢", NARR)
    assert _planner_calls(c.h) == planned
    text = _text(events)
    assert "沿用上一轮的条件：国内、时间「近 30 天」、机型 A920" in text and "共 2 张" in text
    assert "柯洱斯" not in text.split("统计口径")[1]


async def test_all_relaxed_empty_says_what_was_tried_and_gives_no_buttons():
    c = Conversation(scopes.account_jia())
    cn_data.load(c.h, main=lambda _sql, _p: pd.DataFrame())
    events = await c.ask("近 30 天国内 A920 的问题", plan(step("list_issues", domains=CN, time=T30, filters=[A920])))
    assert "只放宽一个条件也都没有单（试过：时间放到近 90 天、不限机型、不限时间）。" in _text(events)
    assert EventType.SUGGESTIONS not in [e.type for e in events] and c.h.llm.suggest_calls == []
    assert c.ws(workspace.SUGGEST)["offered"] == []


async def test_relaxed_label_from_the_model_must_carry_the_count():
    c = Conversation(scopes.account_jia())
    cn_data.load(c.h, main=_main_empty_for(factory=None))

    def reply(m):
        ids = {q: cid for cid, q in fakes.candidates_in(m)}
        return {"suggestions": [{"ids": [ids["那近 90 天呢"]], "query": "放到近 90 天看看", "label": "近 90 天看看"},
                                {"ids": [ids["不限时间呢"]], "query": "不限时间再查", "label": "不限时间有 4 张"}]}
    c.h.llm.suggest_reply = reply
    events = await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)))
    recs = _buttons(events)
    assert [r["query"] for r in recs] == ["放到近 90 天看看", "不限时间再查"]
    # 没写张数的换成默认按钮文字；写了的照用
    assert [r["label"] for r in recs] == ["看近 90 天（4 张）", "不限时间有 4 张"]


async def test_future_period_is_not_relaxed():
    c = Conversation(scopes.account_jia())
    cn_data.load(c.h, main=lambda _sql, _p: pd.DataFrame())
    future = [{"said": "2099 年 1 月", "basis": "建单", "from": "user"}]
    events = await c.ask("2099 年 1 月国内的问题", plan(step("list_issues", domains=CN, time=future)))
    text = _text(events)
    assert "这段时间还没到" in text and "只放宽一个条件" not in text
    assert len(c.h.stats.calls) == 1  # 只有本轮那一次沙箱，没有预查


def test_relax_options_shapes():
    today = date.today()
    spans = [timespan.convert("近 30 天", today)]
    base = step("list_issues", domains=CN, time=T30, filters=[A920, KES])
    got = moves.relax_options(base, spans, today, set())
    assert [(x.kind, x.what) for x in got] == [("time", "近 90 天"), ("drop", "机型"), ("drop", "加工厂"),
                                              ("unlimited", "不限时间")]
    drop = got[1].plan["steps"][0]["params"]
    assert drop["filters"] == [{**KES, "from": "previous"}] and drop["time"][0]["from"] == "previous"
    assert got[0].plan["steps"][0]["params"]["time"] == [{"said": "近 90 天", "basis": "建单", "from": "user"}]
    assert [x.keep_spans for x in got] == [False, True, True, False]
    # 按结案日期筛：不限时间会丢掉「结案了」这层意思，不试
    closed = step("aggregate", domains=CN, time=[{"said": "近 30 天", "basis": "结案", "from": "user"}])
    assert [x.kind for x in moves.relax_options(closed, spans, today, set())] == ["time"]
    # 比较两个时段：不动时间
    two = [{"said": "今年", "basis": "建单", "from": "user"}, {"said": "去年", "basis": "建单", "from": "user"}]
    cmp_step = step("aggregate", domains=CN, time=two, compare="时段", filters=[A920])
    spans2 = [timespan.convert("今年", today), timespan.convert("去年", today)]
    assert [x.kind for x in moves.relax_options(cmp_step, spans2, today, set())] == ["drop"]
    # 本会话执行过的不试
    seen = {got[1].key}
    assert "机型" not in [x.what for x in moves.relax_options(base, spans, today, seen)]


# ---------------------------------------------------------------------------- 几种动作


async def test_after_opening_one_issue_the_rest_of_the_list_is_next():
    """清单里标出、没点开的单留到下一轮（§10 `carry`）：点开其中一张后推「下一张」，点开的那张不再推。"""
    c = Conversation(scopes.account_jia(), data=s4_data)
    c.h.llm.suggest_reply = pick("ZC9901001 的详情")
    await c.ask("近 30 天国内的问题有哪些", plan(step("list_issues", domains=CN, time=T30)), NARR)
    carry = c.ws(workspace.SUGGEST)["carry"]
    assert carry and all("ZC9901001" not in x["key"] for x in carry)
    c.h.llm.suggest_reply = fakes.pick_first_two
    await c.ask("ZC9901001 的详情")
    prompt = c.prompt()
    nexts = [line for line in prompt.splitlines() if f"｜{moves.NEXT}｜" in line]
    assert nexts and all("ZC9901001" not in line for line in nexts)


async def test_similar_issue_uses_the_phenomenon_the_model_wrote():
    c = Conversation(data=s4_data)
    c.h.llm.suggest_reply = lambda m: {"suggestions": [
        {"ids": [line.split("｜", 1)[0]], "query": "有没有类似按键手感差的问题", "phenomenon": "按键手感差"}
        for line in str(m[-1]["content"]).splitlines() if f"｜{moves.SIMILAR}｜" in line]}
    events = await c.ask("ZC9901001")
    assert _queries(events) == ["有没有类似按键手感差的问题"]
    stored = c.ws(workspace.SUGGEST)["offered"][0]["plan"]["steps"][0]
    assert stored["skill"] == "text_search" and stored["params"] == {"mode": "类似问题", "phenomenon": "按键手感差"}
    assert "这张单的问题描述：按键手感差" in c.prompt()


async def test_detail_offers_lists_of_the_same_machine_and_factory():
    c = Conversation(data=s4_data)
    await c.ask("ZC9901001")
    prompt = c.prompt()
    assert f"｜{moves.UP}｜默认问句：国内 A920 近 90 天的问题" in prompt
    assert f"｜{moves.UP}｜默认问句：国内柯洱斯近 90 天的问题" in prompt
