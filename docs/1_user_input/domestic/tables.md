# 国内制程问题表整理

## 核心业务表：

- **CoreINFO.dbo.ZCTracking_ProblemList**：是制程问题管理的核心主表，包含70个字段。主要记录了制程问题的基本信息（如单号、类型、工厂、状态）、质量数据（影响数量、不良率）、处理过程（责任人、改善措施、停线信息）、关联单据（退货单号、CAR编码）以及各类确认与审批状态。该表通过 `ProblemId` 与其他子表（如订单、库存、日志等）关联，形成完整的制程问题追踪闭环。
- **CoreINFO.dbo.ZCTracking_ProductNames**：用于记录制程问题关联的具体机型信息，包含主键、关联的问题ID、机型ID、机型名称及所属系列。
- **CoreINFO.dbo.ZCTracking_ProblemOrders**：用于记录制程问题相关的生产订单信息，包含订单基础信息（订单号、PN、PN名称）、数量统计（订单、入库、在线数量）以及关联的主键ID和版本号等字段。
- **CoreINFO.dbo.ZCTracking_ProblemSteplog**：用于记录制程问题处理过程中的详细步骤日志。该表通过 `ProblemId` 关联主问题表，记录了每个处理步骤（`Step`/`StepStr`）、当前责任人（`MemberList`）、处理结论（`Result`）、意见（`Opinon`）及预防措施（`Measures`），并支持附件上传（`FileUrl`），用于完整追踪问题的解决过程。
- **CoreINFO.dbo.ZCTracking_ProblemOrders**：用于记录制程问题关联的生产订单详细信息，包含订单号、物料信息（PN及名称）、发料日期以及订单、入库和在线的数量统计。
- **CoreINFO.dbo.ZCTracking_XBOrders**：用于记录制程问题相关的小板订单信息，包含订单基础信息（订单号、工厂）、物料信息（物料编号、描述）以及数量统计（订单、入库、未入库数量），并通过 `ProblemId` 关联制程问题表。
- **info.dbo.tbIQCreportOut**：包含检验报告的基础信息、检验数据（抽检/不良数量）、多步骤审批记录及人员信息。
- **info.dbo.tbIQCvendor**：是 IQC 供应商的主数据表，包含供应商的基本信息（名称、地址、联系人）、资质信息（注册资本、认证）、业务属性（供应产品、供货类别、结算币种）以及管理状态（准入分类、等级、删除标记）等核心字段。该表通过 `fid` 作为主键，与其他关联表（如联系人、评价、洽谈记录、年度评价等）进行关联。
- **info.dbo.Department： 部门表**
- **info.dbo.Employee: 人员表**
- **info.dbo.Inventory：**存货档案的主数据表，主要存储物料的基础信息（如编码、名称、规格）、属性标识（如自制/外购、BOM母件）、供应策略（如供应商、采购员、提前期）以及状态信息（如停用日期、选用状态）。该表与 ERP 系统对齐，并关联多个业务日志和配置表。
- **paxbase.dbo.PaxFactory：用于存储工厂名称。**
- **info.dbo.DocumentList**：核心业务附件与文库文档主表，包含完整的文档元数据、业务关联字段（BusinessType, frecid）及状态标志。
- **CoreINFO.dbo.ZCTracking_RiskStream**：该表主要用于记录风险订单的流程状态，包含制程ID、当前步骤（如填写退货/退库信息）、状态、责任人及审计信息（新增人、新增时间）等字段。
- **info.dbo.tbTask：** 用于存储个人事务及待办任务的核心信息。该表包含任务的基础属性（如ID、标题、描述）、时间管理字段（创建、接受、计划完成、实际完成时间）、状态与进度跟踪（状态、优先级、进度百分比）、人员关联（负责人、创建者）以及流程控制字段（前置/后置任务、并发模式、外协标志等）。此外，还包含附件标记、备注、评估信息等扩展字段，以支持复杂的业务流程管理和任务协作。

## 表名：ZCTracking_ProblemList

**表描述**：制程问题表
该表用于记录和管理制程中出现的各类问题（硬件、软件、物料、资料、工厂制程等），涵盖问题发现、责任分配、原因分析、改善措施、停线控制、退货处理及结案确认等全流程信息。

