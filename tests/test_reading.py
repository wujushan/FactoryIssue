"""按什么理解写在开头（决策 2026-11-04「按什么理解写在开头」；设计 §5.3 第 20 条）。

手动测试 2026-11-04：「国内问题比较严重的单」按问题等级 A+、A 查，开头没说，结论写成「国内问题单共 628 张」；
「不良率特别高的国内单」规划器自己定了 20 张，小标题写「按要求列出前 20 张」，结论把列出的 20 张说成一共 20 张。

前半是规整第 20 条本身；后半端到端，并把几条跨环节的规矩逐条查（`_invariants`）：开头写过的理解交到写结论的
模型手里、小标题不把张数归给用户、只列了前几张时交给模型的事实有两个张数。
"""

from __future__ import annotations

import json

import cn_data
import pandas as pd
import pytest
import scopes
from fakes import make_harness, run
from forge_core.events import EventType

from factory_issue_module.plan import normalize as N

CN = {"value": ["国内"], "from": "user"}
LEVELS_AA = {"field": "问题等级", "op": "属于", "value": ["A+", "A"], "from": "user"}
BY_RATE = {"by": "不良率", "order": "降序"}
POINTS_MARK = "挑出了这次值得说的几点"


def plan(*steps: dict, alternatives: list | None = None) -> dict:
    return {"understanding": "按条件查", "alternatives": alternatives or [], "steps": list(steps)}


