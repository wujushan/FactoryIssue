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
#: 过渡：规划层已接上、这一类查询的执行还没接上（S3–S6 各片补上后删掉）
NOT_READY = "这一类查询暂时还答不了，可以先试试下面的问法"
#: 不带任何条件的清单（总述「必要澄清项」表后那句）
NO_CONDITION_LIST = "没有给条件，先按建单时间列出最近的单；还可以按时间、机型、工厂、问题类型、单号等查"
SECTION_FAILED = "这一部分暂时没查到，请稍后再试"
TURN_FAILED = "这次没查到结果，请稍后再试"
TURN_FAILED_CODE = "TURN_FAILED"
TOO_MANY_ROWS = "结果太多，请加上时间或其他条件再查"
TEXT_SEARCH_UNAVAILABLE = "暂不可用"
EXPORT_FAILED = "完整清单导出失败，请稍后再试"
#: 按意思一路用不了（`ctx.retrieval` 为 None、检索或重排服务出错，§14）：类似问题与「可能相关」答暂不可用
SEMANTIC_UNAVAILABLE = "按意思找暂不可用"
#: 候选太多、去掉限定检索（`RetrievalRestrictTooLarge`，§14）
SEMANTIC_PARTIAL = "符合条件的单太多，按意思找的部分不保证完整"


def not_counted(labels: Iterable[str]) -> str:
    """「巴西、海外无权限，未计入」。"""
    return f"{'、'.join(labels)}无权限，未计入"


def text_unavailable(labels: Iterable[str]) -> str:
    """主表可查而文字查找表无权的域（`privileges.md`「域闸门」）：不说成「没有找到」。"""
    return f"{'、'.join(labels)}的文字查找{TEXT_SEARCH_UNAVAILABLE}，未计入"


# 按编号查单（总述「按编号查单」对不上时怎么答；国内「按订单号查单」「按 CAR 编号查单」；巴西「投诉单号」）
def issue_not_found(number: str) -> str:
    return f"没有找到单号为 {number} 的问题单（已删除的单查不到），请核对单号"


CAR_NOT_FOUND = "没有找到这个 CAR 编号对应的物料问题单（已删除的单查不到），请核对编号"
NUMBER_NOT_FOUND = "没有找到挂着这个号的单（已删除的单查不到），请核对"
CLAIM_NOT_FOUND = "没有找到这个投诉单号对应的单（已删除的单查不到），请核对完整的投诉单号"
ORDER_NOT_FOR = "本助手不按其他在线订单号、退货单号查单"
#: 一号一行的合并表里，查不到、无权的那一行怎么写
ROW_NOT_FOUND = "没有找到（已删除的单查不到）"


def spaced(*parts: str) -> str:
    """接起几段文字，汉字与字母、数字之间空一格（「按 PN 编码」「PO 查过」）。"""
    out = ""
    for p in parts:
        if out and p and (out[-1].isascii() and out[-1].isalnum()) != (p[0].isascii() and p[0].isalnum()) \
                and not out[-1].isspace() and not p[0].isspace():
            out += " "
        out += p
    return out


def searched_kinds(kinds: Iterable[str], number: str) -> str:
    """号可能是几种时都没有：「按发货单号、问题编号查过，都没有找到挂着 2406648 的单（已删除的单查不到），请核对」。"""
    return spaced("按", "、".join(kinds), f"查过，都没有找到挂着 {number} 的单（已删除的单查不到），请核对")


def not_searched(labels: Iterable[str]) -> str:
    """号可能在几个域时只查有权的域：「巴西、海外无权限，未查」。"""
    return f"{'、'.join(labels)}无权限，未查"


def hand_orders(number: str, candidates: Iterable[str]) -> str:
    return f"没有找到订单号 {number}，有以它开头的手填订单号：{'、'.join(candidates)}。查哪一个？"


LOOKUP_CALIBER = "查找方式：按号精确匹配（问题编号、CAR 编号不分大小写，投诉单号另去掉空格），已删除的单查不到"

