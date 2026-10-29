"""国内派生（设计 §15 夹具 J-D04、J-D05、J-D06、J-P12 的派生一半）：直接 import `stats/lib` 测。"""

from __future__ import annotations

import pandas as pd

from factory_issue_module import landed
from factory_issue_module.domains import domestic, enums
from factory_issue_module.stats.lib import common, derive_domestic, views

E = derive_domestic.cn_enums(domestic.enum_params())
EMP = pd.DataFrame([{"ID": 11, "Name": "测试甲"}, {"ID": 12, "Name": "测试乙"}, {"ID": 13, "Name": "测试丙"}])


def _main(**rows: dict) -> pd.DataFrame:
    base = {"ProblemType": 1, "MemberList": "11", "MemberListName": "测试甲", "IQCStatus": None,
            "IQCMemberList": None, "IQCMemberListName": None}
    return pd.DataFrame([{**base, "ID": int(k[1:]), **v} for k, v in rows.items()])


def test_jd04_iqc_segment_is_its_own_row_and_counts_once_per_stage():
    """J-D04：IQC 段单独一行，与主状态同名也不合并；IQC 成员算当前责任人；同名两行在该环节下只计一次。"""
    main = _main(i1={"Status": 8, "IQCStatus": 6, "IQCMemberList": "12", "IQCMemberListName": "测试乙"},
                 i2={"Status": 6, "IQCStatus": 6, "IQCMemberList": "13", "IQCMemberListName": "测试丙"})
    states = derive_domestic.cn_states(main, None, None, EMP, E)
    assert states[1] == [("SQE跟进", ["测试甲"], [11]), ("IQC确认", ["测试乙"], [12])]
    assert [s for s, _p, _i in states[2]] == ["IQC确认", "IQC确认"]
    assert derive_domestic.cn_state_text(states[1]) == "SQE跟进 测试甲；IQC确认 测试乙"
    view = pd.DataFrame([{"_id": pid, "_stages": common.fi_unique([s for s, _p, _i in rows])}
                         for pid, rows in states.items()])
    groups = views.vw_group(view, {"col": "_stages", "multi": True})
    assert {k: len(v) for k, v in groups.items()} == {"SQE跟进": 1, "IQC确认": 2}
    hit = views.vw_filter(view.assign(_done=False, _stopped_now=False, _stopped_ever=False, _restarted=False,
                                      _stop_code=None),
                          [{"kind": "status", "items": [["环节", "IQC确认"]]}])
    assert sorted(hit["_id"]) == [1, 2]


def test_jd05_risk_segment_one_row_earliest_step_people_deduped():
    """J-D05：退货 / 退库段只占一行，步骤取进行中记录里最早的一条，人员按员工 ID 去重，已完成的不显示。"""
    main = _main(i1={"Status": 7})
    risk = pd.DataFrame([
        {"ID": 5, "ProblemId": 1, "Step": 14, "Status": 1, "UserID": 12},
        {"ID": 3, "ProblemId": 1, "Step": 15, "Status": 1, "UserID": 13},
        {"ID": 4, "ProblemId": 1, "Step": 15, "Status": 1, "UserID": 13},
        {"ID": 1, "ProblemId": 1, "Step": 14, "Status": 2, "UserID": 11},
    ])
    rows = derive_domestic.cn_states(main, None, risk, EMP, E)[1]
    assert rows == [("填写退货单号", ["测试甲"], [11]), ("填写退库信息", ["测试丙", "测试乙"], [13, 12])]
    assert "填写退货单号" != "填写退货信息" and {"填写退货信息", "填写退货单号"} <= set(enums.CN_STAGES)


def test_jd06_responsible_uses_old_type_after_reclassify():
    """J-D06：结案后改过问题分类，按改之前的类型取（硬件问题取责任人确认的操作人），不按现类型取 SQE跟进。"""
    row = {"ID": 1, "ProblemType": 3, "OldProblemType": 1, "Status": 32}
    steps = [{"ID": 1, "Step": 3, "StepStr": "责任人确认", "AddUser": 11, "AddDate": pd.Timestamp("2099-01-01")},
             {"ID": 2, "Step": 10, "StepStr": "SQE跟进", "AddUser": 12, "AddDate": pd.Timestamp("2099-01-02")},
             {"ID": 3, "Step": 31, "StepStr": "结案确认", "AddUser": 13, "AddDate": pd.Timestamp("2099-01-03")},
             {"ID": 4, "Step": None, "StepStr": "修改问题分类", "AddUser": 13, "AddDate": pd.Timestamp("2099-01-04")}]
    assert derive_domestic.cn_responsible(row, steps, E) == 11
    assert derive_domestic.cn_responsible(row, steps[:3], E) == 12  # 没改过分类：物料问题取 SQE跟进
    late = [*steps[:1], {**steps[0], "ID": 9, "AddUser": 13, "AddDate": pd.Timestamp("2099-01-05")}]
    assert derive_domestic.cn_responsible({**row, "ProblemType": 1}, late, E) == 13  # 最新一条按时间


