"""AI 润色 P2：富文本的拆与拼、判空判长、给模型的字数（决策 2026-11-09「AI 润色技术设计」§6、§4 第 ③ 步）。

原文都是编写的，图片地址用 example.test。
"""

from __future__ import annotations

import pytest

from factory_issue_module.polish import rich
from factory_issue_module.polish.rich import ALT, BRACKET, NotPolishable
from factory_issue_module.turn import errors

IMG = '<img src="https://example.test/a.png" alt="图">'
B64 = '<img src="data:image/png;base64,' + "A" * 500 + '">'
TABLE = "<table><tr><td>工位</td><td>数量</td></tr><tr><td>A1</td><td>3</td></tr></table>"
NESTED = "<table><tr><td>外<table><tr><td>内</td></tr></table></td></tr></table>"
LINK = '<a href="https://example.test/x">报告<b>链接</b></a>'


# ---------------------------------------------------------------- 拆（§6.1）


def test_images_tables_links_become_marks_in_order():
    src = f"<p>如图{IMG}所示</p><p>见表</p>{TABLE}<p>另见{LINK}与{B64}</p>"
    s = rich.split_rich(src)
    # 表格之后不另起一行（拼回时表格的占位会断开段落，§6.3）
    assert s.text == "如图[[图1]]所示\n见表\n[[表1]]另见[[链接1]]与[[图2]]"
    assert s.tokens == (("[[图1]]", IMG), ("[[表1]]", TABLE), ("[[链接1]]", LINK), ("[[图2]]", B64))
    assert s.style == BRACKET and s.rich


def test_nested_table_is_one_mark():
    s = rich.split_rich(f"<p>前</p>{NESTED}<p>后</p>")
    assert s.tokens == (("[[表1]]", NESTED),)
    assert s.text == "前\n[[表1]]后"
    assert rich.assemble(s.text, s) == f"<p>前</p>{NESTED}<p>后</p>"


UNCLOSED_TABLE = "<table><tr><td>没闭合"
UNCLOSED_LINK = '<a href="https://example.test">没闭合的链接<p>后面的段落</p>'


@pytest.mark.parametrize("tail, text, out", [
    (UNCLOSED_TABLE, "正文\n[[表1]]", f"<p>正文</p>{UNCLOSED_TABLE}"),
    (UNCLOSED_LINK, "正文\n[[链接1]]", f"<p>正文</p><p>{UNCLOSED_LINK}</p>"),
])
def test_unclosed_table_or_link_runs_to_the_end(tail, text, out):
    """从未闭合的开标签到原文末尾整个当作一个占位，拼回时原样放回（半截标签不交给模型）。"""
    s = rich.split_rich(f"<p>正文</p>{tail}")
    assert s.text == text
    assert s.tokens[0][1] == tail
    assert rich.assemble(s.text, s) == out


def test_formatting_tags_dropped_entities_restored_and_blank_lines_removed():
    src = ("<p><strong>加粗</strong>&nbsp;&nbsp;<span style=\"color:red\">红字</span>\u00a0A&amp;B</p>"
           "<p>&lt;3&gt;</p><p>  </p><ol><li>第一条</li><li>第二条</li></ol><div>块</div><h2>标题</h2>甲<br>乙")
    assert rich.split_rich(src).text == "加粗 红字 A&B\n<3>\n第一条\n第二条\n块\n标题\n甲\n乙"


def test_alt_marks_when_text_has_brackets():
    s = rich.split_rich(f"<p>写成 [[A]] 的编号</p>{IMG}")
    assert s.style == ALT and s.text == "写成 [[A]] 的编号\n⟦图1⟧"
    assert rich.text_chars(s.text, s.style) == len("写成[[A]]的编号")
    assert rich.assemble("编号写成 [[A]]\n⟦图1⟧", s) == f"<p>编号写成 [[A]]</p><p>{IMG}</p>"


def test_plain_field_is_not_parsed_as_html():
    s = rich.split_plain("  第一行 <b>不是标签</b>\r\n\r\n  第二行  ")
    assert s.text == "第一行 <b>不是标签</b>\n第二行" and s.tokens == () and not s.rich


