"""按单分批读原文（设计 §12 第 4 步）：挑出要写的单按原文字节数组批，`WHERE … IN (…)` 取本批的主表叙述列与子表行，
另按操作人取姓名（去人名前缀用）。经 `ctx.etl.read("info").query(sql, params)`，`:name` 占位。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from factory_issue_module.declarations import SHARED_TABLES
from factory_issue_module.jobs.spec import DomainSource

#: 每批原文合计不超过约 20 MB、不超过 200 张；单张超过 20 MB 的单独一批（最大约 48 MB，G2）
BATCH_BYTES = 20_000_000
BATCH_ISSUES = 200
#: 按员工 ID 取姓名时每块的个数（SQL Server 一条语句至多 2,100 个参数）
NAME_CHUNK = 1000
EMPLOYEE_TABLE = next(t for t in SHARED_TABLES if t.endswith(".Employee"))


def batches(ids: Iterable[str], sizes: Mapping[str, int],
            max_bytes: int = BATCH_BYTES, max_issues: int = BATCH_ISSUES) -> list[list[str]]:
    """按单 ID 的数值先后、原文字节数贪心组批。"""
    out: list[list[str]] = []
    cur: list[str] = []
    total = 0
    for iid in sorted(ids, key=lambda x: (len(x), x)):
        size = sizes.get(iid, 0)
        if cur and (total + size > max_bytes or len(cur) >= max_issues):
            out.append(cur)
            cur, total = [], 0
        cur.append(iid)
        total += size
    if cur:
        out.append(cur)
    return out


def _in(alias: str, col: str, ids: list[int], prefix: str = "i") -> tuple[str, dict[str, Any]]:
    names = [f"{prefix}{n}" for n in range(len(ids))]
    return (f"{alias}.[{col}] IN ({', '.join(':' + n for n in names)})", dict(zip(names, ids, strict=True)))


def main_sql(spec: DomainSource, ids: list[int]) -> tuple[str, dict[str, Any]]:
    cols = [c for _, c in spec.main] + ([spec.phen_json] if spec.phen_json else [])
    where, params = _in("m", spec.id_col, ids)
    select = ", ".join(f"m.[{c}]" for c in cols)
    sql = (f"SELECT m.[{spec.id_col}] AS issue_id, m.[{spec.no_col}] AS issue_no, {select} "
           f"FROM {spec.master} AS m WHERE {where} AND {spec.alive_sql}")
    return sql, params


def sub_sqls(spec: DomainSource, ids: list[int]) -> dict[str, tuple[str, dict[str, Any]]]:
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    if spec.steps is not None:
        s = spec.steps
        where, params = _in("s", s.parent_col, ids)
        wanted = dict.fromkeys((s.id_col, s.key_col, s.name_col, s.user_col, s.result_col, s.opinion_col,
                                s.content_col))  # 海外认环节与环节名称是同一列
        cols = ", ".join(f"s.[{c}]" for c in wanted)
        out["steps"] = (f"SELECT s.[{s.parent_col}] AS issue_id, {cols} FROM {s.table} AS s WHERE {where}", params)
    if spec.process is not None:
        p = spec.process
        where, params = _in("p", p.parent_col, ids)
        cols = ", ".join(f"p.[{c}]" for c in (p.id_col, *(c for _, c in p.columns)))
        out["process"] = (f"SELECT p.[{p.parent_col}] AS issue_id, {cols} FROM {p.table} AS p WHERE {where}", params)
    if spec.cost is not None:
        c = spec.cost
        where, params = _in("c", c.parent_col, ids)
        out["cost"] = (
            f"SELECT c.[{c.parent_col}] AS issue_id, c.[{c.id_col}], c.[{c.type_col}], c.[{c.memo_col}] "
            f"FROM {c.table} AS c WHERE {where}", params)
    if spec.phen_rows is not None:
        r = spec.phen_rows
        where, params = _in("r", r.parent_col, ids)
        out["phen"] = (
            f"SELECT r.[{r.parent_col}] AS issue_id, r.[{r.id_col}], r.[{r.key_col}], p.[{r.master_text}] "
            f"FROM {r.table} AS r INNER JOIN {r.master} AS p ON p.[{r.master_id}] = r.[{r.key_col}] "
            f"WHERE {where}", params)
    return out


def employee_sqls(ids: Iterable[int]) -> list[tuple[str, dict[str, Any]]]:
    unique = sorted(set(ids))
    out = []
    for start in range(0, len(unique), NAME_CHUNK):
        where, params = _in("e", "ID", unique[start:start + NAME_CHUNK], prefix="u")
        out.append((f"SELECT e.[ID], e.[Name] FROM {EMPLOYEE_TABLE} AS e WHERE {where}", params))
    return out
