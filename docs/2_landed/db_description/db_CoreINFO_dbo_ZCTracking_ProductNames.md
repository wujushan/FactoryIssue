# ZCTracking_ProductNames（国内制程问题机型）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_ProductNames
- **所属域**：国内
- **用途**：问题单涉及的机型。一张单可对应多个机型（同一 `ProblemId` 多行）。
- **数据产生方**：INFO 系统制程问题页面录入。
- **列类型**：按 information_schema（业务方 2026-10-20 内网元数据），字符串长度为声明的字符数。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| ProductId | int | （内部字段，不返回） | 机型 ID | — |
| ProductName | nvarchar(60) | 机型 | 具体终端产品型号，常为「字母 + 数字」简写，如 A920、Q92、IM30、A920Pro。直接使用，不另查产品主数据 | — |
| Series | nvarchar(50) | 系列 | 机型所属系列 | — |
