"""汇总统计（设计 §6.3、§6.4、§8.1；总述「跨域规则」「跨域归并」「回答怎么组织」「统计口径说明」「汇总不良率」
「结案时间与结案周期」，巴西「费用」）。

每域：视图 → 条件 → 时间 →（分组 → 各组指标）或（不分组 → 概况：单数、未结案、停线中、问题类型分布）。
比较两个时段时两段各算一遍，按时间先后给增减量与变化率。分组、Top N、并列、增减、平均与中位数都在这里算。

三域一起统计（本步有两个及以上的域）时：
- 不分组或按域分：一张表，一域一行再加合计一行；问题类型分布按名称同名合并。
- 按可以同名合并的维度（问题类型、等级、机型、加工厂、跟进部门、时间等，维度说明里 `merge` 为真）：合成一张表，
  每域一列（该域的单数，没有这一项写「—」），最后一列「单数」是合计，排名按合计。不良率不合成跨域的数（国内、巴西分母不同），
  要不良率时按域分别给。
- 按各域取值不同的维度（处理环节、状态等）：按域分别给，每域一张。
- 比较两个时段：各组两段的单数按域相加。
各域能算哪些指标看 `PARAMS["traits"]`：海外不良率是单上原文、不汇总，要不良率时逐单列出原文。
"""

from factory_issue_module.stats.lib.common import fi_rank, fi_round, fi_with_counts
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.insights import in_insights
from factory_issue_module.stats.lib.views import (
    vw_bins,
    vw_breakdowns,
    vw_counts,
    vw_days,
    vw_filter,
    vw_group,
    vw_period,
    vw_period_range,
    vw_period_start,
    vw_merge_missing,
    vw_rate,
    vw_rate_list,
    vw_time,
)

import pandas as pd

PARAMS = {}


def ag_supported(metrics, T):
    """本域能算的指标（按请求的顺序）。"""
    have = set((T or {}).get("metrics") or [])
    return [m for m in metrics if m in have]


def ag_sum(sub, col):
    if len(sub) == 0 or col not in sub.columns:
        return 0
    return float(sum(x for x in sub[col].tolist() if x is not None and not pd.isna(x)))


def ag_metrics(sub, metrics, C):
    """一组单的指标：{列名: 值}，数都在这里算。"""
    out = {C["count"]: int(len(sub))}
    if "未结案数" in metrics:
        out[C["unclosed"]] = int(sub["_unclosed"].astype(bool).sum()) if len(sub) else 0
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
    if "费用美元" in metrics:
        out[C["usd"]] = fi_round(ag_sum(sub, "_usd"), 2)
    if "费用雷亚尔" in metrics:
        out[C["brl"]] = fi_round(ag_sum(sub, "_brl"), 2)
    if "扣款" in metrics:
        out[C["debit"]] = fi_round(ag_sum(sub, "_debit"), 2)
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
    if "费用美元" in metrics or "费用雷亚尔" in metrics:
        costed = v[v["_has_cost"].astype(bool)] if len(v) else v
        facts["涉及费用的单数"] = int(len(costed))
        caliber["涉及费用的单"] = int(len(costed))
    if "费用美元" in metrics:
        facts["费用美元合计"] = fi_round(ag_sum(v, "_usd"), 2)
        only_brl = v[v.apply(lambda r: (r["_usd"] or 0) <= 0 and (r["_brl"] or 0) > 0, axis=1)] if len(v) else v
        if len(only_brl):
            facts["只产生雷亚尔费用的单数"] = int(len(only_brl))
            facts["这些单的雷亚尔合计"] = fi_round(ag_sum(only_brl, "_brl"), 2)
    if "费用雷亚尔" in metrics:
        facts["费用雷亚尔合计"] = fi_round(ag_sum(v, "_brl"), 2)
    if "扣款" in metrics:
        facts["扣款费用（美元）合计"] = fi_round(ag_sum(v, "_debit"), 2)
        caliber["扣款"] = True
    return facts, caliber


def ag_rate_list(v, P, dom, C):
    """海外不良率是单上原文、不汇总：逐单列出原文（`views.vw_rate_list`，临时统计也用它）。"""
    return vw_rate_list(v, P["names"][dom], P["agg"]["table_rows"])


