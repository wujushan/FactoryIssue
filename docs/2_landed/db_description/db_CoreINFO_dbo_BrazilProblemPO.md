# BrazilProblemPO（巴西制程问题关联申请单）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.BrazilProblemPO
- **所属域**：巴西
- **用途**：问题单与发货侧申请单的关联，用于解析 PN：`RequestID` → `Brazil_RequestList.PartNumber` → `NewProduct.Name`（展示为「PN」，一单多个合并为「PN 列表」）。一张单可关联多条。
- **数据产生方**：INFO 系统巴西制程问题页面录入。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemID | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.BrazilProblemList.ID` |
| RequestID | int | （内部字段，不返回） | 申请单 ID | `info.dbo.Brazil_RequestList.ID` |
| OnlineQty | int | 在线数量 | — | — |

本域不使用源表的 `InvoiceNoAll`、`RequestType`、`Memo`。
