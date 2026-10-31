"""文字查找第 ⑤ 步：「可能相关」的判断（设计 §7.1 ⑤；总述「涉及某个话题怎么找」）。

每域按 ④ 的顺序取前 `judge_max` 张，每批 10 张一次模型调用；一步里各域的批次合计至多 3 个同时进行。输入是话题的
一句话说明（或「涉及 X 的问题」）、说法清单「说明」里讲本次带 ＊ 说法的条目（有的话）与每张候选的上下文；输出 `{"results": [{"no": 批内序号, "related": true/false}]}`，
序号是批内 1–10，不是单号。判为不相关、没判到、某批超时或出错的都不列、不计数。模型只判断，不比大小、不报数。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

BATCH = 10
CONCURRENT = 3
TIMEOUT = 40.0
_CHAT_KW: dict[str, Any] = {"temperature": 0.0, "response_format": {"type": "json_object"}}

JUDGE_SYSTEM = """你帮「制程问题查询助手」判断几张制程问题单是否与用户要找的话题有关。只输出一个 JSON 对象：
{"results": [{"no": 序号, "related": true 或 false}]}，每张候选都要给出，不要别的文字。
- 只看给出的文字。文字说的是这个话题本身的问题现象、原因或处理，判 true；只是顺带出现同一个词、意思不同（如「声音」指
  提示音设置、「漏电」只是漏电流偏大而话题是安全），判 false。拿不准时判 false。
- 给了「判断说明」时，按其中与要找的话题对应的那一种问法判断。
- 不要数张数，不要写理由。"""


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


async def _batch(llm: Any, description: str, items: Sequence[str], gate: asyncio.Semaphore,
                 guides: Sequence[str] = ()) -> list[bool] | None:
    body: dict[str, Any] = {"要找的话题": description}
    if guides:  # 说法清单「说明」里讲本次带 ＊ 说法的条目（`topic_terms.md`「怎么读」）
        body["判断说明"] = list(guides)
    body["候选"] = [{"no": i, "文字": text[:600]} for i, text in enumerate(items, start=1)]
    messages = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)}]
    async with gate:
        try:
            resp = await asyncio.wait_for(llm.chat(messages, **_CHAT_KW), timeout=TIMEOUT)
            data = json.loads(_content(resp))
        except Exception as exc:  # noqa: BLE001 —— 这一批不列、不计数，异常只进日志
            logger.warning("factory_issue_judge_failed", error=type(exc).__name__)
            return None
    out = [False] * len(items)
    for r in (data.get("results") if isinstance(data, dict) else None) or []:
        if not isinstance(r, dict):
            continue
        no = r.get("no")
        if isinstance(no, int) and not isinstance(no, bool) and 1 <= no <= len(items) and r.get("related") is True:
            out[no - 1] = True
    return out


async def judge(llm: Any, description: str, groups: dict[str, list[str]], judge_max: int,
                guides: Sequence[str] = ()) -> dict[str, list[bool | None]]:
    """{域: [每张候选的判断]}，`None` 表示没判到（超出 `judge_max` 或那一批出错）。`guides` 是说法清单「说明」里
    讲本次带 ＊ 说法的条目，每批原样带上。"""
    gate = asyncio.Semaphore(CONCURRENT)
    jobs: list[tuple[str, int, Any]] = []
    out: dict[str, list[bool | None]] = {d: [None] * len(items) for d, items in groups.items()}
    if llm is None:
        return out
    for dom, items in groups.items():
        head = list(items[:judge_max])
        for start in range(0, len(head), BATCH):
            jobs.append((dom, start, _batch(llm, description, head[start:start + BATCH], gate, guides)))
    results = await asyncio.gather(*(j[2] for j in jobs))
    for (dom, start, _job), got in zip(jobs, results, strict=True):
        if got is None:
            continue
        for k, flag in enumerate(got):
            out[dom][start + k] = flag
    return out
