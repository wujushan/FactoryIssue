"""详情与按号查单的假数据（单测夹具清单的写法：单号年份 99、「测试甲」「测试乙」、15 个 9 的编码），按表给假连接器。

在 `s3_data` 三域数据上补：国内另加三张单（J-D01 重启审核中、J-D02 5Why 待答复、5Why 所在环节已退回），国内各子表
（处理步骤、订单、小板订单、其他在线订单、现象、5Why、文档、CAR 报告）；巴西处理过程的叙述列与附件；海外处理步骤、
发货单与已选现象。J-D03（15 位编码在料号、PN 两处都命中）：编码 999999999999999 在 ZC9901001 的料号上，又在
ZC9901003 的生产订单 PN 上。日期相对「今天」生成。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import cn_data
import pandas as pd
import s3_data

TODAY = date.today()
CODE = "999999999999999"
IMG = '<p>按键<img src="data:image/png;base64,' + "QUJD" * 2000 + '"/>手感差</p>'


def _ts(days_ago: int, hour: int = 10) -> datetime:
    d = TODAY - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, hour, 0)


def cn_main() -> pd.DataFrame:
    rows = cn_data.main_rows()
    for r in rows:
        r.update({"ProblemDesc": None, "Reason": None, "Improve": None, "Measures": None, "Prevention": None,
                  "RConfirm": 1, "ZLConfirmResult": None, "Remark": None})
    rows[0].update({"CInvCode": CODE, "ProblemDesc": IMG, "Reason": "<p>按键弹片偏软</p>", "Measures": "更换弹片"})
    base = {**rows[0], "IQCStatus": None, "IQCMemberList": None, "IQCMemberListName": None, "CInvCode": None,
            "ProblemDesc": "<p>测试描述</p>", "Reason": None, "Measures": None, "Rate": None, "BadQty": None}
    rows += [
        {**base, "ID": 5, "Numbers": "ZC9901005", "Status": 2, "IsStop": 1, "StopStatus": 4, "StopDate": _ts(6),
         "ReStartExamineUser": "12", "ReStartScheme": "<p>方案甲</p>", "AddDate": _ts(7)},
        {**base, "ID": 6, "Numbers": "ZC9901006", "Status": 32, "IsStop": 0, "StopStatus": 3, "AddDate": _ts(8),
         "Reason": "<p>焊点虚焊</p>", "Measures": "<p>补焊</p>", "Prevention": "<p>加检</p>", "DesignConfirmResult": 1},
        {**base, "ID": 7, "Numbers": "ZC9901007", "Status": 2, "IsStop": 0, "StopStatus": 3, "AddDate": _ts(9),
         "Reason": "<p>驳回前写的原因</p>"},
    ]
    return pd.DataFrame(rows)


def _step(i: int, pid: int, code: int, name: str, days: int, **kw: Any) -> dict[str, Any]:
    return {"ID": i, "ProblemId": pid, "Step": code, "StepStr": name, "Result": None, "Opinon": None,
            "Measures": None, "FileUrl": None, "AddUser": 11, "AddDate": _ts(days), **kw}


STEPS = pd.DataFrame([
    _step(10, 2, 10, "SQE跟进", 9, AddUser=12, Result="0", Opinon="<p>供应商来料不良</p>"),
    _step(11, 2, 31, "结案确认", 5, Opinon="同意结案"),
    _step(12, 1, 29, "停线重启", 1),
    _step(13, 3, 3, "责任人确认", 15, AddUser=12),
    _step(20, 1, 1, "填写问题", 3, FileUrl="901,902"),
    _step(21, 1, 2, "指定责任人", 3, Measures="指定测试甲跟进"),
    _step(22, 1, 3, "责任人确认", 2, Measures="确认"),
    # J-D01：重启审核中
    _step(30, 5, 1, "填写问题", 7),
    _step(31, 5, 2, "指定责任人", 7),
    _step(32, 5, 29, "停线重启", 6, Result=(TODAY - timedelta(days=5)).isoformat(), Opinon="已恢复"),
    _step(33, 5, 34, "责任人填写重启方案", 5, AddUser=12, Opinon="方案甲"),
    _step(34, 5, 32, "停线重启审核", 4, Result="1", Opinon="同意重启"),
    # J-D02：5Why 随责任人确认显示
    _step(40, 6, 2, "指定责任人", 8),
    _step(41, 6, 3, "责任人确认", 8, Measures="确认，原因焊点虚焊"),
    _step(42, 6, 28, "驳回", 7, Measures="驳回任务,驳回说明:补充 5Why"),
    _step(43, 6, 3, "责任人确认", 6, Measures="重新确认"),
    _step(44, 6, 30, "效果确认", 3, Opinon="有效"),
    _step(45, 6, 31, "结案确认", 2, Opinon="同意结案"),
    # 责任人确认已退回（状态回到责任人确认，且这一步之前写过）
    _step(50, 7, 2, "指定责任人", 9),
    _step(51, 7, 3, "责任人确认", 8),
    _step(52, 7, 28, "驳回", 7, Measures="驳回任务,驳回说明:原因不清"),
])

FIVE = pd.DataFrame([
    {"ID": 1, "ProblemId": 6, "Question": "为什么虚焊", "Reason": "温度偏低", "Status": 1, "AddUser": 11,
     "AddDate": _ts(7), "UpdateUser": 12, "UpdateDate": _ts(6)},
    {"ID": 2, "ProblemId": 6, "Question": "为什么温度偏低", "Reason": None, "Status": 0, "AddUser": 11,
     "AddDate": _ts(6), "UpdateUser": None, "UpdateDate": None},
    {"ID": 3, "ProblemId": 7, "Question": "为什么不良", "Reason": "待查", "Status": 1, "AddUser": 11,
     "AddDate": _ts(8), "UpdateUser": 12, "UpdateDate": _ts(8)},
])

ORDERS = pd.DataFrame([
    {"ID": 1, "ProblemId": 3, "OrderNumber": "990001", "PartNumber": CODE, "PartName": "A99-000-TST-00",
     "IssueDate": _ts(20), "OrderQty": 100, "ReceiptQty": 90, "OnlineQty": 10, "Version": "V1"},
    {"ID": 2, "ProblemId": 1, "OrderNumber": "990002-1", "PartNumber": "999999999999998", "PartName": "A99-000-TST-01",
     "IssueDate": _ts(3), "OrderQty": 50, "ReceiptQty": 50, "OnlineQty": 0, "Version": "V1"},
    {"ID": 3, "ProblemId": 4, "OrderNumber": "990001", "PartNumber": "999999999999997", "PartName": "A99-000-TST-02",
     "IssueDate": _ts(25), "OrderQty": 30, "ReceiptQty": 30, "OnlineQty": 0, "Version": "V2"},
])
XB = pd.DataFrame([{"ID": 1, "ProblemId": 2, "OrderNumber": "990009", "InvCode": "999999999999996",
                    "InvStd": "测试磁头", "Qty": 20, "InQty": 10, "NoQty": 10, "Factory": "亮亮", "Description": "返工"}])
OTHER = pd.DataFrame([{"ID": 1, "ProblemId": 2, "OrderNo": "AB9900001", "ProductName": "A920", "Qty": 5,
                       "IssuedQty": 5, "IssQty": 5, "FaliaoDate": _ts(9), "ReturnQty": 0, "ReturnType": 3,
                       "ReceivingQty": 0, "TotalinQty": 0, "Factory": "05"}])
CHECK = pd.DataFrame([
    {"ID": 1, "ProblemId": 1, "ClassID": 1, "PhenomenonID": 11, "ReasonID": 21},
    {"ID": 2, "ProblemId": 1, "ClassID": 1, "PhenomenonID": 11, "ReasonID": 22},
    {"ID": 3, "ProblemId": 1, "ClassID": 1, "PhenomenonID": 12, "ReasonID": 0},
])
PHEN = pd.DataFrame([{"ID": 11, "PhenomenonDesc": "按键失灵"}, {"ID": 12, "PhenomenonDesc": "测试手填现象"}])
PREASON = pd.DataFrame([{"ID": 21, "PhenomenonID": 11, "ReasonDesc": "弹片疲劳"},
                        {"ID": 22, "PhenomenonID": 11, "ReasonDesc": "按键卡扣松"},
                        {"ID": 31, "PhenomenonID": 39, "ReasonDesc": "屏线松动"},
                        {"ID": 32, "PhenomenonID": 39, "ReasonDesc": "屏幕坏点"}])
PCLASS = pd.DataFrame([{"ID": 1, "TypeName": "功能问题", "ClassName": "按键"}])
PINV = pd.DataFrame([{"ID": 1, "ProblemId": 1, "InvCode": "999999999999995", "InvName": "按键", "InvStd": "测试按键"}])
DOCS = pd.DataFrame([
    {"ID": 901, "DocumentName": "测试照片", "DocumentRealName": "a.jpg", "frecid": 1, "BusinessType": "x",
     "EffectFlag": 0},
    {"ID": 902, "DocumentName": "已删除的照片", "DocumentRealName": "b.jpg", "frecid": 1, "BusinessType": "x",
     "EffectFlag": 1},
    {"ID": 911, "DocumentName": "测试 8D 报告", "DocumentRealName": "c.pdf", "frecid": 1,
     "BusinessType": "巴西制程问题单8D报告", "EffectFlag": 0},
    {"ID": 921, "DocumentName": "海外现场照片", "DocumentRealName": "d.jpg", "frecid": 1, "BusinessType": "海外制程问题",
     "EffectFlag": 0},
])
CAR = pd.DataFrame([{"fid": 5, "fdesc": "来料尺寸超差", "fstep2how1": "隔离库存", "fstep2how2": None, "fstep2how3": None,
                     "fstep3memo": "<p>模具磨损</p>", "fstep4memo": "<p>更换模具</p>", "fstep5memo": "定期点检",
                     "fstep6memo": "连续三批合格"}])

OS_PHEN = json.dumps([{"Key": 39, "Value": "黑屏、白屏"},
                      {"Key": -1, "parentType": "功能问题", "Value": "花屏", "otherVal": "夜间"}], ensure_ascii=False)
OS_STEPS = pd.DataFrame([
    {"Id": 1, "ProblemId": 1, "StepStr": "填写问题", "Result": None, "Opinon": None, "Measures": "测试乙填写问题",
     "DocID": None, "AddUser": 12, "AddDate": _ts(4)},
    {"Id": 2, "ProblemId": 1, "StepStr": "指定责任人", "Result": None, "Opinon": None, "Measures": "指定测试甲",
     "DocID": None, "AddUser": 12, "AddDate": _ts(4)},
    {"Id": 3, "ProblemId": 1, "StepStr": "责任人确认", "Result": None, "Opinon": "原因写了", "Measures": "确认",
     "DocID": None, "AddUser": 11, "AddDate": _ts(3)},
    {"Id": 4, "ProblemId": 1, "StepStr": "驳回", "Result": None, "Opinon": None, "Measures": "驳回任务,驳回说明:重写",
     "DocID": None, "AddUser": 12, "AddDate": _ts(2)},
    {"Id": 21, "ProblemId": 2, "StepStr": "工厂制程分析", "Result": "<p>贴片偏位</p>", "Opinon": "调整贴片程序",
     "Measures": None, "DocID": None, "AddUser": 11, "AddDate": _ts(7)},
    {"Id": 22, "ProblemId": 2, "StepStr": "结案确认", "Result": None, "Opinon": "同意结案", "Measures": None,
     "DocID": None, "AddUser": 12, "AddDate": _ts(6)},
])
DELIVERY = pd.DataFrame([
    {"Id": 2, "ProblemId": 2, "PO": "PO-99-002", "OrderNumber": "9900002", "Date": (TODAY - timedelta(days=9)).isoformat(),
     "PN": "999999999999991", "DeliveryVersion": "D1", "ProdVersion": "P1", "Quantity": 300, "Remark": None},
    {"Id": 1, "ProblemId": 2, "PO": "PO-99-001", "OrderNumber": "9900001", "Date": (TODAY - timedelta(days=10)).isoformat(),
     "PN": "999999999999991", "DeliveryVersion": "D1", "ProdVersion": "P1", "Quantity": 200, "Remark": "测试"},
])


def br_process() -> pd.DataFrame:
    frame = s3_data.FRAMES["BrazilProblemProcess"].copy()
    frame["ReasonAnalysis"] = ["<p>来料不良</p>", None, "<p>最新的原因</p>"]
    frame["ImprovementMeasure"] = ["<p>换料</p>", None, "<p>最新的措施</p>"]
    frame["IsStockPrecess"] = ["是", None, "否"]
    frame["StockPrecessQty"] = [12, None, None]
    frame["ProcessResult"] = ["是", None, "是"]
    frame["IsCostShift"] = ["是", None, "否"]
    frame["DebitNumber"] = ["DB990001", None, None]
    return frame


def load(h: Any, *, car_rows: bool = True) -> None:
    s3_data.load(h)
    info = h.connectors["info"]
    os_main = pd.DataFrame(s3_data.os_rows())
    os_main["hasCheckedPhenomenon"] = [OS_PHEN, None]
    os_main["DocId"] = ["921", None]
    os_main["Reason"] = ["<p>驳回前的原因</p>", None]
    br_main = pd.DataFrame(s3_data.br_rows())
    br_main["ProblemDesc"] = ["<p>巴西测试描述</p>", None, None, None]
    info.frames.update({
        "ZCTracking_ProblemList": cn_main(), "ZCTracking_ProblemSteplog": STEPS.copy(),
        "ZCTracking_ProblemFiveWhy": FIVE.copy(), "ZCTracking_ProblemOrders": ORDERS.copy(),
        "ZCTracking_XBOrders": XB.copy(), "ZCTracking_OtherOrder": OTHER.copy(), "ZCTracking_CheckReason": CHECK.copy(),
        "AfterSaleIssueClassPhenomenon": PHEN.copy(), "AfterSaleIssueClassPhenomenonReason": PREASON.copy(),
        "AfterSaleIssueClass": PCLASS.copy(), "ZCTracking_PossibleInvCode": PINV.copy(), "DocumentList": DOCS.copy(),
        "OverseasProblemDetail": os_main, "OverseasProblem_StepLog": OS_STEPS.copy(),
        "OverseasProblem_DeliveryOrder": DELIVERY.copy(), "BrazilProblemList": br_main,
        "BrazilProblemProcess": br_process(),
    })
    if car_rows:
        info.frames["tbIQCreportOut"] = CAR.copy()
