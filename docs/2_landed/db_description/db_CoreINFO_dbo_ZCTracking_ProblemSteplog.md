# ZCTracking_ProblemSteplog（国内制程问题处理步骤）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.ZCTracking_ProblemSteplog
- **所属域**：国内
- **用途**：问题单每次节点流转的历史留痕，记录每个环节的处理人、结论、意见、措施与附件。主表 `Status` 是当前状态快照，本表是走过的路径。
- **数据产生方**：INFO 系统制程问题流转时写入。
- **列类型**：按 information_schema（业务方 2026-10-20 内网元数据），字符串长度为声明的字符数。

## 两种读法

| 用户要什么 | 怎么取 |
|---|---|
| 完整处理过程、谁处理过哪些步骤 | 该单**全部**记录，按 `ID` 升序（同 `AddDate` 顺序） |
| 某一环节最新一次的结果 | 同一 `ProblemId` + 同一 `StepStr` 只保留 `ID` 最大的一条 |

同一环节名称会多次出现（如驳回后再次「IQC填写意见」），还原时间线时不能去重。

## 字段

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键；决定先后顺序 | — |
| ProblemId | int | （内部字段，不返回） | 所属问题单 | `CoreINFO.dbo.ZCTracking_ProblemList.ID` |
| Step | int | （内部字段，不返回） | 环节编码。与主表 `Status` 相关但不是同一套编号（如 `Step = 14` 为「IQC填写意见」） | — |
| StepStr | nvarchar(60) | 处理环节 | 环节名称，如「填写问题」「指定责任人」「IQC填写意见」「驳回」「结案确认」 | — |
| ProblemStatus | int | （内部字段，不返回） | 该条记录产生时问题单的状态码，枚举同主表 `Status` | — |
| MemberList | nvarchar(525) | 该步骤处理人 | 该步骤责任人 ID，逗号分隔，按段翻成姓名 | `info.dbo.Employee.ID` |
| Result | nvarchar(2000) | 结论 | 富文本 | — |
| Opinon | nvarchar(2000) | 意见 | 富文本 | — |
| Measures | nvarchar(max) | 措施 | 富文本。工程确认环节（`Step = 3`）的内容中含「处理结果：…」一段，见下 | — |
| FileUrl | nvarchar(525) | （内部字段，不返回） | 该步骤附件的文档 ID，可能逗号多值，按段对应 | `info.dbo.DocumentList.ID` |
| AddUser | int | 创建人 | 创建该步骤的员工 ID | `info.dbo.Employee.ID` |
| AddDate | datetime | 发生时间 | — | — |

## 派生：责任人处理结果

取该单 `Step = 3`（工程确认）`ID` 最大的一条记录的 `Measures`，提取其中「处理结果：」之后的那段文字，显示名「责任人处理结果」。没有这段文字时视为未填。
