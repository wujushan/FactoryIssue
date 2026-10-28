"""业务话术（设计 §14）：给用户的句子都出自这里或各模板，业务语言，不带表名、字段名、异常文本。

异常只进日志。说法与 `privileges.md`、总述「回答怎么组织」一致；改这里之前先看那两处。
"""

from __future__ import annotations

from collections.abc import Iterable

# 权限（privileges.md「域闸门」「CAR 报告」「没拿到权限时」）
NO_DOMAIN = "您还没有任何域的查看权限，请先申请"
DOMAIN_NOT_PERMITTED = "您没有该域的查看权限"
APPLY_TO_VIEW = "申请后可查"
CAR_NOT_PERMITTED = "该单关联了 CAR 报告，您没有查看权限，可点链接到报告页面查看"
#: `ctx.data` 缺失或 `describe()` 抛权限错误时（Admin 调试对话、`forge dev serve` 默认授权树带的是
#: 空权限；权限配置写错），按「没拿到权限」答，三个域都不出数（§14 第一行之下补的一行）
ACCESS_UNAVAILABLE = "暂时无法确认您的查看权限，请稍后再试"
ACCESS_UNAVAILABLE_CODE = "ACCESS_UNAVAILABLE"

# 本助手管不着的事（总述「业务定位」）
OUT_OF_SCOPE = "这个问题不在本助手的范围。本助手只查国内、巴西、海外的制程问题，其他问题请换用对应的助手"
READ_ONLY = "本助手只读查询国内、巴西、海外的制程问题，不代替源系统填单、审批、上传或改状态"

# 理解与降级（总述「回答怎么组织」「一问多段」）
NOT_UNDERSTOOD = "没能理解这个问题，可以换个说法"
#: S1 过渡：规划层已接上、这一类查询的执行还没接上（S2–S6 各片补上后删掉）
NOT_READY = "这一类查询暂时还答不了，可以先试试下面的问法"
SECTION_FAILED = "这一部分暂时没查到，请稍后再试"
TURN_FAILED = "这次没查到结果，请稍后再试"
TURN_FAILED_CODE = "TURN_FAILED"
TOO_MANY_ROWS = "结果太多，请加上时间或其他条件再查"
TEXT_SEARCH_UNAVAILABLE = "暂不可用"
EXPORT_FAILED = "完整清单导出失败，请稍后再试"


def not_counted(labels: Iterable[str]) -> str:
    """「巴西、海外无权限，未计入」。"""
    return f"{'、'.join(labels)}无权限，未计入"
