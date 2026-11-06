"""文字查找的按词一路（设计 §7.1 ②；总述「关键词搜索与类似问题」「涉及某个话题怎么找」「点名字段时怎么找」；
`topic_terms.md`「怎么读」）。

每域：视图 → 条件 → 时间（与清单同一套，得出本步范围内、源上仍在的单）→ 在这些单的段里逐段精确匹配（SQL 已用
去空格的文字预筛过，是超集）→ 按单归组、计数。

- 「涉及某个话题」：命中第一组栏目（问题现象、问题描述、原因）的归「问题本身涉及」，只在其余栏目命中的归「处理中
  提到」；带 ＊ 的说法只在第一组栏目命中、且不在前两组的单，作「可能相关」的候选。
- 关键词：「和」要求每个词都在这张单里出现，「或」出现任一。
- 点名字段、问做法：只在点名的栏目或措施类栏目里找；点名问题描述、问题现象、原因时带 ＊ 的命中作补充的候选。
- 问做法又说了现象：做法、现象各找一遍，两边都命中的单列入；只有做法命中的作「可能相关」的候选。
- 国内停线状态为重启审核中、责任人填写重启方案的单，重启方案与处理步骤里重启那三个环节的条目不参与匹配
  （国内「停线」）。

返回值：各域张数与几域相加（`totals`，按钮上的张数）；明细经数据帧通道回传（`kw_<域>` 每单一行：单 ID、组、命中的说法、栏目、上下文；`star_<域>`、
`appr_<域>` 候选；`cand_<域>` 本步范围内的单 ID，按意思一路限定候选用）。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import fi_int, fi_records
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.textmatch import tx_body, tx_lines, tx_match
from factory_issue_module.stats.lib.views import vw_filter, vw_time

PARAMS = {}

KM_KW_COLS = ["issue_id", "grp", "terms", "where", "context"]
KM_CAND_COLS = ["issue_id", "context"]


def km_pieces(dom, data, K, alive, hidden):
    """本域每张单的文字：{单 ID: [(栏目键, 栏目名, 第几组, 文字)]}。只要范围内的单。"""
    titles = K["titles"].get(dom) or {}
    group_of = {c: g for g, codes in K["groups"].items() for c in codes}
    out = {}
    seg = data.get("seg_" + dom)
    if seg is not None and len(seg):
        for r in fi_records(seg):
            iid = fi_int(r.get("issue_id"))
            if iid is None or iid not in alive:
                continue
            code = str(r.get("field") or "")
            title = titles.get(code, code)
            out.setdefault(iid, []).append((code, title, group_of.get(code), tx_body(r.get("seg_text"), title)))
    txt = data.get("txt_" + dom)
    restart = K.get("restart") or {}
    col_titles = K["col_titles"].get(dom) or {}
    if txt is not None and len(txt):
        cols = [c for c in txt.columns if c != "issue_id"]
        for r in fi_records(txt):
            iid = fi_int(r.get("issue_id"))
            if iid is None or iid not in alive:
                continue
            for col in cols:
                text = str(r.get(col) or "")
                if not text.strip():
                    continue
                if iid in hidden and col in (restart.get("columns") or []):
                    continue
                if col in (restart.get("step_columns") or []):
                    heads = (restart.get("step_heads") or []) if iid in hidden else []
                    for line in tx_lines(text, heads):
                        out.setdefault(iid, []).append((col, col_titles.get(col, col), None, line))
                    continue
                out.setdefault(iid, []).append((col, col_titles.get(col, col), None, text))
    return out


def km_probe(pieces, probe):
    """一组说法在一张单里的命中：(不带 ＊ 的命中, 带 ＊ 的命中)，每项 (栏目键, 栏目名, 第几组, 说法, 上下文)。"""
    keys = set(probe.get("codes") or []) | set(probe.get("columns") or [])
    scope_all = probe.get("codes") is None and not probe.get("columns")
    plain = [t for t in probe["terms"] if not t.get("amb")]
    amb = [t for t in probe["terms"] if t.get("amb")] if probe.get("stars") else []
    hits, stars = [], []
    for key, title, grp, text in pieces:
        if not scope_all and key not in keys:
            continue
        if scope_all and grp is None:
            continue  # 文字表的列只在点名时比对
        for term, ctx in tx_match(text, plain, probe.get("excluded") or []):
            hits.append((key, title, grp, term, ctx))
        if grp == "first":
            for term, ctx in tx_match(text, amb, probe.get("excluded") or []):
                stars.append((key, title, grp, term, ctx))
    return hits, stars


def km_ok(hits, probe):
    if not hits:
        return False
    if probe.get("logic") == "和":
        return {t["raw"] for t in probe["terms"]} <= {h[3] for h in hits}
    return True


def km_row(iid, grp, hits):
    """每单一行：组、命中的说法（去重）、栏目（去重）、第一处命中的上下文（第一组的在前）。"""
    ordered = sorted(hits, key=lambda h: 0 if h[2] == "first" else 1)
    terms = []
    wheres = []
    for h in ordered:
        if h[3] not in terms:
            terms.append(h[3])
        if h[1] not in wheres:
            wheres.append(h[1])
    first = ordered[0]
    return [iid, grp, "、".join(terms), "、".join(wheres), first[1] + "：" + first[4]]


def km_frame(rows, cols):
    if not rows:
        return pd.DataFrame({c: pd.Series([], dtype="object") for c in cols})
    return pd.DataFrame(rows, columns=cols)


def run(data):
    P = PARAMS
    K = P["kw"]
    probes = K["probes"]
    main = next((p for p in probes if p["name"] == "main"), None)
    approach = next((p for p in probes if p["name"] == "approach"), None)
    counts, totals, frames = {}, {}, {}
    for dom in P["domains"]:
        v = dm_view(dom, data, P)
        if v is None:
            continue
        if len(v):
            v = vw_filter(v, P["conds"].get(dom))
            v, _missing = vw_time(v, P["times"].get(dom))
        alive = set(int(x) for x in v["_id"].tolist()) if len(v) else set()
        restart = K.get("restart") or {}
        hidden = set()
        if dom == restart.get("domain") and len(v) and "_stop_code" in v.columns:
            stops = set(restart.get("stops") or [])
            hidden = {int(i) for i, s in zip(v["_id"].tolist(), v["_stop_code"].tolist()) if fi_int(s) in stops}
        pieces = km_pieces(dom, data, K, alive, hidden)
        rows, stars, appr = [], [], []
        c = {"hit": 0, "g1": 0, "g2": 0, "star": 0, "both": 0, "approach": 0, "topic": 0}
        if not probes:  # 只要本步范围内的单（类似问题带条件时限定候选用）
            pieces = {}
        for iid in sorted(pieces):
            items = pieces[iid]
            if K.get("intersect") and main is not None and approach is not None:
                t_hits, _s = km_probe(items, main)
                a_hits, _s = km_probe(items, approach)
                t_ok, a_ok = km_ok(t_hits, main), km_ok(a_hits, approach)
                c["topic"] += int(t_ok)
                c["approach"] += int(a_ok)
                if t_ok and a_ok:
                    row = km_row(iid, 0, a_hits)
                    row[4] = row[4] + "｜" + km_row(iid, 0, t_hits)[4]
                    row[2] = "、".join(dict.fromkeys(row[2].split("、") + km_row(iid, 0, t_hits)[2].split("、")))
                    rows.append(row)
                    c["both"] += 1
                elif a_ok:
                    appr.append([iid, km_row(iid, 0, a_hits)[4]])
                continue
            probe = main if main is not None else approach
            hits, star_hits = km_probe(items, probe)
            if km_ok(hits, probe):
                if K.get("grouped"):
                    grp = 1 if any(h[2] == "first" for h in hits) else 2
                    c["g1" if grp == 1 else "g2"] += 1
                else:
                    grp = 0
                rows.append(km_row(iid, grp, hits))
                c["hit"] += 1
            elif star_hits:
                stars.append([iid, km_row(iid, 3, star_hits)[4]])
                c["star"] += 1
        counts[dom] = c
        for k, n in c.items():
            totals[k] = totals.get(k, 0) + n
        frames["kw_" + dom] = km_frame(rows, KM_KW_COLS)
        frames["star_" + dom] = km_frame(stars, KM_CAND_COLS)
        frames["appr_" + dom] = km_frame(appr, KM_CAND_COLS)
        if K.get("cand"):
            frames["cand_" + dom] = pd.DataFrame({"_id": sorted(alive)})
    return {"counts": counts, "totals": totals, **frames}