def ag_ordered_keys(groups, dim, v_list, period_bounds):
    """时间维度按这一期的起始日期排（不按标签的字典序），从起点到终点补齐没有单的月份。"""
    order = vw_period_range(period_bounds[0], period_bounds[1], dim["period"]) if period_bounds else []
    starts = {}
    for v in v_list:
        for ts in v[dim["period_col"]].tolist() if len(v) else []:
            label = vw_period(ts, dim["period"])
            if label is not None and label not in starts:
                starts[label] = vw_period_start(ts, dim["period"])
    rest = sorted((k for k in groups if k not in order), key=lambda k: (starts.get(k) or pd.Timestamp.max, k))
    return list(dict.fromkeys(order + rest))


def ag_dim_table(v, dim, A, C, period_bounds, metrics=None):
    """一个分组维度的表与图数据（一域）。"""
    groups = vw_group(v, dim)
    pairs = [(k, len(ids)) for k, ids in groups.items()]
    metrics = A["metrics"] if metrics is None else metrics
    top = A.get("top") or (A["top_n"] if A.get("ranking") else None)
    if dim.get("period"):
        kept = [(k, len(groups.get(k, ()))) for k in ag_ordered_keys(groups, dim, [v], period_bounds)]
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
    # 一单可多值的维度总写一句（总述「统计口径说明」多值归属：各组之和可能大于问题单总数）
    caliber = {"多值归属": bool(dim.get("multi")), "各组合计": summed}
    if dim.get("multi"):
        facts["各组合计（一单可计入多组）"] = summed
    blank = int(len(v) - len({i for ids in groups.values() for i in ids}))
    if blank > 0:
        caliber["没有" + dim["title"]] = blank
    if dim.get("name") == "责任归属部门" and len(v) and "resp_dept" in v.columns:
        caliber["无需定责"] = int((v["resp_dept"] == "无需定责").sum())
        caliber["未定责"] = int((v["resp_dept"] == "未定责").sum())
        caliber["物料问题"] = int(v["_resp_material"].astype(bool).sum())
    return {"columns": columns, "rows": rows}, chart, facts, caliber, [k for k, _n in kept], first


def ag_compare_groups(v_all, times, dim):
    va, missing = vw_time(v_all, times)
    if dim is None:
        return {"合计": set(va["_id"]) if len(va) else set()}, len(va), missing
    return vw_group(va, dim), len(va), missing


def ag_compare(parts, A, C):
    """比较两个时段（一域或几域相加）：按时间先后，后一段减前一段为增减量，变化率 = 增减量 ÷ 前一段 × 100。

    `parts`：[(域, 视图, 维度说明或 None)]；几域时各组两段的单数按域相加（每单只属于一个域）。
    """
    dom0 = parts[0][0]
    a, b = A["compare"][dom0]
    ga, gb, na_all, nb_all, missing = {}, {}, 0, 0, []
    for dom, v, dim in parts:
        pa, pb = A["compare"][dom]
        g1, n1, m1 = ag_compare_groups(v, pa["times"], dim)
        g2, n2, m2 = ag_compare_groups(v, pb["times"], dim)
        for k, ids in g1.items():
            ga[k] = ga.get(k, 0) + len(ids)
        for k, ids in g2.items():
            gb[k] = gb.get(k, 0) + len(ids)
        na_all, nb_all, missing = na_all + n1, nb_all + n2, missing + m1 + m2
    dims = [d for _dom, _v, d in parts if d is not None]
    names = sorted(set(ga) | set(gb), key=lambda k: (-(ga.get(k, 0) + gb.get(k, 0)), str(k)))
    rows, increased_any = [], []
    for k in names:
        na, nb = ga.get(k, 0), gb.get(k, 0)
        diff = nb - na
        rate = f"{fi_round(diff / na * 100, 2):g}%" if na else "—"
        rows.append([k, na, nb, diff, rate])
        if diff > 0:
            increased_any.append(k)
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
    if len(parts) > 1:
        facts["计入的域"] = [dom for dom, _v, _d in parts]
    caliber = {"未计入": vw_merge_missing(missing), "多值归属": any(d.get("multi") for d in dims)}
    # 画图用的行：两段各一组柱子，数取自上面的表；合计不画（会把各组压扁），增减量、变化率单位不同也不画
    if dims:
        chart = {"dimension": title, "series": [a["label"], b["label"]],
                 "rows": [{title: r[0], a["label"]: r[1], b["label"]: r[2]} for r in rows[:-1]]}
    else:
        chart = {"dimension": C["period"], "series": [C["count"]],
                 "rows": [{C["period"]: a["label"], C["count"]: na_all}, {C["period"]: b["label"], C["count"]: nb_all}]}
    return {"columns": columns, "rows": rows}, chart, facts, caliber, nb_all > na_all, increased_any


