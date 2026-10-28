"""名字对库（设计 §6.5）。纯函数：比较是字符串处理，不产生给用户的数字。

取值清单（机型、系列、工厂、部门、人员）由调用方按可查的域取一次再传进来（S2 起由 `domains/shared.py` 取）。
规则照 `2_landed`：

- 机型、系列：总述「机型与系列怎么对」。不分大小写，忽略空格、连字符、下划线，按完整名称；系列两边都不看
  末尾的「系列」。「X 各款」（计划里的「机型 包含 X」，只来自 §5.3 第 9 条）取 X 与「X + 字母」的机型。
- 部门：总述「部门名称怎么对」，完整名称 → 部门简称（配置）→ 包含匹配，前一步对上就不往下。
- 加工厂：国内、海外按名称包含（国内另认地区说法，配置），巴西按名称整段相等；末尾带「工厂」时先整串对，
  对不上再去掉这两个字对。同名的几个工厂码合成一个名称。
- 人员：按姓名整串相同；同名的不止一人时由调用方追问是哪个部门的。
- 对不上、要请用户核对时的选项（`check_options`）：在可查的域里找与它整串相同的各类名称，最多 3 个，
  `label` 如「TT：巴西的加工厂」；不用包含、相近匹配，这一步只给选项，不替用户选。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from factory_issue_module.config.files import NameTable

_SEP = re.compile(r"[\s\-_]+")
MAX_CHECK_OPTIONS = 3


def key(text: object) -> str:
    """比较用：全角转半角、小写、去掉空格、连字符、下划线。"""
    return _SEP.sub("", unicodedata.normalize("NFKC", str(text or ""))).lower()


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    """去重并保持原顺序（同名的几个工厂码合成一个名称）。"""
    seen: set[str] = set()
    out = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return tuple(out)


# ---------------------------------------------------------------------------- 机型、系列


def machines(said: str, names: Iterable[str], *, each: bool = False) -> tuple[str, ...]:
    """按完整名称对机型；`each`（「X 各款」）时另取名称为「X + 字母」的机型，A800 之于 A80、IM30 之于 M30 都不算。"""
    want = key(said)
    if not want:
        return ()
    pattern = re.compile(re.escape(want) + r"[a-z]+") if each else None
    return _unique(n for n in names if key(n) == want or (pattern is not None and pattern.fullmatch(key(n))))


def _series_key(text: str) -> str:
    return re.sub(r"系列$", "", key(text))


def series(said: str, names: Iterable[str]) -> tuple[str, ...]:
    """按完整名称对系列，两边都不看末尾的「系列」。「其他」「其它」只在明说「其它系列」时才对兜底取值。"""
    raw = key(said)
    want = _series_key(said)
    if not want or (want in ("其他", "其它") and not raw.endswith("系列")):
        return ()
    if want == "其他":
        want = "其它"
    return _unique(n for n in names if _series_key(n) == want)


# ---------------------------------------------------------------------------- 部门


def departments(said: str, names: Iterable[str], aliases: NameTable | None = None) -> tuple[str, ...]:
    """完整名称 → 部门简称 → 包含匹配；对上多个时都返回（按全部合计、分部门给数）。"""
    pool = list(names)
    want = key(said)
    if not want:
        return ()
    exact = _unique(n for n in pool if key(n) == want)
    if exact:
        return exact
    if aliases is not None:
        formal = aliases.owner_of(said)
        if formal is not None:
            hit = _unique(n for n in pool if key(n) == key(formal))
            if hit:
                return hit
    return _unique(n for n in pool if want in key(n))


# ---------------------------------------------------------------------------- 加工厂


def _factory_tries(said: str) -> list[str]:
    want = key(said)
    tries = [want]
    if want.endswith("工厂") and len(want) > 2:
        tries.append(want[: -len("工厂")])
    return [t for t in tries if t]


def factories(said: str, names: Iterable[str], regions: NameTable | None = None) -> tuple[str, ...]:
    """国内、海外：名称包含用户的说法即命中（国内另认地区说法）；对上多个时由调用方请用户选。"""
    pool = list(names)
    if regions is not None:
        listed = regions.items_of(said) or regions.items_of(re.sub(r"(的)?(工厂|加工厂)$", "", said.strip()))
        if listed:
            return _unique(n for n in pool if key(n) in {key(x) for x in listed})
    for want in _factory_tries(said):
        exact = _unique(n for n in pool if key(n) == want)
        if exact:
            return exact
        hit = _unique(n for n in pool if want in key(n))
        if hit:
            return hit
    return ()


def brazil_factories(said: str, names: Iterable[str]) -> tuple[str, ...]:
    """巴西：名称整段相等（不分大小写）；说「TT 工厂」时去掉「工厂」再比。"""
    pool = list(names)
    for want in _factory_tries(said):
        hit = _unique(n for n in pool if key(n) == want)
        if hit:
            return hit
    return ()


# ---------------------------------------------------------------------------- 人员


def people(said: str, staff: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """按姓名整串相同：[(姓名, 所在部门)]；不止一人时由调用方追问「是哪个部门的这位」。"""
    want = key(said)
    return tuple((n, d) for n, d in staff if want and key(n) == want)


def person_options(matched: Sequence[tuple[str, str]]) -> list[str]:
    """重名时的选项，每个部门一个（总述「必要澄清项」示例「生产工程部的张三」）。"""
    return list(_unique(f"{dept}的{name}" for name, dept in matched))


# ---------------------------------------------------------------------------- 对不上时的选项


def check_options(said: str, index: Mapping[str, Sequence[str]], *, skip: str | None = None) -> list[str]:
    """在可查的域里找与它整串相同的各类名称：「TT：巴西的加工厂」，最多 3 个；`skip` 是已对不上的那一类。"""
    want = key(said)
    out: list[str] = []
    for name, kinds in index.items():
        if key(name) != want:
            continue
        for kind in kinds:
            if kind != skip:
                out.append(f"{name}：{kind}")
    return list(_unique(out))[:MAX_CHECK_OPTIONS]
