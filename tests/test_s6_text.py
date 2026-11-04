"""文字查找（S6b，设计 §7、§9.2、§4.1 域闸门；§15 J-D07、J-P11 与「其余单测」里文字查找那几条）。

假数据：国内假单（`cn_data`，单 ID 1–4）与它们在 mart 库里的文字表、分段表（`tests/s6_data.py`）。按意思找的命中由
`FakeRetrieval` 现给；挑说法、判断、摘要三种模型调用按 system 认（`FakeLLM.routes`），规划、分析按顺序回放。
"""

from __future__ import annotations

import io
import json

import pytest
import s6_data
import scopes
from fakes import FakeLLM, make_harness, run
from forge_core.events import EventType
from openpyxl import load_workbook
from structlog.testing import capture_logs

from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import ANSWER_PARAMS, MART, TOPIC_TERMS, Domain
from factory_issue_module.present import summaries
from factory_issue_module.skills import text_search
from factory_issue_module.stats.lib import textmatch as tm
from factory_issue_module.text import judge, keyword, semantic, terms
from factory_issue_module.turn import errors, workspace

CN = {"value": ["国内"], "from": "user"}
T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
SITES = 'issue = "info.test.local"'
TERMS_MARK = "定按文字找单时用哪些说法"
JUDGE_MARK = "是否与用户要找的话题有关"
SIM_MARK = "与用户描述的问题现象是不是同一类问题"
SUMMARY_MARK = "浓缩成一两句话"


def plan(*steps: dict) -> dict:
    return {"understanding": "按文字找", "alternatives": [], "steps": list(steps)}


def step(skill: str, sid: str = "s1", **params) -> dict:
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


def _buttons(events) -> list[dict]:
    for e in events:
        if e.type is EventType.SUGGESTIONS:
            return e.data.get("recommendations") or []
    return []


def _col(table: dict, name: str) -> list:
    at = table["columns"].index(name)
    return [r[at] for r in table["rows"]]


def _numbers(table: dict) -> list[str]:
    """问题编号一列去掉链接（`[ZC9901001](…)` → ZC9901001）。"""
    return [str(r[0]).split("]")[0].lstrip("[") for r in table["rows"]]


def _user(messages) -> dict:
    return json.loads(messages[-1]["content"])


def harness(privileges=None, replies=(), config: dict | None = None, **load):
    h = make_harness(scopes.account_jia() if privileges is None else privileges, llm_replies=list(replies),
                     config_files={"link_sites.toml": SITES, **(config or {})})
    s6_data.load(h, **load)
    return h


def mart_queries(h, table: str | None = None) -> list:
    """发往 mart 库的 SQL（`table` 给了时只要这张表的）。"""
    return [q for q in h.queries if q.source == MART and (table is None or (q.tables and q.tables[0] == table))]


# ---------------------------------------------------------------------------- 按词匹配三点（§15「其余单测」）


def test_english_terms_need_non_alnum_neighbours():
    ic = tm.tx_term("IC")
    assert tm.tx_match("PICC 读卡失败", [ic], []) == []  # 前后是英文字母：不算
    assert tm.tx_match("ICCID 读不到", [ic], []) == []
    assert [t for t, _c in tm.tx_match("IC卡读不到", [ic], [])] == ["IC"]  # 后面是汉字：算
    assert tm.tx_match("插 ic 卡没反应", [ic], [])  # 不分大小写


def test_chinese_terms_ignore_spaces_and_fullwidth():
    assert tm.tx_match("电池 卡扣断裂", [tm.tx_term("电池卡扣")], [])
    assert tm.tx_match("ＮＦＣ 天线不良", [tm.tx_term("NFC天线")], [])
    _term, context = tm.tx_match("客户反馈：电池 卡扣断裂，返工", [tm.tx_term("电池卡扣")], [])[0]
    assert "【电池 卡扣】" in context  # 上下文按原文截、命中处用【】标出


def test_excluded_terms_mask_without_joining_the_sides():
    # 直接删掉「打印标签」两侧会连成「热敏纸」；换成占位就连不起来
    assert "热敏纸" in "热敏打印标签纸".replace("打印标签", "")
    assert tm.tx_match("热敏打印标签纸", [tm.tx_term("热敏纸")], [tm.tx_term("打印标签")]) == []
    non = tm.tx_term("非接")
    assert tm.tx_match("非接丝印模糊", [non], [tm.tx_term("非接丝印")]) == []
    assert tm.tx_match("非接丝印模糊，非接读卡失败", [non], [tm.tx_term("非接丝印")])


def test_restart_steps_are_split_and_dropped_by_heading():
    text = "停线重启审核：换电池\n工厂制程分析：换电池\n\n责任人填写重启方案：换线"
    assert tm.tx_lines(text, ["停线重启审核", "责任人填写重启方案"]) == ["工厂制程分析：换电池"]
    assert len(tm.tx_lines(text, [])) == 3


