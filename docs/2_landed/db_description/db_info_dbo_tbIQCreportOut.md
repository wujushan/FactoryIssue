# tbIQCreportOut（CAR 纠正预防措施报告）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.tbIQCreportOut
- **所属域**：国内
- **用途**：IQC 检验报告与 8 步纠正预防措施记录。国内物料问题单经 `CARID` 关联本表，用于回答物料问题的 CAR 内容；其他类型的单即使有 `CARID` 也不读取、不展示。
- **权限**：本表单独授权。没有 CAR 报告权限的用户不读取、不展示本表内容（见 `privileges.md`「CAR 报告」）。CAR 报告页面链接对所有用户生成，用主表 `CARID` 拼出，不需要读本表（见 `link_rules.md`）。
- **数据产生方**：INFO 系统 IQC 报告页面。
- **列类型**：按 information_schema（业务方 2026-10-20 内网元数据），字符串长度为声明的字符数。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| fid | int | （内部字段，不返回） | 主键 | `ZCTracking_ProblemList.CARID` |
| fcheckid | int | （内部字段，不返回） | 检验单 ID | — |
| fcompany | nvarchar(500) | 公司名称 | — | — |
| fcount | varchar(50) | 检验总数 | 文本存数量，按原值展示，不参与计算 | — |
| fcheckcount | varchar(50) | 检查总数 | 文本存数量，按原值展示，不参与计算 | — |
| fbadcount | varchar(50) | CAR 不良数量 | 文本存数量，按原值展示，不参与计算 | — |
| fbadper | varchar(50) | CAR 不良率 | 文本，按原值展示，不参与计算 | — |
| fdesc | varchar(max) | 问题点 | — | — |
| fstep2how1 | nvarchar(1000) | 围堵对策 1 | — | — |
| fstep2how2 | nvarchar(1000) | 围堵对策 2 | — | — |
| fstep2how3 | nvarchar(1000) | 围堵对策 3 | — | — |
| fstep3memo | varchar(3000) | 根本原因 | — | — |
| fstep3date | smalldatetime | 根本原因录入时间 | — | — |
| fstep4memo | nvarchar(3000) | 永久纠正措施 | — | — |
| fstep4date | smalldatetime | 永久纠正措施录入时间 | — | — |
| fstep5memo | nvarchar(3000) | 预防措施 | — | — |
| fstep5date | smalldatetime | 预防措施录入时间 | — | — |
| fstep6memo | nvarchar(2000) | 有效性确认 | — | — |
| fstep6date | smalldatetime | 有效性确认录入时间 | — | — |

表内另有多步骤审批记录与人员字段，本模块不使用。
