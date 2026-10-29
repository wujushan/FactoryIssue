"""汇总统计（设计 §6.3、§8.1；总述「回答怎么组织」「统计口径说明」「汇总不良率」「结案时间与结案周期」）。

每域：视图 → 条件 → 时间 →（分组 → 各组指标）或（不分组 → 概况：单数、未结案、停线中、问题类型分布）。
比较两个时段时两段各算一遍，按时间先后给增减量与变化率。分组、Top N、并列、增减、平均与中位数都在这里算。
"""

from factory_issue_module.stats.lib.common import fi_rank, fi_round, fi_with_counts
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.views import (
    vw_bins,
    vw_counts,
    vw_days,
    vw_filter,
    vw_breakdowns,
    vw_group,
    vw_period,
    vw_period_range,
    vw_period_start,
    vw_rate,
    vw_time,
)

import pandas as pd

PARAMS = {}


def ag_metrics(sub, metrics, C):
    """一组单的指标：{列名: 值}，数都在这里算。"""
    out = {C["count"]: int(len(sub))}
    if "未结案数" in metrics:
        out[C["unclosed"]] = int((~sub["_done"].astype(bool)).sum()) if len(sub) else 0
    if "合计不良率" in metrics:
        rate, _excluded = vw_rate(sub)
        out[C["rate"]] = rate if rate is not None else "—"
    if "结案周期" in metrics:
        mean, median, _n = vw_days(sub, "_close_days")
        out[C["close_mean"]] = mean if mean is not None else "—"
        out[C["close_median"]] = median if median is not None else "—"
    if "停线时长" in metrics:
        mean, median, _n = vw_days(sub, "_stop_days")
        out[C["stop_mean"]] = mean if mean is not None else "—"
        out[C["stop_median"]] = median if median is not None else "—"
    return out


def ag_metric_facts(v, metrics):
    facts, caliber = {}, {}
    if "合计不良率" in metrics:
        rate, excluded = vw_rate(v)
        facts["合计不良率（%）"] = rate
        caliber["不良率不参与"] = excluded
    if "结案周期" in metrics:
        done = v[v["_done"].astype(bool)] if len(v) else v
        mean, median, n = vw_days(done, "_close_days")
        facts.update({"结案周期平均（天）": mean, "结案周期中位数（天）": median, "计入结案周期的单数": n,
                      "结案周期分档": vw_bins(done)})
        caliber["没有结案时间"] = int(len(done) - n)
    if "停线时长" in metrics:
        stopped = v[v["_stopped_ever"].astype(bool)] if len(v) else v
        mean, median, n = vw_days(stopped, "_stop_days")
        restarted = int(stopped["_restarted"].astype(bool).sum()) if len(stopped) else 0
        facts.update({"停线时长平均（天）": mean, "停线时长中位数（天）": median, "计入停线时长的单数": n,
                      "还没重启的单数": int(stopped["_stopped_now"].astype(bool).sum()) if len(stopped) else 0})
        caliber["已重启但没有重启日期"] = max(restarted - n, 0)
    return facts, caliber


def ag_dim_table(v, dim, A, C, period_bounds):
    """一个分组维度的表与图数据。"""
    groups = vw_group(v, dim)
    pairs = [(k, len(ids)) for k, ids in groups.items()]
    metrics = A["metrics"]
    top = A.get("top") or (A["top_n"] if A.get("ranking") else None)
    if dim.get("period"):
        order = vw_period_range(period_bounds[0], period_bounds[1], dim["period"]) if period_bounds else []
        starts = {}
        for ts in v[dim["period_col"]].tolist() if len(v) else []:
            label = vw_period(ts, dim["period"])
            if label is not None and label not in starts:
                starts[label] = vw_period_start(ts, dim["period"])
        rest = sorted((k for k in groups if k not in order), key=lambda k: (starts.get(k) or pd.Timestamp.max, k))
        known = list(dict.fromkeys(order + rest))
        kept = [(k, len(groups.get(k, ()))) for k in known]
        first, tied = [], []
        if kept:
            best = max(n for _k, n in kept)
            first = [k for k, n in kept if n == best]
    elif dim.get("order"):
        rank = {k: i for i, k in enumerate(dim["order"])}
        kept = sorted(pairs, key=lambda p: (rank.get(p[0], len(rank)), str(p[0])))
        _all, first, tied = fi_rank(pairs)
        if top:
            kept, first, tied = fi_rank(pairs, top)
    else:
        kept, first, tied = fi_rank(pairs, top)
        if not top and len(kept) > A["table_rows"]:
            kept, first, tied = fi_rank(pairs, A["table_rows"])
    rows, chart = [], []
    for name, _n in kept:
        sub = v[v["_id"].isin(groups.get(name, set()))] if len(v) else v
        m = ag_metrics(sub, metrics, C)
        if "占比" in metrics:
            m[C["share"]] = fi_round(len(sub) / len(v) * 100, 2) if len(v) else 0
        rows.append([name] + list(m.values()))
        chart.append({dim["title"]: name, **{k: x for k, x in m.items() if isinstance(x, (int, float))}})
    columns = [dim["title"]] + list(ag_metrics(v, metrics, C).keys())
    if "占比" in metrics:
        columns.append(C["share"])
    summed = sum(len(ids) for ids in groups.values())
    facts = {"按" + dim["title"]: [[k, n] for k, n in kept], "第一": first, "第一并列": len(first) > 1}
    if tied:
        facts["并列"] = tied
        facts["并列名次"] = int(top) if top else int(A["table_rows"])
    if len(groups) > len(kept):
        facts["分组总数"] = len(groups)
    caliber = {"多值归属": bool(dim.get("multi")) and summed > len(v), "各组合计": summed}
    if dim.get("multi"):
        facts["各组合计（一单可计入多组）"] = summed
    blank = int(len(v) - len({i for ids in groups.values() for i in ids}))
    if blank > 0:
        caliber["没有" + dim["title"]] = blank
    if dim.get("name") == "责任归属部门" and len(v):
        caliber["无需定责"] = int((v["resp_dept"] == "无需定责").sum())
        caliber["未定责"] = int((v["resp_dept"] == "未定责").sum())
        caliber["物料问题"] = int(v["_resp_material"].astype(bool).sum())
    return {"columns": columns, "rows": rows}, chart, facts, caliber, [k for k, _n in kept], first


