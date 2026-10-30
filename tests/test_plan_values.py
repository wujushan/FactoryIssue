"""规划器对照集按「同义写法」计对的条件取值，执行层也要认（`scripts/planner_spike/common.py::VALUE_SYNONYMS`）。

对照集说一份计划是对的，执行层却对不上、改成追问，用户看到的就是答错了。CN-025「软件、硬件、结构三类」：
模型照抄写成「软件」「硬件」「结构」，对照集按同义计对，执行层原先只认全称，答成「没有『软件』这个问题类型」。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from factory_issue_module.declarations import Domain
from factory_issue_module.domains import base, enums

_COMMON = Path(__file__).resolve().parents[1] / "scripts" / "planner_spike" / "common.py"
_TYPES = {Domain.DOMESTIC: list(enums.CN_PROBLEM_TYPES.values()), Domain.BRAZIL: list(enums.BR_PROBLEM_TYPES),
          Domain.OVERSEAS: list(enums.OS_PROBLEM_TYPES.values())}
#: 只用在详情的 `aspects` 上，不是条件取值
_ASPECTS_ONLY = {"5why"}


def _synonyms() -> list[tuple[str, str]]:
    spec = importlib.util.spec_from_file_location("_spike_common", _COMMON)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return sorted((k, v) for k, v in mod.VALUE_SYNONYMS.items() if v not in _ASPECTS_ONLY)


def _type_in(domain: Domain, said: str) -> list[str]:
    got = base.problem_types([said], _TYPES[domain], domain.label, False, base.DomainStep(domain=domain))
    assert isinstance(got, list), f"{domain.label}把「{said}」改成了追问"
    return got


@pytest.mark.parametrize(("said", "want"), _synonyms())
def test_execution_accepts_what_the_spike_scores_as_equal(said, want):
    types = {t for ts in _TYPES.values() for t in ts}
    if want in types:
        for domain, known in _TYPES.items():
            assert _type_in(domain, said) == ([want] if want in known else [])
    elif want in ("已结案", "未结案"):
        assert enums.status_kind(said) == (want, "")
    elif want.upper() in enums.CN_LEVELS:
        assert enums.level_codes(said) == [want.upper()]
    elif want in ("是", "否"):
        assert base.yes_no(said) == (1 if want == "是" else 0)
    else:
        pytest.fail(f"对照集的同义写法「{said}」→「{want}」不知道归哪类条件，补进这个测试")


def test_type_suffix_rule_stays_narrow():
    """补「问题」只补在末尾：「制程」不是问题类型（总述「三域共用的说法」），照旧追问。"""
    got = base.problem_types(["制程"], _TYPES[Domain.DOMESTIC], "国内", False, base.DomainStep(domain=Domain.DOMESTIC))
    assert isinstance(got, base.Ask)
    assert _type_in(Domain.DOMESTIC, "软件类") == ["软件问题"]
    assert _type_in(Domain.DOMESTIC, "结构类问题") == ["结构问题"]
    assert _type_in(Domain.BRAZIL, "其他类") == ["其他"]
