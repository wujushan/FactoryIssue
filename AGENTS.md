# AGENTS.md — 制程问题查询助手 工作指引

> 本文件与 [CLAUDE.md](CLAUDE.md) 内容保持一致（同一规则源），修改任一文件时必须同步另一文件。

## 项目一句话

制程问题查询助手（模块编码 FACTORY_ISSUE）：只读查询国内、巴西、海外的制程质量问题。可以按时间、加工厂、机型、物料、问题类型、状态、跟进部门或单号查问题单；点明某一域只查该域，没点明时三个域分别查再汇总。也可以打开一张单看处理进度、原因和改善措施，按机型、工厂、问题类型或时间段做汇总，或用缺陷现象描述查找类似问题。。DataForge2 平台业务模块仓。

## 新会话起步导航

1. **续接入口**：[README.md](README.md) 的「G 流程进度」——当前阶段、下一步都在这里，完成任一 G 阶段后必须更新。
2. **业务口径唯一信源**：[docs/2_landed/](docs/2_landed/)（`business_description.md` 等）。任何业务规则、口径、表关联以此为准；实现与其冲突时**先改 2_landed 再改代码**，并在 docs/decisions/ 追加带日期的决策记录。
3. **字段权威源**：[docs/2_landed/db_description/](docs/2_landed/db_description/)（一表一文件 `db_[database]_[schema]_[table].md`；同构分库/动态分表按**表族**只写一个文件，见该目录 README），勿凭字段名臆测。
4. **歧义清单**：[docs/open-questions.md](docs/open-questions.md)——发现业务歧义/缺口/冲突时立即追加并向业务方确认，G1 清单未清零不得开始写 src/（guard hook 硬拦，显式放行 = 创建 `docs/.g1-cleared`）。
5. **SDK 权威文档（写代码前必读）**：[docs/dev/](docs/dev/)——`02-sdk-reference.md`（API 契约，勿臆造签名）与 `04-permissions-and-data-access.md`（权限/受控取数红线）编码前必读；**产出回给用户的内容前读 `09-answer-presentation.md`**（答案呈现规范：无意义字段不返回、表名字段名不外露、数据之外给分析、寒暄报本板块能力）；建仓/事件流/Dify 迁移/CLI 见 `01`/`03`/`05`/`06`，**初始化选 / 追加能力 profile 见 `07`**；**写/改 `docs/testcases/golden/` 用例集前读 `10-automated-testing.md`**（断言锚在结构化产物 `tables`/`module` 上，别锚在 LLM 措辞上）。此为建仓落盘的快照，随 `uv sync` 的 SDK 版本演进。

## 平台 SDK 协作原则

- 发现平台 SDK **缺少业务所需能力**时，优先整理需求并向平台仓提出；只有平台明确无法满足后，才回到业务仓评估自行实现或其他替代方案，不要一开始就在业务仓绕开平台能力。
- 发现平台 SDK **Bug** 或 `docs/dev/` **开发者文档描述错误**时，及时向平台仓反馈，不在业务仓静默打补丁或沿用错误口径。
- 平台仓同意实施优化变更后，等待其发布对应 SDK 版本，并明确提醒业务开发者先升级相关 `paxsz-forge-*` 依赖、执行 `uv sync`，再继续依赖该变更的业务开发。
- 需要向平台仓沟通需求或问题时，不只给一句结论；至少说明**业务场景、当前 SDK/文档行为、缺口或复现方式、期望行为、影响范围**，必要时附最小示例，方便业务开发者与平台开发者准确传递和确认。

## 落盘文档目录规范

