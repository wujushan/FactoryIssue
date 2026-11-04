"""「未填」不参加排名、引用值分属不同的域、按「没填」筛（G87–G90，决策 2026-11-04「『未填』不参加排名」）：
假 `ctx`、真沙箱、回放的模型回复。断言锚在表格行、引用接上的单与程序写的句子上，不锚模型措辞。"""

from __future__ import annotations

import cn_data
import pandas as pd
import s3_data
import scopes
from fakes import data_queries, make_harness, run
from forge_core.events import EventType

from factory_issue_module.domains import base
from factory_issue_module.stats.tasks.aggregate import ag_split

CN = {"value": ["国内"], "from": "user"}
T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]


def plan(*steps: dict) -> dict:
    return {"understanding": "按条件查", "alternatives": [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


def _chain(field: str, ref: str, *, top: int | None = None, domains: dict | None = CN, detail: bool = False) -> dict:
    """「问题最多的 X 是哪个？把它的单列出来（，不良率最高那张的原因是什么）」。"""
    extra = {"domains": domains} if domains else {}
    s1 = step("aggregate", "s1", time=T30, group_by=[field], ranking=True, **({"top": top} if top else {}), **extra)
    s2 = step("list_issues", "s2", time=T30, filters=[{"field": field, "op": "属于", "value": {"ref": ref},
                                                       "from": "user"}], **extra)
    s3 = {"id": "s3", "skill": "issue_detail", "when": None,
          "params": {"issue": {"ref": "s2.max_defect_rate_issue"}, "aspects": ["原因"]}}
    return plan(s1, s2, *([s3] if detail else []))


async def _cn(query: str, replies: list, *, machines: pd.DataFrame):
    h = make_harness(scopes.account_jia(), llm_replies=replies)
    cn_data.load(h)
    h.connectors["info"].frames["ZCTracking_ProductNames"] = machines
    return h, await run(h, query)


_NO_MACHINES = pd.DataFrame(columns=["ID", "ProblemId", "ProductName", "Series"])


async def test_xc022_only_blank_machine_names_no_first_and_stops():
    """XC-022 的样子：单都没填机型。不点名第一、不调模型写结论，第二步不按「未填」去对机型，停在这里，第三步不执行。"""
    h, events = await _cn("近 30 天国内问题最多的机型是哪个？把它的单列出来，不良率最高那张的原因是什么？",
                          [_chain("机型", "s1.top1", detail=True)], machines=_NO_MACHINES)
    text = _text(events)
    assert _tables(events)[0]["rows"] == [["未填", 4]]
    assert "这 4 张单都没填机型（其中物料单 1 张），没有可以排名的机型" in text
    assert "前一步没有得出可以承接的机型，这一步和后面依赖它的步骤都不再查。" in text
    assert "请核对名称" not in text and "最多的是未填" not in text and "### 3. " not in text
    assert len([q for q in data_queries(h) if q.tables[0] == "ZCTracking_ProblemList"]) == 1


async def test_blank_more_than_first_is_listed_last_and_not_passed_on():
    """「未填」比第一名还多：照常列一行、排在最后；第一名是真实机型，后一步只接它；结论句后另写两句（张数来自沙箱）。"""
    one = pd.DataFrame([{"ID": 1, "ProblemId": 1, "ProductName": "A920", "Series": "A系列"}])
    h, events = await _cn("近 30 天国内问题最多的机型是哪个？把它的单列出来",
                          [_chain("机型", "s1.top_values"), "近 30 天国内共 4 张，A920 最多（1 张）。"], machines=one)
    text = _text(events)
    tables = _tables(events)
    assert tables[0]["rows"] == [["A920", 1], ["未填", 3]]
    assert ("另有 3 张没填机型（其中物料单 1 张），不参加排名。没填机型的单比排第一的还多，排名只反映已填机型的单。"
            in text)
    assert [r[0] for r in tables[1]["rows"]] == ["ZC9901001"]


async def test_referenced_top_names_split_across_domains():
    """三域一起取前 3 名工厂，名字分属国内、巴西：各域只用本域对得上的，写明对不上的；海外一个都对不上，不计入（G90）。"""
    h = make_harness(scopes.GREEN, llm_replies=[_chain("加工厂", "s1.top_values", top=3, domains=None),
                                                "近 30 天合计 10 张。"])
    s3_data.load(h)
    events = await run(h, "近 30 天问题最多的三个工厂各有哪些单？")
    text = _text(events)
    tables = _tables(events)
    assert [r[0] for r in tables[0]["rows"][:3]] == ["CA", "TT", "柯洱斯"]
    assert "国内没有加工厂「CA」「TT」" in text and "巴西没有加工厂「柯洱斯」" in text
    assert "海外没有加工厂「CA」「TT」「柯洱斯」，海外未计入" in text
    listed = {r[0] for t in tables[1:] for r in t["rows"]}
    assert {"ZC9901001", "ZC9901004", "BR9901001", "BR9901002", "BR9901003"} <= listed
    assert not {x for x in listed if x.startswith("HW")} and "BR9901004" not in listed
    assert "请核对名称" not in text


async def test_filter_by_blank_says_cannot_filter():
    """「没填机型的单」：不请用户核对名称，说明目前不能按没填筛（G89）；问题等级的「未填」照常能筛。"""
    reply = plan(step("list_issues", time=T30, filters=[{"field": "机型", "op": "是", "value": "未填",
                                                         "from": "user"}]))
    h = make_harness(scopes.GREEN, llm_replies=[reply])
    s3_data.load(h)
    events = await run(h, "近 30 天没填机型的单有哪些")
    clarify = [e for e in events if e.type is EventType.CLARIFY]
    assert clarify and "目前不能筛出没填机型的单（单上的「未填」表示没填）。" in str(clarify[0].data)
    assert "请核对名称" not in str(clarify[0].data)
    assert base.blank_said(["未填"]) == "未填" and "问题等级" in base.BLANK_OK


BR = {"value": ["巴西"], "from": "user"}
MODEL_DOWN = RuntimeError("模型出错")


async def _br(query: str, replies: list, rows: pd.DataFrame):
    h = make_harness(scopes.GREEN, llm_replies=replies)
    s3_data.load(h, br=rows)
    return h, await run(h, query)


#: 巴西 4 张单里 3 张没填问题类型，「未填」比唯一的真实类型多
_BLANK_TYPES = {2: {"ProblemType": None}, 3: {"ProblemType": None}, 4: {"ProblemType": None}}


def _br_rows_blank() -> pd.DataFrame:
    return pd.DataFrame([{**r, **_BLANK_TYPES.get(r["ID"], {})} for r in s3_data.br_rows()])


async def test_list_template_does_not_name_blank_type_as_most():
    """清单的模板句：「未填」张数最多也不点名为最多的问题类型，另写张数（G87）。"""
    h, events = await _br("近 30 天巴西的问题有哪些", [plan(step("list_issues", domains=BR, time=T30)), MODEL_DOWN],
                          _br_rows_blank())
    text = _text(events)
    assert "最多的问题类型是硬件问题（1 张）；另有 3 张没填问题类型" in text
    assert "最多的问题类型是未填" not in text


async def test_overview_template_lists_blank_type_after_distribution():
    """不分组的统计：问题类型分布不含「未填」，接着写「另有 N 张没填问题类型」；交模型的事实里另放（G87）。"""
    h, events = await _br("近 30 天巴西多少单", [plan(step("aggregate", domains=BR, time=T30)), MODEL_DOWN],
                          _br_rows_blank())
    text = _text(events)
    assert "问题类型分布：硬件问题 1 张；另有 3 张没填问题类型" in text
    facts = h.llm.calls[-1][-1]["content"].split("【事实】", 1)[1]
    assert '"按问题类型": [["硬件问题", 1]]' in facts and '"不参加排名的问题类型": [["未填", 3]]' in facts


async def test_unknown_machine_counts_as_unknown_not_blank():
    """巴西大机型有值但对不上产品主数据：按机型统计时归「未识别机型」（与清单显示一致），排在最后、不参加排名。"""
    rows = pd.DataFrame([{**r, **({"ProductIDAll": "999"} if r["ID"] == 4 else {})} for r in s3_data.br_rows()])
    h, events = await _br("近 30 天巴西按机型统计", [plan(step("aggregate", domains=BR, time=T30, group_by=["机型"])),
                                                 "巴西近 30 天共 4 张。"], rows)
    table = _tables(events)[0]
    assert table["rows"][-1][0] == "未识别机型" and "未填" not in [r[0] for r in table["rows"]]
    assert "另有 1 张为「未识别机型」。" in _text(events)


def test_unranked_lists_are_the_same():
    """`handle()` 一侧（维度说明）与沙箱一侧（分布）用的是同一份不参加排名的取值。"""
    from factory_issue_module.stats.lib.common import FI_UNRANKED

    assert tuple(base.UNRANKED) == tuple(FI_UNRANKED)


def test_placeholder_values_go_last_and_out_of_ranking():
    """海外问题类型「其他（未识别）」与「未填」一样不参加排名（G88），按 `UNRANKED` 的顺序排在最后。"""
    ranked, blanks = ag_split([("其他（未识别）", 9), ("硬件问题", 2), ("未填", 5)], base.UNRANKED)
    assert ranked == [("硬件问题", 2)] and blanks == [("未填", 5), ("其他（未识别）", 9)]
