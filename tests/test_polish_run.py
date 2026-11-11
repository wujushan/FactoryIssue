"""AI 润色 P3：提示、调模型（心跳、超时、停止）、检查与修一次、结果与日志（决策 2026-11-09「AI 润色技术设计」§4、§8、§14）。

原文都是编写的；假模型按 system 里的 `POLISH_MARKER` 认润色那次调用。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import scopes
import structlog
from fakes import make_harness
from forge_core.events import Event, EventType
from forge_core.module import ModuleRequest

from factory_issue_module import landed, polish
from factory_issue_module.polish import prompt, steps
from factory_issue_module.polish.prompt import POLISH_MARKER
from factory_issue_module.polish.rich import ALT, BRACKET
from factory_issue_module.turn import errors

IMG = '<img src="https://example.test/a.png">'
SRC = f"<p>治具松动导致定位偏移{IMG}</p><p>作业员未按要求作业</p>"
TEXT = "治具松动导致定位偏移[[图1]]\n作业员未按要求作业"
GOOD = "治具松动，导致定位偏移[[图1]]\n作业员未按要求作业。"
GOOD_HTML = f"<p>治具松动，导致定位偏移{IMG}</p><p>作业员未按要求作业。</p>"


def _ext(**kw: Any) -> dict[str, Any]:
    return {"task": polish.TASK_CODE, "field": "reason", **kw}


def _reply(text: str) -> dict[str, str]:
    return {"text": text}


def _harness(replies: list[Any] | None = None, *, live: bool = False):
    h = make_harness(scopes.account_jia(), llm_replies=replies)
    h.module.live = live
    return h


def _request(query: str, ext: dict[str, Any]) -> ModuleRequest:
    return ModuleRequest(query=query, conversation_id="c-test", inputs={"ext_param": ext})


async def _handle(h, query: str = SRC, ext: dict[str, Any] | None = None) -> list[Event]:
    return [e async for e in h.module.handle(_request(query, ext or _ext()), h.ctx)]


def _codes(events: list[Event]) -> list[str]:
    return [e.data["code"] for e in events if e.type is EventType.ERROR]


# ---------------------------------------------------------------- 提示（§8）


def test_system_is_r2_word_for_word_in_both_styles():
    assert prompt.POLISH_PROMPT_VERSION == "r2"
    for style in (BRACKET, ALT):
        o, c = style
        text = prompt.system(style)
        assert text.startswith("你帮国内制程问题单的填写人润色他正在填写的一栏内容。\n") and POLISH_MARKER in text
        assert f"5. 原文里 {o}图1{c}、{o}表1{c}、{o}链接1{c} 这样的标记代表图片、表格、链接" in text
        assert text.endswith("不加标题（也不以这一栏的名称开头），不加说明。")
        assert len(text.splitlines()) == 10
    assert "⟦" not in prompt.system(BRACKET) and "[[" not in prompt.system(ALT)


def test_user_sections():
    from factory_issue_module.config import files as config_files
    from factory_issue_module.declarations import POLISH_RULES
    from factory_issue_module.polish import rich

    rules = config_files.default(POLISH_RULES)
    prep = rich.prepare(SRC, rich=True, max_input=3000, limit=2000)
    text = prompt.user(prep, rules.field("measures"), rules, {"原因分析": "治具松动"})
    assert text.splitlines() == [
        "【这一栏】改善措施：说明针对这个问题采取或将要采取的措施",
        "【原文格式】富文本，已去掉格式，[[…]] 是图片、表格或链接",
        f"【字数】润色后的正文不超过 {prep.k} 字",
        "【同一张单的其他内容】",
        '{"原因分析": "治具松动"}',
        "【要润色的原文】",
        json.dumps({"原文": TEXT}, ensure_ascii=False),
    ]
    plain = rich.prepare("Screen flickers", rich=False, max_input=3000, limit=None)
    lines = prompt.user(plain, rules.field("five_why_question"), rules, {}).splitlines()
    assert lines[1:3] == ["【原文格式】纯文字", "【原文语言】英文，润色后仍用英文"]
    assert not any(ln.startswith(("【字数】", "【额外要求】", "【同一张单")) for ln in lines)


# ---------------------------------------------------------------- 一次过、修一次、两次都不过、出错（§4、§9）


async def test_passes_first_time_with_one_delta():
    h = _harness([_reply(GOOD)])
    events = await _handle(h)
    assert [e.type for e in events] == [EventType.DELTA]  # live=False 时不出进度事件
    assert events[0].data["text"] == GOOD_HTML
    assert len(h.llm.calls) == 1
    messages = h.llm.calls[0]
    assert [m["role"] for m in messages] == ["system", "user"] and POLISH_MARKER in messages[0]["content"]
    assert h.queries == []


async def test_call_parameters(monkeypatch):
    seen: list[dict[str, Any]] = []
    h = _harness()

    async def chat(messages, **kw):
        seen.append(kw)
        return {"choices": [{"message": {"content": json.dumps(_reply(GOOD), ensure_ascii=False)}}]}

    monkeypatch.setattr(h.llm, "chat", chat)
    await _handle(h)
    chars = len("治具松动导致定位偏移作业员未按要求作业")
    assert seen == [{"temperature": 0.0, "response_format": {"type": "json_object"},
                     "max_tokens": steps.max_tokens(chars)}]
    assert steps.max_tokens(10) == 512 and steps.max_tokens(1000) == 2256 and steps.max_tokens(9000) == 6000


async def test_repair_once_then_pass():
    h = _harness(["以下是润色后的内容：\n" + GOOD, _reply(GOOD)])
    with structlog.testing.capture_logs() as logs:
        events = await _handle(h)
    assert [e.data.get("text") for e in events] == [GOOD_HTML]
    first, second = h.llm.calls
    done = [e for e in logs if e["event"] == "factory_issue_polish"]
    # 第一次的回复不是 JSON（第 1 项不过）；修一次后通过时留的是第一次不过的编号
    assert [(e["outcome"], e["attempts"], e["failed_checks"]) for e in done] == [("ok", 2, [1])]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[:2] == first
    assert second[2]["content"] == "以下是润色后的内容：\n" + GOOD
    assert second[3]["content"].startswith("上面的输出不合格：")


async def test_fails_twice_answers_polish_failed():
    with structlog.testing.capture_logs() as logs:
        h = _harness([_reply(GOOD + "，另有999台"), _reply(GOOD.replace("[[图1]]", ""))])
        events = await _handle(h)
    assert _codes(events) == [errors.POLISH_FAILED_CODE] and len(h.llm.calls) == 2
    assert not any(e.type is EventType.DELTA for e in events)  # 不退回原文
    rejected = [e for e in logs if e["event"] == "factory_issue_polish_rejected"]
    assert [(e["attempt"], e["checks"]) for e in rejected] == [(1, [3]), (2, [2])]
    done = next(e for e in logs if e["event"] == "factory_issue_polish")
    assert (done["outcome"], done["attempts"], done["failed_checks"]) == (errors.POLISH_FAILED_CODE, 2, [2])


async def test_model_error_is_not_retried():
    with structlog.testing.capture_logs() as logs:
        h = _harness([RuntimeError("服务出错")])
        events = await _handle(h)
    assert _codes(events) == [errors.POLISH_FAILED_CODE] and len(h.llm.calls) == 1
    failed = [e for e in logs if e["event"] == "factory_issue_polish_call_failed"]
    assert [(e["attempt"], e["error"]) for e in failed] == [(1, "RuntimeError")]
    assert "服务出错" not in repr(logs) and "服务出错" not in repr([e.data for e in events])


async def test_model_error_on_repair():
    h = _harness([_reply(GOOD + "，另有999台"), RuntimeError("x")])
    assert _codes(await _handle(h)) == [errors.POLISH_FAILED_CODE] and len(h.llm.calls) == 2


async def test_no_llm_answers_polish_failed():
    h = _harness()
    h.ctx.llm = None
    with structlog.testing.capture_logs() as logs:
        assert _codes(await _handle(h)) == [errors.POLISH_FAILED_CODE]
    failed = next(e for e in logs if e["event"] == "factory_issue_polish_call_failed")
    done = next(e for e in logs if e["event"] == "factory_issue_polish")
    assert (failed["attempt"], failed["error"], done["attempts"]) == (1, "llm_unavailable", 1)


@pytest.mark.parametrize("query, code", [
    ("", errors.POLISH_EMPTY_CODE),  # 真空串（润色样例 PL-26；/test/chat 的 query 有 min_length=1，靠这里兜底）
    ("<p>&nbsp;</p>" + IMG, errors.POLISH_EMPTY_CODE),
    ("<p>" + "字" * 3001 + "</p>", errors.POLISH_TOO_LONG_CODE),
])
async def test_empty_and_too_long_do_not_call_the_model(query, code):
    h = _harness()
    events = await _handle(h, query)
    assert _codes(events) == [code] and h.llm.calls == []
    assert events[0].data["message"] == errors.POLISH_MESSAGES[code] and events[0].data["fatal"] is True


async def test_markup_filling_the_page_limit_is_too_long():
    h = _harness()
    events = await _handle(h, "<p>文字</p>" + IMG, _ext(field="measures", max_length=30))
    assert _codes(events) == [errors.POLISH_TOO_LONG_CODE] and h.llm.calls == []


async def test_live_sends_progress_then_result():
    h = _harness([_reply(GOOD)], live=True)
    events = await _handle(h)
    assert [e.type for e in events] == [EventType.PROGRESS, EventType.DELTA]
    assert events[0].data == {"stage": steps.PROGRESS_POLISH, "detail": "正在润色"}


async def test_plain_field_result_is_plain_text():
    h = _harness([_reply("为什么扭力不够？")])
    events = await _handle(h, "为啥扭力不够", _ext(field="five_why_question"))
    assert [e.data.get("text") for e in events] == ["为什么扭力不够？"]


# ---------------------------------------------------------------- 日志（§14）


async def test_log_fields_shape_only():
    with structlog.testing.capture_logs() as logs:
        await _handle(_harness([_reply(GOOD)]), ext=_ext(issue_no="ZC9911001"))
    done = [e for e in logs if e["event"] == "factory_issue_polish"]
    assert len(done) == 1
    e = done[0]
    assert {k: e[k] for k in ("field", "rich", "input_chars", "output_chars", "limit", "placeholders",
                              "reference", "db", "attempts", "outcome", "failed_checks", "context_dropped")} == {
        "field": "reason", "rich": True, "input_chars": 19, "output_chars": 21, "limit": None,
        "placeholders": 1, "reference": "none", "db": "not_found", "attempts": 1, "outcome": "ok",
        "failed_checks": [], "context_dropped": 0,
    }
    assert isinstance(e["ms"], int)
    blob = repr(logs)
    assert "治具" not in blob and "ZC9911001" not in blob


# ---------------------------------------------------------------- 心跳、超时、停止（§4 第 ⑥ 步）


class SlowLLM:
    """等 `delay` 秒才回；记下被取消了几次。"""

    def __init__(self, delay: float, text: str = GOOD) -> None:
        self.delay, self.text = delay, text
        self.calls = 0
        self.cancelled = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return {"choices": [{"message": {"content": json.dumps({"text": self.text}, ensure_ascii=False)}}]}


async def test_heartbeat_while_waiting(monkeypatch):
    monkeypatch.setattr(steps, "HEARTBEAT", 0.05)
    h = _harness(live=True)
    h.ctx.llm = SlowLLM(0.33)
    events = await _handle(h)
    kinds = [e.type for e in events]
    assert kinds[-1] is EventType.DELTA and events[-1].data["text"] == GOOD_HTML
    beats = kinds[:-1]
    assert set(beats) == {EventType.PROGRESS} and 4 <= len(beats) <= 8  # 第一个「正在润色」+ 每 0.05 秒一个


async def test_timeout_cancels_the_call(monkeypatch):
    monkeypatch.setattr(steps, "HEARTBEAT", 0.05)
    monkeypatch.setattr(steps, "CALL_TIMEOUT", 0.2)
    h = _harness(live=True)
    slow = SlowLLM(30)
    h.ctx.llm = slow
    with structlog.testing.capture_logs() as logs:
        events = await asyncio.wait_for(_handle(h), timeout=5)
    await asyncio.sleep(0)
    assert _codes(events) == [errors.POLISH_FAILED_CODE] and slow.calls == 1  # 超时不重试
    assert slow.cancelled == 1
    assert [e["error"] for e in logs if e["event"] == "factory_issue_polish_call_failed"] == ["timeout"]


async def test_closing_the_turn_while_waiting_cancels_the_call(monkeypatch):
    """用户停止：平台在事件之间关闭 `handle()` 的生成器，还在等的模型调用要被取消。"""
    monkeypatch.setattr(steps, "HEARTBEAT", 0.05)
    h = _harness(live=True)
    slow = SlowLLM(30)
    h.ctx.llm = slow
    gen = h.module.handle(_request(SRC, _ext()), h.ctx)
    first = await gen.__anext__()
    beat = await asyncio.wait_for(gen.__anext__(), timeout=5)
    assert first.type is beat.type is EventType.PROGRESS
    with structlog.testing.capture_logs() as logs:
        await gen.aclose()
    # 只等 1 拍：各层都用 aclosing 时取消在 aclose() 里同步发出；少一层就要靠事件循环的收尾钩子，至少 3 拍
    await asyncio.sleep(0)
    assert slow.calls == 1 and slow.cancelled == 1
    assert [e["outcome"] for e in logs if e["event"] == "factory_issue_polish"] == [steps.OUTCOME_STOPPED]


async def test_outer_cancel_while_waiting_cancels_the_call(monkeypatch):
    """平台强制收住本轮（取消任务）时同样取消模型调用。"""
    monkeypatch.setattr(steps, "HEARTBEAT", 10)
    h = _harness(live=True)
    slow = SlowLLM(30)
    h.ctx.llm = slow
    turn = asyncio.ensure_future(_handle(h))
    await asyncio.sleep(0.05)
    with structlog.testing.capture_logs() as logs:
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        await asyncio.sleep(0)
    assert slow.cancelled == 1
    assert [e["outcome"] for e in logs if e["event"] == "factory_issue_polish"] == [steps.OUTCOME_STOPPED]


async def test_model_finishing_with_an_error_as_the_turn_is_cancelled_leaves_nothing_unretrieved():
    """外层取消与模型调用以异常结束落在同一拍：任务的异常要有人取回（不出「never retrieved」）。"""
    loop = asyncio.get_running_loop()
    reports: list[dict] = []
    old = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reports.append(context))
    try:
        import gc

        box = steps.CallBox()
        holder = [loop.create_future()]

        class Llm:
            def chat(self, messages, **kw):
                return holder[0]

        gen = steps.call_with_heartbeat(Llm(), [], {}, box)
        step = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        holder[0].set_exception(RuntimeError("x"))  # 模型调用以异常结束
        step.cancel()  # 同一拍外层取消
        with pytest.raises((asyncio.CancelledError, StopAsyncIteration)):
            await step
        await gen.aclose()
        await asyncio.sleep(0)
        holder.clear()  # 释放全部引用：没人取回的异常在回收时报「never retrieved」
        del step, gen
        gc.collect()
    finally:
        loop.set_exception_handler(old)
    assert not [r for r in reports if "never retrieved" in str(r.get("message", ""))]


def test_call_timeout_is_within_the_client_timeout():
    assert steps.CALL_TIMEOUT == 110 < 120 and steps.HEARTBEAT == 10


def test_api_doc_states_the_same_waits():
    doc = landed.read("domestic/ai_polish_api.md")
    assert f"每次调模型最多等 {int(steps.CALL_TIMEOUT)} 秒" in doc
    assert f"每 {int(steps.HEARTBEAT)} 秒再发一次" in doc
