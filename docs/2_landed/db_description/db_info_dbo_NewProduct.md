# NewProduct（PN 机型）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.NewProduct
- **所属域**：巴西、海外
- **用途**：新产品（PN）主数据，把 PN 翻成机型名称。
- **数据产生方**：INFO 系统新产品维护。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| FID | int | （内部字段，不返回） | 主键 | — |
| PartNumber | varchar | （内部字段，不返回） | 机型编码，业务主键；连接键，回答中的「PN」展示下面的名称。按 PN 筛选时编码与名称任一命中 | 巴西 `Brazil_RequestList.PartNumber`；海外 `OverseasProblemDetail.PNList`（逗号多值逐段匹配） |
| Name | nvarchar | PN | 巴西、海外回答中的「PN」展示本列；巴西一单多个时去重合并为「PN 列表」，海外多段用逗号拼接 | — |

表内另有描述、大类 / 小类、市场名称、重量尺寸、量产状态等字段，本模块不使用。
