"""五份配置的内置默认值的来源（设计 §11）。

这里只给「默认值从哪来」：三份表格形态的取 `2_landed` 原文（代码里不抄第二份），两份 TOML 形态的
是代码常量。解析交给 `config/files.py` 里与上传内容同一套函数，所以内置默认值本身也过一遍校验。

- 说法清单 = `topic_terms.md`；部门简称 = 总述「部门名称怎么对」的简称表；地区说法 = 国内「加工厂」
  的地区说法表。
- 分段规则取自决策 2026-10-20「G2 数据源与治理决策」的「整理规则」，环节清单取自总述「比对范围」；
  单测对照这两处原文。
- 回答参数取自决策 2026-10-26「回答组织方式默认值」与 G2（重排上限按单数计，见 G2 补记）。
"""

from __future__ import annotations

from typing import Any

from factory_issue_module import landed


def topic_terms_text() -> str:
    return landed.topic_terms_text()


def dept_aliases_text() -> str:
    return landed.dept_aliases_section()


def factory_regions_text() -> str:
    return landed.factory_regions_section()


SEGMENTATION: dict[str, Any] = {
    "rule": "field_split",
    "split_over": 500,
    "seg_min": 300,
    "seg_max": 500,
    "overlap": "sentence",
    "groups": {
        "first": ["phen", "desc", "reason"],
        "second": ["improve", "measure", "prev", "sqe", "step"],
    },
    "steps": {
        "domestic_codes": [3, 4, 6, 10, 11, 13, 14, 35],
        "overseas_names": [
            "SQE跟进", "IQC意见", "IQC填写意见", "工厂制程分析", "责任人确认", "工程确认",
            "设计变更", "设计变更后SQE确认", "预防对策确认",
        ],
    },
}

ANSWER_PARAMS: dict[str, Any] = {
    "top_n": 10,
    "export_threshold": 20,
    "table_rows": 20,
    "judge_max": 30,
    "rerank_max": 100,
    #: 类似问题的重排分下限，低于它的不列（决策 2026-11-03「类似问题逐张判断与分数下限」，探测 Z1）
    "similar_rerank_floor": 0.2,
    #: 类似问题每域列几张（决策 2026-11-03「回答骨架与排版」）
    "similar_rows": 5,
    "custom_stats_enabled": True,
    #: 结论里的要点与需关注的单（总述「结论里的要点与需关注的单」，决策 2026-11-03「结论的要点与需关注的单」）：
    #: 要点至多几条、需关注至多几张；集中的占比门槛（%）、重复的张数门槛、时间的月数门槛、时效的张数门槛
    "points_max": 4,
    "focus_max": 3,
    "concentrate_share": 40,
    "repeat_min": 3,
    "trend_months": 3,
    "close_min": 5,
    #: 类似问题的「共同点」至少几张（决策 2026-11-03「结论的要点与需关注的单」补记，G86）
    "similar_common_min": 2,
    #: 答后建议（设计 §9.5、决策 2026-11-02「答后建议改由模型挑」）
    "suggest_model": True,
    "suggest_seconds": 5,
}
