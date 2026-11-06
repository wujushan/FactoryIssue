"""在「一单一行」视图上做筛选、时间、分组与指标（设计 §6.3、§8.1；三域共用）。

视图的辅助列约定（三域的派生函数都给出）：`_id`、`_number`、`_done`、`_unclosed`（巴西不含待提交、已终止）、
`_rejected`、`_closed_label`、`_add`、`_found`、`_stop`、`_restart`、`_close`、`_stat`（日期）、`_stopped_ever`、
`_stopped_now`、`_restarted`、`_not_stopped`、`_stop_code`、`_stages`、`_machines`、`_series`、`_current_ids`、
`_current_names`、`_responsible_ids`、`_follower_ids`、`_resp_dept_ids`、`_resp_material`、`_rate_value`、`_bad`、
`_den`、`_impact`、`_close_days`、`_stop_days`、`_inv_name`、`_pn_codes`、`_pn_names`。巴西另有费用的 `_usd`、
`_brl`、`_debit`、`_has_cost`。成对列（`VW_LINKS`）：国内、巴西的 `_machine_pairs`，国内的 `_state_pairs`。

条件由 `handle()` 一侧对好库、写成参数（`domains/<域>.py`）：
- `{"kind": "status", "items": [[种类, 值], …], "neg": 否}`：状态说法，几项之间为「或」；
- `{"kind": "any_of", "col": 多值列, "values": […], "neg": 否}`：多值列与取值有交集即命中（比较前统一写法）；
  按 ID 筛、分组列是名称的（当前责任人、责任归属部门、海外问题跟进人）另带 `"group_col": 分组列,
  "group_values": [名称…]`；带 `"label": 叫法` 的（状态条件同）参加分组限定（`vw_keep`）；
- `{"kind": "contains", "col": 列, "values": […], "neg": 否}`：包含任一取值；
- `{"kind": "num", "col": 列, "op": eq/ne/gt/lt/ge/le/between, "values": [数…]}`：数值比较，空值不命中；
- `{"kind": "ids", "values": [单 ID…]}`：在前一步的结果里找。
时间：`{"basis": 日期依据, "start": "YYYY-MM-DD" 或 None, "end": …}`，含两头。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import fi_blank, fi_key, fi_median, fi_rank, fi_round

#: 日期依据 → 视图里的日期列，以及「这个日期没填就不计入」时要数的范围（总述「按哪个日期筛」）
VW_BASIS = {"建单": ("_add", None), "现场发现": ("_found", None), "停线": ("_stop", "_stopped_ever"),
            "重启": ("_restart", "_restarted"), "结案": ("_close", "_done"), "统计日期": ("_stat", None)}


def vw_num_hit(x, op, nums):
    if x is None or pd.isna(x):
        return False
    a = nums[0]
    if op == "between":
        return nums[0] <= x <= nums[1]
    return {"eq": x == a, "ne": x != a, "gt": x > a, "lt": x < a, "ge": x >= a, "le": x <= a}.get(op, False)


def vw_status_hit(row, kind, value):
    if kind == "未结案":
        return bool(row["_unclosed"])
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
    if kind == "没有停线":
        return bool(row["_not_stopped"])
    codes = {"重启审核通过": 5, "重启审核中": 4, "责任人填写重启方案": 6}
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
        hit = view[cond["col"]].apply(lambda x: not fi_blank(x) and any(w in fi_key(x) for w in want))
    elif kind == "in":
        want = {fi_key(v) for v in cond.get("values") or []}
        hit = view[cond["col"]].apply(lambda x: fi_key(x) in want)
    elif kind == "flag":
        hit = view[cond["col"]].apply(lambda x: bool(x) == bool(cond.get("value")))
    elif kind == "pn":
        codes = {fi_key(v) for v in cond.get("values") or []}
        hit = view.apply(lambda r: any(fi_key(c) in codes for c in (r["_pn_codes"] or []))
                         or any(w and w in fi_key(n) for n in (r["_pn_names"] or []) for w in codes), axis=1)
    elif kind == "num":
        nums = [float(x) for x in cond.get("values") or []]
        hit = view[cond["col"]].apply(lambda x: bool(nums) and vw_num_hit(x, cond.get("op"), nums))
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


#: 单上成对登记的几列：成对列 → 各位置对应的视图列。成对列每一项是一组，位置上可以是一个值或一串值。
#: 国内、巴西的机型与系列（一个机型属于一个系列）；国内当前状态每一行的环节、员工 ID、姓名
VW_LINKS = {"_machine_pairs": ["_machines", "_series"], "_state_pairs": ["_stages", "_current_ids", "_current_names"]}
#: 按 ID 筛、按姓名分组的同一维度：ID 列 → 姓名列（口径写「筛选的当前责任人」，不写「与之对应的」）
VW_SAME = {"_current_ids": "_current_names", "_follower_ids": "_follower_names", "_resp_dept_ids": "_resp_dept_names"}


def vw_keep(conds):
    """按一单可多值的维度筛了哪些取值（总述「统计口径说明」多值归属），分组时用来限定（`vw_restrict`）。

    返回 [{"label": 条件的叫法, "show": [口径里写的取值…], "cols": {视图列: [取值…]}}]，同一叫法的几个条件合成一项。
    参加的是带 `label` 的肯定条件：any_of 条件按条件里的列与取值，带 `group_col` 的另加它与 `group_values`；状态条件
    的几项都是「环节」时按处理环节。否定的条件不限定（留下的单本来就没有那些取值）。"""
    by_label = {}
    for c in conds or []:
        if c.get("neg") or not c.get("label"):
            continue
        if c.get("kind") == "any_of":
            cols = {c["col"]: list(c.get("values") or [])}
            if c.get("group_col"):
                cols[c["group_col"]] = list(c.get("group_values") or [])
            show = list(c.get("show") or c.get("group_values") or c.get("values") or [])
        elif c.get("kind") == "status" and c.get("items") and all(k == "环节" for k, _v in c["items"]):
            cols = {"_stages": [v for _k, v in c["items"]]}
            show = list(cols["_stages"])
        else:
            continue
        e = by_label.setdefault(c["label"], {"label": c["label"], "show": [], "cols": {}})
        e["show"] += [x for x in show if x not in e["show"]]
        for col, vals in cols.items():
            got = e["cols"].setdefault(col, [])
            got += [x for x in vals if x not in got]
    return [e for e in by_label.values() if any(e["cols"].values())]


def vw_link_of(e, col):
    """这一项条件经哪个成对列连到分组列 `col`：(成对列, 条件列在组里的位置, 分组列在组里的位置)；连不上为 None。"""
    for pairs, names in VW_LINKS.items():
        if col not in names:
            continue
        src = next((k for k in e["cols"] if k in names and k != col), None)
        if src is not None:
            return pairs, names.index(src), names.index(col)
    return None


def vw_restrict(dims, keep):
    """多值维度与哪几项条件有关（同一列，或经成对列连上），就带上这几项（`keep`）与口径要写的
    （`only_by`：[[叫法, 取值, 是否同一维度]…]）。"""
    out = []
    for d in dims or []:
        col = d.get("col")
        if d.get("multi"):
            rel = [e for e in keep or [] if col in e["cols"] or vw_link_of(e, col) is not None]
            if rel:
                same = [col in e["cols"] or any(VW_SAME.get(k) == col for k in e["cols"]) for e in rel]
                d = {**d, "keep": rel, "only_by": [[e["label"], list(e["show"]), s] for e, s in zip(rel, same)]}
        out.append(d)
    return out


def vw_as_list(x):
    return list(x) if isinstance(x, (list, tuple)) else [x]


def vw_allowed(row, col, keep):
    """这一单在分组列 `col` 下可以计入哪些取值（统一写法后的集合；None = 不限定），以及有没有经成对列限定。

    同一列的条件直接取它的取值；别的列经成对列（`VW_LINKS`）取与筛选取值同组的那些。几项条件都有关时取交集。"""
    allowed, linked = None, False
    for e in keep or []:
        if col in e["cols"]:
            got = {fi_key(x) for x in e["cols"][col]}
        else:
            link = vw_link_of(e, col)
            if link is None or link[0] not in row.index:
                continue
            pairs, i, j = link
            src = VW_LINKS[pairs][i]
            want = {fi_key(x) for x in e["cols"][src]}
            got = {fi_key(y) for t in (row[pairs] or []) if any(fi_key(x) in want for x in vw_as_list(t[i]))
                   for y in vw_as_list(t[j]) if not fi_blank(y)}
            linked = True
        allowed = got if allowed is None else allowed & got
    return allowed, linked


def vw_kept_values(row, col, keep):
    """一单在多值列 `col` 下计入的取值。按同一列筛时一个都对不上（人员姓名的写法与主数据不同）照原样，不让这张单
    掉出分组；经成对列限定、一个都不剩时为空（如按环节筛、那一行环节上没有人：这张单没有可计入的当前责任人）。"""
    vals = list(row[col] or [])
    if not keep:
        return vals
    allowed, linked = vw_allowed(row, col, keep)
    if allowed is None:
        return vals
    got = [x for x in vals if fi_key(x) in allowed]
    return got if (got or linked) else vals


def vw_group(view, dim, total_ids=None):
    """一个分组维度 → {取值: 该组的单 ID 集合}；`dim` 是参数里的维度说明。多值维度带 `keep` 时只在与筛选取值对应的
    取值下计（`vw_restrict`、`vw_kept_values`）。"""
    groups = {}
    col = dim.get("col")
    for _, r in view.iterrows():
        if dim.get("period"):
            vals = [vw_period(r[dim["period_col"]], dim["period"])]
        elif dim.get("const") is not None:
            vals = [dim["const"]]
        elif dim.get("multi"):
            vals = vw_kept_values(r, col, dim.get("keep"))
        else:
            vals = [r[col]]
        # 空值用 fi_blank 判：pandas 3 的文本列里 None 存成 NaN，`v is None` 认不出，会多出一组空白的取值
        vals = [v for v in vals if not fi_blank(v) and v != "—" and (v != "未填" or dim.get("keep_blank"))]
        if not vals and dim.get("unknown_col") and bool(r.get(dim["unknown_col"])):
            vals = ["未识别机型"]  # 巴西、海外大机型有值但对不上产品主数据
        if not vals and dim.get("empty") is not None:
            vals = [dim["empty"]]
        for v in dict.fromkeys(vals):
            if fi_blank(v):
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


def vw_merge_missing(items):
    """[[日期依据, 张数], …]：同一依据的几项（几个域）相加。统计口径「时间范围」那一项按这个形状写（`caliber.time_range`）；
    统计的跨域各段与临时统计共用。"""
    out = {}
    for basis, n in items or []:
        out[basis] = out.get(basis, 0) + int(n)
    return [[k, n] for k, n in out.items()]


def vw_ids(v):
    """后一步引用、工作区要存的结果单（按视图的顺序）：单 ID 与问题编号，作为明细帧（`ids_<域>`）回传。"""
    if not len(v):
        return pd.DataFrame({"_id": pd.Series([], dtype="int64"), "_number": pd.Series([], dtype="object")})
    return pd.DataFrame({"_id": [int(x) for x in v["_id"].tolist()], "_number": [str(x) for x in v["_number"].tolist()]})


def vw_rate_list(v, names, table_rows):
    """海外不良率是单上原文、不汇总：逐单列出原文（建单时间倒序，表格条数同清单；总述「汇总不良率」）。

    `names` 是本域视图列的显示名（`present/columns.py`）。统计与临时统计共用。"""
    rows = vw_sorted(v, "_add", True).head(int(table_rows)) if len(v) else v
    return {"columns": [names["number"], names["rate"]],
            "rows": [[r["number"], r["rate"]] for _, r in rows.iterrows()] if len(rows) else [],
            "ids": [int(x) for x in rows["_id"].tolist()] if len(rows) else [], "found": int(len(v)),
            "shown": int(len(rows)), "truncated": int(len(rows)) < int(len(v))}
