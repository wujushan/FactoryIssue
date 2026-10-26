# ZCTracking_ProblemList（国内制程问题主表）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_ProblemList
- **所属域**：国内
- **用途**：国内制程问题单主表，一行一张问题单。覆盖问题发现、分类、责任分配、原因分析、改善措施、停线控制、退货处理、效果确认与结案全流程。
- **数据产生方**：INFO 系统制程问题页面录入与流转时写入。
- **列类型**：按 information_schema（业务方 2026-10-20 内网元数据），字符串长度为声明的字符数。不可空的列：ID、Numbers、ProblemType、Factory、Status、AddUser、AddDate，其余可空。
- **连接键**：`ID` 被 9 张子表的 `ProblemId` 引用（机型、生产订单、小板订单、其他在线订单、处理步骤、风险订单流程、已选现象与可能原因、可能的问题物料、5Why）；流程待办任务以文本形式在 `frecID` 中引用 `ID`；本表 `CARID` 关联 CAR 报告。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | 子表 `ProblemId`；制程单链接参数 |
| Numbers | nvarchar(60) | 问题编号 | 自动生成，`ZC` + 年 2 位 + 月 2 位 + 当月 3 位序号，如 ZC2109001 | — |
| ProblemType | int | 问题类型 | 1=硬件问题，2=软件问题，3=物料问题，4=资料问题，5=工厂制程，6=结构问题，7=制程优化 | — |
| OldProblemType | int | 原问题类型 | 修改问题类型时保存的旧类型，枚举同 `ProblemType` | — |
| Factory | nvarchar(60) | 加工厂 | 工厂码。业务方 2026-10-22 正式镜像计数：未删除的单只有 04（柯洱斯）、05（亮亮）、09（惠州百富）三个码，没有空值 | `paxbase.dbo.PaxFactory.FactoryID` → `FactoryName` |
| Status | int | 状态 | 见下方「状态枚举」 | — |
| ImpactQty | int | 影响数量 | 整机问题中，关联生产订单的在线数量之和，不是订单数量之和。「物料」单不展示，与管理页面一致 | — |
| BadQty | int | 不良数量 | — | — |
| ProdQty | int | 生产数量 | — | — |
| Rate | decimal(8,2) | 不良率 | 不良数量 ÷ 生产数量，存百分数的数值部分：1 表示 1%，46.4 表示 46.4%，100 表示 100%。少数单为空 | — |
| ProblemDesc | nvarchar(max) | 问题描述 | 富文本（HTML），可能内嵌图片 | — |
| Reason | nvarchar(max) | 原因分析 | 问题发生的原因；富文本 | — |
| Improve | nvarchar(2000) | 改善建议 | 富文本，可能内嵌图片 | — |
| Measures | nvarchar(2000) | 改善措施 | 富文本，可能内嵌图片 | — |
| Prevention | nvarchar(900) | 预防对策 | 富文本，可能内嵌图片 | — |
| FoundDate | datetime | 现场发现日期 | — | — |
| Station | nvarchar(60) | 发现工位 | 自由文本，写法不统一，不是枚举 | — |
| Version | nvarchar(60) | 版本 | — | — |
| ProblemLevel | nvarchar(55) | 问题等级 | A+ / A / B / C，与管理页面一致；空写「未填」。2024-04-17 起才登记，此前建的单都为空。按等级筛选时按显示文字精确匹配，「A」不含「A+」；各级定义见总述「问题等级」 | — |
| OutPutStatus | int | 产品在制属性 | 该单关联的那次生产所处的阶段，显示文字与管理页面一致：5=首次量产，6=首次量产爬坡，7=正常量产，8=量产爬坡，9=未释放PN生产，195=物料试产，196=小批量试产，197=工程样机。其他取值管理页面上显示为空，本助手写「未填」（业务方 2026-10-23 正式镜像计数：194 有 2 张、0 有 1 张）。「物料」单都为空，单张单详情不展示这一项，与管理页面一致 | — |
| MHead | nvarchar(55) | 物料标识 | 只存「物料」或空（空有 NULL 与空串两种，含义相同）。空=整机问题，看关联生产订单；「物料」=磁头、面壳组件等有独立 BOM 的中间产物出的问题，另看小板订单。其他在线订单不分物料标识 | — |
| IsStop | int | 是否停线 | 0=否，1=是。曾经停过线即为 1，重启后不清零 | — |
| StopStatus | int | 停线状态 | 1=停线中，2=已经重启，3=没有停线，4=重启审核中（后附重启审核人），5=重启审核通过（用户说「审核通过」同指 5），6=责任人填写重启方案（后附重启方案制定人），均为管理页面写法。单结案后不一定改回，已完成的单可能仍是 1、4、5、6 | — |
| StopDate | datetime | 停线日期 | — | — |
| ReStartScheme | nvarchar(2000) | 重启方案 | 富文本。与最新一条「责任人填写重启方案」步骤的意见同值；什么时候展示见国内业务描述「停线」 | — |
| ReStartSchemeUser | nvarchar(255) | 重启方案制定人 | 一名员工 ID，文本型，需转整数关联；无效值按空 | `info.dbo.Employee.ID` |
| ReStartExamineUser | nvarchar(255) | 重启审核人 | 一名员工 ID，文本型，需转整数关联；无效值按空 | `info.dbo.Employee.ID` |
| CInvCode | nvarchar(255) | 料号 | 涉及物料编码 | `info.dbo.Inventory.cInvCode` |
| VenCode | nvarchar(255) | 供应商编号 | 可空 | `info.dbo.tbIQCvendor.ferpcode` |
| MemberList | nvarchar(525) | （内部字段，不返回） | 主状态处理人 ID，逗号分隔 | `info.dbo.Employee.ID` |
| MemberListName | nvarchar(525) | 主状态处理人 | 主状态环节的处理人姓名，逗号分隔，与 `MemberList` 一一对应；随最新处理节点变化，直接展示，不另查人员表。按人匹配用 `MemberList` 里的员工 ID。回答中不单列本列，按当前状态、当前责任人给出，本列在其中占哪一行见国内业务描述「当前状态」「当前责任人」 | — |
| RDepartment | int | 问题跟进部门 | 被指定跟进处理本单的部门，即问题跟进人所在部门。只有指定了问题跟进人的类型才有值 | `info.dbo.Department.ID` |
| RUser | nvarchar(255) | 问题跟进人 | 被指定跟进处理本单的一名人员 ID，文本型，需转整数关联；无效值按空。只有硬件、软件、结构问题、制程优化有值 | `info.dbo.Employee.ID` |
| RConfirm | int | 跟进人是否确认 | 0=否，1=是 | — |
| RCompleteTime | datetime | 计划完成时间 | 硬件、软件、结构问题、制程优化在责任人确认时填，资料问题在工程确认时填（源系统称「责任人计划完成时间」） | — |
| AllReDepartment | nvarchar(1000) | 责任归属部门 | 结案后人为定责的部门 ID，一个或多个，逗号分隔。空：已完成的单显示「无需定责」，未完成的单显示「未定责」（见国内业务描述「人员与部门」）。物料问题不展示、按责任部门查单与统计时不计入，与管理页面一致（业务方 2026-10-23 正式镜像计数：物料问题目前都没有填） | `info.dbo.Department.ID` |
| ReasonClass | nvarchar(525) | 原因分类 | 结案时人为归类，从自维护的原因列表中选取，取值是有限集合，如「人为工作疏忽」 | — |
| ReasonClassRemark | nvarchar(2000) | 原因分类说明 | 富文本 | — |
| IsDesignChange | int | 是否设计变更 | 0=否，1=是。只对物料问题有意义 | — |
| DesignUser | int | 设计变更责任人 | 员工 ID，经人员表翻成姓名；是否设计变更为 1 时有值 | `info.dbo.Employee.ID` |
| DesignConfirmResult | int | 处理结果 | 1=改善，2=保持现状，3=挂起；空写「未填」。术语「责任人处理结果」即指本列。一张单只有这一列，后填的环节覆盖先填的；改过问题类型的单可能在不止一处显示同一个值。管理页面在「责任人确认」「工程确认」下叫「处理结果」，在「设计更改」下叫「确认结果」，改善时另附设计变更预计完成时间。各问题类型放在哪一处、什么时候显示，见国内业务描述「处理步骤」「单张单详情各环节怎么显示」。工厂制程没有这一项 | — |
| DesignDate | datetime | 设计变更预计完成时间 | 是否设计变更为 1 时有值 | — |
| IQCOpinion | int | IQC 意见 | 2=退回仓库，3=继续使用；可空 | — |
| IQCStatus | int | IQC 状态 | 复用主状态的码值与文案，常见 6=IQC确认、7=填写退货单号；物料退货流程用，与主状态并行，是独立的一列。IQC 流程走完后清空。业务方 2026-10-22 正式镜像计数：目前未删除的单都为空 | — |
| IQCMemberList | nvarchar(525) | （内部字段，不返回） | IQC 成员 ID，逗号分隔 | `info.dbo.Employee.ID` |
| IQCMemberListName | nvarchar(525) | IQC 成员 | IQC 成员姓名，逗号分隔 | — |
| CAR | nvarchar(50) | CAR 编号 | 纠正预防措施单编号，形如 `CAR` + 9 位数字，一单一个、互不重复；与 CAR 报告 ID 总是同时有值或同时为空。只在物料问题上展示；其他类型的单即使有值也不展示（与源系统管理页面一致）。可按它查单，见国内业务描述「按 CAR 编号查单」 | — |
| CARID | int | （内部字段，不返回） | CAR 报告 ID，可空。问题类型为物料问题且本列有值，才算该单关联了 CAR 报告：展示 CAR 编号、生成 CAR 报告链接、统计关联数都以此为准；其他类型即使有值也按未关联处理。个别 ID 在报告表里查不到，见 `dirty_data.md`「其他」 | `info.dbo.tbIQCreportOut.fid`；CAR 报告链接参数 |
| OReturnOrderNo | nvarchar(525) | 在线退货单号 | — | — |
| SReturnOrderNo | nvarchar(525) | 在库退货单号 | — | — |
| IsChangeOrderV | int | 是否更改订单版本 | 0=否，1=是 | — |
| OrderVersion | nvarchar(60) | 修订的订单版本 | — | — |
| ZLConfirmResult | int | 资料问题确认结果 | 0=否，1=是。只对资料问题有意义 | — |
| Confirmation | nvarchar(525) | 效果确认内容 | 富文本 | — |
| ConfirmUser | int | 效果确认人 | 员工 ID，经人员表翻成姓名 | `info.dbo.Employee.ID` |
| ConfirmDate | datetime | 效果确认时间 | — | — |
| ProduceConfirmUser | int | 生产确认人 | 员工 ID，经人员表翻成姓名 | `info.dbo.Employee.ID` |
| ProduceConfirmRemark | nvarchar(900) | 生产确认备注 | 富文本 | — |
| ProduceConfirmDate | datetime | 生产确认时间 | — | — |
| Remark | nvarchar(900) | 备注 | 富文本 | — |
| AddUser | int | 填单人 | 员工 ID，经人员表翻成姓名 | `info.dbo.Employee.ID` |
| AddDate | datetime | 建单时间 | 制程单填写并提交的时间；默认的时间筛选列 | — |
| UpdateUser | int | （内部字段，不返回） | 审计列：更新人 ID | `info.dbo.Employee.ID` |
| UpdateDate | datetime | （内部字段，不返回） | 审计列：更新时间 | — |
| IsDelete | int | （内部字段，不返回） | 软删标记：0 或空=未删除，1=已删除。已删除的单一律不查，与管理页面一致。子表没有删除标记，随主表。业务方 2026-10-26 正式镜像计数：只有 0 和 1 两种取值，没有空值 | — |

