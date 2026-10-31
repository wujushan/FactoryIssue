"""处理步骤的整理（设计 §12 第 5 步；总述「比对范围」「点名字段时怎么找」；G2「整理规则」）。

一张单的处理步骤整理出两样东西：
- 文字表的三列（结论、意见、内容）：每个环节取最新一条，**全部环节**都取（点名「处理步骤意见里写了返工」时用）；
  结论只取工厂制程分析，其余环节的结论是代码、日期或员工 ID。
- 分段表的「处理步骤」栏目：只取配置里的**分析类环节**，每个环节最新一条，条目 =「环节名称：」+ 意见（内容里已含
  意见时不加）+ 去掉人名前缀的内容 + 工厂制程分析的结论（内容里已含时不加）；同单内相同的条目只留一条。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from factory_issue_module.jobs.clean import clean, strip_name
from factory_issue_module.jobs.spec import StepSource
from factory_issue_module.textnorm import compact

_PART_SEP = "；"


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None if value is None else int(value)
    if isinstance(value, float):
        return None if math.isnan(value) or value != int(value) else int(value)
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def as_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


@dataclass
class StepText:
    result: str = ""
    opinion: str = ""
    content: str = ""
    #: 分析类环节的条目：(「环节名称：」, 条目正文)
    entries: list[tuple[str, str]] = field(default_factory=list)
    #: 内容非空的记录（每个环节最新一条，全部环节）：环节名称 → [去掉了姓名的条数, 没去掉的条数]
    prefix: dict[str, list[int]] = field(default_factory=dict)
    #: 不在分析类清单里的环节（国内编码、海外名称），统计行里报
    outside: set[str] = field(default_factory=set)

    def analysis_text(self) -> str:
        return "\n".join(head + body for head, body in self.entries)


def step_key(src: StepSource, row: Mapping[str, Any]) -> int | str | None:
    raw = row.get(src.key_col)
    if isinstance(src.factory_key, int):
        return as_int(raw)
    text = as_text(raw)
    return text or None


def latest(rows: Iterable[Mapping[str, Any]], src: StepSource) -> list[Mapping[str, Any]]:
    """每个环节 ID 最大的一条，按 ID 先后排。"""
    best: dict[int | str, tuple[int, Mapping[str, Any]]] = {}
    for row in rows:
        key, rid = step_key(src, row), as_int(row.get(src.id_col))
        if key is None or rid is None:
            continue
        if key not in best or rid > best[key][0]:
            best[key] = (rid, row)
    return [row for _rid, row in sorted(best.values(), key=lambda pair: pair[0])]


def build(
    rows: Iterable[Mapping[str, Any]],
    src: StepSource,
    analysis_keys: Iterable[int | str],
    names: Mapping[int, str],
) -> StepText:
    """一张单的处理步骤 → 文字表三列与分析类条目。`names`：员工 ID → 姓名（去人名前缀用）。"""
    wanted = set(analysis_keys)
    out = StepText()
    results: list[str] = []
    opinions: list[str] = []
    contents: list[str] = []
    for row in latest(rows, src):
        key = step_key(src, row)
        name = as_text(row.get(src.name_col))
        head = f"{name}：" if name else ""
        result = clean(row.get(src.result_col))
        opinion = clean(row.get(src.opinion_col))
        raw_content = clean(row.get(src.content_col))
        content, removed = strip_name(raw_content, names.get(as_int(row.get(src.user_col)) or -1))
        is_factory = key == src.factory_key
        if is_factory and result:
            results.append(head + result)
        if opinion:
            opinions.append(head + opinion)
        if content:
            contents.append(head + content)
        if raw_content:  # 全部环节的内容都去姓名、都进文字表，所以都计数（S6a 评审 A1）
            counts = out.prefix.setdefault(name or str(key), [0, 0])
            counts[0 if removed else 1] += 1
        if key not in wanted:
            out.outside.add(str(key))
            continue
        held = compact(content)
        parts = []
        if opinion and compact(opinion) not in held:
            parts.append(opinion)
        if content:
            parts.append(content)
        if is_factory and result and compact(result) not in held:
            parts.append(result)
        if parts:
            entry = (head, _PART_SEP.join(parts))
            if entry not in out.entries:
                out.entries.append(entry)
    out.result, out.opinion, out.content = ("\n".join(x) for x in (results, opinions, contents))
    return out
