"""按号查单（设计 §6.3 `lookup_numbers` 一行、§8.1；总述「按编号查单」、国内「按订单号查单」「按 CAR 编号查单」、
海外「按发货单号、PO 查单」、巴西「投诉单号」）。

SQL 已按号精确匹配取回挂着号的子表行与要列的单（假连接器不执行 WHERE，这里再对一遍）；这里逐个号、逐种号、
逐域对出单，拼成表：
- 问题编号：一号一行，列用清单默认列另加所属域与当前状态（几个号合成一张表）；7 位数字补上前缀按问题编号查时
  还有发货单号，与其余各种号一样每域一张表，所以两种行都给。
- 其余每种号每个域一张表：问题编号、问题类型、当前状态、机型，加上这张单上挂着这个号的明细（生产订单给 PN 与
  订单数量，小板订单给料号、物料描述与订单数量，发货单给 PO、发货单号、发货日期、PN、订单数量……）；同一张单上
  这个号有多行时合成一行。并给问题类型、是否结案的分布。
- 巴西投诉单号：两边都不分大小写、去掉全部空格后精确比（点、斜杠、连字符照原样）。
- 国内手填的带连字符的订单号：给的号查不到、但有以「该号-」开头的号时给出这些号（编排请用户选）；问句末尾带着
  点按钮选回的号时按它查。
- 一次给很多个问题编号（`as_list`，S5）：按清单呈现，按域分开列、域内按建单时间从新到旧，全量作为明细帧回传。
"""

import re

import pandas as pd

from factory_issue_module.stats.lib.common import fi_group, fi_int, fi_lookup, fi_records, fi_show, fi_unique, fi_with_counts
from factory_issue_module.stats.lib.derive_brazil import br_latest
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.views import vw_counts, vw_sorted

PARAMS = {}


def lk_up(x):
    return str(x if x is not None else "").strip().upper()


def lk_claim(x):
    return re.sub(r"\s+", "", str(x if x is not None else "")).upper()


def lk_state(v, dom):
    """当前状态：国内为环节 + 人，巴西、海外为主表状态（术语表「当前状态」）。"""
    return v["status"] if dom == "巴西" else v["current_state"]


def lk_pn(code, name):
    return " ".join(x for x in (fi_show(name, ""), fi_show(code, "")) if x) or "未填"


def lk_group_text(rows, cols):
    """同一张单上这个号的几行合成一格一格：各列取值去重后用「、」连。"""
    return ["、".join(fi_unique([fi_show(r.get(c)) for r in rows])) for c in cols]


