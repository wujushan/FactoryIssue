# ZCTracking_ProblemOrders（国内制程问题生产订单）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_ProblemOrders
- **所属域**：国内
- **用途**：问题单关联的整机生产订单及数量。一张单可关联多张订单。只挂在主表「物料标识」为空（NULL 或空串）的单上，「物料」单没有生产订单。
- **数据产生方**：INFO 系统制程问题页面录入。
- **列类型**：按 information_schema（业务方 2026-10-20 内网元数据），字符串长度为声明的字符数。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| OrderNumber | nvarchar(125) | 生产订单号 | — | — |
| PartNumber | nvarchar(60) | PN 编码 | 15 位数字，与 PN 主数据的业务主键同一套 | — |
| PartName | nvarchar(60) | PN 名称 | 带连字符的型号码。个别为手填说明文字，按原值展示 |

两列合并展示为「PN」一项：「PN 名称 PN 编码」，与管理页面一致。按 PN 筛选时两列都参与：编码精确匹配，名称包含匹配。

| IssueDate | datetime | 发料日期 | — | — |
| OrderQty | int | 订单数量 | — | — |
| ReceiptQty | int | 入库数量 | — | — |
| OnlineQty | int | 在线数量 | — | — |
| Version | nvarchar(250) | 订单版本 | — | — |
