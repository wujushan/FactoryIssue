# tbIQCreportOut（CAR 纠正预防措施报告）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.tbIQCreportOut
- **所属域**：国内
- **用途**：IQC 检验报告与 8 步纠正预防措施记录。国内问题单经 `CARID` 关联本表，用于回答物料问题的 CAR 内容。
- **数据产生方**：INFO 系统 IQC 报告页面。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| fid | int | （内部字段，不返回） | 主键 | `ZCTracking_ProblemList.CARID` |
| fcheckid | — | （内部字段，不返回） | 检验单 ID | — |
| fcompany | — | 公司名称 | — | — |
| fcount | — | 检验总数 | — | — |
| fcheckcount | — | 检查总数 | — | — |
| fbadcount | — | 不良数量 | — | — |
| fbadper | — | 不良率 | — | — |
| fdesc | — | 问题点 | — | — |
| fstep2how1 | — | 围堵对策 1 | — | — |
| fstep2how2 | — | 围堵对策 2 | — | — |
| fstep2how3 | — | 围堵对策 3 | — | — |
| fstep3memo | — | 根本原因 | — | — |
| fstep3date | — | 根本原因录入时间 | — | — |
| fstep4memo | — | 永久纠正措施 | — | — |
| fstep4date | — | 永久纠正措施录入时间 | — | — |
| fstep5memo | — | 预防措施 | — | — |
| fstep5date | — | 预防措施录入时间 | — | — |
| fstep6memo | — | 有效性确认 | — | — |
| fstep6date | — | 有效性确认录入时间 | — | — |

表内另有多步骤审批记录与人员字段，本模块不使用。
