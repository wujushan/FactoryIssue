"""按文字找单（设计 §4.3 文字查找一行、§7；总述「关键词搜索与类似问题」整节、「命中后带回什么与时效」）。

一步的流程（① 与 ⑥ 每步一次，②–⑤ 每域一次、各域并行）：
1. 条件照清单对库（第 6 步已做）；本域主表可查而文字查找表无权的域答「暂不可用」，不说成「没有找到」（域闸门）。
2. ① 定说法（`text/terms.py`，可能一次模型调用）。
3. 各域按条件取数（与清单同一个取数单元），另读本域分段表（预筛过）与文字表要比的列（`text/keyword.py`）。
4. ② 沙箱按词匹配、按单归组（`stats/tasks/keyword_match.py`），同时给出本步范围内的单（按意思一路限定候选）。
5. ③④ 按意思找（`text/semantic.py`）；⑤「可能相关」交模型逐张判断（`text/judge.py`）。类似问题不判断。
6. ⑥ 沙箱收拢、计数、排序（`stats/tasks/text_merge.py`）；问题描述摘要（`present/summaries.py`）、原因与措施（只取
   表格里列出的单，§13）；开头、表格、分析、统计口径「文字查找」一项、按钮。

事件顺序：`delta`（开头：各组张数、本次按哪些说法找）→ 每域一个 `table` → `delta`（分析）→ 统计口径（整轮合并）
→ 导出链接 → `suggestions`。数字都来自沙箱。
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import structlog
from forge_core.errors import TableDenied
from forge_core.events import Event

from factory_issue_module import landed
from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import SEGMENTATION, TOPIC_TERMS, Domain
from factory_issue_module.domains import base, enums
from factory_issue_module.present import caliber as cal
from factory_issue_module.present import columns, export, summaries, tables
from factory_issue_module.skills import list_issues
from factory_issue_module.stats import runner
from factory_issue_module.text import judge, keyword, semantic, terms
from factory_issue_module.text.terms import TermPlan
from factory_issue_module.turn import errors

logger = structlog.get_logger(__name__)

EXPORT_FILENAME = "按文字找到的问题单.xlsx"
THIRD_MAX = 10
SIM_MAX = 10
CONTEXT_MAX = 120
#: 统计口径里的找法（总述「统计口径说明」文字查找一行）
METHODS = {"关键词": "关键词搜索", "话题": "涉及某个话题", "类似问题": "类似问题", "点名字段": "点名字段",
           "做法": "问做法"}
#: 国内停线状态为这两种时，重启方案与处理步骤里重启那三个环节不参与匹配（国内「停线」）
RESTART_HEADS = ("停线重启", "停线重启审核", "停线重启发起", "责任人填写重启方案")
STEP_COLUMNS = ("f_step_result", "f_step_opinion", "f_step_content")


def _clip(text: str) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= CONTEXT_MAX else flat[:CONTEXT_MAX] + "…"


def _labels(tp: TermPlan) -> tuple[dict[str, str], bool]:
    """「分组」一列的说法、要不要这一列（总述「表格列名」）。"""
    if tp.mode == "类似问题" or (tp.mode == "关键词"):
        return {}, False
    if tp.grouped:
        return dict(columns.TEXT_GROUPS), True
    if tp.intersect:
        return {"0": columns.TEXT_BOTH, "3": columns.TEXT_GROUPS["3"]}, True
    if tp.semantic is None:
        return {}, False
    return {"0": columns.TEXT_HIT, "3": columns.TEXT_GROUPS["3"]}, True


def table_keys(step: dict, show_group: bool) -> tuple[list[str], bool]:
    """表格的列（内部键）与要不要加「原因与措施」：用户点名了列按用户说的，「命中处」照加。"""
    p = step.get("params") or {}
    if p.get("columns"):
        keys, _missing = list_issues.columns_for(step)
        reasons = False
    else:
        keys = ["number", "desc"]
        reasons = True
    keys = [k for k in keys if k != "number"]
    head = ["number", "_group"] if show_group else ["number"]
    return [*head, *keys, "_context"], reasons


def _domain_cols(keys: Sequence[str], d: Domain, alias: Mapping[str, Any]) -> list[str]:
    plain = [k for k in keys if not k.startswith("_")]
    mapped, _absent = list_issues.domain_keys(plain, d, alias)
    out: list[str] = []
    for k in keys:
        if k.startswith("_"):
            out.append(k)
        elif k in mapped or any(x in mapped for x in alias.get(k, [k]) or []):
            out += [x for x in (alias.get(k, [k]) or [k]) if x in mapped and x not in out]
    return out


def _restart(d: Domain) -> dict[str, Any] | None:
    if d is not Domain.DOMESTIC:
        return None
    return {"domain": d.label, "stops": [enums.CN_STOP_REVIEWING, enums.CN_STOP_SCHEME], "columns": ["f_restart"],
            "step_columns": list(STEP_COLUMNS), "step_heads": list(RESTART_HEADS)}


def _has_conditions(dsteps: Sequence[base.DomainStep]) -> bool:
    return any(s.sql or s.conds or s.times for s in dsteps)


def _ids(frame: pd.DataFrame | None, col: str) -> list[int]:
    return [int(x) for x in base.column(frame, col)]


def _texts(frame: pd.DataFrame | None) -> dict[int, str]:
    return {int(i): str(c) for i, c in zip(base.column(frame, "issue_id"), base.column(frame, "context"), strict=False)}


# ---------------------------------------------------------------------------- 开头与按钮


def _n(seg: Mapping[str, Any], key: str) -> int:
    value = seg.get(key)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def opening(tp: TermPlan, seg: Mapping[str, Any], label: str, scope: str, counts: Mapping[str, Any]) -> str:
    """一域的开头一句（张数都来自沙箱）。"""
    head = f"{label}{scope}"
    third = _n(seg, "g3")
    if tp.mode == "类似问题":
        if not third:
            return f"{head}按现象描述没有找到相近的问题"
        return f"{head}按现象描述找到 {third} 张相近的问题，按相近程度排序，不保证完整"
    if tp.mode == "关键词":
        how = "同时出现" if tp.logic == "和" and len(tp.used) > 1 else ("出现任一个词" if len(tp.used) > 1 else "出现")
        words = "、".join(f"「{w}」" for w in tp.used)
        return f"{head}{tp.where}里{how}{words}的单共 {_n(seg, 'kw')} 张"
    if tp.intersect:
        both = _n(seg, "kw")
        text = f"{head}用{tp.approach}处理过、又涉及{tp.label}的单 {both} 张"
        if not both:
            text += (f"：用{tp.approach}处理过的 {int(counts.get('approach') or 0)} 张，"
                     f"涉及{tp.label}的 {int(counts.get('topic') or 0)} 张")
        if third:
            text += f"；另有 {third} 张用{tp.approach}处理过、现象可能相关，仅供参考，不保证找全"
        return text
    if tp.grouped:
        kw = _n(seg, "kw")
        if not kw and not third:
            return f"{head}没有找到与{tp.label}有关的单"
        text = f"{head}找到 {kw} 张与{tp.label}有关的单"
        if kw:
            text += f"：问题本身涉及的 {_n(seg, 'g1')} 张"
            if _n(seg, "g2"):
                text += f"；处理过程中提到的 {_n(seg, 'g2')} 张，多是顺带提到，请看每行命中的文字"
        if third:
            text += f"{'；另有' if kw else '，另有'} {third} 张说法不同、可能相关，仅供参考，不保证找全"
        return text
    where = tp.where if tp.mode == "点名字段" else terms.MEASURE_SCOPE.split("（")[0]
    what = tp.label if tp.mode == "点名字段" else tp.approach
    text = f"{head}{where}里提到{what}的单 {_n(seg, 'kw')} 张"
    if third:
        text += f"；另有 {third} 张说法不同、可能相关，仅供参考，不保证找全"
    return text


def used_text(tp: TermPlan) -> str:
    """「本次按这些说法找：…」（总述「涉及某个话题怎么找」）；用户自己给的词只说按哪些词找。"""
    if tp.mode == "类似问题":
        return ""
    if tp.user_words:
        logic = f"（{'都要出现' if tp.logic == '和' else '出现任一个'}）" if len(tp.used) > 1 else ""
        return f"按这些词找{logic}：{'、'.join(tp.used)}"
    if tp.intersect:
        return f"做法按这些说法找：{'、'.join(tp.used_approach)}；现象按这些说法找：{'、'.join(tp.used)}"
    used = tp.used_approach if tp.mode == "做法" else tp.used
    return f"本次按这些说法找：{'、'.join(used)}"


def adjust_hint(tp: TermPlan) -> str:
    """说法有模型挑的或提的：告诉用户可以增减（最小版，开发者 2026-10-30 定：不做按钮）。"""
    if not tp.by_model or tp.user_words or tp.mode == "类似问题":
        return ""
    return "要增减说法时可以直接说「再加上『某个说法』」或「去掉『某个说法』」重新找"


def first_fields(seg: Any) -> str:
    """第一组栏目的叫法（「问题现象、问题描述、原因分析」，取分段规则配置的第一组、国内的栏目名）。"""
    titles = landed.seg_fields()
    return "、".join(next(iter(titles[c].values())) for c in seg.groups["first"] if c in titles)


def buttons(tp: TermPlan, res: Mapping[str, Any], counts: Mapping[str, Any], first: str = "") -> list[dict[str, str]]:
    """文字查找的可点选项（最小版，开发者 2026-10-30 定，2026-10-31 补「只看问题本身涉及的」；按钮形状照 §9.5）。
    张数与有没有某一组都取自沙箱。"""
    out: list[dict[str, str]] = []
    totals = res.get("totals") or {}
    if tp.scope == "比话题小" and tp.topic is not None and not tp.intersect and tp.mode == "话题":
        out.append({"id": "t1", "name": "按整个话题找", "label": "按整个话题找", "query": f"按整个{tp.topic.name}话题找"})
    # 清单外的话题（说法由助手提）：只看第一组。问句写成点名这几栏，规划器照点名字段写计划，不用改计划格式；
    # 两组都有单时才给（只有一组时点了结果一样）
    if (tp.mode == "话题" and tp.grouped and tp.scope == "清单外" and first
            and int(totals.get("g1") or 0) and int(totals.get("g2") or 0)):
        out.append({"id": "t4", "name": "只看问题本身涉及的", "label": "只看问题本身涉及的",
                    "query": f"{first}里提到{tp.label}的单"})
    if tp.intersect and not int(totals.get("kw") or 0):
        kw_totals = counts.get("totals") or {}
        approach, topic = int(kw_totals.get("approach") or 0), int(kw_totals.get("topic") or 0)
        for k, (what, n, query) in enumerate(((f"用{tp.approach}处理过的", approach, f"只看用{tp.approach}处理过的"),
                                              (f"{tp.label}的", topic, f"只看{tp.label}的")), start=1):
            if not n:
                continue
            label = f"只看{what}（{n} 张）"
            if len(label) > 15:
                label = f"只看{'做法' if k == 1 else '现象'}那一边（{n} 张）"
            out.append({"id": f"t{k + 1}", "name": label, "label": label, "query": query})
    return out


# ---------------------------------------------------------------------------- 一步


@dataclasses.dataclass
class Ready:
    """取好数、可以按词匹配的一步。"""

    tp: TermPlan
    executed: list[Domain]
    frames: dict[str, pd.DataFrame]
    head: list[str]
    label_denied: list[str]
    not_counted: list[str]


async def _mart(T: Any, d: Domain, tp: TermPlan) -> tuple[Domain, Any]:
    available = [c.name for c in landed.text_columns() if d.label in c.sources]
    cols = keyword.text_columns(tp.probes, d, available)
    try:
        return d, await keyword.fetch(T.ctx, d, tp.probes, cols)
    except TableDenied as exc:
        logger.warning("factory_issue_text_table_denied", domain=d.value, error=type(exc).__name__)
        return d, "denied"
    except Exception as exc:  # noqa: BLE001 —— 这一域文字查找答查不到，异常只进日志
        logger.error("factory_issue_text_fetch_failed", domain=d.value, error=type(exc).__name__)
        return d, "failed"


async def run_step(run: Any, T: Any, refs: Mapping[str, Any], C: cal.Caliber, notes: list[str],
                   *, present: bool = True, caliber: bool = False) -> Any:
    """执行一步文字查找，返回 `turn/execute.py::StepOut`。`present=False` 只跑到收拢为止（质疑重查的重放），不写分析、
    不取摘要与原因措施；「可能相关」照常判断（它决定列哪几张单）。"""
    from factory_issue_module.turn import execute as X

    out = X.StepOut()
    if run.stored is not None:  # 递进筛选：上一轮那次文字查找的结果，直接用存下的单 ID
        return X.stored_out(run)
    if run.deferred:
        ask = X._resolve(run, T, refs)
        if ask is not None:
            out.events.append(Event.delta(f"{ask.question}\n\n"))
            return out
    topics = T.topics or config_files.default(TOPIC_TERMS)
    seg = T.seg or config_files.default(SEGMENTATION)
    tp = await terms.plan(getattr(T.ctx, "llm", None), run.step, topics, seg)
    if isinstance(tp, base.Ask):
        out.ask, out.final, out.ok = X._with_sid(tp, run.sid), True, True
        return out
    label_denied = [d.label for d in run.denied]
    excluded = list(dict.fromkeys(x for d in run.domains if d in run.dsteps for x in run.dsteps[d].excluded))
    resolved = [d for d in run.domains if d in run.dsteps and not run.dsteps[d].excluded]
    lacking = [d for d in resolved if d.label in tp.missing]
    no_text = [d for d in resolved if d not in T.access.text_search and d not in lacking]
    usable = [d for d in resolved if d not in lacking and d not in no_text]
    not_counted = [f"{d.label}没有『{'』『'.join(tp.missing[d.label])}』这一栏，{d.label}未计入" for d in lacking]
    if no_text:
        not_counted.append(errors.text_unavailable(d.label for d in no_text))
    head = list(notes) + tp.notes
    fetch_run = dataclasses.replace(run, domains=usable, dsteps={d: run.dsteps[d] for d in usable})
    frames, denied_now, problems, executed = await X._frames(fetch_run, T)
    for d in denied_now:
        T.access = T.access.without(d)
    label_denied += [d.label for d in denied_now]
    marts = await asyncio.gather(*(_mart(T, d, tp) for d in executed))
    for d, got in marts:
        if isinstance(got, dict):
            frames |= got
        elif got == "denied":
            executed.remove(d)
            not_counted.append(errors.text_unavailable([d.label]))
        else:
            executed.remove(d)
            problems.append(f"{d.label}：{errors.SECTION_FAILED}")
    C.domains([d.label for d in executed],
              ([errors.not_counted(label_denied)] if label_denied else []) + excluded + not_counted)
    head += ([errors.not_counted(label_denied)] if label_denied else []) + excluded + not_counted + problems
    for d in executed:
        head += run.dsteps[d].notes + run.dsteps[d].skipped
    out.domains = [d.label for d in executed]
    if not executed:
        if head:
            out.events.append(Event.delta("。".join(dict.fromkeys(head)) + "。"))
        out.ok = not problems
        return out
    ready = Ready(tp, executed, frames, head, label_denied, not_counted)
    got = await _search(run, T, ready)
    if got is None:
        out.events.append(Event.delta("。".join([*dict.fromkeys(head), errors.SECTION_FAILED]) + "。"))
        return out
    res, outcome_frames, counts, sem_notes = got
    segs = res.get("segments") or []
    out.ok = True
    out.empty = all((s.get("found") or 0) == 0 for s in segs)
    out.found_any = not out.empty
    out.truncated = any(s.get("truncated") for s in segs)
    out.refs = {f"{run.sid}.{k}": v for k, v in (res.get("refs") or {}).items()}
    out.refs[f"{run.sid}.issues"] = X.issues_from_frames(outcome_frames)
    out.extra = {"text": {"key": terms.key(run.step), "terms": list(dict.fromkeys(tp.used + tp.used_approach)),
                          "judged": tp.semantic is not None and tp.mode != "类似问题"}}
    if not present:
        out.segs = list(segs)
        if caliber:
            _caliber(C, run, tp, segs, sem_notes, X)
        return out
    head += sem_notes
    keys, reasons = table_keys(run.step, _labels(tp)[1])
    if "desc" in keys:
        await summaries.fill_tables(T.ctx, segs, executed)
    if reasons:
        await X._add_reasons(T, segs)
    out.events += _present(run, T, tp, res, segs, counts, head)
    narr = await _narrative(T, X, tp, res, segs, run)
    if narr is not None:
        out.events.append(narr)
    _caliber(C, run, tp, segs, sem_notes, X)
    if res.get("exported"):
        await summaries.fill_exports(T.ctx, outcome_frames, executed)
        text = await export.save_lists(T.ctx, res["exported"], outcome_frames, EXPORT_FILENAME)
        T.record.exports.append(text)
        out.exported = text != f"{errors.EXPORT_FAILED}。"
    out.buttons = buttons(tp, res, counts, first_fields(T.seg or config_files.default(SEGMENTATION)))
    return out


async def _search(run: Any, T: Any, R: Ready) -> tuple[dict[str, Any], dict[str, pd.DataFrame], dict[str, Any], list[str]] | None:
    """②–⑥：按词匹配、按意思找与判断、收拢。沙箱失败返回 None。"""
    from factory_issue_module.turn import execute as X

    tp, executed = R.tp, R.executed
    seg_cfg = T.seg or config_files.default(SEGMENTATION)
    dsteps = [run.dsteps[d] for d in executed]
    conditioned = _has_conditions(dsteps)
    P = X._sandbox_params(run, executed, T.master.failed, T.access.text_search)
    kw_frames: dict[str, pd.DataFrame] = {}
    counts: dict[str, Any] = {}
    if tp.probes or conditioned:
        P["kw"] = {"probes": tp.probes, "grouped": tp.grouped, "intersect": tp.intersect,
                   "groups": {g: list(c) for g, c in seg_cfg.groups.items()},
                   "titles": {d.label: {code: names[d.label] for code, names in landed.seg_fields().items()
                                        if d.label in names} for d in executed},
                   "col_titles": {d.label: {c.name: c.display for c in landed.text_columns()} for d in executed},
                   "restart": next((r for r in (_restart(d) for d in executed) if r), None), "cand": conditioned}
        outcome = await runner.run(T.ctx, "keyword_match", R.frames, P, return_frames=True)
        if not outcome.ok:
            return None
        kw_frames = dict(getattr(outcome, "frames", None) or {})
        counts = {"by_domain": (outcome.result or {}).get("counts") or {},
                  "totals": (outcome.result or {}).get("totals") or {}}
    sem_frames, sem_notes = await _semantic(T, tp, executed, kw_frames, conditioned)
    labels, show_group = _labels(tp)
    keys, _reasons = table_keys(run.step, show_group)
    cols = {d.label: _domain_cols(keys, d, X.ADAPTERS[d].KEY_ALIAS) for d in executed}
    P2 = X._sandbox_params(run, executed, T.master.failed, T.access.text_search)
    P2["tm"] = {"labels": labels, "group_title": columns.TEXT_GROUP, "context_title": columns.TEXT_CONTEXT,
                "columns": cols, "table_rows": T.answer.table_rows, "export": (run.step.get("params") or {}).get("export") is True,
                "export_threshold": T.answer.export_threshold, "export_ok": True, "third_max": THIRD_MAX,
                "sim_max": SIM_MAX, "sim": tp.mode == "类似问题", "threshold": T.answer.rerank_score_threshold}
    datasets = {**R.frames, **{k: v for k, v in kw_frames.items() if k.startswith("kw_")}, **sem_frames}
    outcome2 = await runner.run(T.ctx, "text_merge", datasets, P2, return_frames=True)
    if not outcome2.ok:
        return None
    return outcome2.result or {}, dict(getattr(outcome2, "frames", None) or {}), counts, sem_notes


async def _semantic(T: Any, tp: TermPlan, executed: Sequence[Domain], kw: Mapping[str, pd.DataFrame],
                    conditioned: bool) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """③④⑤：每域检索一次（有带 ＊ 的候选时在候选里再检索一次排好），「可能相关」交模型判断。返回 `sem_<域>` 帧。"""
    if tp.semantic is None:
        return {}, []
    S = tp.semantic
    sim = S["kind"] == "sim"
    judge_max = int(T.answer.judge_max)
    top_n = SIM_MAX if sim else max(judge_max, THIRD_MAX)

    def candidates(d: Domain) -> list[int] | None:
        if S.get("from") == "approach":
            return _ids(kw.get("appr_" + d.label), "issue_id")
        return _ids(kw.get("cand_" + d.label), "_id") if conditioned else None

    async def one(d: Domain) -> tuple[Domain, semantic.Found | None]:
        return d, await semantic.search(T.ctx, d, S["query"], candidates=candidates(d), codes=S.get("codes"),
                                        top_n=top_n)

    found = dict(await asyncio.gather(*(one(d) for d in executed)))
    notes: list[str] = []
    if any(v is None for v in found.values()):
        what = "类似问题" if sim else "「可能相关」一组"
        notes.append(f"{errors.SEMANTIC_UNAVAILABLE}，{what}没有列出")
    if any(v is not None and v.partial for v in found.values()):
        notes.append(errors.SEMANTIC_PARTIAL)
    lists: dict[str, list[tuple[int, str, float | None, float | None]]] = {}
    for d in executed:
        got = found.get(d)
        if got is None:
            continue
        taken = set(_ids(kw.get("kw_" + d.label), "issue_id"))
        items = [(h.issue_id, h.text, h.rerank, h.score) for h in got.hits if h.issue_id not in taken]
        if not sim:
            stars = _texts(kw.get("star_" + d.label))
            seen = {x[0] for x in items}
            extra = [i for i in stars if i not in taken and i not in seen]
            if extra:  # ④ 带 ＊ 的候选与按意思找到的放在一起重排（只有按意思找到的时 ③ 已重排过）
                pool = [*(x[0] for x in items), *extra]
                again = await semantic.search(T.ctx, d, S["query"], candidates=pool, codes=S.get("codes"),
                                              top_n=min(len(pool), int(T.answer.rerank_max)))
                if again is not None:
                    items = [(h.issue_id, h.text, h.rerank, h.score) for h in again.hits if h.issue_id not in taken]
                    seen = {x[0] for x in items}
                items += [(i, stars[i], None, None) for i in extra if i not in seen]  # 向量表里没有段的：排在后面
        lists[d.label] = items
    flags: dict[str, list[bool | None]] = {}
    if not sim:
        flags = await judge.judge(getattr(T.ctx, "llm", None), tp.description,
                                  {dom: [x[1] for x in items] for dom, items in lists.items()}, judge_max)
    frames: dict[str, pd.DataFrame] = {}
    for dom, items in lists.items():
        related = flags.get(dom) or [True] * len(items)
        frames["sem_" + dom] = pd.DataFrame(
            [[i, k, _clip(t), r, s, bool(related[k]) if k < len(related) else False]
             for k, (i, t, r, s) in enumerate(items)],
            columns=["issue_id", "rank", "context", "rerank", "score", "related"])
    return frames, notes


def _present(run: Any, T: Any, tp: TermPlan, res: Mapping[str, Any], segs: Sequence[dict[str, Any]],
             counts: Mapping[str, Mapping[str, Any]], head: list[str]) -> list[Event]:
    from factory_issue_module.turn import execute as X

    events: list[Event] = []
    if head:
        events.append(Event.delta("。".join(dict.fromkeys(head)) + "。\n\n"))
    time_text = X._time_text(run)
    scope = X._scope(time_text)
    by_domain = counts.get("by_domain") or {}
    lines = [opening(tp, seg, str(seg.get("domain")), scope, by_domain.get(str(seg.get("domain"))) or {})
             for seg in segs]
    if len(segs) > 1:
        totals = res.get("totals") or {}
        total_kw, total_third = int(totals.get("kw") or 0), int(totals.get("g3") or 0)
        tail = f"合计 {total_kw} 张" + (f"，另有 {total_third} 张{'相近的问题' if tp.mode == '类似问题' else '可能相关'}"
                                       if total_third else "")
        if tp.mode == "类似问题":
            tail = f"合计 {total_third} 张相近的问题"
        lines.append(tail)
    extra = [x for x in (used_text(tp), adjust_hint(tp)) if x]
    events.append(Event.delta("；\n".join(lines) + "。" + ("\n" + "。".join(extra) + "。" if extra else "")))
    for seg in segs:
        dom = X._BY_LABEL.get(str(seg.get("domain")), Domain.DOMESTIC)
        if seg.get("empty"):
            continue
        text = ""
        if seg.get("truncated"):
            if tp.grouped:  # 前两组各给最近几张（S6b 评审 M1），分开说；哪组没列全由沙箱给
                listed = (f"问题本身涉及的{'最近 ' if seg.get('cut_g1') else ' '}{_n(seg, 'shown_g1')} 张"
                          + (f"、处理中提到的{'最近 ' if seg.get('cut_g2') else ' '}{_n(seg, 'shown_g2')} 张"
                             if _n(seg, "g2") else ""))
            else:
                listed = f"最近 {_n(seg, 'shown_kw')} 张直接提到的单"
            text = f"\n\n{dom.label}表格列出{listed}" + (
                f"，以及 {_n(seg, 'g3')} 张{columns.TEXT_GROUPS['3']}的单" if _n(seg, "g3") else "") + "。"
        events.append(Event.delta(text + "\n\n"))
        title = f"{dom.label}按文字找到的单" + (f"：{time_text}" if time_text else "")
        events.append(tables.event(seg["table"], title, link_ids=seg.get("ids_shown") or None, domain=dom, sites=T.sites))
    return events


async def _narrative(T: Any, X: Any, tp: TermPlan, res: Mapping[str, Any], segs: Sequence[dict[str, Any]],
                     run: Any) -> Event | None:
    shown = [s for s in segs if not s.get("empty")]
    # 只有一两张时分析就是复述（09 文档「不分析的三种情形」）；合计张数取自沙箱
    if not shown or all(s.get("few") for s in shown) or int((res.get("totals") or {}).get("listed") or 0) <= 2:
        return None
    facts: dict[str, Any] = {"找法": METHODS.get(tp.mode, tp.mode), "话题或说法": tp.label}
    for s in shown:
        facts[str(s.get("domain"))] = {**(s.get("facts") or {}), "直接提到": _n(s, "kw"), "可能相关": _n(s, "g3")}
    described = "；".join(tables.describe(f"{s.get('domain')}按文字找到的单", s["table"], s.get("shown")) for s in shown)
    fallback = "以上是按文字找到的单，请看每行命中的文字。"
    return await X._narrate(T, described, None, facts, fallback, X._time_text(run))


def _caliber(C: cal.Caliber, run: Any, tp: TermPlan, segs: Sequence[dict[str, Any]], sem_notes: Sequence[str],
             X: Any) -> None:
    for seg in segs:
        X._add_caliber(C, run, seg, [], [])
    method = METHODS.get(tp.mode, tp.mode)
    if tp.mode == "类似问题":
        words, complete = "按现象描述找意思相近的单", f"最多 {SIM_MAX} 张、按相近程度排序，不保证完整"
    elif tp.user_words:
        logic = f"（{'都要出现' if tp.logic == '和' else '出现任一个'}）" if len(tp.used) > 1 else ""
        words, complete = f"按{'、'.join(tp.used)}这些词{logic}", "列出全部命中的单"
    else:
        words = used_text(tp).replace("本次", "")
        if tp.grouped:
            complete = f"问题本身涉及、处理中提到两组全部列出，可能相关一组最多 {THIRD_MAX} 张、不保证找全"
        elif tp.semantic is not None:
            complete = f"直接提到的全部列出，可能相关的最多 {THIRD_MAX} 张、不保证找全"
        else:
            complete = "列出全部命中的单"
    C.item(cal.text_search(method, words, tp.where, complete))
    for text in sem_notes:
        C.item(text)


async def keywords_for(T: Any, step: dict) -> TermPlan | base.Ask:
    """给测试与重放用：一步的找法（与 `run_step` 里同一个函数）。"""
    topics = T.topics or config_files.default(TOPIC_TERMS)
    seg = T.seg or config_files.default(SEGMENTATION)
    return await terms.plan(getattr(T.ctx, "llm", None), step, topics, seg)
