"""本单文字指纹（设计 §12 第 2 步；G2「同步策略」按指纹增量）。

在源库里用 `HASHBYTES` 把每单叙述列、每行子表叙述列算成摘要，只把「单 ID + 摘要 + 原文字节数」拉回来，
内嵌图片不出库；任务里再把主表摘要与按（子表, 行 ID）排好的子表摘要合成本单指纹。

- 覆盖的列 = 文字表各列的来源（`jobs/spec.py`，与文字表表族文件逐列核对过），加上拼条目用到的环节编码 / 名称、
  操作人、费用类型、已选现象。现象主数据的文字改了不改变指纹，靠凌晨全量重建兜底；分段规则不进指纹。
- SQL 按兼容级别 100 写（`info` 连接默认进哪个库还没定）：不用 `TRY_CONVERT`、`STRING_SPLIT`、`CONCAT`、
  `STRING_AGG`、`CONCAT_WS`；首项转成 `NVARCHAR(MAX)` 免得拼接被截在 4,000 字。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from factory_issue_module.jobs.spec import DomainSource
from factory_issue_module.jobs.steps import as_int, as_text

_SEP = " + NCHAR(31) + "


def _col(alias: str, col: str) -> str:
    return f"{alias}.[{col}]"


def hash_expr(alias: str, cols: Iterable[str]) -> str:
    parts = [f"CAST(ISNULL({_col(alias, c)}, N'') AS NVARCHAR(MAX))" for c in cols]
    return f"HASHBYTES('SHA2_256', {_SEP.join(parts)})"


def bytes_expr(alias: str, cols: Iterable[str]) -> str:
    return " + ".join(f"ISNULL(DATALENGTH({_col(alias, c)}), 0)" for c in cols)


def main_hashed(spec: DomainSource) -> tuple[str, ...]:
    """主表进指纹的列：问题编号、各叙述列、问题现象 JSON。"""
    cols = [spec.no_col, *(c for _, c in spec.main)]
    if spec.phen_json:
        cols.append(spec.phen_json)
    return tuple(cols)


def hashed_columns(spec: DomainSource) -> dict[str, tuple[str, ...]]:
    """（表 → 进指纹的列）：单测拿它与文字表各列的来源对照。键列（环节、操作人、费用类型、现象）也算。"""
    out = {spec.master: main_hashed(spec)}
    if spec.steps is not None:
        s = spec.steps
        out[s.table] = (s.key_col, s.name_col, s.user_col, s.result_col, s.opinion_col, s.content_col)
    if spec.process is not None:
        out[spec.process.table] = tuple(c for _, c in spec.process.columns)
    if spec.cost is not None:
        out[spec.cost.table] = (spec.cost.type_col, spec.cost.memo_col)
    if spec.phen_rows is not None:
        out[spec.phen_rows.table] = (spec.phen_rows.key_col,)
    return out


def main_sql(spec: DomainSource) -> str:
    cols = main_hashed(spec)
    narrative = [c for _, c in spec.main] + ([spec.phen_json] if spec.phen_json else [])
    return (
        f"SELECT {_col('m', spec.id_col)} AS issue_id, {_col('m', spec.no_col)} AS issue_no, "
        f"{hash_expr('m', cols)} AS fp, {bytes_expr('m', narrative)} AS size "
        f"FROM {spec.master} AS m WHERE {spec.alive_sql}"
    )


def _join_master(spec: DomainSource, alias: str, parent_col: str) -> str:
    return (f"INNER JOIN {spec.master} AS m ON {_col('m', spec.id_col)} = {_col(alias, parent_col)} "
            f"WHERE {spec.alive_sql}")


def sub_sqls(spec: DomainSource) -> dict[str, str]:
    """子表每行一行：所属单、行 ID、键列（`k1`–`k3`）、叙述列摘要与字节数。都连主表、带未删除条件。"""
    out: dict[str, str] = {}
    if spec.steps is not None:
        s = spec.steps
        cols = (s.result_col, s.opinion_col, s.content_col)
        out["steps"] = (
            f"SELECT {_col('s', s.parent_col)} AS issue_id, {_col('s', s.id_col)} AS row_id, "
            f"{_col('s', s.key_col)} AS k1, {_col('s', s.name_col)} AS k2, {_col('s', s.user_col)} AS k3, "
            f"{hash_expr('s', cols)} AS fp, {bytes_expr('s', cols)} AS size "
            f"FROM {s.table} AS s {_join_master(spec, 's', s.parent_col)}"
        )
    if spec.process is not None:
        p = spec.process
        cols = tuple(c for _, c in p.columns)
        out["process"] = (
            f"SELECT {_col('p', p.parent_col)} AS issue_id, {_col('p', p.id_col)} AS row_id, "
            f"{hash_expr('p', cols)} AS fp, {bytes_expr('p', cols)} AS size "
            f"FROM {p.table} AS p {_join_master(spec, 'p', p.parent_col)}"
        )
    if spec.cost is not None:
        c = spec.cost
        out["cost"] = (
            f"SELECT {_col('c', c.parent_col)} AS issue_id, {_col('c', c.id_col)} AS row_id, "
            f"{_col('c', c.type_col)} AS k1, {hash_expr('c', [c.memo_col])} AS fp, "
            f"{bytes_expr('c', [c.memo_col])} AS size "
            f"FROM {c.table} AS c {_join_master(spec, 'c', c.parent_col)}"
        )
    if spec.phen_rows is not None:
        r = spec.phen_rows
        out["phen"] = (
            f"SELECT {_col('r', r.parent_col)} AS issue_id, {_col('r', r.id_col)} AS row_id, "
            f"{_col('r', r.key_col)} AS k1 "
            f"FROM {r.table} AS r {_join_master(spec, 'r', r.parent_col)}"
        )
    return out


@dataclass(frozen=True)
class Print:
    issue_no: str
    fingerprint: str
    size: int


def _hex(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return as_text(value)


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or len(frame) == 0:
        return []
    return frame.to_dict("records")


def combine(main: Any, subs: Mapping[str, Any]) -> dict[str, Print]:
    """主表摘要 + 按（子表名, 行 ID）排好的子表摘要 → 本单指纹（sha256 十六进制）与原文字节数。"""
    lines: dict[str, list[tuple[str, int, str]]] = {}
    sizes: dict[str, int] = {}
    for name in sorted(subs):
        for r in _records(subs[name]):
            pid = as_int(r.get("issue_id"))
            if pid is None:
                continue
            key = "|".join(as_text(r.get(k)) for k in ("k1", "k2", "k3"))
            rid = as_int(r.get("row_id")) or 0
            lines.setdefault(str(pid), []).append((name, rid, f"{key}|{_hex(r.get('fp'))}"))
            sizes[str(pid)] = sizes.get(str(pid), 0) + (as_int(r.get("size")) or 0)
    out: dict[str, Print] = {}
    for r in _records(main):
        pid = as_int(r.get("issue_id"))
        if pid is None:
            continue
        iid = str(pid)
        parts = [_hex(r.get("fp"))]
        parts += [f"{name}|{rid}|{body}" for name, rid, body in sorted(lines.get(iid, []))]
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        out[iid] = Print(issue_no=as_text(r.get("issue_no")), fingerprint=digest,
                         size=(as_int(r.get("size")) or 0) + sizes.get(iid, 0))
    return out