- `docs/1_user_input/`（**仅开发者可编辑**）：**复杂输入的临时投递区，不是信源**。业务逻辑较复杂时（一批新功能附需求清单、样例 SQL、数据字典、存储过程、业务方书面答复等），开发者把原始材料放进这里供编程助手梳理，**按批次/主题建子目录**（如 `docs/1_user_input/<主题>/<日期>/`），一批材料对应一次梳理。这些材料只作该批梳理期间的临时素材、仅供理解业务逻辑，**非技术选型标准**。编程助手只读、不改、也不清理此目录（guard 硬拦），清理由开发者 `git rm`。
  - **新投递的材料在落盘前只是待梳理的输入**：与 `2_landed` 现有口径冲突时以 `2_landed` 为准，冲突本身作为歧义列入 `docs/open-questions.md` 向业务方确认，确认后再改 `2_landed`。
  - **该批梳理完成后，任何文档与代码都不再引用其中的文件**——有用内容已落盘进 `2_landed`，素材不作日后追溯依据，随时可能被清理。
- `docs/2_landed/`（**仅编程助手可编辑**）：业务逻辑与代码的**唯一信源**。更新有两条通道、结果一样都是改 `2_landed`：① 内容简单直白时，开发者在对话里直接交代，编程助手直接改；② 内容较复杂时，开发者投递到 `1_user_input/<子目录>/`，编程助手梳理、把歧义列进 `open-questions.md` 确认后落盘（可直接复制素材再编辑，或另建新文档）。必备 `db_description/db_[database]_[schema]_[table].md`（一表一文件，同构的一族表写一个表族文件）与 `business_description.md`（含**数据量声明**：涉及多少张表、每张表约多少行）；可选 `dirty_data.md`（有脏数据）、`privileges.md`（有权限管控）、`glossary.md`（有业务术语，↔ `manifest.glossary` 唯一信源）。开发者不直接改此目录，需修订则向编程助手提出。
- **`2_landed` 自包含、不外引**：不得以 `1_user_input/`、未入库的本机参考目录（如某些仓的 `references/`）或其他目录的文档作为信源或出处——**链接与纯文本提及都不行**，表文件也不写「出处」段。梳理期间可以查阅它们，但有用的信息（字段定义、口径算式、需要逐字遵循的原文，例如本地模型提示词原文）必须**复制落盘**进 `2_landed`；复制的是口径、结构与原文，**不复制真实业务数据行**（`2_landed` 入库并随 wheel 分发）。日后发现信息有误**直接改 `2_landed`**，不回溯原始素材。
  - `docs/decisions/` 是决策过程与变化历史，可作信源之一：`2_landed` 可用纯文本「决策 YYYY-MM-DD」标注依据（**不写成链接**——`2_landed` 打进 wheel，指向 `../decisions/` 的链接在平台 Console 里是死链），但必须按决策的**最新结论**及时同步，记录当前最新口径与原文。
- **`2_landed` 只留结论、不留过程**：落盘的是可直接作为口径信源的**最终业务结论**；梳理/修正业务逻辑时产生的中间过程——语义修正的来龙去脉、澄清问答、讨论推演、被推翻的旧口径——一律**不入** `2_landed`（原始输入只在梳理期间放在 `1_user_input/`、梳理完成后不再引用；需留痕的决策与推翻理由留 `docs/decisions/` 带日期记录）。修订既有口径时直接改写为新结论，不在正文堆叠"原来是…后来改成…"的过程叙述。
- **其他文档同样不留素材路径**：`open-questions.md` 在梳理进行中可以写「请把答复/执行结果放到 `docs/1_user_input/<子目录>/`」；条目关闭时结论写进 `2_landed`（需留痕的写进 `docs/decisions/`），已关闭条目、决策记录、`README.md` 进度表、代码与测试里都不留指向 `1_user_input` 具体文件的路径，素材来源用文字描述（如「业务方 2026-10-10 书面答复」）。
- **G1 业务梳理阶段不做技术决策**，只梳数据字段与业务逻辑，技术选型留到 G2 落 `docs/decisions/`。
- **持续维护**：仓库升级涉及需落盘的业务信息时，及时更新 `2_landed/` 对应文件。

## 技术设计先行（G4a → G4b）

