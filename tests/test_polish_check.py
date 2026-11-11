"""AI 润色 P2：程序检查与修一次的说明（决策 2026-11-09「AI 润色技术设计」§9）。原文都是编写的。"""

from __future__ import annotations

import json

import pytest

from factory_issue_module.polish import check, rich
from factory_issue_module.polish.check import (
    CHECK_ADDED,
    CHECK_FORMAT,
    CHECK_LANG,
    CHECK_LENGTH,
    CHECK_MARKS,
    CHECK_PREFACE,
    CHECK_REMOVED,
)

IMG = '<img src="https://example.test/a.png">'
TABLE = "<table><tr><td>A1</td></tr></table>"


def _prep(query: str, *, is_rich: bool = True, limit: int | None = None) -> rich.Prepared:
    return rich.prepare(query, rich=is_rich, max_input=3000, limit=limit)


def _run(text: str, prep: rich.Prepared, name: str = "原因分析") -> check.Verdict:
    return check.check(json.dumps({"text": text}, ensure_ascii=False), prep, name)


LONG = ("<p>测试机型A999在老化测试中一共测了200台，其中有5台出现开机花屏，不良率2.5%。</p>"
        f"<p>工位S3的治具松动{IMG}，作业员未按SOP作业。</p>{TABLE}")


def test_echo_passes_and_assembles():
    prep = _prep(LONG)
    v = _run(prep.split.text, prep)
    assert v.ok and v.failed == []
    assert v.output == rich.assemble(prep.split.text, prep.split)


# ---------------------------------------------------------------- 第 1 项 格式


@pytest.mark.parametrize("content", [
    "不是 JSON", '{"text": 3}', '{"result": "x"}', '{"text": "  [[图1]] "}', "[1, 2]", "",
])
def test_format(content):
    v = check.check(content, _prep(f"<p>文字</p>{IMG}"), "原因分析")
    assert v.failed == [CHECK_FORMAT] and not v.ok


def test_parse_reply_strips_think_and_surrounding_text():
    assert check.parse_reply('<think>{"text": "错"}</think>好的 {"text": "对"} 完') == "对"
    assert check.parse_reply('{"text": "a"}') == "a"
    assert check.parse_reply("{bad}") is None


# ---------------------------------------------------------------- 第 2 项 占位


@pytest.mark.parametrize("change", [
    lambda t: t.replace("[[图1]]", ""),                 # 丢了
    lambda t: t + "[[图2]]",                            # 多了
    lambda t: t + "[[图1]]",                            # 出现两次
    lambda t: t.replace("[[图1]]", "").replace("[[表1]]", "[[表1]][[图1]]"),  # 顺序变了
])
def test_marks(change):
    prep = _prep(LONG)
    assert CHECK_MARKS in _run(change(prep.split.text), prep).failed


def test_alt_marks_are_checked_and_assembled():
    """原文有 `[[` 时换用 `⟦图1⟧`：检查与拼回都按这一套（不能写死第一套）。"""
    prep = _prep(f"<p>编号写成 [[A]] 的那一批</p>{IMG}")
    assert prep.split.style == rich.ALT
    v = _run("编号写成 [[A]] 的那一批。\n⟦图1⟧", prep)
    assert v.ok and v.output == f"<p>编号写成 [[A]] 的那一批。</p><p>{IMG}</p>"
    assert CHECK_MARKS in _run("编号写成 [[A]] 的那一批。", prep).failed
    assert CHECK_MARKS in _run("编号写成 [[A]] 的那一批。\n[[图1]]", prep).failed


# ---------------------------------------------------------------- 第 3、4 项 事实


def test_added_number_code_and_word():
    prep = _prep(LONG)
    v = _run(prep.split.text + "，另有999台，型号B777，见NG", prep)
    assert CHECK_ADDED in v.failed
    # 贴着字母的 777 不算数字；B777 是编码；以中文为主时比英文词
    assert v.detail["多出"] == {"数字": ["999"], "编码": ["B777"], "英文": ["ng"]}


def test_removed_facts():
    prep = _prep(LONG)
    v = _run(prep.split.text.replace("200", "若干").replace("A999", "该机型").replace("SOP", "规范"), prep)
    assert CHECK_REMOVED in v.failed
    assert "200" in v.detail["缺少"]["数字"] and "A999" in v.detail["缺少"]["编码"]
    assert "sop" in v.detail["缺少"]["英文"]


def test_numbers_compare_by_value_and_fullwidth():
    prep = _prep("<p>第01批，共１２台，厚度1.50毫米的一半是0.75，再试一次看看结果</p>")
    v = _run("第1批，共12台，厚度1.5毫米的一半是0.75，再试一次看看结果。", prep)
    assert CHECK_ADDED not in v.failed and CHECK_REMOVED not in v.failed


def test_codes_compare_literally():
    """带字母的串（型号、料号、`1.50mm`）逐字比：改写法也算改了事实。"""
    prep = _prep("<p>厚度1.50mm，型号a999，再试一次看看结果怎么样</p>")
    v = _run("厚度1.5mm，型号A999，再试一次看看结果怎么样。", prep)
    assert v.detail["缺少"]["编码"] == ["1.50mm", "a999"] and v.detail["多出"]["编码"] == ["1.5mm", "A999"]


