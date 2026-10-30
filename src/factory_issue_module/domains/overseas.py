"""海外适配器（设计 §6.2、§6.3、§6.5；海外业务描述「查询范围」「口径」「关联」）。

- 第 6 步：落在主表列上、写成比较就够的进 SQL：未删除、建单时间、加工厂（海外工厂名称，对上的取值）、国内工厂
  （工厂码）、问题类型、问题跟进部门、IQC 意见、处理结果、是否设计变更、数量、发现工位（包含）。其余在沙箱里按
  派生列筛：问题等级、状态、机型（大机型逐段）、问题跟进人（逗号多值）、当前责任人、不良率（原文统一成百分数
  才比）、物料名称（物料清单的描述）、料号（物料清单任一条）、供应商（物料清单上的名称）、PN、建单以外的日期。
- 海外没有的：系列不作查询条件（「海外系列不作查询条件，未计入」）、产品在制属性、原因分类、是否需要回复 8D。
  按它们筛时海外整域不计入；责任归属部门按问题跟进部门、只说「责任人」按当前责任人解释，并写明。
- 取数：主表一帧，处理步骤在要结案时间时取；人员、PN 主数据按收集到的键取，国内工厂、部门、产品沿用主数据。
  不取叙述原文（§6.1）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pandas as pd

from factory_issue_module.declarations import INFO, Domain
from factory_issue_module.domains import base, brazil, domestic, enums
from factory_issue_module.domains.base import Ask, DomainStep, cond
from factory_issue_module.domains.shared import KIND_MACHINE, KIND_PERSON, MasterData
from factory_issue_module.plan import names, schema
from factory_issue_module.plan.timespan import Span
from factory_issue_module.present import columns

DOMAIN = Domain.OVERSEAS
LABEL = DOMAIN.label
MAIN = DOMAIN.master_table
STEPS = "CoreINFO.dbo.OverseasProblem_StepLog"
EMPLOYEE = "info.dbo.Employee"
PNS = "info.dbo.NewProduct"

#: 主表要取的列（不取问题描述、改善建议、原因分析、措施、对策、效果确认这些叙述，§6.1）
MAIN_COLUMNS = (
    "Id", "Numbers", "ProblemType", "OldProblemType", "ProblemRemark", "Factory", "Factory2", "ProductType", "Series",
    "PNList", "InvInfo", "ImpactQty", "BadQty", "Rate", "ProblemLevel", "FoundDate", "Station", "Version", "IsStop",
    "StopState", "StopDate", "ReStartDate", "Status", "MemberList", "MemberListName", "RDepartment", "RUser",
    "RCompleteTime", "IQCOpinion", "IsDesignChange", "DesignConfirmResult", "AddUser", "AddDate",
)
NOT_DELETED = cond("m.IsDelete", "EQ", 0)

BASES = ("建单", "现场发现", "停线", "重启", "结案")
_BASIS_NEEDS = {"结案": "steps"}
#: 海外不良率是单上原文（% 与 ‰ 混用），不汇总（总述「汇总不良率」）
TRAITS: dict[str, Any] = {"metrics": ["单数", "占比", "未结案数", "结案周期", "停线时长"], "rate": "text",
                          "small_sample": True, "close": "结案确认"}
#: 清单列：海外只说「责任人」同时给当前责任人与问题跟进人；没有责任归属部门，按问题跟进部门；按状态筛时加主表状态
KEY_ALIAS: dict[str, list[str] | None] = {"responsible": ["current_people", "follower"], "resp_dept": ["follow_dept"],
                                          "state_for_filter": ["status"]}
#: 用到海外单上的国内工厂时说一句（海外「加工厂」：国内工厂是另一列，只说「工厂」时不参与；OS-007）
CN_FACTORY_NOTE = "海外单上的「国内工厂」是另一列，与加工厂（海外工厂）不是同一列"

COLUMN_NEEDS = {"close_time": "steps", "pn": "pn"}
#: 靠主数据才写得出来的列（同 `domestic.MASTER_USES`）；海外加工厂是主表原文，不在这里
MASTER_USES = {"machine": "products", "_machines": "products", "follow_dept": "departments",
               "cn_factory": "factories"}
METRIC_NEEDS = {"结案周期": "steps"}
SORT_NEEDS = {"结案时间": "steps"}


def enum_params() -> dict[str, Any]:
    return {"types": enums.OS_PROBLEM_TYPES, "unknown_type": enums.OS_UNKNOWN_TYPE, "status": enums.OS_STATUS,
            "done": enums.OS_DONE, "stop_state": enums.OS_STOP_STATE, "not_stopped": enums.OS_NOT_STOPPED,
            "stopped": enums.OS_STOPPED, "restarted": enums.OS_RESTARTED, "iqc_opinion": enums.OS_IQC_OPINION,
            "design_result": enums.OS_DESIGN_RESULT, "yes_no": enums.OS_YES_NO, "step_close": enums.OS_STEP_CLOSE,
            "step_reject": enums.OS_STEP_REJECT, "non_block": list(enums.OS_NON_BLOCK_STEPS),
            "status_steps": {k: list(v) for k, v in enums.OS_STATUS_STEPS.items()},
            "block_main": {k: list(v) for k, v in enums.OS_BLOCK_MAIN.items()},
            # 单张单详情（S4）
            "step_assign": enums.OS_STEP_ASSIGN, "step_confirm": enums.OS_STEP_CONFIRM,
            "step_effect": enums.OS_STEP_EFFECT, "step_factory": enums.OS_STEP_FACTORY, "step_sqe": enums.OS_STEP_SQE,
            "need_design": enums.CN_NEED_DESIGN}


# ---------------------------------------------------------------------------- 分组维度

_PERIOD_COL = {"建单": "_add", "现场发现": "_found", "停线": "_stop", "重启": "_restart", "结案": "_close"}


def dims(group_by: Sequence[str], basis: str | None) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    def s(key: str) -> str:
        return columns.shown(key, DOMAIN)

    table: dict[str, dict[str, Any]] = {
        "域": {"const": LABEL, "title": columns.DOMAIN, "merge": True},
        "问题类型": {"col": "type", "keep_blank": True, "title": s("type"), "merge": True,
                     "universe": [*enums.OS_PROBLEM_TYPES.values(), "未填", enums.OS_UNKNOWN_TYPE]},
        "机型": {"col": "_machines", "multi": True, "empty": "未填", "title": s("machine"), "merge": True},
        "加工厂": {"col": "factory", "title": s("factory"), "merge": True},
        "国内工厂": {"col": "cn_factory", "title": s("cn_factory")},
        "结案与否": {"col": "_closed_label", "title": columns.CLOSED_OR_NOT, "merge": True,
                     "universe": domestic.CLOSED_UNIVERSE, "fill": domestic.CLOSED_UNIVERSE},
        "处理环节": {"col": "_stages", "multi": True, "title": columns.STAGE},
        "问题等级": {"col": "level", "keep_blank": True, "order": domestic.LEVEL_UNIVERSE, "title": s("level"),
                     "merge": True, "universe": domestic.LEVEL_UNIVERSE, "fill": domestic.LEVEL_FILL},
        "跟进部门": {"col": "follow_dept", "title": s("follow_dept"), "merge": True},
        "跟进人": {"col": "_follower_names", "multi": True, "title": s("follower"), "merge": True},
        "当前责任人": {"col": "_current_names", "multi": True, "title": s("current_people"), "merge": True},
        "责任人": {"col": "_current_names", "multi": True, "title": s("current_people")},
        "责任归属部门": {"col": "follow_dept", "title": s("follow_dept")},
        "处理结果": {"col": "design_result", "keep_blank": True, "title": s("design_result")},
        "停线状态": {"col": "stop_status", "title": s("stop_status")},
        "状态": {"col": "status", "title": s("status")},
    }
    return base.build_dims(group_by, basis, table, _PERIOD_COL, None, _BASIS_NEEDS)


# ---------------------------------------------------------------------------- 第 6 步：条件对库

_MASTER_OF = {"机型": "products", "加工厂": "os_factories", "国内工厂": "factories", "跟进部门": "departments",
              "责任归属部门": "departments", "跟进人": "people", "当前责任人": "people", "责任人": "people"}
_ABSENT = {
    "系列": "海外系列不作查询条件，海外未计入，可以改按机型查",
    "产品在制属性": "海外没有「产品在制属性」，海外未计入",
    "原因分类": "海外没有「原因分类」，海外未计入",
    "是否需要回复8D": "海外没有「是否需要回复 8D」，海外未计入",
}


def resolve(step: dict, spans: Sequence[Span], R: base.Resolver) -> DomainStep | Ask:
    """一步在海外的条件（第 6 步）。"""
    out = DomainStep(domain=DOMAIN)
    p = step.get("params") or {}
    base.time_conditions(step, spans, out, label=LABEL, add_col="m.AddDate", bases=BASES, needs=_BASIS_NEEDS)
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
                out.notes.append(f"海外按以下机型统计：{base.join(hit)}")
            out.conds.append({"kind": "any_of", "col": "_machines", "values": hit, "neg": neg})
            out.echo.append(("机型", base.join(hit)))
        elif fld in ("加工厂", "国内工厂"):
            pool = m.os_factories if fld == "加工厂" else m.factory_names()
            regions = None if fld == "加工厂" else R.regions
            hit = []
            for v in values:
                got = list(names.factories(v, pool, regions))
                if not got:
                    return base.not_found("加工厂" if fld == "加工厂" else "国内工厂", v, R.entities, None)
                if len(got) > 1:
                    return Ask(f"「{v}」对上了这几家工厂：{base.join(got)}。按哪几家查？", [base.join(got), *got][:4],
                               reason="多工厂")
                hit += [x for x in got if x not in hit]
            if fld == "加工厂":
                out.sql.append(cond("m.Factory", "NOT_IN" if neg else "IN", hit))
            else:
                out.sql.append(cond("m.Factory2", "NOT_IN" if neg else "IN", m.factory_codes(hit)))
            out.echo.append((fld, base.join(hit)))
        elif fld == "物料名称":
            out.conds.append({"kind": "contains", "col": "_inv_name", "values": values, "neg": neg})
            out.echo.append(("物料名称包含", shown))
        elif fld == "料号":
            out.conds.append({"kind": "any_of", "col": "_inv_codes", "values": values, "neg": neg})
            out.echo.append(("料号", shown))
        elif fld == "PN":
            out.conds.append({"kind": "pn", "values": values, "neg": neg})
            out.needs.add("pn")
            out.echo.append(("PN", shown))
        elif fld == "供应商":
            # 海外的供应商名称写在物料清单里，不查供应商表（海外业务描述「物料」）：按名称包含找
            out.conds.append({"kind": "contains", "col": "_ven_names_text", "values": values, "neg": neg})
            out.echo.append(("供应商", shown))
        elif fld == "问题类型":
            got_t = base.problem_types(values, list(enums.OS_PROBLEM_TYPES.values()), LABEL, neg, out)
            if isinstance(got_t, Ask):
                return got_t
            codes = [c for t in got_t for c in enums.code_of(enums.OS_PROBLEM_TYPES, t)]
            if codes:
                out.sql.append(cond("m.ProblemType", "NOT_IN" if neg else "IN", base.unique(codes)))
                out.echo.append(("问题类型", base.join(got_t)))
        elif fld == "问题等级":
            got_l = domestic.levels_of(values)
            if isinstance(got_l, Ask):
                return got_l
            out.conds.append({"kind": "in", "col": "level", "values": got_l, "neg": neg})
            out.echo.append(("问题等级", base.join(got_l)))
        elif fld == "状态":
            got_s = brazil.status_items(values, enums.OS_STAGES, LABEL, out)
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
                out.notes.append("海外没有责任归属部门，按问题跟进部门统计")
            out.sql.append(cond("m.RDepartment", "NOT_IN" if neg else "IN", m.dept_ids(got_d)))
            out.echo.append(("问题跟进部门", base.join(got_d)))
            if len(got_d) > len(values) and not neg:
                out.breakdowns.append({"title": columns.shown("follow_dept", DOMAIN), "col": "follow_dept",
                                       "multi": False, "values": got_d})
        elif fld in ("跟进人", "当前责任人", "责任人"):
            ids_all: list[int] = []
            for v in values:
                got_p = base.people(v, R, KIND_PERSON)
                if isinstance(got_p, Ask):
                    return got_p
                ids_all += got_p
            if fld == "跟进人":
                out.conds.append({"kind": "any_of", "col": "_follower_ids", "values": ids_all, "neg": neg})
                out.echo.append(("问题跟进人", shown))
            else:
                if fld == "责任人":
                    out.notes.append("海外的责任人按当前责任人")
                out.conds.append({"kind": "any_of", "col": "_current_ids", "values": ids_all, "neg": neg})
                out.echo.append(("当前责任人", shown))
        elif fld in ("IQC意见", "处理结果"):
            table = {"IQC意见": enums.OS_IQC_OPINION, "处理结果": enums.OS_DESIGN_RESULT}[fld]
            column = {"IQC意见": "m.IQCOpinion", "处理结果": "m.DesignConfirmResult"}[fld]
            got_codes = domestic.enum_codes(fld, values, table)
            if isinstance(got_codes, Ask):
                return got_codes
            out.sql.append(cond(column, "NOT_IN" if neg else "IN", got_codes))
            out.echo.append((fld, shown))
        elif fld == "不良率":
            base.numeric_cond("_rate_value", kind, values, out, fld, str(f.get("op") or "是"))
        elif fld in ("不良数量", "影响数量"):
            column = {"不良数量": "m.BadQty", "影响数量": "m.ImpactQty"}[fld]
            base.numeric_sql(column, kind, values, out, fld, str(f.get("op") or "是"))
        elif fld == "发现工位":
            for v in values:
                out.sql.append(cond("m.Station", "NOT_CONTAINS" if neg else "CONTAINS", v, include_nulls=neg))
            out.echo.append(("发现工位包含", shown))
        elif fld == "是否设计变更":
            yn = base.yes_no_or_chosen(values[0], R.query)
            if yn is None:
                return Ask("是否设计变更，选「是」还是「否」？", ["是", "否"], reason="取值对不上")
            if neg:
                yn = 1 - yn
            out.sql.append(cond("m.IsDesignChange", "EQ", yn))
            out.echo.append(("是否设计变更", "是" if yn else "否"))
        elif fld == "其他":
            domestic.other_column(f, values, neg, out, COLUMN_NEEDS, DOMAIN)
    return out


def within(out: DomainStep, ids: Sequence[int]) -> None:
    out.conds.append({"kind": "ids", "values": [int(i) for i in ids]})


# ---------------------------------------------------------------------------- 取数


def _main_filter(dstep: DomainStep) -> dict[str, Any]:
    return {"logic": "AND", "groups": [{"logic": "AND", "conditions": [NOT_DELETED, *dstep.sql]}]}


def main_spec(dstep: DomainStep) -> dict[str, Any]:
    return {"source": INFO, "from": {"table": MAIN, "alias": "m"}, "select": [f"m.{c}" for c in MAIN_COLUMNS],
            "filter": _main_filter(dstep)}


def steps_spec(dstep: DomainStep) -> dict[str, Any]:
    return {"source": INFO, "from": {"table": STEPS, "alias": "c"},
            "joins": [{"table": {"table": MAIN, "alias": "m"}, "type": "INNER",
                       "on": [{"left": "c.ProblemId", "right": "m.Id"}]}],
            "select": ["c.Id", "c.ProblemId", "c.StepStr", "c.AddDate"], "filter": _main_filter(dstep)}


async def fetch(ctx: Any, dstep: DomainStep, master: MasterData) -> dict[str, pd.DataFrame]:
    """本步海外的全部帧。`TableDenied` 原样抛给调用方（该域改记无权，§14）。"""
    first: dict[str, tuple[dict[str, Any], str]] = {"os_main": (main_spec(dstep), "m.Id")}
    if "steps" in dstep.needs:
        first["os_steps"] = (steps_spec(dstep), "c.Id")
    frames = dict(zip(first, await asyncio.gather(*(base.fetch_all(ctx, s, k) for s, k in first.values())),
                      strict=True))
    main = frames["os_main"]
    second: dict[str, Any] = {}
    people = base.int_keys([*base.column(main, "RUser"), *base.column(main, "AddUser")])
    second["employees"] = base.fetch_in(ctx, {"source": INFO, "from": EMPLOYEE, "select": ["ID", "Name", "Unit"]},
                                        "ID", people)
    if "pn" in dstep.needs:
        codes = base.unique(part.strip() for x in base.column(main, "PNList") if x is not None
                            for part in str(x).replace("，", ",").split(",") if part.strip())
        second["pns"] = base.fetch_in(ctx, {"source": INFO, "from": PNS, "select": ["PartNumber", "Name"]},
                                      "PartNumber", codes)
    frames |= dict(zip(second, await asyncio.gather(*second.values()), strict=True))
    for name in ("departments", "factories", "products"):
        frames[name] = master.frames.get(name, pd.DataFrame())
    return frames


# ---------------------------------------------------------------------------- 单张单详情与按号查单（S4）

DELIVERY = "CoreINFO.dbo.OverseasProblem_DeliveryOrder"
PREASON = "CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason"
#: 单张单详情另取的主表列：叙述原文、已选问题现象、附件、效果确认与设计变更（§13）
DETAIL_COLUMNS = (*MAIN_COLUMNS, "ProblemDesc", "Improve", "Remark", "Reason", "Measures", "Prevention", "Confirmation",
                  "ConfirmUser", "ConfirmDate", "RConfirm", "DesignUser", "DesignDate", "hasCheckedPhenomenon", "DocId")


def issue_step(numbers: Sequence[str] = (), ids: Sequence[int] = ()) -> DomainStep:
    if ids:
        return DomainStep(domain=DOMAIN, sql=[cond("m.Id", "IN", [int(i) for i in ids])])
    return DomainStep(domain=DOMAIN, sql=[cond("m.Numbers", "IN", list(numbers))])


def _child(table: str, select: Sequence[str], dstep: DomainStep, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    flt = _main_filter(dstep)
    if extra is not None:
        flt["groups"].append(extra)
    return {"source": INFO, "from": {"table": table, "alias": "c"},
            "joins": [{"table": {"table": MAIN, "alias": "m"}, "type": "INNER",
                       "on": [{"left": "c.ProblemId", "right": "m.Id"}]}],
            "select": [f"c.{c}" for c in select], "filter": flt}


async def detail_fetch(ctx: Any, dstep: DomainStep, master: MasterData, *, car: bool = False) -> dict[str, pd.DataFrame]:
    """单张单详情的帧（海外「单张单详情」）：主表含叙述列、全部处理步骤、涉及发货单；再按单上登记的附件 ID 取文档
    （海外附件只能从单上登记的 ID 出发取，文档清单表文件）、人员、PN 名称；现象可能原因整表小，整表取。"""
    first: dict[str, Any] = {
        "os_main": base.fetch(ctx, {**main_spec(dstep), "select": [f"m.{c}" for c in DETAIL_COLUMNS]}),
        "os_steps": base.fetch_all(ctx, _child(STEPS, ("Id", "ProblemId", "StepStr", "Result", "Opinon", "Measures",
                                                       "DocID", "AddUser", "AddDate"), dstep), "c.Id"),
        "os_delivery": base.fetch_all(ctx, _child(DELIVERY, ("Id", "ProblemId", "PO", "OrderNumber", "Date", "PN",
                                                             "DeliveryVersion", "ProdVersion", "Quantity", "Remark"),
                                                  dstep), "c.Id"),
        "os_preason": base.fetch(ctx, {"source": INFO, "from": PREASON, "select": ["ID", "PhenomenonID", "ReasonDesc"]}),
    }
    frames = dict(zip(first, await asyncio.gather(*first.values()), strict=True))
    main, steps = frames["os_main"], frames["os_steps"]
    codes = base.unique(part.strip() for x in [*base.column(main, "PNList"), *base.column(frames["os_delivery"], "PN")]
                        if x is not None for part in str(x).replace("，", ",").split(",") if part.strip())
    second: dict[str, Any] = {
        "documents": base.fetch_in(ctx, domestic.documents_spec(), "ID",
                                   base.int_keys([*base.column(main, "DocId"), *base.column(steps, "DocID")])),
        "employees": base.fetch_in(ctx, {"source": INFO, "from": EMPLOYEE, "select": ["ID", "Name", "Unit"]}, "ID",
                                   base.int_keys([*base.column(main, "RUser"), *base.column(main, "AddUser"),
                                                  *base.column(main, "ConfirmUser"), *base.column(main, "DesignUser"),
                                                  *base.column(steps, "AddUser")])),
        "pns": base.fetch_in(ctx, {"source": INFO, "from": PNS, "select": ["PartNumber", "Name"]}, "PartNumber", codes),
    }
    frames |= dict(zip(second, await asyncio.gather(*second.values()), strict=True))
    for name in ("departments", "factories", "products"):
        frames[name] = master.frames.get(name, pd.DataFrame())
    return frames


async def lookup_fetch(ctx: Any, lookups: Sequence[Any], master: MasterData) -> dict[str, pd.DataFrame]:
    """按号查单：问题编号在主表上精确匹配；发货单号、PO 在涉及发货单上精确匹配；料号在物料清单里、PN 在主表 PN 里
    （都是单内的多值，海外未删除的单只有十几张，取全部在沙箱里逐段比）。"""
    by: dict[str, list[str]] = {}
    for lk in lookups:
        by.setdefault(lk.kind, []).append(lk.value)
    frames: dict[str, pd.DataFrame] = {}
    conds = ([cond("c.OrderNumber", "IN", by["delivery"])] if by.get("delivery") else []) + \
            ([cond("c.PO", "IN", by["po"])] if by.get("po") else [])
    if conds:
        frames["os_hit_delivery"] = await base.fetch_all(
            ctx, _child(DELIVERY, ("Id", "ProblemId", "PO", "OrderNumber", "Date", "PN", "Quantity"),
                        DomainStep(domain=DOMAIN), {"logic": "OR", "conditions": conds}), "c.Id")
    if by.get("pn_name"):
        frames["lk_pns"] = await base.fetch_in(ctx, {"source": INFO, "from": PNS, "select": ["PartNumber", "Name"]},
                                               "Name", by["pn_name"])
    sql = [cond("m.Numbers", "IN", by["issue"])] if set(by) == {"issue"} else []
    frames |= await fetch(ctx, DomainStep(domain=DOMAIN, sql=sql, needs={"pn"}), master)
    return frames
