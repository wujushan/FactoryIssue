# AfterSaleIssueClass（问题分类）

- **数据源别名（source）**：info
- **物理表名（table）**：CoreINFO.dbo.AfterSaleIssueClass
- **所属域**：巴西（停线级别）、国内（问题现象所属分类）
- **用途**：售后 / 制程问题的分类主数据，含分类名称、各问题等级的不良率阈值和适用场景。本模块在巴西域把它当作「停线级别」的名称表；在国内域给已选问题现象取所属分类（经 `ZCTracking_CheckReason.ClassID`）。海外不使用。
- **数据产生方**：INFO 系统分类维护页面。

## 字段（本模块用到的部分）

| 字段 | 类型 | 用户可见显示名 | 含义与取值 | 关联 |
|---|---|---|---|---|
| ID | int | （内部字段，不返回） | 主键 | `BrazilProblemList.ProblemClass`；`ZCTracking_CheckReason.ClassID` |
| ClassName | varchar | 停线级别（巴西）；现象分类（国内） | 分类名称。巴西回答停线级别时用名称，不用编号；国内作为问题现象的所属分类 | — |
| TypeName | varchar | 分类类型（国内） | 分类名称的上一级，只在国内展示问题现象所属分类时用（分类类型 → 分类名称） | — |

表内另有 A/B/C 等级不良率上下限、适用场景（人工 / 客户 / 海外制程）与审计列，本模块不使用。
