"""文字查找的假数据（S6b）：国内假单（`cn_data`，单 ID 1–4）在 mart 库里的文字表、分段表，照 S6a 写进 mart 的形状。

- 分段表 `seg_text` 开头是「栏目名：」，`seg_norm`、`seg_compact` 不带（`jobs/segment.py`）；文字表的叙述列只剥净、
  不归一化，处理步骤三列每条「环节名称：」开头、换行分隔。
- 假连接器不执行 WHERE：分段表预筛、按单 `IN` 取都原样返回整张表（是超集，匹配在沙箱里做）。
- `hit()` 造一条按意思找的命中（平台 `ctx.retrieval.search` 返回的样子：`metadata`、`text`、两种分数）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import cn_data
import pandas as pd

from factory_issue_module import landed
from factory_issue_module.declarations import DOMAINS, MART, Domain
from factory_issue_module.textnorm import compact, normalize

#: 单 ID → 栏目代号 → 文字（分段表与文字表同一份）
TEXTS: dict[int, dict[str, str]] = {
    1: {"desc": "触摸屏偶发失灵，客户反馈点击无反应", "reason": "TP 排线压伤", "measure": "更换 TP 排线"},
    2: {"desc": "外壳开裂，扣位断裂", "measure": "换料后正常"},
    3: {"desc": "电池起火冒烟", "reason": "电芯短路", "step": "工厂制程分析：电池鼓包后起火"},
    4: {"desc": "", "measure": "NFC天线换料"},
}
#: 比对范围以外、只在文字表里的列
EXTRA: dict[int, dict[str, str]] = {
    1: {"f_restart": "换电池后重启", "f_step_content": "停线重启审核：换电池\n工厂制程分析：排线压伤"},
    3: {"f_restart": "换电池后重启", "f_step_content": "工厂制程分析：换电池"},
}
_SEG_TEXT_COLUMNS = {"phen", "desc", "reason", "improve", "measure", "prev"}


def _title(code: str, domain: Domain = Domain.DOMESTIC) -> str:
    return landed.seg_fields()[code][domain.label]


def seg_rows(texts: dict[int, dict[str, str]] | None = None, domain: Domain = Domain.DOMESTIC) -> pd.DataFrame:
    rows = []
    for iid, fields in (TEXTS if texts is None else texts).items():
        for code, text in fields.items():
            if not text.strip():
                continue
            rows.append({"seg_id": f"{iid}-{code}-1", "issue_id": str(iid), "field": code, "seq": 1,
                         "seg_text": f"{_title(code, domain)}：{text}", "seg_norm": normalize(text),
                         "seg_compact": compact(text)})
    cols = ["seg_id", "issue_id", "field", "seq", "seg_text", "seg_norm", "seg_compact"]
    return pd.DataFrame(rows, columns=cols)


def text_rows(texts: dict[int, dict[str, str]] | None = None, extra: dict[int, dict[str, str]] | None = None,
              *, missing: tuple[int, ...] = (), numbers: dict[int, str] | None = None,
              domain: Domain = Domain.DOMESTIC) -> pd.DataFrame:
    names = [c.name for c in landed.text_columns() if domain.label in c.sources]
    numbers = numbers or {i: f"ZC99010{i:02d}" for i in range(1, 10)}
    rows = []
    for iid, fields in (TEXTS if texts is None else texts).items():
        if iid in missing:  # 还没整理进文字表（新建不久）
            continue
        row: dict[str, Any] = {"issue_id": str(iid), "issue_no": numbers.get(iid, str(iid))}
        row |= {c: "" for c in names}
        row |= {f"f_{code}": text for code, text in fields.items() if code in _SEG_TEXT_COLUMNS}
        row |= (extra if extra is not None else EXTRA).get(iid, {})
        rows.append(row)
    return pd.DataFrame(rows, columns=["issue_id", "issue_no", *names])


def load(h: Any, *, main: Any = None, texts: dict[int, dict[str, str]] | None = None,
         extra: dict[int, dict[str, str]] | None = None, missing: tuple[int, ...] = (), cn: bool = True) -> None:
    """国内假单（`cn_data`）与它们的文字表、分段表；巴西、海外的 mart 表给空表。"""
    if cn:
        cn_data.load(h, main=main)
    mart = h.connectors[MART]
    for d in DOMAINS:
        mart.frames[d.text_table] = text_rows({}, {}, domain=d)
        mart.frames[d.seg_table] = seg_rows({}, d)
    mart.frames[Domain.DOMESTIC.text_table] = text_rows(texts, extra, missing=missing)
    mart.frames[Domain.DOMESTIC.seg_table] = seg_rows(texts)


def main_with(**changes: dict[str, Any]) -> pd.DataFrame:
    """`cn_data` 的主表改几张单的几列：`main_with(**{"1": {"ProblemLevel": "A+"}})`。"""
    rows = cn_data.main_rows()
    for r in rows:
        r.update(changes.get(str(r["ID"]), {}))
    return pd.DataFrame(rows)


def hit(issue_id: Any, field: str, text: str, rerank: float | None = 0.9, score: float = 0.8) -> SimpleNamespace:
    return SimpleNamespace(metadata={"issue_id": str(issue_id), "field": field}, text=text, rerank_score=rerank,
                           score=score)
