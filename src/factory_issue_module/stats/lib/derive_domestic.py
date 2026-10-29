"""国内派生（设计 §6.2；国内业务描述「当前状态」「当前责任人」「责任人怎么取」「停线」、处理步骤表「派生」）。

输入是本步取回的国内各帧（主表、机型、处理步骤、待办任务、风险订单流程、人员、部门、工厂、供应商、存货），
输出「一单一行」的视图：展示列用内部键（`present/columns.py::VIEW_COLUMNS` 再换成显示名），下划线开头的是
筛选、分组、计数要用的辅助列，不展示。枚举对照由调用方作为参数传进来（`domains/enums.py`）。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import (
    fi_blank,
    fi_date_in_text,
    fi_day,
    fi_group,
    fi_ids,
    fi_int,
    fi_lookup,
    fi_num,
    fi_percent_text,
    fi_records,
    fi_show,
    fi_split,
    fi_ts,
    fi_unique,
)


def cn_enums(raw):
    """参数里的枚举（JSON 的键是字符串）→ 整数键。"""
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[k] = {int(c): x for c, x in v.items()}
        else:
            out[k] = v
    return out


def cn_names(employees):
    return fi_lookup(employees, "ID", "Name", cast="int")


def cn_states(main, tasks, risk, employees, E):
    """当前状态（国内「当前状态」）：问题单 ID → [(环节, [姓名], [员工 ID])]，一行一个环节。

    - 已完成只一行「已完成」，不追加 IQC、退货 / 退库段。
    - 状态 30、36、37 按两类已接受的待办现算（要做预防对策确认的类型才算；两类都没有时保持库里原状态），
      再按现算的状态逐行给：30 为预防对策确认 + 效果确认两行，36 只有效果确认，37 只有预防对策确认。
    - 其余状态：主状态一行；IQC 状态有值时另起一行（与主状态同名也不合并）；有进行中的退货 / 退库时另起一行，
      步骤取进行中记录里最早的一条，人员列全部进行中记录的责任人，按员工 ID 去重。
    - 待办任务只认两个业务表名、任务状态为「已接受」的（取数时已带条件，这里再筛一遍，J-P12）。
    """
    names = cn_names(employees)
    status = E["status"]
    by_task = {}
    for t in fi_records(tasks):
        if str(t.get("ftable")) not in (E["task_effect"], E["task_prevention"]):
            continue
        if "fstat" in t and str(t.get("fstat")) != E["task_accepted"]:
            continue
        pid = fi_int(t.get("frecID"))
        if pid is not None:
            by_task.setdefault(pid, []).append(t)
    by_risk = fi_group(fi_records(risk), "ProblemId")
    out = {}
    for r in fi_records(main):
        pid = fi_int(r.get("ID"))
        s = fi_int(r.get("Status"))
        if s == E["done"]:
            out[pid] = [(status.get(s, "已完成"), [], [])]
            continue
        handlers = (fi_split(r.get("MemberListName")), fi_ids(r.get("MemberList")))
        rows = []
        if s in E["parallel"]:
            mine = by_task.get(pid, [])
            kinds = {str(t.get("ftable")) for t in mine}
            t_code = fi_int(r.get("ProblemType"))
            needs = t_code in E["needs_prevention"]
            comp = s
            if needs:
                effect, prevention = E["task_effect"] in kinds, E["task_prevention"] in kinds
                if effect and prevention:
                    comp = 30
                elif effect:
                    comp = 36
                elif prevention:
                    comp = 37
            prev_ids = fi_unique([fi_int(t.get("fuserID")) for t in mine
                                  if str(t.get("ftable")) == E["task_prevention"] and fi_int(t.get("fuserID")) is not None])
            prev = ([names[i] for i in prev_ids if i in names], [i for i in prev_ids if i in names])
            if comp == 30 and needs:
                rows += [("预防对策确认", *prev), ("效果确认", *handlers)]
            elif comp in (30, 36):
                rows.append(("效果确认", *handlers))
            elif comp == 37:
                rows.append(("预防对策确认", *prev))
            else:
                rows.append((status.get(comp, fi_show(comp)), *handlers))
        else:
            rows.append((status.get(s, fi_show(s)), *handlers))
        iqc = fi_int(r.get("IQCStatus"))
        if iqc is not None:
            rows.append((status.get(iqc, fi_show(iqc)), fi_split(r.get("IQCMemberListName")), fi_ids(r.get("IQCMemberList"))))
        running = sorted((x for x in by_risk.get(pid, []) if fi_int(x.get("Status")) == E["risk_running"]),
                         key=lambda x: fi_int(x.get("ID")) or 0)
        if running:
            step = E["risk_steps"].get(fi_int(running[0].get("Step")), fi_show(running[0].get("Step")))
            ids = fi_unique([fi_int(x.get("UserID")) for x in running if fi_int(x.get("UserID")) is not None])
            rows.append((step, [names[i] for i in ids if i in names], ids))
        out[pid] = rows
    return out


def cn_state_text(rows):
    """「SQE跟进 张三；IQC确认 李四」：每行「环节 人」，同一环节多人用逗号合并。"""
    return "；".join(stage + (" " + ",".join(people) if people else "") for stage, people, _ids in rows)


def cn_steps_by_issue(steps):
    return fi_group(fi_records(steps), "ProblemId")


def cn_close_time(row, steps_of, E):
    """结案时间：只对「已完成」的单定，取环节编码 31、`ID` 最大的一条的操作时间；没有就定不出（处理步骤表「派生」）。"""
    if fi_int(row.get("Status")) != E["done"]:
        return None
    closes = [s for s in steps_of if fi_int(s.get("Step")) == E["step_close"]]
    if not closes:
        return None
    last = max(closes, key=lambda s: fi_int(s.get("ID")) or 0)
    return fi_ts(last.get("AddDate"))


def cn_restart_date(steps_of, E):
    """重启日期：最新一条停线重启（编码 29）结论里登记的日期（国内「停线」）。"""
    rs = [s for s in steps_of if fi_int(s.get("Step")) == E["step_restart"]]
    if not rs:
        return None
    last = max(rs, key=lambda s: fi_int(s.get("ID")) or 0)
    return fi_date_in_text(last.get("Result"))


def cn_responsible(row, steps_of, E):
    """责任人（国内「责任人怎么取」）：按问题类型取对应环节最新一条的操作人员工 ID；没走到该环节返回 None。

    「最新一条」按操作时间最晚、同时间取 `ID` 大的。结案后改过问题分类（「修改问题分类」在最新一条结案确认之后）
    的单，按原问题类型取。
    """
    t = fi_int(row.get("ProblemType"))
    closes = [fi_int(s.get("ID")) or 0 for s in steps_of if fi_int(s.get("Step")) == E["step_close"]]
    if closes:
        last_close = max(closes)
        moved = any(str(s.get("StepStr") or "").strip() == E["step_reclassify"] and (fi_int(s.get("ID")) or 0) > last_close
                    for s in steps_of)
        old = fi_int(row.get("OldProblemType"))
        if moved and old is not None:
            t = old
    code = E["responsible_step"].get(t)
    if code is None:
        return None
    hits = [s for s in steps_of if fi_int(s.get("Step")) == code]
    if not hits:
        return None
    best = max(hits, key=lambda s: (fi_ts(s.get("AddDate")) or pd.Timestamp.min, fi_int(s.get("ID")) or 0))
    return fi_int(best.get("AddUser"))


def cn_view(data, E, desc_text):
    """国内「一单一行」视图。`desc_text` 是问题描述一列（S6 之前、文字查找不可用时为「暂不可用」）。"""
    main = data.get("cn_main")
    if main is None:
        return pd.DataFrame()
    names = cn_names(data.get("employees"))
    depts = fi_lookup(data.get("departments"), "ID", "Name", cast="int")
    factories = fi_lookup(data.get("factories"), "FactoryID", "FactoryName")
    vendors = fi_lookup(data.get("vendors"), "ferpcode", "fname")
    inv_names = fi_lookup(data.get("inventory"), "cInvCode", "cInvName")
    inv_stds = fi_lookup(data.get("inventory"), "cInvCode", "cInvStd")
    models = fi_group(fi_records(data.get("cn_models")), "ProblemId")
    orders = fi_group(fi_records(data.get("cn_orders")), "ProblemId")
    steps = cn_steps_by_issue(data.get("cn_steps"))
    states = cn_states(main, data.get("cn_tasks"), data.get("cn_risk"), data.get("employees"), E)
    rows = []
    for r in fi_records(main):
        pid = fi_int(r.get("ID"))
        t = fi_int(r.get("ProblemType"))
        s = fi_int(r.get("Status"))
        done = s == E["done"]
        material_flag = str(r.get("MHead") or "").strip() == "物料"
        ms = models.get(pid, [])
        machines = fi_unique([str(m.get("ProductName")).strip() for m in ms if not fi_blank(m.get("ProductName"))])
        series = fi_unique([str(m.get("Series")).strip() for m in ms if not fi_blank(m.get("Series"))])
        st_rows = states.get(pid, [])
        cur_ids = [] if done else fi_unique([i for _s, _p, ids in st_rows for i in ids])
        cur_names = [] if done else fi_unique([p for _s, people, _i in st_rows for p in people])
        steps_of = steps.get(pid, [])
        close = cn_close_time(r, steps_of, E)
        restart = cn_restart_date(steps_of, E)
        add = fi_ts(r.get("AddDate"))
        stop = fi_ts(r.get("StopDate"))
        resp = cn_responsible(r, steps_of, E)
        follower_id = fi_int(r.get("RUser"))
        dept_id = fi_int(r.get("RDepartment"))
        stop_code = fi_int(r.get("StopStatus"))
        is_stop = fi_int(r.get("IsStop"))
        resp_ids = [] if t == 3 else fi_ids(r.get("AllReDepartment"))
        if t == 3:
            resp_text = "—"
        elif not resp_ids:
            resp_text = "无需定责" if done else "未定责"
        else:
            resp_text = "、".join(depts[i] for i in resp_ids if i in depts) or "未填"
        bad, prod = fi_num(r.get("BadQty")), fi_num(r.get("ProdQty"))
        inv = None if fi_blank(r.get("CInvCode")) else str(r.get("CInvCode")).strip()
        ven = None if fi_blank(r.get("VenCode")) else str(r.get("VenCode")).strip()
        close_days = None
        if close is not None and add is not None:
            close_days = int((close.normalize() - add.normalize()).days)
        stop_days = None
        if restart is not None and stop is not None:
            stop_days = int((restart.normalize() - stop.normalize()).days)
        rows.append({
            "_id": pid, "_type": t, "_status": s, "_done": done, "_rejected": s == E["rejected"],
            "_closed_label": "已结案" if done else "未结案",
            "_pn_codes": fi_unique([str(o.get("PartNumber")).strip() for o in orders.get(pid, [])
                                    if not fi_blank(o.get("PartNumber"))]),
            "_pn_names": fi_unique([str(o.get("PartName")).strip() for o in orders.get(pid, [])
                                    if not fi_blank(o.get("PartName"))]),
            "_material_flag": material_flag, "_machines": machines, "_series": series,
            "_stages": fi_unique([stage for stage, _p, _i in st_rows]), "_current_ids": cur_ids,
            "_current_names": cur_names, "_responsible_ids": [] if resp is None else [resp],
            "_follower_ids": [] if follower_id is None else [follower_id],
            "_resp_dept_ids": resp_ids, "_resp_dept_names": [depts[i] for i in resp_ids if i in depts],
            "_resp_material": t == 3, "_add": add, "_found": fi_ts(r.get("FoundDate")), "_stop": stop,
            "_restart": restart, "_close": close, "_stop_code": stop_code,
            "_stopped_ever": is_stop == 1, "_stopped_now": stop_code in E["stopped"],
            "_restarted": stop_code == E["restarted"], "_rate_value": fi_num(r.get("Rate")),
            "_bad": bad, "_den": prod, "_impact": None if material_flag else fi_num(r.get("ImpactQty")),
            "_close_days": close_days, "_stop_days": stop_days,
            "_inv_name": inv_names.get(inv), "_number": fi_show(r.get("Numbers")),
            "number": fi_show(r.get("Numbers")),
            "machine": "物料" if material_flag else ("、".join(machines) or "未填"),
            "series": "、".join(series) or "未填",
            "type": E["types"].get(t, "未填"),
            "old_type": E["types"].get(fi_int(r.get("OldProblemType")), "未填"),
            "factory": factories.get(str(r.get("Factory") or "").strip(), "未填"),
            "status": E["status"].get(s, "未填"),
            "current_state": cn_state_text(st_rows) or "未填",
            "current_people": "、".join(cur_names) if cur_names else ("—" if done else "未填"),
            "follower": names.get(follower_id, "未填"),
            "follow_dept": depts.get(dept_id, "未填"),
            "responsible": names.get(resp, "未填"),
            "resp_dept": resp_text,
            "add_date": fi_day(add) or "未填", "found_date": fi_day(fi_ts(r.get("FoundDate"))) or "未填",
            "rate": fi_percent_text(r.get("Rate")), "bad_qty": fi_show(r.get("BadQty")),
            "prod_qty": fi_show(r.get("ProdQty")),
            "impact_qty": "—" if material_flag else fi_show(r.get("ImpactQty")),
            "level": fi_show(r.get("ProblemLevel")),
            "output_status": "—" if material_flag else E["output_status"].get(fi_int(r.get("OutPutStatus")), "未填"),
            "is_stop": E["yes_no"].get(is_stop, "未填"),
            "stop_status": E["stop_status"].get(stop_code, "未填"),
            "stop_date": fi_day(stop) or "未填", "restart_date": fi_day(restart) or "未填",
            "close_time": fi_day(close) or ("未填" if done else "—"),
            "inv_code": inv or "未填", "inv_name": inv_names.get(inv, "未填"), "inv_std": inv_stds.get(inv, "未填"),
            "ven_code": ven or "未填", "ven_name": vendors.get(ven, "未填"),
            "station": fi_show(r.get("Station")), "version": fi_show(r.get("Version")),
            "reason_class": fi_show(r.get("ReasonClass")),
            "design_result": E["design_result"].get(fi_int(r.get("DesignConfirmResult")), "未填"),
            "iqc_opinion": E["iqc_opinion"].get(fi_int(r.get("IQCOpinion")), "未填"),
            "design_change": E["yes_no"].get(fi_int(r.get("IsDesignChange")), "未填"),
            "plan_done": fi_day(fi_ts(r.get("RCompleteTime"))) or "未填",
            "add_user": names.get(fi_int(r.get("AddUser")), "未填"),
            "car": fi_show(r.get("CAR")) if t == 3 and not fi_blank(r.get("CARID")) else "—",
            "desc": desc_text,
        })
    return pd.DataFrame(rows)
