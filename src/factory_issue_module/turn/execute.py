"""执行与呈现（设计 §4.2 第 6、8、9 步，§4.3 清单与统计两行，§6.4，§8，§9.2、§9.3）。国内 S2；巴西、海外与跨域合并 S3。

- 第 6 步 `prepare()`：每步的域取「用户点的域 ∩ 可查的域」（没点就是可查的全部域），各域适配器名字对库、时间换算
  （已在编排里换好），要查库才知道的追问。几个域一起查时，名称只在某些域对不上（「柯洱斯」只是国内的工厂）的，
  对不上的域不计入并写明，不追问；都对不上才追问。引用前一步结果的条件（`{"ref": "s1.top_values"}`、`within`）到
  执行时再对。
- 第 8 步 `run()`：按顺序执行；`when` 不成立的跳过；每步内各域并行取数，人员、存货、PN 这些各域都取的帧拼成一个，
  然后一次沙箱调用（跨域小计、合计与同名归并在沙箱里做）。取数撞上 `TableDenied` 以拒绝为准，该域改记无权
  （J-P09）；其余取数错误与沙箱失败只让这一段答「这一部分暂时没查到」。
- 第 9 步：每段开头、表格、图、分析段；三域一起时开头先给各域张数与合计，清单每域一张表，统计同名合并成一张表；
  分析段每段一次。统计口径整轮合并放最后，按本段计入的域写；结果为空时代码列出放宽默认读法的选项并预先查好张数
  （默认取前 2 个，总述「结果为空时」）；第 13 条修一次仍不一致时开头写明按什么日期理解，并给另一种理解的按钮。
- 详情与按号查单（S4，`skills/issue_detail.py`、`lookup_numbers.py`）：第 6 步认号，认不出、位数不对时追问；单号
  按前缀定域，无权的域不查。几步详情各给一个问题编号、只问当前状态一类时并成一步按号查单（一号一行合成一张表，
  总述「按编号查单」）；详情引用前一步清单的 `issues`、只要原因或措施时并进清单，清单加「原因与措施」一列
  （设计 §5.3 第 5 条前半）。
- 多轮（S5，设计 §10）：边执行边记 `Turn.record`（每步查了哪些域、换算后的时间、各域张数与结果单 ID、图的数据、
  单独说到的那张单），编排在本轮结束时写进工作区。上一轮是按号查单、本轮在它的结果里筛（「其中已结案的」）时，
  那一步按号查单直接用存下的单 ID，不重查、不再列一遍（§10「递进筛选」）。「这单」写不出单号时用 `focus`。
- 导出（S5，§9.3）：用户明说导出、或某域超过 `export_threshold` 张时，沙箱把该域全部行作为明细帧回传，每域一页
  写成一个文件，链接放在统计口径之后。
- 答后按钮（§9.5，`present/suggestions.py`）：纠偏类（其他理解、按上月同期比、改按结案时间算、放宽与换时间范围、
  这一步自己的选项）代码直出、排在前面；接着问由 `present/moves.py` 列候选、`present/suggest.py` 交模型挑，至多 3 个，
  至多 4 个。模型调用在最后一步算完、还没发它的事件时就开始，与正文分段发出重叠（`_start_suggest`）。
- 文字查找（S6b，`skills/text_search.py`）：条件照清单对库，执行交 `text_search.run_step`；清单、按号查单的问题描述
  一列在文字查找表可用的域换成摘要、导出给全文（`present/summaries.py`，§9.2）。递进筛选里照抄上一轮的文字查找时
  用存下的单 ID（`_use_stored_texts`）。
- 临时统计（S7，`skills/custom_stats.py`）：条件照统计对库，执行交 `custom_stats.run_step`；每轮至多一个，第二个那一段
  只答一句。关掉时、没算出来时答一句并附能力介绍的按钮（`StepOut.handled`：已用业务话说明，整轮没有别的结果时不再
  发整轮失败）。脚本存进工作区 `turn.steps`，重放（质疑重查、换图）照它算、不调模型。
- 执行中的信号（设计 §5.4）由代码执行默认动作：引用的上一步为空时停在这一步；清单、统计、临时统计的一步结果为空
  时只放宽一个条件、并行预查张数，「没有查到单」之后说一句卡在哪个条件上，不为 0 的交答后建议做成按钮
  （`_relax_neighbors`、`relax_note`，决策 2026-11-03「结果为空时放宽一个条件」）；第三组候选太多时的那一句在
  `skills/text_search.py`。
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import time
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd
import structlog
from forge_core.errors import TableDenied
from forge_core.events import Event, EventType
from forge_core.module import ModuleManifest

from factory_issue_module.config.files import AnswerParams, LinkSites
from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.domains import base, brazil, domestic, numbers, overseas, shared
from factory_issue_module.domains.base import Ask, DomainStep
from factory_issue_module.domains.shared import MasterData
from factory_issue_module.plan import clarify, names, normalize, schema, timespan
from factory_issue_module.plan.planner import PlanResult
from factory_issue_module.plan.timespan import Span
from factory_issue_module.config.files import Segmentation, TopicTerms
from factory_issue_module.present import caliber as cal
from factory_issue_module.present import (
    charts,
    columns,
    export,
    insights,
    layout,
    links,
    moves,
    narrative,
    suggest,
    suggestions,
    summaries,
    tables,
)
from factory_issue_module.skills import aggregate, custom_stats, issue_detail, list_issues, lookup_numbers, text_search
from factory_issue_module.stats import runner
from factory_issue_module.text import terms as text_terms
from factory_issue_module.turn import errors, greeting, workspace
from factory_issue_module.turn.gate import DomainAccess

logger = structlog.get_logger(__name__)

EXECUTABLE = ("list_issues", "aggregate", "issue_detail", "lookup_numbers", "text_search", "custom_stats")
#: 按条件取数的两种（`run_step`；放宽选项预查张数跑这两种，临时统计只跑它的沙箱 ①）
CONDITIONAL = ("list_issues", "aggregate")
#: 第 6 步按条件对库的几种（文字查找的条件与清单同一套，S6b；临时统计与统计同一套，S7）
RESOLVED = (*CONDITIONAL, "text_search", "custom_stats")
#: 几步详情只问这几项（或没说要看什么）时并成一步按号查单
STATUS_ASPECTS = ("当前状态", "当前责任人", "概况", "跟进人")
ADAPTERS: dict[Domain, Any] = {Domain.DOMESTIC: domestic, Domain.BRAZIL: brazil, Domain.OVERSEAS: overseas}
_BY_LABEL = {d.label: d for d in DOMAINS}
#: 有结果、只说「最近」时另给的两个时间范围（总述「时间说法怎么换算」）
RECENT_WORDS = ("最近", "近期", "近来", "最近一段时间")
RELAX_OPTIONS = ("近 90 天", "今年")
#: 结果为空时只放宽一个条件，至多试几种；哪几种问法试（总述「结果为空时」，决策 2026-11-03）
RELAX_MAX = 4
RELAX_SKILLS = ("list_issues", "aggregate", "custom_stats")
#: 本域算不了的指标在说明里怎么说
_METRIC_ABSENT = {"费用美元": "费用", "费用雷亚尔": "费用", "扣款": "扣款费用", "停线时长": "停线重启时间"}


@dataclass
class Turn:
    """本轮执行要用的东西。"""

    ctx: Any
    manifest: ModuleManifest
    access: DomainAccess
    master: MasterData
    resolver: base.Resolver
    answer: AnswerParams
    query: str
    today: date
    result: PlanResult
    entities: Mapping[str, Sequence[str]]
    #: 本环境 INFO 站点地址（模块配置 `link_sites.toml`）；没配时问题编号不带链接
    sites: LinkSites | None = None
    #: 本轮的执行记录，编排在本轮结束时写进工作区（§10）
    record: workspace.TurnRecord = field(default_factory=workspace.TurnRecord)
    #: 上一轮取过数时 `turn` 的记录与 `results` 里存下的单 ID（递进筛选）、`focus`（「这单」）；读不到为 None
    previous_turn: Mapping[str, Any] | None = None
    previous_results: Mapping[str, Any] | None = None
    focus: Mapping[str, Any] | None = None
    #: 文字查找的说法清单与比对范围（模块配置 `topic_terms.md`、`segmentation.toml`，编排每轮读一次）；None 时用内置默认
    topics: TopicTerms | None = None
    seg: Segmentation | None = None
    #: 上一轮存下的临时统计脚本（[{describe, script}]，`workspace.stored_scripts`）：要算的一样时照它算，不调模型
    scripts: Sequence[Mapping[str, str]] = ()
    #: 本轮由追问选项直填、按地区说法选了其中几家的（`workspace.Filled.scopes`）：与 `resolver.used` 一起写进
    #: `turn.steps`，下一轮「另外的」照它查（G43）
    scopes: Sequence[Mapping[str, Any]] = ()
    #: 最近几轮对话（`conversation_messages`，答后建议给模型看）与工作区 `suggest`（去重、下一张，§9.5）
    history: Sequence[Mapping[str, Any]] = ()
    suggest_state: Mapping[str, Any] | None = None


@dataclass
class StepRun:
    step: dict
    sid: str
    skill: str
    domains: list[Domain]
    denied: list[Domain]
    spans: list[Span]
    dsteps: dict[Domain, DomainStep] = field(default_factory=dict)
    #: 条件引用了前一步的结果，到执行时再对库
    deferred: bool = False
    #: 按号查单：认好的号；详情：计划里写的单号（引用前一步的到执行时再取）
    numbers: list[Any] = field(default_factory=list)
    targets: list[Any] = field(default_factory=list)
    #: 第 5 条前半：这一步详情并进了前一步的清单（不单独成段）；清单要加「原因与措施」一列
    merged: bool = False
    add_reasons: bool = False
    #: 递进筛选：这一步按号查单（或文字查找）就是上一轮那次，只给后一步提供范围，直接用工作区存下的单 ID
    #: （{域: {ids, numbers}}）；文字查找另带上一轮用的说法（再往下一轮还能接着用）
    stored: dict[str, Any] | None = None
    stored_terms: list[str] | None = None


def _asked(step: dict) -> list[Domain]:
    raw = (step.get("params") or {}).get("domains")
    value = raw.get("value") if isinstance(raw, dict) else raw
    labels = [str(x) for x in schema.as_list(value)]
    picked = [_BY_LABEL[x] for x in labels if x in _BY_LABEL]
    return picked or list(DOMAINS)


def _uses_refs(step: dict) -> bool:
    p = step.get("params") or {}
    if schema.is_ref(schema.unwrap_ref(p.get("within"))):
        return True
    return any(isinstance(f, dict) and schema.is_ref(f.get("value")) for f in schema.as_list(p.get("filters")))


def _ref_gaps(step: dict, refs: Mapping[str, Any]) -> list[str]:
    """本步引用前一步结果的条件里，前一步没给出取值的条件名（前一步没有可以排名的取值、没算出来或没执行）。

    各域对库时取值为空的条件会被跳过，这一步就成了不带这个条件、查全部（「问题最多的机型的单」列出全部机型的单），
    所以在执行之前拦下，停在这一步（设计 §8「一问多段」：引用的 `top1` 为空时写明并停在这一步）。"""
    gaps: list[str] = []
    for f in schema.as_list((step.get("params") or {}).get("filters")):
        if not isinstance(f, dict) or not schema.is_ref(f.get("value")):
            continue
        if not base.values_of(refs.get(f["value"]["ref"], [])):
            name = "、".join(str(x) for x in schema.as_list(f.get("field")) if x) or "条件"
            if name not in gaps:
                gaps.append(name)
    return gaps


def _ref_gap_out(gaps: Sequence[str], later_depends: bool) -> StepOut:
    """前一步没给出取值：写明并停在这一步，不取数（见 `_ref_gaps`）。"""
    tail = "这一步和后面依赖它的步骤都不再查" if later_depends else "这一步不再查"
    out = StepOut(ok=True, empty=True, stopped=True)
    out.events.append(Event.delta(f"前一步没有得出可以承接的{'、'.join(gaps)}，{tail}。"))
    return out


def _later_depends(later: Sequence[StepRun]) -> bool:
    """后面的步骤里有没有引用前面结果的（条件引用前一步的取值，或详情引用前一步的单）。"""
    return any(schema.is_ref(f.get("value")) for s in later for f in
               schema.as_list((s.step.get("params") or {}).get("filters")) if isinstance(f, dict)) or any(
        schema.is_ref(issue_detail.issue_value(s.step)) for s in later if s.skill == "issue_detail")


def _group_by(step: dict) -> list[str]:
    return [str(g) for g in schema.as_list((step.get("params") or {}).get("group_by"))]


def _blind(d: Domain, failed: set[str]) -> set[str]:
    """本域视图里靠没取到的主数据才写得出来的列：取不到时这些列会被写成「未填」「未识别机型」（设计 §14）。"""
    return {col for col, label in ADAPTERS[d].MASTER_USES.items() if label in failed}


def _domain_needs(run: StepRun, d: Domain, got: DomainStep, failed: set[str]) -> None:
    """本域要额外取的帧，以及本域整域不计入的维度、指标（总述「通用筛选规则」默认范围）。

    清单要的列、分组用的维度靠的主数据没取到时，这一域这一段答「这一部分暂时没查到」（`unavailable`）。
    """
    A = ADAPTERS[d]
    blind = _blind(d, failed)
    if run.skill == "custom_stats":  # 输入帧的列都要取（§5.5）；靠没取到的主数据才写得出来的列不进帧，不整段放弃
        got.needs |= set(A.CUSTOM_NEEDS)
        return
    if run.skill in ("list_issues", "text_search"):
        if run.skill == "text_search":  # 表格的列（问题编号、机型、问题描述，或用户点名的列）
            keys = [k for k in text_search.table_keys(run.step, False)[0] if not k.startswith("_")]
        else:
            keys, _missing = list_issues.columns_for(run.step)
        dkeys, _absent = list_issues.domain_keys(keys, d, A.KEY_ALIAS)
        got.needs |= list_issues.needs(dkeys, run.step, A.COLUMN_NEEDS, A.SORT_NEEDS) | set(A.INSIGHT_NEEDS)
        got.unavailable = got.unavailable or bool(blind & set(dkeys))
        return
    group_by = _group_by(run.step)
    dims, missing, more = A.dims(group_by, aggregate.basis_of(run.step))
    got.needs |= more | set(A.INSIGHT_NEEDS)
    got.unavailable = got.unavailable or bool(blind & {str(x.get("col")) for x in dims})
    if group_by and not dims and not got.excluded:
        got.excluded.append(f"{d.label}不能按{'、'.join(missing)}统计，{d.label}未计入")
    elif missing:
        got.notes.append(f"{d.label}不能按{'、'.join(missing)}统计")
    metrics = aggregate.metrics_for(run.step)
    lacking = aggregate.unsupported(metrics, A.TRAITS)
    special = [m for m in metrics if m not in aggregate.BASIC_METRICS and m != "合计不良率"]
    what = "、".join(dict.fromkeys(_METRIC_ABSENT.get(m, m) for m in lacking))
    if special and set(special) <= set(lacking) and not got.excluded:
        got.excluded.append(f"{d.label}没有{what}，{d.label}未计入")
    elif lacking:
        got.notes.append(f"{d.label}没有{what}，这一项未计入")
    got.needs |= {A.METRIC_NEEDS[m] for m in metrics if m in A.METRIC_NEEDS}


def _resolve(run: StepRun, T: Turn, refs: Mapping[str, Any]) -> Ask | None:
    """对库：把本步的条件交各域适配器（第 6 步）；需要追问时返回追问。"""
    R = base.Resolver(**{**T.resolver.__dict__, "refs": refs})
    results: list[tuple[Domain, DomainStep | Ask]] = [(d, ADAPTERS[d].resolve(run.step, run.spans, R))
                                                      for d in run.domains]
    asks = [(d, g) for d, g in results if isinstance(g, Ask)]
    if asks:
        oks = [d for d, g in results if not isinstance(g, Ask)]
        hard = [(d, a) for d, a in asks if a.missing is None]
        if hard or not oks:
            if not hard:
                return asks[0][1]
            d0, a0 = hard[0]
            if len(run.domains) == 1 or a0.reason == base.ME_UNKNOWN_REASON:  # 认不出当前用户与哪个域无关
                return a0
            soft = [f"{d.label}{a.missing}" for d, a in asks if a.missing is not None]
            head = "，".join(soft) + "。" if soft else ""
            return Ask(head + d0.label + a0.question, a0.options, a0.reason, said=a0.said, fill=a0.fill)
        results = [(d, DomainStep(domain=d, excluded=[f"{d.label}{g.missing}，{d.label}未计入"])
                    if isinstance(g, Ask) else g) for d, g in results]
    within = schema.unwrap_ref((run.step.get("params") or {}).get("within"))
    for d, got in results:
        assert isinstance(got, DomainStep)
        if schema.is_ref(within):
            issues = refs.get(within["ref"]) or {}
            ADAPTERS[d].within(got, (issues.get(d.label) or {}).get("ids", []) if isinstance(issues, dict) else [])
        if not got.excluded:
            _domain_needs(run, d, got, T.master.failed)
        run.dsteps[d] = got
    return None


def _named(step: dict) -> list[Domain] | None:
    """用户点了的域；没点时为 None（`_asked` 没点时给全部域）。"""
    raw = (step.get("params") or {}).get("domains")
    value = raw.get("value") if isinstance(raw, dict) else raw
    picked = [_BY_LABEL[str(x)] for x in schema.as_list(value) if str(x) in _BY_LABEL]
    return picked or None


def merge_details(plan: dict) -> dict:
    """几步详情各给一个问题编号、只问当前状态一类（或没说要看什么）时，并成一步按号查单：一号一行合成一张表
    （总述「按编号查单」一次给多个号；对照集 XC-005、M-03 两种写法都判对，执行出来是同一张表）。"""
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    if len(steps) < 2 or any(s.get("skill") != "issue_detail" or s.get("when") for s in steps):
        return plan
    raws: list[str] = []
    for s in steps:
        value = issue_detail.issue_value(s)
        if schema.is_ref(value) or not all(a in STATUS_ASPECTS for a in issue_detail.aspects_of(s)):
            return plan
        raws += [str(x) for x in schema.as_list(value)]
    logger.info("factory_issue_details_merged", steps=len(steps))
    return {**plan, "steps": [{"id": "s1", "skill": "lookup_numbers", "when": None,
                               "params": {"numbers": [{"raw": r, "kind_said": None} for r in raws]}}]}


def _fold_reasons(runs: Sequence[StepRun]) -> None:
    """第 5 条前半：详情引用前一步清单的 `issues`、只要原因或措施时并进清单（清单加「原因与措施」一列）。"""
    by_id = {r.sid: r for r in runs}
    for r in runs:
        if r.skill != "issue_detail" or not issue_detail.only_reasons(r.step):
            continue
        value = issue_detail.issue_value(r.step)
        if not schema.is_ref(value):
            continue
        sid, _, out = str(value["ref"]).partition(".")
        src = by_id.get(sid)
        if src is not None and src.skill == "list_issues" and out == "issues":
            src.add_reasons, r.merged = True, True
            logger.info("factory_issue_plan_rule", rule=5, skill="issue_detail", change="并进前一步的清单")


def _with_sid(ask: Ask, sid: str) -> Ask:
    if ask.sid is None:
        ask.sid = sid
    return ask


#: 「这单」「它」一类：规划器没写出单号时按工作区 `focus` 找那张单
_PRONOUNS = ("这单", "这张单", "这张", "该单", "此单", "它", "这个单", "这一单", "上一张", "刚才那张")


def _focus_target(step: dict, T: Turn) -> issue_detail.Target | None:
    """详情的单号写不成单号（空、「这单」），又是沿用上一轮的：取上一轮单独说到的那张单（§10 `focus`）。"""
    focus = T.focus or {}
    dom = _BY_LABEL.get(str(focus.get("domain") or ""))
    if dom is None or not focus.get("number"):
        return None
    raw = (step.get("params") or {}).get("issue")
    value = raw.get("value") if isinstance(raw, dict) else raw
    said = str(value or "").strip()
    from_previous = isinstance(raw, dict) and raw.get("from") == "previous"
    if said and not from_previous and said not in _PRONOUNS:
        return None
    pid = focus.get("id")
    return issue_detail.Target(domain=dom, number=str(focus["number"]),
                               pid=int(pid) if isinstance(pid, int) and not isinstance(pid, bool) else None)


def _previous_lookup(T: Turn) -> dict[str, Any] | None:
    """上一轮的按号查单：(号码原话的集合, 存下的单 ID)；上一轮不是按号查单或没存下时 None。"""
    turn, results = T.previous_turn or {}, T.previous_results or {}
    plan = turn.get("plan") if isinstance(turn.get("plan"), dict) else {}
    for step in plan.get("steps") or []:
        if not isinstance(step, dict) or step.get("skill") != "lookup_numbers":
            continue
        raws = {names.key(x) for x in _raws(step)}
        stored = ((results.get("steps") or {}).get(str(step.get("id"))))
        if raws and isinstance(stored, dict):
            return {"raws": raws, "issues": stored}
    return None


def _raws(step: dict) -> list[str]:
    return [str(x.get("raw") if isinstance(x, dict) else x) for x in
            schema.as_list((step.get("params") or {}).get("numbers")) if x is not None]


def _use_stored_lookups(runs: Sequence[StepRun], T: Turn) -> None:
    """递进筛选（§10）：后一步在一步按号查单的结果里筛（`within` 引用它的 `issues`），那一步的号又与上一轮的按号
    查单相同（本轮用户没要再列一遍）：直接用存下的单 ID，不重查、不单独成段。存下的读不到就照常查。"""
    previous = _previous_lookup(T)
    if previous is None:
        return
    scoped = {str(schema.unwrap_ref((r.step.get("params") or {}).get("within"))["ref"]).partition(".")[0]
              for r in runs if schema.is_ref(schema.unwrap_ref((r.step.get("params") or {}).get("within")))}
    for r in runs:
        if r.skill == "lookup_numbers" and r.sid in scoped and {names.key(x) for x in _raws(r.step)} == previous["raws"]:
            r.stored, r.merged = previous["issues"], True
            logger.info("factory_issue_within_stored", skill="lookup_numbers")


def _scoped(runs: Sequence[StepRun]) -> set[str]:
    """被后一步 `within` 引用的步骤编号。"""
    out: set[str] = set()
    for r in runs:
        within = schema.unwrap_ref((r.step.get("params") or {}).get("within"))
        if schema.is_ref(within):
            out.add(str(within["ref"]).partition(".")[0])
    return out


def _previous_texts(T: Turn) -> dict[str, dict[str, Any]]:
    """上一轮的文字查找：找的是什么（`text/terms.py::key`）→ {issues: 存下的单 ID, terms: 用的说法}。某域存满
    `ID_CAP` 张的不算（存下的不全）。"""
    results = T.previous_results or {}
    texts = results.get("texts") if isinstance(results.get("texts"), dict) else {}
    steps = results.get("steps") if isinstance(results.get("steps"), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for sid, info in texts.items():
        stored = steps.get(str(sid))
        if not isinstance(info, dict) or not info.get("key") or not isinstance(stored, dict):
            continue
        if any(len((v or {}).get("ids") or []) >= workspace.ID_CAP for v in stored.values() if isinstance(v, dict)):
            continue
        out[str(info["key"])] = {"issues": stored, "terms": list(info.get("terms") or [])}
    return out


def _use_stored_texts(runs: Sequence[StepRun], T: Turn) -> None:
    """递进筛选的文字查找一半（§10）：后一步在一步文字查找的结果里筛，那一步找的东西（找法、说法、栏目、条件原话）
    与上一轮的某一步文字查找相同、域也都在上一轮查过的域里：直接用存下的单 ID，不重找（重跑第三组判断既慢又不
    确定）、不单独成段。存下的读不到就照常找。"""
    previous = _previous_texts(T)
    if not previous:
        return
    scoped = _scoped(runs)
    for r in runs:
        if r.skill != "text_search" or r.sid not in scoped or r.deferred:
            continue
        got = previous.get(text_terms.key(r.step))
        if got is None or not {d.label for d in r.domains} <= set(got["issues"]):
            continue
        r.stored, r.stored_terms, r.merged = got["issues"], got["terms"], True
        logger.info("factory_issue_within_stored", skill="text_search")


def stored_out(run: StepRun) -> StepOut:
    """递进筛选里直接用存下的单 ID 的那一步：只给后一步提供范围，不取数、不成段。"""
    stored = run.stored or {}
    out = StepOut(ok=True)
    out.refs = {f"{run.sid}.issues": stored}
    out.found_any = any(isinstance(v, dict) and v.get("ids") for v in stored.values())
    out.domains = [str(d) for d in stored]
    if run.skill == "text_search":
        out.extra = {"text": {"key": text_terms.key(run.step), "terms": list(run.stored_terms or [])}}
    return out


def prepare(plan: dict, spans: Mapping[str, list[Span]], T: Turn) -> list[StepRun] | Ask:
    """第 6 步：每步的域、名字对库、认号；对不上、认不出就追问，本轮不取数。"""
    runs: list[StepRun] = []
    for step in [s for s in merge_details(plan).get("steps") or [] if isinstance(s, dict)]:
        asked = _asked(step)
        run = StepRun(step=step, sid=str(step.get("id")), skill=str(step.get("skill")),
                      domains=[d for d in asked if T.access.can(d)], denied=[d for d in asked if not T.access.can(d)],
                      spans=spans.get(str(step.get("id")), []))
        if run.skill in RESOLVED:
            run.deferred = _uses_refs(step)
            if not run.deferred:
                ask = _resolve(run, T, {})
                if ask is not None:
                    return _with_sid(ask, run.sid)
        elif run.skill == "lookup_numbers":
            run.numbers = lookup_numbers.numbers_of(step, T.query, _named(step))
            ask = lookup_numbers.ask_of(run.numbers)
            if ask is not None:
                return _with_sid(ask, run.sid)
        elif run.skill == "issue_detail":
            run.deferred = schema.is_ref(issue_detail.issue_value(step))
            if not run.deferred:
                run.targets, problems = issue_detail.literal_targets(step)
                if not run.targets:
                    focus = _focus_target(step, T)
                    if focus is not None:
                        run.targets, problems = [focus], []
                if problems and not run.targets:
                    return Ask("；".join(dict.fromkeys(problems)) + "。", [], reason=numbers.FORMAT_REASON,
                               fill=base.FILL_NONE, sid=run.sid)
        runs.append(run)
    _fold_reasons(runs)
    _use_stored_lookups(runs, T)
    _use_stored_texts(runs, T)
    return runs


def person_names(plan: dict) -> list[str]:
    """计划里按人员筛的取值（第 6 步按姓名取人用）。"""
    out: list[str] = []
    for s in plan.get("steps") or []:
        for f in schema.as_list(((s or {}).get("params") or {}).get("filters")):
            if isinstance(f, dict) and f.get("field") in ("跟进人", "当前责任人", "责任人") and not schema.is_ref(f.get("value")):
                for v in schema.as_list(f.get("value")):
                    text = str(v).strip()
                    out += [text, text.rpartition("的")[2]] if "的" in text else [text]
    return out


# ---------------------------------------------------------------------------- 执行一步


@dataclass
class StepOut:
    events: list[Event] = field(default_factory=list)
    refs: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    empty: bool = False
    found_any: bool = False
    #: 这一步是追问（如手填订单号要用户选）：本轮到此为止，不再给统计口径与按钮
    final: bool = False
    ask: Ask | None = None
    #: 实际取了数的域（工作区 `turn.steps` 记下，重查、换图按它）
    domains: list[str] = field(default_factory=list)
    #: 沙箱给的各段（换图、重查要用；只在不呈现时带回）
    segs: list[dict[str, Any]] = field(default_factory=list)
    #: 清单：表格没列全、已导出（模板按钮「导出全部」看它）
    truncated: bool = False
    exported: bool = False
    #: 要另记进工作区的（文字查找：{"text": {"key": 找的是什么, "terms": 用的说法, "judged": 有没有模型判断的一组}}）
    extra: dict[str, Any] = field(default_factory=dict)
    #: 这一步自己的可点选项（文字查找的最小版按钮；临时统计关掉、没算出来时的能力介绍按钮），排在模板按钮的位置
    buttons: list[dict[str, str]] = field(default_factory=list)
    #: 这一步没有结果、但已经用业务话说明了（临时统计关掉、没算出来、一轮里的第二个）：整轮都没有结果时不再发整轮失败
    handled: bool = False
    #: 引用的前一步没给出取值，这一步没执行、已写明停在这里（`_ref_gaps`）：后面依赖它的步骤不执行，不再另说一句
    stopped: bool = False
    #: 答后建议要看的本步产物（§9.5，`present/moves.py`）：清单、统计的各段（`segs`）；详情给出的单与块
    #: （`tickets`、`shown`）。只在本轮内存里用，不进工作区
    digest: dict[str, Any] = field(default_factory=dict)


def _time_text(run: StepRun) -> str | None:
    items = [t for t in schema.as_list((run.step.get("params") or {}).get("time")) if isinstance(t, dict) and t.get("said")]
    parts = list(dict.fromkeys(s.describe() for s in run.spans if not s.unlimited))  # 合成同一段的只写一次
    if (run.step.get("params") or {}).get("compare") == "时段" and len(run.spans) >= 2:
        ordered = sorted(run.spans[:2], key=lambda s: s.start or date.min)
        late, early = base.period_label(ordered[1]), base.period_label(ordered[0])
        # 汉字与数字之间空一格，同时间说法的写法（CN-025 golden「2025 年全年与 2024 年全年对比」）
        return f"{late}与{' ' if early[:1].isdigit() else ''}{early}对比"
    return "；".join(parts) if parts and items else None


def _put(frames: dict[str, pd.DataFrame], name: str, frame: pd.DataFrame) -> None:
    """几个域都取的帧（人员、存货、PN、主数据）拼成一个再交沙箱，后取的不覆盖先取的（§6.4）。"""
    have = frames.get(name)
    if have is None or have is frame or len(have) == 0:
        frames[name] = frame if have is None or len(have) == 0 else have
        return
    if len(frame):
        frames[name] = pd.concat([have, frame], ignore_index=True)


async def _frames(run: StepRun, T: Turn) -> tuple[dict[str, pd.DataFrame], list[Domain], list[str], list[Domain]]:
    """各域并行取数。返回 (帧, 撞上 TableDenied 的域, 这一段要说明的话, 取到了的域)。"""
    frames: dict[str, pd.DataFrame] = {}
    denied: list[Domain] = []
    notes: list[str] = []
    fetched: list[Domain] = []

    async def one(d: Domain) -> tuple[Domain, Any]:
        try:
            return d, await ADAPTERS[d].fetch(T.ctx, run.dsteps[d], T.master)
        except TableDenied as exc:
            logger.warning("factory_issue_table_denied", domain=d.value, error=type(exc).__name__)
            return d, "denied"
        except base.TooManyRows:
            return d, "too_many"
        except Exception as exc:  # noqa: BLE001 —— 权限配置漂移、spec 缺陷等：这一段答查不到，异常只进日志
            logger.error("factory_issue_fetch_failed", domain=d.value, error=type(exc).__name__,
                         detail=str(getattr(exc, "detail", ""))[:200])
            return d, "failed"

    for d in run.domains:
        if d in run.dsteps and run.dsteps[d].unavailable and not run.dsteps[d].excluded:
            notes.append(f"{d.label}：{errors.SECTION_FAILED}")
    ready = [d for d in run.domains if d in run.dsteps and not run.dsteps[d].unavailable
             and not run.dsteps[d].excluded]
    for d, got in await asyncio.gather(*(one(d) for d in ready)):
        if isinstance(got, dict):
            for name, frame in got.items():
                _put(frames, name, frame)
            fetched.append(d)
        elif got == "denied":
            denied.append(d)
        elif got == "too_many":
            notes.append(f"{d.label}：{errors.TOO_MANY_ROWS}")
        else:
            notes.append(f"{d.label}：{errors.SECTION_FAILED}")
    return frames, denied, notes, fetched


def desc_placeholder(d: Domain, text_ok: Iterable[Domain]) -> str:
    """沙箱里问题描述一列先写什么：本域文字查找表可用时留空，呈现前换成摘要（`present/summaries.py`）；不可用时
    写「暂不可用」（§9.2）。"""
    return "" if d in set(text_ok) else columns.DESC_UNAVAILABLE


def _sandbox_params(run: StepRun, executed: Sequence[Domain], failed: set[str],
                    text_ok: Iterable[Domain] = frozenset()) -> dict[str, Any]:
    ok = set(text_ok)
    return {"domains": [d.label for d in executed],
            # 靠没取到的主数据才写得出来的列：清单的分析事实不按它们分（否则会读成「加工厂全部未填」）
            "blind": {d.label: sorted(_blind(d, failed)) for d in executed},
            "enums": {d.label: ADAPTERS[d].enum_params() for d in executed},
            "desc": {d.label: desc_placeholder(d, ok) for d in executed},
            "names": {d.label: columns.view_columns(d) for d in executed},
            "traits": {d.label: ADAPTERS[d].TRAITS for d in executed},
            "cols": aggregate.COLS,
            "conds": {d.label: s.conds for d, s in run.dsteps.items()},
            "times": {d.label: s.times for d, s in run.dsteps.items()},
            "breakdowns": {d.label: s.breakdowns for d, s in run.dsteps.items() if s.breakdowns}}


def _scope(time_text: str | None) -> str:
    return f"，{time_text}，" if time_text else ""


def _num(raw: Mapping[str, Any], key: str) -> int:
    """沙箱口径里的一个张数（三域一起时沙箱已相加）；没有为 0。"""
    value = raw.get(key)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _seg_domains(seg: dict[str, Any]) -> list[str]:
    return [str(d) for d in seg.get("domains") or [seg.get("domain", "")]]


def _add_caliber(C: cal.Caliber, run: StepRun, seg: dict[str, Any], dims: Sequence[dict[str, Any]],
                 metrics: Sequence[str]) -> None:
    raw = seg.get("caliber") or {}
    # 口径定义按本步计入的全部域写一次（按域分别给的几张表共用一条），张数按本段
    ds = [d.label for d, s in run.dsteps.items() if not s.excluded and not s.unavailable] or _seg_domains(seg)
    basis = aggregate.basis_of(run.step)
    named = seg.get("domain", "") if len(ds) > 1 and not seg.get("cross") else ""
    C.time(cal.time_range(_time_text(run), basis, [tuple(x) for x in raw.get("未计入") or []], named))
    dsteps = [run.dsteps[_BY_LABEL[d]] for d in _seg_domains(seg) if d in _BY_LABEL and _BY_LABEL[d] in run.dsteps]
    for dstep in dsteps:
        for name, value in dstep.echo:
            C.condition(name, value)
        for text in dstep.skipped:
            C.item(text)
    kinds = [k for dstep in dsteps for c in dstep.conds for k, _v in (c.get("items") or [])]
    names = {str(d.get("name")) for d in dims} | ({str(seg["name"])} if seg.get("name") else set())
    overview = seg.get("kind") == "overview"
    if any(k in ("未结案", "已结案") for k in kinds) or "未结案数" in metrics or "结案与否" in names or overview:
        C.item(cal.closed(ds))
        if _num(raw, "生产角色驳回"):
            C.item(cal.rejected(_num(raw, "生产角色驳回")))
        aside = [(x[-2], x[-1]) for x in raw.get("另列") or []]
        if aside:
            C.item(cal.set_aside(aside))
    if "停线中" in kinds or "停线状态" in names or overview:
        C.item(cal.stopped(ds))
        if _num(raw, "停线中且已完成"):
            C.item(cal.stopped_done(_num(raw, "停线中且已完成")))
    if "曾经停线" in kinds:
        C.item(cal.STOPPED_EVER)
    if basis == "结案" or "结案周期" in metrics:
        C.item(cal.close_time(ds))
        if raw.get("结案周期分域"):
            C.item(cal.close_split(ds))
        if _num(raw, "没有结案时间"):
            C.item(cal.no_close_time(_num(raw, "没有结案时间")))
    if "停线时长" in metrics:
        C.item(cal.stop_days(ds))
        if _num(raw, "已重启但没有重启日期"):
            C.item(cal.no_restart_date(_num(raw, "已重启但没有重启日期")))
    if "合计不良率" in metrics:
        C.item(cal.rate(ds))
        excluded = raw.get("不良率不参与（分域）") or {_seg_domains(seg)[0]: raw.get("不良率不参与")}
        for d, n in excluded.items():
            if isinstance(n, int) and n:
                C.item(cal.rate_excluded(n, d, named=len(ds) > 1))
    if any(m in metrics for m in ("费用美元", "费用雷亚尔")):
        C.item(cal.COST)
        if _num(raw, "涉及费用的单"):
            C.item(cal.cost_issues(_num(raw, "涉及费用的单")))
    if "扣款" in metrics:
        C.item(cal.DEBIT)
    if names & {"跟进部门", "跟进人"}:
        C.item(cal.follow(ds))
    if "责任归属部门" in names:
        C.item(cal.resp_dept(ds))
        if "国内" in ds:
            C.item(cal.resp_blank(raw.get("无需定责", 0), raw.get("未定责", 0)))
    if "责任人" in names:
        C.item(cal.responsible(ds))
    if "当前责任人" in names:
        C.item(cal.current(ds))
    if "处理环节" in names:
        C.item(cal.stages(ds))
    if "问题等级" in names:
        C.item(cal.level(ds))
    if seg.get("cross") and seg.get("kind") == "group":
        C.item(cal.merged(seg.get("name")))
    if raw.get("多值归属"):
        C.item(cal.multi(raw.get("各组合计", 0), seg.get("found", 0)))
    title = str(seg.get("title") or "")
    if raw.get("没有" + title) and seg.get("name") != "责任归属部门":
        C.item(cal.without(title, raw["没有" + title]))
    for d in dims:
        n = raw.get("没有" + str(d.get("title")))
        if n and d.get("name") not in ("责任归属部门",) and d.get("title") != title:
            C.item(cal.without(str(d.get("title")), n))
    for d, n in raw.get("样本少") or []:
        C.item(cal.small_sample(str(d), int(n)))


async def _conclude(T: Turn, table_text: str | None, note: str | None, facts: dict[str, Any], fallback: str,
                    time_text: str | None, found: Mapping[str, Any] | None, *,
                    segs: Sequence[Mapping[str, Any]] = (), must: Sequence[str] = (), guide: str | None = None,
                    after: str = "", use_llm: bool = True) -> str:
    """结论：加粗的结论句 + 要点 + 需关注（总述「先给结论」「结论里的要点与需关注的单」）。要点与需关注的单是沙箱
    给的（`found` = 结果里的 `insights`）；结论句与要点由模型照着写、逐句核数，不合格的用模板句（`narrative.write_points`）；
    需关注由程序写（`present/insights.py`）。

    `after`：程序写的、接在结论句后面的话（统计「另有 N 张没填机型」，G87）。`use_llm=False`：结论句与要点都用模板句。"""
    found = found or {}
    facts = {"时间范围": time_text or "不限建单时间", **facts}
    points = list(found.get("points") or [])
    llm = getattr(T.ctx, "llm", None) if use_llm else None
    head, bullets = await narrative.write_points(llm, T.query, table_text, note or None, facts,
                                                 points, T.entities, fallback, must=must, guide=guide)
    if after and head:  # 加粗收尾的「**」后面紧跟汉字不算收尾（CommonMark），隔一个空格
        head = f"{head} {after}"
    focus = list(found.get("focus") or [])
    descs = await insights.describe(T.ctx, focus, segs, T.access.text_search) if focus else {}
    return insights.assemble(head, bullets, insights.focus_block(focus, descs, T.sites))


def _future(run: StepRun) -> str:
    return "，这段时间还没到" if any(s.future for s in run.spans) else ""


def _absent_note(d: Domain, absent: Sequence[str]) -> str:
    """本域没有的列（总述「跨域规则」清单呈现：用户点名的列某域可能没有）。"""
    if d is Domain.BRAZIL and columns.shown("current_people") in absent:
        rest = [a for a in absent if a != columns.shown("current_people")]
        return "巴西不提供当前责任人" + (f"，也没有『{'』『'.join(rest)}』这几项" if rest else "")
    return f"{d.label}没有『{'』『'.join(absent)}』这{'几' if len(absent) > 1 else '一'}项"


_IDS_FRAME = "ids_"


def issues_from_frames(frames: Mapping[str, pd.DataFrame]) -> dict[str, dict[str, list[Any]]]:
    """沙箱经数据帧通道回传的结果单（`ids_<域>`：单 ID、问题编号）→ 引用值 `{域: {ids, numbers}}`。只搬值。"""
    out: dict[str, dict[str, list[Any]]] = {}
    for name, frame in frames.items():
        if not name.startswith(_IDS_FRAME):
            continue
        out[name[len(_IDS_FRAME):]] = {"ids": [int(x) for x in frame["_id"].tolist()],
                                       "numbers": [str(x) for x in frame["_number"].tolist()]}
    return out


def _seg_dims(seg: dict[str, Any], dims: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [d for d in dims if d.get("title") == seg.get("title")] if seg.get("kind") == "group" else list(dims)


async def run_step(run: StepRun, T: Turn, refs: Mapping[str, Any], C: cal.Caliber, notes: list[str],
                   *, present: bool = True, caliber: bool = False) -> StepOut:
    """执行一步清单或统计。`present=False` 只跑到沙箱为止（放宽选项的张数、质疑重查、换图重跑），不写分析、
    不调模型；`caliber` 时另把统计口径记进 `C`（质疑重查要写「当时按什么口径算」）。"""
    out = StepOut()
    label_denied = [d.label for d in run.denied]
    if run.deferred:
        ask = _resolve(run, T, refs)
        if ask is not None:
            out.events.append(Event.delta(f"{ask.question}\n\n"))
            return out
    frames, denied_now, problems, executed = await _frames(run, T)
    if denied_now:
        for d in denied_now:
            T.access = T.access.without(d)
            run.dsteps.pop(d, None)
        label_denied += [d.label for d in denied_now]
    excluded = list(dict.fromkeys(x for d in run.domains if d in run.dsteps for x in run.dsteps[d].excluded))
    C.domains([d.label for d in executed], ([errors.not_counted(label_denied)] if label_denied else []) + excluded)
    head = list(notes)
    if label_denied:
        head.append(errors.not_counted(label_denied))
    head += excluded
    for d in executed:
        head += run.dsteps[d].notes + run.dsteps[d].skipped
    head += problems
    if not executed:
        if head:
            out.events.append(Event.delta("。".join(dict.fromkeys(head)) + "。"))
        out.ok = (bool(label_denied) or bool(excluded)) and not problems
        return out
    P = _sandbox_params(run, executed, T.master.failed, T.access.text_search)
    if present:  # 结论的要点与需关注的单（决策 2026-11-03「结论的要点与需关注的单」）；不呈现时不算
        P["insight"] = insights.params(run.step, T.answer, T.today)
    time_text = _time_text(run)
    keys_by: dict[str, list[str]] = {}
    dims_by: dict[str, list[dict[str, Any]]] = {}
    metrics: list[str] = []
    if run.skill == "list_issues":
        keys, missing = list_issues.columns_for(run.step)
        head += [f"本助手没有『{m}』这一项" for m in missing]
        for d in executed:
            keys_by[d.label], absent = list_issues.domain_keys(keys, d, ADAPTERS[d].KEY_ALIAS)
            if absent:
                head.append(_absent_note(d, absent))
        if "cn_factory" in keys_by.get(Domain.OVERSEAS.label, []):
            head.append(overseas.CN_FACTORY_NOTE)
        P["list"] = {**list_issues.params(run.step, keys_by, T.answer), "export_ok": present}
        # 要导出时沙箱把全部行作为明细帧回传（数据帧通道，不塞进 result）
        outcome = await runner.run(T.ctx, "list", frames, P, return_frames=True)
    else:
        group_by = _group_by(run.step)
        basis = aggregate.basis_of(run.step)
        for d in executed:
            dims_by[d.label] = ADAPTERS[d].dims(group_by, basis)[0]
        if "国内工厂" in group_by and Domain.OVERSEAS in executed:
            head.append(overseas.CN_FACTORY_NOTE)
        metrics = aggregate.metrics_for(run.step)
        bounds = None
        first_dims = next(iter(dims_by.values()), [])
        if run.spans and first_dims and first_dims[0].get("period"):
            sp = run.spans[0]
            bounds = [sp.start.isoformat() if sp.start else None, sp.end.isoformat() if sp.end else None]
        agg, period_bounds = aggregate.params(run.step, dims_by, metrics, [run.dsteps[d] for d in executed],
                                              T.answer, bounds)
        P["agg"], P["period_bounds"] = agg, period_bounds
        # 计入这一步的单作为明细帧回传（工作区存下供质疑重查比对），不放进 result
        outcome = await runner.run(T.ctx, "aggregate", frames, P, return_frames=True)
    out.domains = [d.label for d in executed]
    if not outcome.ok:
        out.events.append(Event.delta("。".join([*dict.fromkeys(head), errors.SECTION_FAILED]) + "。"))
        return out
    res = outcome.result or {}
    out.ok = True
    segs = res.get("segments") or []
    out.empty = all((s.get("found") or 0) == 0 for s in segs)
    out.found_any = not out.empty
    out.truncated = any(s.get("truncated") for s in segs)
    out.digest = {"segs": [{k: s.get(k) for k in ("domain", "kind", "title", "name", "found", "empty", "facts")}
                           for s in segs]}
    out.refs = {f"{run.sid}.{k}": v for k, v in (res.get("refs") or {}).items()}
    out.refs[f"{run.sid}.issues"] = issues_from_frames(getattr(outcome, "frames", None) or {})
    all_dims = [d for dims in dims_by.values() for d in dims]
    if not present:
        out.segs = list(segs)
        if caliber:
            for seg in segs:
                _add_caliber(C, run, seg, _seg_dims(seg, all_dims) if run.skill != "list_issues" else [],
                             metrics)
        return out
    if run.skill == "list_issues":
        text_ok = [d for d in executed if d in T.access.text_search]
        await fill_cells(T, segs, text_ok, reasons=run.add_reasons)
        head += _desc_notes(keys_by, T)
    head += _breakdown_notes(segs)
    # 提示行（决策 2026-11-03「回答骨架与排版」）：结论之上一段；也交写结论的模型看，不让它重复
    out.events += layout.para(head)
    note = layout.sentences(head)
    if run.skill == "list_issues":
        out.events += await _present_lists(run, T, res, segs, time_text, C, note)
        out.exported = await _export_lists(T, res, getattr(outcome, "frames", None) or {}, text_ok)
    else:
        out.events += await _present_aggs(run, T, segs, time_text, C, all_dims, metrics, note, res.get("insights"))
    return out


def _desc_notes(keys_by: Mapping[str, list[str]], T: Turn) -> list[str]:
    """问题描述一列有、而本域文字查找表不可用的域（§9.2，总述「清单默认列」）：开头说明一次。"""
    with_desc = [label for label, keys in keys_by.items() if "desc" in keys]
    lacking = [label for label in with_desc if _BY_LABEL[label] not in T.access.text_search]
    if not lacking:
        return []
    who = "" if len(lacking) == len(with_desc) else "、".join(lacking) + "的"
    return [f"{who}问题描述摘要{columns.DESC_UNAVAILABLE}，其他列照常"]


def _breakdown_notes(segs: Sequence[dict[str, Any]]) -> list[str]:
    """一个说法对上几个部门时，开头写明「按以下几个部门统计：研发一部 2 张、研发二部 1 张」（总述「部门名称怎么对」；
    张数来自沙箱）。几域一起时带域名。"""
    multi = len({str(s.get("domain")) for s in segs}) > 1
    out = []
    for seg in segs:
        for _title, pairs in seg.get("breakdowns") or []:
            head = str(seg.get("domain") or "") if multi else ""
            out.append(f"{head}按以下几个部门统计：" + "、".join(f"{name} {n} 张" for name, n in pairs))
    return out


async def _export_lists(T: Turn, res: Mapping[str, Any], frames: Mapping[str, pd.DataFrame],
                       text_ok: Sequence[Domain] = ()) -> bool:
    """要导出的清单（沙箱已按阈值或用户明说挑好、全部行经数据帧通道回传）：每域一页写成一个文件，问题描述给
    剥净后的全文（§9.2）。链接那句放进 `T.record.exports`，在统计口径之后发（§4.3）。张数取自沙箱（`exported`）。"""
    counts = res.get("exported") or []
    if not any("export_" + str(d) in frames for d, _n in counts):
        return False
    await summaries.fill_exports(T.ctx, dict(frames), text_ok)
    text = await export.save_lists(T.ctx, counts, frames, export.LIST_FILENAME)
    T.record.exports.append(text)
    return text != f"{errors.EXPORT_FAILED}。"


# ---------------------------------------------------------------------------- 清单


async def _present_lists(run: StepRun, T: Turn, res: dict[str, Any], segs: Sequence[dict[str, Any]],
                         time_text: str | None, C: cal.Caliber, note: str) -> list[Event]:
    """结论 → 每域一节：小标题（张数）、表格、表格下面一句（决策 2026-11-03「回答骨架与排版」）。几域时结论整步一次
    （总述「跨域规则」清单呈现）。结论由模型写；只有一两张、模型没写出来时用 `list_issues.conclusion` 的模板句。"""
    multi = len(segs) > 1
    order = list_issues.order_text(run.step)
    sections: list[Event] = []
    described: list[str] = []
    for seg in segs:
        dom = _BY_LABEL.get(seg.get("domain", ""), Domain.DOMESTIC)
        got, table_text = _present_list(run, T, seg, dom, C, multi, order)
        sections += got
        if table_text:
            described.append(table_text)
    fallback = list_issues.conclusion(res, segs, _scope(time_text), _future(run))
    shown = [s for s in segs if not s.get("empty")]
    if multi:
        few = bool(res.get("few_total"))
        # 各域张数在小标题上，不交模型（结论句不逐域报张数）
        facts = {"合计张数": res.get("found_total", 0), **{s["domain"]: s.get("facts") or {} for s in shown}}
    else:
        few = not shown or bool(shown[0].get("few"))
        facts = (shown[0].get("facts") or {}) if shown else {}
    text = fallback
    if described and not few:
        text = await _conclude(T, "；".join(described), note, facts, fallback, time_text, res.get("insights"),
                               segs=segs)
    return [Event.delta(text), *sections]


def _present_list(run: StepRun, T: Turn, seg: dict[str, Any], dom: Domain, C: cal.Caliber, multi: bool,
                  order: str | None) -> tuple[list[Event], str | None]:
    """一域一节。没有单的域：几域一起时原位置一句，只有这一域时由结论说。"""
    _add_caliber(C, run, seg, [], [])
    if seg.get("empty"):
        return ([Event.delta(f"{dom.label}没有查到单。")] if multi else []), None
    head = list_issues.heading(seg, dom.label)
    events = [layout.heading(head),
              tables.event(seg["table"], "", link_ids=seg.get("ids_shown") or None, domain=dom, sites=T.sites)]
    events += layout.para([list_issues.caption(seg, order)])
    return events, tables.describe(head, seg["table"], seg.get("shown"))


# ---------------------------------------------------------------------------- 统计


async def _present_aggs(run: StepRun, T: Turn, segs: Sequence[dict[str, Any]], time_text: str | None,
                        C: cal.Caliber, dims: Sequence[dict[str, Any]], metrics: Sequence[str], note: str,
                        found: Mapping[str, Any] | None = None) -> list[Event]:
    """每个维度：结论 → 每张表一节（小标题写合计或总数、表、图）。同一维度按域分别给的几张表（处理环节、状态）共用
    一段结论（决策 2026-11-03「回答骨架与排版」）。结论由模型写，问「哪个最多」时第一名（并列的全部）必须点到；
    模型没写出来、只有概况一行时用 `aggregate.opening` 的模板句。要点与需关注的单（`found`，沙箱给的）只在第一段
    结论里给一次（一样信息只在一处说，决策 2026-11-03「结论的要点与需关注的单」）。"""
    pending = dict(found or {})
    events: list[Event] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for seg in segs:
        groups.setdefault(f"{seg.get('kind')}:{seg.get('title')}", []).append(seg)
    p = run.step.get("params") or {}
    ranking = bool(p.get("ranking") or p.get("top"))
    for members in groups.values():
        sections: list[Event] = []
        described: list[str] = []
        openings: list[str] = []
        facts: dict[str, Any] = {}
        must: list[str] = []
        #: 「另有 N 张没填机型」那句（G87）：程序写在结论句后面，也作【说明】交写结论的模型，免得它再写一遍
        blank_lines: list[str] = []
        #: 每段都只有「未填」一类、没有可以排名的取值：结论句用模板句，不调模型（免得它把「未填」说成第一）
        only_blank = True
        for seg in members:
            got, narr, opening = _present_agg(run, T, seg, time_text, C, dims, metrics)
            sections += got
            openings.append(opening)
            if narr is not None:
                described.append(narr[0])
                facts = narr[1] if len(members) == 1 else {**facts, seg.get("domain", ""): narr[1]}
                if ranking:
                    must += [str(x) for x in (seg.get("facts") or {}).get("第一") or []]
                only_blank = only_blank and bool((seg.get("unranked") or {}).get("only"))
            label = str(seg.get("domain") or "") if len(members) > 1 else ""
            line = aggregate.unranked_note(seg, label, ranking)
            if line:
                blank_lines.append(line)
        fallback = layout.sentences(openings)
        extra = layout.sentences(blank_lines)
        text = layout.sentences([fallback, extra])
        if described:
            text = await _conclude(T, "；".join(described), layout.sentences([note, extra]), facts, fallback,
                                   time_text, pending, must=list(dict.fromkeys(must)), after=extra,
                                   use_llm=not only_blank)
            pending = {}
        events += [Event.delta(text), *sections]
    return events


def _present_agg(run: StepRun, T: Turn, seg: dict[str, Any], time_text: str | None, C: cal.Caliber,
                 dims: Sequence[dict[str, Any]], metrics: Sequence[str]
                 ) -> tuple[list[Event], tuple[str, dict[str, Any]] | None, str]:
    """一张表一节。返回 (这一节的事件, 交写结论的模型看的 (表格说明, 事实), 模板句)。"""
    scope = _scope(time_text)
    label = str(seg.get("domain") or "")
    if seg.get("kind") == "group":
        dims = [d for d in dims if d.get("title") == seg.get("title")]
    _add_caliber(C, run, seg, dims, metrics)
    if (seg.get("found") or 0) == 0 and seg.get("kind") != "compare":
        return [], None, f"{label}{scope}没有查到单{_future(run)}"
    if seg.get("kind") == "group" and not (seg.get("table") or {}).get("rows"):
        return [], None, f"{label}{scope}共 {seg.get('found', 0)} 张，没有可以按{seg.get('title')}统计的单"
    suffix = f"：{time_text}" if time_text else ""
    title = f"{label}按{seg.get('title')}统计{suffix}" if seg.get("kind") == "group" else f"{label}统计{suffix}"
    head = aggregate.heading(seg, label)
    events = [layout.heading(head)]
    if seg.get("table"):
        events.append(tables.event(seg["table"], ""))
    events += layout.para([aggregate.caption(seg)])
    if seg.get("bins"):
        events += [layout.heading(f"{label}结案周期分档"), tables.event(seg["bins"], "")]
    item = chart_item(seg, dims, f"{label}结案周期分档{suffix}" if seg.get("bins") else title)
    if item is not None:
        T.record.charts.append(item)
        user_chart = (run.step.get("params") or {}).get("chart")
        events += chart_events(T, item, user_chart if isinstance(user_chart, str) else None)
    events += _rate_lists(seg, T, suffix)
    opening = aggregate.opening(seg, label, scope, tie=False)
    if seg.get("kind") == "overview" and not seg.get("cross") and not (seg.get("facts") or {}).get("按问题类型"):
        return events, None, opening
    return events, (tables.describe(head, seg.get("table") or {}, seg.get("groups")), seg.get("facts") or {}), opening


def seg_chart_item(run: StepRun, seg: dict[str, Any]) -> dict[str, Any] | None:
    """重跑出来的一段（不呈现）的图数据，标题与呈现时相同（换图重跑用）。"""
    label = str(seg.get("domain") or "")
    time_text = _time_text(run)
    suffix = f"：{time_text}" if time_text else ""
    if seg.get("bins"):
        title = f"{label}结案周期分档{suffix}"
    elif seg.get("kind") == "group":
        title = f"{label}按{seg.get('title')}统计{suffix}"
    else:
        title = f"{label}统计{suffix}"
    return chart_item(seg, [], title)


def chart_item(seg: dict[str, Any], dims: Sequence[dict[str, Any]], title: str) -> dict[str, Any] | None:
    """一段的图数据（沙箱产出的行原样）：本轮画图用，也存进工作区 `charts` 给换图用（§4.3 `rerender`）。"""
    chart = seg.get("chart") or {}
    rows = chart.get("rows") or []
    if not rows:
        return None
    dim_name = str(seg.get("name") or next((d.get("name") for d in dims if d.get("title") == seg.get("title")),
                                           chart.get("dimension")))
    series = list(chart.get("series") or [aggregate.COLS["count"]])
    if dim_name in ("加工厂", "跟进部门") and aggregate.COLS["unclosed"] in (rows[0] or {}):
        series.append(aggregate.COLS["unclosed"])
    return {"domains": _seg_domains(seg), "title": title, "dimension": str(chart.get("dimension")),
            "series": series, "rows": rows, "compare": seg.get("kind") == "compare", "name": dim_name,
            "groups": seg.get("groups") or len(rows), "multi": bool(seg.get("multi"))}


def chart_events(T: Turn, item: Mapping[str, Any], user_chart: str | None) -> list[Event]:
    """按图型画一段图；改了图型时附一句原因。分组不到 2 组、用户说不要图时不画（总述「什么时候配图」）。"""
    rows = list(item.get("rows") or [])
    if item.get("custom"):  # 临时统计：模型给的图型只作首选（§5.5）
        kind, why = charts.choose_custom(str(item.get("prefer") or ""), int(item.get("groups") or len(rows)),
                                         user_chart=user_chart)
    elif item.get("compare"):
        kind, why = charts.choose_compare(len(rows), user_chart=user_chart)
    else:
        kind, why = charts.choose(str(item.get("name")), int(item.get("groups") or len(rows)),
                                  multi=bool(item.get("multi")), user_chart=user_chart)
    if kind is None:
        return []
    events = [charts.event(T.ctx.stats, kind, rows, str(item.get("dimension")), list(item.get("series") or []),
                           str(item.get("title") or ""))]
    if why:
        events.append(Event.delta(why))
    return events


def _rate_lists(seg: dict[str, Any], T: Turn, suffix: str) -> list[Event]:
    """海外不良率是单上原文、不汇总：说明一句，逐单列出原文（总述「汇总不良率」）。"""
    lists = dict(seg.get("rate_lists") or {})
    if seg.get("rate_list"):
        lists[str(seg.get("domain"))] = seg["rate_list"]
    events: list[Event] = []
    for label, rl in lists.items():
        dom = _BY_LABEL.get(label, Domain.OVERSEAS)
        more = (f"，共 {rl.get('found', 0)} 张，表格列出最近 {rl.get('shown', 0)} 张"
                if rl.get("truncated") else "")
        events.append(Event.delta(f"\n\n{label}不良率为单上原文（% 与 ‰ 混用），不汇总，下表逐单列出原文{more}。"))
        if rl.get("rows"):
            events.append(tables.event({"columns": rl["columns"], "rows": rl["rows"]}, f"{label}不良率（单上原文）{suffix}",
                                       link_ids=rl.get("ids"), domain=dom, sites=T.sites))
    return events


# ---------------------------------------------------------------------------- 详情与按号查单（S4）


async def fill_cells(T: Turn, segs: Sequence[dict[str, Any]], text_ok: Sequence[Domain], *, desc: bool = True,
                     reasons: bool = False) -> None:
    """表格里问题描述换成摘要、加「原因与措施」一列，两样并行（各自读改写表格行时中间不让出，互不覆盖；
    问题描述那一列在前，加在最后的一列不挪动它的位置）。"""
    jobs = [*([summaries.fill_tables(T.ctx, segs, text_ok)] if desc else []),
            *([_add_reasons(T, segs)] if reasons else [])]
    if jobs:
        await asyncio.gather(*jobs)


async def _add_reasons(T: Turn, segs: Sequence[dict[str, Any]]) -> None:
    """第 5 条前半与文字查找：表格里列出的单（只取这几张，§13）另取叙述原文，沙箱合成「原因与措施」，浓缩成一两句后
    加在表格最后一列（决策 2026-11-04「表格里的原因与措施给摘要」，`present/summaries.py::reason_texts`）。"""
    targets = [issue_detail.Target(domain=_BY_LABEL[str(seg["domain"])], pid=int(pid))
               for seg in segs if not seg.get("empty") and str(seg.get("domain")) in _BY_LABEL
               for pid in seg.get("ids_shown") or []]
    if not targets:
        return
    got, _denied, _failed = await issue_detail.fetch_tickets(T, targets, mode="reasons")
    items = list(got or [])
    shorts = await summaries.reason_texts(T.ctx, [issue_detail.reason_body(x) for x in items])
    texts = {(str(x["domain"]), int(x["id"])): issue_detail.reason_cell(x, T.sites, short)
             for x, short in zip(items, shorts, strict=True)}
    for seg in segs:
        table = seg.get("table")
        if not table or seg.get("empty"):
            continue
        table["columns"] = [*table["columns"], columns.REASONS]
        dom = str(seg["domain"])
        table["rows"] = [[*row, texts.get((dom, int(pid)), errors.SECTION_FAILED)]
                         for row, pid in zip(table["rows"], seg.get("ids_shown") or [], strict=False)]


def _match(ticket: dict[str, Any], target: issue_detail.Target) -> bool:
    if ticket["domain"] != target.domain.label:
        return False
    if target.pid is not None:
        return int(ticket["id"]) == int(target.pid)
    return str(ticket["number"]).upper() == str(target.number or "").upper()


async def _run_detail(run: StepRun, T: Turn, refs: Mapping[str, Any], C: cal.Caliber) -> StepOut:
    out = StepOut()
    more = False
    if run.deferred:
        targets, more = issue_detail.ref_targets(run.step, refs)
        if not targets:
            out.events.append(Event.delta("前一步没有可以看详情的单，这一步不再查。"))
            out.ok = True
            return out
    else:
        targets = list(run.targets)
    named = _named(run.step)
    aspects = issue_detail.aspects_of(run.step)
    lines: list[str] = []
    allowed = [t for t in targets if T.access.can(t.domain)]
    for t in targets:
        if not T.access.can(t.domain):  # 号只可能在一个域、该域无权：只答这一句，不查、不说有没有（J-P05）
            lines.append(errors.DOMAIN_NOT_PERMITTED + "。" if len(targets) == 1 else
                         f"{t.number}：{errors.DOMAIN_NOT_PERMITTED}。")
    if lines:
        out.events.append(Event.delta("\n".join(lines) + ("\n\n" if allowed else "")))
        out.ok = True
    if not allowed:
        return out
    tickets, denied, failed = await issue_detail.fetch_tickets(T, allowed)
    out.domains = list(dict.fromkeys(t.domain.label for t in allowed if t.domain not in denied))
    if tickets is None:
        out.events.append(Event.delta(f"{errors.SECTION_FAILED}。"))
        return out
    items: list[str] = []
    shown: list[dict[str, Any]] = []
    given: list[dict[str, Any]] = []
    blocks_shown: dict[str, list[str]] = {}
    for i, t in enumerate(allowed):
        if i:
            out.events.append(Event.delta("\n\n"))
        if t.domain in denied:
            out.events.append(Event.delta(f"{t.number or ''}：{errors.DOMAIN_NOT_PERMITTED}。".lstrip("：")))
            continue
        if t.domain in failed:
            out.events.append(Event.delta(f"{errors.SECTION_FAILED}。"))
            continue
        ticket = next((x for x in tickets if _match(x, t)), None)
        if ticket is None:
            out.events.append(Event.delta(f"{errors.issue_not_found(str(t.number or ''))}。"))
            out.ok = True
            continue
        keys, notes, labels = issue_detail.blocks_for(ticket, aspects)
        out.events += issue_detail.render(ticket, keys, notes, labels, aspects, T.sites,
                                          issue_detail.prefix_note(t, named))
        items += issue_detail.caliber_items(ticket, keys)
        out.ok = out.found_any = True
        shown.append({"domain": str(ticket["domain"]), "number": str(ticket["number"]), "id": int(ticket["id"])})
        given.append(ticket)
        blocks_shown[str(ticket["number"])] = list(keys)
    if more:
        out.events.append(Event.delta(f"\n\n前一步的结果不止 {issue_detail.DETAIL_MAX} 张，这里只给前 "
                                      f"{issue_detail.DETAIL_MAX} 张的详情，其余可以按单号单独查。"))
    if items:
        C.domains(list(dict.fromkeys(t.domain.label for t in allowed if t.domain not in denied)), [])
        for text in dict.fromkeys(items):
            C.item(text)
    if len(shown) == 1:  # 单独说到的那张单：下一轮「这单」「它」指它（§10 `focus`）
        T.record.focus = shown[0]
    out.refs = {f"{run.sid}.shown": shown}
    out.digest = {"tickets": given, "shown": blocks_shown}
    return out


def _focus_of(issues: Mapping[str, Any]) -> dict[str, Any] | None:
    """按号查单只找到一张单时，它就是单独说到的那张（§10 `focus`）。"""
    hits = [(str(d), item) for d, item in issues.items() if isinstance(item, dict) and item.get("ids")]
    if len(hits) != 1 or len(hits[0][1]["ids"]) != 1:
        return None
    dom, item = hits[0]
    return {"domain": dom, "number": str((item.get("numbers") or [""])[0]), "id": int(item["ids"][0])}


async def _run_lookup(run: StepRun, T: Turn, C: cal.Caliber) -> StepOut:
    out = StepOut()
    if run.stored is not None:  # 递进筛选：上一轮那次按号查单的结果，直接用存下的单 ID
        return stored_out(run)
    events, refs, ok, ask = await lookup_numbers.run_step(T, run.step, run.numbers, C)
    if ask is not None:
        out.ask, out.final, out.ok = _with_sid(ask, run.sid), True, True
        return out
    out.events, out.ok = events, ok
    issues = (refs or {}).get("issues") or {}
    out.refs = {f"{run.sid}.issues": issues, f"{run.sid}.found": (refs or {}).get("found") or {}}
    out.found_any = any(v.get("ids") for v in issues.values() if isinstance(v, dict))
    out.domains = list(dict.fromkeys([*(str(d) for d in issues), *(d.label for n in run.numbers for d in n.possible
                                                                    if T.access.can(d))]))
    focus = _focus_of(issues)
    if focus is not None:
        T.record.focus = focus
    return out


# ---------------------------------------------------------------------------- 整轮


def _opening_notes(T: Turn) -> list[str]:
    """「按 X 理解」：人员条件写了「我」时按哪位员工；第 7 条按库里的取值定的类；第 13 条修一次仍不一致时按什么日期
    理解。"""
    out = []
    me = T.master.me
    if me is not None and T.result.plan is not None and any(names.is_self(n) for n in person_names(T.result.plan)):
        dept = f"（{me.dept}）" if me.dept and me.dept != "未填" else ""
        out.append(f"「我」按当前用户{me.name}{dept}理解")
    for inf in T.result.inferred:
        out.append(f"「{'、'.join(inf.values)}」按{inf.field}理解")
    if T.result.check_errors and T.result.plan is not None:
        for _sid, said, basis, _hit in normalize.basis_mismatches(T.result.plan, T.query):
            out.append(f"「{said}」按{cal.BASIS_TEXT.get(basis, basis)}理解")
    return out


def _alternative_buttons(T: Turn) -> list[dict[str, str]]:
    """第 13 条修一次仍不一致：另一种理解的按钮（「按结案时间算」，问句「改按结案时间算」）。"""
    if not (T.result.check_errors and T.result.plan is not None):
        return []
    alts = [f"按{cal.BASIS_TEXT.get(hit, hit)}算" for _sid, _said, _basis, hit in
            normalize.basis_mismatches(T.result.plan, T.query)]
    return [suggestions.basis_switch(alt) for alt in dict.fromkeys(alts)][:clarify.MAX_OPTIONS]


def can_relax(r: StepRun, out: StepOut) -> bool:
    """这一步结果为空、值得试着只放宽一个条件（总述「结果为空时」）：清单、统计、临时统计；不引用前一步的结果；
    时间段没有整段还没到。"""
    return (out.empty and r.skill in RELAX_SKILLS and not r.deferred and not _uses_refs(r.step)
            and not any(s.future for s in r.spans))


async def _relax_one(r: StepRun, opt: moves.Relax, T: Turn) -> dict[str, Any] | None:
    """预查一种放宽的张数：只跑到沙箱为止（临时统计只跑沙箱 ①，不写脚本）。查不成（追问、出错）返回 None。"""
    if opt.keep_spans:  # 没改时间：用本轮换算好的起止日期（沿用的滚动窗口不因隔天差一天）
        spans: Mapping[str, list[Span]] = {"s1": list(r.spans)}
    else:
        spans, unknown = timespan.plan_spans(opt.plan, T.today)
        if unknown is not None:
            return None
    prepared = prepare(opt.plan, spans, T)
    if isinstance(prepared, Ask) or len(prepared) != 1:
        return None
    one = prepared[0]
    try:
        if one.skill == "custom_stats":
            res = await custom_stats.run_step(one, T, {}, cal.Caliber(), [], mode="count")
        else:
            res = await run_step(one, T, {}, cal.Caliber(), [], present=False)
    except Exception as exc:  # noqa: BLE001 —— 预查出错：这一种不写、不给按钮，本轮照常回答
        logger.warning("factory_issue_relax_failed", kind=opt.kind, error=type(exc).__name__)
        return None
    if not res.ok:
        return None
    count = res.refs.get(f"{one.sid}.count", res.refs.get(f"{one.sid}.total"))
    if not isinstance(count, int) or isinstance(count, bool):
        return None
    got: dict[str, Any] = {"kind": opt.kind, "what": opt.what, "value": opt.value, "count": count,
                           "plan": opt.plan, "key": opt.key}
    sort = (one.step.get("params") or {}).get("sort")
    by_add = not isinstance(sort, dict) or (sort.get("by") in (None, "建单时间") and sort.get("order") != "升序")
    if opt.kind == "unlimited" and one.skill == "list_issues" and count and by_add:
        # 最近建单的一张：清单的结果单按表格的顺序（建单时间从新到旧）回传；只有一个域有单时才写
        hits = [(d, v) for d, v in (res.refs.get(f"{one.sid}.issues") or {}).items()
                if isinstance(v, dict) and v.get("numbers")]
        if len(hits) == 1:
            dom, item = hits[0]
            got["latest"] = {"domain": dom, "number": str(item["numbers"][0]), "id": int(item["ids"][0])}
    return got


async def _relax_neighbors(r: StepRun, T: Turn) -> list[dict[str, Any]]:
    """结果为空：只放宽一个条件的几种（`moves.relax_options`，本会话执行过、推荐过的不查），至多 `RELAX_MAX` 种，
    并行预查张数。返回查成了的（张数可为 0），顺序同 `relax_options`。"""
    seen = {str(x) for x in (T.suggest_state or {}).get("seen") or []}
    options = moves.relax_options(r.step, r.spans, T.today, seen)[:RELAX_MAX]
    if not options:
        return []
    started = time.monotonic()
    got = await asyncio.gather(*(_relax_one(r, opt, T) for opt in options))
    tried = [x for x in got if x is not None]
    logger.info("factory_issue_relax", step=r.skill, tried=[f"{x['kind']}:{x['what']}" for x in tried],
                counts=[x["count"] for x in tried], failed=len(options) - len(tried),
                ms=int((time.monotonic() - started) * 1000))
    return tried


def relax_note(tried: Sequence[Mapping[str, Any]], T: Turn) -> str:
    """「没有查到单」之后那句：只放宽一个条件时各有几张（为 0 的不写），列清单时不限时间那一项另写最近建单的一张；
    都为 0 时写明试过哪几种（总述「结果为空时」）。张数、单号都取自沙箱。"""
    if not tried:
        return ""
    parts = []
    for x in tried:
        if not x["count"]:
            continue
        text = f"{moves.relax_text(x['kind'], x['what'])}有 {x['count']} 张"
        latest = x.get("latest")
        if latest and latest.get("domain") in _BY_LABEL:
            link = links.issue(T.sites, _BY_LABEL[latest["domain"]], latest["number"], latest["id"])
            text += f"，最近建单的一张是 {link}"
        parts.append(text)
    if parts:
        return "只放宽一个条件时：" + "；".join(parts) + "。"
    return "只放宽一个条件也都没有单（试过：" + "、".join(moves.relax_text(x["kind"], x["what"]) for x in tried) + "）。"


def _recent_said(runs: Sequence[StepRun], T: Turn) -> str | None:
    """计划里只说「最近」的那项时间原话（问句里要能找到它）。"""
    for r in runs:
        for t in schema.as_list((r.step.get("params") or {}).get("time")):
            said = str(t.get("said") or "").strip() if isinstance(t, dict) else ""
            if said in RECENT_WORDS and said in T.query:
                return said
    return None


def _recent_notes(runs: Sequence[StepRun], T: Turn) -> list[str]:
    """「最近」不带数字按近 30 天，回答开头写明（总述「时间说法怎么换算」）。"""
    said = _recent_said(runs, T)
    return [f"「{said}」按近 {timespan.DEFAULT_RECENT_DAYS} 天"] if said else []


def _recent_buttons(runs: Sequence[StepRun], T: Turn) -> list[dict[str, str]]:
    """有结果时同样给「近 90 天」「今年」两个可点的选项（同一条口径）；按钮上不带张数。"""
    said = _recent_said(runs, T)
    if said is None:
        return []
    return [{"id": str(i), "name": "换时间范围", "label": f"看{option}", "query": T.query.replace(said, option, 1)}
            for i, option in enumerate(RELAX_OPTIONS, start=1)]


def _month_to_date(run: StepRun, T: Turn) -> tuple[str, dict[str, str] | None] | None:
    """「这个月比上个月」：本月按月初到今天、上个月按完整自然月比，不自动换成同期；回答写明「本月截至今天」，并给
    「按上月同期比」（总述「时间说法怎么换算」）。返回 (开头那句, 按钮)；不是这种比较时 None。

    今天的日子已到或超过上月的天数（10 月 30、31 日对 9 月）时，上月同期就是上月整月，与原来的比法一样，
    不给按钮，开头那句写明（开发者 2026-10-30 定）。"""
    if (run.step.get("params") or {}).get("compare") != "时段" or len(run.spans) < 2:
        return None
    early, late = sorted(run.spans[:2], key=lambda s: s.start or date.min)
    # 只管「这个月比上个月」「本月比上月」这两种说法；写明了年月的（「2026 年 10 月和 9 月比」）不算（S5 评审 A2）
    if not (timespan.is_this_month(late.said) and timespan.is_last_month(early.said)):
        return None
    first = T.today.replace(day=1)
    last_month_end = first - timedelta(days=1)
    if not (late.start == first and late.end == T.today and late.to_today):
        return None
    if not (early.start == last_month_end.replace(day=1) and early.end == last_month_end):
        return None
    head = (f"「{late.said}」按本月截至今天（{late.start:%Y-%m-%d} 至 {late.end:%Y-%m-%d}），"
            f"「{early.said}」按完整的上个月（{early.start:%Y-%m-%d} 至 {early.end:%Y-%m-%d}）比")
    if T.today.day >= last_month_end.day:
        return head + "；今天已到上月月底这一天，上月同期就是上月整月", None
    return head + "，没有换成同期", suggestions.same_period(T.query, early.said)


_SHOWN_OPS = ("是", "属于")


def _said_items(step: dict) -> list[tuple[str, str]]:
    """一步条件里的各项：(from, 用户认得的说法)。取值照计划里照抄的原话，引用前一步的不算。"""
    p = step.get("params") or {}
    out: list[tuple[str, str]] = []
    d = p.get("domains")
    if isinstance(d, dict) and d.get("value"):
        out.append((str(d.get("from") or "user"), "、".join(str(x) for x in schema.as_list(d["value"]))))
    for t in _time_items(step):
        out.append((str(t.get("from") or "user"), f"时间「{t['said']}」"))
    for f in schema.as_list(p.get("filters")):
        if not isinstance(f, dict) or schema.is_ref(f.get("value")) or f.get("value") in (None, "", []):
            continue
        name = str(f.get("column") or f.get("field") or "") if f.get("field") == "其他" else str(f.get("field") or "")
        op = str(f.get("op") or "是")
        value = "、".join(str(x) for x in schema.as_list(f.get("value")))
        out.append((str(f.get("from") or "user"), f"{name} {value}" if op in _SHOWN_OPS else f"{name}{op} {value}"))
    return out


def carried_notes(plan: dict) -> list[str]:
    """沿用了上一轮的条件时，开头写明沿用了哪些、本轮换了哪些（总述「接着上一轮问」）。"""
    kept: list[str] = []
    changed: list[str] = []
    for step in plan.get("steps") or []:
        if not isinstance(step, dict) or step.get("skill") not in RESOLVED:
            continue
        for src, text in _said_items(step):
            (kept if src == "previous" else changed).append(text)
    kept = list(dict.fromkeys(kept))
    if not kept:
        return []
    changed = [x for x in dict.fromkeys(changed) if x not in kept]
    return [f"沿用上一轮的条件：{'、'.join(kept)}" + (f"；本轮换成：{'、'.join(changed)}" if changed else "")]


def _time_items(step: dict) -> list[dict[str, Any]]:
    return [t for t in schema.as_list((step.get("params") or {}).get("time")) if isinstance(t, dict) and t.get("said")]


def _scopes_of(T: Turn) -> list[dict[str, Any]]:
    """本轮直填记下的与按上一轮候选查了的，按（条件名, 原话）去重（各域、重放会各追加一次）。"""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for s in [*T.scopes, *T.resolver.used]:
        out.setdefault((str(s.get("field")), str(s.get("said"))), {
            "field": str(s.get("field")), "said": str(s.get("said") or ""),
            "candidates": [str(c) for c in s.get("candidates") or []],
            "chosen": [str(c) for c in s.get("chosen") or []]})
    return list(out.values())


def _record(T: Turn, r: StepRun, out: StepOut) -> None:
    """记下这一步实际执行了什么（§10 `turn`、`results`）：查了哪些域、换算后的时间连同原话、各域张数与结果单 ID。"""
    if not out.domains:
        return
    T.record.fetched = True
    bases = [str(t.get("basis") or "建单") for t in _time_items(r.step)]
    T.record.steps[r.sid] = {
        "skill": r.skill, "domains": list(out.domains),
        "times": [workspace.span_dict(s, b) for s, b in zip(r.spans, bases, strict=False)],
        "found": dict(out.refs.get(f"{r.sid}.found") or {}),
        # 看原话才定下的判据（巴西「涉及费用」按标记还是按明细）：沿用与重放照用（S5 评审 M1）
        "decided": {k: v for d in r.dsteps.values() for k, v in d.decided.items()}}
    scopes = _scopes_of(T)
    if scopes:  # 地区候选与选定的几家：下一轮「另外的」、重放本轮都照它（G43）
        T.record.steps[r.sid]["scopes"] = scopes
    custom = out.extra.get("custom")
    if isinstance(custom, dict) and custom.get("script"):  # 临时统计：要算什么与那份脚本，重放照它算（S7）
        T.record.steps[r.sid]["custom"] = {"describe": str(custom.get("describe") or ""),
                                           "script": str(custom["script"])}
    issues = out.refs.get(f"{r.sid}.issues")
    if isinstance(issues, dict):
        T.record.results[r.sid] = issues
    text = out.extra.get("text")
    if isinstance(text, dict) and text.get("key"):  # 文字查找用的说法（§10 `results`），递进筛选认「就是那次」
        T.record.texts[r.sid] = {"key": str(text["key"]), "terms": [str(x) for x in text.get("terms") or []]}
    shown = out.refs.get(f"{r.sid}.shown")
    if isinstance(shown, list) and shown:
        by: dict[str, dict[str, list[Any]]] = {}
        for x in shown:
            item = by.setdefault(str(x["domain"]), {"ids": [], "numbers": []})
            item["ids"].append(int(x["id"]))
            item["numbers"].append(str(x["number"]))
        T.record.results[r.sid] = by


# ---------------------------------------------------------------------------- 答后建议（§9.5）


def _done(r: StepRun, out: StepOut) -> moves.Done:
    """这一步执行完的样子，交 `present/moves.py` 列候选。"""
    prefix = r.sid + "."
    return moves.Done(sid=r.sid, skill=r.skill, step=r.step, domains=list(out.domains), found=out.found_any,
                      truncated=out.truncated, exported=out.exported, segs=list(out.digest.get("segs") or []),
                      refs={k[len(prefix):]: v for k, v in out.refs.items() if k.startswith(prefix)},
                      tickets=list(out.digest.get("tickets") or []), shown=dict(out.digest.get("shown") or {}),
                      spans=list(r.spans), deferred=r.deferred or _uses_refs(r.step),
                      relax=list(out.digest.get("relax") or []))


def _dims_ok(dim: str, labels: Sequence[str], basis: str) -> bool:
    """本步各域都能按这个维度统计（换角度的候选，§9.5）。"""
    for label in labels:
        d = _BY_LABEL.get(str(label))
        if d is None:
            continue
        dims, missing, _more = ADAPTERS[d].dims([dim], basis)
        if missing or not dims:
            return False
    return True


@dataclass
class _Suggesting:
    pool: moves.Pool
    seen: set[str]
    task: asyncio.Task | None = None

    def cancel(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()

    async def result(self, n: int) -> list[suggest.Chosen]:
        if self.task is None:
            return []
        if n <= 0:
            self.cancel()
            return []
        try:
            return list(await self.task)[:n]
        except Exception as exc:  # noqa: BLE001 —— 答后建议出了意外不影响本轮回答
            logger.warning("factory_issue_suggest_failed", error=type(exc).__name__)
            return []


def _start_suggest(T: Turn, done: Sequence[moves.Done], said: Sequence[str]) -> _Suggesting:
    """记下本轮执行过的意图键，列候选，有候选时就开始调模型（不等，与正文分段发出重叠）。"""
    asked = [k for d in done for k in moves.asked_keys(d)] + [moves.question_key(T.query)]
    T.record.seen += asked
    state = T.suggest_state or {}
    seen = {str(x) for x in state.get("seen") or []} | set(asked)
    C = moves.Context(today=T.today, access=[d.label for d in DOMAINS if T.access.can(d)],
                      text_access=[d.label for d in DOMAINS if d in T.access.text_search], seen=seen,
                      carry=[c for c in state.get("carry") or [] if isinstance(c, Mapping)], dims_ok=_dims_ok)
    pool = moves.collect(done, C)
    out = _Suggesting(pool=pool, seen=seen)
    if pool.items:
        out.task = asyncio.create_task(suggest.choose(
            getattr(T.ctx, "llm", None), pool, query=T.query, history=T.history, answer="".join(said),
            n=suggestions.MODEL_MAX, seconds=T.answer.suggest_seconds, seen=seen, use_model=T.answer.suggest_model))
        # 用户中途停下、没人再等它时：它自己在 `suggest_seconds` 内结束，这里只把异常取走，免得记成未处理
        out.task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
    return out


def _offer(T: Turn, recs: Sequence[Mapping[str, str]], chosen: Sequence[suggest.Chosen], done: Sequence[moves.Done],
           pool: moves.Pool | None) -> None:
    """发出去的按钮记进 `T.record`：问句与意图键进 `seen`，接着问连同计划进 `offered`；清单、文字查找的轮次把
    没用上的下钻到单留给下一轮（`carry`），统计、临时统计的轮次清空，详情、按号查单的轮次留着（§10）。"""
    by_query = {c.query: c for c in chosen}
    for rec in recs:
        q = str(rec.get("query") or "")
        T.record.seen.append(moves.question_key(q))
        c = by_query.get(q)
        if c is not None:
            T.record.seen.append(c.key)
            T.record.offered.append({"query": q, "key": c.key, "move": c.move, "plan": c.plan})
    keys = {c.key for c in chosen}
    if any(d.skill in ("list_issues", "text_search") for d in done):
        items = pool.items if pool is not None else []
        T.record.carry = [c.to_carry() for c in items if c.carry and c.key not in keys][:workspace.CARRY_MAX]
    elif any(d.skill in ("aggregate", "custom_stats") for d in done):
        T.record.carry = []


def _texts(events: Iterable[Event]) -> list[str]:
    return [str(ev.data.get("text") or "") for ev in events if ev.type is EventType.DELTA]


def plan_alternatives(T: Turn) -> list[dict[str, str]]:
    """计划的 `alternatives`（其他理解）：「换个理解：…」（§9.5，`plan/clarify.py::alternative_recommendations`）。"""
    plan = T.result.plan or {}
    return clarify.alternative_recommendations(plan.get("alternatives"))


async def run(plan: dict, runs: Sequence[StepRun], T: Turn) -> AsyncIterator[Event]:
    """第 8–9 步。执行记录写进 `T.record`；执行时产生的追问（手填订单号）记进 `T.record.ask`、本轮到此为止，
    由编排写 `pending_clarify` 并发 `clarify`。"""
    C = cal.Caliber()
    refs: dict[str, Any] = {}
    for r in runs:  # 递进筛选：上一轮那次按号查单、文字查找直接用存下的单 ID，不单独成段
        if r.stored is not None:
            stored = stored_out(r)
            refs |= stored.refs
            _record(T, r, stored)
    shown = [r for r in runs if (r.skill in EXECUTABLE or r.skill not in ("clarify", "introduce")) and not r.merged]
    multi = len(shown) > 1
    opening = _opening_notes(T) + carried_notes(plan) + _recent_notes(runs, T)
    any_ok, any_empty, any_found = False, False, False
    #: 没有结果的步骤是不是都已用业务话说明了（临时统计关掉、没算出来）；有没说明的，整轮都没结果时照常发整轮失败
    unexplained = False
    custom_used = False
    #: 这一步自己的可点选项（文字查找的最小版、临时统计没算出来时的能力介绍），纠偏类
    step_buttons: list[dict[str, str]] = []
    alternatives: list[dict[str, str]] = []
    month_noted = False
    #: 答后建议（§9.5）：执行完的各步、本轮正文、候选与那次模型调用
    done: list[moves.Done] = []
    said: list[str] = []
    no_conditions = any(r.skill == "list_issues" and list_issues.no_conditions(r.step) for r in shown)
    suggesting: _Suggesting | None = None
    #: 结果为空时的放宽一轮只对第一个为空的步骤做（§5.4）
    relaxed = False
    #: 块与块之间的空行只在这里放（`present/layout.py`，决策 2026-11-03「回答骨架与排版」）
    spaced = layout.Spacer()
    for i, r in enumerate(shown, start=1):
        if multi:
            title = layout.section_title(i, _title(r))
            said.append(title)
            for ev in spaced([Event.delta(title)]):
                yield ev
        when = r.step.get("when")
        if schema.is_ref(when) and not refs.get(when["ref"]):
            for ev in spaced([Event.delta("前一步的条件不成立，这一段不列。")]):
                yield ev
            continue
        if r.skill not in EXECUTABLE:  # 规整与校验之后不会有；万一有，这一段答查不到
            logger.warning("factory_issue_step_not_executable", skill=r.skill)
            for ev in spaced([Event.delta(f"{errors.SECTION_FAILED}。")]):
                yield ev
            unexplained = True
            continue
        notes = opening if i == 1 else []
        if r.skill == "list_issues" and list_issues.no_conditions(r.step):
            notes = [*notes, errors.NO_CONDITION_LIST]
        month = _month_to_date(r, T) if r.skill == "aggregate" and not month_noted else None
        if month is not None:
            notes, month_noted = [*notes, month[0]], True
            if month[1] is not None:
                alternatives.append(month[1])
        dep = _later_depends(shown[i:])
        gaps = _ref_gaps(r.step, refs)
        if gaps:  # 引用的前一步没给出取值：不带这个条件查就成了查全部，停在这一步
            logger.info("factory_issue_ref_gap", sid=r.sid, fields=gaps)
            out = _ref_gap_out(gaps, dep)
        elif r.skill == "issue_detail":
            for ev in spaced(layout.para(notes)):
                yield ev
            out = await _run_detail(r, T, refs, C)
        elif r.skill == "lookup_numbers":
            for ev in spaced(layout.para(notes)):
                yield ev
            out = await _run_lookup(r, T, C)
        elif r.skill == "text_search":
            out = await text_search.run_step(r, T, refs, C, notes)
        elif r.skill == "custom_stats":
            out = await custom_stats.run_step(r, T, refs, C, notes, used=custom_used)
            custom_used = True
        else:
            out = await run_step(r, T, refs, C, notes)
        if out.final:
            # 执行时才产生的追问：编排先写 `pending_clarify` 再发 `clarify`（写进去了按钮问句才能只写选项，§4.4）
            if out.ask is not None:
                T.record.ask = out.ask
            for ev in spaced(out.events):
                yield ev
            return
        if not relaxed and can_relax(r, out):  # 结果为空：只放宽一个条件、预查张数，说一句卡在哪（§5.4）
            relaxed = True
            tried = await _relax_neighbors(r, T)
            note = relax_note(tried, T)
            if note:
                out.events.append(Event.delta("\n\n" + note))
            out.digest["relax"] = [x for x in tried if x["count"]]
        refs |= out.refs
        _record(T, r, out)
        done.append(_done(r, out))
        if r.skill in ("text_search", "custom_stats"):
            step_buttons += list(out.buttons)
        any_ok = any_ok or out.ok
        unexplained = unexplained or (not out.ok and not out.handled)
        any_empty = any_empty or out.empty
        any_found = any_found or out.found_any
        said += _texts(out.events)
        if i == len(shown) and not no_conditions:  # 最后一步：先开始挑答后建议，再发这一步的事件
            suggesting = _start_suggest(T, done, said)
        for ev in spaced(out.events):
            yield ev
        if out.empty and dep:
            if not out.stopped:
                for ev in spaced([Event.delta("这一步没有结果，后面依赖它的步骤不再执行。")]):
                    yield ev
            break
    T.record.found = any_found
    if suggesting is None and not no_conditions:  # 最后一步没走到（条件不成立、依赖的那步没有结果）
        suggesting = _start_suggest(T, done, said)
    if not any_ok:
        T.record.failed = True
        if suggesting is not None:
            suggesting.cancel()
        if unexplained:
            yield Event.error(errors.TURN_FAILED_CODE, errors.TURN_FAILED, fatal=True)
            return
        recs = suggestions.merge(step_buttons)  # 已用业务话说明（临时统计关掉、没算出来）：只附能力介绍的按钮
        if recs:
            yield Event.suggestions(recs)
        _offer(T, recs, [], done, None)
        return
    tail = ([Event.delta(layout.foot(C.text()))] if C.counted else []) + [Event.delta(t) for t in T.record.exports]
    for ev in spaced(tail):
        yield ev
    # 有结果、只说「最近」：另给两个时间范围；结果为空时的放宽走接着问（上面的 `_relax_neighbors`）
    widened = _recent_buttons(runs, T) if any_found and not any_empty else []
    if no_conditions:  # 不带任何条件的清单：不给接着问，给能力介绍的 3 个按钮（§9.4）
        T.record.seen += [k for d in done for k in moves.asked_keys(d)] + [moves.question_key(T.query)]
        step_buttons = greeting.buttons(T.access)
    seen = suggesting.seen if suggesting is not None else set()
    fixed = [r for r in suggestions.merge(alternatives, plan_alternatives(T), _alternative_buttons(T), widened,
                                          step_buttons) if moves.question_key(r["query"]) not in seen]
    chosen: list[suggest.Chosen] = []
    if suggesting is not None:
        chosen = await suggesting.result(min(suggestions.MODEL_MAX, suggestions.MAX_BUTTONS - len(fixed)))
    recs = suggestions.merge(fixed, [suggestions.follow_up(c.query, c.label) for c in chosen])
    if recs:
        yield Event.suggestions(recs)
    _offer(T, recs, chosen, done, suggesting.pool if suggesting is not None else None)


# ---------------------------------------------------------------------------- 重放上一轮（质疑重查、换图，S5）


def restrict_domains(plan: dict, turn: Mapping[str, Any]) -> dict:
    """重放用的计划：每步的域取上一轮实际查过的域（再由 `prepare` 与本轮可查的域取交集，§4.3）。"""
    out = copy.deepcopy(plan)
    steps = (turn or {}).get("steps") or {}
    for step in out.get("steps") or []:
        if not isinstance(step, dict) or step.get("skill") not in (*RESOLVED, "lookup_numbers"):
            continue
        done = [str(d) for d in ((steps.get(str(step.get("id"))) or {}).get("domains") or []) if str(d) in _BY_LABEL]
        if done:
            step.setdefault("params", {})["domains"] = {"value": done, "from": "previous"}
    return out


@dataclass
class Replayed:
    """重放的结果：每步的输出（不呈现），给质疑重查比对、换图重画。"""

    runs: list[StepRun]
    outs: dict[str, StepOut]
    caliber: cal.Caliber


async def add_people(plan: dict, T: Turn) -> None:
    """第 6 步：计划里按人员筛、问句里没有的姓名按姓名补取（规划前只按本轮问句的片段取过）；写了「我」时按工号
    取当前用户，一轮至多一次（决策 2026-11-03「『我』按当前用户查」）。"""
    said = person_names(plan)
    have = {p.name for p in T.master.people}
    missing = [n for n in said if n not in have and not names.is_self(n)]
    if missing:
        T.master.people += await shared.people_by_name(T.ctx, missing, dict(T.master.departments), T.master.failed)
    if not T.master.me_loaded and any(names.is_self(n) for n in said):
        T.master.me = await shared.current_user(T.ctx, dict(T.master.departments), T.master.failed)
        T.master.me_loaded = True


async def replay(plan: dict, spans: Mapping[str, list[Span]], T: Turn, previous_query: str) -> Replayed | Ask:
    """按上一轮的执行计划重新执行一遍，只跑到沙箱为止（不写分析、不调模型）；详情照常给出这张单现在的样子。
    执行记录照常写进 `T.record`（取过数，本轮覆盖 `turn`）。

    对库照上一轮：看原话的判据用上一轮存下的（`Resolver.carried`、`replay`），认号与按钮带回的选项看上一轮的问句
    （本轮问句是「你确定吗」）；计划里的姓名照常按姓名补取（S5 评审 M1、M2）。"""
    T.query = previous_query or T.query
    T.resolver = dataclasses.replace(T.resolver, query=T.query, replay=True)
    await add_people(plan, T)
    prepared = prepare(plan, spans, T)
    if isinstance(prepared, Ask):
        return prepared
    C = cal.Caliber()
    refs: dict[str, Any] = {}
    outs: dict[str, StepOut] = {}
    for r in prepared:
        if r.stored is not None:  # 递进筛选那一步：存下的单 ID 照样给后一步，不比对、不成段
            stored = stored_out(r)
            refs |= stored.refs
            _record(T, r, stored)
            continue
        if r.merged:
            continue
        when = r.step.get("when")
        if schema.is_ref(when) and not refs.get(when["ref"]):
            continue
        if _ref_gaps(r.step, refs):  # 同 `run()`：引用的前一步没给出取值，不去掉条件查全部
            continue
        if r.skill == "issue_detail":
            out = await _run_detail(r, T, refs, C)
        elif r.skill == "lookup_numbers":
            out = await _run_lookup(r, T, C)
            out.events = []
        elif r.skill == "text_search":
            out = await text_search.run_step(r, T, refs, C, [], present=False, caliber=True)
            if out.final:  # 重放时说法定不下来（现象描述指着上文）：按追问处理
                return out.ask if out.ask is not None else Ask(errors.SECTION_FAILED, [])
        elif r.skill in CONDITIONAL:
            out = await run_step(r, T, refs, C, [], present=False, caliber=True)
        elif r.skill == "custom_stats":  # 照存下的脚本算，不调模型（§5.5）
            out = await custom_stats.run_step(r, T, refs, C, [], mode="replay")
        else:
            continue
        refs |= out.refs
        _record(T, r, out)
        outs[r.sid] = out
    return Replayed(runs=list(prepared), outs=outs, caliber=C)


_TITLES = {"list_issues": "清单", "aggregate": "统计", "issue_detail": "单张单详情", "lookup_numbers": "按号查单",
           "text_search": "按文字找单", "custom_stats": "临时统计"}


def _title(r: StepRun) -> str:
    label = _TITLES.get(r.skill, "其他")
    if r.skill in ("issue_detail", "lookup_numbers"):
        return label
    doms = "、".join(d.label for d in r.domains) or "、".join(d.label for d in r.denied)
    return f"{doms}{label}"
