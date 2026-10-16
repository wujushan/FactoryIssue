# OverseasProblemDetail（海外制程问题主表）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.OverseasProblemDetail
- **所属域**：海外
- **用途**：海外工厂制程问题单主表，一行一张问题单。含物料、已选问题现象、停线、跟进、IQC、设计变更、效果确认与结案。
- **数据产生方**：INFO 系统海外制程问题页面录入与流转时写入。
- **连接键**：`Id` 被子表 `ProblemId` 引用（处理步骤、涉及发货单）。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| Id | int | （内部字段，不返回） | 主键 | 子表 `ProblemId`；制程单链接参数 |
| Numbers | varchar | 问题编号 | `HW` + 年 2 位 + 月 2 位 + 当月 3 位序号，如 HW2609001 | — |
| ProblemType | int | 问题类型 | 1=硬件问题，2=软件问题，3=物料问题，4=其他，5=工厂制程，6=结构问题，7=制程优化。空值显示「未填」，1–7 以外的值显示「其他（未识别）」 | — |
| OldProblemType | int | 原问题类型 | 改分类前的类型，枚举同 `ProblemType` | — |
| ProblemRemark | varchar | 其他问题说明 | 问题类型为「其他」时填写 | — |
| Factory | varchar | 加工厂 | 海外工厂名称，直接存名称，不关联国内工厂主数据。写法统一，取值是可枚举的闭集；按工厂筛选用包含或名称相近匹配，不要求精确相等 | — |
| Factory2 | varchar | 国内工厂 | 国内工厂码 | `paxbase.dbo.PaxFactory.FactoryID` → `FactoryName` |
| ProductType | varchar | （内部字段，不返回） | 大机型 ID，逗号分隔 | `info.dbo.ProductName.ID` → `ProductName`（显示名「大机型」） |
| Series | varchar | 系列 | 选 PN 时随大机型带出的系列文本。只展示原文，不作查询条件，不另关联 | — |
| PNList | varchar | （内部字段，不返回） | PN 编号，逗号分隔。不展示，但按 PN 筛选时编码与名称都参与匹配 | 各段 `= info.dbo.NewProduct.PartNumber` → `Name`（显示名「PN」；多段用逗号拼接） |
| InvInfo | varchar | 物料 | JSON 数组，见下方「JSON 列结构」。不关联存货档案与供应商表 | — |
| hasCheckedPhenomenon | varchar | 已选问题现象 | JSON 数组，见下方「JSON 列结构」 | 元素 `Key`>0 → `CoreINFO.dbo.AfterSaleIssueClassPhenomenon.ID` |
| ImpactQty | int | 影响数量 | — | — |
| BadQty | int | 不良数量 | — | — |
| Rate | varchar | 不良率 | 文本，`%` 与 `‰` 混用，如 `30%`、`6.6667‰`；按原文展示 | — |
| ProblemLevel | varchar | 问题等级 | A+ / A / B / C；NULL 或空写「未填」 | — |
| FoundDate | varchar | 现场发现日期 | 也叫发现日期；文本存日期，格式 `YYYY-MM-DD` | — |
| Station | varchar | 发现工位 | — | — |
| Version | varchar | 版本 | — | — |
| IsStop | int | 是否停线 | 0=否，1=是。停线重启后仍为 1。「曾经停线」看本列为 1 | — |
| StopState | int | 停线状态 | 1=停线中，2=已经重启，其他值或 0=没有停线。「停线中」看本列为 1 | — |
| StopDate | varchar | 停线日期 | 文本存日期，格式 `YYYY-MM-DD` | — |
| ReStartDate | datetime | 停线重启时间 | 停线重启时写入 | — |
| ProblemDesc | varchar | 问题描述 | 自由文本，可能内嵌 base64 图片 | — |
| Improve | varchar | 改善建议 | 自由文本，可能内嵌 base64 图片 | — |
| Reason | varchar | 问题原因 | 本单已填写的原因：责任人确认 / 原因分析文本。不同于「可能问题原因」 | — |
| Measures | nvarchar | 改善措施 | 改善措施、工厂制程原因分析、物料问题设计变更改善情况 / 原因说明 | — |
| Prevention | nvarchar | 预防对策 | 预防对策、工厂制程制定的对策 | — |
| Remark | varchar | 备注 | — | — |
| Status | int | 状态 | 见下方「状态枚举」 | — |
| MemberList | varchar | （内部字段，不返回） | 当前处理人 ID，逗号分隔 | `info.dbo.Employee.ID` |
| MemberListName | varchar | 当前处理人 | 问题单流转到最新节点时的处理人姓名，与 `MemberList` 对应。直接展示，不另查人员表，也不用处理步骤上的成员代替 | — |
| RDepartment | int | 问题跟进部门 | 空或一个部门 ID。填单时先选部门，再选该部门下的人员 | `info.dbo.Department.ID` |
| RUser | nvarchar | 问题跟进人 | 空，或一个 / 多个员工 ID，逗号分隔，如 `4535,4527`；多人都属于问题跟进部门所指的那一个部门 | `info.dbo.Employee.ID` |
| RConfirm | int | 跟进人是否确认 | 0 或空=否，大于 0=是 | — |
| RCompleteTime | datetime | 计划完成时间 | 问题跟进人计划完成时间 | — |
| IQCOpinion | int | IQC 意见 | 2=退回仓库，3=继续使用 | — |
| IsDesignChange | int | 是否设计变更 | 0=否，1=是 | — |
| DesignUser | int | 设计变更责任人 | 员工 ID | `info.dbo.Employee.ID` |
| DesignConfirmResult | int | 设计变更确认结果 | 1=改善，2=保持现状，3=挂起 | — |
| DesignDate | datetime | 设计更改预计完成时间 | — | — |
| Confirmation | nvarchar | 效果确认 | 效果确认结论 | — |
| ConfirmUser | int | 效果确认人 | 员工 ID | `info.dbo.Employee.ID` |
| ConfirmDate | datetime | 效果确认时间 | — | — |
| DocId | varchar | （内部字段，不返回） | 填单附件 ID，逗号分隔 | `info.dbo.DocumentList.ID` |
| AddUser | int | 创建人 | 员工 ID | `info.dbo.Employee.ID` |
| AddDate | datetime | 建单时间 | — | — |
| IsDelete | bit | （内部字段，不返回） | 软删标记：0=未删除，1=已删除；默认只查未删除 | — |

