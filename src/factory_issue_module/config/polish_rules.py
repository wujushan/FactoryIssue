"""润色规则 `polish_rules.md` 的解析与校验（润色设计 §10、§2.2）。

格式与内置默认见 `2_landed/domestic/ai_polish.md`「润色规则（初始版本）」。上传的内容与内置默认走同一个解析函数
`parse`；`validate_config` 就是解析一遍，出错即拒收。报错原样显示在 Console 的上传框里，写成管理员看得懂的话。
内置默认在导入时解析（`config/files.py::SLOTS`）：那一节的标题或表头改坏了，模块导入即失败。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from factory_issue_module import landed
from factory_issue_module.config.errors import ConfigFormatError

SETTING_HEADER = ("项", "值")
FIELD_HEADER = ("栏目代码", "名称", "这一栏写什么", "原文格式", "默认字数上限")
RICH = "富文本"
PLAIN = "纯文字"
NO_LIMIT = "不限"
MAX_INPUT_KEY = "原文长度上限"
#: 原文长度上限的硬上限（§10）：管理员调大也不能超过它。实测（§12.3）6000 字单次约 54 秒、修一次就逼近单次超时
MAX_INPUT_CEILING = 8000
#: 初始的六种栏目与原文格式（是否富文本）：不能删、格式不能改，格式跟着页面的编辑器走（§10）
INITIAL_FIELDS: dict[str, bool] = {
    "problem_desc": True, "reason": True, "five_why_question": False, "five_why_answer": False,
    "measures": True, "prevention": True,
}
CODE_MAX = 64
ABOUT_MAX = 100
FREE_TEXT_MAX = 1000
#: 提示里程序生成的段名（§8.2；r2 起另有「原文语言」）：管理员写的文字里出现了，会和程序生成的部分混在一起
PROMPT_SECTIONS = ("【这一栏】", "【原文格式】", "【原文语言】", "【字数】", "【额外要求】", "【同一张单的其他内容】",
                   "【要润色的原文】")
#: 占位标记的两套写法（§6.1）
PLACEHOLDER_MARKS = ("[[", "]]", "⟦", "⟧")

_CODE = re.compile(r"[a-z][a-z0-9_]*")
_SUB = re.compile(r"^####\s+(.+?)\s*$")
#: 自由文字写这几种表示没有
_NONE = {"", "（没有）", "—", "-"}

_SECTIONS = ("### 设置", "### 栏目", "### 共用要求", "### 各栏要求")


@dataclass(frozen=True)
class PolishField:
    code: str
    name: str
    about: str
    rich: bool
    default_max: int | None
    requirements: str


@dataclass(frozen=True)
class PolishRules:
    max_input: int
    common: str
    fields: tuple[PolishField, ...]

    def field(self, code: str) -> PolishField | None:
        return next((f for f in self.fields if f.code == code), None)


# ---------------------------------------------------------------- 小工具


def _title(heading: str) -> str:
    return heading.lstrip("#").strip()


def _section(text: str, heading: str) -> str:
    try:
        return landed.section(text, heading, where="文件里")
    except landed.LandedParseError as exc:
        raise ConfigFormatError(
            f"缺少「{heading}」一节；文件要有四个小节：{'、'.join(_SECTIONS)}，标题照写"
        ) from exc


def _table(body: str, header: tuple[str, ...], heading: str) -> landed.MdTable:
    where = f"「{_title(heading)}」一节里"
    try:
        return landed.table_with_header(body, header, where=where)
    except landed.LandedParseError as exc:
        raise ConfigFormatError(f"{exc}；表头要逐字写成：| {' | '.join(header)} |") from exc


def _positive(cell: str) -> bool:
    """只认 ASCII 数字（`str.isdigit` 对「²」也为真，`int()` 却抛原生错误）。"""
    return re.fullmatch(r"[0-9]+", cell) is not None and int(cell) > 0


def _free(text: str) -> str:
    t = text.strip()
    return "" if t in _NONE else t


def _check_text(where: str, text: str) -> None:
    """要进提示的文字不能带占位写法与提示里的段名（§10「自由文字」）。"""
    for mark in PLACEHOLDER_MARKS:
        if mark in text:
            raise ConfigFormatError(f"{where}不能出现「{mark}」：这是程序给图片、表格、链接用的标记写法")
    for name in PROMPT_SECTIONS:
        if name in text:
            raise ConfigFormatError(f"{where}不能出现「{name}」：这是程序生成的提示里的段名")


def _check_free(where: str, text: str) -> str:
    body = _free(text)
    if len(body) > FREE_TEXT_MAX:
        raise ConfigFormatError(f"{where}不能超过 {FREE_TEXT_MAX} 字，现在是 {len(body)} 字")
    _check_text(where, body)
    return body


# ---------------------------------------------------------------- 四个小节


def _max_input(text: str) -> int:
    table = _table(_section(text, "### 设置"), SETTING_HEADER, "### 设置")
    values: dict[str, str] = {}
    for key, value in table.rows:
        if key != MAX_INPUT_KEY:
            raise ConfigFormatError(f"「设置」里只认「{MAX_INPUT_KEY}」一项，「{key}」不认识")
        if key in values:
            raise ConfigFormatError(f"「设置」里「{key}」写了不止一次")
        values[key] = value
    if MAX_INPUT_KEY not in values:
        raise ConfigFormatError(f"「设置」里缺「{MAX_INPUT_KEY}」")
    raw = values[MAX_INPUT_KEY]
    if not _positive(raw) or int(raw) > MAX_INPUT_CEILING:
        raise ConfigFormatError(
            f"「{MAX_INPUT_KEY}」要写 1 到 {MAX_INPUT_CEILING} 之间的整数（字），现在是「{raw}」"
        )
    return int(raw)


def _limit(cell: str, where: str) -> int | None:
    if cell == NO_LIMIT:
        return None
    if not _positive(cell):
        raise ConfigFormatError(f"{where}的默认字数上限要写「{NO_LIMIT}」或正整数，现在是「{cell}」")
    return int(cell)


def _fields(text: str) -> list[tuple[str, str, str, bool, int | None]]:
    table = _table(_section(text, "### 栏目"), FIELD_HEADER, "### 栏目")
    out: list[tuple[str, str, str, bool, int | None]] = []
    codes: set[str] = set()
    names: set[str] = set()
    for n, (code, name, about, fmt, limit) in enumerate(table.rows, start=1):
        where = f"栏目表第 {n} 行（「{code}」）" if code else f"栏目表第 {n} 行"
        if not code:
            raise ConfigFormatError(f"{where}缺栏目代码")
        if _CODE.fullmatch(code) is None or len(code) > CODE_MAX:
            raise ConfigFormatError(
                f"{where}的栏目代码只能用小写字母开头的小写字母、数字、下划线，至多 {CODE_MAX} 个字符"
            )
        if code in codes:
            raise ConfigFormatError(f"栏目代码「{code}」出现了不止一次")
        codes.add(code)
        if not name:
            raise ConfigFormatError(f"{where}缺名称")
        if name in names:
            raise ConfigFormatError(f"栏目名称「{name}」出现了不止一次")
        names.add(name)
        if not about:
            raise ConfigFormatError(f"{where}缺「这一栏写什么」")
        if len(about) > ABOUT_MAX:
            raise ConfigFormatError(f"{where}的「这一栏写什么」不能超过 {ABOUT_MAX} 字，现在是 {len(about)} 字")
        _check_text(f"{where}的名称", name)
        _check_text(f"{where}的「这一栏写什么」", about)
        if fmt not in (RICH, PLAIN):
            raise ConfigFormatError(f"{where}的原文格式只能是「{RICH}」或「{PLAIN}」，现在是「{fmt}」")
        rich = fmt == RICH
        if code in INITIAL_FIELDS and INITIAL_FIELDS[code] != rich:
            want = RICH if INITIAL_FIELDS[code] else PLAIN
            raise ConfigFormatError(f"栏目「{code}」的原文格式不能改，要写「{want}」：格式跟着页面的编辑器走")
        out.append((code, name, about, rich, _limit(limit, where)))
    missing = [c for c in INITIAL_FIELDS if c not in codes]
    if missing:
        raise ConfigFormatError(f"初始的栏目不能删，缺：{'、'.join(missing)}")
    return out


def _requirements(text: str, names: set[str]) -> dict[str, str]:
    """「### 各栏要求」：「（没有）」，或每种栏目一个「#### 栏目名称」小节 → {名称: 要求}。"""
    body = _section(text, "### 各栏要求")
    out: dict[str, str] = {}
    lead: list[str] = []
    current: str | None = None
    lines: list[str] = []

    def close() -> None:
        if current is not None:
            out[current] = _check_free(f"「各栏要求」里「{current}」一节", "\n".join(lines))

    for line in body.splitlines():
        m = _SUB.match(line)
        if m:
            close()
            name = m.group(1)
            if name not in names:
                raise ConfigFormatError(f"「各栏要求」里的小标题「{name}」不是栏目表里的名称")
            if name in out:
                raise ConfigFormatError(f"「各栏要求」里「{name}」写了不止一节")
            current, lines = name, []
        elif current is None:
            lead.append(line)
        else:
            lines.append(line)
    close()
    if _free("\n".join(lead)):
        raise ConfigFormatError(
            "「各栏要求」下要么只写「（没有）」，要么每种栏目一个「#### 栏目名称」小标题，要求写在小标题下面"
        )
    return out


def parse(text: str) -> PolishRules:
    max_input = _max_input(text)
    rows = _fields(text)
    common = _check_free("「共用要求」", _section(text, "### 共用要求"))
    reqs = _requirements(text, {name for _, name, _, _, _ in rows})
    fields = tuple(
        PolishField(code=code, name=name, about=about, rich=rich, default_max=limit, requirements=reqs.get(name, ""))
        for code, name, about, rich, limit in rows
    )
    return PolishRules(max_input=max_input, common=common, fields=fields)
