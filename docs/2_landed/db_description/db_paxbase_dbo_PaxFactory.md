# PaxFactory（国内工厂）

- **数据源别名（source）**：erp
- **物理表名（table）**：paxbase.dbo.PaxFactory
- **所属域**：国内、海外
- **用途**：国内工厂主数据，把工厂码翻成工厂名称。
- **数据产生方**：基础资料维护。
- **所在实例**：ERP 实例，与问题单所在的 INFO 实例不是同一台。问题单上的工厂码要与本表分开取、再按工厂码对应。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| FactoryID | varchar(50) | （内部字段，不返回） | 国内工厂码 | 国内 `ZCTracking_ProblemList.Factory`、`ZCTracking_OtherOrder.Factory`；海外 `OverseasProblemDetail.Factory2` |
| FactoryName | nvarchar(100) | 加工厂（国内主表）/ 订单工厂（国内小板订单、其他在线订单）/ 国内工厂（海外） | 国内工厂名称。名称可能重复：业务方 2026-10-24 查询，共 10 个工厂码，「柯洱斯」有 04、06 两个。按名称对工厂码时同名的码一起对上，见国内业务描述「加工厂」 | 国内 `ZCTracking_XBOrders.Factory`（小板订单直接存名称） |
