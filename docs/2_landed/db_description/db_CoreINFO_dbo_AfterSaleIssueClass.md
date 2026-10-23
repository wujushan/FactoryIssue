# AfterSaleIssueClass（现象分类）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.AfterSaleIssueClass
- **所属域**：国内（问题现象所属分类）
- **用途**：售后 / 制程问题的分类主数据，含分类名称、各问题等级的不良率阈值和适用场景。本模块只在国内域用它给已选问题现象取所属分类（经 `ZCTracking_CheckReason.ClassID`）。巴西主表上也有一列指向本表的分类 ID，管理页面不显示，本模块不用；海外不使用。「问题分类」在管理页面上指问题类型，不指本表。
- **数据产生方**：INFO 系统分类维护页面。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | `ZCTracking_CheckReason.ClassID` |
| ClassName | varchar | 分类名称 | 国内问题现象的所属分类 | — |
| TypeName | varchar | 分类类型 | 分类名称的上一级，展示问题现象所属分类时用（分类类型 → 分类名称） | — |
