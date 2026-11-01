"""只换呈现（设计 §4.3 `rerender` 一行；总述「什么时候配图」）。

- 图数据所属的域本轮都还可查：用工作区 `charts` 里上一轮的图数据按新图型重画，不取数。
- 有已无权的域，或图数据读不到：按上一轮的执行计划（`turn`）在本轮可查的域里重跑到沙箱为止，用新算出的图数据
  画，写明不再包含哪个域。重跑取过数，本轮覆盖 `turn`。
- 换成饼图而一张单可以计入多组、或图型用不上时照 `present/charts.py` 改图型并说明原因；只有一组的不画。
- 单张单详情没有图；上一轮是清单时也没有图可换，照实说。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from forge_core.events import Event

from factory_issue_module.declarations import DOMAINS
from factory_issue_module.domains.base import Ask
from factory_issue_module.skills import verify_previous
from factory_issue_module.turn import errors, execute, workspace

_BY_LABEL = {d.label: d for d in DOMAINS}
NO_CHART_DETAIL = "单张单详情没有图，没有可以换的图"
NO_CHART = "上一轮没有可以换图的统计（清单没有图）"
ONE_GROUP = "上一轮的统计只有一组，画不了图"
NO_PICTURE = "好的，这次不配图"


def _wanted(step: Mapping[str, Any]) -> str | None:
    chart = (step.get("params") or {}).get("chart")
    return chart if isinstance(chart, str) and chart.strip() else None


def _skills(turn: Mapping[str, Any]) -> list[str]:
    plan = turn.get("plan") if isinstance(turn.get("plan"), dict) else {}
    return [str(s.get("skill")) for s in plan.get("steps") or [] if isinstance(s, dict)]


def _draw(T: execute.Turn, items: Sequence[Mapping[str, Any]], user_chart: str | None) -> list[Event]:
    events: list[Event] = []
    for item in items:
        events += execute.chart_events(T, item, user_chart)
    return events


async def run(T: execute.Turn, step: Mapping[str, Any], turn: Mapping[str, Any] | None,
              stored: Mapping[str, Any] | None) -> tuple[list[Event], str, Ask | None]:
    """(事件, 本轮结局 `workspace.OUTCOME_*`, 重跑时要追问的)。

    不重跑（重画、不要图、没有图可换）时结局是「查到结果」：上一轮的结果还在，`turn` 不动，下一轮照样接上一轮。
    重跑时按重跑的结果定：要追问记「追问」（事件为空，由编排发 `clarify` 并写 `pending_clarify`），每步都没查成
    记「出错」、不覆盖 `turn`（§10）。"""
    found = workspace.OUTCOME_FOUND
    user_chart = _wanted(step)
    items = list((stored or {}).get("items") or [])
    if user_chart == "不要图":
        return [Event.delta(f"{NO_PICTURE}。")], found, None
    if items and all(_BY_LABEL.get(str(d)) is not None and T.access.can(_BY_LABEL[str(d)])
                     for item in items for d in item.get("domains") or []):
        events = _draw(T, items, user_chart)
        return (events or [Event.delta(f"{ONE_GROUP}。")]), found, None
    if not turn:
        return [Event.delta(f"{NO_CHART}。")], found, None
    skills = _skills(turn)
    if "aggregate" not in skills and "custom_stats" not in skills:
        return [Event.delta(f"{NO_CHART_DETAIL if 'issue_detail' in skills else NO_CHART}。")], found, None
    plan = turn.get("plan") if isinstance(turn.get("plan"), dict) else {}
    denied = verify_previous.denied_domains(turn, T.access)
    got = await execute.replay(execute.restrict_domains(plan, turn), workspace.stored_spans(turn), T,
                               str(turn.get("query") or ""))
    if isinstance(got, Ask):
        return [], workspace.OUTCOME_CLARIFY, got
    by_sid = {r.sid: r for r in got.runs}
    fresh = verify_previous.execute_charts(got, by_sid)  # 临时统计照存下的脚本重算（§5.5）
    T.record.charts = list(fresh)
    events: list[Event] = []
    if denied:
        events.append(Event.delta(f"按上一轮的条件重新统计，不再包含{'、'.join(denied)}（现在没有查看权限）。\n\n"))
    if not any(out.ok for out in got.outs.values()):
        return events + [Event.delta(f"{errors.SECTION_FAILED}。")], workspace.OUTCOME_FAILED, None
    drawn = _draw(T, fresh, user_chart)
    outcome = found if any(out.found_any for out in got.outs.values()) else workspace.OUTCOME_EMPTY
    return events + (drawn or [Event.delta(f"{ONE_GROUP}。")]), outcome, None
