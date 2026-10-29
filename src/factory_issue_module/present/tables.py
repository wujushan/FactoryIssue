"""表格（设计 §9.1、§9.2）：沙箱给出的列名已是显示名，这里只把它包成事件，问题编号换成可跳转的链接。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from forge_core.events import Event

from factory_issue_module.config.files import LinkSites
from factory_issue_module.present import columns, links

NUMBER = columns.shown("number")


def event(table: dict[str, Any], title: str, *, link_ids: Sequence[int] | None = None, domain: Any = None,
          sites: LinkSites | None = None) -> Event:
    """`link_ids` 与行一一对应（沙箱给的单 ID，只进链接参数，不作文字展示）；`sites` 是本环境的站点地址。"""
    cols = list(table.get("columns") or [])
    rows = [list(r) for r in table.get("rows") or []]
    if link_ids is not None and NUMBER in cols:
        at = cols.index(NUMBER)
        for row, pid in zip(rows, link_ids, strict=False):
            row[at] = links.issue(sites, domain, row[at], pid)
    return Event.table(cols, rows, title=title)


def describe(title: str, table: dict[str, Any], shown: int | None) -> str:
    """交给写分析的模型看的表格说明：标题、列名、给了几行（行数由沙箱给）。"""
    cols = "、".join(str(c) for c in table.get("columns") or [])
    return f"{title}，列：{cols}" + (f"，共 {shown} 行" if shown is not None else "")