def ag_compare(v_all, dom, A, C, dims):
    """比较两个时段：按时间先后，后一段减前一段为增减量，变化率 = 增减量 ÷ 前一段 × 100。"""
    a, b = A["compare"][dom]
    va, ma = vw_time(v_all, a["times"])
    vb, mb = vw_time(v_all, b["times"])
    ga = vw_group(va, dims[0]) if dims else {"合计": set(va["_id"]) if len(va) else set()}
    gb = vw_group(vb, dims[0]) if dims else {"合计": set(vb["_id"]) if len(vb) else set()}
    names = sorted(set(ga) | set(gb), key=lambda k: (-(len(ga.get(k, ())) + len(gb.get(k, ()))), str(k)))
    rows, increased_any = [], []
    for k in names:
        na, nb = len(ga.get(k, ())), len(gb.get(k, ()))
        diff = nb - na
        rate = f"{fi_round(diff / na * 100, 2):g}%" if na else "—"
        rows.append([k, na, nb, diff, rate])
        if diff > 0:
            increased_any.append(k)
    na_all, nb_all = int(len(va)), int(len(vb))
    if dims:
        diff = nb_all - na_all
        rows.append(["合计", na_all, nb_all, diff, f"{fi_round(diff / na_all * 100, 2):g}%" if na_all else "—"])
    title = dims[0]["title"] if dims else C["domain"]
    columns = [title, a["label"], b["label"], C["diff"], C["change"]]
    change = nb_all - na_all
    words = f"增加 {change} 张" if change > 0 else (f"减少 {-change} 张" if change < 0 else "持平")
    facts = {a["label"]: na_all, b["label"]: nb_all, "增减量": change, "变化": words,
             "变化率（%）": fi_round((nb_all - na_all) / na_all * 100, 2) if na_all else None,
             "增加的" + title: increased_any, "各组": [[r[0], r[1], r[2], r[3]] for r in rows]}
    caliber = {"未计入": ma + mb, "多值归属": bool(dims and dims[0].get("multi"))}
    # 画图用的行：两段各一组柱子，数取自上面的表；合计不画（会把各组压扁），增减量、变化率单位不同也不画
    if dims:
        chart = {"dimension": title, "series": [a["label"], b["label"]],
                 "rows": [{title: r[0], a["label"]: r[1], b["label"]: r[2]} for r in rows[:-1]]}
    else:
        chart = {"dimension": C["period"], "series": [C["count"]],
                 "rows": [{C["period"]: a["label"], C["count"]: na_all}, {C["period"]: b["label"], C["count"]: nb_all}]}
    return {"columns": columns, "rows": rows}, chart, facts, caliber, nb_all > na_all, increased_any


