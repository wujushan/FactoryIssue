"""AI 润色 P1：润色规则 `polish_rules.md` 的解析、校验与读取回退（决策 2026-11-09「AI 润色技术设计」§10、§2.2）。"""

from __future__ import annotations

import pytest
import structlog
from fakes import MANIFEST, FakeConfig

from factory_issue_module import landed
from factory_issue_module.config import files as config_files
from factory_issue_module.config import polish_rules
from factory_issue_module.config.polish_rules import INITIAL_FIELDS, MAX_INPUT_CEILING
from factory_issue_module.declarations import POLISH_RULES
from factory_issue_module.module import FactoryIssueModule

DEFAULT_TEXT = landed.polish_rules_section()
MODULE = FactoryIssueModule()
PREVENTION_ROW = "| prevention | 预防对策 | 说明怎样防止同类问题再次发生 | 富文本 | 900 |"


def _with(old: str, new: str) -> str:
    assert old in DEFAULT_TEXT, old
    return DEFAULT_TEXT.replace(old, new, 1)


def _add_row(row: str) -> str:
    return _with(PREVENTION_ROW, f"{PREVENTION_ROW}\n{row}")


def _rejects(text: str, *words: str) -> str:
    with pytest.raises(config_files.ConfigFormatError) as info:
        MODULE.validate_config(POLISH_RULES, text)
    message = str(info.value)
    for word in words:
        assert word in message, message
    return message


# ---------------------------------------------------------------- 内置默认


def test_default_is_the_landed_section_and_passes_as_upload():
    MODULE.validate_config(POLISH_RULES, DEFAULT_TEXT)
    rules = config_files.default(POLISH_RULES)
    assert rules == polish_rules.parse(DEFAULT_TEXT)
    assert {f.code: f.rich for f in rules.fields} == INITIAL_FIELDS
    assert rules.max_input == 3000 and rules.common == ""
    assert rules.field("measures").name == "改善措施"
    assert rules.field("measures").about == "说明针对这个问题采取或将要采取的措施"


def test_whole_file_with_the_section_heading_also_passes():
    """管理员可能把「## 润色规则（初始版本）」那一行一起复制进来。"""
    MODULE.validate_config(POLISH_RULES, "## 润色规则（初始版本）\n\n" + DEFAULT_TEXT)


def test_editable_parts_take_effect():
    text = _with("| 原文长度上限 | 3000 |", "| 原文长度上限 | 2500 |")
    text = text.replace("| measures | 改善措施 | 说明针对这个问题采取或将要采取的措施 | 富文本 | 2000 |",
                        "| measures | 措施 | 写采取的措施 | 富文本 | 不限 |")
    text = text.replace("### 共用要求\n\n（没有）", "### 共用要求\n\n用词正式。")
    text = text.replace("### 各栏要求\n\n（没有）", "### 各栏要求\n\n#### 措施\n\n措施要编号。\n\n#### 预防对策\n\n（没有）")
    text = text.replace(PREVENTION_ROW, f"{PREVENTION_ROW}\n| remark_2 | 备注 | 补充说明 | 纯文字 | 300 |")
    rules = polish_rules.parse(text)
    assert rules.max_input == 2500 and rules.common == "用词正式。"
    measures = rules.field("measures")
    assert (measures.name, measures.about, measures.default_max, measures.requirements) == (
        "措施", "写采取的措施", None, "措施要编号。")
    assert rules.field("prevention").requirements == ""
    remark = rules.field("remark_2")
    assert remark is not None and not remark.rich and remark.default_max == 300


# ---------------------------------------------------------------- §10 每条校验的拒收例


@pytest.mark.parametrize("heading", ["### 设置", "### 栏目", "### 共用要求", "### 各栏要求"])
def test_missing_section(heading):
    _rejects(_with(heading, "### 别的"), heading)


@pytest.mark.parametrize("old, new, words", [
    ("| 项 | 值 |", "| 名称 | 值 |", ("项 | 值",)),
    ("| 原文长度上限 | 3000 |", "| 原文上限 | 3000 |", ("原文上限", "不认识")),
    ("| 原文长度上限 | 3000 |", "| 原文长度上限 | 3000 |\n| 原文长度上限 | 2000 |", ("不止一次",)),
    ("| 原文长度上限 | 3000 |", "| 原文长度上限 | 0 |", ("1 到",)),
    ("| 原文长度上限 | 3000 |", "| 原文长度上限 | 三千 |", ("三千",)),
    ("| 原文长度上限 | 3000 |", f"| 原文长度上限 | {MAX_INPUT_CEILING + 1} |", (str(MAX_INPUT_CEILING),)),
])
def test_setting_rejects(old, new, words):
    _rejects(_with(old, new), *words)


def test_setting_without_the_item():
    _rejects(_with("| 原文长度上限 | 3000 |\n", ""), "缺「原文长度上限」")