# ---------------------------------------------------------------- 拼（§6.3）


def test_roundtrip_puts_html_back_and_escapes_text():
    src = f"<p>如图{IMG}所示</p>{TABLE}<p>另见{LINK}，A&lt;B</p>"
    s = rich.split_rich(src)
    out = rich.assemble(s.text, s)
    assert out == f"<p>如图{IMG}所示</p>{TABLE}<p>另见{LINK}，A&lt;B</p>"


def test_table_mark_inside_a_line_breaks_the_paragraph():
    s = rich.split_rich(f"<p>前</p>{TABLE}")
    assert rich.assemble("见下表[[表1]]以上", s) == f"<p>见下表</p>{TABLE}<p>以上</p>"
    assert rich.assemble("[[表1]]", s) == TABLE  # 空段落去掉


def test_unknown_mark_assembles_to_nothing():
    s = rich.split_rich(f"<p>前</p>{IMG}")
    assert rich.assemble("前[[图2]]", s) == "<p>前</p>"


def test_plain_assemble_joins_lines():
    s = rich.split_plain("甲")
    assert rich.assemble("  一 \n\n 二 ", s) == "一\n二"


# ---------------------------------------------------------------- 字数（§6.2）


def test_budget_rich_counts_marks_and_paragraph_tags():
    s = rich.split_rich(f"<p>第一段</p><p>第二段{IMG}</p>")
    # (1000 − 图片 HTML 长度 − 7 ×（2 段 + 2）) × 0.95，向下取整
    assert rich.budget(s, 1000) == int((1000 - len(IMG) - 7 * 4) * 0.95)
    assert rich.budget(s, None) is None


def test_budget_plain_counts_one_newline_per_paragraph():
    s = rich.split_plain("一\n二\n三")
    assert rich.budget(s, 100) == int((100 - 3) * 0.95)


# ---------------------------------------------------------------- 判空、判长（§4 第 ③ 步）


@pytest.mark.parametrize("query, is_rich", [
    ("", True), ("<p>&nbsp;</p><p> </p>", True), (IMG + TABLE, True), ("   \n ", False), (None, False),
])
def test_empty(query, is_rich):
    with pytest.raises(NotPolishable) as info:
        rich.prepare(query, rich=is_rich, max_input=3000, limit=None)
    assert (info.value.code, info.value.reason) == (errors.POLISH_EMPTY_CODE, rich.REASON_EMPTY)


def test_too_long_counts_text_without_marks_and_spaces():
    body = "字" * 3000
    ok = rich.prepare(f"<p>{body}</p>{B64}<p>   </p>", rich=True, max_input=3000, limit=None)
    assert ok.input_chars == 3000  # base64 图片与空白不计
    with pytest.raises(NotPolishable) as info:
        rich.prepare(f"<p>{body}字</p>", rich=True, max_input=3000, limit=None)
    assert (info.value.code, info.value.reason) == (errors.POLISH_TOO_LONG_CODE, rich.REASON_MAX_INPUT)
    assert rich.prepare(f"<p>{body}字</p>", rich=True, max_input=3000, limit=None, ignore_cap=True).input_chars == 3001


def test_markup_filling_the_limit_is_too_long():
    with pytest.raises(NotPolishable) as info:
        rich.prepare(f"<p>文字</p>{B64}", rich=True, max_input=3000, limit=300)
    assert (info.value.code, info.value.reason) == (errors.POLISH_TOO_LONG_CODE, rich.REASON_MARKUP_FILLS)


def test_prepare_keeps_limit_and_k():
    p = rich.prepare("<p>措施一</p><p>措施二</p>", rich=True, max_input=3000, limit=2000)
    assert p.limit == 2000 and p.k == int((2000 - 7 * 4) * 0.95) and p.input_chars == 6


def test_english_only():
    assert rich.english_only("Screen flickers [[图1]]", BRACKET)
    assert not rich.english_only("屏幕 flicker", BRACKET)
    assert not rich.english_only("12345 [[图1]]", BRACKET)
