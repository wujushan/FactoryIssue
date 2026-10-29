"""国内假数据（单测夹具清单的写法：单号年份 99、「测试甲」「测试乙」、15 个 9 的编码），按表给假连接器。

`load(h)` 把各表的帧装进假连接器（按 SQL 里 FROM 的表名返回，不执行 WHERE）。日期都相对「今天」生成，
免得换算出的时间范围与数据对不上。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

TODAY = date.today()


def _ts(days_ago: int) -> datetime:
    d = TODAY - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, 10, 0)


def main_rows() -> list[dict[str, Any]]:
    base = {"OldProblemType": None, "ImpactQty": 10, "ProdQty": 100, "FoundDate": None, "Station": None,
            "Version": None, "OutPutStatus": 5, "MHead": None, "IsStop": 0, "StopStatus": 3, "StopDate": None,
            "CInvCode": None, "VenCode": None, "MemberList": "11", "MemberListName": "测试甲", "RDepartment": 7,
            "RUser": "11", "RCompleteTime": None, "AllReDepartment": None, "ReasonClass": None,
            "IsDesignChange": 0, "DesignConfirmResult": None, "IQCOpinion": None, "IQCStatus": None,
            "IQCMemberList": None, "IQCMemberListName": None, "CAR": None, "CARID": None, "AddUser": 11,
            "ProblemLevel": "B"}
    rows = [
        {"ID": 1, "Numbers": "ZC9901001", "ProblemType": 1, "Factory": "04", "Status": 8, "BadQty": 2,
         "Rate": 2.0, "AddDate": _ts(3), "IQCStatus": 6, "IQCMemberList": "12", "IQCMemberListName": "测试乙",
         "IsStop": 1, "StopStatus": 1, "StopDate": _ts(2), "ProblemLevel": "A"},
        {"ID": 2, "Numbers": "ZC9901002", "ProblemType": 3, "Factory": "05", "Status": 32, "BadQty": 5,
         "Rate": None, "AddDate": _ts(10), "MHead": "物料", "RDepartment": None, "RUser": None,
         "VenCode": "V99", "CAR": "CAR999999999", "CARID": 5, "MemberList": None, "MemberListName": None},
        {"ID": 3, "Numbers": "ZC9901003", "ProblemType": 1, "Factory": "09", "Status": 30, "BadQty": 1,
         "Rate": 1.0, "AddDate": _ts(20)},
        {"ID": 4, "Numbers": "ZC9901004", "ProblemType": 2, "Factory": "04", "Status": 2, "BadQty": None,
         "Rate": None, "AddDate": _ts(25), "ProblemLevel": None},
    ]
    return [{**base, **r} for r in rows]


FRAMES: dict[str, Any] = {
    "ZCTracking_ProductNames": pd.DataFrame([
        {"ID": 1, "ProblemId": 1, "ProductName": "A920", "Series": "A系列"},
        {"ID": 2, "ProblemId": 3, "ProductName": "A920", "Series": "A系列"},
        {"ID": 3, "ProblemId": 3, "ProductName": "A920PRO", "Series": "A系列"},
        {"ID": 4, "ProblemId": 4, "ProductName": "L1400", "Series": "L系列"},
    ]),
    "ZCTracking_ProblemSteplog": pd.DataFrame([
        {"ID": 10, "ProblemId": 2, "Step": 10, "StepStr": "SQE跟进", "Result": None, "AddUser": 12, "AddDate": _ts(9)},
        {"ID": 11, "ProblemId": 2, "Step": 31, "StepStr": "结案确认", "Result": None, "AddUser": 11, "AddDate": _ts(5)},
        {"ID": 12, "ProblemId": 1, "Step": 29, "StepStr": "停线重启", "Result": None, "AddUser": 11, "AddDate": _ts(1)},
        {"ID": 13, "ProblemId": 3, "Step": 3, "StepStr": "责任人确认", "Result": None, "AddUser": 12, "AddDate": _ts(15)},
    ]),
    "ZCTracking_RiskStream": pd.DataFrame(columns=["ID", "ProblemId", "Step", "Status", "UserID"]),
    "tbTask": pd.DataFrame([
        {"frecID": "3", "ftable": "ZCTracking_PreventionConfirm", "fuserID": "12", "fstat": "已接受"},
        {"frecID": "3", "ftable": "ZCTracking_ProblemRestart", "fuserID": "11", "fstat": "已接受"},
    ]),
    "Employee": pd.DataFrame([{"ID": 11, "Name": "测试甲", "Unit": 7}, {"ID": 12, "Name": "测试乙", "Unit": 8}]),
    "Department": pd.DataFrame([{"ID": 7, "Name": "生产工程部"}, {"ID": 8, "Name": "研发一部"}]),
    "tbIQCvendor": pd.DataFrame([{"ferpcode": "V99", "fname": "测试供应商"}]),
}
FACTORIES = pd.DataFrame([{"FactoryID": "04", "FactoryName": "柯洱斯"}, {"FactoryID": "06", "FactoryName": "柯洱斯"},
                          {"FactoryID": "05", "FactoryName": "亮亮"}, {"FactoryID": "09", "FactoryName": "惠州百富"}])


def load(h: Any, *, main: Any = None) -> None:
    """装进假连接器；`main` 给可调用对象时按 SQL 与参数现给主表（如按时间条件返回空）。"""
    info = h.connectors["info"]
    info.frames.update({k: v.copy() for k, v in FRAMES.items()})
    info.frames["ZCTracking_ProblemList"] = main if main is not None else pd.DataFrame(main_rows())
    h.connectors["erp"].frames["PaxFactory"] = FACTORIES.copy()
