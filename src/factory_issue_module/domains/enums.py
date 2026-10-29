"""枚举翻成人话（设计 §6.2、§9.1）。S2 只有国内；巴西、海外随 S3。

对照写在这里，单测断言每个显示文字都出现在对应的表文件里（`db_description/`），防两边漂移。
这些对照拼进沙箱脚本头部的参数（`stats/runner.py`），派生与翻译都在沙箱里做；`handle()` 一侧只拿它们
把用户说的取值对到代码（问题类型、等级、状态说法）。
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------- 国内主表

CN_PROBLEM_TYPES: dict[int, str] = {
    1: "硬件问题", 2: "软件问题", 3: "物料问题", 4: "资料问题", 5: "工厂制程", 6: "结构问题", 7: "制程优化",
}
CN_STATUS: dict[int, str] = {
    1: "指定责任人", 2: "责任人确认", 3: "工程确认", 4: "PMC确认", 5: "工厂制程分析", 6: "IQC确认",
    7: "填写退货单号", 8: "SQE跟进", 9: "设计更改", 10: "SQE确认", 11: "IQC意见", 12: "生产角色确认",
    13: "生产角色驳回", 30: "效果确认", 31: "结案确认", 32: "已完成", 36: "效果确认", 37: "预防对策确认",
}
CN_DONE = 32
CN_REJECTED = 13
CN_PARALLEL = (30, 36, 37)
#: 要做预防对策确认的类型（硬件、软件、物料、资料、结构问题）；工厂制程、制程优化不做
CN_NEEDS_PREVENTION = (1, 2, 3, 4, 6)
CN_STOP_STATUS: dict[int, str] = {
    1: "停线中", 2: "已经重启", 3: "没有停线", 4: "重启审核中", 5: "重启审核通过", 6: "责任人填写重启方案",
}
#: 「停线中」含这四种停线状态（国内「停线」）
CN_STOPPED = (1, 4, 5, 6)
CN_RESTARTED = 2
CN_OUTPUT_STATUS: dict[int, str] = {
    5: "首次量产", 6: "首次量产爬坡", 7: "正常量产", 8: "量产爬坡", 9: "未释放PN生产", 195: "物料试产",
    196: "小批量试产", 197: "工程样机",
}
CN_DESIGN_RESULT: dict[int, str] = {1: "改善", 2: "保持现状", 3: "挂起"}
CN_IQC_OPINION: dict[int, str] = {2: "退回仓库", 3: "继续使用"}
CN_YES_NO: dict[int, str] = {0: "否", 1: "是"}
CN_LEVELS = ("A+", "A", "B", "C")

# ---------------------------------------------------------------------------- 国内子表

#: 风险订单流程的步骤（退货 / 退库段）
CN_RISK_STEPS: dict[int, str] = {14: "填写退货信息", 15: "填写退库信息"}
CN_RISK_RUNNING = 1
#: 并行阶段两类待办的业务表名（国内「当前状态」；`tbTask` 表文件）
CN_TASK_EFFECT = "ZCTracking_ProblemSoftware3"
CN_TASK_PREVENTION = "ZCTracking_PreventionConfirm"
CN_TASK_ACCEPTED = "已接受"
#: 处理步骤的环节编码：结案确认、停线重启
CN_STEP_CLOSE = 31
CN_STEP_RESTART = 29
#: 责任人取哪个环节：问题类型 → 环节编码（国内「责任人怎么取」）
CN_RESPONSIBLE_STEP: dict[int, int] = {1: 3, 2: 3, 6: 3, 7: 3, 3: 10, 4: 4, 5: 6}
#: 「修改问题分类」在源系统里没有数值编码，按环节名称认
CN_STEP_RECLASSIFY = "修改问题分类"
#: 处理步骤要取的环节：责任人四种、停线重启、结案确认
CN_STEPS_NEEDED = (3, 4, 6, 10, CN_STEP_RESTART, CN_STEP_CLOSE)

#: 环节名称（当前状态各行）：主表状态与 IQC 状态的文案、风险订单步骤、并行阶段的两个环节
CN_STAGES: tuple[str, ...] = tuple(dict.fromkeys([
    *(v for k, v in CN_STATUS.items() if k != CN_DONE), *CN_RISK_STEPS.values(), "预防对策确认", "效果确认",
]))


def _key(text: object) -> str:
    return re.sub(r"[\s\-_]+", "", unicodedata.normalize("NFKC", str(text or ""))).lower()


def code_of(table: dict[int, str], said: object) -> list[int]:
    """显示文字 → 代码（不分大小写，忽略空格）；对不上返回空。"""
    want = _key(said)
    return [k for k, v in table.items() if _key(v) == want]


# ---------------------------------------------------------------------------- 状态说法（国内）

#: 「状态」条件的说法 → 判据。判据由沙箱按派生字段算（`stats/lib/derive_domestic.py::status_match`）
_STATUS_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("未结案", ("未结案", "没结案", "未结", "没结", "进行中", "没完成", "未完成", "未关闭", "处理中", "在处理")),
    ("已结案", ("已结案", "结案", "已完成", "完成", "已关闭", "关闭", "结了")),
    ("停线中", ("停线中", "目前停线", "正在停线", "还在停线", "停线未重启", "停线且未重启", "还没重启", "未重启", "没重启")),
    ("曾经停线", ("停线", "停过线", "曾经停线", "发生过停线", "有停线记录", "停产")),
    ("已经重启", ("已经重启", "已重启", "重启了", "已恢复生产", "停线重启")),
    ("重启审核通过", ("重启审核通过", "审核通过")),
    ("重启审核中", ("重启审核中",)),
    ("责任人填写重启方案", ("责任人填写重启方案",)),
    ("没有停线", ("没有停线", "未停线", "没停线")),
)
_STATUS_INDEX = {_key(w): kind for kind, words in _STATUS_WORDS for w in words}
_STAGE_INDEX = {_key(s): s for s in CN_STAGES}
STATUS_KINDS = tuple(kind for kind, _ in _STATUS_WORDS)


def status_kind(said: object) -> tuple[str, str] | None:
    """「状态」条件的一个取值 → (判据种类, 值)：("未结案", "")、("环节", "SQE跟进")；认不出返回 None。

    环节名称按当前状态的每一行比（国内「按处理环节筛选与统计」）；「生产角色驳回」既是主表状态也是环节，按环节认。
    """
    k = _key(said)
    k = re.sub(r"(的|状态|的单|单)$", "", k) or k
    if k in _STATUS_INDEX:
        return _STATUS_INDEX[k], ""
    if k in _STAGE_INDEX:
        return "环节", _STAGE_INDEX[k]
    return None


def status_options() -> list[str]:
    """「状态」说法对不上时给用户选的几种（总述「通用筛选规则」枚举对不上时列出可选值）。"""
    return ["未结案", "已结案", "停线中", "已经重启"]


def level_codes(said: object) -> list[str] | None:
    """问题等级说法 → 等级（「A 级」只指 A；「A 级及以上」= A+、A）；「未填」返回 ["未填"]；认不出返回 None。"""
    k = _key(said).upper()
    k = re.sub(r"(类|级|等级|类问题|级问题)", "", k)
    above = bool(re.search(r"(及以上|以上|及更高|或以上)$", k))
    k = re.sub(r"(及以上|以上|及更高|或以上)$", "", k)
    if k in ("未填", "空", "没有等级", "无"):
        return ["未填"]
    if k not in CN_LEVELS:
        return None
    if not above:
        return [k]
    return list(CN_LEVELS[: CN_LEVELS.index(k) + 1])
