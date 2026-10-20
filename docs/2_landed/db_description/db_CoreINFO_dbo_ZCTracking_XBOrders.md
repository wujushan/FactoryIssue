# ZCTracking_XBOrders（国内制程问题小板订单）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_XBOrders
- **所属域**：国内
- **用途**：中间产物（小板等）生产任务订单。主表「物料标识」为「物料」时关联本表；整机单没有小板订单。
- **数据产生方**：INFO 系统制程问题页面录入。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| OrderNumber | nvarchar | 小板订单号 | — | — |
| InvCode | nvarchar | 料号 | 物料编码 | `info.dbo.Inventory.cInvCode` |
| InvStd | nvarchar | 物料描述 | — | — |
| Qty | decimal | 订单数量 | — | — |
| InQty | decimal | 入库数量 | — | — |
| NoQty | decimal | 未入库数量 | — | — |
| Factory | nvarchar | 订单工厂 | 存工厂**名称**（不是工厂码，与主表、其他在线订单不同） | `paxbase.dbo.PaxFactory.FactoryName` |
| Description | nvarchar | 描述 | — | — |
