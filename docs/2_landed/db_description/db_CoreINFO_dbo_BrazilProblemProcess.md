# BrazilProblemProcess（巴西制程问题处理过程）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.BrazilProblemProcess
- **所属域**：巴西
- **用途**：问题单的处理过程记录：原因分析、改善措施、库存处理、费用转嫁、供应商补料、设计更改、SQE 确认、责任人确认、效果确认与结案。一张单可有多条。
- **数据产生方**：INFO 系统巴西制程问题流转时写入。
- **最新一条**：同一 `ProblemID` 下 `ID` 最大的一条。问题跟进人取最新一条的 `ProcessUserID`，问题跟进部门取该人员在人员表里现在所在的部门。
- **8D 报告与设计更改附件挂接**：本表 `ID` 是这两类文档的业务记录 ID（见 `db_info_dbo_DocumentList.md`）。
- **只取最新一条**：问题单清单、汇总、单张单详情与「完整处理过程」都只取最新一条。前几条是同一单此前的处理轮次，最新一条已在其基础上修改补充（业务方 2026-10-23 答复，见巴西业务描述「单张单详情」）。8D 报告与设计更改附件例外：挂在该单全部处理过程上的有效文档都给。
- **是否类字段**：直接存中文（是 / 否 / 需要 / 不需要 / 改善 / 保持现状 / 确认 / 有效 / 无效），按原值展示。
- **SQE 两步**：先「SQE 跟进结果」（叙述），需要设计更改时进入待设计更改；设计更改完成后进入待 SQE 确认，由「SQE 确认结果」记录结论。
- **结案结果**：结案时由结案人评定的结果，与主表状态语义独立，不由状态推出。
- **叙述字段**：SQE 跟进结果、原因分析、改善措施、改善批次、预防对策及各「备注」「未转嫁原因」为富文本。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 自增主键 | `info.dbo.DocumentList.frecid`（8D 报告、设计更改附件） |
| ProblemID | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.BrazilProblemList.ID` |
| ProblemType | varchar | （内部字段，不返回） | 与主表独立冗余，取值与 `其他\|备注` 写法同主表。不展示，也不参与筛选、统计、跨域归并，这些只用主表问题类型 | — |
| DisposeResult | nvarchar | SQE 跟进结果 | — | — |
| PlanCompleteDate | varchar | 计划完成日期 | 文本存日期，格式 `YYYY-MM-DD` | — |
| ReasonAnalysis | nvarchar | 原因分析 | — | — |
| ImprovementMeasure | nvarchar | 改善措施 | — | — |
| ImprovementBatch | nvarchar | 改善批次 | — | — |
| PrecautionPolicy | nvarchar | 预防对策 | — | — |
| IsStockPrecess | nvarchar | 是否库存处理 | 是 / 否 / 空 | — |
| StockPrecessQty | int | 库存处理数量 | 「是否库存处理」为「是」时展示，与管理页面一致 | — |
| IsCostShift | nvarchar | 费用转嫁 | 是 / 否 / 空：费用是否转嫁给供应商，为是时另有扣款费用与扣款单号。显示名与管理页面一致。用户说「涉案金额」指费用明细（见费用表），不是这一项 | — |
| DebitMoney | decimal | 扣款费用（美元） | — | — |
| DebitNumber | varchar | 扣款单号 | — | — |
| UnCostShiftReason | nvarchar | 未转嫁原因 | — | — |
| IsSupplementMaterial | nvarchar | 是否供应商补料 | 是 / 否 / 空 | — |
| SupplementMaterialQty | int | 供应商补料数量 | 「是否供应商补料」为「是」时展示，与管理页面一致 | — |
| InStoreNumber | varchar | 入库单号 | 「是否供应商补料」为「是」时展示，与管理页面一致 | — |
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
| FinishResult | nvarchar | 结案结果 | 是 / 否 / 空。管理页面「结案确认」下写作「是否结案」；它是结案人的评定，单是否已结案仍只看主表状态 | — |
| FinishMemo | nvarchar | 结案备注 | — | — |
| FinishUserID | int | 结案人 | 员工 ID | `info.dbo.Employee.ID` |
| FinishDate | datetime | 结案日期 | 已结案的单，最新一条处理过程上的结案日期即该单的「结案时间」（见总述「结案时间与结案周期」） | — |

本域不使用源表的 `OReturnOrderNo`（在线退货单号），以及库存处理的 `SReturnOrderNo`（在库退货单号）、`StockPrecessResult`（退货确认结果）、`StockPrecessMemo`（退货确认备注）、`StockPrecessUserID`（退货确认人）、`StockPrecessDate`（退货确认时间）：库存处理暂只给是否库存处理与库存处理数量，这几列不展示、不作筛选条件（见巴西业务描述「补料与库存处理」）。
