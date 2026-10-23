# NewProduct（PN 主数据）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.NewProduct
- **所属域**：巴西、海外
- **用途**：新产品（PN）主数据，把 PN 编码翻成 PN 名称。三域用的是同一套 PN（国内生产订单上自带名称，不查本表）。
- **数据产生方**：INFO 系统新产品维护。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| FID | int | （内部字段，不返回） | 主键 | — |
| PartNumber | varchar | PN 编码 | 15 位数字，业务主键，用户认得的编号。与存货档案的料号是同一套物料编码（料号全部也是 PN 编码，本表另多出少量号；业务方 2026-10-20 确认）。按 PN 筛选时精确匹配 | 巴西 `Brazil_RequestList.PartNumber`；海外 `OverseasProblemDetail.PNList`（逗号多值逐段匹配）、`OverseasProblem_DeliveryOrder.PN` |
| Name | nvarchar | PN 名称 | 带连字符的型号码。按 PN 筛选时包含匹配 | — |

回答中的「PN」展示为「PN 名称 PN 编码」，与管理页面一致；一单多个时去重，用「、」连接（巴西称「PN 列表」）。
