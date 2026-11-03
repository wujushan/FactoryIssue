"""「我跟进的」「我手上的」「我负责的」按当前用户查（G70，决策 2026-11-03「『我』按当前用户查」）：
平台给出的工号就是人员表员工 ID，按 ID 对人，不按姓名；认不出时请用户给出姓名，本轮不取数。

假数据同 `test_s3_execute.py`（三域，人员表里测试甲的员工 ID 是 11、部门生产工程部）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import s3_data
import scopes
from fakes import data_queries, make_harness, run
from forge_core.events import EventType
from forge_core.module import UserContext

from factory_issue_module.config import files
from factory_issue_module.declarations import TOPIC_TERMS
from factory_issue_module.domains import base
from factory_issue_module.plan import names, normalize
from factory_issue_module.plan.normalize import Context

CN = {"value": ["国内"], "from": "user"}
NARR = "共 3 张。最需要关注的是 ZC9901001。"
JIA = UserContext(user_id="11", name="测试甲", department="生产工程部")


def plan(*steps: dict) -> dict:
    return {"understanding": "按条件查", "alternatives": [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params: Any) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def who(field: str, value: Any) -> dict:
    return {"field": field, "op": "是", "value": value, "from": "user"}


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _rows(events) -> list[list[Any]]:
    return [r for e in events if e.type is EventType.TABLE for r in e.data["rows"]]


async def _go(query: str, replies: list, user: UserContext | None = JIA):
    h = make_harness(scopes.GREEN, llm_replies=replies, user=user)
    s3_data.load(h)
    return h, await run(h, query)


def _employee_queries(h) -> list:
    return [q for q in h.queries if q.tables and q.tables[0] == "Employee"]


async def test_my_hands_equals_the_same_question_by_my_name():
    """「我手上的」按当前责任人查，结果与用姓名问同一句相同；开头写明按哪位员工理解；巴西照旧不计入。"""
    _h, mine = await _go("我手上还有哪些单", [plan(step("list_issues", filters=[who("当前责任人", "我")])), NARR])
    _h2, named = await _go("测试甲手上还有哪些单",
                           [plan(step("list_issues", filters=[who("当前责任人", "测试甲")])), NARR])
    assert EventType.CLARIFY not in [e.type for e in mine]
    assert _rows(mine) == _rows(named) and _rows(mine)
    text = _text(mine)
    assert "「我」按当前用户测试甲（生产工程部）理解" in text
    assert "巴西不提供当前责任人，巴西未计入" in text
    assert "当前责任人：测试甲" in text and "当前责任人：我" not in text


async def test_i_follow_matches_by_employee_id_not_by_name():
    """「我跟进的」：按工号（员工 ID 11）对人，国内按问题跟进人的员工 ID 筛；不拿「我」去按姓名取人。"""
    h, events = await _go("我跟进的国内问题", [plan(step("list_issues", domains=CN, filters=[who("跟进人", "我")])), NARR])
    assert EventType.CLARIFY not in [e.type for e in events]
    main = next(q for q in data_queries(h) if q.tables[0] == "ZCTracking_ProblemList")
    assert "11" in [str(v) for v in main.params.values()]
    by_id = [q for q in _employee_queries(h) if 11 in q.params.values()]
    assert by_id and all("我" not in q.params.values() for q in _employee_queries(h))


async def test_no_employee_id_asks_for_a_name_and_fetches_nothing():
    """工号不是员工 ID（测试通道、本机平台的账号）：说明认不出、请给出姓名，本轮不取业务数据。"""
    h, events = await _go("我负责的单有哪些", [plan(step("list_issues", filters=[who("责任人", "我")]))],
                          user=UserContext(user_id="u-test", name="测试甲"))
    assert [e.type for e in events if e.type is not EventType.PROGRESS] == [EventType.CLARIFY]
    assert events[-1].data["question"] == base.ME_UNKNOWN
    assert data_queries(h) == []


async def test_employee_id_not_in_staff_asks_for_a_name():
    """工号是数字、人员表里却没有这名员工：同样请用户给出姓名，不按全部单查，也不按平台给的姓名去对。"""
    h, events = await _go("我手上还有哪些单", [plan(step("list_issues", filters=[who("当前责任人", "我")]))],
                          user=UserContext(user_id="99", name="测试甲"))
    assert events[-1].type is EventType.CLARIFY and events[-1].data["question"] == base.ME_UNKNOWN
    assert data_queries(h) == []


async def test_staff_table_unavailable_is_section_failed_not_ask():
    """取人员表出错：该段按「这一部分暂时没查到」答，不答成认不出您是哪位。"""
    h = make_harness(scopes.GREEN, llm_replies=[plan(step("list_issues", domains=CN, filters=[who("跟进人", "我")]))],
                     user=JIA)
    s3_data.load(h)
    h.connectors["info"].errors["Employee"] = RuntimeError("连不上")
    events = await run(h, "我跟进的国内问题")
    assert base.ME_UNKNOWN not in _text(events)
    assert all(e.type is not EventType.CLARIFY for e in events)


# ---------------------------------------------------------------------------- 规整（§5.3 第 4 条）


def _apply(steps: list[dict], query: str) -> dict:
    ctx = Context(query=query, classes={"人": ["测试甲", "本人"]}, topics=files.default(TOPIC_TERMS),
                  today=date(2026, 11, 3))
    out = normalize.apply({"steps": steps}, ctx)
    assert out is not None
    return out


def test_self_words_in_person_filters_become_wo():
    out = _apply([step("list_issues", filters=[who("当前责任人", "本人"), who("跟进人", ["自己", "测试乙"]),
                                               who("物料名称", "自己")])], "本人手上、自己和测试乙跟进的")
    filters = out["steps"][0]["params"]["filters"]
    assert [f["value"] for f in filters] == ["我", ["我", "测试乙"], "自己"]
    assert [f["field"] for f in filters] == ["当前责任人", "跟进人", "物料名称"]  # 不因库里有人叫「本人」改类


def test_draft_status_becomes_pending_submit():
    """状态「草稿」「未提交」统一成「待提交」（p2.3 对照集 BR-009 五次都写成「草稿」，执行层本来就认）。"""
    out = _apply([step("aggregate", domains={"value": ["巴西"], "from": "user"},
                       filters=[who("状态", "草稿")])], "巴西系统里现在有几张草稿没提交？")
    assert out["steps"][0]["params"]["filters"][0]["value"] == "待提交"


def test_is_self():
    assert all(names.is_self(w) for w in ("我", "本人", "自己", " 我 ", "我自己"))
    assert not any(names.is_self(w) for w in ("我们", "测试甲", "帮我", ""))
