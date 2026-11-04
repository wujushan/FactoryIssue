"""S3 代码评审（2026-10-29）的反例：每条在改之前失败、改之后通过（A2 是补的覆盖，改前就通过）。

M1 巴西、海外文档里的停线说法；M2 三域一起的结案周期不合成一个数；A1 主数据没取到时不把整列写成「未识别机型」；
A2 分组变换的两条公开测试向量；A3 巴西清单的停线状态与分组用同一套字。
"""

from __future__ import annotations

import pytest
import s3_data
import scopes
from fakes import headed_tables, make_harness, run
from forge_core.errors import TableDenied
from forge_core.events import EventType

from factory_issue_module.domains import enums
from factory_issue_module.present import _blk
from factory_issue_module.turn import errors

BR = {"value": ["巴西"], "from": "user"}
CN = {"value": ["国内"], "from": "user"}
CN_OS = {"value": ["国内", "海外"], "from": "user"}
T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
NARR = "近 30 天共 10 张，硬件问题最多。最需要关注的是 ZC9901001。"
MEAN, MEDIAN = "结案周期平均（天）", "结案周期中位数（天）"


def plan(*steps: dict) -> dict:
    return {"understanding": "按条件查", "alternatives": [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


async def _go(query: str, replies: list, *, errors_by_table: dict | None = None, connector: str = "info"):
    h = make_harness(scopes.GREEN, llm_replies=replies)
    s3_data.load(h)
    h.connectors[connector].errors.update(errors_by_table or {})
    return h, await run(h, query)


def _stop(value: str) -> dict:
    return {"field": "状态", "op": "是", "value": value, "from": "user"}


# ---------------------------------------------------------------------------- M1


@pytest.mark.parametrize(("said", "kind"), [("从未停线", "没有停线"), ("停线已重启", "已经重启"),
                                            ("停线后已恢复生产", "已经重启")])
def test_m1_stop_phrases_from_domain_docs_are_recognized(said, kind):
    """巴西「停线」表、海外「停线」表里的原话，三域都认得（不靠规划提示改写）。"""
    for stages in (enums.CN_STAGES, enums.BR_STAGES, enums.OS_STAGES):
        assert enums.status_kind(said, stages) == (kind, "")


async def test_m1_brazil_never_stopped_keeps_only_not_stopped():
    """巴西「从未停线」= 是否停线为「否」：只留 BR9901002、BR9901004，不追问、不当成流程状态。"""
    reply = plan(step("list_issues", domains=BR, filters=[_stop("从未停线")]))
    h, events = await _go("巴西从未停线的单", [reply, "共 2 张。最需要关注的是 BR9901002。"])
    assert EventType.CLARIFY not in [e.type for e in events]
    assert [r[0] for r in _tables(events)[0]["rows"]] == ["BR9901002", "BR9901004"]


async def test_m1_brazil_restarted_keeps_only_marked_restart():
    """巴西「停线已重启」= 是否停线为「是」且停线状态为「停线重启」：只留 BR9901003。"""
    reply = plan(step("list_issues", domains=BR, filters=[_stop("停线已重启")]))
    h, events = await _go("巴西停线已重启的单", [reply, "共 1 张。最需要关注的是 BR9901003。"])
    assert EventType.CLARIFY not in [e.type for e in events]
    assert [r[0] for r in _tables(events)[0]["rows"]] == ["BR9901003"]


# ---------------------------------------------------------------------------- M2


async def test_m2_cross_overview_close_cycle_total_is_dash_when_brazil_is_in():
    """三域一起要结案周期：各域一格是本域的天数；巴西的结案时间取法不同，合计格写「—」。"""
    reply = plan(step("aggregate", time=T30, metrics=["结案周期"]))
    h, events = await _go("近 30 天三个域平均多久结案", [reply, "共 10 张。"])
    table = _tables(events)[0]
    rows = {r[0]: r for r in table["rows"]}
    mean, median = table["columns"].index(MEAN), table["columns"].index(MEDIAN)
    assert rows["合计"][mean] == "—" and rows["合计"][median] == "—"
    assert rows["巴西"][mean] == 8 and rows["海外"][mean] == 2


async def test_m2_cross_overview_close_cycle_total_kept_for_same_definition():
    """国内、海外的结案时间都是最新一条结案确认：只有这两域时合计照算（与停线时长合计同一个道理）。"""
    reply = plan(step("aggregate", domains=CN_OS, time=T30, metrics=["结案周期"]))
    h, events = await _go("近 30 天国内和海外平均多久结案", [reply, "共 6 张。"])
    table = _tables(events)[0]
    rows = {r[0]: r for r in table["rows"]}
    assert isinstance(rows["合计"][table["columns"].index(MEAN)], (int, float))


async def test_m2_cross_group_with_close_cycle_is_given_per_domain():
    """三域一起按问题类型又要结案周期：不合成一张表（合并表每行的天数会把巴西与国内、海外混在一起），按域分别给。"""
    reply = plan(step("aggregate", time=T30, group_by=["问题类型"], metrics=["结案周期"]))
    h, events = await _go("近 30 天各问题类型平均多久结案", [reply, "共 10 张。"])
    tables = _tables(events)
    assert [head.split("按")[0] for head, t in headed_tables(events) if MEAN in t["columns"]] == ["国内", "巴西", "海外"]
    assert all("巴西" not in t["columns"] for t in tables)


# ---------------------------------------------------------------------------- A1


async def test_a1_products_failure_is_section_failed_not_unrecognized_machine():
    """产品主数据没取到：巴西、海外清单答「这一部分暂时没查到」，不把每张单的机型写成「未识别机型」。"""
    h, events = await _go("近 30 天的问题有哪些", [plan(step("list_issues", time=T30)), NARR],
                          errors_by_table={"ProductName": TableDenied("拒绝", detail={})})
    text = _text(events)
    assert f"巴西：{errors.SECTION_FAILED}" in text and f"海外：{errors.SECTION_FAILED}" in text
    assert [head.split("（")[0] for head, _t in headed_tables(events)] == ["国内问题单"]
    assert "未识别机型" not in str(_tables(events))


async def test_a1_products_failure_in_group_by_machine():
    """按机型统计同理：巴西、海外这一段查不到，国内照常（国内机型取机型子表，不用产品主数据）。"""
    reply = plan(step("aggregate", time=T30, group_by=["机型"]))
    h, events = await _go("近 30 天按机型统计", [reply, "国内共 4 张。"],
                          errors_by_table={"ProductName": TableDenied("拒绝", detail={})})
    text = _text(events)
    assert f"巴西：{errors.SECTION_FAILED}" in text and f"海外：{errors.SECTION_FAILED}" in text
    assert all("巴西" not in t["columns"] for t in _tables(events)) and _tables(events)


async def test_a1_factory_master_failure_on_named_column():
    """国内工厂没取到、清单要加工厂这一列：国内这一段查不到，不把加工厂整列写成「未填」。"""
    reply = plan(step("list_issues", domains=CN, time=T30, columns=["问题编号", "加工厂"]))
    h, events = await _go("近 30 天国内的单，列单号和加工厂", [reply],
                          errors_by_table={"PaxFactory": RuntimeError("连不上")}, connector="erp")
    assert errors.SECTION_FAILED in _text(events) and not _tables(events)


async def test_a1_factory_master_failure_keeps_list_without_factory_facts():
    """国内工厂没取到、清单没有加工厂这一列：清单照常，分析事实里不给「按加工厂」（否则会读成全部未填）。"""
    h, events = await _go("近 30 天国内的问题", [plan(step("list_issues", domains=CN, time=T30)), NARR],
                          errors_by_table={"PaxFactory": RuntimeError("连不上")}, connector="erp")
    assert _tables(events) and errors.SECTION_FAILED not in _text(events)
    facts = h.llm.calls[-1][-1]["content"].split("【事实】", 1)[1]
    assert '"按加工厂"' not in facts and '"按问题类型"' in facts


# ---------------------------------------------------------------------------- A2


def test_a2_block_matches_fips197_c3():
    """FIPS-197 附录 C.3（256 位密钥）的公开向量。"""
    key = bytes(range(32))
    got = _blk.block(bytes.fromhex("00112233445566778899aabbccddeeff"), key)
    assert got.hex() == "8ea2b7ca516745bfeafc49904b496089"


def test_a2_seal_matches_sp800_38a_f25():
    """SP 800-38A F.2.5（CBC-AES256.Encrypt）的公开向量；输入正好 4 组时 PKCS7 再补一整组。"""
    key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plain = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a" "ae2d8a571e03ac9c9eb76fac45af8e51"
                          "30c81c46a35ce411e5fbc1191a0a52ef" "f69f2445df4f9b17ad2b417be66c3710")
    want = ("f58c4c04d6e5f1ba779eabfb5f7bfbd6" "9cfc4e967edb808d679f777bc6702c7d"
            "39f23369a9d9bacfa530e26304231461" "b2eb05e2c39be9fcda6c19078c6a9d1b")
    got = _blk.seal(plain, key, iv)
    assert len(got) == 80 and got[:64].hex() == want


# ---------------------------------------------------------------------------- A3


async def test_a3_brazil_list_stop_status_matches_group_labels():
    """巴西清单的停线状态与按停线状态统计用同一套字：否 + 空写「从未停线」，是 + 空写「停线中」。"""
    reply = plan(step("list_issues", domains=BR, columns=["问题编号", "停线状态"]))
    h, events = await _go("巴西的单，列单号和停线状态", [reply, "共 4 张。最需要关注的是 BR9901001。"])
    rows = dict(_tables(events)[0]["rows"])
    assert rows == {"BR9901001": "停线中", "BR9901002": "从未停线", "BR9901003": "停线重启",
                    "BR9901004": "从未停线"}
    reply = plan(step("aggregate", domains=BR, group_by=["停线状态"]))
    h, events = await _go("巴西按停线状态统计", [reply, "巴西共 4 张。"])
    assert {r[0] for r in _tables(events)[0]["rows"]} <= set(rows.values())