def step(skill: str = "list_issues", sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _norm(query: str, p: dict, limit: int = 10) -> tuple[dict, list[str], list]:
    inferred, hits = [], []
    out = N.apply(p, N.Context(query=query, inferred=inferred, hits=hits, default_limit=limit))
    return out, [N.inferred_text(x) for x in inferred], [h for h in hits if h.rule == 20]


# ---------------------------------------------------------------------------- 第 20 条


def test_severe_reads_as_levels_and_quotes_the_users_words():
    _out, notes, _hits = _norm("国内问题比较严重的单", plan(step(domains=CN, filters=[LEVELS_AA])))
    assert notes == ["「比较严重」按问题等级 A+、A 理解"]


def test_count_the_user_did_not_give_becomes_the_default():
    out, notes, hits = _norm("不良率特别高的国内单", plan(step(domains=CN, sort=BY_RATE, limit=20)), limit=10)
    assert out["steps"][0]["params"]["limit"] == 10
    assert notes == ["「不良率特别高」按不良率从高到低列出前 10 张（没说要几张，默认列 10 张）"]
    assert [h.action for h in hits] == ["改写"]


def test_count_without_a_rate_word_says_how_it_was_ordered():
    out, notes, _ = _norm("最新的几张单", plan(step(limit=5)), limit=10)
    assert out["steps"][0]["params"]["limit"] == 10
    assert notes == ["没说要几张，按建单时间从新到旧列出前 10 张"]


@pytest.mark.parametrize(("query", "p"), [
    ("今年不良率最高的 5 张单", plan(step(sort=BY_RATE, limit=5))),
    ("最早建的十张还没结案的单", plan(step(filters=[{"field": "状态", "op": "是", "value": "未结案", "from": "user"}],
                                       sort={"by": "建单时间", "order": "升序"}, limit=10))),
    ("A 级及以上的单", plan(step(filters=[LEVELS_AA]))),
    ("A920 的 A 类问题", plan(step(filters=[{"field": "问题等级", "op": "是", "value": "A", "from": "user"}]))),
    ("物料不良的单", plan(step(filters=[{"field": "问题类型", "op": "是", "value": "物料问题", "from": "user"}]))),
    ("还在处理的单", plan(step(filters=[{"field": "状态", "op": "是", "value": "未结案", "from": "user"}]))),
    ("草稿有哪些", plan(step(filters=[{"field": "状态", "op": "是", "value": "待提交", "from": "user"}]))),
    ("国内安全问题", plan(step(domains=CN, filters=[{"field": "问题等级", "op": "是", "value": "A+", "from": "user"}]))),
    ("那 A 级的呢", plan(step(filters=[{**LEVELS_AA, "from": "previous"}]))),
])
def test_what_the_user_said_is_not_called_an_understanding(query, p):
    out, notes, _ = _norm(query, p)
    assert notes == []
    assert out["steps"][0]["params"].get("limit") == p["steps"][0]["params"].get("limit")


def test_machine_name_is_not_a_level_and_unsaid_values_are_called_out():
    _out, notes, _ = _norm("A920 的问题", plan(step(filters=[{"field": "问题等级", "op": "是", "value": "A", "from": "user"}])))
    assert notes == ["按问题等级 A 理解"]
    _out, notes, _ = _norm("拖着没人管的单", plan(step(filters=[{"field": "状态", "op": "是", "value": "未结案", "from": "user"}])))
    assert notes == ["按状态「未结案」理解"]
    _out, notes, _ = _norm("剩下的类型呢", plan(step(filters=[
        {"field": "问题类型", "op": "不属于", "value": ["结构问题"], "from": "user"}])))
    assert notes == ["按问题类型不属于「结构问题」理解"]


def test_degree_word_read_another_way_is_only_logged():
    """认出了「严重」，计划却没写成 A+、A：照计划查、开头写它的读法，另记一条日志；不打回、不改写。"""
    out, notes, hits = _norm("严重的单", plan(step(filters=[{"field": "状态", "op": "是", "value": "停线中", "from": "user"}])))
    assert notes == ["按状态「停线中」理解"]
    assert [(h.action, h.before) for h in hits] == [("只记日志", ("程度说法：严重",))]
    assert out["steps"][0]["params"]["filters"][0]["value"] == "停线中"
    # 没按不良率排：只记日志，不替它补排序
    _out, notes, hits = _norm("国内不良率特别高的单", plan(step(domains=CN)))
    assert notes == [] and [h.before for h in hits] == [("程度说法：不良率高",)]


@pytest.mark.parametrize("query", ["国内不良率高的单有哪些", "2026 年国内不良率特别高的单", "A920 不良率偏高的单"])
def test_high_rate_sorted_without_a_count_gets_the_default(query):
    """复测 2026-11-05：规划器按不良率从高到低排了、没写张数，原先全部单照排、开头也不说。现在补成默认张数并写明；
    问句里的年份、机型号不算用户说了张数。"""
    out, notes, hits = _norm(query, plan(step(domains=CN, sort=BY_RATE)), limit=10)
    assert out["steps"][0]["params"]["limit"] == 10
    assert len(notes) == 1 and notes[0].endswith("按不良率从高到低列出前 10 张（没说要几张，默认列 10 张）")
    assert [h.action for h in hits] == ["改写"]


@pytest.mark.parametrize(("query", "by"), [
    ("国内不良率最高的单有哪些", "不良率"),
    ("不良率比较突出的单", "不良率"),  # 词表里没有「突出」：看的是规划器写出的排序，不看说法
    ("国内影响数量大的单", "影响数量"),
    ("国内不良数量最多的单", "不良数量"),
    ("按不良率排一下国内的单", "不良率"),  # 只要排序的也列前 10 张，开头写明、答后给「看全部」（开发者 2026-11-05 定）
])
def test_sorting_by_a_quantity_lists_the_top_ones_whatever_the_wording(query, by):
    """G95：要不要只列前几张看计划结构（按不良率、不良数量、影响数量排），不看问句里的程度说法。"""
    out, notes, _ = _norm(query, plan(step(domains=CN, sort={"by": by, "order": "降序"})), limit=10)
    assert out["steps"][0]["params"]["limit"] == 10
    assert notes == [f"没说要几张，按{by}从高到低列出前 10 张"]


@pytest.mark.parametrize(("query", "limit", "want"), [
    ("国内不良率最高的是哪张单", 1, 1),  # 单数说法：规划器写成 1，照它，不改成 10
    ("国内不良率最高的那张单", 1, 1),
    ("国内不良率最高的 5 张单", None, 5),  # 规划器漏写张数：照用户说的
    ("2026 年国内不良率最高的前三张", 20, 3),  # 年份里的数不算张数
])
def test_count_the_user_gave_or_implied_is_kept(query, limit, want):
    p = step(domains=CN, sort=BY_RATE) if limit is None else step(domains=CN, sort=BY_RATE, limit=limit)
    out, notes, _ = _norm(query, plan(p), limit=10)
    assert out["steps"][0]["params"]["limit"] == want and notes == []


@pytest.mark.parametrize(("query", "p"), [
    ("把国内的单按不良率排一下，全部导出", step(domains=CN, sort=BY_RATE, export=True)),  # 要全部
    ("最早建的单有哪些", step(sort={"by": "建单时间", "order": "升序"})),  # 按日期排：清单的默认做法，列全部
])
def test_all_rows_stay_when_the_user_wants_them_or_sorts_by_date(query, p):
    out, notes, _ = _norm(query, plan(p))
    assert out["steps"][0]["params"].get("limit") is None and notes == []


def test_numbers_in_the_question():
    assert N.numbers_in("前十张") >= {10} and N.numbers_in("二十五张") >= {25} and N.numbers_in("最新 ５ 张") >= {5}
    assert N.levels_in("A920PRO 的单") == set() and N.levels_in("B 级及以上") == {"A+", "A", "B"}


async def test_reading_survives_the_clarify_round_trip():
    """第 20 条记下的理解随 `pending_clarify` 带到直填的那一轮（种类与原话都带着），开头照样写。"""
    from fakes import FakeWorkspace

    from factory_issue_module.domains import base
    from factory_issue_module.turn import workspace

    class _Ctx:
        workspace = FakeWorkspace()

    inf = N.Inferred("s1", "问题等级", ("A+", "A"), kind=N.KIND_VALUE, said="比较严重")
    ask = base.Ask("要查哪个工厂？", ["惠州百富"], reason="多个工厂", said="惠州", fill=base.FILL_VALUE)
    p = plan(step(filters=[LEVELS_AA, {"field": "加工厂", "op": "是", "value": "惠州", "from": "user"}]))
    ctx = _Ctx()
    assert await workspace.write_pending(ctx, query="惠州比较严重的单", plan=p, ask=ask,
                                         recommendations=[{"id": "1", "name": "选项", "label": "惠州百富",
                                                           "query": "惠州百富"}], inferred=[inf])
    filled = workspace.fill(await workspace.read(ctx, workspace.PENDING), "惠州百富")
    assert filled is not None and filled.inferred == [inf]
    assert N.inferred_text(filled.inferred[0]) == "「比较严重」按问题等级 A+、A 理解"


# ---------------------------------------------------------------------------- 端到端


def _rows(by_id: dict[int, dict]) -> pd.DataFrame:
    rows = cn_data.main_rows()
    for r in rows:
        r.update(by_id.get(r["ID"], {}))
    return pd.DataFrame(rows)


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _deltas(events) -> list[str]:
    return [e.data["text"].strip() for e in events if e.type is EventType.DELTA]


def _narrative_calls(h) -> list[list[dict]]:
    return h.llm.routed(POINTS_MARK)


def _facts(call: list[dict]) -> dict:
    body = call[1]["content"]
    return json.loads(body.split("【事实】", 1)[1].split("\n【要点】", 1)[0])


async def _go(query: str, replies: list, *, main: pd.DataFrame | None = None, config: dict | None = None):
    h = make_harness(scopes.account_jia(), llm_replies=replies, config_files=config or {})
    cn_data.load(h, main=main)
    return h, await run(h, query)


def _invariants(h, events, notes: list[str]) -> None:
    """跨环节的规矩：开头那几句在结论之前、也交到写结论的模型手里；小标题不写「按要求」；只列了前几张时交给模型的
    事实分开两个张数。"""
    deltas = _deltas(events)
    first = deltas[0]
    for note in notes:
        assert note in first, f"开头没写：{note}"
    assert "按要求" not in _text(events)
    for call in _narrative_calls(h):
        body = call[1]["content"]
        assert "【本次查的是】" in body
        for note in notes:
            assert note in body, f"写结论的模型没拿到：{note}"
        facts = _facts(call)
        if "列出的张数" in facts:
            assert "符合条件的张数" in facts and "张数" not in facts


async def test_severe_list_says_the_reading_first_and_the_conclusion_names_the_levels():
    main = _rows({2: {"ProblemLevel": "A+"}, 3: {"ProblemLevel": "A"}})  # A+、A 共 3 张（1 号本来是 A）
    vague = "**国内问题单共 3 张**"  # 没点到 A+、A：打回重写一次
    named = "**国内 A+、A 级的问题单共 3 张**"
    h, events = await _go("国内问题比较严重的单", [
        plan(step(domains=CN, filters=[LEVELS_AA]), alternatives=["指不良率较高的单", "指停过线的单"]), vague, named],
        main=main)
    note = "「比较严重」按问题等级 A+、A 理解"
    _invariants(h, events, [note])
    deltas = _deltas(events)
    assert deltas[0] == note + "。"
    assert deltas[1].startswith(named)
    calls = _narrative_calls(h)
    assert len(calls) == 2 and "点到：A+、A" in calls[1][-1]["content"]
    assert "【本次查的是】国内；问题等级：A+、A；列出全部 3 张" in calls[0][1]["content"]
    assert "**国内问题单（3 张）**" in _text(events)
    buttons = next(e.data["recommendations"] for e in events if e.type is EventType.SUGGESTIONS)
    assert buttons[0]["query"] == "换个理解：指不良率较高的单"


async def test_severe_template_names_the_levels_when_only_one_or_two():
    h, events = await _go("国内问题比较严重的单", [plan(step(domains=CN, filters=[LEVELS_AA]))])
    _invariants(h, events, ["「比较严重」按问题等级 A+、A 理解"])
    assert _deltas(events)[1].startswith("国内问题等级为 A+、A 的单共 1 张")


async def test_high_rate_list_uses_the_default_count_and_does_not_call_it_the_total():
    main = _rows({2: {"Rate": 5.0}, 4: {"Rate": 3.0}})
    h, events = await _go("不良率特别高的国内单", [
        plan(step(domains=CN, sort=BY_RATE, limit=20), alternatives=["指不良率超过某个值的单"]),
        "**国内不良率最高的 2 张单都还没结案**"], main=main, config={"answer_params.toml": "top_n = 2"})
    note = "「不良率特别高」按不良率从高到低列出前 2 张（没说要几张，默认列 2 张）"
    _invariants(h, events, [note])
    text = _text(events)
    assert "**国内问题单（共 4 张，列出不良率最高的 2 张）**" in text
    table = next(e.data for e in events if e.type is EventType.TABLE)
    assert [r[0] for r in table["rows"]] == ["ZC9901002", "ZC9901004"]
    call = _narrative_calls(h)[0]
    assert "【本次查的是】国内；列出不良率最高的 2 张（符合条件的共 4 张）" in call[1]["content"]
    facts = _facts(call)
    assert facts["符合条件的张数"] == 4 and facts["列出的张数"] == 2


async def test_high_rate_template_keeps_the_two_counts_apart():
    """模型出错时的模板句：先说一共几张、列了哪几张，问题类型与未结案按列出的这几张说（不混两组数）。"""
    main = _rows({2: {"Rate": 5.0}, 4: {"Rate": 3.0}})
    h, events = await _go("不良率特别高的国内单", [plan(step(domains=CN, sort=BY_RATE, limit=20)),
                                                RuntimeError("模型出错")],
                          main=main, config={"answer_params.toml": "top_n = 2"})
    head = _deltas(events)[1]
    assert head.startswith("**国内共 4 张，列出不良率最高的 2 张，这些单里")


async def test_count_the_user_gave_is_kept_and_not_explained():
    main = _rows({2: {"Rate": 5.0}, 4: {"Rate": 3.0}})
    h, events = await _go("国内不良率最高的 3 张单", [plan(step(domains=CN, sort=BY_RATE, limit=3)),
                                                 "**国内不良率最高的 3 张单**"], main=main)
    _invariants(h, events, [])
    text = _text(events)
    assert "没说要几张" not in text and "**国内问题单（共 4 张，列出不良率最高的 3 张）**" in text


async def test_default_count_offers_show_all_and_clicking_runs_the_stored_plan():
    """G95：张数是程序定的、又只列了前几张时，答后给「看全部 N 张」（N 来自沙箱）；点了不重新规划，直接执行存下的
    计划：同样的条件与排法、去掉张数、全部导出。"""
    main = _rows({2: {"Rate": 5.0}, 4: {"Rate": 3.0}})
    h, events = await _go("国内不良率高的单有哪些", [plan(step(domains=CN, sort=BY_RATE)), "**国内不良率最高的 2 张**"],
                          main=main, config={"answer_params.toml": "top_n = 2"})
    buttons = next(e.data["recommendations"] for e in events if e.type is EventType.SUGGESTIONS)
    show_all = next(b for b in buttons if b["name"] == "看全部")
    assert buttons[0] is show_all and show_all["label"] == "看全部 4 张"
    assert show_all["query"] == "按不良率从高到低列出全部并导出"
    calls = len(h.llm.calls)
    again = await run(h, show_all["query"])
    assert not any(c for c in h.llm.calls[calls:] if "规划器" in str(c[0].get("content")))  # 没有重新规划
    table = next(e.data for e in again if e.type is EventType.TABLE)
    assert [r[0] for r in table["rows"]] == ["ZC9901002", "ZC9901004", "ZC9901001", "ZC9901003"]
    assert "没说要几张" not in _text(again) and h.files.saved  # 全部导出


async def test_no_show_all_when_the_user_gave_the_count():
    main = _rows({2: {"Rate": 5.0}, 4: {"Rate": 3.0}})
    _h, events = await _go("国内不良率最高的 2 张单", [plan(step(domains=CN, sort=BY_RATE, limit=2)),
                                                 "**国内不良率最高的 2 张**"], main=main)
    buttons = next((e.data["recommendations"] for e in events if e.type is EventType.SUGGESTIONS), [])
    assert not any(b["name"] == "看全部" for b in buttons)
