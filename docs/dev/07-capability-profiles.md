# 07 · 能力 Profile 指引（初始化与追加的处理手册）

> 面向 **build-time 编程助手（Claude Code / Codex）** 与开发者。
> 当你在本仓要「**初始化时选哪些 profile**」或「**追加某个 profile 能力**」时——
> **先读本文对应小节，按其「声明 / 依赖 / 代码 / 平台前置 / DoD」办**，不要凭记忆展开。
>
> profile 的**权威目录（体系级定义）** 在平台仓的架构决策文档里（你仓内读不到，需要时找平台方）；
> 本文是把「每个 profile 怎么落地」讲清楚的**操作手册**（founding 文档那句「追加 profile + **按其 checklist 补内容**」指的就是本文）。

## 0. 先记住三条事实（否则会做出「表面变更」）

1. **profile 是声明式开关 + 落地清单的索引，不是「加个字符串就自动有能力」。** `manifest.profiles`
   声明本模块启用哪些框架能力；能力真正生效靠你按本文对应小节把配套内容补齐（依赖包 / 数据源 / jobs / handle 范式）。
2. **平台侧目前只运行时消费 `stats-sandbox`**（据此自动注入 `ctx.stats`）。
   其余 profile 的字符串平台不读——它们的能力**完全靠模块自己接线**才成立。
3. **有的 profile 跨 G2 人工决策闸门、依赖平台/运维侧前置**（建 `forge_mart_<code>` 库、在平台
   `data_sources.json` 登记别名、配 jobs 调度）。这些**业务仓内够不到**：不得跳过、不得只改
   `manifest.profiles` 就报「完成」。属于此类的会在下面小节标 **⚠ 跨 G2 / 需平台侧前置**。

## 1. 通用流程

### 初始化时（建仓）

copier 的 `profiles` 问题按需选（逗号分隔，默认 `structured-query`）。生成后，对**每个所选 profile**
逐一按第 3 节对应小节的 4 步（声明 / 依赖 / 代码 / DoD）落地；标了 **⚠ 跨 G2** 的先补 G2 决策。

### 追加时（既有仓扩能力）

1. **判定是否跨 G2**：若涉及治理 / 向量化（`governance-etl` / `semantic-retrieval`），**先在
   `docs/decisions/` 落 G2 决策**（模板见**本仓** `docs/decisions/README.md`，建仓时已生成），
   确认建不建 `forge_mart_<code>` 产物库、同步 cron、由**平台运维建库**。不涉及则跳过本步。
   ⚠️ **G2 决策必须写死两件事**（模板里是必填栏，不是提醒文字）：① **权限承载列清单**——
   逐表列出，缺列平台启动期直接拒绝，返工要改迁移 + 重建表 + 全量重跑 embedding；
   ② **受列级管控字段的处置**——列级权限当前不作用于检索路径，详见本文 `semantic-retrieval`
   小节的权限边界。**评审要发生在申请建库之前**：`provision-mart` 是运维当场传口令、跑完即走
   的动作，不是「先建了再改」的东西。
2. **改声明**：在 `src/<pkg>/module.py` 的 `manifest.profiles` 追加该 profile 字符串。
   ⚠ 名称必须与本文一致——`profiles` 无平台白名单校验，写错**不报错**，只是能力不生效。
3. **补配套**：按第 3 节对应小节补 manifest 关联字段 / `data_sources` / 依赖包 / `jobs()` / `handle()` 范式。
4. **平台 / 运维侧前置（若小节标了）**：新数据源在平台 `data_sources.json` 登记、`forge_mart_<code>` 建库、
   jobs 调度——**业务仓外，需协调平台侧**。
5. **自检 DoD → 验证 → 发布**：`uv run pytest`、`uv run forge dev serve` 冒烟；bump `pyproject.toml` 版本，打 `vX.Y.Z` tag 发 wheel。

> ⚠️ **追加 ≠ 只加字符串**。`stats-sandbox` 接近「加字符串即可」；但 `semantic-retrieval` /
> `governance-etl` 必须走上面第 1、4 步，否则「声明了却不工作」。

## 2. profile 一览（速查）

| Profile | 提供的能力 | 依赖包 | 跨 G2 / 平台前置 |
|---|---|---|---|
| `structured-query` | NL→参数化 SQL / 报表模板 / 结果对拍 | `paxsz-forge-data` | 需登记 `data_sources.json` |
| `stats-sandbox` | 沙箱内统计 / 计数 / 排序 / 对比 | `paxsz-forge-sandbox` | 无（平台自动注入 `ctx.stats`） |
| `semantic-retrieval` | 向量化回填 job + pgvector 检索 + rerank（平台注入 `ctx.retrieval`） | `paxsz-forge-data` | **⚠ 跨 G2 + 建 mart 库 + 登记 + 平台配 embedding 服务** |
| `governance-etl` | 三目录治理 + 增量同步 + 清洗 job + 定时调度 | `paxsz-forge-governance` + `paxsz-forge-data` | **⚠ 跨 G2 + 建 mart 库 + jobs 调度** |
| `analysis-report` | 多步编排 + 引用溯源 + 报告生成 | `paxsz-forge-core`（`ctx.bus`） | 需 `dependencies` / `capability_deps` 装配期 DAG 校验 |
| `knowledge-qa` | 受控知识库检索（平台注入 `ctx.knowledge`，AgentNode 子树编译成标签过滤强制注入） | `paxsz-forge-core` | 需登记 `knowledge_bases.json` |

