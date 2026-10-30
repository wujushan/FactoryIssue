"""巴西、海外假数据（单测夹具清单的写法：单号年份 99、「测试甲」「测试乙」、15 个 9 的编码），按表给假连接器。

`load(h)` 把三域的帧都装进去（国内用 `cn_data`）；日期相对「今天」生成。文本存的日期写成 `YYYY-MM-DD`。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import cn_data
import pandas as pd

TODAY = date.today()


def _ts(days_ago: int) -> datetime:
    d = TODAY - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, 9, 0)


def _text(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def br_rows() -> list[dict[str, Any]]:
    base = {"ClaimNumber": None, "StopDate": None, "StopStatus": None, "ProblemDiscoveryDate": None,
            "ProblemDiscoveryStation": None, "StatisticsDate": None, "cInvCode": None, "cVenCode": None,
            "IsRequire8D": 2, "IsSupplement": 2, "IsCost": 2, "ActorUserID": 11, "AddUserID": 12}
    rows = [
        {"ID": 1, "OrderNumber": "BR9901001", "BrazilFactory": "CA,TT", "ProductIDAll": "101", "ProblemType": "硬件问题",
         "IsStopLine": "是", "StopStatus": "", "StopDate": _text(2), "ProblemLevel": "A", "ImpactQty": 100,
         "BadQty": 5, "Status": 20, "AddDate": _ts(3), "IsCost": 1, "IsRequire8D": 1, "cVenCode": "V99",
         "ClaimNumber": "CLAIM-0099/99"},
        {"ID": 2, "OrderNumber": "BR9901002", "BrazilFactory": "TT", "ProductIDAll": "101, 102",
         "ProblemType": "其他|包装破损", "IsStopLine": "否", "ProblemLevel": "", "ImpactQty": 0, "BadQty": 0,
         "Status": 0, "AddDate": _ts(5)},
        {"ID": 3, "OrderNumber": "BR9901003", "BrazilFactory": "CA", "ProductIDAll": "102", "ProblemType": "物料问题",
         "IsStopLine": "是", "StopStatus": "停线重启", "StopDate": _text(9), "ProblemLevel": "B", "ImpactQty": 50,
         "BadQty": None, "Status": 50, "AddDate": _ts(10), "IsCost": 0},
        {"ID": 4, "OrderNumber": "BR9901004", "BrazilFactory": "TR", "ProductIDAll": "103", "ProblemType": "设计问题",
         "IsStopLine": "否", "ProblemLevel": "C", "ImpactQty": 20, "BadQty": 2, "Status": -2, "AddDate": _ts(20),
         "IsCost": 1},
    ]
    return [{**base, **r} for r in rows]


def os_rows() -> list[dict[str, Any]]:
    base = {"OldProblemType": None, "ProblemRemark": None, "Series": None, "PNList": None, "InvInfo": None,
            "FoundDate": None, "Station": None, "Version": None, "ReStartDate": None, "RCompleteTime": None,
            "IQCOpinion": None, "IsDesignChange": 0, "DesignConfirmResult": None, "AddUser": 12}
    inv = json.dumps([{"PN": "999999999999992", "materialDesc": "测试喇叭", "supplier": "V99",
                       "supplierName": "测试供应商"}], ensure_ascii=False)
    rows = [
        {"Id": 1, "Numbers": "HW9901001", "ProblemType": 1, "Factory": "伊朗PEA工厂", "Factory2": "04",
         "ProductType": "101", "Series": "A系列", "PNList": "999999999999991", "InvInfo": inv, "ImpactQty": 30,
         "BadQty": 3, "Rate": "10%", "ProblemLevel": "A", "IsStop": 1, "StopState": 1, "StopDate": _text(3),
         "Status": 2, "MemberList": "11", "MemberListName": "测试甲", "RDepartment": 7, "RUser": "11,12",
         "AddDate": _ts(4)},
        {"Id": 2, "Numbers": "HW9901002", "ProblemType": 5, "Factory": "伊朗TOSAN工厂", "Factory2": "09",
         "ProductType": "102", "ImpactQty": 3000, "BadQty": 20, "Rate": "6.6667‰", "ProblemLevel": "B", "IsStop": 0,
         "StopState": 0, "StopDate": None, "Status": 32, "MemberList": None, "MemberListName": None,
         "RDepartment": 8, "RUser": "12", "AddDate": _ts(8)},
    ]
    return [{**base, **r} for r in rows]


FRAMES: dict[str, Any] = {
    "BrazilProblemProcess": pd.DataFrame([
        {"ID": 1, "ProblemID": 1, "ProcessUserID": 11, "FinishDate": None, "DebitMoney": 10.0,
         "IsDesignChange": "需要", "PlanCompleteDate": _text(-5)},
        {"ID": 2, "ProblemID": 3, "ProcessUserID": 12, "FinishDate": _ts(4), "DebitMoney": 5.5,
         "IsDesignChange": "不需要", "PlanCompleteDate": None},
        {"ID": 3, "ProblemID": 3, "ProcessUserID": 11, "FinishDate": _ts(2), "DebitMoney": 0.0,
         "IsDesignChange": "不需要", "PlanCompleteDate": None},
    ]),
    "BrazilProblemCost": pd.DataFrame([
        {"ID": 1, "ProblemID": 1, "CostMoney": 100.0, "CostBrlMoney": 0.0},
        {"ID": 2, "ProblemID": 1, "CostMoney": 0.0, "CostBrlMoney": 0.0},
        {"ID": 3, "ProblemID": 3, "CostMoney": 0.0, "CostBrlMoney": 500.0},
        {"ID": 4, "ProblemID": 4, "CostMoney": 20.0, "CostBrlMoney": 10.0},
    ]),
    "BrazilProblemPO": pd.DataFrame([{"ID": 1, "ProblemID": 1, "RequestID": 7},
                                     {"ID": 2, "ProblemID": 2, "RequestID": 8}]),
    "Brazil_RequestList": pd.DataFrame([{"ID": 7, "PartNumber": "999999999999991"}, {"ID": 8, "PartNumber": "0"}]),
    "NewProduct": pd.DataFrame([{"PartNumber": "999999999999991", "Name": "A99-000-TST-00"}]),
    "ProductName": pd.DataFrame([{"ID": 101, "ProductName": "A920", "Series": "A系列"},
                                 {"ID": 102, "ProductName": "Q92", "Series": "Q系列"},
                                 {"ID": 103, "ProductName": "L1400", "Series": "L系列"}]),
    "Brazil_Factory": pd.DataFrame([{"FactoryName": "CA"}, {"FactoryName": "TT"}, {"FactoryName": "TR"}]),
    "OverseasProblem_StepLog": pd.DataFrame([
        {"Id": 21, "ProblemId": 2, "StepStr": "结案确认", "AddDate": _ts(6)},
    ]),
}


def load(h: Any, *, br: Any = None, os_main: Any = None, cn: bool = True) -> None:
    """三域的帧都装进假连接器；`br`、`os_main` 给帧或可调用对象时替换主表。"""
    if cn:
        cn_data.load(h)
    info = h.connectors["info"]
    info.frames.update({k: v.copy() for k, v in FRAMES.items()})
    info.frames["BrazilProblemList"] = br if br is not None else pd.DataFrame(br_rows())
    info.frames["OverseasProblemDetail"] = os_main if os_main is not None else pd.DataFrame(os_rows())
    if not cn:
        info.frames.update({k: v.copy() for k, v in cn_data.FRAMES.items() if k in ("Employee", "Department",
                                                                                     "tbIQCvendor")})
        h.connectors["erp"].frames["PaxFactory"] = cn_data.FACTORIES.copy()