def test_chinese_numeral_to_digit_is_added():
    prep = _prep("<p>有三个原因：一是治具松动，二是作业员未按要求作业，三是首件未检查即开线</p>")
    v = _run("有3个原因：一是治具松动，二是作业员未按要求作业，三是首件未检查即开线。", prep)
    assert CHECK_ADDED in v.failed and "3" in v.detail["多出"]["数字"]


def test_list_numbering_is_not_added():
    src = "<p>治具松动导致定位偏移</p><p>作业员未按要求作业</p><p>首件未检查即开线</p>"
    prep = _prep(src)
    for style in ("{i}. ", "{i}、", "（{i}）", "({i})"):
        text = "\n".join(style.format(i=i) + ln for i, ln in enumerate(prep.split.text.split("\n"), start=1))
        assert _run(text, prep).ok, style
    assert _run("①治具松动导致定位偏移\n②作业员未按要求作业\n③首件未检查即开线", prep).ok


def test_english_words_only_compared_when_mostly_chinese():
    zh = _prep("<p>NFC 模块读卡失败，USB 口松动，客户反馈触摸不灵敏需要处理</p>")
    assert CHECK_REMOVED in _run("近场通信模块读卡失败，USB 口松动，客户反馈触摸不灵敏需要处理。", zh).failed
    en = _prep("<p>The screen flickers after power on and 5 units fail</p>")
    assert _run("After power-on, the screen flickers; 5 units fail.", en).ok


# ---------------------------------------------------------------- 第 5 项 长度


def test_length_over_limit():
    prep = _prep("<p>措施：更换治具并全检库存</p>", limit=40)
    v = _run("措施：更换治具并全检库存。" * 3, prep)
    assert CHECK_LENGTH in v.failed and "超过上限" in v.detail["长度"]
    assert "精简到" in check.repair(v, prep)


def test_length_ratio_for_long_input():
    text = "治具松动导致定位偏移，作业员未按要求作业，首件未检查即开线，造成批量不良需要返工处理，" * 2
    prep = _prep(f"<p>{text}</p>")
    assert prep.input_chars >= check.SHORT_INPUT
    assert CHECK_LENGTH in _run(text[: prep.input_chars // 3], prep).failed
    v = _run(text * 3, prep)
    assert CHECK_LENGTH in v.failed and "改动太大" in check.repair(v, prep)
    assert _run(text, prep).ok


def test_short_input_allows_twenty_more_chars():
    prep = _prep("<p>坏了</p>")  # 2 字，上限放宽为 22 字
    assert CHECK_LENGTH not in _run("已损坏，" + "需" * 18, prep).failed  # 22 字
    assert CHECK_LENGTH in _run("已损坏，" + "需" * 19, prep).failed  # 23 字


# ---------------------------------------------------------------- 第 6 项 说明与栏目名标题


@pytest.mark.parametrize("head", ["以下是润色后的内容：", "润色后：", "好的，", "润色结果如下"])
def test_preface(head):
    prep = _prep("<p>治具松动</p>")
    assert CHECK_PREFACE in _run(f"{head}\n治具松动。", prep).failed


def test_field_name_title_is_removed_not_failed():
    prep = _prep("<p>有三个原因：一是治具松动，二是作业员未按要求作业</p>")
    v = _run("原因分析：\n有三个原因：一是治具松动，二是作业员未按要求作业。", prep)
    assert v.ok and v.detail["去掉的标题"] == "原因分析："
    assert not v.output.startswith("<p>原因分析")


def test_field_name_title_kept_when_original_starts_with_it():
    prep = _prep("<p>原因分析：</p><p>治具松动了</p>")
    v = _run("原因分析：\n治具松动。", prep)
    assert v.ok and v.output.startswith("<p>原因分析")


def test_field_name_only_line_is_not_removed():
    """只有一行时不去掉（去掉就没有正文了），按第 1 项之外的检查照常判。"""
    prep = _prep("<p>治具松动</p>")
    v = _run("原因分析：", prep)
    assert "去掉的标题" not in v.detail


# ---------------------------------------------------------------- 第 7 项 语言


def test_english_translated_to_chinese_fails():
    prep = _prep("<p>The screen flickers. 5 of 100 units fail. Model: A999.</p>")
    v = _run("上电后屏幕闪烁，100台中有5台不良，型号A999。", prep)
    assert CHECK_LANG in v.failed
    assert "用英文润色" in check.repair(v, prep)


def test_mixed_original_may_stay_mixed():
    prep = _prep("<p>屏幕 flicker 了，5 台不良</p>")
    assert CHECK_LANG not in _run("屏幕出现 flicker 现象，5 台不良。", prep).failed


# ---------------------------------------------------------------- 纯文字栏与修一次的说明


def test_plain_field_check():
    prep = rich.prepare("为啥扭力不够", rich=False, max_input=3000, limit=None)
    v = _run("为什么扭力不够？", prep, "5Why 的问")
    assert v.ok and v.output == "为什么扭力不够？"


def test_repair_lists_only_failed_items():
    prep = _prep(LONG)
    v = _run("以下是：\n" + prep.split.text.replace("[[图1]]", "") + "，另有999台", prep)
    note = check.repair(v, prep)
    assert note.startswith("上面的输出不合格：") and note.endswith('只输出 {"text": "…"}。')
    assert "[[图1]]" in note and "999" in note and "开头的说明" in note
    assert "英文" not in note and "精简" not in note
    fmt = check.check("不是 JSON", prep, "原因分析")
    assert '请只输出 {"text": "润色后的全文"}' in check.repair(fmt, prep)
