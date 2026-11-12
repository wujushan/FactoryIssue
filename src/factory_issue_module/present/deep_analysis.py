"""仅由用户明确请求时生成的、带记录证据的深入分析与研发建议（G106）。

默认统计结论仍由 `narrative.POINTS_SYSTEM` 写作；本模块单独提供意图白名单、证据摘取、引用核验、数值核验与呈现。
模型只能引用代码给出的证据代号；最终显示的域、问题编号、字段与引文都由代码回填。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from forge_core.events import Event

from factory_issue_module.declarations import DOMAINS
from factory_issue_module.present import links, narrative

logger = structlog.get_logger(__name__)

#: FakeLLM 路由标记；生产代码使用本模块专属的固定 system。
ROUTE_MARKER = "本轮记录证据的深入分析与研发改进建议"
SYSTEM = """本轮记录证据的深入分析与研发改进建议。你是制程问题记录的证据分析助手。你只能使用本轮用户问句、程序给出的统计摘要、以及【可引用记录片段】中的文字。

规则：
1. 只分析这些记录和本轮查询范围；不要引用外部知识、未提供的单据或上轮记录。统计摘要由程序确定，不能重新计算。
2. 每条判断只说一项记录支持的模式、差异或证据缺口，保持谨慎，不把少数所选记录推广成整体结论。不要把相关性说成已证实因果，不要断言根因。没有记录支持时不凑结论。
3. 每条分析判断都要有至少一条直接支持它的引用。引用只能使用给定的 evidence_id，并逐字摘录该片段中连续的原文；不得改写引文。判断正文必须包含每条引用中的原文关键短语，不能只在引用列表中放一段与判断无关的原文。
4. 【本轮请求类别】由程序按用户原话的明确短语判定；只输出值为 true 的类别。值为 false 的类别必须是空数组，不得从上下文推断用户想要它。
5. 只有用户明确要求研发改进建议时才输出 recommendations。每条建议必须与记录证据相连，是需要验证的候选方向，并写清验证方法；不得声称措施已经有效。证据不够就返回空数组。
6. 不计算、不推测、不改写任何数字、比例、排名、日期、目标值或时限；如需数字，统计已在正式结果中给出，不要在判断或建议里另报数字。
7. 不输出事实段，事实由程序按原文呈现。不要输出标题、Markdown 围栏或额外说明。
8. 严格只输出一个 JSON 对象，形状如下：
{"analysis":[{"text":"一条判断","citations":[{"evidence_id":"E1","quote":"连续原文"}]}],"recommendations":[{"proposal":"待验证的研发方向","validation":"核实方式","citations":[{"evidence_id":"E1","quote":"连续原文"}]}]}
"""

MAX_TICKETS = 9
MAX_TICKETS_PER_DOMAIN = 3
MAX_EVIDENCE_PER_TICKET = 2
MAX_EVIDENCE_CHARS = 360
MAX_ITEMS = 3
MAX_CITATIONS = 3
MAX_CITATION_CHARS = 80
MAX_CLAIM_CHARS = 600
_CHAT_KW: dict[str, Any] = {"temperature": 0, "max_tokens": 1800, "response_format": {"type": "json_object"}}

_ANALYSIS_REQUEST = re.compile(r"深入分析|深度分析|进一步分析|详细分析|deep\s*analysis", re.I)
_RECOMMEND_REQUEST = re.compile(
    r"(?:研发(?:改进)?(?:建议|方案|方向)|改进(?:建议|方案|方向)|改善(?:建议|方案)|优化(?:建议|方案)"
    r"|(?:怎么|如何)(?:改进|改善|优化))",
    re.I,
)
_NEGATION = re.compile(r"(?:不要|别|勿|不必|无需|不需要|不用|不想要|不希望|不提供|不生成|不输出|不做|不再需要)")
_NEGATION_FILLERS = tuple(sorted((
    "直接", "单独", "额外", "具体", "相关", "本轮", "这部分", "一份", "一段", "一条", "任何", "一些",
    "给出", "提供", "提出", "生成", "输出", "做出", "作出", "写出", "附上", "列出", "进行", "开展",
    "展开", "采用", "使用", "尝试", "处理", "给我", "帮我", "对这张单", "这张单", "对", "这", "张",
    "本次", "此次", "该", "为", "你", "有", "去", "帮", "给", "做", "写", "附", "加", "再", "只", "仅",
    "以及", "或者", "并且", "还有", "和", "与", "及", "或",
    "我", "的", "要", "深入", "深度", "详细", "研发", "改进", "改善", "优化", "分析", "建议", "方案",
    "方向", "内容", "一", "个", "些",
), key=len, reverse=True))
_CLAUSE_BOUNDARY = re.compile(r"[，,。；;！？!?\n]")
_CANDIDATE_LANGUAGE = re.compile(r"建议|可考虑|可以考虑|候选|待验证|待核实|验证方向|排查方向|试点")
_VALIDATION_METHOD = re.compile(r"复测|抽检|检查|核对|验证|记录|观察|对照|试产|测试|比对|监测|跟踪|复现|测量|审查|追溯")

# 不确定限定只能降低断言语气，不能让没有引用的猜测通过；引用与数字另有独立核验。
_CAUSAL = re.compile(
    r"根因|根本原因|原因是|是因为|因为|由于|导致|造成|引起|引发|促成|触发|归因|源于|因果|因此|所以|因而|从而|进而|使得"
)
_HEDGE = re.compile(r"可能|或许|推测|疑似|待验证|有待|尚不明确|尚不能确认|不能确认|不能断定|验证是否|排查是否|不排除")
_MODEL_NUMBER = re.compile(
    r"百分比|百分之[零一二两三四五六七八九十百千万亿]+|[零一二两三四五六七八九十百千万亿]+分之"
    r"[零一二两三四五六七八九十百千万亿]+|比例|占比|排名|排行|半数|一半|"
    r"今年|去年|前年|明年|本月|上月|下月|本周|上周|下周|今天|昨天|明天|近期|最近|"
    r"所有|全部|每[张个条份项起]|多[次张个条]|许多|大量|多数|少数|若干|普遍|通常|常见|广泛|大部分|绝大部分|"
    r"第[一二两三四五六七八九十]+|(?<![A-Za-z])[几零一二两三四五六七八九十百千万亿]+"
    r"(?:余|多|来)?(?=[张个条次天周月年倍名成项起类家台])"
)
_THINK = re.compile(r"<think>.*?</think>", re.S)
_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)

#: 只摘录与现象、原因、处理有关且本来就在用户可见详情里的文字字段；表格中的人员、时间、数量不作分析证据。
_EVIDENCE_BLOCKS = ("description", "reasons", "phenomena", "possible_reasons")
_PLACEHOLDERS = {"", "未填", "—", "–", "-", "n/a", "none", "nan"}
_DOMAIN_BY_LABEL = {domain.label: domain for domain in DOMAINS}


@dataclass(frozen=True)
class Request:
    analysis: bool = False
    recommendations: bool = False

    @property
    def active(self) -> bool:
        return self.analysis or self.recommendations


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    domain: str
    number: str
    record_id: int
    field: str
    text: str
    truncated: bool = False


@dataclass(frozen=True)
class Citation:
    evidence: Evidence
    quote: str


@dataclass(frozen=True)
class AnalysisItem:
    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class RecommendationItem:
    proposal: str
    validation: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Generated:
    analysis: tuple[AnalysisItem, ...] = ()
    recommendations: tuple[RecommendationItem, ...] = ()


def _normalise_query(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).lower()


def _negated(text: str, start: int) -> bool:
    """同一分句里的明确否定生效；「不要只给统计，要深入分析」不误判成否定分析。"""
    boundary = max((m.end() for m in _CLAUSE_BOUNDARY.finditer(text, 0, start)), default=0)
    before = text[boundary:start]
    # 「不要只给建议」表示不想要的只是“仅有建议”，不能关闭建议本身。
    if re.search(r"(?:不要|别|不必|无需|不需要|不用)只", before):
        return False
    tail = before[-40:]
    matches = list(_NEGATION.finditer(tail))
    if not matches:
        return False
    rest = tail[matches[-1].end():]
    while rest:
        filler = next((word for word in _NEGATION_FILLERS if rest.startswith(word)), None)
        if filler is None:
            return False
        rest = rest[len(filler):]
    return True


def _has_request(pattern: re.Pattern[str], text: str) -> bool:
    return any(not _negated(text, match.start()) for match in pattern.finditer(text))


def requested(query: str) -> Request:
    """只从本轮用户原话按短语白名单触发；规划模型与历史消息不参与判断。"""
    text = _normalise_query(query)
    return Request(_has_request(_ANALYSIS_REQUEST, text), _has_request(_RECOMMEND_REQUEST, text))


def _trimmed_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return "" if text.casefold() in _PLACEHOLDERS else text


def evidence_from_tickets(tickets: Sequence[Mapping[str, Any]]) -> list[Evidence]:
    """从详情的可见原文中按优先级选证据；每单最多两段，每段最多 360 字。"""
    out: list[Evidence] = []
    for ticket in tickets:
        domain = str(ticket.get("domain") or "")
        number = str(ticket.get("number") or "")
        record_id = ticket.get("id")
        if domain not in _DOMAIN_BY_LABEL or not number or not isinstance(record_id, int):
            continue
        blocks = ticket.get("blocks")
        if not isinstance(blocks, Mapping):
            continue
        used_fields: set[str] = set()
        for block_key in _EVIDENCE_BLOCKS:
            block = blocks.get(block_key)
            if not isinstance(block, Mapping):
                continue
            # 每个来源块最多取一段：先保留问题描述，再为原因/措施留一段，避免描述块里的备注挤掉原因证据。
            for item in block.get("fields") or []:
                if not isinstance(item, Sequence) or isinstance(item, str) or len(item) < 2:
                    continue
                field_name = str(item[0] or "").strip()
                text = _trimmed_text(item[1])
                if not field_name or not text or field_name in used_fields:
                    continue
                excerpt = text[:MAX_EVIDENCE_CHARS]
                out.append(Evidence(
                    evidence_id=f"E{len(out) + 1}", domain=domain, number=number, record_id=record_id,
                    field=field_name, text=excerpt, truncated=len(text) > len(excerpt),
                ))
                used_fields.add(field_name)
                break
            if len(used_fields) >= MAX_EVIDENCE_PER_TICKET:
                break
    return out


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(v) for v in value]
    return str(value)


def _compact(text: str) -> tuple[str, list[int], list[int]]:
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        chars.append(char)
        starts.append(index)
        ends.append(index + 1)
    return "".join(chars), starts, ends


def _source_quote(source: str, quote: str) -> str | None:
    """允许引文空白格式不同，但必须是原文（去空白后）的连续子串；返回原文中的准确切片。"""
    wanted, _, _ = _compact(str(quote or ""))
    available, starts, ends = _compact(source)
    if len(wanted) < 3:
        return None
    start = available.find(wanted)
    if start < 0:
        return None
    return source[starts[start]:ends[start + len(wanted) - 1]]


def _citations(raw: Any, evidence: Mapping[str, Evidence]) -> tuple[Citation, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for item in raw[:MAX_CITATIONS]:
        if not isinstance(item, Mapping):
            continue
        evidence_id = str(item.get("evidence_id") or "")
        source = evidence.get(evidence_id)
        if source is None:
            continue
        raw_quote = str(item.get("quote") or "")
        if len(_compact(raw_quote)[0]) > MAX_CITATION_CHARS:
            continue
        quote = _source_quote(source.text, raw_quote)
        key = (evidence_id, quote or "")
        if quote is None or key in seen:
            continue
        seen.add(key)
        out.append(Citation(source, quote))
    return tuple(out)


def _causality_is_qualified(text: str) -> bool:
    for match in _CAUSAL.finditer(text):
        nearby = text[max(0, match.start() - 18):match.end() + 18]
        if not _HEDGE.search(nearby):
            return False
    return True


def _claim_has_citation_anchor(text: str, citations: Sequence[Citation]) -> bool:
    claim, _, _ = _compact(text)
    return bool(citations) and all(_compact(citation.quote)[0] in claim for citation in citations)


def _claim_is_supported(question: str, stats: Any, citations: Sequence[Citation], text: str,
                        entities: Mapping[str, Sequence[str]]) -> bool:
    # 统计数字、比例、日期、排名都留给确定性结果；原文中的数值由事实段直接展示，不让模型在分析 prose 里复述。
    if any(char.isnumeric() for char in text) or _MODEL_NUMBER.search(text):
        return False
    # 核数只把这条判断实际引用的原文放进出处，避免借用另一张未引用记录里的数字或名称。
    quoted = [{"域": c.evidence.domain, "问题编号": c.evidence.number, "字段": c.evidence.field, "原文": c.quote}
              for c in citations]
    source_facts = {"本轮确定性统计": _json_safe(stats), "本条引用原文": quoted}
    table = json.dumps(_json_safe(stats), ensure_ascii=False)
    rows = "\n".join(f"{c.evidence.domain} {c.evidence.number} {c.evidence.field} {c.quote}" for c in citations)
    checked = narrative.check(question, None, table, source_facts, text, entities, rows)
    return (_claim_has_citation_anchor(text, citations) and not checked["bad"] and not checked["leaks"]
            and _causality_is_qualified(text))


def _clean_claim(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    if not text or len(text) > MAX_CLAIM_CHARS:
        return ""
    return text


def _valid_analysis(raw: Any, evidence: Mapping[str, Evidence], question: str, stats: Any,
                    entities: Mapping[str, Sequence[str]]) -> tuple[AnalysisItem, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[AnalysisItem] = []
    for item in raw[:MAX_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        text = _clean_claim(item.get("text"))
        citations = _citations(item.get("citations"), evidence)
        if len(text) < 8 or not citations or not _claim_is_supported(question, stats, citations, text, entities):
            continue
        out.append(AnalysisItem(text, citations))
    return tuple(out)


def _valid_recommendations(raw: Any, evidence: Mapping[str, Evidence], question: str, stats: Any,
                           entities: Mapping[str, Sequence[str]]) -> tuple[RecommendationItem, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[RecommendationItem] = []
    for item in raw[:MAX_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        proposal = _clean_claim(item.get("proposal"))
        validation = _clean_claim(item.get("validation"))
        citations = _citations(item.get("citations"), evidence)
        claim = "。".join(text for text in (proposal, validation) if text)
        if (len(proposal) < 6 or len(validation) < 4 or not citations
                or not _CANDIDATE_LANGUAGE.search(proposal)
                or not _VALIDATION_METHOD.search(validation)
                or not _claim_has_citation_anchor(proposal, citations)
                or not _claim_is_supported(question, stats, citations, claim, entities)):
            continue
        out.append(RecommendationItem(proposal, validation, citations))
    return tuple(out)


def _response_content(response: Any) -> str:
    try:
        return str(response["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


async def generate(llm: Any, question: str, step_name: str, stats: Any, evidence: Sequence[Evidence],
                   entities: Mapping[str, Sequence[str]], request: Request | None = None) -> Generated:
    """最多调用一次模型；仅生成明确请求的类别，任何无效声明都 fail-closed。"""
    request = request or requested(question)
    if llm is None or not evidence or not request.active:
        return Generated()
    allowed = {item.evidence_id: item for item in evidence}
    user_payload = {
        "本轮用户问句": question,
        "本轮最后一个实际执行步骤": step_name,
        "本轮请求类别": {"深入分析": request.analysis, "研发改进建议": request.recommendations},
        "程序确定的统计摘要": _json_safe(stats),
        "可引用记录片段": [
            {"evidence_id": item.evidence_id, "域": item.domain, "问题编号": item.number,
             "字段": item.field, "原文": item.text}
            for item in evidence
        ],
    }
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    try:
        raw = _response_content(await llm.chat(messages, **_CHAT_KW))
    except Exception as exc:  # noqa: BLE001 — 此为可选增补，失败时保留已发的统计与明细
        logger.warning("factory_issue_deep_analysis_failed", error=type(exc).__name__)
        return Generated()
    content = _THINK.sub("", raw).strip()
    content = _CODE_FENCE.sub("", content)
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.info("factory_issue_deep_analysis_invalid_json")
        return Generated()
    if not isinstance(payload, Mapping):
        return Generated()
    analysis = (_valid_analysis(payload.get("analysis"), allowed, question, stats, entities)
                if request.analysis else ())
    recommendations = (_valid_recommendations(payload.get("recommendations"), allowed, question, stats, entities)
                       if request.recommendations else ())
    return Generated(analysis, recommendations)


def _evidence_label(item: Evidence, sites: Any) -> str:
    domain = _DOMAIN_BY_LABEL[item.domain]
    number = links.issue(sites, domain, item.number, item.record_id)
    excerpt = "，节录" if item.truncated else ""
    return f"{item.domain} {number}（{item.field}{excerpt}）"


def _evidence_block(item: Evidence, sites: Any, quote: str | None = None) -> str:
    text = item.text if quote is None else quote
    lines = text.splitlines() or [text]
    citation = _evidence_label(item, sites)
    return f"{citation}：\n" + "\n".join(f"  > {line}" for line in lines)


def _render_citations(citations: Sequence[Citation], sites: Any) -> str:
    return "\n".join(f"  - 依据：{_evidence_block(item.evidence, sites, item.quote)}" for item in citations)


def render(request: Request, evidence: Sequence[Evidence], generated: Generated, sites: Any,
           gap_notice: str | None = None) -> Event:
    """记录事实始终由程序按原文呈现；分析与建议仅呈现用户本轮明确请求的类别。"""
    sections = ["**本轮记录事实（原文片段）**"]
    sections.extend(f"- {_evidence_block(item, sites)}" for item in evidence)
    if gap_notice:
        sections.append(gap_notice)
    sections.append("所选记录仅用于定性举证，不据此推断整体比例或已证实因果。")

    if request.analysis:
        sections.append("**基于记录的分析判断（推断）**")
        if generated.analysis:
            for item in generated.analysis:
                sections.append(f"- {item.text}")
                sections.append(_render_citations(item.citations, sites))
        else:
            sections.append("当前记录未能形成满足引用与核验要求的分析判断。")

    if request.recommendations:
        sections.append("**研发改进建议（待验证）**")
        if generated.recommendations:
            for item in generated.recommendations:
                sections.append(f"- {item.proposal}")
                sections.append(f"  - 验证方式：{item.validation}")
                sections.append(_render_citations(item.citations, sites))
        else:
            sections.append("当前记录不足以形成有引用依据的研发改进建议，暂不提出建议。")

    return Event.delta("\n\n" + "\n".join(sections))


def no_results(request: Request) -> Event:
    parts = ["本轮没有查到可供引用的单据。"]
    if request.analysis:
        parts.append("无法基于记录生成深入分析。")
    if request.recommendations:
        parts.append("没有足够记录证据提出研发改进建议。")
    return Event.delta("\n\n" + "".join(parts))


def no_evidence(request: Request, gap_notice: str | None = None) -> Event:
    parts = ["本轮未能取得可供引用的记录原文。"]
    if request.analysis:
        parts.append("未生成基于记录的深入分析。")
    if request.recommendations:
        parts.append("没有足够证据提出研发改进建议。")
    if gap_notice:
        parts.append(gap_notice)
    return Event.delta("\n\n" + "".join(parts))


def skipped_previous(request: Request) -> Event:
    parts = ["为确保只依据本轮实际取数的记录，本次没有使用上一轮暂存结果。"]
    if request.analysis:
        parts.append("未生成基于上一轮记录的深入分析。")
    if request.recommendations:
        parts.append("未基于上一轮记录提出研发改进建议。")
    return Event.delta("\n\n" + "".join(parts))
