"""主数据（设计 §4.2 第 4–6 步、§6.2「主数据」、§6.5）。国内 S2；巴西、海外 S3。

每轮规划之前按可查的域取一次，给三处用：
- 规划器（`plan/planner.py::PlanInputs`）：`classes`（第 7 条名字归类：类 → 库里的名字，部门简称、国内工厂的地区
  说法也放进对应的类）、`entities`（第 15 条与对不上时的选项：名字 → 它在库里属于哪几类；类别列表里有「机型」
  的才参与机型校验）、`machines`（号码直通不把写了连字符的机型当 PN / PO）。
- 第 6 步名字对库（`plan/names.py`）：机型、系列、工厂、部门、供应商的取值清单，人员按姓名另取。
- 执行：部门、工厂、供应商、产品整表都小，取一次当翻译表交给沙箱。

各域取哪些（只取可查的域要用的）：
- 国内：国内机型子表的机型与系列（去重）、国内工厂（`erp`）、供应商。
- 巴西：产品主数据（大机型名称与系列，480 行）、巴西工厂（12 行）、供应商。
- 海外：产品主数据、海外主表上出现过的加工厂（海外工厂直接存名称、是闭集，没有单独的工厂表；未删除的单）、
  国内工厂（海外单上另记一列国内工厂）。
- 部门三域共用。

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
PRODUCT = "info.dbo.ProductName"
BR_FACTORY = "info.dbo.Brazil_Factory"
OS_MAIN = Domain.OVERSEAS.master_table

#: entities 里各类的叫法（「TT：巴西的加工厂」这类选项的后半句）；第 15 条只认「机型」这一项
KIND_MACHINE = "机型"
KIND_SERIES = "系列"
KIND_DEPT = "部门"
KIND_PERSON = "人员"
KIND_SUPPLIER = "供应商"
KIND_CN_FACTORY = "国内的加工厂"
KIND_BR_FACTORY = "巴西的加工厂"
KIND_OS_FACTORY = "海外的加工厂"

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
    #: 可查的域的机型名称合起来（规划器、号码直通用）；各域自己的在 `machines_of`
    machines: list[str] = field(default_factory=list)
    series: list[str] = field(default_factory=list)
    #: 各域的机型、系列取值：国内取机型子表，巴西、海外取产品主数据（大机型）；海外系列不作查询条件
    machines_of: dict[Domain, list[str]] = field(default_factory=dict)
    series_of: dict[Domain, list[str]] = field(default_factory=dict)
    #: 国内工厂：(工厂码, 名称)；同名的几个码都在
    factories: list[tuple[str, str]] = field(default_factory=list)
    #: 巴西工厂名称、海外单上出现过的加工厂名称
    br_factories: list[str] = field(default_factory=list)
    os_factories: list[str] = field(default_factory=list)
    departments: list[tuple[int, str]] = field(default_factory=list)
    #: 供应商：(编号, 名称)
    suppliers: list[tuple[str, str]] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    #: 当前用户（计划里人员条件写了「我」时按工号取，`execute.add_people`）；取过、没对上时为 None
    me: Person | None = None
    me_loaded: bool = False
    #: 机型 → 它的系列（「A920 系列」对不上时说明 A920 属于哪个系列）
    machine_series: dict[str, str] = field(default_factory=dict)
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    #: 没取到的主数据（models、products、factories、br_factories、os_factories、departments、suppliers、people）：
    #: 取数出错或无权。对库要用它时那一段答「这一部分暂时没查到」，不答成「没有找到这个名字」（设计 §14）
    failed: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ 给规划器

    def factory_names(self) -> list[str]:
        """国内工厂的名称（同名的码合成一个）。"""
        return base.unique(name for _code, name in self.factories)

    def dept_names(self) -> list[str]:
        return base.unique(name for _id, name in self.departments)

    def supplier_names(self) -> list[str]:
        return base.unique(name for _code, name in self.suppliers)

    def machines_in(self, domain: Domain) -> list[str]:
        return self.machines_of.get(domain, [])

    def series_in(self, domain: Domain) -> list[str]:
        return self.series_of.get(domain, [])

    def classes(self, dept_aliases: NameTable | None, regions: NameTable | None) -> dict[str, list[str]]:
        """第 7 条：类 → 库里的名字（可查的域）。类名同 `plan/normalize.py::NAME_GROUPS`。"""
        factories = self.factory_names()
        if regions is not None and factories:
            factories += [name for name, _items in regions.entries]
        factories += [*self.br_factories, *self.os_factories]
        depts = self.dept_names()
        if dept_aliases is not None and depts:
            depts += [item for _name, items in dept_aliases.entries for item in items]
        return {"工厂": base.unique(factories), "人": base.unique(p.name for p in self.people), "部门": depts,
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
        put(self.br_factories, KIND_BR_FACTORY)
        put(self.os_factories, KIND_OS_FACTORY)
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


async def current_user(ctx: Any, departments: Mapping[int, str], failed: set[str] | None = None) -> Person | None:
    """当前用户：平台给出的工号就是人员表的员工 ID，按 ID 取，不按姓名（总述「三域共用的说法」我跟进的一行）。

    工号为空、不是数字、人员表里没有这名员工时返回 None（由调用方请用户给出姓名）；取数出错时记进 `failed`，
    该段按「这一部分暂时没查到」答（设计 §14）。日志不记工号与姓名。"""
    ids = base.int_keys([getattr(getattr(ctx, "user", None), "user_id", None)])
    if not ids:
        logger.info("factory_issue_current_user", found=False, reason="no_employee_id")
        return None
    spec = {"source": INFO, "from": EMPLOYEE, "select": ["ID", "Name", "Unit"]}
    try:
        frame = await base.fetch_in(ctx, spec, "ID", ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("factory_issue_master_unavailable", table="people", error=type(exc).__name__)
        if failed is not None:
            failed.add("people")
        return None
    for rid, name, unit in zip(base.column(frame, "ID"), base.column(frame, "Name"), base.column(frame, "Unit"),
                               strict=False):
        units = base.int_keys([unit])
        if base.int_keys([rid]) == ids and name is not None and str(name).strip():
            logger.info("factory_issue_current_user", found=True)
            return Person(ids[0], str(name).strip(), departments.get(units[0], "未填") if units else "未填")
    logger.info("factory_issue_current_user", found=False, reason="not_in_employee")
    return None


def _texts(frame: pd.DataFrame | None, col: str) -> list[str]:
    return base.unique(str(x).strip() for x in base.column(frame, col) if x is not None)


def overseas_factory_spec() -> dict[str, Any]:
    """海外加工厂的取值清单：海外主表上出现过的加工厂（未删除的单，去重）。"""
    return {"source": INFO, "from": OS_MAIN, "select": ["Factory"], "distinct": True,
            "filter": {"logic": "AND", "groups": [{"logic": "AND", "conditions": [
                base.cond("IsDelete", "EQ", 0)]}]}}


async def load(ctx: Any, domains: Iterable[Domain], query: str) -> MasterData:
    """按可查的域取一次主数据。"""
    doms = frozenset(domains)
    master = MasterData(domains=doms)
    if not doms:
        return master
    bad = master.failed
    cn, br, os_ = Domain.DOMESTIC in doms, Domain.BRAZIL in doms, Domain.OVERSEAS in doms
    wanted: dict[str, dict[str, Any]] = {
        "departments": {"source": INFO, "from": DEPARTMENT, "select": ["ID", "Name"]},
    }
    if cn:
        wanted["models"] = {"source": INFO, "from": MODELS, "select": ["ProductName", "Series"], "distinct": True}
    if cn or os_:
        wanted["factories"] = {"source": ERP, "from": FACTORY_TABLE, "select": ["FactoryID", "FactoryName"]}
    if cn or br:
        wanted["suppliers"] = {"source": INFO, "from": VENDOR, "select": ["ferpcode", "fname"]}
    if br or os_:
        wanted["products"] = {"source": INFO, "from": PRODUCT, "select": ["ID", "ProductName", "Series"]}
    if br:
        wanted["br_factories"] = {"source": INFO, "from": BR_FACTORY, "select": ["FactoryName"]}
    if os_:
        wanted["os_factories"] = overseas_factory_spec()
    got = dict(zip(wanted, await asyncio.gather(*(_safe(ctx, k, s, bad) for k, s in wanted.items())), strict=True))
    models, products = got.get("models"), got.get("products")
    if cn:
        master.machines_of[Domain.DOMESTIC] = _texts(models, "ProductName")
        master.series_of[Domain.DOMESTIC] = _texts(models, "Series")
    if br or os_:
        names = _texts(products, "ProductName")
        for d in (Domain.BRAZIL, Domain.OVERSEAS):
            if d in doms:
                master.machines_of[d] = names
        if br:
            master.series_of[Domain.BRAZIL] = _texts(products, "Series")
    master.machines = base.unique(n for d in (Domain.DOMESTIC, Domain.BRAZIL, Domain.OVERSEAS)
                                  for n in master.machines_of.get(d, []))
    master.series = base.unique(n for d in (Domain.DOMESTIC, Domain.BRAZIL) for n in master.series_of.get(d, []))
    for frame in (models, products):
        for m, s in zip(base.column(frame, "ProductName"), base.column(frame, "Series"), strict=False):
            if m is not None and s is not None and str(s).strip():
                master.machine_series.setdefault(str(m).strip(), str(s).strip())
    factories, depts, vendors = got.get("factories"), got["departments"], got.get("suppliers")
    master.factories = [(str(c).strip(), str(n).strip()) for c, n in
                        zip(base.column(factories, "FactoryID"), base.column(factories, "FactoryName"), strict=False)
                        if c is not None and n is not None]
    master.br_factories = _texts(got.get("br_factories"), "FactoryName")
    master.os_factories = _texts(got.get("os_factories"), "Factory")
    master.departments = [(i[0], str(n).strip()) for i, n in
                          ((base.int_keys([x]), y) for x, y in zip(base.column(depts, "ID"), base.column(depts, "Name"),
                                                                   strict=False))
                          if i and n is not None]
    master.suppliers = [(str(c).strip(), str(n).strip()) for c, n in
                        zip(base.column(vendors, "ferpcode"), base.column(vendors, "fname"), strict=False)
                        if c is not None and str(c).strip() and n is not None]
    master.frames = {"departments": depts}
    for name, frame in (("factories", factories), ("vendors", vendors), ("products", products)):
        if frame is not None:
            master.frames[name] = frame
    master.people = await people_by_name(ctx, name_candidates(query), dict(master.departments), master.failed)
    return master