> API 签名一律以 [`02-sdk-reference.md`](02-sdk-reference.md) 与你 `uv sync` 到的 `forge-*` 源码为准，**勿臆造**；
> 权限 / 取数红线见 [`04-permissions-and-data-access.md`](04-permissions-and-data-access.md)。

## 3. 逐 profile 落地手册

### `structured-query`（直查结构化数据，最常用）

- **何时启用**：用 NL 直查 info/erp 的结构化表出结果 / 报表。几乎所有数据查询模块都含它。
- **声明**：`profiles` 含 `structured-query`；`manifest.data_sources` 声明用到的源别名；有权限管控字段时
  填 `manifest.field_mappings`（`别名 -> {协议权限字段 -> 物理列}`）；**要多表联查时**在对应
  `DataSourceRef` 上补 `tables` + `joins`（可连接表图，见下）。
- **依赖**：`paxsz-forge-data`（运行依赖）。
- **代码**：`handle()` 内经受控句柄取数 `df = ctx.data.fetch(QuerySpec.model_validate({...}))`
  （**同步调用、直接回 DataFrame，别 `await`**；DataScopeFilter 取数前阻断，红线见 04）；
  配合引导式交互填 `clarify_dimensions` / `analysis_dimensions` / `glossary`。
  取回来的列**不等于**该回给用户的列（自增 ID/权限承载列不外露、表名字段名不外露、数据之外要给分析）——见
  [09 答案呈现规范](09-answer-presentation.md)。
  > `.query(source, table, select=[...], where="...")` 是保留的单表简写。它的裸 `where` **不过列级
  > 白名单**（列级权限可被当 oracle 反推），故**新代码优先 `.fetch(spec)`**；`where` 每次调用打
  > `raw_where` 审计 flag，退役看遥测。
