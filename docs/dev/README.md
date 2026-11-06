# 业务模块开发者指南（DataForge2 SDK）

> 面向**业务模块仓的开发者**与**开发业务时使用的编程助手**。
> 本目录是 forge SDK 面向消费方的**权威文档**（single source of truth），随框架代码一起版本化：
> 你 `uv sync` 到的 `forge-*` 版本，对应的就是这一份文档的同版本内容。

## 我该按什么顺序读

**人类开发者**第一次接触，按序读 01 → 02 →（做数据查询就读 04）→ 05；**动手写 `handle()` 前扫一遍 09**（回给用户的东西该长什么样）；**要发版（发测试包 / 正式包）时读 08**；**要在真机测试数据上跑全量问答回归时读 10**；**模块要一个自己的 mart 库时（`governance-etl` 和/或 `semantic-retrieval`），先读 11 看清整条链路上哪几步不归你做**：

| # | 文档 | 什么时候看 |
|---|---|---|
| 01 | [从零上手 Getting Started](01-getting-started.md) | 建仓、装 SDK、跑起第一个模块、验证；**已建好的仓要[升级 SDK 版本](01-getting-started.md#升级-sdk-版本已建好的仓)也看这篇** |
| 02 | [SDK API 参考](02-sdk-reference.md) | 写代码时查 `paxsz-forge-core` / `paxsz-forge-data` / `paxsz-forge-sandbox` / `paxsz-forge-governance` 的类与函数签名（import 名仍是 `forge_core` 等）；**做多轮对话看[多轮上下文](02-sdk-reference.md#多轮上下文-forge_coreconversation)**（历史怎么取、谁负责指代消解）；末尾还有[怎么打日志](02-sdk-reference.md#打日志无需任何-sdk-api)（无需任何 API，平台自动打模块标签）；**被业务页面调用（自动审核、填单）看[任务面](02-sdk-reference.md#任务面-v2tasks-与-manifesttasks)** |
| 03 | [事件协议与流式输出](03-events-and-streaming.md) | `handle()` 里该 `yield` 什么、怎么流式回话 |
| 04 | [权限与受控取数](04-permissions-and-data-access.md) | 做**数据查询**模块必读：`field_mappings`、行/列权限、`ctx.data`、沙箱数字处理；任务要用超出用户权限的数据时读[任务级系统数据范围](04-permissions-and-data-access.md#任务级系统数据范围data_scopesystem) |
| 05 | [从 Dify 应用迁移](05-migration-from-dify.md) | 把现有 Dify 应用重建为 forge 模块的概念映射与步骤 |
| 06 | [forge CLI 速查（业务仓本地）](06-cli-reference.md) | `forge dev serve`（含本地能力桩）/ `modules` / `capabilities` / `jobs` / `vectorize` / `eval` / `data check`；**只收在你仓里跑得通的**，平台服务器运维命令不在此列 |
| 07 | [能力 Profile 指引](07-capability-profiles.md) | **初始化选 profile / 追加某 profile 能力时必读**：每个 profile 的声明/依赖/代码/平台前置/DoD |
| 08 | [发布与装配触发](08-release-and-assembly.md) | **要发版时必读**：发测试包→平台测试环境自动装配 / 发正式包→正式环境（平台仓管理员手动审核 gated）的完整流程与业务仓该做什么 |
| 09 | [答案呈现规范](09-answer-presentation.md) | **产出任何回给用户的内容前必读**：不返回无意义字段（自增 ID 等）、不许露表名/字段名、数据之外要给分析、寒暄要报本板块能力与常用场景 |
| 10 | [业务问答自动化测试](10-automated-testing.md) | **要在真实测试数据上跑全量问答回归时读**：`/test` 通道 API、api-key 申请、断言该锚在哪（结构化产物而非 LLM 措辞）、接 CI、能力签名分发与能力直调 |
| 11 | [mart 库模块端到端时序](11-vectorization-and-governance.md) | **做 `governance-etl` 或 `semantic-retrieval` 时读**（两者**相互独立**，只治理/只向量化/两者都要三种都成立）：A 轨业务仓侧 / B 轨平台侧的阶段顺序、每步的执行者、上线 checklist（**首轮跑数最容易漏**）、排查表。只讲时序，语义细节链到 04/06/07/08 |

**编程助手（Claude Code 等）**：开始为某业务模块写代码前，先读 02（API 契约，避免臆造签名）与 04（权限/取数红线），再按任务读 03/05；**写 `handle()` 产出回给用户的事件前读 [09](09-answer-presentation.md)**（那几条是行为规范，与 API 契约同等约束力——越线不会报错，直接变成用户看到的东西）；**涉及初始化或追加能力 profile 时先读 [07](07-capability-profiles.md) 对应小节**（按其分步清单办，勿只改字符串就当完成）；**涉及 `semantic-retrieval` / `governance-etl` 时再读 [11](11-vectorization-and-governance.md)**（那条链路有一半的步骤在业务仓外，且**不写向量化回填代码/不写向量表 DDL/不 new embedding 客户端；但**治理后表的建表 DDL 是你写的**，写在 ETL job 开头**——写了就是把权限透传从框架焊死退回成「开发者记得」）。所有代码示例都可直接照抄改写。

## 三条不可协商的红线（写任何代码前先记住）

1. **权限只走 `ctx.data`**：取数只能经平台注入的受控句柄 `ctx.data`（`DataAccessPort`），DataScopeFilter 由框架强制注入、取数前阻断、fail-closed。模块**拿不到裸连接、不得自己拼连接串直连数据库**。LLM 永不参与权限判断。见 [04](04-permissions-and-data-access.md)。
2. **数字处理只走沙箱**：一切统计/算术/计数/排序/对比**不得由 LLM 直接产出**（因 LLM 数字运算不可靠，**非因**禁其接触数据），必须经 `forge_sandbox.run_script` 在受限子进程里跑脚本。见 [04](04-permissions-and-data-access.md#沙箱数字处理)。
3. **模型只用本地服务**：LLM/Embedding/Rerank 仅本地 endpoint（Qwen-3.8-27B / Qwen3-Embedding-8B / Qwen3-Reranker-8B），禁外部模型 API。数据严格留内网；**线上本地模型（Qwen）允许接触真实数据**做解读/总结/初步分析，仅**外部 build-time 编程助手与外部模型 API** 可看 schema/业务逻辑但**严禁接触真实数据、严禁直连数据库**。

## 你的模块依赖什么

业务模块仓**只强依赖 `paxsz-forge-core`**（模块契约 + 事件协议 + 权限模型 + 本地模型客户端）。按能力 profile 追加：

| 需要的能力 | 加的包 | 装在 |
|---|---|---|
| 结构化取数 / 向量检索 | `paxsz-forge-data` | 运行依赖 |
| 数字处理（统计/算术） | `paxsz-forge-sandbox` | 运行依赖 |
| 数据治理脚手架 / 数据画像 | `paxsz-forge-governance`（可选装） | 运行依赖 |
| 本地起平台调试（dev harness + mini console） | `paxsz-forge-platform` | **dev 依赖** |

版本演进：模块仓 bump `paxsz-forge-core` 等版本 → `uv sync` 即获得框架改进（不 clone 平台仓、无「克隆冻结」）。

## 能力 Profile（模块声明启用哪些框架能力）

模块在 `manifest.profiles` 声明启用哪些能力 profile（建仓时 copier 询问，默认 `structured-query`）。
**业务扩展 = 追加 profile + 按其 checklist 补内容**——不必一次性上齐，也不会"因框架强制某能力而整个绕开框架"。
每个 profile「怎么初始化 / 怎么追加」的分步 checklist（声明/依赖/代码/平台前置/DoD）见
**[07 能力 Profile 指引](07-capability-profiles.md)**——追加能力前先读对应小节。

| Profile | 提供的能力 | 典型场景 |
|---|---|---|
| `structured-query` | NL→参数化 SQL / 报表模板 / 结果对拍 | 直查结构化数据（最常用） |
| `semantic-retrieval` | pgvector 检索 + rerank（平台注入 `ctx.retrieval`）；向量化回填按 `manifest.vectorize` 声明式生成，**你不写** | 非结构化字段的语义检索 |
| `governance-etl` | 三目录治理 + 增量同步 + 清洗 job + 定时调度 | 脏数据多 / 数据量大需治理 |
| `stats-sandbox` | 沙箱内统计 / 计数 / 排序 / 对比 | 一切数字处理（红线：LLM 不得直算） |
| `analysis-report` | 多步编排 + 引用溯源 + 报告生成 | 综合分析 / 经验总结 |
| `knowledge-qa` | 受控知识库检索（`ctx.knowledge`，权限由平台编译注入） | 知识库问答（一个模块可声明多个库别名） |

> 例：物料助手今天是 `structured-query` + `stats-sandbox`；将来查「到货质量问题」再追加
> `semantic-retrieval` 甚至 `governance-etl`，框架能力现成。profile 与依赖包的对应见上表「你的模块依赖什么」。

## 相关文档

- **发版流程（业务仓视角，你会用到）**：本目录 [08 发布与装配触发](08-release-and-assembly.md)
> 下面这几份都在**平台仓**，你仓里读不到；列在这里只为让你知道它们存在、需要时找平台方要。

- 建仓与 GitLab 配置（平台方视角）：「新建业务模块仓指引」
- 装配清单与触发链路的平台侧操作手册：「装配与触发链路指引」
- 平台 SDK 五包发布（与你发自己的 wheel 是两回事）：「发包指引」
- 体系架构（founding document）：「目标架构与技术路线」决策文档
