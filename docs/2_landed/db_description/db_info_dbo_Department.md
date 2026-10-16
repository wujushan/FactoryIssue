# Department（部门）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.Department
- **所属域**：三域共用
- **用途**：部门主数据，把部门 ID 翻成名称。
- **数据产生方**：INFO 系统组织架构。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 部门 ID | `Employee.Unit`；国内 `RDepartment`、`AllReDepartment`；海外 `RDepartment` |
| Name | varchar | 部门 | 部门中文常用名。回答中按所在列的业务角色显示（如「问题跟进部门」「责任归属部门」） | — |