def test_terms_are_normalized_before_they_reach_the_spec():
    probe = {"name": "main", "terms": [terms.term("NFC 天线"), terms.term("PICC"), terms.term("Ｔｐ 排线")],
             "codes": None, "columns": [], "excluded": [], "logic": "或", "stars": False}
    spec = keyword.seg_spec(Domain.DOMESTIC, [probe], None)
    conds = spec["filter"]["groups"][-1]["conditions"]
    # PG 的 CONTAINS 编成区分大小写的 LIKE，两列都是小写：不归一会静默漏单
    assert {(c["field"], c["operator"], c["value"]) for c in conds} == {
        ("seg_compact", "CONTAINS", "nfc天线"), ("seg_norm", "CONTAINS", "picc"), ("seg_compact", "CONTAINS", "tp排线")}
    named = keyword.seg_spec(Domain.DOMESTIC, [{**probe, "codes": ["measure"]}], ["measure"])
    assert named["filter"]["groups"][0]["conditions"][0] == {"field": "field", "operator": "IN", "value": ["measure"]}


def test_semantic_hits_order_by_score_then_number():
    from factory_issue_module.stats.tasks import text_merge

    sem = [(3, "c", 0.5), (1, "a", 0.9), (4, "d", None), (2, "b", 0.5)]
    numbers = {1: "ZC9901001", 2: "ZC9901002", 3: "ZC9901003", 4: "ZC9901004"}
    # 同分按问题编号；向量表里没有段的（没有分数）排在最后
    assert [x[0] for x in text_merge.tm_order(sem, numbers)] == [1, 2, 3, 4]


def test_partial_field_names_prefer_the_comparison_range():
    # 只说栏目名的一部分：先对比对范围里的栏目（按词、按意思都找），对不上才对文字表的其他列（决策 2026-10-31）
    assert terms.resolve_fields(["原因"]).codes == ["reason"]  # 不是国内的原因分类说明
    assert terms.resolve_fields(["描述"]).codes == ["desc"]
    assert terms.resolve_fields(["改善"]).codes == ["improve", "measure"]  # 两栏都算
    assert terms.resolve_fields(["原因分类"]).columns == ["f_rclass"]
    assert terms.resolve_fields(["处理步骤意见"]).columns == ["f_step_opinion"]
    assert terms.resolve_fields(["处理步骤"]).codes == ["step"]
    # 哪一域没有点名的栏目：巴西没有改善建议；「改善」还有改善措施，三域都计入
    assert terms.missing_in(terms.resolve_fields(["改善建议"])) == {"巴西": ["改善建议"]}
    assert terms.missing_in(terms.resolve_fields(["改善"])) == {}
    # 点名的几栏本域一栏都没有才不计入；栏目名照有这一栏的域的叫法，与点名时先列栏目、后列文字表的列无关
    assert terms.missing_in(terms.resolve_fields(["重启方案", "改善建议"])) == {"巴西": ["改善建议", "重启方案"]}


async def test_parts_of_a_combined_term_are_dropped():
    llm = FakeLLM([{"terms": ["电池卡扣", "卡扣", "电池扣", "扣"]}])
    got = await terms.choose(llm, "电池卡扣", "组合说法", config_files.default(TOPIC_TERMS), allow_amb=True)
    assert [t["raw"] for t in got.terms] == ["电池卡扣", "电池扣"]  # 「卡扣」是原话的一部分、「扣」只有一个字
    assert got.by_model


# ---------------------------------------------------------------------------- J-D07：安全问题两路分开列


async def test_jd07_safety_lists_aplus_and_text_routes_separately():
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="安全"))
    h = harness(replies=[reply], main=s6_data.main_with(**{"1": {"ProblemLevel": "A+"}}))
    events = await run(h, "近 30 天国内有没有安全问题")
    text = _text(events)
    tables = _tables(events)
    assert len(tables) == 2, text
    assert _numbers(tables[0]) == ["ZC9901001"]  # A+ 一路
    assert _numbers(tables[1]) == ["ZC9901003"]  # 文字一路：起火
    assert _col(tables[1], "分组") == ["问题本身涉及"]
    assert "【起火】" in _col(tables[1], "命中处")[0]
    assert "问题本身涉及的 1 张" in text and "本次按这些说法找：起火" in text
    assert "文字查找：涉及某个话题" in text


def _related(*flags: bool):
    """「可能相关」判断的回复：按这一批的候选张数逐张给（批内序号 1 起）。"""

    def reply(messages):
        items = _user(messages)["候选"]
        return {"results": [{"no": c["no"], "related": flags[k] if k < len(flags) else False}
                            for k, c in enumerate(items)]}

    return reply


async def test_topic_search_groups_and_judges_the_third_group():
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="触摸"))
    h = harness(replies=[reply])
    h.retrieval.hits = [[s6_data.hit(2, "desc", "问题描述：外壳开裂，扣位断裂"),
                         s6_data.hit(4, "measure", "改善措施：NFC天线换料")]]
    h.llm.routes[JUDGE_MARK] = _related(True, False)
    events = await run(h, "国内近 30 天有没有涉及触摸的问题")
    table = _tables(events)[0]
    assert _numbers(table) == ["ZC9901001", "ZC9901002"]  # 判为不相关的那张不列、不计数
    assert _col(table, "分组") == ["问题本身涉及", "可能相关"]
    text = _text(events)
    assert "找到 1 张与触摸有关的单" in text and "另有 1 张说法不同、可能相关" in text
    # 按意思一路限定在本步范围内的单（有时间条件），按单而不是按段
    call = h.retrieval.calls[0]
    assert call["table"] == Domain.DOMESTIC.vec_table and call["restrict_column"] == "issue_id"
    assert call["group_by"] == "issue_id" and sorted(call["restrict_ids"]) == ["1", "2", "3", "4"]
    judged = h.llm.routed(JUDGE_MARK)
    assert len(judged) == 1 and [c["no"] for c in _user(judged[0])["候选"]] == [1, 2]  # 已按词命中的不再判断


