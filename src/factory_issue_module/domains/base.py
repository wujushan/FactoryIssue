"""取数公共部分（设计 §6.1）。

- 一律 `ctx.data.fetch(QuerySpec)`；`fetch` 是同步调用，放进 `asyncio.to_thread` 并行。`to_thread` 复制当前上下文，
  平台的取数录制列表（`forge_data` 的 `record_queries`）在新线程里仍是同一个，`queries.json` 照常归档（单测锁住）。
- `IN` 每块不超过 1,000 个（SQL Server 单条语句最多 2,100 个参数，`fetch` 不替你分块）。
- 不给 `limit` 时超过 1 万行抛 `RowLimitExceeded`：这时改走 `fetch_all()`，显式 `limit=5000`、按主键排序，下一页取
  「主键大于上一页最后一行的主键」的行（SQL 已排好序，直接取最后一行），每步合计不超过 5 万行，超了抛 `TooManyRows`。
  不用 `offset` 翻页：连接是 READ UNCOMMITTED，翻页期间有写入时 `offset` 会重行或漏行。
- `handle()` 一侧只拼 spec、收集关联键（去重、按逗号拆段）、拼接分块取回的帧；比大小、计数、求和都在沙箱里做。
"""

from __future__ import annotations

import asyncio
import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from forge_core.dataquery import QuerySpec
from forge_core.errors import RowLimitExceeded

IN_CHUNK = 1000
PAGE = 5000
PAGE_CAP = 50_000


class TooManyRows(RuntimeError):
    """翻页合计超过 5 万行：按 §14 答「结果太多，请加上时间或其他条件再查」。"""


@dataclass
class Ask:
    """第 6 步要查库才知道的追问（名称对不上、对上多个、重名、枚举说法对不上）：本轮不取数。"""

    question: str
    options: list[str] = field(default_factory=list)
    reason: str = "名称核对"
    #: 这个名称或取值在本域对不上（「没有加工厂『柯洱斯』」）。几个域一起查、别的域对得上时不追问：本域不计入并写明
    #: （总述「跨域规则」各域按自己的取值查；「通用筛选规则」某域没有对应时该域不计入）。都对不上时照常追问
    missing: str | None = None


@dataclass
class DomainStep:
    """一步在某一域里对好库、换算好的条件（设计 §4.2 第 6 步）。"""

    domain: Any
    #: 主表上的条件（`fetch` 的 FilterCondition，列名带主表别名）
    sql: list[dict[str, Any]] = field(default_factory=list)
    #: 沙箱里按派生列筛的条件（`stats/lib/views.py` 的写法）
    conds: list[dict[str, Any]] = field(default_factory=list)
    #: 沙箱里筛的时间（日期依据不是建单、或比较两个时段时）
    times: list[dict[str, Any]] = field(default_factory=list)
    #: 比较两个时段：[{label, times}, {label, times}]，按时间先后
    compare: list[dict[str, Any]] | None = None
    #: 统计口径「筛选条件」的回显：(条件名, 用户原话与对上的取值)
    echo: list[tuple[str, str]] = field(default_factory=list)
    #: 开头要写的话（「按以下几个部门统计：…」）
    notes: list[str] = field(default_factory=list)
    #: 本域没有对应的列、因而不计入的条件（「国内无『其他』类型，未计入」）
    skipped: list[str] = field(default_factory=list)
    #: 要额外取的帧：steps、state、inventory、orders
    needs: set[str] = field(default_factory=set)
    #: 一个说法对上几个取值、按全部合计时，各取值的张数由沙箱另给（总述「部门名称怎么对」第 3 条）：
    #: [{"title": 列名, "col": 视图列, "multi": 是否多值, "values": [取值…]}]
    breakdowns: list[dict[str, Any]] = field(default_factory=list)
    #: 对库要用的取值清单没取到（主数据取数失败或无权）：这一域这一段答「这一部分暂时没查到」，不当成「没找到」
    unavailable: bool = False
    #: 本域没有对应的列、因而整域不计入的原因（总述「通用筛选规则」默认范围、「跨域归并」点名的类型某域没有）：
    #: 「国内没有统计日期，国内未计入」。有一条就不取数，统计口径「统计范围」写明
    excluded: list[str] = field(default_factory=list)


