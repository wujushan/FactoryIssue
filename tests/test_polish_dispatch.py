"""AI 润色 P0：入口分派、任务声明、参数校验、错误文案（决策 2026-11-09「AI 润色技术设计」§2、§3、§5、§11、§13）。"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
import scopes
import structlog
from fakes import MANIFEST, make_harness
from forge_core.events import Event, EventType
from forge_core.module import ModuleRequest

from factory_issue_module import landed, module, polish
from factory_issue_module.config import files as config_files
from factory_issue_module.config import polish_rules
from factory_issue_module.declarations import POLISH_RULES, TASKS
from factory_issue_module.polish import params
from factory_issue_module.turn import errors

ROOT = Path(__file__).resolve().parents[1]
POLISH_DIR = ROOT / "src" / "factory_issue_module" / "polish"
RULES = config_files.default(POLISH_RULES)
FULL = scopes.account_jia()  # 有国内权限的测试账号甲；润色分支（不带编号时）不该用到 ctx.data


def _ext(**kw: Any) -> dict[str, Any]:
    return {"task": polish.TASK_CODE, **kw}


async def _handle(harness, query: str, ext: dict[str, Any] | None) -> list[Event]:
    inputs = {"ext_param": ext} if ext is not None else {}
    request = ModuleRequest(query=query, conversation_id=harness.ctx.conversation_id, inputs=inputs)
    return [e async for e in harness.module.handle(request, harness.ctx)]


def _forbid_query_path(harness, monkeypatch) -> list[str]:
    """记下润色分支不该碰的：`describe()`、工作区读写、查询编排。"""
    touched: list[str] = []

    def describe(*_a, **_k):
        touched.append("describe")
        raise AssertionError("润色分支不该调 describe()")

    async def ws(*_a, **_k):
        touched.append("workspace")
        return None

    monkeypatch.setattr(harness.ctx.data, "describe", describe)
    for name in ("get", "put", "delete", "keys", "clear"):
        monkeypatch.setattr(harness.ctx.workspace, name, ws)

    async def no_turn(*_a, **_k):
        touched.append("orchestrator")
        yield Event.delta("查询流程")

    monkeypatch.setattr(module.orchestrator, "run_turn", no_turn)
    return touched


# ---------------------------------------------------------------- 分派（§3）


async def test_polish_task_goes_to_polish_without_touching_query_path(monkeypatch):
    harness = make_harness(FULL)
    touched = _forbid_query_path(harness, monkeypatch)
    events = await _handle(harness, "<p>测试原文</p>", _ext(field="measures"))
    assert touched == []
    assert harness.queries == []
    assert harness.llm.calls == []  # P0 还不调模型
    assert [e.type for e in events] == [EventType.ERROR]
    assert events[0].data["code"] == errors.POLISH_FAILED_CODE  # P0：校验过了暂答 POLISH_FAILED


async def test_task_code_with_spaces_still_polishes(monkeypatch):
    harness = make_harness(FULL)
    touched = _forbid_query_path(harness, monkeypatch)
    await _handle(harness, "测试", {"task": f" {polish.TASK_CODE} ", "field": "reason"})
    assert touched == []


@pytest.mark.parametrize("ext", [None, {"task": "polish_issue", "field": "measures"}, {"task": ""}, "domestic_polish"])
async def test_other_rounds_go_to_query_flow(monkeypatch, ext):
    harness = make_harness(FULL)
    touched = _forbid_query_path(harness, monkeypatch)
    events = await _handle(harness, "最近一周国内的问题单", ext)
    assert touched == ["orchestrator"]
    assert [e.data.get("text") for e in events] == ["查询流程"]


async def test_query_flow_unchanged_without_ext_param(monkeypatch):
    """不带 ext_param 的轮次交给 `run_turn` 的是原样的 request。"""
    harness = make_harness(FULL)
    seen: list[ModuleRequest] = []

    async def spy(manifest, request, ctx):
        seen.append(request)
        yield Event.delta("x")

    monkeypatch.setattr(module.orchestrator, "run_turn", spy)
    await _handle(harness, "你好", None)
    assert len(seen) == 1 and seen[0].query == "你好" and seen[0].inputs == {}


async def test_live_polish_skips_pacing_and_history(monkeypatch):
    """面向前端（`live=True`）时润色同样不经打字机分段（§3），也不读多轮历史。"""
    harness = make_harness(FULL, history=[("上一问", "上一答")])
    harness.module.live = True
    touched = _forbid_query_path(harness, monkeypatch)

    def paced(events):
        touched.append("pacing")
        return events

    async def history(*_a, **_k):
        touched.append("session")
        return []

    monkeypatch.setattr(module.pacing, "paced", paced)
    monkeypatch.setattr(harness.ctx.session, "history", history)
    events = await _handle(harness, "<p>测试原文</p>", _ext(field="measures"))
    assert touched == []
    assert [e.data["code"] for e in events] == [errors.POLISH_FAILED_CODE]


async def test_unknown_task_is_logged(monkeypatch):
    harness = make_harness(FULL)
    _forbid_query_path(harness, monkeypatch)
    with structlog.testing.capture_logs() as logs:
        await _handle(harness, "测试", {"task": "polish_issue"})
        await _handle(harness, "测试", None)
    assert [(e["event"], e.get("task")) for e in logs if e["event"] == "factory_issue_unknown_task"] == [
        ("factory_issue_unknown_task", "polish_issue"),
    ]


async def test_polish_logs_shape_only():
    """§14：结束记 `factory_issue_polish`；参数有误另记 `factory_issue_polish_bad_param`（含 `issue_no` 不是字符串）。
    不记原文与问题编号。"""
    harness = make_harness(FULL)
    with structlog.testing.capture_logs() as logs:
        await _handle(harness, "测试原文甲", _ext(field="remark"))
        await _handle(harness, "测试原文乙", _ext(field="reason", issue_no=99, context={"x": 1, "reason": "y"}))
    bad = [e["reason"] for e in logs if e["event"] == "factory_issue_polish_bad_param"]
    assert bad == [params.REASON_UNKNOWN_FIELD, params.REASON_ISSUE_NO_IGNORED]
    done = [e for e in logs if e["event"] == "factory_issue_polish"]
    assert [e["outcome"] for e in done] == [errors.POLISH_BAD_PARAM_CODE, errors.POLISH_FAILED_CODE]
    assert done[1]["field"] == "reason" and done[1]["rich"] is True and done[1]["context_dropped"] == 1
    assert done[1]["limit"] is None and isinstance(done[1]["ms"], int)
    assert not any("测试原文" in repr(e) or "issue_no" in e for e in logs)


def test_every_dispatched_task_code_is_declared():
    """`/test/chat` 不检查声明，`/v2/tasks` 只放行声明过的任务码（docs/dev/10）。"""
    assert [t.code for t in MANIFEST.tasks] == [polish.TASK_CODE] == [t.code for t in TASKS]
    spec = MANIFEST.find_task(polish.TASK_CODE)
    assert spec is not None and spec.data_scope == "user"
    assert spec.ext_param_schema["properties"]["task"] == {"const": polish.TASK_CODE}


def test_task_code_matches_the_api_doc():
    doc = landed.read("domestic/ai_polish_api.md")
    consts = landed.table_with_header(landed.section(doc, "## 常量"), ("项", "值")).rows
    assert dict(consts)["`ext_param.task`"] == f"`{polish.TASK_CODE}`"
    assert dict(consts)["`target`"] == f"`{MANIFEST.code}`"


def test_polish_does_not_import_query_parts():
    """§1.2：`polish/` 不 import `turn/orchestrator`、`plan`、`present`、`skills`、`stats`。"""
    banned = re.compile(r"^factory_issue_module\.(plan|present|skills|stats|turn\.orchestrator)(\.|$)")
    for path in POLISH_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            bad = [n for n in names if banned.match(n)]
            assert not bad, f"{path.name} import 了 {bad}"


# ---------------------------------------------------------------- 错误文案（§11）


def test_error_codes_and_messages_match_the_api_doc():
    doc = landed.read("domestic/ai_polish_api.md")
    rows = landed.table_with_header(doc, ("code", "场景", "message")).rows
    documented = {code.strip("`"): message for code, _, message in rows}
    assert documented == errors.POLISH_MESSAGES


# ---------------------------------------------------------------- 参数（§5）


async def _codes(ext: dict[str, Any], query: str = "测试原文") -> tuple[list[str], list[dict[str, Any]]]:
    harness = make_harness(FULL)
    events = await _handle(harness, query, ext)
    return [e.data["code"] for e in events if e.type is EventType.ERROR], events


@pytest.mark.parametrize("ext, reason", [
    (_ext(), params.REASON_FIELD),
    (_ext(field=3), params.REASON_FIELD),
    (_ext(field="  "), params.REASON_FIELD),
    (_ext(field="remark"), params.REASON_UNKNOWN_FIELD),
    (_ext(field="measures", max_length=0), params.REASON_MAX_LENGTH),
    (_ext(field="measures", max_length=-5), params.REASON_MAX_LENGTH),
    (_ext(field="measures", max_length=True), params.REASON_MAX_LENGTH),
    (_ext(field="measures", max_length=12.0), params.REASON_MAX_LENGTH),
    (_ext(field="measures", max_length="2000"), params.REASON_MAX_LENGTH),
    (_ext(field="five_why_answer"), params.REASON_CURRENT_QUESTION),
    (_ext(field="five_why_answer", context={"current_question": "  "}), params.REASON_CURRENT_QUESTION),
    (_ext(field="five_why_answer", context={"current_question": 5}), params.REASON_CURRENT_QUESTION),
])
def test_bad_params_are_rejected(ext, reason):
    with pytest.raises(params.BadParam) as info:
        params.parse(ext, RULES)
    assert info.value.reason == reason


@pytest.mark.parametrize("ext", [_ext(field="remark"), _ext(field="measures", max_length="2000"), _ext()])
async def test_bad_params_answer_polish_bad_param(ext):
    codes, events = await _codes(ext)
    assert codes == [errors.POLISH_BAD_PARAM_CODE]
    assert events[0].data["message"] == errors.POLISH_BAD_PARAM
    assert events[0].data.get("fatal") is True


def test_field_code_is_trimmed():
    assert params.parse(_ext(field=" reason "), RULES).field == "reason"


def test_page_limit_wins_over_field_default():
    """页面给了就用页面的（含比栏目默认大的），没给才用栏目默认；不取较小的一个（§5）。"""
    measures = RULES.field("measures")
    assert measures.default_max == 2000
    bigger = params.parse(_ext(field="measures", max_length=3000), RULES)
    smaller = params.parse(_ext(field="measures", max_length=500), RULES)
    absent = params.parse(_ext(field="measures"), RULES)
    unlimited = params.parse(_ext(field="reason"), RULES)
    assert params.limit_of(bigger, measures) == 3000
    assert params.limit_of(smaller, measures) == 500
    assert params.limit_of(absent, measures) == 2000
    assert params.limit_of(unlimited, RULES.field("reason")) is None


def test_issue_no_not_a_string_is_ignored():
    req = params.parse(_ext(field="reason", issue_no=2026110001), RULES)
    assert req.issue_no is None and req.issue_no_ignored
    ok = params.parse(_ext(field="reason", issue_no="ZC9911001"), RULES)
    assert ok.issue_no == "ZC9911001" and not ok.issue_no_ignored


def test_bad_context_items_are_dropped_not_rejected():
    ctx = {
        "reason": "测试原因",
        "measures": ["不是字符串"],
        "unknown": "x",
        "five_why": [{"question": "为什么甲", "answer": ""}, {"question": 1, "answer": "乙"}, "不是对象",
                     {"question": "为什么丙"}, {}, {"question": " ", "answer": ""}],
        "current_question": "为什么丁",
    }
    req = params.parse(_ext(field="five_why_answer", context=ctx), RULES)
    assert req.context["reason"] == "测试原因"
    assert "measures" not in req.context and "unknown" not in req.context
    # 缺的键按空串；问与答都为空的项丢掉
    assert req.context["five_why"] == [{"question": "为什么甲", "answer": ""}, {"question": "为什么丙", "answer": ""}]
    assert req.dropped == 6  # measures、unknown、five_why 里的四项
    not_object = params.parse(_ext(field="reason", context="不是对象"), RULES)
    assert not_object.context == {} and not_object.dropped == 1


def test_five_why_list_not_a_list_is_dropped():
    req = params.parse(_ext(field="reason", context={"five_why": "x"}), RULES)
    assert "five_why" not in req.context and req.dropped == 1


# ---------------------------------------------------------------- 规则槽位（P0 占位解析，§10 的校验在 P1）


def test_polish_rules_default_is_the_landed_section():
    assert [f.code for f in RULES.fields] == [
        "problem_desc", "reason", "five_why_question", "five_why_answer", "measures", "prevention",
    ]
    assert RULES.max_input == 3000 and RULES.common == ""
    assert [f.rich for f in RULES.fields] == [True, True, False, False, True, True]
    assert [f.default_max for f in RULES.fields] == [None, None, None, None, 2000, 900]
    assert all(f.requirements == "" for f in RULES.fields)


def test_landed_polish_rules_pass_validation_as_upload():
    module.FactoryIssueModule().validate_config(POLISH_RULES, landed.polish_rules_section())


@pytest.mark.parametrize("old, new", [
    ("| 原文长度上限 | 3000 |", "| 原文长度上限 | ² |"),
    ("| 富文本 | 900 |", "| 富文本 | ² |"),
    ("| 富文本 | 900 |", "| 富文本 | 0 |"),
])
def test_polish_rules_bad_numbers_give_admin_message(old, new):
    """「²」这类字符 `str.isdigit` 为真、`int()` 却抛原生错误：要报给管理员看得懂的话。"""
    with pytest.raises(config_files.ConfigFormatError):
        polish_rules.parse(landed.polish_rules_section().replace(old, new))


def test_polish_rules_bad_header_is_rejected():
    bad = landed.polish_rules_section().replace("| 栏目代码 | 名称 |", "| 代码 | 名称 |")
    with pytest.raises(config_files.ConfigFormatError):
        polish_rules.parse(bad)


async def test_uploaded_rules_drive_known_fields():
    """上传版里新增的栏目即可用（不认识的栏目代码按 `unknown_field` 拒）。"""
    text = landed.polish_rules_section().replace(
        "| prevention | 预防对策 | 说明怎样防止同类问题再次发生 | 富文本 | 900 |",
        "| prevention | 预防对策 | 说明怎样防止同类问题再次发生 | 富文本 | 900 |\n"
        "| remark | 备注 | 补充说明 | 纯文字 | 不限 |",
    )
    harness = make_harness(FULL, config_files={POLISH_RULES: text})
    events = await _handle(harness, "测试", _ext(field="remark"))
    assert [e.data["code"] for e in events] == [errors.POLISH_FAILED_CODE]  # 校验过了（P0 暂答 FAILED）
