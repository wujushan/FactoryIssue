"""国内适配器（设计 §6.2、§6.3、§6.5；国内业务描述「口径」「关联」）。

- 第 6 步：把计划里的条件（照抄的用户说法）对到库里的取值与代码，换算时间，写成两份：落在主表列上的条件进
  SQL（`fetch` 的 FilterCondition），要派生才知道的（状态、当前责任人、责任人、责任归属部门、机型、系列、物料名称、
  PN、建单以外的日期）交沙箱。对不上、对上多个、重名、枚举说法对不上时返回追问（`base.Ask`），本轮不取数。
- 取数：主表一帧，机型、处理步骤、风险订单流程、生产订单按需各一帧（子表 INNER JOIN 主表，带主表的条件），
  再按收集到的键取待办任务、存货、人员。不取叙述原文（§6.1）。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from factory_issue_module import landed
from factory_issue_module.config.files import NameTable
from factory_issue_module.declarations import INFO, TASK_TABLE, Domain
from factory_issue_module.domains import base, enums
from factory_issue_module.domains.base import Ask, DomainStep, cond
from factory_issue_module.domains.shared import KIND_MACHINE, KIND_PERSON, MasterData
from factory_issue_module.plan import names, schema
from factory_issue_module.plan.timespan import Span
from factory_issue_module.present import columns

DOMAIN = Domain.DOMESTIC
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
    }


# ---------------------------------------------------------------------------- 分组维度

_PERIOD_COL = {"建单": "_add", "现场发现": "_found", "停线": "_stop", "重启": "_restart", "结案": "_close"}
PERIOD_DIMS = ("年", "季度", "月", "周")


def dims(group_by: Sequence[str], basis: str | None) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """计划的分组维度 → 沙箱的维度说明；返回 (维度, 国内没有的维度, 要额外取的帧)。"""
    s = columns.shown
    table: dict[str, dict[str, Any]] = {
        "域": {"const": DOMAIN.label, "title": columns.DOMAIN},
        "问题类型": {"col": "type", "title": s("type")},
        "机型": {"col": "_machines", "multi": True, "empty": "未填", "title": s("machine")},
        "系列": {"col": "_series", "multi": True, "empty": "未填", "title": s("series")},
        "加工厂": {"col": "factory", "title": s("factory")},
        "结案与否": {"col": "_closed_label", "title": columns.CLOSED_OR_NOT},
        "处理环节": {"col": "_stages", "multi": True, "title": columns.STAGE},
        "问题等级": {"col": "level", "keep_blank": True, "order": [*enums.CN_LEVELS, "未填"], "title": s("level")},
        "跟进部门": {"col": "follow_dept", "title": s("follow_dept")},
        "跟进人": {"col": "follower", "title": s("follower")},
        "当前责任人": {"col": "_current_names", "multi": True, "title": s("current_people")},
        "责任人": {"col": "responsible", "title": s("responsible")},
        "责任归属部门": {"col": "_resp_dept_names", "multi": True, "title": s("resp_dept")},
        "原因分类": {"col": "reason_class", "keep_blank": True, "title": s("reason_class")},
        "处理结果": {"col": "design_result", "keep_blank": True, "title": s("design_result")},
        "产品在制属性": {"col": "output_status", "keep_blank": True, "title": s("output_status")},
        "停线状态": {"col": "stop_status", "keep_blank": True, "title": s("stop_status")},
        "状态": {"col": "status", "title": s("status")},
    }
    needs_by = {"处理环节": "state", "当前责任人": "state", "责任人": "steps"}
    out: list[dict[str, Any]] = []
    missing: list[str] = []
    needs: set[str] = set()
    for g in group_by:
        if g in PERIOD_DIMS:
            col = _PERIOD_COL.get(basis or "建单", "_add")
            out.append({"name": g, "period": g, "period_col": col, "title": g})
            if col in ("_restart", "_close"):
                needs.add("steps")
        elif g in table:
            out.append({"name": g, **table[g]})
            if g in needs_by:
                needs.add(needs_by[g])
        else:
            missing.append(g)
    return out, missing, needs


#: 列（清单）与指标、排序要额外取的帧
COLUMN_NEEDS = {"current_state": "state", "current_people": "state", "responsible": "steps",
                "close_time": "steps", "restart_date": "steps", "inv_name": "inventory", "inv_std": "inventory"}
METRIC_NEEDS = {"结案周期": "steps", "停线时长": "steps"}
SORT_NEEDS = {"结案时间": "steps"}
#: 国内没有的指标（巴西才有）
METRICS_ELSEWHERE = ("费用美元", "费用雷亚尔", "扣款")


# ---------------------------------------------------------------------------- 第 6 步：条件对库


@dataclass
class Resolver:
    master: MasterData
    dept_aliases: NameTable | None
    regions: NameTable | None
    entities: Mapping[str, Sequence[str]]
    today: date
    #: 前一步给的引用值（已经是库里的名字），按「步骤.输出名」
    refs: Mapping[str, Any] = field(default_factory=dict)


#: 条件 → 对库要用的主数据（`MasterData.failed` 里的名字）
_MASTER_OF = {"机型": "models", "系列": "models", "加工厂": "factories", "供应商": "suppliers", "跟进部门": "departments",
              "责任归属部门": "departments", "跟进人": "people", "当前责任人": "people", "责任人": "people"}


def _values(v: Any) -> list[str]:
    items = v if isinstance(v, list) else [v]
    return [str(x).strip() for x in items if x is not None and not isinstance(x, dict) and str(x).strip()]


def _join(items: Sequence[str]) -> str:
    return "、".join(items)


def _not_found(kind: str, said: str, R: Resolver, skip: str | None) -> Ask:
    return Ask(f"没有找到{kind}「{said}」，请核对名称。", names.check_options(said, R.entities, skip=skip))


def _yes_no(said: str) -> int | None:
    k = names.key(said)
    if k in ("是", "需要", "有", "要"):
        return 1
    if k in ("否", "不需要", "没有", "无", "不"):
        return 0
    return None


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_SQL_OPS = {"eq": "EQ", "ne": "NE", "gt": "GT", "lt": "LT", "ge": "GE", "le": "LE"}


def _numbers(values: Sequence[str]) -> list[float]:
    """数值条件的取值（「100%」→ 100）：参数换算，不产生给用户的数。"""
    out: list[float] = []
    for v in values:
        out += [float(x) for x in _NUMBER.findall(v)]
    return out


def _people(said: str, R: Resolver) -> list[int] | Ask:
    """姓名 → 员工 ID。重名时追问「是哪个部门的这位」；「生产工程部的张三」按部门挑。"""
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
        return Ask(f"没有找到人员「{said}」，请核对姓名。", names.check_options(said, R.entities, skip=KIND_PERSON))
    depts = base.unique(p.dept for p in hits)
    if len(depts) > 1:
        options = names.person_options([(p.name, p.dept) for p in hits])
        return Ask(f"「{said}」有几位同名的，是哪个部门的这位？", options, reason="重名")
    return [p.id for p in hits]


def _types_elsewhere() -> dict[str, tuple[str, ...]]:
    return landed.problem_types()


def _span_bounds(span: Span) -> tuple[date | None, date | None]:
    if span.unlimited:
        return None, None
    return span.start, span.end


def period_label(span: Span) -> str:
    """比较两个时段时每段的叫法：整年「2025 年全年」、整月「2026 年 9 月」，其余写起止日期。"""
    start, end = span.start, span.end
    if start and end and not span.to_today:
        if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31 and start.year == end.year:
            return f"{start.year} 年全年"
        nxt = date(end.year + (end.month == 12), end.month % 12 + 1, 1)
        if start.day == 1 and start.year == end.year and start.month == end.month and end + timedelta(days=1) == nxt:
            return f"{start.year} 年 {start.month} 月"
    return span.describe()


def _time_conditions(step: dict, spans: Sequence[Span], out: DomainStep, compare: bool) -> None:
    items = [t for t in schema.as_list((step.get("params") or {}).get("time")) if isinstance(t, dict) and t.get("said")]
    periods: list[tuple[Span, dict[str, Any]]] = []
    seen: set[tuple[str, Span]] = set()
    for t, span in zip(items, spans, strict=False):
        basis = str(t.get("basis") or "建单")
        if not compare:
            # 同一依据的几项已合成同一段（`timespan._intersect_same_basis`），条件只写一次
            if (basis, span) in seen:
                continue
            seen.add((basis, span))
        if basis == "统计日期":
            out.skipped.append("国内没有统计日期，按统计日期筛时国内未计入")
            continue
        start, end = _span_bounds(span)
        cond_t = {"basis": basis, "start": start.isoformat() if start else None,
                  "end": end.isoformat() if end else None}
        if basis in ("结案", "重启"):
            out.needs.add("steps")
        if compare:
            periods.append((span, cond_t))
            continue
        if start is None and end is None:
            continue
        if basis == "建单":
            if span.relative() is not None:
                out.sql.append(cond("m.AddDate", "GE", span.relative()))
            elif start is not None:
                out.sql.append(cond("m.AddDate", "GE", datetime(start.year, start.month, start.day)))
            if end is not None and span.relative() is None:
                nxt = end + timedelta(days=1)
                out.sql.append(cond("m.AddDate", "LT", datetime(nxt.year, nxt.month, nxt.day)))
        else:
            out.times.append(cond_t)
    if compare and len(periods) >= 2:
        ordered = sorted(periods[:2], key=lambda p: p[0].start or date.min)
        out.compare = [{"label": period_label(sp), "times": [c]} for sp, c in ordered]


def resolve(step: dict, spans: Sequence[Span], R: Resolver) -> DomainStep | Ask:
    """一步在国内的条件（第 6 步）。"""
    out = DomainStep(domain=DOMAIN)
    p = step.get("params") or {}
    _time_conditions(step, spans, out, compare=p.get("compare") == "时段")
    m = R.master
    for f in schema.as_list(p.get("filters")):
        if not isinstance(f, dict):
            continue
        fld = str(f.get("field") or "")
        kind = schema.OP_KINDS.get(str(f.get("op") or "是"), "eq")
        neg = kind in ("ne", "nhas")
        raw = f.get("value")
        values = _values(R.refs.get(raw["ref"], []) if schema.is_ref(raw) else raw)
        if not values:
            continue
        if _MASTER_OF.get(fld) in m.failed:
            out.unavailable = True
            continue
        shown = _join(values)
        if fld == "机型":
            hit: list[str] = []
            for v in values:
                got = names.machines(v, m.machines, each=kind == "has")
                if not got:
                    return _not_found("机型", v, R, KIND_MACHINE)
                hit += [x for x in got if x not in hit]
            if kind == "has":
                out.notes.append(f"按以下机型统计：{_join(hit)}")
            out.conds.append({"kind": "any_of", "col": "_machines", "values": hit, "neg": neg})
            out.echo.append(("机型", _join(hit)))
        elif fld == "系列":
            hit = []
            for v in values:
                got = list(names.series(v, m.series))
                if not got:
                    machine = names.machines(re.sub(r"系列$", "", v), m.machines)
                    tip = f"「{machine[0]}」是机型，属于{m.machine_series[machine[0]]}。" if (
                        machine and machine[0] in m.machine_series) else ""
                    return Ask(f"没有找到「{v}」这个系列。{tip}可选的系列有：{_join(m.series[:12])}。",
                               list(m.series[:4]), reason="系列对不上")
                hit += [x for x in got if x not in hit]
            out.conds.append({"kind": "any_of", "col": "_series", "values": hit, "neg": neg})
            out.echo.append(("系列", _join(hit)))
        elif fld == "加工厂":
            hit = []
            for v in values:
                got = list(names.factories(v, m.factory_names(), R.regions))
                if not got:
                    return _not_found("加工厂", v, R, None)
                if len(got) > 1:
                    return Ask(f"「{v}」对上了这几家工厂：{_join(got)}。按哪几家查？", [_join(got), *got][:4],
                               reason="多工厂")
                hit += [x for x in got if x not in hit]
            codes = m.factory_codes(hit)
            out.sql.append(cond("m.Factory", "NOT_IN" if neg else "IN", codes))
            out.echo.append(("加工厂", _join(hit)))
        elif fld == "国内工厂":
            out.skipped.append("「国内工厂」只是海外单上的一列，国内单按加工厂查")
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
            hit = []
            pool = m.supplier_names()
            for v in values:
                got = [n for n in pool if names.key(n) == names.key(v)] or \
                      [n for n in pool if names.key(v) and names.key(v) in names.key(n)]
                if not got:
                    return _not_found("供应商", v, R, None)
                if len(got) > 1:
                    return Ask(f"「{v}」对上了这几家供应商：{_join(got[:12])}。查哪一家？", got[:4], reason="多供应商")
                hit += [x for x in got if x not in hit]
            out.sql.append(cond("m.VenCode", "NOT_IN" if neg else "IN", m.supplier_codes(hit)))
            out.echo.append(("供应商", _join(hit)))
        elif fld == "问题类型":
            codes: list[int] = []
            for v in values:
                got = enums.code_of(enums.CN_PROBLEM_TYPES, v)
                if not got and v.endswith("类"):
                    got = enums.code_of(enums.CN_PROBLEM_TYPES, v[:-1])
                if got:
                    codes += got
                elif v in _types_elsewhere():
                    out.skipped.append(f"国内无「{v}」类型，未计入")
                else:
                    return Ask(f"没有「{v}」这个问题类型，国内的问题类型有：{_join(enums.CN_PROBLEM_TYPES.values())}。",
                               list(enums.CN_PROBLEM_TYPES.values())[:4], reason="类型对不上")
            if codes:
                out.sql.append(cond("m.ProblemType", "NOT_IN" if neg else "IN", base.unique(codes)))
                out.echo.append(("问题类型", _join(enums.CN_PROBLEM_TYPES[c] for c in base.unique(codes))))
            elif not neg:
                out.skipped.append("国内没有这些问题类型")
        elif fld == "问题等级":
            levels: list[str] = []
            for v in values:
                got = enums.level_codes(v)
                if got is None:
                    return Ask(f"问题等级「{v}」对不上，等级有 A+、A、B、C。", list(enums.CN_LEVELS), reason="等级对不上")
                levels += [x for x in got if x not in levels]
            # 「未填」与具体等级可以同时选，按展示文字在沙箱里比（等级的空值有 NULL 与空串两种）
            out.conds.append({"kind": "in", "col": "level", "values": levels, "neg": neg})
            out.echo.append(("问题等级", _join(levels)))
        elif fld == "状态":
            items: list[list[str]] = []
            for v in values:
                got = enums.status_kind(v)
                if got is None:
                    return Ask(f"「{v}」这个状态对不上，可以选：", enums.status_options(), reason="状态对不上")
                items.append([got[0], got[1]])
                if got[0] == "环节":
                    out.needs.add("state")
            out.conds.append({"kind": "status", "items": items, "neg": neg})
            out.echo.append(("状态", shown))
        elif fld in ("跟进部门", "责任归属部门"):
            hit = []
            for v in values:
                got = list(names.departments(v, m.dept_names(), R.dept_aliases))
                if not got:
                    return _not_found("部门", v, R, None)
                hit += [x for x in got if x not in hit]
            several = len(hit) > len(values) and not neg
            ids = m.dept_ids(hit)
            if fld == "跟进部门":
                out.sql.append(cond("m.RDepartment", "NOT_IN" if neg else "IN", ids))
                out.echo.append(("问题跟进部门", _join(hit)))
                if several:
                    out.breakdowns.append({"title": columns.shown("follow_dept"), "col": "follow_dept",
                                           "multi": False, "values": hit})
            else:
                if several:
                    out.breakdowns.append({"title": columns.shown("resp_dept"), "col": "_resp_dept_names",
                                           "multi": True, "values": hit})
                out.conds.append({"kind": "any_of", "col": "_resp_dept_ids", "values": ids, "neg": neg})
                out.conds.append({"kind": "flag", "col": "_resp_material", "value": False})
                out.echo.append(("责任归属部门", _join(hit)))
        elif fld in ("跟进人", "当前责任人", "责任人"):
            ids_all: list[int] = []
            for v in values:
                got = _people(v, R)
                if isinstance(got, Ask):
                    return got
                ids_all += got
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
            got_codes: list[int] = []
            for v in values:
                got = enums.code_of(table, v)
                if not got:
                    return Ask(f"{fld}「{v}」对不上，可以选：", list(table.values())[:4], reason="取值对不上")
                got_codes += got
            out.sql.append(cond(column, "NOT_IN" if neg else "IN", base.unique(got_codes)))
            out.echo.append((fld, shown))
        elif fld in ("不良率", "不良数量", "影响数量"):
            column = {"不良率": "m.Rate", "不良数量": "m.BadQty", "影响数量": "m.ImpactQty"}[fld]
            nums = _numbers(values)
            if kind == "between" and len(nums) >= 2:
                out.sql.append(cond(column, "GE", nums[0]))
                out.sql.append(cond(column, "LE", nums[1]))
            elif nums and kind in _SQL_OPS:
                out.sql.append(cond(column, _SQL_OPS[kind], nums[0]))
            else:
                out.notes.append(f"「{fld}{shown}」没能换成数值条件，未按它筛")
                continue
            out.echo.append((fld, f"{f.get('op') or '是'} {shown}"))
        elif fld == "发现工位":
            for v in values:
                out.sql.append(cond("m.Station", "NOT_CONTAINS" if neg else "CONTAINS", v, include_nulls=neg))
            out.echo.append(("发现工位包含", shown))
        elif fld == "是否设计变更":
            yn = _yes_no(values[0])
            if yn is None:
                return Ask("是否设计变更，选「是」还是「否」？", ["是", "否"], reason="取值对不上")
            if neg:
                yn = 1 - yn
            out.sql.append(cond("m.IsDesignChange", "EQ", yn))
            out.echo.append(("是否设计变更", "是" if yn else "否"))
        elif fld == "原因分类":
            out.conds.append({"kind": "contains", "col": "reason_class", "values": values, "neg": neg})
            out.echo.append(("原因分类", shown))
        elif fld == "是否需要回复8D":
            out.skipped.append("国内没有「是否需要回复 8D」，按它筛时国内未计入")
        elif fld == "其他":
            key = columns.resolve(str(f.get("column") or ""))
            if key is None:
                out.notes.append(f"本助手没有『{f.get('column') or '这一项'}』这一项")
                continue
            out.conds.append({"kind": "contains", "col": key, "values": values, "neg": neg})
            out.needs |= {COLUMN_NEEDS[key]} if key in COLUMN_NEEDS else set()
            out.echo.append((columns.shown(key), shown))
    return out


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


async def fetch(ctx: Any, dstep: DomainStep, master: MasterData) -> dict[str, pd.DataFrame]:
    """本步国内的全部帧。`TableDenied` 原样抛给调用方（该域改记无权，§14）。"""
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