@dataclass
class Resolver:
    """第 6 步对库要用的东西（三域共用）。"""

    master: Any
    dept_aliases: Any
    regions: Any
    entities: Mapping[str, Sequence[str]]
    today: date
    #: 前一步给的引用值（已经是库里的名字），按「步骤.输出名」
    refs: Mapping[str, Any] = field(default_factory=dict)
    #: 本轮问句原话（巴西「是否涉及费用」要看用户是否明说，巴西业务描述「费用」）
    query: str = ""


def cond(field: str, operator: str, value: Any = None, *, include_nulls: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"field": field, "operator": operator}
    if value is not None:
        out["value"] = value
    if include_nulls:
        out["include_nulls"] = True
    return out


def chunks(values: Sequence[Any], size: int = IN_CHUNK) -> list[list[Any]]:
    return [list(values[i : i + size]) for i in range(0, len(values), size)]


def unique(values: Iterable[Any]) -> list[Any]:
    """去重、保持原顺序，空值不要（收集关联键）。"""
    seen: dict[Any, None] = {}
    for v in values:
        if v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip()):
            continue
        seen.setdefault(v.strip() if isinstance(v, str) else v, None)
    return list(seen)


def int_keys(values: Iterable[Any]) -> list[int]:
    """文本型的 ID、逗号多值拆成整数键（收集关联键，不产生给用户的数）。"""
    out: list[int] = []
    for v in values:
        if v is None or (isinstance(v, float) and v != v):
            continue
        for part in re.split(r"[,，]", str(v)):
            part = part.strip()
            if re.fullmatch(r"\d+(\.0+)?", part):
                out.append(int(float(part)))
    return unique(out)


def column(frame: pd.DataFrame | None, name: str) -> list[Any]:
    if frame is None or name not in frame.columns:
        return []
    return frame[name].tolist()


def _spec(spec: dict[str, Any]) -> QuerySpec:
    return QuerySpec.model_validate(spec)


async def fetch(ctx: Any, spec: dict[str, Any]) -> pd.DataFrame:
    return await asyncio.to_thread(ctx.data.fetch, _spec(spec))


def _with_condition(spec: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(spec)
    flt = out.get("filter") or {"logic": "AND", "groups": []}
    flt.setdefault("groups", []).append({"logic": "AND", "conditions": [extra]})
    flt["logic"] = "AND"
    out["filter"] = flt
    return out


async def fetch_all(ctx: Any, spec: dict[str, Any], key: str, *, cap: int = PAGE_CAP) -> pd.DataFrame:
    """先照常取；超过平台行数上限时按主键续取（见模块说明）。`key` 是主键列（多表时带别名）。"""
    try:
        return await fetch(ctx, spec)
    except RowLimitExceeded:
        pass
    pages: list[pd.DataFrame] = []
    taken = 0
    last: Any = None
    out_key = key.split(".")[-1]
    while True:
        page_spec = copy.deepcopy(spec)
        page_spec["order_by"] = [{"field": key, "direction": "ASC"}]
        page_spec["limit"] = PAGE
        if last is not None:
            page_spec = _with_condition(page_spec, cond(key, "GT", last))
        page = await fetch(ctx, page_spec)
        pages.append(page)
        taken += len(page)
        if taken > cap:
            raise TooManyRows(f"翻页合计超过 {cap} 行")
        if len(page) < PAGE:
            break
        last = page.iloc[-1][out_key]
    return pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()


async def fetch_in(ctx: Any, spec: dict[str, Any], field: str, values: Sequence[Any]) -> pd.DataFrame:
    """按键分块 `IN` 取，块与块并行，拼接回一个帧。没有键时不发 SQL。"""
    keys = unique(values)
    if not keys:
        return pd.DataFrame()
    parts = await asyncio.gather(*(fetch(ctx, _with_condition(spec, cond(field, "IN", part)))
                                   for part in chunks(keys)))
    return pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]


# ---------------------------------------------------------------------------- 第 6 步三域共用的对库小工具（§6.5）


def values_of(v: Any) -> list[str]:
    """条件的取值（照抄的用户说法）→ 去掉空的字符串列表。"""
    items = v if isinstance(v, list) else [v]
    return [str(x).strip() for x in items if x is not None and not isinstance(x, dict) and str(x).strip()]


def join(items: Iterable[Any]) -> str:
    return "、".join(str(x) for x in items)