def ag_bounds(P, dom, dims, v, found):
    bounds = P.get("period_bounds", {}).get(dom)
    if not bounds:
        return None
    bounds = [pd.Timestamp(bounds[0]) if bounds[0] else None, pd.Timestamp(bounds[1]) if bounds[1] else None]
    if (bounds[0] is None or bounds[1] is None) and found and dims:
        col = dims[0].get("period_col") or "_add"
        vals = [x for x in v[col].tolist() if x is not None and not pd.isna(x)]
        if vals:
            bounds = [bounds[0] or min(vals), bounds[1] or max(vals)]
    return bounds


# ---------------------------------------------------------------------------- 一域


def ag_overview(dom, v, missing, A, C, P):
    T = P["traits"].get(dom) or {}
    metrics = ag_supported(A["metrics"], T)
    found = int(len(v))
    mfacts, mcal = ag_metric_facts(v, metrics) if found else ({}, {})
    row = {C["domain"]: dom, C["count"]: found,
           C["unclosed"]: int(v["_unclosed"].astype(bool).sum()) if found else 0,
           C["stopped"]: int(v["_stopped_now"].astype(bool).sum()) if found else 0}
    if found:
        for k, x in ag_metrics(v, metrics, C).items():
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
            "停线中且已完成": stopped_done, "另列": ag_set_aside(v)}
    breakdowns = vw_breakdowns(v, P.get("breakdowns", {}).get(dom))
    if breakdowns:
        facts["分取值"] = breakdowns
    seg = {"domain": dom, "kind": "overview", "title": C["domain"],
           "table": {"columns": list(row.keys()), "rows": [list(row.values())]},
           "found": found, "facts": fi_with_counts(facts), "breakdowns": breakdowns,
           "caliber": {"未计入": missing, **mcal, **ocal}}
    if "结案周期" in metrics and found:
        seg["bins"] = {"columns": [C["close_days"], C["count"]], "rows": mfacts.get("结案周期分档", [])}
        seg["chart"] = {"dimension": C["close_days"], "rows": [{C["close_days"]: k, C["count"]: n}
                                                               for k, n in mfacts.get("结案周期分档", [])]}
    if "合计不良率" in A["metrics"] and T.get("rate") == "text":
        seg["rate_list"] = ag_rate_list(v, P, dom, C)
    return seg


def ag_small_sample(pairs, A, P):
    """巴西、海外按年季月周统计、单数很少时提示样本少（总述「统计口径说明」样本量一行）：[[域, 张数]]。"""
    limit = int(A.get("small_sample") or 0)
    return [[dom, int(n)] for dom, n in pairs
            if (P["traits"].get(dom) or {}).get("small_sample") and 0 < int(n) < limit]


def ag_set_aside(v):
    """巴西另列的待提交、已终止（不算已结案也不算未结案，总述「跨域归并」）。"""
    if len(v) == 0:
        return []
    out = []
    for label in ("待提交", "已终止"):
        n = int((v["_closed_label"] == label).sum())
        if n:
            out.append([label, n])
    return out


