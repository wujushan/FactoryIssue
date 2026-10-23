# Inventory（存货档案）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.Inventory
- **所属域**：国内、巴西
- **用途**：物料主数据（与 ERP 对齐），把料号翻成物料名称与规格型号。
- **数据产生方**：由 ERP 存货档案同步到 INFO。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| cInvCode | nvarchar | 料号 | 物料编码，15 位数字（个别例外）；与 PN 主数据的 PN 编码是同一套编码 | 国内 `ZCTracking_ProblemList.CInvCode`、`ZCTracking_XBOrders.InvCode`；巴西 `BrazilProblemList.cInvCode` |
| cInvName | nvarchar | 物料名称 | — | — |
| cInvStd | nvarchar | 规格型号 | 物料描述 / 规格型号 | — |
