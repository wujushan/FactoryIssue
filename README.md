# 制程问题查询助手（FACTORY_ISSUE）

只读查询国内、巴西、海外的制程质量问题。可以按时间、加工厂、机型、物料、问题类型、状态、跟进部门或单号查问题单；点明某一域只查该域，没点明时三个域分别查再汇总。也可以打开一张单看处理进度、原因和改善措施，按机型、工厂、问题类型或时间段做汇总，或用缺陷现象描述查找类似问题。

> 本仓库是 DataForge2 平台的业务模块仓，基于平台模板生成。
> 开发必须遵循 **G 流程 v2**（见平台仓 docs/decisions/2026-07-03-目标架构与技术路线.md 第三节）。
> 工作指引见 [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md)（两文件内容同步）。

## G 流程进度（新会话续接入口，随开发实时更新）

- [ ] **G1 业务逻辑梳理与落盘**：2026-10-20 完成（含当天补定的 PN 口径、订单号与 CAR 编号反查、通用筛选规则、料号与 PN 编码同一套）。口径在 `docs/2_landed/`（29 张表：28 张 `info`、1 张 `erp`），清单里的 G22–G24 属 G2，决策过程见 `docs/decisions/`，探测见 `docs/probes/`。业务方另有一批功能定义待投递，届时按同一流程补梳理。
  - **重新打开（2026-10-20）**：G29 提议扩充比对范围（改动 G10 已落盘口径），待业务方答复原则并跑探测 `docs/probes/2026-10-20-比对范围扩充探测说明.md` E1–E5（正式镜像）。
  - **带入后续阶段**：
    - G2：类似问题怎么比对（关键词还是语义检索）、富文本清洗放在哪、要不要建 `forge_mart_factory_issue`；如建 mart，每张单要带所属域、可按域过滤，CAR 报告正文不进检索文本；海外附件只能从单上登记的 ID 取。确认平台 `data_sources.json` 已登记 `info`、`erp`。
    - 权限：给权限平台配待办任务表的固定行规则前，先跑探测 C8；`docs/platform-feedback/` 两份待平台答复，实现前三种出错情形只靠权限平台承诺兜住（业务方已接受）。
    - G3：权限分支在自动化测试通道验不到，要构造权限数据的单元测试，加四类真实账号人工验收。
    - G4a：每轮开头用 `ctx.data.describe()` 判域；`manifest.glossary` 按 `glossary.md` 同步；各分析维度的图表样式（`Event.chart` 的 `style`）在设计里定，「加工厂」「跟进部门」的「单数与未结案数」不能直接堆叠（未结案含在单数里，会重复计数），要堆叠就拆成「已结案 / 未结案」两段，否则用并列柱。
    - G6：按 `privileges.md`「上线前核对」逐条核对。
