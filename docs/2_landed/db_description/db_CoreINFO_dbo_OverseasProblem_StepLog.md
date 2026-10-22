# OverseasProblem_StepLog（海外制程问题处理步骤）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.OverseasProblem_StepLog
- **所属域**：海外
- **用途**：问题单流转的处理步骤日志，记录每个环节的处理人、结论、意见、预防措施与附件。
- **数据产生方**：INFO 系统海外制程问题流转时写入。
- **去重规则**：同一问题单（`ProblemId`）的同一步骤名称（`StepStr`）会有多条，只保留 `Id` 最大的一条。查看该环节、看完整处理过程都如此，完整处理过程再按 `Id` 升序排（与国内一致，业务方 2026-10-22 答复）。
- 按文字找单时只比对分析类环节、每个环节最新一条的意见与预防措施（工厂制程分析另含结论），环节清单见总述「比对范围」。
- 步骤上的成员是该步骤节点的处理人，不用它代替主表的当前责任人。步骤上的预防措施与主表的改善措施是两列。
- **派生：结案时间**：只对主表状态为「已完成」的单定，取该单 `StepStr` 为「结案确认」、`Id` 最大的一条记录的 `AddDate`，显示名「结案时间」。没有这样的记录时定不出结案时间，按结案时间筛选、统计时不计入（见总述「结案时间与结案周期」）。个别已完成的单没有「结案确认」记录（见 `dirty_data.md`「其他」）。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| Id | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.OverseasProblemDetail.Id` |
| Step | int | （内部字段，不返回） | 步骤序号 | — |
| StepStr | varchar | 处理环节 | 步骤名称 | — |
| ProblemStatus | int | （内部字段，不返回） | 该步骤时问题单的状态码，枚举同主表 `Status` | — |
| MemberList | varchar | 该步骤处理人 | 该步骤成员 ID，逗号分隔，按段翻成姓名 | `info.dbo.Employee.ID` |
| Result | nvarchar | 结论 | 只有工厂制程分析环节是文字，原样展示。SQE跟进存 0 / 1，与国内一致：0 = 不需要设计变更，1 = 需要设计变更（目前只有 0）。其余环节为空 | — |
| Opinon | nvarchar | 意见 | — | — |
| Measures | nvarchar | 预防措施 | — | — |
| DocID | varchar | （内部字段，不返回） | 该步骤附件 ID，逗号分隔 | `info.dbo.DocumentList.ID` |
| AddUser | int | 创建人 | 创建该步骤的员工 ID | `info.dbo.Employee.ID` |
| AddDate | datetime | 发生时间 | — | — |
