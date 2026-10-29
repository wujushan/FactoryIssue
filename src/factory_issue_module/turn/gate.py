"""权限前置（设计 §4.1；`privileges.md`「域闸门」）。

每轮开头调一次 `ctx.data.describe()`：它按当前用户的权限过滤、不访问数据库，与取数共用同一段表级
判定。由此定出：
- 三张主表各自可见 → 该域可查（主表无权时子表一律不查，即使子表本身没被拒）；
- CAR 报告表可见 → 有 CAR 报告权限；
- 本域文字表、分段表、向量表三张都可见 → 该域文字查找可用（S6 之前没声明 mart，一律不可用）。

整轮复用这一结果。取数时若仍撞上 `TableDenied`，以拒绝为准，用 `without()` 把该域改记为无权。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from forge_core.errors import PermissionDenied

from factory_issue_module.declarations import CAR_TABLE, DOMAINS, INFO, MART, Domain

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DomainAccess:
    domains: frozenset[Domain]
    car: bool
    text_search: frozenset[Domain]

    @property
    def none(self) -> bool:
        return not self.domains

    def can(self, domain: Domain) -> bool:
        return domain in self.domains

    def allowed(self) -> tuple[Domain, ...]:
        """可查的域，按国内、巴西、海外的顺序。"""
        return tuple(d for d in DOMAINS if d in self.domains)

    def denied(self) -> tuple[Domain, ...]:
        return tuple(d for d in DOMAINS if d not in self.domains)

    def without(self, domain: Domain) -> DomainAccess:
        """取数时撞上 `TableDenied`：以拒绝为准，该域改记为无权。"""
        return DomainAccess(
            domains=self.domains - {domain},
            car=self.car and domain is not Domain.DOMESTIC,
            text_search=self.text_search - {domain},
        )


def resolve(ctx: Any) -> DomainAccess | None:
    """定出本轮可查的域。拿不到可用的权限判断时返回 None，由编排按「没拿到权限」答。

    None 的两种来源都不是终端用户会遇到的：`ctx.data` 为 None（平台没配数据源）；`describe()`
    抛权限错误（模块声明了 `require_privileges=True`，而 Admin 调试对话、`forge dev serve` 默认
    授权树带的是空权限，抛 `PrivilegesRequiredError`；或权限配置本身写错）。
    """
    data = getattr(ctx, "data", None)
    if data is None:
        logger.error("factory_issue_gate_unavailable", reason="no_data_handle")
        return None
    try:
        catalogs = data.describe()
    except PermissionDenied as exc:
        logger.error("factory_issue_gate_unavailable", reason=type(exc).__name__)
        return None
    visible = {(c.source, t.table) for c in catalogs for t in c.tables}
    domains = frozenset(d for d in DOMAINS if (INFO, d.master_table) in visible)
    access = DomainAccess(
        domains=domains,
        car=Domain.DOMESTIC in domains and (INFO, CAR_TABLE) in visible,
        text_search=frozenset(
            d for d in domains if all((MART, t) in visible for t in d.mart_tables)
        ),
    )
    logger.info(
        "factory_issue_gate",
        domains=[d.value for d in access.allowed()],
        car=access.car,
        text_search=[d.value for d in DOMAINS if d in access.text_search],
    )
    return access
