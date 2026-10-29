"""巴西、海外与跨域合并（设计 §6.2–§6.4、§8、§9.1；任务单 S3）：假 `ctx`、真沙箱、回放的模型回复。

夹具 J-D08（只有雷亚尔的费用单）、J-D12（是否涉及费用为测试值 0）、J-P01（部分域有权、三域一起问）在这里；
J-D10、J-D11（海外详情的区块）在 `test_s3_derive.py`。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
import s3_data
import scopes
from fakes import data_queries, is_factory_list, make_harness, run, table_tail
from forge_core.events import EventType

from factory_issue_module.declarations import DOMAINS, LOOKUP_TABLES, Domain
from factory_issue_module.present import caliber as cal
from factory_issue_module.turn import errors

BR = {"value": ["巴西"], "from": "user"}
OS = {"value": ["海外"], "from": "user"}
T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
NARR = "近 30 天共 10 张，硬件问题最多。最需要关注的是 ZC9901001。"


def plan(*steps: dict) -> dict:
    return {"understanding": "按条件查", "alternatives": [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _types(events) -> list[EventType]:
    return [e.type for e in events]


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


async def _go(query: str, replies: list, *, privileges=None, **load):
    h = make_harness(privileges or scopes.GREEN, llm_replies=replies)
    s3_data.load(h, **load)
    return h, await run(h, query)


# ---------------------------------------------------------------------------- 巴西、海外各自


async def test_brazil_list_default_columns_and_derivations():
    h, events = await _go("近 30 天巴西的问题有哪些", [plan(step("list_issues", domains=BR, time=T30)),
                                                     "巴西近 30 天共 4 张。最需要关注的是 BR9901001。"])
    table = _tables(events)[0]
    assert table["columns"] == ["问题编号", "机型", "问题类型", "不良率", "不良数量", "问题描述"]
    rows = {r[0]: r for r in table["rows"]}
    assert list(rows) == ["BR9901001", "BR9901002", "BR9901003", "BR9901004"]  # 建单时间倒序；草稿、已终止都在
    assert rows["BR9901001"][1:4] == ["A920", "硬件问题", "5.00%"]  # 不良率现算，保留 2 位
    assert rows["BR9901002"][1:4] == ["A920、Q92", "其他", "0.00%"]  # 大机型逗号多值；「其他|备注」；影响数量 0
    assert rows["BR9901003"][3] == "未填"  # 不良数量为空，算不出
    main = next(q for q in data_queries(h) if q.tables[0] == "BrazilProblemList")
    assert "[Status] <>" in main.sql and -1 in main.params.values()  # 已删除只靠状态 -1
    assert "ProblemDesc" not in " ".join(q.sql for q in h.queries)  # 不取叙述原文
    assert {"BrazilProblemProcess"} <= {q.tables[0] for q in data_queries(h)}


async def test_overseas_list_rate_is_original_text():
    h, events = await _go("近 30 天海外的问题有哪些", [plan(step("list_issues", domains=OS, time=T30))])
    rows = {r[0]: r for r in _tables(events)[0]["rows"]}
    assert rows["HW9901001"][1:4] == ["A920", "硬件问题", "10%"]
    assert rows["HW9901002"][1:4] == ["Q92", "工厂制程", "6.6667‰"]  # ‰ 照原文
    main = next(q for q in data_queries(h) if q.tables[0] == "OverseasProblemDetail")
    assert "IsDelete" in main.sql and "InvInfo" in main.sql and "ProblemDesc" not in main.sql


async def test_brazil_factory_matches_by_segment():
    """巴西加工厂逗号多值逐段比：CA 命中「CA」与「CA,TT」，不命中别的（BR-006）。"""
    reply = plan(step("list_issues", domains=BR, filters=[{"field": "加工厂", "op": "是", "value": "CA 工厂",
                                                           "from": "user"}]))
    h, events = await _go("巴西 CA 工厂的问题", [reply, "共 2 张。最需要关注的是 BR9901001。"])
    assert [r[0] for r in _tables(events)[0]["rows"]] == ["BR9901001", "BR9901003"]
    assert "加工厂：CA" in _text(events)


async def test_brazil_draft_status_counts_as_its_own():
    """巴西草稿即待提交，仍在范围内，不并进未结案（BR-009）。"""
    reply = plan(step("aggregate", domains=BR, filters=[{"field": "状态", "op": "是", "value": "草稿", "from": "user"}]))
    h, events = await _go("巴西现在有几张草稿没提交", [reply, "巴西共 1 张待提交。"])
    assert "共 1 张" in _text(events) and "待提交" in _text(events)


async def test_jd08_usd_total_mentions_brl_only_issues():
    """J-D08：问花了多少美元时给美元合计，另说明只产生了雷亚尔费用的单数与雷亚尔合计；涉及费用的单把它计入。"""
    reply = plan(step("aggregate", domains=BR, time=T30, metrics=["费用美元", "扣款"]))
    h, events = await _go("近 30 天巴西花了多少美元，扣款多少", [reply, "巴西共 4 张。"])
    text = _text(events)
    assert "涉及费用的单 3 张" in text and "费用合计 120 美元" in text
    assert "另有 1 张只产生了雷亚尔费用，合计 500 雷亚尔" in text
    assert "扣款 10 美元" in text and cal.COST in text and cal.DEBIT in text
    table = _tables(events)[0]
    assert table["columns"][-2:] == ["费用（美元）", "扣款费用（美元）"] and table["rows"][0][-2:] == [120, 10]
    assert any(q.tables[0] == "BrazilProblemCost" for q in data_queries(h))


async def test_jd12_is_cost_flag_excludes_test_value_zero():
    """J-D12：用户明说「是否涉及费用为是」时按单上的标记筛，只看 1、2；0 是测试脏值，不计入。"""
    reply = plan(step("list_issues", domains=BR, filters=[{"field": "其他", "column": "是否涉及费用", "op": "是",
                                                           "value": "是", "from": "user"}]))
    h, events = await _go("巴西是否涉及费用为是的单", [reply, "共 2 张。最需要关注的是 BR9901001。"])
    main = next(q for q in data_queries(h) if q.tables[0] == "BrazilProblemList")
    assert "[IsCost] =" in main.sql and 1 in main.params.values() and 0 not in main.params.values()
    rows = [r[0] for r in _tables(events)[0]["rows"]]
    assert rows == ["BR9901001", "BR9901004"]  # BR9901003 的标记是 0，不计入（假连接器不执行 WHERE，沙箱里再筛）
    assert "是否涉及费用：是" in _text(events)


async def test_has_cost_without_saying_flag_uses_cost_lines():
    """「涉及费用的单」按费用明细合计大于 0 认定，不看标记（巴西「费用」）。"""
    reply = plan(step("list_issues", domains=BR, filters=[{"field": "其他", "column": "涉及费用", "op": "是",
                                                           "value": "是", "from": "user"}]))
    h, events = await _go("巴西涉及费用的单", [reply, "共 3 张。最需要关注的是 BR9901001。"])
    main = next(q for q in data_queries(h) if q.tables[0] == "BrazilProblemList")
    assert "IsCost" not in main.sql.split("WHERE", 1)[-1]
    assert [r[0] for r in _tables(events)[0]["rows"]] == ["BR9901001", "BR9901003", "BR9901004"]


async def test_overseas_rate_is_not_averaged():
    """OS-008：海外不良率是单上原文，不汇总，逐单列出原文。"""
    reply = plan(step("aggregate", domains=OS, metrics=["合计不良率"]))
    h, events = await _go("把海外所有单的不良率合成一个平均值", [reply, "海外共 2 张。"])
    text = _text(events)
    assert "不汇总" in text and "海外不良率为单上原文，未汇总" in text
    rate_table = next(t for t in _tables(events) if t["columns"] == ["问题编号", "不良率"])
    assert rate_table["rows"] == [["HW9901001", "10%"], ["HW9901002", "6.6667‰"]]
    assert all("不良率（%）" not in t["columns"] for t in _tables(events))


async def test_overseas_series_is_not_a_condition():
    """OS-009：海外系列不作查询条件，海外不计入并写明。"""
    reply = plan(step("list_issues", domains=OS, filters=[{"field": "系列", "op": "是", "value": "A 系列",
                                                           "from": "user"}]))
    h, events = await _go("海外 A 系列的问题有哪些", [reply])
    assert "海外系列不作查询条件" in _text(events) and EventType.ERROR not in _types(events)
    assert not any(q.tables[0] == "OverseasProblemDetail" for q in data_queries(h))


# ---------------------------------------------------------------------------- 三域一起


async def test_cross_list_gives_counts_per_domain_and_one_analysis():
    """总述「跨域规则」清单呈现：开头各域张数与合计，每域一张表，分析段整步一次。"""
    h, events = await _go("近 30 天的问题有哪些", [plan(step("list_issues", time=T30)), NARR])
    text = _text(events)
    assert "合计 10 张：国内 4 张、巴西 4 张、海外 2 张" in text
    assert [t["title"].split("：")[0] for t in _tables(events)] == ["国内问题单", "巴西问题单", "海外问题单"]
    assert len(h.llm.calls) == 2 and text.count("问题描述摘要暂不可用") == 1
    assert "统计范围：国内、巴西、海外" in text


async def test_cross_types_merge_by_name_with_dash_for_absent():
    """XC-002：问题类型同名合并；该域没有这个类型写「—」，有但为 0 写 0；合计按域相加。"""
    reply = plan(step("aggregate", time=T30, group_by=["问题类型"]))
    h, events = await _go("近 30 天按问题类型统计", [reply, "共 10 张，硬件问题最多，有 4 张。"])
    table = _tables(events)[0]
    assert table["columns"] == ["问题类型", "国内", "巴西", "海外", "单数"]
    rows = {r[0]: r[1:] for r in table["rows"]}
    assert rows["硬件问题"] == [2, 1, 1, 4]
    assert rows["工厂制程"] == [0, "—", 1, 1] and rows["其他"] == ["—", 1, 0, 1] and rows["设计问题"][2] == "—"
    chart = next(e.data for e in events if e.type is EventType.CHART)
    assert chart["chart_type"] == "pie" and chart["series"][0]["data"][0] == 4
    text = _text(events)
    assert "合计 10 张（国内 4 张、巴西 4 张、海外 2 张）" in text and "最多的是硬件问题（4 张）" in text
    assert cal.merged("问题类型") in text


async def test_cross_levels_list_every_level():
    """XC-003：问题等级同名合并，A+、A、B、C 没有单也列出，未填单独一行。"""
    reply = plan(step("aggregate", time=T30, group_by=["问题等级"]))
    h, events = await _go("近 30 天三个域一起按问题等级统计", [reply, "共 10 张。B 级最多。"])
    rows = {r[0]: r[1:] for r in _tables(events)[0]["rows"]}
    assert list(rows) == ["A+", "A", "B", "C", "未填"] and rows["A+"] == [0, 0, 0, 0]
    assert rows["未填"] == [1, 1, 0, 2]  # 国内 NULL、巴西空串都算未填
    assert "最多的是B（4 张）" in _text(events)


async def test_cross_overview_rows_per_domain_and_set_aside():
    """XC-001：一域一行再加合计；域维度配柱状；巴西待提交、已终止另列，口径写各域结案的含义。"""
    reply = plan(step("aggregate", time=T30))
    h, events = await _go("近 30 天三个域一共出了多少张问题单", [reply, "共 10 张。"])
    table = _tables(events)[0]
    assert table["columns"][:5] == ["域", "单数", "未结案数", "停线中", "未结案占比（%）"]
    assert [r[0] for r in table["rows"]] == ["国内", "巴西", "海外", "合计"]
    assert table["rows"][1][1:3] == [4, 1]  # 巴西未结案不含待提交、已终止
    assert table["rows"][-1][1] == 10
    chart = next(e.data for e in events if e.type is EventType.CHART)
    assert chart["chart_type"] == "bar" and chart["x"]["data"] == ["国内", "巴西", "海外"]
    text = _text(events)
    assert cal.closed(["国内", "巴西", "海外"]) in text and "巴西另列：待提交 1 张、已终止 1 张" in text


async def test_cross_rate_is_given_per_domain():
    """XC-007：国内、巴西分母不同，分域给出不良率；海外只列原文、未汇总。"""
    reply = plan(step("aggregate", time=T30, metrics=["合计不良率"]))
    h, events = await _go("近 30 天三个域合起来的不良率是多少", [reply, "共 10 张。"])
    table = _tables(events)[0]
    at = table["columns"].index("不良率（%）")
    assert [r[at] for r in table["rows"]] == [2.67, 5.83, "—", "—"]
    text = _text(events)
    assert "合计不良率分域给出：国内 2.67%、巴西 5.83%" in text and "不合成跨域不良率" in text
    assert "海外不良率为单上原文" in text


async def test_cross_factory_only_in_one_domain_excludes_the_others():
    """名称只在某些域对得上（「柯洱斯」只是国内的工厂）：对不上的域不计入并写明，不追问。"""
    reply = plan(step("list_issues", filters=[{"field": "加工厂", "op": "是", "value": "柯洱斯", "from": "user"}]))
    h, events = await _go("柯洱斯工厂的问题", [reply, "共 2 张。最需要关注的是 ZC9901001。"])
    text = _text(events)
    assert "巴西没有加工厂「柯洱斯」，巴西未计入" in text and "海外没有加工厂「柯洱斯」，海外未计入" in text
    assert {q.tables[0] for q in data_queries(h)} & {"BrazilProblemList", "OverseasProblemDetail"} == set()


async def test_xc010_several_overseas_factories_clarify_and_say_other_domains():
    """XC-010：海外「伊朗」对上两家，列出请用户选；国内、巴西没有，追问里写明；本轮不出单。"""
    reply = plan(step("list_issues", filters=[{"field": "加工厂", "op": "是", "value": "伊朗工厂", "from": "user"}]))
    h, events = await _go("伊朗工厂的问题有哪些？", [reply])
    assert _types(events) == [EventType.CLARIFY]
    question = events[0].data["question"]
    assert "国内" in question and "巴西" in question and "伊朗PEA工厂" in question and "伊朗TOSAN工厂" in question
    assert data_queries(h) == []


async def test_name_found_nowhere_still_clarifies_with_other_kind():
    """M-16：「TT」不是任何域的机型，追问请核对，选项给「TT：巴西的加工厂」。"""
    reply = plan(step("aggregate", time=[{"said": "今年", "basis": "建单", "from": "user"}],
                      filters=[{"field": "机型", "op": "是", "value": "TT", "from": "user"}]))
    h, events = await _go("TT 今年多少单", [reply])
    assert _types(events) == [EventType.CLARIFY]
    assert "TT：巴西的加工厂" in [r["label"] for r in events[0].data["recommendations"]]


async def test_current_responsible_excludes_brazil():
    """某人手上的单：巴西不提供当前责任人，巴西不计入并写明（巴西「人员与部门」）。"""
    reply = plan(step("list_issues", filters=[{"field": "当前责任人", "op": "是", "value": "测试甲", "from": "user"}]))
    h, events = await _go("测试甲手上还有哪些单", [reply, "共 3 张。最需要关注的是 ZC9901001。"])
    assert "巴西不提供当前责任人，巴西未计入" in _text(events)
    assert not any(q.tables[0] == "BrazilProblemList" for q in data_queries(h))


async def test_type_only_elsewhere_excludes_domestic():
    """点名的类型国内没有（「设计问题」）：国内不计入并写明，不再把国内全部单算进来。"""
    reply = plan(step("aggregate", time=T30, filters=[{"field": "问题类型", "op": "是", "value": "设计问题",
                                                        "from": "user"}]))
    h, events = await _go("近 30 天的设计问题有多少", [reply, "巴西共 1 张。"])
    text = _text(events)
    assert "国内无「设计问题」类型，未计入" in text and "海外无「设计问题」类型，未计入" in text
    assert not any(q.tables[0] in ("ZCTracking_ProblemList", "OverseasProblemDetail") for q in data_queries(h))
    assert "巴西，" in text and "共 1 张" in text


async def test_chained_top_values_come_from_merged_ranking():
    """链式步骤三域一起：第一步的第一名按合计排（同名合并后），第二步按它在各域列清单。"""
    s1 = step("aggregate", "s1", time=T30, group_by=["机型"], ranking=True, top=1)
    s2 = step("list_issues", "s2", time=T30, filters=[{"field": "机型", "op": "属于", "value": {"ref": "s1.top_values"},
                                                       "from": "user"}])
    h, events = await _go("近 30 天问题最多的机型是哪个，把它的单列出来", [plan(s1, s2), "共 5 张。A920 最多。", NARR])
    tables = [t for t in _tables(events)]
    assert tables[0]["rows"][0][0] == "A920" and tables[0]["rows"][0][-1] == 5
    listed = [r[0] for t in tables[1:] for r in t["rows"]]
    assert "BR9901001" in listed and "HW9901001" in listed and "BR9901004" not in listed


async def test_jp01_partial_domains_no_sql_for_brazil_or_overseas():
    """J-P01：只申请了国内，三域一起问 → 只查国内；开头写明巴西、海外无权限未计入；对巴西、海外的表没有取数请求。"""
    h = make_harness(scopes.account_jia(), llm_replies=[plan(step("list_issues", time=T30)), NARR])
    s3_data.load(h)
    events = await run(h, "近 30 天的问题有哪些")
    text = _text(events)
    assert errors.not_counted(["巴西", "海外"]) in text and "没有数据" not in text
    br_os = {table_tail(t) for d in (Domain.BRAZIL, Domain.OVERSEAS) for t in (d.master_table, *d.sub_tables)}
    br_os |= {"Brazil_Factory", "Brazil_RequestList", "ProductName", "NewProduct"}
    assert {t for q in h.queries for t in q.tables} & br_os == set()
    assert [t["title"].split("：")[0] for t in _tables(events)] == ["国内问题单"]
    assert set(LOOKUP_TABLES) and all(d in DOMAINS for d in (Domain.BRAZIL, Domain.OVERSEAS))


async def test_overseas_factory_list_is_master_data_not_business_data():
    """海外加工厂的取值清单取自海外主表的去重加工厂一列，算主数据（规划前每轮取一次）。"""
    h = make_harness(scopes.GREEN, llm_replies=[plan(step("clarify", reason="接不上上一轮", question="想查什么？",
                                                          options=["近 30 天的单"]))])
    s3_data.load(h)
    events = await run(h, "那个呢")
    assert _types(events) == [EventType.CLARIFY]
    lists = [q for q in h.queries if is_factory_list(q)]
    assert len(lists) == 1 and "IsDelete" in lists[0].sql and data_queries(h) == []


async def test_period_by_month_small_sample_note():
    """巴西、海外按月统计、单数很少时提示样本少（总述「统计口径说明」样本量一行）。"""
    year = date.today().year
    reply = plan(step("aggregate", time=[{"said": "今年", "basis": "建单", "from": "user"}], group_by=["月"]))
    h, events = await _go("今年按月统计", [reply, "共 10 张。"])
    table = _tables(events)[0]
    assert table["columns"] == ["月", "国内", "巴西", "海外", "单数"] and table["rows"][0][0] == f"{year}-01"
    assert cal.small_sample("海外", 2) in _text(events)


async def test_stage_dims_stay_per_domain():
    """处理环节各域不同，按域分别给，每域一张，不合成跨域的环节表；分析段这一维写一次。"""
    reply = plan(step("aggregate", time=T30, group_by=["处理环节"]))
    h, events = await _go("近 30 天各环节有多少单", [reply, "国内、巴西、海外各环节都只有 1 张。没有哪一个环节明显积压。"])
    titles = [t["title"].split("按")[0] for t in _tables(events)]
    assert titles == ["国内", "巴西", "海外"] and len(h.llm.calls) == 2
    assert _text(events).count("处理环节：") == 1


@pytest.mark.parametrize("value", ["停线中", "曾经停线", "已经重启", "没有停线"])
async def test_stop_kinds_work_in_every_domain(value):
    reply = plan(step("list_issues", time=T30, filters=[{"field": "状态", "op": "是", "value": value, "from": "user"}]))
    h, events = await _go(f"近 30 天{value}的单", [reply, NARR])
    assert EventType.ERROR not in _types(events) and len(_tables(events)) >= 1
    assert "未计入" not in _text(events).split("**统计口径**")[0]


async def test_cn_only_stop_state_excludes_brazil_and_overseas():
    reply = plan(step("list_issues", time=T30, filters=[{"field": "状态", "op": "是", "value": "重启审核中",
                                                          "from": "user"}]))
    h, events = await _go("近 30 天重启审核中的单", [reply])
    text = _text(events)
    assert "巴西没有「重启审核中」这一状态，巴西未计入" in text and "海外没有「重启审核中」这一状态" in text


def test_tie_already_named_as_first_is_not_repeated():
    """S2 复评留下的一处：第一名全体并列、并列人数又超过要的名次时，「第 N 名并列」点的是同一批名字，只说前一句。"""
    from factory_issue_module.skills import aggregate

    seg = {"kind": "group", "title": "加工厂", "facts": {
        "总单数": 3, "按加工厂": [["A", 1], ["B", 1], ["C", 1]], "第一": ["A", "B", "C"], "第一并列": True,
        "并列": ["A", "B", "C"], "并列名次": 2}}
    text = aggregate.opening(seg, "国内", "")
    assert "并列最多的是A、B、C（1 张）" in text and "第 2 名并列" not in text
    seg["facts"]["第一"] = ["A"]
    seg["facts"]["按加工厂"] = [["A", 3], ["B", 1], ["C", 1]]
    seg["facts"]["并列"] = ["B", "C"]
    assert "第 2 名并列，B、C都列出" in aggregate.opening(seg, "国内", "")


def test_opening_first_count_for_ordered_dims():
    """按等级、按月这类按固定顺序排的维度，「最多的是 X（N 张）」的 N 取 X 那一行，不取第一行。"""
    from factory_issue_module.skills import aggregate

    seg = {"kind": "group", "title": "问题等级", "facts": {"总单数": 5, "按问题等级": [["A+", 0], ["A", 1], ["B", 4]],
                                                       "第一": ["B"], "第一并列": False}}
    assert "最多的是B（4 张）" in aggregate.opening(seg, "国内", "")


async def test_merge_frames_do_not_overwrite_each_other():
    """人员、存货这些各域都取的帧拼成一个再交沙箱，后取的不覆盖先取的（§6.4）。"""
    h, events = await _go("近 30 天按跟进人统计", [plan(step("aggregate", time=T30, group_by=["跟进人"])), "共 7 张。"])
    table = _tables(events)[0]
    assert table["columns"][:5] == ["问题跟进人", "国内", "巴西", "海外", "单数"]
    rows = {r[0]: r[1:5] for r in table["rows"]}
    # 国内跟进人一列、巴西最新一条处理过程的跟进人、海外逗号多值的跟进人，人员帧三域拼在一起翻译
    assert rows["测试甲"] == [3, 2, 1, 6] and rows["测试乙"] == [0, 0, 2, 2]


async def test_brazil_link_uses_sealed_params(monkeypatch):
    """巴西问题编号链接：type 与 ID 两个参数照 `link_rules.md` 换成大写十六进制，不做 URL 编码。"""
    from factory_issue_module.present import _p7, links

    monkeypatch.setattr(_p7, "pair", lambda: (b"Q" * 32, b"W" * 16))
    sites = "issue = \"info.test.local\"\nbrazil = \"br.test.local\""
    h = make_harness(scopes.GREEN, llm_replies=[plan(step("list_issues", domains=BR, time=T30)), NARR],
                     config_files={"link_sites.toml": sites})
    s3_data.load(h)
    events = await run(h, "近 30 天巴西的问题")
    cell = _tables(events)[0]["rows"][0][0]
    assert cell.startswith("[BR9901001](https://br.test.local/#/BrazilProblem/AddBrazilProblemPage?type=")
    kind = cell.split("type=")[1].split("&")[0]
    ident = cell.split("&ID=")[1].rstrip(")")
    assert kind == links._blk.seal(b"check", b"Q" * 32, b"W" * 16).hex().upper() and len(kind) == 32
    assert ident == links._blk.seal(b"1", b"Q" * 32, b"W" * 16).hex().upper() and ident.isupper()


def test_brazil_link_values_are_in_code():
    """两项值已写进代码（长度照 `link_rules.md`：32 与 16 个 ASCII 字符）；值本身不在测试里出现。"""
    from factory_issue_module.present import _p7, links

    got = _p7.pair()
    assert got is not None and links.brazil_ready()
    a, b = got
    assert len(a) == 32 and len(b) == 16 and all(32 < c < 127 for c in a + b)


async def test_brazil_number_is_text_until_values_are_in(monkeypatch):
    from factory_issue_module.present import _p7, links

    monkeypatch.setattr(_p7, "pair", lambda: None)
    assert not links.brazil_ready()
    from factory_issue_module.config.files import LinkSites

    sites = LinkSites(issue="https://a", brazil="https://b", attachment="https://a")
    assert links.issue(sites, Domain.BRAZIL, "BR9901001", 1) == "BR9901001"
    assert links.issue(sites, Domain.OVERSEAS, "HW9901001", 1) == "[HW9901001](https://a/#/QualityManage/OverseasProblemAllDetail?id=1)"


def test_frames_rows_for_brazil_and_overseas_load():
    assert len(pd.DataFrame(s3_data.br_rows())) == 4 and len(pd.DataFrame(s3_data.os_rows())) == 2


async def test_os005_status_filter_adds_main_status_column():
    """OS-005：按状态筛时加上状态一列；巴西、海外是主表状态（国内照旧是当前状态）；IQC 意见按条件加列。"""
    reply = plan(step("list_issues", domains=OS, filters=[
        {"field": "状态", "op": "是", "value": "已完成", "from": "user"},
        {"field": "IQC意见", "op": "是", "value": "退回仓库", "from": "user"},
        {"field": "问题类型", "op": "是", "value": "物料问题", "from": "user"}]))
    h, events = await _go("海外已完成、IQC 意见为退回仓库的物料问题有哪些？", [reply])
    main = next(q for q in data_queries(h) if q.tables[0] == "OverseasProblemDetail")
    assert "[IQCOpinion] IN" in main.sql and "[ProblemType] IN" in main.sql
    text = _text(events)
    assert "海外" in text and EventType.ERROR not in _types(events)


async def test_status_column_per_domain():
    reply = plan(step("list_issues", time=T30, filters=[{"field": "状态", "op": "是", "value": "未结案",
                                                          "from": "user"}]))
    h, events = await _go("近 30 天未结案的单", [reply, NARR])
    cols = {t["title"].split("问题单")[0]: t["columns"] for t in _tables(events)}
    assert "当前状态" in cols["国内"] and "状态" in cols["巴西"] and "状态" in cols["海外"]
    assert "当前状态" not in cols["巴西"] and "当前状态" not in cols["海外"]


async def test_os007_domestic_factory_column_says_it_is_another_column():
    reply = plan(step("aggregate", domains=OS, group_by=["国内工厂"]))
    h, events = await _go("海外单上记的国内工厂都有哪些？所有单", [reply, "海外共 2 张。"])
    text = _text(events)
    assert "国内工厂" in text and "加工厂" in text
    assert {r[0] for r in _tables(events)[0]["rows"]} == {"柯洱斯", "惠州百富"}