async def test_second_group_stays_on_the_table_when_the_first_fills_it():
    """S6b 评审 M1：问题本身涉及的单多于表格条数时，处理中提到的单仍要进表（前两组各给最近 `table_rows` 张）。"""
    texts = {1: {"desc": "触摸失灵"}, 2: {"desc": "触摸漂移"}, 3: {"desc": "触摸无反应"}, 4: {"measure": "更换触摸屏"}}
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="触摸"))
    h = harness(replies=[reply], config={"answer_params.toml": "table_rows = 2"}, texts=texts, extra={})
    events = await run(h, "国内近 30 天有没有涉及触摸的问题")
    table = _tables(events)[0]
    # 第一组 3 张按建单时间取最近 2 张，第二组 1 张照列
    assert dict(zip(_numbers(table), _col(table, "分组"), strict=True)) == {
        "ZC9901001": "问题本身涉及", "ZC9901002": "问题本身涉及", "ZC9901004": "处理中提到"}
    text = _text(events)
    assert "问题本身涉及的 3 张；处理过程中提到的 1 张" in text
    assert "表格列出问题本身涉及的最近 2 张、处理中提到的 1 张" in text


def test_topic_notes_are_read_from_the_explanations_section():
    topics = config_files.default(TOPIC_TERMS)
    leak = topics.notes_for(["漏电"])
    assert len(leak) == 1 and leak[0].asks == (("漏电的问题", "只提到漏电流偏大、电池电压低、待机耗电快的单不列入。"),)
    assert "问安全问题" in leak[0].text  # 整条（含按问法分的三种）交给判断
    assert [n.terms for n in topics.notes_for(["批锋"])] == [("批锋", "披锋")]
    assert topics.notes_for(["刷卡", "打印"]) == []  # 只收讲带 ＊ 说法的条目
    # 管理员上传的清单可以没有「说明」：照常解析，只是没有判断提示
    text = config_files.defaults.topic_terms_text().split("## 说明")[0]
    assert config_files.parse_topic_terms(text).notes == ()


async def test_asking_an_ambiguous_term_states_its_rule_and_judges_by_it():
    """CN-056：问「漏电」只按漏电找；说法清单「说明」那一条交给判断，开头照写哪些单不列入。"""
    texts = {1: {"desc": "整机待机漏电流偏大，耗电快"}, 2: {"desc": "外壳开裂"},
             3: {"desc": "适配器漏电，有触电风险"}, 4: {"desc": ""}}
    reply = plan(step("text_search", domains=CN, mode="话题", topic="漏电"))
    h = harness(replies=[reply], texts=texts, extra={})
    h.llm.routes[TERMS_MARK] = lambda m: {"terms": ["漏电"]}

    def judge_by_guide(messages):
        body = _user(messages)
        assert any("只提到漏电流偏大" in g for g in body.get("判断说明") or [])
        return {"results": [{"no": c["no"], "related": "触电" in c["文字"]} for c in body["候选"]]}

    h.llm.routes[JUDGE_MARK] = judge_by_guide
    events = await run(h, "国内有没有漏电的问题？")
    text = _text(events)
    assert "本次按这些说法找：漏电。只提到漏电流偏大、电池电压低、待机耗电快的单不列入" in text
    table = _tables(events)[0]
    assert dict(zip(_numbers(table), _col(table, "分组"), strict=True)) == {"ZC9901003": "可能相关"}
    assert "找到 0 张与漏电有关的单" in text and "另有 1 张说法不同、可能相关" in text


async def test_whole_topic_judges_by_the_notes_without_listing_them():
    reply = plan(step("text_search", domains=CN, mode="话题", topic="安全"))
    h = harness(replies=[reply], texts={1: {"desc": "整机漏电流偏大"}, 3: {"desc": "电池起火"}}, extra={})
    seen: list[list[str]] = []

    def judge(messages):
        body = _user(messages)
        seen.append(list(body.get("判断说明") or []))
        return {"results": [{"no": c["no"], "related": False} for c in body["候选"]]}

    h.llm.routes[JUDGE_MARK] = judge
    text = _text(await run(h, "国内有没有安全问题"))
    assert seen and any("问安全问题" in g for g in seen[0]) and any("鼓包" in g for g in seen[0])
    assert "不列入" not in text  # 问整个话题时不逐条写


# ---------------------------------------------------------------------------- J-P11：只返回有权的域