- [ ] **G2 数据现状勘察与治理决策**：数据画像（内网执行，聚合统计特征，外传前人工审核）→ 治理必要性评估报告 → 决策落盘 `docs/decisions/`。**判定是否需要治理/向量化**：原始结构化取数一律直连 info/erp（只读热备副本），仅当需数据治理或非结构化字段向量化时才建 `forge_mart_<模块编码>` 产物库并启用 `governance-etl`/`semantic-retrieval`（模板见 `docs/decisions/README.md`）。**建 mart 就必须在决策里写死两件事**：① 权限承载列清单（缺列平台直接拒绝启动，返工要重建表 + 重跑 embedding）；② 受列级管控字段的处置（列级权限当前不作用于检索路径）。**评审必须在申请建库之前**——建库是运维当场传口令、跑完即走的动作
  - **进行中（2026-10-20）**：决策草案 `docs/decisions/2026-10-20-G2数据源与治理决策.md`（结构化直连；文字查找建 `forge_mart_factory_issue`，每域文字表 + 分段表 + 向量表、不设权限承载列；按字段分段向量化；「涉及某现象」走关键词与语义两路）。待：
    - 画像 `docs/probes/2026-10-20-G2数据画像探测说明.md`：P0、F1–F3、F5 已在正式镜像库 `ai-info` 跑完（清洗必要、三域都是中文、每单都有比对文字；内嵌图片占叙述文字约 98%，单值最长约 4,800 万字）；F6、F7 已在 SQL Server 开发库跑完（两张大表有索引，直连；SQL Server 2019，但 `info` 库兼容级别 100）；F8 已跑（指纹、分页可用；`info` 为当前库时 `TRY_CONVERT` / `STRING_SPLIT` 不可用，G4a 约束），画像全部完成，可以评审；DBA 确认正式库版本与索引一致、平台告知 `info` 连接的默认库（建议 `CoreINFO`），都不阻塞评审；
    - 业务方答复 `docs/open-questions.md` G22–G24、G29，G24 附同义说法清单，G29 附探测 E1–E5 结果（未决期间 guard 拦 src/）；
    - 平台答复 `docs/platform-feedback/` 的「切块后按业务记录限定与去重」「查询侧缺少任务说明」「治理任务缺少大模型与重排句柄」（都不阻塞）；「候选范围限定」已实现，本仓已升到 core 0.3.6 / data 0.3.1。
    - 齐了再评审，评审通过才申请建库。
  - **带入 G3**：检索评测集（非接、音频、花屏等主题问句 + 业务方确认的应命中单），用来定分段规则，见决策「检索评测」。
- [ ] **G3 测试案例集**：种子问题集 → 编程助手扩展 → `docs/testcases/`（每条附参考 SQL/预期工具调用；自动化 golden 集 + 人工测试手册双产物）。golden 集用 `scripts/qa_test.py` 经平台 `/test` 通道在真实测试数据上跑，格式与断言原则见 [docs/dev/10](docs/dev/10-automated-testing.md)
- [ ] **G4a 技术设计定稿**：落 `docs/decisions/YYYY-MM-DD-模块技术设计.md`（模板见 `docs/decisions/README.md`）——manifest 草案 + **`field_mappings` 逐列锚定**（协议权限字段 → 物理列；缺失 fail-closed 拒查、锚错列即越权，这是最该被人看一眼的地方）+ `handle()` 编排与事件序列 + SQL/沙箱边界 + 错误与降级。纯 `structured-query` 模块几十行足够；带 `governance-etl`/`semantic-retrieval`/`analysis-report` 的必须独立成文
- [ ] **G4b 编码实现**：照 G4a 的设计写 manifest（intents/keywords/dependencies/**data_sources**/field_mappings）+ tools + 流式事件；**偏离设计要回改 G4a 文档**，别让代码与设计各说各话。data_sources 别名须与 G1 各表 `source` 并集一致、且平台侧 data_sources.json 已登记（否则平台拒绝启动）。**回给用户的内容按 [docs/dev/09 答案呈现规范](docs/dev/09-answer-presentation.md) 自检**：无意义字段（自增 ID 等）不返回、表名/字段名不外露、数据之外给合理分析、寒暄（「你好」「你能做什么」）报本板块能力与常用场景
- [ ] **G5 评测与对拍**：golden 集达标（`uv run python scripts/qa_test.py docs/testcases/golden/cases.json`，接真实测试数据）+ 数字口径对拍 + 人工测试手册验收
- [ ] **G6 发布**：tag 触发 CI 发 wheel → 平台装配仓 bump 版本 → 部署
  - **发布前必做**：按 `docs/2_landed/privileges.md`「上线前核对」，用权限平台准备的四类真实账号逐条核对权限配置（自动化测试通道不验权限）。

## 落盘文档目录规范（谁能改）

业务逻辑梳理与落盘阶段（G1）分工明确，两个目录的编辑权限互斥：

