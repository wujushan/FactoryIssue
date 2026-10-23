# Brazil_RequestList（巴西申请单）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.Brazil_RequestList
- **所属域**：巴西
- **用途**：巴西业务的需求 / 请票主表。本模块只用它把巴西问题单关联的申请单桥接到 PN。
- **数据产生方**：INFO 系统巴西业务页面。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | `CoreINFO.dbo.BrazilProblemPO.RequestID` |
| PartNumber | varchar | PN 编码 | 数字编码，多为 15 位。「0」是没选 PN 时的占位值（业务方 2026-10-22 正式镜像计数：未删除单关联的 307 条申请单中 52 条），与管理页面一致，不展示、不参与按 PN 查，见巴西业务描述「大机型与 PN」。其余与 PN 主数据的 PartNumber 关联得到 PN 名称，展示为「PN 名称 PN 编码」，找不到名称时只给编码。按 PN 筛选时编码精确匹配、名称包含匹配，任一命中即算 | `info.dbo.NewProduct.PartNumber` |
