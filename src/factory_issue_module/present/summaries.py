"""问题描述摘要与导出的全文（设计 §9.2；总述「清单默认列」）。

- 取表格里列出的单在本域文字表里的问题描述（已剥净图片与格式，`f_desc`）。不超过约 60 个字的照抄；更长的一次模型
  调用把这批描述各浓缩成一两句（输出按批内序号对应）。代码核对摘要里的每串数字都出现在原文里，不过、缺了或模型出错
  就退回原文前约 60 个字。
- 文字表里没有这张单（多是最近约半小时内新建的）写「新建不久，稍后可见」，不写「未填」，也不去单上现取原文；
  有这张单而问题描述为空的写「未填」。
- 本域的文字查找表无权时问题描述一列写「暂不可用」（沙箱里就写好了，这里不碰）。
- 导出文件给剥净后的全文，不给摘要（同样「新建不久，稍后可见」）。
- 表格里「原因与措施」一格（`reason_texts`，决策 2026-11-04「表格里的原因与措施给摘要」）同一套做法：不超过约
  60 个字的照抄，更长的每 `REASON_BATCH` 张一次模型调用、各写成一两句，核对同上，不过就退回原文前约 60 个字。
- 只是取文字、替换表格里那一格；不算任何数。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pandas as pd
import structlog

from factory_issue_module.declarations import MART, DOMAINS, Domain
from factory_issue_module.domains import base
from factory_issue_module.present import columns

logger = structlog.get_logger(__name__)

NEW_SOON = "新建不久，稍后可见"
EMPTY = "未填"
SHORT = 60
SUMMARY_MAX = 120
TIMEOUT = 40.0
_BY_LABEL = {d.label: d for d in DOMAINS}
_NUM = re.compile(r"\d+(?:\.\d+)?")
_CHAT_KW: dict[str, Any] = {"temperature": 0.0, "response_format": {"type": "json_object"}}

SUMMARY_SYSTEM = """你帮「制程问题查询助手」把问题单的问题描述各浓缩成一两句话，保留核心内容（什么产品、出了什么问题、在哪发现）。
只输出一个 JSON 对象：{"items": [{"no": 序号, "summary": "摘要"}]}，每条都要给，不要别的文字。
- 摘要里的数字只照抄原文，不做计算，不换算单位，不写原文没有的数字。
- 每条不超过 60 个字；不加评价，不写「该单」「本问题」一类开头。"""

#: 原因与措施每批几张、每张交模型看前多少个字
REASON_BATCH = 10
REASON_INPUT = 800
#: 认这次调用用的一段（单测的假模型按它认）
REASON_MARKER = "原因与措施各写成一句话"
REASON_SYSTEM = """你帮「制程问题查询助手」把问题单的原因与措施各写成一句话，放进表格的一格：先说原因，再说怎么处理的。
只输出一个 JSON 对象：{"items": [{"no": 序号, "summary": "摘要"}]}，每条都要给，不要别的文字。
- 只写原文里有的内容；原文只写了原因或只写了处理办法时，就只写那一样。
- 数字只照抄原文，不做计算，不换算单位，不写原文没有的数字。
- 每条不超过 60 个字；不写栏目名、环节名、人名，不加评价，不写「该单」「本问题」一类开头。"""


def _clip(text: str) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= SHORT else flat[:SHORT] + "…"


def _numbers_ok(summary: str, source: str) -> bool:
    flat = re.sub(r"\s+", "", source)
    return all(n in flat for n in _NUM.findall(summary))


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


async def descriptions(ctx: Any, domain: Domain, ids: Sequence[int]) -> dict[int, str] | None:
    """这几张单在本域文字表里的问题描述：{单 ID: 文字}；文字表里没有的单不在里面。取数出错为 None。"""
    keys = [str(int(i)) for i in ids]
    if not keys:
        return {}
    try:
        frame = await base.fetch_in(ctx, {"source": MART, "from": domain.text_table, "select": ["issue_id", "f_desc"]},
                                    "issue_id", keys)
    except Exception as exc:  # noqa: BLE001 —— 取不到时这一列写「暂不可用」，异常只进日志
        logger.warning("factory_issue_desc_unreadable", domain=domain.value, error=type(exc).__name__)
        return None
    out: dict[int, str] = {}
    for iid, text in zip(base.column(frame, "issue_id"), base.column(frame, "f_desc"), strict=False):
        try:
            out[int(str(iid).strip())] = "" if text is None or (isinstance(text, float) and text != text) else str(text)
        except ValueError:
            continue
    return out


async def _summarize(llm: Any, texts: Sequence[str], system: str = SUMMARY_SYSTEM, field: str = "问题描述",
                     cut: int = 1500) -> list[str | None]:
    if llm is None or not texts:
        return [None] * len(texts)
    body = [{"no": i, field: t[:cut]} for i, t in enumerate(texts, start=1)]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)}]
    try:
        resp = await asyncio.wait_for(llm.chat(messages, **_CHAT_KW), timeout=TIMEOUT)
        data = json.loads(_content(resp))
    except Exception as exc:  # noqa: BLE001 —— 退回原文前约 60 个字
        logger.warning("factory_issue_summary_failed", error=type(exc).__name__)
        return [None] * len(texts)
    out: list[str | None] = [None] * len(texts)
    for r in (data.get("items") if isinstance(data, dict) else None) or []:
        if not isinstance(r, dict):
            continue
        no, summary = r.get("no"), r.get("summary")
        if isinstance(no, int) and not isinstance(no, bool) and 1 <= no <= len(texts) and isinstance(summary, str):
            out[no - 1] = summary.strip()
    return out


async def cells(ctx: Any, domain: Domain, ids: Sequence[int]) -> list[str]:
    """表格里这几张单问题描述一格的文字，顺序同 `ids`。"""
    got = await descriptions(ctx, domain, ids)
    if got is None:
        return [columns.DESC_UNAVAILABLE] * len(ids)
    out: list[str] = []
    long_at: list[int] = []
    for k, iid in enumerate(ids):
        text = got.get(int(iid))
        if text is None:
            out.append(NEW_SOON)
        elif not text.strip():
            out.append(EMPTY)
        elif len(re.sub(r"\s+", " ", text).strip()) <= SHORT:
            out.append(re.sub(r"\s+", " ", text).strip())
        else:
            out.append("")
            long_at.append(k)
    if long_at:
        sources = [got[int(ids[k])] for k in long_at]
        for k, text in zip(long_at, await _shorten(getattr(ctx, "llm", None), sources), strict=True):
            out[k] = text
    return out


async def _shorten(llm: Any, sources: Sequence[str], **kw: Any) -> list[str]:
    """一次模型调用把这批长文字各浓缩成一两句；每条核对数字与长度，不过、缺了或出错就退回原文前约 60 个字。"""
    summaries = await _summarize(llm, sources, **kw)
    out: list[str] = []
    for source, summary in zip(sources, summaries, strict=True):
        ok = bool(summary) and len(summary or "") <= SUMMARY_MAX and _numbers_ok(summary or "", source)
        if summary and not ok:
            logger.info("factory_issue_summary_rejected")
        out.append(summary if ok and summary else _clip(source))
    return out


async def reason_texts(ctx: Any, texts: Sequence[str]) -> list[str]:
    """表格里「原因与措施」一格的摘要，顺序同 `texts`（决策 2026-11-04「表格里的原因与措施给摘要」）：空的照空，
    不超过约 60 个字的照抄，更长的每 `REASON_BATCH` 张一次模型调用、各批并行。"""
    out = [re.sub(r"\s+", " ", t or "").strip() for t in texts]
    long_at = [k for k, t in enumerate(out) if len(t) > SHORT]
    if not long_at:
        return out
    llm = getattr(ctx, "llm", None)
    batches = [long_at[i:i + REASON_BATCH] for i in range(0, len(long_at), REASON_BATCH)]
    results = await asyncio.gather(*(_shorten(llm, [texts[k] for k in b], system=REASON_SYSTEM, field="原因与措施",
                                              cut=REASON_INPUT) for b in batches))
    for b, got in zip(batches, results, strict=True):
        for k, text in zip(b, got, strict=True):
            out[k] = text
    return out


async def fill_tables(ctx: Any, segs: Sequence[dict[str, Any]], text_ok: Iterable[Domain]) -> None:
    """把各段表格里问题描述那一格换成摘要（本域文字查找表可用时；不可用的沙箱已写「暂不可用」）。各域并行。"""
    ok = set(text_ok)
    jobs = []
    for seg in segs:
        dom = _BY_LABEL.get(str(seg.get("domain")))
        table = seg.get("table") or {}
        if dom is None or dom not in ok or seg.get("empty"):
            continue
        title = columns.shown("desc", dom)
        if title not in (table.get("columns") or []):
            continue
        jobs.append((seg, table["columns"].index(title), cells(ctx, dom, list(seg.get("ids_shown") or []))))
    if not jobs:
        return
    results = await asyncio.gather(*(j[2] for j in jobs))
    for (seg, at, _job), got in zip(jobs, results, strict=True):
        rows = seg["table"]["rows"]
        seg["table"]["rows"] = [[*row[:at], text, *row[at + 1:]] for row, text in zip(rows, got, strict=False)] + rows[len(got):]


async def fill_rows(ctx: Any, items: Sequence[tuple[list[Any], int, Domain, int | None]],
                    text_ok: Iterable[Domain]) -> None:
    """按号查单的表（一号一行、很多个号按清单呈现）：每项是 (那一行, 问题描述在第几列, 域, 单 ID)。本域文字查找表
    可用、找到了这张单的才换成摘要；其余照沙箱写的。各域一次，并行。"""
    ok = set(text_ok)
    by_dom: dict[Domain, list[tuple[list[Any], int, int]]] = {}
    for row, at, dom, pid in items:
        if dom in ok and pid is not None and 0 <= at < len(row):
            by_dom.setdefault(dom, []).append((row, at, int(pid)))
    if not by_dom:
        return
    doms = list(by_dom)
    results = await asyncio.gather(*(cells(ctx, d, [pid for _r, _a, pid in by_dom[d]]) for d in doms))
    for d, got in zip(doms, results, strict=True):
        for (row, at, _pid), text in zip(by_dom[d], got, strict=True):
            row[at] = text


async def fill_exports(ctx: Any, frames: dict[str, pd.DataFrame], text_ok: Iterable[Domain]) -> None:
    """导出文件里问题描述一列给剥净后的全文（导出帧与结果单 `ids_<域>` 同序、同行数，沙箱给的）。取不到时整列
    写「暂不可用」。"""
    for dom in text_ok:
        title = columns.shown("desc", dom)
        frame = frames.get("export_" + dom.label)
        ids = frames.get("ids_" + dom.label)
        if frame is None or ids is None or title not in frame.columns or len(ids) != len(frame):
            continue
        keys = [int(x) for x in ids["_id"].tolist()]
        got = await descriptions(ctx, dom, keys)
        if got is None:
            frame[title] = [columns.DESC_UNAVAILABLE] * len(keys)
            continue
        values: Mapping[int, str] = got
        frame[title] = [(values[k] if values[k].strip() else EMPTY) if k in values else NEW_SOON for k in keys]