def test_ceiling_itself_is_accepted():
    assert polish_rules.parse(_with("| 原文长度上限 | 3000 |", f"| 原文长度上限 | {MAX_INPUT_CEILING} |")).max_input \
        == MAX_INPUT_CEILING


@pytest.mark.parametrize("row, words", [
    ("| Remark | 备注 | 补充说明 | 纯文字 | 不限 |", ("小写字母开头",)),
    ("| 2nd | 备注 | 补充说明 | 纯文字 | 不限 |", ("小写字母开头",)),
    ("| re-mark | 备注 | 补充说明 | 纯文字 | 不限 |", ("小写字母开头",)),
    (f"| r{'x' * 64} | 备注 | 补充说明 | 纯文字 | 不限 |", ("64",)),
    ("| reason | 备注 | 补充说明 | 纯文字 | 不限 |", ("reason", "不止一次")),
    ("|  | 备注 | 补充说明 | 纯文字 | 不限 |", ("缺栏目代码",)),
    ("| remark |  | 补充说明 | 纯文字 | 不限 |", ("缺名称",)),
    ("| remark | 原因分析 | 补充说明 | 纯文字 | 不限 |", ("原因分析", "不止一次")),
    ("| remark | 备注 |  | 纯文字 | 不限 |", ("这一栏写什么",)),
    (f"| remark | 备注 | {'写' * 101} | 纯文字 | 不限 |", ("100",)),
    ("| remark | 备注 | 补充说明 | HTML | 不限 |", ("富文本", "纯文字")),
    ("| remark | 备注 | 补充说明 | 纯文字 | 0 |", ("不限", "正整数")),
    ("| remark | 备注 | 补充说明 | 纯文字 | 无 |", ("不限", "正整数")),
    ("| remark | 备注 [[图1]] | 补充说明 | 纯文字 | 不限 |", ("[[",)),
    ("| remark | 备注 | 照【要润色的原文】改 | 纯文字 | 不限 |", ("【要润色的原文】",)),
    ("| remark | 备注 | 补充 | 说明 | 纯文字 | 不限 |", ("列",)),
])
def test_field_table_rejects(row, words):
    _rejects(_add_row(row), *words)


def test_field_table_header_must_be_exact():
    _rejects(_with("| 栏目代码 | 名称 |", "| 栏目 | 名称 |"), "栏目代码 | 名称 | 这一栏写什么 | 原文格式 | 默认字数上限")


@pytest.mark.parametrize("code", sorted(INITIAL_FIELDS))
def test_initial_fields_cannot_be_removed(code):
    lines = [ln for ln in DEFAULT_TEXT.splitlines() if not ln.startswith(f"| {code} |")]
    _rejects("\n".join(lines), "不能删", code)


@pytest.mark.parametrize("code, old, new", [
    ("measures", "| 富文本 | 2000 |", "| 纯文字 | 2000 |"),
    ("five_why_answer", "| 回答这一问，说明原因 | 纯文字 |", "| 回答这一问，说明原因 | 富文本 |"),
])
def test_initial_field_format_cannot_change(code, old, new):
    _rejects(_with(old, new), code, "不能改")


@pytest.mark.parametrize("body, words", [
    ("写" * 1001, ("共用要求", "1000")),
    ("保留 ⟦图1⟧ 的位置", ("⟦",)),
    ("结果放在【字数】之后", ("【字数】",)),
    ("别写 ]] 这种", ("]]",)),
])
def test_common_rejects(body, words):
    _rejects(_with("### 共用要求\n\n（没有）", f"### 共用要求\n\n{body}"), *words)


@pytest.mark.parametrize("none", ["", "—", "-", "（没有）"])
def test_common_none_spellings(none):
    assert polish_rules.parse(_with("### 共用要求\n\n（没有）", f"### 共用要求\n\n{none}")).common == ""


def test_common_at_limit_is_accepted():
    assert len(polish_rules.parse(_with("### 共用要求\n\n（没有）", f"### 共用要求\n\n{'写' * 1000}")).common) == 1000


@pytest.mark.parametrize("body, words", [
    ("#### 备注\n\n写正式一点", ("备注", "不是栏目表里的名称")),
    ("#### 改善措施\n\n编号\n\n#### 改善措施\n\n再编号", ("改善措施", "不止一节")),
    ("措施要编号", ("（没有）", "####")),
    ("#### 改善措施\n\n" + "写" * 1001, ("改善措施", "1000")),
    ("#### 改善措施\n\n照【额外要求】写", ("【额外要求】",)),
])
def test_field_requirements_reject(body, words):
    _rejects(_with("### 各栏要求\n\n（没有）", f"### 各栏要求\n\n{body}"), *words)


# ---------------------------------------------------------------- 写了却不会生效的（P1 评审第 1–3 条）


