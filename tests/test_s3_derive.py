"""巴西、海外派生（设计 §15 夹具 J-D10、J-D11；§6.2、§9.1）：直接 import `stats/lib` 测。"""

from __future__ import annotations

import pandas as pd

from factory_issue_module import landed
from factory_issue_module.domains import brazil, enums, overseas
from factory_issue_module.stats.lib import common, derive_brazil, derive_overseas

E_OS = derive_overseas.os_enums(overseas.enum_params())
E_BR = derive_brazil.br_enums(brazil.enum_params())


def _step(i: int, name: str) -> dict:
    return {"Id": i, "StepStr": name, "AddDate": pd.Timestamp("2099-01-01") + pd.Timedelta(days=i)}


def test_jd10_rejected_and_not_resubmitted_block_gives_nothing_old():
    """J-D10：当前状态为责任人确认、最近一次驳回之后责任人确认还没有新记录 → 这一块连同主表原因、措施、对策都不给
    驳回前的内容，答「该环节已退回重新处理」。"""
    row = {"Status": 2, "ProblemType": 1}
    steps = [_step(1, "填写问题"), _step(2, "指定责任人"), _step(3, "责任人确认"), _step(4, "驳回")]
    blocks = derive_overseas.os_blocks(row, steps, E_OS)
    assert [b["stage"] for b in blocks] == ["指定责任人", "责任人确认"]
    confirm = blocks[1]
    assert confirm["returned"] and confirm["step"] is None and confirm["main"] == []
    assert blocks[0]["step"]["Id"] == 2 and not blocks[0]["returned"]
    # 重新提交之后：这一块只给最新一条，主表各项照给
    again = derive_overseas.os_blocks(row, [*steps, _step(5, "责任人确认")], E_OS)[1]
    assert not again["returned"] and again["step"]["Id"] == 5 and "Reason" in again["main"]


def test_jd10_status_iqc_maps_to_its_step_name():
    """当前状态「IQC意见」对环节「IQC填写意见」（C32，`domains/enums.py`）。"""
    row = {"Status": 4}
    steps = [_step(1, "指定责任人"), _step(2, "责任人确认"), _step(3, "IQC填写意见"), _step(4, "驳回")]
    blocks = derive_overseas.os_blocks(row, steps, E_OS)
    assert [b["returned"] for b in blocks] == [False, False, True]


def test_jd11_structure_problem_blocks_follow_walked_steps():
    """J-D11：结构问题（目前没有这类单）按单上走过的环节逐块给，不按现有类型的区块表套。"""
    row = {"Status": 30, "ProblemType": 6}
    steps = [_step(1, "填写问题"), _step(2, "指定责任人"), _step(3, "任务转移"), _step(4, "责任人确认"),
             _step(5, "效果确认")]
    blocks = derive_overseas.os_blocks(row, steps, E_OS)
    assert [b["stage"] for b in blocks] == ["指定责任人", "责任人确认", "效果确认"]
    assert all(not b["returned"] for b in blocks)
    assert blocks[2]["main"] == ["Confirmation"]


def test_overseas_close_time_only_for_done_and_latest():
    steps = [_step(3, "结案确认"), _step(7, "结案确认"), _step(9, "效果确认")]
    assert derive_overseas.os_close_time({"Status": 32}, steps, E_OS) == steps[1]["AddDate"]
    assert derive_overseas.os_close_time({"Status": 31}, steps, E_OS) is None
    assert derive_overseas.os_close_time({"Status": 32}, [steps[2]], E_OS) is None  # 已完成却没有结案确认：定不出


def test_overseas_rate_value_for_comparison_only():
    assert derive_overseas.os_rate_value("30%") == 30.0
    assert abs(derive_overseas.os_rate_value("6.6667‰") - 0.66667) < 1e-9
    assert derive_overseas.os_rate_value("") is None and derive_overseas.os_rate_value("约 3%") is None


