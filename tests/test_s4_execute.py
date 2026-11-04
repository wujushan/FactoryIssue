"""详情与按号查单（设计 §4.3 两行、§6.3、§13；任务单 S4）：假 `ctx`、真沙箱、回放的规划回复。

夹具 J-D01（重启审核中）、J-D02（5Why 待答复）、J-D03（15 位编码两处命中）、J-P05（无权域单号）、J-P06（多域号码）、
J-P07、J-P08（没有 CAR 报告权限）在这里。计划的写法照对照集里模型的实际写法（`issue` 一律 `{value, from}`，
`aspects` 用 ASPECTS 里的词，偶尔写「处理结果」「其他:…」；`numbers` 的 `kind_said` 为 null 或「订单号」等）。
"""

from __future__ import annotations

import s4_data
import scopes
from fakes import data_queries, make_harness, run
from forge_core.errors import TableDenied
from forge_core.events import EventType

from factory_issue_module.declarations import Domain
from factory_issue_module.turn import errors

SITES = 'issue = "info.test.local"'


def plan(*steps: dict) -> dict:
    return {"understanding": "x", "alternatives": [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def detail(number: str, *aspects: str, sid: str = "s1", frm: str = "user") -> dict:
    params = {"issue": {"value": number, "from": frm}}
    if aspects:
        params["aspects"] = list(aspects)
    return step("issue_detail", sid, **params)


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


def _heads(h) -> set[str]:
    return {q.tables[0] for q in data_queries(h)}


async def _go(query: str, replies: list, privileges=None, edit=None, *, ws: bool = True, **load):
    h = make_harness(scopes.GREEN if privileges is None else privileges, llm_replies=replies,
                     config_files={"link_sites.toml": SITES}, workspace=ws)
    s4_data.load(h, **load)
    if edit is not None:  # 在假数据上改几格再跑
        edit(h.connectors["info"].frames)
    return h, await run(h, query)


def _blank_rconfirm(frames) -> None:
    main = frames["ZCTracking_ProblemList"]
    main["RConfirm"] = main["RConfirm"].astype(object)
    main.loc[main["ID"] == 6, "RConfirm"] = None


# ---------------------------------------------------------------------------- 单张单详情


async def test_domestic_detail_default_blocks_and_no_model_call_after_planning():
    """号码直通：不调规划；默认给整张详情（抬头、订单、停线、现象、描述、附件、各环节），叙述剥图，已删除的附件不给。"""
    h, events = await _go("ZC9901001 这张单帮我查一下", [])
    text = _text(events)
    assert "[ZC9901001](https://info.test.local/#/QualityManage/ProblemDetail?id=1)" in text
    assert "当前状态" in text and "SQE跟进 测试甲" in text and "IQC确认 测试乙" in text
    assert "按键手感差" in text and "base64" not in text and "QUJD" not in text  # 剥图
    assert "测试照片" in text and "已删除的照片" not in text
    assert "弹片疲劳" in text and "根据选择的问题现象" in text  # 可能问题原因
    assert [t["columns"][0] for t in _tables(events)] == ["生产订单号"]
    assert h.llm.calls == []  # 详情不写分析段
    assert all("ProblemDesc" not in q.sql for q in data_queries(h) if q.tables[0] != "ZCTracking_ProblemList")
    assert any("ProblemDesc" in q.sql for q in data_queries(h) if q.tables[0] == "ZCTracking_ProblemList")


async def test_jd01_restart_under_review_hides_scheme_review_and_restart_log():
    """J-D01：停线状态为重启审核中时不给重启方案、重启审核意见，完整处理过程不给重启操作日志（国内「停线」）。"""
    _h, events = await _go("ZC9901005 的停线重启方案和审核意见是什么？",
                           [plan(detail("ZC9901005", "停线与重启", "完整处理过程"))])
    text = _text(events)
    assert "重启审核中（重启审核人：测试乙）" in text and "重启日期" in text
    assert "方案甲" not in text and "同意重启" not in text and "重启方案审核中，暂不展示" in text
    titles = [t["title"] for t in _tables(events)]
    assert titles == ["国内 ZC9901005 完整处理过程"]
    kinds = [r[2] for r in _tables(events)[0]["rows"]]
    assert "停线重启" not in kinds and "责任人填写重启方案" not in kinds and "停线重启审核" not in kinds


async def test_jd02_five_why_pending_and_follows_its_stage():
    """J-D02：待答复的写「待答复」；5Why 随所在分析环节显示，环节已退回时不给。"""
    _h, events = await _go("ZC9901006 的 5Why 是怎么分析的？", [plan(detail("ZC9901006", "5Why"))])
    five = next(t for t in _tables(events) if "5Why" in t["title"])
    assert five["columns"][:5] == ["序号", "问题", "提问人", "提问时间", "原因"]
    assert five["rows"][1][4:7] == ["待答复", "待答复", "待答复"] and five["rows"][0][4] == "温度偏低"
    _h, events = await _go("ZC9901007 的 5Why", [plan(detail("ZC9901007", "5Why", "原因"))])
    text = _text(events)
    assert _tables(events) == [] and "「责任人确认」该环节已退回重新处理" in text
    assert "驳回前写的原因" not in text  # 主表原因随责任人确认一起不给


async def test_reasons_and_reject_count_as_the_model_writes_it():
    """CN-049 / CN-022 的写法：aspects 含「驳回」时数驳回次数（沙箱给的数）；「处理结果」不在 ASPECTS 里也认。"""
    _h, events = await _go("ZC9901006 完整处理过程，被驳回过几次？原因和措施",
                           [plan(detail("ZC9901006", "完整处理过程", "驳回", "原因", "措施", "处理结果"))])
    text = _text(events)
    assert "处理过程里驳回过 1 次" in text
    assert "焊点虚焊" in text and "补焊" in text and "nan" not in text
    process = next(t for t in _tables(events) if "完整处理过程" in t["title"])
    assert process["columns"] == ["操作人", "操作时间", "类型", "内容", "附件"]
    assert sum(1 for t in _tables(events) if "5Why" in t["title"]) == 1  # 5Why 只给一次


async def test_blank_rconfirm_is_not_confirmed():
    """跟进人是否确认为空：与管理页面一致按「否」，给修改后的问题分类，不给主表原因、措施、对策、处理结果、计划完成时间
    与 5Why（国内「单张单详情各环节怎么显示」：只在确认结果为「是」时显示；开发者 2026-10-30 定空值照页面）。"""
    _h, events = await _go("ZC9901006", [], edit=_blank_rconfirm)  # 号码直通，整张详情
    text = _text(events)
    assert "**跟进人是否确认**：否" in text and "**修改后的问题分类**：硬件问题" in text
    for word in ("焊点虚焊", "补焊", "加检", "为什么虚焊", "处理结果", "计划完成时间"):
        assert word not in text, word
    _h, events = await _go("ZC9901006 的原因、措施和 5Why", [plan(detail("ZC9901006", "原因", "措施", "5Why"))],
                           edit=_blank_rconfirm)
    text = _text(events)
    assert "焊点虚焊" not in text and "补焊" not in text and "为什么虚焊" not in text
    assert not any("5Why" in t["title"] for t in _tables(events))


async def test_jp07_no_car_permission_no_report_sql_but_number_and_link():
    """J-P07：没有 CAR 报告权限时不对报告表取数，CAR 编号照常显示并附链接，按 `privileges.md` 的说法答。"""
    h, events = await _go("ZC9901002 的 CAR 写了什么根本原因？", [plan(detail("ZC9901002", "CAR", "原因"))],
                          privileges=scopes.account_jia())
    text = _text(events)
    assert "tbIQCreportOut" not in _heads(h)
    assert errors.CAR_NOT_PERMITTED in text and "CAR999999999" in text
    assert "VendorReportOutDetail.aspx?VendorReportOutID=5" in text and "模具磨损" not in text
    h, events = await _go("ZC9901002 的 CAR 写了什么根本原因？", [plan(detail("ZC9901002", "CAR"))],
                          privileges=scopes.privileges([Domain.DOMESTIC], car=True))
    assert "tbIQCreportOut" in _heads(h) and "模具磨损" in _text(events) and "更换模具" in _text(events)


async def test_car_report_denied_at_fetch_time_only_drops_report_content():
    """前置判断有 CAR 报告权限、取数时报告表被拒：以拒绝为准，只当没有 CAR 报告权限，问题单其余内容照常。"""
    h = make_harness(scopes.privileges([Domain.DOMESTIC], car=True), llm_replies=[plan(detail("ZC9901002", "CAR"))],
                     config_files={"link_sites.toml": SITES})
    s4_data.load(h)
    h.connectors["info"].errors["tbIQCreportOut"] = TableDenied("拒绝", detail={})
    events = await run(h, "ZC9901002 的 CAR")
    text = _text(events)
    assert errors.CAR_NOT_PERMITTED in text and "CAR999999999" in text and "模具磨损" not in text
    assert EventType.ERROR not in [e.type for e in events]


async def test_jp09_detail_table_denied_at_fetch_time():
    """J-P09 的详情一面：前置说国内可查、取数时主表被拒，按无权答，不报内部错误、不说没有这张单。"""
    h = make_harness(scopes.account_jia(), llm_replies=[], config_files={"link_sites.toml": SITES})
    s4_data.load(h)
    h.connectors["info"].errors["ZCTracking_ProblemList"] = TableDenied("拒绝", detail={})
    events = await run(h, "ZC9901001")
    assert errors.DOMAIN_NOT_PERMITTED in _text(events) and "没有找到" not in _text(events)


async def test_jp05_number_of_denied_domain_only_says_no_permission():
    """J-P05：号只可能在一个无权的域：只答「您没有该域的查看权限」，不查这张单。"""
    h, events = await _go("BR9901001 现在到哪了？", [plan(detail("BR9901001", "当前状态"))],
                          privileges=scopes.account_jia())
    assert _text(events) == f"{errors.DOMAIN_NOT_PERMITTED}。"
    assert data_queries(h) == []
    h, events = await _go("BR9901001", [], privileges=scopes.account_jia())  # 号码直通
    assert _text(events) == f"{errors.DOMAIN_NOT_PERMITTED}。" and data_queries(h) == []


async def test_not_found_issue_number_message_and_no_tables():
    """CN-059 的形状：格式对但查不到，固定说法（括号里那句总带上），不出表。"""
    _h, events = await _go("ZC9909999 这张单帮我查一下。", [])
    assert _tables(events) == []
    assert "没有找到单号为 ZC9909999 的问题单（已删除的单查不到），请核对单号" in _text(events)


async def test_bad_issue_number_asks_without_fetching():
    """XC-013：「ZC2509 是哪张单」位数不对，追问，不取数。"""
    h, events = await _go("ZC2509 是哪张单？", [plan(step("lookup_numbers",
                                                          numbers=[{"raw": "ZC2509", "kind_said": None}]))])
    assert [e.type for e in events] == [EventType.CLARIFY] and "序号" in events[0].data["question"]
    assert data_queries(h) == []


async def test_brazil_detail_current_and_follower():
    """BR-002 / BR-008：巴西不提供当前责任人，给问题跟进人；同一项在几块里只给一次。"""
    _h, events = await _go("BR9901001 现在到哪一步了？谁在跟？", [plan(detail("BR9901001", "当前状态", "跟进人"))])
    text = _text(events)
    assert "不提供当前责任人" in text and "跟进人" in text and "待跟进" in text
    assert text.count("**问题跟进人**：测试甲") == 1
    _h, events = await _go("这单的责任人是谁？", [plan(detail("BR9901001", "责任人", frm="previous"))])
    assert "巴西的责任人即问题跟进人" in _text(events)


async def test_brazil_detail_costs_stock_and_five_why():
    """巴西费用明细给全部行（含 0 金额行），合计由沙箱算，扣款另列；库存处理为「是」时给数量；5Why 暂不提供。"""
    _h, events = await _go("BR9901001 花了多少钱、库存处理、5Why",
                           [plan(detail("BR9901001", "费用", "库存处理", "5Why"))])
    text = _text(events)
    cost = next(t for t in _tables(events) if "费用明细" in t["title"])
    assert len(cost["rows"]) == 2 and cost["rows"][1][1] == "0.00"
    assert "费用美元合计**：100.00" in text and "扣款费用（美元）**：10.00" in text and "扣款单独列出" in text
    assert "库存处理数量**：12" in text and "5Why分析过程" in text and "统计口径" in text


async def test_overseas_detail_phenomena_candidates_and_current():
    """OS-002：已选问题现象展平、可能原因写明是候选、当前责任人；责任人确认驳回后未重提时不给旧内容（J-D10）。"""
    _h, events = await _go("HW9901001 选了哪些现象？可能原因是什么？现在谁在处理？",
                           [plan(detail("HW9901001", "问题现象", "可能原因", "当前责任人"))])
    text = _text(events)
    assert "黑屏、白屏；功能问题 -> 花屏 (夜间)" in text and "候选" in text and "当前责任人" in text
    assert "屏幕坏点" in text
    _h, events = await _go("HW9901001 的原因", [plan(detail("HW9901001", "原因"))])
    assert "该环节已退回重新处理" in _text(events) and "驳回前的原因" not in _text(events)


async def test_overseas_delivery_table_and_total():
    """OS-003：涉及发货单按发货单号升序、序号现编，订单数量合计由沙箱算。"""
    _h, events = await _go("HW9901002 涉及哪些发货单？订单数量合计多少？", [plan(detail("HW9901002", "发货单"))])
    table = _tables(events)[0]
    assert table["columns"] == ["序号", "PO", "发货单号", "发货日期", "PN", "发货版本", "生产版本", "订单数量", "备注"]
    assert [r[0] for r in table["rows"]] == ["1", "2"] and [r[2] for r in table["rows"]] == ["9900001", "9900002"]
    assert "订单数量合计**：500" in _text(events) and "合计" in _text(events)


async def test_material_unit_explains_machine_and_impact():
    """CN-053：「物料」单机型显示「物料」、不展示影响数量（「其他:…」的写法照模型实际写的）。"""
    _h, events = await _go("这张物料单为什么机型显示「物料」？它的影响数量怎么没有？",
                           [plan(detail("ZC9901002", "物料", "其他:影响数量为何为空", frm="previous"))])
    text = _text(events)
    assert "机型一栏显示「物料」" in text and "不展示产品在制属性与影响数量" in text


async def test_material_unit_follow_up_written_as_out_of_scope_is_bounced():
    """CN-053（golden 实测）：上一轮打开了「物料」单，本轮「这张物料单为什么…」模型写成超出范围时，第 19 条打回，
    修后的详情照常取数作答。这里工作区里没有上一轮计划，从上一轮的用户问句认出那张单。"""
    query = "这张物料单为什么机型显示「物料」？它的影响数量怎么没有？"
    out_of_scope = plan(step("introduce", kind="超出范围"))
    h = make_harness(scopes.GREEN, llm_replies=[out_of_scope, plan(detail("ZC9901002", "机型", "其他:影响数量为何为空",
                                                                        frm="previous"))],
                     config_files={"link_sites.toml": SITES},
                     history=[("ZC9901002 这张单是什么情况？", "（单张单详情）")])
    s4_data.load(h)
    events = await run(h, query)
    text = _text(events)
    assert errors.OUT_OF_SCOPE not in text
    assert "ZC9901002" in text and "机型一栏显示「物料」" in text and "不展示产品在制属性与影响数量" in text
    assert data_queries(h)
    repair = h.llm.calls[1][-1]["content"]
    assert "这张物料单" in repair and "ZC9901002" in repair


async def test_detail_ref_to_max_defect_rate_issue():
    """XC-022 第三步：详情引用前一步不良率最高的那张，给原因。"""
    reply = plan(step("list_issues", domains={"value": ["国内"], "from": "user"},
                      time=[{"said": "近 30 天", "basis": "建单", "from": "user"}]),
                 step("issue_detail", "s2", issue={"value": {"ref": "s1.max_defect_rate_issue"}, "from": "user"},
                      aspects=["原因"]))
    _h, events = await _go("近 30 天国内的单，不良率最高那张的原因是什么？", [reply, "共 4 张。"])
    text = _text(events)
    assert "\n\n### 2. 单张单详情" in text and "ZC9901001" in text and "按键弹片偏软" in text


async def test_rule5_detail_with_only_reasons_folds_into_the_list():
    """第 5 条前半（BR-005 的写法）：清单 + 引用它的详情只要措施，执行时并进清单：一张表加「原因与措施」一列，
    不另出详情段。"""
    reply = plan(step("list_issues", domains={"value": ["巴西"], "from": "user"},
                      filters=[{"field": "问题类型", "op": "是", "value": "物料问题", "from": "user"}]),
                 step("issue_detail", "s2", issue={"value": {"ref": "s1.issues"}, "from": "previous"},
                      aspects=["措施"]))
    _h, events = await _go("巴西需要回 8D 的物料问题有哪些？改善措施写了什么？", [reply, "共 1 张。"])
    tables = _tables(events)
    assert len(tables) == 1 and tables[0]["columns"][-1] == "原因与措施"
    assert tables[0]["rows"][0][0].startswith("[BR9901003]") and "最新的措施" in tables[0]["rows"][0][-1]
    assert "单张单详情" not in _text(events)


async def test_rule5_folded_cell_carries_five_why_and_car_link():
    """并进清单的「原因与措施」一格同详情一样给（总述「原因与措施怎么给」）：国内有 5Why 时附在后面，每项截到 200 字；
    没有 CAR 报告权限时那句说明后附报告链接（链接在 `handle()` 一侧拼）。"""
    reply = plan(step("list_issues", domains={"value": ["国内"], "from": "user"},
                      time=[{"said": "近 30 天", "basis": "建单", "from": "user"}]),
                 step("issue_detail", "s2", issue={"value": {"ref": "s1.issues"}, "from": "previous"},
                      aspects=["原因"]))

    def long_question(frames) -> None:
        five = frames["ZCTracking_ProblemFiveWhy"]
        five.loc[five["ID"] == 1, "Question"] = "为什么虚焊" + "长" * 300

    _h, events = await _go("近 30 天国内的单各是什么原因？", [reply, "共 7 张。"], privileges=scopes.account_jia(),
                           edit=long_question)
    tables = _tables(events)
    assert len(tables) == 1 and tables[0]["columns"][-1] == "原因与措施"
    cells = {r[0].split("]")[0].lstrip("["): r[-1] for r in tables[0]["rows"]}
    six = cells["ZC9901006"]
    assert "焊点虚焊" in six and "5Why" in six and "为什么虚焊" in six and "长" * 300 not in six
    assert "为什么温度偏低" in six and "待答复" in six
    car = cells["ZC9901002"]
    assert errors.CAR_NOT_PERMITTED in car and "VendorReportOutDetail.aspx?VendorReportOutID=5" in car


# ---------------------------------------------------------------------------- 按号查单


async def test_seven_digits_hitting_an_issue_number_lists_its_row():
    """只给 7 位数字、前四位像年月、库里有对应的单：按问题编号那张表里有这一行，编号能点开（总述「按编号查单」：
    命中的分开列出，写明按哪种号找到）。"""
    _h, events = await _go("9901005", [])
    tables = _tables(events)
    assert [t["title"] for t in tables] == ["问题编号 ZC9901005（国内）"]
    assert tables[0]["columns"] == ["问题编号", "问题类型", "当前状态", "机型"]
    assert len(tables[0]["rows"]) == 1 and tables[0]["rows"][0][0].startswith("[ZC9901005](https://info.test.local/")
    _h, events = await _go("9901001", [])
    tables = _tables(events)
    assert len(tables) == 3 and all(len(t["rows"]) == 1 for t in tables)
    assert [t["rows"][0][0].split("]")[0] for t in tables] == ["[ZC9901001", "[BR9901001", "[HW9901001"]


async def test_jd03_fifteen_digits_hit_both_inv_and_pn_listed_apart():
    """J-D03：15 位编码在料号、PN 两处都查，分开列出、写明命中在哪；不替用户判断。"""
    _h, events = await _go("999999999999999", [])
    tables = _tables(events)
    assert [t["title"] for t in tables] == ["料号 999999999999999（国内）", "PN 编码 999999999999999（国内）"]
    assert tables[0]["rows"][0][0].startswith("[ZC9901001]") and tables[1]["rows"][0][0].startswith("[ZC9901003]")
    assert tables[0]["columns"][:4] == ["问题编号", "问题类型", "当前状态", "机型"]


async def test_jp06_multi_domain_number_only_searches_allowed_domains():
    """J-P06：号可能在几个域时只查国内，写明另两域未查；对巴西、海外的表没有 SQL。"""
    h, events = await _go("200209010001203 是哪些单的物料或 PN？",
                          [plan(step("lookup_numbers", numbers=[{"raw": "999999999999999", "kind_said": None}]))],
                          privileges=scopes.account_jia())
    assert "巴西、海外无权限，未查" in _text(events)
    assert not {"BrazilProblemList", "OverseasProblemDetail", "BrazilProblemPO"} & _heads(h)


async def test_jp08_car_lookup_without_car_permission():
    """J-P08：按 CAR 编号查单不需要 CAR 报告权限，不读报告表；CAR 编号带报告链接。"""
    h, events = await _go("CAR 编号 CAR999999999 对应哪张制程单？", [], privileges=scopes.account_jia())
    table = _tables(events)[0]
    assert table["rows"][0][0].startswith("[ZC9901002]") and "VendorReportOutID=5" in table["rows"][0][-1]
    assert "tbIQCreportOut" not in _heads(h) and "CAR999999999" in _text(events) + str(table)


async def test_order_lookup_columns_and_distribution():
    """CN-048：订单号查国内生产订单，一单一行，给问题类型、当前状态、机型与订单明细，开头给分布。"""
    _h, events = await _go("订单 990001 关联了哪些制程问题？",
                           [plan(step("lookup_numbers", numbers=[{"raw": "990001", "kind_said": "订单号"}]))])
    table = _tables(events)[0]
    assert table["columns"][:4] == ["问题编号", "问题类型", "当前状态", "机型"] and "PN" in table["columns"]
    assert len(table["rows"]) == 2 and "生产订单" in _text(events) + table["title"]
    assert "硬件问题 1 张、软件问题 1 张" in _text(events)


async def test_hand_filled_order_asks_then_the_click_round_does_not_loop():
    """国内手填的带连字符的订单号：查不到 990002、有 990002-1 时追问；点了按钮那一轮按选回的号查，不再追问。
    每轮一个新环境、没有工作区：测的是按钮发问句全文的退路（直填见 `test_s5_multiturn.py`）。"""
    reply = plan(step("lookup_numbers", numbers=[{"raw": "990002", "kind_said": "订单号"}]))
    _h, events = await _go("订单 990002 关联了哪张单？", [reply], ws=False)
    assert [e.type for e in events] == [EventType.CLARIFY]
    rec = events[0].data["recommendations"][0]
    assert rec["label"] == "990002-1" and rec["query"].endswith("（990002-1）")
    _h, events = await _go(rec["query"], [reply])  # 模型照旧只抄 990002
    assert EventType.CLARIFY not in [e.type for e in events]
    assert _tables(events)[0]["rows"][0][0].startswith("[ZC9901001]")


async def test_unknown_number_asks_with_kinds_then_the_click_round_does_not_loop():
    """XC-012：认不出是什么号，列出能用来查单的号并给选项；点了「订单号」那一轮不再追问。"""
    reply = plan(step("lookup_numbers", numbers=[{"raw": "202501011234", "kind_said": None}]))
    h, events = await _go("202501011234 是什么单？", [reply], ws=False)
    assert [e.type for e in events] == [EventType.CLARIFY] and data_queries(h) == []
    text = events[0].data["question"]
    assert "问题编号" in text and "投诉单号" in text
    rec = next(r for r in events[0].data["recommendations"] if r["label"] == "订单号")
    _h, events = await _go(rec["query"], [reply])
    assert EventType.CLARIFY not in [e.type for e in events]
    assert "按生产订单号、小板订单号、发货单号、PO 查过，都没有找到挂着 202501011234 的单" in _text(events)


async def test_several_issue_numbers_one_table_including_denied_rows():
    """XC-005：几个问题编号合成一张表（两步详情的写法也并成这张表），一号一行，无权的在该行注明。"""
    reply = plan(detail("ZC9901001", "当前状态"), detail("BR9901002", "当前状态", sid="s2"))
    _h, events = await _go("ZC9901001、BR9901002 现在到哪了？", [reply])
    table = _tables(events)[0]
    assert table["columns"][:3] == ["问题编号", "所属域", "当前状态"]
    assert [r[1] for r in table["rows"]] == ["国内", "巴西"] and table["rows"][1][2] == "待提交"
    h, events = await _go("ZC9901001、BR9901002 现在到哪了？", [reply], privileges=scopes.account_jia())
    rows = _tables(events)[0]["rows"]
    assert rows[1][:3] == ["BR9901002", "巴西", errors.DOMAIN_NOT_PERMITTED]
    assert "BrazilProblemList" not in _heads(h)


async def test_claim_number_matches_without_spaces_case_insensitive():
    """BR-010：投诉单号不分大小写、去掉空格后精确比。"""
    reply = plan(step("lookup_numbers", numbers=[{"raw": "claim - 0099/99", "kind_said": "投诉单号"}]))
    _h, events = await _go("投诉单号 claim - 0099/99 对应哪张单？", [reply])
    assert _tables(events)[0]["rows"][0][0].startswith("[BR9901001]")
    reply = plan(step("lookup_numbers", numbers=[{"raw": "0099/99", "kind_said": "投诉单号"}]))
    _h, events = await _go("投诉单号 0099/99", [reply])
    assert errors.CLAIM_NOT_FOUND in _text(events)


async def test_delivery_number_lookup():
    """OS-004：发货单号查海外；7 位数字同时按三域问题编号查，都没有时写明按哪几种号查过。"""
    _h, events = await _go("发货单号 9900001 是哪张海外单？",
                           [plan(step("lookup_numbers", domains={"value": ["海外"], "from": "user"},
                                      numbers=[{"raw": "9900001", "kind_said": "发货单号"}]))])
    table = _tables(events)[0]
    assert table["rows"][0][0].startswith("[HW9901002]") and "发货单" in _text(events) + table["title"]
    _h, events = await _go("2406648", [])
    assert "按发货单号、问题编号查过，都没有找到挂着 2406648 的单" in _text(events)
