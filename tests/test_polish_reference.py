"""AI 润色 P4：同单参考内容（决策 2026-11-09「AI 润色技术设计」§7、§12.1「参考内容」）。

假数据照单测夹具的约定：编号用 99 年号，人名、料号、机型都是编写的。
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest
import scopes
import structlog
from fakes import make_harness
from forge_core.errors import ColumnNotPermitted, PrivilegesRequiredError, TableDenied
from forge_core.events import EventType
from forge_core.module import ModuleRequest

from factory_issue_module import polish
from factory_issue_module.polish import reference
from factory_issue_module.polish.prompt import POLISH_MARKER

NO = "ZC9911001"
MAIN = "ZCTracking_ProblemList"
MODELS = "ZCTracking_ProductNames"
FIVE = "ZCTracking_ProblemFiveWhy"
INV = "Inventory"
CODE = "999999999999999"


def _main(**over: Any) -> pd.DataFrame:
    row = {"ID": 7, "ProblemType": 1, "MHead": None, "CInvCode": CODE,
           "ProblemDesc": "<p>开机花屏<img src=\"data:image/png;base64,AAAA\"></p>", "Reason": "<p>库里的原因</p>",
           "Measures": "<p>库里的措施</p>", "Prevention": None, **over}
    return pd.DataFrame([row])


def _five(rows: list[tuple[str | None, str | None]]) -> pd.DataFrame:
    return pd.DataFrame([{"ID": i, "Question": q, "Reason": a, "Status": 1 if a else 0,
                          "AddDate": pd.Timestamp("2099-11-01") + pd.Timedelta(days=i)}
                         for i, (q, a) in enumerate(rows, start=1)])


def _harness(privileges: dict | None = None, *, replies: list | None = None):
    h = make_harness(scopes.account_jia() if privileges is None else privileges,
                     llm_replies=replies if replies is not None else [{"text": "测试。"}])
    frames = h.connectors["info"].frames
    frames[MAIN] = _main()
    frames[MODELS] = pd.DataFrame([{"ProductName": "A999"}, {"ProductName": "B999"}, {"ProductName": "A999"}])
    frames[FIVE] = _five([("为什么花屏？", "排线松动"), ("为什么排线松动？", None)])
    frames[INV] = pd.DataFrame([{"cInvCode": CODE, "cInvName": "测试排线"}])
    return h


async def _polish(h, field: str = "measures", **ext: Any):
    request = ModuleRequest(query="<p>测试原文</p>" if field not in ("five_why_question", "five_why_answer")
                            else "测试原文", conversation_id="c-test",
                            inputs={"ext_param": {"task": polish.TASK_CODE, "field": field, **ext}})
    with structlog.testing.capture_logs() as logs:
        events = [e async for e in h.module.handle(request, h.ctx)]
    done = [e for e in logs if e["event"] == "factory_issue_polish"]
    return events, done[0], logs


def _ref(h) -> dict[str, Any] | None:
    """提示里的「同一张单的其他内容」（没有这一段为 None）。"""
    calls = h.llm.routed(POLISH_MARKER)
    lines = calls[0][1]["content"].splitlines()
    if "【同一张单的其他内容】" not in lines:
        return None
    return json.loads(lines[lines.index("【同一张单的其他内容】") + 1])


# ---------------------------------------------------------------- 按编号查库（§7.2）


async def test_issue_no_sends_at_most_four_queries_with_the_right_tables_and_columns():
    h = _harness()
    events, done, _ = await _polish(h, issue_no="zc 9911-001")  # 写法统一同按编号查单
    assert [e.type for e in events] == [EventType.DELTA]
    heads = sorted(q.tables[0] for q in h.queries)
    assert heads == sorted([MAIN, MODELS, FIVE, INV])
    by = {q.tables[0]: q for q in h.queries}

    def selected(table: str) -> list[str]:
        head = by[table].sql.split(" FROM ")[0]
        return [part.split(".")[-1].strip("[] ") for part in head.removeprefix("SELECT ").split(",")]

    assert selected(MAIN) == list(reference.MAIN_SELECT)
    assert f"[{MAIN}].[Numbers] IN" in by[MAIN].sql and f"[{MAIN}].[IsDelete]" in by[MAIN].sql
    assert list(by[MAIN].params.values()).count(NO) == 1
    assert selected(MODELS) == ["ProductName"] and f"INNER JOIN [CoreINFO].[dbo].[{MAIN}]" in by[MODELS].sql
    assert selected(FIVE) == list(reference.FIVE_SELECT)  # 排序用的 ID、AddDate 在 select 里
    assert f"ORDER BY [{FIVE}].[AddDate] ASC, [{FIVE}].[ID] ASC" in by[FIVE].sql
    assert f"INNER JOIN [CoreINFO].[dbo].[{MAIN}]" in by[FIVE].sql  # 带主表条件
    assert selected(INV) == ["cInvCode", "cInvName"] and CODE in by[INV].params.values()
    assert (done["db"], done["reference"]) == ("ok", "db")


async def test_db_values_translated_and_merged():
    h = _harness()
    await _polish(h, issue_no=NO)
    ref = _ref(h)
    assert ref == {
        "问题类型": "硬件问题",
        "机型": "A999、B999",
        "物料": f"测试排线（{CODE}）",
        "问题描述": "开机花屏",
        "原因分析": "库里的原因",
        "已有的 5Why": [{"问": "为什么花屏？", "答": "排线松动"}, {"问": "为什么排线松动？", "答": "（待答复）"}],
    }  # 正在润色的「改善措施」不进参考；预防对策为空不写


async def test_material_unit_and_missing_inventory_name():
    h = _harness()
    h.connectors["info"].frames[MAIN] = _main(MHead="物料", ProblemType=3)
    h.connectors["info"].frames[INV] = pd.DataFrame(columns=["cInvCode", "cInvName"])
    await _polish(h, issue_no=NO)
    ref = _ref(h)
    assert ref["机型"] == "物料" and ref["问题类型"] == "物料问题" and ref["物料"] == CODE


async def test_no_material_code_skips_inventory():
    h = _harness()
    h.connectors["info"].frames[MAIN] = _main(CInvCode=None)
    await _polish(h, issue_no=NO)
    assert INV not in {q.tables[0] for q in h.queries} and "物料" not in _ref(h)


async def test_page_values_win_over_db():
    h = _harness()
    _, done, _ = await _polish(h, issue_no=NO, context={
        "reason": "<p>页面上刚写的原因</p>", "model": "", "five_why": [{"question": "页面的问", "answer": ""}]})
    ref = _ref(h)
    assert ref["原因分析"] == "页面上刚写的原因"
    assert "机型" not in ref  # 页面给了空串：以页面为准，不拿库里的旧值
    assert ref["已有的 5Why"] == [{"问": "页面的问", "答": "（待答复）"}]
    assert ref["问题描述"] == "开机花屏"  # 页面没给的按编号补
    assert done["reference"] == "both"


async def test_the_answer_being_written_is_not_in_the_five_why():
    """润色 5Why 的答：库里「问与 current_question 相同、答为空」的那一行就是正在答的。"""
    h = _harness()
    await _polish(h, "five_why_answer", issue_no=NO, context={"current_question": " 为什么排线松动？ "})
    ref = _ref(h)
    assert ref["已有的 5Why"] == [{"问": "为什么花屏？", "答": "排线松动"}]
    assert ref["这一答对应的问"] == "为什么排线松动？"
    assert ref["改善措施"] == "库里的措施"


async def test_db_five_why_drops_empty_rows():
    h = _harness()
    h.connectors["info"].frames[FIVE] = _five([(None, None), ("  ", ""), ("为什么？", "因为")])
    await _polish(h, issue_no=NO)
    assert _ref(h)["已有的 5Why"] == [{"问": "为什么？", "答": "因为"}]


@pytest.mark.parametrize("issue_no", ["ZC99110", "BR9911001", "HW9911001", "abc", ""])
async def test_bad_or_foreign_number_is_skipped(issue_no):
    h = _harness()
    events, done, _ = await _polish(h, issue_no=issue_no)
    assert h.queries == [] and done["db"] == "skipped" and done["reference"] == "none"
    assert [e.type for e in events] == [EventType.DELTA]


async def test_not_found():
    h = _harness()
    h.connectors["info"].frames[MAIN] = pd.DataFrame(columns=list(reference.MAIN_SELECT))
    events, done, _ = await _polish(h, issue_no=NO)
    assert done["db"] == "not_found" and _ref(h) is None
    assert [e.type for e in events] == [EventType.DELTA]


async def test_domestic_denied_still_polishes():
    h = _harness(scopes.no_domain())
    events, done, logs = await _polish(h, issue_no=NO)
    assert done["db"] == "denied" and _ref(h) is None
    assert [e.type for e in events] == [EventType.DELTA]
    assert [e["error"] for e in logs if e["event"] == "factory_issue_polish_db_failed"] == ["TableDenied"]


@pytest.mark.parametrize("exc, status", [
    (TableDenied("x"), "denied"), (ColumnNotPermitted("x"), "denied"), (PrivilegesRequiredError("x"), "denied"),
    (RuntimeError("库出错"), "failed"),
])
async def test_main_query_error_still_polishes(exc, status):
    h = _harness()
    h.connectors["info"].errors[MAIN] = exc
    events, done, logs = await _polish(h, issue_no=NO, context={"reason": "页面的原因"})
    assert done["db"] == status and done["reference"] == "page"
    assert _ref(h) == {"原因分析": "页面的原因"}
    assert [e.type for e in events] == [EventType.DELTA]
    assert "库出错" not in repr(logs)


@pytest.mark.parametrize("table, part, label", [(MODELS, "model", "机型"), (FIVE, "five_why", "已有的 5Why"),
                                                 (INV, "inventory", None)])
async def test_part_errors_only_lose_that_part(table, part, label):
    h = _harness()
    h.connectors["info"].errors[table] = RuntimeError("x")
    _, done, logs = await _polish(h, issue_no=NO)
    ref = _ref(h)
    assert done["db"] == "ok" and done["db_missing"] == [part]
    assert [e["part"] for e in logs if e["event"] == "factory_issue_polish_db_part_failed"] == [part]
    if label:
        assert label not in ref
    else:
        assert ref["物料"] == CODE  # 只少物料名称，料号照写
    assert ref["原因分析"] == "库里的原因"


async def test_unexpected_error_while_translating_still_polishes(monkeypatch):
    """`build` 的兜底：查库之后的整理出了没想到的错，照样润色、记 failed，页面的参考照用。"""
    h = _harness()

    def boom(*_a, **_k):
        raise KeyError("x")

    monkeypatch.setattr(reference, "_five_items", boom)
    events, done, logs = await _polish(h, issue_no=NO, context={"reason": "页面的原因"})
    assert done["db"] == "failed" and _ref(h) == {"原因分析": "页面的原因"}
    assert [e.type for e in events] == [EventType.DELTA]
    assert [e["error"] for e in logs if e["event"] == "factory_issue_polish_db_failed"] == ["KeyError"]


async def test_slow_database_does_not_hold_up_polishing(monkeypatch):
    """库慢：到 `DB_TIMEOUT` 不再等，记 failed，照样润色。"""
    import time

    monkeypatch.setattr(reference, "DB_TIMEOUT", 0.2)
    h = _harness()
    h.connectors["info"].frames[MAIN] = lambda sql, params: (time.sleep(1.0), _main())[1]
    started = time.monotonic()
    events, done, logs = await _polish(h, issue_no=NO)
    assert time.monotonic() - started < 0.9
    assert done["db"] == "failed" and [e.type for e in events] == [EventType.DELTA]
    assert [e["error"] for e in logs if e["event"] == "factory_issue_polish_db_failed"] == ["timeout"]


async def test_no_data_handle_still_polishes():
    h = _harness()
    h.ctx.data = None
    events, done, _ = await _polish(h, issue_no=NO)
    assert done["db"] == "failed" and [e.type for e in events] == [EventType.DELTA]


async def test_without_issue_no_no_sql():
    h = _harness()
    _, done, _ = await _polish(h, context={"problem_type": "硬件问题"})
    assert h.queries == [] and done["db"] == "skipped" and done["reference"] == "page"


# ---------------------------------------------------------------- 截断与正在润色的这一栏（§7.3）


def test_render_truncates_and_skips_the_field_being_polished():
    values = {"reason": "因" * 900, "model": "M" * 150, "measures": "措施",
              "five_why": [{"question": "问" * 250, "answer": ""}] * 12}
    out, used = reference.render(values, "measures", "")
    assert out["原因分析"] == "因" * 800 + "…"
    assert out["机型"] == "M" * 100 + "…"
    assert "改善措施" not in out and "measures" not in used
    assert len(out["已有的 5Why"]) == 10
    assert out["已有的 5Why"][0] == {"问": "问" * 200 + "…", "答": "（待答复）"}


def test_render_strips_html_and_collapses_spaces():
    out, _ = reference.render({"reason": "<p>甲&nbsp;&nbsp;乙</p><p>丙</p>"}, "measures", "")
    assert out == {"原因分析": "甲 乙 丙"}


def test_five_why_answer_always_has_the_question():
    out, _ = reference.render({}, "five_why_answer", "为什么？")
    assert out == {"这一答对应的问": "为什么？"}
