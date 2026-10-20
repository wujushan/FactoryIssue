# ProductName（产品 / 大机型）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.ProductName
- **所属域**：巴西、海外
- **用途**：产品（大机型）主数据，把大机型 ID 翻成名称与系列。
- **数据产生方**：INFO 系统产品主数据维护。
- **列类型**：按 information_schema（业务方 2026-10-20 内网元数据），字符串长度为声明的字符数。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | 巴西 `BrazilProblemList.ProductIDAll`（逗号多值逐段匹配）；海外 `OverseasProblemDetail.ProductType`（逗号多值逐段匹配） |
| ProductName | varchar(50) | 大机型 | 产品 / 大机型名称，不可空。巴西、海外一单可多个，去重后用「、」连接 | — |
| Series | varchar(50) | 系列 | 可空 | — |

表内另有编码、分类、在用状态、产品经理等字段，本模块不使用。