def test_brazil_type_rate_and_latest_process():
    assert derive_brazil.br_type("其他|包装破损") == ("其他", "包装破损")
    assert derive_brazil.br_type("其他") == ("其他", "未填") and derive_brazil.br_type("") == ("未填", "未填")
    assert derive_brazil.br_type("物料问题") == ("物料问题", "未填")
    assert derive_brazil.br_rate(5, 100) == (5.0, "5.00%")
    assert derive_brazil.br_rate(46.4, 100) == (46.4, "46.40%")
    assert derive_brazil.br_rate(0, 0) == (0.0, "0.00%") and derive_brazil.br_rate(3, None) == (None, "未填")
    assert derive_brazil.br_latest([{"ID": 2}, {"ID": 9}, {"ID": 5}])["ID"] == 9


def test_text_dates_and_json_lists():
    """`dirty_data.md`「文本存日期」只认 YYYY-MM-DD；JSON 列解析不了按空数组，巴西现象的非法转义先容错。"""
    assert common.fi_text_date("2099-03-04") == pd.Timestamp(2099, 3, 4)
    assert common.fi_text_date("2099/03/04") is None and common.fi_text_date("") is None
    assert common.fi_text_date("2099-02-30") is None
    assert common.fi_json_list('[{"Key": 1, "Value": "花屏"}]') == [{"Key": 1, "Value": "花屏"}]
    assert common.fi_json_list('[{"Key": -1, "Value": "C:\\temp 花屏"}]')[0]["Key"] == -1
    assert common.fi_json_list("不是 JSON") == [] and common.fi_json_list(None) == []


def test_status_words_per_domain():
    assert enums.status_kind("草稿", enums.BR_STAGES) == ("环节", "待提交")
    assert enums.status_kind("已终止", enums.BR_STAGES) == ("环节", "已终止")
    assert enums.status_kind("未结案", enums.BR_STAGES) == ("未结案", "")
    assert enums.status_kind("IQC填写意见", enums.OS_STAGES) == ("环节", "IQC意见")
    assert enums.status_kind("待提交") is None  # 国内没有这个状态
    assert enums.status_kind("重启审核中", enums.OS_STAGES)[0] in enums.CN_ONLY_KINDS


def test_enum_texts_appear_in_table_docs():
    """§9.1：巴西、海外枚举对照的每个显示文字都出现在对应的表文件里。"""
    br = landed.read(landed.table_docs()["CoreINFO.dbo.BrazilProblemList"].file)
    for code, text in enums.BR_STATUS.items():
        assert f"| {code} | {text} |" in br, text
    assert all(t in br for t in enums.BR_PROBLEM_TYPES)
    assert all(f"{k}={v}" in br for k, v in enums.BR_YES_NO.items())
    assert enums.BR_RESTARTED in br
    os_ = landed.read(landed.table_docs()["CoreINFO.dbo.OverseasProblemDetail"].file)
    for table in (enums.OS_PROBLEM_TYPES, enums.OS_STOP_STATE, enums.OS_IQC_OPINION, enums.OS_DESIGN_RESULT):
        assert all(f"{k}={v}" in os_ for k, v in table.items())
    for code, text in enums.OS_STATUS.items():
        assert f"| {code} | {text} |" in os_, text
    steps = landed.read(landed.table_docs()["CoreINFO.dbo.OverseasProblem_StepLog"].file)
    assert all(s in steps for s in ("结案确认", "驳回", "IQC填写意见", "任务转移", "填写问题", "修改问题"))
    assert enums.OS_UNKNOWN_TYPE in os_


def test_problem_types_match_cross_domain_matrix():
    types = landed.problem_types()
    assert set(enums.BR_PROBLEM_TYPES) == {t for t, ds in types.items() if "巴西" in ds}
    assert set(enums.OS_PROBLEM_TYPES.values()) == {t for t, ds in types.items() if "海外" in ds}
