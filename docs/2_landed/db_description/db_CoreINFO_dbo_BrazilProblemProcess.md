# BrazilProblemProcess（巴西制程问题处理过程）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.BrazilProblemProcess
- **所属域**：巴西
- **用途**：问题单的处理过程记录：原因分析、改善措施、库存处理、费用转嫁、供应商补料、设计更改、SQE 确认、责任人确认、效果确认与结案。一张单可有多条。
- **数据产生方**：INFO 系统巴西制程问题流转时写入。
- **最新一条**：同一 `ProblemID` 下 `ID` 最大的一条。问题跟进人取最新一条的 `ProcessUserID`，问题跟进部门取该人员所在部门。
- **8D 挂接**：本表 `ID` 是 8D 报告文档的业务记录 ID（见 `db_info_dbo_DocumentList.md`）。
- **两种读法**：问题单清单与汇总中的过程类字段只取最新一条；看「完整处理过程」时给该单全部记录，按 `ID` 升序。
- **是否类字段**：直接存中文（是 / 否 / 需要 / 不需要 / 改善 / 保持现状 / 确认 / 有效 / 无效），按原值展示。
- **SQE 两步**：先「SQE 跟进结果」（叙述），需要设计更改时进入待设计更改；设计更改完成后进入待 SQE 确认，由「SQE 确认结果」记录结论。
- **结案结果**：结案时由结案人评定的结果，与主表状态语义独立，不由状态推出。
- **叙述字段**：SQE 跟进结果、原因分析、改善措施、改善批次、预防对策及各「备注」「未转嫁原因」为富文本。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 自增主键 | `info.dbo.DocumentList.frecid`（8D） |
| ProblemID | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.BrazilProblemList.ID` |
| ProblemType | varchar | 问题类型 | 与主表独立冗余，取值同主表 | — |
| DisposeResult | nvarchar | SQE 跟进结果 | — | — |
| PlanCompleteDate | varchar | 计划完成日期 | 文本存日期，格式 `YYYY-MM-DD` | — |
| ReasonAnalysis | nvarchar | 原因分析 | — | — |
| ImprovementMeasure | nvarchar | 改善措施 | — | — |
| ImprovementBatch | nvarchar | 改善批次 | — | — |
| PrecautionPolicy | nvarchar | 预防对策 | — | — |
| IsStockPrecess | nvarchar | 是否库存处理 | 是 / 否 / 空 | — |
| StockPrecessQty | int | 库存处理数量 | — | — |
| SReturnOrderNo | nvarchar | 在库退货单号 | — | — |
| StockPrecessResult | nvarchar | 退货确认结果 | 是 / 否 / 空 | — |
| StockPrecessMemo | nvarchar | 退货确认备注 | — | — |
| StockPrecessUserID | int | 退货确认人 | 员工 ID | `info.dbo.Employee.ID` |
| StockPrecessDate | datetime | 退货确认时间 | — | — |
| IsCostShift | nvarchar | 是否有涉案金额 | 是 / 否 / 空 | — |
| DebitMoney | decimal | 扣款费用（美元） | — | — |
| DebitNumber | varchar | 扣款单号 | — | — |
| UnCostShiftReason | nvarchar | 未转嫁原因 | — | — |
| IsSupplementMaterial | nvarchar | 是否供应商补料 | 是 / 否 / 空 | — |
| SupplementMaterialQty | int | 供应商补料数量 | — | — |
| InStoreNumber | varchar | 入库单号 | — | — |
| IsDesignChange | nvarchar | 是否设计更改 | 需要 / 不需要 / 空 | — |
| DesignUserID | int | 设计更改人 | 员工 ID | `info.dbo.Employee.ID` |
| DesignResult | nvarchar | 设计更改结果 | 改善 / 保持现状 / 空 | — |
| DesignMemo | nvarchar | 设计更改备注 | — | — |
| DesignEstimateDate | nvarchar | 设计更改评估时间 | 文本存日期，格式 `YYYY-MM-DD` | — |
| DesignDate | datetime | 设计更改日期 | — | — |
| SQEResult | nvarchar | SQE 确认结果 | 确认 / 空 | — |
| SQEMemo | nvarchar | SQE 确认备注 | — | — |
| SQEUserID | int | SQE 确认人 | 员工 ID | `info.dbo.Employee.ID` |
| SQEDate | datetime | SQE 确认时间 | — | — |
| ProcessResult | nvarchar | 责任人确认结果 | 是 / 否 / 空 | — |
| ProcessMemo | nvarchar | 责任人确认备注 | — | — |
| ProcessUserID | int | 问题跟进人 | 员工 ID | `info.dbo.Employee.ID`（`Unit` → 问题跟进部门） |
| ProcessDate | datetime | 责任人确认日期 | — | — |
| ConfirmResult | nvarchar | 效果确认结果 | 有效 / 无效 / 空 | — |
| ConfirmMemo | nvarchar | 效果确认备注 | — | — |
| ConfirmUserID | int | 效果确认人 | 员工 ID | `info.dbo.Employee.ID` |
| ConfirmDate | datetime | 效果确认日期 | — | — |
| FinishResult | nvarchar | 结案结果 | 是 / 否 / 空 | — |
| FinishMemo | nvarchar | 结案备注 | — | — |
| FinishUserID | int | 结案人 | 员工 ID | `info.dbo.Employee.ID` |
| FinishDate | datetime | 结案日期 | — | — |

本域不使用源表的 `OReturnOrderNo`。
