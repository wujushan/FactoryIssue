"""主数据（设计 §4.2 第 4–6 步、§6.2「主数据」、§6.5）。S2 只取国内的；巴西、海外随 S3。

每轮规划之前按可查的域取一次，给三处用：
- 规划器（`plan/planner.py::PlanInputs`）：`classes`（第 7 条名字归类：类 → 库里的名字，部门简称、国内工厂的地区
  说法也放进对应的类）、`entities`（第 15 条与对不上时的选项：名字 → 它在库里属于哪几类；类别列表里有「机型」
  的才参与机型校验）、`machines`（号码直通不把写了连字符的机型当 PN / PO）。
- 第 6 步名字对库（`plan/names.py`）：机型、系列、工厂、部门、供应商的取值清单，人员按姓名另取。
- 执行：部门、工厂、供应商整表都小，取一次当翻译表交给沙箱。

人员表 1.5 万行，不整表取：规划前只按问句里可能是人名的片段（2–4 个汉字的连续片段、英文词）取姓名完全相同的
人；计划里沿用上一轮、问句里没有的姓名到第 6 步再按姓名取。某张表取不到（无权或出错）时当它是空的，记日志。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import structlog

from factory_issue_module.config.files import NameTable
from factory_issue_module.declarations import (
    ERP,
    FACTORY_TABLE,
    INFO,
    Domain,
)
from factory_issue_module.domains import base

logger = structlog.get_logger(__name__)

MODELS = "CoreINFO.dbo.ZCTracking_ProductNames"
EMPLOYEE = "info.dbo.Employee"
DEPARTMENT = "info.dbo.Department"
VENDOR = "info.dbo.tbIQCvendor"

#: entities 里各类的叫法（「TT：巴西的加工厂」这类选项的后半句）；第 15 条只认「机型」这一项
KIND_MACHINE = "机型"
KIND_SERIES = "系列"
KIND_DEPT = "部门"
KIND_PERSON = "人员"
KIND_SUPPLIER = "供应商"
KIND_CN_FACTORY = "国内的加工厂"

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_WORD = re.compile(r"[A-Za-z][A-Za-z.\-']+")
_MAX_CANDIDATES = 900


@dataclass
class Person:
    id: int
    name: str
    dept: str


@dataclass
class MasterData:
    domains: frozenset[Domain] = frozenset()
    machines: list[str] = field(default_factory=list)
    series: list[str] = field(default_factory=list)
    #: 国内工厂：(工厂码, 名称)；同名的几个码都在
    factories: list[tuple[str, str]] = field(default_factory=list)
    departments: list[tuple[int, str]] = field(default_factory=list)
    #: 供应商：(编号, 名称)
    suppliers: list[tuple[str, str]] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    #: 机型 → 它的系列（「A920 系列」对不上时说明 A920 属于哪个系列）
    machine_series: dict[str, str] = field(default_factory=dict)
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    #: 没取到的主数据（models、departments、factories、suppliers、people）：取数出错或无权。对库要用它时那一段
    #: 答「这一部分暂时没查到」，不答成「没有找到这个名字」（设计 §14）
    failed: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ 给规划器

    def factory_names(self) -> list[str]:
        return base.unique(name for _code, name in self.factories)

    def dept_names(self) -> list[str]:
        return base.unique(name for _id, name in self.departments)

    def supplier_names(self) -> list[str]:
        return base.unique(name for _code, name in self.suppliers)

    def classes(self, dept_aliases: NameTable | None, regions: NameTable | None) -> dict[str, list[str]]:
        """第 7 条：类 → 库里的名字（可查的域）。类名同 `plan/normalize.py::NAME_GROUPS`。"""
        factories = self.factory_names()
        if regions is not None and factories:
            factories += [name for name, _items in regions.entries]
        depts = self.dept_names()
        if dept_aliases is not None and depts:
            depts += [item for _name, items in dept_aliases.entries for item in items]
        return {"工厂": factories, "人": base.unique(p.name for p in self.people), "部门": depts,
                "供应商": self.supplier_names(), "系列": list(self.series)}

    def entities(self, dept_aliases: NameTable | None, regions: NameTable | None) -> dict[str, list[str]]:
        """第 15 条与对不上时的选项：名字 → 在库里属于哪几类。"""
        out: dict[str, list[str]] = {}

        def put(names: Iterable[str], kind: str) -> None:
            for n in names:
                kinds = out.setdefault(n, [])
                if kind not in kinds:
                    kinds.append(kind)

        put(self.machines, KIND_MACHINE)
        put(self.series, KIND_SERIES)
        put(self.factory_names(), KIND_CN_FACTORY)
        if regions is not None and self.factories:
            put((name for name, _items in regions.entries), KIND_CN_FACTORY)
        put(self.dept_names(), KIND_DEPT)
        if dept_aliases is not None and self.departments:
            put((item for _name, items in dept_aliases.entries for item in items), KIND_DEPT)
        put(self.supplier_names(), KIND_SUPPLIER)
        put((p.name for p in self.people), KIND_PERSON)
        return out

    # ------------------------------------------------------------------ 第 6 步

    def factory_codes(self, names: Sequence[str]) -> list[str]:
        """名称 → 全部同名的工厂码（国内「加工厂」同名的工厂码）。"""
        want = set(names)
        return base.unique(code for code, name in self.factories if name in want)

    def dept_ids(self, names: Sequence[str]) -> list[int]:
        want = set(names)
        return base.unique(i for i, name in self.departments if name in want)

    def supplier_codes(self, names: Sequence[str]) -> list[str]:
        want = set(names)
        return base.unique(code for code, name in self.suppliers if name in want)

    def staff(self) -> list[tuple[str, str]]:
        return [(p.name, p.dept) for p in self.people]


def name_candidates(text: str) -> list[str]:
    """问句里可能是人名的片段：连续汉字里 2–4 个字的全部子串，加英文词与相邻两个词。"""
    out: dict[str, None] = {}
    for run in _CJK_RUN.findall(text or ""):
        for size in (2, 3, 4):
            for i in range(0, len(run) - size + 1):
                out.setdefault(run[i : i + size], None)
    words = _WORD.findall(text or "")
    for i, w in enumerate(words):
        out.setdefault(w, None)
        if i + 1 < len(words):
            out.setdefault(f"{w} {words[i + 1]}", None)
    return list(out)[:_MAX_CANDIDATES]


async def _safe(ctx: Any, label: str, spec: dict[str, Any], failed: set[str]) -> pd.DataFrame:
    try:
        return await base.fetch(ctx, spec)
    except Exception as exc:  # noqa: BLE001 —— 主数据取不到：记下来，规划照常走，对库用到它时那一段答查不到
        logger.warning("factory_issue_master_unavailable", table=label, error=type(exc).__name__)
        failed.add(label)
        return pd.DataFrame()


async def people_by_name(ctx: Any, names: Sequence[str], departments: Mapping[int, str],
                         failed: set[str] | None = None) -> list[Person]:
    """按姓名整串相同取人（人员表按员工 ID 匹配，姓名只用于对人，总述「三域共用的说法」只说人名一行）。"""
    keys = base.unique(n.strip() for n in names if n and n.strip())
    if not keys:
        return []
    spec = {"source": INFO, "from": EMPLOYEE, "select": ["ID", "Name", "Unit"]}
    try:
        frame = await base.fetch_in(ctx, spec, "Name", keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("factory_issue_master_unavailable", table="people", error=type(exc).__name__)
        if failed is not None:
            failed.add("people")
        return []
    out = []
    for rid, name, unit in zip(base.column(frame, "ID"), base.column(frame, "Name"), base.column(frame, "Unit"),
                               strict=False):
        ids = base.int_keys([rid])
        units = base.int_keys([unit])
        if ids and name:
            out.append(Person(ids[0], str(name).strip(), departments.get(units[0], "未填") if units else "未填"))
    return out


async def load(ctx: Any, domains: Iterable[Domain], query: str) -> MasterData:
    """按可查的域取一次主数据（S2：国内）。"""
    doms = frozenset(domains)
    master = MasterData(domains=doms)
    if Domain.DOMESTIC not in doms:
        return master
    bad = master.failed
    models, depts, factories, vendors = await asyncio.gather(
        _safe(ctx, "models", {"source": INFO, "from": MODELS, "select": ["ProductName", "Series"], "distinct": True},
              bad),
        _safe(ctx, "departments", {"source": INFO, "from": DEPARTMENT, "select": ["ID", "Name"]}, bad),
        _safe(ctx, "factories", {"source": ERP, "from": FACTORY_TABLE, "select": ["FactoryID", "FactoryName"]}, bad),
        _safe(ctx, "suppliers", {"source": INFO, "from": VENDOR, "select": ["ferpcode", "fname"]}, bad),
    )
    master.machines = base.unique(str(x).strip() for x in base.column(models, "ProductName") if x is not None)
    master.series = base.unique(str(x).strip() for x in base.column(models, "Series") if x is not None)
    for m, s in zip(base.column(models, "ProductName"), base.column(models, "Series"), strict=False):
        if m is not None and s is not None and str(s).strip():
            master.machine_series.setdefault(str(m).strip(), str(s).strip())
    master.factories = [(str(c).strip(), str(n).strip()) for c, n in
                        zip(base.column(factories, "FactoryID"), base.column(factories, "FactoryName"), strict=False)
                        if c is not None and n is not None]
    master.departments = [(i[0], str(n).strip()) for i, n in
                          ((base.int_keys([x]), y) for x, y in zip(base.column(depts, "ID"), base.column(depts, "Name"),
                                                                   strict=False))
                          if i and n is not None]
    master.suppliers = [(str(c).strip(), str(n).strip()) for c, n in
                        zip(base.column(vendors, "ferpcode"), base.column(vendors, "fname"), strict=False)
                        if c is not None and str(c).strip() and n is not None]
    master.frames = {"departments": depts, "factories": factories, "vendors": vendors}
    master.people = await people_by_name(ctx, name_candidates(query), dict(master.departments), master.failed)
    return master
