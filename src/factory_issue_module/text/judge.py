"""文字查找第 ⑤ 步：按意思找到的单逐张判断（设计 §7.1 ⑤；总述「涉及某个话题怎么找」「类似问题：什么算相近」）。

两种判断，同一套批次与输出：
- 「可能相关」：每域按 ④ 的顺序取前 `judge_max` 张。输入是话题的一句话说明（或「涉及 X 的问题」）、说法清单「说明」
  里讲本次带 ＊ 说法的条目（有的话）与每张候选的上下文。判为不相关、没判到、某批超时或出错的都不列、不计数。
- 类似问题（`SIM_SYSTEM`）：每域取最相近的前 10 张（`skills/text_search.SIM_JUDGE`）。输入是用户描述的现象与每张
  候选的上下文；判断标准照总述「类似问题：什么算相近」。某批出错时由调用方按相近程度照列、写明没能逐张判断。

每批 10 张一次模型调用；一步里各域的批次合计至多 3 个同时进行。输出 `{"results": [{"no": 批内序号, "related": true/false}]}`，
序号是批内 1–10，不是单号。模型只判断，不比大小、不报数。
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

#: 类似问题的判断（总述「类似问题：什么算相近」，开发者 2026-11-03 定；例子取自探测 Z1 的人工标注）
SIM_SYSTEM = """你帮「制程问题查询助手」判断几张制程问题单与用户描述的问题现象是不是同一类问题。只输出一个 JSON 对象：
{"results": [{"no": 序号, "related": true 或 false}]}，每张候选都要给出，不要别的文字。
- 只看给出的文字。同一个部件或功能上、表现同一类的异常判 true；机型、工厂、触发条件不同不影响。说法不同、表现相近的也算，
  如「开机花屏」与「开机闪屏」「屏幕抖动」「白屏花屏缺画」。
- 部件或功能不同，或部件相同但异常不同，判 false：如「开机花屏」与「开机黑屏」「卡机黑屏」「屏幕局部颜色偏黑」。只是
  顺带出现同一个词、说的不是这类异常的，判 false。
- 文字是原因或处理过程（如「更换屏幕后测试正常」）时，看它处理的是不是这一类问题。拿不准时判 false。
- 不要数张数，不要写理由。"""
#: 两种判断交给模型的「要找什么」那一项的名字
TOPIC_KEY = "要找的话题"
SIM_KEY = "用户描述的问题现象"


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


async def _batch(llm: Any, description: str, items: Sequence[str], gate: asyncio.Semaphore,
                 guides: Sequence[str] = (), similar: bool = False) -> list[bool] | None:
    body: dict[str, Any] = {SIM_KEY if similar else TOPIC_KEY: description}
    if guides:  # 说法清单「说明」里讲本次带 ＊ 说法的条目（`topic_terms.md`「怎么读」）
        body["判断说明"] = list(guides)
    body["候选"] = [{"no": i, "文字": text[:600]} for i, text in enumerate(items, start=1)]
    messages = [{"role": "system", "content": SIM_SYSTEM if similar else JUDGE_SYSTEM},
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
                guides: Sequence[str] = (), *, similar: bool = False) -> dict[str, list[bool | None]]:
    """{域: [每张候选的判断]}，`None` 表示没判到（超出 `judge_max` 或那一批出错）。`guides` 是说法清单「说明」里
    讲本次带 ＊ 说法的条目，每批原样带上。`similar` 为真时按类似问题判断（`SIM_SYSTEM`），`description` 是用户描述的现象。"""
    gate = asyncio.Semaphore(CONCURRENT)
    jobs: list[tuple[str, int, Any]] = []
    out: dict[str, list[bool | None]] = {d: [None] * len(items) for d, items in groups.items()}
    if llm is None:
        return out
    for dom, items in groups.items():
        head = list(items[:judge_max])
        for start in range(0, len(head), BATCH):
            jobs.append((dom, start, _batch(llm, description, head[start:start + BATCH], gate, guides, similar)))
    results = await asyncio.gather(*(j[2] for j in jobs))
    for (dom, start, _job), got in zip(jobs, results, strict=True):
        if got is None:
            continue
        for k, flag in enumerate(got):
            out[dom][start + k] = flag
    return out
