"""海外派生（设计 §6.2；海外业务描述「口径」「单张单详情」、处理步骤表「派生：结案时间」）。

输入是本步取回的海外各帧（主表、处理步骤、人员、部门、产品、PN 主数据、国内工厂），输出与国内同一套辅助列的
「一单一行」视图（列表见 `views.py` 开头）。展示列用内部键（`present/columns.py::OS_VIEW_COLUMNS`）。

- 当前责任人取主表上的姓名列，不用处理步骤上的成员拼；已完成的单没有当前责任人。
- 不良率是单上原文（% 与 ‰ 混用），展示原文、不汇总；`_rate_value` 统一成百分数只用于比大小与排序。
- 物料是 JSON 数组：料号、描述、供应商编号与名称逐条；按物料名称找看描述，按料号找看任一条的料号。
- 结案时间：已完成的单取「结案确认」`Id` 最大的一条的操作时间。
- `os_blocks` 给单张单详情的区块（J-D10、J-D11）：按单上走过的环节逐块给，驳回后还没重新提交的那一块标「已退回」。
"""

import re

import pandas as pd

from factory_issue_module.stats.lib.common import (
    fi_blank,
    fi_day,
    fi_group,
    fi_ids,
    fi_int,
    fi_json_list,
    fi_lookup,
    fi_num,
    fi_records,
    fi_show,
    fi_split,
    fi_text_date,
    fi_ts,
    fi_unique,
)

_OS_RATE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(%|‰)\s*$")


def os_enums(raw):
    """参数里的枚举（JSON 的键是字符串）→ 整数键。"""
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict) and all(re.fullmatch(r"-?\d+", str(c)) for c in v):
            out[k] = {int(c): x for c, x in v.items()}
        else:
            out[k] = v
    return out


def os_rate_value(text):
    """单上原文的不良率 → 百分数（‰ 除以 10）；认不出按空。只用于比大小，不展示、不汇总。"""
    if fi_blank(text):
        return None
    m = _OS_RATE.match(str(text))
    if not m:
        return None
    x = float(m.group(1))
    return x / 10 if m.group(2) == "‰" else x


def os_type(code, E):
    if code is None:
        return "未填"
    return E["types"].get(code, E["unknown_type"])


def os_close_time(row, steps_of, E):
    """结案时间：只对「已完成」的单定，取「结案确认」`Id` 最大的一条的操作时间；没有这样的记录时定不出。"""
    if fi_int(row.get("Status")) != E["done"]:
        return None
    closes = [s for s in steps_of if str(s.get("StepStr") or "").strip() == E["step_close"]]
    if not closes:
        return None
    last = max(closes, key=lambda s: fi_int(s.get("Id")) or 0)
    return fi_ts(last.get("AddDate"))


def os_blocks(row, steps_of, E):
    """单张单详情的区块（海外「单张单详情」）：[{"stage", "step", "returned", "main"}]，按第一次走到的先后。

    - 按单上走过的环节逐块给，没走到的环节不显示；填写问题、驳回、任务转移这类记录不成块。不按问题类型的区块表
      套（结构问题、制程优化目前没有单，J-D11）。
    - 每块取该环节最新一条（`Id` 最大）；`main` 是放在这一块里的主表各项（责任人确认的原因、措施、对策等）。
    - 驳回后还没重新提交（当前状态就是这个环节，且它在最近一次驳回之后没有新记录）：`returned` 为真，`step` 为空、
      `main` 为空，连同主表各项都不给驳回前的内容，答「该环节已退回重新处理」（J-D10）。
    """
    recs = sorted(steps_of, key=lambda s: fi_int(s.get("Id")) or 0)
    order = []
    for s in recs:
        name = str(s.get("StepStr") or "").strip()
        if name and name not in E["non_block"] and name not in order:
            order.append(name)
    rejects = [fi_int(s.get("Id")) or 0 for s in recs if str(s.get("StepStr") or "").strip() == E["step_reject"]]
    last_reject = max(rejects) if rejects else None
    label = E["status"].get(fi_int(row.get("Status")))
    current = E["status_steps"].get(label, [label]) if label else []
    out = []
    for name in order:
        mine = [s for s in recs if str(s.get("StepStr") or "").strip() == name]
        returned = (last_reject is not None and name in current
                    and not any((fi_int(s.get("Id")) or 0) > last_reject for s in mine))
        out.append({"stage": name, "step": None if returned else mine[-1], "returned": returned,
                    "main": [] if returned else list(E["block_main"].get(name, []))})
    return out


