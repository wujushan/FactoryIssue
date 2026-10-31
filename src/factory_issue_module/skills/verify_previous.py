"""质疑上一轮（设计 §4.3 `verify_previous` 一行、§10；总述「接着上一轮问」）。

用户说「你确定吗」「好像不对」时，不因质疑改口：按工作区 `turn` 里上一轮的执行计划原样重查一遍（换算好的起止
日期照当时的，§10「沿用以执行计划为准」），域取「上一轮查过的域 ∩ 本轮可查的域」。

事件顺序：`delta`（复核结论：一致，或各域张数怎么变、哪些单多了少了）→ 有变化时 `table`（变化的单）→ 详情照这张单
现在的样子重新给出 → `delta`（当时按什么理解、按什么口径算）→ `suggestions`（上一轮的其他理解）。

- 比对在沙箱里做（`stats/tasks/verify.py`）：存下的单 ID、张数与重查的逐步逐域比，只比本轮可查的域。
- 上一轮查过、本轮已无权的域不重查，写明。上一轮计划读不到时由编排按「接不上上一轮」追问。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from forge_core.events import Event

from factory_issue_module.declarations import DOMAINS
from factory_issue_module.domains.base import Ask
from factory_issue_module.plan import clarify
from factory_issue_module.present import columns, links
from factory_issue_module.stats import runner
from factory_issue_module.turn import errors, execute, workspace

_BY_LABEL = {d.label: d for d in DOMAINS}
_COMPARED = ("list_issues", "aggregate", "lookup_numbers")
_TITLES = {"list_issues": "清单", "aggregate": "统计", "lookup_numbers": "按号查单", "issue_detail": "单张单详情"}
#: 变化的单那张表「变化」一列的说法（总述「表格列名」，`present/columns.py` 导入时核对）
TEXTS = {"added": columns.VERIFY_ADDED, "removed": columns.VERIFY_REMOVED}
CHANGE_COLUMN = columns.VERIFY_CHANGE
#: 有「这次没查到」的单时表格下面那句（总述「表格列名」）：只说可能的原因，不替用户猜是哪一种
REMOVED_NOTE = "这次没查到的单可能已删除，或这期间改了状态、类型等，已不符合上一轮的条件"


def _old(turn: Mapping[str, Any], results: Mapping[str, Any] | None, sid: str) -> dict[str, Any]:
    found = ((turn.get("steps") or {}).get(sid) or {}).get("found") or {}
    stored = ((results or {}).get("steps") or {}).get(sid) or {}
    out: dict[str, Any] = {}
    for dom in dict.fromkeys([*found, *stored]):
        item = stored.get(dom) or {}
        out[str(dom)] = {"ids": list(item.get("ids") or []), "numbers": list(item.get("numbers") or []),
                         "found": found.get(dom, 0)}
    return out


def _new(out: execute.StepOut, sid: str) -> dict[str, Any]:
    issues = out.refs.get(f"{sid}.issues") or {}
    found = out.refs.get(f"{sid}.found") or {}
    return {str(dom): {"ids": list((issues.get(dom) or {}).get("ids") or []),
                       "numbers": list((issues.get(dom) or {}).get("numbers") or []),
                       "found": found.get(dom, 0)} for dom in dict.fromkeys([*issues, *found])}


#: 结果太多、工作区只存了前一段时（`stats/tasks/verify.py` 的 `partial`）
PARTIAL_NOTE = "（结果较多，只比了张数，没有逐张比）"


def _line(item: Mapping[str, Any]) -> str:
    dom = item["domain"]
    tail = PARTIAL_NOTE if item["partial"] else ""
    if item["same"]:
        return f"{dom}：与上一轮一致，{item['new']} 张{tail}"
    if not item["had"]:
        return f"{dom}：上一轮没有存下这一域的结果，这次 {item['new']} 张"
    text = f"{dom}：上一轮 {item['old']} 张，这次 {item['new']} 张"
    if item["added_count"]:
        text += f"，新查到 {item['added_count']} 张"
    if item["removed_count"]:
        text += f"，{item['removed_count']} 张这次没查到"
    return text + tail


def denied_domains(turn: Mapping[str, Any], access: Any) -> list[str]:
    """上一轮查过、本轮已经没有权限的域。"""
    done = [str(d) for info in (turn.get("steps") or {}).values() for d in (info or {}).get("domains") or []]
    return [d for d in dict.fromkeys(done) if d in _BY_LABEL and not access.can(_BY_LABEL[d])]


async def run(T: execute.Turn, turn: Mapping[str, Any], results: Mapping[str, Any] | None
              ) -> tuple[list[Event], str, Ask | None]:
    """(事件, 本轮结局 `workspace.OUTCOME_*`, 重放时要追问的)。要追问时事件为空，由编排发 `clarify` 并写
    `pending_clarify`（问句全文是上一轮问句加选项）；每步都没查成时结局为「出错」，不覆盖 `turn`（§10）。"""
    plan = turn.get("plan") if isinstance(turn.get("plan"), dict) else {}
    previous_query = str(turn.get("query") or "")
    denied = denied_domains(turn, T.access)
    got = await execute.replay(execute.restrict_domains(plan, turn), workspace.stored_spans(turn), T, previous_query)
    if isinstance(got, Ask):
        return [], workspace.OUTCOME_CLARIFY, got
    head = [f"按上一轮的条件重新查了一遍（上一轮问的是「{previous_query}」）"]
    if denied:
        head.append(f"{'、'.join(denied)}现在没有查看权限，这次没有重查")
    events: list[Event] = [Event.delta("。".join(head) + "。\n\n")]
    by_sid = {r.sid: r for r in got.runs}
    # 重查算出的图数据照样存下（下一轮换图用），本轮不画
    T.record.charts = [x for sid, out in got.outs.items() if by_sid[sid].skill == "aggregate"
                       for x in (execute.seg_chart_item(by_sid[sid], seg) for seg in out.segs) if x is not None]
    compared = [sid for sid, out in got.outs.items() if by_sid[sid].skill in _COMPARED and out.domains]
    found = any(out.found_any for out in got.outs.values())
    if compared:
        P = {"steps": compared, "old": {sid: _old(turn, results, sid) for sid in compared},
             "new": {sid: _new(got.outs[sid], sid) for sid in compared},
             "domains": {sid: list(got.outs[sid].domains) for sid in compared},
             "cap": workspace.ID_CAP, "table_rows": T.answer.table_rows, "texts": TEXTS}
        outcome = await runner.run(T.ctx, "verify", {}, P)
        if not outcome.ok:
            events.append(Event.delta(f"{errors.SECTION_FAILED}。"))
        else:
            events += _present(T, outcome.result or {}, by_sid, len(compared) > 1)
    elif not any(by_sid[sid].skill == "issue_detail" for sid in got.outs):
        events.append(Event.delta(f"{errors.SECTION_FAILED}。"))
    for sid, out in got.outs.items():
        if by_sid[sid].skill == "issue_detail" and out.events:
            events.append(Event.delta("\n\n单张单详情按这张单现在的情况重新给出：\n\n"))
            events += out.events
    tail = []
    if plan.get("understanding"):
        tail.append(f"上一轮按「{str(plan['understanding']).rstrip('。')}」理解。")
    if got.caliber.counted:
        tail.append(got.caliber.text())
    if tail:
        events.append(Event.delta("\n\n" + "\n\n".join(tail)))
    recs = clarify.alternative_recommendations(plan.get("alternatives"))
    if recs:
        events.append(Event.suggestions(recs))
    if not any(out.ok for out in got.outs.values()):
        return events, workspace.OUTCOME_FAILED, None
    return events, (workspace.OUTCOME_FOUND if found else workspace.OUTCOME_EMPTY), None


def _present(T: execute.Turn, res: Mapping[str, Any], by_sid: Mapping[str, Any], multi: bool) -> list[Event]:
    lines: list[str] = []
    for k, step in enumerate(res.get("steps") or [], start=1):
        prefix = f"第 {k} 步（{_TITLES.get(by_sid[step['sid']].skill, '其他')}）" if multi else ""
        body = "；".join(_line(x) for x in step.get("domains") or [])
        if body:
            lines.append(f"{prefix}{'：' if prefix else ''}{body}。")
    rows: Sequence[Sequence[Any]] = res.get("rows") or []
    if not res.get("changed"):
        lines.append("结果与上一轮一致。")
    else:
        lines.append("与上一轮相比有变化，变化的单见下表（多半是这期间数据有更新）。" if rows else
                     "与上一轮相比张数有变化（多半是这期间数据有更新）。")
    events = [Event.delta("\n".join(lines))]
    if res.get("changed") and rows:
        if res.get("rows_more"):
            events.append(Event.delta(f"\n\n共 {res.get('rows_total', 0)} 张有变化，表格列出前 {T.answer.table_rows} 张。"))
        linked = []
        for row, (dom, pid) in zip(rows, res.get("row_ids") or [], strict=False):
            domain = _BY_LABEL.get(str(dom))
            linked.append([links.issue(T.sites, domain, row[0], pid), row[1], row[2]])
        events.append(Event.table([columns.shown("number"), columns.OWNER_DOMAIN, CHANGE_COLUMN], linked,
                                  title="与上一轮相比有变化的单"))
        if any(str(row[2]) == TEXTS["removed"] for row in rows):
            events.append(Event.delta(f"\n\n{REMOVED_NOTE}。"))
    return events