别用 `ReStartDate`（停线重启时间）：管理页面不写也不展示；重启日期取处理步骤（见国内业务描述「停线」）。

## 状态枚举（Status）

| 值 | 显示 | 值 | 显示 |
|---|---|---|---|
| 1 | 指定责任人 | 10 | SQE确认 |
| 2 | 责任人确认 | 11 | IQC意见 |
| 3 | 工程确认 | 12 | 生产角色确认 |
| 4 | PMC确认 | 13 | 生产角色驳回 |
| 5 | 工厂制程分析 | 30 | 效果确认 |
| 6 | IQC确认 | 31 | 结案确认 |
| 7 | 填写退货单号 | 32 | 已完成 |
| 8 | SQE跟进 | 36 | 效果确认 |
| 9 | 设计更改 | 37 | 预防对策确认 |

30、36、37 是效果确认与预防对策确认的并行阶段：30 两项都未完成，36 只剩效果确认（预防对策确认已完成），37 只剩预防对策确认（效果确认已完成）。本列在并行阶段可能是旧值，状态要按两类待办现算；现算规则与各行处理人见国内业务描述「当前状态」。
按处理环节筛选、统计不只看本列，见国内业务描述「按处理环节筛选与统计」。判断是否结案只看本列。
14–29 未使用。结案完成只有 32「已完成」；31「结案确认」仍算未结案。
不同问题类型走不同路径，也可能被驳回到前序环节后再推进；当前在哪一步看当前状态（本列是其中主状态那一行），走过哪些步看处理步骤表。
