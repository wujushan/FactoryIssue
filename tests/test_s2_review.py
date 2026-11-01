"""S2 评审（`docs/reviews/2026-10-29-G4b-S2国内清单与统计评审.md`）M1–M5、A1–A7 的反例单测。

每条先在改之前的代码上跑过、确认失败，改后通过（同 S1 评审的做法）。
"""

from __future__ import annotations

import cn_data
import pandas as pd
import scopes
from fakes import make_harness, run
from forge_core.events import EventType
from test_s2_execute import CN, RECENT30, _go, _tables, _text, _types, plan, step

from factory_issue_module.domains import domestic
from factory_issue_module.present import caliber as cal
from factory_issue_module.stats.lib import views
from factory_issue_module.turn import errors

NARR = "共 4 张，硬件问题最多。其中未结案 3 张。"


async def test_m1_only_brazil_is_answered_by_the_brazil_adapter():
    """M1：S2 时只问巴西答「暂时还答不了」；S3 接上巴西适配器后照常查，查不到时答没有查到单，不发整轮失败。"""
    reply = plan(step("list_issues", domains={"value": ["巴西"], "from": "user"}, time=RECENT30))
    h, events = await _go("近 30 天巴西的问题有哪些", [reply], privileges=scopes.GREEN)
    assert EventType.ERROR not in _types(events)
    text = _text(events)
    assert "暂时还答不了" not in text and "巴西" in text and "没有查到单" in text
    assert any(q.tables[0] == "BrazilProblemList" for q in h.queries if q.tables)


async def test_m2_overview_caliber_defines_closed_and_stopped():
    """M2：概况写了未结案、停线中的张数，统计口径要写这两个说法怎么算；驳回、停线中已完成大于 0 时点出张数。"""
    rows = cn_data.main_rows() + [
        {**cn_data.main_rows()[3], "ID": 5, "Numbers": "ZC9901005", "Status": 13, "ProblemType": 7},
        {**cn_data.main_rows()[3], "ID": 6, "Numbers": "ZC9901006", "Status": 32, "IsStop": 1, "StopStatus": 4},
    ]
    reply = plan(step("aggregate", domains=CN, time=RECENT30))
    h, events = await _go("国内最近咋样", [reply, NARR], main=pd.DataFrame(rows))
    text = _text(events)
    assert cal.CLOSED in text and cal.STOPPED in text
    assert cal.rejected(1) in text and cal.stopped_done(1) in text


def test_m3_weeks_sorted_by_time_not_by_label():
    """M3：按周统计时类目按该周的起始日期排，不按标签字典序（第 2 周、第 10 周、第 11 周）。"""
    from factory_issue_module.stats.tasks import aggregate as task

    v = pd.DataFrame([{"_id": i, "_add": pd.Timestamp(d), "_done": False}
                      for i, d in enumerate(["2026-01-05", "2026-03-02", "2026-03-09"], start=1)])
    dim = {"name": "周", "period": "周", "period_col": "_add", "title": "周"}
    A = {"metrics": ["单数"], "top": None, "ranking": False, "top_n": 10, "table_rows": 20}
    table, *_ = task.ag_dim_table(v, dim, A, {"count": "单数"}, None)
    assert [r[0] for r in table["rows"]] == ["2026 年第 2 周", "2026 年第 10 周", "2026 年第 11 周"]
    assert views.vw_period(pd.Timestamp("2026-01-05"), "周") == "2026 年第 2 周"


async def test_m4_design_change_no_does_not_take_blanks():
    """M4：「是否设计变更」选「否」只比 0，空值留在「未填」。"""
    reply = plan(step("list_issues", domains=CN, time=RECENT30,
                      filters=[{"field": "是否设计变更", "op": "是", "value": "否", "from": "user"}]))
    h, _events = await _go("近 30 天国内不需要设计变更的单", [reply, NARR])
    main = next(q for q in h.queries if q.tables and q.tables[0] == "ZCTracking_ProblemList")
    assert "[IsDesignChange] =" in main.sql and "[IsDesignChange] IS NULL" not in main.sql


async def test_m5_several_departments_give_per_department_counts():
    """M5：一个说法对上多个部门时按全部合计，同时分部门给出各自的张数（数由沙箱算）。"""
    rows = cn_data.main_rows()
    rows[2] = {**rows[2], "RDepartment": 8}
    h = make_harness(scopes.account_jia(), llm_replies=[
        plan(step("list_issues", domains=CN, time=RECENT30,
                  filters=[{"field": "跟进部门", "op": "是", "value": "研发", "from": "user"}])), NARR])
    cn_data.load(h, main=pd.DataFrame(rows))
    h.connectors["info"].frames["Department"] = pd.DataFrame(
        [{"ID": 7, "Name": "研发一部"}, {"ID": 8, "Name": "研发二部"}, {"ID": 9, "Name": "生产工程部"}])
    events = await run(h, "近 30 天国内研发跟进的单")
    text = _text(events)
    assert "按以下几个部门统计" in text
    assert "研发一部 2 张" in text and "研发二部 1 张" in text


