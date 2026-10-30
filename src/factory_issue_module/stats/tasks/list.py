"""清单（设计 §6.3、§8.1、§9.2、§9.3；总述「清单默认列」「跨域规则」清单呈现、「排名、长清单与导出」）。

每域：视图 → 条件 → 时间 → 排序（默认建单时间倒序，排序值相同按问题编号）→ 前 `limit` 张 → 表格给前
`table_rows` 张；同时给分析用的事实、统计口径要的数与后一步引用的值。
要导出（用户明说，或某域超过 `export_threshold` 张）时，该域的全部行（列与表格相同）作为明细帧放在返回值的
顶层（`export_<域>`），编排用 `return_frames=True` 从 `outcome.frames` 取，不塞进 `result`（20 万字符上限）。
结果单（后一步的 `issues` 引用、工作区 `results`）同样作为明细帧回传（`ids_<域>`：单 ID、问题编号）。
引用值另给各域张数（`found`），工作区存下供质疑重查比对（设计 §10）。
"""

import pandas as pd

from factory_issue_module.stats.lib.common import fi_blank, fi_rank, fi_with_counts
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.views import vw_breakdowns, vw_counts, vw_filter, vw_sorted, vw_time

PARAMS = {}

LS_SORT = {"建单时间": "_add", "现场发现日期": "_found", "停线日期": "_stop", "结案时间": "_close",
           "不良率": "_rate_value", "不良数量": "_bad", "影响数量": "_impact"}


def ls_facts(v, P, cond_kinds, blind=()):
    """分析用的事实。`blind` 是靠没取到的主数据才写得出来的列，不按它们分（否则全是「未填」）。"""
    pairs_type, _f, _t = fi_rank(vw_counts(v, "type"))
    unclosed = v[v["_unclosed"].astype(bool)] if len(v) else v
    stopped = v[v["_stopped_now"].astype(bool)] if len(v) else v
    facts = {"张数": int(len(v)), "按问题类型": [list(p) for p in pairs_type]}
    if "factory" not in blind:
        pairs_factory, _f, _t = fi_rank(vw_counts(v, "factory"))
        facts["按加工厂"] = [list(p) for p in pairs_factory]
    if "_machines" not in blind:
        pairs_machine, _f, _t = fi_rank(vw_counts(v, "_machines", multi=True), 5)
        facts["按机型（前五）"] = [list(p) for p in pairs_machine[:5]]
    facts.update({"未结案": int(len(unclosed)), "停线中": int(len(stopped))})
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


def ls_ids(v):
    """后一步引用、工作区要存的结果单（`limit` 之后、按表格的顺序）：单 ID 与问题编号，作为明细帧回传。"""
    if not len(v):
        return pd.DataFrame({"_id": pd.Series([], dtype="int64"), "_number": pd.Series([], dtype="object")})
    return pd.DataFrame({"_id": [int(x) for x in v["_id"].tolist()], "_number": [str(x) for x in v["_number"].tolist()]})


def ls_export(v, cols, names):
    """导出用的明细帧：该域的全部行（`limit` 之后），列与表格相同、列名是显示名。"""
    return pd.DataFrame([[r[c] for c in cols] for _, r in v.iterrows()], columns=[names[c] for c in cols])


def run(data):
    P = PARAMS
    L = P["list"]
    segments, issues, missing_domains = [], {}, []
    found_by, exports = {}, {}
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
        names = P["names"][dom]
        cond_kinds = [k for c in P["conds"].get(dom) or [] for k, _v in (c.get("items") or [])]
        caliber = {"未计入": missing}
        if len(v):
            rejected = int(v["_rejected"].astype(bool).sum())
            if rejected and any(k == "未结案" for k in cond_kinds):
                caliber["生产角色驳回"] = rejected
            if "停线中" in cond_kinds:
                caliber["停线中且已完成"] = int(v[v["_stopped_now"].astype(bool)]["_done"].astype(bool).sum())
        breakdowns = vw_breakdowns(v, P.get("breakdowns", {}).get(dom))
        facts = ls_facts(v, P, cond_kinds, P.get("blind", {}).get(dom) or []) if len(v) else {"张数": 0}
        if breakdowns:
            facts["分取值"] = breakdowns
        exported = bool(L.get("export_ok")) and len(v) > 0 and (
            bool(L.get("export")) or found > int(L.get("export_threshold") or 0))
        if exported:
            exports["export_" + dom] = ls_export(v, cols, names)
        segments.append({"domain": dom, "table": {"columns": [names[c] for c in cols], "rows": rows},
                         "breakdowns": breakdowns,
                         "found": found, "listed": int(len(v)), "shown": int(len(head)),
                         "ids_shown": [int(x) for x in head["_id"].tolist()] if len(head) else [],
                         "limited": int(len(v)) < found, "truncated": int(len(head)) < int(len(v)),
                         "empty": found == 0, "few": found <= 2, "exported": exported,
                         "facts": facts, "caliber": caliber})
        issues["ids_" + dom] = ls_ids(v)
        found_by[dom] = found
        total_all += int(len(v))
        if len(v):
            rated = vw_sorted(v[v["_rate_value"].apply(lambda x: not fi_blank(x))], "_rate_value", True)
            if len(rated):
                top = rated.iloc[0]
                if best is None or top["_rate_value"] > best["rate"]:
                    best = {"domain": dom, "id": int(top["_id"]), "number": top["_number"],
                            "rate": float(top["_rate_value"])}
    # 结果单（`issues`）不放进 refs：几千张单的编号会撑满 result 的 20 万字符，经数据帧通道回传（设计 §8.1）
    refs = {"count": total_all, "max_defect_rate_issue": best, "found": found_by}
    # 三域一起列清单时开头给各域张数与合计（总述「跨域规则」清单呈现）
    by_domain = [[s["domain"], s["found"]] for s in segments]
    found_total = sum(n for _d, n in by_domain)
    return {"segments": segments, "refs": refs, "missing_domains": missing_domains, "total": total_all,
            "found_total": found_total, "by_domain": by_domain, "few_total": found_total <= 2,
            "exported": [[s["domain"], s["listed"]] for s in segments if s["exported"]], **exports, **issues}