- **`docs/1_user_input/`——仅开发者可编辑，复杂输入的临时投递区**：业务逻辑较复杂时，开发者把需求清单、样例 SQL、数据字典、存储过程、业务方书面答复等**原始材料**按批次/主题建子目录放进来（如 `docs/1_user_input/<主题>/<日期>/`），供编程助手梳理。它**不是信源**：新材料与 `2_landed/` 冲突时以 `2_landed/` 为准、冲突列入 `docs/open-questions.md` 确认；**该批梳理完成后任何文档与代码都不再引用其中的文件**，素材随时可由开发者清理。编程助手只读、不改此目录。
- **`docs/2_landed/`——仅编程助手可编辑，业务逻辑与代码的唯一信源**：两条更新通道——简单内容开发者在对话里直接交代、助手直接改；复杂内容走 `1_user_input/` 投递、助手梳理确认后落盘。`2_landed/` **自包含、不外引**：有用信息（字段定义、口径算式、需逐字遵循的原文）复制落盘进来，不以 `1_user_input/` 或本机参考目录的文档作出处；日后发现有误直接改 `2_landed/`。开发者不直接改此目录，如需修订走「向编程助手提出 → 助手改 `2_landed/`」。

> 简言之：**开发者投递 `1_user_input/`（临时），编程助手产出 `2_landed/`（唯一信源）**。业务口径以 `2_landed/` 为准；实现与其冲突时先改 `2_landed/` 再改代码，并在 `docs/decisions/` 追加带日期的决策。

## 能力 Profile（本模块声明启用哪些框架能力）

本模块当前启用：**`structured-query,semantic-retrieval,governance-etl,stats-sandbox,analysis-report`**（在 `manifest.profiles` 声明，业务扩展 = 追加 profile + 按其 checklist 补内容）。

> **初始化选 profile / 追加某 profile 能力前，先读 [docs/dev/07-capability-profiles.md](docs/dev/07-capability-profiles.md)** 的对应小节，按其「声明 / 依赖 / 代码 / 平台前置 / DoD」分步办。⚠️ 追加 ≠ 只加字符串：`semantic-retrieval` / `governance-etl` 跨 G2 决策、需平台侧建 `forge_mart_<模块编码>` 库并登记数据源，**不得跳过、不得只改字符串就报完成**。

各 profile 含义：

| Profile | 提供的能力 | 典型场景 |
|---|---|---|
| `structured-query` | NL→参数化 SQL / 报表模板 / 结果对拍 | 直查结构化数据（最常用） |
| `semantic-retrieval` | pgvector 检索 + rerank（平台注入 `ctx.retrieval`）；向量化回填按 `manifest.vectorize` 声明式生成，**你不写** | 非结构化字段的语义检索 |
| `governance-etl` | 三目录治理 + 增量同步 + 清洗 job + 定时调度 | 脏数据多 / 数据量大需治理 |
| `stats-sandbox` | 沙箱内统计 / 计数 / 排序 / 对比 | 一切数字处理（红线：LLM 不得直算） |
| `analysis-report` | 多步编排 + 引用溯源 + 报告生成 | 综合分析 / 经验总结 |
| `knowledge-qa` | 受控知识库检索（`ctx.knowledge`，权限由平台编译注入） | 知识库问答（一个模块可声明多个库别名） |

## 开发者文档（SDK 权威文档，建仓时已落盘）

[docs/dev/](docs/dev/) 是 forge SDK 面向消费方的权威文档快照（建仓时从平台仓落盘、随本仓版本化）。
**在本仓工作的开发者与 AI 编程助手写代码前先读这里**，勿凭记忆臆造 API/权限规则：

