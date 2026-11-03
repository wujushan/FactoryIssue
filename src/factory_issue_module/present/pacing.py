"""正文分小段陆续发出（打字机效果，开发者 2026-11-02 定先做这一种；设计 §4.3）。

模型调用仍是一次拿回整段（`ctx.llm.chat`），分析段照旧逐句核对数字之后才放出（设计 §8.3）。这里只把已经定稿的
`delta` 正文切成小段（每段 1–8 个字随机）、隔一小会儿发一段，INFO 网页端就按到达的先后逐段显示。其他事件
（表格、图、按钮、追问、进度、出错）原样转发，不切也不等。

- 不在 Markdown 链接中间切：问题编号、导出文件的链接整段发出，免得前端先显示半截链接。
- 一轮总共最多等 `TURN_BUDGET` 秒；超过之后剩下的正文照常一次发出，不为了效果拖慢长回答。
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable

from forge_core.events import Event, EventType

#: 每段的字数在这个范围里随机取（开发者 2026-11-02 建议：固定字数看着像一格格吐字，随机更像在打字）
CHUNK_MIN, CHUNK_MAX = 1, 8
#: 两段之间等多久（秒）
CHUNK_DELAY = 0.02
#: 一轮里分段发出最多花多少秒
TURN_BUDGET = 2.5
#: 一个 `delta` 至多切成几段（长段落每段的字数随之变多，单个 `delta` 不超过约 0.8 秒）
MAX_PIECES = 40

_LINK = re.compile(r"\[[^\]\n]*\]\([^)\s]*\)")


def _units(text: str) -> list[str]:
    """逐字拆开，Markdown 链接整个算一个单位。"""
    units: list[str] = []
    pos = 0
    for m in _LINK.finditer(text):
        units.extend(text[pos:m.start()])
        units.append(m.group(0))
        pos = m.end()
    units.extend(text[pos:])
    return units


def pieces(text: str, max_pieces: int = MAX_PIECES, rng: random.Random | None = None) -> list[str]:
    """切成小段，每段 1–8 个字随机，拼回去与原文逐字相同。段数超过 `max_pieces` 时（长段落）按等长切到
    `max_pieces` 段以内。"""
    if not text:
        return []
    units = _units(text)
    pick = rng or random
    out: list[str] = []
    i = 0
    while i < len(units):
        size = pick.randint(CHUNK_MIN, CHUNK_MAX)
        out.append("".join(units[i:i + size]))
        i += size
    if len(out) > max(max_pieces, 1):
        size = -(-len(units) // max(max_pieces, 1))
        out = ["".join(units[j:j + size]) for j in range(0, len(units), size)]
    return out


async def paced(events: AsyncIterator[Event], *, delay: float = CHUNK_DELAY, budget: float = TURN_BUDGET,
                sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> AsyncIterator[Event]:
    """把 `delta` 切成小段陆续发出，其余事件原样转发。"""
    spent = 0.0
    async for event in events:
        if event.type is not EventType.DELTA:
            yield event
            continue
        text = str(event.data.get("text") or "")
        parts = pieces(text) if spent < budget else [text]
        for i, part in enumerate(parts):
            if i and spent < budget:
                await sleep(delay)
                spent += delay
            yield Event.delta(part, source=event.source)
