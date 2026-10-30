"""认号（`domains/numbers.py`；总述「按编号查单」认号表与对不上时怎么答）。

号与种类的写法照对照集里模型的实际写法（`runtime/planner_spike/20261029-p2.2` 里 `lookup_numbers` 的 `kind_said`：
null、「CAR 编号」「订单号」「投诉单号」「物料或 PN」「发货单号」「PN」），S3 的教训。
"""

from __future__ import annotations

import pytest

from factory_issue_module.declarations import Domain
from factory_issue_module.domains import numbers as N


def kinds(raw: str, said: str | None = None, query: str = "") -> list[tuple[str, str, tuple[str, ...]]]:
    got = N.recognize(raw, said, query)
    return [(lk.kind, lk.value, tuple(d.label for d in lk.domains)) for lk in got.lookups]


@pytest.mark.parametrize(("raw", "value", "domain"), [
    ("ZC2509012", "ZC2509012", "国内"), ("zc2509012", "ZC2509012", "国内"), ("ZC 2509012", "ZC2509012", "国内"),
    ("ZC-2509-012", "ZC2509012", "国内"), ("ＢＲ２６０１００９", "BR2601009", "巴西"), ("HW2512001", "HW2512001", "海外"),
])
def test_issue_numbers_are_normalized_and_domain_by_prefix(raw, value, domain):
    assert kinds(raw) == [(N.ISSUE, value, (domain,))]


@pytest.mark.parametrize("raw", ["ZC25090", "ZC2513001", "ZC2509"])
def test_bad_issue_numbers_are_not_guessed(raw):
    got = N.recognize(raw)
    assert got.lookups == [] and got.problem == N.ISSUE_FORMAT and "序号" in got.problem


def test_car_numbers():
    assert kinds("CAR202610059", "CAR 编号") == [(N.CAR, "CAR202610059", ("国内",))]
    assert kinds("car202610059") == [(N.CAR, "CAR202610059", ("国内",))]
    assert N.recognize("CAR12345").problem == N.CAR_FORMAT


def test_shapes_without_kind_said():
    assert kinds("230939") == [(N.PROD_ORDER, "230939", ("国内",)), (N.XB_ORDER, "230939", ("国内",))]
    assert kinds("123456-2") == [(N.PROD_ORDER, "123456-2", ("国内",)), (N.XB_ORDER, "123456-2", ("国内",))]
    assert kinds("200209010001203") == [(N.INV, "200209010001203", ("国内", "巴西", "海外")),
                                        (N.PN_CODE, "200209010001203", ("国内", "巴西", "海外"))]
    assert kinds("A35-000-RD6-00E0") == [(N.PN_NAME, "A35-000-RD6-00E0", ("国内", "巴西", "海外")),
                                         (N.PO, "A35-000-RD6-00E0", ("海外",))]
    assert kinds("CLAIM-0037/26") == [(N.CLAIM, "CLAIM-0037/26", ("巴西",))]


def test_seven_digits_are_delivery_and_maybe_problem_numbers():
    """前四位是 2021 年以来的年月时也按三域问题编号（补上前缀）查。"""
    assert kinds("2406648") == [(N.DELIVERY, "2406648", ("海外",)), (N.ISSUE, "ZC2406648", ("国内",)),
                                (N.ISSUE, "BR2406648", ("巴西",)), (N.ISSUE, "HW2406648", ("海外",))]
    assert kinds("1913001") == [(N.DELIVERY, "1913001", ("海外",))]


def test_kind_said_as_the_model_writes_it():
    assert kinds("230939", "订单号") == [(N.PROD_ORDER, "230939", ("国内",)), (N.XB_ORDER, "230939", ("国内",)),
                                        (N.DELIVERY, "230939", ("海外",)), (N.PO, "230939", ("海外",))]
    assert kinds("CLAIM-0037/26", "投诉单号") == [(N.CLAIM, "CLAIM-0037/26", ("巴西",))]
    assert kinds("2406648", "发货单号") == [(N.DELIVERY, "2406648", ("海外",))]
    assert kinds("A35-000-RD6-00E0", "PN") == [(N.PN_NAME, "A35-000-RD6-00E0", ("国内", "巴西", "海外"))]
    assert [k for k, *_ in kinds("200209010001203", "物料或 PN")] == [N.INV, N.PN_CODE]
    assert [k for k, *_ in kinds("200209010001203", "料号")] == [N.INV]
    # 问题编号、15 位编码、CAR 编号的样子总按样子认，用户说是订单也不当订单号（国内「按订单号查单」）
    assert kinds("ZC2509012", "订单号") == [(N.ISSUE, "ZC2509012", ("国内",))]
    assert [k for k, *_ in kinds("200209010001203", "订单号")] == [N.INV, N.PN_CODE]


def test_unsupported_and_unknown():
    assert N.recognize("AB2509012").unsupported == N.NOT_FOR_LOOKUP
    assert N.recognize("990001", "其他在线订单号").unsupported == N.NOT_FOR_LOOKUP
    got = N.recognize("202501011234")
    assert got.lookups == [] and got.reason == N.UNKNOWN_REASON and "问题编号" in got.problem and "投诉单号" in got.problem
    assert got.options == list(N.UNKNOWN_OPTIONS)


def test_unknown_number_after_clicking_an_option_is_not_asked_again():
    """追问按钮发回「原话（订单号）」：下一轮模型多半照旧写 kind_said 为 null，按问句末尾认回选项（S3 BR-004 教训）。"""
    got = N.recognize("202501011234", None, "202501011234 是什么单？（订单号）")
    assert got.problem is None and [lk.kind for lk in got.lookups][:2] == [N.PROD_ORDER, N.XB_ORDER]


def test_within_named_domains():
    n = N.recognize("200209010001203")
    assert [lk.domains for lk in N.within(n, [Domain.DOMESTIC]).lookups] == [(Domain.DOMESTIC,), (Domain.DOMESTIC,)]
    issue = N.recognize("ZC2509012")
    assert N.within(issue, [Domain.BRAZIL]).lookups == issue.lookups  # 按前缀定域
    assert N.prefix_note(issue, [Domain.BRAZIL]) == "ZC2509012 是国内的单，按国内查"
    assert N.single_domain(issue) is Domain.DOMESTIC and N.single_domain(n) is None
