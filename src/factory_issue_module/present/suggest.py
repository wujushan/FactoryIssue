"""答后建议由模型挑（设计 §9.5「模型挑」「核对」「退路」，决策 2026-11-02「答后建议改由模型挑」）。

- 输入：最近几轮对话、本轮问句、本轮回答的开头、代码列的候选（`present/moves.py`，至多 `POOL_MAX` 条）。
- 输出：挑哪几条、每条的问句；找类似另写现象。同一个底的两条可以合成一条。
- 每条单独核对，不过的丢掉：编号与叠加、长度、必带、数与问题编号都要在这条候选里出现过、不露表名字段名、
  不与会话里问过推荐过的相同（离不开本轮上下文的「放宽」只按意图键比，不按问句比）。按钮文字（`label`，INFO 网页
  前端 2026-11-03 起显示它）单独核，不过时用候选的默认按钮文字，没有则由调用方用问句全文，这一条不丢。以省略号
  结尾的标签不合格。模型出错、超时、关掉、挑的全被丢掉时按代码的默认顺序取（`defaults`）；模型挑了
  0 条时不给接着问。
- 一次调用、不重试；超时由调用方给的秒数控制。system 固定（§5.6）。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from factory_issue_module.plan import clarify, schema
from factory_issue_module.present import moves
from factory_issue_module.present.narrative import _LEAK

logger = structlog.get_logger(__name__)

#: system 里认这次调用的一段文字（单测的假模型按它认）
MARKER = "答后建议的挑选人"
POOL_MAX = 12
QUERY_MIN, QUERY_MAX = 2, 30
PHENOMENON_MAX = 30
HISTORY_CHARS = 300
ANSWER_CHARS = 600
_CHAT_KW: dict[str, Any] = {"temperature": 0.3, "response_format": {"type": "json_object"}}
_NUM = re.compile(r"\d+(?:\.\d+)?")
_END_PUNCT = "？?。.！!，, "

SYSTEM = f"""你是「制程问题查询助手」的{MARKER}。程序已经回答完用户这一轮的问题，并按本轮结果列出了下一步可以接着问的候选，每条点了都能直接查。你从候选里挑出最贴近对话走向、对用户最有用的几条，给每条写一句显示在按钮上、点了就发出去的问句。

要求：
1. 只能用【候选】里的编号。标了「可叠加」且底相同的两条可以合成一条（ids 写两个编号，问句要把两件事都说到）；其余的不能合。
2. 看【最近几轮】【本轮问题】【本轮回答】判断用户在往哪个方向看：盯着一张单深挖时，先挑这张单还没看的内容和与它相关的单；在看整体分布时，先挑换角度、收窄和下钻到最该关注的单。
3. 问句写成用户会说的一句短话，不超过 20 个字。候选里「必带」的每一项都要原样出现在问句里（单号、机型、工厂、维度名、时间说法不能改写）。
4. 问句里不要出现候选和对话里没有的数字、单号或名称，不要写统计结论或判断。
5. 已经问过的不要再挑；几条之间意思不要重复。
6. 「要写现象」的那条另写 phenomenon：一句不看上文也能懂的现象描述，不超过 20 个字，只写现象，不写处理办法、机型、工厂、时间。
7. 每条另写 label：显示在按钮上的文字。尽量不超过 15 个字；说不完可以写到 30 个字，必须是完整的一句，不要用省略号。问句本身不超过 30 个字时 label 可以照抄问句；候选给了「默认按钮」且里面有张数的，label 里要写上这个张数。
8. 没有合适的就少挑，可以一条都不挑。

