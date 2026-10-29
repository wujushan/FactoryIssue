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
- 其他技能随各自那一片，在那之前这一段答「暂时还答不了」。
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
import structlog
from forge_core.errors import TableDenied
from forge_core.events import Event
from forge_core.module import ModuleManifest

from factory_issue_module.config.files import AnswerParams, LinkSites
from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.domains import base, brazil, domestic, overseas
from factory_issue_module.domains.base import Ask, DomainStep
from factory_issue_module.domains.shared import MasterData
from factory_issue_module.plan import clarify, normalize, schema, timespan
from factory_issue_module.plan.planner import PlanResult
from factory_issue_module.plan.timespan import Span
from factory_issue_module.present import caliber as cal
from factory_issue_module.present import charts, columns, narrative, tables
from factory_issue_module.skills import aggregate, list_issues
from factory_issue_module.stats import runner
from factory_issue_module.turn import errors, greeting
from factory_issue_module.turn.gate import DomainAccess

logger = structlog.get_logger(__name__)

EXECUTABLE = ("list_issues", "aggregate")
ADAPTERS: dict[Domain, Any] = {Domain.DOMESTIC: domestic, Domain.BRAZIL: brazil, Domain.OVERSEAS: overseas}
_BY_LABEL = {d.label: d for d in DOMAINS}
#: 结果为空、时间是默认读法（只说「最近」）时可放宽到的说法（总述「结果为空时」「时间说法怎么换算」）
RECENT_WORDS = ("最近", "近期", "近来", "最近一段时间")
RELAX_OPTIONS = ("近 90 天", "今年")
RELAX_MAX = 2
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
    if run.skill == "list_issues":
        keys, _missing = list_issues.columns_for(run.step)
        dkeys, _absent = list_issues.domain_keys(keys, d, A.KEY_ALIAS)
        got.needs |= list_issues.needs(dkeys, run.step, A.COLUMN_NEEDS, A.SORT_NEEDS)
        got.unavailable = got.unavailable or bool(blind & set(dkeys))
        return
    group_by = _group_by(run.step)
    dims, missing, more = A.dims(group_by, aggregate.basis_of(run.step))
    got.needs |= more
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
            if len(run.domains) == 1:
                return a0
            soft = [f"{d.label}{a.missing}" for d, a in asks if a.missing is not None]
            head = "，".join(soft) + "。" if soft else ""
            return Ask(head + d0.label + a0.question, a0.options, a0.reason)
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


def prepare(plan: dict, spans: Mapping[str, list[Span]], T: Turn) -> list[StepRun] | Ask:
    """第 6 步：每步的域、名字对库；对不上就追问，本轮不取数。"""
    runs: list[StepRun] = []
    for step in [s for s in plan.get("steps") or [] if isinstance(s, dict)]:
        asked = _asked(step)
        run = StepRun(step=step, sid=str(step.get("id")), skill=str(step.get("skill")),
                      domains=[d for d in asked if T.access.can(d)], denied=[d for d in asked if not T.access.can(d)],
                      spans=spans.get(str(step.get("id")), []))
        if run.skill in EXECUTABLE:
            run.deferred = _uses_refs(step)
            if not run.deferred:
                ask = _resolve(run, T, {})
                if ask is not None:
                    return ask
        runs.append(run)
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


def _time_text(run: StepRun) -> str | None:
    items = [t for t in schema.as_list((run.step.get("params") or {}).get("time")) if isinstance(t, dict) and t.get("said")]
    parts = list(dict.fromkeys(s.describe() for s in run.spans if not s.unlimited))  # 合成同一段的只写一次
    if (run.step.get("params") or {}).get("compare") == "时段" and len(run.spans) >= 2:
        ordered = sorted(run.spans[:2], key=lambda s: s.start or date.min)
        return f"{base.period_label(ordered[1])}与{base.period_label(ordered[0])}对比"
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


