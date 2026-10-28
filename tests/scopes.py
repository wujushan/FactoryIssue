"""按 `privileges.md` 的 v1.3 写法构造权限（设计 §15，单测夹具清单「三、权限分支」）。

默认效果取「拒绝」，已申请的域与 CAR 报告列为「允许」；主表与最外层表显式写不限行、不屏蔽列，
子表挂在本域主表下并继承父表；流程待办任务表带固定行规则。四段名的实例段写 `info` / `erp` / `mart`。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from factory_issue_module.declarations import (
    CAR_TABLE,
    DOMAINS,
    FACTORY_TABLE,
    LOOKUP_TABLES,
    MART,
    SHARED_TABLES,
    TASK_TABLE,
    Domain,
)

OPEN_ROW = {"mode": "DENY", "logic": "OR", "rules": []}
OPEN_COLUMN = {"mode": "DENY", "rules": []}
TASK_NAMES = ["ZCTracking_ProblemSoftware3", "ZCTracking_PreventionConfirm"]

#: 测试通道、调试对话关管控时平台给的「全放开」权限（`privileges.md`「没拿到权限时」）
GREEN = {"defaultEffect": "ALLOW", "dataScope": []}

_PARENT_KEY = {Domain.DOMESTIC: ("ID", "ProblemId"), Domain.BRAZIL: ("ID", "ProblemID"),
               Domain.OVERSEAS: ("Id", "ProblemId")}


def four_part(table: str) -> str:
    if table == FACTORY_TABLE:
        return f"erp.{table}"
    if "." not in table:
        return f"mart.{MART}.public.{table}"
    return f"info.{table}"


def outer(table: str, *, mode: str = "ALLOW", row: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"name": four_part(table), "mode": mode, "column": OPEN_COLUMN,
                            "cell": {}, "sub_tables": []}
    if mode == "ALLOW":
        body["row"] = row or OPEN_ROW
    return {"type": "DB", "table": body}


def _sub(domain: Domain, table: str) -> dict[str, Any]:
    parent, child = _PARENT_KEY[domain]
    return {
        "name": four_part(table), "mode": "ALLOW", "inherit_parent": True, "column": OPEN_COLUMN,
        "cell": {}, "sub_tables": [],
        "relation": {"mappings": [{"parent_field": parent, "child_field": child}]},
    }


def master(domain: Domain) -> dict[str, Any]:
    item = outer(domain.master_table)
    item["table"]["sub_tables"] = [_sub(domain, t) for t in domain.sub_tables]
    return item


def task_table() -> dict[str, Any]:
    rule = {"mode": "ALLOW", "logic": "OR", "rules": [{"logic": "AND", "conditions": [
        {"field": "ftable", "operator": "IN", "value": list(TASK_NAMES)}]}]}
    return outer(TASK_TABLE, row=rule)


def privileges(
    domains: Iterable[Domain] = (),
    *,
    car: bool = False,
    mart: bool = True,
    extra: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """按「权限里要列出的表」的「何时给允许」一列列出本用户该有的表。"""
    ds = set(domains)
    scope: list[dict[str, Any]] = [master(d) for d in DOMAINS if d in ds]
    lookups = {
        "CoreINFO.dbo.AfterSaleIssueClass": Domain.DOMESTIC in ds,
        "CoreINFO.dbo.AfterSaleIssueClassPhenomenon": bool(ds & {Domain.DOMESTIC, Domain.OVERSEAS}),
        "CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason": bool(
            ds & {Domain.DOMESTIC, Domain.OVERSEAS}
        ),
        "info.dbo.Brazil_Factory": Domain.BRAZIL in ds,
        "info.dbo.Brazil_RequestList": Domain.BRAZIL in ds,
    }
    assert set(lookups) == set(LOOKUP_TABLES)
    scope += [outer(t) for t in LOOKUP_TABLES if lookups[t]]
    if ds:
        scope += [outer(t) for t in (*SHARED_TABLES, FACTORY_TABLE)]
    if Domain.DOMESTIC in ds:
        scope.append(task_table())
    if car:
        scope.append(outer(CAR_TABLE))
    if mart:
        scope += [outer(t) for d in DOMAINS if d in ds for t in d.mart_tables]
    scope += list(extra)
    return {"version": "1.3", "defaultEffect": "DENY", "level": {"code": "A"}, "dataScope": scope}


def account_jia() -> dict[str, Any]:
    """测试账号甲 / J-P01：只申请了国内、没申请 CAR，共 25 张表。"""
    return privileges([Domain.DOMESTIC])


def no_domain() -> dict[str, Any]:
    """J-P02、J-P03：三个域都没申请。

    权限平台总是列出表清单（`privileges.md`「没拿到权限时」：带级别 A 却一张表都没列 = 整库放开），
    所以这里把三张主表显式列为拒绝，而不是给一个空的 dataScope。
    """
    return {
        "version": "1.3", "defaultEffect": "DENY", "level": {"code": "A"},
        "dataScope": [outer(d.master_table, mode="DENY") for d in DOMAINS],
    }


def count_tables(payload: dict[str, Any]) -> int:
    def walk(table: dict[str, Any]) -> int:
        return 1 + sum(walk(t) for t in table.get("sub_tables", []))

    return sum(walk(item["table"]) for item in payload["dataScope"])
