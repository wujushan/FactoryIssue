"""按多值维度分组、又按它或与它成对的维度筛：分组只列与筛选取值对应的（总述「统计口径说明」多值归属；决策
2026-11-06「按多值维度既筛又分组」及其补记）。

手动测试 2026-11-06「Q92 和 IM30 今年哪个问题最多？」：一张单登记了 Q92、Q60 两个机型，因 Q92 计入，表与图却另出
一行 Q60（1 张），与筛选条件（机型：Q92、IM30）、结论（只说 Q92、IM30）对不上。夹具里同样的形状：
- 国内 ZC9901003 登记 A920、A920PRO；ZC9901001 当前状态是「SQE跟进 测试甲 / IQC确认 测试乙」，ZC9901004 是
  「责任人确认 测试甲」；
- 巴西 BR9901001 的工厂是 CA、TT；BR9901002 登记 A920（A系列）、Q92（Q系列）；BR9901003 只有 Q92；
- 海外 HW9901001 的问题跟进人是测试甲、测试乙。
"""

from __future__ import annotations

import pandas as pd
from test_s3_execute import BR, MODEL_DOWN, OS, T30, _go, _tables, _text, plan, step

from factory_issue_module.present import caliber as cal
from factory_issue_module.stats.lib import custom, views

CN = {"value": ["国内"], "from": "user"}


def _eq(field: str, value: str) -> dict:
    return {"field": field, "op": "是", "value": value, "from": "user"}


def _counts(events) -> dict:
    return {r[0]: r[1] for r in _tables(events)[0]["rows"]}


# ---------------------------------------------------------------------------- 同一维度（G98）


async def test_machine_filter_and_group_lists_only_the_filtered_machines():
    """三域一起「A920 哪个问题最多」：表、图只有 A920 一行，不另出 A920PRO（国内）、Q92（巴西）；口径写明。"""
    reply = plan(step("aggregate", time=T30, filters=[_eq("机型", "A920")], group_by=["机型"], ranking=True))
    _h, events = await _go("近 30 天 A920 的问题有多少", [reply, MODEL_DOWN])
    table = _tables(events)[0]
    assert [r[0] for r in table["rows"]] == ["A920"]
    assert table["rows"][0][-1] == 5  # 国内 2 + 巴西 2 + 海外 1
    text = _text(events)
    assert "A920PRO" not in text and "Q92" not in text
    assert cal.only_filtered("机型", "机型", ["A920"]) in text


async def test_brazil_factory_filter_and_group_lists_only_the_filtered_factory():
    """巴西「TT 工厂」按加工厂统计：BR9901001（CA、TT）只在 TT 下计，不另出 CA。"""
    reply = plan(step("aggregate", domains=BR, time=T30, filters=[_eq("加工厂", "TT")], group_by=["加工厂"]))
    _h, events = await _go("近 30 天巴西 TT 工厂按加工厂统计", [reply, MODEL_DOWN])
    assert _counts(events) == {"TT": 2}


async def test_overseas_follower_filter_and_group_lists_only_the_filtered_person():
    """海外「测试甲跟进的单按跟进人统计」：HW9901001（测试甲、测试乙）只在测试甲下计（按 ID 筛、按姓名分组）。"""
    reply = plan(step("aggregate", domains=OS, time=T30, filters=[_eq("跟进人", "测试甲")], group_by=["跟进人"]))
    _h, events = await _go("近 30 天海外测试甲跟进的单按跟进人统计", [reply, MODEL_DOWN])
    assert list(_counts(events)) == ["测试甲"]


async def test_group_without_filter_still_counts_every_value():
    """不按机型筛时照旧：一单在它的每个机型下各计一次（巴西 A920 2、Q92 2）。"""
    reply = plan(step("aggregate", domains=BR, time=T30, group_by=["机型"]))
    _h, events = await _go("近 30 天巴西按机型统计", [reply, MODEL_DOWN])
    got = _counts(events)
    assert got["A920"] == 2 and got["Q92"] == 2
    assert "单上同时登记的其他" not in _text(events)


# ---------------------------------------------------------------------------- 成对的另一维度（G99）