#: 单张单详情里的说法（各域「单张单详情」、国内「停线」「处理步骤」、总述「原因与措施怎么给」）；作为参数传进沙箱
DETAIL_TEXTS: dict[str, object] = {
    "long": "（内容较长，完整内容请到管理页面查看）",
    "header_title": "",
    "br_header_title": "填单信息",
    "br_stages": ["填单信息", "责任人确认", "SQE 确认", "效果确认", "结案确认"],
    "stop_title": "停线",
    "restart_reviewing": "重启方案审核中，暂不展示",
    "process_title": "完整处理过程",
    "restart_log_title": "重启操作日志",
    "reasons_title": "原因与措施",
    "returned": "该环节已退回重新处理，之前填写的内容可在处理过程里看到",
    "no_reasons": "这张单上和处理过程里都没有写原因与措施",
    "car_denied": CAR_NOT_PERMITTED,
    "car_missing": "该单登记的 CAR 报告查不到内容",
    "other_orders_count": "其他在线订单 {n} 条，需要可以列出",
    "material_unit": "这是「物料」单（磁头、面壳组件等中间产物出的问题），与管理页面一致：机型一栏显示「物料」，"
                     "不展示产品在制属性与影响数量",
    "possible_reasons_intro": "根据选择的问题现象，系统分析的可能原因（不是这张单上写下的原因分析）",
    "possible_inv_intro": "根据问题类别和现象，系统分析的可能涉及问题物料（不是这张单的涉及物料）",
    "no_attachments": "这张单没有附件",
    "no_five_why": "这张单没有 5Why 记录",
    "cn_no_follower": "物料问题、工厂制程、资料问题按类型流转到固定处理角色，不指定问题跟进人",
    "cn_roles": "责任人取对应环节最新一条处理步骤的操作人，与问题跟进人、当前责任人是三种角色",
    "cost_title": "费用明细与合计",
    "debit_apart": "扣款单独列出，未计入费用",
    "no_cost": "这张单没有费用明细",
    "br_no_current": "巴西不提供当前责任人",
    "br_responsible": "巴西的责任人即问题跟进人，巴西不提供当前责任人",
    "br_latest_only": "巴西只给最新一条处理过程：后一条是在前一条的基础上修改、补充的",
    "no_8d_doc": "还没有上传 8D 报告（「需要回复 8D」为是不代表已有文件）",
    "br_pn_zero": "单上关联的 PN 编码是「0」，是没选 PN 时留下的占位值，与管理页面一致不展示，所以 PN 显示「未填」",
    "br_stock_more": "库存处理的其余信息暂不提供，请到管理页面查看",
    "br_no_restart": "巴西没有停线重启时间",
    "br_five_why": "管理页面「责任人确认」里的「5Why分析过程」本助手暂不提供，请到管理页面查看",
    "delivery_title": "涉及发货单",
    "no_delivery": "这张单没有涉及发货单",
    "no_material": "这张单没有登记物料",
    "os_responsible": "海外只说「责任人」时给当前责任人与问题跟进人",
    "os_reasons_intro": "根据选择的问题现象，系统给出的候选原因清单（不是这张单上写下的原因分析）",
    "no_possible_reasons": "这张单选的现象下没有可能问题原因",
    "os_five_why": "管理页面「责任人确认」里的「5Why分析过程」本助手暂不提供，请到管理页面查看",
}

#: 详情里某一项本域没有（总述「三个域」各域「不管什么」、各域「查询范围」）：(域, 块) → 说法
DETAIL_ABSENT: dict[tuple[str, str], str] = {
    ("国内", "delivery"): "国内单上没有发货单，发货单是海外的单上的",
    ("国内", "cost"): "国内单上没有费用，费用只在巴西的单上",
    ("国内", "eight_d"): "国内单上没有 8D，8D 只在巴西的单上",
    ("国内", "supplement"): "国内单上没有补料，补料只在巴西的单上",
    ("国内", "stock"): "国内单上没有库存处理这一项，库存处理只在巴西的单上",
    ("国内", "car"): "只有物料问题展示 CAR，这张单没有关联 CAR",
    ("国内", "orders"): "这张单没有生产订单或小板订单",
    ("国内", "other_orders"): "这张单没有其他在线订单",
    ("国内", "phenomena"): "这张单没有选问题现象",
    ("国内", "possible_reasons"): "这张单没有可能问题原因",
    ("巴西", "orders"): "巴西单上没有订单，涉及的 PO 只用来解析 PN",
    ("巴西", "other_orders"): "巴西单上没有其他在线订单",
    ("巴西", "delivery"): "巴西单上没有发货单，发货单是海外的单上的",
    ("巴西", "car"): "巴西没有 CAR",
    ("巴西", "possible_reasons"): "巴西单上没有可能问题原因",
    ("巴西", "current"): "巴西不提供当前责任人",
    ("海外", "cost"): "海外没有费用",
    ("海外", "eight_d"): "海外没有 8D",
    ("海外", "car"): "海外没有 CAR",
    ("海外", "supplement"): "海外单上没有补料，补料只在巴西的单上",
    ("海外", "stock"): "海外单上的库存不在查询范围",
    ("海外", "other_orders"): "海外单上的其他在线订单不在查询范围",
}


def not_available(item: str) -> str:
    """点名的项本助手没有（总述「业务定位」）。"""
    return f"本助手没有『{item}』这一项"
