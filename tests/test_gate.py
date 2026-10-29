"""权限前置与三域都无权的一轮（设计 §4.1、§4.2 第 1–2 步、§9.4；夹具 J-P02、J-P03、J-P10）。"""

from __future__ import annotations

import pytest
import scopes
from fakes import MANIFEST, data_queries, make_harness, run
from forge_core.events import EventType

from factory_issue_module import landed
from factory_issue_module.declarations import Domain
from factory_issue_module.turn import errors, gate, greeting

ALL = frozenset(Domain)


def _types(events):
    return [e.type for e in events]


def _text(events) -> str:
    return "\n".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


# ---------------------------------------------------------------- 判域


def test_account_jia_has_25_tables_and_only_domestic():
    payload = scopes.account_jia()
    assert scopes.count_tables(payload) == 25
    access = gate.resolve(make_harness(payload).ctx)
    assert access is not None
    assert access.domains == {Domain.DOMESTIC}
    assert access.car is False
    assert access.text_search == frozenset()  # S6 之前没声明 mart
    assert access.denied() == (Domain.BRAZIL, Domain.OVERSEAS)


def test_three_domains_with_car():
    access = gate.resolve(make_harness(scopes.privileges(ALL, car=True)).ctx)
    assert access is not None and access.domains == ALL and access.car


def test_green_light_opens_everything():
    access = gate.resolve(make_harness(scopes.GREEN).ctx)
    assert access is not None and access.domains == ALL and access.car


def test_no_domain_privileges_open_nothing():
    access = gate.resolve(make_harness(scopes.no_domain()).ctx)
    assert access is not None and access.none and not access.car


def test_jp10_master_denied_sub_table_allowed_still_denies_domain():
    """J-P10：国内主表拒绝、国内处理步骤表单独允许（配置漂移）→ 国内按无权处理。"""
    extra = [
        scopes.outer(Domain.DOMESTIC.master_table, mode="DENY"),
        scopes.outer("CoreINFO.dbo.ZCTracking_ProblemSteplog"),
    ]
    h = make_harness(scopes.privileges([Domain.BRAZIL], extra=extra))
    visible = {t.table for c in h.ctx.data.describe() for t in c.tables}
    assert "CoreINFO.dbo.ZCTracking_ProblemSteplog" in visible  # 子表本身没被拒
    access = gate.resolve(h.ctx)
    assert access is not None and access.domains == {Domain.BRAZIL}
    assert h.queries == []


def test_car_needs_domestic():
    access = gate.resolve(make_harness(scopes.privileges([Domain.BRAZIL], car=True)).ctx)
    assert access is not None and access.domains == {Domain.BRAZIL} and access.car is False


def test_without_drops_a_domain_after_table_denied():
    access = gate.DomainAccess(domains=ALL, car=True, text_search=ALL)
    after = access.without(Domain.DOMESTIC)
    assert after.domains == {Domain.BRAZIL, Domain.OVERSEAS}
    assert after.car is False and Domain.DOMESTIC not in after.text_search


def test_tree_without_privileges_is_unavailable():
    """Admin 调试对话、`forge dev serve` 默认授权树带空权限：require_privileges=True 时 describe 即拒。"""
    h = make_harness(None, resolved=False)
    assert gate.resolve(h.ctx) is None


def test_no_data_handle_is_unavailable():
    h = make_harness(scopes.GREEN)
    h.ctx.data = None
    assert gate.resolve(h.ctx) is None


# ---------------------------------------------------------------- 三域都无权（J-P02、J-P03）


async def test_jp02_no_domain_data_question():
    h = make_harness(scopes.no_domain())
    events = await run(h, "帮我查下制程问题")
    assert _types(events) == [EventType.DELTA]
    assert _text(events) == f"{errors.NO_DOMAIN}。"
    assert h.queries == [] and h.llm.calls == [] and h.stats.calls == []


async def test_jp03_no_domain_greeting_introduces_three_domains():
    h = make_harness(scopes.no_domain())
    events = await run(h, "你好，你能帮我查什么？")
    assert _types(events) == [EventType.DELTA]  # 三域都无权：不给按钮
    text = _text(events)
    for scene in landed.scenes():
        assert f"**{scene.name}**：{scene.answers}" in text
    for d in Domain:
        assert f"**{d.label}**" in text
    assert text.count(f"（{errors.APPLY_TO_VIEW}）") == 3
    assert errors.NO_DOMAIN in text
    assert MANIFEST.name in text
    assert h.queries == [] and h.llm.calls == [] and h.stats.calls == []


async def test_unavailable_privileges_answer_without_fetching():
    h = make_harness(None, resolved=False)
    events = await run(h, "你好")
    assert _types(events) == [EventType.ERROR]
    assert events[0].data == {
        "code": errors.ACCESS_UNAVAILABLE_CODE, "message": errors.ACCESS_UNAVAILABLE, "fatal": True,
    }
    assert h.queries == [] and h.llm.calls == []


