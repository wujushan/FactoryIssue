"""一次润色的步骤编排（润色设计 §4、§14）。

文件不叫 `run.py`：包对外露的 `polish.run` 是函数，同名子模块会被它遮住，单测改不到这里的常量（评审 P0 第 1 条）。

① 校验参数 → ② 读规则 → ③ 拆富文本、判空判长 → 进度「正在润色」→ ④ 参考内容 → ⑤ 组提示 → ⑥ 调模型（每
`HEARTBEAT` 秒补一个进度）→ ⑦ 检查，不过修一次 → ⑧ 拼回，结果作为一条 `delta` 发出。
第 ④ 步见 `polish/reference.py`。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

import structlog
from forge_core.events import Event
from forge_core.module import ModuleManifest, ModuleRequest

from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import POLISH_RULES
from factory_issue_module.polish import check, params, prompt, reference, rich
from factory_issue_module.turn import errors

logger = structlog.get_logger(__name__)

#: §4（§12.3 实测后定）：单次调用最多等 110 秒，低于 `ctx.llm` 客户端固定的 120 秒（开发者 2026-11-10 定）
CALL_TIMEOUT = 110.0
#: 等模型时每隔多少秒补发一个进度事件（平台 0.3.9 的 SSE 没有保活，§4）
HEARTBEAT = 10.0
#: 进度事件的阶段与说法
PROGRESS_POLISH = "polish"
PROGRESS_TEXT = "正在润色"
#: 第 ⑥ 步的调用参数（§4）；`max_tokens` 按原文字数另给
_CHAT_KW: dict[str, Any] = {"temperature": 0.0, "response_format": {"type": "json_object"}}


def max_tokens(input_chars: int) -> int:
    """原文文字数 × 2 + 256，夹在 512 到 6000 之间（§4，实测没有截断）。"""
    return max(512, min(6000, input_chars * 2 + 256))


def _error(code: str) -> Event:
    """错误事件一律 `fatal=True`（§4）；文案只出自 `turn/errors.py`。"""
    return Event.error(code, errors.POLISH_MESSAGES[code], fatal=True)


def _progress() -> Event:
    return Event.progress(PROGRESS_POLISH, PROGRESS_TEXT)


def ext_param(request: ModuleRequest) -> dict[str, Any]:
    raw = (request.inputs or {}).get("ext_param")
    return raw if isinstance(raw, dict) else {}


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


def _check_no(label: str) -> int:
    """检查项「3 多出」→ 3（日志 `failed_checks` 只记编号）。"""
    return int(label.split()[0])


# ---------------------------------------------------------------- 第 ⑥ 步：边等边发心跳


@dataclass
class CallBox:
    """异步生成器不能 `return` 值：调用结果放在这里。`error` 为 None 且 `response` 有值即成功。"""

    response: Any = None
    error: str | None = None


async def call_with_heartbeat(llm: Any, messages: list[dict[str, str]], kw: dict[str, Any],
                              box: CallBox) -> AsyncIterator[Event]:
    """调用放进任务、按心跳间隔等，没等到就发一个进度事件；到 `CALL_TIMEOUT` 记超时并返回。

    不能写成 `await asyncio.wait_for(...)`：生成器停在那一个 `await` 上，等待期间发不出进度事件（§4、§17 第 1 条）。
    收尾放在 `finally`：用户停止时生成器在 `yield` 处被关闭，抛的是 `GeneratorExit`；平台强制收住时是
    `CancelledError`。两种都要取消还在等的模型调用。"""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(llm.chat(messages, **kw))
    deadline = loop.time() + CALL_TIMEOUT
    try:
        while not task.done():
            left = deadline - loop.time()
            if left <= 0:
                box.error = "timeout"
                return
            await asyncio.wait({task}, timeout=min(HEARTBEAT, left))
            if not task.done():
                yield _progress()
        try:
            box.response = task.result()
        except Exception as exc:  # noqa: BLE001 —— 模型出错：POLISH_FAILED，异常类名进日志
            box.error = type(exc).__name__
    finally:
        if not task.done():
            task.cancel()
        # 外层取消与模型调用结束落在同一拍时，任务的异常没人取回，asyncio 会记「never retrieved」（P3 评审第 5 条）
        task.add_done_callback(_retrieve)


def _retrieve(task: asyncio.Future) -> None:
    if not task.cancelled():
        task.exception()


# ---------------------------------------------------------------- 编排


#: 用户停止或平台强制收住本轮时结束日志的 `outcome`（§14）
OUTCOME_STOPPED = "stopped"


class _Log:
    """§14：每次润色结束记一条 `factory_issue_polish`，只记形状，不记原文、结果、参考内容与问题编号。"""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.shape: dict[str, Any] = {"field": None, "reference": "none", "db": "skipped", "attempts": 0,
                                      "failed_checks": []}
        self.done = False

    def finish(self, outcome: str) -> None:
        self.done = True
        logger.info("factory_issue_polish", **self.shape, outcome=outcome,
                    ms=int((time.monotonic() - self.started) * 1000))


async def run(manifest: ModuleManifest, request: ModuleRequest, ctx: Any) -> AsyncIterator[Event]:
    log = _Log()
    try:
        async with aclosing(_steps(request, ctx, log)) as events:
            async for event in events:
                yield event
    except (GeneratorExit, asyncio.CancelledError):
        if not log.done:  # 停止也记一条（P3 评审第 3 条）
            log.finish(OUTCOME_STOPPED)
        raise


async def _steps(request: ModuleRequest, ctx: Any, log: _Log) -> AsyncIterator[Event]:
    shape, finish = log.shape, log.finish

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
    limit = params.limit_of(req, fld)
    shape.update(field=req.field, rich=fld.rich, limit=limit, context_dropped=req.dropped)

    # ③ 拆富文本、判空判长（§6）
    try:
        prep = rich.prepare(request.query, rich=fld.rich, max_input=rules.max_input, limit=limit)
    except rich.NotPolishable as exc:
        finish(exc.code)
        yield _error(exc.code)
        return
    shape.update(input_chars=prep.input_chars, placeholders=len(prep.split.tokens))
    yield _progress()

    # ④ 同单参考内容（§7）：页面发来的为准，带编号时再查库补；查不到、没权限、出错都照样润色
    ref = await reference.build(ctx, req.context, req.issue_no, req.field)
    shape.update(reference=ref.source, db=ref.db)
    if ref.missing:
        shape["db_missing"] = list(ref.missing)

    # ⑤ 组提示（§8）
    messages = prompt.first_messages(prep, fld, rules, ref.items)
    llm = getattr(ctx, "llm", None)
    if llm is None:  # 算作第 1 次调用就失败，日志两处都记 1
        shape["attempts"] = 1
        logger.warning("factory_issue_polish_call_failed", attempt=1, error="llm_unavailable")
        finish(errors.POLISH_FAILED_CODE)
        yield _error(errors.POLISH_FAILED_CODE)
        return
    kw = {**_CHAT_KW, "max_tokens": max_tokens(prep.input_chars)}

    # ⑥ ⑦ 调模型、检查，不过修一次（§4、§9）
    for attempt in (1, 2):
        shape["attempts"] = attempt
        box = CallBox()
        async with aclosing(call_with_heartbeat(llm, messages, kw, box)) as beats:
            async for beat in beats:
                yield beat
        if box.error is not None:
            logger.warning("factory_issue_polish_call_failed", attempt=attempt, error=box.error)
            finish(errors.POLISH_FAILED_CODE)
            yield _error(errors.POLISH_FAILED_CODE)
            return
        output = _content(box.response)
        verdict = check.check(output, prep, fld.name)
        if verdict.ok:
            # ⑧ 拼回（§6.3），结果整段一次发出
            # 与 input_chars 同一口径：去掉占位标记与空白后的字数（P3 评审第 4 条）
            shape["output_chars"] = rich.text_chars(verdict.text or "", prep.split.style)
            finish("ok")
            yield Event.delta(verdict.output or "")
            return
        numbers = [_check_no(label) for label in verdict.failed]
        shape["failed_checks"] = numbers
        logger.info("factory_issue_polish_rejected", attempt=attempt, checks=numbers)
        if attempt == 1:
            messages = prompt.repair_messages(messages, output, check.repair(verdict, prep))

    finish(errors.POLISH_FAILED_CODE)  # 修一次后仍没通过：不退回原文（§9 末段）
    yield _error(errors.POLISH_FAILED_CODE)
