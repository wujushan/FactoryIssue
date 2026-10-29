"""配置文件（设计 §11）：六份 `config_files` 的解析、校验、缓存与回退。

`link_sites.toml`（本环境 INFO 站点地址）随环境不同，没有内置默认值，没传时不生成链接；
传了就必须写出 `issue`，否则保存时拒绝。

- 上传的内容与内置默认值走同一套解析函数；`validate_config()` 就是「解析一遍，出错即拒绝保存」，
  报错文字原样显示在 Console 的上传框里，所以都写成管理员看得懂的话。
- 读不到（没上传过，`version` 为 0、`text()` 为 None）用内置默认值；读到却解析失败（平台升级前存下的
  旧版本等）同样回退，记 WARNING。
- 解析结果按 `(文件名, 版本号)` 缓存在进程内；同一轮里平台保证读到的是同一版。
- `validate_config` 在网关进程里同步执行、没有超时保护，这里只做解析与快速检查，不读库。
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog
from forge_core.errors import ConfigFileNotDeclared

from factory_issue_module import landed
from factory_issue_module.config import defaults
from factory_issue_module.declarations import (
    ANSWER_PARAMS,
    DEPT_ALIASES,
    FACTORY_REGIONS,
    LINK_SITES,
    SEGMENTATION,
    TOPIC_TERMS,
)
from factory_issue_module.textnorm import compact, has_cjk

logger = structlog.get_logger(__name__)

_MARK = "＊"


class ConfigFormatError(ValueError):
    """配置内容不合格。消息直接给管理员看。"""


# ---------------------------------------------------------------- 解析结果


@dataclass(frozen=True)
class TopicTerm:
    text: str
    ambiguous: bool


@dataclass(frozen=True)
class Topic:
    name: str
    description: str
    terms: tuple[TopicTerm, ...]
    excluded: tuple[str, ...]


@dataclass(frozen=True)
class TopicTerms:
    topics: tuple[Topic, ...]

    def get(self, name: str) -> Topic | None:
        return next((t for t in self.topics if t.name == name), None)


@dataclass(frozen=True)
class Segmentation:
    rule: str
    split_over: int
    seg_min: int
    seg_max: int
    overlap: str
    groups: Mapping[str, tuple[str, ...]]
    domestic_codes: tuple[int, ...]
    overseas_names: tuple[str, ...]

    def group_of(self, field_code: str) -> str:
        """字段代号归「涉及某个话题」的哪一组（first / second）。"""
        for group, fields in self.groups.items():
            if field_code in fields:
                return group
        raise KeyError(field_code)


@dataclass(frozen=True)
class NameTable:
    """两列表：名称 → 若干说法 / 工厂（部门简称、地区说法共用）。"""

    entries: tuple[tuple[str, tuple[str, ...]], ...]
    _index: dict[str, str] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        for name, items in self.entries:
            for item in items:
                self._index.setdefault(compact(item), name)

    def owner_of(self, item: str) -> str | None:
        """说法（如「工程部」）对到的名称（如「生产工程部」）；对不上返回 None。"""
        return self._index.get(compact(item))

    def items_of(self, name: str) -> tuple[str, ...] | None:
        key = compact(name)
        return next((items for n, items in self.entries if compact(n) == key), None)


@dataclass(frozen=True)
class LinkSites:
    """本环境 INFO 站点的地址（`link_rules.md`）：`https://主机名[:端口]` 形式，没配为 None（不生成链接）。"""

    issue: str | None = None
    brazil: str | None = None
    attachment: str | None = None


@dataclass(frozen=True)
class AnswerParams:
    top_n: int
    export_threshold: int
    table_rows: int
    judge_max: int
    rerank_max: int
    rerank_score_threshold: float | None
    custom_stats_enabled: bool


# ---------------------------------------------------------------- Markdown 两种形态

_TOPIC_HEADER = ("话题", "一句话说明", "算的说法（＊ = 有歧义）", "不算的说法")
_DEPT_HEADER = ("正式部门名称", "简称、日常说法")
_REGION_HEADER = ("地区说法", "对到的工厂")


def _table(text: str, header: tuple[str, ...], *, scope: str = "") -> landed.MdTable:
    """取表头逐字等于 `header` 的第一张表（`scope` 给出时只在该节标题下找）。"""
    try:
        body = landed.section(text, scope, where="文件里") if scope else text
        return landed.table_with_header(body, header, where="文件里")
    except landed.LandedParseError as exc:
        raise ConfigFormatError(str(exc)) from exc


def _split(cell: str) -> list[str]:
    return landed.split_items(cell)


def parse_topic_terms(text: str) -> TopicTerms:
    table = _table(text, _TOPIC_HEADER, scope="## 清单")
    topics: list[Topic] = []
    seen_topics: set[str] = set()
    for n, (name, desc, terms_cell, excluded_cell) in enumerate(table.rows, start=1):
        where = f"第 {n} 行（话题「{name}」）" if name else f"第 {n} 行"
        if not name:
            raise ConfigFormatError(f"{where}缺话题名称")
        if compact(name) in seen_topics:
            raise ConfigFormatError(f"话题「{name}」出现了不止一次")
        seen_topics.add(compact(name))
        if not desc:
            raise ConfigFormatError(f"{where}缺一句话说明")
        terms: list[TopicTerm] = []
        for raw in _split(terms_cell):
            if "*" in raw:
                raise ConfigFormatError(f"{where}说法「{raw}」里的 * 要写成全角「＊」")
            ambiguous = raw.startswith(_MARK)
            if raw.count(_MARK) > (1 if ambiguous else 0):
                raise ConfigFormatError(f"{where}说法「{raw}」：＊ 只能写在说法开头，且只写一个")
            body = raw[1:].strip() if ambiguous else raw
            if not body:
                raise ConfigFormatError(f"{where}「＊」后面缺说法")
            terms.append(TopicTerm(text=body, ambiguous=ambiguous))
        excluded = _split(excluded_cell)
        for raw in excluded:
            if _MARK in raw or "*" in raw:
                raise ConfigFormatError(f"{where}不算的说法「{raw}」不能带 ＊")
        if not terms:
            raise ConfigFormatError(f"{where}至少要有一个算的说法")
        for word in [t.text for t in terms] + excluded:
            if has_cjk(word) and len(compact(word)) < 2:
                raise ConfigFormatError(f"{where}中文说法「{word}」不足 2 个字")
        _no_duplicates(where, "算的说法", [t.text for t in terms])
        _no_duplicates(where, "不算的说法", excluded)
        both = {compact(t.text) for t in terms} & {compact(w) for w in excluded}
        if both:
            word = next(w for w in excluded if compact(w) in both)
            raise ConfigFormatError(f"{where}「{word}」同时写在了算的说法和不算的说法里")
        topics.append(
            Topic(name=name, description=desc, terms=tuple(terms), excluded=tuple(excluded))
        )
    if not topics:
        raise ConfigFormatError("清单里没有话题")
    return TopicTerms(topics=tuple(topics))


def _no_duplicates(where: str, kind: str, words: list[str]) -> None:
    seen: set[str] = set()
    for word in words:
        key = compact(word)
        if key in seen:
            raise ConfigFormatError(f"{where}{kind}「{word}」重复")
        seen.add(key)


def parse_dept_aliases(text: str) -> NameTable:
    table = _table(text, _DEPT_HEADER)
    owner: dict[str, str] = {}
    entries: list[tuple[str, tuple[str, ...]]] = []
    for n, (dept, cell) in enumerate(table.rows, start=1):
        if not dept:
            raise ConfigFormatError(f"第 {n} 行缺正式部门名称")
        aliases = _split(cell)
        for alias in aliases:
            prev = owner.get(compact(alias))
            if prev is not None and compact(prev) != compact(dept):
                raise ConfigFormatError(f"简称「{alias}」同时对到了「{prev}」和「{dept}」")
            owner[compact(alias)] = dept
        entries.append((dept, tuple(aliases)))
    return NameTable(entries=tuple(entries))


def parse_factory_regions(text: str) -> NameTable:
    table = _table(text, _REGION_HEADER)
    seen: set[str] = set()
    entries: list[tuple[str, tuple[str, ...]]] = []
    for n, (region, cell) in enumerate(table.rows, start=1):
        if not region:
            raise ConfigFormatError(f"第 {n} 行缺地区说法")
        if compact(region) in seen:
            raise ConfigFormatError(f"地区说法「{region}」出现了不止一次")
        seen.add(compact(region))
        if any(sep in cell for sep in ("，", ",", "/", "；", ";")):
            raise ConfigFormatError(f"地区「{region}」的工厂之间请用「、」分隔")
        factories = _split(cell)
        if not factories:
            raise ConfigFormatError(f"地区「{region}」没有写对到的工厂")
        entries.append((region, tuple(factories)))
    return NameTable(entries=tuple(entries))


# ---------------------------------------------------------------- TOML 两份

_RULES = ("whole", "field", "field_split")
_OVERLAPS = ("sentence", "none")
FIELD_CODES = ("phen", "desc", "reason", "improve", "measure", "prev", "sqe", "step")


def _toml(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigFormatError(f"TOML 写法不对：{exc}") from exc


def _only_keys(where: str, data: Mapping[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = [k for k in data if k not in allowed]
    if unknown:
        raise ConfigFormatError(
            f"{where}有不认识的项：{'、'.join(unknown)}（可写的项：{'、'.join(allowed)}）"
        )


def _positive_int(name: str, value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise ConfigFormatError(f"{name} 要写正整数，现在是 {value!r}")
    return value


def parse_segmentation(text: str) -> Segmentation:
    return segmentation_from(_toml(text))


def segmentation_from(data: Mapping[str, Any]) -> Segmentation:
    _only_keys("", data, ("rule", "split_over", "seg_min", "seg_max", "overlap", "groups", "steps"))
    base = defaults.SEGMENTATION
    merged = {**base, **data}
    rule = merged["rule"]
    if rule not in _RULES:
        raise ConfigFormatError(f"rule 只能是 {' / '.join(_RULES)}，现在是 {rule!r}")
    split_over = _positive_int("split_over", merged["split_over"])
    seg_min = _positive_int("seg_min", merged["seg_min"])
    seg_max = _positive_int("seg_max", merged["seg_max"])
    if seg_min > seg_max:
        raise ConfigFormatError(f"seg_min（{seg_min}）不能大于 seg_max（{seg_max}）")
    overlap = merged["overlap"]
    if overlap not in _OVERLAPS:
        raise ConfigFormatError(f"overlap 只能是 {' / '.join(_OVERLAPS)}，现在是 {overlap!r}")

    groups_in = data.get("groups", {})
    if not isinstance(groups_in, Mapping):
        raise ConfigFormatError("[groups] 要写成表，如 first = [\"phen\", \"desc\"]")
    _only_keys("[groups] ", groups_in, ("first", "second"))
    groups = {**base["groups"], **groups_in}
    owner: dict[str, str] = {}
    for group, fields in groups.items():
        if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
            raise ConfigFormatError(f"[groups] {group} 要写成字段代号的列表")
        for f in fields:
            if f not in FIELD_CODES:
                raise ConfigFormatError(f"[groups] {group} 里的「{f}」不是字段代号（可用：{'、'.join(FIELD_CODES)}）")
            if f in owner:
                raise ConfigFormatError(f"字段代号「{f}」同时归在 {owner[f]} 和 {group} 两组")
            owner[f] = group
    missing = [f for f in FIELD_CODES if f not in owner]
    if missing:
        raise ConfigFormatError(f"[groups] 没有覆盖这些字段代号：{'、'.join(missing)}")

    steps_in = data.get("steps", {})
    if not isinstance(steps_in, Mapping):
        raise ConfigFormatError("[steps] 要写成表")
    _only_keys("[steps] ", steps_in, ("domestic_codes", "overseas_names"))
    steps = {**base["steps"], **steps_in}
    codes = steps["domestic_codes"]
    if not isinstance(codes, list) or not all(type(c) is int for c in codes):
        raise ConfigFormatError("[steps] domestic_codes 要写成整数列表，如 [3, 4, 6]")
    names = steps["overseas_names"]
    if not isinstance(names, list) or not all(isinstance(s, str) and s.strip() for s in names):
        raise ConfigFormatError("[steps] overseas_names 要写成环节名称的列表")
    return Segmentation(
        rule=rule,
        split_over=split_over,
        seg_min=seg_min,
        seg_max=seg_max,
        overlap=overlap,
        groups={g: tuple(fs) for g, fs in groups.items()},
        domestic_codes=tuple(codes),
        overseas_names=tuple(s.strip() for s in names),
    )


_ANSWER_KEYS = (
    "top_n", "export_threshold", "table_rows", "judge_max", "rerank_max",
    "rerank_score_threshold", "custom_stats_enabled",
)


def parse_answer_params(text: str) -> AnswerParams:
    return answer_params_from(_toml(text))


def answer_params_from(data: Mapping[str, Any]) -> AnswerParams:
    _only_keys("", data, _ANSWER_KEYS)
    merged = {**defaults.ANSWER_PARAMS, **data}
    ints = {
        k: _positive_int(k, merged[k])
        for k in ("top_n", "export_threshold", "table_rows", "judge_max", "rerank_max")
    }
    threshold = merged.get("rerank_score_threshold")
    if threshold is not None:
        if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
            raise ConfigFormatError(f"rerank_score_threshold 要写 0 到 1 之间的数，现在是 {threshold!r}")
        threshold = float(threshold)
    enabled = merged["custom_stats_enabled"]
    if type(enabled) is not bool:
        raise ConfigFormatError(f"custom_stats_enabled 要写 true 或 false，现在是 {enabled!r}")
    return AnswerParams(**ints, rerank_score_threshold=threshold, custom_stats_enabled=enabled)


#: issue 必须先列：brazil、attachment 不写时与它相同
_SITE_KEYS = ("issue", "brazil", "attachment")
_SITE = re.compile(r"^(?:(?P<scheme>https?)://)?(?P<host>[A-Za-z0-9](?:[A-Za-z0-9.\-]*[A-Za-z0-9])?)(?::(?P<port>\d{1,5}))?$")


def _site(key: str, value: Any) -> str:
    """站点地址 → `scheme://主机名[:端口]`；没写协议按 https（`link_rules.md`）。"""
    if not isinstance(value, str) or not value.strip():
        raise ConfigFormatError(f"{key} 要写站点地址的字符串，如 {key} = \"info.example.com\"，现在是 {value!r}")
    text = value.strip()
    if text.endswith("/"):
        raise ConfigFormatError(f"{key} 末尾不要带 /：{text}")
    m = _SITE.match(text)
    if m is None:
        raise ConfigFormatError(
            f"{key} 只写主机名（可带端口），不写路径与参数，如 info.example.com 或 10.1.2.3:8080；现在是 {text}"
        )
    port = m.group("port")
    if port is not None and not 0 < int(port) <= 65535:
        raise ConfigFormatError(f"{key} 的端口 {port} 不在 1–65535 之间")
    return f"{m.group('scheme') or 'https'}://{m.group('host')}" + (f":{port}" if port else "")


def parse_link_sites(text: str) -> LinkSites:
    return link_sites_from(_toml(text))


def link_sites_from(data: Mapping[str, Any]) -> LinkSites:
    """上传的内容必须写出 `issue`：空文件、只有注释、只写了另两项都拒绝保存。

    平台的 `required=True` 只看文件传没传过；传了一份没有 `issue` 的文件，启动告警就停了，
    国内问题编号却仍然不带链接，管理员看不出没配上。没传时的「不生成链接」走槽位默认值，不经过这里。
    """
    _only_keys("", data, _SITE_KEYS)
    if "issue" not in data:
        raise ConfigFormatError(
            "缺 issue：要写本环境 INFO 站点的地址，如 issue = \"info.example.com\"；"
            "brazil、attachment 不写时与 issue 相同"
        )
    sites = {k: _site(k, data[k]) for k in _SITE_KEYS if k in data}
    issue = sites["issue"]
    return LinkSites(issue=issue, brazil=sites.get("brazil", issue), attachment=sites.get("attachment", issue))


# ---------------------------------------------------------------- 槽位、默认值、读取


@dataclass(frozen=True)
class _Slot:
    parse: Callable[[str], Any]
    default: Any


SLOTS: dict[str, _Slot] = {
    TOPIC_TERMS: _Slot(parse_topic_terms, parse_topic_terms(defaults.topic_terms_text())),
    SEGMENTATION: _Slot(parse_segmentation, segmentation_from({})),
    DEPT_ALIASES: _Slot(parse_dept_aliases, parse_dept_aliases(defaults.dept_aliases_text())),
    FACTORY_REGIONS: _Slot(
        parse_factory_regions, parse_factory_regions(defaults.factory_regions_text())
    ),
    ANSWER_PARAMS: _Slot(parse_answer_params, answer_params_from({})),
    #: 站点地址随环境不同，没有内置默认值：没传时不生成链接（上传的内容必须写出 issue，见 link_sites_from）
    LINK_SITES: _Slot(parse_link_sites, LinkSites()),
}

_cache: dict[tuple[str, int], Any] = {}


def default(name: str) -> Any:
    return SLOTS[name].default


def validate(name: str, text: str) -> None:
    """`ForgeModule.validate_config` 的实现：不认识的文件名直接放行（将来加新槽位时老实现不拦）。"""
    slot = SLOTS.get(name)
    if slot is None:
        return
    slot.parse(text)


async def load(ctx: Any, name: str) -> Any:
    """读一份配置的解析结果；读不到或解析失败都回退到内置默认值。"""
    slot = SLOTS[name]
    port = getattr(ctx, "config", None)
    if port is None:
        return slot.default
    try:
        version = await port.version(name)
    except ConfigFileNotDeclared:
        raise
    except Exception as exc:  # noqa: BLE001 —— 配置存储出错时照常用默认值答
        logger.warning("factory_issue_config_unreadable", file=name, error=type(exc).__name__)
        return slot.default
    if not version:
        return slot.default
    key = (name, version)
    if key in _cache:
        return _cache[key]
    text = await port.text(name)
    if text is None:
        return slot.default
    try:
        value = slot.parse(text)
    except Exception as exc:  # noqa: BLE001 —— 平台升级前存下的旧版本等，回退并留痕
        logger.warning(
            "factory_issue_config_fallback", file=name, version=version, error=str(exc)[:200]
        )
        value = slot.default
    _cache[key] = value
    return value
