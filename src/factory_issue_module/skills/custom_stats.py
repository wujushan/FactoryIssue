"""临时统计（设计 §4.3 `custom_stats` 一行、§5.5、§8.1；总述「回答怎么组织」「临时统计」）。

一步的流程：
1. 管理员关掉了（`answer_params.toml` 的 `custom_stats_enabled = false`），或这一轮已经做过一个临时统计：只答一句，
   不取数、不调模型。
2. 条件照统计那一套对库（第 6 步已做），各域并行取数（`turn/execute.py::_frames`）。
3. 沙箱 ①（`stats/tasks/custom_frame.py`）：派生、筛选，整理成一张一单一行、带「所属域」的帧，经数据帧通道回传，
   另给样例、各域张数与结果单。0 张时照实说没有，不调模型。
4. 脚本：上一轮存下了要算的同一件事（`describe` 相同）的脚本时照它算，不调模型（质疑重查、换图、「那上个月呢」）；
   否则模型写（system 固定，列说明、样例与要算什么在 user）。AST 检查（`stats/custom.py::check_script`）。
5. 沙箱 ②（外壳 `stats/tasks/custom_run.py`）：这张帧作为数据集 `issues` 传入。形状检查（`check_result`）。
   AST 检查、运行出错、形状检查任一不过，把错处交模型修一次（三处合计一次）；仍不过答「没算出来」。
6. 呈现：开头「以下为临时统计」与张数 → 表 → 图（模型给的图型只作首选，`present/charts.py::choose_custom`）→ 海外
   不良率原文（本步有海外、脚本用到不良率时）→ 分析段 → 统计口径（时间、域、条件、脚本用到的派生列的口径、
   「统计方法」）。

数字都来自两次沙箱调用：张数来自 ①，表与图的数来自 ②；`handle()` 一侧只搬值。脚本是模型输出，随审计归档
`llm.json` 留存，另存进工作区 `turn.steps`（§10）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import pandas as pd
import structlog
from forge_core.events import Event

from factory_issue_module import landed
from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.domains import brazil, domestic, overseas
from factory_issue_module.present import caliber as cal
from factory_issue_module.present import columns, insights, layout, tables
from factory_issue_module.skills import aggregate
from factory_issue_module.stats import custom as checks
from factory_issue_module.stats import runner
from factory_issue_module.turn import errors, greeting

logger = structlog.get_logger(__name__)

SAMPLE_ROWS = 3
#: AST 检查、运行出错、形状检查三处合计修一次（§1.2）
REPAIRS = 1
_CHAT_KW: dict[str, Any] = {"temperature": 0}
#: FakeLLM 与 spike 按 system 里的这段文字认临时统计的调用
ROUTE_MARKER = "在沙箱里运行的 Python 统计脚本"

_ADAPTERS = {Domain.DOMESTIC: domestic, Domain.BRAZIL: brazil, Domain.OVERSEAS: overseas}


@dataclass(frozen=True)
class Col:
    """输入帧的一列：显示名、类型、各域从视图的哪一列来（没有的域这一列为空）。"""

    name: str
    kind: str  # text / multi / date / bool / num / int / domain
    src: dict[str, str] = field(default_factory=dict)


def _all(key: str) -> dict[str, str]:
    return {d.label: key for d in DOMAINS}


def _only(key: str, *domains: Domain) -> dict[str, str]:
    return {d.label: key for d in domains}


def _metric(key: str, metric: str) -> dict[str, str]:
    """本域能算这个指标时才有这一列（各适配器的 `TRAITS`）。"""
    return {d.label: key for d, a in _ADAPTERS.items() if metric in a.TRAITS["metrics"]}


_s = columns.shown
_CN, _BR, _OS = Domain.DOMESTIC, Domain.BRAZIL, Domain.OVERSEAS

#: 输入帧的列（§5.5）：列名是显示名（`present/columns.py`），值取自三域派生后的视图。单 ID、权限承载列、内部编码
#: 与 `_` 开头的辅助列本身都不进这张帧；下划线开头的视图列只作取值来源（如机型取 `_machines` 用「、」连成一格）
COLUMNS: tuple[Col, ...] = (
    Col(_s("number"), "text", _all("number")),
    Col(columns.OWNER_DOMAIN, "domain"),
    Col(_s("add_date"), "date", _all("_add")),
    Col(_s("found_date"), "date", _all("_found")),
    Col(_s("stat_date", _BR), "date", _only("_stat", _BR)),
    Col(_s("machine"), "multi", _all("_machines")),
    Col(_s("series"), "multi", _only("_series", _CN, _BR)),
    Col(_s("type"), "text", _all("type")),
    Col(_s("factory"), "multi", _all("factory")),
    Col(_s("level"), "text", _all("level")),
    Col(_s("status"), "text", _all("status")),
    Col(columns.STAGE, "multi", _all("_stages")),
    Col(columns.CLOSED, "bool", _all("_done")),
    Col(_s("close_time"), "date", _all("_close")),
    Col(columns.CLOSE_DAYS, "int", _metric("_close_days", "结案周期")),
    Col(columns.STOPPED_EVER, "bool", _all("_stopped_ever")),
    Col(columns.STOPPED, "bool", _all("_stopped_now")),
    Col(_s("stop_date"), "date", _all("_stop")),
    Col(_s("restart_date"), "date", _only("_restart", _CN, _OS)),
    Col(columns.STOP_DAYS, "int", _metric("_stop_days", "停线时长")),
    Col(_s("follower"), "multi", {_CN.label: "follower", _BR.label: "follower", _OS.label: "_follower_names"}),
    Col(_s("follow_dept"), "text", _all("follow_dept")),
    Col(_s("current_people"), "multi", _only("_current_names", _CN, _OS)),
    Col(_s("resp_dept"), "multi", _only("_resp_dept_names", _CN)),
    Col(_s("bad_qty"), "num", _all("_bad")),
    Col(_s("prod_qty"), "num", _only("_den", _CN)),
    Col(_s("impact_qty"), "num", _all("_impact")),
    Col(columns.RATE, "num", _only("_rate_value", _CN, _BR)),
    Col(_s("inv_code"), "multi", _all("inv_code")),
    Col(_s("inv_name"), "multi", _all("inv_name")),
    Col(_s("ven_name"), "multi", _all("ven_name")),
    Col(columns.COST_USD, "num", _only("_usd", _BR)),
    Col(columns.COST_BRL, "num", _only("_brl", _BR)),
    Col(columns.DEBIT, "num", _only("_debit", _BR)),
    Col(columns.HAS_COST, "bool", _only("_has_cost", _BR)),
)
#: 口径函数要的几列名（外壳写进沙箱的 `CS_NAMES`；分母国内是生产数量、巴西是影响数量，总述「汇总不良率」）
NAMES = {"domain": columns.OWNER_DOMAIN, "bad": _s("bad_qty"),
         "den": {_CN.label: _s("prod_qty"), _BR.label: _s("impact_qty")}}
#: 脚本用到这些列或口径函数时，统计口径补上对应的一项（§5.5「统计口径照统计那一套」）
RATE_WORDS = (columns.RATE, "合计不良率")


def frame_columns(executed: Sequence[Domain], blind: Mapping[str, Sequence[str]]) -> list[dict[str, Any]]:
    """本步的帧有哪些列：只留本步计入的域里有来源的；靠没取到的主数据才写得出来的列（`blind`）不进帧。"""
    labels = {d.label for d in executed}
    out: list[dict[str, Any]] = []
    for c in COLUMNS:
        if c.kind == "domain":
            out.append({"name": c.name, "kind": c.kind, "src": {}})
            continue
        src = {d: k for d, k in c.src.items() if d in labels and k not in set(blind.get(d) or ())}
        if src:
            out.append({"name": c.name, "kind": c.kind, "src": src})
    return out


_TYPE_TEXT = {"text": "文本", "multi": "文本，一单多个时用「、」连接", "date": "日期", "bool": "是否（True / False）",
              "num": "数", "int": "整数", "domain": "文本"}
_PAREN = re.compile(r"（.*?）")


@cache
def glossary_note(name: str) -> str:
    """列说明取自术语表（`glossary.md`）：列名（去掉括号里的单位）是规范词或别称时取它口径定义的第一句（后面多是
    怎么按它筛、怎么对名字，帧里的值已经派生好，用不上）；否则取某条口径定义里以这个列名开头的那一句（「停线时长 =
    重启日期 − 停线日期」）；都没有时为空。不在代码里另写一份口径。"""
    base = _PAREN.sub("", name).strip()
    terms = landed.glossary()
    for term in terms:
        if base == term.term or base in [_PAREN.sub("", a).strip() for a in term.aliases]:
            return term.definition.split("。")[0].strip()
    for term in terms:
        for sentence in re.split(r"[。；]", term.definition):
            if sentence.strip().startswith(base):
                return sentence.strip()
    return ""


def describe_columns(cols: Sequence[Mapping[str, Any]], executed: Sequence[Domain]) -> list[tuple[str, str, str]]:
    """【数据列】：（列名, 类型, 说明）。说明是这一列哪些域有，加术语表的口径定义。"""
    labels = [d.label for d in executed]
    out: list[tuple[str, str, str]] = []
    for c in cols:
        notes: list[str] = []
        if c["kind"] == "domain":
            notes.append("本次有：" + "、".join(labels))
        else:
            have = [d for d in labels if d in c["src"]]
            if len(have) < len(labels):
                notes.append(f"只有{'、'.join(have)}有，其余为空")
            if glossary_note(c["name"]):
                notes.append(glossary_note(c["name"]))
        out.append((c["name"], _TYPE_TEXT[c["kind"]], "；".join(notes) or "—"))
    return out


# ---------------------------------------------------------------------------- 提示（§5.6：system 固定，会变的放 user）


@cache
def stats_system() -> str:
    imports = "、".join(m for m in sorted(checks.ALLOWED_IMPORTS) if not m.startswith("_") and m not in ("time", "dateutil"))
    return f"""你为「制程问题查询助手」写一段在沙箱里运行的 Python 统计脚本。程序已经按用户的条件取好了单、按口径算好了派生的列；你只在这张表上计数、分组、排序。
