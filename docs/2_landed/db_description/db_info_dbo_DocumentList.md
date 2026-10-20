# DocumentList（文档清单）

- **数据源别名（source）**：info
- **物理表名（table）**：info.dbo.DocumentList
- **所属域**：三域共用
- **用途**：INFO 通用业务附件与文库文档主表。本模块用于问题单附件、处理步骤附件与巴西 8D 报告。附件对应到本表一行后，按「链接规则」生成预览地址，可点击文字用文档名称。
- **数据产生方**：INFO 系统各业务页面上传附件时写入。
- **有效性**：只取 `EffectFlag = 0` 的行；`EffectFlag = 1`（已删除）不展示、不生成链接。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 文档 ID；附件预览链接参数 | 国内 `ZCTracking_ProblemSteplog.FileUrl`；海外 `OverseasProblemDetail.DocId`、`OverseasProblem_StepLog.DocID` |
| DocumentName | nvarchar | 文档名称 | 预览链接的可点击文字 | — |
| DocumentRealName | nvarchar | 文件名 | 含后缀的全称 | — |
| DocumentExtension | nvarchar | 文件类型 | 扩展名 | — |
| DocumentPath | nvarchar | （内部字段，不返回） | 存储路径 | — |
| frecid | int | （内部字段，不返回） | 业务记录 ID，含义随 `BusinessType` 而定 | 巴西 8D：`BrazilProblemProcess.ID`；海外：`OverseasProblemDetail.Id` |
| BusinessType | varchar | （内部字段，不返回） | 业务名称 | — |
| AddDate | datetime | 上传时间 | — | — |
| EffectFlag | int | （内部字段，不返回） | 删除标志：0=有效，1=已删除 | — |

表内另有分组、大小、摘要、浏览 / 下载次数、作者、转换标志等字段，本模块不使用。

## 各域选取附件的条件

| 用途 | 条件 |
|---|---|
| 国内步骤附件 | 处理步骤 `FileUrl` 各段 `= ID`，且 `EffectFlag = 0` |
| 海外填单附件 | 主表 `DocId` 各段 `= ID`；有效性要求 `frecid = 海外主表 Id` 且 `EffectFlag = 0`，不加 `BusinessType` 条件 |
| 海外步骤附件 | 处理步骤 `DocID` 各段 `= ID`；有效性条件同上 |
| 巴西 8D 报告 | `BusinessType = '巴西制程问题单8D报告'`，且 `frecid` 属于该单处理过程表的全部 `ID`，且 `EffectFlag = 0` |

国内、巴西除上表外的其他附件不在查询范围。

海外附件只能从单上登记的文档 ID 出发取，不能只按业务记录 ID 反查。`frecid` 是全公司各业务共用的编号，按海外单 `Id` 反查会撞上 200 多种其他业务的文档（业务方 2026-10-20 内网计数）。单上登记的海外附件，业务记录 ID 都等于海外主表 Id、都未删除；业务名称是「海外制程问题」（填单附件）、「海外制程问题SQE跟进附件」与「海外制程问题工厂分析附件」（步骤附件）。
