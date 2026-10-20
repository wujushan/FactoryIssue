# Brazil_RequestList（巴西申请单）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.Brazil_RequestList
- **所属域**：巴西
- **用途**：巴西业务的需求 / 请票主表。本模块只用它把巴西问题单关联的申请单桥接到 PN。
- **数据产生方**：INFO 系统巴西业务页面。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | `CoreINFO.dbo.BrazilProblemPO.RequestID` |
| PartNumber | varchar | （内部字段，不返回） | 零件号 / PN 编码；连接键，回答中的「PN」展示 PN 主数据上的名称。按 PN 筛选时编码精确匹配、名称包含匹配，任一命中即算 | `info.dbo.NewProduct.PartNumber` |

表内另有合同、客户、需求数量、齐料状态、销售价等字段，本模块不使用。
