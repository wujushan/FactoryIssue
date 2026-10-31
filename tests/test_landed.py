"""`landed.py` 每张表都解析得出、行数与源文件一致；声明与 `2_landed` 不漂移（设计 §2.3、§2.2）。

行数用另一套最朴素的写法（数以「|」开头的行）独立数一遍，与解析结果对照。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from factory_issue_module import landed
from factory_issue_module.declarations import (
    DATA_SOURCES,
    DOMAINS,
    ERP,
    INFO,
    JOINS,
    MART,
    Domain,
)
from factory_issue_module.module import FactoryIssueModule

ROOT = Path(__file__).resolve().parents[1]
LANDED = ROOT / "docs" / "2_landed"
MANIFEST = FactoryIssueModule.manifest


def _raw(rel: str) -> str:
    return (LANDED / rel).read_text(encoding="utf-8")


def _rows_under(rel: str, heading: str, header_start: str) -> list[list[str]]:
    """朴素数法：标题下第一张以 `header_start` 开头的表的数据行。"""
    lines = _raw(rel).splitlines()
    i = lines.index(heading)
    while not lines[i].lstrip().startswith(header_start):
        i += 1
    rows = []
    for line in lines[i + 2 :]:
        if not line.lstrip().startswith("|"):
            break
        rows.append([c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]])
    return rows


def test_landed_root_is_the_repo_copy_in_source_tree():
    assert landed.landed_root() == LANDED


def test_scenes_and_intents_match_source():
    rows = _rows_under("business_description.md", "## 常用查询场景", "| 场景 |")
    assert [s.name for s in landed.scenes()] == [r[0] for r in rows]
    expected = [e.strip() for r in rows for e in r[2].split(" / ")]
    assert landed.intents() == expected
    assert len(expected) == 25  # 设计 §2.1「现为 25 句」
    assert MANIFEST.intents == expected


def test_glossary_matches_source():
    rows = _rows_under("glossary.md", "# 业务术语表", "| 规范词 |")
    terms = landed.glossary()
    assert [t.term for t in terms] == [r[0] for r in rows]
    assert [t.term for t in MANIFEST.glossary] == [r[0] for r in rows]
    by_term = {t.term: t for t in terms}
    assert by_term["当前责任人"].aliases == ["当前处理人", "当前谁在处理", "手上的单", "待处理的单"]
    assert by_term["国内工厂"].aliases == []  # 「—」= 没有别称


def test_glossary_header_says_module_reads_it():
    head = _raw("glossary.md").splitlines()[2]
    assert "须同步" not in head
    assert "landed.py" in head


def test_clarify_dimensions_match_source():
    rows = _rows_under("business_description.md", "## 必要澄清项", "| 缺什么 |")
    dims = landed.clarify_dimensions()
    assert [d.name for d in dims] == [r[0] for r in rows]
    assert dims[0].examples == ["今年", "近 30 天", "2026 年上半年", "不限时间"]
    assert MANIFEST.clarify_dimensions == dims


def test_analysis_dimensions_match_source():
    rows = _rows_under("business_description.md", "## 初步分析维度", "| 维度 |")
    dims = landed.analysis_dimensions()
    assert [d.name for d in dims] == [r[0] for r in rows]
    assert {d.chart for d in dims} <= {"bar", "pie", "line"}
    assert {d.name: d.chart for d in dims}["时间"] == "line"
    assert MANIFEST.analysis_dimensions == dims


def test_domains_match_source():
    rows = _rows_under("business_description.md", "## 三个域", "| 域 |")
    assert [(d.name, d.prefix) for d in landed.domains()] == [(r[0], r[1].strip("`")) for r in rows]
    assert [d.label for d in DOMAINS] == ["国内", "巴西", "海外"]
    assert [d.prefix for d in DOMAINS] == ["ZC", "BR", "HW"]


def _field_rows(text: str) -> int:
    """朴素数法：所有「| 字段 |…用户可见显示名…」表的数据行之和。"""
    lines = text.splitlines()
    total = 0
    for i, line in enumerate(lines):
        if line.startswith("| 字段 |") and "用户可见显示名" in line:
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                total += 1
    return total


def test_every_table_doc_parses_with_all_rows():
    files = sorted((LANDED / "db_description").glob("db_*.md"))
    docs = landed.table_docs()
    assert len(docs) == len(files) == 35  # 32 张原始表 + 产物库 3 个表族文件（S6）
    for doc in docs.values():
        assert doc.source in {INFO, ERP, MART}
        assert len(doc.columns) == _field_rows(_raw(doc.file)), doc.file
    main = docs[Domain.DOMESTIC.master_table]
    assert main.columns["ID"] is None  # 内部字段
    assert main.columns["Numbers"] == "问题编号"
    assert landed.display_name("CoreINFO.dbo.ZCTracking_ProblemList", "AddDate") == "建单时间"


def _family(table: str) -> set[str]:
    """产物库的表族文件写的是国内那张（`public.domestic_…`）；`data_sources` 里三域各一张、不带 `public.`。"""
    tail = table.removeprefix("public.")
    return {tail.replace("domestic_", f"{d.value}_", 1) for d in DOMAINS}


def test_declared_tables_match_db_description_sources():
    docs = landed.table_docs()
    by_source: dict[str, set[str]] = {}
    for doc in docs.values():
        tables = _family(doc.table) if doc.source == MART else {doc.table}
        by_source.setdefault(doc.source, set()).update(tables)
    declared = {ref.alias: set(ref.tables) for ref in DATA_SOURCES}
    assert declared == by_source
    assert len(declared[INFO]) == 31 and len(declared[ERP]) == 1 and len(declared[MART]) == 9
    assert declared[MART] == {t for d in DOMAINS for t in d.mart_tables}
    assert MANIFEST.source_aliases == {INFO, ERP, MART}


def test_mart_text_columns_and_seg_fields_match_source():
    cols = _rows_under(landed.MART_TEXT_DOC, "## 成员差异：各域的叙述列", "| 字段 |")
    parsed = landed.text_columns()
    assert [c.name for c in parsed] == [r[0] for r in cols]
    assert len(parsed) == 25
    assert {c.name: set(c.sources) for c in parsed}["f_sqe"] == {"巴西"}
    fields = _rows_under(landed.MART_SEG_DOC, "## 字段代号", "| 代号 |")
    assert list(landed.seg_fields()) == [r[0] for r in fields]
    assert list(landed.seg_fields()) == ["phen", "desc", "reason", "improve", "measure", "prev", "sqe", "step"]
    assert landed.seg_fields()["phen"]["海外"] == "已选问题现象"


def _privileges_listed_tables() -> set[str]:
    """`privileges.md`「权限里要列出的表」第一列的四段名。同一格里后几个只写尾段，沿用前一个的前缀。"""
    body = landed.section(landed.read("privileges.md"), "## 权限里要列出的表")
    table = landed.table_with_header(body, ("表（四段名）", "放在哪", "何时给「允许」"))
    names: set[str] = set()
    for row in table.rows:
        prefix = ""
        for token in re.findall(r"`([^`]+)`", row[0]):
            if not re.fullmatch(r"[\w.]+", token):
                continue  # 如分组行里的「inherit_parent: true」
            if token.count(".") == 3:
                prefix = token.rsplit(".", 1)[0]
                names.add(token)
            else:
                names.add(f"{prefix}.{token}")
    return names


def test_declared_tables_match_privileges_list():
    """`privileges.md` 列的 41 张去掉实例段，即 `data_sources` 声明的 41 张（原始表 32 张 + mart 9 张）。"""
    listed = _privileges_listed_tables()
    assert len(listed) == 41
    raw = {n.split(".", 1)[1] for n in listed if not n.startswith("mart.")}
    declared = {t for ref in DATA_SOURCES if ref.alias != MART for t in ref.tables}
    assert raw == declared
    mart = {n.rsplit(".", 1)[1] for n in listed if n.startswith("mart.")}
    assert mart == {t for d in DOMAINS for t in d.mart_tables}
    assert mart == set(next(ref.tables for ref in DATA_SOURCES if ref.alias == MART))


def test_joins_cover_every_sub_table_inner_only():
    assert len(JOINS) == 14
    pairs = {(e.left, e.right) for e in JOINS}
    assert pairs == {(d.master_table, s) for d in DOMAINS for s in d.sub_tables}
    assert all([t.value for t in e.types] == ["INNER"] for e in JOINS)


def test_manifest_field_mappings_is_table_level_only():
    """mart 别名不填 `field_mappings`（G2「权限承载列清单」：无）。"""
    assert MANIFEST.field_mappings == {INFO: {"info.dbo.tbTask": {"ftable": "ftable"}}}
    assert MANIFEST.require_privileges is True


def test_vectorize_is_g2_three_specs_verbatim():
    """G2「向量表」的 3 条：来源是按意思找的段表，`metadata_columns` 建表后不能再改。"""
    got = [(v.source, v.vector_table, v.origin_table, v.id_column, v.text_columns, v.default_cron,
            v.metadata_columns) for v in MANIFEST.vectorize]
    assert got == [
        (MART, f"{d}_issue_vec", f"{d}_issue_vseg", "seg_id", ["seg_text"], "10,40 * * * *", ["issue_id", "field"])
        for d in ("domestic", "brazil", "overseas")
    ]
    mart_tables = next(ref.tables for ref in DATA_SOURCES if ref.alias == MART)
    assert not any(t.endswith("_vseg") for t in mart_tables)  # 按意思找的段表不声明、不读（G2）


def test_jobs_are_the_two_governance_tasks():
    jobs = FactoryIssueModule().jobs()
    assert [(j.spec.name, j.spec.default_cron) for j in jobs] == [
        ("sync_issue_text", "*/30 * * * *"), ("rebuild_issue_text", "30 2 * * *"),
    ]


@pytest.mark.parametrize("bad", ["| 场景 | 能回答什么 |\n|---|---|\n| a | b |", "没有表"])
def test_parse_errors_are_loud(bad):
    with pytest.raises(landed.LandedParseError):
        landed.table_with_header(bad, ("场景", "能回答什么", "示例问题"))


def test_row_with_wrong_column_count_is_rejected():
    text = "| a | b |\n|---|---|\n| 1 | 2 | 3 |"
    with pytest.raises(landed.LandedParseError, match="第 1 行有 3 列"):
        landed.tables(text)


def test_escaped_pipe_stays_inside_cell():
    (table,) = landed.tables("| a | b |\n|---|---|\n| 其他\\|备注 | x |")
    assert table.rows == (("其他|备注", "x"),)
