"""正文分段发出与进度事件（`present/pacing.py`、`module.live`；开发者 2026-11-02 定，打字机效果先做这一种）。"""

from __future__ import annotations

import random
from typing import Any

import pytest
import scopes
from fakes import make_harness, run
from forge_core.events import Event, EventType

from factory_issue_module.present import pacing


def _text(events: list[Any]) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


@pytest.mark.parametrize("text", [
    "", "短句。", "国内近 30 天共 4 张，硬件问题最多（2 张），最需要关注的是 ZC9901001。" * 3,
    "完整 120 张见附件：[制程问题清单.xlsx](https://files.local/t1?x=1)（24 小时内有效）。",
])
def test_pieces_join_back_to_the_original(text: str):
    assert "".join(pacing.pieces(text)) == text


def test_markdown_links_are_never_split():
    link = "[ZC9901001](https://info.test.local/a?id=1&type=2)"
    parts = pacing.pieces(f"最需要关注的是 {link}，其次是 [ZC9901002](https://info.test.local/a?id=2)。")
    assert any(link in p for p in parts)
    assert not any(("[ZC99" in p) != (")" in p and "](" in p) for p in parts if "[" in p or "](" in p)


def test_long_paragraph_is_cut_into_at_most_max_pieces():
    assert len(pacing.pieces("字" * 5000)) <= pacing.MAX_PIECES


def test_piece_sizes_are_random_between_one_and_eight():
    """每段 1–8 个字随机（开发者 2026-11-02 建议）；拼回去与原文逐字相同。"""
    text = "国内近 30 天共 4 张，硬件问题最多，最需要关注的是 ZC9901001。" * 2
    parts = pacing.pieces(text, rng=random.Random(7))
    assert "".join(parts) == text
    assert all(pacing.CHUNK_MIN <= len(p) <= pacing.CHUNK_MAX for p in parts)
    assert len({len(p) for p in parts}) > 1  # 不是固定字数


async def _collect(events: list[Event], budget: float) -> tuple[list[Event], list[float]]:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    async def source():
        for e in events:
            yield e

    out = [e async for e in pacing.paced(source(), delay=0.1, budget=budget, sleep=fake_sleep)]
    return out, waits


async def test_paced_splits_deltas_and_passes_other_events_through():
    table = Event.table(columns=["问题编号"], rows=[["ZC9901001"]], title="t")
    events = [Event.delta("开头一句，共 4 张。" * 2), table, Event.delta("统计口径：近 30 天。")]
    out, waits = await _collect(events, budget=10)
    assert _text(out) == _text(events)
    assert [e for e in out if e.type is EventType.TABLE] == [table]
    assert sum(1 for e in out if e.type is EventType.DELTA) > 2 and waits


async def test_paced_stops_waiting_after_the_budget():
    out, waits = await _collect([Event.delta("字" * 400), Event.delta("后面的话" * 50)], budget=0.3)
    assert sum(waits) <= 0.3 + 1e-9
    assert out[-1].data["text"] == "后面的话" * 50  # 超过预算之后整段一次发出
    assert _text(out) == "字" * 400 + "后面的话" * 50


NARR = "近 30 天国内共 4 张，硬件问题最多。最需要关注的是 ZC9901001。"


def _list_reply() -> dict:
    return {"understanding": "列近 30 天国内的单", "alternatives": [], "steps": [{
        "id": "s1", "skill": "list_issues", "when": None, "params": {
            "domains": {"value": ["国内"], "from": "user"},
            "time": [{"said": "近 30 天", "basis": "建单", "from": "user"}]}}]}


async def test_live_handle_sends_progress_and_the_same_text_in_pieces():
    import cn_data

    quiet = make_harness(scopes.account_jia(), llm_replies=[_list_reply(), NARR])
    cn_data.load(quiet)
    live = make_harness(scopes.account_jia(), llm_replies=[_list_reply(), NARR])
    cn_data.load(live)
    live.module.live = True
    before = await run(quiet, "近 30 天国内的问题有哪些")
    after = await run(live, "近 30 天国内的问题有哪些")
    assert EventType.PROGRESS not in [e.type for e in before]
    stages = [e.data["stage"] for e in after if e.type is EventType.PROGRESS]
    assert stages == ["plan", "query"]
    assert _text(after) == _text(before)
    assert sum(1 for e in after if e.type is EventType.DELTA) > sum(1 for e in before if e.type is EventType.DELTA)
    # 表格、按钮原样都在
    assert [e.type for e in after if e.type not in (EventType.DELTA, EventType.PROGRESS)] == \
        [e.type for e in before if e.type is not EventType.DELTA]