def not_found(kind: str, said: str, entities: Mapping[str, Sequence[str]], skip: str | None) -> Ask:
    from factory_issue_module.plan import names

    return Ask(f"没有找到{kind}「{said}」，请核对名称。", names.check_options(said, entities, skip=skip),
               missing=f"没有{kind}「{said}」")


def yes_no(said: str) -> int | None:
    """「是 / 否」说法 → 1 / 0；认不出返回 None。"""
    from factory_issue_module.plan import names

    k = names.key(said)
    # 规划器对照集按同义计对的写法都认（`scripts/planner_spike/common.py::VALUE_SYNONYMS`，`tests/test_plan_values.py`）
    if k in ("是", "需要", "有", "要", "涉及", "true", "yes"):
        return 1
    if k in ("否", "不需要", "没有", "无", "不", "不涉及", "false", "no"):
        return 0
    return None


#: 追问按钮发回的问句末尾带着选定的那一项（`plan/clarify.py::with_choice`：「原话（是）」）
_CHOSEN = re.compile(r"（\s*(是|否)\s*）\s*$")


def yes_no_or_chosen(said: str, query: str) -> int | None:
    """「是 / 否」说法；认不出时看问句末尾是否带着「（是）」「（否）」。

    用户点了「选『是』还是『否』」的按钮，问句是原话加选定的一项。模型下一轮照旧把认不出的取值抄进计划，不按
    选定的这一项就会一直追问同一句（BR-004）。按钮直接填参数、不重新规划随 S5 的工作区（设计 §4.4）。
    """
    yn = yes_no(said)
    if yn is not None:
        return yn
    m = _CHOSEN.search(query or "")
    return None if m is None else (1 if m.group(1) == "是" else 0)


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
SQL_OPS = {"eq": "EQ", "ne": "NE", "gt": "GT", "lt": "LT", "ge": "GE", "le": "LE"}


def numbers(values: Sequence[str]) -> list[float]:
    """数值条件的取值（「100%」→ 100）：参数换算，不产生给用户的数。"""
    out: list[float] = []
    for v in values:
        out += [float(x) for x in _NUMBER.findall(v)]
    return out


def numeric_sql(column: str, kind: str, values: Sequence[str], out: DomainStep, field_name: str,
                op_said: str) -> bool:
    """数值条件进 SQL；换不成数值时写一句说明、不按它筛，返回 False。"""
    nums = numbers(values)
    if kind == "between" and len(nums) >= 2:
        out.sql.append(cond(column, "GE", nums[0]))
        out.sql.append(cond(column, "LE", nums[1]))
    elif nums and kind in SQL_OPS:
        out.sql.append(cond(column, SQL_OPS[kind], nums[0]))
    else:
        out.notes.append(f"「{field_name}{join(values)}」没能换成数值条件，未按它筛")
        return False
    out.echo.append((field_name, f"{op_said} {join(values)}"))
    return True


def numeric_cond(col: str, kind: str, values: Sequence[str], out: DomainStep, field_name: str, op_said: str) -> bool:
    """数值条件交沙箱（巴西现算的不良率、海外文本的不良率）。"""
    nums = numbers(values)
    if not nums or (kind == "between" and len(nums) < 2) or (kind not in SQL_OPS and kind != "between"):
        out.notes.append(f"「{field_name}{join(values)}」没能换成数值条件，未按它筛")
        return False
    out.conds.append({"kind": "num", "col": col, "op": kind, "values": nums[:2]})
    out.echo.append((field_name, f"{op_said} {join(values)}"))
    return True


def people(said: str, R: Resolver, person_kind: str) -> list[int] | Ask:
    """姓名 → 员工 ID。重名时追问「是哪个部门的这位」；「生产工程部的张三」按部门挑。"""
    from factory_issue_module.plan import names

    staff = R.master.people
    want = names.key(said)
    dept_hint = None
    if not any(names.key(p.name) == want for p in staff) and "的" in said:
        dept_hint, _, person = said.rpartition("的")
        want = names.key(person)
    hits = [p for p in staff if names.key(p.name) == want]
    if dept_hint is not None:
        hits = [p for p in hits if names.key(p.dept) == names.key(dept_hint)
                or names.departments(dept_hint, [p.dept], R.dept_aliases)]
    if not hits:
        return Ask(f"没有找到人员「{said}」，请核对姓名。", names.check_options(said, R.entities, skip=person_kind))
    depts = unique(p.dept for p in hits)
    if len(depts) > 1:
        options = names.person_options([(p.name, p.dept) for p in hits])
        return Ask(f"「{said}」有几位同名的，是哪个部门的这位？", options, reason="重名")
    return [p.id for p in hits]


