"""文字查找第 ② 步的取数（设计 §7.1 ②）：经 `ctx.data.fetch` 读本域分段表、文字表，匹配与计数在沙箱里做。

- 分段表预筛：`field IN 本次比对的栏目` AND（中文与夹英文的说法 `seg_compact CONTAINS 去空格的说法` OR 纯英文缩写
  `seg_norm CONTAINS 说法`）。说法已归一（`text/terms.py::term`）：PG 的 `CONTAINS` 编成区分大小写的 `LIKE`，而两列
  都是小写，不归一预筛会静默漏单。这是超集：屏蔽只会去掉命中，造不出命中。不按候选单筛（候选范围在沙箱里定）。
- 比对范围以外的栏目：读文字表的该列，不预筛（文字表只剥净、不归一化，见文字表族文件）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from factory_issue_module.declarations import MART, Domain
from factory_issue_module.domains import base


def seg_spec(domain: Domain, probes: Sequence[dict[str, Any]], codes: Sequence[str] | None) -> dict[str, Any] | None:
    """本域分段表的预筛 spec；没有要按分段表比的说法时为 None。"""
    terms = [t for p in probes if p.get("codes") is None or p.get("codes") for t in p["terms"]]
    if not terms:
        return None
    ors = [base.cond("seg_compact" if t["cjk"] else "seg_norm", "CONTAINS", t["key"])
           for t in {t["key"] + str(t["cjk"]): t for t in terms}.values()]
    groups: list[dict[str, Any]] = [{"logic": "OR", "conditions": ors}]
    if codes is not None:
        groups.insert(0, {"logic": "AND", "conditions": [base.cond("field", "IN", list(codes))]})
    return {"source": MART, "from": domain.seg_table, "select": ["seg_id", "issue_id", "field", "seg_text"],
            "filter": {"logic": "AND", "groups": groups}}


def codes_of(probes: Sequence[dict[str, Any]]) -> list[str] | None:
    """各组说法要比的分段表栏目的并集；有一组不限栏目时为 None。"""
    out: list[str] = []
    for p in probes:
        if p.get("codes") is None and not p.get("columns"):
            return None
        out += list(p.get("codes") or [])
    return list(dict.fromkeys(out))


def text_columns(probes: Sequence[dict[str, Any]], domain: Domain, available: Sequence[str]) -> list[str]:
    return [c for p in probes for c in p.get("columns") or [] if c in available]


async def fetch(ctx: Any, domain: Domain, probes: Sequence[dict[str, Any]], columns: Sequence[str]
                ) -> dict[str, pd.DataFrame]:
    """本域按词一路要的帧：`seg_<域>`、`txt_<域>`（沙箱的数据集名）。`TableDenied` 原样抛给调用方。"""
    out: dict[str, pd.DataFrame] = {}
    spec = seg_spec(domain, probes, codes_of(probes))
    if spec is not None and (codes_of(probes) is None or codes_of(probes)):
        out["seg_" + domain.label] = await base.fetch_all(ctx, spec, "seg_id")
    if columns:
        out["txt_" + domain.label] = await base.fetch_all(
            ctx, {"source": MART, "from": domain.text_table, "select": ["issue_id", *columns]}, "issue_id")
    return out
