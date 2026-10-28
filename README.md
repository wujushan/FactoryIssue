# 制程问题查询助手（FACTORY_ISSUE）

只读查询国内、巴西、海外的制程质量问题。可以按时间、加工厂、机型、物料、问题类型、状态、跟进部门或单号查问题单；点明某一域只查该域，没点明时三个域分别查再汇总。也可以打开一张单看处理进度、原因和改善措施，按机型、工厂、问题类型或时间段做汇总，或用缺陷现象描述查找类似问题。

> 本仓库是 DataForge2 平台的业务模块仓，基于平台模板生成。
> 开发必须遵循 **G 流程 v2**（见平台仓 docs/decisions/2026-07-03-目标架构与技术路线.md 第三节）。
> 工作指引见 [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md)（两文件内容同步）。

## G 流程进度（新会话续接入口，随开发实时更新）

- [x] **G1 业务逻辑梳理与落盘**：2026-10-23 完成（第四次复核清零并做完落盘精炼，见决策 2026-10-23「G1 四次复核修订」「G1 落盘精炼」）。口径在 `docs/2_landed/`（32 张表：31 张 `info`、1 张 `erp`），决策过程见 `docs/decisions/`，内网探测见 `docs/probes/`。业务方另有一批功能定义待投递，届时按同一流程补梳理。
  - 2026-10-24 梳理测试案例集时重新打开，新增 9 项当日全部关闭并落盘（决策 2026-10-24「测试案例梳理补充口径」），歧义清单再次清零。
  - 2026-10-27 写 G4a 设计时重新打开，新增 G59–G64 当日全部关闭并落盘（决策 2026-10-27「G4a 设计时补的口径」及其补记）。
  - 2026-10-28 按 G4a 评审修订时新增 G65、G66，当日关闭并落盘（同一决策的补记），歧义清单再次清零。
  - **带入后续阶段**：
    - 权限：待办任务表的固定行规则为业务表名 `IN` 两个（`privileges.md`，探测 C8 已核对），G4a 要给这条规则用到的字段写 `field_mappings`，否则取数会被拒；`docs/platform-feedback/` 两份待平台答复，实现前三种出错情形只靠权限平台承诺兜住（业务方已接受）。
    - G3：权限分支在自动化测试通道验不到，要构造权限数据的单元测试，加四类真实账号人工验收。正式数据里目前没有国内当前状态的 IQC 段、进行中的退货 / 退库段，也没有巴西只有雷亚尔费用的单，这几条规则要构造数据测。`2_landed` 里示例问题的单号只示意问法，场景按钮与测试用例的单号另从正式镜像挑。
    - G4a：每轮开头用 `ctx.data.describe()` 判域；`manifest.glossary` 按 `glossary.md` 同步，说法清单配置的内置默认值按 `topic_terms.md`，按词找时屏蔽不算的说法后两侧不拼接；各分析维度的图表样式（`Event.chart` 的 `style`）在设计里定；配图规则、一问多段、多轮沿用、Top N 与导出条数、表格列名已定（总述「回答怎么组织」「初步分析维度」，决策 2026-10-26「回答组织方式默认值」），其中 Top N、导出阈值与表格条数做成 `ctx.config` 可配。
    - G6：按 `privileges.md`「上线前核对」逐条核对。
- [x] **G2 数据现状勘察与治理决策**：2026-10-26 完成（独立评审修后，开发者复评通过）。决策见 `docs/decisions/2026-10-20-G2数据源与治理决策.md`（结构化直连 `info` / `erp`；文字查找建 `forge_mart_factory_issue`，每域 4 张表共 12 张，不设权限承载列），画像见 `docs/probes/`，评审见 `docs/reviews/`。
  - **带入后续阶段**：
    - 平台 / 运维：按 `docs/platform-feedback/2026-10-26-申请建产物库与上线前置.md` 在测试、正式两套环境建库、登记别名、配权限，必须早于装配含 mart 声明的版本；DBA 书面确认正式库版本与两张大表索引（首轮跑数前）；三份反馈待平台答复（都不阻塞上线）。
    - G3：检索评测集已落 `docs/testcases/检索评测集.md`（决策 2026-10-28）。分段的 `whole` / `field` / `field_split` 对比还没跑，默认仍是 `field_split`。
    - G4a / G4b：manifest 按决策「结论」写 `data_sources`（mart 别名的 `tables` 列 9 张）、`vectorize` 3 条（`metadata_columns` 不得后改）、`config_files`；mart 别名不填 `field_mappings`；查询流程按决策「查询期怎么用」「叙述原文的取数」细化；平台没把 `info` 默认库设为 `CoreINFO` 前，经 `info` 发出的 SQL 不用 `TRY_CONVERT` / `STRING_SPLIT`。
    - 上线：首轮跑数先全量重建，再 3 个向量化任务，再重启平台；统计行发回业务仓做决策「上线首轮核对」。
