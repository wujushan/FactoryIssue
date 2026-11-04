"""按文字找单（设计 §4.3 文字查找一行、§7；总述「关键词搜索与类似问题」整节、「命中后带回什么与时效」）。

一步的流程（① 与 ⑥ 每步一次，②–⑤ 每域一次、各域并行）：
1. 条件照清单对库（第 6 步已做）；本域主表可查而文字查找表无权的域答「暂不可用」，不说成「没有找到」（域闸门）。
2. ① 定说法（`text/terms.py`，可能一次模型调用）。
3. 各域按条件取数（与清单同一个取数单元），另读本域分段表（预筛过）与文字表要比的列（`text/keyword.py`）。
4. ② 沙箱按词匹配、按单归组（`stats/tasks/keyword_match.py`），同时给出本步范围内的单（按意思一路限定候选）。
5. ③④ 按意思找（`text/semantic.py`）；⑤「可能相关」与类似问题交模型逐张判断（`text/judge.py`）。
6. ⑥ 沙箱收拢、计数、排序（`stats/tasks/text_merge.py`）；问题描述摘要与原因与措施摘要（`present/summaries.py`，
   原因与措施只取表格里列出的单，§13），两样并行；提示行、结论（合计一两张时点名单号、机型、结案没有）、各域一节、
   统计口径「文字查找」一项、按钮。

事件顺序（决策 2026-11-03「回答骨架与排版」）：提示行（无权与未计入的域、本次按哪些说法找）→ 结论（模型写，看得到
每域前几张单的内容；模板句是 `fallback`）→ 每域一节（小标题写张数、`table`、表格下面几句）→ 要增减说法、候选太多
时那句 → 统计口径或查找说明（整轮合并）→ 导出链接 → `suggestions`。数字都来自沙箱。
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
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
from factory_issue_module.plan import clarify
from factory_issue_module.present import caliber as cal
from factory_issue_module.present import columns, export, insights, layout, links, summaries, tables
from factory_issue_module.skills import list_issues
from factory_issue_module.stats import runner
from factory_issue_module.text import judge, keyword, semantic, terms
from factory_issue_module.text.terms import TermPlan
from factory_issue_module.turn import errors

logger = structlog.get_logger(__name__)

EXPORT_FILENAME = "按文字找到的问题单.xlsx"
THIRD_MAX = 10
#: 类似问题每域交模型判断的张数（最相近的前几张，一批）。每域列几张是 `answer_params.toml` 的 `similar_rows`（默认 5，
#: 决策 2026-11-03「回答骨架与排版」），不超过这里（`config/files.SIMILAR_ROWS_MAX`）：没判断过的不列
SIM_JUDGE = 10
#: 类似问题：写结论的模型每域看表格前几张单的内容（【列出的单】）。其余找法的需关注由程序挑（`present/insights.py`）
NARRATIVE_ROWS = 5
#: 交写结论的模型看的每格文字最多几个字
NARRATIVE_CELL = 150
CONTEXT_MAX = 120
#: 用户没点名列时表格的列（「命中处」「原因与措施」另加）
DEFAULT_KEYS = ("number", "machine", "desc")
#: 合计不超过这么多张时结论那一句点名每一张（总述「先给结论」：结果只有一两张时）
NAME_MAX = 2
#: 统计口径里的找法（总述「统计口径说明」文字查找一行）
METHODS = {"关键词": "关键词搜索", "话题": "涉及某个话题", "类似问题": "类似问题", "点名字段": "点名字段",
           "做法": "问做法"}
#: 国内停线状态为这两种时，重启方案与处理步骤里重启那三个环节不参与匹配（国内「停线」）
RESTART_HEADS = ("停线重启", "停线重启审核", "停线重启发起", "责任人填写重启方案")
STEP_COLUMNS = ("f_step_result", "f_step_opinion", "f_step_content")
_BY_LABEL = {d.label: d for d in Domain}


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
    """表格的列（内部键）与要不要加「原因与措施」：用户点名了列按用户说的，「命中处」照加。默认是问题编号、机型、
    问题描述、命中处、原因与措施（总述「表格列名」，决策 2026-11-04「表格里的原因与措施给摘要」）。"""
    p = step.get("params") or {}
    if p.get("columns"):
        keys, _missing = list_issues.columns_for(step)
        reasons = False
    else:
        keys = list(DEFAULT_KEYS)
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
    """一域的一句（张数都来自沙箱）：没有单的域在原位置说这一句；结论的模板句也用它。"""
    head = f"{label}{scope}"
    third = _n(seg, "g3")
    if tp.mode == "类似问题":
        if not third:
            return f"{head}按现象描述没有找到相近的问题"
        return f"{head}按现象描述列出 {third} 张最相近的问题"
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


def _what(tp: TermPlan) -> str:
    """各域小标题里「找到的是什么单」（决策 2026-11-03「回答骨架与排版」）。"""
    if tp.mode == "类似问题":
        return "最相近的问题"
    if tp.mode == "关键词":
        how = "同时出现" if tp.logic == "和" and len(tp.used) > 1 else ("出现任一个词" if len(tp.used) > 1 else "出现")
        return f"{tp.where}里{how}{'、'.join(f'「{w}」' for w in tp.used)}的单"
    if tp.intersect:
        return f"用{tp.approach}处理过、又涉及{tp.label}的单"
    if tp.grouped:
        return f"与{tp.label}有关的单"
    where = tp.where if tp.mode == "点名字段" else terms.MEASURE_SCOPE.split("（")[0]
    what = tp.label if tp.mode == "点名字段" else tp.approach
    return f"{where}里提到{what}的单"


def heading(tp: TermPlan, seg: Mapping[str, Any], label: str) -> str:
    """一域一节的小标题：这一域找到几张，另有可能相关的一并写上（张数都来自沙箱）。"""
    third = _n(seg, "g3")
    if tp.mode == "类似问题":
        return f"{label}{_what(tp)}（{third} 张）"
    more = f"，另有 {third} 张{columns.TEXT_GROUPS['3']}" if third else ""
    return f"{label}{_what(tp)}（{_n(seg, 'kw')} 张{more}）"


def captions(tp: TermPlan, seg: Mapping[str, Any], counts: Mapping[str, Any]) -> list[str]:
    """表格下面的几句：分组各几张与含义、两边都命中为 0 时各边几张、表格没列全（总述「涉及某个话题怎么找」）。"""
    out: list[str] = []
    kw, third = _n(seg, "kw"), _n(seg, "g3")
    if tp.grouped and kw:
        text = f"问题本身涉及的 {_n(seg, 'g1')} 张"
        if _n(seg, "g2"):
            text += f"、处理中提到的 {_n(seg, 'g2')} 张；处理中提到的多是顺带提到，请看每行命中的文字"
        out.append(text)
    if tp.intersect and not kw:
        out.append(f"用{tp.approach}处理过的 {int(counts.get('approach') or 0)} 张，"
                   f"涉及{tp.label}的 {int(counts.get('topic') or 0)} 张")
    if seg.get("truncated"):
        if tp.grouped:  # 前两组各给最近几张（S6b 评审 M1），分开说；哪组没列全由沙箱给
            listed = (f"问题本身涉及的{'最近 ' if seg.get('cut_g1') else ' '}{_n(seg, 'shown_g1')} 张"
                      + (f"、处理中提到的{'最近 ' if seg.get('cut_g2') else ' '}{_n(seg, 'shown_g2')} 张"
                         if _n(seg, "g2") else ""))
        else:
            listed = f"最近 {_n(seg, 'shown_kw')} 张直接提到的单"
        out.append(f"表格列出{listed}" + (f"，以及 {third} 张{columns.TEXT_GROUPS['3']}的单" if third else "")
                   + ("，完整清单见文末附件" if seg.get("exported") else ""))
    if third and tp.mode != "类似问题":
        out.append(f"{columns.TEXT_GROUPS['3']}的仅供参考，不保证找全")
    return out


def named(res: Mapping[str, Any], segs: Sequence[Mapping[str, Any]], sites: Any) -> str:
    """合计只有一两张时结论那一句点名的单（总述「先给结论」）：「[ZC…](链接)（机型 A920，已结案）」，几张用「、」连。
    编号、机型、结案没有都取自沙箱给的表格行；合计更多时为空。"""
    if int((res.get("totals") or {}).get("listed") or 0) > NAME_MAX:
        return ""
    out: list[str] = []
    for s in segs:
        dom = _BY_LABEL.get(str(s.get("domain")))
        table = s.get("table") or {}
        if s.get("empty") or dom is None:
            continue
        cols = [str(c) for c in table.get("columns") or []]
        machine = columns.shown("machine", dom)
        at = cols.index(machine) if machine in cols else None
        ids, opened = list(s.get("ids_shown") or []), list(s.get("open_shown") or [])
        for k, row in enumerate(table.get("rows") or []):
            bits: list[str] = []
            value = str(row[at]).strip() if at is not None and at < len(row) and row[at] is not None else ""
            if value:
                bits.append(value if value == "物料" else (f"机型{value}" if value == "未填" else f"机型 {value}"))
            if k < len(opened):
                bits.append("未结案" if opened[k] else "已结案")
            number = links.issue(sites, dom, row[0], ids[k] if k < len(ids) else None)
            out.append(number + (f"（{'，'.join(bits)}）" if bits else ""))
    return "、".join(out)


def fallback(tp: TermPlan, segs: Sequence[Mapping[str, Any]], scope: str, counts: Mapping[str, Any],
             named_text: str = "") -> str:
    """结论的模板句：只有一两张不写分析、模型没写出合格的结论时用（张数、单号都来自沙箱）。`named_text` 是合计只有
    一两张时要点名的单（`named`），接在这一句后面，问「单号是多少」时开头就是答案。"""
    tail = f"单号：{named_text}。" if named_text else ""
    labels = "、".join(str(s.get("domain")) for s in segs)
    hit = [s for s in segs if not s.get("empty")]
    miss = [str(s.get("domain")) for s in segs if s.get("empty")]
    if len(segs) == 1:
        seg = segs[0]
        return opening(tp, seg, str(seg.get("domain")), scope, counts.get(str(seg.get("domain"))) or {}) + "。" + tail
    if not hit:
        if tp.mode == "类似问题":
            return f"{labels}{scope}按现象描述都没有找到相近的问题。"
        return layout.sentences([f"{labels}{scope}{_what(tp)}都没有找到"]
                                + [opening(tp, s, str(s.get("domain")), "", counts.get(str(s.get("domain"))) or {})
                                   for s in segs if tp.intersect])
    who = "、".join(str(s.get("domain")) for s in hit)
    if tp.mode == "类似问题":
        numbers = [str(r[0]) for s in hit for r in (s.get("table") or {}).get("rows") or []]
        text = f"{who}{scope}有现象相近的问题" + (f"：{'、'.join(numbers)}" if len(numbers) <= 3 and not tail else "")
    else:
        total = sum(_n(s, "kw") for s in hit)
        third = sum(_n(s, "g3") for s in hit)
        text = f"{who}{scope}{_what(tp)}合计 {total} 张" + (f"，另有 {third} 张{columns.TEXT_GROUPS['3']}" if third else "")
    return text + (f"；{'、'.join(miss)}没有找到" if miss else "") + "。" + tail


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
            if len(label) > clarify.LABEL_MAX:
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
              ([errors.not_counted(label_denied)] if label_denied else []) + excluded + not_counted, kind="text")
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
    res, outcome_frames, counts, sem_notes, crowded = got
    segs = res.get("segments") or []
    out.ok = True
    out.empty = all((s.get("found") or 0) == 0 for s in segs)
    out.found_any = not out.empty
    out.truncated = any(s.get("truncated") for s in segs)
    out.refs = {f"{run.sid}.{k}": v for k, v in (res.get("refs") or {}).items()}
    out.refs[f"{run.sid}.issues"] = X.issues_from_frames(outcome_frames)
    out.extra = {"text": {"key": terms.key(run.step), "terms": list(dict.fromkeys(tp.used + tp.used_approach)),
                          "judged": tp.semantic is not None}}
    if not present:
        out.segs = list(segs)
        if caliber:
            _caliber(C, run, tp, segs, sem_notes, X, T.answer.similar_rows)
        return out
    head += sem_notes
    keys, reasons = table_keys(run.step, _labels(tp)[1])
    await X.fill_cells(T, segs, executed, desc="desc" in keys, reasons=reasons)
    # 提示行：无权与未计入的域、本次按哪些说法找、说法清单「说明」里那种问法的那一句（决策 2026-11-03「回答骨架与排版」）
    notice = [*head, used_text(tp), tp.asked_rule]
    by_domain = counts.get("by_domain") or {}
    scope = X._scope(X._time_text(run))
    conclusion = await _narrative(T, X, tp, res, segs, run, layout.sentences(notice),
                                  fallback(tp, segs, scope, by_domain, named(res, segs, T.sites)))
    out.events += layout.para(notice)
    out.events += _present(T, tp, segs, by_domain, conclusion, crowded_hint(run.step) if crowded else "")
    _caliber(C, run, tp, segs, sem_notes, X, T.answer.similar_rows)
    if res.get("exported"):
        await summaries.fill_exports(T.ctx, outcome_frames, executed)
        text = await export.save_lists(T.ctx, res["exported"], outcome_frames, EXPORT_FILENAME)
        T.record.exports.append(text)
        out.exported = text != f"{errors.EXPORT_FAILED}。"
    out.buttons = buttons(tp, res, counts, first_fields(T.seg or config_files.default(SEGMENTATION)))
    return out


async def _search(run: Any, T: Any, R: Ready) -> tuple[dict[str, Any], dict[str, pd.DataFrame], dict[str, Any], list[str],
                                                       bool] | None:
    """②–⑥：按词匹配、按意思找与判断、收拢。沙箱失败返回 None；最后一项是第三组候选是否太多（§5.4）。"""
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
    sem_frames, sem_notes, crowded = await _semantic(T, tp, executed, kw_frames, conditioned)
    labels, show_group = _labels(tp)
    keys, _reasons = table_keys(run.step, show_group)
    cols = {d.label: _domain_cols(keys, d, X.ADAPTERS[d].KEY_ALIAS) for d in executed}
    P2 = X._sandbox_params(run, executed, T.master.failed, T.access.text_search)
    P2["tm"] = {"labels": labels, "group_title": columns.TEXT_GROUP, "context_title": columns.TEXT_CONTEXT,
                "columns": cols, "table_rows": T.answer.table_rows, "export": (run.step.get("params") or {}).get("export") is True,
                "export_threshold": T.answer.export_threshold, "export_ok": True, "third_max": THIRD_MAX,
                "sim_max": T.answer.similar_rows, "sim": tp.mode == "类似问题",
                # 类似问题按自己的下限筛（只管类似问题），「可能相关」仍按 `rerank_score_threshold`（缺省不启用）
                "threshold": T.answer.similar_rerank_floor if tp.mode == "类似问题" else T.answer.rerank_score_threshold}
    # 结论的要点与需关注的单（类似问题不给，沙箱里判断；决策 2026-11-03「结论的要点与需关注的单」）
    P2["insight"] = insights.params(run.step, T.answer, T.today)
    datasets = {**R.frames, **{k: v for k, v in kw_frames.items() if k.startswith("kw_")}, **sem_frames}
    outcome2 = await runner.run(T.ctx, "text_merge", datasets, P2, return_frames=True)
    if not outcome2.ok:
        return None
    res = outcome2.result or {}
    if tp.semantic is not None and tp.mode == "类似问题":
        _log_sim_scores(tp.semantic["query"], res.get("segments") or [], T.answer.similar_rerank_floor)
    return res, dict(getattr(outcome2, "frames", None) or {}), counts, sem_notes, crowded


def _log_sim_scores(query: str, segs: Sequence[dict[str, Any]], floor: float) -> None:
    """类似问题的分数分布（探测 Z1 起记，留着供以后调下限）：每域一行日志，`scores` 是本步范围内全部候选的
    [重排分, 向量分, 判断]，按相近程度排；判断 1 为相近、0 为不相近、None 为没交去判断或那一批出错。列出的是判断为 1、
    重排分不低于 `floor` 的前 `listed` 张。只记分数，不记文字与单号；记完从段里拿掉，不进呈现与工作区。"""
    for seg in segs:
        scores = seg.pop("sem_scores", None)
        if scores is None:
            continue
        logger.info("factory_issue_sim_scores", domain=seg.get("domain"), query=query, listed=_n(seg, "g3"),
                    floor=floor, scores=scores)


async def _semantic(T: Any, tp: TermPlan, executed: Sequence[Domain], kw: Mapping[str, pd.DataFrame],
                    conditioned: bool) -> tuple[dict[str, pd.DataFrame], list[str], bool]:
    """③④⑤：每域检索一次（有带 ＊ 的候选时在候选里再检索一次排好），「可能相关」交模型判断。返回 (`sem_<域>` 帧,
    统计口径要写的几句, 候选是不是多到来不及逐张看完)。

    候选太多（设计 §5.4 第三种信号）：某域按意思找取回的张数到了上限（`top_n`，取回的就是最相近的那一批，后面可能
    还有），或带 ＊ 的候选并进来后超过判断上限 `judge_max`（多出的没判）。类似问题只判最相近的 `SIM_JUDGE` 张，不算。

    类似问题（决策 2026-11-03「类似问题逐张判断与分数下限」）：每域按平台给的先后取前 `SIM_JUDGE` 张交模型判断，
    判为相近、重排分不低于 `similar_rerank_floor` 的才列（下限在 ⑥ 的沙箱里比，`handle()` 不比大小，所以低于下限的
    也会交去判断）。某批判断出错时那几张按相近程度照列，开头与统计口径写明没能逐张判断。"""
    if tp.semantic is None:
        return {}, [], False
    S = tp.semantic
    sim = S["kind"] == "sim"
    judge_max = int(T.answer.judge_max)
    # 类似问题向重排要回全部候选的分（重排本来就给 `top_k` 张都打分，多回几行不多算）：表格仍由沙箱截到
    # `similar_rows` 张，全部分数进日志，供以后调下限（`_log_sim_scores`）
    top_n = semantic.TOP_K if sim else max(judge_max, THIRD_MAX)

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
    crowded = False
    for d in executed:
        got = found.get(d)
        if got is None:
            continue
        # 取回的张数到了上限：比的是张数与上限，不产出给用户的数（话术里不带数）
        crowded = crowded or (not sim and len(got.hits) >= top_n)
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
                crowded = crowded or len(items) > judge_max
        lists[d.label] = items
    llm = getattr(T.ctx, "llm", None)
    if sim:  # 类似问题：每域只判最相近的前 `SIM_JUDGE` 张（一批），重排分下限在 ⑥ 的沙箱里筛
        flags = await judge.judge(llm, str(S["query"]), {dom: [x[1] for x in items[:SIM_JUDGE]]
                                                          for dom, items in lists.items()}, SIM_JUDGE, similar=True)
    else:
        flags = await judge.judge(llm, tp.description, {dom: [x[1] for x in items] for dom, items in lists.items()},
                                  judge_max, tp.guides)
    unjudged = False
    frames: dict[str, pd.DataFrame] = {}
    for dom, items in lists.items():
        got_flags = flags.get(dom) or []
        rows = []
        for k, (i, t, r, s) in enumerate(items):
            flag = got_flags[k] if k < len(got_flags) else None
            judged = flag is not None
            related = bool(flag)
            if sim and k < SIM_JUDGE and not judged:  # 那一批出错：按相近程度照列，开头与统计口径写明
                related, unjudged = True, True
            rows.append([i, k, _clip(t), r, s, related, judged])
        frames["sem_" + dom] = pd.DataFrame(
            rows, columns=["issue_id", "rank", "context", "rerank", "score", "related", "judged"])
    if unjudged:
        notes.append(errors.SIMILAR_UNJUDGED)
    return frames, notes, crowded


#: 候选太多时建议加的条件，按这个顺序点用户还没给的前两个（总述「涉及某个话题怎么找」）
_NARROWERS = (("时间", None), ("机型", ("机型", "系列")), ("加工厂", ("加工厂",)))


def crowded_hint(step: Mapping[str, Any]) -> str:
    """第三组候选太多、来不及逐张看完（设计 §5.4）：建议加时间、机型等条件再查，只点用户还没给的条件。"""
    p = step.get("params") or {}
    fields = {str(f.get("field")) for f in p.get("filters") or [] if isinstance(f, dict)}
    has_time = any(isinstance(t, dict) and t.get("said") for t in p.get("time") or [])
    left = [name for name, fs in _NARROWERS if not (has_time if fs is None else fields & set(fs))][:2]
    tail = f"可以加上{'、'.join(left)}等条件再查" if left else "可以把条件再收窄一些再查"
    return f"「{columns.TEXT_GROUPS['3']}」一组的候选较多，来不及逐张看完，只看了最相近的一批；{tail}"


def _present(T: Any, tp: TermPlan, segs: Sequence[dict[str, Any]], counts: Mapping[str, Mapping[str, Any]],
             conclusion: str, hint: str = "") -> list[Event]:
    """结论 → 每域一节（小标题、表格、表格下面几句）→ 各节之后的提示（要增减说法、候选太多时加条件）。
    提示行在调用方（决策 2026-11-03「回答骨架与排版」）。"""
    from factory_issue_module.turn import execute as X

    events: list[Event] = [Event.delta(conclusion)]
    multi = len(segs) > 1
    for seg in segs:
        dom = X._BY_LABEL.get(str(seg.get("domain")), Domain.DOMESTIC)
        got = counts.get(dom.label) or {}
        if seg.get("empty"):  # 没有单的域：几域一起时原位置一句，只有这一域时由结论说
            if multi:
                events.append(Event.delta(opening(tp, seg, dom.label, "", got) + "。"))
            continue
        events.append(layout.heading(heading(tp, seg, dom.label)))
        events.append(tables.event(seg["table"], "", link_ids=seg.get("ids_shown") or None, domain=dom, sites=T.sites))
        events += layout.para(captions(tp, seg, got))
    # `hint`：第三组候选太多、来不及逐张看完时建议加条件（设计 §5.4）
    events += layout.para([adjust_hint(tp), hint])
    return events


_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def _cell(value: Any) -> str:
    """交写结论的模型看的一格：去掉 Markdown 链接只留文字，压成一行，最多 `NARRATIVE_CELL` 个字。"""
    flat = " ".join(_LINK.sub(r"\1", str(value if value is not None else "")).split())
    return flat if len(flat) <= NARRATIVE_CELL else flat[:NARRATIVE_CELL] + "…"


def listed_rows(segs: Sequence[Mapping[str, Any]]) -> str:
    """【列出的单】：每域表格前 `NARRATIVE_ROWS` 张的内容，末尾写结案没有（是否未结案由沙箱按行给）。"""
    lines: list[str] = []
    for s in segs:
        table = s.get("table") or {}
        cols = [str(c) for c in table.get("columns") or []]
        opened = list(s.get("open_shown") or [])
        for k, row in enumerate((table.get("rows") or [])[:NARRATIVE_ROWS]):
            cells = [f"{c}：{_cell(v)}" if i else _cell(v) for i, (c, v) in enumerate(zip(cols, row, strict=False))]
            state = ("未结案" if opened[k] else "已结案") if k < len(opened) else ""
            lines.append("｜".join([str(s.get("domain")), *cells, *([state] if state else [])]))
    return "\n".join(lines)


#: 写结论的【写法】（决策 2026-11-03「回答骨架与排版」）
SIM_GUIDE = ("用户想知道以前有没有出现过他描述的现象。【列出的单】是各域按相近程度排在最前、已经逐张看过是同一类现象的单。"
             "第一句回答有没有出现过；再点名最像的两三张：问题编号、一句话说清是什么现象、当时的原因与措施、结案没有。"
             "不按问题类型、机型分布分析。")


async def _narrative(T: Any, X: Any, tp: TermPlan, res: Mapping[str, Any], segs: Sequence[dict[str, Any]],
                     run: Any, note: str, fallback_text: str) -> str:
    """结论。合计只有一两张（09 文档「不分析的三种情形」）、各域都没有单时不调模型，用模板句；合计张数取自沙箱。
    看的是几域合计，不是每域：三域各一两张时合计已有好几张，结论要点名最像的几张（同清单的 `few_total`）。"""
    shown = [s for s in segs if not s.get("empty")]
    if not shown or int((res.get("totals") or {}).get("listed") or 0) <= 2:
        return fallback_text
    sim = tp.mode == "类似问题"
    facts: dict[str, Any] = {"找法": METHODS.get(tp.mode, tp.mode), ("现象描述" if sim else "话题或说法"): tp.label}
    for s in shown:
        f = s.get("facts") or {}
        if sim:  # 最相近的几张按问题类型、机型分布没有意义，只给张数与未结案几张
            facts[str(s.get("domain"))] = {"列出的张数": _n(s, "g3"), "其中未结案": f.get("未结案", 0)}
        elif tp.grouped:
            facts[str(s.get("domain"))] = {**f, "问题本身涉及": _n(s, "g1"), "处理中提到": _n(s, "g2"),
                                           columns.TEXT_GROUPS["3"]: _n(s, "g3")}
        else:
            facts[str(s.get("domain"))] = {**f, "按词找到": _n(s, "kw"), columns.TEXT_GROUPS["3"]: _n(s, "g3")}
    described = "；".join(tables.describe(heading(tp, s, str(s.get("domain"))), s["table"], s.get("shown"))
                          for s in shown)
    if sim:
        return await X._narrate(T, described, note, facts, fallback_text, X._time_text(run), rows=listed_rows(shown),
                                guide=SIM_GUIDE, dims=False)
    # 结论句 + 要点 + 需关注（决策 2026-11-03「结论的要点与需关注的单」）：要点与需关注的单由沙箱按直接找到的单给
    return await X._conclude(T, described, note, facts, fallback_text, X._time_text(run), res.get("insights"),
                             segs=shown)


def _caliber(C: cal.Caliber, run: Any, tp: TermPlan, segs: Sequence[dict[str, Any]], sem_notes: Sequence[str],
             X: Any, similar_rows: int) -> None:
    """统计口径（或查找说明）「文字查找」一项。按哪些词或说法找已写在开头的提示行（`used_text`），这里不重复
    （决策 2026-11-03「回答骨架与排版」）；类似问题没有说法，写「按现象描述找意思相近的单」。"""
    for seg in segs:
        X._add_caliber(C, run, seg, [], [])
    method = METHODS.get(tp.mode, tp.mode)
    words = ""
    if tp.mode == "类似问题":
        words = "按现象描述找意思相近的单"
        complete = f"逐张判断是同一类现象的才列出，每域最多 {similar_rows} 张、按相近程度排序，不保证完整"
    elif tp.user_words:
        complete = "列出全部命中的单"
    else:
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
