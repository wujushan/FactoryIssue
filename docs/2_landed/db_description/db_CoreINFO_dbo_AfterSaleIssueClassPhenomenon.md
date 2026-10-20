# AfterSaleIssueClassPhenomenon（标准问题现象）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.AfterSaleIssueClassPhenomenon
- **所属域**：海外
- **用途**：标准问题现象主数据。海外主表「已选问题现象」中 `Key` 大于 0 的元素指向本表。
- **数据产生方**：INFO 系统分类维护页面。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | `OverseasProblemDetail.hasCheckedPhenomenon[].Key`；`AfterSaleIssueClassPhenomenonReason.PhenomenonID` |
| ClassID | int | （内部字段，不返回） | 所属分类；本模块不使用，不关联问题分类表 | — |
| PhenomenonDesc | nvarchar | 标准现象描述 | 标准现象的文字。不替代海外单上「已选问题现象」的文字 | — |
| AddUser | int | （内部字段，不返回） | 审计列：录入人 | `info.dbo.Employee.ID` |
| AddDate | datetime | （内部字段，不返回） | 审计列：创建时间 | — |
| LastUser | int | （内部字段，不返回） | 审计列：最后修改人 | — |
| LastDate | datetime | （内部字段，不返回） | 审计列：最后修改时间 | — |
