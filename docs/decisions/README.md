# docs/decisions —— 带日期的决策记录

业务与技术决策的追加式记录（G2 治理决策、**G4a 模块技术设计**、口径变更、G1 放行说明等）。
文件名 `YYYY-MM-DD-<主题>.md`。推翻既有决策须新增记录并在原文标注，不直接改写历史。

## G2 数据源与治理/向量化决策模板（复制改写）

原始结构化取数**一律直连 info/erp**（连接串指向只读热备副本，无同步延迟、不打主库）——G2 不再权衡「直连 vs 镜像」。
G2 只判定：**是否需要数据治理（清洗/标准化）或非结构化字段向量化**？需要则建 `forge_mart_<code>` 产物库并启用对应 profile。

```markdown
# YYYY-MM-DD 数据源与治理决策

## 涉及数据与数据量（来自 G1 business_description）
- 表 / 大致行数 / 更新频率 / 是否含脏数据 / 是否含需向量化的非结构化字段

## 是否需要治理/向量化（逐源判定）
| 数据（表/域） | 当前所属实例 | 是否含脏数据 | 是否含需向量化的非结构化字段 | 决策：直连即可 / 建 forge_mart_<code>（治理后表/向量表） | 同步策略(cron/水位) |
|---|---|---|---|---|---|
| … | info / erp | 否 / 是 | 否 / 是 | … | 直连则空 |

## 权限承载列清单（建 mart 就必填，逐表列出）
> 这是全链路最贵的返工点：ETL/向量化漏透传一列 → 平台启动期将该模块隔离下线
> （`/healthz` 的 `failed_modules`，`reason=vector_scope_missing`）→ 补列 → 改迁移 → 重建表 → 全量重跑 embedding。**在这里写死，别留到编码时才想**。

| 产物表 | 权限承载列（= privileges 行/列规则引用的字段对应的物理列） | 来自源表哪一列 | 是否已确认不跨权限维度预聚合 |
|---|---|---|---|
| … | dept_id, … | … | 是 / 否（否则行级过滤失去粒度） |

## 受列级管控字段的处置（有 semantic-retrieval 且字段受 dataScope.column 管控时必填）
> **列级权限当前不作用于检索路径**（协议层语义空缺）——别默认「跟 .query() 一样严」。
> 二选一并写明理由：

- [ ] 不向量化该字段
- [ ] 按敏感度分表/分区，把列级**降维成行级**（向量库里唯一能真正下推的形态）
- 涉及字段与结论：…

## 结论
- manifest.data_sources 需声明的别名：`[...]`（原始表 = info/erp 并集；如建 mart 则加 forge_mart_<code>）
- 启用的 profiles：structured-query / semantic-retrieval / governance-etl …
- 若建治理/向量产物库：库名 forge_mart_<code>、同步/向量化 job 的 cron、由平台运维建库（部署指南 §5.1）
```

> ⏱ **时序硬约束**：本决策的评审必须发生在**申请建库之前**。`forge data provision-mart` 是运维
> 当场传入管理员口令、跑完即走的动作，不是可以「先建了再改」的东西。

## G4a 模块技术设计模板（复制改写）

G2 定的是**数据侧形态**（用哪些源、要不要治理/向量化）；G4a 定的是**模块内部设计**。
纯 `structured-query` 模块几十行足够，带 `governance-etl`/`semantic-retrieval`/`analysis-report`
的必须独立成文。**编码时偏离本文档，要回来改本文档**，别让代码与设计各说各话。

```markdown
# YYYY-MM-DD 模块技术设计

## manifest 草案
- intents / keywords（路由素材，直接影响入口路由质量）
- data_sources：别名 + 用到的表（须与 G1 各表 source 并集一致）
- dependencies：要调用的其他模块编码（装配期做 DAG 校验）

## 权限字段映射（field_mappings）—— 逐列锚定，本文档最该被评审的一节
| 数据源别名 | 协议权限字段 | 物理列 | 依据（db_description 哪张表哪一列） |
|---|---|---|---|
| info | departmentId | dept_id | db_INFODB_dbo_Xxx.md |

> 映射缺失 → DataScopeFilter fail-closed 拒查；锚错列 → 越权。两种都不会在测试里自己蹦出来。

## handle() 编排与事件序列
- 参数够不够 → 不够发什么 CLARIFY（对应 manifest.clarify_dimensions）
- 取数：走 ctx.data 的哪几次查询、select 哪些列
- 数字：哪些统计交给 ctx.stats（沙箱脚本的输入输出形状）
- 输出顺序：delta / table / chart / citation / suggestions
- 多轮：要不要用 conversation_messages 拼上下文；**若把 query 当检索输入，先消解成自足 query**

## 错误与降级
- 取不到数 / 权限不足 / 上游超时，各自返回什么（message 一律业务语言，不露表名字段名）
```

> **治理/向量产物库（mart）的权限透传硬约束**（建 mart 即必须满足，否则取数 fail-closed）：INFO 的 privileges 用与库无关的
> 协议字段词汇，`field_mappings` 按源把它锚定到物理列——它只能重指已存在的列，不能凭空造。所以治理/向量 ETL **必须
> 透传全部权限承载列**（privileges 行/列规则引用的字段）且**不得跨权限维度预聚合**
> （否则行级过滤失去粒度）。详见平台仓 `docs/dev/04-permissions-and-data-access.md`「原始取数直连 info/erp；mart 只用于治理/向量化」小节。