def ag_single(dom, v, missing, dims, A, C, P, refs):
    """一域的各段：不分组时概况；分组时每个维度一段。"""
    found = int(len(v))
    refs["total"] += found
    if not dims:
        return [ag_overview(dom, v, missing, A, C, P)]
    T = P["traits"].get(dom) or {}
    metrics = ag_supported(A["metrics"], T)
    mfacts, mcal = ag_metric_facts(v, metrics) if found else ({}, {})
    bounds = ag_bounds(P, dom, dims, v, found)
    breakdowns = vw_breakdowns(v, P.get("breakdowns", {}).get(dom))
    out = []
    for dim in dims:
        table, chart, facts, caliber, kept, first = ag_dim_table(v, dim, A, C, bounds, metrics)
        facts = {"总单数": found, **facts, **mfacts}
        if breakdowns:
            facts["分取值"] = breakdowns
        caliber = {"未计入": missing, **caliber, **mcal}
        refs["top1"] += [x for x in first if x not in refs["top1"]]
        refs["top_values"] += [x for x in kept if x not in refs["top_values"]]
        if dim.get("period"):
            caliber["样本少"] = ag_small_sample([(dom, found)], A, P)
        out.append({"domain": dom, "kind": "group", "title": dim["title"], "multi": bool(dim.get("multi")),
                    "name": dim.get("name"), "table": table, "chart": {"dimension": dim["title"], "rows": chart},
                    "groups": len(table["rows"]), "found": found, "facts": fi_with_counts(facts),
                    "breakdowns": breakdowns, "caliber": caliber})
    if "合计不良率" in A["metrics"] and T.get("rate") == "text" and out:
        out[0]["rate_list"] = ag_rate_list(v, P, dom, C)
    return out


# ---------------------------------------------------------------------------- 三域一起


