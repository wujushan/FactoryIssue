"""结论里的要点与需关注的单（总述「结论里的要点与需关注的单」，决策 2026-11-03「结论的要点与需关注的单」）。

清单、按文字找单、汇总统计、临时统计共用：输入本步各域计入的单（「一单一行」视图，`views.py` 开头的辅助列），
按集中、积压、严重、重复、时间、时效六项逐项判断，成立的给出数与单号；需关注的单按四档排好。数都在这里算
（设计 §8.1），`handle()` 一侧只照着写成句子。

参数 `Q`（`present/insights.py::params` 给）：`today`（建单天数算到这天）、`share`（集中的占比门槛，%）、`repeat`
（重复的张数门槛）、`months`（时间的月数门槛）、`close_min`（时效的张数门槛）、`points`、`focus`（至多几条、几张）、
`skip`（用户已按它筛选或分组、不写的项：集中、积压、等级、停线、机型、加工厂、供应商、时间、时效）。
`blind` 是各域靠没取到的主数据才写得出来的列，`traits` 是各域特性（海外不良率是原文，不参与比较）。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import fi_blank, fi_median, fi_rank, fi_round
from factory_issue_module.stats.lib.views import vw_counts

#: 国内这一天之前建的单没有问题等级（总述「初步分析维度」问题等级一行）
IN_LEVEL_FROM = "2024-04-17"
IN_AGE_BINS = (("30 天及以内", 0, 30), ("31–90 天", 31, 90), ("91 天及以上", 91, None))
IN_HIGH = ("A+", "A")
#: 结论最少几张才给要点与需关注（只有一两张时一句话代替整个结论）
IN_FEW = 2
#: 时间：建单最多的月份并列超过这么多个时不写（说不出哪个月最多）
IN_PEAK_MAX = 3
#: 积压：某域最多的环节不少于这么多张、并列不超过这么多个时才写这一域停在哪
IN_STAGE_MIN = 2
IN_STAGE_TIES = 2


def in_age(ts, today):
    """建单至今的天数（按日计）；没有建单时间为 None。"""
    if ts is None or pd.isna(ts):
        return None
    return int((today - ts.normalize()).days)


def in_named(pairs):
    """去掉空值、「未填」「—」的 [(取值, 张数)]。"""
    return [(k, n) for k, n in pairs if not fi_blank(k) and k not in ("未填", "—", "未识别机型")]


def in_concentrate(parts, total, Q):
    counts = {}
    for _dom, v in parts:
        for name, n in in_named(vw_counts(v, "type")):
            counts[name] = counts.get(name, 0) + n
    ranked, first, _t = fi_rank(list(counts.items()))
    if not ranked:
        return None
    top = ranked[0][1]
    share = fi_round(top / total * 100, 1)
    if share < float(Q["share"]):
        return None
    out = {"发现": "集中", "名称": "问题类型", "计入张数": total, "最多的问题类型": [[k, top] for k in first],
           "占比（%）": share}
    rest = [p for p in ranked if p[0] not in first]
    if rest:
        out["其次"] = [[k, n] for k, n in rest if n == rest[0][1]]
    return out


def in_backlog(parts, today):
    unclosed, stages, bins, oldest = 0, [], [0, 0, 0], None
    for dom, v in parts:
        u = v[v["_unclosed"].astype(bool)]
        if not len(u):
            continue
        unclosed += int(len(u))
        ranked, first, _t = fi_rank(in_named(vw_counts(u, "_stages", multi=True)))
        # 最多的环节不到 2 张、或并列超过 2 个时说不出积压在哪，这一域不写（各环节各 1 张不算积压）
        if first and ranked[0][1] >= IN_STAGE_MIN and len(first) <= IN_STAGE_TIES:
            stages.append({"域": dom, "最多停在的环节": first, "张数": int(ranked[0][1]), "该域未结案": int(len(u))})
        for r in u.to_dict("records"):
            age = in_age(r.get("_add"), today)
            if age is None:
                continue
            for k, (_label, low, high) in enumerate(IN_AGE_BINS):
                if age >= low and (high is None or age <= high):
                    bins[k] += 1
            key = (-age, str(r.get("_number")))
            if oldest is None or key < oldest[0]:
                oldest = (key, {"域": dom, "问题编号": r.get("_number"), "建单天数": age})
    if not unclosed:
        return None
    out = {"发现": "积压", "名称": "积压", "未结案": unclosed}
    if stages:
        out["各域未结案最多停在的环节"] = stages
    if any(bins):
        out["未结案建单天数分档"] = [[label, bins[k]] for k, (label, _l, _h) in enumerate(IN_AGE_BINS)]
    if oldest is not None:
        out["建单最久的未结案单"] = oldest[1]
    return out


def in_severe(parts, Q):
    skip = set(Q.get("skip") or [])
    out = {"发现": "严重", "名称": "严重程度"}
    if "等级" not in skip:
        for level in IN_HIGH:
            n = sum(int((v["level"] == level).sum()) for _dom, v in parts)
            if n:
                out[level + " 级"] = n
    if "停线" not in skip:
        n = sum(int(v["_stopped_now"].astype(bool).sum()) for _dom, v in parts)
        if n:
            out["停线中"] = n
    if len(out) == 2:
        return None
    if "等级" not in skip:
        cut = pd.Timestamp(IN_LEVEL_FROM)
        early = sum(int(v["_add"].apply(lambda x: x is not None and not pd.isna(x) and x < cut).sum())
                    for dom, v in parts if dom == "国内")
        if early:
            out["国内 2024-04-17 之前建的单（没有问题等级）"] = early
    return out


def in_values(v, what):
    """每张单在这一项下的取值（一单可多值）。"""
    if what == "机型":
        return [list(x or []) for x in v["_machines"].tolist()]
    if what == "加工厂":
        if "_factories" in v.columns:
            return [list(x or []) for x in v["_factories"].tolist()]
        return [[x] for x in v["factory"].tolist()]
    if "_ven_names_text" in v.columns:
        return [[s.strip() for s in str(x).split("；") if s.strip()] if not fi_blank(x) else []
                for x in v["_ven_names_text"].tolist()]
    return [[x] for x in v["ven_name"].tolist()]


#: 重复看的三项：(说法, 视图里靠主数据写出的列名，没取到主数据时这一域不看)
IN_REPEAT = (("机型", "_machines"), ("加工厂", "factory"), ("供应商", "ven_name"))


def in_repeat(parts, Q, blind):
    skip = set(Q.get("skip") or [])
    out = {"发现": "重复", "名称": "重复出现"}
    for what, col in IN_REPEAT:
        if what in skip:
            continue
        counts = {}
        for dom, v in parts:
            if col in (blind.get(dom) or []):
                continue
            for vals in in_values(v, what):
                for x in dict.fromkeys(vals):
                    if not fi_blank(x) and x not in ("未填", "—", "未识别机型", "物料"):
                        counts[x] = counts.get(x, 0) + 1
        ranked, first, _t = fi_rank(list(counts.items()))
        if ranked and ranked[0][1] >= int(Q["repeat"]):
            out[what] = [[k, ranked[0][1]] for k in first]
    return out if len(out) > 2 else None


def in_months(parts, Q):
    stamps = [x for _dom, v in parts for x in v["_add"].tolist() if x is not None and not pd.isna(x)]
    if not stamps:
        return None
    lo, hi = min(stamps), max(stamps)
    span = (hi.year - lo.year) * 12 + hi.month - lo.month + 1
    if span < int(Q["months"]):
        return None
    counts = {}
    for x in stamps:
        key = x.strftime("%Y-%m")
        counts[key] = counts.get(key, 0) + 1
    _r, first, _t = fi_rank(list(counts.items()))
    if not first or len(first) > IN_PEAK_MAX:
        return None
    return {"发现": "时间", "名称": "时间分布", "建单月份范围": [lo.strftime("%Y-%m"), hi.strftime("%Y-%m")],
            "跨几个月": span, "建单最多的月份": [[k, counts[k]] for k in sorted(first)]}


def in_close(parts, Q):
    out = []
    for dom, v in parts:
        done = v[v["_done"].astype(bool)]
        vals = [int(x) for x in done["_close_days"].tolist() if x is not None and not pd.isna(x)] if len(done) else []
        if len(vals) >= int(Q["close_min"]):
            out.append({"域": dom, "结案周期中位数（天）": fi_round(fi_median(vals), 1), "计入张数": len(vals)})
    if not out:
        return None
    return {"发现": "时效", "名称": "结案时效", "各域已结案的单": out}


def in_focus(parts, Q, today, traits):
    """需关注的单：停线中 → A+、A 级且未结案 → 未结案、建单最久的 → 不良率最高的，取前 `focus` 张。"""
    cands = []
    for dom, v in parts:
        text_rate = (traits.get(dom) or {}).get("rate") == "text"
        for r in v.to_dict("records"):
            rate = None if text_rate or fi_blank(r.get("_rate_value")) else float(r["_rate_value"])
            cands.append({"dom": dom, "id": int(r["_id"]), "number": str(r.get("_number")),
                          "age": in_age(r.get("_add"), today), "level": r.get("level"),
                          "stopped": bool(r.get("_stopped_now")), "unclosed": bool(r.get("_unclosed")),
                          "rate": rate, "rate_text": r.get("rate")})

    def older(c):
        return (c["age"] is None, -(c["age"] or 0), c["number"])

    tiers = [
        (sorted([c for c in cands if c["stopped"]], key=older), lambda c: "停线中"),
        (sorted([c for c in cands if c["unclosed"] and c["level"] in IN_HIGH],
                key=lambda c: (c["level"] != "A+", *older(c))), lambda c: f"{c['level']} 级，未结案"),
        (sorted([c for c in cands if c["unclosed"]], key=older),
         lambda c: f"未结案 {c['age']} 天" if c["age"] is not None else "未结案"),
        (sorted([c for c in cands if c["rate"] is not None], key=lambda c: (-c["rate"], c["number"])),
         lambda c: f"不良率 {c['rate_text']}"),
    ]
    out, seen = [], set()
    for members, reason in tiers:
        for c in members:
            if len(out) >= int(Q["focus"]):
                return out
            key = (c["dom"], c["id"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"域": c["dom"], "问题编号": c["number"], "理由": reason(c), "id": c["id"]})
    return out


def in_day(ts):
    return None if ts is None or pd.isna(ts) else ts.strftime("%Y-%m-%d")


def in_sim_dates(parts):
    stamps = [x for _dom, v in parts for x in v["_add"].tolist() if x is not None and not pd.isna(x)]
    if len(stamps) < 2 or min(stamps).normalize() == max(stamps).normalize():
        return None
    return {"发现": "相近时间", "名称": "时间", "最早一次建单": in_day(min(stamps)), "最近一次建单": in_day(max(stamps))}


def in_sim_recur(parts):
    """同一域里某张单结案之后又建了相近的单：每域取之后建的张数最多的一张（并列取结案早的）。"""
    found = []
    for dom, v in parts:
        rows = v.to_dict("records")
        best = None
        for a in rows:
            close = a.get("_close")
            if not bool(a.get("_done")) or close is None or pd.isna(close):
                continue
            later = sorted([b for b in rows if b.get("_add") is not None and not pd.isna(b.get("_add"))
                            and b["_add"] > close], key=lambda b: (b["_add"], str(b.get("_number"))))
            if not later:
                continue
            key = (-len(later), close, str(a.get("_number")))
            if best is None or key < best[0]:
                best = (key, {"域": dom, "结案的单": a.get("_number"), "结案日期": in_day(close),
                              "之后又建的相近单": [b.get("_number") for b in later], "张数": len(later)})
        if best is not None:
            found.append(best[1])
    if not found:
        return None
    return {"发现": "结案后又出现", "名称": "结案后又出现", "各域": found}


#: 类似问题的共同点：(说法, 视图里靠主数据写出的列名，没取到主数据时这一域不看)
IN_COMMON = (("供应商", "ven_name"), ("机型", "_machines"), ("加工厂", "factory"), ("原因分类", "reason_class"))


def in_sim_common(parts, Q, blind):
    skip = set(Q.get("skip") or [])
    total = sum(int(len(v)) for _dom, v in parts)
    out = {"发现": "共同点", "名称": "共同点", "列出的张数": total}
    for what, col in IN_COMMON:
        if what in skip:
            continue
        counts = {}
        for dom, v in parts:
            if col in (blind.get(dom) or []):
                continue
            if what == "原因分类":
                if "reason_class" not in v.columns:
                    continue
                values = [[x] for x in v["reason_class"].tolist()]
            else:
                values = in_values(v, what)
            for vals in values:
                for x in dict.fromkeys(vals):
                    if not fi_blank(x) and x not in ("未填", "—", "未识别机型", "物料"):
                        counts[x] = counts.get(x, 0) + 1
        ranked, first, _t = fi_rank(list(counts.items()))
        if ranked and ranked[0][1] >= int(Q.get("common") or 2):
            out[what] = [[k, ranked[0][1]] for k in first]
    return out if len(out) > 3 else None


def in_sim_open(parts):
    items = []
    for dom, v in parts:
        u = v[v["_unclosed"].astype(bool)]
        for r in u.to_dict("records"):
            stages = [s for s in (r.get("_stages") or []) if not fi_blank(s)]
            items.append({"域": dom, "问题编号": r.get("_number"), "停在的环节": stages})
    if not items:
        return None
    return {"发现": "未结案", "名称": "未结案", "未结案的单": items}


def in_similar(parts, Q, blind=None):
    """类似问题的要点（总述「结论里的要点与需关注的单」末「类似问题的要点」，G86）：时间、结案后又出现、共同点、
    未结案，按这个顺序、至多 `points` 条；没有需关注。`parts`：[(域, 列出的相近问题)]，只陈述数据。"""
    if not Q:
        return {"points": [], "focus": []}
    parts = [(dom, v) for dom, v in parts if v is not None and len(v)]
    if sum(int(len(v)) for _dom, v in parts) < 2:
        return {"points": [], "focus": []}
    found = [in_sim_dates(parts), in_sim_recur(parts), in_sim_common(parts, Q, blind or {}), in_sim_open(parts)]
    return {"points": [x for x in found if x][: int(Q["points"])], "focus": []}


def in_insights(parts, Q, blind=None, traits=None):
    """要点（`points`，按表的顺序、至多 `points` 条）与需关注的单（`focus`）。`parts`：[(域, 视图)]。"""
    if not Q:
        return {"points": [], "focus": []}
    parts = [(dom, v) for dom, v in parts if v is not None and len(v)]
    total = sum(int(len(v)) for _dom, v in parts)
    if total <= IN_FEW:
        return {"points": [], "focus": []}
    today = pd.Timestamp(Q["today"])
    skip = set(Q.get("skip") or [])
    found = []
    if "集中" not in skip:
        found.append(in_concentrate(parts, total, Q))
    if "积压" not in skip:
        found.append(in_backlog(parts, today))
    found.append(in_severe(parts, Q))
    found.append(in_repeat(parts, Q, blind or {}))
    if "时间" not in skip:
        found.append(in_months(parts, Q))
    if "时效" not in skip:
        found.append(in_close(parts, Q))
    points = [x for x in found if x][: int(Q["points"])]
    focus = in_focus(parts, Q, today, traits or {}) if int(Q["focus"]) > 0 else []
    return {"points": points, "focus": focus}
