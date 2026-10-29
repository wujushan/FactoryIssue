"""巴西适配器（设计 §6.2、§6.3、§6.5；巴西业务描述「查询范围」「口径」「关联」）。

- 第 6 步：落在主表列上、写成比较就够的进 SQL：未删除（状态不是「已删除」）、建单时间、料号、供应商（编号）、
  问题类型以外的数量、发现工位（包含）、是否需要回复 8D、用户明说的是否涉及费用。其余在沙箱里按派生列筛：
  问题类型（「其他|备注」也算「其他」）、问题等级、状态、加工厂（逗号多值逐段比）、机型与系列（大机型逐段）、
  问题跟进人与跟进部门（最新一条处理过程）、不良率（现算）、PN（关联申请单）、物料名称、建单以外的日期
  （文本日期先解析）、涉及费用（费用明细合计大于 0）。
- 巴西没有的：当前责任人（「巴西不提供当前责任人，未计入」）、停线重启时间、产品在制属性、IQC 意见、原因分类、
  处理结果、海外单上的国内工厂。按它们筛时巴西整域不计入；责任归属部门按问题跟进部门、只说「责任人」按问题
  跟进人解释，并写明。
- 取数：主表与处理过程每次都取（处理过程 204 行，跟进人、跟进部门、结案日期、扣款都靠它）；费用明细、关联申请单
  按需取，申请单、PN 主数据、存货、人员按收集到的键取。不取叙述原文（§6.1）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pandas as pd

from factory_issue_module.declarations import INFO, Domain
from factory_issue_module.domains import base, domestic, enums
from factory_issue_module.domains.base import Ask, DomainStep, cond
from factory_issue_module.domains.shared import KIND_MACHINE, KIND_PERSON, MasterData
from factory_issue_module.plan import names, schema
from factory_issue_module.plan.timespan import Span
from factory_issue_module.present import columns

DOMAIN = Domain.BRAZIL
LABEL = DOMAIN.label
MAIN = DOMAIN.master_table
PROCESS = "CoreINFO.dbo.BrazilProblemProcess"
COST = "CoreINFO.dbo.BrazilProblemCost"
PO = "CoreINFO.dbo.BrazilProblemPO"
REQUESTS = "info.dbo.Brazil_RequestList"
PNS = "info.dbo.NewProduct"
EMPLOYEE = "info.dbo.Employee"
INVENTORY = "info.dbo.Inventory"

#: 主表要取的列：标识、枚举、数量、日期、人员 ID（不取问题描述、补料备注、备注这些叙述，§6.1）
MAIN_COLUMNS = (
    "ID", "OrderNumber", "ClaimNumber", "BrazilFactory", "ProductIDAll", "ProblemType", "IsStopLine", "StopDate",
    "StopStatus", "ProblemLevel", "ProblemDiscoveryDate", "ProblemDiscoveryStation", "StatisticsDate", "cInvCode",
    "cVenCode", "ImpactQty", "BadQty", "IsRequire8D", "IsSupplement", "IsCost", "ActorUserID", "AddUserID", "AddDate",
    "Status",
)
PROCESS_COLUMNS = ("ID", "ProblemID", "ProcessUserID", "FinishDate", "DebitMoney", "IsDesignChange", "PlanCompleteDate")
#: 已删除只靠状态 -1 表达；待提交（草稿）与已终止仍在范围内
NOT_DELETED = cond("m.Status", "NE", enums.BR_DELETED)

BASES = ("建单", "现场发现", "停线", "结案", "统计日期")
TRAITS: dict[str, Any] = {"metrics": ["单数", "占比", "未结案数", "合计不良率", "结案周期", "费用美元", "费用雷亚尔", "扣款"],
                          "rate": "sum", "rate_den": "影响数量", "small_sample": True, "close": "结案日期"}
#: 清单列：巴西只说「责任人」给问题跟进人；没有责任归属部门，按问题跟进部门；当前状态即主表状态（术语表「当前状态」）
KEY_ALIAS: dict[str, list[str] | None] = {"responsible": ["follower"], "resp_dept": ["follow_dept"],
                                          "current_state": ["status"], "state_for_filter": ["status"]}

COLUMN_NEEDS = {"inv_name": "inventory", "inv_std": "inventory", "pn": "pn", "cost_usd": "cost", "cost_brl": "cost"}
#: 靠主数据才写得出来的列（同 `domestic.MASTER_USES`）：大机型、系列按产品主数据对 ID，产品没取到时不写成「未识别机型」
MASTER_USES = {"machine": "products", "series": "products", "_machines": "products", "_series": "products",
               "follow_dept": "departments", "_follow_dept_group": "departments", "ven_name": "suppliers"}
METRIC_NEEDS = {"费用美元": "cost", "费用雷亚尔": "cost"}
SORT_NEEDS: dict[str, str] = {}


def enum_params() -> dict[str, Any]:
    return {"status": enums.BR_STATUS, "done": enums.BR_DONE, "draft": enums.BR_DRAFT,
            "terminated": enums.BR_TERMINATED, "unclosed": list(enums.BR_UNCLOSED), "yes_no": enums.BR_YES_NO,
            "stop_yes": enums.BR_STOP_YES, "restarted": enums.BR_RESTARTED}


# ---------------------------------------------------------------------------- 分组维度

_PERIOD_COL = {"建单": "_add", "现场发现": "_found", "停线": "_stop", "结案": "_close", "统计日期": "_stat"}


def dims(group_by: Sequence[str], basis: str | None) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    def s(key: str) -> str:
        return columns.shown(key, DOMAIN)

    closed = [*domestic.CLOSED_UNIVERSE, enums.BR_STATUS[enums.BR_DRAFT], enums.BR_STATUS[enums.BR_TERMINATED]]
    table: dict[str, dict[str, Any]] = {
        "域": {"const": LABEL, "title": columns.DOMAIN, "merge": True},
        "问题类型": {"col": "type", "keep_blank": True, "title": s("type"), "merge": True,
                     "universe": [*enums.BR_PROBLEM_TYPES, "未填"]},
        "机型": {"col": "_machines", "multi": True, "empty": "未填", "title": s("machine"), "merge": True},
        "系列": {"col": "_series", "multi": True, "empty": "未填", "title": s("series"), "merge": True},
        "加工厂": {"col": "_factories", "multi": True, "title": s("factory"), "merge": True},
        "结案与否": {"col": "_closed_label", "title": columns.CLOSED_OR_NOT, "merge": True, "universe": closed,
                     "fill": domestic.CLOSED_UNIVERSE},
        "处理环节": {"col": "_stages", "multi": True, "title": columns.STAGE},
        "问题等级": {"col": "level", "keep_blank": True, "order": domestic.LEVEL_UNIVERSE, "title": s("level"),
                     "merge": True, "universe": domestic.LEVEL_UNIVERSE, "fill": domestic.LEVEL_FILL},
        "跟进部门": {"col": "_follow_dept_group", "title": s("follow_dept"), "merge": True},
        "跟进人": {"col": "_follower_group", "title": s("follower"), "merge": True},
        "责任人": {"col": "_follower_group", "title": s("follower")},
        "责任归属部门": {"col": "_follow_dept_group", "title": s("follow_dept")},
        "停线状态": {"col": "_stop_label", "title": s("stop_status")},
        "状态": {"col": "status", "title": s("status")},
    }
    return base.build_dims(group_by, basis, table, _PERIOD_COL)


# ---------------------------------------------------------------------------- 第 6 步：条件对库

_MASTER_OF = {"机型": "products", "系列": "products", "加工厂": "br_factories", "供应商": "suppliers",
              "跟进部门": "departments", "责任归属部门": "departments", "跟进人": "people", "责任人": "people"}
#: 巴西没有对应列的条件：按它筛时巴西整域不计入（巴西业务描述「人员与部门」「不做」）
_ABSENT = {
    "当前责任人": "巴西不提供当前责任人，巴西未计入",
    "国内工厂": "「国内工厂」只是海外单上的一列，巴西未计入",
    "产品在制属性": "巴西没有「产品在制属性」，巴西未计入",
    "IQC意见": "巴西没有「IQC 意见」，巴西未计入",
    "原因分类": "巴西没有「原因分类」，巴西未计入",
    "处理结果": "巴西没有「处理结果」，巴西未计入",
}
_COST_WORDS = ("费用", "涉案金额")
_NEGATIONS = ("不", "没", "无", "未")


def resolve(step: dict, spans: Sequence[Span], R: base.Resolver) -> DomainStep | Ask:
    """一步在巴西的条件（第 6 步）。"""
    out = DomainStep(domain=DOMAIN)
    p = step.get("params") or {}
    base.time_conditions(step, spans, out, label=LABEL, add_col="m.AddDate", bases=BASES)
    m = R.master
    for f in schema.as_list(p.get("filters")):
        if not isinstance(f, dict):
            continue
        fld = str(f.get("field") or "")
        kind = schema.OP_KINDS.get(str(f.get("op") or "是"), "eq")
        neg = kind in ("ne", "nhas")
        raw = f.get("value")
        values = base.values_of(R.refs.get(raw["ref"], []) if schema.is_ref(raw) else raw)
        if not values:
            continue
        if _MASTER_OF.get(fld) in m.failed:
            out.unavailable = True
            continue
        if fld in _ABSENT:
            out.excluded.append(_ABSENT[fld])
            continue
        shown = base.join(values)
        if fld == "机型":
            hit: list[str] = []
            for v in values:
                got = names.machines(v, m.machines_in(DOMAIN), each=kind == "has")
                if not got:
                    return base.not_found("机型", v, R.entities, KIND_MACHINE)
                hit += [x for x in got if x not in hit]
            if kind == "has":
                out.notes.append(f"巴西按以下机型统计：{base.join(hit)}")
            out.conds.append({"kind": "any_of", "col": "_machines", "values": hit, "neg": neg})
            out.echo.append(("机型", base.join(hit)))
        elif fld == "系列":
            got_series = domestic.series_of(values, m, DOMAIN)
            if isinstance(got_series, Ask):
                return got_series
            out.conds.append({"kind": "any_of", "col": "_series", "values": got_series, "neg": neg})
            out.echo.append(("系列", base.join(got_series)))
        elif fld == "加工厂":
            hit = []
            for v in values:
                got = list(names.brazil_factories(v, m.br_factories))
                if not got:
                    return base.not_found("加工厂", v, R.entities, None)
                hit += [x for x in got if x not in hit]
            # 逗号多值：任一段等于该工厂即命中（「CA」命中「CA」与「CA,TT」）
            out.conds.append({"kind": "any_of", "col": "_factories", "values": hit, "neg": neg})
            out.echo.append(("加工厂", base.join(hit)))
        elif fld == "物料名称":
            out.conds.append({"kind": "contains", "col": "_inv_name", "values": values, "neg": neg})
            out.needs.add("inventory")
            out.echo.append(("物料名称包含", shown))
        elif fld == "料号":
            out.sql.append(cond("m.cInvCode", "NOT_IN" if neg else "IN", values))
            out.echo.append(("料号", shown))
        elif fld == "PN":
            out.conds.append({"kind": "pn", "values": values, "neg": neg})
            out.needs.add("pn")
            out.echo.append(("PN", shown))
        elif fld == "供应商":
            got_v = base.suppliers(values, R)
            if isinstance(got_v, Ask):
                return got_v
            out.sql.append(cond("m.cVenCode", "NOT_IN" if neg else "IN", m.supplier_codes(got_v)))
            out.echo.append(("供应商", base.join(got_v)))
        elif fld == "问题类型":
            got_t = base.problem_types(values, list(enums.BR_PROBLEM_TYPES), LABEL, neg, out)
            if isinstance(got_t, Ask):
                return got_t
            if got_t:
                out.conds.append({"kind": "in", "col": "type", "values": got_t, "neg": neg})
                out.echo.append(("问题类型", base.join(got_t)))
        elif fld == "问题等级":
            got_l = domestic.levels_of(values)
            if isinstance(got_l, Ask):
                return got_l
            out.conds.append({"kind": "in", "col": "level", "values": got_l, "neg": neg})
            out.echo.append(("问题等级", base.join(got_l)))
        elif fld == "状态":
            got_s = status_items(values, enums.BR_STAGES, LABEL, out)
            if isinstance(got_s, Ask):
                return got_s
            if got_s:
                out.conds.append({"kind": "status", "items": got_s, "neg": neg})
                out.echo.append(("状态", shown))
        elif fld in ("跟进部门", "责任归属部门"):
            got_d = base.departments(values, R)
            if isinstance(got_d, Ask):
                return got_d
            if fld == "责任归属部门":
                out.notes.append("巴西没有责任归属部门，按问题跟进部门统计")
            out.conds.append({"kind": "any_of", "col": "_follow_dept_ids", "values": m.dept_ids(got_d), "neg": neg})
            out.echo.append(("问题跟进部门", base.join(got_d)))
            if len(got_d) > len(values) and not neg:
                out.breakdowns.append({"title": columns.shown("follow_dept", DOMAIN), "col": "follow_dept",
                                       "multi": False, "values": got_d})
        elif fld in ("跟进人", "责任人"):
            ids_all: list[int] = []
            for v in values:
                got_p = base.people(v, R, KIND_PERSON)
                if isinstance(got_p, Ask):
                    return got_p
                ids_all += got_p
            if fld == "责任人":
                out.notes.append("巴西的责任人即问题跟进人，巴西不提供当前责任人")
            out.conds.append({"kind": "any_of", "col": "_follower_ids", "values": ids_all, "neg": neg})
            out.echo.append(("问题跟进人", shown))
        elif fld == "不良率":
            base.numeric_cond("_rate_value", kind, values, out, fld, str(f.get("op") or "是"))
        elif fld in ("不良数量", "影响数量"):
            column = {"不良数量": "m.BadQty", "影响数量": "m.ImpactQty"}[fld]
            base.numeric_sql(column, kind, values, out, fld, str(f.get("op") or "是"))
        elif fld == "发现工位":
            for v in values:
                out.sql.append(cond("m.ProblemDiscoveryStation", "NOT_CONTAINS" if neg else "CONTAINS", v,
                                    include_nulls=neg))
            out.echo.append(("发现工位包含", shown))
        elif fld == "是否设计变更":
            yn = base.yes_no_or_chosen(values[0], R.query)
            if yn is None:
                return Ask("是否设计更改，选「是」还是「否」？", ["是", "否"], reason="取值对不上")
            if neg:
                yn = 1 - yn
            # 巴西处理过程上存「需要 / 不需要」（最新一条处理过程）
            out.conds.append({"kind": "in", "col": "design_change", "values": ["需要" if yn else "不需要"]})
            out.echo.append(("是否设计更改", "需要" if yn else "不需要"))
        elif fld == "是否需要回复8D":
            yn = base.yes_no_or_chosen(values[0], R.query)
            if yn is None:
                return Ask("是否需要回复 8D，选「是」还是「否」？", ["是", "否"], reason="取值对不上")
            if neg:
                yn = 1 - yn
            out.sql.append(cond("m.IsRequire8D", "EQ", 1 if yn else 2))
            out.echo.append(("是否需要回复 8D", "是" if yn else "否"))
        elif fld == "其他":
            said = str(f.get("column") or "")
            if columns.resolve(said) == "is_cost" or any(w in said for w in _COST_WORDS):
                ask = _cost_condition(values[0], neg, out, R.query)
                if ask is not None:
                    return ask
            else:
                domestic.other_column(f, values, neg, out, COLUMN_NEEDS, DOMAIN)
    return out


def _cost_condition(said: str, neg: bool, out: DomainStep, query: str) -> Ask | None:
    """巴西「费用」：用户明说「是否涉及费用」时按单上的标记筛，只看是、否两种（0 是测试脏值，不计入，J-D12）；
    其余说法（「涉及费用的单」「有费用的单」）按费用明细合计大于 0 认定，不看标记（巴西业务描述「费用」）。

    规划器常把条件本身写进取值（BR-004：列「费用明细合计大于 0」、取值「涉及费用」）：取值里说到费用时就是
    「是」，前面带否定词（「没有费用」「不涉及费用」）时是「否」。
    """
    yn = base.yes_no(said)
    k = names.key(said)
    if yn is None and any(w in k for w in _COST_WORDS):
        yn = 0 if k.startswith(_NEGATIONS) else 1
    if yn is None:
        yn = base.yes_no_or_chosen(said, query)
    if yn is None:
        return Ask("是否涉及费用，选「是」还是「否」？", ["是", "否"], reason="取值对不上")
    if neg:
        yn = 1 - yn
    if "是否涉及费用" in names.key(query):
        out.sql.append(cond("m.IsCost", "EQ", 1 if yn else 2))
        out.conds.append({"kind": "in", "col": "is_cost", "values": ["是" if yn else "否"]})
        out.echo.append(("是否涉及费用", "是" if yn else "否"))
    else:
        out.conds.append({"kind": "flag", "col": "_has_cost", "value": bool(yn)})
        out.needs.add("cost")
        out.echo.append(("涉及费用", "是（按费用明细认定）" if yn else "否（按费用明细认定）"))
    return None


def status_items(values: Sequence[str], stages: tuple[str, ...], label: str, out: DomainStep
                 ) -> list[list[str]] | Ask:
    """状态说法 → 判据（巴西、海外）。只有国内的停线状态（重启审核两步与重启方案）本域整域不计入。"""
    items: list[list[str]] = []
    for v in values:
        got = enums.status_kind(v, stages)
        if got is None:
            return Ask(f"「{v}」这个状态对不上，{label}的状态有：{base.join(stages)}。", list(stages)[:4],
                       reason="状态对不上", missing=f"没有「{v}」这一状态")
        if got[0] in enums.CN_ONLY_KINDS:
            out.excluded.append(f"{label}没有「{got[0]}」这一状态，{label}未计入")
            continue
        items.append([got[0], got[1]])
    return items


def within(out: DomainStep, ids: Sequence[int]) -> None:
    out.conds.append({"kind": "ids", "values": [int(i) for i in ids]})


# ---------------------------------------------------------------------------- 取数


def _main_filter(dstep: DomainStep) -> dict[str, Any]:
    return {"logic": "AND", "groups": [{"logic": "AND", "conditions": [NOT_DELETED, *dstep.sql]}]}


def _child(table: str, select: Sequence[str], dstep: DomainStep) -> dict[str, Any]:
    return {"source": INFO, "from": {"table": table, "alias": "c"},
            "joins": [{"table": {"table": MAIN, "alias": "m"}, "type": "INNER",
                       "on": [{"left": "c.ProblemID", "right": "m.ID"}]}],
            "select": [f"c.{c}" for c in select], "filter": _main_filter(dstep)}


def main_spec(dstep: DomainStep) -> dict[str, Any]:
    return {"source": INFO, "from": {"table": MAIN, "alias": "m"}, "select": [f"m.{c}" for c in MAIN_COLUMNS],
            "filter": _main_filter(dstep)}


def specs(dstep: DomainStep) -> dict[str, tuple[dict[str, Any], str | None]]:
    out: dict[str, tuple[dict[str, Any], str | None]] = {
        "br_main": (main_spec(dstep), "m.ID"),
        "br_process": (_child(PROCESS, PROCESS_COLUMNS, dstep), "c.ID"),
    }
    if "cost" in dstep.needs:
        out["br_cost"] = (_child(COST, ("ID", "ProblemID", "CostMoney", "CostBrlMoney"), dstep), "c.ID")
    if "pn" in dstep.needs:
        out["br_po"] = (_child(PO, ("ID", "ProblemID", "RequestID"), dstep), "c.ID")
    return out


async def fetch(ctx: Any, dstep: DomainStep, master: MasterData) -> dict[str, pd.DataFrame]:
    """本步巴西的全部帧。`TableDenied` 原样抛给调用方（该域改记无权，§14）。"""
    first = specs(dstep)
    frames = dict(zip(first, await asyncio.gather(*(base.fetch_all(ctx, s, k) for s, k in first.values())),
                      strict=True))
    main, process = frames["br_main"], frames["br_process"]
    second: dict[str, Any] = {}
    if "br_po" in frames:
        second["br_requests"] = base.fetch_in(
            ctx, {"source": INFO, "from": REQUESTS, "select": ["ID", "PartNumber"]}, "ID",
            base.int_keys(base.column(frames["br_po"], "RequestID")))
    if "inventory" in dstep.needs:
        second["inventory"] = base.fetch_in(
            ctx, {"source": INFO, "from": INVENTORY, "select": ["cInvCode", "cInvName", "cInvStd"]},
            "cInvCode", base.unique(str(x).strip() for x in base.column(main, "cInvCode") if x is not None))
    people = base.int_keys([*base.column(process, "ProcessUserID"), *base.column(main, "AddUserID"),
                            *base.column(main, "ActorUserID")])
    second["employees"] = base.fetch_in(ctx, {"source": INFO, "from": EMPLOYEE, "select": ["ID", "Name", "Unit"]},
                                        "ID", people)
    frames |= dict(zip(second, await asyncio.gather(*second.values()), strict=True))
    if "br_requests" in frames:
        codes = base.unique(str(x).strip() for x in base.column(frames["br_requests"], "PartNumber")
                            if x is not None and str(x).strip() not in ("", "0"))
        frames["pns"] = await base.fetch_in(ctx, {"source": INFO, "from": PNS, "select": ["PartNumber", "Name"]},
                                            "PartNumber", codes)
    for name in ("departments", "vendors", "products"):
        frames[name] = master.frames.get(name, pd.DataFrame())
    return frames