- 脚本必须在最外层定义 def run(data):，data["issues"] 是一个 pandas DataFrame，一张单一行，列见【数据列】。pd、np 可以直接用。
- 只能 import：{imports}。不能读写文件，不能联网，不能定义 class，不能用 open、eval、exec、getattr、hasattr、vars、globals、type，也不能访问双下划线开头的属性。
- 下面这些口径函数已经定义好，直接调用即可，不要重新定义：
```python
{runner.helper_doc(checks.HELPERS)}
```
- 用法：
  - 标了「一单多个时用「、」连接」的列，按它的取值统计时先用 拆多值，一单在它的每个值下各计一次。
  - 要合计不良率时用 合计不良率，一个域调用一次（按「所属域」分开）；不要自己把不良数量、生产数量相加再除。
  - 结案时间、结案周期、停线时长、处理环节这些列已经按口径算好，直接用，不要从别的列推。
  - 空值（None、NaN、NaT）不当成 0：计数、分组时不计入，要单列时写成「未填」一组。
  - 【要算什么】没说的条件不要自己加，表里的单已经按用户的条件筛好了。
- 返回值必须是 dict，只有三个键：{{"columns": [列名, …], "rows": [[值, …], …], "chart": {{"type": "bar 或 line 或 pie 或 none", "x": 横轴那一列的列名, "series": [数值列的列名, …]}}}}。
  - columns 是表头，用中文业务说法，计数列叫「单数」，不要用英文或代码名。
  - rows 每行的值个数等于 columns；值只能是 int、float、str 或 None；日期写成「YYYY-MM-DD」文本；小数保留 2 位以内。
  - rows 按要看的顺序排好：时间按先后，其余按数值从大到小、同值按名称。不超过 {checks.ROWS_MAX} 行，多了请按更粗的粒度汇总。
  - chart：只有一组或只有一个数时 type 写 "none"；按时间先后的用 line，看各类占比且不超过 8 组的用 pie，其余用 bar。
