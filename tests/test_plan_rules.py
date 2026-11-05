"""规整与校验每条规则的固定用例（设计 §5.3 第 1–18 条）与号码直通（§4.2 第 4 步）。

规则的原型与对照集离线重算在 `scripts/planner_spike/`（S1 起它调这里的实现，自检里还有更多用例）。
名字归类用的「库里的取值」是示意名单，名字取自测试案例集与 `2_landed`，不是真实明细。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from factory_issue_module.config import files
from factory_issue_module.declarations import TOPIC_TERMS
from factory_issue_module.plan import normalize, prematch, schema
from factory_issue_module.plan.normalize import Context, RuleHit

TOPICS = files.default(TOPIC_TERMS)
CLASSES = {
    "工厂": ["柯洱斯", "亮亮", "惠州百富", "TT", "CA"],
    "人": ["李飞", "马万军", "张三"],
    "部门": ["工程部", "生产工程部", "研发一部", "研发二部"],
    "供应商": ["普瑞特", "高展光电", "亮亮"],
    "系列": ["底座", "A"],
}
ENTITIES = {"A960": ["机型"], "A920": ["机型"], "A920PRO": ["机型"], "柯洱斯": ["国内工厂"]}
TODAY = date(2026, 10, 21)
T = [{"said": "今年", "basis": "建单", "from": "user"}]


def agg(sid: str = "s1", **params: Any) -> dict:
    return {"id": sid, "skill": "aggregate", "when": None, "params": params}


def lst(sid: str = "s1", **params: Any) -> dict:
    return {"id": sid, "skill": "list_issues", "when": None, "params": params}


def txt(sid: str = "s1", **params: Any) -> dict:
    return {"id": sid, "skill": "text_search", "when": None, "params": params}


def apply(steps: list[dict], query: str | None = None, **kw: Any) -> dict:
    ctx = Context(query=query, classes=CLASSES, topics=TOPICS, today=TODAY, **kw)
    out = normalize.apply({"steps": steps}, ctx)
    assert out is not None
    return out


def checks(steps: list[dict], query: str) -> list[tuple[int, str]]:
    return normalize.tagged_checks(apply(steps, query), query, ENTITIES, TODAY)


def params(plan: dict, i: int = 0) -> dict:
    return plan["steps"][i]["params"]


def skills(plan: dict) -> list[str]:
    return [s["skill"] for s in plan["steps"]]


# ---------------------------------------------------------------- 第 1 条 话题范围


@pytest.mark.parametrize(
    ("topic", "scope"),
    [("磁卡", "比话题小"), ("eSIM", "比话题小"), ("音频（喇叭、蜂鸣器）", "话题本身"), ("非接相关问题", "话题本身"),
     ("电池卡扣", "组合说法"), ("电池鼓包", "比话题小"), ("外壳开裂", "比话题小"), ("换料", "清单外")],
)
def test_rule1_topic_scope(topic: str, scope: str) -> None:
    assert normalize.topic_scope(topic, TOPICS) == scope
    assert params(apply([txt(mode="话题", topic=topic, topic_scope="话题本身")]))["topic_scope"] == scope


# ---------------------------------------------------------------- 第 2 条 合并重复统计


def test_rule2_merges_same_scope_and_rewrites_refs() -> None:
    plan = apply([agg("s1", time=T, group_by=["机型"], ranking=True), agg("s2", time=T, group_by=["机型"]),
                  lst("s3", time=T, filters=[{"field": "机型", "value": {"ref": "s2.top1"}}])])
    assert len(plan["steps"]) == 2 and plan["steps"][1]["id"] == "s2"
    assert params(plan, 1)["filters"][0]["value"] == {"ref": "s1.top1"}


def test_rule2_keeps_different_groupings() -> None:
    assert len(apply([agg("s1", time=T, group_by=["问题类型"]), agg("s2", time=T, group_by=["加工厂"])])["steps"]) == 2


# ---------------------------------------------------------------- 第 3 条 追问与取数混在一起


def test_rule3_clarify_alone() -> None:
    clarify = {"id": "s2", "skill": "clarify", "when": None,
               "params": {"reason": "现象太泛", "question": "什么现象？", "options": ["开机花屏"]}}
    plan = apply([lst("s1", time=T), clarify], "有什么问题")
    assert skills(plan) == ["clarify"] and plan["steps"][0]["id"] == "s1"


# ---------------------------------------------------------------- 第 4 条 写法统一


def test_rule4_object_compare_becomes_filter_and_group() -> None:
    p = params(apply([agg(time=T, compare={"kind": "对象", "field": "机型", "items": ["A930", "A8900"]})]))
    assert "compare" not in p and p["group_by"] == ["机型"] and p["filters"][0]["value"] == ["A930", "A8900"]


def test_rule4_old_period_compare_gets_time_items() -> None:
    p = params(apply([agg(compare={"kind": "时段", "items": ["这个月", "上个月"]})]))
    assert p["compare"] == "时段" and [t["said"] for t in p["time"]] == ["这个月", "上个月"]


def test_rule4_implied_status_dropped_and_issue_wrapped() -> None:
    p = params(apply([agg(time=[{"said": "今年", "basis": "停线"}], group_by=["加工厂"],
                          filters=[{"field": "状态", "op": "是", "value": "曾经停线"}])]))
    assert "filters" not in p
    detail = {"id": "s1", "skill": "issue_detail", "when": None, "params": {"issue": "ZC9910001"}}
    assert params(apply([detail]))["issue"] == {"value": "ZC9910001", "from": "user"}


# ---------------------------------------------------------------- 第 5 条后半 沿用的清单并进后一步


def test_rule5_previous_list_folds_into_next_step() -> None:
    prev = {"from": "previous"}
    plan = apply([lst("s1", time=[{"said": "今年", "basis": "建单", **prev}],
                      filters=[{"field": "机型", "op": "是", "value": "A920", **prev}]),
                  agg("s2", within={"ref": "s1.issues"},
                      filters=[{"field": "状态", "op": "是", "value": "已结案", "from": "user"}])],
                 "其中已完成的有多少？", previous={"steps": [lst(time=T)]})
    assert skills(plan) == ["aggregate"] and "within" not in params(plan)
    assert [f["value"] for f in params(plan)["filters"]] == ["A920", "已结案"]


def test_rule5_list_asked_this_turn_is_kept() -> None:
    plan = apply([lst("s1", time=T, filters=[{"field": "机型", "op": "是", "value": "A920", "from": "user"}]),
                  agg("s2", within={"ref": "s1.issues"}, filters=[{"field": "状态", "op": "是", "value": "已结案"}])])
    assert skills(plan) == ["list_issues", "aggregate"]


# ---------------------------------------------------------------- 第 6 条 检索文字里去掉条件值


def test_rule6_strip_model_from_phenomenon_but_not_material() -> None:
    p = params(apply([txt(mode="类似问题", phenomenon="A960 煲机时屏幕显示异常",
                          filters=[{"field": "机型", "op": "是", "value": "A960"}])], "国内 A960 煲机时屏幕显示异常"))
    assert p["phenomenon"] == "煲机时屏幕显示异常"
    p = params(apply([txt(mode="话题", topic="喇叭", filters=[{"field": "物料名称", "op": "包含", "value": "喇叭"}])],
                     "喇叭的问题有哪些"))
    assert p["topic"] == "喇叭"


# ---------------------------------------------------------------- 第 7 条 名字归类


def field_of(plan: dict) -> str:
    return params(plan)["filters"][0]["field"]


def test_rule7_name_only_moves_to_the_one_matching_class() -> None:
    plan = apply([agg(time=[{"said": "这个月"}], filters=[{"field": "跟进人", "op": "属于", "value": ["柯洱斯", "亮亮"]}],
                      group_by=["跟进人"])], "这个月柯洱斯和亮亮各提交了几张单")
    assert field_of(plan) == "加工厂" and params(plan)["group_by"] == ["加工厂"]


@pytest.mark.parametrize("chosen", ["加工厂", "供应商", "跟进人"])
def test_rule7_name_matching_two_classes_becomes_clarify(chosen: str) -> None:
    plan = apply([agg(time=T, filters=[{"field": chosen, "op": "是", "value": "亮亮"}])], "亮亮今年多少单")
    assert skills(plan) == ["clarify"]
    assert {"亮亮：加工厂", "亮亮：供应商"} <= set(params(plan)["options"])


@pytest.mark.parametrize(
    ("query", "value", "want"),
    [("跟进人是柯洱斯的单有哪些", "柯洱斯", "跟进人"),  # 说了类别却对不上：不改类
     ("百富的单有哪些", "百富", "加工厂"),  # 一类都没有完全相同的：只有加工厂照包含对得上（G91）
     ("工程部跟进的单有哪些", "工程部", "跟进部门"),  # 「跟进」同时指人员与部门
     ("跟进人是工程部的单有哪些", "工程部", "跟进人")],
)
def test_rule7_class_words(query: str, value: str, want: str) -> None:
    assert field_of(apply([lst(filters=[{"field": "跟进人", "op": "是", "value": value}])], query)) == want


#: 供应商主数据存全称、用户说简称（G91 手动测试的五句；名称是示意的）
FULL_NAMES = {
    "工厂": ["柯洱斯", "惠州百富", "TT"],
    "人": ["李飞"],
    "部门": ["生产工程部", "研发一部"],
    "供应商": ["深圳市普瑞特电子有限公司", "东莞科全达五金制品有限公司", "深圳圳泰新科技有限公司",
             "鸿展光电科技有限公司", "深圳鸿展光电有限公司", "屿峰塑胶制品厂", "研发配件厂"],
    "系列": ["A"],
}


def _rule7(field: str, value: str, query: str, classes: dict = FULL_NAMES) -> tuple[dict, list[str]]:
    inferred: list[normalize.Inferred] = []
    ctx = Context(query=query, classes=classes, topics=TOPICS, today=TODAY, inferred=inferred)
    out = normalize.apply({"steps": [agg(time=T, filters=[{"field": field, "op": "是", "value": value}])]}, ctx)
    assert out is not None
    return out, [i.field for i in inferred]


@pytest.mark.parametrize(("query", "value"), [
    ("普瑞特今年问题单", "普瑞特"), ("科全达今年有几张问题单", "科全达"), ("圳泰新今年问题单", "圳泰新"),
    ("鸿展光电2026年的单", "鸿展光电"), ("屿峰塑胶今年几张问题单", "屿峰塑胶")])
def test_rule7_short_supplier_name_moves_from_factory_to_supplier(query: str, value: str) -> None:
    """G91：只给名称、五类都没有完全相同的，模型放进加工厂而只有供应商照包含对得上 → 改到供应商并写明。"""
    plan, inferred = _rule7("加工厂", value, query)
    assert field_of(plan) == "供应商" and inferred == ["供应商"]


def test_rule7_contains_keeps_chosen_class_and_says_so() -> None:
    """所选那一类照包含对得上就不改，同样写「按 X 理解」。"""
    plan, inferred = _rule7("加工厂", "百富", "百富今年问题单")
    assert field_of(plan) == "加工厂" and inferred == ["加工厂"]
    plan, inferred = _rule7("供应商", "鸿展光电", "鸿展光电今年问题单")  # 对上两家：不改类，交第 6 步追问选哪家
    assert field_of(plan) == "供应商" and inferred == ["供应商"]


def test_rule7_contains_in_two_other_classes_does_not_move() -> None:
    """「研发」在部门与供应商名称里都有，所选的加工厂对不上：不改，照加工厂答没找到。"""
    plan, inferred = _rule7("加工厂", "研发", "研发今年问题单")
    assert field_of(plan) == "加工厂" and inferred == []


@pytest.mark.parametrize(("field", "value", "query"), [
    ("加工厂", "普瑞特", "普瑞特工厂今年问题单"),  # 说了类别：不改类
    ("跟进人", "瑞特", "瑞特今年问题单"),  # 人员不按包含；供应商照包含对得上，改过去
])
def test_rule7_contains_respects_class_words(field: str, value: str, query: str) -> None:
    plan, _ = _rule7(field, value, query)
    assert field_of(plan) == ("加工厂" if "工厂" in query else "供应商")


def test_rule7_people_do_not_match_by_contains() -> None:
    """人员只认完全相同：名字只是某个人名的一部分时不改到人员。"""
    classes = {**FULL_NAMES, "人": ["李飞飞"]}
    plan, inferred = _rule7("加工厂", "李飞", "李飞今年问题单", classes)
    assert field_of(plan) == "加工厂" and inferred == []


def test_rule7_check_half_bounces_name_next_to_another_class_word() -> None:
    bounced = checks([lst(filters=[{"field": "供应商", "op": "是", "value": "普瑞特"}])], "普瑞特工厂的物料问题")
    assert [r for r, _ in bounced] == [7]
    assert not checks([lst(filters=[{"field": "供应商", "op": "是", "value": "普瑞特"}])], "供应商普瑞特的物料问题")


def test_rule7_records_a_hit() -> None:
    hits: list[RuleHit] = []
    apply([agg(time=T, filters=[{"field": "跟进人", "op": "属于", "value": ["柯洱斯", "亮亮"]}])],
          "这个月柯洱斯和亮亮各提交了几张单", hits=hits)
    assert [(h.rule, h.before, h.after) for h in hits if h.rule == 7] == [(7, ("跟进人",), ("加工厂",))]


# ---------------------------------------------------------------- 第 8–11 条


def test_rule8_status_written_as_time_goes_back_to_condition() -> None:
    p = params(apply([lst(time=[{"said": "今年", "basis": "建单", "from": "previous"},
                                {"said": "停过线", "basis": "停线", "from": "user"}])], "再看看里面停过线的"))
    assert [t["said"] for t in p["time"]] == ["今年"] and p["filters"][0]["value"] == "曾经停线"


def test_rule9_each_model() -> None:
    p = params(apply([agg(time=[{"said": "去年"}], filters=[{"field": "系列", "op": "是", "value": "A930"}],
                          group_by=["机型"])], "A930 各款去年各有多少问题"))
    assert p["filters"][0] == {"field": "机型", "op": "包含", "value": "A930"} and p["group_by"] == ["机型"]


def test_rule10_fields_must_be_named() -> None:
    plan = apply([txt(mode="关键词", terms=["USB", "打印"], logic="或", fields=["问题描述"])], "搜一下含USB或打印的问题")
    assert "fields" not in params(plan)
    plan = apply([txt(mode="关键词", terms=["打印", "USB"], logic="和", fields=["问题描述"])], "搜索描述中有「打印」和「USB」的问题")
    assert params(plan)["fields"] == ["问题描述"]


def test_rule11_safety_splits_in_two_unless_aplus() -> None:
    plan = apply([txt(mode="话题", topic="电池起火", domains={"value": ["国内"], "from": "user"})], "国内有没有电池起火这类安全问题？")
    assert skills(plan) == ["list_issues", "text_search"]
    assert params(plan)["filters"][-1]["value"] == "A+" and params(plan, 1)["topic"] == "安全"
    assert len(apply([lst(filters=[{"field": "问题等级", "value": "A+"}])], "安全问题里 A+ 的单有哪些")["steps"]) == 1


# ---------------------------------------------------------------- 第 12 条 格式


def test_rule12_format() -> None:
    wrapped = {"steps": [lst(domains=None, params={"domains": {"value": ["国内"], "from": "user"}})]}
    assert any("格式之外的键" in e for e in schema.check_format(wrapped))
    assert schema.check_format({"steps": [lst(status="未结案")]})
    harmless = {"steps": [txt(mode="话题", topic="音频", **{"from": "user", "topic_scope": "话题本身"})]}
    assert schema.check_format(harmless) == []
    assert schema.check_format({"steps": [lst(f"s{i}") for i in range(1, schema.MAX_STEPS + 2)]})
    bad_ref = {"steps": [lst("s1", filters=[{"field": "机型", "value": {"ref": "s2.top1"}}]), agg("s2", time=T)]}
    assert any("不在本步之前" in e for e in schema.check_format(bad_ref))


# ---------------------------------------------------------------- 第 13–16 条 校验


def test_rule13_event_word_after_time() -> None:
    assert [r for r, _ in checks([agg(time=[{"said": "今年", "basis": "建单"}])], "今年结案了多少单")] == [13]
    assert not checks([agg(time=[{"said": "今年", "basis": "建单"}])], "今年国内结案的单有多少")


def test_rule14_time_in_query_must_be_in_plan() -> None:
    assert [r for r, _ in checks([lst(domains={"value": ["国内"], "from": "user"})], "上个月国内的问题有哪些")] == [14]
    assert not checks([lst(time=[{"said": "上个月", "basis": "建单"}])], "上个月国内的问题有哪些")
    # 结案周期的分档不是时间条件
    assert not checks([agg(time=[{"said": "2026年9月", "basis": "结案"}], metrics=["结案周期"])],
                      "2026 年 9 月结案的国内单平均多久结案？30 天以内、31 到 90 天的各几张？")


def test_rule15_numbers_and_models_in_query_must_be_in_plan() -> None:
    assert [r for r, _ in checks([txt(mode="类似问题", phenomenon="屏幕闪烁")], "A960 屏幕闪烁以前有过吗")] == [15]
    assert [r for r, _ in checks([lst()], "ZC2608038 现在谁在处理")] == [15]


def _intro(kind: str) -> dict:
    return {"id": "s1", "skill": "introduce", "when": None, "params": {"kind": kind}}


DETAIL_PREV = {"steps": [{"id": "s1", "skill": "issue_detail", "when": None,
                          "params": {"issue": {"value": "ZC2604012", "from": "user"}}}]}


def test_rule19_out_of_scope_on_previous_issue_bounces() -> None:
    """CN-053：上一轮打开了一张单，本轮「这张物料单为什么…」写成超出范围时打回，说明里给出那张单。"""
    q = "这张物料单为什么机型显示「物料」？它的影响数量怎么没有？"
    issue = normalize.previous_issue(DETAIL_PREV)
    assert issue == "ZC2604012"
    bounced = normalize.tagged_checks(apply([_intro("超出范围")], q), q, ENTITIES, TODAY, issue)
    assert [r for r, _ in bounced] == [19]
    assert "这张物料单" in bounced[0][1] and "ZC2604012" in bounced[0][1] and "issue_detail" in bounced[0][1]
    # 读不到上一轮计划时看上一轮的用户问句
    assert normalize.previous_issue(None, "ZC2604012 这张单是什么情况？") == "ZC2604012"


@pytest.mark.parametrize(("query", "kind", "issue"), [
    ("能帮我把这张单结案吗？", "只读请求", "ZC2604012"),     # 只读请求照答
    ("这张单的跟进人怎么样了", "寒暄", "ZC2604012"),          # 只管超出范围
    ("今天天气怎么样", "超出范围", "ZC2604012"),              # 没指一张单
    ("其它问题你能查吗", "超出范围", "ZC2604012"),            # 「其它」不是「它」
    ("这些单为什么机型显示物料", "超出范围", "ZC2604012"),     # 指一批
    ("这张单为什么机型显示物料", "超出范围", None),            # 上一轮没有单独说到的单
])
def test_rule19_does_not_bounce_other_introduces(query: str, kind: str, issue: str | None) -> None:
    assert not normalize.tagged_checks(apply([_intro(kind)], query), query, ENTITIES, TODAY, issue)


def test_rule19_previous_issue_needs_exactly_one_number() -> None:
    two = {"steps": [{"id": "s1", "skill": "lookup_numbers", "when": None, "params": {
        "numbers": [{"raw": "ZC2604012", "kind_said": None}, {"raw": "ZC2604013", "kind_said": None}]}}]}
    assert normalize.previous_issue(two) is None
    assert normalize.previous_issue({"steps": [lst()]}, "ZC2604012 这张单是什么情况？") is None  # 有计划时只看计划
    assert normalize.previous_issue(None, None) is None


def test_rule16_values_not_in_query_only_logged() -> None:
    plan = {"steps": [lst(filters=[{"field": "机型", "op": "是", "value": "A930", "from": "user"},
                                   {"field": "加工厂", "op": "是", "value": "亮亮", "from": "previous"}])]}
    assert normalize.values_not_in_query(plan, "国内的问题有哪些") == ["机型"]


# ---------------------------------------------------------------- 第 17 条 汇总没给时间


@pytest.mark.parametrize(
    ("query", "steps"),
    [("各加工厂的合计不良率排一下", [agg(group_by=["加工厂"], metrics=["合计不良率"], ranking=True)]),
     ("所有工厂的合计不良率排一下", [agg(group_by=["加工厂"], metrics=["合计不良率"])]),
     ("按加工厂统计单数和未结案数", [agg(group_by=["加工厂"], metrics=["单数", "未结案数"])])],
)
def test_rule17_aggregate_without_time_asks(query: str, steps: list[dict]) -> None:
    plan = apply(steps, query)
    assert skills(plan) == ["clarify"]
    assert params(plan)["options"] == ["今年", "近 30 天", "2026 年上半年", "不限时间"]


@pytest.mark.parametrize(
    ("query", "step"),
    [("现在各状态各有多少单", agg(group_by=["状态"])),
     ("停线中和已经重启的各有多少单", agg(group_by=["停线状态"])),
     ("各工厂现在还有多少没结案的", agg(group_by=["加工厂"], metrics=["未结案数"])),
     ("现在还有多少单停线", agg(filters=[{"field": "状态", "op": "是", "value": "停线中"}])),
     ("不限时间，按问题类型统计一下", agg(group_by=["问题类型"])),
     ("所有时间里各工厂的问题数", agg(group_by=["加工厂"])),
     ("找到的这些单按工厂分一下", agg(within={"ref": "s0.issues"}, group_by=["加工厂"])),
     ("国内的问题有哪些", lst(domains={"value": ["国内"], "from": "user"}))],
)
def test_rule17_no_clarify(query: str, step: dict) -> None:
    assert skills(apply([step], query)) == [step["skill"]]


def test_rule17_previous_without_time() -> None:
    this_turn = [agg(domains={"value": ["国内"], "from": "previous"}, group_by=["问题类型"])]
    no_time = {"steps": [lst(domains={"value": ["国内"], "from": "user"})]}
    assert skills(apply(this_turn, "按问题类型统计这些单", previous=no_time)) == ["aggregate"]
    assert skills(apply(this_turn, "按问题类型统计这些单", previous={"steps": [lst(time=T)]})) == ["clarify"]
    assert skills(apply(this_turn, "按问题类型统计这些单")) == ["clarify"]


def test_rule17_model_written_time_clarify_uses_code_options() -> None:
    model = {"id": "s1", "skill": "clarify", "when": None,
             "params": {"reason": "缺时间", "question": "统计哪段时间？", "options": ["今年"]}}
    assert params(apply([model], "统计一下制程问题"))["options"] == normalize.missing_time_clarify(TODAY)["options"]


@pytest.mark.parametrize(
    ("today", "half"),
    [(date(2026, 10, 26), "2026 年上半年"), (date(2027, 3, 1), "2026 年上半年"), (date(2027, 7, 1), "2027 年上半年")],
)
def test_rule17_half_year_option(today: date, half: str) -> None:
    assert normalize.missing_time_clarify(today)["options"] == ["今年", "近 30 天", half, "不限时间"]


# ---------------------------------------------------------------- 第 18 条 上一轮没有结果时「其中」


INHERIT = [agg(filters=[{"field": "机型", "op": "是", "value": "A921", "from": "previous"}], group_by=["状态"])]


def test_rule18_in_previous_after_no_result_asks_with_earlier_option() -> None:
    plan = apply(INHERIT, "其中按状态统计一下", previous_outcome="追问", earlier_query="查询今年 A920 的记录。")
    assert skills(plan) == ["clarify"]
    assert params(plan)["reason"] == normalize.NO_RESULT_REASON
    assert params(plan)["options"] == ["查询今年 A920 的记录，其中按状态统计一下"]
    assert params(apply(INHERIT, "其中按状态统计一下", previous_outcome="查出 0 张"))["options"] == []


def test_rule18_not_applied_when_previous_found_or_only_conditions_change() -> None:
    assert skills(apply(INHERIT, "其中按状态统计一下")) == ["aggregate"]
    assert skills(apply(INHERIT, "那上个月呢", previous_outcome="追问")) == ["aggregate"]


# ---------------------------------------------------------------- 号码直通


_CASES = Path(__file__).resolve().parents[1] / "scripts" / "planner_spike" / "cases" / "plan_cases.json"
#: 对照集 c5 里命中号码直通的问句（§4.2 第 4 步：208 条里命中 16 条，c5 加通用输入后不变）
SHORTCUT_IDS = {f"M-0{i}" for i in range(1, 10)} | {"CN-042", "CN-048", "CN-059", "BR-010", "XC-012", "V-36", "V-37"}


def test_number_shortcut_hits_exactly_the_fixed_set() -> None:
    cases = json.loads(_CASES.read_text(encoding="utf-8"))["cases"]
    got = {c["id"] for c in cases if prematch.number_shortcut(c["q"]) is not None}
    assert got == SHORTCUT_IDS


@pytest.mark.parametrize(
    ("query", "skill"),
    [("ZC2608038", "issue_detail"), ("帮我查一下 ZC2608038 这张单", "issue_detail"),
     ("CAR202601001 关联了哪些制程问题", "lookup_numbers"), ("ZC2608038 和 BR2601009", "lookup_numbers")],
)
def test_number_shortcut_plans(query: str, skill: str) -> None:
    plan = prematch.number_shortcut(query)
    assert plan is not None and plan["steps"][0]["skill"] == skill
    assert schema.check_format(plan) == []


@pytest.mark.parametrize(
    "query",
    ["ZC2608038 现在谁在处理", "上个月国内 ZC2608038 的原因", "A920 的问题有哪些",
     # 评审 M2：写了连字符的机型（总述「机型与系列怎么对」忽略连字符），没说是 PN、PO 时不直通
     "A920-PRO 的问题有哪些", "查一下 A920-PRO", "a920-pro"],
)
def test_number_shortcut_leaves_other_meanings_to_the_planner(query: str) -> None:
    assert prematch.number_shortcut(query) is None


def test_number_shortcut_pn_said_or_machine_list() -> None:
    assert prematch.number_shortcut("PN A920-PRO 是哪些单的")["steps"][0]["skill"] == "lookup_numbers"
    assert prematch.number_shortcut("A35-000-RD6-00E0")["steps"][0]["skill"] == "lookup_numbers"
    # 有机型清单时，对得上的照样不直通
    assert prematch.number_shortcut("A35-000-RD6-00E0", machines={"A35000RD600E0"}) is None


# ---------------------------------------------------------------- 评审 A1、A3、A4


@pytest.mark.parametrize("query", ["各工厂累计不良率排一下", "按累计停线时长排名"])
def test_cumulative_metric_is_not_unlimited_time(query: str) -> None:
    plan = apply([agg(group_by=["加工厂"], metrics=["合计不良率"], ranking=True)], query)
    assert skills(plan) == ["clarify"]


def test_cumulative_count_is_unlimited_time() -> None:
    assert skills(apply([agg(group_by=["加工厂"])], "各工厂累计有多少单")) == ["aggregate"]


def test_rule17_partial_time_is_only_logged() -> None:
    hits: list[RuleHit] = []
    plan = apply([agg("s1", time=T, group_by=["问题类型"]), agg("s2", group_by=["加工厂"])],
                 "今年按问题类型统计，再按工厂统计", hits=hits)
    assert skills(plan) == ["aggregate", "aggregate"]
    assert [(h.rule, h.action) for h in hits] == [(17, "只记日志")]
    hits.clear()
    apply([agg("s1", time=T, group_by=["问题类型"])], "今年按问题类型统计", hits=hits)
    assert hits == []


def test_rule7_inferred_kind_is_recorded_even_when_model_was_right() -> None:
    inferred: list[normalize.Inferred] = []
    apply([lst(filters=[{"field": "供应商", "op": "是", "value": "普瑞特"}])], "普瑞特 物料问题", inferred=inferred)
    assert inferred == [normalize.Inferred("s1", "供应商", ("普瑞特",))]
    inferred.clear()
    apply([agg(time=T, filters=[{"field": "跟进人", "op": "属于", "value": ["柯洱斯", "亮亮"]}])],
          "这个月柯洱斯和亮亮各提交了几张单", inferred=inferred)
    assert inferred == [normalize.Inferred("s1", "加工厂", ("柯洱斯", "亮亮"))]
    inferred.clear()
    apply([lst(filters=[{"field": "供应商", "op": "是", "value": "普瑞特"}])], "供应商普瑞特的物料问题", inferred=inferred)
    assert inferred == []  # 用户说了类别，不是推断
