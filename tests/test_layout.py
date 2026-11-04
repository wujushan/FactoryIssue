"""回答骨架与排版（决策 2026-11-03「回答骨架与排版」，`present/layout.py`）：块之间的空行、段标题、提示行。"""

from __future__ import annotations

from forge_core.events import Event, EventType

from factory_issue_module.present import caliber as cal
from factory_issue_module.present import layout


def _texts(events) -> list[str]:
    return [e.data["text"] for e in events if e.type is EventType.DELTA]


def test_spacer_puts_one_blank_line_between_blocks_across_batches():
    spaced = layout.Spacer()
    table = Event.table(["问题编号"], [["ZC9901001"]])
    first = spaced([Event.delta("提示行。\n\n"), Event.delta("\n\n"), Event.delta("\n\n结论。"), table])
    second = spaced([Event.delta("**统计口径**\n- 时间范围：不限建单时间")])
    assert _texts(first) == ["提示行。", "\n\n结论。"]  # 只有空白的正文丢掉，前后空行去掉再统一加
    assert [e.type for e in first] == [EventType.DELTA, EventType.DELTA, EventType.TABLE]
    assert _texts(second) == ["\n\n**统计口径**\n- 时间范围：不限建单时间"]  # 段内的单个换行不动


def test_spacer_starts_without_a_blank_line_and_keeps_other_events():
    spaced = layout.Spacer()
    out = spaced([Event.suggestions([]), Event.delta("第一句。")])
    assert out[0].type is EventType.SUGGESTIONS and _texts(out) == ["第一句。"]


def test_sentences_dedupes_and_ends_each_with_a_full_stop():
    assert layout.sentences(["巴西无权限，未计入。", "", "巴西无权限，未计入", "本次按这些说法找：漏电"]) == \
        "巴西无权限，未计入。本次按这些说法找：漏电。"
    assert layout.sentences([]) == "" and layout.para(["", "。"]) == []


def test_section_title_heading_and_foot():
    """开发者 2026-11-03 看样例后定：段标题用三级标题，各域小标题用粗体，结尾前一条分隔线。"""
    assert layout.section_title(1, "国内清单") == "### 1. 国内清单"
    assert layout.heading("国内问题单（4 张）").data["text"] == "**国内问题单（4 张）**"
    assert layout.foot("**统计口径**") == "---\n\n**统计口径**"


def test_rule_before_the_foot_always_follows_a_blank_line():
    """`---` 紧贴在一段文字下面会把那段文字变成标题：结尾那段前面总有一个空行。"""
    spaced = layout.Spacer()
    out = spaced([Event.delta("结论。"), Event.delta(layout.foot("**统计口径**\n- 时间范围：不限建单时间"))])
    assert _texts(out)[1].startswith("\n\n---\n\n**统计口径**")


def test_search_only_turn_ends_with_search_notes():
    c = cal.Caliber()
    c.domains(["国内"], ["巴西、海外无权限，未计入"], kind="text")
    text = c.text()
    assert text.startswith("**查找说明**") and "查找范围：国内；巴西、海外无权限，未计入；已删除的单不查" in text
    assert "计数单位" not in text and "统计范围" not in text
    c.domains(["国内"], [])  # 一轮里还有清单、统计：照旧叫统计口径
    assert c.text().startswith("**统计口径**") and "计数单位" in c.text()
