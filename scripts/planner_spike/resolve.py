"""规整与校验：S1 起调 src（`factory_issue_module.plan.normalize`、`plan.prematch`），这里只按 spike 的调用形状转接。

实测分数是「模型 + 规整」一起的结果，规则只在 src 里写一份（设计 §1.3 末条、§5.3）。规则编号与说明见
`src/factory_issue_module/plan/normalize.py`。spike 这一侧只提供线上要查库才有的两样输入：

- `CATALOG`：第 7 条名字归类用的「库里的取值」（类 → 名字）。只放对照集问句里出现的名字（来自测试案例集与
  2_landed，非真实明细）；线上是可查的域的主数据。
- `mockdata.CATALOG`：第 15 条与预匹配用的「名字 → 在库里属于哪几类」（合成主数据，条数与真实库同一量级）。

两份互不影响，分数按它们得出，改了要重算对照集。第 18 条线上另给「按更早那次的条件查」的选项（问句取工作区
`last`），对照集没有那句原话，这里不给。
"""

from __future__ import annotations

from datetime import date

from factory_issue_module.plan import normalize
from factory_issue_module.plan import prematch as _prematch

import mockdata
import prompts

CATALOG = {
    "工厂": ["柯洱斯", "亮亮", "惠州百富", "TT", "CA"],
    "人": ["李飞", "马万军", "张三"],
    "部门": ["工程部", "生产工程部", "研发一部", "研发二部"],
    "供应商": ["普瑞特", "高展光电", "亮亮"],  # 亮亮与国内工厂同名（c4 加，见 mockdata.py）
    "系列": ["底座", "A"],
}

NO_RESULT_CLARIFY = normalize.NO_RESULT_CLARIFY
merge_duplicate_aggregates = normalize.merge_duplicate_aggregates
fold_previous_list = normalize.fold_previous_list
number_shortcut = _prematch.number_shortcut


def topic_scope(topic: str | None) -> str | None:
    return normalize.topic_scope(topic, prompts.TOPICS)


def missing_time_clarify(today: date | None = None) -> dict:
    return normalize.missing_time_clarify(today)


def apply(plan: dict | None, query: str | None = None, previous: dict | None = None,
          previous_outcome: str | None = None) -> dict | None:
    """返回处理后的计划副本（不改原计划）。`query` 不给时只做不看问句的那几条。"""
    return normalize.apply(plan, normalize.Context(
        query=query, previous=previous, previous_outcome=previous_outcome, classes=CATALOG, topics=prompts.TOPICS))


def query_checks(plan: dict, query: str, case: dict | None = None) -> list[str]:
    """第 7 条的校验一半、第 13、14、15、19 条；空表示通过。plan 用规整后的。

    `case` 是对照集的一条：第 19 条从它的 `previous_plan`、`history` 最后一轮的用户问句找上一轮那张单，同线上。
    """
    case = case or {}
    history = case.get("history") or []
    last_user = history[-1].get("user") if history else None
    return normalize.query_checks(plan, query, mockdata.CATALOG,
                                  previous_issue=normalize.previous_issue(case.get("previous_plan"), last_user))
