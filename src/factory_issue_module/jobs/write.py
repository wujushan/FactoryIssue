"""写入（设计 §12 第 7 步）：每批一条语句，用数据修改型 CTE 把整批写成一个事务。

`ctx.etl.write(MART).execute(sql, params)` 每次调用开一个自动提交的连接、没有批量接口，所以一批的文字表行、两张段表
的删与插放进同一条语句。行数据以 JSON 文本传入、`jsonb_to_recordset` 展开；单 ID、段编号的集合也以 JSON 数组传入
（`jsonb_array_elements_text`），空集合与非空走同一种写法，不靠驱动推断数组类型。

- 删段只删「这批单里新段集合以外」的段，插段只碰新段集合，两者不碰同一行；同一语句里各 CTE 的执行先后不确定，
  这样写与先后无关。
- 按意思找的段表只在文字真变了时更新，内容哈希不变就不触发重嵌。
- 已删除或已不存在的单：一条语句从三张表一起删，平台回填随后删掉对应向量（G2）。
- SQL 里没有 `%`（PG 一侧经 psycopg 的 `%(name)s` 绑定），也没有带冒号的字面量（`:name` 会被当成占位符）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from factory_issue_module.jobs import ddl
from factory_issue_module.jobs.spec import DomainSource

_SEG_TYPES = {"seq": "int"}


def _ids(name: str) -> str:
    return f"(SELECT jsonb_array_elements_text(CAST(:{name} AS jsonb)))"


def _recordset(param: str, cols: Sequence[str]) -> str:
    defs = ", ".join(f"{c} {_SEG_TYPES.get(c, 'text')}" for c in cols)
    return f"jsonb_to_recordset(CAST(:{param} AS jsonb)) AS r({defs})"


def upsert_sql(spec: DomainSource) -> str:
    d = spec.domain
    text_cols = [c for c in ddl.text_columns(spec) if c != "synced_at"]
    text_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in text_cols if c != "issue_id")
    seg_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in ddl.SEG_COLUMNS if c != "seg_id")
    vseg_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in ddl.VSEG_COLUMNS if c != "seg_id")
    return (
        f"WITH t AS (INSERT INTO {d.text_table} ({', '.join(text_cols)}, synced_at) "
        f"SELECT {', '.join('r.' + c for c in text_cols)}, now() FROM {_recordset('text_rows', text_cols)} "
        f"ON CONFLICT (issue_id) DO UPDATE SET {text_set}, synced_at = EXCLUDED.synced_at RETURNING 1), "
        f"sd AS (DELETE FROM {d.seg_table} WHERE issue_id IN {_ids('ids')} "
        f"AND seg_id NOT IN {_ids('seg_ids')} RETURNING 1), "
        f"su AS (INSERT INTO {d.seg_table} ({', '.join(ddl.SEG_COLUMNS)}) "
        f"SELECT {', '.join('r.' + c for c in ddl.SEG_COLUMNS)} FROM {_recordset('seg_rows', ddl.SEG_COLUMNS)} "
        f"ON CONFLICT (seg_id) DO UPDATE SET {seg_set} RETURNING 1), "
        f"vd AS (DELETE FROM {d.vseg_table} WHERE issue_id IN {_ids('ids')} "
        f"AND seg_id NOT IN {_ids('vseg_ids')} RETURNING 1), "
        f"vu AS (INSERT INTO {d.vseg_table} ({', '.join(ddl.VSEG_COLUMNS)}) "
        f"SELECT {', '.join('r.' + c for c in ddl.VSEG_COLUMNS)} FROM {_recordset('vseg_rows', ddl.VSEG_COLUMNS)} "
        f"ON CONFLICT (seg_id) DO UPDATE SET {vseg_set} "
        f"WHERE {d.vseg_table}.seg_text IS DISTINCT FROM EXCLUDED.seg_text RETURNING 1) "
        "SELECT 1"
    )


def _scrub(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉文字里的 NUL：PG 的 jsonb 与 text 都不收 `\\u0000`，源库的富文本里偶尔会夹着它。"""
    return [{k: v.replace("\x00", "") if isinstance(v, str) else v for k, v in r.items()} for r in rows]


def upsert_params(text_rows: list[dict[str, Any]], seg_rows: list[dict[str, Any]],
                  vseg_rows: list[dict[str, Any]]) -> dict[str, str]:
    """一批的参数：都是 JSON 文本。段编号在一批里不重复（`ON CONFLICT DO UPDATE` 不许同一语句改同一行两次）。"""
    for rows, key in ((text_rows, "issue_id"), (seg_rows, "seg_id"), (vseg_rows, "seg_id")):
        keys = [r[key] for r in rows]
        if len(keys) != len(set(keys)):
            raise ValueError(f"同一批里 {key} 重复")
    text_rows, seg_rows, vseg_rows = (_scrub(rows) for rows in (text_rows, seg_rows, vseg_rows))
    dump = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    return {
        "text_rows": dump(text_rows), "ids": dump([r["issue_id"] for r in text_rows]),
        "seg_rows": dump(seg_rows), "seg_ids": dump([r["seg_id"] for r in seg_rows]),
        "vseg_rows": dump(vseg_rows), "vseg_ids": dump([r["seg_id"] for r in vseg_rows]),
    }


def delete_sql(spec: DomainSource) -> str:
    d = spec.domain
    parts = [f"{alias} AS (DELETE FROM {table} WHERE issue_id IN {_ids('ids')} RETURNING 1)"
             for alias, table in (("a", d.text_table), ("b", d.seg_table), ("c", d.vseg_table))]
    return "WITH " + ", ".join(parts) + " SELECT 1"


def delete_params(ids: Sequence[str]) -> dict[str, str]:
    return {"ids": json.dumps(list(ids), ensure_ascii=False)}
