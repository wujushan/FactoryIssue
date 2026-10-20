# OverseasProblem_StepLog（海外制程问题处理步骤）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.OverseasProblem_StepLog
- **所属域**：海外
- **用途**：问题单流转的处理步骤日志，记录每个环节的处理人、结论、意见、预防措施与附件。
- **数据产生方**：INFO 系统海外制程问题流转时写入。
- **去重规则**：同一问题单（`ProblemId`）的同一步骤名称（`StepStr`）会有多条，查看该环节时只保留 `Id` 最大的一条。看完整处理过程时给全部记录，按 `Id` 升序。
- 步骤上的成员是该步骤节点的处理人，不用它代替主表的当前责任人。步骤上的预防措施与主表的改善措施是两列。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| Id | int | （内部字段，不返回） | 主键 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.OverseasProblemDetail.Id` |
| Step | int | （内部字段，不返回） | 步骤序号 | — |
| StepStr | varchar | 处理环节 | 步骤名称 | — |
| ProblemStatus | int | （内部字段，不返回） | 该步骤时问题单的状态码，枚举同主表 `Status` | — |
| MemberList | varchar | 该步骤处理人 | 该步骤成员 ID，逗号分隔，按段翻成姓名 | `info.dbo.Employee.ID` |
| Result | nvarchar | 结论 | — | — |
| Opinon | nvarchar | 意见 | — | — |
| Measures | nvarchar | 预防措施 | — | — |
| DocID | varchar | （内部字段，不返回） | 该步骤附件 ID，逗号分隔 | `info.dbo.DocumentList.ID` |
| AddUser | int | 创建人 | 创建该步骤的员工 ID | `info.dbo.Employee.ID` |
| AddDate | datetime | 发生时间 | — | — |
