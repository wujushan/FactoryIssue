"""国内适配器（设计 §6.2、§6.3、§6.5；国内业务描述「口径」「关联」）。

- 第 6 步：把计划里的条件（照抄的用户说法）对到库里的取值与代码，换算时间，写成两份：落在主表列上的条件进
  SQL（`fetch` 的 FilterCondition），要派生才知道的（状态、当前责任人、责任人、责任归属部门、机型、系列、物料名称、
  PN、建单以外的日期）交沙箱。对不上、对上多个、重名、枚举说法对不上时返回追问（`base.Ask`），本轮不取数。
  国内没有的列（统计日期、是否需要回复 8D、海外单上的国内工厂）、点名的类型国内一个都没有时，国内整域不计入
  （`DomainStep.excluded`，总述「通用筛选规则」默认范围）。
- 取数：主表一帧，机型、处理步骤、风险订单流程、生产订单按需各一帧（子表 INNER JOIN 主表，带主表的条件），
  再按收集到的键取待办任务、存货、人员。不取叙述原文（§6.1）。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

import pandas as pd
import structlog
from forge_core.errors import TableDenied

from factory_issue_module.declarations import INFO, TASK_TABLE, Domain
from factory_issue_module.domains import base, enums
from factory_issue_module.domains.base import Ask, DomainStep, cond
from factory_issue_module.domains.shared import KIND_MACHINE, KIND_PERSON, MasterData
from factory_issue_module.plan import names, schema
from factory_issue_module.plan.timespan import Span
from factory_issue_module.present import columns

logger = structlog.get_logger(__name__)

DOMAIN = Domain.DOMESTIC
LABEL = DOMAIN.label
MAIN = DOMAIN.master_table
MODELS = "CoreINFO.dbo.ZCTracking_ProductNames"
STEPS = "CoreINFO.dbo.ZCTracking_ProblemSteplog"
RISK = "CoreINFO.dbo.ZCTracking_RiskStream"
ORDERS = "CoreINFO.dbo.ZCTracking_ProblemOrders"
EMPLOYEE = "info.dbo.Employee"
INVENTORY = "info.dbo.Inventory"

#: 主表要取的列：标识、枚举、数量、日期、人员与部门 ID（不取叙述原文，§6.1）
MAIN_COLUMNS = (
    "ID", "Numbers", "ProblemType", "OldProblemType", "Factory", "Status", "ImpactQty", "BadQty", "ProdQty", "Rate",
    "FoundDate", "Station", "Version", "ProblemLevel", "OutPutStatus", "MHead", "IsStop", "StopStatus", "StopDate",
    "CInvCode", "VenCode", "MemberList", "MemberListName", "RDepartment", "RUser", "RCompleteTime",
    "AllReDepartment", "ReasonClass", "IsDesignChange", "DesignConfirmResult", "IQCOpinion", "IQCStatus",
    "IQCMemberList", "IQCMemberListName", "CAR", "CARID", "AddUser", "AddDate",
)
NOT_DELETED = cond("m.IsDelete", "EQ", 0, include_nulls=True)

#: 国内有的日期依据（总述「按哪个日期筛」）；按结案、重启筛要取处理步骤
BASES = ("建单", "现场发现", "停线", "重启", "结案")
_BASIS_NEEDS = {"结案": "steps", "重启": "steps"}

#: 沙箱里的域特性：能算哪些指标、不良率怎么汇总（总述「汇总不良率」：国内分母为生产数量）
#: `close` 是结案时间的取法（总述「结案时间与结案周期」）：几域取法相同时结案周期才能合在一起算
TRAITS: dict[str, Any] = {"metrics": ["单数", "占比", "未结案数", "合计不良率", "结案周期", "停线时长"],
                          "rate": "sum", "rate_den": "生产数量", "close": "结案确认"}

#: 清单列：用户叫法对到的内部键在本域换成哪几列（None = 本域没有这一项）。国内每一项都有
KEY_ALIAS: dict[str, list[str] | None] = {}


def enum_params() -> dict[str, Any]:
    """沙箱派生要的枚举对照（`domains/enums.py`）。"""
    return {
        "types": enums.CN_PROBLEM_TYPES, "status": enums.CN_STATUS, "stop_status": enums.CN_STOP_STATUS,
        "output_status": enums.CN_OUTPUT_STATUS, "design_result": enums.CN_DESIGN_RESULT,
        "iqc_opinion": enums.CN_IQC_OPINION, "yes_no": enums.CN_YES_NO, "risk_steps": enums.CN_RISK_STEPS,
        "responsible_step": enums.CN_RESPONSIBLE_STEP, "done": enums.CN_DONE, "rejected": enums.CN_REJECTED,
        "parallel": list(enums.CN_PARALLEL), "needs_prevention": list(enums.CN_NEEDS_PREVENTION),
        "stopped": list(enums.CN_STOPPED), "restarted": enums.CN_RESTARTED, "task_effect": enums.CN_TASK_EFFECT,
        "task_prevention": enums.CN_TASK_PREVENTION, "task_accepted": enums.CN_TASK_ACCEPTED,
        "step_close": enums.CN_STEP_CLOSE, "step_restart": enums.CN_STEP_RESTART,
        "step_reclassify": enums.CN_STEP_RECLASSIFY, "risk_running": enums.CN_RISK_RUNNING,
        # 单张单详情（S4）
        "detail_stages": enums.CN_DETAIL_STAGES, "step_fill": enums.CN_STEP_FILL, "step_reject": enums.CN_STEP_REJECT,
        "restart_steps": list(enums.CN_RESTART_STEPS), "step_restart_review": enums.CN_STEP_RESTART_REVIEW,
        "step_restart_scheme": enums.CN_STEP_RESTART_SCHEME, "stop_reviewing": enums.CN_STOP_REVIEWING,
        "stop_scheme": enums.CN_STOP_SCHEME, "review_result": enums.CN_REVIEW_RESULT,
        "role_agree": enums.CN_ROLE_AGREE, "role_disagree": enums.CN_ROLE_DISAGREE, "need_design": enums.CN_NEED_DESIGN,
        "return_type": enums.CN_RETURN_TYPE, "five_status": enums.CN_FIVE_WHY_STATUS,
        "five_pending": enums.CN_FIVE_WHY_PENDING, "five_stage": enums.CN_FIVE_WHY_STAGE,
    }


# ---------------------------------------------------------------------------- 分组维度

_PERIOD_COL = {"建单": "_add", "现场发现": "_found", "停线": "_stop", "重启": "_restart", "结案": "_close"}
PERIOD_DIMS = base.PERIOD_DIMS
#: 问题等级三域相同：合并表里 A+、A、B、C 没有单也列出（总述「跨域归并」）
LEVEL_FILL = list(enums.CN_LEVELS)
LEVEL_UNIVERSE = [*enums.CN_LEVELS, "未填"]
CLOSED_UNIVERSE = ["已结案", "未结案"]


def dims(group_by: Sequence[str], basis: str | None) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """计划的分组维度 → 沙箱的维度说明；返回 (维度, 国内没有的维度, 要额外取的帧)。"""
    s = columns.shown
    table: dict[str, dict[str, Any]] = {
        "域": {"const": LABEL, "title": columns.DOMAIN, "merge": True},
        "问题类型": {"col": "type", "keep_blank": True, "title": s("type"), "merge": True,
                     "universe": [*enums.CN_PROBLEM_TYPES.values(), "未填"]},
        "机型": {"col": "_machines", "multi": True, "empty": "未填", "title": s("machine"), "merge": True},
        "系列": {"col": "_series", "multi": True, "empty": "未填", "title": s("series"), "merge": True},
        "加工厂": {"col": "factory", "title": s("factory"), "merge": True},
        "结案与否": {"col": "_closed_label", "title": columns.CLOSED_OR_NOT, "merge": True,
                     "universe": CLOSED_UNIVERSE, "fill": CLOSED_UNIVERSE},
        "处理环节": {"col": "_stages", "multi": True, "title": columns.STAGE},
        "问题等级": {"col": "level", "keep_blank": True, "order": LEVEL_UNIVERSE, "title": s("level"),
                     "merge": True, "universe": LEVEL_UNIVERSE, "fill": LEVEL_FILL},
        "跟进部门": {"col": "follow_dept", "title": s("follow_dept"), "merge": True},
        "跟进人": {"col": "follower", "title": s("follower"), "merge": True},
        "当前责任人": {"col": "_current_names", "multi": True, "title": s("current_people"), "merge": True},
        "责任人": {"col": "responsible", "title": s("responsible")},
        "责任归属部门": {"col": "_resp_dept_names", "multi": True, "title": s("resp_dept")},
        "原因分类": {"col": "reason_class", "keep_blank": True, "title": s("reason_class")},
        "处理结果": {"col": "design_result", "keep_blank": True, "title": s("design_result")},
        "产品在制属性": {"col": "output_status", "keep_blank": True, "title": s("output_status")},
        "停线状态": {"col": "stop_status", "keep_blank": True, "title": s("stop_status")},
        "状态": {"col": "status", "title": s("status")},
    }
    needs_by = {"处理环节": "state", "当前责任人": "state", "责任人": "steps"}
    return base.build_dims(group_by, basis, table, _PERIOD_COL, needs_by, _BASIS_NEEDS)


#: 列（清单）与指标、排序要额外取的帧
COLUMN_NEEDS = {"current_state": "state", "current_people": "state", "responsible": "steps",
                "close_time": "steps", "restart_date": "steps", "inv_name": "inventory", "inv_std": "inventory"}
#: 视图里靠第 4 步之前取的主数据才写得出来的列 → 主数据名（`MasterData.failed` 里的名字）。主数据没取到时，清单
#: 要这一列或按它分组，这一段答「这一部分暂时没查到」，不把整列写成「未填」（设计 §14）
MASTER_USES = {"factory": "factories", "follow_dept": "departments", "resp_dept": "departments",
               "_resp_dept_names": "departments", "ven_name": "suppliers"}
METRIC_NEEDS = {"结案周期": "steps", "停线时长": "steps"}
SORT_NEEDS = {"结案时间": "steps"}
#: 临时统计的输入帧要的帧（结案时间、重启日期、停线时长、责任人看处理步骤；当前状态、处理环节、当前责任人看待办
#: 任务与风险订单流程；物料名称看存货，§5.5）
CUSTOM_NEEDS = frozenset({"steps", "state", "inventory"})
#: 结论的要点要的帧：积压看处理环节（待办任务与风险订单流程），时效看结案时间（处理步骤）（决策 2026-11-03
#: 「结论的要点与需关注的单」）
INSIGHT_NEEDS = frozenset({"steps", "state"})


# ---------------------------------------------------------------------------- 第 6 步：条件对库

#: 三域共用（S3 起放在 `domains/base.py`）；这里留名字给旧的调用方
Resolver = base.Resolver
period_label = base.period_label

#: 条件 → 对库要用的主数据（`MasterData.failed` 里的名字）
_MASTER_OF = {"机型": "models", "系列": "models", "加工厂": "factories", "供应商": "suppliers", "跟进部门": "departments",
              "责任归属部门": "departments", "跟进人": "people", "当前责任人": "people", "责任人": "people"}
#: 国内没有对应列的条件：按它筛时国内整域不计入
_ABSENT = {"国内工厂": "「国内工厂」只是海外单上的一列，国内未计入",
           "是否需要回复8D": "国内没有「是否需要回复 8D」，国内未计入"}


def resolve(step: dict, spans: Sequence[Span], R: base.Resolver) -> DomainStep | Ask:
    """一步在国内的条件（第 6 步）。"""
    out = DomainStep(domain=DOMAIN)
    p = step.get("params") or {}
    base.time_conditions(step, spans, out, label=LABEL, add_col="m.AddDate", bases=BASES, needs=_BASIS_NEEDS)
    m = R.master
    for f in base.each_filter(p, out):
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
                out.notes.append(f"按以下机型统计：{base.join(hit)}")
            out.conds.append({"kind": "any_of", "col": "_machines", "values": hit, "neg": neg})
            out.echo.append(("机型", base.join(hit)))
        elif fld == "系列":
            got_series = series_of(values, m, DOMAIN)
            if isinstance(got_series, Ask):
                return got_series
            out.conds.append({"kind": "any_of", "col": "_series", "values": got_series, "neg": neg})
            out.echo.append(("系列", base.join(got_series)))
        elif fld == "加工厂":
            rest = base.rest_of(fld, values, neg, R)
            if rest is not None:  # 上一轮选了地区里的几家、本轮问另外的（G43）
                left, note = rest
                out.notes.append(note)
                out.sql.append(cond("m.Factory", "IN", m.factory_codes(left)))
                base.echo_as_is(out, "加工厂", base.join(left))
                continue
            hit = []
            for v in values:
                got = list(names.factories(v, m.factory_names(), R.regions))
                if not got:
                    return base.not_found("加工厂", v, R.entities, None)
                if len(got) > 1:
                    scope = {"field": fld, "candidates": got} if names.region_items(v, R.regions) else None
                    return Ask(f"「{v}」对上了这几家工厂：{base.join(got)}。按哪几家查？", [base.join(got), *got][:4],
                               reason="多工厂", said=v, scope=scope)
                hit += [x for x in got if x not in hit]
            codes = m.factory_codes(hit)
            out.sql.append(cond("m.Factory", "NOT_IN" if neg else "IN", codes))
            out.echo.append(("加工厂", base.join(hit)))
        elif fld == "物料名称":
            out.conds.append({"kind": "contains", "col": "_inv_name", "values": values, "neg": neg})
            out.needs.add("inventory")
            out.echo.append(("物料名称包含", shown))
        elif fld == "料号":
            out.sql.append(cond("m.CInvCode", "NOT_IN" if neg else "IN", values))
            out.echo.append(("料号", shown))
        elif fld == "PN":
            out.conds.append({"kind": "pn", "values": values, "neg": neg})
            out.needs.add("orders")
            out.echo.append(("PN", shown))
        elif fld == "供应商":
            got_v = base.suppliers(values, R)
            if isinstance(got_v, Ask):
                return got_v
            out.sql.append(cond("m.VenCode", "NOT_IN" if neg else "IN", m.supplier_codes(got_v)))
            out.echo.append(("供应商", base.join(got_v)))
        elif fld == "问题类型":
            got_t = base.problem_types(values, list(enums.CN_PROBLEM_TYPES.values()), LABEL, neg, out)
            if isinstance(got_t, Ask):
                return got_t
            codes_t = [c for t in got_t for c in enums.code_of(enums.CN_PROBLEM_TYPES, t)]
            if codes_t:
                out.sql.append(cond("m.ProblemType", "NOT_IN" if neg else "IN", base.unique(codes_t)))
                out.echo.append(("问题类型", base.join(got_t)))
        elif fld == "问题等级":
            got_l = levels_of(values)
            if isinstance(got_l, Ask):
                return got_l
            # 「未填」与具体等级可以同时选，按展示文字在沙箱里比（等级的空值有 NULL 与空串两种）
            out.conds.append({"kind": "in", "col": "level", "values": got_l, "neg": neg})
            out.echo.append(("问题等级", base.join(got_l)))
        elif fld == "状态":
            items: list[list[str]] = []
            for v in values:
                got_s = enums.status_kind(v)
                if got_s is None:
                    return Ask(f"「{v}」这个状态对不上，可以选：", enums.status_options(), reason="状态对不上",
                               missing=f"没有「{v}」这一状态", said=v)
                items.append([got_s[0], got_s[1]])
                if got_s[0] == "环节":
                    out.needs.add("state")
            out.conds.append({"kind": "status", "items": items, "neg": neg})
            out.echo.append(("状态", shown))
        elif fld in ("跟进部门", "责任归属部门"):
            got_d = base.departments(values, R)
            if isinstance(got_d, Ask):
                return got_d
            several = len(got_d) > len(values) and not neg
            ids = m.dept_ids(got_d)
            if fld == "跟进部门":
                out.sql.append(cond("m.RDepartment", "NOT_IN" if neg else "IN", ids))
                out.echo.append(("问题跟进部门", base.join(got_d)))
                if several:
                    out.breakdowns.append({"title": columns.shown("follow_dept"), "col": "follow_dept",
                                           "multi": False, "values": got_d})
            else:
                if several:
                    out.breakdowns.append({"title": columns.shown("resp_dept"), "col": "_resp_dept_names",
                                           "multi": True, "values": got_d})
                out.conds.append({"kind": "any_of", "col": "_resp_dept_ids", "values": ids, "neg": neg})
                out.conds.append({"kind": "flag", "col": "_resp_material", "value": False})
                out.echo.append(("责任归属部门", base.join(got_d)))
        elif fld in ("跟进人", "当前责任人", "责任人"):
            ids_all: list[int] = []
            for v in values:
                got_p = base.people(v, R, KIND_PERSON)
                if isinstance(got_p, Ask):
                    return got_p
                ids_all += got_p
            shown = base.person_shown(values, R)
            if fld == "跟进人":
                out.sql.append(cond("m.RUser", "NOT_IN" if neg else "IN", [str(i) for i in ids_all]))
                out.echo.append(("问题跟进人", shown))
            elif fld == "当前责任人":
                out.conds.append({"kind": "any_of", "col": "_current_ids", "values": ids_all, "neg": neg})
                out.needs.add("state")
                out.echo.append(("当前责任人", shown))
            else:
                out.conds.append({"kind": "any_of", "col": "_responsible_ids", "values": ids_all, "neg": neg})
                out.needs.add("steps")
                out.echo.append(("责任人", shown))
        elif fld in ("产品在制属性", "处理结果", "IQC意见"):
            table = {"产品在制属性": enums.CN_OUTPUT_STATUS, "处理结果": enums.CN_DESIGN_RESULT,
                     "IQC意见": enums.CN_IQC_OPINION}[fld]
            column = {"产品在制属性": "m.OutPutStatus", "处理结果": "m.DesignConfirmResult", "IQC意见": "m.IQCOpinion"}[fld]
            got_codes = enum_codes(fld, values, table)
            if isinstance(got_codes, Ask):
                return got_codes
            out.sql.append(cond(column, "NOT_IN" if neg else "IN", got_codes))
            out.echo.append((fld, shown))
        elif fld in ("不良率", "不良数量", "影响数量"):
            column = {"不良率": "m.Rate", "不良数量": "m.BadQty", "影响数量": "m.ImpactQty"}[fld]
            base.numeric_sql(column, kind, values, out, fld, str(f.get("op") or "是"))
        elif fld == "发现工位":
            for v in values:
                out.sql.append(cond("m.Station", "NOT_CONTAINS" if neg else "CONTAINS", v, include_nulls=neg))
            out.echo.append(("发现工位包含", shown))
        elif fld == "是否设计变更":
            yn = base.yes_no_or_chosen(values[0], R.query)
            if yn is None:
                return Ask("是否设计变更，选「是」还是「否」？", ["是", "否"], reason="取值对不上", said=values[0])
            if neg:
                yn = 1 - yn
            out.sql.append(cond("m.IsDesignChange", "EQ", yn))
            base.echo_as_is(out, "是否设计变更", "是" if yn else "否")
        elif fld == "原因分类":
            out.conds.append({"kind": "contains", "col": "reason_class", "values": values, "neg": neg})
            out.echo.append(("原因分类", shown))
        elif fld == "其他":
            other_column(f, values, neg, out, COLUMN_NEEDS, DOMAIN)
    return out


# ---------------------------------------------------------------------------- 三域共用的几种条件（巴西、海外也调）


def series_of(values: Sequence[str], m: MasterData, domain: Domain) -> list[str] | Ask:
    """系列（总述「机型与系列怎么对」）：对不上时列出可选系列请用户选；给的是机型名称时说明它属于哪个系列。"""
    pool = m.series_in(domain)
    hit: list[str] = []
    for v in values:
        got = list(names.series(v, pool))
        if not got:
            machine = names.machines(re.sub(r"系列$", "", v), m.machines_in(domain))
            tip = f"「{machine[0]}」是机型，属于{m.machine_series[machine[0]]}。" if (
                machine and machine[0] in m.machine_series) else ""
            return Ask(f"没有找到「{v}」这个系列。{tip}可选的系列有：{base.join(pool[:12])}。",
                       list(pool[:4]), reason="系列对不上", missing=f"没有「{v}」这个系列", said=v)
        hit += [x for x in got if x not in hit]
    return hit


def levels_of(values: Sequence[str]) -> list[str] | Ask:
    """问题等级（总述「问题等级」）：「A 级」只指 A，「A 级及以上」= A+、A；「未填」可与具体等级同时选。"""
    out: list[str] = []
    for v in values:
        got = enums.level_codes(v)
        if got is None:
            return Ask(f"问题等级「{v}」对不上，等级有 A+、A、B、C。", list(enums.CN_LEVELS), reason="等级对不上",
                       said=v)
        out += [x for x in got if x not in out]
    return out


def enum_codes(fld: str, values: Sequence[str], table: dict[int, str]) -> list[int] | Ask:
    codes: list[int] = []
    for v in values:
        got = enums.code_of(table, v)
        if not got:
            return Ask(f"{fld}「{v}」对不上，可以选：", list(table.values())[:4], reason="取值对不上", said=v)
        codes += got
    return base.unique(codes)


def other_column(f: dict, values: Sequence[str], neg: bool, out: DomainStep, needs: dict[str, str],
                 domain: Domain) -> None:
    """「其他」条件：点名的列先对显示名与术语表；对不上的写「本助手没有『X』这一项」，本域没有的列整域不计入。"""
    said = str(f.get("column") or "")
    key = columns.resolve(said)
    if key is None:
        out.notes.append(f"本助手没有『{said or '这一项'}』这一项")
        return
    if key not in columns.view_columns(domain):
        out.excluded.append(f"{domain.label}没有「{columns.shown(key)}」，{domain.label}未计入")
        return
    out.conds.append({"kind": "contains", "col": key, "values": list(values), "neg": neg})
    out.needs |= {needs[key]} if key in needs else set()
    out.echo.append((columns.shown(key, domain), base.join(values)))


def within(out: DomainStep, ids: Sequence[int]) -> None:
    """在前一步的结果里找。"""
    out.conds.append({"kind": "ids", "values": [int(i) for i in ids]})


# ---------------------------------------------------------------------------- 取数


def _main_filter(dstep: DomainStep) -> dict[str, Any]:
    return {"logic": "AND", "groups": [{"logic": "AND", "conditions": [NOT_DELETED, *dstep.sql]}]}


def _child(table: str, select: Sequence[str], dstep: DomainStep, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    flt = _main_filter(dstep)
    if extra is not None:
        flt["groups"].append(extra)
    return {"source": INFO, "from": {"table": table, "alias": "c"},
            "joins": [{"table": {"table": MAIN, "alias": "m"}, "type": "INNER",
                       "on": [{"left": "c.ProblemId", "right": "m.ID"}]}],
            "select": [f"c.{c}" for c in select], "filter": flt}


def main_spec(dstep: DomainStep) -> dict[str, Any]:
    return {"source": INFO, "from": {"table": MAIN, "alias": "m"}, "select": [f"m.{c}" for c in MAIN_COLUMNS],
            "filter": _main_filter(dstep)}


def specs(dstep: DomainStep) -> dict[str, tuple[dict[str, Any], str | None]]:
    """第一轮的取数（主表与子表，都带主表条件）：名字 → (spec, 翻页主键)。"""
    out: dict[str, tuple[dict[str, Any], str | None]] = {
        "cn_main": (main_spec(dstep), "m.ID"),
        "cn_models": (_child(MODELS, ("ID", "ProblemId", "ProductName", "Series"), dstep), "c.ID"),
    }
    if "steps" in dstep.needs:
        wanted = {"logic": "OR", "conditions": [cond("c.Step", "IN", list(enums.CN_STEPS_NEEDED)),
                                                cond("c.StepStr", "EQ", enums.CN_STEP_RECLASSIFY)]}
        out["cn_steps"] = (_child(STEPS, ("ID", "ProblemId", "Step", "StepStr", "Result", "AddUser", "AddDate"),
                                  dstep, wanted), "c.ID")
    if "state" in dstep.needs:
        out["cn_risk"] = (_child(RISK, ("ID", "ProblemId", "Step", "Status", "UserID"), dstep), "c.ID")
    if "orders" in dstep.needs:
        out["cn_orders"] = (_child(ORDERS, ("ID", "ProblemId", "PartNumber", "PartName"), dstep), "c.ID")
    return out


def task_spec() -> dict[str, Any]:
    """待办任务：两个业务表名、任务状态为「已接受」，再按单 ID 分块（§3、J-P12）。"""
    return {"source": INFO, "from": TASK_TABLE, "select": ["frecID", "ftable", "fuserID", "fstat"],
            "filter": {"logic": "AND", "groups": [{"logic": "AND", "conditions": [
                cond("ftable", "IN", [enums.CN_TASK_EFFECT, enums.CN_TASK_PREVENTION]),
                cond("fstat", "EQ", enums.CN_TASK_ACCEPTED)]}]}}


def _people_of(frames: dict[str, pd.DataFrame], cols: dict[str, Sequence[str]]) -> list[int]:
    return base.int_keys([x for name, names in cols.items() for c in names for x in base.column(frames.get(name), c)])


async def fetch(ctx: Any, dstep: DomainStep, master: MasterData) -> dict[str, pd.DataFrame]:
    """本步国内的全部帧。`TableDenied` 原样抛给调用方（该域改记无权，§14）。

    人员、存货与主数据的帧不带域前缀：三域一起取时由编排拼成一个帧再交沙箱（`turn/execute.py::_frames`）。
    """
    first = specs(dstep)
    frames = dict(zip(first, await asyncio.gather(*(base.fetch_all(ctx, s, k) for s, k in first.values())),
                      strict=True))
    main = frames["cn_main"]
    second: dict[str, Any] = {}
    if "state" in dstep.needs:
        ids = [str(i) for i in base.int_keys(base.column(main, "ID"))]
        second["cn_tasks"] = base.fetch_in(ctx, task_spec(), "frecID", ids)
    if "inventory" in dstep.needs:
        second["inventory"] = base.fetch_in(
            ctx, {"source": INFO, "from": INVENTORY, "select": ["cInvCode", "cInvName", "cInvStd"]},
            "cInvCode", base.unique(str(x).strip() for x in base.column(main, "CInvCode") if x is not None))
    if second:
        frames |= dict(zip(second, await asyncio.gather(*second.values()), strict=True))
    people = base.int_keys([*base.column(main, "RUser"), *base.column(main, "AddUser"),
                            *base.column(frames.get("cn_steps"), "AddUser"),
                            *base.column(frames.get("cn_tasks"), "fuserID"),
                            *base.column(frames.get("cn_risk"), "UserID")])
    frames["employees"] = await base.fetch_in(
        ctx, {"source": INFO, "from": EMPLOYEE, "select": ["ID", "Name", "Unit"]}, "ID", people)
    for name in ("departments", "factories", "vendors"):
        frames[name] = master.frames.get(name, pd.DataFrame())
    return frames


# ---------------------------------------------------------------------------- 单张单详情与按号查单（S4）

OTHER = "CoreINFO.dbo.ZCTracking_OtherOrder"
XB = "CoreINFO.dbo.ZCTracking_XBOrders"
CHECK = "CoreINFO.dbo.ZCTracking_CheckReason"
PINV = "CoreINFO.dbo.ZCTracking_PossibleInvCode"
FIVE = "CoreINFO.dbo.ZCTracking_ProblemFiveWhy"
PHEN = "CoreINFO.dbo.AfterSaleIssueClassPhenomenon"
PREASON = "CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason"
PCLASS = "CoreINFO.dbo.AfterSaleIssueClass"
DOCUMENTS = "info.dbo.DocumentList"
CAR_REPORT = "info.dbo.tbIQCreportOut"

#: 单张单详情另取的主表列：叙述原文与只在详情里给的几项（§13：一次只取要看的那几张单）
DETAIL_COLUMNS = (*MAIN_COLUMNS, "ProblemDesc", "Reason", "Improve", "Measures", "Prevention", "ReasonClassRemark",
                  "Remark", "RConfirm", "DesignUser", "DesignDate", "ZLConfirmResult", "IsChangeOrderV", "OrderVersion",
                  "ReStartScheme", "ReStartSchemeUser", "ReStartExamineUser", "Confirmation")
_DETAIL_CHILDREN: dict[str, tuple[str, tuple[str, ...]]] = {
    "cn_models": (MODELS, ("ID", "ProblemId", "ProductName", "Series")),
    "cn_steps": (STEPS, ("ID", "ProblemId", "Step", "StepStr", "Result", "Opinon", "Measures", "FileUrl", "AddUser",
                         "AddDate")),
    "cn_orders": (ORDERS, ("ID", "ProblemId", "OrderNumber", "PartNumber", "PartName", "IssueDate", "OrderQty",
                           "ReceiptQty", "OnlineQty", "Version")),
    "cn_xb": (XB, ("ID", "ProblemId", "OrderNumber", "InvCode", "InvStd", "Qty", "InQty", "NoQty", "Factory",
                   "Description")),
    "cn_other": (OTHER, ("ID", "ProblemId", "OrderNo", "ProductName", "Qty", "IssuedQty", "IssQty", "FaliaoDate",
                         "ReturnQty", "ReturnType", "ReceivingQty", "TotalinQty", "Factory")),
    "cn_risk": (RISK, ("ID", "ProblemId", "Step", "Status", "UserID")),
    "cn_check": (CHECK, ("ID", "ProblemId", "ClassID", "PhenomenonID", "ReasonID")),
    "cn_pinv": (PINV, ("ID", "ProblemId", "InvCode", "InvName", "InvStd")),
    "cn_five": (FIVE, ("ID", "ProblemId", "Question", "Reason", "Status", "AddUser", "AddDate", "UpdateUser",
                       "UpdateDate")),
}
DOC_COLUMNS = ["ID", "DocumentName", "DocumentRealName", "frecid", "BusinessType", "EffectFlag"]


def documents_spec() -> dict[str, Any]:
    """文档清单：只取没删除的（`EffectFlag = 0`），再按附件 ID 分块。"""
    return {"source": INFO, "from": DOCUMENTS, "select": DOC_COLUMNS,
            "filter": {"logic": "AND", "groups": [{"logic": "AND", "conditions": [cond("EffectFlag", "EQ", 0)]}]}}


#: CAR 报告表取数时被拒（与权限前置不一致）：只当没有 CAR 报告权限，问题单其余内容照常（`privileges.md`「CAR 报告」）
CAR_DENIED = "cn_car_denied"


async def _car_reports(ctx: Any, car_ids: Sequence[int]) -> pd.DataFrame | None:
    try:
        return await base.fetch_in(ctx, {"source": INFO, "from": CAR_REPORT, "select": [
            "fid", "fdesc", "fstep2how1", "fstep2how2", "fstep2how3", "fstep3memo", "fstep4memo", "fstep5memo",
            "fstep6memo"]}, "fid", car_ids)
    except TableDenied as exc:
        logger.warning("factory_issue_table_denied", domain="car_report", error=type(exc).__name__)
        return None


def issue_step(numbers: Sequence[str] = (), ids: Sequence[int] = ()) -> DomainStep:
    """按编号或单 ID 取一张（几张）单。"""
    if ids:
        return DomainStep(domain=DOMAIN, sql=[cond("m.ID", "IN", [int(i) for i in ids])])
    return DomainStep(domain=DOMAIN, sql=[cond("m.Numbers", "IN", list(numbers))])


async def detail_fetch(ctx: Any, dstep: DomainStep, master: MasterData, *, car: bool) -> dict[str, pd.DataFrame]:
    """单张单详情的帧（§6.3 `issue_detail` 一行）：主表含叙述列、全部子表（带主表条件）、待办任务、文档、现象查表、
    人员；有 CAR 报告权限、物料问题且 CAR 报告 ID 有值时才读 CAR 报告（`privileges.md`「CAR 报告」）。"""
    first: dict[str, Any] = {"cn_main": base.fetch(ctx, {**main_spec(dstep), "select": [f"m.{c}" for c in DETAIL_COLUMNS]})}
    for name, (table, select) in _DETAIL_CHILDREN.items():
        first[name] = base.fetch_all(ctx, _child(table, select, dstep), "c.ID")
    frames = dict(zip(first, await asyncio.gather(*first.values()), strict=True))
    main, steps, checks = frames["cn_main"], frames["cn_steps"], frames["cn_check"]
    second: dict[str, Any] = {
        "cn_tasks": base.fetch_in(ctx, task_spec(), "frecID", [str(i) for i in base.int_keys(base.column(main, "ID"))]),
        "inventory": base.fetch_in(ctx, {"source": INFO, "from": INVENTORY, "select": ["cInvCode", "cInvName", "cInvStd"]},
                                   "cInvCode", base.unique(str(x).strip() for x in base.column(main, "CInvCode")
                                                           if x is not None)),
        "documents": base.fetch_in(ctx, documents_spec(), "ID", base.int_keys(base.column(steps, "FileUrl"))),
        "cn_phen": base.fetch_in(ctx, {"source": INFO, "from": PHEN, "select": ["ID", "PhenomenonDesc"]}, "ID",
                                 base.int_keys(base.column(checks, "PhenomenonID"))),
        "cn_preason": base.fetch_in(ctx, {"source": INFO, "from": PREASON, "select": ["ID", "ReasonDesc"]}, "ID",
                                    [i for i in base.int_keys(base.column(checks, "ReasonID")) if i > 0]),
        "cn_pclass": base.fetch_in(ctx, {"source": INFO, "from": PCLASS, "select": ["ID", "TypeName", "ClassName"]}, "ID",
                                   base.int_keys(base.column(checks, "ClassID"))),
    }
    material = enums.code_of(enums.CN_PROBLEM_TYPES, "物料问题")  # 只有物料问题展示 CAR（国内「物料问题专属」）
    car_ids: list[int] = []
    for kind, car_id in zip(base.column(main, "ProblemType"), base.column(main, "CARID"), strict=False):
        if base.int_keys([kind]) == material:
            car_ids += base.int_keys([car_id])
    if car and car_ids:
        second["cn_car"] = _car_reports(ctx, car_ids)
    frames |= dict(zip(second, await asyncio.gather(*second.values()), strict=True))
    if "cn_car" in frames and frames["cn_car"] is None:
        del frames["cn_car"]
        frames[CAR_DENIED] = pd.DataFrame()
    people = _people_of(frames, {"cn_main": ("RUser", "AddUser", "DesignUser", "ReStartSchemeUser", "ReStartExamineUser"),
                                 "cn_steps": ("AddUser",), "cn_tasks": ("fuserID",), "cn_risk": ("UserID",),
                                 "cn_five": ("AddUser", "UpdateUser")})
    frames["employees"] = await base.fetch_in(
        ctx, {"source": INFO, "from": EMPLOYEE, "select": ["ID", "Name", "Unit"]}, "ID", people)
    for name in ("departments", "factories", "vendors"):
        frames[name] = master.frames.get(name, pd.DataFrame())
    return frames


def _any_of(conds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"logic": "OR", "conditions": conds}


async def lookup_fetch(ctx: Any, lookups: Sequence[Any], master: MasterData) -> dict[str, pd.DataFrame]:
    """按号查单（§6.3 `lookup_numbers` 一行）：先按号在主表编号、CAR 编号、料号与生产订单、小板订单上精确匹配，再按
    对上的单 ID 取清单那一套帧（不取叙述原文，§6.1）。手填的带连字符的订单号一起取出来（以「该号-」开头）。"""
    by: dict[str, list[str]] = {}
    for lk in lookups:
        by.setdefault(lk.kind, []).append(lk.value)
    frames: dict[str, pd.DataFrame] = {}
    tasks: dict[str, Any] = {}
    main_conds = [cond(f"m.{col}", "IN", by[kind]) for kind, col in (("issue", "Numbers"), ("car", "CAR"),
                                                                     ("inv", "CInvCode")) if by.get(kind)]
    if main_conds:
        spec = main_spec(DomainStep(domain=DOMAIN))
        spec["select"] = ["m.ID"]
        spec["filter"]["groups"].append(_any_of(main_conds))
        tasks["cn_hit_main"] = base.fetch_all(ctx, spec, "m.ID")
    order_conds = [cond("c.OrderNumber", "IN", by["prod_order"])] if by.get("prod_order") else []
    order_conds += [cond("c.OrderNumber", "STARTS_WITH", v + "-") for v in by.get("prod_order", [])
                    if re.fullmatch(r"\d{6}", v)]
    order_conds += [cond("c.PartNumber", "IN", by["pn_code"])] if by.get("pn_code") else []
    order_conds += [cond("c.PartName", "IN", by["pn_name"])] if by.get("pn_name") else []
    if order_conds:
        tasks["cn_hit_orders"] = base.fetch_all(ctx, _child(ORDERS, ("ID", "ProblemId", "OrderNumber", "PartNumber",
                                                                     "PartName", "OrderQty"), DomainStep(domain=DOMAIN),
                                                            _any_of(order_conds)), "c.ID")
    if by.get("xb_order"):
        tasks["cn_hit_xb"] = base.fetch_all(ctx, _child(XB, ("ID", "ProblemId", "OrderNumber", "InvCode", "InvStd", "Qty"),
                                                        DomainStep(domain=DOMAIN),
                                                        _any_of([cond("c.OrderNumber", "IN", by["xb_order"])])), "c.ID")
    frames |= dict(zip(tasks, await asyncio.gather(*tasks.values()), strict=True))
    ids = base.int_keys([*base.column(frames.get("cn_hit_main"), "ID"),
                         *base.column(frames.get("cn_hit_orders"), "ProblemId"),
                         *base.column(frames.get("cn_hit_xb"), "ProblemId")])
    if ids:
        dstep = DomainStep(domain=DOMAIN, sql=[cond("m.ID", "IN", ids)] if len(ids) <= base.IN_CHUNK else [],
                           needs={"state"})
        frames |= await fetch(ctx, dstep, master)
    return frames
