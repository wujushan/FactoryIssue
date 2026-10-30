"""答后建议（设计 §9.5）。

INFO 网页前端把按钮的 `query` 当按钮文字显示、点了照发（设计 §19「S5 提交后 INFO 前端按钮显示问题的处理」），
所以 `query` 写成短的、动作在前的说法，不再拼本轮原话；接的是哪一问由规划器从历史与上一轮计划看出来。

- 先放其他理解：计划的 `alternatives`（「换个理解：…」，`plan/clarify.py::alternative_recommendations`）、
  第 13 条修一次仍不一致时的日期依据（「改按结案时间算」）、「本月比上月」的按上月同期比（原话里的「上个月」
  换成「上月同期」）。
- 再放结果为空时的放宽选项、「最近」的另两个时间范围（`turn/execute.py` 预先查好张数；原话里的时间说法换掉）。
- 再按技能补模板按钮：清单后「按问题类型统计这些单」「把这些单全部导出」，单维度汇总后「列出惠州百富的单」
  （第一名的取值），只有一张单的详情、按号查单后「ZC2601001 的完整处理过程」「ZC2601001 的原因与措施」。
- 不带任何条件的清单：模板按钮换成能力介绍的 3 个按钮。
- 按钮总数不超过 4 个，同一个问句只留一个；每项是 `{id, name, label, query}` 对象，`label` 不超过 15 个字。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from factory_issue_module.domains import base, enums
from factory_issue_module.plan import clarify, schema

MAX_BUTTONS = clarify.MAX_OPTIONS
TEMPLATE_NAME = "接着问"

STAT_BY_TYPE = "按问题类型统计这些单"
EXPORT_ALL = "导出全部"
EXPORT_ALL_QUERY = "把这些单全部导出"
FULL_PROCESS = "看完整处理过程"
REASONS = "看原因与措施"
SAME_PERIOD = "按上月同期比"
#: 「列出第一名的单」至多点名几个并列第一的取值；更多时不给这个按钮
TOP1_MAX = 3
#: 第一名是这些取值时不给「列出…的单」（不是用户能拿来筛的说法）
_TOP1_PLACEHOLDERS = ("未填", enums.OS_UNKNOWN_TYPE)

_PROCESS_ASPECTS = ("完整处理过程", "驳回")
_REASON_ASPECTS = ("原因", "措施", "处理结果")


def template(label: str, query: str) -> dict[str, str]:
    return {"id": "", "name": TEMPLATE_NAME, "label": clarify.button_label(label), "query": query}


def list_templates(step: Mapping[str, Any], *, found: bool, truncated: bool,
                   exported: bool) -> list[dict[str, str]]:
    """清单之后：按问题类型统计这些单（本步没按问题类型筛时）、导出全部（表格没列全又还没导出时）。"""
    if not found:
        return []
    out = []
    filters = schema.as_list((step.get("params") or {}).get("filters"))
    if not any(isinstance(f, dict) and f.get("field") == "问题类型" for f in filters):
        out.append(template(STAT_BY_TYPE, STAT_BY_TYPE))
    if truncated and not exported:
        out.append(template(EXPORT_ALL, EXPORT_ALL_QUERY))
    return out


def aggregate_templates(step: Mapping[str, Any], *, top1: Sequence[Any]) -> list[dict[str, str]]:
    """只按一个维度分组的汇总之后，有第一名时「列出惠州百富的单」。按时间（年季月周）分组、比较、并列第一的
    多于 `TOP1_MAX` 个、第一名是「未填」一类时不给。"""
    p = step.get("params") or {}
    group_by = [str(g) for g in schema.as_list(p.get("group_by"))]
    if len(group_by) != 1 or group_by[0] in base.PERIOD_DIMS or p.get("compare"):
        return []
    values = [str(x).strip() for x in top1 if x is not None and str(x).strip()]
    values = list(dict.fromkeys(values))
    if not values or len(values) > TOP1_MAX or any(v in _TOP1_PLACEHOLDERS for v in values):
        return []
    joined = "、".join(values)
    text = f"列出 {joined} 级的单" if group_by[0] == "问题等级" else f"列出{joined}的单"
    return [template(text, text)]


def detail_templates(aspects: Sequence[str], number: str | None) -> list[dict[str, str]]:
    """只有一张单的详情、按号查单之后：还没看的完整处理过程、原因与措施（问句带上问题编号）。"""
    if not number:
        return []
    out = []
    if not any(a in _PROCESS_ASPECTS for a in aspects):
        out.append(template(FULL_PROCESS, f"{number} 的完整处理过程"))
    if not any(a in _REASON_ASPECTS for a in aspects):
        out.append(template(REASONS, f"{number} 的原因与措施"))
    return out


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


def merge(*groups: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """按顺序合并，同一个问句只留第一个，至多 4 个，重新编号。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for rec in group:
            q = str(rec.get("query") or "").strip()
            if not q or q in seen:
                continue
            seen.add(q)
            out.append({**rec, "id": str(len(out) + 1)})
            if len(out) >= MAX_BUTTONS:
                return out
    return out
