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

_MAIN = "CoreINFO.dbo.ZCTracking_ProblemList"
_MODELS = "CoreINFO.dbo.ZCTracking_ProductNames"
_INVENTORY = "info.dbo.Inventory"
_VENDOR = "info.dbo.tbIQCvendor"


def _shown(table: str, column: str) -> str:
    name = landed.display_name(table, column)
    if not name:
        raise landed.LandedParseError(f"{table}.{column} 标了内部字段，不能当列展示")
    return name


@cache
def _corpus() -> str:
    parts = [landed.read("glossary.md"), landed.read("business_description.md"),
             landed.read("domestic/business_description.md")]
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
STAGE = _derived("处理环节")
CLOSED_OR_NOT = _derived("结案与否")

#: 清单默认 6 列（总述「清单默认列」）
DEFAULT_LIST = ("number", "machine", "type", "rate", "bad_qty", "desc")

#: 问题描述摘要还不能取时（文字查找表无权，或 S6 之前没声明）写这句（总述「清单默认列」）
DESC_UNAVAILABLE = "暂不可用"


def _norm(text: object) -> str:
    return re.sub(r"[\s\-_]+", "", unicodedata.normalize("NFKC", str(text or ""))).lower()


@cache
def _aliases() -> dict[str, str]:
    """用户的叫法 → 内部键：显示名本身，加术语表里规范词与别称（规范词对得上某个显示名时）。"""
    by_name = {_norm(v): k for k, v in VIEW_COLUMNS.items()}
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


def shown(key: str) -> str:
    return VIEW_COLUMNS[key]
