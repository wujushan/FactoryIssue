"""配置解析、`validate_config` 与读取回退（设计 §11）。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import structlog
from fakes import MANIFEST, FakeConfig

from factory_issue_module import landed
from factory_issue_module.config import defaults, files
from factory_issue_module.config.files import ConfigFormatError
from factory_issue_module.declarations import (
    ANSWER_PARAMS,
    DEPT_ALIASES,
    FACTORY_REGIONS,
    LINK_SITES,
    SEGMENTATION,
    TOPIC_TERMS,
)
from factory_issue_module.module import FactoryIssueModule

ROOT = Path(__file__).resolve().parents[1]
MODULE = FactoryIssueModule()


def validate(name: str, text: str) -> None:
    MODULE.validate_config(name, text)


# ---------------------------------------------------------------- 内置默认值与源文件一致


def test_declared_config_files_are_the_six_slots():
    assert [s.name for s in MANIFEST.config_files] == [
        TOPIC_TERMS, SEGMENTATION, DEPT_ALIASES, FACTORY_REGIONS, ANSWER_PARAMS, LINK_SITES,
    ]
    assert set(files.SLOTS) == {s.name for s in MANIFEST.config_files}
    # 只有站点地址标必填：它随环境不同、没有内置默认值，没传时平台启动告警一次（不阻断）
    assert [s.name for s in MANIFEST.config_files if s.required] == [LINK_SITES]


def test_topic_terms_default_is_the_landed_list():
    body = landed.section(landed.topic_terms_text(), "## 清单")
    rows = [line for line in body.splitlines() if line.startswith("|")][2:]
    terms = files.default(TOPIC_TERMS)
    assert len(terms.topics) == len(rows) == 14
    audio = terms.get("音频")
    assert audio is not None
    assert [t.text for t in audio.terms if t.ambiguous] == ["声音", "杂音", "破音"]
    assert "喇叭" in [t.text for t in audio.terms]
    printing = terms.get("打印")
    assert printing is not None and "打印机盖" in printing.excluded
    assert terms.get("音频").excluded == ()  # 「—」= 没有


def test_landed_topic_terms_file_passes_validation_as_upload():
    validate(TOPIC_TERMS, landed.topic_terms_text())


def test_dept_aliases_default_is_the_landed_table():
    table = files.default(DEPT_ALIASES)
    assert len(table.entries) == 4
    assert table.owner_of("工程部") == "生产工程部"
    assert table.owner_of("IT部门") == "信息技术部"
    assert table.owner_of("研 一") == "研发一部"  # 忽略空格
    assert table.owner_of("质量部") is None


def test_factory_regions_default_is_the_landed_table():
    table = files.default(FACTORY_REGIONS)
    assert table.items_of("惠州") == ("柯洱斯", "亮亮", "惠州百富")
    assert table.items_of("深圳") is None


def test_segmentation_default_matches_g2_and_comparison_scope():
    seg = files.default(SEGMENTATION)
    assert (seg.rule, seg.split_over, seg.seg_min, seg.seg_max, seg.overlap) == (
        "field_split", 500, 300, 500, "sentence",
    )
    g2 = (ROOT / "docs/decisions/2026-10-20-G2数据源与治理决策.md").read_text(encoding="utf-8")
    rules = landed.section(g2, "### 整理规则（文字表与两张段表共用）")
    assert "`field_split`（默认）" in rules
    assert "超过约 500 字的按段落切成约 300–500 字的段，相邻段重叠一句" in rules
    assert "`phen`、`desc`、`reason`" in rules and "归第一组" in rules
    assert "`improve`、`measure`、`prev`、`sqe`、`step` 归第二组" in rules
    assert seg.groups == {"first": ("phen", "desc", "reason"),
                          "second": ("improve", "measure", "prev", "sqe", "step")}

    scope = landed.comparison_scope_section()
    domestic = re.search(r"\*\*国内纳入的环节\*\*（按编码）：\n((?:\s+- \d+ .+\n)+)", scope)
    assert domestic is not None
    codes = tuple(int(m) for m in re.findall(r"- (\d+) ", domestic.group(1)))
    assert seg.domestic_codes == codes
    overseas = re.search(r"\*\*海外纳入的环节\*\*（按名称）：(.+?)。", scope)
    assert overseas is not None
    assert seg.overseas_names == tuple(overseas.group(1).split("、"))
    assert seg.group_of("step") == "second"


def test_answer_params_default():
    p = files.default(ANSWER_PARAMS)
    assert (p.top_n, p.export_threshold, p.table_rows, p.judge_max, p.rerank_max) == (
        10, 20, 20, 30, 100,
    )
    assert p.rerank_score_threshold is None and p.custom_stats_enabled is True
    assert p.similar_rerank_floor == 0.2 and p.similar_rows == 5


# ---------------------------------------------------------------- validate_config 正反例

TOPIC_HEAD = "## 清单\n\n| 话题 | 一句话说明 | 算的说法（＊ = 有歧义） | 不算的说法 |\n|---|---|---|---|\n"


def topic_doc(*rows: str) -> str:
    return "# 说法清单\n\n" + TOPIC_HEAD + "\n".join(rows) + "\n"


def test_topic_terms_accepts_minimal_doc():
    validate(TOPIC_TERMS, topic_doc("| 非接 | 非接触读卡 | NFC、非接、＊RF | 非接丝印 |"))


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("| 非接 | 非接触读卡 | NFC、*RF | — |", "全角"),
        ("| 非接 | 非接触读卡 | NFC、R＊F | — |", "开头"),
        ("| 非接 | 非接触读卡 | NFC、＊＊RF | — |", "开头"),
        ("| 非接 | 非接触读卡 | NFC、＊ | — |", "缺说法"),
        ("| 非接 | 非接触读卡 | NFC | ＊丝印 |", "不能带"),
        ("| 音频 | 发声 | 喇叭、声 | — |", "不足 2 个字"),
        ("| 音频 | 发声 | 喇叭 | 音 |", "不足 2 个字"),
        ("| 音频 | 发声 | 喇叭、喇 叭 | — |", "重复"),
        ("| 音频 | 发声 | 喇叭、＊喇叭 | — |", "重复"),
        ("| 音频 | 发声 | 喇叭 | 杂音、杂音 |", "重复"),
        ("| 音频 | 发声 | 喇叭、杂音 | 杂音 |", "同时写在"),
        ("| 音频 |  | 喇叭 | — |", "说明"),
        ("| 音频 | 发声 | — | 杂音 |", "至少要有一个"),
        ("|  | 发声 | 喇叭 | — |", "话题名称"),
        ("| 音频 | 发声 | 喇叭 |", "列"),
    ],
)
def test_topic_terms_rejects(row, message):
    with pytest.raises(ConfigFormatError, match=message):
        validate(TOPIC_TERMS, topic_doc(row))


def test_topic_terms_rejects_duplicate_topic_and_missing_heading():
    with pytest.raises(ConfigFormatError, match="不止一次"):
        validate(TOPIC_TERMS, topic_doc("| 音频 | a | 喇叭 | — |", "| 音频 | b | 蜂鸣器 | — |"))
    with pytest.raises(ConfigFormatError, match="## 清单"):
        validate(TOPIC_TERMS, "| 话题 | 一句话说明 | 算的说法（＊ = 有歧义） | 不算的说法 |\n|---|---|---|---|\n")
    with pytest.raises(ConfigFormatError, match="表头"):
        validate(TOPIC_TERMS, "## 清单\n\n| 话题 | 说明 | 说法 | 不算 |\n|---|---|---|---|\n| a | b | cc | — |\n")


def test_segmentation_accepts_partial_file():
    validate(SEGMENTATION, 'rule = "field"\n')
    seg = files.parse_segmentation('rule = "whole"\n[steps]\ndomestic_codes = [3, 4]\n')
    assert seg.rule == "whole" and seg.domestic_codes == (3, 4)
    assert seg.overseas_names == files.default(SEGMENTATION).overseas_names


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('rule = "chunk"\n', "rule"),
        ("seg_min = 0\n", "正整数"),
        ("seg_max = 200\n", "不能大于"),
        ("split_over = true\n", "正整数"),
        ('overlap = "two"\n', "overlap"),
        ("segmax = 300\n", "不认识"),
        ('[groups]\nfirst = ["phen", "desc", "reason", "step"]\n', "同时归在"),
        ('[groups]\nfirst = ["phen", "desc"]\n', "没有覆盖"),
        ('[groups]\nfirst = ["phen", "desc", "reason", "title"]\n', "不是字段代号"),
        ('[groups]\nthird = ["x"]\n', "不认识"),
        ('[steps]\ndomestic_codes = ["3"]\n', "整数"),
        ("[steps]\ndomestic_codes = [3, true]\n", "整数"),
        ('[steps]\noverseas_names = ["SQE跟进", ""]\n', "环节名称"),
        ("rule = \n", "TOML"),
    ],
)
def test_segmentation_rejects(text, message):
    with pytest.raises(ConfigFormatError, match=message):
        validate(SEGMENTATION, text)


DEPT_HEAD = "| 正式部门名称 | 简称、日常说法 |\n|---|---|\n"


def test_dept_aliases_accepts_and_rejects():
    validate(DEPT_ALIASES, DEPT_HEAD + "| 生产工程部 | 工程部、生工 |\n| 研发一部 | 一部 |\n")
    with pytest.raises(ConfigFormatError, match="同时对到了"):
        validate(DEPT_ALIASES, DEPT_HEAD + "| 研发一部 | 一部 |\n| 生产一部 | 一部 |\n")
    with pytest.raises(ConfigFormatError, match="表头"):
        validate(DEPT_ALIASES, "| 部门 | 简称 |\n|---|---|\n| 研发一部 | 一部 |\n")
    with pytest.raises(ConfigFormatError, match="缺正式部门名称"):
        validate(DEPT_ALIASES, DEPT_HEAD + "|  | 一部 |\n")


REGION_HEAD = "| 地区说法 | 对到的工厂 |\n|---|---|\n"


def test_factory_regions_accepts_and_rejects():
    validate(FACTORY_REGIONS, REGION_HEAD + "| 惠州 | 柯洱斯、亮亮、惠州百富 |\n")
    with pytest.raises(ConfigFormatError, match="「、」分隔"):
        validate(FACTORY_REGIONS, REGION_HEAD + "| 惠州 | 柯洱斯，亮亮 |\n")
    with pytest.raises(ConfigFormatError, match="不止一次"):
        validate(FACTORY_REGIONS, REGION_HEAD + "| 惠州 | 亮亮 |\n| 惠 州 | 柯洱斯 |\n")
    with pytest.raises(ConfigFormatError, match="没有写"):
        validate(FACTORY_REGIONS, REGION_HEAD + "| 惠州 | — |\n")


def test_answer_params_accepts_and_rejects():
    validate(ANSWER_PARAMS, "top_n = 5\nrerank_score_threshold = 0.3\ncustom_stats_enabled = false\n")
    assert files.parse_answer_params("rerank_score_threshold = 1\n").rerank_score_threshold == 1.0
    assert files.parse_answer_params("similar_rerank_floor = 0\n").similar_rerank_floor == 0.0
    assert files.parse_answer_params("similar_rows = 10\n").similar_rows == 10
    # 每域列几张不超过逐张判断的张数：没判断过的不列（决策 2026-11-03「回答骨架与排版」）
    from factory_issue_module.skills import text_search
    assert files.SIMILAR_ROWS_MAX == text_search.SIM_JUDGE
    # 结论里的要点与需关注的单（决策 2026-11-03「结论的要点与需关注的单」）：默认值照总述，写 0 即不给
    p = files.parse_answer_params("points_max = 0\nfocus_max = 0\n")
    assert (p.points_max, p.focus_max) == (0, 0)
    d = files.parse_answer_params("")
    assert (d.points_max, d.focus_max, d.concentrate_share, d.repeat_min, d.trend_months, d.close_min) == \
        (4, 3, 40, 3, 3, 5)
    for text, message in [
        ("points_max = 7\n", "0 到 6"),
        ("concentrate_share = 0\n", "1 到 100"),
        ("repeat_min = 1\n", "2 到 1000"),
        ("close_min = 2.5\n", "1 到 1000"),
        ("top_n = 0\n", "正整数"),
        ("top_n = true\n", "正整数"),
        ("table_rows = 2.5\n", "正整数"),
        ("rerank_score_threshold = 1.5\n", "0 到 1"),
        ("similar_rerank_floor = -0.1\n", "0 到 1"),
        ("similar_rows = 0\n", "1 到 10"),
        ("similar_rows = 11\n", "1 到 10"),
        ("similar_rows = 2.5\n", "1 到 10"),
        ('similar_rerank_floor = "0.2"\n', "0 到 1"),
        ('custom_stats_enabled = "yes"\n', "true 或 false"),
        ("topn = 5\n", "不认识"),
    ]:
        with pytest.raises(ConfigFormatError, match=message):
            validate(ANSWER_PARAMS, text)


def test_link_sites_default_is_empty_no_link():
    assert files.default(LINK_SITES) == files.LinkSites()


def test_link_sites_accepts_host_port_and_scheme():
    s = files.parse_link_sites('issue = "info.example.test"\n')
    assert s == files.LinkSites("https://info.example.test", "https://info.example.test", "https://info.example.test")
    s = files.parse_link_sites('issue = "10.1.2.3:8080"\nbrazil = "http://br.example.test"\n')
    assert (s.issue, s.brazil, s.attachment) == ("https://10.1.2.3:8080", "http://br.example.test",
                                                 "https://10.1.2.3:8080")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('issue = "info.example.test/"\n', "末尾"),
        ('issue = "info.example.test/#/QualityManage"\n', "不写路径"),
        ('issue = "ftp://info.example.test"\n', "不写路径"),
        ('issue = "info.example.test:70000"\n', "端口"),
        ('issue = ""\n', "字符串"),
        ("issue = 1\n", "字符串"),
        ('site = "info.example.test"\n', "不认识"),
        ('issue = \n', "TOML"),
        # 平台的必填只看传没传过：传了却没写 issue，国内问题编号照样不带链接，要在保存时拦下
        ("", "缺 issue"),
        ("# 测试环境站点\n\n", "缺 issue"),
        ('brazil = "br.example.test"\n', "缺 issue"),
        ('brazil = "br.example.test"\nattachment = "files.example.test"\n', "缺 issue"),
    ],
)
def test_link_sites_rejects(text, message):
    with pytest.raises(ConfigFormatError, match=message):
        validate(LINK_SITES, text)


async def test_link_sites_stored_without_issue_falls_back_to_no_link():
    """这条校验之前存下的、没写 issue 的版本：读时解析失败，回退为不生成链接并留 WARNING，不拿 brazil 顶替。"""
    config = FakeConfig(MANIFEST, {LINK_SITES: ['brazil = "br.example.test"\n']})
    with structlog.testing.capture_logs() as logs:
        sites = await files.load(_Ctx(config), LINK_SITES)
    assert sites == files.LinkSites()
    assert any(e["event"] == "factory_issue_config_fallback" and e["file"] == LINK_SITES for e in logs)


def test_unknown_config_name_is_not_rejected():
    validate("future.json", "{}")


# ---------------------------------------------------------------- 读取：默认值、缓存、回退


class _Ctx:
    def __init__(self, config):
        self.config = config


async def test_load_uses_default_when_missing_or_no_config_handle():
    assert await files.load(_Ctx(None), ANSWER_PARAMS) == files.default(ANSWER_PARAMS)
    assert await files.load(_Ctx(FakeConfig(MANIFEST)), ANSWER_PARAMS) == files.default(ANSWER_PARAMS)


async def test_load_parses_upload_and_caches_by_version(monkeypatch):
    config = FakeConfig(MANIFEST, {ANSWER_PARAMS: ["top_n = 3\n"]})
    first = await files.load(_Ctx(config), ANSWER_PARAMS)
    assert first.top_n == 3
    calls = []
    original = files.parse_answer_params

    def spy(text):
        calls.append(text)
        return original(text)

    monkeypatch.setitem(files.SLOTS, ANSWER_PARAMS, files._Slot(spy, files.default(ANSWER_PARAMS)))
    again = await files.load(_Ctx(config), ANSWER_PARAMS)
    assert again.top_n == 3 and calls == []  # 同一版本走缓存
    config.versions[ANSWER_PARAMS].append("top_n = 7\n")
    newer = await files.load(_Ctx(config), ANSWER_PARAMS)
    assert newer.top_n == 7 and len(calls) == 1


async def test_load_falls_back_to_default_on_broken_stored_text():
    config = FakeConfig(MANIFEST, {SEGMENTATION: ['rule = "nope"\n']})
    with structlog.testing.capture_logs() as logs:
        seg = await files.load(_Ctx(config), SEGMENTATION)
    assert seg == files.default(SEGMENTATION)
    assert any(e["event"] == "factory_issue_config_fallback" for e in logs)


async def test_load_undeclared_name_is_a_bug_not_a_default():
    from forge_core.errors import ConfigFileNotDeclared

    files.SLOTS["undeclared.toml"] = files._Slot(files.parse_answer_params, None)
    try:
        with pytest.raises(ConfigFileNotDeclared):
            await files.load(_Ctx(FakeConfig(MANIFEST)), "undeclared.toml")
    finally:
        del files.SLOTS["undeclared.toml"]


def test_defaults_module_has_no_hand_copied_tables():
    """三份表格形态的默认值只从 2_landed 取原文（§2.3），defaults.py 里不抄说法、简称、地区。"""
    source = Path(defaults.__file__).read_text(encoding="utf-8")
    for word in ("喇叭", "生产工程部", "柯洱斯"):
        assert word not in source
