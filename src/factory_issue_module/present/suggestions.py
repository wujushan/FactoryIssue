"""答后建议的两类按钮怎么合（设计 §9.5）。

INFO 网页前端把按钮的 `query` 当按钮文字显示、点了照发（设计 §19「S5 提交后 INFO 前端按钮显示问题的处理」），
所以 `query` 写成短的、动作在前的说法，不拼本轮原话。

- 纠偏类，代码直出、排在前面：计划的 `alternatives`（「换个理解：…」，`plan/clarify.py::alternative_recommendations`）、
  第 13 条修一次仍不一致时的日期依据（「改按结案时间算」，`basis_switch`）、「本月比上月」的按上月同期比
  （`same_period`）、结果为空时的放宽与「最近」的另两个时间范围（`turn/execute.py`）、文字查找那几个、临时统计
  关掉或没算出来时的能力介绍按钮。点了照常规划。
- 接着问：代码列候选（`present/moves.py`）、模型挑（`present/suggest.py`），至多 `MODEL_MAX` 个，点了直接执行存下
  的计划（`turn/workspace.py::picked`）。结果为空时的放宽也在这一类（2026-11-03 起，按钮文字带预先查好的张数）。
- 按钮总数不超过 4 个，同一个问句只留一个；每项是 `{id, name, label, query}` 对象，`label` 不超过 15 个字。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from factory_issue_module.plan import clarify

MAX_BUTTONS = clarify.MAX_OPTIONS
#: 接着问至多几个
MODEL_MAX = 3
TEMPLATE_NAME = "接着问"
SAME_PERIOD = "按上月同期比"


def follow_up(query: str, label: str = "") -> dict[str, str]:
    """一个接着问按钮：`label` 是模型写的按钮文字（核过的，`present/suggest.py`），没有时把问句截到 15 个字。"""
    return {"id": "", "name": TEMPLATE_NAME, "label": label or clarify.button_label(query), "query": query}


def basis_switch(alternative: str) -> dict[str, str]:
    """第 13 条修一次仍不一致：另一种日期依据（「按结案时间算」→ 问句「改按结案时间算」）。"""
    return {"id": "", "name": clarify.ALTERNATIVE_NAME, "label": clarify.button_label(alternative),
            "query": "改" + alternative}


def same_period(query: str, said: str) -> dict[str, str]:
    """「本月比上月」：本月按月初到今天，上个月按完整自然月比；选项把原话里的「上个月」「上月」换成「上月同期」
    （上月 1 日到上月的今天这一天，`plan/timespan.py`）。`said` 只会是这两种说法（调用方查过），写明了年月的
    不替换；原话里找不到那段说法时问句写「改按上月同期比」。"""
    ask = query.replace(said, "上月同期", 1) if said and said in query else "改" + SAME_PERIOD
    return {"id": "", "name": clarify.ALTERNATIVE_NAME, "label": SAME_PERIOD, "query": ask}


def merge(*groups: Iterable[Mapping[str, str]], limit: int = MAX_BUTTONS) -> list[dict[str, str]]:
    """按顺序合并，同一个问句只留第一个，至多 `limit` 个，重新编号。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for rec in group:
            q = str(rec.get("query") or "").strip()
            if not q or q in seen:
                continue
            seen.add(q)
            out.append({**rec, "id": str(len(out) + 1)})
            if len(out) >= limit:
                return out
    return out