def run(data):
    P = PARAMS
    A = P["agg"]
    C = P["cols"]
    segments, missing_domains = [], []
    refs = {"top1": [], "top_values": [], "total": 0, "increased": False}
    for dom in P["domains"]:
        v = dm_view(dom, data, P)
        if v is None:
            missing_domains.append(dom)
            continue
        dims = A["dims"].get(dom) or []
        v = vw_filter(v, P["conds"].get(dom)) if len(v) else v
        if A.get("compare"):
            if len(v) == 0:
                segments.append({"domain": dom, "kind": "compare", "found": 0, "facts": {"总单数": 0}, "caliber": {}})
                continue
            table, chart, facts, caliber, inc, inc_values = ag_compare(v, dom, A, C, dims)
            refs["increased"] = refs["increased"] or inc
            refs["top_values"] += [x for x in inc_values if x not in refs["top_values"]]
            segments.append({"domain": dom, "kind": "compare", "title": table["columns"][0], "table": table,
                             "chart": chart, "multi": bool(dims and dims[0].get("multi")),
                             "found": facts[table["columns"][1]] + facts[table["columns"][2]],
                             "facts": fi_with_counts(facts), "caliber": caliber})
            continue
        missing = []
        if len(v):
            v, missing = vw_time(v, P["times"].get(dom))
        found = int(len(v))
        refs["total"] += found
        mfacts, mcal = ag_metric_facts(v, A["metrics"]) if found else ({}, {})
        if not dims:
            row = {C["domain"]: dom, C["count"]: found,
                   C["unclosed"]: int((~v["_done"].astype(bool)).sum()) if found else 0,
                   C["stopped"]: int(v["_stopped_now"].astype(bool).sum()) if found else 0}
            if found:
                extra = ag_metrics(v, A["metrics"], C)
                for k, x in extra.items():
                    row.setdefault(k, x)
            pairs, _f, _t = fi_rank(vw_counts(v, "type")) if found else ([], [], [])
            facts = {"总单数": found, "未结案": row[C["unclosed"]], "停线中": row[C["stopped"]],
                     "按问题类型": [list(p) for p in pairs], **mfacts}
            rejected = int(v["_rejected"].astype(bool).sum()) if found else 0
            if rejected:
                facts["未结案中生产角色驳回、流程已结束"] = rejected
            stopped = v[v["_stopped_now"].astype(bool)] if found else v
            stopped_done = int(stopped["_done"].astype(bool).sum()) if len(stopped) else 0
            # 概况写了未结案、停线中的张数，口径要写这两个说法怎么算（总述「统计口径说明」）
            ocal = {"未结案": row[C["unclosed"]], "生产角色驳回": rejected, "停线中": row[C["stopped"]],
                    "停线中且已完成": stopped_done}
            breakdowns = vw_breakdowns(v, P.get("breakdowns", {}).get(dom))
            if breakdowns:
                facts["分取值"] = breakdowns
            seg = {"domain": dom, "kind": "overview", "title": C["domain"],
                   "table": {"columns": list(row.keys()), "rows": [list(row.values())]},
                   "found": found, "facts": fi_with_counts(facts), "breakdowns": breakdowns,
                   "caliber": {"未计入": missing, **mcal, **ocal}}
            if "结案周期" in A["metrics"] and found:
                seg["bins"] = {"columns": [C["close_days"], C["count"]], "rows": mfacts.get("结案周期分档", [])}
                seg["chart"] = {"dimension": C["close_days"], "rows": [{C["close_days"]: k, C["count"]: n}
                                                                       for k, n in mfacts.get("结案周期分档", [])]}
            segments.append(seg)
            continue
        bounds = P.get("period_bounds", {}).get(dom)
        if bounds:
            bounds = [pd.Timestamp(bounds[0]) if bounds[0] else None, pd.Timestamp(bounds[1]) if bounds[1] else None]
            if (bounds[0] is None or bounds[1] is None) and found:
                col = dims[0].get("period_col") or "_add"
                vals = [x for x in v[col].tolist() if x is not None]
                if vals:
                    bounds = [bounds[0] or min(vals), bounds[1] or max(vals)]
        breakdowns = vw_breakdowns(v, P.get("breakdowns", {}).get(dom))
        for dim in dims:
            table, chart, facts, caliber, kept, first = ag_dim_table(v, dim, A, C, bounds)
            facts = {"总单数": found, **facts, **mfacts}
            if breakdowns:
                facts["分取值"] = breakdowns
            caliber = {"未计入": missing, **caliber, **mcal}
            refs["top1"] += [x for x in first if x not in refs["top1"]]
            refs["top_values"] += [x for x in kept if x not in refs["top_values"]]
            segments.append({"domain": dom, "kind": "group", "title": dim["title"], "multi": bool(dim.get("multi")),
                             "table": table, "chart": {"dimension": dim["title"], "rows": chart},
                             "groups": len(table["rows"]), "found": found, "facts": fi_with_counts(facts),
                             "breakdowns": breakdowns, "caliber": caliber})
    return {"segments": segments, "refs": refs, "missing_domains": missing_domains}
