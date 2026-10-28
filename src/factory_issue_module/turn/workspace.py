"""会话工作区（设计 §10）。S1 只读 `last` 与 `turn`，供规划器的「上一轮」与 §5.3 第 17、18 条；写入随 S5。

- 每个键的值都是 `{"v": 版本, …}`；读到的版本与 `VERSION` 不同，按没有上文处理并记日志。
- `ctx.workspace` 为 None（没有会话号）或读不到时按没有上文处理（§14）。
- 隔了很多轮：`last` 里的问句原话不在最近几轮的用户发言里，就不给规划器上一轮计划。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

#: 计划格式（`plan/schema.py`）或下面几个键的结构改了就加一
VERSION = 1

TURN = "turn"
LAST = "last"

#: `last.outcome` 的取值（§10）
OUTCOME_FOUND = "查到结果"
OUTCOME_EMPTY = "查出 0 张"
OUTCOME_CLARIFY = "追问"
OUTCOME_FAILED = "出错"
NO_RESULT_OUTCOMES = (OUTCOME_EMPTY, OUTCOME_CLARIFY, OUTCOME_FAILED)


@dataclass(frozen=True)
class Previous:
    """规划要用的上一轮信息；读不到时各项为 None。"""

    #: 上一轮的计划：上一轮查到结果时取 `turn` 里的执行计划，其余结局取 `last` 里的计划
    plan: dict | None = None
    #: 上一轮没有查到结果时的结局（追问、查出 0 张、出错），交给规划器与第 18 条
    outcome: str | None = None
    #: 最近一次查到结果的问句原话（第 18 条拼「按更早那次的条件查」）
    earlier_query: str | None = None


NOTHING = Previous()


async def _get(ctx: Any, key: str) -> dict | None:
    port = getattr(ctx, "workspace", None)
    if port is None:
        return None
    try:
        value = await port.get(key)
    except Exception as exc:  # noqa: BLE001 —— 工作区读不到按没有上文处理（§14）
        logger.warning("factory_issue_workspace_unreadable", key=key, error=type(exc).__name__)
        return None
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("v") != VERSION:
        logger.info("factory_issue_workspace_version_mismatch", key=key,
                    got=value.get("v") if isinstance(value, Mapping) else type(value).__name__)
        return None
    return dict(value)


def _user_said(history: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(m.get("content") or "").strip() for m in history if m.get("role") == "user"}


async def read_previous(ctx: Any, history: Sequence[Mapping[str, Any]]) -> Previous:
    last = await _get(ctx, LAST)
    if last is None:
        return NOTHING
    query = str(last.get("query") or "").strip()
    if not query or query not in _user_said(history):
        return NOTHING  # 隔了很多轮
    outcome = last.get("outcome")
    earlier = last.get("earlier_query") or None
    if outcome == OUTCOME_FOUND:
        turn = await _get(ctx, TURN)
        plan = turn.get("plan") if turn else None
        return Previous(plan=plan if isinstance(plan, dict) else None, outcome=None, earlier_query=earlier)
    plan = last.get("plan")
    return Previous(
        plan=plan if isinstance(plan, dict) else None,
        outcome=outcome if outcome in NO_RESULT_OUTCOMES else None,
        earlier_query=earlier,
    )
