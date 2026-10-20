# 脏数据描述

> 登记源数据中需在下游处置的脏数据与质量异常。业务口径见 `business_description.md`；待澄清见 `3_open/`。

## 需在 ODS/ETL 处置

| # | 问题 | 处置 |
|---|------|------|
| C1 | 长文本字段含 **HTML 富文本**（`<p>` / `<strong>` / `&nbsp;` 等）及 **图片**：① Base64 内嵌 `<img src="data:image/…;base64,…">`；② 外链 `<img src="https://info2api.paxsz.com/…">`（见 `business_description.md`「富文本（HTML）格式」） | **L2 展示**：`strip_base64_img` **仅**过滤 Base64 图片标签，不剥离段落 HTML、不删外链图；不保证 100% 清除内嵌图。**嵌入路径**（`chunking.strip_html_for_embed`，PR-R4）：Base64 图 + 全部 HTML 标签/`&nbsp;` 等实体剥净后再切 chunk，避免稀释向量与污染 ILIKE；生效需 `dataforge index` 增量/全量重建 |
| C2 | nvarchar(-1) 超大字段（ProblemDesc、Reason） | 叙述型字段：禁入 WHERE / GROUP BY / JOIN |
| C3 | `ZCTracking_ProblemSteplog` 同 `ProblemId` + `StepStr` 有多条记录 | **完整过程**：按 ID/AddDate 保留全部；**某环节最新一次**：同 `ProblemId` + `StepStr` 只保留 ID 最大的一条 |
| C4 | `ZCTracking_ProblemSteplog`.`Measures` 含半结构化「处理结果：…」 | 从 `ZCTracking_ProblemSteplog`.`Step`=3 最新记录正则提取为「责任人处理结果」 |

## 固有数据质量（无法根治）

| # | 问题 | 处置 |
|---|------|------|
| Q1 | Station 自由文本约 425 个不同值；非原子值、分隔符混乱、同义多种写法 | 不可作枚举过滤；靠 LIKE / 语义检索；同义词可能导致漏检 |

## 软删除

`ZCTracking_ProblemList`.`IsDelete` = 1 为已删除记录；子表无独立删除标记，经 `ProblemId` 关联 `ZCTracking_ProblemList`。默认查询排除已删除的制程问题记录。

## 类型不一致

`RUser`、`ReStartExamineUser`、`ReStartSchemeUser` 在源库为 nvarchar，关联 `Employee.ID`（int）时需类型转换；无效值应作空处理。

## 可空关联

`VenCode`、 `AllReDepartment`、`CARID` 等可空；LEFT JOIN 后展示为空而非报错。