只输出一个 JSON 对象，不要输出其他内容：{{"suggestions": [{{"ids": ["c1"], "query": "问句", "label": "按钮文字", "phenomenon": "只有要写现象的那条才写"}}]}}"""

_ROLE = {"user": "用户", "assistant": "助手"}


@dataclass
class Chosen:
    move: str
    key: str
    query: str
    plan: dict
    #: 按钮上显示的文字（INFO 网页前端 2026-11-03 起显示它）；空时用问句全文
    label: str = ""


LABEL_MAX = clarify.LABEL_MAX


def _clip(text: Any, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[:n] + "…"


def user_text(query: str, history: Sequence[Mapping[str, Any]], answer: str,
              items: Sequence[tuple[str, moves.Candidate]], n: int) -> str:
    lines = ["【最近几轮】"]
    shown = [m for m in history if m.get("role") in _ROLE and m.get("content")]
    lines += [f"{_ROLE[str(m['role'])]}：{_clip(m['content'], HISTORY_CHARS)}" for m in shown] or ["（无）"]
    lines.append(f"【本轮问题】{query}")
    lines.append(f"【本轮回答（开头）】{_clip(answer, ANSWER_CHARS) or '（无）'}")
    lines.append("【候选】")
    bases: dict[str, str] = {}
    for cid, c in items:
        parts = [cid, c.move, f"默认问句：{c.query}"]
        if c.label:
            parts.append(f"默认按钮：{c.label}")
        if c.hint:
            parts.append(f"依据：{c.hint}")
        if c.must:
            parts.append("必带：" + "、".join(c.must))
        if c.base:
            parts.append("可叠加，底 " + bases.setdefault(c.base, chr(ord("A") + len(bases))))
        if c.slot:
            parts.append("要写现象")
        lines.append("｜".join(parts))
    lines.append(f"【要挑】至多 {n} 条")
    return "\n".join(lines)


def _numbers(text: str) -> set[str]:
    return set(_NUM.findall(text or ""))


def _clean(text: Any) -> str:
    return str(text or "").strip().strip("「」\"'").rstrip(_END_PUNCT).strip()


def check(item: Mapping[str, Any], by_id: Mapping[str, moves.Candidate], pool: moves.Pool,
          taken: set[str]) -> Chosen | str:
    """一条模型的选择 → `Chosen`；不合格时返回原因。`taken` 是会话里问过、推荐过的与本轮已挑的问句键。"""
    ids = [str(x).strip() for x in schema.as_list(item.get("ids") or item.get("id"))]
    if not ids or len(ids) > 2 or any(i not in by_id for i in ids):
        return "编号"
    cands = [by_id[i] for i in dict.fromkeys(ids)]
    got = cands[0] if len(cands) == 1 else moves.compose(pool, cands[0], cands[1])
    if got is None or got.plan is None:
        return "叠加"
    if got.key in taken:
        return "重复"
    query = _clean(item.get("query"))
    size = len(moves.compact(query))
    if not QUERY_MIN <= size <= QUERY_MAX:
        return "长度"
    if any(moves.compact(m) not in moves.compact(query) for m in got.must):
        return "必带"
    source = " ".join([*(c.query for c in cands), *(m for c in cands for m in c.must), *(c.hint for c in cands),
                       json.dumps([c.plan for c in cands], ensure_ascii=False)])
    if not _numbers(query) <= _numbers(source):
        return "数字"
    if not set(moves.issue_numbers(query)) <= set(moves.issue_numbers(source)):
        return "单号"
    if _LEAK.search(query):
        return "字段名"
    if moves.question_key(query) in taken and not all(c.by_context for c in cands):
        return "重复"
    label = _label(item.get("label"), got, source)
    plan = got.plan
    slot = next((c for c in cands if c.slot), None)
    if slot is not None:
        phenomenon = _clean(item.get("phenomenon")) or (slot.slot_default or "")
        if not 2 <= len(moves.compact(phenomenon)) <= PHENOMENON_MAX or moves.issue_numbers(phenomenon):
            return "现象"
        if not _numbers(phenomenon) <= _numbers(slot.source):
            return "现象"
        plan = moves.with_phenomenon(plan, phenomenon)
    return Chosen(move=got.move, key=got.key, query=query, plan=plan, label=label)


def _label(raw: Any, got: moves.Candidate, source: str) -> str:
    """模型写的按钮文字单独核，不过不丢这一条：1–30 个字、不以省略号结尾，必带的都出现（按钮上少了取值，「列出其他
    的单」就读不出是哪个「其他」，决策 2026-11-06「其他理解与接着问的按钮不自相矛盾」），数与单号要在这条候选里出现
    过，不露表名字段名；带张数的候选要写上张数。不过时用候选的默认按钮文字（空时调用方用问句全文）。"""
    label = _clean(raw)
    ok = (bool(label) and not label.endswith("…") and len(label) <= LABEL_MAX
          and all(moves.compact(m) in moves.compact(label) for m in got.must)
          and _numbers(label) <= _numbers(source)
          and set(moves.issue_numbers(label)) <= set(moves.issue_numbers(source)) and not _LEAK.search(label)
          and (got.count is None or str(got.count) in _numbers(label)))
    return label if ok else got.label


def defaults(items: Sequence[moves.Candidate], n: int, taken: set[str]) -> list[Chosen]:
    """按代码的默认顺序取前几条、用默认问句；要写现象又没有默认现象的跳过。"""
    out: list[Chosen] = []
    for c in items:
        if len(out) >= n:
            break
        if c.plan is None or c.key in taken or (not c.by_context and moves.question_key(c.query) in taken):
            continue
        plan = c.plan
        if c.slot:
            if not c.slot_default:
                continue
            plan = moves.with_phenomenon(plan, c.slot_default)
        out.append(Chosen(move=c.move, key=c.key, query=c.query, plan=plan, label=c.label))
        taken = taken | {c.key, moves.question_key(c.query)}
    return out


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


async def choose(llm: Any, pool: moves.Pool, *, query: str, history: Sequence[Mapping[str, Any]], answer: str,
                 n: int, seconds: float, seen: set[str], use_model: bool = True) -> list[Chosen]:
    """挑至多 `n` 条接着问。"""
    items = pool.items[:POOL_MAX]
    if not items or n <= 0:
        return []
    taken = set(seen)
    reason, dropped = "", []
    out: list[Chosen] | None = None
    if not use_model:
        reason = "关掉"
    elif llm is None:
        reason = "没有模型"
    else:
        listed = [(f"c{i}", c) for i, c in enumerate(items, start=1)]
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user_text(query, history, answer, listed, n)}]
        try:
            text = _content(await asyncio.wait_for(llm.chat(messages, **_CHAT_KW), timeout=seconds))
            raw = schema.as_list(schema.parse_reply(text).get("suggestions"))
        except TimeoutError:
            reason = "超时"
        except Exception as exc:  # noqa: BLE001 —— 模型出错、格式不对：走退路，异常只进日志
            reason = "出错" if not isinstance(exc, ValueError) else "格式"
            logger.warning("factory_issue_suggest_failed", error=type(exc).__name__)
        else:
            by_id = dict(listed)
            out = []
            for item in raw[: n + 2]:
                got = check(item, by_id, pool, taken) if isinstance(item, Mapping) else "格式"
                if isinstance(got, str):
                    dropped.append(got)
                    continue
                out.append(got)
                taken |= {got.key, moves.question_key(got.query)}
                if len(out) >= n:
                    break
            if raw and not out:
                reason, out = "全部丢掉", None
    if out is None:
        out = defaults(items, n, set(seen))
        source = "退路"
    else:
        source = "模型"
    logger.info("factory_issue_suggest", candidates=len(items), picked=len(out), source=source,
                reason=reason or None, dropped=dropped or None, moves=[c.move for c in out])
    return out