def ag_concat(frames):
    parts = [f for f in frames if len(f)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def ag_same_close(doms, P):
    """这几个域的结案时间取法相同（国内、海外都是最新一条结案确认，巴西是处理过程上的结案日期；总述「结案时间与
    结案周期」）。不同时结案周期分域给，不合成一个跨域的数。"""
    kinds = {(P["traits"].get(d) or {}).get("close") for d in doms}
    return len(kinds) == 1 and None not in kinds


def ag_cross_overview(timed, A, C, P, refs):
    """按域统计：一域一行再加合计一行（总述「跨域规则」汇总呈现：先给各域小计，再给合计）。"""
    metrics = A["metrics"]
    extra_metrics = [m for m in metrics if m not in ("单数", "未结案数", "占比")]
    extra_cols = [k for k in ag_metrics(pd.DataFrame(), extra_metrics, C) if k != C["count"]]
    columns = [C["domain"], C["count"], C["unclosed"], C["stopped"], C["unclosed_share"], *extra_cols]
    rows, chart, per, type_pairs, missing = [], [], {}, {}, []
    totals = {"count": 0, "unclosed": 0, "stopped": 0, "rejected": 0, "stopped_done": 0}
    rate_lists, set_aside, mcal_all = {}, [], {}
    for dom, (v, miss) in timed.items():
        T = P["traits"].get(dom) or {}
        ms = ag_supported(extra_metrics, T)
        n = int(len(v))
        u = int(v["_unclosed"].astype(bool).sum()) if n else 0
        s = int(v["_stopped_now"].astype(bool).sum()) if n else 0
        row = {C["domain"]: dom, C["count"]: n, C["unclosed"]: u, C["stopped"]: s,
               C["unclosed_share"]: fi_round(u / n * 100, 2) if n else "—"}
        extra = ag_metrics(v, ms, C) if n else {}
        for col in extra_cols:
            row[col] = extra.get(col, "—")
        rows.append([row[c] for c in columns])
        chart.append({C["domain"]: dom, C["count"]: n})
        mfacts, mcal = ag_metric_facts(v, ms) if n else ({}, {})
        for k, x in mcal.items():
            if isinstance(x, bool):
                mcal_all[k] = mcal_all.get(k) or x
            else:
                # 口径里的张数三域相加在这里做；分域的另存一份（不良率不参与按域写）
                mcal_all[k] = mcal_all.get(k, 0) + x
                mcal_all.setdefault(k + "（分域）", {})[dom] = x
        per[dom] = {"单数": n, "未结案": u, "停线中": s, **mfacts}
        for name, k in vw_counts(v, "type") if n else []:
            type_pairs[name] = type_pairs.get(name, 0) + k
        totals["count"] += n
        totals["unclosed"] += u
        totals["stopped"] += s
        totals["rejected"] += int(v["_rejected"].astype(bool).sum()) if n else 0
        stopped = v[v["_stopped_now"].astype(bool)] if n else v
        totals["stopped_done"] += int(stopped["_done"].astype(bool).sum()) if len(stopped) else 0
        set_aside += [[dom, label, k] for label, k in ag_set_aside(v)]
        missing += miss
        if "合计不良率" in metrics and T.get("rate") == "text":
            rate_lists[dom] = ag_rate_list(v, P, dom, C)
    n_all, u_all = totals["count"], totals["unclosed"]
    total_row = {C["domain"]: C["total"], C["count"]: n_all, C["unclosed"]: u_all, C["stopped"]: totals["stopped"],
                 C["unclosed_share"]: fi_round(u_all / n_all * 100, 2) if n_all else "—"}
    combined = ag_concat([v for v, _m in timed.values()])
    close_split = "结案周期" in extra_metrics and not ag_same_close(list(timed), P)
    if "结案周期" in extra_metrics and not close_split:
        done = combined[combined["_done"].astype(bool)] if len(combined) else combined
        mean, median, _n = vw_days(done, "_close_days")
        total_row[C["close_mean"]] = mean if mean is not None else "—"
        total_row[C["close_median"]] = median if median is not None else "—"
    if "停线时长" in extra_metrics:
        mean, median, _n = vw_days(combined, "_stop_days")
        total_row[C["stop_mean"]] = mean if mean is not None else "—"
        total_row[C["stop_median"]] = median if median is not None else "—"
    for key in ("usd", "brl", "debit"):
        if C[key] in extra_cols:
            vals = [r[columns.index(C[key])] for r in rows if isinstance(r[columns.index(C[key])], (int, float))]
            total_row[C[key]] = fi_round(sum(vals), 2) if vals else "—"
    rows.append([total_row.get(c, "—") for c in columns])
    ranked, _f, _t = fi_rank(list(type_pairs.items()))
    facts = {"总单数": n_all, "各域单数": [[d, per[d]["单数"]] for d in per], "未结案": u_all,
             "停线中": totals["stopped"], "按问题类型": [list(p) for p in ranked], "各域": per}
    if totals["rejected"]:
        facts["未结案中生产角色驳回、流程已结束"] = totals["rejected"]
    if set_aside:
        facts["另列"] = set_aside
    return {"domain": "、".join(timed), "domains": list(timed), "kind": "overview", "cross": True,
            "title": C["domain"], "table": {"columns": columns, "rows": rows},
            "chart": {"dimension": C["domain"], "rows": chart, "series": [C["count"]]},
            "groups": len(timed), "found": n_all, "facts": fi_with_counts(facts),
            "caliber": {"未计入": vw_merge_missing(missing), "生产角色驳回": totals["rejected"],
                        "停线中且已完成": totals["stopped_done"], "另列": set_aside, "结案周期分域": close_split,
                        **mcal_all},
            "rate_lists": rate_lists}


def ag_cross_dim(parts, A, C, P, refs):
    """按可以同名合并的维度：每域一列（该域的单数，该域没有这一项写「—」），最后一列「单数」是三域合计。

    `parts`：[(域, 视图, 维度说明)]。取值合并按名称（视图里已按各域规则写成显示文字）。排名、Top N、并列按合计。
    """
    dim0 = parts[0][2]
    title = dim0["title"]
    groups = {dom: vw_group(v, dim) for dom, v, dim in parts}
    fill = list(dim0.get("fill") or [])
    keys = list(dict.fromkeys(fill + [k for dom, _v, _d in parts for k in groups[dom]]))
    totals = {k: sum(len(groups[dom].get(k, ())) for dom, _v, _d in parts) for k in keys}
    top = A.get("top") or (A["top_n"] if A.get("ranking") else None)
    pairs = [(k, totals[k]) for k in keys]
    if dim0.get("period"):
        bounds = ag_bounds(P, parts[0][0], [dim0], ag_concat([v for _d, v, _x in parts]),
                           sum(len(v) for _d, v, _x in parts))
        kept = [(k, totals.get(k, 0)) for k in ag_ordered_keys(totals, dim0, [v for _d, v, _x in parts], bounds)]
        first, tied = [], []
        if kept:
            best = max(n for _k, n in kept)
            first = [k for k, n in kept if n == best]
    elif dim0.get("order"):
        rank = {k: i for i, k in enumerate(dim0["order"])}
        kept = sorted(pairs, key=lambda p: (rank.get(p[0], len(rank)), str(p[0])))
        _all, first, tied = fi_rank([p for p in pairs if p[1]] or pairs)
        if top:
            kept, first, tied = fi_rank(pairs, top)
    else:
        kept, first, tied = fi_rank(pairs, top)
        if not top and len(kept) > A["table_rows"]:
            kept, first, tied = fi_rank(pairs, A["table_rows"])
    metrics = [m for m in A["metrics"] if m in ("未结案数", "占比", "结案周期", "停线时长")]
    grand = sum(len(v) for _d, v, _x in parts)
    # 每域一列是该域的单数，最后一列「单数」是三域合计（总述「表格列名」）
    columns = [title] + [dom for dom, _v, _d in parts] + [C["count"]]
    extra_names = [k for k in ag_metrics(pd.DataFrame(), [m for m in metrics if m != "占比"], C) if k != C["count"]]
    columns += extra_names + ([C["share"]] if "占比" in metrics else [])
    rows, chart = [], []
    for k, n in kept:
        cells = []
        for dom, _v, dim in parts:
            universe = dim.get("universe")
            cells.append("—" if universe and k not in universe else len(groups[dom].get(k, ())))
        subs = ag_concat([v[v["_id"].isin(groups[dom].get(k, set()))] for dom, v, _d in parts if len(v)])
        m = ag_metrics(subs, [x for x in metrics if x != "占比"], C)
        extra = [m[c] for c in extra_names]
        share = [fi_round(n / grand * 100, 2) if grand else 0] if "占比" in metrics else []
        rows.append([k, *cells, n, *extra, *share])
        point = {title: k, C["count"]: n}
        if C["unclosed"] in m:
            point[C["unclosed"]] = m[C["unclosed"]]
        chart.append(point)
    summed = sum(totals.values())
    multi = any(d.get("multi") for _dom, _v, d in parts)
    blank = sum(int(len(v) - len({i for ids in groups[dom].values() for i in ids})) for dom, v, _d in parts)
    facts = {"总单数": grand, "各域单数": [[dom, int(len(v))] for dom, v, _d in parts],
             "按" + title: [[k, n] for k, n in kept], "第一": first, "第一并列": len(first) > 1}
    if tied:
        facts["并列"] = tied
        facts["并列名次"] = int(top) if top else int(A["table_rows"])
    if len([k for k in keys if totals[k]]) > len(kept):
        facts["分组总数"] = len([k for k in keys if totals[k]])
    if multi:
        facts["各组合计（一单可计入多组）"] = summed
    caliber = {"多值归属": multi, "各组合计": summed, "跨域归并": dim0.get("name")}
    if blank > 0:
        caliber["没有" + title] = blank
    if dim0.get("period"):
        caliber["样本少"] = ag_small_sample([(dom, len(v)) for dom, v, _d in parts], A, P)
    refs["top1"] += [x for x in first if x not in refs["top1"]]
    refs["top_values"] += [x for x, _n in kept if x not in refs["top_values"]]
    return {"domain": "、".join(dom for dom, _v, _d in parts), "domains": [dom for dom, _v, _d in parts],
            "kind": "group", "cross": True, "title": title, "name": dim0.get("name"), "multi": multi,
            "table": {"columns": columns, "rows": rows},
            "chart": {"dimension": title, "rows": chart, "series": [C["count"]]},
            "groups": len(rows), "found": grand, "facts": fi_with_counts(facts), "caliber": caliber}


def ag_cross(timed, A, C, P, refs):
    """本步有两个及以上的域：按域统计、同名合并的维度合成一张表，其余维度按域分别给。"""
    refs["total"] += sum(int(len(v)) for v, _m in timed.values())
    names = list(A.get("group_by") or [])
    if not names or names == ["域"]:
        return [ag_cross_overview(timed, A, C, P, refs)]
    rate = "合计不良率" in A["metrics"]
    out = []
    # 一域的那几段只借用排名的引用值，总数已在上面按各域相加
    local = {"total": 0, "top1": refs["top1"], "top_values": refs["top_values"]}
    for name in names:
        if name == "域":
            out.append(ag_cross_overview(timed, A, C, P, refs))
            continue
        parts = []
        for dom, (v, _m) in timed.items():
            dim = next((d for d in A["dims"].get(dom) or [] if d.get("name") == name), None)
            if dim is not None:
                parts.append((dom, v, dim))
        # 要不良率（分母不同）或结案周期（结案时间取法不同）时合并表每行的数会把几域混在一起：按域分别给
        close_split = "结案周期" in A["metrics"] and not ag_same_close([dom for dom, _v, _d in parts], P)
        if len(parts) >= 2 and all(d.get("merge") for _dom, _v, d in parts) and not rate and not close_split:
            out.append(ag_cross_dim(parts, A, C, P, refs))
            continue
        for dom, v, dim in parts:
            segs = ag_single(dom, v, timed[dom][1], [dim], A, C, P, local)
            for seg in segs:
                seg["caliber"]["结案周期分域"] = close_split and len(parts) >= 2
            out += segs
    return out


def ag_ref_issues(refs, ids, dom, frames):
    """本域计入这一步的单（比较两个时段时是两段的并集）：张数进 `refs["found"]`，单 ID 与问题编号作为明细帧
    （`ids_<域>`）回传，不放进 result（几千张单的编号会撑满 20 万字符，设计 §8.1）。工作区存下供质疑重查比对
    （设计 §10）；不进回答。"""
    parts = [f for f in frames if len(f)]
    v = pd.concat(parts, ignore_index=True).drop_duplicates("_id") if parts else None
    if v is None:
        ids["ids_" + dom] = pd.DataFrame({"_id": pd.Series([], dtype="int64"), "_number": pd.Series([], dtype="object")})
        refs["found"][dom] = 0
        return
    ids["ids_" + dom] = pd.DataFrame({"_id": [int(x) for x in v["_id"].tolist()],
                                      "_number": [str(x) for x in v["_number"].tolist()]})
    refs["found"][dom] = int(len(v))


def run(data):
    P = PARAMS
    A = P["agg"]
    C = P["cols"]
    segments, missing_domains = [], []
    refs = {"top1": [], "top_values": [], "total": 0, "increased": False, "found": {}}
    ids = {}
    views = {}
    for dom in P["domains"]:
        v = dm_view(dom, data, P)
        if v is None:
            missing_domains.append(dom)
            continue
        views[dom] = vw_filter(v, P["conds"].get(dom)) if len(v) else v
    if A.get("compare"):
        for dom, v in views.items():
            periods = (A["compare"].get(dom) or []) if len(v) else []
            ag_ref_issues(refs, ids, dom, [vw_time(v, p["times"])[0] for p in periods])
        parts = [(dom, v, (A["dims"].get(dom) or [None])[0]) for dom, v in views.items() if dom in A["compare"]]
        groups = [parts] if len(parts) >= 2 else [[p] for p in parts]
        for group in groups:
            dom = group[0][0] if len(group) == 1 else "、".join(d for d, _v, _x in group)
            if all(len(v) == 0 for _d, v, _x in group):
                segments.append({"domain": dom, "domains": [d for d, _v, _x in group], "kind": "compare",
                                 "found": 0, "facts": {"总单数": 0}, "caliber": {}})
                continue
            table, chart, facts, caliber, inc, inc_values = ag_compare(group, A, C)
            refs["increased"] = refs["increased"] or inc
            refs["top_values"] += [x for x in inc_values if x not in refs["top_values"]]
            dims0 = [d for _dom, _v, d in group if d is not None]
            segments.append({"domain": dom, "domains": [d for d, _v, _x in group], "kind": "compare",
                             "cross": len(group) > 1, "title": table["columns"][0], "table": table,
                             "chart": chart, "multi": any(d.get("multi") for d in dims0),
                             "found": facts[table["columns"][1]] + facts[table["columns"][2]],
                             "facts": fi_with_counts(facts), "caliber": caliber})
        return {"segments": segments, "refs": refs, "missing_domains": missing_domains, **ids}
    timed = {}
    for dom, v in views.items():
        timed[dom] = vw_time(v, P["times"].get(dom)) if len(v) else (v, [])
        ag_ref_issues(refs, ids, dom, [timed[dom][0]])
    if len(timed) >= 2:
        segments = ag_cross(timed, A, C, P, refs)
    else:
        for dom, (v, missing) in timed.items():
            segments += ag_single(dom, v, missing, A["dims"].get(dom) or [], A, C, P, refs)
    # 结论的要点与需关注的单按计入统计的单算；比较两个时段时不给（上面已返回；决策 2026-11-03「结论的要点与需关注的单」）
    insights = in_insights([(dom, v) for dom, (v, _m) in timed.items()], P.get("insight"), P.get("blind"),
                           P.get("traits"))
    return {"segments": segments, "refs": refs, "missing_domains": missing_domains, "insights": insights, **ids}