async def test_series_filter_and_group_by_machine_lists_only_machines_of_the_series():
    """巴西「A 系列哪个机型问题最多」：BR9901002（A920、Q92）只在 A920 下计，不另出 Q92。"""
    reply = plan(step("aggregate", domains=BR, time=T30, filters=[_eq("系列", "A系列")], group_by=["机型"],
                      ranking=True))
    _h, events = await _go("近 30 天巴西 A 系列哪个机型问题最多", [reply, MODEL_DOWN])
    assert _counts(events) == {"A920": 2}
    assert cal.only_filtered("机型", "系列", ["A系列"], same=False) in _text(events)


async def test_machine_filter_and_group_by_series_lists_only_the_series_of_the_machine():
    """巴西「Q92 按系列统计」：BR9901002（A系列的 A920、Q系列的 Q92）只在 Q系列下计，不另出 A系列。"""
    reply = plan(step("aggregate", domains=BR, time=T30, filters=[_eq("机型", "Q92")], group_by=["系列"]))
    _h, events = await _go("近 30 天巴西 Q92 按系列统计", [reply, MODEL_DOWN])
    assert _counts(events) == {"Q系列": 2}


async def test_person_filter_and_group_by_stage_counts_only_the_persons_stages():
    """国内「测试甲手上的单都卡在哪个环节」：ZC9901001 的 IQC确认 是测试乙在处理，不计。"""
    reply = plan(step("aggregate", domains=CN, time=T30, filters=[_eq("当前责任人", "测试甲")],
                      group_by=["处理环节"]))
    _h, events = await _go("近 30 天测试甲手上的单都卡在哪个环节", [reply, MODEL_DOWN])
    assert _counts(events) == {"SQE跟进": 1, "责任人确认": 1}
    text = _text(events)
    assert "IQC确认" not in text
    assert cal.only_filtered("处理环节", "当前责任人", ["测试甲"], same=False) in text


async def test_stage_filter_and_group_by_person_counts_only_people_on_that_stage():
    """国内「SQE跟进环节的单各人手上多少」：ZC9901001 上的测试乙在 IQC确认 那一行，不计。"""
    reply = plan(step("aggregate", domains=CN, time=T30, filters=[_eq("状态", "SQE跟进")], group_by=["当前责任人"]))
    _h, events = await _go("近 30 天 SQE跟进 环节的单各人手上多少", [reply, MODEL_DOWN])
    assert _counts(events) == {"测试甲": 1}


# ---------------------------------------------------------------------------- 沙箱函数


def test_keep_ignores_negated_and_unlabelled_conditions_and_reads_stage_status():
    conds = [{"kind": "any_of", "col": "_machines", "values": ["Q92"], "neg": False, "label": "机型"},
             {"kind": "any_of", "col": "_machines", "values": ["IM30"], "neg": False, "label": "机型"},
             {"kind": "any_of", "col": "_series", "values": ["A系列"], "neg": True, "label": "系列"},
             {"kind": "any_of", "col": "_inv_codes", "values": ["X"], "neg": False},
             {"kind": "any_of", "col": "_current_ids", "values": [11], "neg": False,
              "group_col": "_current_names", "group_values": ["测试甲"], "label": "当前责任人"},
             {"kind": "status", "items": [["环节", "SQE跟进"]], "neg": False, "label": "处理环节"},
             {"kind": "status", "items": [["环节", "IQC确认"], ["未结案", None]], "neg": False, "label": "处理环节"}]
    assert views.vw_keep(conds) == [
        {"label": "机型", "show": ["Q92", "IM30"], "cols": {"_machines": ["Q92", "IM30"]}},
        {"label": "当前责任人", "show": ["测试甲"], "cols": {"_current_ids": [11], "_current_names": ["测试甲"]}},
        {"label": "处理环节", "show": ["SQE跟进"], "cols": {"_stages": ["SQE跟进"]}},
    ]


def test_same_column_falls_back_when_no_value_matches():
    """按同一列筛、人员姓名写法与主数据不同、一个都对不上时，这张单照原样计，不掉出分组。"""
    view = pd.DataFrame([{"_id": 1, "_names": ["测试甲", "测试乙"]}, {"_id": 2, "_names": ["测试丁"]}])
    keep = [{"label": "人", "show": ["测试甲"], "cols": {"_names": ["测试甲", "测试丙"]}}]
    groups = views.vw_group(view, {"col": "_names", "multi": True, "keep": keep})
    assert {k: sorted(v) for k, v in groups.items()} == {"测试甲": [1], "测试丁": [2]}


