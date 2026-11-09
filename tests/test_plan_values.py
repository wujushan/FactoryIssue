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


@pytest.mark.parametrize(("said", "want"), [
    ("硬件毛病", "硬件问题"), ("结构毛病", "结构问题"), ("结构方面的问题", "结构问题"), ("软件方面的毛病", "软件问题"),
    ("软件相关", "软件问题"), ("软件相关的单", "软件问题"), ("软件bug", "软件问题"), ("BUG", "软件问题"),
    ("软件BUG单", "软件问题"), ("软件缺陷", "软件问题"), ("物料方面", "物料问题"),
])
def test_type_colloquial_sayings(said, want):
    """问题类型的口语说法（决策 2026-11-09「问题类型的口语说法」）：程序固定认，不靠规划器改写。"""
    assert _type_in(Domain.DOMESTIC, said) == [want]


def test_type_colloquial_brazil_has_no_software():
    step = base.DomainStep(domain=Domain.BRAZIL)
    assert base.problem_types(["软件bug"], _TYPES[Domain.BRAZIL], "巴西", False, step) == []
    assert step.excluded == ["巴西无「软件问题」类型，未计入"]


@pytest.mark.parametrize("said", ["毛病", "制程相关", "电池毛病"])
def test_type_colloquial_still_asks_when_core_is_not_a_type(said):
    got = base.problem_types([said], _TYPES[Domain.DOMESTIC], "国内", False, base.DomainStep(domain=Domain.DOMESTIC))
    assert isinstance(got, base.Ask) and got.question.startswith(f"没有「{said}」这个问题类型")


@pytest.mark.parametrize("domain", list(_TYPES))
@pytest.mark.parametrize("said", ["电子料问题", "电子料不良", "电子料"])
def test_electronic_parts_asks_material_or_hardware(domain, said):
    """「电子料问题」不是类型、单上不区分电子料：追问按物料问题还是硬件问题查，选项直填回计划。"""
    got = base.problem_types([said], _TYPES[domain], domain.label, False, base.DomainStep(domain=domain))
    assert isinstance(got, base.Ask)
    assert got.options == ["物料问题", "硬件问题"] and got.said == said and got.fill == base.FILL_VALUE
    assert "不是问题类型" in got.question