- [x] **G3 测试案例集**：2026-10-28 完成（开发者确认按现稿收口，案例集冻为 v1.0）。114 条 golden 在 `docs/testcases/golden/cases.json` 与 `golden/sql/`，人工手册在 `manual/首批.md`（33 条）和 `manual/其余.md`（81 条 + 权限 5 条）。权限 5 条不进 golden。检索评测集在 `docs/testcases/检索评测集.md`。验收写业务行为，不写调用次数和事件顺序。
  - **带入后续阶段**：
    - G5：`uv run python scripts/qa_test.py docs/testcases/golden/cases.json` 接真实测试数据；四类权限账号人工验收；分段 `whole` / `field` / `field_split` 的对比在平台测试环境跑，默认仍是 `field_split`。
    - 参考 SQL 里能下推到数据库的语句，评审或对拍时在 `info` 上抽查即可，不要求 114 份都先跑通。澄清和不取数的文件没有可执行查询。
- [ ] **G4a 技术设计定稿**（进行中）：草案 `docs/decisions/2026-10-27-模块技术设计.md`。2026-10-28 独立评审结论「修后再评」（`docs/reviews/2026-10-28-G4a模块技术设计独立评审.md`），已按评审修订，待复评。
- [ ] **G4b 编码实现**（未开始；分片、完成标准与进度见 `docs/handoffs/2026-10-27-G4b编码任务单.md`）：照 G4a 的设计写 manifest（intents/keywords/dependencies/**data_sources**/field_mappings）+ tools + 流式事件；**偏离设计要回改 G4a 文档**，别让代码与设计各说各话。data_sources 别名须与 G1 各表 `source` 并集一致、且平台侧 data_sources.json 已登记（否则平台拒绝启动）。**回给用户的内容按 [docs/dev/09 答案呈现规范](docs/dev/09-answer-presentation.md) 自检**：无意义字段（自增 ID 等）不返回、表名/字段名不外露、数据之外给合理分析、寒暄（「你好」「你能做什么」）报本板块能力与常用场景
- [ ] **G5 评测与对拍**：golden 集达标（`uv run python scripts/qa_test.py docs/testcases/golden/cases.json`，接真实测试数据）+ 数字口径对拍 + 人工测试手册验收
- [ ] **G6 发布**：tag 触发 CI 发 wheel → 平台装配仓 bump 版本 → 部署
  - **发布前必做**：按 `docs/2_landed/privileges.md`「上线前核对」，用权限平台准备的四类真实账号逐条核对权限配置（自动化测试通道不验权限）。

## 落盘文档目录规范（谁能改）

业务逻辑梳理与落盘阶段（G1）分工明确，两个目录的编辑权限互斥：

- **`docs/1_user_input/`——仅开发者可编辑，复杂输入的临时投递区**：业务逻辑较复杂时，开发者把需求清单、样例 SQL、数据字典、存储过程、业务方书面答复等**原始材料**按批次/主题建子目录放进来（如 `docs/1_user_input/<主题>/<日期>/`），供编程助手梳理。它**不是信源**：新材料与 `2_landed/` 冲突时以 `2_landed/` 为准、冲突列入 `docs/open-questions.md` 确认；**该批梳理完成后任何文档与代码都不再引用其中的文件**，素材随时可由开发者清理。编程助手只读、不改此目录。
- **`docs/2_landed/`——仅编程助手可编辑，业务逻辑与代码的唯一信源**：两条更新通道——简单内容开发者在对话里直接交代、助手直接改；复杂内容走 `1_user_input/` 投递、助手梳理确认后落盘。`2_landed/` **自包含、不外引**：有用信息（字段定义、口径算式、需逐字遵循的原文）复制落盘进来，不以 `1_user_input/` 或本机参考目录的文档作出处；日后发现有误直接改 `2_landed/`。开发者不直接改此目录，如需修订走「向编程助手提出 → 助手改 `2_landed/`」。

> 简言之：**开发者投递 `1_user_input/`（临时），编程助手产出 `2_landed/`（唯一信源）**。业务口径以 `2_landed/` 为准；实现与其冲突时先改 `2_landed/` 再改代码，并在 `docs/decisions/` 追加带日期的决策。

## 能力 Profile（本模块声明启用哪些框架能力）

本模块当前启用：**`structured-query,semantic-retrieval,governance-etl,stats-sandbox`**（在 `manifest.profiles` 声明，业务扩展 = 追加 profile + 按其 checklist 补内容）。`analysis-report` 按 G2 决策不启用：本助手不调用其他模块。

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
