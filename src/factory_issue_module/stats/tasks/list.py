"""清单（设计 §6.3、§8.1、§9.2；总述「清单默认列」「跨域规则」清单呈现）。

每域：视图 → 条件 → 时间 → 排序（默认建单时间倒序，排序值相同按问题编号）→ 前 `limit` 张 → 表格给前
`table_rows` 张；同时给分析用的事实、统计口径要的数与后一步引用的值。
"""

from factory_issue_module.stats.lib.common import fi_blank, fi_rank, fi_with_counts
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.views import vw_breakdowns, vw_counts, vw_filter, vw_sorted, vw_time

PARAMS = {}

LS_SORT = {"建单时间": "_add", "现场发现日期": "_found", "停线日期": "_stop", "结案时间": "_close",
           "不良率": "_rate_value", "不良数量": "_bad", "影响数量": "_impact"}


def ls_facts(v, P, cond_kinds):
    pairs_type, _f, _t = fi_rank(vw_counts(v, "type"))
    pairs_factory, _f, _t = fi_rank(vw_counts(v, "factory"))
    pairs_machine, _f, _t = fi_rank(vw_counts(v, "_machines", multi=True), 5)
    unclosed = v[~v["_done"].astype(bool)] if len(v) else v
    stopped = v[v["_stopped_now"].astype(bool)] if len(v) else v
    facts = {"张数": int(len(v)), "按问题类型": [list(p) for p in pairs_type],
             "按加工厂": [list(p) for p in pairs_factory], "按机型（前五）": [list(p) for p in pairs_machine[:5]],
             "未结案": int(len(unclosed)), "停线中": int(len(stopped))}
    rejected = int(v["_rejected"].astype(bool).sum()) if len(v) else 0
    if rejected:
        facts["未结案中生产角色驳回、流程已结束"] = rejected
    if 0 < len(stopped) <= 5:
        facts["停线中的单"] = stopped["_number"].tolist()
    if "停线中" in cond_kinds and len(stopped):
        facts["停线中且已完成"] = int(stopped["_done"].astype(bool).sum())
    rated = vw_sorted(v[v["_rate_value"].apply(lambda x: not fi_blank(x))], "_rate_value", True) if len(v) else v
    if len(rated):
        facts["不良率最高的单"] = [[r["_number"], r["rate"]] for _, r in rated.head(3).iterrows()]
    return fi_with_counts(facts)


def run(data):
    P = PARAMS
    L = P["list"]
    segments, issues, missing_domains = [], {}, []
    total_all = 0
    best = None
    for dom in P["domains"]:
        v = dm_view(dom, data, P)
        if v is None:
            missing_domains.append(dom)
            continue
        missing = []
        if len(v):
            v = vw_filter(v, P["conds"].get(dom))
            v, missing = vw_time(v, P["times"].get(dom))
        key = LS_SORT.get(L.get("sort_by") or "建单时间", "_add")
        v = vw_sorted(v, key if key in v.columns or len(v) == 0 else "_add", L.get("desc", True))
        found = int(len(v))
        if L.get("limit"):
            v = v.head(int(L["limit"]))
        cols = L["columns"][dom]
        head = v.head(int(L["table_rows"]))
        rows = [[r[c] for c in cols] for _, r in head.iterrows()]
        cond_kinds = [k for c in P["conds"].get(dom) or [] for k, _v in (c.get("items") or [])]
        caliber = {"未计入": missing}
        if len(v):
            rejected = int(v["_rejected"].astype(bool).sum())
            if rejected and any(k == "未结案" for k in cond_kinds):
                caliber["生产角色驳回"] = rejected
            if "停线中" in cond_kinds:
                caliber["停线中且已完成"] = int(v[v["_stopped_now"].astype(bool)]["_done"].astype(bool).sum())
        breakdowns = vw_breakdowns(v, P.get("breakdowns", {}).get(dom))
        facts = ls_facts(v, P, cond_kinds) if len(v) else {"张数": 0}
        if breakdowns:
            facts["分取值"] = breakdowns
        segments.append({"domain": dom, "table": {"columns": [P["names"][c] for c in cols], "rows": rows},
                         "breakdowns": breakdowns,
                         "found": found, "listed": int(len(v)), "shown": int(len(head)),
                         "ids_shown": [int(x) for x in head["_id"].tolist()] if len(head) else [],
                         "limited": int(len(v)) < found, "truncated": int(len(head)) < int(len(v)),
                         "empty": found == 0, "few": found <= 2,
                         "facts": facts, "caliber": caliber})
        issues[dom] = {"ids": [int(x) for x in v["_id"].tolist()] if len(v) else [],
                       "numbers": v["_number"].tolist() if len(v) else []}
        total_all += int(len(v))
        if len(v):
            rated = vw_sorted(v[v["_rate_value"].apply(lambda x: not fi_blank(x))], "_rate_value", True)
            if len(rated):
                top = rated.iloc[0]
                if best is None or top["_rate_value"] > best["rate"]:
                    best = {"domain": dom, "id": int(top["_id"]), "number": top["_number"],
                            "rate": float(top["_rate_value"])}
    refs = {"issues": issues, "count": total_all, "max_defect_rate_issue": best}
    return {"segments": segments, "refs": refs, "missing_domains": missing_domains, "total": total_all}
