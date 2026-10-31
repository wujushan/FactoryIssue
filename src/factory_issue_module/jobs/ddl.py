"""三张治理表的建表与核对列（设计 §12 第 1 步与「三张治理表的 DDL」）。

每轮开头 `CREATE TABLE IF NOT EXISTS`；之后经只读句柄读 `information_schema.columns` 核对列（写句柄的 `execute`
只回影响的行数，读不回列）。`IF NOT EXISTS` 不会给已存在的表补列、删列，对不上就让任务失败并报出差在哪几列
（文字表的列首轮之后再改，要删表再全量重建一次）。向量表由平台建，不在这里。
"""

from __future__ import annotations

from typing import Any

from factory_issue_module.jobs.spec import DomainSource

TEXT_HEAD = ("issue_id", "issue_no")
TEXT_TAIL = ("text_fingerprint", "synced_at")
SEG_COLUMNS = ("seg_id", "issue_id", "field", "seq", "seg_text", "seg_norm", "seg_compact")
VSEG_COLUMNS = ("seg_id", "issue_id", "field", "seq", "seg_text")


class MartTableMismatch(RuntimeError):
    """mart 里已有的治理表与这一版声明的列对不上。"""


def text_columns(spec: DomainSource) -> tuple[str, ...]:
    return (*TEXT_HEAD, *spec.text_columns(), *TEXT_TAIL)


def expected(spec: DomainSource) -> dict[str, tuple[str, ...]]:
    d = spec.domain
    return {d.text_table: text_columns(spec), d.seg_table: SEG_COLUMNS, d.vseg_table: VSEG_COLUMNS}


def statements(spec: DomainSource) -> list[str]:
    d = spec.domain
    narrative = ", ".join(f"{c} text NOT NULL" for c in spec.text_columns())
    return [
        f"CREATE TABLE IF NOT EXISTS {d.text_table} (issue_id text PRIMARY KEY, issue_no text NOT NULL, "
        f"{narrative}, text_fingerprint text NOT NULL, synced_at timestamptz NOT NULL)",
        f"CREATE TABLE IF NOT EXISTS {d.seg_table} (seg_id text PRIMARY KEY, issue_id text NOT NULL, "
        "field text NOT NULL, seq int NOT NULL, seg_text text NOT NULL, seg_norm text NOT NULL, "
        "seg_compact text NOT NULL)",
        f"CREATE INDEX IF NOT EXISTS {d.seg_table}_issue ON {d.seg_table} (issue_id)",
        f"CREATE TABLE IF NOT EXISTS {d.vseg_table} (seg_id text PRIMARY KEY, issue_id text NOT NULL, "
        "field text NOT NULL, seq int NOT NULL, seg_text text NOT NULL)",
    ]


def columns_sql(spec: DomainSource) -> tuple[str, dict[str, Any]]:
    names = list(expected(spec))
    marks = ", ".join(f":t{i}" for i in range(len(names)))
    sql = ("SELECT table_name, column_name FROM information_schema.columns "
           f"WHERE table_schema = 'public' AND table_name IN ({marks})")
    return sql, {f"t{i}": n for i, n in enumerate(names)}


def check(spec: DomainSource, frame: Any) -> None:
    """建表后读回的列与声明的逐张比对；缺列、多列都让任务失败。"""
    found: dict[str, set[str]] = {}
    for r in ([] if frame is None or len(frame) == 0 else frame.to_dict("records")):
        found.setdefault(str(r["table_name"]), set()).add(str(r["column_name"]).lower())
    problems = []
    for table, cols in expected(spec).items():
        have = found.get(table, set())
        missing = [c for c in cols if c not in have]
        extra = sorted(have - set(cols))
        if not have:
            problems.append(f"{table} 读不到列（表没建成，或只读账号没被授权读这张表）")
        elif missing or extra:
            problems.append(f"{table} 缺列 {missing or '无'}、多出 {extra or '无'}")
    if problems:
        raise MartTableMismatch(
            "治理表与这一版的列对不上：" + "；".join(problems)
            + "。文字表改了列要删表后跑一次全量重建（rebuild_issue_text）"
        )


def ensure(spec: DomainSource, writer: Any, reader: Any) -> None:
    for sql in statements(spec):
        writer.execute(sql)
    sql, params = columns_sql(spec)
    check(spec, reader.query(sql, params))
