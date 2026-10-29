"""在「一单一行」视图上做筛选、时间、分组与指标（设计 §6.3、§8.1；各域共用，S3 起巴西、海外的视图同样用）。

视图的辅助列约定（各域派生函数给出）：`_id`、`_number`、`_done`、`_rejected`、`_add`、`_found`、`_stop`、`_restart`、
`_close`（日期）、`_stopped_ever`、`_stopped_now`、`_restarted`、`_stop_code`、`_stages`、`_machines`、`_series`、
`_current_ids`、`_responsible_ids`、`_follower_ids`、`_resp_dept_ids`、`_resp_material`、`_rate_value`、`_bad`、
`_den`、`_close_days`、`_stop_days`、`_inv_name`。

条件由 `handle()` 一侧对好库、写成参数（`domains/domestic.py`）：
- `{"kind": "status", "items": [[种类, 值], …], "neg": 否}`：状态说法，几项之间为「或」；
- `{"kind": "any_of", "col": 多值列, "values": […], "neg": 否}`：多值列与取值有交集即命中（比较前统一写法）；
- `{"kind": "contains", "col": 列, "values": […], "neg": 否}`：包含任一取值；
- `{"kind": "ids", "values": [单 ID…]}`：在前一步的结果里找。
时间：`{"basis": 日期依据, "start": "YYYY-MM-DD" 或 None, "end": …}`，含两头。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import fi_blank, fi_key, fi_median, fi_rank, fi_round

#: 日期依据 → 视图里的日期列，以及「这个日期没填就不计入」时要数的范围（总述「按哪个日期筛」）
VW_BASIS = {"建单": ("_add", None), "现场发现": ("_found", None), "停线": ("_stop", "_stopped_ever"),
            "重启": ("_restart", "_restarted"), "结案": ("_close", "_done")}


def vw_status_hit(row, kind, value):
    if kind == "未结案":
        return not row["_done"]
    if kind == "已结案":
        return bool(row["_done"])
    if kind == "停线中":
        return bool(row["_stopped_now"])
    if kind == "曾经停线":
        return bool(row["_stopped_ever"])
    if kind == "已经重启":
        return bool(row["_restarted"])
    if kind == "环节":
        return value in (row["_stages"] or [])
    codes = {"重启审核通过": 5, "重启审核中": 4, "责任人填写重启方案": 6, "没有停线": 3}
    if kind in codes:
        return row["_stop_code"] == codes[kind]
    return False


def vw_cond_mask(view, cond):
    kind = cond.get("kind")
    if kind == "status":
        items = cond.get("items") or []
        hit = view.apply(lambda r: any(vw_status_hit(r, k, v) for k, v in items), axis=1)
    elif kind == "any_of":
        want = {fi_key(v) for v in cond.get("values") or []}
        hit = view[cond["col"]].apply(lambda xs: any(fi_key(x) in want for x in (xs or [])))
    elif kind == "contains":
        want = [fi_key(v) for v in cond.get("values") or [] if fi_key(v)]
        hit = view[cond["col"]].apply(lambda x: x is not None and any(w in fi_key(x) for w in want))
    elif kind == "in":
        want = {fi_key(v) for v in cond.get("values") or []}
        hit = view[cond["col"]].apply(lambda x: fi_key(x) in want)
    elif kind == "flag":
        hit = view[cond["col"]].apply(lambda x: bool(x) == bool(cond.get("value")))
    elif kind == "pn":
        codes = {fi_key(v) for v in cond.get("values") or []}
        hit = view.apply(lambda r: any(fi_key(c) in codes for c in (r["_pn_codes"] or []))
                         or any(w and w in fi_key(n) for n in (r["_pn_names"] or []) for w in codes), axis=1)
    elif kind == "ids":
        want = set(cond.get("values") or [])
        hit = view["_id"].apply(lambda x: x in want)
    else:
        hit = pd.Series([True] * len(view), index=view.index)
    hit = hit.astype(bool)
    return ~hit if cond.get("neg") else hit


def vw_filter(view, conds):
    if len(view) == 0:
        return view
    mask = pd.Series([True] * len(view), index=view.index)
    for cond in conds or []:
        mask = mask & vw_cond_mask(view, cond)
    return view[mask]


def vw_time(view, times):
    """按时间条件筛；返回 (筛后的视图, [[日期依据, 该日期没填而未计入的张数], …])。"""
    missing = []
    for t in times or []:
        col, scope = VW_BASIS.get(t.get("basis") or "建单", ("_add", None))
        if len(view) == 0:
            continue
        pool = view if scope is None else view[view[scope].astype(bool)]
        blank = pool[col].apply(lambda x: x is None or pd.isna(x))
        n_blank = int(blank.sum())
        if n_blank and t.get("basis") not in (None, "建单"):
            missing.append([t.get("basis"), n_blank])
        start = pd.Timestamp(t["start"]) if t.get("start") else None
        end = pd.Timestamp(t["end"]) + pd.Timedelta(days=1) if t.get("end") else None

        def inside(x, start=start, end=end):
            if x is None or pd.isna(x):
                return False
            return (start is None or x >= start) and (end is None or x < end)

        view = view[view[col].apply(inside)]
    return view, missing


def vw_sorted(view, key="_add", desc=True):
    """排序带次键：同值时按问题编号排，同一查询两次给出的前 N 条一样（设计 §8.1）。空值排最后。"""
    if len(view) == 0:
        return view
    v = view.copy()
    v["_k_null"] = v[key].apply(lambda x: x is None or pd.isna(x))
    v["_k"] = v[key].apply(lambda x: None if x is None or pd.isna(x) else x)
    v = v.sort_values(["_k_null", "_k", "_number"], ascending=[True, not desc, not desc], na_position="last",
                      kind="mergesort")
    return v.drop(columns=["_k_null", "_k"])


def vw_counts(view, col, multi=False):
    """[(取值, 张数)]：多值列一单在每个取值下各计一次（同一单同一取值只计一次）。"""
    counts = {}
    for _, r in view.iterrows():
        vals = r[col] if multi else [r[col]]
        for v in dict.fromkeys(vals or []):
            counts[v] = counts.get(v, 0) + 1
    return list(counts.items())


def vw_period(ts, dim):
    if ts is None or pd.isna(ts):
        return None
    if dim == "年":
        return f"{ts.year} 年"
    if dim == "季度":
        return f"{ts.year} 年第 {(ts.month - 1) // 3 + 1} 季度"
    if dim == "月":
        return ts.strftime("%Y-%m")
    if dim == "周":
        y, w, _d = ts.isocalendar()
        return f"{y} 年第 {w} 周"
    return None


def vw_period_start(ts, dim):
    """这一期的起始日期（时间类目按它排，不按标签的字典序：「第 10 周」不排在「第 2 周」前面）。"""
    if ts is None or pd.isna(ts):
        return None
    day = ts.normalize()
    if dim == "年":
        return pd.Timestamp(day.year, 1, 1)
    if dim == "季度":
        return pd.Timestamp(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    if dim == "月":
        return pd.Timestamp(day.year, day.month, 1)
    if dim == "周":
        return day - pd.Timedelta(days=day.weekday())
    return None


def vw_breakdowns(view, specs):
    """一个说法对上几个取值时（如「研发」对上研发一部、研发二部），按全部合计，同时给每个取值各自的张数。

    `specs`：[{"title": 列名, "col": 视图列, "multi": 是否多值, "values": [取值…]}] → [[列名, [[取值, 张数]…]]…]。
    """
    out = []
    for spec in specs or []:
        col, multi = spec["col"], bool(spec.get("multi"))
        pairs = []
        for value in spec.get("values") or []:
            if len(view) == 0:
                n = 0
            elif multi:
                n = int(view[col].apply(lambda xs, value=value: value in (xs or [])).sum())
            else:
                n = int((view[col] == value).sum())
            pairs.append([value, n])
        out.append([spec["title"], pairs])
    return out


def vw_period_range(start, end, dim):
    """时间维度的全部类目（含没有单的月份），从起点到终点；周不补齐。"""
    if start is None or end is None or dim not in ("年", "季度", "月"):
        return []
    out = []
    cur = pd.Timestamp(start.year, start.month, 1)
    while cur <= end and len(out) < 240:
        label = vw_period(cur, dim)
        if label not in out:
            out.append(label)
        cur = cur + pd.DateOffset(months=1)
    return out


def vw_group(view, dim, total_ids=None):
    """一个分组维度 → {取值: 该组的单 ID 集合}；`dim` 是参数里的维度说明。"""
    groups = {}
    col = dim.get("col")
    for _, r in view.iterrows():
        if dim.get("period"):
            vals = [vw_period(r[dim["period_col"]], dim["period"])]
        elif dim.get("const") is not None:
            vals = [dim["const"]]
        elif dim.get("multi"):
            vals = list(r[col] or [])
        else:
            vals = [r[col]]
        vals = [v for v in vals if v not in (None, "", "—") and (v != "未填" or dim.get("keep_blank"))]
        if not vals and dim.get("empty") is not None:
            vals = [dim["empty"]]
        for v in dict.fromkeys(vals):
            if v is None:
                continue
            groups.setdefault(v, set()).add(r["_id"])
    return groups


def vw_rate(sub):
    """合计不良率 = 合计不良数量 ÷ 合计分母 × 100，保留 2 位；不良数量为空、分母为 0 或空的单不参与（总述「汇总不良率」）。"""
    ok = sub[sub.apply(lambda r: not fi_blank(r["_bad"]) and not fi_blank(r["_den"]) and r["_den"] > 0, axis=1)] \
        if len(sub) else sub
    excluded = int(len(sub) - len(ok))
    if len(ok) == 0:
        return None, excluded
    return fi_round(float(ok["_bad"].sum()) / float(ok["_den"].sum()) * 100, 2), excluded


def vw_days(sub, col):
    vals = [int(x) for x in sub[col].tolist() if x is not None and not pd.isna(x)] if len(sub) else []
    if not vals:
        return None, None, 0
    return fi_round(sum(vals) / len(vals), 1), fi_round(fi_median(vals), 1), len(vals)


def vw_bins(sub):
    """结案周期分档：30 天及以内、31–90 天、91 天及以上（总述「结案时间与结案周期」）。"""
    vals = [int(x) for x in sub["_close_days"].tolist() if x is not None and not pd.isna(x)] if len(sub) else []
    return [["30 天及以内", sum(1 for v in vals if v <= 30)], ["31–90 天", sum(1 for v in vals if 31 <= v <= 90)],
            ["91 天及以上", sum(1 for v in vals if v >= 91)]]


def vw_top(pairs, top):
    return fi_rank(pairs, top)
