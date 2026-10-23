# AfterSaleIssueClassPhenomenonReason（现象可能原因）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason
- **所属域**：海外、国内
- **用途**：某条标准现象下可供选择的原因清单。回答「可能问题原因」时用；它不是问题单上已经写下的原因分析。海外按标准现象取全部原因；国内只取单上登记的那几条（`ZCTracking_CheckReason.ReasonID`）。
- **数据产生方**：INFO 系统分类维护页面。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | `ZCTracking_CheckReason.ReasonID` |
| PhenomenonID | int | （内部字段，不返回） | 所属标准现象 | `CoreINFO.dbo.AfterSaleIssueClassPhenomenon.ID` |
| ReasonDesc | nvarchar | 可能问题原因 | 原因描述 | — |
| AddUser | int | （内部字段，不返回） | 审计列：录入人 | `info.dbo.Employee.ID` |
| AddDate | datetime | （内部字段，不返回） | 审计列：创建时间 | — |
| LastUser | int | （内部字段，不返回） | 审计列：最后修改人 | — |
| LastDate | datetime | （内部字段，不返回） | 审计列：最后修改时间 | — |