#### 字段详情列表

| 字段名称 (Field Name)        | 数据类型           | 字段描述 (备注)                                                                                                                                                                                                      |
| ------------------------ | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ID**                   | int            | 主键 ID                                                                                                                                                                                                          |
| **Numbers**              | nvarchar(120)  | 单号 (自动生成，如 ZC2109001，其中：ZC为固定前缀；21为年份；09为月份；001是序号，表示当月的001号问题)                                                                                                                                                |
| **ProblemType**          | int            | 问题类型 (1:硬件问题，2:软件问题，3:物料问题，4:资料问题，5:工厂制程 6:结构问题，7:制程优化)                                                                                                                                                        |
| **Factory**              | nvarchar(120)  | 关联`PaxFactory.FactoryID`段。                                                                                                                                                                                     |
| **Status**               | int            | 处理状态流转 (1:指定责任人, 2:责任人确认, 3:工程确认, 4:PMC确认, 5:工厂制程分析, 6:IQC确认, 7:填写退货单号, 8:SQC跟进, 9:设计更改, 10:设计变更后SQE确认, 11:IQC意见, 12:生产角色确认, 13:生产角色驳回, 30:效果确认, 31:结案确认, 32:已完成,36:仅效果确认(预防对策确认已完成)，37 并行阶段:仅预防对策确认(效果确认已完成)) |
| **ImpactQty**            | int            | 影响数量                                                                                                                                                                                                           |
| **BadQty**               | int            | 不良数量                                                                                                                                                                                                           |
| **Rate**                 | decimal        | 不良率，1代表1%，46.4表示46.4%，100表示百分百或者100%                                                                                                                                                                           |
| **ProblemDesc**          | nvarchar(-1)   | 问题描述，长文本描述（可能包含base64编码的图片数据）                                                                                                                                                                                  |
| **Improve**              | nvarchar(4000) | 改善建议，长文本描述（可能包含base64编码的图片数据）                                                                                                                                                                                  |
| **Measures**             | nvarchar(1800) | 改善措施，长文本描述（可能包含base64编码的图片数据）                                                                                                                                                                                  |
| **Prevention**           | nvarchar(1800) | 预防对策，长文本描述（可能包含base64编码的图片数据）                                                                                                                                                                                  |
| **FoundDate**            | datetime       | 现场发现日期                                                                                                                                                                                                         |
| **Station**              | nvarchar(120)  | 发现工位                                                                                                                                                                                                           |
| **Version**              | nvarchar(120)  | 版本                                                                                                                                                                                                             |
| **IsStop**               | int            | 是否停线 (0:否，1:是)                                                                                                                                                                                                 |
| **StopStatus**           | int            | 停线状态 (1:停线中，2:已重启，3:未停线，4:重启审核, 5:审核通过， 6:填写重启方案)                                                                                                                                                              |
| **StopDate**             | datetime       | 停线日期                                                                                                                                                                                                           |
| **CInvCode**             | nvarchar(510)  | 涉及物料编码，关联表`Inventory`的`cInvCode`字段                                                                                                                                                                             |
| **VenCode**              | nvarchar(510)  | 供应商编码，关联表`tbIQCvendor`的`ferpcode`字段。可以为空                                                                                                                                                                       |
| **Confirmation**         | nvarchar(1050) | 效果确认内容                                                                                                                                                                                                         |
| **ConfirmUser**          | int            | 效果确认人 ID，关联表`Employee`的`ID`字段                                                                                                                                                                                  |
| **ConfirmDate**          | datetime       | 效果确认时间                                                                                                                                                                                                         |
| **OReturnOrderNo**       | nvarchar(1050) | 在线退货单号                                                                                                                                                                                                         |
| **SReturnOrderNo**       | nvarchar(1050) | 在库退货单号                                                                                                                                                                                                         |
| **AddUser**              | int            | 填单人 ID，关联表`Employee`的`ID`字段                                                                                                                                                                                    |
| **AddDate**              | datetime       | 填单时间/建单时间，是制程单填写和提交日期，默认使用该日期作为问题的时间过滤筛选条件                                                                                                                                                                     |
| **IsChangeOrderV**       | int            | 是否更改订单版本 (0:否，1:是)                                                                                                                                                                                             |
| **OrderVersion**         | nvarchar(120)  | 修订的订单版本                                                                                                                                                                                                        |
| **MemberList**           | nvarchar(1050) | 当前责任人列表，如：`624,1719`，关联`Employee`的`ID`字段。                                                                                                                                                                      |
| **MemberListName**       | nvarchar(1050) | 当前责任人姓名列表，如：`张三,李四`                                                                                                                                                                                            |
| **RDepartment**          | int            | 问题跟进部门ID，被指定跟进处理制程问题的部门，是`RUser`所在的部门，关联`Department.ID`                                                                                                                                                        |
| **RUser**                | nvarchar(510)  | 问题跟进人ID，被指定跟进处理制程问题的人员，关联`Employee.ID`                                                                                                                                                                         |
| **RConfirm**             | int            | 问题跟进人确认状态(0:否，1:是)                                                                                                                                                                                             |
| **IsDesignChange**       | int            | 是否设计变更 (0:否，1:是)                                                                                                                                                                                               |
| **DesignUser**           | int            | 设计变更责任人 ID，关联表`Employee`的`ID`字段                                                                                                                                                                                |
| **DesignConfirmResult**  | int            | 设计变更确认结果 (1:改善，2:保持现状，3:挂起)                                                                                                                                                                                    |
| **DesignDate**           | datetime       | 设计变更预计完成时间                                                                                                                                                                                                     |
| **Remark**               | nvarchar(1800) | 备注                                                                                                                                                                                                             |
| **RCompleteTime**        | datetime       | 软硬件问题责任人计划完成时间                                                                                                                                                                                                 |
| **IQCOpinion**           | int            | IQC意见 (2:退回仓库 ，3:继续使用), 可以为null                                                                                                                                                                                |
| **CAR**                  | nvarchar(100)  | CAR 编码 (纠正预防措施单)                                                                                                                                                                                               |
| **CARID**                | int            | CAR ID，关联表`tbIQCreportOut`字段`fid`                                                                                                                                                                              |
| **UpdateUser**           | int            | 更新人 ID，关联表`Employee`的`ID`字段                                                                                                                                                                                    |
| **UpdateDate**           | datetime       | 更新时间                                                                                                                                                                                                           |
| **IsDelete**             | int            | 是否删除 (0:否；1:是，标记该记录已删除）                                                                                                                                                                                        |
| OldProblemType           | int            | 修改问题类型时，用于保存旧的问题类型                                                                                                                                                                                             |
| **OutPutStatus**         | int            | 订单类型。5: 首次量产 6: 首次量产爬坡 7：正常量产 8：量产爬坡 9：未释放PN 195：物料试产 196：小批量试产 197：工程样机                                                                                                                                       |
| **ProblemLevel**         | nvarchar(110)  | 问题等级 (A/B/C)                                                                                                                                                                                                   |
| **Reason**               | nvarchar(-1)   | 原因描述 （长文本描述）                                                                                                                                                                                                   |
| **MHead**                | nvarchar(110)  | 物料标识。实际存储值均为「物料」。业务背景：产线除整机外还生产磁头、面壳组件等中间产物（有独立 BOM）。当这些中间产物的制程发生问题时填写「物料」，用于区分整机问题与中间产物/物料问题；此时关联 `ZCTracking_XBOrders`（小板生产任务订单）和 `ZCTracking_OtherOrder`（其他在线订单）                                            |
| **ProdQty**              | int            | 生产数量                                                                                                                                                                                                           |
| **AllReDepartment**      | nvarchar(2000) | 责任归属部门，保存的是部门id，是制程问题处理完结后人为定责，为空时表示无需定责。关联表`Department.ID`。例如：`34`或者`23,35`或者`为空`                                                                                                                             |
| **ReasonClass**          | nvarchar(1050) | 原因分类，为人为定义的导致问题发生的原因，比如：`人为工作疏忽`等                                                                                                                                                                              |
| **ReStartDate**          | datetime       | 停线重启时间                                                                                                                                                                                                         |
| **ReasonClassRemark**    | nvarchar(4000) | 原因分类说明                                                                                                                                                                                                         |
| **ProduceConfirmUser**   | int            | 生产确认人，关联表`Employee`的`ID`字段                                                                                                                                                                                     |
| **ProduceConfirmRemark** | nvarchar(1800) | 生产确认备注（长文本描述）                                                                                                                                                                                                  |
| **ProduceConfirmDate**   | datetime       | 生产确认时间                                                                                                                                                                                                         |
| **ReStartExamineUser**   | nvarchar(510)  | 重启审核人，关联表`Employee`的`ID`字段                                                                                                                                                                                     |
| **ReStartScheme**        | nvarchar(4000) | 重启方案（长文本描述                                                                                                                                                                                                     |
| **ReStartSchemeUser**    | nvarchar(510)  | 重启方案制定人，关联表`Employee`的`ID`字段                                                                                                                                                                                   |
| **ZLConfirmResult**      | int            | 资料问题确认结果。0:否；1:是                                                                                                                                                                                               |
| IQCStatus                | int            | IQC 状态。6：IQC确认 7：填写退货单号                                                                                                                                                                                        |
| IQCMemberList            | nvarchar(1050) | IQC 成员列表。逗号分隔的用户ID。如：1,2。关联表`Employee`的`ID`字段                                                                                                                                                                  |
| IQCMemberListName        | nvarchar(1050) | IQC 成员名单。逗号分隔的成员名。如：张三,李四                                                                                                                                                                                      |

### 总结

`ZCTracking_ProblemList` 表是制程质量管理系统的核心表之一，共包含 **69** 个字段。

- **核心功能**：实现从问题发现、分类（硬件/软件/物料等）、流程流转（责任分配、改善、确认）、停线控制、退货处理到最终结案的全生命周期管理。
- **关键字段**：`Numbers` (追踪单号)、`Status` (状态机)、`ProblemType` (问题分类)、`IsStop`/`StopStatus` (停线管理)、`CAR` (纠正措施关联)。

## 表名：Department

| **字段名称** | **字段类型** | **字段描述**                                 |
| -------- | -------- | ---------------------------------------- |
| ID       | int      | 部门主键。Employee.Unit 通常关联本字段（与 fid 现网值一致）。 |
| Name     | varchar  | 部门名称（中文常用名，列表/权限/通讯录展示主名称）。              |

## 表名：ZCTracking_ProductNames

**表描述**：制程问题机型

| 字段名称        | 字段描述                                        |
| ----------- | ------------------------------------------- |
| ID          | 主键 ID                                       |
| ProblemId   | 制程问题表 Id，关联`ZCTracking_ProblemList`表的`ID`字段 |
| ProductId   | 机型 Id                                       |
| ProductName | 机型名称                                        |
| Series      | 系列                                          |

**总结**：
该表（`ZCTracking_ProductNames`）主要用于记录制程问题(`ZCTracking_ProblemList`)涉及的机型信息，包含主键、关联的制程问题 ID 及机型 ID，并存储具体的机型名称和系列信息。

- 同一个`ProblemId`可能会有多条记录，即1条制程问题记录可能会关联到多个机型。

## 表：ZCTracking_ProblemSteplog

**表描述**：问题过程跟踪日志

| 字段名称          | 字段描述                                        |
| ------------- | ------------------------------------------- |
| ID            | 主键 ID                                       |
| ProblemId     | 制程问题 Id，关联主表`ZCTracking_ProblemList`的`ID`字段 |
| Step          | 步骤                                          |
| StepStr       | 步骤描述                                        |
| AddUser       | 创建人                                         |
| AddDate       | 创建时间                                        |
| ProblemStatus | 制程问题状态                                      |
| MemberList    | 当前步骤责任人                                     |
| Result        | 结论                                          |
| Opinon        | 意见                                          |
| Measures      | 预防措施                                        |
| FileUrl       | 附件ID。关联`DocumentList.ID`                    |

**总结**：
该表用于记录制程问题的全流程跟踪日志，包含从问题 ID、当前步骤、责任人、处理结论到预防措施及附件的完整信息。

- `StepStr`表示一个步骤名称，会有重复，需去重：对同一问题（ProblemId）的相同步骤（StepStr），只保留最新记录

## 表名：Employee 主表

**表描述**：员工表 / 人员表 / 通信录（核心员工信息表）

| 序号  | 字段名  | 数据类型         | 字段描述      |
| --- | ---- | ------------ | --------- |
| 1   | ID   | int          | 员工ID / 工号 |
| 2   | Name | varchar(100) | 姓名        |
| 3   | Unit | int          | 部门ID      |

## 表：tbIQCvendor (供应商基础信息表)

| 序号  | 字段名称     | 数据类型         | 字段描述         |
| --- | -------- | ------------ | ------------ |
| 1   | fid      | int          | 主键 ID        |
| 2   | frnd     | int          | 关联 ID (NULL) |
| 3   | ferpcode | varchar(50)  | ERP 编码       |
| 4   | fname    | varchar(100) | 供应商名称        |
| 5   | ftype    | varchar(50)  | 供应商类型        |

主表`ZCTracking_ProblemList`关联此表，

## 表：tbIQCreportOut (IQC 报告主表)

| 字段名称               | 字段描述              |
| ------------------ | ----------------- |
| **fid**            | 主键ID              |
| **fcheckid**       | 检验单 ID            |
| **fcompany**       | 公司名称              |
| **fcount**         | 检验总数              |
| **fcheckcount**    | 检查总数              |
| **fbadcount**      | 不良数量              |
| **fbadper**        | 不良率               |
| **fdesc**          | 问题点               |
| **fstep2how1/2/3** | 围堵对策1/2/3         |
| **fstep3date**     | `fstep3memo`的录入时间 |
| **fstep3memo**     | 根本原因              |
| **fstep4date**     | `fstep4memo`的录入时间 |
| **fstep4memo**     | 永久纠正措施            |
| **fstep5date**     | `fstep5memo`的录入时间 |
| **fstep5memo**     | 预防措施              |
| **fstep6date**     | `fstep6memo`的录入时间 |
| **fstep6memo**     | 有效性确认             |

## 表： PaxFactory

**表名：** PaxFactory

| 序号  | 字段名称        | 字段描述 |
| --- | ----------- | ---- |
| 1   | FactoryID   | NULL |
| 2   | FactoryName | NULL |

## 表：ZCTracking_ProblemOrders

**表描述**：制程问题生产订单

### 字段明细

| 序号  | 字段名称        | 字段描述     |
| --- | ----------- | -------- |
| 1   | ID          | 主键 ID    |
| 2   | ProblemId   | 制程问题表 Id |
| 3   | OrderNumber | 订单号      |
| 4   | PartNumber  | PN       |
| 5   | PartName    | PN 名称    |
| 6   | IssueDate   | 发料日期     |
| 7   | OrderQty    | 订单数量     |
| 8   | ReceiptQty  | 入库数量     |
| 9   | OnlineQty   | 在线数量     |
| 10  | Version     | 版本号      |

---

**总结**：
该表 (`ZCTracking_ProblemOrders`) 用于管理制程环节中的问题生产订单数据，核心包含订单标识（ID、ProblemId）、物料信息（PartNumber/Name）、订单状态及数量追踪（OrderQty、ReceiptQty、OnlineQty），以及版本管理（Version）。

## 表：Inventory

根据您提供的数据库内容，针对关键字 `Inventory` 筛选出的相关表结构如下。已按表名分类整理，仅保留核心字段名称及描述。

### 1. 核心物料信息表

#### 表：`Inventory`

*主要存储通用物料基础信息、供应商及属性配置。*

| 字段名称            | 字段描述         |
| --------------- | ------------ |
| cInvCode        | 物料编码         |
| cInvName        | 物料名称         |
| cInvCCode       | 物料分类编码       |
| cInvStd         | 物料描述         |
| cProduceAddress | 生产地址         |
| cEnglishName    | 英文名称         |
| cInvDefine3     | 扩展定义字段 3     |
| dEDate          | 失效日期         |
| cVenCode        | 供应商编码        |
| bBomMain        | 是否为 BOM 主表物料 |
| cproducenation  | 生产国家         |

## 表：ZCTracking_XBOrders

**表描述**：制程问题小板订单  

#### 字段列表

| 序号  | 字段名称        | 数据类型     | 字段描述    |
| --- | ----------- | -------- | ------- |
| 1   | ID          | int      | 主键ID    |
| 2   | ProblemId   | int      | 制程问题表Id |
| 3   | OrderNumber | nvarchar | 订单号     |
| 4   | InvCode     | nvarchar | 物料编号    |
| 5   | InvStd      | nvarchar | 物料描述    |
| 6   | Qty         | decimal  | 订单数量    |
| 7   | InQty       | decimal  | 入库数量    |
| 8   | NoQty       | decimal  | 未入库数量   |
| 9   | Factory     | nvarchar | 工厂      |
| 10  | Description | nvarchar | 描述      |

---

**总结**：该表用于记录“制程问题小板订单”业务数据，包含订单基础信息（单号、物料）、数量统计（订单量、入库量、未入库量）以及工厂和描述等关联信息。当主表 `ZCTracking_ProblemList.MHead` =「物料」时关联本表。

## 表名：ZCTracking_OtherOrder (其他在线订单)

| 字段名称         | 字段描述                           |
| ------------ | ------------------------------ |
| ID           | 主键 ID                          |
| ProblemId    | 制程问题表 Id                       |
| OrderNo      | 订单号                            |
| PartNumber   | 零件号                            |
| ProductName  | 机型                             |
| Qty          | 订单数量                           |
| IssuedQty    | 规划用量                           |
| ReturnQty    | 需退货数量                          |
| ReturnType   | 处理方式 (1:就地销毁，2:退回仓库，3:挑选，4:特采) |
| ReceivingQty | 仓库收货数量                         |
| Factory      | 工厂                             |
| FaliaoDate   | 发料日期                           |
| TotalinQty   | 已入库数量                          |
| IssQty       | 发料数量                           |

---

**总结信息：**
`ZCTracking_OtherOrder` 表存储了“其他在线订单”的详细信息，核心包含订单编号、物料信息（机型、零件号）、数量状态（总数量、发料、退货、收货、入库）以及处理方式。该表关联了“制程问题表”，可用于追踪生产过程中的异常订单处理流程。当主表 `ZCTracking_ProblemList.MHead` =「物料」时关联本表（中间产物关联的其他生产订单）。

## 表名：DocumentList

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

---

`frecid` ∈ 该制程制程问题主键 `ID`，且 `EffectFlag = 0`。

### 表名：**ZCTracking_RiskStream**

| **字段名称**  | **字段类型** | **字段描述**                          |
| --------- | -------- | --------------------------------- |
| ID        | int      |                                   |
| ProblemId | int      | 制程ID。关联 ZCTracking_ProblemList.ID |
| Step      | int      | 步骤;14填写退货信息，15填写退库信息              |
| Status    | int      | 状态;1进行中，2完成                       |
| UserID    | int      | 责任人ID。关联Employee.ID               |
| Remark    | nvarchar | 备注                                |
| AddUser   | int      | 新增人                               |
| AddDate   | datetime | 新增时间                              |

### 表名：**tbTask**

| **字段名称** | **字段类型** | **字段描述**                                                 |
| ------------ | ------------ | ------------------------------------------------------------ |
| fid          | int          | 主键。                                                       |
| ftable       | varchar      | 具体业务（表）名称。                                         |
| frecID       | varchar      | 业务记录ID。                                                 |
| fname        | varchar      | 任务标题（一句话）。                                         |
| fuserID      | varchar      | 任务对应人员（单个工号，多人需要每人增加一条记录）。         |
| fstat        | varchar      | 状态。枚举：326=业务码值 326；完成=完成；已取消=已取消；已完成=已完成；已接受=已接受；已接收=已接收；待接受=待接受；陈莹莹2020.04.02邮件通知张洁凤废弃物料。=陈莹莹2020.04.02邮件通知张洁凤废弃物料。 |