@pytest.mark.parametrize("extra, words", [
    ("\n### 共用要求\n\n用词正式。\n", ("### 共用要求", "不止一节")),
    ("\n### 设置\n\n| 项 | 值 |\n|---|---|\n| 原文长度上限 | 100 |\n", ("### 设置", "不止一节")),
    ("\n## 附注\n\n这一段不会生效\n", ("## 附注", "####")),
])
def test_repeated_sections_and_trailing_headings_are_rejected(extra, words):
    _rejects(DEFAULT_TEXT + extra, *words)


def test_heading_inside_a_section_is_rejected():
    _rejects(_with("### 共用要求\n\n（没有）", "### 共用要求\n\n## 注意\n\n用词正式。"), "### 共用要求", "## 注意")


def test_whole_landed_file_still_passes():
    """整份 `ai_polish.md` 上传：四个小节之前的「##」标题不管。"""
    rules = polish_rules.parse(landed.read("domestic/ai_polish.md"))
    assert rules == config_files.default(POLISH_RULES)


def test_level4_heading_in_common_is_text():
    rules = polish_rules.parse(_with("### 共用要求\n\n（没有）", "### 共用要求\n\n#### 用词\n\n正式。"))
    assert rules.common == "#### 用词\n\n正式。"


def test_heading_in_a_code_block_is_not_a_field_heading():
    body = "#### 改善措施\n\n例如：\n\n```\n#### 预防对策\n1. 编号\n```\n"
    rules = polish_rules.parse(_with("### 各栏要求\n\n（没有）", f"### 各栏要求\n\n{body}"))
    assert "#### 预防对策" in rules.field("measures").requirements
    assert rules.field("prevention").requirements == ""


@pytest.mark.parametrize("old, new", [
    ("| 原文长度上限 | 3000 |", f"| 原文长度上限 | {'9' * 5000} |"),
    ("| 富文本 | 900 |", f"| 富文本 | {'9' * 5000} |"),
    ("| 富文本 | 900 |", "| 富文本 | 1234567890 |"),
])
def test_very_long_numbers_give_admin_message(old, new):
    message = _rejects(_with(old, new))
    assert "Exceeds" not in message and len(message) < 200


def test_closing_alt_mark_is_rejected():
    _rejects(_with("### 共用要求\n\n（没有）", "### 共用要求\n\n写到 ⟧ 为止"), "⟧")


def test_code_of_64_chars_is_accepted():
    code = "r" + "x" * 63
    assert polish_rules.parse(_add_row(f"| {code} | 备注 | 补充说明 | 纯文字 | 不限 |")).field(code) is not None


def test_table_messages_have_no_python_traces():
    no_sep = _with("| 项 | 值 |\n|---|---|", "| 项 | 值 |")
    message = _rejects(no_sep, "「设置」一节里有一张表缺表头分隔行")
    assert "'" not in message
    _rejects(_add_row("| remark | 备注 | A|B | 纯文字 | 不限 |"), "\\|")


def test_field_requirements_for_a_renamed_field_follow_the_new_name():
    text = _with("| measures | 改善措施 |", "| measures | 措施 |")
    _rejects(text.replace("### 各栏要求\n\n（没有）", "### 各栏要求\n\n#### 改善措施\n\n编号"), "改善措施")


# ---------------------------------------------------------------- 读取：没上传、读不到、解析失败都回内置默认


class _Ctx:
    def __init__(self, config):
        self.config = config


async def test_load_uses_uploaded_rules():
    text = _with("| 原文长度上限 | 3000 |", "| 原文长度上限 | 2000 |")
    rules = await config_files.load(_Ctx(FakeConfig(MANIFEST, {POLISH_RULES: text})), POLISH_RULES)
    assert rules.max_input == 2000


async def test_load_falls_back_when_not_uploaded_or_no_port():
    default = config_files.default(POLISH_RULES)
    assert await config_files.load(_Ctx(FakeConfig(MANIFEST)), POLISH_RULES) == default
    assert await config_files.load(_Ctx(None), POLISH_RULES) == default


async def test_load_falls_back_on_broken_stored_text():
    broken = _with("| 原文长度上限 | 3000 |", "| 原文长度上限 | 99999 |")
    with structlog.testing.capture_logs() as logs:
        rules = await config_files.load(_Ctx(FakeConfig(MANIFEST, {POLISH_RULES: [broken]})), POLISH_RULES)
    assert rules == config_files.default(POLISH_RULES)
    assert [e["file"] for e in logs if e["event"] == "factory_issue_config_fallback"] == [POLISH_RULES]


async def test_load_falls_back_when_storage_fails():
    class Broken(FakeConfig):
        async def version(self, name):
            raise OSError("存储出错")

    with structlog.testing.capture_logs() as logs:
        rules = await config_files.load(_Ctx(Broken(MANIFEST)), POLISH_RULES)
    assert rules == config_files.default(POLISH_RULES)
    assert any(e["event"] == "factory_issue_config_unreadable" for e in logs)
