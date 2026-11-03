"""文字查找的收拢（设计 §7.1 ⑥；总述「涉及某个话题怎么找」「命中后带回什么与时效」「跨域规则」清单呈现）。

每域：视图 → 条件 → 时间（与按词一路同一套）→ 按词命中的单（`kw_<域>`）与按意思找到、判断为相关的单（`sem_<域>`）
合起来：前两组（或按词找到的）按建单时间倒序，「可能相关」按重排分（没有时按向量分）从高到低、同分按问题编号、
最多 `third_max` 张；类似问题只有按意思一路，判断为相近、重排分不低于下限的同样排、最多 `sim_max` 张（决策
2026-11-03「类似问题逐张判断与分数下限」）。各组张数、表格、分析用的事实都在这里算。

表格给前两组各自最近的 `table_rows` 张（不分组时按词找到的最近 `table_rows` 张），再接上「可能相关」的全部
（不超过 `third_max`）；要导出时全部行经数据帧通道回传
（`export_<域>`），结果单同样（`ids_<域>`），不塞进 `result`。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import fi_int, fi_num, fi_rank, fi_round, fi_with_counts
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.views import vw_counts, vw_filter, vw_sorted, vw_time

PARAMS = {}


def tm_hits(frame):
    """按词一路的明细帧 → {单 ID: (组, 上下文)}。"""
    out = {}
    if frame is None or len(frame) == 0:
        return out
    for r in frame.to_dict("records"):
        iid = fi_int(r.get("issue_id"))
        if iid is not None:
            out[iid] = (int(fi_int(r.get("grp")) or 0), str(r.get("context") or ""))
    return out


def tm_sem(frame, threshold, related_only):
    """按意思一路的明细帧 → [(单 ID, 上下文, 分数)]，按先后（`rank`）。分数取重排分，没有时取向量分（重排出错时
    平台退回向量顺序），都没有为 None（带 ＊ 的候选在向量表里没有段）。判断为不相关、重排分低于阈值的不要。"""
    if frame is None or len(frame) == 0:
        return []
    rows = []
    for r in frame.to_dict("records"):
        iid = fi_int(r.get("issue_id"))
        if iid is None:
            continue
        if related_only and not bool(r.get("related")):
            continue
        rerank = fi_num(r.get("rerank"))
        if threshold is not None and rerank is not None and rerank < float(threshold):
            continue
        value = rerank if rerank is not None else fi_num(r.get("score"))
        rows.append((int(fi_int(r.get("rank")) or 0), iid, str(r.get("context") or ""), value))
    rows.sort(key=lambda x: x[0])
    return [(iid, ctx, value) for _rank, iid, ctx, value in rows]


def tm_scores(frame):
    """按意思一路的明细帧 → {单 ID: [重排分, 向量分, 判断]}（分数保留 4 位小数，没有的为 None；判断 1 相近、0 不相近、
    None 没交去判断或那一批出错）。只给类似问题的分数日志用（探测 Z1 起记）：沙箱外只记日志，不进回答。"""
    out = {}
    if frame is None or len(frame) == 0:
        return out
    for r in frame.to_dict("records"):
        iid = fi_int(r.get("issue_id"))
        if iid is not None and iid not in out:
            verdict = (1 if bool(r.get("related")) else 0) if bool(r.get("judged")) else None
            out[iid] = [fi_round(fi_num(r.get("rerank")), 4), fi_round(fi_num(r.get("score")), 4), verdict]
    return out


def tm_order(sem, numbers):
    """按分数从高到低，同分按问题编号（同一查询两次给出的前几张一样）；没有分数的排在最后、保持原来的先后。"""
    scored = [x for x in sem if x[2] is not None]
    rest = [x for x in sem if x[2] is None]
    scored.sort(key=lambda x: (-float(x[2]), numbers.get(x[0], "")))
    return scored + rest


def tm_facts(v):
    if not len(v):
        return {"张数": 0}
    pairs_type, _f, _t = fi_rank(vw_counts(v, "type"))
    pairs_machine, _f, _t = fi_rank(vw_counts(v, "_machines", multi=True), 5)
    facts = {"张数": int(len(v)), "按问题类型": [list(p) for p in pairs_type],
             "按机型（前五）": [list(p) for p in pairs_machine[:5]],
             "未结案": int(v["_unclosed"].astype(bool).sum())}
    return fi_with_counts(facts)


def tm_rows(v, cols):
    return [[r[c] for c in cols] for _, r in v.iterrows()]


def tm_ids(v):
    if not len(v):
        return pd.DataFrame({"_id": pd.Series([], dtype="int64"), "_number": pd.Series([], dtype="object")})
    return pd.DataFrame({"_id": [int(x) for x in v["_id"].tolist()], "_number": [str(x) for x in v["_number"].tolist()]})


def run(data):
    P = PARAMS
    T = P["tm"]
    labels = T["labels"]
    segments, frames, by_domain = [], {}, []
    pending = {}
    totals = {"kw": 0, "g1": 0, "g2": 0, "g3": 0, "listed": 0}
    for dom in P["domains"]:
        v = dm_view(dom, data, P)
        if v is None:
            continue
        missing = []
        if len(v):
            v = vw_filter(v, P["conds"].get(dom))
            v, missing = vw_time(v, P["times"].get(dom))
        hits = tm_hits(data.get("kw_" + dom))
        sim = bool(T.get("sim"))
        # 判断为相近（相关）、重排分不低于阈值的才要；类似问题的阈值是它自己的下限（决策 2026-11-03）
        sem = tm_sem(data.get("sem_" + dom), T.get("threshold"), True)
        numbers = {int(i): str(n) for i, n in zip(v["_id"].tolist(), v["_number"].tolist())} if len(v) else {}
        # 先去掉不在本步范围里的（已删除、不合条件），排好再截条数：不让它们占掉名额
        sem = tm_order([x for x in sem if x[0] not in hits and x[0] in numbers], numbers)
        # 类似问题：本步范围内全部候选的分数与判断（筛之前，按相近程度排），只进日志
        sem_scores = []
        if sim:
            got = tm_scores(data.get("sem_" + dom))
            every = tm_order([x for x in tm_sem(data.get("sem_" + dom), None, False) if x[0] in numbers], numbers)
            sem_scores = [got.get(i, [None, None, None]) for i, _c, _v in every]
        sem = [(i, c) for i, c, _v in sem][: int(T["sim_max"] if sim else T["third_max"])]
        vk = v[v["_id"].apply(lambda x: int(x) in hits)].copy() if len(v) else v.copy()
        if len(vk):
            vk["_grp"] = [hits[int(x)][0] for x in vk["_id"].tolist()]
            vk["_group"] = [labels.get(str(g), "") for g in vk["_grp"].tolist()]
            vk["_context"] = [hits[int(x)][1] for x in vk["_id"].tolist()]
            vk = vw_sorted(vk, "_add", True)
            vk = vk.sort_values("_grp", kind="mergesort")
        order = {iid: k for k, (iid, _c) in enumerate(sem)}
        ctx3 = dict(sem)
        v3 = v[v["_id"].apply(lambda x: int(x) in order)].copy() if len(v) else v.copy()
        if len(v3):
            v3["_grp"] = 3
            v3["_group"] = labels.get("3", "")
            v3["_context"] = [ctx3[int(x)] for x in v3["_id"].tolist()]
            v3["_rank"] = [order[int(x)] for x in v3["_id"].tolist()]
            v3 = v3.sort_values("_rank", kind="mergesort")
        cols = T["columns"][dom]
        names = {**P["names"][dom], "_group": T["group_title"], "_context": T["context_title"]}
        rows_max = int(T["table_rows"])
        # 前两组各给最近 `table_rows` 张：第一组多时不把第二组挤出表格（S6b 评审 M1）；不分组时就是按词找到的前几张
        parts = [vk[vk["_grp"] == g].head(rows_max) for g in sorted(set(vk["_grp"].tolist()))] if len(vk) else []
        head_k = pd.concat(parts) if parts else vk.head(rows_max)
        shown_g1 = int((head_k["_grp"] == 1).sum()) if len(head_k) else 0
        shown_g2 = int((head_k["_grp"] == 2).sum()) if len(head_k) else 0
        shown = pd.concat([head_k, v3]) if len(v3) else head_k
        rows = tm_rows(shown, cols)
        everything = pd.concat([vk, v3]) if len(v3) else vk
        n_kw, n3 = int(len(vk)), int(len(v3))
        g1 = int((vk["_grp"] == 1).sum()) if len(vk) else 0
        g2 = int((vk["_grp"] == 2).sum()) if len(vk) else 0
        listed = n_kw + n3
        if listed > 0:  # 要不要导出在各域都列完之后定（列出的每个域都进文件）
            pending["export_" + dom] = (everything, cols, names)
        frames["ids_" + dom] = tm_ids(everything)
        facts = tm_facts(everything)
        segments.append({
            "domain": dom, "table": {"columns": [names[c] for c in cols], "rows": rows},
            "found": listed, "kw": n_kw, "g1": g1, "g2": g2, "g3": n3, "shown": int(len(shown)),
            "shown_kw": int(len(head_k)), "shown_g1": shown_g1, "shown_g2": shown_g2,
            "cut_g1": shown_g1 < g1, "cut_g2": shown_g2 < g2,
            "ids_shown": [int(x) for x in shown["_id"].tolist()] if len(shown) else [],
            # 表格每行是否未结案（与行同序）：交写结论的模型看，点名时说清结案没有（决策 2026-11-03「回答骨架与排版」）
            "open_shown": [bool(x) for x in shown["_unclosed"].tolist()] if len(shown) else [],
            "truncated": int(len(head_k)) < n_kw, "empty": listed == 0, "few": listed <= 2,
            "exported": False, "facts": facts, "caliber": {"未计入": missing},
            **({"sem_scores": sem_scores} if sim else {}),
        })
        by_domain.append([dom, n_kw])
        for k, n in (("kw", n_kw), ("g1", g1), ("g2", g2), ("g3", n3), ("listed", listed)):
            totals[k] += n
    # 导出（同清单）：用户明说，或某域按词找到的超过阈值时，列出的每个域都进文件、每域一页
    want = bool(T.get("export_ok")) and (
        bool(T.get("export")) or any(s["kw"] > int(T.get("export_threshold") or 0) for s in segments))
    if want:
        for s in segments:
            got = pending.get("export_" + s["domain"])
            if got is not None:
                s["exported"] = True
                everything, cols, names = got
                frames["export_" + s["domain"]] = pd.DataFrame(tm_rows(everything, cols),
                                                                columns=[names[c] for c in cols])
    refs = {"count": totals["listed"], "found": {s["domain"]: s["found"] for s in segments}}
    return {"segments": segments, "refs": refs, "totals": totals, "by_domain": by_domain,
            "exported": [[s["domain"], s["found"]] for s in segments if s["exported"]], **frames}
