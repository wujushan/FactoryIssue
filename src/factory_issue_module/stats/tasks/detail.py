"""单张单详情（设计 §6.3 `issue_detail` 一行、§8.1、§13）：每步一次，输入各域本步取回的帧（主表含叙述列、全部子表、
文档与主数据），给每张要看的单的各块（`stats/lib/detail.py`）。

`mode` 为 `reasons` 时只给每张单「原因与措施」合成的一格：第 5 条前半，详情引用前一步的清单、只要原因或措施时
并进清单（设计 §5.3 第 5 条）。关联了 CAR 的单另带报告 ID 与 CAR 编号，链接由 `handle()` 一侧拼。
"""

from factory_issue_module.stats.lib.detail import dt_reason_text, dt_tickets

PARAMS = {}


def run(data):
    P = PARAMS
    tickets = dt_tickets(data, P)
    if P.get("mode") == "reasons":
        out = []
        for t in tickets:
            block = t["blocks"]["reasons"]
            out.append({"domain": t["domain"], "id": t["id"], "text": dt_reason_text(block, P["labels"]),
                        "car_id": block.get("car_id"), "car_text": block.get("car_text")})
        return {"reasons": out}
    return {"tickets": tickets}
