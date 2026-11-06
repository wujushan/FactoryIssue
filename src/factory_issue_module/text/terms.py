"""文字查找第 ① 步：定说法与找法（设计 §7.1 ①；总述「按哪些说法找」「点名字段时怎么找」「按问法分工」「涉及某个
话题怎么找」；`topic_terms.md`）。

- 话题本身：说法清单里这个话题的全部说法，不调模型。
- 比话题小：一次模型调用，从相关话题的说法里挑意思相同的几个（只能从清单里挑）；用户的说法本身总在里面。
- 组合说法、清单外：同一次调用让模型提几个说法（中文至少 2 个字）；用户原话本身总在里面，模型提的若是原话的一部分
  （「电池卡扣」里的「卡扣」）丢掉并记日志。挑到的说法在清单里时沿用清单的 ＊ 与不算的说法。
- 关键词、用户自己用引号给的词：只按用户给的词找，不套说法清单。
- 点名字段：比对范围内的栏目按词、按意思都找，其余栏目只按词找文字表的那一列；点名问题描述、问题现象、原因时
  带 ＊ 的命中作补充的候选，点名其他栏目不用带 ＊ 的说法。
- 问做法：只在措施类栏目里找，不用带 ＊ 的说法；还说了现象时做法、现象各找一遍，两边都命中的才列入。
- 检索前的问句必须自足（D-10）：类似问题取计划里的现象描述，话题本身取话题的一句话说明，其余取「涉及 + 原话 +
  的问题」；现象描述里还有「这个」「那种」一类指代时按「接不上上一轮」追问。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

from factory_issue_module import landed
from factory_issue_module.config.files import Segmentation, Topic, TopicTerms
from factory_issue_module.domains import base
from factory_issue_module.plan import normalize, schema
from factory_issue_module.textnorm import compact, has_cjk
from factory_issue_module.textnorm import normalize as tn_normalize

logger = structlog.get_logger(__name__)

#: 现象描述里出现这些说法，说明它指着上文、不能拿去检索（D-10）
PRONOUNS = ("这个", "那个", "这种", "那种", "上面", "上述", "刚才", "这类", "那类", "这些", "那些", "同样的", "类似的情况")
PROPOSE_MAX = 5
LLM_TIMEOUT = 40.0
_CHAT_KW: dict[str, Any] = {"temperature": 0.0, "response_format": {"type": "json_object"}}

TERMS_SYSTEM = """你帮「制程问题查询助手」定按文字找单时用哪些说法。只输出一个 JSON 对象：{"terms": ["说法", …]}，不要别的文字。
- 任务「挑说法」：从【候选说法】里挑出与【用户说的】意思相同的说法。只能原样抄候选里的说法，可以一个都不挑；不要挑意思更宽的（用户说「喇叭」时不挑「音频」「声音」）。
- 任务「提说法」：为【用户说的】提 2 到 5 个意思相同、问题单上常见的写法，如「换料」→ 换料、更换物料、替换物料。中文说法至少 2 个字；整个说法当一个词组，不要拆成更短的词（「电池卡扣」不要提「卡扣」「电池」）。
- 只写说法本身，不写解释。"""


@dataclass
class TermPlan:
    """一步文字查找怎么找。`probes` 交沙箱按词匹配；`semantic` 是按意思一路（None 表示不走）。"""

    mode: str
    #: 涉及某个话题：分「问题本身涉及」「处理中提到」两组
    grouped: bool = False
    probes: list[dict[str, Any]] = field(default_factory=list)
    #: 问做法又说了现象：两边都命中的才列入
    intersect: bool = False
    #: {"query": 检索问句, "codes": 栏目代号或 None, "kind": "third" | "sim", "from": "cond" | "approach"}
    semantic: dict[str, Any] | None = None
    #: 给「可能相关」判断用的一句话：话题的说明，或「涉及 X 的问题」
    description: str = ""
    #: 本次用的说法（回答与统计口径里列出）；做法另列
    used: list[str] = field(default_factory=list)
    used_approach: list[str] = field(default_factory=list)
    #: 回答里怎么称呼：「与非接有关」的「非接」；问做法时的做法
    label: str = ""
    approach: str = ""
    #: 在哪些文字里找（统计口径）
    where: str = ""
    #: 关键词「和」「或」
    logic: str = "或"
    #: 说法里有模型挑的或提的（回答里提示可以增减说法）
    by_model: bool = False
    #: 话题本身的话题、比话题小时所在的话题（「按整个话题找」按钮）
    topic: Topic | None = None
    scope: str | None = None
    #: 本域没有点名的栏目：{域名: [栏目名]}，该域不计入
    missing: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: 用户自己给的词（关键词、点名字段里引号给的词）：不套说法清单、不按意思补
    user_words: bool = False
    #: 说法清单「说明」里讲本次带 ＊ 说法的条目：判断「可能相关」时交给模型（`topic_terms.md`「怎么读」）
    guides: list[str] = field(default_factory=list)
    #: 用户问的就是「说明」里点名的那种问法（问「漏电的问题」）时那一条怎么判：回答在所用说法之后照写
    asked_rule: str = ""


def term(text: str, amb: bool = False) -> dict[str, Any]:
    """沙箱匹配用的一个说法：中文说法（含夹带英文的）去掉全部空白，纯英文缩写只归一化（`stats/lib/textmatch.py`）。"""
    raw = str(text).strip()
    cjk = has_cjk(raw)
    return {"raw": raw, "key": compact(raw) if cjk else tn_normalize(raw), "cjk": cjk, "amb": amb}


def _dedupe(terms: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t in terms:
        if t["key"] and t["key"] not in out:
            out[t["key"]] = t
    return list(out.values())


# ---------------------------------------------------------------------------- 栏目


@dataclass(frozen=True)
class Fields:
    codes: list[str]
    columns: list[str]
    titles: list[str]
    unknown: list[str]


def _field_key(text: str) -> str:
    return compact(re.sub(r"[「」『』\"'“”]", "", str(text)))


def resolve_fields(names: Sequence[str]) -> Fields:
    """点名的栏目 → 分段表的栏目代号（比对范围内）、文字表的列（比对范围外）。先找名称完全相同的，再找包含的；
    只说「处理步骤」指比对范围里的处理步骤，「处理步骤意见」指文字表那一列（总述「点名字段时怎么找」）。

    包含的先找比对范围里的栏目，再找文字表的列：「原因」是原因分析，不是国内的原因分类说明；「描述」是比对范围里的
    问题描述（按词、按意思都找），不是文字表的同名列（只按词找）。"""
    seg = {code: {_field_key(t) for t in titles.values()} for code, titles in landed.seg_fields().items()}
    cols = {c.name: _field_key(c.display) for c in landed.text_columns()}
    codes, columns, titles, unknown = [], [], [], []
    for name in names:
        key = _field_key(name)
        if not key:
            continue
        hit_codes = [c for c, ts in seg.items() if key in ts][:1]
        hit_col = None if hit_codes else next((c for c, d in cols.items() if d == key), None)
        if not hit_codes and hit_col is None and len(key) >= 2:
            # 包含的可能不止一个（「改善」是改善建议与改善措施）：都算
            hit_codes = [c for c, ts in seg.items() if any(key in t or t in key for t in ts)]
            if not hit_codes:
                hit_col = next((c for c, d in sorted(cols.items(), key=lambda x: -len(x[1])) if key in d), None)
        if hit_codes:
            codes += hit_codes
            titles.append(str(name))
        elif hit_col is not None:
            columns.append(hit_col)
            titles.append(str(name))
        else:
            unknown.append(str(name))
    return Fields(list(dict.fromkeys(codes)), list(dict.fromkeys(columns)), titles, unknown)


def missing_in(fields: Fields) -> dict[str, list[str]]:
    """哪一域没有点名的栏目（该域不计入，总述「通用筛选规则」默认范围）。"""
    seg = landed.seg_fields()
    cols = {c.name: c for c in landed.text_columns()}
    out: dict[str, list[str]] = {}
    for dom in landed.DOMAIN_LABELS:
        # 栏目名取有这一栏的域的叫法（点名的说法与栏目不一一对应：「改善」是两栏）
        lacking = [next(iter(seg[c].values())) for c in fields.codes if c in seg and dom not in seg[c]]
        lacking += [cols[c].display for c in fields.columns if dom not in cols[c].sources]
        if lacking and len(lacking) == len(fields.codes) + len(fields.columns):
            out[dom] = lacking
    return out


# ---------------------------------------------------------------------------- 说法清单


def topic_of(said: str, topics: TopicTerms) -> Topic | None:
    """用户的说法对到哪个话题：去掉括号与尾巴后与话题名相同；或括号里的例子、说法里含的说法同属一个话题。"""
    names, term_topics = normalize.topic_index(topics)
    core = normalize.topic_core(said)
    if core in names:
        return topics.get(names[core])
    inner = re.findall(r"[（(](.*?)[)）]", str(said))
    votes: dict[str, int] = {}
    for part in re.split(r"[、,，/]", "、".join(inner)):
        for name in term_topics.get(normalize.norm(part), ()):
            votes[name] = votes.get(name, 0) + 1
    if votes:
        best = max(votes.values())
        winners = [n for n, k in votes.items() if k == best]
        if len(winners) == 1:
            return topics.get(winners[0])
    hits = [set(ts) for t, ts in term_topics.items() if len(t) >= 2 and t in core]
    if hits:
        common = set.intersection(*hits)
        if len(common) == 1:
            return topics.get(next(iter(common)))
    return None


def _owning(said_terms: Sequence[str], topics: TopicTerms) -> list[Topic]:
    _names, term_topics = normalize.topic_index(topics)
    found: list[str] = []
    for t in said_terms:
        for name in term_topics.get(normalize.norm(t), ()):
            if name not in found:
                found.append(name)
    return [x for x in (topics.get(n) for n in found) if x is not None]


def _in_list(text: str, topics: TopicTerms) -> list[tuple[Topic, bool]]:
    """说法在哪些话题里、在那个话题里是不是带 ＊。"""
    key = normalize.norm(text)
    return [(t, x.ambiguous) for t in topics.topics for x in t.terms if normalize.norm(x.text) == key]


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


async def _ask_model(llm: Any, task: str, said: str, candidates: Sequence[str]) -> list[str] | None:
    """挑说法或提说法：一次模型调用（固定 system，变化的都在 user，§5.6）。出错、超时、格式不对返回 None。"""
    if llm is None:
        return None
    body: dict[str, Any] = {"任务": task, "用户说的": said}
    if candidates:
        body["候选说法"] = list(candidates)
    messages = [{"role": "system", "content": TERMS_SYSTEM},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)}]
    try:
        resp = await asyncio.wait_for(llm.chat(messages, **_CHAT_KW), timeout=LLM_TIMEOUT)
        data = json.loads(_content(resp))
    except Exception as exc:  # noqa: BLE001 —— 模型出错时用退路的说法，异常只进日志
        logger.warning("factory_issue_terms_failed", task=task, error=type(exc).__name__)
        return None
    raw = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]


@dataclass
class Chosen:
    terms: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    label: str
    description: str
    topic: Topic | None
    scope: str
    by_model: bool


async def choose(llm: Any, said: str, scope: str | None, topics: TopicTerms, *, allow_amb: bool) -> Chosen:
    """按用户的说法定一组说法（总述「按哪些说法找」）。`allow_amb` 为假时不用带 ＊ 的说法（措施类栏目）。"""
    scope = scope or normalize.topic_scope(said, topics) or "清单外"
    display = normalize.topic_display(said)
    topic = topic_of(said, topics) if scope in ("话题本身", "比话题小") else None
    if scope == "话题本身" and topic is not None:
        terms = [term(x.text, x.ambiguous) for x in topic.terms if allow_amb or not x.ambiguous]
        return Chosen(_dedupe(terms), [term(x) for x in topic.excluded], topic.name, topic.description,
                      topic, scope, False)
    if scope == "话题本身":
        scope = "清单外"
    core = normalize.topic_core(said)
    if scope == "比话题小":
        _names, term_topics = normalize.topic_index(topics)
        contained = [t for t in term_topics if len(t) >= 2 and t in core]
        owners = _owning(contained, topics)
        candidates = list(dict.fromkeys(x.text for t in owners for x in t.terms))
        picked = await _ask_model(llm, "挑说法", display, candidates)
        allowed = {normalize.norm(c): c for c in candidates}
        chosen = [allowed[normalize.norm(p)] for p in picked or [] if normalize.norm(p) in allowed]
        if picked is None:  # 模型出错：只用用户的说法本身与它恰好是的那个说法
            chosen = [c for c in candidates if normalize.norm(c) == core]
        items = [display, *chosen]
        by_model = picked is not None
        topic = topic if topic is not None else (owners[0] if len(owners) == 1 else None)
    else:
        proposed = await _ask_model(llm, "提说法", display, [])
        kept: list[str] = []
        for p in proposed or []:
            pk = compact(p)
            if has_cjk(p) and len(pk) < 2:
                continue
            if pk != compact(display) and pk in compact(display):
                logger.info("factory_issue_term_dropped", reason="原话的一部分")  # R7，G5 抽查
                continue
            kept.append(p)
        items = [display, *kept[:PROPOSE_MAX]]
        by_model = proposed is not None
    terms, excluded = [], []
    for text in items:
        owners_amb = _in_list(text, topics)
        amb = any(a for _t, a in owners_amb)
        if amb and not allow_amb:
            continue
        terms.append(term(text, amb))
        for t, _a in owners_amb:
            excluded += [term(x) for x in t.excluded]
    if not terms:
        terms = [term(display)]
    return Chosen(_dedupe(terms), _dedupe(excluded), display, f"涉及{display}的问题", topic, scope, by_model)


# ---------------------------------------------------------------------------- 一步的找法


def _probe(name: str, terms: Sequence[dict[str, Any]], *, excluded: Sequence[dict[str, Any]] = (),
           codes: Sequence[str] | None = None, columns: Sequence[str] = (), logic: str = "或",
           stars: bool = False) -> dict[str, Any]:
    return {"name": name, "terms": list(terms), "excluded": list(excluded),
            "codes": None if codes is None else list(codes), "columns": list(columns), "logic": logic,
            "stars": stars}


def _said(value: Any) -> str:
    text = value.get("value") if isinstance(value, dict) else value
    return str(text or "").strip()


def _words(value: Any) -> list[str]:
    return [str(x).strip() for x in schema.as_list(value) if isinstance(x, str) and str(x).strip()]


def _scope_text(fields: Fields) -> str:
    return "、".join(fields.titles) if fields.titles else ""


#: 没点名栏目时「在哪些文字里找」的说法（总述「统计口径说明」文字查找一行：不对用户说「比对范围」）
ALL_SCOPE = "问题现象、问题描述、原因分析、改善措施、处理步骤等文字"
#: 类似问题没点名栏目时的说法：只按意思找，建单时选的问题现象不参与（总述「预设的问题现象只按词找」）
SIM_SCOPE = "问题描述、原因分析、改善措施、处理步骤等文字"
MEASURE_SCOPE = "措施类文字（改善建议、改善措施、预防对策、处理步骤，巴西另有 SQE 跟进结果）"
NEEDS_PREVIOUS = "接不上上一轮"


async def plan(llm: Any, step: dict, topics: TopicTerms, seg: Segmentation) -> TermPlan | base.Ask:
    """一步文字查找的找法。要追问时（现象描述指着上文）返回 `Ask`。"""
    got = await _plan(llm, step, topics, seg)
    if isinstance(got, TermPlan):
        p = step.get("params") or {}
        _attach_guides(got, topics, _said(p.get("topic")) or _said(p.get("approach")))
    return got


def _attach_guides(tp: TermPlan, topics: TopicTerms, said: str) -> None:
    """说法清单「说明」里讲本次带 ＊ 说法的条目交给判断；用户问的正是其中「问『X』：…」那种问法时，记下那一条。"""
    if tp.user_words or tp.mode == "类似问题":
        return
    notes = topics.notes_for(t["raw"] for p in tp.probes for t in p["terms"] if t.get("amb"))
    tp.guides = [n.text for n in notes]
    core = normalize.topic_core(said)
    rule = next((r for n in notes for asked, r in n.asks if core and normalize.topic_core(asked) == core), "")
    tp.asked_rule = rule.rstrip("。")


async def _plan(llm: Any, step: dict, topics: TopicTerms, seg: Segmentation) -> TermPlan | base.Ask:
    p = step.get("params") or {}
    mode = str(p.get("mode") or "")
    ask = str(p.get("ask") or "现象")
    topic = _said(p.get("topic"))
    approach = _said(p.get("approach"))
    phenomenon = _said(p.get("phenomenon"))
    words = _words(p.get("terms"))
    fields = resolve_fields(_words(p.get("fields")))
    first, measure = list(seg.groups["first"]), list(seg.groups["second"])
    notes = [f"『{x}』不是可以按文字查找的栏目" for x in fields.unknown]

    if mode == "类似问题" or not (topic or words or approach):
        said = phenomenon or topic
        if not said:
            return base.Ask("请描述一下要找的问题现象。", [], reason=NEEDS_PREVIOUS, fill=base.FILL_NONE)
        if any(x in said for x in PRONOUNS):
            return base.Ask(f"「{said}」指的是哪一种现象？请把现象描述完整一些。", [], reason=NEEDS_PREVIOUS,
                            fill=base.FILL_NONE)
        codes = fields.codes or None
        return TermPlan(mode="类似问题", semantic={"query": said, "codes": codes, "kind": "sim", "from": "cond"},
                        label=said, where=_scope_text(fields) or SIM_SCOPE, notes=notes,
                        missing=missing_in(fields) if fields.codes else {})

    if mode == "关键词" or (words and mode != "点名字段" and not topic):
        logic = "和" if p.get("logic") == "和" else "或"
        codes = fields.codes if (fields.codes or fields.columns) else None
        probe = _probe("main", [term(w) for w in words], codes=codes, columns=fields.columns, logic=logic)
        return TermPlan(mode="关键词", probes=[probe], used=words, label="、".join(words), logic=logic,
                        where=_scope_text(fields) or ALL_SCOPE, notes=notes, user_words=True,
                        missing=missing_in(fields) if (fields.codes or fields.columns) else {})

    if mode == "点名字段" and (fields.codes or fields.columns):
        missing = missing_in(fields)
        where = _scope_text(fields)
        if words:
            probe = _probe("main", [term(w) for w in words], codes=fields.codes, columns=fields.columns)
            return TermPlan(mode="点名字段", probes=[probe], used=words, label="、".join(words), where=where,
                            notes=notes, missing=missing, user_words=True)
        said = topic or approach
        stars_ok = bool(fields.codes) and not fields.columns and set(fields.codes) <= set(first)
        got = await choose(llm, said, p.get("topic_scope") if topic else None, topics, allow_amb=stars_ok)
        probe = _probe("main", got.terms, excluded=got.excluded, codes=fields.codes, columns=fields.columns,
                       stars=stars_ok)
        semantic = None
        if fields.codes and not fields.columns:
            semantic = {"query": got.description, "codes": list(fields.codes), "kind": "third", "from": "cond"}
        return TermPlan(mode="点名字段", probes=[probe], semantic=semantic, description=got.description,
                        used=[t["raw"] for t in got.terms], label=got.label, where=where, by_model=got.by_model,
                        topic=got.topic, scope=got.scope, notes=notes, missing=missing)

    if ask == "做法":
        said = approach or topic
        got_a = await choose(llm, said, None, topics, allow_amb=False)
        a_probe = _probe("approach", got_a.terms, excluded=got_a.excluded, codes=measure)
        if approach and topic:
            got_t = await choose(llm, topic, p.get("topic_scope"), topics, allow_amb=False)
            t_probe = _probe("main", got_t.terms, excluded=got_t.excluded)
            return TermPlan(mode="做法", probes=[t_probe, a_probe], intersect=True,
                            semantic={"query": got_t.description, "codes": None, "kind": "third", "from": "approach"},
                            description=got_t.description, used=[t["raw"] for t in got_t.terms],
                            used_approach=[t["raw"] for t in got_a.terms], label=got_t.label,
                            approach=got_a.label, where=ALL_SCOPE, by_model=got_t.by_model or got_a.by_model,
                            topic=got_t.topic, scope=got_t.scope, notes=notes)
        description = f"用{got_a.label}处理、解决的问题"
        return TermPlan(mode="做法", probes=[a_probe],
                        semantic={"query": description, "codes": measure, "kind": "third", "from": "cond"},
                        description=description, used_approach=[t["raw"] for t in got_a.terms],
                        approach=got_a.label, label=got_a.label, where=MEASURE_SCOPE, by_model=got_a.by_model,
                        topic=got_a.topic, scope=got_a.scope, notes=notes)

    got = await choose(llm, topic, p.get("topic_scope"), topics, allow_amb=True)
    probe = _probe("main", got.terms, excluded=got.excluded, stars=True)
    return TermPlan(mode="话题", grouped=True, probes=[probe],
                    semantic={"query": got.description, "codes": None, "kind": "third", "from": "cond"},
                    description=got.description, used=[t["raw"] for t in got.terms], label=got.label,
                    where=ALL_SCOPE, by_model=got.by_model, topic=got.topic, scope=got.scope, notes=notes)


def key(step: Mapping[str, Any]) -> str:
    """一步文字查找「找的是什么」（递进筛选认出「就是上一轮那次」用，§10）：找法、说法、栏目与条件原话。"""
    p = step.get("params") or {}
    keep = {k: p.get(k) for k in ("mode", "terms", "logic", "fields", "topic", "phenomenon", "ask", "approach")}
    keep["time"] = [_said(t.get("said")) for t in schema.as_list(p.get("time")) if isinstance(t, dict)]
    keep["filters"] = [[str(f.get("field")), _words(f.get("value"))] for f in schema.as_list(p.get("filters"))
                       if isinstance(f, dict) and not schema.is_ref(f.get("value"))]
    return normalize.norm(json.dumps(keep, ensure_ascii=False, sort_keys=True))
