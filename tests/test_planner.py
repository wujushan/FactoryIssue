"""规划器与有权限的一轮（设计 §4.2 第 3–7 步、§4.4、§5.6、§9.4；夹具 J-P04）。"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from typing import Any

import pytest
import scopes
from fakes import MANIFEST, data_queries, make_harness, run
from forge_core.events import EventType

from factory_issue_module.config import files
from factory_issue_module.declarations import TOPIC_TERMS
from factory_issue_module.plan import clarify, normalize, prompt
from factory_issue_module.plan.planner import PlanInputs, Planner
from factory_issue_module.turn import errors, workspace

TOPICS = files.default(TOPIC_TERMS)


def plan_of(*steps: dict, alternatives: list[str] | None = None) -> dict:
    return {"understanding": "测试", "alternatives": alternatives or [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params: Any) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


LIST_LAST_MONTH = plan_of(step("list_issues", domains={"value": ["国内"], "from": "user"},
                               time=[{"said": "上个月", "basis": "建单", "from": "user"}]))


def _types(events: list[Any]) -> list[EventType]:
    return [e.type for e in events]


def _text(events: list[Any]) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


# ---------------------------------------------------------------- 规划与修一次（顺序同 spike 的 run_plan）


class _LLM:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[dict], dict]] = []

    async def chat(self, messages: list[dict], **kw: Any) -> dict:
        self.calls.append((messages, kw))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else __import__("json").dumps(reply, ensure_ascii=False)
        return {"choices": [{"message": {"content": content}}]}


async def _plan(query: str, *replies: Any) -> tuple[Any, _LLM]:
    llm = _LLM(*replies)
    result = await Planner(MANIFEST, TOPICS).plan(llm, PlanInputs(query=query))
    return result, llm


async def test_good_plan_is_one_call_with_json_and_temperature_zero():
    result, llm = await _plan("上个月国内的问题有哪些", LIST_LAST_MONTH)
    assert result.plan is not None and result.calls == 1
    messages, kw = llm.calls[0]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert kw == {"temperature": 0.0, "response_format": {"type": "json_object"}}


async def test_bad_format_is_repaired_once_with_the_same_prefix():
    result, llm = await _plan("上个月国内的问题有哪些", "不是 JSON", LIST_LAST_MONTH)
    assert result.plan is not None and result.calls == 2
    first, _ = llm.calls[0]
    second, _ = llm.calls[1]
    assert second[:2] == first and [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == "不是 JSON" and "不合格" in second[3]["content"]


async def test_bad_twice_fails():
    result, _ = await _plan("上个月国内的问题有哪些", "不是 JSON", {"steps": []})
    assert result.plan is None and result.calls == 2


async def test_check_bounce_then_bad_repair_keeps_first_plan():
    no_time = plan_of(step("list_issues", domains={"value": ["国内"], "from": "user"}))
    result, llm = await _plan("上个月国内的问题有哪些", no_time, "坏了")
    assert result.plan is not None and result.calls == 2
    assert "time" not in result.plan["steps"][0]["params"]
    assert result.check_errors and "上个月" in result.check_errors[0]
    assert "上个月" in llm.calls[1][0][3]["content"]


async def test_check_bounce_then_good_repair_uses_repaired_plan():
    no_time = plan_of(step("list_issues", domains={"value": ["国内"], "from": "user"}))
    result, _ = await _plan("上个月国内的问题有哪些", no_time, LIST_LAST_MONTH)
    assert result.plan["steps"][0]["params"]["time"][0]["said"] == "上个月" and result.check_errors == []


async def test_call_error_fails_without_retry():
    result, llm = await _plan("上个月国内的问题有哪些", TimeoutError("超时"))
    assert result.plan is None and len(llm.calls) == 1


async def test_number_shortcut_skips_the_model():
    result, llm = await _plan("ZC2608038", LIST_LAST_MONTH)
    assert result.source == "shortcut" and llm.calls == [] and result.plan["steps"][0]["skill"] == "issue_detail"


async def test_rule_hits_are_returned():
    model = plan_of(step("aggregate", group_by=["加工厂"], metrics=["合计不良率"]))
    result, _ = await _plan("各加工厂的合计不良率排一下", model)
    assert result.plan["steps"][0]["skill"] == "clarify"
    assert [h.rule for h in result.hits] == [17]


# ---------------------------------------------------------------- 提示词（§5.6）


def test_system_has_no_date_and_is_cached():
    system = prompt.planner_system(MANIFEST, TOPICS)
    assert system is prompt.planner_system(MANIFEST, TOPICS)
    assert "2026-" not in system and prompt.PROMPT_VERSION == "p2.2"
    assert "一部今年有哪些问题" in system


def test_user_carries_history_previous_plan_and_outcome():
    user = prompt.planner_user("其中按状态统计一下", [{"role": "user", "content": "查 A921"},
                                                    {"role": "assistant", "content": "没有找到机型 A921"}],
                               {"steps": [step("list_issues")]}, "追问")
    assert user.splitlines()[:3] == ["【最近几轮】", "用户：查 A921", "助手：没有找到机型 A921"]
    assert "【上一轮结局】追问，没有查到结果" in user and user.endswith("【本轮问题】其中按状态统计一下")


_DIGEST = (
    "import hashlib;"
    "from factory_issue_module.config import files;"
    "from factory_issue_module.declarations import TOPIC_TERMS;"
    "from factory_issue_module.module import FactoryIssueModule;"
    "from factory_issue_module.plan import prompt;"
    "print(hashlib.sha256(prompt.planner_system(FactoryIssueModule.manifest,"
    " files.default(TOPIC_TERMS)).encode()).hexdigest())"
)


def test_system_is_the_same_across_hash_seeds():
    """拼装不遍历 set：不同进程（字符串哈希随机）拼出的 system 逐字相同（§5.6）。"""
    here = hashlib.sha256(prompt.planner_system(MANIFEST, TOPICS).encode()).hexdigest()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([sys.executable, "-c", _DIGEST], env=env, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == here, seed


# ---------------------------------------------------------------- 追问的形状（§4.4）


def test_code_options_append_value_to_the_question():
    recs = clarify.recommendations(normalize.missing_time_clarify(), "按工厂统计一下问题数量")
    assert [r["query"] for r in recs][:1] == ["按工厂统计一下问题数量（今年）"]
    assert recs[-1]["query"] == "按工厂统计一下问题数量（不限时间）"
    assert all(set(r) == {"id", "name", "label", "query"} for r in recs)


def test_cannot_follow_options_are_sent_as_they_are():
    """接不上上一轮：原话多是「？？？」或乱码，选项直接作问句。"""
    recs = clarify.recommendations(
        {"reason": "接不上上一轮", "question": "想查什么？", "options": ["列出最近的问题单", "统计问题数量"]}, "？？？")
    assert [r["query"] for r in recs] == ["列出最近的问题单", "统计问题数量"]


@pytest.mark.parametrize(
    ("reason", "query", "option", "want"),
    [("现象太泛", "以前有没有类似的情况？", "开机花屏", "以前有没有类似的情况（开机花屏）"),
     ("「其他」指什么", "有哪些其他问题？", "问题类型为「其他」", "有哪些其他问题（问题类型为「其他」）")],
)
def test_model_options_with_meaningful_question_append_to_it(reason, query, option, want):
    """「其他」指什么、现象太泛：原话有意思，选项多是短语，`query` 是原话加选项（开发者 2026-10-29 定）。"""
    recs = clarify.recommendations({"reason": reason, "question": "…", "options": [option]}, query)
    assert recs[0]["query"] == want and recs[0]["label"] == option


def test_alternatives_become_switch_to_that_understanding():
    """其他理解的按钮不拼本轮原话（INFO 网页前端把 `query` 当按钮文字，设计 §19）：「换个理解：这条理解」。"""
    recs = clarify.alternative_recommendations(["「普瑞特」指物料名称", "", "按供应商为普瑞特查物料问题的单。"])
    assert [r["query"] for r in recs] == ["换个理解：「普瑞特」指物料名称", "换个理解：按供应商为普瑞特查物料问题的单"]
    assert all(set(r) == {"id", "name", "label", "query"} and len(r["label"]) <= 15 for r in recs)
    assert clarify.alternative_recommendations(None) == []


def test_short_code_options_send_the_option_itself():
    """代码追问、`pending_clarify` 写进去了：按钮的 `query` 就是选项本身，与问句全文的按钮同一顺序。"""
    params = {"reason": "名称对上多个", "question": "…", "options": ["惠州百富", "惠州二厂", "TT：巴西的加工厂"]}
    short, full = clarify.short_recommendations(params), clarify.recommendations(params, "惠州工厂的问题？")
    assert [r["query"] for r in short] == ["惠州百富", "惠州二厂", "TT：巴西的加工厂"]
    assert [r["label"] for r in short] == [r["label"] for r in full]
    assert full[0]["query"] == "惠州工厂的问题（惠州百富）"
    assert all(set(r) == {"id", "name", "label", "query"} for r in short)


def test_earlier_query_option_label():
    recs = clarify.recommendations({"reason": normalize.NO_RESULT_REASON, "question": "…",
                                    "options": ["查询今年 A920 的记录，其中按状态统计一下"]}, "其中按状态统计一下")
    assert recs[0]["label"] == clarify.EARLIER_LABEL and recs[0]["query"].startswith("查询今年 A920")


def test_unknown_time_option_replaces_the_phrase():
    recs = clarify.recommendations(clarify.time_unknown_step("国庆以来")["params"], "国庆以来国内有多少单")
    assert [r["query"] for r in recs] == ["近 30 天国内有多少单", "今年国内有多少单"]


def test_labels_are_short_and_at_most_four():
    recs = clarify.recommendations({"reason": "现象太泛", "options": [f"选项{i}" * 5 for i in range(6)]}, "q")
    assert len(recs) == 4 and all(len(r["label"]) <= 15 for r in recs)


# ---------------------------------------------------------------- 有权限的一轮


async def test_jp04_partial_domain_greeting_via_planner():
    """J-P04：只有国内权限的用户寒暄 → 规划器写 introduce，介绍三域，巴西、海外注「申请后可查」，按钮只用国内示例。"""
    h = make_harness(scopes.account_jia(), llm_replies=[plan_of(step("introduce", kind="寒暄"))])
    events = await run(h, "你好")
    assert _types(events) == [EventType.DELTA, EventType.SUGGESTIONS]
    text = _text(events)
    assert text.count(errors.APPLY_TO_VIEW) == 2 and "国内" in text
    for rec in events[1].data["recommendations"]:
        assert "巴西" not in rec["query"] and "海外" not in rec["query"]
    assert data_queries(h) == [] and len(h.llm.calls) == 1


@pytest.mark.parametrize(("kind", "answer"), [("只读请求", errors.READ_ONLY), ("超出范围", errors.OUT_OF_SCOPE)])
async def test_introduce_out_of_scope(kind: str, answer: str):
    h = make_harness(scopes.account_jia(), llm_replies=[plan_of(step("introduce", kind=kind))])
    events = await run(h, "帮我把 ZC9910001 结案")
    assert _types(events) == [EventType.DELTA, EventType.SUGGESTIONS] and answer in _text(events)
    assert data_queries(h) == []


async def test_model_clarify_is_one_clarify_event():
    reply = plan_of(step("clarify", reason="现象太泛", question="想查什么现象？", options=["开机花屏", "按键失灵"]))
    h = make_harness(scopes.account_jia(), llm_replies=[reply])
    events = await run(h, "以前有没有类似的情况")
    assert _types(events) == [EventType.CLARIFY]
    assert [r["query"] for r in events[0].data["recommendations"]] == [
        "以前有没有类似的情况（开机花屏）", "以前有没有类似的情况（按键失灵）"]


async def test_aggregate_without_time_clarifies_with_code_options():
    reply = plan_of(step("aggregate", group_by=["加工厂"]))
    h = make_harness(scopes.account_jia(), llm_replies=[reply])
    events = await run(h, "按工厂统计一下问题数量")
    assert _types(events) == [EventType.CLARIFY]
    assert "按工厂统计一下问题数量（不限时间）" in [r["query"] for r in events[0].data["recommendations"]]


async def test_unknown_time_clarifies_without_fetching():
    reply = plan_of(step("aggregate", time=[{"said": "国庆以来", "basis": "建单", "from": "user"}]))
    h = make_harness(scopes.account_jia(), llm_replies=[reply])
    events = await run(h, "国庆以来国内有多少单")
    assert _types(events) == [EventType.CLARIFY] and "国庆以来" in events[0].data["question"]
    assert data_queries(h) == []


async def test_skill_not_yet_wired_answers_not_ready():
    """临时统计随 S7 接上；在那之前答「暂时还答不了」，不取业务数据（文字查找 S6b 已接上）。"""
    reply = plan_of(step("custom_stats", describe="按星期几统计建单数",
                         time=[{"said": "今年", "basis": "建单", "from": "user"}]))
    h = make_harness(scopes.account_jia(), llm_replies=[reply])
    events = await run(h, "今年按星期几统计一下建单数")
    assert _types(events) == [EventType.DELTA, EventType.SUGGESTIONS] and errors.NOT_READY in _text(events)
    assert data_queries(h) == []


async def test_rule18_reads_last_from_workspace_and_history():
    """上一轮是追问（工作区 `last`）、本轮「其中…」：改为追问，选项是更早那次的原话接上本轮原话。"""
    reply = plan_of(step("aggregate", group_by=["状态"],
                         filters=[{"field": "机型", "op": "是", "value": "A921", "from": "previous"}]))
    history = [("查询今年 A920 的记录。", "（列出了今年 A920 的问题单）"),
               ("查一下不存在的型号A921有哪些记录。", "没有找到机型 A921，请核对机型名称。")]
    h = make_harness(scopes.account_jia(), llm_replies=[reply], history=history)
    h.workspace.store[workspace.LAST] = {
        "v": workspace.VERSION, "query": "查一下不存在的型号A921有哪些记录。", "outcome": workspace.OUTCOME_CLARIFY,
        "plan": plan_of(step("list_issues", filters=[{"field": "机型", "op": "是", "value": "A921"}])),
        "earlier_query": "查询今年 A920 的记录。"}
    events = await run(h, "其中按状态统计一下")
    assert _types(events) == [EventType.CLARIFY]
    rec = events[0].data["recommendations"][0]
    assert rec["label"] == clarify.EARLIER_LABEL and rec["query"] == "查询今年 A920 的记录，其中按状态统计一下"
    user = h.llm.calls[0][1]["content"]
    assert "【上一轮结局】追问，没有查到结果" in user and "A921" in user


async def test_last_from_long_ago_or_old_version_is_ignored():
    h = make_harness(scopes.account_jia(), history=[("上个月国内的问题有哪些", "（清单）")])
    h.workspace.store[workspace.LAST] = {"v": workspace.VERSION, "query": "很久以前的问题", "outcome": "追问"}
    assert await workspace.read_previous(h.ctx, [{"role": "user", "content": "上个月国内的问题有哪些"}]) == workspace.NOTHING
    h.workspace.store[workspace.LAST] = {"v": 0, "query": "上个月国内的问题有哪些", "outcome": "追问"}
    assert await workspace.read_previous(h.ctx, [{"role": "user", "content": "上个月国内的问题有哪些"}]) == workspace.NOTHING
