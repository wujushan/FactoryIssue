"""按条件列清单（设计 §4.3 清单一行、§6.3、§9.2；总述「清单默认列」「跨域规则」清单呈现）。

事件顺序：`delta`（开头：各域张数与合计、无权的域、「按 X 理解」）→ 每域一个 `table` → `delta`（分析）→ 统计口径
（整轮合并，放最后）→ 导出链接（S5：用户明说导出，或某域超过导出阈值时，`turn/execute.py::_export_lists`）。
问题描述摘要随 S6（在那之前文字查找不可用，问题描述一列写「暂不可用」）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from factory_issue_module.config.files import AnswerParams
from factory_issue_module.declarations import Domain
from factory_issue_module.domains import enums
from factory_issue_module.plan import schema
from factory_issue_module.present import columns

#: 用户没点名列时，条件对应的列加在默认 6 列后面（看得到按什么筛的）
_FILTER_COLUMNS = {
    "加工厂": ["factory"], "系列": ["series"], "物料名称": ["inv_name"], "料号": ["inv_code"], "供应商": ["ven_name"],
    "问题等级": ["level"], "跟进部门": ["follow_dept"], "跟进人": ["follower"],
    "当前责任人": ["current_state", "current_people"], "责任人": ["responsible"], "责任归属部门": ["resp_dept"],
    "产品在制属性": ["output_status"], "影响数量": ["impact_qty"], "发现工位": ["station"],
    "是否设计变更": ["design_change"], "IQC意见": ["iqc_opinion"], "原因分类": ["reason_class"],
    "处理结果": ["design_result"], "国内工厂": ["cn_factory"], "是否需要回复8D": ["need_8d"], "PN": ["pn"],
}
_BASIS_COLUMNS = {"现场发现": ["found_date"], "停线": ["stop_status", "stop_date"], "重启": ["restart_date"],
                  "结案": ["close_time"]}
_SORT_COLUMNS = {"现场发现日期": "found_date", "停线日期": "stop_date", "结案时间": "close_time", "影响数量": "impact_qty"}
_STOP_KINDS = ("停线中", "曾经停线", "已经重启", "重启审核通过", "重启审核中", "责任人填写重启方案", "没有停线")


def _status_columns(step: dict) -> list[str]:
    out: list[str] = []
    for f in schema.as_list((step.get("params") or {}).get("filters")):
        if not isinstance(f, dict) or f.get("field") != "状态":
            continue
        for v in schema.as_list(f.get("value")):
            kind = (enums.status_kind(v) or enums.status_kind(v, enums.BR_STAGES)
                    or enums.status_kind(v, enums.OS_STAGES))
            if kind is None:
                continue
            out += ["stop_status", "stop_date"] if kind[0] in _STOP_KINDS else [STATE_FOR_FILTER]
    return out


#: 按状态筛时加的那一列：国内是当前状态（环节 + 人），巴西、海外是主表状态（各适配器的 `KEY_ALIAS` 换成实际的列）
STATE_FOR_FILTER = "state_for_filter"


def columns_for(step: dict) -> tuple[list[str], list[str]]:
    """(列的内部键, 用户点名了、本助手没有的项)。问题编号总在第一列（业务标识给全）。"""
    p = step.get("params") or {}
    missing: list[str] = []

    def pick(items: Any) -> list[str]:
        keys = []
        for said in schema.as_list(items):
            key = columns.resolve(str(said))
            if key is None:
                missing.append(str(said))
            elif key not in keys:
                keys.append(key)
        return keys

    if p.get("columns"):
        keys = pick(p["columns"])
    else:
        keys = list(columns.DEFAULT_LIST)
        for f in schema.as_list(p.get("filters")):
            if isinstance(f, dict):
                keys += _FILTER_COLUMNS.get(str(f.get("field")), [])
                if f.get("field") == "其他" and columns.resolve(str(f.get("column") or "")) is not None:
                    keys.append(str(columns.resolve(str(f.get("column") or ""))))
        keys += _status_columns(step)
        for t in schema.as_list(p.get("time")):
            if isinstance(t, dict):
                keys += _BASIS_COLUMNS.get(str(t.get("basis") or "建单"), [])
        sort = p.get("sort") if isinstance(p.get("sort"), dict) else {}
        if sort.get("by") in _SORT_COLUMNS:
            keys.append(_SORT_COLUMNS[sort["by"]])
    keys += pick(p.get("add_columns"))
    keys = list(dict.fromkeys(["number", *keys]))
    return keys, missing


def domain_keys(keys: Sequence[str], domain: Domain, alias: dict[str, list[str] | None]) -> tuple[list[str], list[str]]:
    """通用的列 → 本域的列与本域没有的项（总述「跨域规则」：用户点名的列某域可能没有）。

    `alias` 是适配器的 `KEY_ALIAS`：巴西只说「责任人」给问题跟进人，海外同时给当前责任人与问题跟进人；没有责任归属
    部门的按问题跟进部门。本域没有的列不放进表格，开头写一句「巴西没有『当前状态』这一项」。
    """
    have = columns.view_columns(domain)
    out: list[str] = []
    absent: list[str] = []
    for k in keys:
        if k == STATE_FOR_FILTER:
            got = alias.get(k) or ["current_state"]
            out += [x for x in got if x in have and x not in out]
            continue
        for x in alias.get(k, [k]) or []:
            if x in have and x not in out:
                out.append(x)
            elif x not in have and k not in absent:
                absent.append(k)
    return out, [columns.shown(k) for k in absent]


def needs(keys: Sequence[str], step: dict, column_needs: dict[str, str], sort_needs: dict[str, str]) -> set[str]:
    out = {column_needs[k] for k in keys if k in column_needs}
    sort = (step.get("params") or {}).get("sort")
    if isinstance(sort, dict) and sort.get("by") in sort_needs:
        out.add(sort_needs[sort["by"]])
    return out


def params(step: dict, keys_by_domain: dict[str, list[str]], answer: AnswerParams) -> dict[str, Any]:
    p = step.get("params") or {}
    sort = p.get("sort") if isinstance(p.get("sort"), dict) else {}
    limit = p.get("limit") if isinstance(p.get("limit"), int) and not isinstance(p.get("limit"), bool) else None
    return {"columns": {label: list(keys) for label, keys in keys_by_domain.items()}, "table_rows": answer.table_rows,
            "sort_by": sort.get("by"), "desc": sort.get("order", "降序") != "升序", "limit": limit,
            # 导出（§9.3）：用户明说「导出」「全部给我」时不论多少都导出；否则某域超过阈值才导出
            "export": p.get("export") is True, "export_threshold": answer.export_threshold}


def no_conditions(step: dict) -> bool:
    """不带任何条件的清单（「帮我查下制程问题」）：计划里没有域、时间、条件（§9.5）。"""
    p = step.get("params") or {}
    return not (p.get("domains") or p.get("time") or p.get("filters") or p.get("within"))


_DATE_SORTS = ("建单时间", "现场发现日期", "停线日期", "结案时间")


def order_text(step: dict) -> str | None:
    """表格是按什么排的：默认（建单时间从新到旧）返回 None，开头说「最近 N 张」；其余写出排序。"""
    sort = (step.get("params") or {}).get("sort")
    if not isinstance(sort, dict) or not sort.get("by"):
        return None
    by, asc = str(sort["by"]), sort.get("order") == "升序"
    if by == "建单时间" and not asc:
        return None
    if by in _DATE_SORTS:
        return f"按{by}从{'旧到新' if asc else '新到旧'}"
    return f"按{by}从{'低到高' if asc else '高到低'}"


def opening(seg: dict[str, Any], label: str, scope: str, order: str | None = None) -> str:
    """开头一句：张数与表格列了几张（数都来自沙箱）。不是按建单时间倒序时不说「最近」。"""
    text = f"{label}{scope}共 {seg.get('found', 0)} 张"
    if seg.get("limited"):
        text += f"，按要求列出前 {seg.get('listed', 0)} 张"
    if seg.get("truncated"):
        text += (f"，表格列出最近 {seg.get('shown', 0)} 张" if order is None
                 else f"，表格{order}列出前 {seg.get('shown', 0)} 张")
    return text


def domain_counts(by_domain: Sequence[Sequence[Any]]) -> str:
    """「国内 3 张、巴西 1 张、海外 0 张」（张数来自沙箱）。"""
    return "、".join(f"{d} {n} 张" for d, n in by_domain)


def cross_opening(res: dict[str, Any], scope: str) -> str:
    """三域一起列清单时开头一句：各域张数与合计（总述「跨域规则」清单呈现）。"""
    by_domain = res.get("by_domain") or []
    labels = "、".join(str(d) for d, _n in by_domain)
    return f"{labels}{scope}合计 {res.get('found_total', 0)} 张：{domain_counts(by_domain)}。"


def fallback(facts: dict[str, Any]) -> str:
    """分析段核数两次都不过时的模板句（数字取自沙箱的 facts）。"""
    if "各域张数" in facts:
        return f"合计 {facts.get('合计张数', 0)} 张：{domain_counts(facts['各域张数'])}。"
    text = f"共 {facts.get('张数', 0)} 张"
    types = facts.get("按问题类型") or []
    if types:
        text += f"，最多的问题类型是{types[0][0]}（{types[0][1]} 张）"
    if facts.get("未结案"):
        text += f"，其中未结案 {facts['未结案']} 张"
    return text + "。"