async def test_jp11_text_search_only_covers_permitted_domains():
    reply = plan(step("text_search", mode="类似问题", phenomenon="电池起火冒烟"))
    h = harness(replies=[reply])  # 只申请了国内
    h.llm.routes[SIM_MARK] = _related(True, True, True)
    h.retrieval.hits = [[s6_data.hit(3, "desc", "问题描述：电池起火冒烟"), s6_data.hit(99, "desc", "问题描述：别处的单"),
                         s6_data.hit("x", "desc", "问题描述：认不出单号")]]
    events = await run(h, "以前有没有出现过电池起火冒烟")
    tables = _tables(events)
    assert len(tables) == 1 and _numbers(tables[0]) == ["ZC9901003"]
    assert [c["table"] for c in h.retrieval.calls] == [Domain.DOMESTIC.vec_table]  # 只检索国内向量表
    assert "restrict_ids" not in h.retrieval.calls[0]  # 没有条件：不限定候选
    text = _text(events)
    # 只有文字查找：结尾叫查找说明（决策 2026-11-03「回答骨架与排版」）
    assert "巴西、海外无权限，未计入" in text and "查找范围：国内；巴西、海外无权限，未计入" in text
    assert "统计口径" not in text and "**查找说明**" in text and "计数单位" not in text
    assert "国内最相近的问题（1 张）" in text and "文字查找：类似问题" in text and "每域最多 5 张" in text
    assert not h.llm.routed(JUDGE_MARK) and len(h.llm.routed(SIM_MARK)) == 1  # 按类似问题的标准判断


# ---------------------------------------------------------------------------- 类似问题：逐张判断与分数下限


def _sim_hits():
    """三张候选：重排分 0.9、0.5、0.1（第三张低于默认下限 0.2）。"""
    return [[s6_data.hit(1, "desc", "问题描述：开机后屏幕花屏", rerank=0.9),
             s6_data.hit(2, "desc", "问题描述：开机黑屏", rerank=0.5),
             s6_data.hit(3, "desc", "问题描述：开机花屏缺画", rerank=0.1)]]


async def test_similar_lists_only_judged_close_and_above_the_floor():
    reply = plan(step("text_search", domains=CN, mode="类似问题", phenomenon="开机时屏幕出现花屏"))
    h = harness(replies=[reply])
    h.retrieval.hits = _sim_hits()
    h.llm.routes[SIM_MARK] = _related(True, False, True)
    with capture_logs() as logs:
        events = await run(h, "国内有没有出现过开机花屏")
    assert _numbers(_tables(events)[0]) == ["ZC9901001"]  # 第 2 张判为不相近，第 3 张低于下限
    call = h.llm.routed(SIM_MARK)[0]
    body = _user(call)
    assert body[judge.SIM_KEY] == "开机时屏幕出现花屏" and [c["no"] for c in body["候选"]] == [1, 2, 3]
    assert h.retrieval.calls[0]["top_n"] == semantic.TOP_K
    text = _text(events)
    assert "国内最相近的问题（1 张）" in text and "逐张判断是同一类现象的才列出" in text
    got = [x for x in logs if x["event"] == "factory_issue_sim_scores"]
    assert got[0]["floor"] == 0.2 and got[0]["listed"] == 1
    assert got[0]["scores"] == [[0.9, 0.8, 1], [0.5, 0.8, 0], [0.1, 0.8, 1]]
    assert all("sem_scores" not in str(e.data) for e in events)


async def test_similar_says_none_found_when_nothing_is_close():
    reply = plan(step("text_search", domains=CN, mode="类似问题", phenomenon="开机后设备自动播放音乐"))
    h = harness(replies=[reply])
    h.retrieval.hits = _sim_hits()
    h.llm.routes[SIM_MARK] = _related(False, False, False)
    events = await run(h, "国内有没有开机后设备自动播放音乐的")
    assert not _tables(events) and "国内按现象描述没有找到相近的问题" in _text(events)


async def test_similar_floor_is_configurable_and_zero_turns_it_off():
    reply = plan(step("text_search", domains=CN, mode="类似问题", phenomenon="开机时屏幕出现花屏"))
    h = harness(replies=[reply], config={ANSWER_PARAMS: "similar_rerank_floor = 0\n"})
    h.retrieval.hits = _sim_hits()
    h.llm.routes[SIM_MARK] = _related(True, False, True)
    assert _numbers(_tables(await run(h, "国内有没有出现过开机花屏"))[0]) == ["ZC9901001", "ZC9901003"]


async def test_similar_falls_back_to_listing_when_judging_fails():
    reply = plan(step("text_search", domains=CN, mode="类似问题", phenomenon="开机时屏幕出现花屏"))
    h = harness(replies=[reply])
    h.retrieval.hits = _sim_hits()
    h.llm.routes[SIM_MARK] = lambda _m: TimeoutError("超时")
    events = await run(h, "国内有没有出现过开机花屏")
    assert _numbers(_tables(events)[0]) == ["ZC9901001", "ZC9901002"]  # 照列，下限照样筛
    assert errors.SIMILAR_UNJUDGED in _text(events)


async def test_similar_judges_only_the_closest_few_and_the_topic_threshold_does_not_apply():
    reply = plan(step("text_search", domains=CN, mode="类似问题", phenomenon="开机时屏幕出现花屏"))
    h = harness(replies=[reply], config={ANSWER_PARAMS: "rerank_score_threshold = 0.95\n"})
    h.retrieval.hits = [[s6_data.hit(1 + k % 4, "desc", f"问题描述：第 {k} 段", rerank=0.9) for k in range(12)]]
    h.llm.routes[SIM_MARK] = _related(*[True] * 12)
    events = await run(h, "国内有没有出现过开机花屏")
    assert [len(_user(c)["候选"]) for c in h.llm.routed(SIM_MARK)] == [text_search.SIM_JUDGE]
    assert _tables(events)  # 「可能相关」的阈值 0.95 不管类似问题


