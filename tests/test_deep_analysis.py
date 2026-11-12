"""G106：明确请求时才启用、原文可追溯、无效判断与建议 fail-closed。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from forge_core.events import EventType

import s4_data
import scopes
from fakes import FakeLLM, data_queries, make_harness, run

from factory_issue_module.declarations import Domain
from factory_issue_module.present import deep_analysis
from factory_issue_module.turn import deep_analysis as turn_deep_analysis
from factory_issue_module.turn.gate import DomainAccess

CN = {"value": ["国内"], "from": "user"}
RECENT30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
SITES = 'issue = "info.test.local"'


def _plan(*steps: dict) -> dict:
    return {"understanding": "按条件查", "alternatives": [], "steps": list(steps)}


def _step(skill: str, **params) -> dict:
    return {"id": "s1", "skill": skill, "when": None, "params": params}


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _analysis_reply(messages):
    assert [m["role"] for m in messages].count("system") == 1
    assert messages[0]["role"] == "system"
    payload = json.loads(messages[-1]["content"])
    assert payload["本轮请求类别"] == {"深入分析": True, "研发改进建议": True}
    evidence = payload["可引用记录片段"]
    assert evidence
    desc = next(item for item in evidence if item["字段"] == "问题描述")
    reason = next(item for item in evidence if item["字段"] == "原因")
    desc_quote, reason_quote = desc["原文"][:6], reason["原文"][:6]
    return {
        "analysis": [{
            "text": f"记录中的“{desc_quote}”与“{reason_quote}”分别记载异常表现和原因字段内容，二者关系仍需结合处理过程核实。",
            "citations": [
                {"evidence_id": desc["evidence_id"], "quote": desc_quote},
                {"evidence_id": reason["evidence_id"], "quote": reason_quote},
            ],
        }],
        "recommendations": [{
            "proposal": f"建议将记录中的“{reason_quote}”作为待验证的复测方向，检查是否与异常表现同时出现。",
            "validation": "复测时记录输入条件和处理前后现象，再判断是否需要调整验证内容。",
            "citations": [{"evidence_id": reason["evidence_id"], "quote": reason_quote}],
        }],
    }


def _sample_evidence() -> list[deep_analysis.Evidence]:
    return [deep_analysis.Evidence("E1", "国内", "ZC9901001", 1, "问题描述", "按键偶发失灵")]


@pytest.mark.parametrize(
    ("query", "analysis", "recommendations"),
    [
        ("近 30 天国内按问题类型统计", False, False),
        ("按问题类型分析今年的情况", False, False),
        ("这张单的原因与改善措施是什么", False, False),
        ("请深入分析这批问题", True, False),
        ("请给出研发改进建议", False, True),
        ("请深入分析，但不要给研发改进建议", True, False),
        ("不要深度分析，但请给改进建议", False, True),
        ("不要提出研发改进建议，但请深入分析", True, False),
        ("不要只给统计，要深入分析", True, False),
        ("不要深度分析，也不需要优化建议", False, False),
        ("不要深度分析和研发改进建议", False, False),
        ("请不要对这张单做深入分析", False, False),
        ("请勿给出研发改进建议", False, False),
        ("不要深度分析，但请给出研发改进建议", False, True),
        ("有什么建议，按机型统计", False, False),
    ],
)
def test_request_uses_explicit_phrases_and_category_specific_negation(query, analysis, recommendations):
    assert deep_analysis.requested(query) == deep_analysis.Request(analysis, recommendations)


def test_evidence_selection_keeps_description_and_reason_before_other_description_fields():
    ticket = {
        "domain": "国内",
        "number": "ZC9901001",
        "id": 1,
        "blocks": {
            "description": {"fields": [
                ["问题描述", "按键偶发失灵"], ["改善建议", "记录中已有的改善方向"], ["备注", "一般备注"],
            ]},
            "reasons": {"fields": [["原因", "按键弹片偏软"], ["措施", "更换弹片"]]},
            "phenomena": {"fields": [["问题现象", "输入时偶发无响应"]]},
        },
    }
    evidence = deep_analysis.evidence_from_tickets([ticket])
    assert [(item.field, item.text) for item in evidence] == [
        ("问题描述", "按键偶发失灵"), ("原因", "按键弹片偏软"),
    ]


def test_evidence_rejects_bad_records_and_marks_truncated_original_text():
    long_text = "按键偶发失灵" * 100
    evidence = deep_analysis.evidence_from_tickets([
        {"domain": "国内", "number": "ZC9901001", "id": 1,
         "blocks": {"description": {"fields": [["问题描述", long_text]]}}},
        {"domain": "未知域", "number": "X1", "id": 2,
         "blocks": {"description": {"fields": [["问题描述", "不应进入证据"]]}}},
        {"domain": "国内", "number": "ZC9901003", "id": 3,
         "blocks": {"description": {"fields": [["问题描述", "未填"]]}}},
    ])
    assert len(evidence) == 1
    assert evidence[0].text == long_text[:deep_analysis.MAX_EVIDENCE_CHARS]
    assert evidence[0].truncated


async def test_validates_citations_anchors_causality_numbers_and_requested_categories():
    evidence = _sample_evidence()
    llm = FakeLLM([{
        "analysis": [
            {"text": "问题描述记录“按键偶发失灵”，这段原文没有说明具体原因。",
             "citations": [{"evidence_id": "E1", "quote": "按键 偶发失灵"}]},
            {"text": "单据显示存在系统性缺陷，已影响其他产品。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
            {"text": "按键偶发失灵的根因是接触不良。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
        ],
        "recommendations": [{
            "proposal": "建议把“按键偶发失灵”纳入待验证的检查方向。",
            "validation": "复测时记录输入条件和处理前后现象。",
            "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}],
        }],
    }])
    generated = await deep_analysis.generate(
        llm, "请深入分析", "单张单详情", {}, evidence, {}, deep_analysis.Request(analysis=True),
    )
    assert len(generated.analysis) == 1
    assert generated.analysis[0].text.startswith("问题描述记录")
    assert generated.analysis[0].citations[0].quote == "按键偶发失灵"
    # 虽然模型返回了建议，代码按本轮类别开关丢弃，分析请求不会产生建议。
    assert generated.recommendations == ()
    payload = json.loads(llm.calls[0][-1]["content"])
    assert payload["本轮请求类别"] == {"深入分析": True, "研发改进建议": False}


async def test_unhedged_causal_claims_are_rejected():
    evidence = _sample_evidence()
    llm = FakeLLM([{
        "analysis": [
            {"text": "按键偶发失灵的因果关系已经明确。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
            {"text": "按键偶发失灵触发了设计问题。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
        ],
        "recommendations": [],
    }])
    generated = await deep_analysis.generate(
        llm, "请深入分析", "单张单详情", {}, evidence, {}, deep_analysis.Request(analysis=True),
    )
    assert generated.analysis == ()


async def test_model_cannot_introduce_numbers_or_unverifiable_citations():
    evidence = _sample_evidence()
    llm = FakeLLM([{
        "analysis": [
            {"text": "按键偶发失灵记录数量达到 99 张。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
            {"text": "本轮计入 1 张单，按键偶发失灵。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
            {"text": "按键偶发失灵。",
             "citations": [{"evidence_id": "E99", "quote": "按键偶发失灵"},
                           {"evidence_id": "E1", "quote": "按键完全失灵"}]},
        ],
        "recommendations": [{
            "proposal": "建议把“按键偶发失灵”纳入待验证的检查方向。",
            "validation": "复测时记录输入条件和处理前后现象。",
            "citations": [{"evidence_id": "E1", "quote": "不存在的原文"}],
        }],
    }])
    generated = await deep_analysis.generate(
        llm, "请深入分析并给改进建议", "清单", {"计入单数": 1}, evidence, {},
        deep_analysis.Request(analysis=True, recommendations=True),
    )
    assert generated.analysis == ()
    assert generated.recommendations == ()


async def test_model_failure_fails_closed_without_affecting_requested_result_sections():
    evidence = _sample_evidence()
    llm = FakeLLM([TimeoutError("model timeout")])
    request = deep_analysis.Request(analysis=True, recommendations=True)
    generated = await deep_analysis.generate(llm, "请深入分析并给改进建议", "清单", {}, evidence, {}, request)
    event = deep_analysis.render(request, evidence, generated, None)
    assert generated == deep_analysis.Generated()
    assert "本轮记录事实（原文片段）" in event.data["text"]
    assert "当前记录未能形成满足引用与核验要求的分析判断" in event.data["text"]
    assert "暂不提出建议" in event.data["text"]
    assert "model timeout" not in event.data["text"]


async def test_recommendations_must_be_evidence_linked_candidates_with_a_verification_method():
    evidence = _sample_evidence()
    llm = FakeLLM([{
        "analysis": [{"text": "不应生成分析段。",
                      "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]}],
        "recommendations": [
            {"proposal": "建议将“按键偶发失灵”作为待验证方向。",
             "validation": "复测时记录输入条件和处理前后现象。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
            {"proposal": "建议更换弹片并直接定为最终措施。",
             "validation": "复测时记录结果。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
            {"proposal": "可以考虑更换零件。", "validation": "再确认一下。",
             "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}]},
        ],
    }])
    generated = await deep_analysis.generate(
        llm, "请给研发改进建议", "单张单详情", {}, evidence, {},
        deep_analysis.Request(recommendations=True),
    )
    assert generated.analysis == ()
    assert len(generated.recommendations) == 1
    assert generated.recommendations[0].proposal == "建议将“按键偶发失灵”作为待验证方向。"


def test_text_search_analysis_candidates_exclude_possible_related_and_preserve_number_alignment():
    run_step = SimpleNamespace(skill="text_search", sid="s1", stored=None)
    out = SimpleNamespace(
        refs={"s1.issues": {"国内": {"ids": [1, 2, 3], "numbers": ["ZC9901001", "ZC9901002", "ZC9901003"]}}},
        digest={"analysis_issues": {"国内": [2, 3]}, "focus": [
            {"dom": "国内", "id": 3}, {"dom": "国内", "id": 3},
        ]},
    )
    access = DomainAccess(frozenset({Domain.DOMESTIC}), car=False, text_search=frozenset({Domain.DOMESTIC}))

    targets = turn_deep_analysis._targets(run_step, out, access)
    assert [(target.pid, target.number) for target in targets] == [
        (3, "ZC9901003"), (2, "ZC9901002"),
    ]


def test_focus_order_is_global_before_stable_result_fallback():
    run_step = SimpleNamespace(skill="list_issues", sid="s1", stored=None)
    out = SimpleNamespace(
        refs={"s1.issues": {
            "国内": {"ids": [1, 2], "numbers": ["ZC9901001", "ZC9901002"]},
            "海外": {"ids": [8, 9], "numbers": ["HW9901008", "HW9901009"]},
        }},
        digest={"focus": [{"dom": "海外", "id": 9}, {"dom": "国内", "id": 2}]},
    )
    access = DomainAccess(frozenset({Domain.DOMESTIC, Domain.OVERSEAS}), car=False, text_search=frozenset())

    targets = turn_deep_analysis._targets(run_step, out, access)
    assert [(target.domain.label, target.number) for target in targets] == [
        ("海外", "HW9901009"), ("国内", "ZC9901002"), ("国内", "ZC9901001"), ("海外", "HW9901008"),
    ]


async def test_partial_evidence_gaps_and_denied_domains_are_disclosed(monkeypatch):
    run_step = SimpleNamespace(skill="list_issues", sid="s1", stored=None, denied=[Domain.BRAZIL])
    out = SimpleNamespace(
        ok=True,
        found_any=True,
        domains=["国内"],
        refs={"s1.issues": {"国内": {"ids": [1, 2], "numbers": ["ZC9901001", "ZC9901002"]}}},
        digest={},
    )
    ticket = {"domain": "国内", "number": "ZC9901001", "id": 1,
              "blocks": {"description": {"fields": [["问题描述", "按键偶发失灵"]]}}}

    async def fetch(_T, _targets):
        return [ticket], [], []

    monkeypatch.setattr(turn_deep_analysis.issue_detail, "fetch_tickets", fetch)
    h = make_harness(scopes.GREEN, llm_replies=[])
    h.llm.routes[deep_analysis.ROUTE_MARKER] = lambda messages: {
        "analysis": [{
            "text": "记录中的“按键偶发失灵”仍需结合处理过程核实。",
            "citations": [{"evidence_id": "E1", "quote": "按键偶发失灵"}],
        }],
    }
    T = SimpleNamespace(access=DomainAccess(frozenset({Domain.DOMESTIC}), car=False, text_search=frozenset()),
                        ctx=h.ctx, query="请深入分析", entities={}, sites=None)

    events = await turn_deep_analysis.events_for(T, run_step, out, deep_analysis.Request(analysis=True))
    text = "".join(event.data.get("text", "") for event in events)
    assert "受权限限制未纳入分析的域：巴西" in text
    assert "详情未能读取：国内 ZC9901002" in text
    assert "仅基于已取得的原文" in text


async def test_explicit_request_adds_cited_analysis_after_stats_and_export_only():
    query = "近 30 天国内的问题有哪些？请深入分析并给研发改进建议。"
    config = {"link_sites.toml": SITES, "answer_params.toml": "export_threshold = 1"}
    h = make_harness(scopes.GREEN, llm_replies=[
        _plan(_step("list_issues", domains=CN, time=RECENT30)),
        "近 30 天国内问题单已按时间列出。",
    ], config_files=config)
    s4_data.load(h)
    h.llm.routes[deep_analysis.ROUTE_MARKER] = _analysis_reply

    events = await run(h, query)
    text = _text(events)
    assert "**本轮记录事实（原文片段）**" in text
    assert "**基于记录的分析判断（推断）**" in text
    assert "**研发改进建议（待验证）**" in text
    assert "按键手感差" in text and "按键弹片偏软" in text
    assert "验证方式：复测时记录输入条件和处理前后现象" in text
    assert "问题描述" in text and "原因" in text and "ZC9901001" in text
    assert "https://info.test.local/#/QualityManage/ProblemDetail?id=1" in text
    assert len(h.llm.routed(deep_analysis.ROUTE_MARKER)) == 1
    assert any("ProblemDesc" in q.sql for q in h.queries if q.tables and q.tables[0] == "ZCTracking_ProblemList")

    analysis_index = next(i for i, event in enumerate(events)
                          if event.type is EventType.DELTA and "本轮记录事实" in event.data.get("text", ""))
    normal_output_indices = [i for i, event in enumerate(events) if event.type in (EventType.TABLE, EventType.CHART)]
    normal_output_indices += [i for i, event in enumerate(events)
                              if event.type is EventType.DELTA and
                              ("统计口径" in event.data.get("text", "") or ".xlsx" in event.data.get("text", ""))]
    assert normal_output_indices and analysis_index > max(normal_output_indices)
    suggestion_indices = [i for i, event in enumerate(events) if event.type is EventType.SUGGESTIONS]
    assert suggestion_indices and analysis_index < min(suggestion_indices)

    # 普通列表与带 opt-in 的同一查询保持原有事件/模型路径，不增加详情取数或分析模型调用。
    normal = make_harness(scopes.GREEN, llm_replies=[
        _plan(_step("list_issues", domains=CN, time=RECENT30)),
        "近 30 天国内问题单已按时间列出。",
    ], config_files=config)
    s4_data.load(normal)
    normal_events = await run(normal, "近 30 天国内的问题有哪些")
    assert "本轮记录事实" not in _text(normal_events)
    assert normal.llm.routed(deep_analysis.ROUTE_MARKER) == []
    assert len(normal.llm.calls) == 2
    assert not any("ProblemDesc" in q.sql for q in normal.queries
                   if q.tables and q.tables[0] == "ZCTracking_ProblemList")
    assert len(data_queries(h)) > len(data_queries(normal))


async def test_single_issue_detail_reuses_this_turn_detail_without_fetching_again():
    config = {"link_sites.toml": SITES}
    deep = make_harness(scopes.GREEN, llm_replies=[
        _plan(_step("issue_detail", issue={"value": "ZC9901001", "from": "user"})),
    ], config_files=config)
    s4_data.load(deep)
    deep.llm.routes[deep_analysis.ROUTE_MARKER] = _analysis_reply
    deep_events = await run(deep, "ZC9901001 请深入分析并给研发改进建议")
    assert "按键手感差" in _text(deep_events)
    assert len(deep.llm.routed(deep_analysis.ROUTE_MARKER)) == 1

    ordinary = make_harness(scopes.GREEN, llm_replies=[], config_files=config)
    s4_data.load(ordinary)
    ordinary_events = await run(ordinary, "ZC9901001 这张单帮我查一下")
    assert "本轮记录事实" not in _text(ordinary_events)
    assert len(ordinary.llm.calls) == 0
    assert len(data_queries(deep)) == len(data_queries(ordinary))


def test_analysis_only_render_does_not_show_recommendation_section():
    evidence = _sample_evidence()
    cited = deep_analysis.Citation(evidence[0], "按键偶发失灵")
    generated = deep_analysis.Generated(
        analysis=(deep_analysis.AnalysisItem("记录描述显示按键偶发失灵。", (cited,)),),
        recommendations=(deep_analysis.RecommendationItem(
            "建议把按键偶发失灵纳入待验证方向。", "复测并记录结果。", (cited,)
        ),),
    )
    event = deep_analysis.render(
        deep_analysis.Request(analysis=True), evidence, generated, None,
        "证据缺口：详情未能读取：国内 ZC9901002。以下内容仅基于已取得的原文。",
    )
    assert "基于记录的分析判断" in event.data["text"]
    assert "研发改进建议" not in event.data["text"]
    assert "证据缺口" in event.data["text"] and "ZC9901002" in event.data["text"]

    recommendation = deep_analysis.render(deep_analysis.Request(recommendations=True), evidence, generated, None)
    assert "研发改进建议（待验证）" in recommendation.data["text"]
    assert "基于记录的分析判断" not in recommendation.data["text"]
