# ZCTracking_ProblemOrders（国内制程问题生产订单）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_ProblemOrders
- **所属域**：国内
- **用途**：问题单关联的整机生产订单及数量。一张单可关联多张订单。
- **数据产生方**：INFO 系统制程问题页面录入。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| OrderNumber | nvarchar | 生产订单号 | — | — |
| PartNumber | nvarchar | PN | — | — |
| PartName | nvarchar | PN 名称 | — | — |
| IssueDate | datetime | 发料日期 | — | — |
| OrderQty | int | 订单数量 | — | — |
| ReceiptQty | int | 入库数量 | — | — |
| OnlineQty | int | 在线数量 | — | — |
| Version | nvarchar | 订单版本 | — | — |