- **多表联查（混合模型）**：`spec.joins` 只能用 `manifest` 声明过的边——**你审过哪些连接，LLM 才能连
  哪些**。声明 `JoinEdge(left=..., right=..., on=[("customer_id", "id")], types=[...])`，越界即
  `JoinNotDeclared`；不声明 = 该源不支持 JOIN。让 LLM 组 spec 前先把
  `"\n\n".join(c.as_prompt() for c in ctx.data.describe())` 拼进提示词——同一张声明图既是白名单也是目录，
  LLM 于是不用猜。写法与那条「scope 进 ON、filter 进 WHERE」的非对称性见
  [04 · 多表 JOIN](04-permissions-and-data-access.md#多表-joininner--left)。
- **聚合下推（GROUP BY / HAVING）**：`select` 里的 `{"field": "amount", "agg": "SUM"}`、`group_by`、
  `having`、以及带 `agg` 的 `order_by`，都由框架编译成 SQL。**这不违反数字红线**——判据与写法见下面
  `stats-sandbox` 那条，以及 [04 · 聚合与分组](04-permissions-and-data-access.md)。
  两处最容易出事的：**聚合参数与投影列同权**（`AVG(salary)` 无权即 `ColumnNotPermitted`，因为分组键
  足够细时聚合就是投影）；**结果列名由框架生成**（`sum_amount` / `count_star`），`df[...]` 按它取。
- **平台前置**：`data_sources` 声明的别名**必须已在平台 `data_sources.json` 登记**，否则平台**拒绝启动**。
  行数上限 `FORGE_QUERY_MAX_ROWS`（默认 10000，**只作用于 `.fetch()`**）与相对时间时区
  `FORGE_QUERY_TIMEZONE`（默认服务器本地）由平台配置，模块不用管。
- **DoD**：`data_sources` 别名并集 = `db_description` 各表 `source` 并集；`field_mappings` 覆盖全部权限承载字段；
  业务过滤走结构化 `filter`（残留的裸 `where` 每条都确认过其引用列你有权 `select`）；日期区间用
  `{"$relative": ...}` 交框架算而非 LLM 自算；用到 JOIN 时每条边都在 `joins` 里声明过、复合关联列写全，
  且 LLM 组 spec 的提示词里带了 `describe()` 的目录；能用「已有列 + COUNT/SUM/AVG/MIN/MAX」表达完的
  聚合已下推 SQL（而不是把明细全量拉回来再算）；`forge dev serve` 冒烟取数通过。

### `stats-sandbox`（一切数字处理；数字红线落点）

- **何时启用**：需要任何统计 / 算术 / 计数 / 排序 / 对比 / 出图。**数字红线要求**：这类结果不得由 LLM 或
  `handle()` 内 Python 直算。
- **声明**：`profiles` 含 `stats-sandbox`——**就这一步**（这是最轻的 profile）。
- **依赖**：`paxsz-forge-sandbox`（运行依赖）。
- **代码**：`outcome = await ctx.stats.run(script, {"rows": df})`（`script` 可由 LLM 生成，数字在受限子进程内算）；
  出图 `yield Event.chart(**ctx.stats.to_chart(outcome, chart_type="bar", x_key="...", series_keys=[...]))`。
  **禁**在 `handle()` 里写 `sum/sorted/pandas` 聚合、**禁**让 LLM 直接给数字。
  沙箱产出的是**明细帧**（下钻数据集等要存下来再用的中间表）而非几个数时，用
  `ctx.stats.run(script, datasets, return_frames=True)` 从 `outcome.frames` 拿 DataFrame——**别**把帧拆成 records
  塞进 `result`（那条通道上限 20 万字符，迟早撞）。数据帧通道上限按**每次调用**计，见
  [04 · 拿回明细帧](04-permissions-and-data-access.md#拿回明细帧数据帧通道)。
- **⚠️ SQL 聚合不在禁止之列**（这条最容易被上一行误读成「所有聚合都得走沙箱」）：

  > 红线禁的是**谁产出数字**，不是**哪里出现算术**。禁的两件事没变：LLM 自己报数、`handle()` 里用
  > Python/pandas 直算。SQL 引擎与 `ctx.stats` 沙箱**同属确定性执行器**——同一份输入必得同一个数、
  > 过程可复现可审计，都不在禁止之列。
  > 分工判据：**这个聚合能否用「表里已有的列 + COUNT/SUM/AVG/MIN/MAX」表达完？**
  > 能 → **优先**下推 SQL（数据在 DB 侧就收敛，更快，也让更少的无关行离开数据库）；
  > 不能（同比环比、分档、加权、跨源）→ `ctx.stats` 沙箱。
  > 两条路通向同一条不变量：**LLM 只能引用执行器的产出，永远不许自己报数**——包括「顺手心算一下
  > 百分比」。

  下推写法（`structured-query` 的 `spec.group_by` / `having` / `agg`）见
  [04 · 聚合与分组](04-permissions-and-data-access.md)。
- **平台前置**：无。平台**按此 profile 自动注入 `ctx.stats`**；不声明则 `ctx.stats is None`。
- **DoD**：CHART / 分析事件里的每个数字都来自 `outcome.result` **或 SQL 聚合的结果列**；`handle()` 内
  无 Python 直算；chart spec 的 x/series 数字均来自确定性执行器的产物。

### `semantic-retrieval`（非结构化字段语义检索） ⚠ 跨 G2 + 需平台侧前置

> 📅 **本小节讲「声明什么、写什么代码」；整条链路的时序（谁在哪台机器上按什么顺序做，
> 上线要补哪几步，出问题查哪张表）见 [11 mart 库模块端到端时序](11-vectorization-and-governance.md)。**
> ⚠️ **本 profile 与 `governance-etl` 相互独立**：`vectorize` 的 `origin_table` 指向谁都行，
> 不要求它是治理产物——「源表已经够干净、只是有个长文本字段要语义检索」完全成立。

- **何时启用**：要对非结构化文本字段（如「到货质量问题」描述）做语义检索，而非精确 SQL 过滤。
- **⚠ 先过 G2**：在 `docs/decisions/` 落 G2 决策——判定要不要向量化、建 `forge_mart_<code>` 向量库、同步/向量化 cron；
  **建库由平台运维做**（业务仓够不到）。
- **声明**：`profiles` 含 `semantic-retrieval`；`manifest.data_sources` 增 `forge_mart_<code>` 向量源别名
  （向量库就是一个普通 PG 库，**别名与结构化源同一族**，不另起命名体系；启动期校验与 `ctx.data`/`ctx.retrieval`
  的别名白名单因此对它同样生效）。权限承载字段照常填 `manifest.field_mappings[<mart 别名>]`——
  值是**向量表上的物理列**（见下「权限透传硬约束」）。
  再加一条 `manifest.vectorize` 声明「哪张治理后表的哪些文本列 → 哪张向量表」：

  ```python
  vectorize=[VectorizeSpec(
      source="forge_mart_kb", vector_table="issues_vec", origin_table="issues",
      id_column="issue_id", text_columns=["defect_desc", "handling"],
      default_cron="30 2 * * *",
  )]
  ```

  **`vectorize` 是个列表，一条 spec = 一张向量表**。要单独检索的每个文本字段各写一条：

  ```python
  vectorize=[
      # 同一张源表的两个字段，各自成表 —— 用户问「有什么缺陷」和问「怎么处理的」各命中各的
      VectorizeSpec(source="forge_mart_kb", vector_table="issues_desc_vec", origin_table="issues",
                    id_column="issue_id", text_columns=["defect_desc"]),
      VectorizeSpec(source="forge_mart_kb", vector_table="issues_handling_vec", origin_table="issues",
                    id_column="issue_id", text_columns=["handling"]),
      # 另一张源表；cron 也可以各配各的
      VectorizeSpec(source="forge_mart_kb", vector_table="parts_vec", origin_table="parts",
                    id_column="part_id", text_columns=["spec_text"], default_cron="0 4 * * *"),
  ]
  ```

  约束只有一条：**同一 source 下 `vector_table` 不能重名**（`origin_table` 可以重复出现）。
  每条各自生成一张表、一个回填 job（`<模块编码>.vectorize:<向量表>`）、一份 cron。

  **一条 spec 里的多个 `text_columns` 是拼成一段 content、出一个向量**，不是分别向量化——
  那是「这几列合起来描述同一件事」时才该用的写法（如 `["defect_desc", "handling"]` 合起来
  才是一次完整的问题处置记录）。**判据：你希望用户的问题分别命中它们，就分表；希望它们作为
  一个整体被命中，就合进一条 spec 的 `text_columns`。** 检索时由你的 `handle()` 用
  `ctx.retrieval.search(..., table=...)` 选表——平台不替你选，也不跨表自动合并。

  **权限承载列不在这里重复声明**——平台从 `field_mappings[source]` 自动算出，喂给 DDL / 回填 SQL /
  启动期校验三处（同一信源，不会漂移）。**表达力边界是「单表 + 列拼接」**：复杂拼装靠分层，
  用 `governance-etl` 先把数据落成一张可直接向量化的干净表（含 content 源列 + 权限承载列），
  本声明只读它。声明表达不了的，答案是「加一步治理 ETL」，不是「加一个声明字段」。
- **依赖**：`paxsz-forge-data`（检索由平台注入，回填编排见 `forge_data.etl.run_vectorize_backfill`；签名查 02 / 源码）。
- **代码**：
  - `handle()` 检索：`hits = await ctx.retrieval.search(query, source="forge_mart_<code>", table="<向量表>")`
    （平台注入的受控句柄，pgvector 召回 + 本地 rerank 一步到位）。
    ⚠️ **检索前的 query 必须是自足的**：`request.query` 恒为用户原话（平台不替你消解指代），
    多轮里那句「那上个月呢」拿去算 embedding 毫无意义——**这是本 profile 与 `knowledge-qa`
    才有的必修课**（纯 `structured-query` 模块把历史塞进 messages 就够了，消解是模型的默认
    行为）。先用 `conversation_messages` 取历史让模型补全成独立问题，再拿补全后的那句去检索。
    见 [02 · 多轮上下文](02-sdk-reference.md#多轮上下文-forge_coreconversation)。**别自己 new `PgVectorIndex` /
    `EmbeddingClient`、别自己读 env**——绕开平台配置 = 绕开权限下推与检索审计。`ctx.retrieval is None`
    表示 profile 没声明或平台没配 embedding 服务，找平台侧解决，不要自造句柄。
  - **向量化回填不用你写**（`jobs()` 里**不要**有向量化 job）：它 100% 定型（扫需要 embed 的行 →
    embed → upsert），且恰好是**权限透传的落点**——自写就永远停在「依赖开发者记得 SELECT dept_id」。
    平台按 `manifest.vectorize` 生成回填 job（全局名 `<模块编码>.vectorize:<向量表>`，cron 可照常
    被平台侧覆盖），SELECT 与 upsert 自动带上 scope 列，源表删掉的行连带删向量。
    你的活是（若需要）用 `governance-etl` 把数据落成一张可直接向量化的表。
  - **建表 DDL 也由平台生成、也由平台执行**：`forge vectorize ddl` 在你仓里**只打印**（建表 + HNSW
    索引 + **每个 scope 列的 btree 索引**，scope 列已自动带上），真正建表是运维在服务器上跑
    `forge vectorize apply`（装配时由部署脚本自动执行）。**你不需要 Alembic 迁移，模板里也没有**
    ——旧口径「纳入你的 Alembic 迁移」承诺了一个不存在的机制，已被
    平台侧 2026-08-06 的决策推翻。
    **别手写向量表 DDL**——手写就等于把「scope 列该有哪些」又交回给人记。scope 列的 btree 是让
    planner 在窄权限查询上**有得选**（精确扫描 vs HNSW 续扫，按选择性自选）；没它就只剩 HNSW 一条路。
  - **增量靠 content hash，不需要水位列**：平台在向量表维护 `content_hash`，回填只挑「没有的」和
    「hash 对不上的」。新增/更新/**改了 `text_columns` 或 `separator`**（= content 变了）都会自动
    重嵌，不用你手动清表。
    **换 embedding 模型同样自动重嵌**：模型名混在 `content_hash` 里（`md5(<模型名> || content)`），
    换模型 = 全表 hash 变 = 下一轮回填全量重嵌，**零运维动作**。旧口径「须运维手动清空向量表」
    已被平台侧 2026-08-06 的决策推翻
    （此前的行为是：换模型不重嵌、不报错、静默返回垃圾结果）。
  - Embedding/Rerank **仅本地服务**（Qwen3-Embedding-8B / Qwen3-Reranker-8B），由平台按部署配置装配。
- **平台 / 运维前置**：建 `forge_mart_<code>` PG 库（含 pgvector 扩展 **>= 0.8.0**；向量表 DDL 用
  `forge vectorize ddl` 生成）；`forge_mart_<code>` 别名在平台 `data_sources.json` 登记（`type: postgres`），
  **并配 `write_user`/`write_password_env`**（回填 job 落数走它，缺则 job fail-closed）；平台须配
  `FORGE_EMBEDDING_BASE_URL`（缺则 `ctx.retrieval` 为 None、回填 job 也报错）、建议配
  `FORGE_RERANKER_BASE_URL`（缺则只召回不重排）；jobs 调度接入。这些都在平台侧，找平台方确认。
  **权限透传硬约束（平台启动期校验）**：向量表必须带齐权限承载列、不得跨权限维度预聚合——行级规则
  是在**向量表**上编译成 WHERE 的，规则引用的列不在表上即 fail-closed 报错（见 04）。
  平台启动时扫 `information_schema`，要求该 mart 库内**每张**向量表都带齐 `field_mappings[<mart 别名>]`
  的全部物理列，**缺列即拒绝启动**（`VECTOR_SCOPE_COLUMNS_MISSING`），不必等到首次检索才发现。
  故同一 mart 别名下的向量表**权限口径须一致**；无需管控的向量库别填 `field_mappings`。
  用了 `manifest.vectorize` 的模块还多一层：**声明了的向量表不存在也拒绝启动**（声明与现实矛盾）。
- **⚠️ 两个必须知道的权限边界**（详见 [04](04-permissions-and-data-access.md#语义检索semantic-retrieval)）：
  - **列级权限（`dataScope.column`）当前不作用于检索路径**（协议层语义空缺，平台侧待办、未定）。若本模块的**向量化字段受列级管控**，
    须在 G2 决策里显式处理：不向量化该字段，或按敏感度分表/分区把列级**降维成行级**
    （后者是向量库里唯一能真正下推的形态）。**别默认「跟 `.query()` 一样严」。**
  - **HNSW 近似检索 + 行级过滤 → 权限窄的用户会静默少召回**（安全不受影响）。服务端 pgvector
    >= 0.8.0 时平台自动下发 `hnsw.iterative_scan` 续扫补救；低于此版本只能告警降级。
  - **主子表规则（协议 v1.3）同样经 `row_scope_sql` 流入检索**：若 dataScope 对向量表的条件引用了
    子表字段、或向量表本身是 `inherit_parent` 子表，对应 `EXISTS(...)` 会随行级 WHERE 一并下推——那些子表/父表
    须在同一 mart 别名下真实存在（向量表通常已去规范化、无子表，故一般无感）。见 [04](04-permissions-and-data-access.md)。
- **DoD**：G2 决策已落盘；`forge_mart_<code>` 已建库并登记（含 `write_user`/`write_password_env`）、`SELECT extversion FROM
  pg_extension WHERE extname='vector'` >= 0.8.0；向量表 DDL 由 `forge vectorize ddl` 生成并进了迁移；
  回填 job 在 **jobs worker** 上跑通（`forge jobs run <编码>.vectorize:<向量表>`）；`jobs()` 里**没有**
  自写的向量化 job；检索经 `ctx.retrieval`（未绕开平台，`handle()` 内无裸 `PgVectorIndex`/`EmbeddingClient`）
  且结果经本地 rerank；权限承载列已随向量表落地——**平台起得来就是这一条的证据**（缺列拒启动），
  若启动报 `VECTOR_SCOPE_COLUMNS_MISSING` 即向量表缺列或声明的表不存在，按提示补列/迁移后重新回填；
  若日志出现 `vector_table_absent` 则表还没迁移或只读账号没 GRANT。
  **两条必须用「窄权限账号」实测**（管理员账号两条都测不出来）：① **安全**——无权数据检索不出来；
  ② **召回**——有权数据**捞得全**（同一问题下窄权限账号返回条数应接近 `top_n`，若远少于或为 0，
  即 HNSW 后过滤塌陷，查 pgvector 服务端版本）。向量化字段若受列级管控，G2 决策已给出处置。

### `governance-etl`（脏数据 / 大数据量需治理） ⚠ 跨 G2 + 需平台侧前置

> 📅 **本小节讲「声明什么、写什么代码」；建库/登记/首轮跑数这些平台侧步骤的时序见
> [11 mart 库模块的端到端时序](11-vectorization-and-governance.md)。**
> ⚠️ **本 profile 与 `semantic-retrieval` 相互独立**：只治理不向量化（治理后直接结构化取数）、
> 只向量化不治理（源表已经够干净，`vectorize` 直接读它）、两者都要——三种都成立。
> 别把治理当成向量化的必经前置。

- **何时启用**：源数据脏（编码不一致 / 大量空值 / 需标准化）或数据量大到直连不划算，需清洗治理后再查。
- **⚠ 先过 G2**：落 G2 决策——数据画像（内网执行、外传前人工审核）→ 治理必要性评估 → 建 `forge_mart_<code>` 治理库 + 同步策略。
- **声明**：`profiles` 含 `governance-etl`；`manifest.data_sources` 增 `forge_mart_<code>` 治理源别名。
- **依赖**：`paxsz-forge-governance`（`init_governance` / `profile_dataframe` / `guard_evaluate`，见 02）+ `paxsz-forge-data`。
- **代码**：`init_governance(...)` 建三目录治理脚手架；`jobs()` 注册增量同步 / 清洗 job（`JobBinding` + `default_cron`）；
  `profile_dataframe(df)` 出数据画像（只聚合特征、不含原始值）。
  - **句柄从 `JobContext` 取**：`run(ctx)` 里 `ctx.etl.read(<源别名>)` / `ctx.etl.write("forge_mart_<code>")`，
    编排用 `forge_data.etl.run_incremental_sync`。**别自己 new 连接、别自己读 env**（见 02）。
  - ⚠️ `ctx.etl` **不受权限过滤管辖**（ETL 期没有 AgentNode，系统级全量读写）——所以你的 SELECT
    **必须带上权限承载列**并原样落进 mart 表，那是查询期能施加行级过滤的唯一前提。
    漏了**平台启动期就拒绝**（`TABLE_SCOPE_COLUMNS_MISSING`，见下「平台前置」）。
  - **治理后表的建表 DDL 归你写，就写在这个 job 里**：`ctx.etl.write(...).execute("CREATE TABLE
    IF NOT EXISTS ...")` 放在 job 开头，每轮重放都是空操作、首轮自动建表。
    **不需要 Alembic，模板里也没有。**

    ```python
    async def _sync(self, ctx: JobContext) -> None:
        dst = ctx.etl.write("forge_mart_kb")
        dst.execute(
            "CREATE TABLE IF NOT EXISTS issues ("
            "  id text PRIMARY KEY, content text,"
            "  dept_id text,"          # ← 权限承载列：漏了平台启动期就拒绝
            "  ts timestamptz)"
        )
        ...
    ```

    **为什么建表归你、而向量表归平台**（两者刻意不同）：向量表结构是
    **定型**的（id/content/embedding/metadata + 权限承载列 + content_hash），平台能生成也能建；
    治理后表**每个模块都不一样**，平台无从生成。而它与填它的那条 SELECT 必须逐列一致——
    加一列要两处都改，放在同一个函数里最不容易漂。治理后表也**没有向量表那种时序硬约束**
    （平台启动不要求它已存在），所以由首轮 job 建出来完全来得及。
  - **本 profile 只写「治理」这一段**。要不要接向量化是**独立**的决定：治理后表可以直接被
    `ctx.data` 结构化取数，也可以再挂 `semantic-retrieval` 做语义检索。接的话，
    **向量化回填不用你写**——见 `semantic-retrieval` 小节。
- **平台 / 运维前置**：建 `forge_mart_<code>` 库并登记别名（运维一条命令：`forge data provision-mart
  --module <编码>`，建库 + 建一对专属账号 `forge_mart_<code>_ro`/`_etl` + 授权）；**该源配
  `write_user`/`write_password_env`**（否则 `ctx.etl.write()` fail-closed）；jobs 调度接入。
  **权限透传硬约束（平台启动期校验）**：`manifest.data_sources[].tables` 里声明的表若已存在，
  必须带齐 `field_mappings[<别名>]` 的全部物理列，**缺列即拒绝启动**（`TABLE_SCOPE_COLUMNS_MISSING`）。
  分级与向量表那侧同款，但有两处**刻意不同**：① 按你**声明的 tables** 校验而不是全库扫
  （mart 库里合法地有水位表 / 中间表，它们没有承载权限的义务）——**不声明就查不到，`tables` 是可选字段**；
  ② **表不存在只告警**（`declared_table_absent`），因为治理后表由 job 首轮跑时才建，启动时缺席是正常中间态。
  见 [04](04-permissions-and-data-access.md)。
- **DoD**：G2 决策已落盘；治理三目录建立；同步 job 的 cron / 水位已定；`forge_mart_<code>` 已登记且配了写连接；
  建表 DDL 写在 job 开头且是 `CREATE TABLE IF NOT EXISTS`（重放安全）；
  `data_sources[].tables` 声明了治理后表（**不声明则启动期校验查不到它**，等于自愿放弃这道闸）；
  权限透传满足（治理后表带齐 `field_mappings` 的物理列，**平台起得来就是证据**；
  启动报 `TABLE_SCOPE_COLUMNS_MISSING` 即缺列，补列后重跑 job）；落数 job 用 `forge jobs run <模块>.<job>`
  在 **jobs worker** 上验过（写句柄只在那个进程构造；平台 Console 任务页的「运行」按钮同样
  由 jobs worker 执行）。

### `analysis-report`（综合分析 / 经验总结）

- **何时启用**：一次问答要跨多个数据域 / 多步编排、产报告并给出引用溯源。
- **声明**：`profiles` 含 `analysis-report`；按用途配 `manifest.dependencies`（问答式转调的模块编码）
  与 `manifest.capability_deps`（要取的结构化能力）。跨域**数据**依赖配后者。
- **依赖**：`paxsz-forge-core`（`ctx.bus`）；具体数据能力仍靠所调模块的 profile。
- **代码**：两条通道分工明确（决策 2026-09-10，用法见 [02 · 结构化能力调用](02-sdk-reference.md)）：
  - **要数据做再加工** → `await ctx.bus.invoke(ctx, "<模块编码>", "<能力名>", {...})`，
    拿回带连接键、类型明确的 `CapabilityResult`，喂 `ctx.stats` 做跨域 join；
  - **要把别人的回答转给用户看** → `ctx.bus.call(ctx, "<模块编码>", request)` 透传事件流。

  ⚠️ **别用 `call` 去解析对方正文里的数字**：事件流里的表格按呈现规范是裁剪过的（连接键被砍、
  只给前 N 条），而从自然语言里「读出」数字的产出者是 LLM 的文本解析——撞数字红线。

  `Event.suggestions([...])` 给后续追问（每项 `{id,name,label,query}`，见 03「追问建议」）；引用随 assistant 记录落库（citations）。
  数字仍走 `ctx.stats`（需并启 `stats-sandbox`）。
- **平台前置**：两种依赖的边**一起**参与装配期 DAG 校验（防环，取并集）；`capability_deps` 指向的
  能力若目标模块不提供或版本对不上 → **隔离调用方模块**（目标未装载则只告警）。
  被调模块须在当前用户授权树内（运行期 fail-closed），且平台按被调方自己的 code 单独拉行列权限。
- **DoD**：两种依赖已按用途声明且装配无环；跨模块调用在授权白名单内；跨域数据走 `invoke` 而非
  解析正文；报告含引用溯源。

### `knowledge-qa`（知识库问答）

- **何时启用**：面向企业知识库（RAGFlow）做检索式问答。
  **粒度按检索域、不按 dataset**：一个模块声明 N 个知识库别名，别为每个库建一个仓
  （2026-07-17 起的口径）。
- **声明**：`profiles` 含 `knowledge-qa`；`knowledge_bases: [{alias, description}, ...]` 列出要检索的
  别名。别名须已在平台 `knowledge_bases.json` 登记——**启动期校验，缺则拒绝启动**。
- **依赖**：`paxsz-forge-core`（只用 `ctx.knowledge`，不直接依赖 forge-data）。
- **代码**：
  ```python
  # 单库一次调用（检索参数你想传几个传几个，下面是存量 Dify 壳应用那一整组）
  resp = await ctx.knowledge.retrieve(
      "pdc", question,
      page=1, page_size=15,
      similarity_threshold=0.1,
      vector_similarity_weight=0.3,
      top_k=1024,
      rerank_id="bge-reranker-v2-m3___OpenAI-API@OpenAI-API-Compatible",
      cross_languages=["zh", "en"],
  )
  # 或：一次调用跨多库（= 存量 Dify 壳应用的形态，5 个库同一次请求）
  resp = await ctx.knowledge.retrieve(["pdc", "qmc", "ts"], question, page_size=15)
  chunks = resp["data"]["chunks"]        # provider 原样响应（已过权限编译与回验）
  docs = await ctx.knowledge.list_documents("pdc", page=1, page_size=100)
  ```
  检索参数、答案合成、问题改写、域判断、文档列表 UX **全是业务、全在你这边**；平台只管权限与采集。
  ⚠️ **`question` 必须是自足的**：`request.query` 恒为用户原话（平台不替你消解指代），多轮里
  那句「那上个月呢」拿去检索毫无意义。这就是上面「问题改写在你这边」的具体所指——先用
  `conversation_messages` 取历史让模型补全成独立问题，再拿它去检索。
  见 [02 · 多轮上下文](02-sdk-reference.md#多轮上下文-forge_coreconversation)。
- **检索参数：全部透传，黑名单只有一个**。`**params` 原样进 RAGFlow 请求体，平台既不挑拣、也不设
  业务默认档——**唯独 `metadata_condition` 传了就拒绝**（那是权限，见下条）。即：文档里举 `page_size`
  的例子是**举例，不是白名单**；RAGFlow `POST /api/v1/retrieval` 认的参数你都能传，平台不用为此改代码。
  已确证可用的一组（= 存量 DSL 在用的）：

  | 参数 | 说明 |
  |---|---|
  | `page` / `page_size` | 分页。**扩召回池只能动 `page_size`**（见下「调参前必读」） |
  | `similarity_threshold` | 相似度下限，低于即丢 |
  | `vector_similarity_weight` | 向量分与词项分的混合权重 |
  | `top_k` | 参与向量召回的候选数。⚠️ **本部署上调大是空操作**（见下） |
  | `rerank_id` | RAGFlow 侧注册的重排模型名；**不传即不重排** |
  | `cross_languages` | 跨语言检索，会调 RAGFlow 配的 chat 模型做查询翻译 |
  **单库/多库也是你的选择**——框架两种都给：多库共争同一个 rerank 池（结果已全局排序、无需自己
  合并），单库则每库一个池、且**各库耗时才可观测**（多库调用时 `duration_ms` 是整次调用的，
  各库行共享它——RAGFlow 不分解到库）。拿真实数据评测哪种召回更好。多库要求诸别名同源
  （同 endpoint/key/标签 schema），不同源即 `ConfigError`。
- **权限（红线，你不用做、也做不了）**：平台把当前用户的 `privileges.dataScope[type=KB].directory`
  目录白名单编译成 `metadata_condition`（`permission_code start with <库内目录路径前缀>`）强制注入；
  **你传 `metadata_condition` 会被直接拒绝**（`KnowledgeScopeOverrideError`）。另外几条要知道：
  - **库级 fail-closed**：显式授权过的库才在访问范围内，其余剔除；本次请求的库全未授权 → `PermissionDenied`
    （请求不发）。**目录级 fail-open**：某库目录白名单为空 = 该库全部目录可访问。
  - **两条载体**：`privileges.dataScope[type=KB]` 优先，没有 KB 项时回落 `sub_agents`（INFO 至今只发这个）。
  - 未在 `manifest.knowledge_bases` 声明的别名 → `PermissionDenied`。
  - 被查库未在 `knowledge_bases.json` 配 `agent_code`（旧载体的库编码）→ `ConfigError`；
    用户有 KB 项、但未配 `directory_name`（协议库名）→ `ConfigError`。
  - 响应回验：越界 chunk/文档平台会丢掉——你拿到的 `chunks` 已是过滤后的，**别再自己拼过滤**。
    ⚠️ 平台侧回验只挡跨库（`dataset_id`）；库内目录过滤下推给 RAGFlow 服务端照做，别把「有回验」读成
    库内也有平台闸（决策 2026-07-18 候选 a）。
  ⚠️ 本路径的权限粒度是**文档目录标签**（`dataScope[type=KB].directory`），不是 `dataScope` 的行/列——
  `field_mappings` / `require_privileges` 在此不适用，别按 `.query()` 想当然。历史上曾走 AgentNode
  sub_agents 子树 + 执行暂缓，2026-07-18 换为 directory 白名单**替换**。
- **平台前置**：`knowledge_bases.json` 登记别名（provider / base_url / dataset_id / api_key_env），
  登记由平台方做。未配置 → `ctx.knowledge` 为 None。
- **观测（平台自动做）**：每次 `retrieve` 登记一条（别名/命中数/耗时/最高分）进 `audit_retrievals`
  侧表，Admin 统计页支持 `dimension=kb`。**零命中也会登记 `hits=0`**——这是「检索了没命中」，
  与「没检索」（`retrieval_count=0`）、「未知」（NULL）是三个不同状态。
- **引用溯源（两步，缺一步用户就看不到引用）**，详见
  [03 §引用溯源](03-events-and-streaming.md#引用溯源citation)：
  1. `yield Event.citation(ctx.knowledge.citations(kb, payload))` —— **别自己从 chunks 拼**：
     文件名前缀编着该文档的库内目录路径（= permission_code），helper 负责剥掉它；自己拼就是把
     权限标签随答案发给终端用户。剥离段数按库配（`knowledge_bases.json` 的 `name_tag_segments`，
     默认 5）。
  2. **把 `doc_id` 拼进喂给模型的切片正文，并在提示词里约定 `<sup>[doc_id]</sup>` 格式** ——
     角标是模型写出来的，平台不改 chunk 正文，模型看不见 id 就一个角标都不会出。
     ⚠️ 喂 `doc_name` 时用 helper 里那份**已剥离**的 `document_name`，别喂原始文件名（模型会抄进正文）。
- **预览链接**：`ctx.knowledge.document_url("pdc", document_id, ext="pdf")` 拼给浏览器直接打开的
  地址（**不经平台**，RAGFlow 自己鉴权）。别自己读环境变量拼——base_url 由平台持有。
  ⚠️ 渲染引用一般**不用**直接调它：`citations()` 已经把 `url` 拼好放进每条 item 了。
- ⚠️ **embedding / rerank 的模型执行全在 RAGFlow 侧，平台一个都不调**（与 `ctx.retrieval` 的关键分野）。
  **两侧现已是不同模型**：平台侧升到 Qwen3-Embedding-8B / Qwen3-Reranker-8B，RAGFlow 侧仍是
  bge-m3 / bge-reranker-v2-m3（下面 `rerank_id` 里的就是它）——本节出现的 bge-* 不是漏改。
  **这说的是「谁跑模型」，不是「你能传什么参数」**——`rerank_id` / `cross_languages` /
  `vector_similarity_weight` 这些参数你**照常传**（见上「检索参数」），平台原样转发；只是跑模型的
  是 RAGFlow 而不是平台：
  - 问题向量化用的是**该 dataset 在 RAGFlow 里配的** embedding 模型——请求里没这个参数，
    这一项是真的**传不了**（唯一一个）。
  - 重排靠 `rerank_id`，值是 **RAGFlow 侧注册的模型名**（现状
    `"bge-reranker-v2-m3___OpenAI-API@OpenAI-API-Compatible"`）；不传即不重排。
    ⚠️ 这个字符串是 **RAGFlow 部署侧的事实**，不是业务口味：它那边重新注册/改名，你这边硬编码的值
    就会失效（表现为报错或静默不重排）。别把它散抄进多处，收在模块自己的一个常量/配置里。
  - `cross_languages: ["zh","en"]` 会调 **RAGFlow 配的 chat 模型**做查询翻译。
  - 即：平台的 `FORGE_EMBEDDING_BASE_URL` / `FORGE_RERANKER_BASE_URL`（`ctx.retrieval` 那套）
    **与本 profile 无关**，配了也不会被用；**不用**为了 `knowledge-qa` 去配它们。
- **调参前必读**（RAGFlow v0.24.0 fork 的既知边界）：`RERANK_LIMIT ≈ 75`，故 `top_k` 调大是**空操作**，
  扩召回池只能动 `page_size`；DFS 修复只对无 `knn` 的纯文本查询生效，带向量的检索主路径
  per-shard IDF 问题仍在。
- **DoD**：别名已登记且启动校验通过；检索参数有依据（真实数据评测过，不是抄默认值）；
  零授权用户被拒而非看到全库；答案由本地模型合成；**引用溯源经 `ctx.knowledge.citations()` 产出
  （文件名不带权限标签前缀），且正文里的 `<sup>[doc_id]</sup>` 角标在调试台渲染成可点链接**
  ——角标不出即第 2 步没接上。

## 4. 新增/修改 profile 时（平台维护者）

如果你是在**平台仓**新增一个 profile 能力（而非在业务仓消费），**不要只改本文一处**——
profile 定义散落在多个落点，必须按平台仓 `docs/decisions/2026-07-11-能力profile指引与新增维护清单.md`
的「**新增 profile 落地维护清单**」逐项同步（founding 表、本文小节、模板 README/copier、平台消费点、部署文档等），
否则会出现「文档说有、代码没接」或各处定义漂移。
