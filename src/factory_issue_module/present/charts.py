"""图表（设计 §8.2；总述「初步分析维度」「什么时候配图」）。

`to_chart` 只认 `outcome.result` 为 `{"rows": [...]}`，只读 `ok`、`result`、`error` 三个属性：每段图构造一个只带这
三个属性的小对象再调 `ctx.stats.to_chart(…)`，只是搬数，不另算；不 import `forge_sandbox` 的 `SandboxOutcome`
（它在本仓只是 dev 依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_core.events import Event

from factory_issue_module import landed

_LABEL_TOP = {"series": {"label": {"show": True, "position": "top"}}}
_BAR_ONE = {**_LABEL_TOP, "legend": {"show": False}}
_BAR_TWO = {**_LABEL_TOP, "legend": {"bottom": 0}}
_PIE = {"series": {"radius": ["40%", "70%"], "label": {"formatter": "{b}：{c}"}}}
_LINE = {"series": {"symbol": "circle", "label": {"show": True}}}
_ROTATE = {"xAxis": {"axisLabel": {"interval": 0, "rotate": 30}}}
_TYPES = {"柱状": "bar", "饼图": "pie", "折线": "line"}
PIE_MAX = 8
PERIODS = ("年", "季度", "月", "周")


@dataclass
class _Rows:
    """`to_chart` 只读这三个属性。"""

    ok: bool
    result: dict[str, Any]
    error: str | None = None


def _dimension_chart(name: str) -> str | None:
    """总述「初步分析维度」里这个维度的图型。"""
    for dim in landed.analysis_dimensions():
        if dim.name == name:
            return dim.chart
    return None


def choose(dimension: str, groups: int, *, multi: bool, user_chart: str | None) -> tuple[str | None, str | None]:
    """(图型, 改图型时的说明)；不画时图型为 None。分组 2 组及以上才画；用户说「不要图」不画。"""
    if user_chart == "不要图" or groups < 2:
        return None, None
    if user_chart in _TYPES:
        kind = _TYPES[user_chart]
        if kind == "pie" and multi:
            return "bar", "一张单可以计入多组，各组之和大于总单数，画成饼图比例会失真，改用柱状图。"
        return kind, None
    if dimension in PERIODS:
        return ("line" if groups >= 3 else "bar"), None
    kind = _dimension_chart(dimension) or "bar"
    if kind == "pie" and (groups > PIE_MAX or multi):
        kind = "bar"
    if kind == "line" and groups < 3:
        kind = "bar"
    return kind, None


def choose_compare(groups: int, *, user_chart: str | None) -> tuple[str | None, str | None]:
    """比较两个时段：两段各一组柱子（分组柱状）；没有分组时横轴是这两段，各一根柱子。

    分组 2 组及以上才画（总述「什么时候配图」）。要折线照给；要饼图改柱状：两段各一组数，一张饼图放不下。
    """
    if user_chart == "不要图" or groups < 2:
        return None, None
    if user_chart == "折线":
        return "line", None
    if user_chart == "饼图":
        return "bar", "两个时段各有一组数，一张饼图放不下，改用柱状图。"
    return "bar", None


_MODEL_TYPES = {"bar": "bar", "line": "line", "pie": "pie"}


def choose_custom(prefer: str | None, groups: int, *, user_chart: str | None) -> tuple[str | None, str | None]:
    """临时统计（设计 §5.5）：模型给的图型只作首选，仍照总述「什么时候配图」：2 组及以上才画；时间点少于 3 个
    用柱状、不用折线；饼图超过 8 组改柱状。用户点名了图型照用户的（同 `choose`，临时统计的表不是一单多值的维度）。"""
    if user_chart == "不要图" or groups < 2:
        return None, None
    if user_chart in _TYPES:
        return _TYPES[user_chart], None
    kind = _MODEL_TYPES.get(str(prefer or ""))
    if kind is None:
        return None, None
    if kind == "pie" and groups > PIE_MAX:
        kind = "bar"
    if kind == "line" and groups < 3:
        kind = "bar"
    return kind, None


def style(kind: str, series_count: int, groups: int) -> dict[str, Any]:
    if kind == "pie":
        return _PIE
    if kind == "line":
        return _LINE
    out = dict(_BAR_TWO if series_count > 1 else _BAR_ONE)
    if groups > 6:
        out = {**out, **_ROTATE}
    return out


def event(stats: Any, kind: str, rows: list[dict[str, Any]], x_key: str, series: list[str], title: str) -> Event:
    """数字只从沙箱产出的行里搬（`ctx.stats.to_chart`）。"""
    spec = stats.to_chart(_Rows(ok=True, result={"rows": rows}), chart_type=kind, x_key=x_key,
                          series_keys=series, title=title, style=style(kind, len(series), len(rows)))
    return Event.chart(**spec)
