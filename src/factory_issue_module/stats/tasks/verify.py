"""质疑重查的比对（设计 §4.3 `verify_previous` 一行、§10）：上一轮存下的单 ID、张数与这次按同一份执行计划
重查的结果逐步逐域比，只比本轮可查的域。哪些单多了、少了，张数各是多少，都在这里算。

参数：`steps` 步骤编号；`old`、`new` 为 {步骤: {域: {ids, numbers, found}}}；`domains` 为 {步骤: [要比的域]}；
`cap` 为工作区每域存的单 ID 上限：任一边到了上限（存下的只是前一段），这一域只比张数，不列单的增减；
`table_rows`；`texts` 为「变化」一列的说法。
"""

PARAMS = {}


def vf_pairs(item):
    ids = [int(x) for x in (item or {}).get("ids") or []]
    nums = [str(x) for x in (item or {}).get("numbers") or []]
    return ids, nums


def run(data):
    P = PARAMS
    cap = int(P.get("cap") or 5000)
    texts = P["texts"]
    steps, rows, row_ids = [], [], []
    for sid in P["steps"]:
        old = (P["old"].get(sid) or {})
        new = (P["new"].get(sid) or {})
        items, same_all = [], True
        for dom in P["domains"].get(sid) or []:
            o, n = old.get(dom) or {}, new.get(dom) or {}
            o_ids, o_nums = vf_pairs(o)
            n_ids, n_nums = vf_pairs(n)
            o_found, n_found = int(o.get("found") or 0), int(n.get("found") or 0)
            # 存满了（工作区每域只存前 `cap` 张）：存下的只是一段，按单比会把截掉的那截报成新查到，只比张数
            partial = len(o_ids) >= cap or len(n_ids) >= cap
            o_set, n_set = set(o_ids), set(n_ids)
            added = [] if partial else [(i, x) for i, x in zip(n_ids, n_nums) if i not in o_set]
            removed = [] if partial else [(i, x) for i, x in zip(o_ids, o_nums) if i not in n_set]
            same = o_found == n_found and not added and not removed
            same_all = same_all and same
            items.append({"domain": dom, "old": o_found, "new": n_found, "same": same, "partial": partial,
                          "had": dom in old, "added": [x for _i, x in added], "removed": [x for _i, x in removed],
                          "added_count": len(added), "removed_count": len(removed)})
            for i, x in added:
                rows.append([x, dom, texts["added"]])
                row_ids.append([dom, i])
            for i, x in removed:
                rows.append([x, dom, texts["removed"]])
                row_ids.append([dom, i])
        steps.append({"sid": sid, "same": same_all, "domains": items})
    limit = int(P.get("table_rows") or 20)
    return {"steps": steps, "rows": rows[:limit], "row_ids": row_ids[:limit], "rows_total": len(rows),
            "rows_more": len(rows) > limit, "changed": any(not s["same"] for s in steps)}