async def test_partial_domain_planner_call_failed_answers_not_understood_with_buttons():
    """§14「规划超时」：有权限的问句要经规划器；模型调用出错时答没能理解，附 3 个按钮，不取数。"""
    h = make_harness(scopes.account_jia(), llm_replies=[TimeoutError("规划超时")])
    events = await run(h, "上个月国内的问题有哪些")
    assert _types(events) == [EventType.DELTA, EventType.SUGGESTIONS]
    assert errors.NOT_UNDERSTOOD in _text(events)
    assert data_queries(h) == [] and len(h.llm.calls) == 1


# ---------------------------------------------------------------- 能力介绍的组成（J-P04 的有权一半在 S1 经规划器）


def test_partial_domain_introduction_marks_unapplied_domains():
    access = gate.DomainAccess(domains=frozenset({Domain.DOMESTIC}), car=False, text_search=frozenset())
    text = greeting.introduction(MANIFEST, access)
    assert "**国内**（单号 ZC 开头）：" in text
    lines = {line.split("**")[1]: line for line in text.splitlines() if line.startswith("- **") and "单号" in line}
    assert errors.APPLY_TO_VIEW not in lines["国内"]
    assert errors.APPLY_TO_VIEW in lines["巴西"] and errors.APPLY_TO_VIEW in lines["海外"]
    assert errors.NO_DOMAIN not in text


def test_buttons_only_use_examples_the_user_can_ask():
    domestic_only = gate.DomainAccess(
        domains=frozenset({Domain.DOMESTIC}), car=False, text_search=frozenset()
    )
    recs = greeting.buttons(domestic_only)
    assert [r["name"] for r in recs] == ["问题单清单", "汇总统计", "停线查询"]
    assert recs[0]["query"] == "上个月国内的工厂制程问题有哪些？"
    brazil_only = gate.DomainAccess(
        domains=frozenset({Domain.BRAZIL}), car=False, text_search=frozenset({Domain.BRAZIL})
    )
    recs = greeting.buttons(brazil_only)
    assert recs[0]["query"] == "巴西 CA 工厂今年的物料问题"
    assert recs[1]["query"] == "6 月总共发生多少制程问题？"
    assert recs[2]["name"] == "类似问题" and recs[2]["label"] == "类似问题"  # 示例太长，用场景名
    for r in recs:
        assert set(r) == {"id", "name", "label", "query"} and len(r["label"]) <= 15


@pytest.mark.parametrize(
    "query",
    ["你好", "您好！", "hi", "Hello~", "在吗？", "你好你好", "你能帮我查什么？", "你是谁", "这个助手怎么用",
     "能做什么", "？你好"],
)
def test_is_greeting_positive(query):
    assert greeting.is_greeting(query)


@pytest.mark.parametrize(
    "query",
    ["帮我查下制程问题", "ZC2509012 现在到哪一步了？", "你好，帮我查一下上个月的单", "能帮我把这张单结案吗？",
     "嗯？", "？", "？？？", "……", "   ", "", "_—_!"],
)
def test_is_greeting_negative(query):
    assert not greeting.is_greeting(query)


@pytest.mark.parametrize("query", ["？", "？？？", "……", "   ", "", "?!。、", "_—_"])
def test_is_blank_positive(query):
    assert greeting.is_blank(query)


@pytest.mark.parametrize("query", ["嗯？", "？你好", "帮我查下制程问题", "A920", "1"])
def test_is_blank_negative(query):
    assert not greeting.is_blank(query)


# ---------------------------------------------------------------- 空问句（§4.2 第 2 步）


@pytest.mark.parametrize("query", ["？？？", "……", "   "])
async def test_blank_question_without_any_domain_is_only_not_understood(query):
    h = make_harness(scopes.no_domain())
    events = await run(h, query)
    assert _types(events) == [EventType.DELTA]
    text = _text(events)
    assert text == f"{errors.NOT_UNDERSTOOD}。"
    assert errors.NO_DOMAIN not in text and "常用场景" not in text
    assert h.queries == [] and h.llm.calls == [] and h.stats.calls == []


async def test_blank_question_with_a_domain_gets_buttons():
    h = make_harness(scopes.account_jia())
    events = await run(h, "？？？")
    assert _types(events) == [EventType.DELTA, EventType.SUGGESTIONS]
    assert _text(events) == f"{errors.NOT_UNDERSTOOD}。"
    recs = events[1].data["recommendations"]
    assert [r["name"] for r in recs] == ["问题单清单", "汇总统计", "停线查询"]
    assert h.queries == [] and h.llm.calls == [] and h.stats.calls == []


async def test_blank_question_still_needs_privileges_first():
    no_tree = make_harness(None, resolved=False)
    no_data = make_harness(scopes.GREEN)
    no_data.ctx.data = None
    for h in (no_tree, no_data):
        events = await run(h, "？？？")
        assert _types(events) == [EventType.ERROR]
        assert events[0].data["code"] == errors.ACCESS_UNAVAILABLE_CODE
        assert errors.NOT_UNDERSTOOD not in events[0].data["message"]
        assert h.queries == [] and h.llm.calls == []