def lk_match(lk, dom, view, data, L, P):
    """一种号在一域里对上的单：(明细列名, {单 ID: [明细…]}, 手填订单号候选)。"""
    kind, value = lk["kind"], str(lk["value"])
    up = lk_up(value)
    hits, cols, candidates = {}, [], []
    rows = [v for _, v in view.iterrows()] if len(view) else []
    if kind == "issue":
        for v in rows:
            if lk_up(v["_number"]) == up:
                hits[int(v["_id"])] = []
    elif kind == "car":
        cols = [L["car"]]
        for v in rows:
            if lk_up(v["car"]) == up:
                hits[int(v["_id"])] = [v["car"]]
    elif kind == "inv":
        cols = [L["inv_code"]]
        for v in rows:
            codes = list(v["_inv_codes"] or []) if dom == "海外" else [v["inv_code"]]
            if any(lk_up(c) == up for c in codes):
                hits[int(v["_id"])] = [value]
    elif kind in ("pn_code", "pn_name"):
        cols = [L["pn"]]
        if dom == "国内":
            got = {}
            for o in fi_records(data.get("cn_hit_orders")):
                ok = lk_up(o.get("PartNumber")) == up if kind == "pn_code" else lk_up(o.get("PartName")) == up
                if ok and fi_int(o.get("ProblemId")) is not None:
                    got.setdefault(fi_int(o.get("ProblemId")), []).append(lk_pn(o.get("PartNumber"), o.get("PartName")))
            hits = {k: ["、".join(fi_unique(x))] for k, x in got.items()}
        else:
            if kind == "pn_code":
                codes = {up}
            else:
                codes = {lk_up(p.get("PartNumber")) for p in fi_records(data.get("lk_pns")) if lk_up(p.get("Name")) == up}
            for v in rows:
                if any(lk_up(c) in codes for c in (v["_pn_codes"] or [])):
                    hits[int(v["_id"])] = [v["pn"]]
    elif kind in ("prod_order", "xb_order"):
        frame = "cn_hit_orders" if kind == "prod_order" else "cn_hit_xb"
        recs = fi_records(data.get(frame))
        mine = [o for o in recs if lk_up(o.get("OrderNumber")) == up]
        if kind == "prod_order" and not mine and re.fullmatch(r"\d{6}", value):
            candidates = sorted(fi_unique([str(o.get("OrderNumber")).strip() for o in recs
                                           if str(o.get("OrderNumber") or "").strip().startswith(value + "-")]))
            chosen = P.get("chosen")
            if chosen in candidates:
                mine = [o for o in recs if str(o.get("OrderNumber") or "").strip() == chosen]
                candidates = []
        by = fi_group(mine, "ProblemId")
        if kind == "prod_order":
            cols = [L["ord.OrderNumber"], L["pn"], L["ord.OrderQty"]]
            for pid, items in by.items():
                hits[pid] = ["、".join(fi_unique([fi_show(o.get("OrderNumber")) for o in items])),
                             "、".join(fi_unique([lk_pn(o.get("PartNumber"), o.get("PartName")) for o in items])),
                             "、".join(fi_show(o.get("OrderQty")) for o in items)]
        else:
            cols = [L["xb.InvCode"], L["xb.InvStd"], L["xb.Qty"]]
            for pid, items in by.items():
                hits[pid] = lk_group_text(items, ("InvCode", "InvStd", "Qty"))
    elif kind in ("delivery", "po"):
        cols = [L["osd.PO"], L["osd.OrderNumber"], L["osd.Date"], L["osd.PN"], L["osd.Quantity"]]
        pn_names = fi_lookup(data.get("pns"), "PartNumber", "Name")
        mine = [d for d in fi_records(data.get("os_hit_delivery"))
                if lk_up(d.get("OrderNumber" if kind == "delivery" else "PO")) == up]
        for pid, items in fi_group(mine, "ProblemId").items():
            items = sorted(items, key=lambda d: (str(d.get("OrderNumber") or ""), fi_int(d.get("Id")) or 0))
            pns = [lk_pn(d.get("PN"), pn_names.get(str(d.get("PN") or "").strip())) for d in items]
            hits[pid] = ["、".join(fi_unique([fi_show(d.get("PO")) for d in items])),
                         "、".join(fi_unique([fi_show(d.get("OrderNumber")) for d in items])),
                         "、".join(fi_unique([fi_show(d.get("Date")) for d in items])),
                         "、".join(fi_unique(pns)), "、".join(fi_show(d.get("Quantity")) for d in items)]
    elif kind == "claim":
        cols = [L["claim"]]
        want = lk_claim(value)
        for v in rows:
            if v["claim"] != "未填" and lk_claim(v["claim"]) == want:
                hits[int(v["_id"])] = [v["claim"]]
    elif kind in ("debit", "instore"):
        col = "DebitNumber" if kind == "debit" else "InStoreNumber"
        cols = [L["brp." + col]]
        for pid, items in fi_group(fi_records(data.get("br_hit_process")), "ProblemID").items():
            latest = br_latest(items)
            if latest is not None and lk_up(latest.get(col)) == up:
                hits[pid] = [fi_show(latest.get(col))]
    return cols, hits, candidates


