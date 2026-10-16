# BrazilProblemList（巴西制程问题主表）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.BrazilProblemList
- **所属域**：巴西
- **用途**：巴西工厂产线制程问题单主表，一行一张问题单。覆盖问题发现、影响评估、补料、8D、费用与状态跟踪。
- **数据产生方**：INFO 系统巴西制程问题页面录入与流转时写入。
- **连接键**：`ID` 被子表 `ProblemID` 引用（处理过程、费用、关联申请单）。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 自增主键 | 子表 `ProblemID`；制程单链接参数（加密后） |
| OrderNumber | varchar | 问题编号 | `BR` + 年 2 位 + 月 2 位 + 当月 3 位序号，如 BR2404001 | — |
| ClaimNumber | varchar | 投诉单号 | 自由文本，无固定编码规则。多数以 `CLAIM` 开头（如 `CLAIM 014.04/2024`、`CLAIM-019/24`），但不绝对；可空 | — |
| BrazilFactory | varchar | 加工厂 | 巴西工厂**名称**（不是 ID），可逗号多值，如 `CA,TT`。已有取值如 TT、CA、TR | `info.dbo.Brazil_Factory.FactoryName`（按段匹配） |
| ProductIDAll | varchar | （内部字段，不返回） | 大机型 ID，空 / 单值 / 逗号分隔多值，可能带空格或无效 ID | `info.dbo.ProductName.ID` → `ProductName`（显示名「机型名称列表」）、`Series` |
| ProblemType | varchar | 问题类型 | 文本：设计问题、结构问题、生产问题、制程优化、硬件问题、物料问题、其他。「其他」可写成 `其他\|备注`，此时问题类型显示「其他」，`\|` 后的文字显示为「其他问题备注说明」。只有待提交（草稿）可为空 | — |
| IsStopLine | varchar | 是否停线 | 是 / 否，默认否。曾发生停线即为「是」，重启后不改回「否」 | — |
| StopDate | varchar | 停线日期 | 文本存日期，格式 `YYYY-MM-DD` | — |
| StopStatus | varchar | 停线状态 | 是否已标记停线重启：`停线重启`=已重启；空或其他取值（如 `停线中`）=未标记重启。没有固定枚举 | — |
| ProblemClass | varchar | （内部字段，不返回） | 停线级别 ID | `CoreINFO.dbo.AfterSaleIssueClass.ID` → `ClassName`（显示名「停线级别」） |
| ProblemPhenomenon | nvarchar | 问题现象 | JSON 数组，展平规则见下方「问题现象」 | — |
| ProblemLevel | varchar | 问题等级 | A / B / C / 空（空写「未填」） | — |
| ProblemDiscoveryDate | varchar | 现场发现日期 | 文本存日期，格式 `YYYY-MM-DD` | — |
| ProblemDiscoveryStation | varchar | 发现工位 | 自由文本，可空 | — |
| StatisticsDate | varchar | 统计日期 | 文本存日期，格式 `YYYY-MM-DD` | — |
| cInvCode | varchar | 料号 | — | `info.dbo.Inventory.cInvCode` |
| cVenCode | varchar | 供应商编号 | — | `info.dbo.tbIQCvendor.ferpcode`（空值不关联） |
| ImpactQty | int | 影响数量 | — | — |
| BadQty | int | 不良数量 | — | — |
| ProblemDesc | nvarchar | 问题描述 | 富文本 | — |
| IsRequire8D | int | 是否需要回复 8D | 1=是，2=否 | — |
| IsSupplement | int | 是否需要补料 | 1=是，2=否 | — |
| SupplementQty | int | 补料数量 | — | — |
| SupplementResult | varchar | 补料结果 | 是 / 否 / 空 | — |
| SupplementMemo | nvarchar | 补料备注 | 富文本 | — |
| SupplementUserID | int | 补料人 | 员工 ID | `info.dbo.Employee.ID` |
| SupplementDate | datetime | 补料日期 | — | — |
| IsCost | int | 是否涉及费用 | 1=是，2=否；0 为删除状态的测试数据，按无效值处理 | — |
| ActorUserID | int | 初始责任人 | 员工 ID | `info.dbo.Employee.ID` |
| Memo | nvarchar | 备注 | 富文本 | — |
| AddUserID | int | 填单人 | 员工 ID | `info.dbo.Employee.ID` |
| AddDate | datetime | 建单时间 | — | — |
| UpdateUserID | int | （内部字段，不返回） | 审计列：最后修改人 | `info.dbo.Employee.ID` |
| UpdateDate | datetime | （内部字段，不返回） | 审计列：最后修改时间 | — |
| Status | int | 状态 | 见下方「状态枚举」 | — |

本域不使用源表的 `RequestID`（默认 0；PN 不以本列为准，只经 `BrazilProblemPO` 解析）与 `MailCount`。

## 状态枚举（Status）

| 值 | 显示 | 值 | 显示 |
|---|---|---|---|
| 0 | 待提交 | 30 | 待效果确认 |
| 10 | 待修改类别 | 40 | 待结案 |
| 20 | 待跟进 | 50 | 已结案 |
| 25 | 待设计更改 | -2 | 已终止 |
| 26 | 待SQE确认 | -1 | 已删除 |

结案完成为 50「已结案」。-1「已删除」一律排除；0「待提交」（草稿）与 -2「已终止」仍在查询范围内。本表没有独立的删除标记，软删只靠状态 -1 表达。

## 问题现象（ProblemPhenomenon）

JSON 数组，每个元素含 `Key`（整数）、`Value`、`parentType`、`otherVal`。对用户展示展平后的文本「问题现象」，不展示原始 JSON。

- 空值、空串，或去掉首尾空白后不以 `[` 开头：视为空数组。否则对非法转义做容错后按 JSON 数组解析。
- 单元素片段：

  | Key | 片段 |
  |---|---|
  | 大于 0 | `Value` |
  | 小于 0（手填） | `parentType` + `->` + `Value`；`otherVal` 非空时再追加一个空格和 `otherVal` |
  | 0 或其他 | `Value` |

  各键为空时按空串拼接。
- 各片段按数组顺序用中文分号「；」连接。

## 问题类型的「其他|备注」

| 源值 | 问题类型（展示） | 其他问题备注说明 |
|---|---|---|
| `物料问题` | 物料问题 | （空） |
| `其他\|包装破损` | 其他 | 包装破损 |
| `其他` | 其他 | （空） |

按「其他」筛选时，`其他` 与 `其他|…` 都要命中。