- 只输出代码，放在一个 ```python 代码块里。"""


def stats_user(describe: str, query: str | None, cols: Sequence[tuple[str, str, str]], sample: Sequence[Mapping]) -> str:
    lines = "\n".join(f"- {name}（{kind}）：{note}" for name, kind, note in cols)
    head = f"【要算什么】{describe}\n" + (f"【用户问题】{query}\n" if query else "")
    return f"{head}【数据列】\n{lines}\n【样例行】{json.dumps(list(sample), ensure_ascii=False, default=str)}"


def repair_user(problems: Sequence[str]) -> str:
    return "脚本没有通过检查：\n" + "\n".join(f"- {p}" for p in problems) + "\n请修正后重新给出完整脚本，只输出代码。"


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


# ---------------------------------------------------------------------------- 脚本：照存下的跑，或模型写


async def _try(ctx: Any, code: str, frame: pd.DataFrame) -> tuple[dict | None, list[str]]:
    """AST 检查 → 沙箱 ② → 形状检查。返回 (整理后的返回值, 问题)。"""
    problems = checks.check_script(code)
    if problems:
        return None, problems
    outcome, offset = await runner.run_custom(ctx, code, frame, {"names": NAMES})
    if not outcome.ok:
        lines = code.strip("\n").count("\n") + 1  # 与 `runner.custom_script` 拼进去的模型代码同一段
        return None, ["脚本运行出错：\n" + checks.model_error(outcome.error or "", offset, lines)]
    out = (outcome.result or {}).get("out") if isinstance(outcome.result, dict) else None
    problems = checks.check_result(out)
    return (out if not problems else None), problems


async def write_and_run(llm: Any, ctx: Any, describe: str, query: str | None, cols: Sequence[tuple[str, str, str]],
                        sample: Sequence[Mapping], frame: pd.DataFrame) -> tuple[str | None, dict | None]:
    """模型写脚本并跑；不过时带着错处修一次。返回 (脚本, 返回值)；修一次仍不过、调用出错时为 (None, None)。"""
    if llm is None:
        return None, None
    messages = [{"role": "system", "content": stats_system()},
                {"role": "user", "content": stats_user(describe, query, cols, sample)}]
    for attempt in range(1 + REPAIRS):
        try:
            text = _content(await llm.chat(messages, **_CHAT_KW))
        except Exception as exc:  # noqa: BLE001 —— 写脚本的调用出错：答没算出来，异常只进日志
            logger.warning("factory_issue_custom_llm_failed", attempt=attempt + 1, error=type(exc).__name__)
            return None, None
        code = checks.extract_code(text)
        out, problems = await _try(ctx, code, frame)
        if out is not None:
            return code, out
        logger.info("factory_issue_custom_rejected", attempt=attempt + 1, problems=len(problems),
                    first=(problems[0] if problems else "")[:200])
        messages = [*messages[:2], {"role": "assistant", "content": text}, {"role": "user", "content": repair_user(problems)}]
    return None, None


def stored_for(T: Any, describe: str) -> str | None:
    """上一轮存下的、要算的是同一件事的脚本（§10 `turn.steps` 的 `custom`）。"""
    want = describe.strip()
    for item in getattr(T, "scripts", None) or ():
        if str(item.get("describe") or "").strip() == want and item.get("script"):
            return str(item["script"])
    return None


# ---------------------------------------------------------------------------- 一步


def describe_of(step: Mapping[str, Any]) -> str:
    return str(((step.get("params") or {}).get("describe")) or "").strip()


def _uses_rate(code: str) -> bool:
    names = checks.referenced(code)
    return any(w in names for w in RATE_WORDS) or any("不良率" in n for n in names if isinstance(n, str))


def _caliber_items(code: str, ds: Sequence[str], raw: Mapping[str, Any]) -> list[str]:
    """脚本用到的派生列与口径函数 → 统计口径里对应的那几项（照统计那一套的模板，§8.4）。"""
    used = checks.referenced(code)

    def has(*names: str) -> bool:
        return any(n in used for n in names)

    out: list[str] = []
    if has(columns.CLOSED):
        out.append(cal.closed(ds))
    if has(columns.STOPPED):
        out.append(cal.stopped(ds))
    if has(columns.STOPPED_EVER):
        out.append(cal.STOPPED_EVER)
    if has(_s("close_time"), columns.CLOSE_DAYS):
        out.append(cal.close_time(ds))
        n = raw.get("没有结案时间")
        if isinstance(n, int) and n:
            out.append(cal.no_close_time(n))
    if has(columns.STOP_DAYS):
        out.append(cal.stop_days(ds))
    if _uses_rate(code):
        out.append(cal.rate(ds))
    if has(_s("follower"), _s("follow_dept")):
        out.append(cal.follow(ds))
    if has(_s("resp_dept")):
        out.append(cal.resp_dept(ds))
    if has(_s("current_people")):
        out.append(cal.current(ds))
    if has(columns.STAGE):
        out.append(cal.stages(ds))
    if has(_s("level")):
        out.append(cal.level(ds))
    if has(columns.COST_USD, columns.COST_BRL, columns.HAS_COST):
        out.append(cal.COST)
    if has(columns.DEBIT):
        out.append(cal.DEBIT)
    return out


def chart_item(out: Mapping[str, Any], domains: Sequence[str], title: str) -> dict[str, Any] | None:
    """图的数据（沙箱结果原样，行写成字典）：本轮画图用，也存进工作区 `charts` 给换图用。`x`、`series` 不在表里
    （模型写了 none）时没有图数据。"""
    chart = out.get("chart") or {}
    cols = list(out.get("columns") or [])
    x, series = chart.get("x"), list(chart.get("series") or [])
    if x not in cols or not series or any(s not in cols for s in series):
        return None
    rows = [dict(zip(cols, row, strict=False)) for row in out.get("rows") or []]
    return {"domains": list(domains), "title": title, "dimension": str(x), "series": series, "rows": rows,
            "compare": False, "name": str(x), "groups": len(rows), "multi": False, "custom": True,
            "prefer": str(chart.get("type") or "none")}


async def run_step(run: Any, T: Any, refs: Mapping[str, Any], C: cal.Caliber, notes: list[str],
                   *, used: bool = False, mode: str = "full") -> Any:
    """执行一步临时统计，返回 `turn/execute.py::StepOut`。

    `mode`：`full` 照常呈现；`replay` 只跑到沙箱为止、不调模型（质疑重查、换图的重放：照存下的脚本算，没有存下的
    只跑沙箱 ① 给张数与结果单）；`count` 只跑沙箱 ①（结果为空时预查放宽选项的张数）。`used` 是这一轮已经做过一个
    临时统计（每轮至多一个，§1.2）。"""
    from factory_issue_module.turn import execute as X

    out = X.StepOut()
    describe = describe_of(run.step)
    if mode == "full" and not T.answer.custom_stats_enabled:
        out.events.append(Event.delta(f"{errors.CUSTOM_DISABLED}。"))
        out.buttons, out.handled = greeting.buttons(T.access), True
        return out
    if mode == "full" and used:
        out.events.append(Event.delta(f"{errors.CUSTOM_SECOND}。"))
        out.handled = True
        return out
    if run.deferred:
        ask = X._resolve(run, T, refs)
        if ask is not None:
            out.events.append(Event.delta(f"{ask.question}\n\n"))
            return out
    frames, denied_now, problems, executed = await X._frames(run, T)
    for d in denied_now:
        T.access = T.access.without(d)
        run.dsteps.pop(d, None)
    label_denied = [d.label for d in [*run.denied, *denied_now]]
    excluded = list(dict.fromkeys(x for d in run.domains if d in run.dsteps for x in run.dsteps[d].excluded))
    not_counted = ([errors.not_counted(label_denied)] if label_denied else []) + excluded
    head = list(notes) + not_counted
    for d in executed:
        head += run.dsteps[d].notes + run.dsteps[d].skipped
    head += problems
    out.domains = [d.label for d in executed]
    if not executed:
        if head and mode == "full":
            out.events.append(Event.delta("。".join(dict.fromkeys(head)) + "。"))
        out.ok = (bool(label_denied) or bool(excluded)) and not problems
        return out
    P = X._sandbox_params(run, executed, T.master.failed, T.access.text_search)
    cols = frame_columns(executed, P["blind"])
    P["cs"] = {"columns": cols, "sample_rows": SAMPLE_ROWS, "add_col": _s("add_date"), "number_col": _s("number"),
               "table_rows": T.answer.table_rows,
               "rate_text": [d.label for d in executed if _ADAPTERS[d].TRAITS.get("rate") == "text"]}
    if mode == "full":  # 结论的要点与需关注的单（决策 2026-11-03「结论的要点与需关注的单」）
        P["insight"] = insights.params(run.step, T.answer, T.today)
    first = await runner.run(T.ctx, "custom_frame", frames, P, return_frames=True)
    if not first.ok:
        if mode == "full":
            out.events.append(Event.delta("。".join([*dict.fromkeys(head), errors.SECTION_FAILED]) + "。"))
        return out
    res = first.result or {}
    got_frames = dict(getattr(first, "frames", None) or {})
    total = int(res.get("total") or 0)
    out.refs = {f"{run.sid}.issues": X.issues_from_frames(got_frames), f"{run.sid}.found": dict(res.get("found") or {}),
                f"{run.sid}.count": total}
    out.ok, out.empty, out.found_any = True, total == 0, total > 0
    time_text = X._time_text(run)
    if mode == "count":
        return out
    _add_caliber(C, run, executed, not_counted, time_text, res)
    if total == 0:
        if mode == "full":
            future = any(s.future for s in run.spans)
            text = f"{'、'.join(out.domains)}{X._scope(time_text)}没有查到单" + ("，这段时间还没到" if future else "")
            out.events.append(Event.delta("。".join([*dict.fromkeys(head), text]) + "。"))
        return out
    frame = got_frames.get("frame")
    stored = stored_for(T, describe)
    code, result = None, None
    if stored is not None:
        result, why = await _try(T.ctx, stored, frame)
        code = stored if result is not None else None
        if result is None:
            logger.info("factory_issue_custom_stored_failed", problems=len(why))
    if result is None and mode == "full":
        code, result = await write_and_run(getattr(T.ctx, "llm", None), T.ctx, describe, T.query,
                                           describe_columns(cols, executed), res.get("sample") or [], frame)
    if result is None or code is None:
        if mode == "full":
            out.events.append(Event.delta("。".join([*dict.fromkeys(head), errors.CUSTOM_FAILED]) + "。"))
            out.buttons, out.handled, out.ok = greeting.buttons(T.access), True, False
        else:
            out.ok = bool(out.refs)  # 重放：张数与结果单照比，图没有
        return out
    out.extra["custom"] = {"describe": describe, "script": code}
    ds = [d.label for d in executed]
    for text in _caliber_items(code, ds, res.get("caliber") or {}):
        C.item(text)
    C.item(errors.CUSTOM_METHOD)
    suffix = f"：{time_text}" if time_text else ""
    title = f"临时统计{suffix}"
    item = chart_item(result, ds, title)
    if item is not None:
        out.extra["chart"] = item
    if mode != "full":
        return out
    out.events += await _present(run, T, result, res, ds, head, time_text, title, item, code)
    return out


def _add_caliber(C: cal.Caliber, run: Any, executed: Sequence[Domain], not_counted: Sequence[str],
                 time_text: str | None, res: Mapping[str, Any]) -> None:
    C.domains([d.label for d in executed], not_counted)
    raw = res.get("caliber") or {}
    C.time(cal.time_range(time_text, aggregate.basis_of(run.step), [tuple(x) for x in raw.get("未计入") or []]))
    for d in executed:
        for name, value in run.dsteps[d].echo:
            C.condition(name, value)
        for text in run.dsteps[d].skipped:
            C.item(text)


def opening(res: Mapping[str, Any], ds: Sequence[str], scope: str) -> str:
    """结论的模板句：计入的张数（几域时各域张数，数都来自沙箱 ①）。只有一两行、模型没写出合格的结论时用。"""
    found = res.get("found") or {}
    text = f"{'、'.join(ds)}{scope}共 {res.get('total', 0)} 张单"
    if len(ds) > 1:
        text += "（" + "、".join(f"{d} {found.get(d, 0)} 张" for d in ds) + "）"
    return text + "。"


def heading(res: Mapping[str, Any], ds: Sequence[str]) -> str:
    """结果表那一节的小标题：计入几张单，几域时各域几张（决策 2026-11-03「回答骨架与排版」）。"""
    found = res.get("found") or {}
    per = "：" + "、".join(f"{d} {found.get(d, 0)} 张" for d in ds) if len(ds) > 1 else ""
    return f"临时统计结果（计入 {res.get('total', 0)} 张单{per}）"


async def _present(run: Any, T: Any, result: Mapping[str, Any], res: Mapping[str, Any], ds: Sequence[str],
                   head: Sequence[str], time_text: str | None, title: str, item: Mapping[str, Any] | None,
                   code: str) -> list[Event]:
    """提示行（「以下为临时统计」在最前）→ 结论 → 结果表一节（小标题、表、图）。"""
    from factory_issue_module.turn import execute as X

    notice = [errors.CUSTOM_HEAD, *head]
    table = {"columns": list(result.get("columns") or []), "rows": [list(r) for r in result.get("rows") or []]}
    fallback = opening(res, ds, X._scope(time_text))
    text = fallback
    if len(table["rows"]) > 2:  # 只有一两行时分析就是复述（09 文档「不分析的三种情形」）
        facts = {"总单数": res.get("total", 0), "各域单数": [[d, (res.get("found") or {}).get(d, 0)] for d in ds],
                 "临时统计的结果": {"列": table["columns"], "行": table["rows"]}}
        text = await X._conclude(T, tables.describe(heading(res, ds), table, None), layout.sentences(notice), facts,
                                 fallback, time_text, res.get("insights"))
    events = [*layout.para(notice), Event.delta(text), layout.heading(heading(res, ds)), tables.event(table, "")]
    if item is not None:
        T.record.charts.append(dict(item))
        events += X.chart_events(T, item, None)
    lists = {d: rl for d, rl in (res.get("rate_lists") or {}).items() if d in ds}
    if lists and _uses_rate(code):
        events += X._rate_lists({"rate_lists": lists}, T, f"：{time_text}" if time_text else "")
    return events
