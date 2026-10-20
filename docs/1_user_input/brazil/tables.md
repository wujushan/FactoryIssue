# 巴西制程问题表整理

## 表的描述

可分为：核心业务表、基础资料表、文档表。

### 核心业务表

- **CoreINFO.dbo.BrazilProblemList（主表）**：`CoreINFO.dbo.BrazilProblemList` 是巴西工厂问题跟踪的核心主表，用于记录生产或质量问题的详细信息。该表涵盖了从问题发现（日期、工位、现象）、影响评估（数量、级别）、处理过程（补料、8D报告、费用产生）到最终状态跟踪的全生命周期数据。它通过 `ProblemID` 与成本表 (`BrazilProblemCost`)、存货表 (`BrazilProblemInvCode`)、采购订单表 (`BrazilProblemPO`) 及处理过程表 (`BrazilProblemProcess`) 等子表关联，形成完整的问题闭环管理。
- **CoreINFO.dbo.BrazilProblemProcess**：用于记录巴西工厂生产或质量问题的详细处理过程。该表通过 `ProblemID` 关联主表 `CoreINFO.dbo.BrazilProblemList`，涵盖了从问题原因分析、改善措施制定、库存处理、费用转移、设计变更、SQE确认到最终结案确认的全生命周期字段。
- **CoreINFO.dbo.BrazilProblemCost**：用于记录巴西问题跟踪中的成本明细，包含费用类型、金额（含巴西雷亚尔）、汇率及备注等信息，通过 `ProblemID` 关联至问题主表。
- **CoreINFO.dbo.BrazilProblemPO**：用于记录巴西问题跟踪中的采购订单相关信息，主要包含问题关联ID、申请单关联ID、在线数量、发票号汇总、请求类型及备注等字段。桥接 RequestList 以解析 PN。
- **CoreINFO.dbo.BrazilProblemInvCode**：用于记录巴西问题跟踪中涉及的存货编码及其相关数量信息，通过 `ProblemID` 关联至问题主表，包含存货编码、数量及库存数量等关键字段。
- **info.dbo.ProductName**：产品名称的主数据表，包含产品的基础信息（如名称、编码、系列、分类）、状态标识（如是否在用、是否分体、是否有SN）、关联人员信息（如产品经理、工程师）以及扩展自定义字段。该表通过 `ID` 作为主键，与其他业务表（如认证证书、制程问题等）进行关联。
- **info.dbo.NewProduct**：新产品的主数据表，包含产品的基本信息（如料号、名称、描述）、分类信息（大类、小类、市场名称）、物理属性（重量、尺寸）、状态信息（在用状态、试产进度、量产状态）以及相关的业务属性（如是否含锂电池、是否需要核算、SN规则等）。该表通过 `ProductID` 关联产品族，通过 `PartNumber` 作为业务主键被其他业务表引用。
- **info.dbo.Brazil_RequestList**：是巴西业务域中的核心需求/请票主表，用于记录巴西工厂或外贸业务的需求订单信息。该表通过 `RequestID` 关联下游的发票表（`Brazil_InvoiceList`）和明细表（`Brazil_RequestItem`），并通过 `ContractID` 关联合同表，`ClientID` 关联客户表。表中包含需求数量、状态、齐料状态、销售价等关键业务字段，是巴西业务流程中从需求到发货、开票的核心驱动表。
- **CoreINFO.dbo.AfterSaleIssueClass**：用于定义售后问题的分类体系。该表不仅包含分类的基本信息（如名称、类型），还定义了不同问题等级（A/B/C）对应的不良率阈值范围（下限与上限），并记录了分类的适用场景（人工使用、客户使用、海外制程使用）以及审计字段（创建/修改人与时间）。该表通过 `ClassID` 与其他表（如现象、原因、存货分类码）建立关联。
- **info.dbo.Brazil_Factory**：用于存储巴西工厂的基础信息，包括工厂名称、地址、联系方式、所属公司、站点及职责段落等，~~并通过~~ `ClientID` ~~字段关联至~~ `info.dbo.Brazil_Client` ~~表以标识工厂对应的客户~~。
- **info.dbo.DocumentList**：核心业务附件与文库文档主表，包含完整的文档元数据、业务关联字段（BusinessType, frecid）及状态标志。