def test_paired_restriction_intersects_and_may_leave_nothing():
    """几项条件都有关时取交集；经成对列限定、那一行上没有人时，这张单没有可计入的当前责任人（不照原样）。"""
    view = pd.DataFrame([
        {"_id": 1, "_stages": ["SQE跟进", "IQC确认"], "_current_ids": [11, 12], "_current_names": ["测试甲", "测试乙"],
         "_state_pairs": [["SQE跟进", [11], ["测试甲"]], ["IQC确认", [12], ["测试乙"]]]},
        {"_id": 2, "_stages": ["SQE跟进", "IQC确认"], "_current_ids": [12], "_current_names": ["测试乙"],
         "_state_pairs": [["SQE跟进", [], []], ["IQC确认", [12], ["测试乙"]]]},
    ])
    by_stage = [{"label": "处理环节", "show": ["SQE跟进"], "cols": {"_stages": ["SQE跟进"]}}]
    dims = views.vw_restrict([{"col": "_current_names", "multi": True, "title": "当前责任人"}], by_stage)
    assert dims[0]["only_by"] == [["处理环节", ["SQE跟进"], False]]
    assert {k: sorted(v) for k, v in views.vw_group(view, dims[0]).items()} == {"测试甲": [1]}
    by_person = [{"label": "当前责任人", "show": ["测试乙"], "cols": {"_current_ids": [12]}}]
    both = views.vw_restrict([{"col": "_stages", "multi": True}], by_stage + by_person)[0]
    assert {k: sorted(v) for k, v in views.vw_group(view, both).items()} == {}  # SQE跟进 一行上都没有测试乙
    only_person = views.vw_restrict([{"col": "_stages", "multi": True}], by_person)[0]
    assert {k: sorted(v) for k, v in views.vw_group(view, only_person).items()} == {"IQC确认": [1, 2]}


def test_split_multi_follows_the_per_issue_keep_in_custom_stats():
    """临时统计的 `拆多值`：按第一次调用给出的各单取值拆（只记与原值不同的单）；没有所属域、问题编号两列时照原样。"""
    df = pd.DataFrame({"所属域": ["国内", "国内", "巴西"], "问题编号": ["ZC1", "ZC2", "BR1"],
                       "机型": ["Q92、Q60", "IM30", "Q60、Q92"]})
    custom.CS_NAMES.update({"domain": "所属域", "number": "问题编号"})
    custom.CS_KEEP.clear()
    custom.CS_KEEP.update({"机型": {"国内|ZC1": ["Q92"], "巴西|BR1": ["Q92"]}})
    try:
        got = custom.拆多值(df, "机型")["机型"].tolist()
        plain = custom.拆多值(df[["机型"]], "机型")["机型"].tolist()
    finally:
        custom.CS_KEEP.clear()
    assert got == ["Q92", "IM30", "Q92"]
    assert plain == ["Q92", "Q60", "IM30", "Q60", "Q92"]


def test_custom_frame_records_only_issues_whose_values_change():
    """临时统计第一次调用：按系列筛时记下 BR9901002 只计 A920；单上的机型都在筛选范围内的单不记。"""
    from factory_issue_module.stats.tasks import custom_frame

    v = pd.DataFrame([
        {"_number": "BR1", "_machines": ["A920"], "_machine_pairs": [["A920", "A系列"]]},
        {"_number": "BR2", "_machines": ["A920", "Q92"], "_machine_pairs": [["A920", "A系列"], ["Q92", "Q系列"]]},
    ])
    conds = [{"kind": "any_of", "col": "_series", "values": ["A系列"], "neg": False, "label": "系列"}]
    cols = [{"name": "机型", "kind": "multi", "src": {"巴西": "_machines"}},
            {"name": "问题编号", "kind": "text", "src": {"巴西": "number"}}]
    out = {}
    custom_frame.cf_keep(v, "巴西", conds, cols, out)
    assert out == {"机型": {"巴西|BR2": ["A920"]}}