# ---------------------------------------------------------------------------- 域闸门、按意思一路用不了


async def test_text_tables_denied_answers_unavailable_not_none_found():
    reply = plan(step("text_search", domains=CN, mode="关键词", terms=["起火"]))
    h = harness(scopes.privileges([Domain.DOMESTIC], mart=False), replies=[reply])
    events = await run(h, "搜一下国内描述里有起火的单")
    text = _text(events)
    assert "国内的文字查找暂不可用，未计入" in text and "没有找到" not in text
    assert not _tables(events) and mart_queries(h) == [] and h.retrieval.calls == []


async def test_list_desc_is_unavailable_when_text_tables_are_denied():
    reply = plan(step("list_issues", domains=CN, time=T30))
    h = harness(scopes.privileges([Domain.DOMESTIC], mart=False), replies=[reply, "共 4 张。"])
    events = await run(h, "近 30 天国内的问题有哪些")
    table = _tables(events)[0]
    assert set(_col(table, "问题描述")) == {"暂不可用"} and "问题描述摘要暂不可用，其他列照常" in _text(events)
    assert mart_queries(h) == []


def _mart_renamed(rename) -> dict:
    payload = scopes.privileges([Domain.DOMESTIC])
    names = [item["table"] for item in payload["dataScope"] if item["table"]["name"].startswith("mart.")]
    assert len(names) == 3
    for table in names:
        table["name"] = rename(table["name"])
    return payload


@pytest.mark.parametrize("rename", [lambda n: "pg_other." + n[len("mart."):],
                                    lambda n: n.replace("forge_mart_factory_issue.public", "other_db.other")])
async def test_mart_tables_match_on_the_table_name_only(rename):
    """权限四段名：`privileges.md` 写 `mart.forge_mart_factory_issue.public.<表名>`。本助手按不带架构的表名查这几张表，
    平台 SDK 只比四段名的最后几段（段数同查询的表名，这里就是表名一段），实例段、库、架构写成别的值文字查找也照常
    （前置判断与取数两处，data 0.3.2 `_select_table_path`）。哪天升级 SDK 后这条失败，说明前几段开始参与匹配，要与
    权限平台对齐写法。"""
    reply = plan(step("text_search", domains=CN, mode="关键词", terms=["起火"]))
    h = harness(_mart_renamed(rename), replies=[reply])
    events = await run(h, "搜一下国内描述里有起火的单")
    assert _numbers(_tables(events)[0]) == ["ZC9901003"]
    assert "暂不可用" not in _text(events)


async def test_mart_table_name_itself_must_match():
    reply = plan(step("text_search", domains=CN, mode="关键词", terms=["起火"]))
    h = harness(_mart_renamed(lambda n: n + "_x"), replies=[reply])
    text = _text(await run(h, "搜一下国内描述里有起火的单"))
    assert "国内的文字查找暂不可用，未计入" in text and mart_queries(h) == []


async def test_semantic_unavailable_keeps_keyword_hits():
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="触摸"))
    h = harness(replies=[reply])
    h.ctx.retrieval = None
    events = await run(h, "国内近 30 天有没有涉及触摸的问题")
    assert _numbers(_tables(events)[0]) == ["ZC9901001"]
    text = _text(events)
    assert "按意思找暂不可用，「可能相关」一组没有列出" in text


async def test_similar_without_retrieval_says_unavailable():
    reply = plan(step("text_search", domains=CN, mode="类似问题", phenomenon="电池起火冒烟"))
    h = harness(replies=[reply])
    h.ctx.retrieval = None
    text = _text(await run(h, "国内以前有没有电池起火冒烟的"))
    assert "按意思找暂不可用，类似问题没有列出" in text


async def test_pronoun_in_phenomenon_asks_instead_of_searching():
    reply = plan(step("text_search", domains=CN, mode="类似问题", phenomenon="这种问题"))
    h = harness(replies=[reply])
    events = await run(h, "这种问题以前有过吗")
    assert any(e.type is EventType.CLARIFY for e in events)
    assert h.retrieval.calls == [] and mart_queries(h) == []


# ---------------------------------------------------------------------------- 重启审核中的单（国内「停线」）


async def test_restart_review_issues_do_not_match_restart_scheme_or_steps():
    main = s6_data.main_with(**{"1": {"StopStatus": 4}, "3": {"IsStop": 1, "StopStatus": 3}})
    for fields in (["重启方案"], ["处理步骤内容"]):
        reply = plan(step("text_search", domains=CN, time=T30, mode="点名字段", fields=fields, terms=["换电池"]))
        h = harness(replies=[reply], main=main)
        events = await run(h, f"国内近 30 天{fields[0]}里写了换电池的单")
        assert _numbers(_tables(events)[0]) == ["ZC9901003"], fields  # ZC9901001 重启审核中：不匹配
    # 处理步骤内容里其余环节的条目照常比对
    reply = plan(step("text_search", domains=CN, time=T30, mode="点名字段", fields=["处理步骤内容"],
                      terms=["工厂制程分析"]))
    h = harness(replies=[reply], main=main)
    assert _numbers(_tables(await run(h, "处理步骤内容里提到工厂制程分析的单"))[0]) == ["ZC9901001", "ZC9901003"]


# ---------------------------------------------------------------------------- 问题描述摘要（§9.2）


