"""列显示名（设计 §9.1）。

显示名只有一个来源：
- 表里的列：`landed.display_name(表, 列)`，即 `db_description/` 各表字段表的「用户可见显示名」。
- 派生列与统计列（当前状态、当前责任人、责任人、结案时间、重启日期、单数、未结案数、占比（%）……）：名字写在
  这里，导入时逐个断言它出现在 `2_landed` 的正文里（术语表、总述、国内业务描述、表文件），对不上模块加载即失败，
  免得两边各说各话。

沙箱里的结果表直接用显示名作列名（§8.1），呈现层不再翻译。`VIEW_COLUMNS` 是沙箱派生出的「一单一行」视图里
各列的内部键 → 显示名，作为参数写进脚本头部。
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache

from factory_issue_module import landed

from factory_issue_module.declarations import Domain

_MAIN = "CoreINFO.dbo.ZCTracking_ProblemList"
_MODELS = "CoreINFO.dbo.ZCTracking_ProductNames"
_INVENTORY = "info.dbo.Inventory"
_VENDOR = "info.dbo.tbIQCvendor"
_BR = "CoreINFO.dbo.BrazilProblemList"
_BRP = "CoreINFO.dbo.BrazilProblemProcess"
_OS = "CoreINFO.dbo.OverseasProblemDetail"
_PRODUCT = "info.dbo.ProductName"


def _shown(table: str, column: str) -> str:
    name = landed.display_name(table, column)
    if not name:
        raise landed.LandedParseError(f"{table}.{column} 标了内部字段，不能当列展示")
    return name


def _key_shown(table: str, key: str) -> str:
    """JSON 列里某个键的显示名（海外物料的料号、描述、供应商）。"""
    name = landed.table_docs()[table].keys.get(key)
    if not name:
        raise landed.LandedParseError(f"{table} 的 JSON 键 {key} 没有显示名")
    return name


@cache
def _corpus() -> str:
    parts = [landed.read("glossary.md"), landed.read("business_description.md"),
             landed.read("domestic/business_description.md"), landed.read("brazil/business_description.md"),
             landed.read("overseas/business_description.md")]
    parts += [landed.read(doc.file) for doc in landed.table_docs().values()]
    return "\n".join(parts)


def _derived(name: str) -> str:
    if name not in _corpus():
        raise landed.LandedParseError(f"派生列名「{name}」在 2_landed 里找不到")
    return name


#: 国内「一单一行」视图的列：内部键 → 显示名
VIEW_COLUMNS: dict[str, str] = {
    "number": _shown(_MAIN, "Numbers"),
    "machine": _shown(_MODELS, "ProductName"),
    "series": _shown(_MODELS, "Series"),
    "type": _shown(_MAIN, "ProblemType"),
    "old_type": _shown(_MAIN, "OldProblemType"),
    "factory": _shown(_MAIN, "Factory"),
    "status": _shown(_MAIN, "Status"),
    "current_state": _derived("当前状态"),
    "current_people": _derived("当前责任人"),
    "follower": _shown(_MAIN, "RUser"),
    "follow_dept": _shown(_MAIN, "RDepartment"),
    "responsible": _derived("责任人"),
    "resp_dept": _shown(_MAIN, "AllReDepartment"),
    "add_date": _shown(_MAIN, "AddDate"),
    "found_date": _shown(_MAIN, "FoundDate"),
    "rate": _shown(_MAIN, "Rate"),
    "bad_qty": _shown(_MAIN, "BadQty"),
    "prod_qty": _shown(_MAIN, "ProdQty"),
    "impact_qty": _shown(_MAIN, "ImpactQty"),
    "level": _shown(_MAIN, "ProblemLevel"),
    "output_status": _shown(_MAIN, "OutPutStatus"),
    "is_stop": _shown(_MAIN, "IsStop"),
    "stop_status": _shown(_MAIN, "StopStatus"),
    "stop_date": _shown(_MAIN, "StopDate"),
    "restart_date": _derived("重启日期"),
    "close_time": _derived("结案时间"),
    "inv_code": _shown(_MAIN, "CInvCode"),
    "inv_name": _shown(_INVENTORY, "cInvName"),
    "inv_std": _shown(_INVENTORY, "cInvStd"),
    "ven_code": _shown(_MAIN, "VenCode"),
    "ven_name": _shown(_VENDOR, "fname"),
    "station": _shown(_MAIN, "Station"),
    "version": _shown(_MAIN, "Version"),
    "reason_class": _shown(_MAIN, "ReasonClass"),
    "design_result": _shown(_MAIN, "DesignConfirmResult"),
    "iqc_opinion": _shown(_MAIN, "IQCOpinion"),
    "design_change": _shown(_MAIN, "IsDesignChange"),
    "plan_done": _shown(_MAIN, "RCompleteTime"),
    "add_user": _shown(_MAIN, "AddUser"),
    "car": _shown(_MAIN, "CAR"),
    "desc": _shown(_MAIN, "ProblemDesc"),
}

#: 巴西「一单一行」视图的列。机型一列三域都叫「机型」（总述「清单默认列」），取巴西的大机型
BR_VIEW_COLUMNS: dict[str, str] = {
    "number": _shown(_BR, "OrderNumber"),
    "claim": _shown(_BR, "ClaimNumber"),
    "machine": VIEW_COLUMNS["machine"],
    "series": _shown(_PRODUCT, "Series"),
    "pn": _derived("PN"),
    "type": _shown(_BR, "ProblemType"),
    "other_desc": _derived("其他问题说明"),
    "factory": _shown(_BR, "BrazilFactory"),
    "status": _shown(_BR, "Status"),
    "follower": _shown(_BRP, "ProcessUserID"),
    "follow_dept": _derived("问题跟进部门"),
    "add_date": _shown(_BR, "AddDate"),
    "found_date": _shown(_BR, "ProblemDiscoveryDate"),
    "stat_date": _shown(_BR, "StatisticsDate"),
    "rate": _derived("不良率"),
    "bad_qty": _shown(_BR, "BadQty"),
    "impact_qty": _shown(_BR, "ImpactQty"),
    "level": _shown(_BR, "ProblemLevel"),
    "is_stop": _shown(_BR, "IsStopLine"),
    "stop_status": _shown(_BR, "StopStatus"),
    "stop_date": _shown(_BR, "StopDate"),
    "close_time": _derived("结案时间"),
    "inv_code": _shown(_BR, "cInvCode"),
    "inv_name": _shown(_INVENTORY, "cInvName"),
    "inv_std": _shown(_INVENTORY, "cInvStd"),
    "ven_code": _shown(_BR, "cVenCode"),
    "ven_name": _shown(_VENDOR, "fname"),
    "station": _shown(_BR, "ProblemDiscoveryStation"),
    "need_8d": _shown(_BR, "IsRequire8D"),
    "supplement": _shown(_BR, "IsSupplement"),
    "is_cost": _shown(_BR, "IsCost"),
    "cost_usd": _derived("费用美元合计"),
    "cost_brl": _derived("费用雷亚尔合计"),
    "debit": _shown(_BRP, "DebitMoney"),
    "design_change": _shown(_BRP, "IsDesignChange"),
    "plan_done": _shown(_BRP, "PlanCompleteDate"),
    "add_user": _shown(_BR, "AddUserID"),
    "initial_owner": _shown(_BR, "ActorUserID"),
    "desc": _shown(_BR, "ProblemDesc"),
}

#: 海外「一单一行」视图的列。机型取大机型，列名同国内
OS_VIEW_COLUMNS: dict[str, str] = {
    "number": _shown(_OS, "Numbers"),
    "machine": VIEW_COLUMNS["machine"],
    "series": _shown(_OS, "Series"),
    "pn": _shown(_OS, "PNList"),
    "type": _shown(_OS, "ProblemType"),
    "old_type": _shown(_OS, "OldProblemType"),
    "other_desc": _shown(_OS, "ProblemRemark"),
    "factory": _shown(_OS, "Factory"),
    "cn_factory": _shown(_OS, "Factory2"),
    "status": _shown(_OS, "Status"),
    "current_state": _derived("当前状态"),
    "current_people": _shown(_OS, "MemberListName"),
    "follower": _shown(_OS, "RUser"),
    "follow_dept": _shown(_OS, "RDepartment"),
    "add_date": _shown(_OS, "AddDate"),
    "found_date": _shown(_OS, "FoundDate"),
    "rate": _shown(_OS, "Rate"),
    "bad_qty": _shown(_OS, "BadQty"),
    "impact_qty": _shown(_OS, "ImpactQty"),
    "level": _shown(_OS, "ProblemLevel"),
    "is_stop": _shown(_OS, "IsStop"),
    "stop_status": _shown(_OS, "StopState"),
    "stop_date": _shown(_OS, "StopDate"),
    "restart_date": _shown(_OS, "ReStartDate"),
    "close_time": _derived("结案时间"),
    "inv_code": _key_shown(_OS, "PN"),
    "inv_name": _shown(_OS, "InvInfo"),
    "ven_code": _key_shown(_OS, "supplier"),
    "ven_name": _key_shown(_OS, "supplierName"),
    "station": _shown(_OS, "Station"),
    "version": _shown(_OS, "Version"),
    "iqc_opinion": _shown(_OS, "IQCOpinion"),
    "design_change": _shown(_OS, "IsDesignChange"),
    "design_result": _shown(_OS, "DesignConfirmResult"),
    "plan_done": _shown(_OS, "RCompleteTime"),
    "add_user": _shown(_OS, "AddUser"),
    "desc": _shown(_OS, "ProblemDesc"),
}

_BY_DOMAIN: dict[Domain, dict[str, str]] = {
    Domain.DOMESTIC: VIEW_COLUMNS, Domain.BRAZIL: BR_VIEW_COLUMNS, Domain.OVERSEAS: OS_VIEW_COLUMNS,
}

# ---------------------------------------------------------------------------- 单张单详情与按号查单（S4）

_STEPS = "CoreINFO.dbo.ZCTracking_ProblemSteplog"
_ORDERS = "CoreINFO.dbo.ZCTracking_ProblemOrders"
_XB = "CoreINFO.dbo.ZCTracking_XBOrders"
_OTHER = "CoreINFO.dbo.ZCTracking_OtherOrder"
_PHEN = "CoreINFO.dbo.AfterSaleIssueClassPhenomenon"
_PREASON = "CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason"
_CLASS = "CoreINFO.dbo.AfterSaleIssueClass"
_PINV = "CoreINFO.dbo.ZCTracking_PossibleInvCode"
_FIVE = "CoreINFO.dbo.ZCTracking_ProblemFiveWhy"
_CAR = "info.dbo.tbIQCreportOut"
_BRC = "CoreINFO.dbo.BrazilProblemCost"
_OSS = "CoreINFO.dbo.OverseasProblem_StepLog"
_OSD = "CoreINFO.dbo.OverseasProblem_DeliveryOrder"


def _cols(prefix: str, table: str, names: str) -> dict[str, str]:
    return {f"{prefix}.{c}": _shown(table, c) for c in names.split()}


#: 详情各块与按号查单各表的标签：内部键 → 显示名（沙箱参数 `labels`）。表里的列取表文件的显示名，其余取
#: 各域业务描述「单张单详情」、处理步骤表「单张单详情里的结论」里的叫法，导入时逐个核对（`_shown`、`_derived`）
DETAIL: dict[str, str] = {
    **_cols("cn", _MAIN, "Reason Improve Measures Prevention ReasonClassRemark Remark RConfirm DesignUser DesignDate "
                         "ZLConfirmResult IsChangeOrderV OrderVersion ReStartScheme ReStartSchemeUser "
                         "ReStartExamineUser IQCMemberListName Confirmation MHead"),
    **_cols("step", _STEPS, "StepStr Result Opinon Measures FileUrl AddUser AddDate"),
    **_cols("ord", _ORDERS, "OrderNumber IssueDate OrderQty ReceiptQty OnlineQty Version"),
    **_cols("xb", _XB, "OrderNumber InvCode InvStd Qty InQty NoQty Factory Description"),
    **_cols("oo", _OTHER, "OrderNo ProductName Qty IssuedQty IssQty FaliaoDate ReturnQty ReturnType ReceivingQty "
                          "TotalinQty Factory"),
    **_cols("phen", _PHEN, "PhenomenonDesc"),
    **_cols("preason", _PREASON, "ReasonDesc"),
    **_cols("pclass", _CLASS, "TypeName ClassName"),
    **_cols("pinv", _PINV, "InvCode InvStd"),
    **_cols("fw", _FIVE, "Question Reason Status AddUser AddDate UpdateUser UpdateDate"),
    **_cols("car", _CAR, "fdesc fstep2how1 fstep2how2 fstep2how3 fstep3memo fstep4memo fstep5memo fstep6memo"),
    **_cols("br", _BR, "ProblemPhenomenon SupplementQty SupplementResult SupplementMemo SupplementUserID "
                       "SupplementDate Memo"),
    **_cols("brp", _BRP, "DisposeResult PlanCompleteDate ReasonAnalysis ImprovementMeasure ImprovementBatch "
                         "PrecautionPolicy IsStockPrecess StockPrecessQty IsCostShift DebitMoney DebitNumber "
                         "UnCostShiftReason IsSupplementMaterial SupplementMaterialQty InStoreNumber IsDesignChange "
                         "DesignUserID DesignResult DesignMemo DesignEstimateDate DesignDate SQEResult SQEMemo "
                         "SQEUserID SQEDate ProcessResult ProcessMemo ProcessUserID ProcessDate ConfirmResult "
                         "ConfirmMemo ConfirmUserID ConfirmDate FinishResult FinishMemo FinishUserID FinishDate"),
    **_cols("brc", _BRC, "CostType CostMoney CostBrlMoney ConstBrlRate CostMemo"),
    **_cols("os", _OS, "hasCheckedPhenomenon Improve Remark Reason Measures Prevention Confirmation RConfirm DocId "
                       "DesignUser DesignDate"),
    **_cols("oss", _OSS, "StepStr Result Opinon Measures DocID AddUser AddDate"),
    **_cols("osd", _OSD, "PO OrderNumber Date PN DeliveryVersion ProdVersion Quantity Remark"),
    "os.materialDesc": _key_shown(_OS, "materialDesc"),
    # 各块里的叫法（国内处理步骤表「单张单详情里的结论」、各域「单张单详情」）
    "handler": _derived("处理人"),
    "confirm_result": _derived("确认结果"),
    "note": _derived("备注"),
    "seq": _derived("序号"),
    "new_type": _derived("修改后的问题分类"),
    "need_design": _derived("是否设计更改"),
    "sqe_result": _derived("SQE跟进结果"),
    "reason_note": _derived("原因说明"),
    "countermeasure": _derived("制定对策"),
    "prevention_confirm": _derived("预防对策确认"),
    "effect_result": _derived("效果确认结果"),
    "close_conclusion": _derived("结案结论"),
    "restart_note": _derived("重启备注"),
    "restart_review": _derived("重启审核意见"),
    "prod_orders": _derived("生产订单"),
    "xb_orders": _derived("小板订单"),
    "other_orders": _derived("其他在线订单"),
    "possible_inv": _derived("可能的问题物料"),
    "car_report": _derived("CAR 报告"),
    "claim_docs": _derived("投诉单附件"),
    "eight_d": _derived("8D 报告"),
    "design_docs": _derived("设计更改附件"),
    "delivery_total": _derived("订单数量合计"),
    "domain": _derived("所属域"),
    #: 巴西「当前状态」即主表状态（术语表「当前状态」），按号查单的表三域都写这一列名
    "current_state": _derived("当前状态"),
    "pn": _derived("PN"),
    "debit": _derived("扣款"),
}


def detail(key: str) -> str:
    return DETAIL[key]


def view_columns(domain: Domain) -> dict[str, str]:
    """某一域「一单一行」视图的列：内部键 → 显示名（沙箱参数 `names` 按域给）。"""
    return _BY_DOMAIN[domain]


#: 统计表的列（总述「表格列名」「初步分析维度」）
COUNT = _derived("单数")
UNCLOSED = _derived("未结案数")
SHARE = _derived("占比（%）")
DOMAIN = _derived("域")
CLOSE_DAYS = _derived("结案周期")
RATE = _derived("不良率（%）")
CLOSE_MEAN = _derived("结案周期平均（天）")
CLOSE_MEDIAN = _derived("结案周期中位数（天）")
STOP_MEAN = _derived("停线时长平均（天）")
STOP_MEDIAN = _derived("停线时长中位数（天）")
STOPPED = _derived("停线中")
DIFF = _derived("增减量")
CHANGE = _derived("变化率")
#: 比较两个时段、又没有分组时，图的横轴（两段时间各一根柱子）
PERIOD = _derived("时段")
STAGE = _derived("处理环节")
CLOSED_OR_NOT = _derived("结案与否")
#: 三域一起统计时：各域小计各一列、再给合计（总述「跨域规则」汇总呈现）；域一行时的未结案占比
TOTAL = _derived("合计")
UNCLOSED_SHARE = _derived("未结案占比（%）")
#: 巴西费用（总述「表格列名」：金额列带币种）；扣款单列（巴西「费用」）
COST_USD = _derived("费用（美元）")
COST_BRL = _derived("费用（雷亚尔）")
DEBIT = BR_VIEW_COLUMNS["debit"]

#: 第 5 条前半：详情只要原因或措施时并进前一步的清单，清单加这一列（总述「原因与措施怎么给」）
REASONS = _derived("原因与措施")
#: 几个问题编号合成一张表时另加的一列（总述「按编号查单」一次给多个号）
OWNER_DOMAIN = _derived("所属域")
#: 按文字找单的表格另加的两列与「分组」一列的说法（总述「表格列名」、「涉及某个话题怎么找」）
TEXT_GROUP = _derived("分组")
TEXT_CONTEXT = _derived("命中处")
TEXT_GROUPS = {"1": _derived("问题本身涉及"), "2": _derived("处理中提到"), "3": _derived("可能相关")}
#: 点名字段、问做法的第一组；问做法又说了现象时两边都命中的那组。第三组各种找法都叫「可能相关」（开发者 2026-10-31 定）
TEXT_HIT = _derived("直接提到")
TEXT_BOTH = _derived("两边都提到")
#: 质疑上一轮、重查后有变化的单那张表的「变化」一列与它的两种说法（总述「表格列名」）
VERIFY_CHANGE = _derived("变化")
VERIFY_ADDED = _derived("这次新查到")
VERIFY_REMOVED = _derived("这次没查到")

#: 清单默认 6 列（总述「清单默认列」）
DEFAULT_LIST = ("number", "machine", "type", "rate", "bad_qty", "desc")

#: 问题描述摘要取不到时（本域文字查找表无权，或读文字表出错）写这句（总述「清单默认列」）
DESC_UNAVAILABLE = "暂不可用"


def _norm(text: object) -> str:
    return re.sub(r"[\s\-_]+", "", unicodedata.normalize("NFKC", str(text or ""))).lower()


@cache
def _aliases() -> dict[str, str]:
    """用户的叫法 → 内部键：显示名本身（国内在先，巴西、海外补上国内没有的），加术语表里规范词与别称（规范词
    对得上某个显示名时）。"""
    by_name: dict[str, str] = {}
    for mapping in (VIEW_COLUMNS, BR_VIEW_COLUMNS, OS_VIEW_COLUMNS):
        for k, v in mapping.items():
            by_name.setdefault(_norm(v), k)
    out = dict(by_name)
    for term in landed.glossary():
        key = by_name.get(_norm(term.term))
        if key is None:
            continue
        for alias in term.aliases:
            out.setdefault(_norm(re.sub(r"（.*?）", "", alias)), key)
    # 列清单时只说「处理人」指问题跟进人（总述「三域共用的说法」、术语表「问题跟进人」的口径定义）
    out.setdefault(_norm("处理人"), "follower")
    return out


def resolve(said: str) -> str | None:
    """用户点名的列 → 内部键；对不上返回 None（回答开头写「本助手没有『X』这一项」）。"""
    return _aliases().get(_norm(said))


def shown(key: str, domain: Domain | None = None) -> str:
    """内部键的显示名：给了域就用该域的叫法，该域没有这一列时（或没给域）按国内、巴西、海外的顺序取。"""
    if domain is not None and key in _BY_DOMAIN[domain]:
        return _BY_DOMAIN[domain][key]
    for mapping in (VIEW_COLUMNS, BR_VIEW_COLUMNS, OS_VIEW_COLUMNS):
        if key in mapping:
            return mapping[key]
    raise KeyError(key)
