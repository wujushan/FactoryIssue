"""读随 wheel 分发的 `2_landed`（设计 §2.3、§9.1）。

信源只有 `docs/2_landed` 一份，代码里不抄第二份：术语、常用场景（`intents`）、必要澄清项、
初步分析维度、三个域、各表字段的「用户可见显示名」都在导入时从这里解析；说法清单、部门简称、
地区说法三份配置的内置默认值也从这里取原文（`config/defaults.py` 解析）。

防漂移：标题改名、表头变了或某行列数不对，导入时抛 `LandedParseError`，模块加载失败；
单测逐张表断言解析得出、行数与源文件一致（设计 §2.3）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from forge_core.module import AnalysisDimension, ClarifyDimension, GlossaryTerm

_PKG_DIR = Path(__file__).resolve().parent
_EMPTY_CELL = "—"
_INTERNAL = "（内部字段，不返回）"


class LandedParseError(RuntimeError):
    """`2_landed` 的某张表解析不出来（标题、表头或列数与代码约定的不一致）。"""


@cache
def landed_root() -> Path:
    """wheel 里是包内 `_landed_docs/`（pyproject 的 force-include）；源码树里是仓库的 `docs/2_landed/`。"""
    packaged = _PKG_DIR / "_landed_docs"
    if packaged.is_dir():
        return packaged
    repo = _PKG_DIR.parents[1] / "docs" / "2_landed"
    if repo.is_dir():
        return repo
    raise LandedParseError(f"找不到 2_landed：既没有 {packaged}，也没有 {repo}")


@cache
def read(rel: str) -> str:
    path = landed_root() / rel
    if not path.is_file():
        raise LandedParseError(f"2_landed 缺文件：{rel}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- Markdown 小工具


@dataclass(frozen=True)
class MdTable:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def column(self, name: str) -> int:
        return self.header.index(name)


_HEADING = re.compile(r"^(#{1,6})\s+\S")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _content_lines(text: str) -> list[tuple[str, bool]]:
    """逐行给出 (行, 是否在代码块里)。代码块里的 `#` 与 `|` 不算标题、不算表格。"""
    out: list[tuple[str, bool]] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            out.append((line, True))
            fenced = not fenced
            continue
        out.append((line, fenced))
    return out


def section(text: str, heading: str, *, where: str = "") -> str:
    """取 `heading`（整行，如「## 常用查询场景」）下的正文，到同级或更高级的下一个标题为止。"""
    level = len(heading) - len(heading.lstrip("#"))
    lines = _content_lines(text)
    start = None
    for i, (line, fenced) in enumerate(lines):
        if not fenced and line.rstrip() == heading:
            start = i + 1
            break
    if start is None:
        raise LandedParseError(f"{where or '2_landed'} 找不到标题「{heading}」")
    body: list[str] = []
    for line, fenced in lines[start:]:
        m = None if fenced else _HEADING.match(line)
        if m and len(m.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def _split_row(line: str) -> tuple[str, ...]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|") and not raw.endswith("\\|"):
        raw = raw[:-1]
    return tuple(cell.strip().replace("\\|", "|") for cell in _CELL_SPLIT.split(raw))


def tables(text: str, *, where: str = "") -> list[MdTable]:
    """正文里的全部 GFM 表格（允许缩进在列表项里）。列数与表头不一致即抛错。"""
    found: list[MdTable] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        if len(block) < 2 or not set(block[1].replace("|", "").strip()) <= set("-: "):
            raise LandedParseError(f"{where or '2_landed'} 有一张表缺表头分隔行：{block[0]!r}")
        header = _split_row(block[0])
        rows = []
        for n, line in enumerate(block[2:], start=1):
            cells = _split_row(line)
            if len(cells) != len(header):
                raise LandedParseError(
                    f"{where or '2_landed'} 表「{' | '.join(header)}」第 {n} 行有 {len(cells)} 列，"
                    f"表头是 {len(header)} 列"
                )
            rows.append(cells)
        found.append(MdTable(header=header, rows=tuple(rows)))
        block.clear()

    for line, fenced in _content_lines(text):
        if not fenced and line.lstrip().startswith("|"):
            block.append(line.strip())
        else:
            flush()
    flush()
    return found


def table_with_header(text: str, header: Sequence[str], *, where: str = "") -> MdTable:
    """第一张表头与 `header` 逐字相同的表；没有就抛错。"""
    want = tuple(header)
    for table in tables(text, where=where):
        if table.header == want:
            return table
    raise LandedParseError(f"{where or '2_landed'} 找不到表头为「{' | '.join(want)}」的表")


def split_items(cell: str, sep: str = "、") -> list[str]:
    """按「、」拆一格；「—」或空格表示没有。"""
    cell = cell.strip()
    if not cell or cell == _EMPTY_CELL:
        return []
    return [item.strip() for item in cell.split(sep) if item.strip()]


# ---------------------------------------------------------------- 总述与术语表

_SUMMARY = "business_description.md"


@dataclass(frozen=True)
class Scene:
    """总述「常用查询场景」一行。"""

    name: str
    answers: str
    examples: tuple[str, ...]


@cache
def scenes() -> tuple[Scene, ...]:
    where = f"{_SUMMARY}「常用查询场景」"
    body = section(read(_SUMMARY), "## 常用查询场景", where=where)
    table = table_with_header(body, ("场景", "能回答什么", "示例问题"), where=where)
    out = []
    for name, answers, examples in table.rows:
        items = tuple(e.strip() for e in examples.split(" / ") if e.strip())
        if not name or not answers or not items:
            raise LandedParseError(f"{where}「{name}」一行缺内容")
        out.append(Scene(name=name, answers=answers, examples=items))
    return tuple(out)


def intents() -> list[str]:
    """`manifest.intents`：各场景的示例问题按「 / 」拆开（设计 §2.1）。"""
    return [example for scene in scenes() for example in scene.examples]


@cache
def _glossary_rows() -> tuple[tuple[str, ...], ...]:
    where = "glossary.md"
    return table_with_header(read("glossary.md"), ("规范词", "别称", "口径定义"), where=where).rows


def glossary() -> list[GlossaryTerm]:
    return [
        GlossaryTerm(term=term, aliases=split_items(aliases), definition=definition)
        for term, aliases, definition in _glossary_rows()
    ]


@cache
def _clarify_rows() -> tuple[tuple[str, ...], ...]:
    where = f"{_SUMMARY}「必要澄清项」"
    body = section(read(_SUMMARY), "## 必要澄清项", where=where)
    return table_with_header(body, ("缺什么", "追问什么", "示例回答"), where=where).rows


def clarify_dimensions() -> list[ClarifyDimension]:
    return [
        ClarifyDimension(name=name, question=question, examples=split_items(examples))
        for name, question, examples in _clarify_rows()
    ]


_CHART_TYPES = {"柱状": "bar", "饼图": "pie", "折线": "line"}


@cache
def _analysis_rows() -> tuple[tuple[str, ...], ...]:
    where = f"{_SUMMARY}「初步分析维度」"
    body = section(read(_SUMMARY), "## 初步分析维度", where=where)
    rows = table_with_header(body, ("维度", "看什么", "图型"), where=where).rows
    for name, _desc, chart in rows:
        if chart not in _CHART_TYPES:
            raise LandedParseError(f"{where}「{name}」的图型「{chart}」不认识")
    return rows


def analysis_dimensions() -> list[AnalysisDimension]:
    return [
        AnalysisDimension(name=name, description=desc, chart=_CHART_TYPES[chart])
        for name, desc, chart in _analysis_rows()
    ]


@dataclass(frozen=True)
class DomainInfo:
    """总述「三个域」一行：域名、单号前缀、管什么。"""

    name: str
    prefix: str
    scope: str


@cache
def domains() -> tuple[DomainInfo, ...]:
    where = f"{_SUMMARY}「三个域」"
    body = section(read(_SUMMARY), "## 三个域", where=where)
    table = table_with_header(body, ("域", "单号前缀", "管什么", "不管什么"), where=where)
    return tuple(
        DomainInfo(name=name, prefix=prefix.strip("`"), scope=scope)
        for name, prefix, scope, _not in table.rows
    )


# ---------------------------------------------------------------- 三份配置默认值的原文


def dept_aliases_section() -> str:
    """总述「部门名称怎么对」整节（含简称表），`dept_aliases.md` 的内置默认值从这里解析。"""
    return section(read(_SUMMARY), "### 部门名称怎么对", where=f"{_SUMMARY}「部门名称怎么对」")


def factory_regions_section() -> str:
    """国内「加工厂」整节（含地区说法表），`factory_regions.md` 的内置默认值从这里解析。"""
    rel = "domestic/business_description.md"
    return section(read(rel), "### 加工厂", where=f"{rel}「加工厂」")


def topic_terms_text() -> str:
    """`topic_terms.md` 全文，`topic_terms.md` 配置的内置默认值从这里解析。"""
    return read("topic_terms.md")


def comparison_scope_section() -> str:
    """总述「比对范围」整节（`segmentation.toml` 默认环节清单的单测对照原文）。"""
    return section(read(_SUMMARY), "### 比对范围", where=f"{_SUMMARY}「比对范围」")


# ---------------------------------------------------------------- db_description 显示名

_SOURCE_LINE = re.compile(r"^- \*\*数据源别名（source）\*\*：\s*(\S+)\s*$", re.MULTILINE)
_TABLE_LINE = re.compile(r"^- \*\*物理表名（table）\*\*：\s*(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class TableDoc:
    """一个 db_description 表文件：所属数据源、物理表名、各列的显示名。

    `columns` 的值为 None 表示标了「内部字段，不返回」；`keys` 是 JSON 列里各键的显示名。
    """

    file: str
    source: str
    table: str
    columns: dict[str, str | None]
    keys: dict[str, str | None]


@cache
def table_docs() -> dict[str, TableDoc]:
    """物理表名 → 表文件的解析结果。每个表文件都要解析得出 source、物理表名与字段表。"""
    out: dict[str, TableDoc] = {}
    folder = landed_root() / "db_description"
    for path in sorted(folder.glob("db_*.md")):
        rel = f"db_description/{path.name}"
        text = read(rel)
        source = _SOURCE_LINE.search(text)
        table = _TABLE_LINE.search(text)
        if not source or not table:
            raise LandedParseError(f"{rel} 缺「数据源别名（source）」或「物理表名（table）」一行")
        columns: dict[str, str | None] = {}
        keys: dict[str, str | None] = {}
        for t in tables(text, where=rel):
            if "用户可见显示名" not in t.header:
                continue
            target = {"字段": columns, "键": keys}.get(t.header[0])
            if target is None:
                continue
            col = t.column("用户可见显示名")
            for row in t.rows:
                name = row[0].strip("`")
                display = row[col]
                target[name] = None if display == _INTERNAL else display
        if not columns:
            raise LandedParseError(f"{rel} 没有带「用户可见显示名」的字段表")
        out[table.group(1)] = TableDoc(
            file=rel, source=source.group(1), table=table.group(1), columns=columns, keys=keys
        )
    if not out:
        raise LandedParseError("db_description 下没有表文件")
    return out


def display_name(table: str, column: str) -> str | None:
    """（物理表名, 列名）的用户可见显示名；内部字段返回 None。没写这一列即抛 KeyError。"""
    return table_docs()[table].columns[column]


def _parse_all() -> None:
    """导入时把各张表都解析一遍：任一张对不上，模块加载即失败（设计 §2.3）。"""
    scenes()
    _glossary_rows()
    _clarify_rows()
    _analysis_rows()
    domains()
    table_docs()


_parse_all()