LONG = "客户现场反馈 A920 在批量 300 台中有 12 台开机后触摸屏偶发失灵，点击图标无反应，重启后恢复，但约半小时后复现，影响出货"


async def test_list_desc_summaries_new_soon_empty_short_and_checked_numbers():
    texts = {1: {"desc": LONG}, 2: {"desc": LONG}, 3: {"desc": "电池起火冒烟"}, 4: {"desc": ""}}
    reply = plan(step("list_issues", domains=CN, time=T30))
    h = harness(replies=[reply, "共 4 张。"], texts=texts, extra={}, missing=(2,))
    h.llm.routes[SUMMARY_MARK] = lambda m: {"items": [{"no": 1, "summary": "A920 批量 300 台有 13 台触摸屏失灵"}]}
    table = _tables(await run(h, "近 30 天国内的问题有哪些"))[0]
    desc = dict(zip(_numbers(table), _col(table, "问题描述"), strict=True))
    assert desc["ZC9901002"] == summaries.NEW_SOON  # 文字表里还没有这张单
    assert desc["ZC9901003"] == "电池起火冒烟"  # 短的照抄
    assert desc["ZC9901004"] == "未填"
    # 摘要里的「13」原文没有：退回原文前约 60 字
    assert desc["ZC9901001"] == LONG[:summaries.SHORT] + "…"
    calls = h.llm.routed(SUMMARY_MARK)
    assert len(calls) == 1 and [x["no"] for x in _user(calls[0])] == [1]  # 只发长的那张，一次调用

    h = harness(replies=[reply, "共 4 张。"], texts=texts, extra={})
    h.llm.routes[SUMMARY_MARK] = lambda m: {"items": [{"no": 1, "summary": "A920 批量 300 台中 12 台触摸屏偶发失灵"},
                                                      {"no": 2, "summary": "同上"}]}
    table = _tables(await run(h, "近 30 天国内的问题有哪些"))[0]
    assert _col(table, "问题描述")[:2] == ["A920 批量 300 台中 12 台触摸屏偶发失灵", "同上"]


async def test_list_export_gives_full_stripped_description():
    texts = {1: {"desc": LONG}, 2: {"desc": "外壳开裂"}, 3: {"desc": "电池起火冒烟"}, 4: {"desc": ""}}
    reply = plan(step("list_issues", domains=CN, time=T30, export=True))
    h = harness(replies=[reply, "共 4 张。"], texts=texts, extra={}, missing=(2,))
    h.llm.routes[SUMMARY_MARK] = lambda m: {"items": [{"no": 1, "summary": "A920 批量 300 台中 12 台触摸屏失灵"}]}
    events = await run(h, "把近 30 天国内的问题全部导出")
    assert "完整 4 张见附件" in _text(events)
    ws = load_workbook(io.BytesIO(next(iter(h.files.saved.values())))).worksheets[0]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    at = rows[0].index("问题描述")
    got = {r[0]: r[at] for r in rows[1:]}
    assert got["ZC9901001"] == LONG and got["ZC9901002"] == summaries.NEW_SOON and got["ZC9901004"] == "未填"


async def test_text_search_export_per_domain_with_full_description():
    texts = {1: {"desc": LONG}, 3: {"desc": "电池起火冒烟"}}
    reply = plan(step("text_search", domains=CN, time=T30, mode="关键词", terms=["触摸", "起火"], export=True))
    h = harness(replies=[reply], texts=texts, extra={})
    h.llm.routes[SUMMARY_MARK] = lambda m: {"items": [{"no": 1, "summary": "A920 触摸屏偶发失灵"}]}
    events = await run(h, "把国内描述里有触摸或起火的单导出")
    assert "完整 2 张见附件" in _text(events)
    ws = load_workbook(io.BytesIO(h.files.saved["按文字找到的问题单.xlsx"])).worksheets[0]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    assert rows[0][:3] == ["问题编号", "机型", "问题描述"] and "命中处" in rows[0]
    assert {r[0]: r[2] for r in rows[1:]}["ZC9901001"] == LONG


async def test_one_or_two_hits_are_named_in_the_first_sentence():
    """合计只有一两张时（决策 2026-11-04「表格里的原因与措施给摘要」）：结论那一句接着点名，单号带链接、括号里写机型
    与结案没有；表格默认列带机型，原因与措施一格是摘要；答后建议有这张单的原因与措施（看全文）。"""
    reply = plan(step("text_search", domains=CN, time=T30, mode="关键词", terms=["起火"]))
    h = harness(replies=[reply], texts={3: {"desc": "电池起火冒烟"}}, extra={})
    events = await run(h, "国内描述里有起火的是哪张单")
    table = _tables(events)[0]
    assert _numbers(table) == ["ZC9901003"]
    assert table["columns"][:3] == ["问题编号", "机型", "问题描述"]
    assert table["columns"][-2:] == ["命中处", "原因与措施"]
    assert _col(table, "机型") == ["A920、A920PRO"]
    conclusion = _text(events).split("\n\n")[1]
    assert conclusion.endswith("的单共 1 张。单号：[ZC9901003](https://info.test.local/#/QualityManage/ProblemDetail?id=3)"
                               "（机型 A920、A920PRO，未结案）。")
    assert _col(table, "原因与措施") == ["这张单上和处理过程里都没有写原因与措施"]
    queries = [b["query"] for b in _buttons(events)]
    assert "ZC9901003 的原因与措施" in queries