async def test_a1_overview_opening_has_type_distribution():
    reply = plan(step("aggregate", domains=CN, time=RECENT30))
    h, events = await _go("国内最近咋样", [reply, "共 4 张。"])
    assert "硬件问题 2 张" in _text(events).split("\n\n")[0]


async def test_a2_recent_says_thirty_days_and_offers_wider_windows():
    reply = plan(step("list_issues", domains=CN, time=[{"said": "最近", "basis": "建单", "from": "user"}]))
    h, events = await _go("国内最近的问题", [reply, NARR])
    assert "按近 30 天" in _text(events)
    recs = next(e for e in events if e.type is EventType.SUGGESTIONS).data["recommendations"]
    # 两个时间范围在前，S5 的模板按钮在后（§9.5）
    assert [r["query"] for r in recs][:2] == ["国内近 90 天的问题", "国内今年的问题"]


async def test_a3_relax_counts_do_not_call_the_model_again():
    from datetime import date, datetime, timedelta

    cutoff = datetime.combine(date.today() - timedelta(days=40), datetime.min.time())

    def main(sql: str, params: dict) -> pd.DataFrame:
        starts = [v for v in params.values() if isinstance(v, datetime)]
        return pd.DataFrame() if starts and min(starts) > cutoff else pd.DataFrame(cn_data.main_rows())

    reply = plan(step("list_issues", domains=CN, time=[{"said": "最近", "basis": "建单", "from": "user"}]))
    h, events = await _go("国内最近的问题", [reply], main=main)
    assert len(h.llm.calls) == 1
    labels = [r["label"] for r in next(e for e in events if e.type is EventType.SUGGESTIONS).data["recommendations"]]
    assert labels == ["看近 90 天（4 张）", "看今年（4 张）"]


async def test_a4_supplier_partial_name_matching_several_clarifies():
    reply = plan(step("list_issues", domains=CN, time=RECENT30,
                      filters=[{"field": "供应商", "op": "是", "value": "测试", "from": "user"}]))
    h = make_harness(scopes.account_jia(), llm_replies=[reply])
    cn_data.load(h)
    h.connectors["info"].frames["tbIQCvendor"] = pd.DataFrame(
        [{"ferpcode": "V98", "fname": "测试电子"}, {"ferpcode": "V99", "fname": "测试供应商"}])
    events = await run(h, "近 30 天国内测试的单")
    assert _types(events) == [EventType.CLARIFY] and "测试电子" in events[0].data["question"]


async def test_a5_master_data_failure_is_not_answered_as_not_found():
    from forge_core.errors import TableDenied

    reply = plan(step("list_issues", domains=CN, time=RECENT30,
                      filters=[{"field": "机型", "op": "是", "value": "A920", "from": "user"}]))
    h = make_harness(scopes.account_jia(), llm_replies=[reply])
    cn_data.load(h)
    h.connectors["info"].errors["ZCTracking_ProductNames"] = TableDenied("拒绝", detail={})
    events = await run(h, "近 30 天国内 A920 的问题")
    text = _text(events) + "".join(e.data.get("question", "") + e.data.get("message", "") for e in events)
    assert "没有找到" not in text and errors.SECTION_FAILED in text


async def test_a6_sorted_by_rate_does_not_say_latest():
    rows = [{**cn_data.main_rows()[0], "ID": i, "Numbers": f"ZC99020{i:02d}", "Rate": float(i)} for i in range(1, 26)]
    reply = plan(step("list_issues", domains=CN, time=RECENT30, sort={"by": "不良率", "order": "降序"}))
    h, events = await _go("近 30 天国内不良率最高的单", [reply, NARR], main=pd.DataFrame(rows))
    head = _text(events).split("\n\n")[0]
    assert "最近" not in head and "不良率从高到低" in head
    assert _tables(events)[0]["rows"][0][0] == "ZC9902025"


async def test_a7_tie_at_the_last_rank_is_said():
    rows = cn_data.main_rows()
    reply = plan(step("aggregate", domains=CN, time=RECENT30, group_by=["加工厂"], ranking=True, top=2))
    h, events = await _go("近 30 天国内问题最多的两个工厂", [reply, NARR], main=pd.DataFrame(rows))
    assert len(_tables(events)[0]["rows"]) == 3  # 第 2 名亮亮、惠州百富并列，都列出
    assert "第 2 名并列" in _text(events)


def test_m4_resolve_condition_shape():
    """M4 的条件本身：「否」= 0 且不带空值；「是」= 1。"""
    from datetime import date

    from factory_issue_module.domains.shared import MasterData

    R = domestic.Resolver(master=MasterData(), dept_aliases=None, regions=None, entities={}, today=date.today())
    for said, want in (("否", 0), ("是", 1)):
        st = {"params": {"filters": [{"field": "是否设计变更", "op": "是", "value": said}]}}
        got = domestic.resolve(st, [], R)
        cond = next(c for c in got.sql if c["field"] == "m.IsDesignChange")
        assert cond["value"] == want and not cond.get("include_nulls")
