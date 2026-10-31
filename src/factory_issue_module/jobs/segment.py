"""分段（设计 §12 第 6 步；G2「分段表」「按意思找的段表」「整理规则」）。

- 分段表：一单一个栏目一段，不切；`seg_text` 开头带栏目名，`seg_norm`、`seg_compact` 不带。
- 按意思找的段表：只收参与按意思找的内容（调用方已去掉国内问题现象、巴西海外的标准现象、不超过 10 个字的栏目
  与处理步骤条目），再按分段规则切：
  - `whole`：整单一段（评测对照组），栏目代号记 `whole`，按栏目找（`filters`）对它不起作用；
  - `field`：每个栏目一段；
  - `field_split`（默认）：每个栏目一段，超过 `split_over` 字的按句子拼成不超过 `seg_max` 字的段，段落之间
    保留换行；一段不到 `seg_min` 字而下一句放不下时把下一句截开补满；相邻段重叠一句（`overlap = "sentence"`）。
- 段编号 `<issue_id>:<栏目代号>:<序号>`，两张表各自编号。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from factory_issue_module.textnorm import compact, normalize

WHOLE = "whole"
#: 句末标点（中文与英文）；切开后标点留在前一句
_SENT_END = re.compile(r"(?<=[。！？!?；;])")


def seg_id(issue_id: str, code: str, seq: int) -> str:
    return f"{issue_id}:{code}:{seq}"


def seg_rows(issue_id: str, texts: Mapping[str, str], names: Mapping[str, str]) -> list[dict[str, Any]]:
    """分段表的行：`texts` 为栏目代号 → 剥净的文字（空的不写），顺序照 `names`。"""
    rows = []
    for code, title in names.items():
        text = texts.get(code, "")
        if not text:
            continue
        rows.append({
            "seg_id": seg_id(issue_id, code, 0), "issue_id": issue_id, "field": code, "seq": 0,
            "seg_text": f"{title}：{text}", "seg_norm": normalize(text), "seg_compact": compact(text),
        })
    return rows


def vseg_rows(issue_id: str, texts: Mapping[str, str], names: Mapping[str, str], cfg: Any) -> list[dict[str, Any]]:
    """按意思找的段表的行。`cfg` 是分段规则（`config.files.Segmentation`）。"""
    present = [(code, title, texts[code]) for code, title in names.items() if texts.get(code)]
    if not present:
        return []
    if cfg.rule == WHOLE:
        body = "\n".join(f"{title}：{text}" for _code, title, text in present)
        return [_vrow(issue_id, WHOLE, 0, body)]
    rows = []
    for code, title, text in present:
        chunks = [text] if cfg.rule == "field" else split(text, cfg)
        rows += [_vrow(issue_id, code, i, f"{title}：{chunk}") for i, chunk in enumerate(chunks)]
    return rows


def _vrow(issue_id: str, code: str, seq: int, text: str) -> dict[str, Any]:
    return {"seg_id": seg_id(issue_id, code, seq), "issue_id": issue_id, "field": code, "seq": seq, "seg_text": text}


# ---------------------------------------------------------------- field_split


def _sentences(paragraph: str) -> list[str]:
    return [s for s in _SENT_END.split(paragraph) if s.strip()]


def _units(text: str, seg_max: int) -> list[tuple[str, str]]:
    """文字 → [(句子, 前面的连接符)]：段落之间是换行，同一段里的句子之间不加；超长的句子按 `seg_max` 硬切。"""
    out: list[tuple[str, str]] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        joiner = "\n"
        for sentence in _sentences(paragraph):
            while len(sentence) > seg_max:
                out.append((sentence[:seg_max], joiner))
                sentence, joiner = sentence[seg_max:], ""
            if sentence:
                out.append((sentence, joiner))
                joiner = ""
    return out


def _length(parts: list[tuple[str, str]]) -> int:
    return sum(len(t) + len(j) for t, j in parts) - (len(parts[0][1]) if parts else 0)


def _join(parts: list[tuple[str, str]]) -> str:
    return "".join((j if i else "") + t for i, (t, j) in enumerate(parts))


def split(text: str, cfg: Any) -> list[str]:
    """`field_split` 的切法；不超过 `split_over` 字时整段返回。"""
    if len(text) <= cfg.split_over:
        return [text]
    chunks: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    for unit in _units(text, cfg.seg_max):
        if cur and _length([*cur, unit]) > cfg.seg_max:
            if _length(cur) < cfg.seg_min:
                room = cfg.seg_max - _length(cur) - len(unit[1])
                if room > 0:
                    cur.append((unit[0][:room], unit[1]))
                    unit = (unit[0][room:], "")
            chunks.append(cur)
            cur = []
            if cfg.overlap == "sentence":
                last = chunks[-1][-1][0]
                if _length([(last, ""), unit]) <= cfg.seg_max:
                    cur = [(last, "")]
        if unit[0]:
            cur.append(unit)
    if cur:
        chunks.append(cur)
    return [_join(c) for c in chunks]