def _sandbox_params(run: StepRun, executed: Sequence[Domain], failed: set[str]) -> dict[str, Any]:
    return {"domains": [d.label for d in executed],
            # 靠没取到的主数据才写得出来的列：清单的分析事实不按它们分（否则会读成「加工厂全部未填」）
            "blind": {d.label: sorted(_blind(d, failed)) for d in executed},
            "enums": {d.label: ADAPTERS[d].enum_params() for d in executed},
            "desc": {d.label: columns.DESC_UNAVAILABLE for d in executed},
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


async def _narrate(T: Turn, table_text: str | None, note: str | None, facts: dict[str, Any], fallback: str,
                   time_text: str | None) -> Event:
    facts = {"时间范围": time_text or "不限建单时间", **facts}
    text = await narrative.write(getattr(T.ctx, "llm", None), T.manifest, T.query, table_text, note, facts,
                                 T.entities, fallback)
    return Event.delta("\n\n" + text)


def _absent_note(d: Domain, absent: Sequence[str]) -> str:
    """本域没有的列（总述「跨域规则」清单呈现：用户点名的列某域可能没有）。"""
    if d is Domain.BRAZIL and columns.shown("current_people") in absent:
        rest = [a for a in absent if a != columns.shown("current_people")]
        return "巴西不提供当前责任人" + (f"，也没有『{'』『'.join(rest)}』这几项" if rest else "")
    return f"{d.label}没有『{'』『'.join(absent)}』这{'几' if len(absent) > 1 else '一'}项"


async def run_step(run: StepRun, T: Turn, refs: Mapping[str, Any], C: cal.Caliber, notes: list[str],
                   *, present: bool = True) -> StepOut:
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
    P = _sandbox_params(run, executed, T.master.failed)
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
        P["list"] = list_issues.params(run.step, keys_by, T.answer)
        outcome = await runner.run(T.ctx, "list", frames, P)
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
        outcome = await runner.run(T.ctx, "aggregate", frames, P)
    if not outcome.ok:
        out.events.append(Event.delta("。".join([*dict.fromkeys(head), errors.SECTION_FAILED]) + "。"))
        return out
    res = outcome.result or {}
    out.ok = True
    segs = res.get("segments") or []
    out.empty = all((s.get("found") or 0) == 0 for s in segs)
    out.found_any = not out.empty
    out.refs = {f"{run.sid}.{k}": v for k, v in (res.get("refs") or {}).items()}
    if not present:
        return out
    if head:
        out.events.append(Event.delta("。".join(dict.fromkeys(head)) + "。\n\n"))
    if run.skill == "list_issues":
        out.events += await _present_lists(run, T, res, segs, time_text, C, keys_by)
    else:
        all_dims = [d for dims in dims_by.values() for d in dims]
        out.events += await _present_aggs(run, T, segs, time_text, C, all_dims, metrics)
    return out


# ---------------------------------------------------------------------------- 清单


async def _present_lists(run: StepRun, T: Turn, res: dict[str, Any], segs: Sequence[dict[str, Any]],
                         time_text: str | None, C: cal.Caliber, keys_by: Mapping[str, list[str]]) -> list[Event]:
    """一域：开头、表、分析。几域：开头先给各域张数与合计，每域一张表，分析段整步一次（总述「跨域规则」）。"""
    events: list[Event] = []
    multi = len(segs) > 1
    scope = _scope(time_text)
    desc = any("desc" in keys for keys in keys_by.values())
    if multi:
        text = list_issues.cross_opening(res, scope)
        if desc:
            text = text[:-1] + f"；问题描述摘要{columns.DESC_UNAVAILABLE}，其他列照常。"
        events.append(Event.delta(text + "\n\n"))
    described: list[str] = []
    for i, seg in enumerate(segs):
        dom = _BY_LABEL.get(seg.get("domain", ""), Domain.DOMESTIC)
        if multi and i:
            events.append(Event.delta("\n\n"))
        got, table_text = _present_list(run, T, seg, dom, time_text, C, "desc" in keys_by.get(dom.label, [])
                                        and not multi)
        events += got
        if table_text:
            described.append(table_text)
            if not multi and not seg.get("few"):
                events.append(await _narrate(T, table_text, None, seg.get("facts") or {},
                                             list_issues.fallback(seg.get("facts") or {}), time_text))
    if multi and not res.get("few_total"):
        facts = {"合计张数": res.get("found_total", 0), "各域张数": res.get("by_domain") or [],
                 **{s["domain"]: s.get("facts") or {} for s in segs if not s.get("empty")}}
        events.append(await _narrate(T, "；".join(described), None, facts, list_issues.fallback(facts), time_text))
    return events


def _present_list(run: StepRun, T: Turn, seg: dict[str, Any], dom: Domain, time_text: str | None,
                  C: cal.Caliber, desc_note: bool) -> tuple[list[Event], str | None]:
    events: list[Event] = []
    scope = _scope(time_text)
    if seg.get("empty"):
        future = any(s.future for s in run.spans)
        events.append(Event.delta(f"{dom.label}{scope}没有查到单" + ("，这段时间还没到" if future else "") + "。"))
        _add_caliber(C, run, seg, [], [])
        return events, None
    text = list_issues.opening(seg, dom.label, scope, list_issues.order_text(run.step)) + _breakdown_text(seg)
    if desc_note:
        text += f"；问题描述摘要{columns.DESC_UNAVAILABLE}，其他列照常"
    events.append(Event.delta(text + "。"))
    title = f"{dom.label}问题单" + (f"：{time_text}" if time_text else "")
    ids = (seg.get("ids_shown") or None)
    events.append(tables.event(seg["table"], title, link_ids=ids, domain=dom, sites=T.sites))
    _add_caliber(C, run, seg, [], [])
    return events, tables.describe(title, seg["table"], seg.get("shown"))


# ---------------------------------------------------------------------------- 统计


async def _present_aggs(run: StepRun, T: Turn, segs: Sequence[dict[str, Any]], time_text: str | None,
                        C: cal.Caliber, dims: Sequence[dict[str, Any]], metrics: Sequence[str]) -> list[Event]:
    """每段：开头、表、图；同一维度按域分别给的几张表（处理环节、状态）合写一段分析。"""
    events: list[Event] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for seg in segs:
        groups.setdefault(f"{seg.get('kind')}:{seg.get('title')}", []).append(seg)
    for key, members in groups.items():
        described: list[str] = []
        facts: dict[str, Any] = {}
        for i, seg in enumerate(members):
            if events and i:
                events.append(Event.delta("\n\n"))
            got, narr = _present_agg(run, T, seg, time_text, C, dims, metrics)
            events += got
            if narr is not None:
                described.append(narr[0])
                facts = narr[1] if len(members) == 1 else {**facts, seg.get("domain", ""): narr[1]}
        if described:
            said = await _narrate(T, "；".join(described), None, facts, "", time_text)
            if said.data.get("text", "").strip():
                events.append(said)
        if key != list(groups)[-1]:
            events.append(Event.delta("\n\n"))
    return events


def _present_agg(run: StepRun, T: Turn, seg: dict[str, Any], time_text: str | None, C: cal.Caliber,
                 dims: Sequence[dict[str, Any]], metrics: Sequence[str]
                 ) -> tuple[list[Event], tuple[str, dict[str, Any]] | None]:
    events: list[Event] = []
    scope = _scope(time_text)
    label = str(seg.get("domain") or "")
    if seg.get("kind") == "group":
        dims = [d for d in dims if d.get("title") == seg.get("title")]
    if (seg.get("found") or 0) == 0 and seg.get("kind") != "compare":
        future = any(s.future for s in run.spans)
        events.append(Event.delta(f"{label}{scope}没有查到单" + ("，这段时间还没到" if future else "") + "。"))
        _add_caliber(C, run, seg, dims, metrics)
        return events, None
    if seg.get("kind") == "group" and not (seg.get("table") or {}).get("rows"):
        events.append(Event.delta(f"{label}{scope}共 {seg.get('found', 0)} 张，没有可以按{seg.get('title')}统计的单。"))
        _add_caliber(C, run, seg, dims, metrics)
        return events, None
    events.append(Event.delta(aggregate.opening(seg, label, scope) + _breakdown_text(seg) + "。"))
    suffix = f"：{time_text}" if time_text else ""
    title = f"{label}按{seg.get('title')}统计{suffix}" if seg.get("kind") == "group" else f"{label}统计{suffix}"
    if seg.get("table"):
        events.append(tables.event(seg["table"], title))
    if seg.get("bins"):
        events.append(tables.event(seg["bins"], f"{label}结案周期分档{suffix}"))
    chart = seg.get("chart") or {}
    dim_name = str(seg.get("name") or next((d.get("name") for d in dims if d.get("title") == seg.get("title")),
                                           chart.get("dimension")))
    if chart.get("rows"):
        user_chart = (run.step.get("params") or {}).get("chart")
        user_chart = user_chart if isinstance(user_chart, str) else None
        if seg.get("kind") == "compare":
            kind, why = charts.choose_compare(len(chart["rows"]), user_chart=user_chart)
        else:
            kind, why = charts.choose(dim_name, seg.get("groups") or len(chart["rows"]), multi=bool(seg.get("multi")),
                                      user_chart=user_chart)
        if kind is not None:
            series = list(chart.get("series") or [aggregate.COLS["count"]])
            if dim_name in ("加工厂", "跟进部门") and aggregate.COLS["unclosed"] in (chart["rows"][0] or {}):
                series.append(aggregate.COLS["unclosed"])
            chart_title = f"{label}结案周期分档{suffix}" if seg.get("bins") else title
            events.append(charts.event(T.ctx.stats, kind, chart["rows"], str(chart.get("dimension")), series,
                                       chart_title))
            if why:
                events.append(Event.delta(why))
    events += _rate_lists(seg, T, suffix)
    _add_caliber(C, run, seg, dims, metrics)
    if seg.get("kind") == "overview" and not seg.get("cross") and not (seg.get("facts") or {}).get("按问题类型"):
        return events, None
    return events, (tables.describe(title, seg.get("table") or {}, seg.get("groups")), seg.get("facts") or {})


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


# ---------------------------------------------------------------------------- 整轮


def _opening_notes(T: Turn) -> list[str]:
    """「按 X 理解」：第 7 条按库里的取值定的类；第 13 条修一次仍不一致时按什么日期理解。"""
    out = []
    for inf in T.result.inferred:
        out.append(f"「{'、'.join(inf.values)}」按{inf.field}理解")
    if T.result.check_errors and T.result.plan is not None:
        for _sid, said, basis, _hit in normalize.basis_mismatches(T.result.plan, T.query):
            out.append(f"「{said}」按{cal.BASIS_TEXT.get(basis, basis)}理解")
    return out


def _alternative_buttons(T: Turn) -> list[dict[str, str]]:
    """第 13 条修一次仍不一致：另一种理解的按钮（原话加这条理解）。"""
    if not (T.result.check_errors and T.result.plan is not None):
        return []
    alts = [f"按{cal.BASIS_TEXT.get(hit, hit)}算" for _sid, _said, _basis, hit in
            normalize.basis_mismatches(T.result.plan, T.query)]
    return clarify.alternative_recommendations(list(dict.fromkeys(alts)), T.query)


async def _relax_buttons(plan: dict, runs: Sequence[StepRun], T: Turn) -> list[dict[str, str]]:
    """结果为空、时间是默认读法（只说「最近」）时：代码列出放宽的说法，每个预先查好张数，张数为 0 的不列。"""
    said = next((str(t["said"]) for r in runs for t in schema.as_list((r.step.get("params") or {}).get("time"))
                 if isinstance(t, dict) and str(t.get("said") or "").strip() in RECENT_WORDS), None)
    if said is None or said not in T.query:
        return []
    out: list[dict[str, str]] = []
    for option in RELAX_OPTIONS:
        trial = _swap_time(plan, said, option)
        spans, unknown = timespan.plan_spans(trial, T.today)
        if unknown is not None:
            continue
        prepared = prepare(trial, spans, T)
        if isinstance(prepared, Ask):
            continue
        found = False
        refs: dict[str, Any] = {}
        for r in prepared:
            if r.skill not in EXECUTABLE:
                continue
            res = await run_step(r, T, refs, cal.Caliber(), [], present=False)
            refs |= res.refs
            if res.found_any:
                count = res.refs.get(f"{r.sid}.count", res.refs.get(f"{r.sid}.total"))
                out.append({"id": str(len(out) + 1), "name": "放宽时间", "query": T.query.replace(said, option, 1),
                            "label": f"看{option}（{count} 张）" if count is not None else f"看{option}"})
                found = True
                break
        if found and len(out) >= RELAX_MAX:
            break
    return out[:RELAX_MAX]


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


def _breakdown_text(seg: dict[str, Any]) -> str:
    """一个说法对上几个取值时：「按以下几个部门统计：研发一部 2 张、研发二部 1 张」（张数来自沙箱）。"""
    parts = []
    for _title, pairs in seg.get("breakdowns") or []:
        parts.append("、".join(f"{name} {n} 张" for name, n in pairs))
    return "".join(f"；按以下几个部门统计：{p}" for p in parts)


def _swap_time(plan: dict, said: str, option: str) -> dict:
    trial = copy.deepcopy(plan)
    for s in trial.get("steps") or []:
        for t in schema.as_list((s.get("params") or {}).get("time")):
            if isinstance(t, dict) and str(t.get("said") or "").strip() == said:
                t["said"] = option
    return trial


async def run(plan: dict, runs: Sequence[StepRun], T: Turn) -> AsyncIterator[Event]:
    """第 8–9 步。"""
    C = cal.Caliber()
    refs: dict[str, Any] = {}
    shown = [r for r in runs if r.skill in EXECUTABLE or r.skill not in ("clarify", "introduce")]
    multi = len(shown) > 1
    opening = _opening_notes(T) + _recent_notes(runs, T)
    any_ok, any_empty, any_found = False, False, False
    for i, r in enumerate(shown, start=1):
        if multi:
            yield Event.delta(f"{'' if i == 1 else chr(10) * 2}**{i}. {_title(r)}**\n\n")
        when = r.step.get("when")
        if schema.is_ref(when) and not refs.get(when["ref"]):
            yield Event.delta("前一步的条件不成立，这一段不列。")
            continue
        if r.skill not in EXECUTABLE:
            yield Event.delta(f"{errors.NOT_READY}。")
            continue
        notes = opening if i == 1 else []
        if r.skill == "list_issues" and list_issues.no_conditions(r.step):
            notes = [*notes, errors.NO_CONDITION_LIST]
        out = await run_step(r, T, refs, C, notes)
        refs |= out.refs
        any_ok = any_ok or out.ok
        any_empty = any_empty or out.empty
        any_found = any_found or out.found_any
        for ev in out.events:
            yield ev
        dep = any(schema.is_ref(f.get("value")) for s in shown[i:] for f in
                  schema.as_list((s.step.get("params") or {}).get("filters")) if isinstance(f, dict))
        if out.empty and dep:
            yield Event.delta("\n\n这一步没有结果，后面依赖它的步骤不再执行。")
            break
    if not any_ok:
        yield Event.error(errors.TURN_FAILED_CODE, errors.TURN_FAILED, fatal=True)
        return
    if C.counted:
        yield Event.delta("\n\n" + C.text())
    buttons = _alternative_buttons(T)
    if any_empty:
        buttons += await _relax_buttons(plan, runs, T)
    elif any_found:
        buttons += _recent_buttons(runs, T)
    if any(r.skill == "list_issues" and list_issues.no_conditions(r.step) for r in shown):
        buttons += greeting.buttons(T.access)
    if buttons:
        recs = [{**b, "id": str(k)} for k, b in enumerate(buttons[: clarify.MAX_OPTIONS], start=1)]
        yield Event.suggestions(recs)


def _title(r: StepRun) -> str:
    label = "清单" if r.skill == "list_issues" else "统计" if r.skill == "aggregate" else "其他"
    doms = "、".join(d.label for d in r.domains) or "、".join(d.label for d in r.denied)
    return f"{doms}{label}"
