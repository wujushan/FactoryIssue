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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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
