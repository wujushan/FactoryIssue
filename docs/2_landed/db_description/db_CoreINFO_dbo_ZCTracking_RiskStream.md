# ZCTracking_RiskStream（国内风险订单流程）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_RiskStream
- **所属域**：国内
- **用途**：问题单涉及风险订单时的退货 / 退库流程，记录当前步骤、进度与责任人。用于「当前状态」中的退货 / 退库一段。
- **数据产生方**：INFO 系统制程问题流转时写入。
- **连接键**：`ProblemId` → 国内主表 `ID`。没有删除标记，随主表。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| Step | int | 退货 / 退库环节 | 14=填写退货信息，15=填写退库信息。与主表状态、处理步骤环节编码不是同一套编号 | — |
| Status | int | 进度 | 1=进行中，2=完成 | — |
| UserID | int | （内部字段，不返回） | 责任人员工 ID，经人员表翻成姓名，显示「责任人」 | `info.dbo.Employee.ID` |
| Remark | nvarchar | 备注 | — | — |
| AddUser | int | 新增人 | 员工 ID | `info.dbo.Employee.ID` |
| AddDate | datetime | 新增时间 | — | — |