def departments(values: Sequence[str], R: Resolver) -> list[str] | Ask:
    """部门说法 → 部门名称（完整名称 → 简称 → 包含，总述「部门名称怎么对」）；对不上时请用户核对。"""
    from factory_issue_module.plan import names

    hit: list[str] = []
    for v in values:
        got = list(names.departments(v, R.master.dept_names(), R.dept_aliases))
        if not got:
            return not_found("部门", v, R.entities, None)
        hit += [x for x in got if x not in hit]
    return hit


def suppliers(values: Sequence[str], R: Resolver) -> list[str] | Ask:
    """供应商：整名对上为准，对不上按名称包含找；包含对上几家时追问选哪一家，不静默扩大（S2 评审 A4）。"""
    from factory_issue_module.plan import names

    hit: list[str] = []
    pool = R.master.supplier_names()
    for v in values:
        got = [n for n in pool if names.key(n) == names.key(v)] or \
              [n for n in pool if names.key(v) and names.key(v) in names.key(n)]
        if not got:
            return not_found("供应商", v, R.entities, None)
        if len(got) > 1:
            return Ask(f"「{v}」对上了这几家供应商：{join(got[:12])}。查哪一家？", got[:4], reason="多供应商")
        hit += [x for x in got if x not in hit]
    return hit


def period_label(span: Any) -> str:
    """比较两个时段时每段的叫法：整年「2025 年全年」、整月「2026 年 9 月」，其余写起止日期。"""
    start, end = span.start, span.end
    if start and end and not span.to_today:
        if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31 and start.year == end.year:
            return f"{start.year} 年全年"
        nxt = date(end.year + (end.month == 12), end.month % 12 + 1, 1)
        if start.day == 1 and start.year == end.year and start.month == end.month and end + timedelta(days=1) == nxt:
            return f"{start.year} 年 {start.month} 月"
    return span.describe()


#: 某域没有这个日期依据时，说明里怎么叫它（总述「按哪个日期筛」）
BASIS_NAMES = {"现场发现": "现场发现日期", "停线": "停线日期", "重启": "停线重启时间", "结案": "结案时间",
               "统计日期": "统计日期"}


def time_conditions(step: dict, spans: Sequence[Any], out: DomainStep, *, label: str, add_col: str,
                    bases: Iterable[str], needs: Mapping[str, str] | None = None) -> None:
    """时间条件（§6.1）：建单时间进 SQL（`add_col`），其余依据与比较两个时段交沙箱。

    `bases` 是本域有的日期依据；没有的依据整域不计入（总述「按哪个日期筛」：某域没有这个日期时，该域不计入并
    写明）。`needs`：依据 → 要额外取的帧（国内按结案、重启筛要取处理步骤）。
    """
    from factory_issue_module.plan import schema

    p = step.get("params") or {}
    compare = p.get("compare") == "时段"
    have = set(bases)
    items = [t for t in schema.as_list(p.get("time")) if isinstance(t, dict) and t.get("said")]
    periods: list[tuple[Any, dict[str, Any]]] = []
    seen: set[tuple[str, Any]] = set()
    for t, span in zip(items, spans, strict=False):
        basis = str(t.get("basis") or "建单")
        if not compare:
            # 同一依据的几项已合成同一段（`timespan._intersect_same_basis`），条件只写一次
            if (basis, span) in seen:
                continue
            seen.add((basis, span))
        if basis not in have:
            text = f"{label}没有{BASIS_NAMES.get(basis, basis)}，{label}未计入"
            if text not in out.excluded:
                out.excluded.append(text)
            continue
        start, end = (None, None) if span.unlimited else (span.start, span.end)
        cond_t = {"basis": basis, "start": start.isoformat() if start else None,
                  "end": end.isoformat() if end else None}
        if needs and basis in needs:
            out.needs.add(needs[basis])
        if compare:
            periods.append((span, cond_t))
            continue
        if start is None and end is None:
            continue
        if basis == "建单":
            if span.relative() is not None:
                out.sql.append(cond(add_col, "GE", span.relative()))
            elif start is not None:
                out.sql.append(cond(add_col, "GE", datetime(start.year, start.month, start.day)))
            if end is not None and span.relative() is None:
                nxt = end + timedelta(days=1)
                out.sql.append(cond(add_col, "LT", datetime(nxt.year, nxt.month, nxt.day)))
        else:
            out.times.append(cond_t)
    if compare and len(periods) >= 2:
        ordered = sorted(periods[:2], key=lambda p: p[0].start or date.min)
        out.compare = [{"label": period_label(sp), "times": [c]} for sp, c in ordered]