本域不使用源表的 `OtherOnline`（其他在线）、`StockList`（库存）、`OReturnOrderNo`（在线退货单号）、`SReturnOrderNo`（在库退货单号）。

## 状态枚举（Status）

| 值 | 显示 | 值 | 显示 |
|---|---|---|---|
| 1 | 指定责任人 | 7 | 填写退货单号 |
| 2 | 责任人确认 | 8 | SQE跟进 |
| 3 | 其他问题确认 | 9 | 设计更改 |
| 4 | IQC意见 | 10 | 设计变更后SQE确认 |
| 5 | 工厂制程分析 | 30 | 效果确认 |
| 6 | IQC确认 | 31 | 结案确认 |
|  |  | 32 | 已完成 |

结案完成只有 32「已完成」。

## JSON 列结构

**InvInfo（物料）**：JSON 数组，每个元素一条物料，一单可多条；只有一条时仍是数组。

| 键 | 用户可见显示名 | 含义 |
|---|---|---|
| PN | 料号 | 物料编码，与国内、巴西的料号同一套。与主表 `PNList` 的 PN 不是同一套编号 |
| materialDesc | 描述 | 整段展示，不拆成物料名称和规格型号 |
| supplier | 供应商编号 | 与 `tbIQCvendor.ferpcode` 同义，写在元素内 |
| supplierName | 供应商名称 | 展示用这里的名称，不另查供应商表 |

不展示原始 JSON。多条时按数组顺序逐条列出，每条一行。空值、空串、不是 JSON 数组或数组为空时，不显示物料。

**hasCheckedPhenomenon（已选问题现象）**：JSON 数组，每个元素一条已选现象，标准现象和手填现象可混在一起；只有一条时仍是数组。元素键有 `Key`、`Value`、`parentType`、`otherVal`，以及 `subTypeId`、`subTypeName`、`parentIndex`、`tagIndex`。

展示为一段文字「已选问题现象」，不展示原始 JSON，也不用标准现象表的描述替换。

- 空值、空串，或去掉首尾空白后不以 `[` 开头：视为空数组。否则按 JSON 数组解析。
- 单元素片段（`parentType`、`Value` 为空时按空串拼接）：

  | Key | 片段 |
  |---|---|
  | 大于 0 | `Value` |
  | 小于 0（手填） | `parentType` + ` -> ` + `Value`；`otherVal` 去掉空白后仍有内容时，再追加空格、`(`、`otherVal`、`)` |
  | 0 或缺失 | `Value` |

  `Key` 大于 0 时不用 `parentType`、`subTypeName`、`otherVal`；`subTypeId`、`parentIndex`、`tagIndex` 一律不进展示文本。
- 按数组顺序用中文分号「；」连接；某段为空串时位置仍保留。

| 数组 | 已选问题现象 |
|---|---|
| `[{"Key":39,"Value":"黑屏、白屏"}]` | 黑屏、白屏 |
| `[{"Key":39,"Value":"黑屏、白屏"},{"Key":-1,"parentType":"功能问题","Value":"花屏","otherVal":"夜间"}]` | 黑屏、白屏；功能问题 -> 花屏 (夜间) |

**可能问题原因**：对每个 `Key` 大于 0 的元素分别查：`Key = AfterSaleIssueClassPhenomenon.ID`，再以它查 `AfterSaleIssueClassPhenomenonReason.PhenomenonID`，命中的每行 `ReasonDesc` 是这条现象下的一条可能问题原因。JSON 不保存选中的原因，所以得到的是候选清单。`Key` 小于 0 的手填现象不查。JSON 里的 `parentType`、`subTypeId` 等键不参与这条关联，也不对应现象表的分类 ID。