def os_view(data, E, desc_text):
    """海外「一单一行」视图。`desc_text` 是问题描述一列（S6 之前、文字查找不可用时为「暂不可用」）。"""
    main = data.get("os_main")
    if main is None:
        return pd.DataFrame()
    names = fi_lookup(data.get("employees"), "ID", "Name", cast="int")
    depts = fi_lookup(data.get("departments"), "ID", "Name", cast="int")
    product_names = fi_lookup(data.get("products"), "ID", "ProductName", cast="int")
    cn_factories = fi_lookup(data.get("factories"), "FactoryID", "FactoryName")
    pn_names = fi_lookup(data.get("pns"), "PartNumber", "Name")
    steps = fi_group(fi_records(data.get("os_steps")), "ProblemId")
    status = E["status"]
    rows = []
    for r in fi_records(main):
        pid = fi_int(r.get("Id"))
        s = fi_int(r.get("Status"))
        done = s == E["done"]
        t = fi_int(r.get("ProblemType"))
        segs = fi_ids(r.get("ProductType"))
        machines = fi_unique([product_names[i] for i in segs if i in product_names])
        machine_text = "、".join(machines) if machines else ("未识别机型" if segs else "未填")
        pn_codes = fi_unique(fi_split(r.get("PNList")))
        pn_text = "、".join(f"{pn_names[c]} {c}" if c in pn_names else c for c in pn_codes) or "未填"
        items = fi_json_list(r.get("InvInfo"))
        inv_codes = fi_unique([str(x.get("PN")).strip() for x in items if not fi_blank(x.get("PN"))])
        descs = fi_unique([str(x.get("materialDesc")).strip() for x in items if not fi_blank(x.get("materialDesc"))])
        ven_codes = fi_unique([str(x.get("supplier")).strip() for x in items if not fi_blank(x.get("supplier"))])
        ven_names = fi_unique([str(x.get("supplierName")).strip() for x in items
                               if not fi_blank(x.get("supplierName"))])
        follower_ids = fi_ids(r.get("RUser"))
        followers = [names[i] for i in follower_ids if i in names]
        dept_id = fi_int(r.get("RDepartment"))
        current_ids = [] if done else fi_ids(r.get("MemberList"))
        current_names = [] if done else fi_split(r.get("MemberListName"))
        stop_code = fi_int(r.get("StopState"))
        is_stop = fi_int(r.get("IsStop")) == 1
        add = fi_ts(r.get("AddDate"))
        stop = fi_text_date(r.get("StopDate"))
        restart = fi_ts(r.get("ReStartDate"))
        close = os_close_time(r, steps.get(pid, []), E)
        close_days = int((close.normalize() - add.normalize()).days) if (close is not None and add is not None) else None
        stop_days = int((restart.normalize() - stop.normalize()).days) if (restart is not None and stop is not None) \
            else None
        status_text = status.get(s, "未填")
        current_text = "、".join(current_names) if current_names else ("—" if done else "未填")
        state_text = status_text if (done or not current_names) else f"{status_text} {'、'.join(current_names)}"
        follower_text = "、".join(followers) or "未填"
        rows.append({
            "_id": pid, "_status": s, "_done": done, "_unclosed": not done, "_rejected": False,
            "_closed_label": "已结案" if done else "未结案",
            "_add": add, "_found": fi_text_date(r.get("FoundDate")), "_stop": stop, "_restart": restart,
            "_close": close, "_stat": None,
            "_stopped_ever": is_stop, "_stopped_now": stop_code == E["stopped"],
            "_restarted": stop_code == E["restarted"],
            "_not_stopped": stop_code not in (E["stopped"], E["restarted"]), "_stop_code": None,
            "_stages": [status_text], "_machines": machines, "_series": [],
            # 大机型有值但一段都对不上产品主数据：按机型统计时归「未识别机型」，不归「未填」（与清单显示一致）
            "_machines_unknown": machine_text == "未识别机型",
            "_current_ids": current_ids, "_current_names": current_names,
            "_follower_ids": follower_ids, "_follower_names": followers, "_responsible_ids": current_ids,
            "_follow_dept_ids": [] if dept_id is None else [dept_id], "_resp_dept_ids": [], "_resp_material": False,
            "_rate_value": os_rate_value(r.get("Rate")), "_bad": fi_num(r.get("BadQty")), "_den": None,
            "_impact": fi_num(r.get("ImpactQty")), "_close_days": close_days, "_stop_days": stop_days,
            "_inv_name": "；".join(descs) or None, "_inv_codes": inv_codes, "_ven_codes": ven_codes,
            "_ven_names_text": "；".join(ven_names) or None,
            "_pn_codes": pn_codes, "_pn_names": [pn_names[c] for c in pn_codes if c in pn_names],
            "_number": fi_show(r.get("Numbers")),
            "number": fi_show(r.get("Numbers")), "machine": machine_text, "series": fi_show(r.get("Series")),
            "pn": pn_text, "type": os_type(t, E), "old_type": os_type(fi_int(r.get("OldProblemType")), E)
            if not fi_blank(r.get("OldProblemType")) else "未填",
            "other_desc": fi_show(r.get("ProblemRemark")), "factory": fi_show(r.get("Factory")),
            "cn_factory": cn_factories.get(str(r.get("Factory2") or "").strip(), "未填"),
            "status": status_text, "current_state": state_text, "current_people": current_text,
            "follower": follower_text, "follow_dept": depts.get(dept_id, "未填"),
            "responsible": f"当前责任人：{current_text}；问题跟进人：{follower_text}",
            "add_date": fi_day(add) or "未填", "found_date": fi_show(r.get("FoundDate")),
            "rate": fi_show(r.get("Rate")), "bad_qty": fi_show(r.get("BadQty")),
            "impact_qty": fi_show(r.get("ImpactQty")), "level": fi_show(r.get("ProblemLevel")),
            "is_stop": E["yes_no"].get(fi_int(r.get("IsStop")), "未填"),
            "stop_status": E["stop_state"].get(stop_code, E["not_stopped"]),
            "stop_date": fi_show(r.get("StopDate")), "restart_date": fi_day(restart) or "未填",
            "close_time": fi_day(close) or ("未填" if done else "—"),
            "inv_code": "、".join(inv_codes) or "未填", "inv_name": "；".join(descs) or "未填",
            "ven_code": "、".join(ven_codes) or "未填", "ven_name": "、".join(ven_names) or "未填",
            "station": fi_show(r.get("Station")), "version": fi_show(r.get("Version")),
            "iqc_opinion": E["iqc_opinion"].get(fi_int(r.get("IQCOpinion")), "未填"),
            "design_change": E["yes_no"].get(fi_int(r.get("IsDesignChange")), "未填"),
            "design_result": E["design_result"].get(fi_int(r.get("DesignConfirmResult")), "未填"),
            "plan_done": fi_day(fi_ts(r.get("RCompleteTime"))) or "未填",
            "add_user": names.get(fi_int(r.get("AddUser")), "未填"),
            "desc": desc_text,
        })
    return pd.DataFrame(rows)