def _type_keys(k: str) -> list[str]:
    """一个问题类型说法（已归一）依次试的写法：原样；「X 类」「X 类问题」去掉「类」；末尾补上「问题」。

    只在末尾补「问题」，不做包含匹配：「制程」补成「制程问题」也对不上任何类型，照旧追问（总述「三域共用的说法」：
    制程不是问题类型）。
    """
    out = [k]
    if k.endswith("类问题"):
        out.append(k[:-3] + "问题")
    if k.endswith("类"):
        out += [k[:-1], k[:-1] + "问题"]
    if not k.endswith("问题"):
        out.append(k + "问题")
    return out


def problem_types(values: Sequence[str], known: Sequence[str], label: str, neg: bool,
                  out: DomainStep) -> list[str] | Ask:
    """问题类型说法 → 本域的类型名（总述「跨域归并」「三域共用的说法」）。

    只在别的域有的类型：本域不计入这一项并写明（「巴西无『工厂制程』类型，未计入」）；点名的类型本域一个都没有时
    整域不计入。三域都没有的说法，列出本域的类型请用户选。类型名称可以省掉末尾的「问题」、带「类」
    （「软件、硬件、结构三类」即软件问题、硬件问题、结构问题），见 `_type_keys`。
    """
    from factory_issue_module import landed
    from factory_issue_module.plan import names

    keys = {names.key(t): t for t in known}
    elsewhere = {names.key(t): t for t in landed.problem_types()}
    hit: list[str] = []
    for v in values:
        tries = _type_keys(names.key(v))
        got = next((keys[k] for k in tries if k in keys), None)
        if got is not None:
            if got not in hit:
                hit.append(got)
            continue
        other = next((elsewhere[k] for k in tries if k in elsewhere), None)
        if other is not None:
            if not neg:
                out.skipped.append(f"{label}无「{other}」类型，未计入")
            continue
        return Ask(f"没有「{v}」这个问题类型，{label}的问题类型有：{join(known)}。", list(known)[:4],
                   reason="类型对不上")
    if not hit and not neg:
        out.excluded += [s for s in out.skipped if s.endswith("类型，未计入") and s not in out.excluded]
        out.skipped = [s for s in out.skipped if s not in out.excluded]
    return hit


# ---------------------------------------------------------------------------- 分组维度（三域共用的拼法）

PERIOD_DIMS = ("年", "季度", "月", "周")


def build_dims(group_by: Sequence[str], basis: str | None, table: Mapping[str, dict[str, Any]],
               period_cols: Mapping[str, str], needs_by: Mapping[str, str] | None = None,
               period_needs: Mapping[str, str] | None = None
               ) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """计划的分组维度 → 沙箱的维度说明；返回 (维度, 本域没有的维度, 要额外取的帧)。

    维度说明里 `merge` 为真的，三域一起统计时按名称同名合并成一张表（总述「跨域归并」）；`universe` 是本域可能有的
    取值（该域没有的取值在合并表里写「—」），`fill` 是没有单也要列出的取值（问题等级 A+、A、B、C）。
    时间维度按日期依据取列；本域没有这个日期依据时算本域没有的维度。
    """
    out: list[dict[str, Any]] = []
    missing: list[str] = []
    needs: set[str] = set()
    for g in group_by:
        if g in PERIOD_DIMS:
            col = period_cols.get(basis or "建单")
            if col is None:
                missing.append(g)
                continue
            out.append({"name": g, "period": g, "period_col": col, "title": g, "merge": True})
            if period_needs and (basis or "建单") in period_needs:
                needs.add(period_needs[basis or "建单"])
        elif g in table:
            out.append({"name": g, **table[g]})
            if needs_by and g in needs_by:
                needs.add(needs_by[g])
        else:
            missing.append(g)
    return out, missing, needs
