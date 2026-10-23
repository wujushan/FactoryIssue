# Brazil_Factory（巴西工厂）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.Brazil_Factory
- **所属域**：巴西
- **用途**：巴西工厂主数据。巴西问题单直接存工厂**名称**，本表用于工厂名称的取值清单与校对。
- **数据产生方**：INFO 系统巴西业务页面。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| fID | int | （内部字段，不返回） | 主键 | — |
| FactoryName | nvarchar | 加工厂 | 巴西工厂名称 | `BrazilProblemList.BrazilFactory`（逗号多值逐段匹配） |
