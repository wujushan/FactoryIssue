"""巴西派生（设计 §6.2；巴西业务描述「口径」「关联」、处理过程表与费用表的「按单汇总」）。

输入是本步取回的巴西各帧（主表、处理过程、费用明细、关联申请单、申请单、PN 主数据、人员、部门、产品、存货、
供应商），输出与国内同一套辅助列的「一单一行」视图（列表见 `views.py` 开头）。展示列用内部键
（`present/columns.py::BR_VIEW_COLUMNS` 再换成显示名）。

- 处理过程只取最新一条（`ID` 最大）：问题跟进人、问题跟进部门（跟进人现在所在的部门）、结案日期、扣款都从它来；
  还没有处理过程的单跟进人、跟进部门写「未指定」，按人、按部门统计时不计入。
- 不良率现算：不良数量 × 100 ÷ 影响数量，保留 2 位；影响数量为 0 时 0.00%，为空时「未填」。
- 费用按单汇总：美元、雷亚尔各自合计（空值按 0）；「涉及费用」= 两者有一个大于 0。
- 大机型、加工厂逗号多值，逐段去首尾空格；PN 编码为「0」的是占位值，不算。
- 未结案不含待提交、已终止（`_unclosed`）；`_closed_label` 把这两种另列。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import (
    fi_blank,
    fi_day,
    fi_group,
    fi_ids,
    fi_int,
    fi_lookup,
    fi_num,
    fi_records,
    fi_round,
    fi_show,
    fi_split,
    fi_text_date,
    fi_ts,
    fi_unique,
)


def br_enums(raw):
    """参数里的枚举（JSON 的键是字符串）→ 整数键。"""
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[k] = {int(c): x for c, x in v.items()}
        else:
            out[k] = v
    return out


def br_type(raw):
    """问题类型：「其他|备注」显示「其他」，备注进「其他问题说明」；空（只有草稿）为「未填」。"""
    if fi_blank(raw):
        return "未填", "未填"
    text = str(raw).strip()
    if text.startswith("其他"):
        head, sep, rest = text.partition("|")
        if head.strip() == "其他":
            return "其他", rest.strip() if sep and rest.strip() else "未填"
    return text, "未填"


def br_rate(bad, impact):
    """（数值, 展示文字）：影响数量为 0 时 0.00%；影响数量或不良数量为空时算不出，「未填」。"""
    if impact is None:
        return None, "未填"
    if impact == 0:
        return 0.0, "0.00%"
    if bad is None:
        return None, "未填"
    value = fi_round(bad * 100 / impact, 2)
    return value, f"{value:.2f}%"


def br_latest(records):
    """同一单的处理过程里 `ID` 最大的一条。"""
    if not records:
        return None
    return max(records, key=lambda r: fi_int(r.get("ID")) or 0)


def br_money(v):
    x = fi_num(v)
    return 0.0 if x is None else x


def br_view(data, E, desc_text):
    """巴西「一单一行」视图。`desc_text` 是问题描述一列（S6 之前、文字查找不可用时为「暂不可用」）。"""
    main = data.get("br_main")
    if main is None:
        return pd.DataFrame()
    employees = data.get("employees")
    names = fi_lookup(employees, "ID", "Name", cast="int")
    units = {k: fi_int(v) for k, v in fi_lookup(employees, "ID", "Unit", cast="int").items()}
    depts = fi_lookup(data.get("departments"), "ID", "Name", cast="int")
    product_names = fi_lookup(data.get("products"), "ID", "ProductName", cast="int")
    product_series = fi_lookup(data.get("products"), "ID", "Series", cast="int")
    inv_names = fi_lookup(data.get("inventory"), "cInvCode", "cInvName")
    inv_stds = fi_lookup(data.get("inventory"), "cInvCode", "cInvStd")
    vendors = fi_lookup(data.get("vendors"), "ferpcode", "fname")
    pn_names = fi_lookup(data.get("pns"), "PartNumber", "Name")
    request_pn = fi_lookup(data.get("br_requests"), "ID", "PartNumber", cast="int")
    process = fi_group(fi_records(data.get("br_process")), "ProblemID")
    costs = fi_group(fi_records(data.get("br_cost")), "ProblemID")
    pos = fi_group(fi_records(data.get("br_po")), "ProblemID")
    status = E["status"]
    rows = []
    for r in fi_records(main):
        pid = fi_int(r.get("ID"))
        s = fi_int(r.get("Status"))
        done = s == E["done"]
        unclosed = s in E["unclosed"]
        if done:
            closed_label = "已结案"
        elif s == E["draft"]:
            closed_label = status.get(E["draft"], "待提交")
        elif s == E["terminated"]:
            closed_label = status.get(E["terminated"], "已终止")
        else:
            closed_label = "未结案"
        type_show, other_desc = br_type(r.get("ProblemType"))
        latest = br_latest(process.get(pid, []))
        follower_id = fi_int(latest.get("ProcessUserID")) if latest else None
        if latest is None:
            follower, follow_dept, follower_group, dept_group = "未指定", "未指定", None, None
            dept_id = None
        else:
            follower = names.get(follower_id, "未填")
            dept_id = units.get(follower_id)
            follow_dept = depts.get(dept_id, "未填")
            follower_group = names.get(follower_id)
            dept_group = depts.get(dept_id)
        segs = fi_ids(r.get("ProductIDAll"))
        machines = fi_unique([product_names[i] for i in segs if i in product_names])
        series = fi_unique([product_series[i] for i in segs if i in product_series])
        if machines:
            machine_text = "、".join(machines)
        else:
            machine_text = "未识别机型" if segs else "未填"
        factories = fi_unique(fi_split(r.get("BrazilFactory")))
        pn_codes = fi_unique([str(request_pn.get(fi_int(p.get("RequestID")))).strip()
                              for p in pos.get(pid, []) if fi_int(p.get("RequestID")) in request_pn])
        pn_codes = [c for c in pn_codes if c and c != "0"]
        pn_named = [c for c in pn_codes if c in pn_names]
        pn_text = "、".join(f"{pn_names[c]} {c}" if c in pn_names else c for c in pn_codes) or "未填"
        usd = sum(br_money(c.get("CostMoney")) for c in costs.get(pid, []))
        brl = sum(br_money(c.get("CostBrlMoney")) for c in costs.get(pid, []))
        debit = fi_num(latest.get("DebitMoney")) if latest else None
        is_stop = str(r.get("IsStopLine") or "").strip() == E["stop_yes"]
        restarted = is_stop and str(r.get("StopStatus") or "").strip() == E["restarted"]
        stopped_now = is_stop and not restarted
        # 清单的停线状态与按停线状态统计用同一套字（巴西「停线」表：否 + 空即从未停线，是 + 空即停线中）
        stop_label = "停线重启" if restarted else ("停线中" if stopped_now else "从未停线")
        bad, impact = fi_num(r.get("BadQty")), fi_num(r.get("ImpactQty"))
        rate_value, rate_text = br_rate(bad, impact)
        add = fi_ts(r.get("AddDate"))
        close = fi_ts(latest.get("FinishDate")) if (done and latest) else None
        close_days = int((close.normalize() - add.normalize()).days) if (close is not None and add is not None) else None
        inv = None if fi_blank(r.get("cInvCode")) else str(r.get("cInvCode")).strip()
        ven = None if fi_blank(r.get("cVenCode")) else str(r.get("cVenCode")).strip()
        level = fi_show(r.get("ProblemLevel"))
        rows.append({
            "_id": pid, "_status": s, "_done": done, "_unclosed": unclosed, "_rejected": False,
            "_closed_label": closed_label,
            "_add": add, "_found": fi_text_date(r.get("ProblemDiscoveryDate")), "_stop": fi_text_date(r.get("StopDate")),
            "_restart": None, "_close": close, "_stat": fi_text_date(r.get("StatisticsDate")),
            "_stopped_ever": is_stop, "_stopped_now": stopped_now, "_restarted": restarted,
            "_not_stopped": not is_stop, "_stop_code": None,
            "_stop_label": stop_label,
            "_stages": [status.get(s, fi_show(s))], "_machines": machines, "_series": series,
            # 大机型有值但一段都对不上产品主数据：按机型统计时归「未识别机型」，不归「未填」（与清单显示一致）
            "_machines_unknown": machine_text == "未识别机型",
            "_factories": factories, "_current_ids": [], "_current_names": [],
            "_follower_ids": [] if follower_id is None else [follower_id],
            "_responsible_ids": [] if follower_id is None else [follower_id],
            "_follow_dept_ids": [] if dept_id is None else [dept_id],
            "_follower_group": follower_group, "_follow_dept_group": dept_group,
            "_resp_dept_ids": [], "_resp_material": False,
            "_rate_value": rate_value, "_bad": bad, "_den": impact, "_impact": impact,
            "_close_days": close_days, "_stop_days": None, "_inv_name": inv_names.get(inv),
            "_pn_codes": pn_codes, "_pn_names": [pn_names[c] for c in pn_named],
            "_usd": usd, "_brl": brl, "_debit": debit, "_has_cost": usd > 0 or brl > 0,
            "_number": fi_show(r.get("OrderNumber")),
            "number": fi_show(r.get("OrderNumber")), "claim": fi_show(r.get("ClaimNumber")),
            "machine": machine_text, "series": "、".join(series) or "未填", "pn": pn_text,
            "type": type_show, "other_desc": other_desc,
            "factory": "、".join(factories) or "未填", "status": status.get(s, "未填"),
            "follower": follower, "follow_dept": follow_dept, "responsible": follower,
            "add_date": fi_day(add) or "未填", "found_date": fi_show(r.get("ProblemDiscoveryDate")),
            "stat_date": fi_show(r.get("StatisticsDate")), "rate": rate_text,
            "bad_qty": fi_show(r.get("BadQty")), "impact_qty": fi_show(r.get("ImpactQty")), "level": level,
            "is_stop": fi_show(r.get("IsStopLine")), "stop_status": stop_label,
            "stop_date": fi_show(r.get("StopDate")), "close_time": fi_day(close) or ("未填" if done else "—"),
            "inv_code": inv or "未填", "inv_name": inv_names.get(inv, "未填"), "inv_std": inv_stds.get(inv, "未填"),
            "ven_code": ven or "未填", "ven_name": vendors.get(ven, "未填"),
            "station": fi_show(r.get("ProblemDiscoveryStation")),
            "need_8d": E["yes_no"].get(fi_int(r.get("IsRequire8D")), "未填"),
            "supplement": E["yes_no"].get(fi_int(r.get("IsSupplement")), "未填"),
            "is_cost": E["yes_no"].get(fi_int(r.get("IsCost")), "未填"),
            "cost_usd": fi_round(usd, 2), "cost_brl": fi_round(brl, 2),
            "debit": fi_show(fi_round(debit, 2)) if debit is not None else "未填",
            "design_change": fi_show(latest.get("IsDesignChange")) if latest else "未填",
            "plan_done": fi_show(latest.get("PlanCompleteDate")) if latest else "未填",
            "add_user": names.get(fi_int(r.get("AddUserID")), "未填"),
            "initial_owner": names.get(fi_int(r.get("ActorUserID")), "未填"),
            "desc": desc_text,
        })
    return pd.DataFrame(rows)
