# 05 · 从 Dify 应用迁移到 forge 模块

面向要把现有 Dify 应用重建为进程内 forge 模块的开发者。**迁移不是着急的事**：存量 Dify 应用已经
经 Dify 出站适配器无缝接入平台在跑（P1），下线是逐个来的（P6）——每重建好一个、验收达标，才下线对应
的 Dify 应用。本文讲「重建」这一步的概念映射与流程。

## 两种状态先分清

| | 现状（P1，已在跑） | 迁移目标（P6，逐个做） |
|---|---|---|
| 形态 | Dify 应用 + 平台的 **Dify 出站适配器**（远程模块） | 进程内 **forge 模块**（`ForgeModule`） |
| 授权 | AgentNode 经 `inputs.sub_agents` 注入 Dify | 平台直接注入 `ctx.agent_node` |
| 取数 | Dify 内部逻辑 | `ctx.data`（DataScopeFilter 强制） |
| 数字处理 | Dify 内部 | `forge_sandbox.run_script` |
| 你要做的 | **什么都不用做**（配置即接入） | 按 G 流程 v2 重建 |

所以：**迁移 = 用 forge SDK 把某个 Dify 应用的业务能力重写为一个 `ForgeModule`**，跑通验收后下线该 Dify 应用。

## 概念映射表

| Dify 概念 | forge 对应 | 说明 |
|---|---|---|
| 一个 Dify 应用 | 一个 `ForgeModule`（+ 一个业务模块仓） | 一个应用 = 一个模块 = 一个 `manifest.code` |
| 应用的提示词/意图 | `manifest.intents` / `keywords` | 路由素材。**语义判定吃 `name`+`description`+`intents`**，`keywords` 只是分类器弃权时的兜底（决策 2026-09-03）——描述与示例问题写好比堆关键词管用 |
| 入口路由 / sub_agents | 平台一次性路由 + `AgentNode` 授权树 | 路由已拍平；树只作授权白名单 |
| 工具 / 工作流节点 | `handle()` 里的普通 Python + `ctx.data` / `run_script` / `ctx.llm` | 编排逻辑变成代码 |
| 知识库检索 | `forge_data.retrieve`（`semantic-retrieval` profile） | 现状知识库壳应用仍走 Dify 适配器，RAGFlow KnowledgeProvider 后置到 P6 |
| LLM 节点 | `ctx.llm.chat` / `.chat_stream`（本地模型） | 红线：仅本地 endpoint |
| 流式输出 | `yield Event.*`（SSE 事件协议） | 见 [03](03-events-and-streaming.md) |
| 会话 conversation_id | 平台是唯一源 | 历史归 forge 自有库；迁移用 `forge migrate dify-history` |
| 定时任务 | `ForgeModule.jobs()` → `JobBinding` | 平台 jobs worker 调度 |

## 迁移步骤（对齐 G 流程 v2）

从模板建仓（[01 · 上手](01-getting-started.md)）后，按 G 流程推进。**G1 是强制第一步**，未过闸门 guard hook 硬拦编码：

1. **G1 业务逻辑梳理与落盘** → `docs/2_landed/`：把该 Dify 应用的业务口径落成唯一信源。必备 `db_description/db_[库]_[schema]_[表].md`（字段权威源，一表一文件；同构分库/动态分表按表族只写一个文件）+ `business_description.md`。清零 `docs/open-questions.md` 或显式放行（建 `docs/.g1-cleared`）。**只梳字段/逻辑，不做技术决策。**
2. **G2 数据现状勘察与治理决策**：内网跑数据画像（`forge_governance.profile_dataframe`，只出聚合特征、外传前人工审核）→ 评估治理必要性 → 决策落 `docs/decisions/`。脏数据多/数据量大才装 `paxsz-forge-governance`。
3. **G3 测试案例集** → `docs/testcases/`：种子问题 → 编程助手扩展，每条附参考 SQL / 预期工具调用（自动化 golden 集 + 人工测试手册）。
4. **G4 编码实现**：写 `manifest`（intents/keywords/dependencies/**field_mappings**）+ `handle()` 事件流。取数走 `ctx.data`、数字走沙箱、检索走 `retrieve`。见 [02](02-sdk-reference.md) / [04](04-permissions-and-data-access.md)。
5. **G5 评测与对拍**：golden 集达标 + **数字口径与原 Dify 应用对拍**（同问题同答案）+ 人工测试手册验收。
6. **G6 发布**：打 `vX.Y.Z` tag → CI 发 wheel → 平台按 `assembly.toml` 装配更新 → 部署。完整流程见 [08 发布与装配触发](08-release-and-assembly.md)。验收达标后**下线对应 Dify 应用**。

## 迁移时容易踩的坑

- **别把权限逻辑搬进 handle**：Dify 里可能有「按部门过滤」的手写逻辑；forge 里这属于 `privileges`，由 `ctx.data` 自动施加，你只需在 `field_mappings` 里把协议字段映射到物理列。LLM/代码都不做权限判断。
- **别让 LLM 直接给数字**：Dify 提示词里「统计/汇总/排序」若是丢给模型算的，迁移时必须改成沙箱脚本，否则违反红线且不可复现。
- **conversation_id 不要自己造**：平台是唯一源，`ModuleRequest.conversation_id` 已给。历史迁移用 `forge migrate dify-history`（默认 dry-run、仅内网、保留 conversation_id 不变量）。
- **知识库先别急着自建检索**：现状知识库壳应用统一走 Dify 适配器；迁到 `knowledge-qa` 模块（`ctx.knowledge`）是 P6 的事。平台侧（受控检索句柄 + 别名族 + 权限编译 + 检索观测）已就绪，见 [07](07-capability-profiles.md#knowledge-qa知识库问答)；届时是**一个 KB 模块声明多个库别名**，不是一库一模块。
- **通用助手（GENERAL_ISSUE）暂不实现**：翻译/写作/代码等纯 LLM 请求为低优先待办，不在首批迁移范围（平台侧已记为低优先待办）。

## 迁移完成的判据

- golden 集通过率达标 + 数字口径与原应用对拍一致；
- 人工测试手册验收通过；
- 权限 fail-closed 回归通过（越权查询被拒、无权列不出、无权向量不出库）；
- 平台正式环境按装配清单上线该模块 → 下线对应 Dify 应用。
