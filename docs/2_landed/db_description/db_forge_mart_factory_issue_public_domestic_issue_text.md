# domestic_issue_text（文字表，三域同族）

- **数据源别名（source）**：forge_mart_factory_issue
- **物理表名（table）**：public.domestic_issue_text
- **表族（family）**：public.<域>_issue_text（域 = domestic、brazil、overseas，即国内、巴西、海外）
- **所属域**：每域一张，国内为代表成员
- **用途**：按文字找单用的叙述文字，一单一行，只含未删除的单。比对范围以外的叙述字段与处理步骤的某一列在这里按词找（总述「点名字段时怎么找」）；导出清单时的问题描述全文也取这里。
- **数据产生方**：本助手的治理任务，从各域主表与子表读原文，剥净后写入：按指纹增量每 30 分钟一次，全量重建每天凌晨一次（决策 2026-10-20「G2 数据源与治理决策」「同步策略」）。表由治理任务建，首轮跑之前不存在。最近约半小时内新建或改过文字的单可能还没整理进来（总述「命中后带回什么与时效」）。
- **列类型**：全部列 text，不可空；同步时间为 timestamptz。叙述列没有内容时存空串。
- **权限**：表级，随所属域给「允许」（`privileges.md`「权限里要列出的表」）；没有行级、列级规则，也没有权限承载列。

## 字段（三域共有）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| issue_id | text | （内部字段，不返回） | 本域主表主键转成的文字；主键 | 国内 `ZCTracking_ProblemList.ID`、巴西 `BrazilProblemList.ID`、海外 `OverseasProblemDetail.Id` |
| issue_no | text | （内部字段，不返回） | 问题编号，只便于排查；回答里的问题编号取主表 | — |
| text_fingerprint | text | （内部字段，不返回） | 源库算出的本单文字指纹，增量同步时比较用 | — |
| synced_at | timestamptz | （内部字段，不返回） | 本行同步时间 | — |

## 成员差异：各域的叙述列

每个叙述字段一列，列名是 `f_` 加字段代号。文字都已剥净：去掉内嵌图片、外链图片、HTML 标签，实体还原，段落与换行留成换行，行内连续空白压成一个（`dirty_data.md`「富文本」）。不做大小写、全半角的归一化，命中处的上下文直接从这里截。没有该字段的域没有这一列（下表「—」）。

| 字段 | 用户可见显示名 | 国内 | 巴西 | 海外 |
|---|---|---|---|---|
| f_phen | 问题现象 | 已选现象表 `PhenomenonID` → 现象主数据 `PhenomenonDesc`，按现象去重、按已选现象表 `ID` 先后，用「；」连接 | 主表 `ProblemPhenomenon` 按展平规则（标准与手填都进） | 主表 `hasCheckedPhenomenon` 按展平规则（标准与手填都进），即「已选问题现象」 |
| f_desc | 问题描述 | 主表 `ProblemDesc` | 主表 `ProblemDesc` | 主表 `ProblemDesc` |
| f_reason | 原因分析 | 主表 `Reason` | 最新一条处理过程 `ReasonAnalysis` | 主表 `Reason` |
| f_improve | 改善建议 | 主表 `Improve` | — | 主表 `Improve` |
| f_measure | 改善措施 | 主表 `Measures` | 最新一条处理过程 `ImprovementMeasure` | 主表 `Measures` |
| f_prev | 预防对策 | 主表 `Prevention` | 最新一条处理过程 `PrecautionPolicy` | 主表 `Prevention` |
| f_sqe | SQE 跟进结果 | — | 最新一条处理过程 `DisposeResult` | — |
| f_confirm | 效果确认内容 | 主表 `Confirmation` | — | 主表 `Confirmation` |
| f_remark | 备注 | 主表 `Remark` | 主表 `Memo` | 主表 `Remark` |
| f_produce | 生产确认备注 | 主表 `ProduceConfirmRemark` | — | — |
| f_rclass | 原因分类说明 | 主表 `ReasonClassRemark` | — | — |
| f_restart | 重启方案 | 主表 `ReStartScheme` | — | — |
| f_other | 其他问题说明 | — | — | 主表 `ProblemRemark` |
| f_supply | 补料备注 | — | 主表 `SupplementMemo` | — |
| f_batch | 改善批次 | — | 最新一条处理过程 `ImprovementBatch` | — |
| f_unshift | 未转嫁原因 | — | 最新一条处理过程 `UnCostShiftReason` | — |
| f_owner_memo | 责任人确认备注 | — | 最新一条处理过程 `ProcessMemo` | — |
| f_design_memo | 设计更改备注 | — | 最新一条处理过程 `DesignMemo` | — |
| f_sqe_memo | SQE 确认备注 | — | 最新一条处理过程 `SQEMemo` | — |
| f_confirm_memo | 效果确认备注 | — | 最新一条处理过程 `ConfirmMemo` | — |
| f_finish_memo | 结案备注 | — | 最新一条处理过程 `FinishMemo` | — |
| f_cost_memo | 费用备注 | — | 费用明细 `CostMemo`：全部费用行按 `ID` 先后，每条「费用类型：备注」，换行分隔，备注为空的行不写 | — |
| f_step_result | 处理步骤结论 | 处理步骤 `Result`，见下 | — | 处理步骤 `Result`，见下 |
| f_step_opinion | 处理步骤意见 | 处理步骤 `Opinon`，见下 | — | 处理步骤 `Opinon`，见下 |
| f_step_content | 处理步骤内容 | 处理步骤 `Measures`，见下 | — | 处理步骤 `Measures`，见下 |

- **最新一条处理过程**（巴西）：同一张单 `ID` 最大的一条，与清单、详情的取法相同（巴西处理过程表「只取最新一条」）。
- **处理步骤三列**（国内、海外）：每个环节取 `ID` 最大的一条，全部环节都取，不限于分析类环节（总述「点名字段时怎么找」）；国内按环节编码 `Step` 认环节，海外按环节名称 `StepStr` 认。按这些记录的 `ID` 先后排，每条「环节名称：」开头（名称取那一条上的），换行分隔；该列为空的环节不写。
  - 内容列去掉开头的操作人姓名：内容以这一条操作人的姓名开头时去掉姓名，姓名后紧跟「，」「,」「：」「:」「、」或空白时连这一个分隔符一起去掉；姓名不在开头的不动。
  - 结论只取工厂制程分析一个环节：其余环节的结论存的是代码、日期、员工 ID 或空（国内、海外处理步骤表「结论」），按词找不该命中它们。
- **不在这张表里的**：巴西问题类型里的「其他问题说明」（巴西「叙述文字」没有列它）；处理步骤的附件、操作人；可能问题原因、可能的问题物料、5Why（不进比对范围，也不在各域「叙述文字」里）。
- **查询时另判的**：本表照存重启方案与重启那三个环节的条目；停线状态为重启审核中、责任人填写重启方案的单按词找时不匹配它们，按实时的停线状态判（国内「停线」）。
