# 脏数据描述

> 登记源数据中需在下游处置的脏数据与质量异常。业务口径见 `business_description.md`。

## 需在下游处置

| # | 问题 | 处置 |
|---|------|------|
| D2 | **ClaimNumber 写法多样**：自由文本；多数以 `CLAIM` 开头（如 `CLAIM 014.04/2024`、`CLAIM-019/24`），但非强制；**不是** `CLAIN` | 展示原值；筛选靠模糊匹配或语义检索，不作固定格式解析 |
| D3 | **Process 是否类字段源值混型**：源库可能存在 `'1'`/`'2'` 数字写法 | **以 `tables.md` 中文枚举为准**（是、否、为空、需要、不需要等）；归一化为统一展示值 |
| D4 | **ProblemType 管道格式**：`其他\|自由文本备注` | 类型恒为「其他」；`问题类型` 展示归一化为「其他」；备注进展示列 **`其他问题备注说明`**；筛选「其他」须含 `其他\|*` 模式 |
| D5 | **ProblemPhenomenon JSON**：可能含转义问题；非 `[` 开头或空则按空数组 | 按 `business_description.md`「问题现象」展平为 `；` 分隔可读文本；非法转义须容错后再解析 |
| D6 | **长文本 HTML + Base64 图片**（叙述型长文本字段） | **默认与 `ProblemDesc` 相同**：源数据保留 HTML；展示与语义检索前**仅剔内嵌 Base64 图片**；段落 HTML、外链图保留；**不以**长文本字段做结构化筛选条件；语义检索在清洗后分块 |
| D7 | **DocumentList 软删除** | `EffectFlag=1` 为已删除文档；查 8D 默认仅 `EffectFlag=0` |

## 日期字段治理

> **策略**：与国内一致——**源数据严格镜像源类型**；**主查询口径收敛**为可筛选、可排序的统一日期。信源：`2_landed/domestic/data_architecture.md`。

### 分层

| 层 | 规则 |
|----|------|
| **源数据镜像** | varchar 日期列 **原样保留**（不改类型、不丢原值）；已是 `datetime` 的列原样保留 |
| **主查询** | 为 varchar 日期列提供解析后的可比较日期；**筛选 / 排序 / 统计仅使用解析列** |
| **无效值** | 解析失败 → 视为空（不作猜测填充） |

### varchar 日期列（须在主查询解析）

| 表 | 字段 |
|----|------|
| `BrazilProblemList` | `StopDate`、`ProblemDiscoveryDate`、`StatisticsDate` |
| `BrazilProblemProcess` | `PlanCompleteDate`、`DesignEstimateDate` |

### 已是 datetime（源数据与主查询直通，与国内相同）

| 表 | 字段（节选） |
|----|-------------|
| `BrazilProblemList` | `AddDate` → 主查询 **`建单日期`**（**默认时间筛选**）、`UpdateDate`、`SupplementDate` |
| `BrazilProblemProcess` | `StockPrecessDate`、`DesignDate`、`SQEDate`、`ProcessDate`、`ConfirmDate`、`FinishDate` 等 |

### 混型（varchar 与 datetime 并存）

同表内 varchar 与 datetime 并存 **不视为数据错误**；源数据保持源类型，主查询统一提供可比较的日期列；**筛选 / 排序 / 统计仅使用解析列**。

### 解析格式

优先支持常见字面量：`YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY-MM-DD HH:MI:SS` 等；具体容错以对账抽样为准（类比国内对字符串日期的容错思路）。

## 固有数据质量（无法根治）

| # | 问题 | 处置 |
|---|------|------|
| Q1 | `BrazilFactory` 存**工厂名称**（源自 `Brazil_Factory.FactoryName`），可为逗号分隔多值（如 `CA,TT`） | **按段匹配**：搜 `CA` 须命中 `CA` 与 `CA,TT`；对主查询列 `加工厂` 按逗号拆分后逐段比较 |
| Q2 | `ProblemDiscoveryStation` 自由文本，无固定枚举 | 同 Q1 |
| Q3 | `StopStatus` 仅两态：空（未标记重启）或 `停线重启`；**`IsStopLine` 一旦发生停线为「是」，重启后不改为「否」** | 「停线中」=`是否停线`=是 且 `停线状态` 为空；「曾停线」= `是否停线`=是；「从未停线」=`是否停线`=否 |
| Q4 | `ProductIDAll` 逗号分隔 ID，可能含空格或无效 ID | 去除首尾空格；无效 ID 展示原始片段 |
| Q5 | `IsCost = 0` 为删除状态测试数据 | 展示时按无效值处理；筛选业务口径用 `IN (1, 2)` |
| Q6 | 同一 `ProblemID` 多条 `BrazilProblemPO`：PN **一般相同**，但**不能排除**不同 PN | v1 合并为 **`PN列表`**；筛选按列表是否包含指定 PN |
| Q7 | 同一 `ProblemID` 多条 `BrazilProblemCost`：常**按费用类型占满行**，多数行为 0 金额；零行上 `ConstBrlRate` 常为 0 | 主查询 `费用USD合计`/`费用BRL合计` = 全部费用行金额求和；`专项费用明细` **仅非零行**；汇率/备注在费用明细查询中展示（见 `business_description.md` §费用聚合） |
| Q8 | 8D 文件挂在过程表 `ID`，非主表 `ID`；一单多过程可对应多份文档 | 检索：`BusinessType='巴西制程问题单8D报告'` 且 `frecid` ∈ 该单全部过程 `ID`；主查询不并文件行（见 §8D 报告） |

## 默认查询排除（业务口径，非权限）

| 条件 | 含义 |
|------|------|
| `Status = -1` | 已删除 |

默认查询：`Status <> -1`。`Status = 0`（待提交 / 草稿）**不排除**。子表无独立删除标记，经 `ProblemID` 关联主表。

## 类型不一致

| 问题 | 处置 |
|------|------|
| `ProblemClass` 存 `AfterSaleIssueClass.ID`，源类型可能为 varchar | 关联时按源库实际类型对账转换 |
| varchar 与 datetime 日期混存 | 见上「日期字段治理」；**不在源数据镜像层强行统一类型** |

## 可空关联

`cVenCode`、`ProductIDAll`、`ProblemDiscoveryStation`、`ClaimNumber` 等可空；关联后展示为空而非报错。

## 一对多子表汇总（一行一单）

> 明细规则见 `business_description.md`「一行一单原则」。

| 子表 / 字段 | 规则 |
|-------------|------|
| `BrazilProblemProcess` | 同 `ProblemID` 取 `ID` 最大的一条（最新过程记录） |
| `BrazilProblemPO` | 同 `ProblemID` 可**多条**；合并去重为 **`PN列表`**，主表仍一行 |
| `BrazilProblemCost` | 同 `ProblemID` 汇总为 `费用USD合计` / `费用BRL合计` / `专项费用明细`（非零行拼接），**主表一行** |
| `ProductIDAll` | 列内逗号分隔 ID：解析后合并为机型名称列表，不增加行数 |
| `ProblemPhenomenon` | 列内 JSON：展平为 `问题现象` 可读文本，不增加行数 |

## v1 不纳入（无需同步脏数据规则）

`BrazilProblemInvCode`、`BrazilProblemLog`、`BrazilProblemProcessCKD`、`BrazilProblemProcessStock`、`tbTask`。