def test_jp12_parallel_state_ignores_other_task_tables():
    """J-P12 派生一半：别的业务表名的已接受待办（如停线重启类）不影响现算状态；只认「已接受」。"""
    main = _main(i3={"Status": 30, "ProblemType": 1})
    tasks = pd.DataFrame([
        {"frecID": "3", "ftable": enums.CN_TASK_PREVENTION, "fuserID": "12", "fstat": "已接受"},
        {"frecID": "3", "ftable": "ZCTracking_ProblemRestart", "fuserID": "13", "fstat": "已接受"},
        {"frecID": "3", "ftable": enums.CN_TASK_EFFECT, "fuserID": "11", "fstat": "已完成"},
    ])
    assert derive_domestic.cn_states(main, tasks, None, EMP, E)[3] == [("预防对策确认", ["测试乙"], [12])]
    both = pd.concat([tasks, pd.DataFrame([{"frecID": "3", "ftable": enums.CN_TASK_EFFECT, "fuserID": "11",
                                            "fstat": "已接受"}])])
    rows = derive_domestic.cn_states(main, both, None, EMP, E)[3]
    assert [s for s, _p, _i in rows] == ["预防对策确认", "效果确认"]
    factory = _main(i3={"Status": 30, "ProblemType": 5})  # 工厂制程不做预防对策确认，保持库里原状态
    assert [s for s, _p, _i in derive_domestic.cn_states(factory, tasks, None, EMP, E)[3]] == ["效果确认"]


def test_done_issue_is_only_done():
    rows = derive_domestic.cn_states(_main(i1={"Status": 32, "IQCStatus": 6}), None, None, EMP, E)[1]
    assert rows == [("已完成", [], [])]


def test_close_time_and_restart_date():
    steps = [{"ID": 1, "Step": 31, "AddDate": pd.Timestamp("2099-02-01 08:00")},
             {"ID": 2, "Step": 31, "AddDate": pd.Timestamp("2099-02-03 09:00")},
             {"ID": 3, "Step": 29, "Result": "2099-02-10", "AddDate": pd.Timestamp("2099-02-11")}]
    assert derive_domestic.cn_close_time({"Status": 32}, steps, E) == pd.Timestamp("2099-02-03 09:00")
    assert derive_domestic.cn_close_time({"Status": 31}, steps, E) is None
    assert derive_domestic.cn_restart_date(steps, E) == pd.Timestamp("2099-02-10")


def test_rank_keeps_ties_at_the_edge_and_counts_lists():
    rows, first, tied = common.fi_rank([("A", 3), ("B", 2), ("C", 2), ("D", 1)], 2)
    assert rows == [("A", 3), ("B", 2), ("C", 2)] and first == ["A"] and tied == ["B", "C"]
    assert common.fi_with_counts({"按机型": [["A", 3], ["B", 2]], "x": {"y": [1]}}) == {
        "按机型": [["A", 3], ["B", 2]], "按机型（项数）": 2, "x": {"y": [1], "y（项数）": 1}}


def test_enum_texts_appear_in_table_docs():
    """§9.1：枚举对照的每个显示文字都出现在对应的表文件里。"""
    main = landed.read(landed.table_docs()["CoreINFO.dbo.ZCTracking_ProblemList"].file)
    for table in (enums.CN_PROBLEM_TYPES, enums.CN_STATUS, enums.CN_STOP_STATUS, enums.CN_OUTPUT_STATUS,
                  enums.CN_DESIGN_RESULT, enums.CN_IQC_OPINION):
        for code, text in table.items():
            assert f"{code}={text}" in main or f"| {code} | {text} |" in main, text
    risk = landed.read(landed.table_docs()["CoreINFO.dbo.ZCTracking_RiskStream"].file)
    assert all(f"{k}={v}" in risk for k, v in enums.CN_RISK_STEPS.items())


def test_problem_types_matrix_parses():
    types = landed.problem_types()
    assert types["硬件问题"] == ("国内", "巴西", "海外") and types["其他"] == ("巴西", "海外")
    assert set(enums.CN_PROBLEM_TYPES.values()) == {t for t, ds in types.items() if "国内" in ds}
