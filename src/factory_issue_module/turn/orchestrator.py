"""一轮的编排（设计 §4.2）。S0 只接上第 1、2 步，第 3–9 步随 S1 起各片补上。

1. 权限前置（`gate.resolve`）；拿不到可用的权限判断时按「没拿到权限」答，三个域都不出数。
2. 代码先接住的两种，都不调模型、不取数：
   - 问句去掉标点与空白后为空：答「没能理解这个问题，可以换个说法」，有可查的域时附能力介绍的
     3 个按钮；三域都无权时同样这一句，不当寒暄，也不答请先申请。
   - 三域都无权：代码规则判断是不是寒暄或问能力，是就做能力介绍，不是就只答请先申请。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog
from forge_core.events import Event
from forge_core.module import ModuleManifest, ModuleRequest

from factory_issue_module.turn import errors, gate, greeting

logger = structlog.get_logger(__name__)


async def run_turn(
    manifest: ModuleManifest, request: ModuleRequest, ctx: Any
) -> AsyncIterator[Event]:
    access = gate.resolve(ctx)
    if access is None:
        yield Event.error(errors.ACCESS_UNAVAILABLE_CODE, errors.ACCESS_UNAVAILABLE, fatal=True)
        return

    if greeting.is_blank(request.query):
        for event in greeting.not_understood(access):
            yield event
        return

    if access.none:
        if greeting.is_greeting(request.query):
            for event in greeting.introduce(manifest, access):
                yield event
        else:
            yield Event.delta(f"{errors.NO_DOMAIN}。")
        return

    # 第 3–9 步（读工作区、号码直通、规划、对库与换算、追问、执行、呈现）从 S1 起接上。
    # 规划层接上之前，按 §14「规划超时或修一次仍不合格」答。
    for event in greeting.not_understood(access):
        yield event
