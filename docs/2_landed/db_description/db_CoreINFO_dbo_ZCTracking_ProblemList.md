# ZCTracking_ProblemList（国内制程问题主表）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_ProblemList
- **所属域**：国内
- **用途**：国内制程问题单主表，一行一张问题单。覆盖问题发现、分类、责任分配、原因分析、改善措施、停线控制、退货处理、效果确认与结案全流程。
- **数据产生方**：INFO 系统制程问题页面录入与流转时写入。
- **连接键**：`ID` 被子表 `ProblemId` 引用（机型、生产订单、小板订单、其他在线订单、处理步骤）。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | 子表 `ProblemId`；制程单链接参数 |
| Numbers | nvarchar(120) | 问题编号 | 自动生成，`ZC` + 年 2 位 + 月 2 位 + 当月 3 位序号，如 ZC2109001 | — |
| ProblemType | int | 问题类型 | 1=硬件问题，2=软件问题，3=物料问题，4=资料问题，5=工厂制程，6=结构问题，7=制程优化 | — |
| OldProblemType | int | 原问题类型 | 修改问题类型时保存的旧类型，枚举同 `ProblemType` | — |
| Factory | nvarchar(120) | 加工厂 | 工厂码 | `paxbase.dbo.PaxFactory.FactoryID` → `FactoryName` |
| Status | int | 状态 | 见下方「状态枚举」 | — |
| ImpactQty | int | 影响数量 | 整机问题中，受影响的关联生产订单的订单数量之和 | — |
| BadQty | int | 不良数量 | — | — |
| ProdQty | int | 生产数量 | — | — |
| Rate | decimal | 不良率 | 不良数量 ÷ 生产数量，存百分数的数值部分：1 表示 1%，46.4 表示 46.4%，100 表示 100% | — |
| ProblemDesc | nvarchar(max) | 问题描述 | 富文本（HTML），可能内嵌图片 | — |
| Reason | nvarchar(max) | 原因分析 | 问题发生的原因；富文本 | — |
| Improve | nvarchar(4000) | 改善建议 | 富文本，可能内嵌图片 | — |
| Measures | nvarchar(1800) | 改善措施 | 富文本，可能内嵌图片 | — |
| Prevention | nvarchar(1800) | 预防对策 | 富文本，可能内嵌图片 | — |
| FoundDate | datetime | 现场发现日期 | — | — |
| Station | nvarchar(120) | 发现工位 | 自由文本，写法不统一，不是枚举 | — |
| Version | nvarchar(120) | 版本 | — | — |
| ProblemLevel | nvarchar(110) | 问题等级 | A / B / C | — |
| OutPutStatus | int | 产品在制属性 | 该单关联的那次生产所处的阶段：5=首次量产，6=首次量产爬坡，7=正常量产，8=量产爬坡，9=未释放PN，195=物料试产，196=小批量试产，197=工程样机 | — |
| MHead | nvarchar(110) | 物料标识 | 只存「物料」或空（空有 NULL 与空串两种，含义相同）。空=整机问题，看关联生产订单；「物料」=磁头、面壳组件等有独立 BOM 的中间产物出的问题，另看小板订单。其他在线订单不分物料标识 | — |
| IsStop | int | 是否停线 | 0=否，1=是。曾经停过线即为 1，重启后不清零 | — |
| StopStatus | int | 停线状态 | 1=停线中，2=已经重启，3=没有停线，4=重启审核，5=审核通过，6=填写重启方案 | — |
| StopDate | datetime | 停线日期 | — | — |
| ReStartDate | datetime | 停线重启时间 | — | — |
| ReStartScheme | nvarchar(4000) | 重启方案 | 富文本 | — |
| ReStartSchemeUser | nvarchar(510) | 重启方案制定人 | 员工 ID，文本型，需转整数关联；无效值按空 | `info.dbo.Employee.ID` |
| ReStartExamineUser | nvarchar(510) | 重启审核人 | 员工 ID，文本型，需转整数关联；无效值按空 | `info.dbo.Employee.ID` |
| CInvCode | nvarchar(510) | 料号 | 涉及物料编码 | `info.dbo.Inventory.cInvCode` |
| VenCode | nvarchar(510) | 供应商编号 | 可空 | `info.dbo.tbIQCvendor.ferpcode` |
| MemberList | nvarchar(1050) | （内部字段，不返回） | 当前处理人 ID，逗号分隔，如 `624,1719` | `info.dbo.Employee.ID` |
| MemberListName | nvarchar(1050) | 当前处理人 | 当前处理人姓名，逗号分隔，与 `MemberList` 一一对应；随最新处理节点变化。直接展示，不另查人员表 | — |
| RDepartment | int | 问题跟进部门 | 被指定跟进处理本单的部门，即问题跟进人所在部门。只有指定了问题跟进人的类型才有值 | `info.dbo.Department.ID` |
| RUser | nvarchar(510) | 问题跟进人 | 被指定跟进处理本单的一名人员 ID，文本型，需转整数关联；无效值按空。只有硬件、软件、结构问题、制程优化有值 | `info.dbo.Employee.ID` |
| RConfirm | int | 跟进人是否确认 | 0=否，1=是 | — |
| RCompleteTime | datetime | 计划完成时间 | 软硬件问题责任人计划完成时间 | — |
| AllReDepartment | nvarchar(2000) | 责任归属部门 | 结案后人为定责的部门 ID，逗号分隔，如 `34`、`23,35`；空=无需定责 | `info.dbo.Department.ID` |
| ReasonClass | nvarchar(1050) | 原因分类 | 结案时人为归类，从自维护的原因列表中选取，取值是有限集合，如「人为工作疏忽」 | — |
| ReasonClassRemark | nvarchar(4000) | 原因分类说明 | 富文本 | — |
| IsDesignChange | int | 是否设计变更 | 0=否，1=是。只对物料问题有意义 | — |
| DesignUser | int | 设计变更责任人 | 员工 ID；是否设计变更为 1 时有值 | `info.dbo.Employee.ID` |
| DesignConfirmResult | int | 设计变更确认结果 | 1=改善，2=保持现状，3=挂起；是否设计变更为 1 时有值 | — |
| DesignDate | datetime | 设计变更预计完成时间 | 是否设计变更为 1 时有值 | — |
| IQCOpinion | int | IQC 意见 | 2=退回仓库，3=继续使用；可空 | — |
| IQCStatus | int | IQC 状态 | 6=IQC确认，7=填写退货单号。与主状态的 6、7 含义相同，但是独立的一列 | — |
| IQCMemberList | nvarchar(1050) | （内部字段，不返回） | IQC 成员 ID，逗号分隔 | `info.dbo.Employee.ID` |
| IQCMemberListName | nvarchar(1050) | IQC 成员 | IQC 成员姓名，逗号分隔 | — |
| CAR | nvarchar(100) | CAR 编号 | 纠正预防措施单编号；只有物料问题可关联 | — |
| CARID | int | （内部字段，不返回） | CAR 报告 ID；只有物料问题可关联，可空 | `info.dbo.tbIQCreportOut.fid` |
| OReturnOrderNo | nvarchar(1050) | 在线退货单号 | — | — |
| SReturnOrderNo | nvarchar(1050) | 在库退货单号 | — | — |
| IsChangeOrderV | int | 是否更改订单版本 | 0=否，1=是 | — |
| OrderVersion | nvarchar(120) | 修订的订单版本 | — | — |
| ZLConfirmResult | int | 资料问题确认结果 | 0=否，1=是。只对资料问题有意义 | — |
| Confirmation | nvarchar(1050) | 效果确认内容 | 富文本 | — |
| ConfirmUser | int | 效果确认人 | 员工 ID | `info.dbo.Employee.ID` |
| ConfirmDate | datetime | 效果确认时间 | — | — |
| ProduceConfirmUser | int | 生产确认人 | 员工 ID | `info.dbo.Employee.ID` |
| ProduceConfirmRemark | nvarchar(1800) | 生产确认备注 | 富文本 | — |
| ProduceConfirmDate | datetime | 生产确认时间 | — | — |
| Remark | nvarchar(1800) | 备注 | 富文本 | — |
| AddUser | int | 填单人 | 员工 ID | `info.dbo.Employee.ID` |
| AddDate | datetime | 建单时间 | 制程单填写并提交的时间；默认的时间筛选列 | — |
| UpdateUser | int | （内部字段，不返回） | 审计列：更新人 ID | `info.dbo.Employee.ID` |
| UpdateDate | datetime | （内部字段，不返回） | 审计列：更新时间 | — |
| IsDelete | int | （内部字段，不返回） | 软删标记：0 或空=未删除，1=已删除。子表没有删除标记，随主表 | — |

## 状态枚举（Status）

| 值 | 显示 | 值 | 显示 |
|---|---|---|---|
| 1 | 指定责任人 | 10 | 设计变更后SQE确认 |
| 2 | 责任人确认 | 11 | IQC意见 |
| 3 | 工程确认 | 12 | 生产角色确认 |
| 4 | PMC确认 | 13 | 生产角色驳回 |
| 5 | 工厂制程分析 | 30 | 效果确认 |
| 6 | IQC确认 | 31 | 结案确认 |
| 7 | 填写退货单号 | 32 | 已完成 |
| 8 | SQC跟进 | 36 | 仅效果确认（预防对策确认已完成） |
| 9 | 设计更改 | 37 | 仅预防对策确认（效果确认已完成） |

36、37 是效果确认与预防对策确认并行时的阶段；14–29 未使用。结案完成只有 32「已完成」；31「结案确认」仍算未结案。
不同问题类型走不同路径，也可能被驳回到前序环节后再推进；当前在哪一步看本列，走过哪些步看处理步骤表。
