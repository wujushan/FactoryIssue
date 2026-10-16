# ZCTracking_OtherOrder（国内制程问题其他在线订单）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_OtherOrder
- **所属域**：国内
- **用途**：问题单关联、受影响的其他在线生产订单及处理方式。不分物料标识，整机单与「物料」单都可能有，有就展示；绝大多数挂在整机单上。
- **数据产生方**：INFO 系统制程问题页面录入。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| OrderNo | nvarchar | 订单号 | — | — |
| PartNumber | nvarchar | 零件号 | — | — |
| ProductName | nvarchar | 机型 | — | — |
| Qty | — | 订单数量 | — | — |
| IssuedQty | — | 规划用量 | — | — |
| IssQty | — | 发料数量 | — | — |
| FaliaoDate | — | 发料日期 | — | — |
| ReturnQty | — | 需退货数量 | — | — |
| ReturnType | int | 处理方式 | 1=就地销毁，2=退回仓库，3=挑选，4=特采 | — |
| ReceivingQty | — | 仓库收货数量 | — | — |
| TotalinQty | — | 已入库数量 | — | — |
| Factory | nvarchar | 工厂 | 存工厂码（与主表一致；小板订单存的是名称） | `paxbase.dbo.PaxFactory.FactoryID` → `FactoryName` |