**G4 分两步：先定稿设计（G4a），再写代码（G4b）。** 不是官僚流程——`field_mappings` 这类东西
（协议权限字段 → 物理列）映射缺失就 fail-closed 拒查、锚错列就是越权，两种都不会在测试里自己
蹦出来，必须有一份能被人看一眼的稿子。

- 产物：`docs/decisions/YYYY-MM-DD-模块技术设计.md`（模板在 `docs/decisions/README.md`）。
- 内容：manifest 草案 + **field_mappings 逐列锚定** + `handle()` 编排与事件序列 + SQL/沙箱边界
  + 多轮上下文用法 + 错误与降级。**G2 已定的数据侧形态不重复**（用哪些源、要不要治理/向量化）。
- 分档：纯 `structured-query` 模块几十行足够；带 `governance-etl` / `semantic-retrieval` /
  `analysis-report` 的必须独立成文。
- **编码时偏离设计 → 回来改设计文档**，别让代码与设计各说各话。
- 无 guard 硬拦（全流程只有 G1 有）。这是信任，不是可以跳过的意思。

## 引导式交互与初步分析（G1 采集 + G4b 实现）

线上助手要做到「意图澄清 / 每轮引导 / 初步分析+图表 / 术语理解」四项体验，靠平台已铺好的轨道 + 本模块填域。**这四项是运行时行为；本仓 CLAUDE.md/AGENTS.md 只约束你（build-time 编程助手）如何采集内容与按范式写代码，不约束线上助手本身**（线上行为由平台代码 + 下面这些声明驱动）。

> **设计取向（灵活性 vs 稳定性）**：线上本地 Qwen 尺寸/能力有限但**可信任地读取真实数据**做澄清/解读/初步分析（对它的唯一限制是别直接算数字，见红线）。采集澄清项/分析维度、写系统提示时按各环节可靠度取舍：数字/权限/路由等**不容错**处焊死走确定性轨道（沙箱/权限/白名单）保稳定，澄清/解读/引导等**容错**处放开让 Qwen 灵活发挥提体验——越关键越收紧、越容错越放开。

- **G1 采集（落 `2_landed` + `manifest`）**：
  - 必要澄清项 → `manifest.clarify_dimensions`（用户缺时间/机型等关键参数时该追问什么）。
  - 初步分析维度 → `manifest.analysis_dimensions`（本域该按机型/类别/等级等看什么、各画什么图）。
  - 业务术语表 → `docs/2_landed/glossary.md`（唯一信源）并同步到 `manifest.glossary`（术语/别称/口径）。
- **G4b 实现（照 `src/.../module.py` 的 handle 标准范式）**：
  - 数字红线：统计/计数/排序/对比一律 `await ctx.stats.run(script, {...})` 沙箱内算；`handle()` 里不写 pandas 聚合、不让 LLM 直算。**但 SQL 聚合不在禁止之列**——判据见下文红线里的「谁产出数字」条。
  - 沙箱产出的是**明细帧**（下钻数据集等中间表）时用 `ctx.stats.run(..., return_frames=True)`，从 `outcome.frames` 拿 DataFrame；**别**把帧拆成 records 塞进 `result` 再重建（上限 20 万字符，迟早撞）。见 `docs/dev/04` 的「拿回明细帧」。
  - 图表：`Event.chart(**ctx.stats.to_chart(outcome, ...))` 只产**抽象 spec**（数字来自沙箱产物，平台转 echarts）。
  - 术语/维度注入提示：`system = MY_SYSTEM + domain_prompt_section(self.manifest)`（数字走沙箱等平台红线 policy 已由 `ctx.llm` 自动前置，勿重复写）。
  - 答后引导：按本轮结果 `Event.suggestions([...])`——每项是 `{id,name,label,query}` 对象，**不是字符串**（传字符串不报错但前端出不来按钮，形状见 `docs/dev/02` 事件协议）。
- **软性 opt-in**：以上字段/文档缺省即不启用对应能力，平台不报错、不硬拦（区别于 `data_sources`/权限的硬校验）；有则精修、无则平台通用兜底。

