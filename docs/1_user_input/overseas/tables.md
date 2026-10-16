# 海外制程问题表整理

## 表描述 (Tables & Aliases)

1. **CoreINFO.dbo.OverseasProblemDetail**
  - **描述**：主表，海外问题详情表。
  - **作用**：存储问题的核心数据，如问题类型 (ProblemType)、单号 (Numbers)、工厂 (Factory)、添加人 (AddUser)、发现日期 (FoundDate)、产品类型 (ProductType)、影响数量 (ImpactQty) 等。
2. **info.dbo.Employee**
  - **描述**：员工信息表（位于 info 数据库的 dbo 架构下）。
  - **作用**：通过主表的添加人ID，查询并显示具体的员工姓名 (Name as AddUserName)。
3. **info.dbo.ProductName**
  - **描述**：产品名称表（同样位于 info 数据库下）。
  - **作用**：用于将主表中存储的产品ID转换为具体的产品名称 (ProductName)。
4. **CoreINFO.dbo.OverseasProblem_StepLog**
  - **描述**：海外问题处理步骤/日志表。
  - **作用**：记录针对某个问题 (ProblemId) 的多次处理日志或步骤。在此 SQL 中用于提取并拼接参与该问题的所有成员列表 (MemberList)。
5. **CoreINFO.dbo.OverseasProblem_DeliveryOrder**：包含 10 个字段，主要记录海外问题相关的发货单信息，包括发货单号、日期、物料编号、版本、数量及采购订单号等。该表通过 `ProblemId` 与主表 `OverseasProblemDetail` 关联。
6. **paxbase.dbo.PaxFactory：用于存储国内工厂名称。**
7. **CoreINFO.dbo.AfterSaleIssueClassPhenomenon:** 用于存储售后问题分类与故障现象的关联关系。该表通过 `ClassID` 关联到售后问题分类主表，并记录具体的 `PhenomenonDesc`（故障现象描述）。同时包含标准的审计字段（创建人、创建时间、最后修改人、最后修改时间），用于追踪数据的变更历史。
8. **CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason:** 用于存储售后问题中特定故障现象对应的故障原因信息。该表通过 `PhenomenonID` 关联到具体的故障现象，并记录原因描述（`ReasonDesc`）及标准的审计字段（录入人、创建时间、最后修改人、最后修改时间）。
9. **info.dbo.DocumentList**：核心业务附件与文库文档主表，包含完整的文档元数据、业务关联字段（BusinessType, frecid）及状态标志。



## 表字段说明



### OverseasProblemDetail


