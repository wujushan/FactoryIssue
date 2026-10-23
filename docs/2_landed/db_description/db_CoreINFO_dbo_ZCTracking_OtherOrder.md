# ZCTracking_OtherOrder（国内制程问题其他在线订单）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_OtherOrder
- **所属域**：国内
- **用途**：问题单关联、受影响的其他在线生产订单及处理方式。不分物料标识、不分问题类型，整机单与「物料」单都可能有。绝大多数挂在整机单上，按问题类型几乎都是物料问题。
- **怎么给**：单张单详情里只给条数，用户追问时再逐条列出下表各列（见国内业务描述「物料标识与关联订单」）。
- **数据产生方**：INFO 系统制程问题页面录入。
- **列类型**：按 information_schema（业务方 2026-10-20 内网元数据），字符串长度为声明的字符数。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| OrderNo | nvarchar(60) | 订单号 | — | — |
| PartNumber | nvarchar(50) | （内部字段，不返回） | 管理页面的其他在线订单表格不显示这一列，本助手也不展示 | — |
| ProductName | nvarchar(255) | 订单机型 | 该订单的机型文字。按机型查单只看机型子表，不看本列 | — |
| Qty | int | 订单数量 | — | — |
| IssuedQty | int | 规划用量 | — | — |
| IssQty | int | 发料数量 | — | — |
| FaliaoDate | datetime | 发料日期 | — | — |
| ReturnQty | int | 需退货数量 | — | — |
| ReturnType | int | 处理方式 | 1=就地销毁，2=退回仓库，3=继续使用，与管理页面一致。业务方 2026-10-22 正式镜像计数：目前只有 3（17,184 行）与 2（2 行），没有空值 | — |
| ReceivingQty | int | 仓库收货数量 | — | — |
| TotalinQty | int | 入库数量 | 管理页面写作「已入库数量」 | — |
| Factory | nvarchar(60) | 订单工厂 | 存工厂码（与主表一致；小板订单存的是名称） | `paxbase.dbo.PaxFactory.FactoryID` → `FactoryName` |
