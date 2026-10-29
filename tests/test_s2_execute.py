"""国内清单与统计端到端（设计 §4.2 第 6–9 步、§6、§8、§9；任务单 S2）：假 `ctx`、真沙箱、回放的模型回复。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import cn_data
import pandas as pd
import scopes
from fakes import data_queries, make_harness, run
from forge_core.dataquery import QuerySpec
from forge_core.errors import TableDenied
from forge_core.events import EventType
from forge_data.datasources.base import record_queries, record_query

from factory_issue_module.domains import base
from factory_issue_module.turn import errors

CN = {"value": ["国内"], "from": "user"}
RECENT30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]


def plan(*steps: dict, alternatives: list | None = None) -> dict:
    return {"understanding": "按条件查", "alternatives": alternatives or [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _types(events) -> list[EventType]:
    return [e.type for e in events]


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


async def _go(query: str, replies: list, *, privileges=None, main=None):
    h = make_harness(privileges or scopes.account_jia(), llm_replies=replies)
    cn_data.load(h, main=main)
    return h, await run(h, query)


async def test_domestic_list_default_columns_analysis_and_caliber():
    narrative = "近 30 天国内共 4 张，硬件问题最多。最需要关注的是 ZC9901001。其中 1 张已完成。"
    h, events = await _go("近 30 天国内的问题有哪些",
                          [plan(step("list_issues", domains=CN, time=RECENT30)), narrative])
    assert _types(events) == [EventType.DELTA, EventType.TABLE, EventType.DELTA, EventType.DELTA]
    table = _tables(events)[0]
    assert table["columns"] == ["问题编号", "机型", "问题类型", "不良率", "不良数量", "问题描述"]
    assert [r[0] for r in table["rows"]] == ["ZC9901001", "ZC9901002", "ZC9901003", "ZC9901004"]  # 建单时间倒序
    assert table["rows"][1][1] == "物料" and table["rows"][2][1] == "A920、A920PRO"
    assert {r[5] for r in table["rows"]} == {"暂不可用"}
    text = _text(events)
    assert "共 4 张" in text and "问题描述摘要暂不可用" in text and narrative in text
    assert "统计口径" in text and "按建单时间" in text and "已删除的单未计入" in text
    main_sql = [q for q in data_queries(h) if q.tables[0] == "ZCTracking_ProblemList"]
    assert main_sql and "IsDelete" in main_sql[0].sql and "AddDate" in main_sql[0].sql
    assert "ProblemDesc" not in " ".join(q.sql for q in h.queries)  # 不取叙述原文
    assert len(h.llm.calls) == 2


async def test_domestic_aggregate_by_type_table_chart_caliber():
    reply = plan(step("aggregate", domains=CN, time=RECENT30, group_by=["问题类型"], metrics=["单数", "占比"]))
    h, events = await _go("近 30 天国内按问题类型统计", [reply, "共 4 张，硬件问题最多。物料问题和软件问题各 1 张。"])
    assert _types(events) == [EventType.DELTA, EventType.TABLE, EventType.CHART, EventType.DELTA, EventType.DELTA]
    table = _tables(events)[0]
    assert table["columns"] == ["问题类型", "单数", "占比（%）"]
    assert table["rows"][0] == ["硬件问题", 2, 50]
    chart = next(e.data for e in events if e.type is EventType.CHART)
    assert chart["chart_type"] == "pie" and chart["series"][0]["data"] == [2, 1, 1]
    assert "最多的是硬件问题（2 张）" in _text(events)


async def test_stages_need_current_state_and_task_sql_carries_both_names():
    """处理环节按当前状态每一行计（J-D04 的统计一半）；待办任务 SQL 都带两个业务表名（J-P12）。"""
    reply = plan(step("aggregate", domains=CN, time=RECENT30, group_by=["处理环节"]))
    h, events = await _go("近 30 天国内各处理环节有多少单", [reply, "共 4 张。SQE跟进与 IQC确认各 1 张。"])
    rows = dict((r[0], r[1]) for r in _tables(events)[0]["rows"])
    assert rows == {"IQC确认": 1, "SQE跟进": 1, "已完成": 1, "责任人确认": 1, "预防对策确认": 1}
    tasks = [q for q in h.queries if q.tables and q.tables[0] == "tbTask"]
    assert tasks and all("ZCTracking_ProblemSoftware3" in q.params.values()
                         and "ZCTracking_PreventionConfirm" in q.params.values() for q in tasks)
    assert "多值归属" in _text(events)


async def test_overview_close_cycle_and_rate():
    reply = plan(step("aggregate", domains=CN, time=RECENT30, metrics=["结案周期", "合计不良率"]))
    h, events = await _go("近 30 天国内平均多久结案", [reply, "共 4 张。已结案的 1 张平均 5 天结案。"])
    text = _text(events)
    assert "合计不良率 2.67%" in text and "中位数 5 天" in text and "结案确认" in text and "不参与" in text
    assert any(t["columns"] == ["结案周期", "单数"] for t in _tables(events))


async def test_jp09_table_denied_at_fetch_is_no_permission_not_empty():
    """J-P09：目录里国内主表可查，取数时却拒绝 → 以拒绝为准，按无权限答，不报内部错误、不说没有数据。"""
    h = make_harness(scopes.account_jia(), llm_replies=[plan(step("list_issues", domains=CN, time=RECENT30))])
    cn_data.load(h)
    h.connectors["info"].errors["ZCTracking_ProblemList"] = TableDenied("拒绝", detail={})
    events = await run(h, "近 30 天国内的问题有哪些")
    assert EventType.ERROR not in _types(events) and EventType.TABLE not in _types(events)
    text = _text(events)
    assert errors.not_counted(["国内"]) in text and "没有查到" not in text


async def test_machine_not_found_clarifies_without_fetching():
    reply = plan(step("list_issues", domains=CN, filters=[{"field": "机型", "op": "是", "value": "Z999", "from": "user"}]))
    h, events = await _go("国内 Z999 的问题", [reply])
    assert _types(events) == [EventType.CLARIFY] and "Z999" in events[0].data["question"]
    assert data_queries(h) == []


async def test_region_matching_several_factories_clarifies():
    """总述「必要澄清项」：按地区说工厂对上多家时追问，选项为几家合起来与每家单独（CN-011）。"""
    reply = plan(step("aggregate", domains=CN, time=[{"said": "今年", "basis": "建单", "from": "user"}],
                      filters=[{"field": "加工厂", "op": "是", "value": "惠州", "from": "user"}]))
    h, events = await _go("今年国内惠州的三个工厂一共出了多少问题", [reply])
    assert _types(events) == [EventType.CLARIFY]
    labels = [r["label"] for r in events[0].data["recommendations"]]
    assert labels[0] == "柯洱斯、亮亮、惠州百富" and set(labels[1:]) == {"柯洱斯", "亮亮", "惠州百富"}
    assert data_queries(h) == []


async def test_same_name_factory_codes_all_used():
    reply = plan(step("list_issues", domains=CN, filters=[{"field": "加工厂", "op": "是", "value": "柯洱斯", "from": "user"}]))
    h, events = await _go("国内柯洱斯的问题", [reply, "共 4 张。最需要关注的是 ZC9901001。"])
    main = next(q for q in data_queries(h) if q.tables[0] == "ZCTracking_ProblemList")
    assert {"04", "06"} <= set(main.params.values())
    assert "加工厂：柯洱斯" in _text(events)


async def test_inferred_class_is_said_in_opening():
    """第 7 条：只给名称、库里只有加工厂叫这个名字 → 按加工厂查，开头写「按加工厂理解」（模型放错类时改过来）。"""
    reply = plan(step("aggregate", domains=CN, time=[{"said": "今年", "basis": "建单", "from": "user"}],
                      filters=[{"field": "供应商", "op": "是", "value": "亮亮", "from": "user"}]))
    h, events = await _go("国内亮亮今年多少单", [reply, "共 1 张。"])
    assert "「亮亮」按加工厂理解" in _text(events)
    main = next(q for q in data_queries(h) if q.tables[0] == "ZCTracking_ProblemList")
    assert "Factory" in main.sql and "05" in main.params.values()


async def test_rule13_still_mismatched_opens_with_basis_and_offers_other_reading():
    """第 13 条修一次仍不一致：按计划执行，开头写明按什么日期理解，并给另一种理解的按钮。"""
    bad = plan(step("aggregate", domains=CN, time=[{"said": "今年", "basis": "建单", "from": "user"}]))
    h, events = await _go("今年结案了多少单", [bad, bad, "共 4 张。其中未结案 3 张。"])
    assert "「今年」按建单时间理解" in _text(events)
    sugg = next(e for e in events if e.type is EventType.SUGGESTIONS)
    assert sugg.data["recommendations"][0]["query"] == "今年结案了多少单（按结案时间算）"


async def test_rule15_gets_machine_names_from_master_data():
    """第 15 条的机型一半（S1 留下的口子）：问句里的机型名对得上库里的机型，计划里却没有 → 打回重写一次。"""
    missing = plan(step("list_issues", domains=CN, time=RECENT30))
    fixed = plan(step("list_issues", domains=CN, time=RECENT30,
                      filters=[{"field": "机型", "op": "是", "value": "A920", "from": "user"}]))
    h, events = await _go("近 30 天国内 A920 的问题", [missing, fixed])
    assert len(h.llm.calls) == 2 and "A920" in h.llm.calls[1][-1]["content"]  # 只有两张，不写分析段
    assert "机型：A920" in _text(events)


async def test_future_period_with_year_says_not_yet():
    """G77：写明了年份、整段都还没到的时间照原样查，查不到时答这段时间还没到，不追问。"""
    year = date.today().year + 1
    reply = plan(step("list_issues", domains=CN, time=[{"said": f"{year} 年", "basis": "建单", "from": "user"}]))
    h, events = await _go(f"{year} 年国内的问题", [reply], main=lambda sql, params: pd.DataFrame())
    assert "这段时间还没到" in _text(events) and EventType.TABLE not in _types(events)


async def test_empty_result_offers_relaxed_time_with_counts():
    """总述「结果为空时」：照实说没有，再给至多 2 个放宽默认读法的按钮，按钮上带预先查好的张数。"""
    cutoff = datetime.combine(date.today() - timedelta(days=40), datetime.min.time())

    def main(sql: str, params: dict) -> pd.DataFrame:
        starts = [v for v in params.values() if isinstance(v, datetime)]
        return pd.DataFrame() if starts and min(starts) > cutoff else pd.DataFrame(cn_data.main_rows())

    reply = plan(step("list_issues", domains=CN, time=[{"said": "最近", "basis": "建单", "from": "user"}]))
    h, events = await _go("国内最近的问题", [reply], main=main)  # 预先查张数只到沙箱，不写分析（S2 评审 A3）
    assert "没有查到单" in _text(events)
    recs = next(e for e in events if e.type is EventType.SUGGESTIONS).data["recommendations"]
    assert [r["label"] for r in recs] == ["看近 90 天（4 张）", "看今年（4 张）"]
    assert recs[0]["query"] == "国内近 90 天的问题"


async def test_list_without_conditions_says_so_and_offers_greeting_buttons():
    reply = plan(step("list_issues"))
    h, events = await _go("帮我查下制程问题", [reply, "共 4 张。最需要关注的是 ZC9901001。"])
    assert errors.NO_CONDITION_LIST in _text(events)
    assert _types(events)[-1] is EventType.SUGGESTIONS
    assert "巴西、海外无权限，未计入" in _text(events)


async def test_chained_steps_pass_top_values_by_reference():
    """链式步骤：第一步统计出的第一名由沙箱给（`top_values`），第二步按它列清单；口径合并成一段放最后。"""
    s1 = step("aggregate", "s1", domains=CN, time=RECENT30, group_by=["机型"], ranking=True, top=1)
    s2 = step("list_issues", "s2", domains=CN, time=RECENT30,
              filters=[{"field": "机型", "op": "属于", "value": {"ref": "s1.top_values"}, "from": "user"}])
    h, events = await _go("近 30 天国内问题最多的机型是哪个，把它的单列出来",
                          [plan(s1, s2), "共 4 张。A920 最多，有 2 张。"])
    text = _text(events)
    assert "**1. " in text and "**2. " in text and text.count("统计口径") == 1
    tables = _tables(events)
    assert tables[0]["rows"] == [["A920", 2]]
    assert [r[0] for r in tables[1]["rows"]] == ["ZC9901001", "ZC9901003"]


async def test_parallel_fetch_keeps_query_recording():
    """§6.1：`fetch` 放进 `asyncio.to_thread` 并行，平台的取数录制列表照常收到每一条（`queries.json` 归档）。"""
    h = make_harness(scopes.account_jia())

    def recorded(sql: str, params: dict) -> pd.DataFrame:
        record_query(source="info", sql=sql, params=params, rows=0, duration_ms=0)
        return pd.DataFrame()

    h.connectors["info"].frames["Employee"] = recorded
    spec = {"source": "info", "from": "info.dbo.Employee", "select": ["ID", "Name"]}
    with record_queries() as recs:
        await base.fetch_in(h.ctx, spec, "ID", list(range(2500)))  # 3 块并行
        await asyncio.gather(*(base.fetch(h.ctx, spec) for _ in range(4)))
    assert len(recs) == 7 and all(r["source"] == "info" for r in recs)
    QuerySpec.model_validate(spec)
