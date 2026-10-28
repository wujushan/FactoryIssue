"""待办任务表行规则的 `field_mappings` 编译（设计 §3 实测 ①②③，收进 J-P12 的编译断言）。

S0 只验 manifest 的表级映射：有映射时权限段编成 `ftable IN (两个业务表名)`；缺映射时 fail-closed；
「全放开」权限下权限段是 `1 = 1`，本模块自带的业务表名条件照样在。待办任务的取数模板与派生函数
自己的过滤在 S2（`domains/domestic.py`、`derive_domestic.current_state`）补齐 J-P12 的另一半。
"""

from __future__ import annotations

import pytest
import scopes
from fakes import make_harness
from forge_core.dataquery import QuerySpec
from forge_core.errors import MappingMissingError

from factory_issue_module.declarations import INFO, TASK_TABLE


def _task_spec() -> QuerySpec:
    return QuerySpec.model_validate({
        "source": INFO,
        "from": TASK_TABLE,
        "select": ["frecID", "ftable", "fuserID"],
        "filter": {"groups": [{"conditions": [
            {"field": "ftable", "operator": "IN", "value": scopes.TASK_NAMES},
            {"field": "fstat", "operator": "EQ", "value": "已接受"},
            {"field": "frecID", "operator": "IN", "value": ["9901001", "9901002"]},
        ]}]},
    })


def _only_query(h):
    assert len(h.queries) == 1
    return h.queries[0]


def test_row_rule_compiles_onto_ftable_with_table_level_mapping():
    h = make_harness(scopes.account_jia())
    h.ctx.data.fetch(_task_spec())
    q = _only_query(h)
    assert q.tables == ("tbTask",)
    assert "[tbTask].[ftable] IN (:t0s_0, :t0s_1)" in q.sql
    scope_params = sorted(v for k, v in q.params.items() if k.startswith("t0s_"))
    assert scope_params == sorted(scopes.TASK_NAMES)
    module_params = [v for k, v in q.params.items() if k.startswith("_forge_p_")]
    assert scopes.TASK_NAMES[0] in module_params and "已接受" in module_params


def test_missing_mapping_fails_closed():
    h = make_harness(scopes.account_jia(), field_mappings={})
    with pytest.raises(MappingMissingError):
        h.ctx.data.fetch(_task_spec())
    assert h.queries == []


def test_green_light_scope_is_open_but_module_condition_stays():
    h = make_harness(scopes.GREEN)
    h.ctx.data.fetch(_task_spec())
    q = _only_query(h)
    assert "1 = 1" in q.sql
    assert not any(k.startswith("t0s_") for k in q.params)
    assert "[tbTask].[ftable] IN (" in q.sql
    assert [v for k, v in q.params.items() if k.startswith("_forge_p_")][:2] == scopes.TASK_NAMES