def lk_section(lk, dom, view, data, L, P):
    cols, hits, candidates = lk_match(lk, dom, view, data, L, P)
    sub = view[view["_id"].isin([int(i) for i in hits])] if len(view) and hits else view.iloc[0:0] if len(view) else view
    sub = vw_sorted(sub, "_add", True) if len(sub) else sub
    rows, ids, car_ids = [], [], []
    car_of = {fi_int(r.get("ID")): fi_int(r.get("CARID")) for r in fi_records(data.get("cn_main"))} \
        if dom == "国内" and lk["kind"] == "car" else {}
    issue_rows = []
    for _, v in sub.iterrows() if len(sub) else []:
        pid = int(v["_id"])
        ids.append(pid)
        # 问题编号两张表都填：只有这一种号时编排用合并表那一行，7 位数字（还有发货单号）走每种号一张表
        if lk["kind"] == "issue":
            issue_rows.append([v["number"], dom, lk_state(v, dom), v["machine"], v["type"], v["rate"], v["bad_qty"],
                               v["desc"]])
        rows.append([v["number"], v["type"], lk_state(v, dom), v["machine"], *hits.get(pid, [])])
        car_ids.append(car_of.get(pid))
    base = [L["number"], L["type"], L["current_state"], L["machine"]]
    facts = {"张数": len(ids)}
    if len(sub):
        facts["按问题类型"] = [list(p) for p in sorted(vw_counts(sub, "type"), key=lambda p: (-p[1], str(p[0])))]
        closed = vw_counts(sub, "_closed_label")
        order = {"未结案": 0, "已结案": 1}
        facts["是否结案"] = [list(p) for p in sorted(closed, key=lambda p: (order.get(p[0], 9), str(p[0])))]
    return {"i": lk["i"], "kind": lk["kind"], "domain": dom, "value": lk["value"], "found": len(ids),
            "columns": base + cols, "rows": rows, "ids": ids, "car_ids": car_ids, "issue_rows": issue_rows,
            "candidates": candidates, "facts": fi_with_counts(facts)}


def run(data):
    P = PARAMS
    L = P["labels"]
    views = {}
    for dom in P["domains"]:
        v = dm_view(dom, data, P)
        if v is not None:
            views[dom] = v
    sections, issues = [], {}
    for lk in P["lookups"]:
        dom = lk["domain"]
        if dom not in views:
            continue
        sec = lk_section(lk, dom, views[dom], data, {**L, **P["names"][dom]}, P)
        sections.append(sec)
        got = issues.setdefault(dom, {"ids": [], "numbers": []})
        view = views[dom]
        for pid in sec["ids"]:
            if pid not in got["ids"]:
                got["ids"].append(pid)
                got["numbers"].append(str(view[view["_id"] == pid]["_number"].iloc[0]))
    # 各域找到几张（工作区存下供质疑重查比对，设计 §10）
    found = {dom: len(got["ids"]) for dom, got in issues.items()}
    out = {"sections": sections, "refs": {"issues": issues, "found": found}}
    if P.get("as_list"):
        out.update(lk_as_list(sections, views, L, P))
    return out


def lk_as_list(sections, views, L, P):
    """一次给很多个问题编号（总述「按编号查单」：超过约 20 个时按清单呈现，全量导出）：按问题编号找到的单按域
    分开列，域内按建单时间从新到旧，表格给前 `table_rows` 张；该域全部行作为明细帧（`export_<域>`，同序的单 ID 在
    `ids_<域>`）回传。"""
    limit = int(P["as_list"]["table_rows"])
    lists, frames, total = [], {}, 0
    for dom, view in views.items():
        ids = [i for s in sections if s["kind"] == "issue" and s["domain"] == dom for i in s["ids"]]
        if not ids:
            continue
        sub = vw_sorted(view[view["_id"].isin(ids)], "_add", True)
        names = {**L, **P["names"][dom]}
        cols = [names["number"], names["current_state"], names["machine"], names["type"], names["rate"],
                names["bad_qty"], names["desc"]]
        rows = [[v["number"], lk_state(v, dom), v["machine"], v["type"], v["rate"], v["bad_qty"], v["desc"]]
                for _, v in sub.iterrows()]
        lists.append({"domain": dom, "found": len(rows), "shown": min(len(rows), limit), "columns": cols,
                      "rows": rows[:limit], "ids_shown": [int(x) for x in sub["_id"].tolist()[:limit]]})
        frames["export_" + dom] = pd.DataFrame(rows, columns=cols)
        # 与导出帧同序：编排按它把导出文件的问题描述换成全文（S6b）
        frames["ids_" + dom] = pd.DataFrame({"_id": [int(x) for x in sub["_id"].tolist()],
                                             "_number": [str(x) for x in sub["_number"].tolist()]})
        total += len(rows)
    return {"as_list": lists, "as_list_total": total,
            "as_list_counts": [[x["domain"], x["found"]] for x in lists], **frames}
