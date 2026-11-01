"""临时统计的第一次沙箱调用：整理输入帧（设计 §5.5、§8.1）。

本步的条件照统计那一套筛（视图 → 条件 → 时间，与 `aggregate.py` 同一套 `dm_view`、`vw_filter`、`vw_time`），
每域整理成显示名列的行（`custom.cs_rows`），合成一张一单一行、带「所属域」的帧，按建单时间从新到旧、同时间按
问题编号排。返回：
- `frame`：这张帧，经数据帧通道回传，第二次调用作为数据集 `issues` 传给模型写的脚本；
- `ids_<域>`：计入这一步的单（单 ID、问题编号），工作区存下供质疑重查比对，同统计；
- `found`（各域张数）、`total`、`sample`（前几行，只交本地模型）、`caliber`：形状与统计的跨域各段相同（S7 评审
  M1、M2）——「未计入」是 `[[日期依据, 张数], …]`，几域同一依据相加（`views.vw_merge_missing`）；「没有结案时间」是
  已结案却定不出结案时间的张数，几域相加成一个整数；
- 有海外时 `rate_lists`：海外不良率是单上原文，逐单列出原文（`views.vw_rate_list`），脚本用到不良率时呈现。
"""

from factory_issue_module.stats.lib.common import fi_blank
from factory_issue_module.stats.lib.custom import cs_rows, cs_sample, cs_typed
from factory_issue_module.stats.lib.domains import dm_view
from factory_issue_module.stats.lib.views import vw_filter, vw_ids, vw_merge_missing, vw_rate_list, vw_sorted, vw_time

PARAMS = {}


def run(data):
    P = PARAMS
    S = P["cs"]
    cols = S["columns"]
    rows, ids, found, missing, rate_lists = [], {}, {}, [], {}
    no_close = 0
    for dom in P["domains"]:
        v = dm_view(dom, data, P)
        if v is None:
            continue
        if len(v):
            v = vw_filter(v, P["conds"].get(dom))
            v, miss = vw_time(v, P["times"].get(dom))
            missing += miss
        v = vw_sorted(v, "_add", True)
        found[dom] = int(len(v))
        ids["ids_" + dom] = vw_ids(v)
        if len(v):
            done = v[v["_done"].astype(bool)]
            no_close += int(done["_close"].apply(fi_blank).sum()) if len(done) else 0
        rows += cs_rows(v, dom, cols)
        if dom in (S.get("rate_text") or []):
            rate_lists[dom] = vw_rate_list(v, P["names"][dom], S["table_rows"])
    frame = cs_typed(rows, cols)
    if len(frame):
        frame = frame.sort_values([S["add_col"], S["number_col"]], ascending=[False, True], na_position="last",
                                  kind="mergesort").reset_index(drop=True)
    total = int(len(frame))
    return {"frame": frame, **ids, "found": found, "total": total, "sample": cs_sample(frame, S["sample_rows"]),
            "caliber": {"未计入": vw_merge_missing(missing), "没有结案时间": no_close}, "rate_lists": rate_lists}