## 多轮上下文（怎么拼、谁负责指代消解）

**会话的读写分工**：落库只有平台一个写入方（你 `yield` 事件，平台负责写；`ctx.session` 没有
`append`）；**读并注入 LLM 上下文是你的事**——平台不会把历史塞进 `ModuleRequest`。

- **跨轮的中间状态放 `ctx.workspace`，别塞进回答正文、别自己落盘**：下钻焦点、上一轮取到的明细帧、
  待用户选的候选——按「模块 + 会话」隔离、缓存语义（整体过期，**读不到是合法状态**，按未命中处理）、
  只放 dict/list/DataFrame 这类纯数据。见 docs/dev/02「会话工作区」。

- **「改了不该发版」的参数放 `ctx.config`，别写死在代码里、别自己读文件**：阈值、同义词表、
  字段展示名映射、话术模板。先在 `manifest.config_files` 声明文件名槽位，管理员在 Console
  「模块配置」页上传/回滚；平台**只存取不解析**，格式随你挑（json/yaml/ini/csv/.env）、
  解析与兜底全在你这边。三条别踩：**读不到（还没传）是合法状态**，兜底永远要有；
  **别放凭据**（Console 预览会明文展示，连库走 `manifest.data_sources` 的别名）；
  实现 `validate_config()` 把「配置写错了」拦在保存那一刻，而不是留到用户提问时炸。
  见 docs/dev/02「自管配置文件」。

