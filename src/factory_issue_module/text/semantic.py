"""文字查找第 ③④ 步：按意思一路（设计 §7.1 ③④；G2「查询期怎么用」③④ 与补记）。

经平台注入的 `ctx.retrieval.search` 检索本域向量表（不自己 new 索引、不读 env）。每域一张向量表、一次调用：
- 有条件时按本步范围内的单限定候选（`restrict_ids=单 ID, restrict_column="issue_id"`，按单而不是按段编号），
  平台走精确近邻；条件筛出 0 张时不检索。
- 只在某些栏目里找时 `filters={"field": [...]}`；按单去重 `group_by="issue_id"`，`top_n` 数的是单数。
- 候选超过平台上限（`RetrievalRestrictTooLarge`）：去掉限定、`top_k` 加到 200，取回后只留候选里的单，回答注明
  不保证完整。
- `ctx.retrieval` 为 None、检索或重排服务出错：这一路跳过（返回 None），由调用方答「暂不可用」。
- 命中从 `h.metadata["issue_id"]` 取单；顺序照平台给的（重排成功时按重排分，否则按向量距离），这里不另排。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
from forge_core.errors import RetrievalRestrictTooLarge

from factory_issue_module.declarations import MART, Domain

logger = structlog.get_logger(__name__)

TOP_K = 50
TOP_K_UNRESTRICTED = 200


@dataclass
class Hit:
    issue_id: int
    field: str
    text: str
    rerank: float | None
    score: float | None


@dataclass
class Found:
    hits: list[Hit] = field(default_factory=list)
    #: 候选太多、去掉限定检索的：结果不保证完整
    partial: bool = False


def _as_hit(h: Any) -> Hit | None:
    meta = getattr(h, "metadata", None) or {}
    raw = meta.get("issue_id") if isinstance(meta, dict) else None
    try:
        iid = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return Hit(issue_id=iid, field=str(meta.get("field") or ""), text=str(getattr(h, "text", "") or ""),
               rerank=getattr(h, "rerank_score", None), score=getattr(h, "score", None))


async def search(ctx: Any, domain: Domain, query: str, *, candidates: Sequence[int] | None,
                 codes: Sequence[str] | None, top_n: int, top_k: int = TOP_K) -> Found | None:
    """检索本域向量表。`candidates` 为 None 表示不限定；返回 None 表示这一路用不了（没配检索、服务出错）。"""
    retrieval = getattr(ctx, "retrieval", None)
    if retrieval is None:
        return None
    if candidates is not None and not candidates:
        return Found()
    kw: dict[str, Any] = {"source": MART, "table": domain.vec_table, "top_k": max(top_k, top_n), "top_n": top_n,
                          "group_by": "issue_id"}
    if codes:
        kw["filters"] = {"field": list(codes)}
    restrict = None if candidates is None else [str(int(i)) for i in candidates]
    try:
        if restrict is not None:
            raw = await retrieval.search(query, restrict_ids=restrict, restrict_column="issue_id", **kw)
        else:
            raw = await retrieval.search(query, **kw)
        partial = False
    except RetrievalRestrictTooLarge:
        logger.info("factory_issue_retrieval_unrestricted", domain=domain.value)
        try:
            raw = await retrieval.search(query, **{**kw, "top_k": TOP_K_UNRESTRICTED})
        except Exception as exc:  # noqa: BLE001
            logger.warning("factory_issue_retrieval_failed", domain=domain.value, error=type(exc).__name__)
            return None
        partial = True
    except Exception as exc:  # noqa: BLE001 —— 检索、重排服务出错：这一路跳过，按词的结果照给
        logger.warning("factory_issue_retrieval_failed", domain=domain.value, error=type(exc).__name__)
        return None
    keep = None if candidates is None else {int(i) for i in candidates}
    hits = [h for h in (_as_hit(x) for x in raw or []) if h is not None and (keep is None or h.issue_id in keep)]
    return Found(hits=hits, partial=partial)
