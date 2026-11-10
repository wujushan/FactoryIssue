"""一次润色的步骤编排（润色设计 §4、§14）。

文件不叫 `run.py`：包对外露的 `polish.run` 是函数，同名子模块会被它遮住，单测改不到这里的常量（评审 P0 第 1 条）。

P0（任务单）：只做第 ①、② 步（读规则、校验参数），校验过了暂答 `POLISH_FAILED`；第 ③–⑧ 步在 P2–P4 接上。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import structlog
from forge_core.events import Event
from forge_core.module import ModuleManifest, ModuleRequest

from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import POLISH_RULES
from factory_issue_module.polish import params
from factory_issue_module.turn import errors

logger = structlog.get_logger(__name__)


def _error(code: str) -> Event:
    """错误事件一律 `fatal=True`（§4）；文案只出自 `turn/errors.py`。"""
    return Event.error(code, errors.POLISH_MESSAGES[code], fatal=True)


def ext_param(request: ModuleRequest) -> dict[str, Any]:
    raw = (request.inputs or {}).get("ext_param")
    return raw if isinstance(raw, dict) else {}


async def run(manifest: ModuleManifest, request: ModuleRequest, ctx: Any) -> AsyncIterator[Event]:
    started = time.monotonic()
    shape: dict[str, Any] = {"field": None}

    def finish(outcome: str) -> None:
        """§14：每次润色结束记一条，只记形状，不记原文、结果、参考内容与问题编号。"""
        logger.info("factory_issue_polish", **shape, outcome=outcome,
                    ms=int((time.monotonic() - started) * 1000))

    # ① ② 读规则、校验参数（§5）
    rules = await config_files.load(ctx, POLISH_RULES)
    try:
        req = params.parse(ext_param(request), rules)
    except params.BadParam as exc:
        logger.warning("factory_issue_polish_bad_param", reason=exc.reason)
        finish(errors.POLISH_BAD_PARAM_CODE)
        yield _error(errors.POLISH_BAD_PARAM_CODE)
        return
    if req.issue_no_ignored:
        logger.warning("factory_issue_polish_bad_param", reason=params.REASON_ISSUE_NO_IGNORED)
    fld = rules.field(req.field)
    shape.update(field=req.field, rich=fld.rich, limit=params.limit_of(req, fld), context_dropped=req.dropped)

    # ③–⑧ 在 P2–P4 接上（任务单）；P0 校验过了暂答 POLISH_FAILED
    finish(errors.POLISH_FAILED_CODE)
    yield _error(errors.POLISH_FAILED_CODE)