| **字段名称**             | **字段类型** | **字段描述**                                                                                                                                                                |
| -------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Id                   | int      | 主键。                                                                                                                                                                     |
| Factory              | varchar  | 加工厂（海外工厂名称）                                                                                                                                                             |
| ProblemType          | int      | 问题类型。枚举：1=硬件问题；2=软件问题；3=物料问题；4=其他；5=工厂制程；6=结构问题；7=制程优化。                                                                                                                 |
| InvInfo              | varchar  | 物料信息。JSON 数组（materialDesc/PN/supplier/supplierName），非独立子表。【关联】供应商编码supplier关联 Info.dbo.tbIQCvendor.ferpcode（JSON 内存，非外键）。                                               |
| ImpactQty            | int      | 影响数量。                                                                                                                                                                   |
| BadQty               | int      | 不良数量。                                                                                                                                                                   |
| Rate                 | varchar  | 不良率。格式有`30%`、`6.6667‰`、`1.72%`、`100%`、`0.1‰` （% 和 ‰ 混用）                                                                                                                 |
| hasCheckedPhenomenon | varchar  | 已选问题现象。JSON 数组（Key/Value/parentType/otherVal）。【关联】Key>0 为 AfterSaleIssueClassPhenomenon 现象ID；Key<0 为手填现象。可能原因经 AfterSaleIssueClassPhenomenonReason 按现象ID查询。             |
| ProblemLevel         | varchar  | 问题等级。有A+/A/B/C或为NULL / 空。                                                                                                                                               |
| FoundDate            | varchar  | 发现日期或现场发现日期                                                                                                                                                             |
| Version              | varchar  | 版本。                                                                                                                                                                     |
| Station              | varchar  | 发现工位。                                                                                                                                                                   |
| IsStop               | int      | 是否停线。枚举：0=否；1=是。后续停线重启后，也不会改变该值。展示停线过程看 StopState。                                                                                                                      |
| StopDate             | varchar  | 停线日期。                                                                                                                                                                   |
| ProblemDesc          | varchar  | 问题描述。自由文本，可能包含有图片base64编码的数据                                                                                                                                            |
| Improve              | varchar  | 改善建议。自由文本，可能包含有图片base64编码的数据                                                                                                                                            |
| Remark               | varchar  | 备注。                                                                                                                                                                     |
| Status               | int      | 制程问题单状态。取值：1=指定责任人；2=责任人确认；3=其他问题确认；4=IQC意见；5=工厂制程分析；6=IQC确认；7=填写退货单号；8=SQE跟进；9=设计更改；10=设计变更后SQE确认；30=效果确认；31=结案确认；32=已完成。过程节点另见 OverseasProblem_StepLog.ProblemStatus。 |
| Numbers              | varchar  | 问题编号。按月生成 HW+yyMM+3位序号，如： HW2609001                                                                                                                                     |
| AddDate              | datetime | 建单时间                                                                                                                                                                    |
| AddUser              | int      | 创建人。【关联】Info.dbo.Employee.ID。                                                                                                                                           |
| Series               | varchar  | 系列。选 PN 时随大机型带出。【关联】Info.dbo.ProductName.Series / Info.dbo.NewProduct（非外键，存名称或系列文本）。                                                                                    |
| ProductType          | varchar  | 大机型。逗号分隔 ID。【关联】Info.dbo.ProductName.ID（LIKE 匹配 ','+ProductType+','）。                                                                                                   |
| PNList               | varchar  | PN列表。逗号分隔物料编号 PN。【关联】Info.dbo.NewProduct.PartNumber（LIKE 匹配 ','+PNList+','）。                                                                                            |
| Factory2             | varchar  | 国内工厂。关联PaxFactory.FactoryID                                                                                                                                             |
| ProblemRemark        | varchar  | 其他问题说明（ProblemType=4 时使用）。                                                                                                                                              |
| MemberListName       | varchar  | 当前处理人名称。冗余展示，与 MemberList 对应。【关联】Info.dbo.Employee.Name（由 MemberList 拼出）。是问题单流转最新节点下的处理人                                                                                |
| MemberList           | varchar  | 当前处理人ID。逗号分隔当前节点办理人。【关联】Info.dbo.Employee.ID。是问题单流转最新节点下的处理人ID列表                                                                                                        |
| DocId                | varchar  | 附件id。逗号分隔。【关联】Info.dbo.DocumentList.ID（填单附件）。                                                                                                                           |
| StopState            | int      | 停线状态。展示：1=停线中；2=已经重启；其它/0=没有停线。                                                                                                                                         |
| ReStartDate          | datetime | 重启日期。停线重启时写入。                                                                                                                                                           |
| RDepartment          | int      | 问题跟进部门。是问题跟进人所在的部门。空或部门ID。【关联】Info.dbo.Department.ID。                                                                                                                   |
| RUser                | nvarchar | 问题跟进人。空、或一个或多个员工ID，使用逗号分隔【关联】Info.dbo.Employee.ID。如：4535,4527                                                                                                           |
| RConfirm             | int      | 问题跟进人确认。0/空=否（不重新走流程）；>0=是。                                                                                                                                             |
| RCompleteTime        | datetime | 问题跟进人计划完成时间。                                                                                                                                                            |
| DesignConfirmResult  | int      | 设计变更确认结果。枚举（DesignConfirmResultDic）：1=改善；2=保持现状；3=挂起。                                                                                                                   |
| Reason               | varchar  | 问题原因。责任人确认/原因分析文本。自由文本                                                                                                                                                  |
| Prevention           | nvarchar | 预防对策、工厂制程制定对策。自由文本。                                                                                                                                                     |
| Measures             | nvarchar | 改善措施、工厂制程原因分析、物料问题设计变更改善情况/原因说明。自由文本。                                                                                                                                   |
| OldProblemType       | int      | 旧问题类型。改分类前的 ProblemType，枚举同 ProblemType。                                                                                                                                |
| Confirmation         | nvarchar | 效果确认。效果确认结论文本。                                                                                                                                                          |
| ConfirmUser          | int      | 效果确认人。【关联】Info.dbo.Employee.ID                                                                                                                                          |
| ConfirmDate          | datetime | 效果确认时间。                                                                                                                                                                 |
| IsDelete             | bit      | 是否删除。0/false=否；1/true=是（逻辑删除）。                                                                                                                                          |
| IQCOpinion           | int      | IQC意见。枚举：2是退回仓库，3是继续使用。                                                                                                                                                 |
| OtherOnline          | varchar  | 其他在线。JSON，结构同 ZCTracking_OtherOrder（Factory 等），内嵌本列、不落 ZCTracking_OtherOrder 表。Factory 码同 Factory2。【关联】无物理外键。                                                           |
| StockList            | varchar  | 库存。JSON，结构同 ZCTracking_Stock，内嵌本列、不落 ZCTracking_Stock 表。【关联】无物理外键。                                                                                                      |
| OReturnOrderNo       | nvarchar | 在线退货单号。                                                                                                                                                                 |
| SReturnOrderNo       | nvarchar | 在库退货单号。                                                                                                                                                                 |
| IsDesignChange       | int      | 是否设计变更。枚举：0=否；1=是。                                                                                                                                                      |
| DesignUser           | int      | 设计变更责任人。【关联】Info.dbo.Employee.ID。                                                                                                                                       |
| DesignDate           | datetime | 设计更改预计完成时间。                                                                                                                                                             |




