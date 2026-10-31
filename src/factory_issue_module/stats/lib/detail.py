"""单张单详情的各块（设计 §6.3 `issue_detail` 一行、§13；国内「单张单详情各环节怎么显示」「停线」「处理步骤」，
巴西「单张单详情」，海外「单张单详情」；总述「原因与措施怎么给」）。

输入是一域本步取回的帧（主表含叙述列、全部子表、文档、主数据），输出每张单的各块：
`{"key", "title", "fields": [[标签, 文字] 或 [标签, 文字, [[文档 ID, 文档名称], …]]], "tables": [...], "notes": [...]}`。
标签都是显示名（参数 `labels`，`present/columns.py::DETAIL`），给用户的句子来自参数 `texts`（`turn/errors.py`）。
文档 ID、CAR 报告 ID 只用来拼链接，不作文字展示（链接在 `handle()` 一侧拼：附件摘要要的值不进沙箱脚本）。

- 叙述列先剥图（`textnorm.rich_display`），剥净后单个字段超过 2 万字截断并注明（§13）。
- 只拼、只挑、只排；计数（驳回几次、其他在线订单几条）与合计（发货单订单数量、费用）都在这里算。
- 只在 `detail` 任务的脚本里拼进来（`stats/runner.py::TASK_LIBS`），清单与统计的脚本不带它。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import (
    fi_blank,
    fi_date_in_text,
    fi_day,
    fi_group,
    fi_ids,
    fi_int,
    fi_json_list,
    fi_lookup,
    fi_num,
    fi_records,
    fi_round,
    fi_show,
    fi_ts,
    fi_unique,
)
from factory_issue_module.stats.lib.derive_brazil import br_enums, br_latest, br_view
from factory_issue_module.stats.lib.derive_domestic import cn_enums, cn_view
from factory_issue_module.stats.lib.derive_overseas import os_blocks, os_enums, os_view
from factory_issue_module.textnorm import phen_text, rich_display

# ---------------------------------------------------------------------------- 小工具


def dt_text(v, T):
    """叙述列 → 展示文字；超长时截断并注明。"""
    text, cut = rich_display(v)
    return text + ("\n" + T["long"] if cut else "")


def dt_add(fields, label, value, docs=None):
    """有内容才加（叙述栏「有内容才显示，没有就不显示」）。"""
    if value is None:
        return
    s = value if isinstance(value, str) else fi_show(value, "")
    if not str(s).strip() or str(s).strip() == "未填":
        return
    fields.append([label, str(s)] if docs is None else [label, str(s), docs])


def dt_put(fields, label, value):
    """总是显示，空写「未填」。"""
    s = value if isinstance(value, str) and value.strip() else fi_show(value)
    fields.append([label, s])


def dt_time(v):
    ts = fi_ts(v)
    return None if ts is None else ts.strftime("%Y-%m-%d %H:%M")


def dt_block(key, title, fields=None, tables=None, notes=None):
    return {"key": key, "title": title, "fields": fields or [], "tables": tables or [], "notes": notes or []}


def dt_table(title, columns, rows, docs=None, link_col=None, limit=None):
    shown = rows if limit is None else rows[: int(limit)]
    out = {"title": title, "columns": columns, "rows": shown, "total": len(rows), "shown": len(shown)}
    if docs is not None:
        out["docs"] = docs[: len(shown)]
        out["link_col"] = link_col
    return out


def dt_doc_map(frame):
    """文档清单：文档 ID → {name, frecid, type}，只留没删除的（`EffectFlag = 0`）。"""
    out = {}
    for r in fi_records(frame):
        i = fi_int(r.get("ID"))
        if i is None or fi_int(r.get("EffectFlag")) != 0:
            continue
        name = fi_show(r.get("DocumentName"), "") or fi_show(r.get("DocumentRealName"), "")
        if name:
            out[i] = {"name": name, "frecid": fi_int(r.get("frecid")), "type": str(r.get("BusinessType") or "").strip()}
    return out


def dt_docs(ids_text, docs, frecid=None):
    """逗号多值的附件 ID → [[ID, 名称]]：逐段对应文档，已删除的不给；`frecid` 给了时再要求业务记录 ID 相同（海外）。"""
    out = []
    for i in fi_ids(ids_text):
        d = docs.get(i)
        if d is None or (frecid is not None and d["frecid"] != frecid):
            continue
        out.append([i, d["name"]])
    return out


def dt_doc_text(items):
    return "、".join(name for _i, name in items)


def dt_pick(view, P, domain):
    """本步要看的单：编号或单 ID 对上的（假连接器不执行 WHERE，这里再对一遍）。"""
    want = P["targets"].get(domain) or {}
    numbers = set(want.get("numbers") or [])
    ids = set(int(x) for x in want.get("ids") or [])
    if len(view) == 0:
        return []
    out = []
    for _, v in view.iterrows():
        if str(v["_number"]).upper() in numbers or int(v["_id"]) in ids:
            out.append(v)
    return out


def dt_money(x):
    return f"{fi_round(x, 2):.2f}"


def dt_numbered(lines):
    return "\n".join(f"{i}. {x}" for i, x in enumerate(lines, start=1))


# ---------------------------------------------------------------------------- 国内


def dt_cn_latest(steps):
    """同一环节编码只取最新一条（`ID` 最大）。"""
    by = {}
    for s in steps:
        c = fi_int(s.get("Step"))
        if c is not None:
            by[c] = s
    return by


def dt_cn_stages(r, v, by, E):
    """单张单详情的环节（国内「单张单详情各环节怎么显示」）：按页面顺序给
    [{"code", "name", "shown", "returned", "rec"}]。`returned` 是本类型有这一环节、也有这一步，只因当前状态
    退回到它之前而不显示的（回答「该环节已退回重新处理」）。状态 30、36、37 用按待办现算后的状态码。"""
    t = v["_type"]
    s = fi_int(v["_comp_status"]) or 0
    old = fi_int(r.get("OldProblemType"))
    zl_yes = dt_cn_confirmed(r, 4)
    out = []

    def add(code, type_ok, status_ok, rec=None):
        rec = rec if rec is not None else by.get(code)
        if rec is None or not type_ok:
            return
        out.append({"code": code, "name": E["detail_stages"].get(code, ""), "shown": bool(status_ok),
                    "returned": not status_ok, "rec": rec})

    add(33, t == 7, True)
    add(2, True, s > 1)
    add(3, True, s > 2)
    add(14, old == 3 and t != 3, s != 11)
    add(4, old == 4 and t != 4 and not zl_yes, s != 3)
    add(14, t == 3, s != 11)
    iqc = [x for x in (by.get(7), by.get(8)) if x is not None]
    if iqc:
        add(7, t == 3, s >= 6, max(iqc, key=lambda x: fi_int(x.get("ID")) or 0))
    add(10, t == 3, s > 8)
    add(11, t == 3, s > 9)
    add(13, t == 3, s > 10)
    add(4, t == 4, s > 3)
    add(5, t == 4, s > 4)
    add(6, t == 5, s > 5)
    add(35, t in (1, 2, 3, 4, 6), True)
    add(30, True, s in (31, 32, 37))
    add(31, True, s == 32)
    for i, st in enumerate(out):
        st["changed"] = (st["code"] == 14 and t != 3) or (st["code"] == 4 and t != 4)
        st["key"] = f"stage:{i}"
    return out


def dt_cn_five(five_of, names, E, L):
    """5Why：按提问时间排（同一时间按录入先后），现编序号；问题与原因都空的不给；待答复的写「待答复」。"""
    rows = sorted(five_of, key=lambda x: (fi_ts(x.get("AddDate")) or pd.Timestamp.min, fi_int(x.get("ID")) or 0))
    out = []
    pending = E["five_status"].get(E["five_pending"], "")
    for x in rows:
        q = str(x.get("Question") or "").strip()
        a = str(x.get("Reason") or "").strip()
        if not q and not a:
            continue
        waiting = fi_int(x.get("Status")) == E["five_pending"]
        out.append([str(len(out) + 1), q or "未填", fi_show(names.get(fi_int(x.get("AddUser")))),
                    dt_time(x.get("AddDate")) or "未填",
                    pending if waiting else (a or "未填"),
                    pending if waiting else fi_show(names.get(fi_int(x.get("UpdateUser")))),
                    pending if waiting else (dt_time(x.get("UpdateDate")) or "未填"),
                    E["five_status"].get(fi_int(x.get("Status")), "未填")])
    cols = [L["seq"], L["fw.Question"], L["fw.AddUser"], L["fw.AddDate"], L["fw.Reason"], L["fw.UpdateUser"],
            L["fw.UpdateDate"], L["fw.Status"]]
    return cols, out


def dt_cn_confirmed(r, code):
    """主表原因、措施、对策、处理结果、计划完成时间与 5Why 所在环节的确认结果是否为「是」：责任人确认看跟进人是否确认，
    工程确认看资料问题确认结果。与管理页面一致只看有没有值：不为 0 即「是」，0 或空即「否」（「是」才给那几项，
    「否」给修改后的问题分类）。"""
    return (fi_int(r.get("RConfirm" if code == 3 else "ZLConfirmResult")) or 0) != 0


def dt_cn_stage_fields(st, r, v, names, docs, E, L, T):
    """一个环节块里给什么（国内处理步骤表「单张单详情里的结论」）。"""
    rec = st["rec"]
    code = st["code"]
    f = []
    dt_put(f, L["handler"], names.get(fi_int(rec.get("AddUser"))))
    dt_add(f, L["step.AddDate"], dt_time(rec.get("AddDate")))
    result = fi_int(rec.get("Result"))
    opinion = dt_text(rec.get("Opinon"), T)
    files = dt_docs(rec.get("FileUrl"), docs)
    if code == 33:
        dt_put(f, L["confirm_result"], E["role_disagree"] if result == 0 else E["role_agree"])
        dt_add(f, L["note"], opinion)
    elif code == 2:
        dt_put(f, L["follower"], v["follower"])
        dt_put(f, L["follow_dept"], v["follow_dept"])
    elif code == 3 or (code == 4 and not st["changed"]):
        confirmed = dt_cn_confirmed(r, code)
        dt_put(f, L["cn.RConfirm" if code == 3 else "cn.ZLConfirmResult"], E["yes_no"].get(1 if confirmed else 0))
        if confirmed:
            dt_add(f, L["cn.Reason"], dt_text(r.get("Reason"), T))
            dt_add(f, L["cn.Measures"], dt_text(r.get("Measures"), T))
            dt_add(f, L["cn.Prevention"], dt_text(r.get("Prevention"), T))
            dt_put(f, L["design_result"], v["design_result"])
            dt_put(f, L["plan_done"], v["plan_done"])
            if code == 4:
                change = fi_int(r.get("IsChangeOrderV"))
                dt_put(f, L["cn.IsChangeOrderV"], E["yes_no"].get(change, "未填"))
                if change == 1:
                    dt_add(f, L["cn.OrderVersion"], r.get("OrderVersion"))
        else:
            dt_put(f, L["new_type"], v["type"])
    elif code == 4:  # 资料问题改成别的类型后的工程确认：只给处理人、确认结果「否」、修改后的问题分类、附件、备注
        dt_put(f, L["confirm_result"], E["yes_no"].get(0, "否"))
        dt_put(f, L["new_type"], v["type"])
        dt_add(f, L["note"], opinion)
    elif code == 14:
        dt_put(f, L["iqc_opinion"], v["iqc_opinion"])
        dt_add(f, L["step.Opinon"], opinion)
    elif code == 10:
        need = E["need_design"].get(result)
        dt_put(f, L["need_design"], need or "未填")
        if result == 1:
            dt_put(f, L["cn.DesignUser"], names.get(fi_int(r.get("DesignUser"))))
        dt_add(f, L["sqe_result"], opinion)
    elif code == 11:
        dt_put(f, L["confirm_result"], v["design_result"])
        if fi_int(r.get("DesignConfirmResult")) == 1:
            dt_put(f, L["cn.DesignDate"], fi_day(fi_ts(r.get("DesignDate"))))
        dt_add(f, L["reason_note"], opinion)
    elif code == 6:
        dt_add(f, L["cn.Reason"], dt_text(rec.get("Result"), T))
        dt_add(f, L["countermeasure"], opinion)
    elif code == 35:
        dt_add(f, L["prevention_confirm"], opinion)
    elif code == 30:
        dt_add(f, L["effect_result"], opinion)
    elif code == 31:
        dt_add(f, L["close_conclusion"], opinion)
    else:
        dt_add(f, L["step.Opinon"], opinion)
    if files:
        f.append([L["step.FileUrl"], dt_doc_text(files), files])
    return f


def dt_cn_stop(r, v, by, names, E, L, T):
    """单张单详情的停线部分（国内「停线」）：每项取对应环节编码最新的一条。"""
    f = []
    stop = fi_int(r.get("StopStatus"))
    dt_put(f, L["is_stop"], v["is_stop"])
    notes = []
    if fi_int(r.get("IsStop")) == 1:
        text = v["stop_status"]
        if stop == E["stop_reviewing"] and not fi_blank(r.get("ReStartExamineUser")):
            text += f"（{L['cn.ReStartExamineUser']}：{fi_show(names.get(fi_int(r.get('ReStartExamineUser'))))}）"
        if stop == E["stop_scheme"] and not fi_blank(r.get("ReStartSchemeUser")):
            text += f"（{L['cn.ReStartSchemeUser']}：{fi_show(names.get(fi_int(r.get('ReStartSchemeUser'))))}）"
        dt_put(f, L["stop_status"], text)
        dt_put(f, L["stop_date"], v["stop_date"])
    restart = by.get(E["step_restart"])
    if restart is not None and not (fi_blank(restart.get("Result")) and fi_blank(restart.get("Opinon"))):
        day = fi_date_in_text(restart.get("Result"))
        dt_add(f, L["restart_date"], fi_day(day))
        dt_add(f, L["restart_note"], dt_text(restart.get("Opinon"), T))
    hidden = stop in (E["stop_reviewing"], E["stop_scheme"])
    scheme = by.get(E["step_restart_scheme"])
    if scheme is not None and not hidden:
        text = dt_text(scheme.get("Opinon"), T)
        if text:
            who = fi_show(names.get(fi_int(scheme.get("AddUser"))))
            dt_add(f, L["cn.ReStartScheme"], f"{text}（{L['cn.ReStartSchemeUser']}：{who}，{dt_time(scheme.get('AddDate'))}）")
    review = by.get(E["step_restart_review"])
    if review is not None and not hidden:
        said = E["review_result"].get(fi_int(review.get("Result")), "")
        extra = dt_text(review.get("Opinon"), T)
        who = fi_show(names.get(fi_int(review.get("AddUser"))))
        text = "；".join(x for x in (said, extra) if x)
        dt_add(f, L["restart_review"], f"{text}（{L['cn.ReStartExamineUser']}：{who}，{dt_time(review.get('AddDate'))}）"
               if text else "")
    if stop == E["stop_reviewing"] and (scheme is not None or review is not None):
        notes.append(T["restart_reviewing"])
    return dt_block("stop", T["stop_title"], f, notes=notes)


def dt_cn_process(steps, names, docs, r, E, L, T, limit):
    """完整处理过程（国内处理步骤表「处理过程怎么展示」）：全部记录按先后，5 列；停线重启三步另列「重启操作日志」，
    停线状态为重启审核中时那一段不给。"""
    main_rows, main_docs, restart_rows = [], [], []
    for s in steps:
        content = dt_text(s.get("Measures"), T) or dt_text(s.get("Opinon"), T)
        who = fi_show(names.get(fi_int(s.get("AddUser"))))
        when = dt_time(s.get("AddDate")) or "未填"
        kind = fi_show(s.get("StepStr"))
        if fi_int(s.get("Step")) in E["restart_steps"]:
            restart_rows.append([who, when, kind, content or "未填"])
            continue
        files = dt_docs(s.get("FileUrl"), docs)
        main_rows.append([who, when, kind, content or "未填", dt_doc_text(files) or "—"])
        main_docs.append(files)
    cols = [L["step.AddUser"], L["step.AddDate"], L["step.StepStr"], L["step.Measures"], L["step.FileUrl"]]
    tables = [dt_table(T["process_title"], cols, main_rows, main_docs, 4, limit)]
    notes = []
    if restart_rows:
        if fi_int(r.get("StopStatus")) == E["stop_reviewing"]:
            notes.append(T["restart_reviewing"])
        else:
            tables.append(dt_table(T["restart_log_title"], cols[:4], restart_rows, None, None, limit))
    rejects = len([s for s in steps if fi_int(s.get("Step")) == E["step_reject"]])
    block = dt_block("process", T["process_title"], tables=tables, notes=notes)
    return block, rejects


def dt_cn_reasons(r, v, stages, by, five, car_block, E, L, T, P):
    """原因与措施（总述「原因与措施怎么给」国内一行）：主表三项（随所在环节显示），分析类环节每个环节最新一条的
    意见、内容（工厂制程分析另含结论），只给当前显示的环节；5Why 附在后面；物料问题关联了 CAR 时附报告两项。"""
    t = v["_type"]
    f, notes = [], []
    shown = {st["code"]: st for st in stages if st["shown"] and not st["changed"]}
    returned = [st for st in stages if st["returned"]]
    host = {1: 3, 2: 3, 6: 3, 7: 3, 4: 4}.get(t)
    if host is None or (host in shown and dt_cn_confirmed(r, host)):
        dt_add(f, L["cn.Reason"], dt_text(r.get("Reason"), T))
        dt_add(f, L["cn.Measures"], dt_text(r.get("Measures"), T))
        dt_add(f, L["cn.Prevention"], dt_text(r.get("Prevention"), T))
    codes = [int(c) for c in P["analysis"]["codes"]]
    picked = sorted((st for st in stages if st["code"] in codes and st["shown"]),
                    key=lambda st: fi_int(st["rec"].get("ID")) or 0)
    labels = {6: L["countermeasure"], 10: L["sqe_result"], 11: L["reason_note"], 35: L["prevention_confirm"]}
    for st in picked:
        rec = st["rec"]
        parts = []
        if st["code"] == 6:
            res = dt_text(rec.get("Result"), T)
            if res:
                parts.append(f"{L['cn.Reason']}：{res}")
        op = dt_text(rec.get("Opinon"), T)
        if op:
            parts.append(f"{labels.get(st['code'], L['step.Opinon'])}：{op}")
        content = dt_text(rec.get("Measures"), T)
        if content and content != op:
            parts.append(f"{L['step.Measures']}：{content}")
        if parts:
            f.append([fi_show(rec.get("StepStr")) or st["name"], "；".join(parts)])
    for st in returned:
        if st["code"] in codes or st["code"] == host:
            notes.append(f"「{st['name']}」{T['returned']}")
    tables = []
    if five is not None:
        tables.append(five)
    if car_block is not None:
        f += [x for x in car_block["fields"] if x[0] in (L["car.fstep3memo"], L["car.fstep4memo"])]
        notes += car_block["notes"]
    if not f and not tables and not notes:
        notes.append(T["no_reasons"])
    block = dt_block("reasons", T["reasons_title"], f, tables, notes)
    if car_block is not None:
        block["car_id"], block["car_text"] = car_block["car_id"], car_block["car_text"]
    return block


def dt_cn_car(r, v, car_rows, E, L, T, P):
    """CAR（国内「物料问题专属」，`privileges.md`「CAR 报告」）：只有物料问题且 CAR 报告 ID 有值才有；
    有报告权限时给六项内容，没有时只给编号与链接、按那里的说法答。"""
    car_id = fi_int(r.get("CARID"))
    if v["_type"] != 3 or car_id is None:
        return None
    f = []
    dt_put(f, L["car"], fi_show(r.get("CAR"), L["car_report"]))
    notes = []
    if not P.get("car"):
        notes.append(T["car_denied"])
    else:
        rep = next((x for x in car_rows if fi_int(x.get("fid")) == car_id), None)
        if rep is None:
            notes.append(T["car_missing"])
        else:
            for col in ("fdesc", "fstep2how1", "fstep2how2", "fstep2how3", "fstep3memo", "fstep4memo", "fstep5memo",
                        "fstep6memo"):
                dt_add(f, L["car." + col], dt_text(rep.get(col), T))
    block = dt_block("car", L["car_report"], f, notes=notes)
    block["car_id"] = car_id
    block["car_text"] = fi_show(r.get("CAR"), L["car_report"])
    return block


def dt_cn(data, E, L, T, P):
    """国内各单的详情块。"""
    view = cn_view(data, E, P["desc"].get("国内", "未填"))
    picked = dt_pick(view, P, "国内")
    if not picked:
        return []
    names = fi_lookup(data.get("employees"), "ID", "Name", cast="int")
    docs = dt_doc_map(data.get("documents"))
    factories = fi_lookup(data.get("factories"), "FactoryID", "FactoryName")
    inv_names = fi_lookup(data.get("inventory"), "cInvCode", "cInvName")
    mains = {fi_int(x.get("ID")): x for x in fi_records(data.get("cn_main"))}
    steps_by = fi_group(fi_records(data.get("cn_steps")), "ProblemId")
    orders_by = fi_group(fi_records(data.get("cn_orders")), "ProblemId")
    xb_by = fi_group(fi_records(data.get("cn_xb")), "ProblemId")
    other_by = fi_group(fi_records(data.get("cn_other")), "ProblemId")
    check_by = fi_group(fi_records(data.get("cn_check")), "ProblemId")
    pinv_by = fi_group(fi_records(data.get("cn_pinv")), "ProblemId")
    five_by = fi_group(fi_records(data.get("cn_five")), "ProblemId")
    phen = fi_lookup(data.get("cn_phen"), "ID", "PhenomenonDesc", cast="int")
    preason = fi_lookup(data.get("cn_preason"), "ID", "ReasonDesc", cast="int")
    ctype = fi_lookup(data.get("cn_pclass"), "ID", "TypeName", cast="int")
    cname = fi_lookup(data.get("cn_pclass"), "ID", "ClassName", cast="int")
    car_rows = fi_records(data.get("cn_car"))
    limit = P.get("table_rows")
    out = []
    for v in picked:
        pid = int(v["_id"])
        r = mains.get(pid) or {}
        material = bool(v["_material_flag"])
        t = v["_type"]
        steps = sorted(steps_by.get(pid, []), key=lambda s: fi_int(s.get("ID")) or 0)
        by = dt_cn_latest(steps)
        stages = dt_cn_stages(r, v, by, E)
        blocks = {}
        # 抬头
        h = []
        dt_put(h, L["factory"], v["factory"])
        dt_put(h, L["machine"], v["machine"])
        dt_put(h, L["found_date"], v["found_date"])
        dt_put(h, L["type"], v["type"])
        dt_put(h, L["add_user"], v["add_user"])
        dt_put(h, L["add_date"], dt_time(r.get("AddDate")))
        dt_put(h, L["station"], v["station"])
        dt_put(h, L["version"], v["version"])
        dt_put(h, L["current_state"], "\n".join(v["_state_lines"]) or "未填")
        dt_put(h, L["level"], v["level"])
        if not material:
            dt_put(h, L["output_status"], v["output_status"])
        if not (fi_blank(r.get("AllReDepartment")) and fi_blank(r.get("ReasonClass"))):
            if t != 3:
                dt_put(h, L["resp_dept"], v["resp_dept"])
            dt_put(h, L["reason_class"], v["reason_class"])
        dt_add(h, L["cn.ReasonClassRemark"], dt_text(r.get("ReasonClassRemark"), T))
        if not material:
            dt_put(h, L["impact_qty"], v["impact_qty"])
        dt_put(h, L["prod_qty"], v["prod_qty"])
        dt_put(h, L["bad_qty"], v["bad_qty"])
        dt_put(h, L["rate"], v["rate"])
        for key in ("inv_code", "inv_std", "ven_code", "ven_name"):  # 有值时才给
            dt_add(h, L[key], v[key])
        car = dt_cn_car(r, v, car_rows, E, L, T, P)
        if car is not None:
            dt_put(h, L["car"], car["car_text"])
        others = other_by.get(pid, [])
        notes = [T["other_orders_count"].replace("{n}", str(len(others)))] if others else []
        blocks["header"] = dt_block("header", T["header_title"], h, notes=notes)
        if car is not None:
            blocks["header"]["car_id"] = car["car_id"]
            blocks["header"]["car_text"] = car["car_text"]
            blocks["car"] = car
        # 订单
        if material:
            rows = [[fi_show(o.get("OrderNumber")), fi_show(o.get("InvCode")), fi_show(o.get("InvStd")),
                     fi_show(o.get("Qty")), fi_show(o.get("InQty")), fi_show(o.get("NoQty")), fi_show(o.get("Factory")),
                     fi_show(o.get("Description"))] for o in sorted(xb_by.get(pid, []), key=lambda o: fi_int(o.get("ID")) or 0)]
            cols = [L["xb." + c] for c in ("OrderNumber", "InvCode", "InvStd", "Qty", "InQty", "NoQty", "Factory",
                                            "Description")]
            title = L["xb_orders"]
        else:
            rows = []
            for o in sorted(orders_by.get(pid, []), key=lambda o: fi_int(o.get("ID")) or 0):
                pn = " ".join(x for x in (fi_show(o.get("PartName"), ""), fi_show(o.get("PartNumber"), "")) if x)
                rows.append([fi_show(o.get("OrderNumber")), pn or "未填", fi_day(fi_ts(o.get("IssueDate"))) or "未填",
                             fi_show(o.get("OrderQty")), fi_show(o.get("ReceiptQty")), fi_show(o.get("OnlineQty")),
                             fi_show(o.get("Version"))])
            cols = [L["ord.OrderNumber"], L["pn"], L["ord.IssueDate"], L["ord.OrderQty"], L["ord.ReceiptQty"],
                    L["ord.OnlineQty"], L["ord.Version"]]
            title = L["prod_orders"]
        if rows:
            blocks["orders"] = dt_block("orders", title, tables=[dt_table(title, cols, rows, limit=limit)])
        pns = fi_unique([row[1] for row in rows]) if not material else []
        blocks["pn"] = dt_block("pn", L["pn"], [[L["pn"], "、".join(pns) or "未填"]],
                                notes=[T["material_unit"]] if material else [])
        if others:
            orows = []
            for o in sorted(others, key=lambda o: fi_int(o.get("ID")) or 0):
                orows.append([fi_show(o.get("OrderNo")), fi_show(o.get("ProductName")), fi_show(o.get("Qty")),
                              fi_show(o.get("IssuedQty")), fi_show(o.get("IssQty")),
                              fi_day(fi_ts(o.get("FaliaoDate"))) or "未填", fi_show(o.get("ReturnQty")),
                              E["return_type"].get(fi_int(o.get("ReturnType")), "未填"), fi_show(o.get("ReceivingQty")),
                              fi_show(o.get("TotalinQty")),
                              factories.get(str(o.get("Factory") or "").strip(), fi_show(o.get("Factory")))])
            ocols = [L["oo." + c] for c in ("OrderNo", "ProductName", "Qty", "IssuedQty", "IssQty", "FaliaoDate",
                                             "ReturnQty", "ReturnType", "ReceivingQty", "TotalinQty", "Factory")]
            blocks["other_orders"] = dt_block("other_orders", L["other_orders"],
                                              tables=[dt_table(L["other_orders"], ocols, orows, limit=limit)])
        # 停线
        blocks["stop"] = dt_cn_stop(r, v, by, names, E, L, T)
        # 问题现象、可能问题原因、可能的问题物料
        checks = sorted(check_by.get(pid, []), key=lambda x: fi_int(x.get("ID")) or 0)
        seen, phen_lines = [], []
        for c in checks:
            ph = fi_int(c.get("PhenomenonID"))
            if ph is None or ph in seen or ph not in phen:
                continue
            seen.append(ph)
            cls = fi_int(c.get("ClassID"))
            where = " → ".join(x for x in (ctype.get(cls), cname.get(cls)) if x)
            phen_lines.append(phen[ph] + (f"（{where}）" if where else ""))
        if phen_lines:
            blocks["phenomena"] = dt_block("phenomena", L["phen.PhenomenonDesc"],
                                           [[L["phen.PhenomenonDesc"], "\n".join(phen_lines)]])
        reasons = sorted(fi_unique([preason[fi_int(c.get("ReasonID"))] for c in checks
                                    if fi_int(c.get("ReasonID")) in preason]))
        if reasons:
            blocks["possible_reasons"] = dt_block("possible_reasons", L["preason.ReasonDesc"],
                                                  [[L["preason.ReasonDesc"], dt_numbered(reasons)]],
                                                  notes=[T["possible_reasons_intro"]])
        pinv = [" ".join(x for x in (fi_show(p.get("InvCode"), ""), fi_show(p.get("InvStd"), "")) if x)
                for p in sorted(pinv_by.get(pid, []), key=lambda p: fi_int(p.get("ID")) or 0)]
        pinv = [x for x in pinv if x]
        if pinv:
            blocks["possible_inv"] = dt_block("possible_inv", L["possible_inv"], [[L["possible_inv"], dt_numbered(pinv)]],
                                              notes=[T["possible_inv_intro"]])
        # 问题描述、改善建议、备注；附件（填写问题这一步）
        d = []
        dt_put(d, L["desc"], dt_text(r.get("ProblemDesc"), T) or "未填")
        dt_add(d, L["cn.Improve"], dt_text(r.get("Improve"), T))
        dt_add(d, L["cn.Remark"], dt_text(r.get("Remark"), T))
        blocks["description"] = dt_block("description", L["desc"], d)
        fill = by.get(E["step_fill"])
        files = dt_docs(fill.get("FileUrl"), docs) if fill is not None else []
        if files:
            blocks["attachments"] = dt_block("attachments", L["step.FileUrl"],
                                             [[L["step.FileUrl"], dt_doc_text(files), files]])
        step_files = [[fi_show(s.get("StepStr")), dt_docs(s.get("FileUrl"), docs)] for s in steps
                      if fi_int(s.get("Step")) != E["step_fill"]]
        all_files = ([[L["step.FileUrl"], dt_doc_text(files), files]] if files else []) + \
            [[name, dt_doc_text(fs), fs] for name, fs in step_files if fs]
        blocks["all_attachments"] = dt_block("all_attachments", L["step.FileUrl"], all_files,
                                             notes=[] if all_files else [T["no_attachments"]])
        # 5Why：随本类型的分析环节显示或隐藏
        five_cols, five_rows = dt_cn_five(five_by.get(pid, []), names, E, L)
        host_code = E["five_stage"].get(t)
        host = next((st for st in stages if st["code"] == host_code and not st["changed"]), None)
        host_ok = host is not None and host["shown"] and (host_code not in (3, 4) or dt_cn_confirmed(r, host_code))
        five = dt_table("5Why", five_cols, five_rows) if (five_rows and host_ok) else None
        if five is not None:
            blocks["five_why"] = dt_block("five_why", "5Why", tables=[five])
        elif five_rows and host is not None and host["returned"]:
            blocks["five_why"] = dt_block("five_why", "5Why", notes=[f"「{host['name']}」{T['returned']}"])
        else:
            blocks["five_why"] = dt_block("five_why", "5Why", notes=[T["no_five_why"]])
        # 各环节
        order = ["header", "orders", "stop", "phenomena", "possible_reasons", "possible_inv", "description",
                 "attachments"]
        for st in stages:
            if not st["shown"]:
                continue
            fields = dt_cn_stage_fields(st, r, v, names, docs, E, L, T)
            tables = [five] if (five is not None and host is st) else []
            blocks[st["key"]] = dt_block(st["key"], st["name"], fields, tables)
            order.append(st["key"])
        # 按要看的内容另给的几块
        blocks["reasons"] = dt_cn_reasons(r, v, stages, by, five, car, E, L, T, P)
        process, rejects = dt_cn_process(steps, names, docs, r, E, L, T, limit)
        blocks["process"] = process
        cur = []
        dt_put(cur, L["current_state"], "\n".join(v["_state_lines"]) or "未填")
        dt_put(cur, L["current_people"], v["current_people"])
        blocks["current"] = dt_block("current", L["current_state"], cur)
        fol = [[L["follower"], v["follower"]], [L["follow_dept"], v["follow_dept"]]]
        blocks["follow"] = dt_block("follow", L["follower"], fol, notes=[T["cn_no_follower"]] if t in (3, 4, 5) else [])
        resp = [[L["responsible"], v["responsible"]]]
        if not v["_done"]:
            resp.append([L["current_people"], v["current_people"]])
        resp.append([L["follower"], v["follower"]])
        blocks["responsible"] = dt_block("responsible", L["responsible"], resp, notes=[T["cn_roles"]])
        blocks["machine"] = dt_block("machine", L["machine"], [[L["machine"], v["machine"]], [L["series"], v["series"]]],
                                     notes=[T["material_unit"]] if material else [])
        mat = [[L["cn.MHead"], "物料" if material else "—"], [L["inv_code"], v["inv_code"]],
               [L["inv_name"], inv_names.get(str(r.get("CInvCode") or "").strip(), "未填")], [L["inv_std"], v["inv_std"]],
               [L["ven_code"], v["ven_code"]], [L["ven_name"], v["ven_name"]]]
        blocks["material"] = dt_block("material", L["inv_code"], mat, notes=[T["material_unit"]] if material else [])
        des = [[L["design_change"], v["design_change"]]]
        if fi_int(r.get("IsDesignChange")) == 1:
            des.append([L["cn.DesignUser"], fi_show(names.get(fi_int(r.get("DesignUser"))))])
        des.append([L["design_result"], v["design_result"]])
        if fi_int(r.get("DesignConfirmResult")) == 1 and not fi_blank(r.get("DesignDate")):
            des.append([L["cn.DesignDate"], fi_day(fi_ts(r.get("DesignDate")))])
        blocks["design"] = dt_block("design", L["design_change"], des)
        out.append({"domain": "国内", "id": pid, "number": v["_number"], "blocks": blocks, "order": order,
                    "material": material, "facts": {"驳回次数": rejects, "其他在线订单条数": len(others)}})
    return out


# ---------------------------------------------------------------------------- 巴西


def dt_br_phen(raw):
    """巴西问题现象 JSON 展平（巴西主表「问题现象」）：规则在 `textnorm.phen_text`，治理任务共用。"""
    return "" if fi_blank(raw) else phen_text(raw, "brazil")


def dt_br(data, E, L, T, P):
    """巴西各单的详情块（巴西「单张单详情」）：处理过程只给最新一条；8D 报告、设计更改附件给全部处理过程上的。"""
    view = br_view(data, E, P["desc"].get("巴西", "未填"))
    picked = dt_pick(view, P, "巴西")
    if not picked:
        return []
    names = fi_lookup(data.get("employees"), "ID", "Name", cast="int")
    docs = dt_doc_map(data.get("documents"))
    mains = {fi_int(x.get("ID")): x for x in fi_records(data.get("br_main"))}
    process_by = fi_group(fi_records(data.get("br_process")), "ProblemID")
    cost_by = fi_group(fi_records(data.get("br_cost")), "ProblemID")
    po_by = fi_group(fi_records(data.get("br_po")), "ProblemID")
    request_pn = fi_lookup(data.get("br_requests"), "ID", "PartNumber", cast="int")
    yes, no = E["yes_text"], E["no_text"]
    out = []
    for v in picked:
        pid = int(v["_id"])
        r = mains.get(pid) or {}
        procs = process_by.get(pid, [])
        p = br_latest(procs) or {}
        proc_ids = [fi_int(x.get("ID")) for x in procs]

        def bdocs(kind, ids):
            return [[i, d["name"]] for i, d in sorted(docs.items()) if d["type"] == kind and d["frecid"] in ids]

        claim_docs = bdocs(E["doc_claim"], [pid])
        docs_8d = bdocs(E["doc_8d"], proc_ids)
        design_docs = bdocs(E["doc_design"], proc_ids)
        blocks = {}
        h = []
        dt_put(h, L["status"], v["status"])
        dt_put(h, L["add_user"], v["add_user"])
        dt_put(h, L["add_date"], dt_time(r.get("AddDate")))
        dt_put(h, L["factory"], v["factory"])
        dt_put(h, L["claim"], v["claim"])
        dt_put(h, L["series"], v["series"])
        dt_put(h, L["machine"], v["machine"])
        dt_put(h, L["pn"], v["pn"])
        dt_put(h, L["type"], v["type"])
        dt_add(h, L["other_desc"], v["other_desc"])
        dt_put(h, L["inv_code"], v["inv_code"])
        dt_put(h, L["inv_name"], v["inv_name"])
        dt_put(h, L["ven_code"], v["ven_code"])
        dt_put(h, L["ven_name"], v["ven_name"])
        dt_put(h, L["impact_qty"], v["impact_qty"])
        dt_put(h, L["bad_qty"], v["bad_qty"])
        dt_put(h, L["rate"], v["rate"])
        dt_add(h, L["br.ProblemPhenomenon"], dt_br_phen(r.get("ProblemPhenomenon")))
        dt_put(h, L["level"], v["level"])
        dt_put(h, L["is_stop"], v["is_stop"])
        if v["_stopped_ever"]:
            dt_put(h, L["stop_status"], v["stop_status"])
            dt_put(h, L["stop_date"], v["stop_date"])
        dt_put(h, L["found_date"], v["found_date"])
        dt_put(h, L["station"], v["station"])
        dt_put(h, L["stat_date"], v["stat_date"])
        dt_put(h, L["desc"], dt_text(r.get("ProblemDesc"), T) or "未填")
        dt_put(h, L["supplement"], v["supplement"])
        if fi_int(r.get("IsSupplement")) == 1:
            dt_put(h, L["br.SupplementQty"], r.get("SupplementQty"))
        dt_put(h, L["need_8d"], v["need_8d"])
        dt_put(h, L["is_cost"], v["is_cost"])
        dt_add(h, L["br.Memo"], dt_text(r.get("Memo"), T))
        if claim_docs:
            h.append([L["claim_docs"], dt_doc_text(claim_docs), claim_docs])
        blocks["header"] = dt_block("header", T["br_header_title"], h)
        # 费用明细与合计（含 0 金额行、汇率、备注）；扣款另列
        costs = sorted(cost_by.get(pid, []), key=lambda c: fi_int(c.get("ID")) or 0)
        crow = [[fi_show(c.get("CostType")), dt_money(fi_num(c.get("CostMoney")) or 0.0),
                 dt_money(fi_num(c.get("CostBrlMoney")) or 0.0), fi_show(fi_round(fi_num(c.get("ConstBrlRate")), 4)),
                 dt_text(c.get("CostMemo"), T) or "未填"] for c in costs]
        ccols = [L["brc." + c] for c in ("CostType", "CostMoney", "CostBrlMoney", "ConstBrlRate", "CostMemo")]
        usd = sum(fi_num(c.get("CostMoney")) or 0.0 for c in costs)
        brl = sum(fi_num(c.get("CostBrlMoney")) or 0.0 for c in costs)
        cf = [[L["cost_usd"], dt_money(usd)], [L["cost_brl"], dt_money(brl)]]
        debit = fi_num(p.get("DebitMoney"))
        if debit is not None:
            cf.append([L["brp.DebitMoney"], dt_money(debit)])
        blocks["cost"] = dt_block("cost", T["cost_title"], cf,
                                  [dt_table(T["cost_title"], ccols, crow)] if crow else [],
                                  [T["debit_apart"]] if debit is not None else ([] if crow else [T["no_cost"]]))
        # 责任人确认、SQE 确认、效果确认、结案确认（最新一条处理过程）
        order = ["header", "cost"]
        if p:
            f = []
            dt_put(f, L["brp.ProcessResult"], p.get("ProcessResult"))
            dt_put(f, L["brp.ProcessUserID"], names.get(fi_int(p.get("ProcessUserID"))))
            dt_put(f, L["brp.ProcessDate"], fi_day(fi_ts(p.get("ProcessDate"))))
            dt_put(f, L["brp.PlanCompleteDate"], p.get("PlanCompleteDate"))
            dt_add(f, L["brp.DisposeResult"], dt_text(p.get("DisposeResult"), T))
            dt_put(f, L["brp.IsDesignChange"], p.get("IsDesignChange"))
            dt_put(f, L["brp.IsStockPrecess"], p.get("IsStockPrecess"))
            if str(p.get("IsStockPrecess") or "").strip() == yes:
                dt_put(f, L["brp.StockPrecessQty"], p.get("StockPrecessQty"))
            for col in ("ReasonAnalysis", "ImprovementMeasure", "ImprovementBatch", "PrecautionPolicy"):
                dt_add(f, L["brp." + col], dt_text(p.get(col), T))
            shift = str(p.get("IsCostShift") or "").strip()
            dt_put(f, L["brp.IsCostShift"], p.get("IsCostShift"))
            if shift == yes:
                dt_put(f, L["brp.DebitMoney"], dt_money(debit) if debit is not None else None)
                dt_put(f, L["brp.DebitNumber"], p.get("DebitNumber"))
            elif shift == no:
                dt_add(f, L["brp.UnCostShiftReason"], dt_text(p.get("UnCostShiftReason"), T))
            dt_put(f, L["brp.IsSupplementMaterial"], p.get("IsSupplementMaterial"))
            if str(p.get("IsSupplementMaterial") or "").strip() == yes:
                dt_put(f, L["brp.SupplementMaterialQty"], p.get("SupplementMaterialQty"))
                dt_put(f, L["brp.InStoreNumber"], p.get("InStoreNumber"))
            if docs_8d:
                f.append([L["eight_d"], dt_doc_text(docs_8d), docs_8d])
            blocks["stage:confirm"] = dt_block("stage:confirm", T["br_stages"][1], f)
            order.append("stage:confirm")
            if not (fi_blank(p.get("SQEResult")) and fi_blank(p.get("SQEDate"))):
                f = []
                dt_put(f, L["brp.DesignUserID"], names.get(fi_int(p.get("DesignUserID"))))
                dt_put(f, L["brp.DesignResult"], p.get("DesignResult"))
                dt_add(f, L["brp.DesignMemo"], dt_text(p.get("DesignMemo"), T))
                dt_put(f, L["brp.DesignEstimateDate"], p.get("DesignEstimateDate"))
                dt_put(f, L["brp.DesignDate"], fi_day(fi_ts(p.get("DesignDate"))))
                dt_put(f, L["brp.SQEResult"], p.get("SQEResult"))
                dt_add(f, L["brp.SQEMemo"], dt_text(p.get("SQEMemo"), T))
                dt_put(f, L["brp.SQEUserID"], names.get(fi_int(p.get("SQEUserID"))))
                dt_put(f, L["brp.SQEDate"], fi_day(fi_ts(p.get("SQEDate"))))
                if design_docs:
                    f.append([L["design_docs"], dt_doc_text(design_docs), design_docs])
                blocks["stage:sqe"] = dt_block("stage:sqe", T["br_stages"][2], f)
                order.append("stage:sqe")
            if not (fi_blank(p.get("ConfirmResult")) and fi_blank(p.get("ConfirmDate"))):
                f = []
                dt_put(f, L["brp.ConfirmResult"], p.get("ConfirmResult"))
                dt_add(f, L["brp.ConfirmMemo"], dt_text(p.get("ConfirmMemo"), T))
                dt_put(f, L["brp.ConfirmUserID"], names.get(fi_int(p.get("ConfirmUserID"))))
                dt_put(f, L["brp.ConfirmDate"], fi_day(fi_ts(p.get("ConfirmDate"))))
                blocks["stage:effect"] = dt_block("stage:effect", T["br_stages"][3], f)
                order.append("stage:effect")
            if not (fi_blank(p.get("FinishResult")) and fi_blank(p.get("FinishDate"))):
                f = []
                dt_put(f, L["brp.FinishResult"], p.get("FinishResult"))
                dt_add(f, L["brp.FinishMemo"], dt_text(p.get("FinishMemo"), T))
                dt_put(f, L["brp.FinishUserID"], names.get(fi_int(p.get("FinishUserID"))))
                dt_put(f, L["brp.FinishDate"], fi_day(fi_ts(p.get("FinishDate"))))
                blocks["stage:finish"] = dt_block("stage:finish", T["br_stages"][4], f)
                order.append("stage:finish")
        # 按要看的内容另给的几块
        rf = []
        for col in ("ReasonAnalysis", "ImprovementMeasure", "PrecautionPolicy", "DisposeResult"):
            dt_add(rf, L["brp." + col], dt_text(p.get(col), T))
        blocks["reasons"] = dt_block("reasons", T["reasons_title"], rf, notes=[] if rf else [T["no_reasons"]])
        fol = [[L["follower"], v["follower"]], [L["follow_dept"], v["follow_dept"]]]
        blocks["current"] = dt_block("current", L["status"], [[L["status"], v["status"]], *fol],
                                     notes=[T["br_no_current"]])
        blocks["follow"] = dt_block("follow", L["follower"], fol)
        blocks["responsible"] = dt_block("responsible", L["follower"], fol, notes=[T["br_responsible"]])
        blocks["process"] = dt_block("process", T["process_title"], notes=[T["br_latest_only"]])
        e8 = [[L["need_8d"], v["need_8d"]]]
        if docs_8d:
            e8.append([L["eight_d"], dt_doc_text(docs_8d), docs_8d])
        blocks["eight_d"] = dt_block("eight_d", L["eight_d"], e8, notes=[] if docs_8d else [T["no_8d_doc"]])
        att = []
        for label, items in ((L["claim_docs"], claim_docs), (L["eight_d"], docs_8d), (L["design_docs"], design_docs)):
            if items:
                att.append([label, dt_doc_text(items), items])
        blocks["all_attachments"] = dt_block("all_attachments", L["step.FileUrl"], att,
                                             notes=[] if att else [T["no_attachments"]])
        phen = dt_br_phen(r.get("ProblemPhenomenon"))
        blocks["phenomena"] = dt_block("phenomena", L["br.ProblemPhenomenon"],
                                       [[L["br.ProblemPhenomenon"], phen or "未填"]])
        raw_pns = [str(request_pn.get(fi_int(x.get("RequestID")), "")).strip() for x in po_by.get(pid, [])]
        zero_only = bool(raw_pns) and all(c in ("0", "") for c in raw_pns)
        blocks["pn"] = dt_block("pn", L["pn"], [[L["pn"], v["pn"]]], notes=[T["br_pn_zero"]] if zero_only else [])
        blocks["machine"] = dt_block("machine", L["machine"], [[L["machine"], v["machine"]], [L["series"], v["series"]]])
        blocks["material"] = dt_block("material", L["inv_code"], [[L["inv_code"], v["inv_code"]],
                                                                  [L["inv_name"], v["inv_name"]],
                                                                  [L["ven_code"], v["ven_code"]],
                                                                  [L["ven_name"], v["ven_name"]]])
        sup = [[L["supplement"], v["supplement"]]]
        if fi_int(r.get("IsSupplement")) == 1:
            for col in ("SupplementQty", "SupplementResult", "SupplementMemo"):
                sup.append([L["br." + col], dt_text(r.get(col), T) or fi_show(r.get(col))])
            sup.append([L["br.SupplementUserID"], fi_show(names.get(fi_int(r.get("SupplementUserID"))))])
            sup.append([L["br.SupplementDate"], fi_day(fi_ts(r.get("SupplementDate"))) or "未填"])
        sup.append([L["brp.IsSupplementMaterial"], fi_show(p.get("IsSupplementMaterial"))])
        if str(p.get("IsSupplementMaterial") or "").strip() == yes:
            sup.append([L["brp.SupplementMaterialQty"], fi_show(p.get("SupplementMaterialQty"))])
            sup.append([L["brp.InStoreNumber"], fi_show(p.get("InStoreNumber"))])
        blocks["supplement"] = dt_block("supplement", L["supplement"], sup)
        stock = [[L["brp.IsStockPrecess"], fi_show(p.get("IsStockPrecess"))]]
        if str(p.get("IsStockPrecess") or "").strip() == yes:
            stock.append([L["brp.StockPrecessQty"], fi_show(p.get("StockPrecessQty"))])
        blocks["stock"] = dt_block("stock", L["brp.IsStockPrecess"], stock, notes=[T["br_stock_more"]])
        blocks["design"] = blocks.get("stage:sqe") or dt_block(
            "design", L["brp.IsDesignChange"], [[L["brp.IsDesignChange"], fi_show(p.get("IsDesignChange"))]])
        stop = [[L["is_stop"], v["is_stop"]]]
        if v["_stopped_ever"]:
            stop += [[L["stop_status"], v["stop_status"]], [L["stop_date"], v["stop_date"]]]
        blocks["stop"] = dt_block("stop", T["stop_title"], stop, notes=[T["br_no_restart"]])
        blocks["five_why"] = dt_block("five_why", "5Why", notes=[T["br_five_why"]])
        out.append({"domain": "巴西", "id": pid, "number": v["_number"], "blocks": blocks, "order": order,
                    "material": False, "facts": {}})
    return out


# ---------------------------------------------------------------------------- 海外


def dt_os_phen(raw):
    """海外已选问题现象 JSON 展平（海外主表「JSON 列结构」）：规则在 `textnorm.phen_text`，治理任务共用。"""
    return "" if fi_blank(raw) else phen_text(raw, "overseas")


def dt_os(data, E, L, T, P):
    """海外各单的详情块（海外「单张单详情」）：抬头，再按单上走过的环节逐块给（`os_blocks`）。"""
    view = os_view(data, E, P["desc"].get("海外", "未填"))
    picked = dt_pick(view, P, "海外")
    if not picked:
        return []
    names = fi_lookup(data.get("employees"), "ID", "Name", cast="int")
    docs = dt_doc_map(data.get("documents"))
    pn_names = fi_lookup(data.get("pns"), "PartNumber", "Name")
    mains = {fi_int(x.get("Id")): x for x in fi_records(data.get("os_main"))}
    steps_by = fi_group(fi_records(data.get("os_steps")), "ProblemId")
    delivery_by = fi_group(fi_records(data.get("os_delivery")), "ProblemId")
    reasons_by = fi_group(fi_records(data.get("os_preason")), "PhenomenonID")
    analysis = list(P["analysis"]["names"])
    limit = P.get("table_rows")
    out = []
    for v in picked:
        pid = int(v["_id"])
        r = mains.get(pid) or {}
        steps = sorted(steps_by.get(pid, []), key=lambda s: fi_int(s.get("Id")) or 0)
        blocks = {}
        h = []
        dt_put(h, L["factory"], v["factory"])
        dt_put(h, L["machine"], v["machine"])
        dt_put(h, L["pn"], v["pn"])
        dt_put(h, L["add_user"], v["add_user"])
        dt_put(h, L["add_date"], dt_time(r.get("AddDate")))
        dt_put(h, L["current_state"], v["current_state"])
        dt_put(h, L["type"], v["type"])
        dt_put(h, L["impact_qty"], v["impact_qty"])
        dt_put(h, L["bad_qty"], v["bad_qty"])
        dt_put(h, L["rate"], v["rate"])
        dt_add(h, L["os.hasCheckedPhenomenon"], dt_os_phen(r.get("hasCheckedPhenomenon")))
        dt_put(h, L["level"], v["level"])
        dt_put(h, L["station"], v["station"])
        dt_put(h, L["version"], v["version"])
        dt_put(h, L["found_date"], v["found_date"])
        dt_put(h, L["is_stop"], v["is_stop"])
        if v["_stopped_ever"]:
            dt_put(h, L["stop_status"], v["stop_status"])
            dt_put(h, L["stop_date"], v["stop_date"])
        dt_put(h, L["desc"], dt_text(r.get("ProblemDesc"), T) or "未填")
        dt_add(h, L["os.Improve"], dt_text(r.get("Improve"), T))
        dt_add(h, L["series"], v["series"])
        dt_add(h, L["cn_factory"], v["cn_factory"])
        dt_add(h, L["other_desc"], v["other_desc"])
        dt_add(h, L["os.Remark"], dt_text(r.get("Remark"), T))
        files = dt_docs(r.get("DocId"), docs, pid)
        if files:
            h.append([L["os.DocId"], dt_doc_text(files), files])
        blocks["header"] = dt_block("header", T["header_title"], h)
        # 涉及发货单：按发货单号升序，序号现编，另给订单数量合计
        rows_d = sorted(delivery_by.get(pid, []), key=lambda d: (str(d.get("OrderNumber") or ""), fi_int(d.get("Id")) or 0))
        drows = []
        for i, d in enumerate(rows_d, start=1):
            code = fi_show(d.get("PN"), "")
            pn = f"{pn_names[code]} {code}" if code in pn_names else (code or "未填")
            drows.append([str(i), fi_show(d.get("PO")), fi_show(d.get("OrderNumber")), fi_show(d.get("Date")), pn,
                          fi_show(d.get("DeliveryVersion")), fi_show(d.get("ProdVersion")), fi_show(d.get("Quantity")),
                          fi_show(d.get("Remark"))])
        order = ["header"]
        if drows:
            total = sum(fi_num(d.get("Quantity")) or 0 for d in rows_d)
            dcols = [L["seq"]] + [L["osd." + c] for c in ("PO", "OrderNumber", "Date", "PN", "DeliveryVersion",
                                                         "ProdVersion", "Quantity", "Remark")]
            blocks["delivery"] = dt_block("delivery", T["delivery_title"], [[L["delivery_total"], fi_show(total)]],
                                          [dt_table(T["delivery_title"], dcols, drows, limit=limit)])
            order.append("delivery")
        else:
            blocks["delivery"] = dt_block("delivery", T["delivery_title"], notes=[T["no_delivery"]])
        items = fi_json_list(r.get("InvInfo"))
        mrows = [[fi_show(x.get("PN")), fi_show(x.get("materialDesc")), fi_show(x.get("supplier")),
                  fi_show(x.get("supplierName"))] for x in items]
        mcols = [L["inv_code"], L["os.materialDesc"], L["ven_code"], L["ven_name"]]
        if mrows:
            blocks["material"] = dt_block("material", L["inv_name"], tables=[dt_table(L["inv_name"], mcols, mrows)])
            order.append("material")
        else:
            blocks["material"] = dt_block("material", L["inv_name"], notes=[T["no_material"]])
        # 各环节
        bl = os_blocks(r, steps, E)
        stage_of = {}
        for i, b in enumerate(bl):
            key = f"stage:{i}"
            stage_of[b["stage"]] = b
            if b["returned"]:
                blocks[key] = dt_block(key, b["stage"], notes=[T["returned"]])
                order.append(key)
                continue
            s = b["step"]
            f = []
            dt_put(f, L["handler"], names.get(fi_int(s.get("AddUser"))))
            dt_add(f, L["oss.AddDate"], dt_time(s.get("AddDate")))
            name = b["stage"]
            if name == E["step_assign"]:
                dt_put(f, L["follower"], v["follower"])
            elif name == E["step_confirm"]:
                dt_put(f, L["os.RConfirm"], E["yes_no"].get(1 if (fi_int(r.get("RConfirm")) or 0) > 0 else 0))
                dt_put(f, L["design_result"], v["design_result"])
                dt_put(f, L["plan_done"], v["plan_done"])
                for col in ("Reason", "Measures", "Prevention"):
                    dt_add(f, L["os." + col], dt_text(r.get(col), T))
            elif name == E["step_effect"]:
                dt_add(f, L["effect_result"], dt_text(r.get("Confirmation"), T))
            elif name == E["step_close"]:
                dt_add(f, L["close_conclusion"], dt_text(s.get("Opinon"), T))
            elif name == E["step_sqe"]:
                dt_put(f, L["need_design"], E["need_design"].get(fi_int(s.get("Result")), "未填"))
                dt_add(f, L["oss.Opinon"], dt_text(s.get("Opinon"), T))
            else:
                dt_add(f, L["oss.Result"], dt_text(s.get("Result"), T))
                dt_add(f, L["oss.Opinon"], dt_text(s.get("Opinon"), T))
            sf = dt_docs(s.get("DocID"), docs, pid)
            if sf:
                f.append([L["oss.DocID"], dt_doc_text(sf), sf])
            blocks[key] = dt_block(key, name, f)
            order.append(key)
        # 原因与措施（总述「原因与措施怎么给」海外一行）
        rf, rnotes = [], []
        confirm = stage_of.get(E["step_confirm"])
        if confirm is None or not confirm["returned"]:
            for col in ("Reason", "Measures", "Prevention"):
                dt_add(rf, L["os." + col], dt_text(r.get(col), T))
        for b in bl:
            if b["stage"] not in analysis:
                continue
            if b["returned"]:
                rnotes.append(f"「{b['stage']}」{T['returned']}")
                continue
            s = b["step"]
            parts = []
            if b["stage"] == E["step_factory"]:
                res = dt_text(s.get("Result"), T)
                if res:
                    parts.append(f"{L['oss.Result']}：{res}")
            op = dt_text(s.get("Opinon"), T)
            if op:
                parts.append(f"{L['oss.Opinon']}：{op}")
            content = dt_text(s.get("Measures"), T)
            if content and content != op:
                parts.append(f"{L['oss.Measures']}：{content}")
            if parts:
                rf.append([b["stage"], "；".join(parts)])
        if not rf and not rnotes:
            rnotes.append(T["no_reasons"])
        blocks["reasons"] = dt_block("reasons", T["reasons_title"], rf, notes=rnotes)
        # 完整处理过程：全部记录按 Id 升序，5 列
        prow, pdocs = [], []
        for s in steps:
            sf = dt_docs(s.get("DocID"), docs, pid)
            content = dt_text(s.get("Measures"), T) or dt_text(s.get("Opinon"), T)
            prow.append([fi_show(names.get(fi_int(s.get("AddUser")))), dt_time(s.get("AddDate")) or "未填",
                         fi_show(s.get("StepStr")), content or "未填", dt_doc_text(sf) or "—"])
            pdocs.append(sf)
        pcols = [L["oss." + c] for c in ("AddUser", "AddDate", "StepStr", "Measures", "DocID")]
        blocks["process"] = dt_block("process", T["process_title"],
                                     tables=[dt_table(T["process_title"], pcols, prow, pdocs, 4, limit)])
        rejects = len([s for s in steps if str(s.get("StepStr") or "").strip() == E["step_reject"]])
        blocks["current"] = dt_block("current", L["current_state"], [[L["status"], v["status"]],
                                                                    [L["current_people"], v["current_people"]]])
        fol = [[L["follower"], v["follower"]], [L["follow_dept"], v["follow_dept"]]]
        blocks["follow"] = dt_block("follow", L["follower"], fol)
        blocks["responsible"] = dt_block("responsible", L["current_people"],
                                         [[L["current_people"], v["current_people"]], [L["follower"], v["follower"]]],
                                         notes=[T["os_responsible"]])
        blocks["phenomena"] = dt_block("phenomena", L["os.hasCheckedPhenomenon"],
                                       [[L["os.hasCheckedPhenomenon"], dt_os_phen(r.get("hasCheckedPhenomenon")) or "未填"]])
        lines = []
        for x in fi_json_list(r.get("hasCheckedPhenomenon")):
            key = fi_int(x.get("Key"))
            if key is None or key <= 0:
                continue
            got = sorted(fi_unique([str(y.get("ReasonDesc") or "").strip() for y in reasons_by.get(key, [])
                                    if str(y.get("ReasonDesc") or "").strip()]))
            if got:
                lines.append(f"{str(x.get('Value') or '')}：{'；'.join(got)}")
        blocks["possible_reasons"] = dt_block("possible_reasons", L["preason.ReasonDesc"],
                                              [[L["preason.ReasonDesc"], "\n".join(lines)]] if lines else [],
                                              notes=[T["os_reasons_intro"]] if lines else [T["no_possible_reasons"]])
        att = [[L["os.DocId"], dt_doc_text(files), files]] if files else []
        for s in steps:
            sf = dt_docs(s.get("DocID"), docs, pid)
            if sf:
                att.append([fi_show(s.get("StepStr")), dt_doc_text(sf), sf])
        blocks["all_attachments"] = dt_block("all_attachments", L["os.DocId"], att,
                                             notes=[] if att else [T["no_attachments"]])
        blocks["pn"] = dt_block("pn", L["pn"], [[L["pn"], v["pn"]]])
        blocks["machine"] = dt_block("machine", L["machine"], [[L["machine"], v["machine"]], [L["series"], v["series"]]])
        des = [[L["design_change"], v["design_change"]]]
        if fi_int(r.get("IsDesignChange")) == 1:
            des.append([L["os.DesignUser"], fi_show(names.get(fi_int(r.get("DesignUser"))))])
        des.append([L["design_result"], v["design_result"]])
        if not fi_blank(r.get("DesignDate")):
            des.append([L["os.DesignDate"], fi_day(fi_ts(r.get("DesignDate")))])
        blocks["design"] = dt_block("design", L["design_change"], des)
        stop = [[L["is_stop"], v["is_stop"]]]
        if v["_stopped_ever"]:
            stop += [[L["stop_status"], v["stop_status"]], [L["stop_date"], v["stop_date"]]]
        blocks["stop"] = dt_block("stop", T["stop_title"], stop)
        blocks["five_why"] = dt_block("five_why", "5Why", notes=[T["os_five_why"]])
        out.append({"domain": "海外", "id": pid, "number": v["_number"], "blocks": blocks, "order": order,
                    "material": False, "facts": {"驳回次数": rejects}})
    return out


# ---------------------------------------------------------------------------- 入口


def dt_tickets(data, P):
    """本步各域要看的单的详情块（`P["targets"]` 按域给编号或单 ID）。"""
    L, T = P["labels"], P["texts"]
    out = []
    for dom in P["domains"]:
        if dom == "国内":
            out += dt_cn(data, cn_enums(P["enums"]["国内"]), {**L, **P["names"]["国内"]}, T, P)
        elif dom == "巴西":
            out += dt_br(data, br_enums(P["enums"]["巴西"]), {**L, **P["names"]["巴西"]}, T, P)
        elif dom == "海外":
            out += dt_os(data, os_enums(P["enums"]["海外"]), {**L, **P["names"]["海外"]}, T, P)
    return out


def dt_cut(text, cut):
    text = str(text).replace("\n", " ")
    return text[:cut] + "…" if len(text) > cut else text


def dt_reason_text(block, L, cut=200):
    """「原因与措施」一块合成清单的一格（第 5 条前半：详情只要原因或措施时并进前一步的清单），内容与详情那一块相同：
    各项、5Why（国内有时附在后面，一问一答算一项）、说明；每项截到 `cut` 字。CAR 报告的链接不在这里拼。"""
    parts = [f"{item[0]}：{dt_cut(item[1], cut)}" for item in block["fields"]]
    for table in block["tables"]:
        cols = table["columns"]
        if L["fw.Question"] not in cols or L["fw.Reason"] not in cols:
            continue
        q, a = cols.index(L["fw.Question"]), cols.index(L["fw.Reason"])
        for row in table["rows"]:
            parts.append(dt_cut(f"{table['title']} {row[0]}. {cols[q]}：{row[q]}，{cols[a]}：{row[a]}", cut))
    parts += list(block["notes"])
    return "；".join(parts)