### 基础资料表

- **Employee / Department**：人员姓名与部门。
- **Inventory**：物料编码、名称、规格。
- **tbIQCvendor**：供应商 ERP 编码与名称。
- **ProductName**：大机型名称（主表 `ProductIDAll`）。
- **NewProduct**：PN 机型名称（经 RequestList）。
- **Brazil_RequestList**：请求单 → PartNumber（PN 桥接）。
- **AfterSaleIssueClass**：停线级别名称。
- **Brazil_Factory**：工厂名称主数据。

### 文档表

- **DocumentList**：通用文档；本域用于挂接 8D 报告。

---

## 核心业务表

### BrazilProblemList

**表描述**：巴西制程问题主表。


| 序号  | 字段名称                    | 字段类型     | 字段描述                                                                                |
| --- | ----------------------- | -------- | ----------------------------------------------------------------------------------- |
| 1   | ID                      | int      | 自增 ID                                                                               |
| 2   | OrderNumber             | varchar  | 问题编号，如 BR2404001、BR2601009                                                          |
| 3   | ClaimNumber             | varchar  | 投诉单号（自由文本）                                                                          |
| 4   | BrazilFactory           | varchar  | 巴西工厂**名称**（非 ID）；来源 `Brazil_Factory.FactoryName`；可逗号多值如 `CA,TT`                     |
| 5   | ProductIDAll            | varchar  | 大机型 ID；空/单值/`，`分隔多值；关联 `ProductName.ID`                                             |
| 6   | ProblemType             | varchar  | 问题类型：设计问题、结构问题、生产问题、制程优化、硬件问题、物料问题、其他；`其他                                           |
| 7   | IsStopLine              | varchar  | 是否发生过停线（是/否，默认否）；发生后不因重启改回否                                                         |
| 8   | StopDate                | varchar  | 停线日期                                                                                |
| 9   | StopStatus              | varchar  | 停线重启状态；空=未标记重启；`停线重启`=已重启                                                           |
| 10  | ProblemClass            | varchar  | 停线级别；关联 `AfterSaleIssueClass.ID`                                                    |
| 11  | ProblemPhenomenon       | nvarchar | 问题现象（JSON 数组）                                                                       |
| 12  | ProblemLevel            | varchar  | 问题等级：A/B/C/空                                                                        |
| 13  | ProblemDiscoveryDate    | varchar  | 现场发现日期                                                                              |
| 14  | ProblemDiscoveryStation | varchar  | 发现工位（自由文本，可空）                                                                       |
| 15  | StatisticsDate          | varchar  | 统计日期                                                                                |
| 16  | cInvCode                | varchar  | 物料编号；关联 `Inventory.cInvCode`                                                        |
| 17  | cVenCode                | varchar  | 供应商编号；关联 `tbIQCvendor.ferpcode`                                                     |
| 18  | ImpactQty               | int      | 影响数量                                                                                |
| 19  | BadQty                  | int      | 不良数量                                                                                |
| 20  | ProblemDesc             | nvarchar | 问题描述                                                                                |
| 21  | IsRequire8D             | int      | 是否需要回复 8D（1=是；2=否）                                                                  |
| 22  | IsSupplement            | int      | 是否需要补料（1=是；2=否）                                                                     |
| 23  | SupplementQty           | int      | 补料数量                                                                                |
| 24  | SupplementResult        | varchar  | 补料结果。（是、否、null）                                                                     |
| 25  | SupplementMemo          | nvarchar | 补料备注                                                                                |
| 26  | SupplementUserID        | int      | 补料人；关联 `Employee.ID`                                                                |
| 27  | SupplementDate          | datetime | 补料日期                                                                                |
| 28  | IsCost                  | int      | 是否涉及费用（1=是；2=否；0=测试脏值）                                                              |
| 29  | ActorUserID             | int      | 初始责任人；关联 `Employee.ID`                                                              |
| 30  | Memo                    | nvarchar | 备注                                                                                  |
| 31  | AddUserID               | int      | 填单人；关联 `Employee.ID`                                                                |
| 32  | AddDate                 | datetime | 建单日期                                                                                |
| 33  | UpdateUserID            | int      | 最后修改人；关联 `Employee.ID`                                                              |
| 34  | UpdateDate              | datetime | 最后修改时间                                                                              |
| 35  | Status                  | int      | 制程单状态：0 待提交；10 待修改类别；20 待跟进；25 待设计更改；26 待SQE确认；30 待效果确认；40 待结案；50 已结案；-2 已终止；-1 已删除 |


**已从本域剔除（相对源表）**：`RequestID`（PN 不以本字段为准）、`MailCount`。

### BrazilProblemProcess

**表描述**：巴西问题处理过程记录。


| 序号  | 字段名称                  | 字段类型     | 字段描述                                    |
| --- | --------------------- | -------- | --------------------------------------- |
| 1   | ID                    | int      | 自增 ID（亦可作为 8D 文档 `DocumentList.frecid`） |
| 2   | ProblemID             | int      | 关联 `BrazilProblemList.ID`               |
| 3   | ProblemType           | varchar  | 问题类型（与主表独立冗余）                           |
| 4   | DisposeResult         | nvarchar | SQE 跟进结果                                |
| 5   | PlanCompleteDate      | varchar  | 计划完成日期                                  |
| 6   | ReasonAnalysis        | nvarchar | 原因分析                                    |
| 7   | ImprovementMeasure    | nvarchar | 改善措施                                    |
| 8   | ImprovementBatch      | nvarchar | 改善批次                                    |
| 9   | PrecautionPolicy      | nvarchar | 预防对策                                    |
| 10  | IsStockPrecess        | nvarchar | 是否库存处理：是、否、为空                           |
| 11  | StockPrecessQty       | int      | 库存处理数量                                  |
| 12  | SReturnOrderNo        | nvarchar | 在库退货单号                                  |
| 13  | StockPrecessResult    | nvarchar | 退货确认结果：是、否、为空                           |
| 14  | StockPrecessMemo      | nvarchar | 退货确认备注                                  |
| 15  | StockPrecessUserID    | int      | 退货确认人；关联 `Employee.ID`                  |
| 16  | StockPrecessDate      | datetime | 退货确认时间                                  |
| 17  | IsCostShift           | nvarchar | 是否有涉案金额：是、否、为空                          |
| 18  | DebitMoney            | decimal  | 扣款费用（美元）                                |
| 19  | DebitNumber           | varchar  | 扣款单号                                    |
| 20  | UnCostShiftReason     | nvarchar | 未转嫁原因                                   |
| 21  | IsSupplementMaterial  | nvarchar | 是否供应商补料：是、否、为空                          |
| 22  | SupplementMaterialQty | int      | 供应商补料数量                                 |
| 23  | InStoreNumber         | varchar  | 入库单号                                    |
| 24  | IsDesignChange        | nvarchar | 是否设计更改：null、需要、不需要、为空                   |
| 25  | DesignUserID          | int      | 设计更改人；关联 `Employee.ID`                  |
| 26  | DesignResult          | nvarchar | 设计更改结果：改善、保持现状、null                     |
| 27  | DesignMemo            | nvarchar | 设计更改备注                                  |
| 28  | DesignEstimateDate    | nvarchar | 设计更改评估时间                                |
| 29  | DesignDate            | datetime | 设计更改日期                                  |
| 30  | SQEResult             | nvarchar | SQE 确认结果：确认、为空                          |
| 31  | SQEMemo               | nvarchar | SQE 确认备注                                |
| 32  | SQEUserID             | int      | SQE 确认人；关联 `Employee.ID`                |
| 33  | SQEDate               | datetime | SQE 确认时间                                |
| 34  | ProcessResult         | nvarchar | 责任人确认结果：null、是、否                        |
| 35  | ProcessMemo           | nvarchar | 责任人确认备注                                 |
| 36  | ProcessUserID         | int      | 问题责任人/跟进人；关联 `Employee.ID`              |
| 37  | ProcessDate           | datetime | 确认日期                                    |
| 38  | ConfirmResult         | nvarchar | 效果确认结果：有效、无效、null                       |
| 39  | ConfirmMemo           | nvarchar | 效果确认备注                                  |
| 40  | ConfirmUserID         | int      | 效果确认人；关联 `Employee.ID`                  |
| 41  | ConfirmDate           | datetime | 效果确认日期                                  |
| 42  | FinishResult          | nvarchar | 结案结果：null、是、否                           |
| 43  | FinishMemo            | nvarchar | 结案备注                                    |
| 44  | FinishUserID          | int      | 结案人；关联 `Employee.ID`                    |
| 45  | FinishDate            | datetime | 结案日期                                    |


**已从本域剔除**：`OReturnOrderNo`（v1 未使用）。

### BrazilProblemCost

**表描述**：巴西问题费用明细。


| 序号  | 字段名称         | 字段类型     | 字段描述                      |
| --- | ------------ | -------- | ------------------------- |
| 1   | ID           | int      | 主键                        |
| 2   | ProblemID    | int      | 关联 `BrazilProblemList.ID` |
| 3   | CostType     | nvarchar | 费用类型                      |
| 4   | CostMoney    | decimal  | 花费金额（美元）                  |
| 5   | CostBrlMoney | decimal  | 花费金额（BRL）                 |
| 6   | ConstBrlRate | decimal  | 巴西汇率                      |
| 7   | CostMemo     | nvarchar | 备注                        |


### BrazilProblemPO

**表描述**：问题与采购请求的关联（用于解析 PN）。


| 序号  | 字段名称      | 字段类型 | 字段描述                       |
| --- | --------- | ---- | -------------------------- |
| 1   | ID        | int  | 主键                         |
| 2   | ProblemID | int  | 关联 `BrazilProblemList.ID`  |
| 3   | RequestID | int  | 关联 `Brazil_RequestList.ID` |
| 4   | OnlineQty | int  | 在线数量                       |


**已从本域剔除**：`InvoiceNoAll`、`RequestType`、`Memo`。

---

### BrazilProblemInvCode

**表描述**：巴西问题跟踪 — 存货编码。


| **字段名称**  | **字段类型** | **字段描述** |
| --------- | -------- | -------- |
| ID        | int      | 主键。      |
| ProblemID | int      | 关联问题主键。  |
| cInvCode  | varchar  | 存货编码。    |
| Qty       | int      | 数量。      |
| StockQty  | int      | 库存数量。    |


## 基础资料表

### Employee


| 字段名称 | 字段描述                       |
| ---- | -------------------------- |
| ID   | 员工 ID                      |
| Name | 姓名                         |
| Unit | 所属部门 ID；关联 `Department.ID` |


### Department


| 字段名称 | 字段描述  |
| ---- | ----- |
| ID   | 部门 ID |
| Name | 部门名称  |


### Inventory


| 字段名称     | 字段类型     | 字段描述   |
| -------- | -------- | ------ |
| cInvCode | nvarchar | 物料编码   |
| cInvName | nvarchar | 物料名称   |
| cInvStd  | nvarchar | 物料规格型号 |


### tbIQCvendor


| 字段名称     | 字段类型    | 字段描述                   |
| -------- | ------- | ---------------------- |
| ferpcode | varchar | ERP 编码；对应主表 `cVenCode` |
| fname    | varchar | 供应商名称                  |


### ProductName


| 字段名称        | 字段类型    | 字段描述                   |
| ----------- | ------- | ---------------------- |
| ID          | int     | 主键；对应主表 `ProductIDAll` |
| ProductName | varchar | 产品 / 大机型名称             |


### NewProduct


| 字段名称       | 字段类型     | 字段描述                                         |
| ---------- | -------- | -------------------------------------------- |
| FID        | int      | 主键                                           |
| PartNumber | varchar  | 机型编码 / PN；对应 `Brazil_RequestList.PartNumber` |
| Name       | nvarchar | 机型名称（写入 `PN列表`）                              |


### Brazil_RequestList


| 字段名称       | 字段类型    | 字段描述                                  |
| ---------- | ------- | ------------------------------------- |
| ID         | int     | 主键；对应 `BrazilProblemPO.RequestID`     |
| PartNumber | varchar | 零件号 / PN 键；关联 `NewProduct.PartNumber` |


### AfterSaleIssueClass


| 字段名称      | 字段类型    | 字段描述                   |
| --------- | ------- | ---------------------- |
| ID        | int     | 主键；对应主表 `ProblemClass` |
| ClassName | varchar | 停线级别名称                 |


### Brazil_Factory


| 字段名称        | 字段类型     | 字段描述                          |
| ----------- | -------- | ----------------------------- |
| fID         | int      | 工厂主键                          |
| FactoryName | nvarchar | 工厂名称（主表 `BrazilFactory` 存此名称） |


---

## 文档表

### DocumentList

**表描述**：通用文档清单；本域仅用于 8D 报告挂接。


| 字段名称              | 字段类型     | 字段描述                                     |
| ----------------- | -------- | ---------------------------------------- |
| ID                | int      | 文档唯一 ID                                  |
| DocumentName      | nvarchar | 文档名称                                     |
| DocumentRealName  | nvarchar | 文档全称（含后缀）                                |
| DocumentExtension | nvarchar | 扩展名                                      |
| DocumentPath      | nvarchar | 存储路径                                     |
| frecid            | int      | 业务记录 ID；8D 时 = `BrazilProblemProcess.ID` |
| AddDate           | datetime | 添加时间                                     |
| EffectFlag        | int      | 删除标志：0=有效，1=已删除                          |
| BusinessType      | varchar  | 业务名称；8D = `巴西制程问题单8D报告`                  |


**已从本域剔除**：`TypeIDGroup`、`DocumentSize`、`DocumentSummary`、`ViewNo`、`DownLoadNo`、`AuthorID`、`TransFormFlag`、`TransMemo`、`DateMark`、`Define1`、`Define2`。

**8D 检索**：`BusinessType = '巴西制程问题单8D报告'` 且 `frecid` ∈ 该制程单过程表全部 `ID`，且 `EffectFlag = 0`。

---

## 表关联（本域）

以 `BrazilProblemList` 为中心：


| 关联    | 条件                                                                                                      |
| ----- | ------------------------------------------------------------------------------------------------------- |
| 过程    | `BrazilProblemProcess.ProblemID` = `BrazilProblemList.ID`                                               |
| 费用    | `BrazilProblemCost.ProblemID` = `BrazilProblemList.ID`                                                  |
| PO    | `BrazilProblemPO.ProblemID` = `BrazilProblemList.ID`                                                    |
| PN    | `BrazilProblemPO.RequestID` = `Brazil_RequestList.ID` → `PartNumber` = `NewProduct.PartNumber` → `Name` |
| 大机型   | `ProductIDAll` 中 ID → `ProductName.ID`                                                                  |
| 物料    | `cInvCode` = `Inventory.cInvCode`                                                                       |
| 供应商   | `cVenCode` = `tbIQCvendor.ferpcode`                                                                     |
| 停线级别  | `ProblemClass` = `AfterSaleIssueClass.ID` → 展示 `ClassName`                                              |
| 工厂    | `BrazilFactory` = `Brazil_Factory.FactoryName`（名称，可逗号多值按段匹配）                                            |
| 人员/部门 | 各 `*UserID` = `Employee.ID`；`Employee.Unit` = `Department.ID`                                           |
| 8D 文档 | `DocumentList.BusinessType` = `巴西制程问题单8D报告` 且 `frecid` = `BrazilProblemProcess.ID`                      |