### OverseasProblem_StepLog


| **字段名称**      | **字段类型** | **字段描述**                         |
| ------------- | -------- | -------------------------------- |
| Id            | int      | 主键。                              |
| ProblemId     | int      | 问题ID， 关联OverseasProblemDetail.ID |
| Step          | int      | 步骤序号。                            |
| AddUser       | int      | 创建人。关联 Employee.ID               |
| AddDate       | datetime | 创建/发生时间。                         |
| ProblemStatus | int      | 问题状态。                            |
| MemberList    | varchar  | 成员列表。                            |
| StepStr       | varchar  | 步骤描述                             |
| Result        | nvarchar | 结论                               |
| Opinon        | nvarchar | 意见                               |
| Measures      | nvarchar | 预防措施                             |
| DocID         | varchar  | 文件id，关联`DocumentList.ID`         |


- `StepStr`表示一个步骤名称，会有重复，需去重：对同一问题（ProblemId）的相同步骤（StepStr），只保留最新记录

### 表： PaxFactory

**表名：** PaxFactory


| **序号** | **字段名称**    | **字段类型**      | **字段描述** |
| ------ | ----------- | ------------- | -------- |
| 1      | FactoryID   | varchar(50)   | 国内工厂码    |
| 2      | FactoryName | nvarchar(100) | 国内工厂名称   |




### **表：AfterSaleIssueClassPhenomenon**


| **序号** | **字段名称**       | **字段类型** | **字段描述**        |
| ------ | -------------- | -------- | --------------- |
| 1      | ID             | int      | 主键。             |
| 2      | ClassID        | int      | 关联分类主键。         |
| 3      | PhenomenonDesc | nvarchar | 故障现象描述。         |
| 4      | AddUser        | int      | 录入人 Employee.ID |
| 5      | AddDate        | datetime | 创建时间。           |
| 6      | LastUser       | int      | 最后修改人。          |
| 7      | LastDate       | datetime | 最后修改时间。         |




### **表：AfterSaleIssueClassPhenomenonReason**


| **字段名称**     | **字段类型** | **字段描述**                                  |
| ------------ | -------- | ----------------------------------------- |
| ID           | int      | 主键。                                       |
| PhenomenonID | int      | 关联不良现象主键。AfterSaleIssueClassPhenomenon.ID |
| ReasonDesc   | nvarchar | 故障原因描述。                                   |
| AddUser      | int      | 录入人Employee.ID。                           |
| AddDate      | datetime | 创建时间。                                     |
| LastUser     | int      | 最后修改人。                                    |
| LastDate     | datetime | 最后修改时间。                                   |




### **表：OverseasProblem_DeliveryOrder**


| **字段名称**        | **字段类型** | **字段描述**                            |
| --------------- | -------- | ----------------------------------- |
| Id              | int      | 主键。                                 |
| ProblemId       | int      | 海外问题ID，关联`OverseasProblemDetail.ID` |
| OrderNumber     | varchar  | 发货单号                                |
| Date            | varchar  | 发货日期                                |
| PN              | varchar  | 物料编号 PN。                            |
| DeliveryVersion | varchar  | 发货版本                                |
| ProdVersion     | varchar  | 生产版本                                |
| Quantity        | int      | 订单数量                                |
| Remark          | varchar  | 备注                                  |
| PO              | varchar  | 采购订单号 PO。                           |




### **表：DocumentList**

**表描述**：通用文档清单


| 字段名称              | 字段类型     | 字段描述                                |
| ----------------- | -------- | ----------------------------------- |
| ID                | int      | 文档唯一 ID                             |
| DocumentName      | nvarchar | 文档名称                                |
| DocumentRealName  | nvarchar | 文档全称（含后缀）                           |
| DocumentExtension | nvarchar | 扩展名                                 |
| DocumentPath      | nvarchar | 存储路径                                |
| frecid            | int      | 业务记录 ID； `OverseasProblemDetail.ID` |
| AddDate           | datetime | 添加时间                                |
| EffectFlag        | int      | 删除标志：0=有效，1=已删除                     |
| BusinessType      | varchar  | 业务名称；例如：海外制程问题                      |


`frecid` ∈ 该制程制程问题主键 `ID`，且 `EffectFlag = 0`。