| # | 文档 | 什么时候看 |
|---|---|---|
| 01 | [docs/dev/01-getting-started.md](docs/dev/01-getting-started.md) | 建仓、装 SDK、跑起第一个模块、验证；**[升级 SDK 版本](docs/dev/01-getting-started.md#升级-sdk-版本已建好的仓)**（要带 `--upgrade-package`，光 `uv sync` 升不动）也在这篇 |
| 02 | [docs/dev/02-sdk-reference.md](docs/dev/02-sdk-reference.md) | 写代码时查 `paxsz-forge-core`/`paxsz-forge-data`/`paxsz-forge-sandbox` 的类与函数签名（import 名仍是 `forge_core` 等） |
| 03 | [docs/dev/03-events-and-streaming.md](docs/dev/03-events-and-streaming.md) | `handle()` 里该 `yield` 什么、怎么流式回话 |
| 04 | [docs/dev/04-permissions-and-data-access.md](docs/dev/04-permissions-and-data-access.md) | 做**数据查询**模块必读：`field_mappings`、行/列权限、`ctx.data`、沙箱数字处理 |
| 07 | [docs/dev/07-capability-profiles.md](docs/dev/07-capability-profiles.md) | **初始化选 / 追加能力 profile 时必读**：每个 profile 的声明/依赖/代码/平台前置/DoD |
| 09 | [docs/dev/09-answer-presentation.md](docs/dev/09-answer-presentation.md) | **产出回给用户的内容前必读**：无意义字段（自增 ID 等）不返回、表名字段名不外露、数据之外要给分析 |
| 10 | [docs/dev/10-automated-testing.md](docs/dev/10-automated-testing.md) | **G3/G5 跑全量问答回归时必读**：`/test` 通道 API、api-key 怎么申请、断言该锚在哪（结构化产物而非 LLM 措辞） |
| 11 | [docs/dev/11-vectorization-and-governance.md](docs/dev/11-vectorization-and-governance.md) | **做 `governance-etl` 或 `semantic-retrieval` 时必读**：两者可独立启用；业务仓侧 / 平台侧时序、执行者与上线 checklist（含首轮跑数） |
| 05/06/08 | [docs/dev/README.md](docs/dev/README.md) | Dify 迁移、forge CLI 速查、发版与装配触发 |

## 快速开始

```bash
uv sync                              # 安装依赖（本模块 editable + forge SDK）
python scripts/install_hooks.py      # ★ 每个 clone 装一次：推 v* tag 前本地校验版本一致性
uv run pytest                        # 测试
uv run forge dev serve               # dev harness：本地迷你平台（自动授权本模块），默认 127.0.0.1:8090
uv run forge dev serve --port 8123   # 指定运行端口（--host 可改绑定地址）
# 验证（把 8090 换成你实际使用的端口）：
# curl -N -X POST http://127.0.0.1:8090/v2/chat -H 'Content-Type: application/json' \
#   -d '{"query":"测试", "user_id":"dev", "target":"FACTORY_ISSUE"}'
```

发版（发测试包 / 正式包）：

```bash
uv run forge release --alpha         # 预发布 → 平台测试环境；版本号不用写（a1→a2→a3 自动接续）
uv run forge release 0.1.0           # 正式版（须在 main 上）→ 平台正式环境，待管理员确认装配
```

> **`pyproject.toml` 里永远只写正式版号**（如 `0.1.0`）——它就是预发布的基线；预发布号只存在于
> tag 指向的那个 commit 里，不进任何分支 —— 命令把 bump 提交做在 detached HEAD 上，跑完自动切回，
> 你的分支纹丝不动。
> tag 版本必须与 `pyproject.toml` 版本一字不差（CI 的 `guard-tag-version` 会拦），正式版还必须打在
> main 上（`guard-tag-on-main`）。用上面这条命令就不用操心这些。
> 完整版本号规则见 [docs/dev/08-release-and-assembly.md](docs/dev/08-release-and-assembly.md)。

## 红线（不可协商）

- LLM/Embedding/Rerank 仅本地服务；线上本地模型（Qwen）允许接触真实数据做解读/分析，仅外部 build-time 编程助手与外部模型 API 可看 schema/业务逻辑但严禁接触真实数据、严禁直连数据库。
- 数据权限走 DataScopeFilter 取数前阻断（fail-closed），LLM 永不参与权限判断。
- 一切数字处理（统计/算术/计数/排序）走脚本/沙箱，禁止 LLM 直算（LLM 数字能力不可靠，非因禁其接触数据）。
- 回给用户的内容里不出现数据库表名/字段名，也不出现自增 ID 一类对用户无意义的标识；数据之外要给合理分析（用户明说只要数据除外）——见 [docs/dev/09-answer-presentation.md](docs/dev/09-answer-presentation.md)。
- `.env` 永不入库；业务口径与实现冲突时，先改 `docs/2_landed/` 再改代码。
