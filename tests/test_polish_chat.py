"""AI 润色 P5：对话框里说「润色」时引导到问题单页面（决策 2026-11-09「AI 润色技术设计」§13.3）。"""

from __future__ import annotations

import pytest
import scopes
from fakes import make_harness, run
from forge_core.events import EventType

from factory_issue_module.turn import errors, greeting

ASK = "帮我润色这段原因分析：治具松动，作业员没按要求作业"


def _kinds(events):
    return [e.type for e in events]


@pytest.mark.parametrize("query", [ASK, "能不能润色一下", "AI润色怎么用", "润色"])
async def test_polish_in_chat_redirects_without_model_or_data(query):
    h = make_harness(scopes.account_jia())
    events = await run(h, query)
    assert _kinds(events) == [EventType.DELTA, EventType.SUGGESTIONS]
    assert events[0].data["text"] == errors.POLISH_IN_CHAT
    assert events[1].data["recommendations"] == greeting.buttons(_access(h))  # 同能力介绍的按钮
    assert h.llm.calls == [] and h.llm.suggest_calls == [] and h.queries == []
    assert h.workspace.store == {}  # 同寒暄、能力介绍：不写工作区


def _access(h):
    from factory_issue_module.turn import gate

    return gate.resolve(h.ctx)


async def test_no_domain_still_redirects_without_buttons():
    """位置在判「三域都无权」之前：无权的用户问润色同样答引导语，不答请先申请；三域都无权时不给按钮。"""
    h = make_harness(scopes.no_domain())
    events = await run(h, ASK)
    assert [(e.type, e.data.get("text")) for e in events] == [(EventType.DELTA, errors.POLISH_IN_CHAT)]
    assert h.llm.calls == [] and h.llm.suggest_calls == [] and h.queries == []
    assert h.workspace.store == {}


async def test_access_unavailable_comes_first():
    h = make_harness(None, resolved=False)
    events = await run(h, ASK)
    assert [e.data.get("code") for e in events] == [errors.ACCESS_UNAVAILABLE_CODE]


async def test_blank_comes_first():
    h = make_harness(scopes.account_jia())
    events = await run(h, "？？？")
    assert events[0].data["text"] == f"{errors.NOT_UNDERSTOOD}。"


@pytest.mark.parametrize("query", ["帮我改写这段原因分析", "优化措辞：治具松动"])
async def test_other_rewrite_words_still_go_to_the_planner(query):
    """只认「润色」：「改写」「优化措辞」照常规划（答超出范围或只读请求）。"""
    plan = {"understanding": "x", "alternatives": [],
            "steps": [{"id": "s1", "skill": "introduce", "when": None, "params": {"kind": "超出范围"}}]}
    h = make_harness(scopes.account_jia(), llm_replies=[plan])
    events = await run(h, query)
    assert len(h.llm.calls) == 1  # 规划调了一次
    assert events[0].data["text"] == f"{errors.OUT_OF_SCOPE}。"


def test_message_matches_the_landed_boundary():
    """引导语说的是 `2_landed/domestic/ai_polish.md`「边界」那一条：问题单页面、该栏旁的【AI润色】。"""
    from factory_issue_module import landed

    body = landed.section(landed.read("domestic/ai_polish.md"), "## 边界")
    assert "引导他到问题单页面点该栏旁的【AI润色】" in body
    assert "问题单页面点该栏旁的【AI润色】" in errors.POLISH_IN_CHAT
