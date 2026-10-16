# OverseasProblem_DeliveryOrder（海外制程问题涉及发货单）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.OverseasProblem_DeliveryOrder
- **所属域**：海外
- **用途**：问题单涉及的发货单。一张单可有多行；发货单行数不是问题单张数。
- **展示**：按下表顺序列出，首列「序号」展示时从 1 现编；默认按发货单号升序。另给「订单数量合计」= 该单各行订单数量之和。没有发货单时不展示列表与合计。
- **数据产生方**：INFO 系统海外制程问题页面录入。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| Id | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.OverseasProblemDetail.Id` |
| PO | varchar | PO | 采购订单号 | — |
| OrderNumber | varchar | 发货单号 | — | — |
| Date | varchar | 发货日期 | 文本存日期，格式 `YYYY-MM-DD` | — |
| PN | varchar | PN | 发货单自己的 PN 编号，按原文展示，不经 PN 主数据翻译 | — |
| DeliveryVersion | varchar | 发货版本 | — | — |
| ProdVersion | varchar | 生产版本 | — | — |
| Quantity | int | 订单数量 | — | — |
| Remark | varchar | 备注 | — | — |