- **拼上下文用 SDK helper，别自己撸**：

  ```python
  from forge_core.conversation import conversation_messages

  history = await conversation_messages(ctx, request, turns=3)
  resp = await ctx.llm.chat([{"role": "system", "content": system}, *history,
                             {"role": "user", "content": request.query}])
  ```

  它替你处理三个「自己写必踩」的坑：① 落库正文里混着平台投影的**渲染块**（GFM 表格、
  ```echarts 围栏、`<intent_routing_clarify>` 按钮数据）——喂给模型是纯噪声，一张几百行的表
  能把上下文预算一次吃光；② **当前轮的 user 行已经在历史里**（平台在分发给你之前就落库了），
  不排除就会把当前问题重复一遍；③ `limit` 是条数不是轮数。

- **`request.query` 恒为用户原话，平台不替你改写**。指代消解（把「那上个月呢」补成自足问题）
  是你的事——平台的通用消解会**掩盖「参数其实缺失」这个信号**（该发 CLARIFY 的轮次就不发了），
  而「那个批次」「上一版」要靠你的 `glossary` 与本域数据形态才解得准。

- **⚠️ 但多数时候你不需要「消解这一步」**：历史进了 messages 数组，指代消解就是模型的默认
  行为。**真正必须显式消解的是「query 被当作检索输入」时**——`ctx.retrieval.search(request.query, ...)`
  / `ctx.knowledge.retrieve(..., question)` 拿「那上个月呢」去算 embedding 毫无意义。
  规则记成：**检索前的 query 必须是自足的**。纯 `structured-query` 模块把历史塞进 messages 就够了。

## 答案呈现规范（回给用户的东西，按红线执行）

**权威详版 + 自检清单：[docs/dev/09-answer-presentation.md](docs/dev/09-answer-presentation.md)——产出任何回给用户的事件前先读它。** 下面各条越线**不会报错**（框架管不了它），直接变成用户看到的东西，故按红线要求自己守住：

1. **只返回对用户有意义的内容**。自增 ID / 代理主键 / GUID / 内部状态码 / 软删标记 / 审计列 / 权限承载列 / 连接键**一律不出现**在 `Event.table` 的列与正文里——**取到 ≠ 返回**（`select` 该取的照取，那是给权限与沙箱用的，取数集 ⊃ 展示集）。反面同样是要求：工单号/料号/项目编号这类**用户认得的业务标识必须给全**，别「精简」到只剩名称。
   - **序号照给、但序号不是主键**：要「第几条」就在展示层现生成 1..N（沙箱产物加一列或表格首列），**别拿自增 id 冒充序号**（用户会拿它当业务编号去别处查）。
   - 枚举/代码值翻成人话（`stage_code=3` → 「量产」），`None`/`NaN`/`1970-01-01` 一类占位值写「未填」。
2. **任何情况下不许把数据库表名、字段名甩给用户**。表格列名、`delta` 正文、图表轴、`Event.error` 的 message 一律业务语言：`prj_dly_days` → 「延期天数」。数据源别名（`info`/`erp`/`forge_mart_*`）、向量表名、SQL 片段、沙箱脚本、内部异常同样不外露——用户不需要知道数据在哪张表里。平台只脱敏**上游异常**，你自己写的 message 它不会替你翻译。
   - **显示名唯一信源** = `docs/2_landed/db_description/` 各字段的「用户可见显示名」+ `glossary.md`。**别每处即兴翻译**：同一列这轮叫「延期天数」下轮叫「拖期时长」，用户会以为是两个指标。
3. **给了数据还要给分析（默认要，除非用户明说只要数据）**。在精确给出目标数据的基础上追加：总量 → 分档/分布 → 最需要关注的 Top N（点名）→ 一句结论。例：查延期项目 = 清单 + 「共 37 个」+ 按延期时长分档（≤7 天 / 8–30 天 / >30 天）+ 延期最严重的几个 + 集中在哪个部门/阶段。判据是能回答「所以呢」——只把总数复述一遍不算分析，只丢一张表回去就是那种苍白冰冷的回答。
   - **分析什么由上下文决定**，本域该看的维度是 G1 采集产物、落 `manifest.analysis_dimensions`（平台 `domain_prompt_section` 注入 system）；**别硬编码进提示串**，那样换个问法就失效。
   - **数字全部走 `ctx.stats` 沙箱**（红线）：分档/计数/排序/Top N 都是数字；`Event.chart` 里每个数都必须来自 `outcome.result`。**不许为了「有分析」而编**，缺的数据就说缺。
   - **不分析的三种情形**：用户明说「只要列表/只要数据/我自己看/导出」；结果只有一两行（分析=复述）；用户在追问某一条记录的细节。
4. **结果上百条：表格给前 N 条 + 结论，全量走 `ctx.files` 导出成 Excel、把链接嵌进正文**。`ref = await ctx.files.save_dataframe(df, "延期项目明细.xlsx")` → `yield Event.delta(f"完整 {len(df)} 项见 {ref.markdown}（24 小时内有效）")`。**没有 `file` 事件**，链接就是一条普通 Markdown 正文。导出文件的表头同样过第 2 条那关（`dept_id` 出现在 Excel 里和出现在对话框里是同一个问题），但**可以**比展示多给几列——明细文件本就是拿去自己筛的。用法见 [docs/dev/02](docs/dev/02-sdk-reference.md)。**几十万行以上**（单次取数上限/单轮预算装不下）走后台导出任务 `ctx.files.submit_export(...)`：链接立刻给、生成完自动下载，见 docs/dev/02「后台导出任务」。
5. **寒暄与「你能做什么」：报本板块能力 + 列常用场景**。「你好 / 你是谁 / 你能帮我查什么」这类问题**会落进你的 `handle()`**——平台路由没有闲聊分支，这种问题不含模块关键词、分类器多半弃权，接着就是**单候选时直通你**、**上一轮路由过谁就粘回谁**（只有「多候选 + 无粘性」才被路由的澄清兜底接住）。所以骨架那句 `Event.delta(f"[{MODULE_CODE}] 收到: …")` 留着，用户第一句话拿到的就是它。答法：一句话说明本板块负责哪个域 → 列举常用场景 → **每个场景配一句简短介绍**（这个场景能回答什么问题），并配 `Event.suggestions` 把最常用的两三个做成可点按钮。「您好！有什么可以帮您的吗？」这种空洞客套不算数——用户还是不知道能问什么。
   - **只介绍本板块**：别顺带列举其他模块的能力——用户不一定有那些模块权限，那是给他一个点不动的预期，也把他看不到的权限边界说漏了。跨域引导是平台路由的事（澄清兜底只推荐权限内候选）。
   - **场景清单唯一信源** = `manifest.intents`（G1 采集的示例问题）+ `docs/2_landed/business_description.md`，**别即兴编**：编的场景要么模块压根不支持，要么措辞与 `intents` 对不上，用户照着你给的说法问一遍却路由不回来。反过来这也要求 `intents` 写成**用户认得的说法**、不是内部黑话。
   - **不因寒暄去取数**（一句「你好」不构成查询意图）；能力介绍同样过第 2 条那关——介绍的是**业务场景**，不是数据存在哪张表。**本域够不着的问题**同理：说清本板块管什么、不管什么，别硬答。

## 能力 Profile（初始化 / 追加必读）

模块在 `manifest.profiles`（`src/.../module.py`）声明启用哪些框架能力。**收到「追加 profile」「加 xxx 能力」类请求时，先读 [docs/dev/07-capability-profiles.md](docs/dev/07-capability-profiles.md) 对应小节**，按其「声明 / 依赖 / 代码 / 平台前置 / DoD」分步办、逐项自检。build-time 硬规则：

- **追加 ≠ 只加字符串**：`profiles` 无平台白名单校验，名字写错不报错、能力也不生效。`stats-sandbox` 近乎「加字符串即可」（平台按 profile 自动注入 `ctx.stats`）；但 `semantic-retrieval` / `governance-etl` **跨 G2 人工决策闸门**、需平台/运维侧建 `forge_mart_<模块编码>` 库并在平台 `data_sources.json` 登记数据源——这些**业务仓内够不到**，**不得跳过、不得只改 `manifest.profiles` 就报完成**。
- 涉及治理/向量化的 profile：**先在 `docs/decisions/` 落 G2 决策**（建不建 mart 库、同步 cron、权限透传约束）再动代码；平台侧登记/建库需协调平台仓，如无法完成须明确告知开发者、不得静默略过。

## 版本号规则

- 语义化三段 `X.Y.Z`（PEP 440），基础**必须恰三段**（各段可多位；两段/四段/`1.2.3-alpha1` 不合法），预发布用 `aN`/`bN`/`rcN`、开发版 `.devN`。
- `version` 写在 `pyproject.toml` 静态字段；打 `vX.Y.Z` tag 触发 CI 发 wheel。各模块仓独立 bump 自己的版本，规则统一。
- **版本号只此一处**：`manifest.version` 由 `module.py` 顶部的 `MODULE_VERSION` 读已装 wheel 元数据得来，不要改回手写字面量（手写那份发版时没人跟着改，最后就是机器上装着 `0.1.0a5`、Console 模块页却一直显示 `0.1.0`）。

## 硬约束（红线）

- LLM/Embedding/Rerank 仅本地服务（Qwen-3.8-27B / Qwen3-Embedding-8B / Qwen3-Reranker-8B；型号随平台升级，以 `docs/dev/README.md` 为准）。**线上本地模型（Qwen）允许接触真实业务数据**用于解读/总结/初步分析（本地部署的意义）；只有**外部 build-time 编程助手（你自己）与任何外部模型 API** 严禁接触真实数据、严禁直连数据库。
- 数据源必须在 manifest.data_sources 声明（别名=实例/库句柄，多实例多条）；平台启动校验别名已在 data_sources.json 登记、运行期 ctx.data 只放行已声明别名。每张 db_description 表须标 `source`（所属实例），别名并集与 manifest.data_sources 一致。
- 数据权限必须经 forge-data DataScopeFilter 取数前阻断（fail-closed）；权限字段映射在 manifest.field_mappings 声明（同一别名下不同表的权限承载列名不同时，须写**表级映射**，否则会拿 A 表的列名去编译 B 表的 WHERE = 静默的错误过滤）。
- **取数优先用 `ctx.data.fetch(spec)`（声明式 QuerySpec）而不是 `.query(where="...")`**：裸 `where` 串**不过列级白名单**（禁列可被当 oracle 二分反推），且每次调用打 `raw_where` 审计 flag。`fetch` 把列级权限管到 spec 的**每一个**列引用位置（select / filter / order_by / 跨列比较 `{"$column": ...}` 的目标列）。两者请求无权列都**抛 ColumnNotPermitted**（不是静默少列）。
- **日期区间写 `{"$relative": "-30d"}` 交框架算，别让 LLM 自己算「30 天前是哪天」**——那是数字红线。filter **只有比较、没有计算**：算术表达式交 `ctx.stats` 沙箱（小数据）或 governance-etl 在 mart 落派生列（大数据）。
- **表级无权在 `fetch`/`query`/`raw` 一律抛 `TableDenied`**（不可重试，取数前即阻断，不是返回空 DataFrame）——空结果谁都会读成「该数据不存在」而不是「你没权限」。唯一例外是 `row_scope_sql()`（只产 SQL 片段、不执行，仍编译成 `1 = 0`）。`fetch` 另有两处与 `.query()` 不同：不给 limit 时施加平台行数上限且**超限报错**（不是静默截断）、limit/offset 的方言差异由框架编译。多轮重试用 `SpecRepairLog` 累积「已知不可用」，别死磕 `retryable=False` 的错。
- **多表 JOIN 只能连 manifest 声明过的边**：在 `data_sources[].joins` 写 `JoinEdge(left, right, on=[("customer_id","id")], types=[...])`，spec 越界即 `JoinNotDeclared`；不声明 = 该源不支持 JOIN（**没审过的连接不放行**，不是「没声明就随便连」）。关联列要与声明**完全一致**（漏写复合键的一半在 SQL 里合法，只会静默多关联出一堆行）。让 LLM 组 spec 前把 `ctx.data.describe()` 的目录（`as_prompt()`）拼进提示词——同一张图既是白名单也是目录，LLM 不用猜。
- **JOIN 的两条反直觉之处**（不知道会当成框架 bug）：① 框架加的行级 scope 编译进被连接表**自己的 `ON`**，所以 `LEFT JOIN` 不会因为关联表无权而退化成 `INNER`；但**你写的 `filter` 仍进 `WHERE`**，引用被 LEFT JOIN 表的列时**仍会退化**——那是标准 SQL 语义、是你显式要的过滤，框架不替你改。② 关联键（`on` 的列）与投影列**同权**，无豁免（`ON a.dept_id = d.id` 配可读的 `d` 就是把禁列明文读出来）。按业务方约定关联列一定在授权范围内（例外只有「整张关联表不许访问」，那是 `TableDenied`），所以正常撞不上；真撞上会拿到 `ColumnNotPermitted` 且 `detail.position="join_on"`——那是**权限配置漂移**，拿着 hint 找 INFO 把该列纳入列级授权，别当框架 bug。
- **取数句柄一律用平台注入的，不得自造**：结构化走 `ctx.data`、语义检索走 `ctx.retrieval`（需 `semantic-retrieval` profile）。禁止在模块里 `new ScopedDataAccess/PgVectorIndex/EmbeddingClient`、禁止自己读 env 拿 endpoint 或连接串——那样绕开的是权限下推与审计归档（自造的检索连权限 WHERE 都没有）。句柄为 `None` 时是 profile 未声明或平台未配置，**找平台侧解决，不得自己造一个顶上**。
- **ETL / jobs 同理**：句柄从 `JobContext` 取（`ctx.etl.read/write`、`ctx.embedder`），`run(ctx)` 里取、不在 `jobs()` 里预绑；同样禁止自己 new 连接、禁止读 env。⚠️ `ctx.etl` **不是** `ctx.data`——ETL 期没有 AgentNode，它是**系统级、不受权限过滤管辖**的；ETL 的权限义务是**把权限承载列透传**进 mart 表（漏了平台启动期即拒绝 `VECTOR_SCOPE_COLUMNS_MISSING`），不是「过滤」。
- **向量化回填不许自己写**：声明 `manifest.vectorize`，平台生成回填 job + 建表 DDL（`forge vectorize ddl`）并**自动透传权限承载列**。自己写 = 把「记得 SELECT dept_id」这个坑重新挖开。你要写的是（如需要）治理 ETL：把数据落成一张含 content 列 + 权限承载列的干净表，向量化只读它。
- 一切数字处理（统计/算术/计数/排序/对比）走 `ctx.stats` 沙箱脚本，禁止 handle() 内直算、禁止 LLM 直算（因 LLM 数字运算不可靠，**非因**禁止其接触数据——把数据交给 Qwen 做解读/分析是允许且鼓励的）；图表 `Event.chart` 只产抽象 spec，其数字必须来自确定性执行器的产物。
- **红线禁的是「谁产出数字」，不是「哪里出现算术」**：禁的两件事没变——LLM 自己报数、`handle()` 里用 Python/pandas 直算。SQL 引擎与 `ctx.stats` 沙箱**同属确定性执行器**（同一份输入必得同一个数、过程可复现可审计），都不在禁止之列。分工判据：**这个聚合能否用「表里已有的列 + COUNT/SUM/AVG/MIN/MAX」表达完？** 能 → **优先**下推 SQL（`spec.group_by` / `having` / `{"field": "amount", "agg": "SUM"}`；数据在 DB 侧就收敛，更快，也让更少的无关行离开数据库）；不能（同比环比、分档、加权、跨源）→ `ctx.stats` 沙箱。两条路通向同一条不变量：**LLM 只能引用执行器的产出，永远不许自己报数**——包括「顺手心算一下百分比」。
- **聚合的三处坑**：① **聚合参数与投影列同权**——`AVG(salary)` 无权即 `ColumnNotPermitted`（`where` 一次泄露一个 bit，聚合直接返回明文；分组键足够细时聚合就是投影）。② **结果列名由框架生成**（`sum_amount` / `count_star` / `count_distinct_id`，给了 `label` 就用 `label`），`df[...]` 按它取；结果列名重复即报错（多表下两张表都有 `id` 是最常见的撞法）。③ 既非聚合、又不在 `group_by` 里的列 → `GroupByIncomplete`（`select` / `order_by` / `having` 三处都查）；按聚合结果过滤只能写 `having`，`filter` 里放 `agg` 会被拒——**WHERE 在 GROUP BY 之前执行**，而行级 scope 就编译在那里，这正是查询期聚合安全的理由（与「建 mart 时别把权限维度预聚合掉」是两回事）。
- 回给用户的内容里不出现数据库表名/字段名，也不出现自增 ID 一类对用户无意义的标识；数据之外要给合理分析（用户明说只要数据除外）；「你好/你能做什么」这类寒暄要报本板块能力与常用场景（不是回声、也不是空洞客套）——详见上文「[答案呈现规范](#答案呈现规范回给用户的东西按红线执行)」与 `docs/dev/09-answer-presentation.md`。
- `.env` 永不入库。
- 文档同步触发：业务信息变更即时更新 `docs/2_landed/` 对应文件；大改动/累积改动全量核查一致性；发现矛盾向程序员提问确认。

## 常用命令

```bash
uv sync && uv run pytest
uv run forge dev serve                # 本地迷你平台（debug chat: POST /v2/chat + target），默认 127.0.0.1:8090
uv run forge dev serve --port 8123    # 指定运行端口（--host 改绑定地址）
uv run ruff check src tests
```

## 语言

- 默认优先使用简体中文回答，其次是英文。
- 代码、命令、文件名、API 名称和技术术语保持原文。