async def test_text_search_answer_follows_the_skeleton():
    """回答骨架（决策 2026-11-03「回答骨架与排版」）：提示行（按哪些词找）→ 结论 → 每域一节（小标题写张数、表）
    → 查找说明。模型出错时结论句退回模板句，要点、需关注照常给（决策 2026-11-03「结论的要点与需关注的单」）；张数
    不在开头逐域再说一遍。"""
    reply = plan(step("text_search", domains=CN, time=T30, mode="关键词", terms=["排线", "开裂", "NFC"], logic="或"))
    h = harness(replies=[reply, RuntimeError("模型出错")])
    events = await run(h, "国内描述里有排线、开裂或 NFC 的单")
    types = [e.type for e in events]
    table_at = types.index(EventType.TABLE)
    before = [e.data["text"] for e in events[:table_at] if e.type is EventType.DELTA]
    assert len(before) == 3
    assert before[0].startswith("按这些词找（出现任一个）：排线、开裂、NFC")  # 提示行在最前
    assert "共 3 张" in before[1] and before[1].startswith("\n\n**国内，")  # 结论（模板句）
    assert "\n- **" in before[1] and "**需关注**" in before[1]  # 要点与需关注照常给
    assert before[2] == "\n\n**国内比对范围内的文字里出现任一个词「排线」、「开裂」、「NFC」的单（3 张）**"  # 小标题写张数
    after = "".join(e.data["text"] for e in events[table_at:] if e.type is EventType.DELTA)
    assert "**查找说明**" in after and "排线、开裂、NFC" not in after  # 说法在提示行，结尾不重复
    assert all("；\n" not in e.data["text"] for e in events if e.type is EventType.DELTA)


async def test_lookup_table_desc_uses_the_text_table_too():
    nums = [{"raw": "ZC9901001", "kind_said": None}, {"raw": "ZC9901003", "kind_said": None}]
    h = harness(replies=[plan(step("lookup_numbers", numbers=nums))], missing=(1,))
    table = _tables(await run(h, "ZC9901001、ZC9901003 现在什么状态"))[0]
    assert dict(zip(_numbers(table), _col(table, "问题描述"), strict=True)) == {
        "ZC9901001": summaries.NEW_SOON, "ZC9901003": "电池起火冒烟"}


# ---------------------------------------------------------------------------- 可点选项（最小版）


async def test_narrower_than_topic_offers_whole_topic_button():
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="TP 排线"))
    h = harness(replies=[reply])
    h.llm.routes[TERMS_MARK] = lambda m: {"terms": ["TP"]}
    events = await run(h, "国内近 30 天有没有 TP 排线的问题")
    text = _text(events)
    assert "再加上『某个说法』" in text  # 说法有模型挑的：可以增减（不做按钮）
    buttons = _buttons(events)
    assert buttons and buttons[0]["label"] == "按整个话题找" and buttons[0]["query"] == "按整个触摸话题找"
    picked = h.llm.routed(TERMS_MARK)
    assert len(picked) == 1 and _user(picked[0])["任务"] == "挑说法"


PIPE = {1: {"desc": "触摸屏偶发失灵", "reason": "排线压伤"}, 2: {"desc": "外壳开裂", "measure": "顺带更换排线后正常"},
        3: {"desc": "电池起火冒烟"}, 4: {"desc": ""}}


async def test_off_list_topic_offers_first_group_only_and_the_click_names_those_fields():
    from test_s5_multiturn import Conversation

    class Data:  # 这一条的假数据：「排线」第一组、第二组各命中一张
        @staticmethod
        def load(h):
            s6_data.load(h, texts=PIPE, extra={})

    c = Conversation(scopes.account_jia(), data=Data)
    c.h.llm.routes[TERMS_MARK] = lambda m: {"terms": ["软排线"]}
    events = await c.ask("国内近 30 天有没有涉及排线的问题",
                         plan(step("text_search", domains=CN, time=T30, mode="话题", topic="排线")))
    table = _tables(events)[0]
    assert _col(table, "分组") == ["问题本身涉及", "处理中提到"]
    first = next(b for b in _buttons(events) if b["label"] == "只看问题本身涉及的")
    assert first["query"] == "问题现象、问题描述、原因分析里提到排线的单"  # 规划器照点名字段写，不用改计划格式
    assert len(first["label"]) <= 30
    # 点了之后：规划器写成点名第一组三栏、沿用上一轮的条件
    c.h.llm.routes[JUDGE_MARK] = _related(True)
    c.h.retrieval.hits = [[s6_data.hit(3, "desc", "问题描述：电池起火冒烟")]]
    again = plan(step("text_search", domains={"value": ["国内"], "from": "previous"},
                      time=[{**T30[0], "from": "previous"}], mode="点名字段",
                      fields=["问题现象", "问题描述", "原因分析"], topic="排线"))
    events = await c.ask(first["query"], again)
    table = _tables(events)[0]
    assert dict(zip(_numbers(table), _col(table, "分组"), strict=True)) == {"ZC9901001": "直接提到",
                                                                           "ZC9901003": "可能相关"}
    assert c.h.retrieval.calls[-1]["filters"] == {"field": ["phen", "desc", "reason"]}  # 按意思找也只在这三栏
    text = _text(events)
    assert "问题现象、问题描述、原因分析里提到排线的单 1 张；另有 1 张说法不同、可能相关" in text
    assert not any(b["label"] == "只看问题本身涉及的" for b in _buttons(events))


