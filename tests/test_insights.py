"""结论里的要点与需关注的单（总述「结论里的要点与需关注的单」，决策 2026-11-03「结论的要点与需关注的单」）。

沙箱公共库 `stats/lib/insights.py` 直接 import 测（运行时拼进沙箱，§1.4）；`present/insights.py` 的模板句、需关注
一段与跳过的项；`narrative.write_points` 的逐条核与模板句退路。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fakes import FakeLLM

from factory_issue_module.config import files
from factory_issue_module.present import insights, narrative
from factory_issue_module.stats.lib.insights import in_insights

TODAY = "2026-11-03"
Q = {"today": TODAY, "share": 40, "repeat": 3, "months": 3, "close_min": 5, "points": 4, "focus": 3, "skip": []}
TRAITS = {"国内": {"rate": "number"}, "巴西": {"rate": "number"}, "海外": {"rate": "text"}}


def _row(i: int, *, type_: str = "硬件问题", add: str = "2026-10-01", unclosed: bool = True, stopped: bool = False,
         level: str = "B", machines=("A920",), factory: str = "柯洱斯", ven: str = "未填", stages=("SQE跟进",),
         close_days=None, rate=None) -> dict:
    return {"_id": i, "_number": f"ZC99{i:05d}", "type": type_, "_add": pd.Timestamp(add), "_unclosed": unclosed,
            "_done": not unclosed, "_stopped_now": stopped, "level": level, "_machines": list(machines),
            "factory": factory, "ven_name": ven, "_stages": list(stages) if unclosed else ["已完成"],
            "_close_days": close_days, "_rate_value": rate, "rate": "未填" if rate is None else f"{rate:g}%"}


def _view(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _kinds(got: dict) -> list[str]:
    return [p["发现"] for p in got["points"]]


def test_few_issues_give_nothing():
    got = in_insights([("国内", _view([_row(1), _row(2)]))], Q, {}, TRAITS)
    assert got == {"points": [], "focus": []}


def test_concentrate_needs_the_share_and_names_the_runner_up():
    rows = [_row(1), _row(2), _row(3, type_="软件问题"), _row(4, type_="物料问题")]
    got = in_insights([("国内", _view(rows))], Q, {}, TRAITS)
    point = got["points"][0]
    assert point["发现"] == "集中" and point["最多的问题类型"] == [["硬件问题", 2]] and point["占比（%）"] == 50.0
    assert point["其次"] == [["物料问题", 1], ["软件问题", 1]]
    assert "集中" not in _kinds(in_insights([("国内", _view(rows))], {**Q, "share": 60}, {}, TRAITS))
    assert "集中" not in _kinds(in_insights([("国内", _view(rows))], {**Q, "skip": ["集中"]}, {}, TRAITS))


def test_backlog_stage_age_bins_and_oldest():
    rows = [_row(1, add="2026-10-20"), _row(2, add="2026-07-01", stages=("IQC确认",)),
            _row(3, add="2026-01-01", unclosed=False), _row(4, add="2026-09-01")]
    point = next(p for p in in_insights([("国内", _view(rows))], Q, {}, TRAITS)["points"] if p["发现"] == "积压")
    assert point["未结案"] == 3
    assert point["各域未结案最多停在的环节"] == [{"域": "国内", "最多停在的环节": ["SQE跟进"], "张数": 2, "该域未结案": 3}]
    assert point["未结案建单天数分档"] == [["30 天及以内", 1], ["31–90 天", 1], ["91 天及以上", 1]]
    assert point["建单最久的未结案单"] == {"域": "国内", "问题编号": "ZC9900002", "建单天数": 125}
    spread = [_row(i, stages=(s,)) for i, s in enumerate(("IQC确认", "SQE跟进", "责任人确认"), start=1)]
    point = next(p for p in in_insights([("国内", _view(spread))], Q, {}, TRAITS)["points"] if p["发现"] == "积压")
    assert "各域未结案最多停在的环节" not in point  # 各环节各 1 张：说不出积压在哪


def test_severe_counts_levels_and_notes_domestic_issues_without_levels():
    rows = [_row(1, level="A"), _row(2, level="A+", stopped=True), _row(3, add="2024-01-05", level="未填")]
    point = next(p for p in in_insights([("国内", _view(rows))], Q, {}, TRAITS)["points"] if p["发现"] == "严重")
    assert point["A+ 级"] == 1 and point["A 级"] == 1 and point["停线中"] == 1
    assert point["国内 2024-04-17 之前建的单（没有问题等级）"] == 1
    skipped = in_insights([("国内", _view(rows))], {**Q, "skip": ["等级"]}, {}, TRAITS)
    assert next(p for p in skipped["points"] if p["发现"] == "严重") == {"发现": "严重", "名称": "严重程度", "停线中": 1}


def test_repeat_needs_the_minimum_and_skips_blind_columns():
    rows = [_row(i, machines=("A8700",) if i < 4 else ("Q92",), factory="柯洱斯" if i < 3 else "亮亮") for i in range(1, 6)]
    point = next(p for p in in_insights([("国内", _view(rows))], Q, {}, TRAITS)["points"] if p["发现"] == "重复")
    assert point["机型"] == [["A8700", 3]] and point["加工厂"] == [["亮亮", 3]] and "供应商" not in point
    blind = in_insights([("国内", _view(rows))], Q, {"国内": ["_machines", "factory"]}, TRAITS)
    assert "重复" not in _kinds(blind)
    assert "重复" not in _kinds(in_insights([("国内", _view(rows))], {**Q, "repeat": 4}, {}, TRAITS))


def test_months_need_the_span_and_a_clear_peak():
    rows = [_row(1, add="2026-01-10"), _row(2, add="2026-03-02"), _row(3, add="2026-03-20"), _row(4, add="2026-05-01")]
    point = next(p for p in in_insights([("国内", _view(rows))], Q, {}, TRAITS)["points"] if p["发现"] == "时间")
    assert point["跨几个月"] == 5 and point["建单最多的月份"] == [["2026-03", 2]]
    flat = [_row(i, add=f"2026-0{i}-01") for i in range(1, 6)]  # 5 个月各 1 张：说不出哪个月最多
    assert "时间" not in _kinds(in_insights([("国内", _view(flat))], {**Q, "points": 6}, {}, TRAITS))


def test_close_cycle_per_domain_needs_enough_closed_issues():
    rows = [_row(i, unclosed=False, close_days=d) for i, d in enumerate([3, 5, 8, 10, 30], start=1)]
    got = in_insights([("国内", _view(rows))], {**Q, "points": 6}, {}, TRAITS)
    point = next(p for p in got["points"] if p["发现"] == "时效")
    assert point["各域已结案的单"] == [{"域": "国内", "结案周期中位数（天）": 8.0, "计入张数": 5}]
    assert "时效" not in _kinds(in_insights([("国内", _view(rows))], {**Q, "close_min": 6, "points": 6}, {}, TRAITS))


def test_points_follow_the_table_order_and_the_limit():
    rows = [_row(i, level="A", stopped=i == 1) for i in range(1, 5)]
    got = in_insights([("国内", _view(rows))], {**Q, "points": 2}, {}, TRAITS)
    assert _kinds(got) == ["集中", "积压"]


def test_focus_tiers_and_overseas_rate_does_not_compete():
    cn = [_row(1, add="2026-10-01"), _row(2, add="2026-09-01", level="A"), _row(3, add="2026-10-15", stopped=True),
          _row(4, unclosed=False, rate=12.5)]
    os_ = [{**_row(9, unclosed=False, rate=99.0), "_number": "HW9900009"}]
    got = in_insights([("国内", _view(cn)), ("海外", _view(os_))], Q, {}, TRAITS)
    assert [(f["问题编号"], f["理由"]) for f in got["focus"]] == [
        ("ZC9900003", "停线中"), ("ZC9900002", "A 级，未结案"), ("ZC9900001", "未结案 33 天")]
    closed = [_row(i, unclosed=False, rate=r) for i, r in ((1, 2.0), (2, 12.5), (3, None))]
    got = in_insights([("国内", _view(closed)), ("海外", _view(os_))], Q, {}, TRAITS)
    assert [(f["问题编号"], f["理由"]) for f in got["focus"]] == [("ZC9900002", "不良率 12.5%"),
                                                                ("ZC9900001", "不良率 2%")]
    nothing = [_row(i, unclosed=False) for i in (1, 2, 3)]
    assert in_insights([("国内", _view(nothing))], Q, {}, TRAITS)["focus"] == []


def test_skips_follow_the_users_filters_and_groups():
    step = {"params": {"filters": [{"field": "问题类型", "op": "是", "value": "硬件问题"},
                                   {"field": "机型", "op": "不是", "value": "A920"},
                                   {"field": "状态", "op": "是", "value": "停线中"}],
                       "group_by": ["月"], "metrics": ["结案周期"]}}
    assert insights.skips(step) == ["停线", "时效", "时间", "集中"]
    answer = files.answer_params_from({})
    got = insights.params(step, answer, date(2026, 11, 3))
    assert got["today"] == TODAY and got["share"] == 40 and got["points"] == 4 and got["focus"] == 3


def test_point_templates_and_focus_block():
    point = {"发现": "集中", "名称": "问题类型", "最多的问题类型": [["物料问题", 7]], "占比（%）": 53.8,
             "其次": [["制程优化", 2]]}
    assert insights.point_text(point) == "- **问题类型**：最多的是物料问题（7 张），占 53.8%；其次是制程优化（2 张）"
    focus = [{"域": "国内", "问题编号": "ZC9900003", "理由": "停线中", "id": 3},
             {"域": "国内", "问题编号": "ZC9900001", "理由": "未结案 33 天", "id": 1}]
    block = insights.focus_block(focus, {("国内", 3): "A920 触摸屏失灵", ("国内", 1): "新建不久，稍后可见"}, None)
    assert block == "**需关注**\n\n- ZC9900003（停线中）：A920 触摸屏失灵\n- ZC9900001（未结案 33 天）"
    assert insights.assemble("**共 4 张。**", ["- **积压**：未结案 3 张"], block).startswith(
        "**共 4 张。**\n\n- **积压**：未结案 3 张\n\n**需关注**")


POINTS = [{"发现": "集中", "名称": "问题类型", "最多的问题类型": [["物料问题", 7]], "占比（%）": 53.8},
          {"发现": "积压", "名称": "积压", "未结案": 8}]
FACTS = {"时间范围": "2026 年", "合计张数": 13}


async def test_write_points_keeps_good_bullets_and_templates_bad_ones():
    llm = FakeLLM(["**2026 年共 13 张，8 张未结案。**\n- 问题类型：物料问题最多，7 张，占 53.8%\n- 积压：未结案 9 张"])
    head, bullets = await narrative.write_points(llm, "26 年的问题", None, None, FACTS, POINTS, {}, "共 13 张。")
    assert head == "**2026 年共 13 张，8 张未结案。**"
    assert bullets == ["- **问题类型**：物料问题最多，7 张，占 53.8%", insights.point_text(POINTS[1])]
    assert llm.calls[0][0]["content"] == narrative.POINTS_SYSTEM and "【要点】" in llm.calls[0][1]["content"]


async def test_write_points_count_mismatch_uses_templates_and_bad_head_falls_back():
    llm = FakeLLM(["2026 年共 99 张。\n- 物料问题最多", "2026 年共 98 张。"])
    head, bullets = await narrative.write_points(llm, "26 年的问题", None, None, FACTS, POINTS, {}, "共 13 张。")
    assert head == "**共 13 张。**" and bullets == [insights.point_text(p) for p in POINTS]
    assert "99" in llm.calls[1][-1]["content"]


async def test_write_points_without_model_and_with_must():
    head, bullets = await narrative.write_points(None, "q", None, None, FACTS, POINTS, {}, "共 13 张。")
    assert head == "**共 13 张。**" and len(bullets) == 2
    llm = FakeLLM(["**共 13 张。**", "**共 13 张，物料问题最多。**"])
    head, _b = await narrative.write_points(llm, "q", None, None, FACTS, [], {}, "模板。", must=["物料问题"])
    assert head == "**共 13 张，物料问题最多。**" and "要点名最多的：物料问题" in llm.calls[1][-1]["content"]