async def test_first_group_button_needs_both_groups_and_an_off_list_topic():
    # 只有一组有单：点了结果一样，不给；话题本身（说法来自清单）：不给
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="排线"))
    h = harness(replies=[reply], texts={**PIPE, 2: {"desc": "外壳开裂"}}, extra={})
    h.llm.routes[TERMS_MARK] = lambda m: {"terms": []}
    assert not any(b["label"] == "只看问题本身涉及的" for b in _buttons(await run(h, "有没有涉及排线的问题")))
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="触摸"))
    h = harness(replies=[reply], texts={1: {"desc": "触摸失灵"}, 2: {"measure": "更换触摸屏"}}, extra={})
    events = await run(h, "有没有涉及触摸的问题")
    assert _col(_tables(events)[0], "分组") == ["问题本身涉及", "处理中提到"]
    assert not any(b["label"] == "只看问题本身涉及的" for b in _buttons(events))


async def test_approach_and_phenomenon_without_overlap_offer_two_counted_buttons():
    reply = plan(step("text_search", domains=CN, time=T30, mode="话题", topic="电池起火", approach="换料", ask="做法"))
    h = harness(replies=[reply])
    h.llm.routes[TERMS_MARK] = lambda m: {"terms": []}
    events = await run(h, "国内近 30 天有没有用换料解决过电池起火")
    text = _text(events)
    # 做法：ZC9901002「换料后正常」、ZC9901004「NFC天线换料」；现象：ZC9901003「电池起火冒烟」；两边都命中的没有
    assert "用换料处理过、又涉及电池起火的单 0 张：用换料处理过的 2 张，涉及电池起火的 1 张" in text
    buttons = _buttons(events)
    assert [b["label"] for b in buttons] == ["只看用换料处理过的（2 张）", "只看电池起火的（1 张）"]
    assert [b["query"] for b in buttons] == ["只看用换料处理过的", "只看电池起火的"]
    assert all(len(b["label"]) <= 30 for b in buttons)


# ---------------------------------------------------------------------------- 多轮：工作区、递进筛选、质疑重查


async def test_text_round_records_terms_and_next_round_filters_within_stored_ids():
    from test_s5_multiturn import Conversation

    c = Conversation(scopes.account_jia(), data=s6_data)
    first = plan(step("text_search", domains=CN, time=T30, mode="关键词", terms=["换"]))
    await c.ask("国内近 30 天描述里有「换」的单", first)
    results = c.ws(workspace.RESULTS)
    assert results["v"] == workspace.VERSION >= 2  # S6b 加 `texts` 时为 2，S7 加临时统计的脚本后为 3
    assert results["texts"]["s1"]["terms"] == ["换"] and results["steps"]["s1"]["国内"]["numbers"] == [
        "ZC9901001", "ZC9901002", "ZC9901004"]
    seg = Domain.DOMESTIC.seg_table
    seg_before, vec_before = len(mart_queries(c.h, seg)), len(c.h.retrieval.calls)
    assert seg_before == 1
    again = {**first["steps"][0], "params": {**first["steps"][0]["params"], "domains": {"value": ["国内"],
                                                                                        "from": "previous"}}}
    second = plan(again, step("list_issues", "s2", within={"ref": "s1.issues"},
                              filters=[{"field": "状态", "op": "是", "value": "曾经停线", "from": "user"}]))
    events = await c.ask("其中停过线的", second)
    assert len(mart_queries(c.h, seg)) == seg_before  # 不重找：分段表没有再读
    assert _numbers(_tables(events)[0]) == ["ZC9901001"]
    assert "按文字找" not in _text(events)  # 那一步不单独成段
    assert c.ws(workspace.RESULTS)["texts"]["s1"]["terms"] == ["换"]  # 再往下一轮还能接着用
    assert len(c.h.retrieval.calls) == vec_before


async def test_verify_previous_text_search_compares_and_notes_judging():
    from test_s5_multiturn import Conversation

    c = Conversation(scopes.account_jia(), data=s6_data)
    c.h.llm.routes[JUDGE_MARK] = _related(True)
    c.h.retrieval.hits = [[s6_data.hit(2, "desc", "问题描述：外壳开裂")], [s6_data.hit(2, "desc", "问题描述：外壳开裂")]]
    await c.ask("国内近 30 天有没有涉及触摸的问题",
                plan(step("text_search", domains=CN, time=T30, mode="话题", topic="触摸")))
    events = await c.ask("你确定吗", plan(step("verify_previous")))
    text = _text(events)
    assert "国内：与上一轮一致，2 张" in text
    assert "每次判断可能略有不同" in text
    assert not _tables(events)


@pytest.mark.parametrize("version", [1, 2])  # 2：S7 之前的值（`turn.steps` 里还没有临时统计的脚本）
async def test_old_workspace_version_is_treated_as_no_context(version):
    from test_s5_multiturn import Conversation

    c = Conversation(scopes.account_jia(), data=s6_data)
    c.h.workspace.store[workspace.RESULTS] = {"v": version, "steps": {}}
    assert await workspace.read(c.h.ctx, workspace.RESULTS) is None
