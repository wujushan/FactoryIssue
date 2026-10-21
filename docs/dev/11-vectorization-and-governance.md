# 11 mart 库模块的端到端时序（开发 → 上线 → 日常运行）

> **这篇只承载时序**：阶段顺序、每步的**执行者**（业务开发者 / 平台运维 / 平台自动）、
> 在**哪台机器、哪个进程**上发生，以及症状 → 原因 → 修法的排查表。
>
> **语义与契约细节一律不在这里重复**——`manifest.vectorize` 怎么写、权限透传规则是什么、
> DDL 长什么样、别名怎么取，全部链接到 [04](04-permissions-and-data-access.md) /
> [06](06-cli-reference.md) / [07](07-capability-profiles.md) / [08](08-release-and-assembly.md)。
> 本文里凡是规则性陈述都应该是一句话 + 链接；发现有第二份定义，那是 bug，改这里。

## 适用范围：凡是要一个 `forge_mart_<编码>` 库的模块

两个 profile 会让你需要一个自己的 mart 库，**它们相互独立、可单独启用**：

| 你的模块 | profile | mart 库里有什么 | 要走哪几段 |
|---|---|---|---|
| **只治理，不向量化** | `governance-etl` | 治理后表 | 治理段 ✅ / 向量化段 ❌ |
| **只向量化，不治理** | `semantic-retrieval` | 向量表（`vectorize` 直接读源表） | 治理段 ❌ / 向量化段 ✅ |
| **两者都要** | 两个都声明 | 治理后表 + 向量表 | 两段都走 |

> ⚠️ **别把治理当成向量化的必经前置**。「源表已经够干净、只是有个长文本字段要语义检索」
> 是完全成立的形态——`manifest.vectorize` 的 `origin_table` 指向谁都行，不要求它是治理产物。
> 反过来「治理完直接 `ctx.data` 结构化取数、根本不做向量」也一样成立。
> 需要治理的判据只有一条：**源数据脏 / 量大到直连不划算**，与向不向量化无关。

下面的阶段表用 **🅖**（governance-etl 才做）/ **🅥**（semantic-retrieval 才做）标出可跳过的步骤，
没标的两种模块都要做。

---

## 0. 先看这几样东西你**不用写**

这条链路里业务仓最容易多写、写错的，平台已经替你做了：

| 不用你写 | 谁做的 | 细节看哪 |
|---|---|---|
| 🅥 **向量化回填代码**（扫 → embed → upsert → 清孤儿） | 平台按 `manifest.vectorize` **生成** job | [07 · semantic-retrieval](07-capability-profiles.md) |
| 🅥 **向量表 DDL**（建表 + HNSW + scope 列 btree） | 平台生成，运维执行 | [06 · vectorize](06-cli-reference.md) |
| 🅥 **embedding / rerank 客户端** | 平台按部署配置装配，注入 `ctx.retrieval` | [07](07-capability-profiles.md)、[02](02-sdk-reference.md) |

`jobs()` 里**不要**写向量化 job，`handle()` 里**不要** new `PgVectorIndex` / `EmbeddingClient`。
自己写这三样的直接后果不是「重复劳动」，而是**权限承载列的透传从框架焊死退回到「开发者记得」**。

**反过来，🅖 治理后表的建表 DDL 是你写的**（写在 ETL job 开头的 `CREATE TABLE IF NOT EXISTS`）——
它每个模块都不一样，平台无从生成，也不需要像向量表那样赶在平台重启前建好。
（向量表结构定型，且必须先于平台重启存在——两条差别决定了执行者不同。）

---

## 1. 谁负责什么

三个角色，跨三台机器。**上线卡住时先确认卡在哪一列**——绝大多数「声明了却不工作」是角色错位，
不是代码错。

**这条链路是两条轨道，不是一条直线**。分不清哪一步在哪条轨道上，就会得出「建表要用模块的
manifest，可那时模块还没装配」这种死结（它是真死结——只不过建表并不发生在你以为的那个时刻）：

- **A 轨 · 业务仓侧（开发期，阶段 0–5）**：在开发者自己的机器上，产出一个 wheel。
- **B 轨 · 平台侧（上线期，阶段 6–9）**：在平台服务器上，把那个 wheel 变成能用的服务。
  **B 轨对每个环境（测试 / 正式）各走一遍。**

A 轨全部做完（wheel 已发布）之后，B 轨才开始。**建向量表在 B 轨的阶段 7 里面，不在 A 轨**。

| 轨 | 阶段 | 业务开发者（自己机器 / 业务仓） | 平台运维（平台服务器） | 平台自动 |
|---|---|---|---|---|
| A | 0 G2 决策 | ✅ 落 `docs/decisions/` | 参与评审 | |
| A | 1 manifest 声明 | ✅ | | |
| A | 2 🅖 治理 ETL（**含建治理后表**） | ✅ 写 `jobs()` + `CREATE TABLE IF NOT EXISTS` | | |
| A | 3 `handle()` 取数 / 🅥 检索 | ✅ | | |
| A | 4 本地验证 | ✅ | | |
| A | 5 发包 | ✅ `forge release --alpha` / `<正式版号>` | | |
| B | 6 建 mart 库 + 登记别名 | ❌ 够不到 | ✅ `forge data provision-mart` | |
| B | 7 装配（🅥 **含建向量表** + 重启） | | 正式环境点一次手动确认 | ✅ 装 wheel → `vectorize apply` → 重启 |
| B | 8 首轮跑数 | ❌ 够不到真库 | ✅ `forge jobs run` | ❌ **不会自动跑**（最容易漏，见阶段 8） |
| B | 9 日常运行 | | 看能力面板 / 排查表 | ✅ cron 增量跑数 |

> **两类表的建表执行者不同，别混**：🅖 治理后表由**你的 ETL job** 建（阶段 2 写代码、阶段 8 首轮
> 跑时真正建出来）；🅥 向量表由**平台**建（阶段 7，随部署自动）。
> **判据**：向量表结构定型故平台能生成，且它必须先于平台重启存在；治理后表每个模块都不同、
> 也没有那个时序约束，由首轮 job 建完全来得及。

> **「够不到」是设计而非缺失**：开发者不接触生产数据库账号；建库/建角色凭据由运维当场传入、
> 跑完即走，不进任何服务配置。一模块一对专属账号，不跨 mart 库共用。

**B 轨内部的顺序是硬约束，三步都不能换位**（每一步都被前后夹死，理由见阶段 6/7）：

```
6 建库 + 登记别名  →  7 装配（装 wheel → 🅥 建向量表 → 重启）  →  8 首轮跑数
   ↑ 不需要 wheel        ↑ 建向量表要 wheel，又必须早于重启         ↑ 🅖 首轮建治理后表并填数
   漏了：平台拒绝启动     漏了：平台拒绝启动                        ↑ 🅥 首轮把向量填满
                                                                 漏了：查不到/检索 0 条，且不报错
```

---

## 2. A 轨 · 业务仓侧（阶段 0–5）

### 阶段 0 · G2 决策（业务开发者，跨闸门）

判定**要不要建 mart 库**，以及建了之后**治理 / 向量化各要不要**（三种组合都成立，见开头适用范围）。
**评审必须在申请建库之前**。决策里必须写死两件事：① 权限承载列清单；② 受列级管控字段的处置
（🅥 才涉及）。
→ 内容清单见 [07](07-capability-profiles.md) 对应 profile 小节的「⚠ 先过 G2」。

### 阶段 1 · manifest 声明（业务开发者，业务仓）

`profiles` / `data_sources`（含 `tables`）/ `field_mappings` 三处两类模块都要；🅥 再加 `vectorize`。
→ 每处写什么、`VectorizeSpec` 各字段含义、表达力边界见 [07](07-capability-profiles.md) 对应小节。

⚠️ 🅖 **`data_sources[].tables` 要把治理后表写进去**：它今天仍是可选字段，但**启动期的权限承载列
校验只查已声明的表**——不声明就等于自愿放弃那道闸（漏透传要等运行期 42703）。

**一个字段一张向量表**：`manifest.vectorize` 是个**列表**，要单独检索的每个文本字段各写一条
`VectorizeSpec`（同一张 origin 表可以出现多次，只要 `vector_table` 不重名）。多张源表同理。
每条各自生成一张表、一个回填 job、一份 cron。
反过来，写进同一条 spec 的 `text_columns` 会被拼成**一段 content、一个向量**——那是「这几列合起来
描述同一件事」时才该用的。判据在阶段 3：**你希望用户的问题分别命中它们，就分表**。

此刻在你机器上能做的自检只有一条：`uv run forge vectorize ddl` 打得出 DDL，且
「权限承载列」那行不是空的（空的说明 `field_mappings` 没配对，检索期就没有行级过滤可编译）。

### 阶段 2 · 🅖 治理 ETL + 建治理后表（业务开发者，业务仓）

**只有 `governance-etl` 模块做这一步。** 判据是**源数据脏 / 量大到直连不划算**——与向不向量化无关。
（若同时启用 🅥，附带的好处是治理后表可以被 `vectorize` 当 `origin_table` 读，
从而绕过 `VectorizeSpec`「单表 + 列拼接」的表达力边界；但那是结果，不是做治理的理由。）

**治理后表的建表 DDL 写在这个 job 的开头**，`CREATE TABLE IF NOT EXISTS`，首轮跑时自动建出来：

```python
async def _sync(self, ctx: JobContext) -> None:
    dst = ctx.etl.write("forge_mart_kb")
    dst.execute("CREATE TABLE IF NOT EXISTS issues (id text PRIMARY KEY, content text,"
                " dept_id text, ts timestamptz)")   # dept_id = 权限承载列，漏了平台启动期就拒绝
    ...
```

**你不需要 Alembic，模板里也没有。**
→ 声明/依赖/代码/DoD 见 [07 · governance-etl](07-capability-profiles.md)；
`ctx.etl` 为什么不受权限管辖、透传义务是什么见 [04](04-permissions-and-data-access.md)。

### 阶段 3 · `handle()` 里取数（业务开发者，业务仓）

🅖 治理后表和普通业务表一样，走 `ctx.data.fetch(spec)` 结构化取数——**它不必再接向量化**：

```python
df = ctx.data.fetch(QuerySpec.model_validate({"source": "forge_mart_<编码>", "from": "issues", ...}))
```

🅥 语义检索走 `ctx.retrieval`：

```python
hits = await ctx.retrieval.search(request.query, source="forge_mart_<编码>", table="<向量表>")
```

`table` 参数决定检索哪一张向量表。声明了多张（阶段 1）时，**选哪张是你的业务逻辑**：按意图选一张，
或并发检索多张再合并——平台不替你选，也不会跨表自动合并。

→ 取数红线与 `QuerySpec` 写法见 [04](04-permissions-and-data-access.md)；
🅥 检索前 query 必须自足（多轮指代消解是本 profile 的必修课）、列级权限不作用于检索路径、
HNSW 召回塌陷这三条边界见 [07 · semantic-retrieval](07-capability-profiles.md) 与
[04](04-permissions-and-data-access.md)。回给用户的内容还要过 [09](09-answer-presentation.md)。

### 阶段 4 · 本地验证（业务开发者，自己机器）

本地没有 mart 库，能验的只有「代码路径通不通」：`uv run forge dev serve` 起迷你平台。
🅥 `ctx.retrieval` 为 `None` 是**正常的**（本地没配 embedding 服务）——你要确认的是模块在
`ctx.retrieval is None` 时给出的是清楚的提示而不是 `AttributeError`。
真实数据与召回质量只能在接了真库的环境上验，即 B 轨跑完之后。
→ 命令见 [06](06-cli-reference.md)。

### 阶段 5 · 发包（业务开发者，业务仓）

```bash
uv run forge release --alpha        # 预发布 → 平台测试环境
uv run forge release <正式版号>      # 正式版（须在 main 上）→ 平台正式环境（gated）
```

→ 完整发版流程、两道 tag 门禁见 [08](08-release-and-assembly.md)。

**A 轨到此结束**：你交付的是一个 wheel。下面 B 轨的四步全在平台服务器上，
**测试环境和正式环境各走一遍**——wheel 会自动进测试环境，但库 / 账号 / 表 / 数据**一样都不跟着走**。

---

## 3. B 轨 · 平台侧（阶段 6–9，每个环境各走一遍）

### 阶段 6 · 建 mart 库 + 登记别名（平台运维，平台服务器）

```bash
uv run forge data provision-mart --module <编码> --host <PG主机> --vector --apply --write-config
```

建 `forge_mart_<编码>` 库 + 一对专属账号 + 授权 + 装 pgvector + 写回 `data_sources.json`。
→ 两道前置闸门、口令怎么贴、`--alias` 的含义在**平台仓**的服务器命令手册里（运维侧文档，
你仓里读不到；这一步本来就不归你做）。

- **这一步不需要模块 wheel**（库名只由 `--module` 推出），所以它能、也**必须**排在装配之前。
- **必须早于阶段 7**：平台启动期会校验模块声明的别名已登记，没登记就**拒绝启动**。
  而装配是自动的（测试）或一键 gated（正式）——一旦触发就装 wheel + 重启，
  此时才发现库没建，平台就起不来了。
- ⚠️ **必须配 `write_user` / `write_password_env`**（`--write-config` 会写好）：
  🅥 阶段 7 建向量表、🅖 阶段 8 建治理后表并落数，全走它，缺了都 fail-closed。

### 阶段 7 · 装配（平台自动；正式环境需一次手动确认）

模块 wheel 进入运行环境。🅥 **建向量表就发生在这一步里面**，不是一个独立的手工阶段
（🅖 治理后表不在这里建——它由阶段 8 的首轮 job 建，见下）。

平台的部署脚本按这个次序跑（**平台侧内部细节，你不需要也没法碰**，列出来只为解释下面那条约束）：

```
装模块 wheel  →  平台自己的库迁移  →  ★ 建向量表  →  重启平台与 jobs
```

**为什么建表只能夹在中间这一格**——它被两头夹死，这正是「建表要用模块的 manifest，可那时模块还没
装配」这个疑问的答案：

- 建表命令读的是**已装进运行环境的模块的** `manifest.vectorize`，所以它**必须在装 wheel 之后**；
- 平台一重启就校验声明的向量表存在（缺表**拒绝启动**），所以它**必须在重启之前**。

于是窗口只有这一个，部署脚本已经占住了它。**走正常装配链路时，没有人需要手动跑建表命令**
（手工换过 wheel、或上次建表失败要补跑时，运维会手动补一次；那是平台侧的事）。

→ 全部语句是 `CREATE ... IF NOT EXISTS`，所以重放安全、也不需要版本化迁移；scope 列一律建成
`text` 是刻意的契约（回填与检索两侧都归一到 text），源列是 int / date / bool 都不影响。

### 阶段 8 · 首轮跑数（平台运维，平台服务器）⚠️ 最容易被漏掉的一步

```bash
uv run forge jobs list                              # 列出这台机器上全部 job 与生效 cron
uv run forge jobs run <模块编码>.<job名>             # 🅖 治理同步：首轮**建表 + 灌数**
uv run forge jobs run <模块编码>.vectorize:<向量表>   # 🅥 向量化回填：声明了几张表就跑几次
```

🅖 先跑治理 job（它建出治理后表并灌数），🅥 再跑向量化回填（它读治理后表）——两者都启用时顺序不能反，
否则向量化回填读不到源表。

**在 `$APP_DIR` 下跑**：`forge` 启动时加载当前目录的 `config/.env`（其次仓根 `.env`），口令类变量
（`FORGE_DS_*_PASSWORD`）就是从这里来的；换个目录跑会报「环境变量未设置」。`run` 只解析
`<模块编码>` 声明过的那些别名，不要求无关数据源（info/erp）的口令也在环境里。

**平台不会在启动时替你跑第一次**。jobs worker 只把 job 注册给 APScheduler 的 cron 触发器，
`default_cron="30 2 * * *"` 的模块上线后，第一次执行在**次日 02:30**。在那之前：

- 🅖 治理后表根本不存在（它由 job 建），`ctx.data` 取数直接报表不存在；
- 🅥 向量表是空的，检索**恒返回 0 条**；
- **平台不报错**——启动期校验只查 `information_schema` 的列结构，不查行数；治理后表不存在时
  更是**只告警**（`declared_table_absent`），因为「首轮还没跑」本就是正常中间态。

也就是说，不跑这一步的症状是「上线了，功能静默不工作，日志干净」。前两步漏了都会以「平台起不来」
的形式当场暴露，**只有这一步是静默的**。**把它写进上线 checklist。**

首轮耗时按行数（🅥 还要按 embedding 吞吐）估，全量可能是小时级；`forge jobs run` 是前台执行，
建议放在 `tmux` / `nohup` 里，跑完打印一条执行记录 JSON。跑的过程中约 2 秒打一行进度到 stderr
（`1200/2860（42%）`）：🅥 的分母平台自动数（与回填同一套 WHERE 的 count，数不出来就只报已完成条数，
回填照跑）；🅖 治理同步要有进度得自己调 `ctx.progress(...)`，见
[02 §定时任务](02-sdk-reference.md#定时任务-forge_corejobs)。

跑的过程中**能看见进度**（约 2 秒一行，走 stderr，与 Admin Console 任务页显示的是同一份）：

```text
[forge jobs] KB.vectorize:issues_vec 1200/2860（42%） 向量化回填 issues_vec，已用 96s
```

🅥 向量化回填的分母由平台自动数出来（与回填同一套 WHERE 的 count，故它就是「这轮真要跑的行数」）；
数不出来时退化成「已完成 N 条（总量未知）」——**回填照跑**，进度数字从不反过来弄挂任务。
🅖 治理同步要有进度得自己在 job 里调 `ctx.progress(done, total, "阶段名")`
（见 [02 §定时任务](02-sdk-reference.md#定时任务-forge_corejobs)），不调就显示「该任务未上报进度」。

**跑完再重启一次 `forge-platform`**：🅖 治理后表此刻才存在，重启后启动期校验才真正校验得到它
（此前是 `declared_table_absent` 告警）——这是确认权限承载列没漏的最省事方式。

### 阶段 9 · 日常运行（平台自动）

cron 到点，jobs worker 按各 job 的 cron 跑增量：

- 🅖 治理同步：按你写的水位/增量逻辑（`run_incremental_sync`）；建表语句每轮空转一次。
- 🅥 向量化回填：只挑向量表里没有的行、content 变了的行、**以及换了 embedding 模型之后的全部行**
  （模型名在 content_hash 里，换模型自动全量重嵌，无需任何运维动作）。源表删掉的行连带删向量。

---

## 4. jobs worker 的注册时机（为什么改了配置必须重启）

这是日常运行里最反直觉的一条，单独讲清楚：

```
deploy.sh  systemctl --user restart forge-jobs
            └─> forge jobs serve
                 └─> JobsWorker.collect()          ← 此刻从 manifest.vectorize **现生成**向量化 job
                      └─> scheduler.add_job(CronTrigger.from_crontab(cron))
```

**job 列表在进程启动那一刻定型。** 推论：

- 改了 `manifest.vectorize`（新增向量表、改 cron）或改了 `.env` 的 `FORGE_JOB_CRON_OVERRIDES`，
  **必须重启 `forge-jobs`** 才生效；
- 走正常装配链路自动满足（`deploy.sh` 结尾就是重启 platform + jobs）；
- **手工换 wheel 而不重启的话，worker 还在跑旧的那份任务表**——新声明的向量表一次都不会被回填，
  而 `forge jobs list` 因为是新进程，会**显示得完全正常**。这个组合极难查，遇到「list 里有、
  就是不跑」先看 `systemctl --user show forge-jobs -p ActiveEnterTimestamp` 是不是早于换 wheel。

同理，某个模块被隔离（下面第 4 节）之后修好了配置，也要重启 `forge-jobs` 才会重新收上来。

---

## 5. 启动期校验的结局（两张表各一套，严厉程度不同）

平台启动时跑两道权限承载列校验：🅥 一道管向量表，🅖 一道管你声明的其他表。
**别把告警当拒绝、也别把拒绝当 bug**：

| 表 | 情况 | 结局 | 为什么是这个结局 |
|---|---|---|---|
| 两者 | 连不上库 / 探测抛异常 | **仅告警**（`vector_scope_probe_failed` / `table_scope_probe_failed`） | 不把启动耦合到库的可用性——库维护期重启不该起不来 |
| 🅥 向量表 | `manifest.vectorize` 声明的表不存在 | **拒绝启动**（`VECTOR_SCOPE_COLUMNS_MISSING`） | 它必须先于重启建好（阶段 7），不存在就是确定性部署缺口 |
| 🅥 向量表 | 缺 `field_mappings` 的物理列 | **拒绝启动**（同上） | 缺列 = 检索期编译不出行级 WHERE，权限红线缺口 |
| 🅥 向量表 | 一张都扫不到，且没声明过 | **仅告警**（`vector_table_absent`） | 模块自写向量化时平台无从知道本该有几张表 |
| 🅖 声明的表 | `data_sources[].tables` 里的表不存在 | **仅告警**（`declared_table_absent`） | 治理后表由 job 首轮跑时才建，启动时缺席是正常中间态 |
| 🅖 声明的表 | 表在但缺 `field_mappings` 的物理列 | **拒绝启动**（`TABLE_SCOPE_COLUMNS_MISSING`） | 同上，取数期编译不出行级 WHERE |

> **两张表的校验对象怎么来，是刻意不同的**：向量表靠**结构识别**（扫全库找含 pgvector 列的表），
> 「扫到的都得对」；治理后表没有这种标记，只能**按 `data_sources[].tables` 的声明**查——
> mart 库里合法地存在水位表 / 中间表，它们没有承载权限的义务。
> 代价：**不声明 tables 就查不到**（`tables` 至今是可选字段，不能因为新增校验就把存量 manifest
> 判成非法）。

> 探测以**只读取数账号**身份执行，而 PG 的 `information_schema` 只列出当前账号有权限的对象。
> 所以「扫到 0 张表」有两种可能：表还没建，或只读账号没被 GRANT。两者都是部署缺口。

---

## 6. 排查表（症状 → 原因 → 修法）

| 症状 | 最可能的原因 | 修法 |
|---|---|---|
| 🅥 **检索恒返回 0 条，日志干净** | 阶段 8 没做：向量表是空的，cron 还没到点 | `forge jobs run <编码>.vectorize:<表>` 跑首轮全量回填 |
| 🅖 **取数报「表不存在」，启动日志有 `declared_table_absent`** | 阶段 8 没做：治理后表由 job 首轮跑时才建，还没跑过 | `forge jobs run <编码>.<治理job名>`；跑完重启平台，让启动期校验真正校验到它 |
| 🅖 平台起不来，`TABLE_SCOPE_COLUMNS_MISSING` | 治理后表建出来了但缺权限承载列（建表 DDL 与 `field_mappings` 不一致） | 改 job 里的 `CREATE TABLE` 加列 + 改 SELECT 带出该列，然后加列 `ALTER TABLE ... ADD COLUMN` 或重建表后重跑 job（`IF NOT EXISTS` 不会替你改已存在的表） |
| 🅖 改了 `field_mappings` 却没报错 | 该源的表没写进 `data_sources[].tables` —— 启动期校验只查已声明的表 | 把治理后表补进 `tables`（不声明 = 自愿放弃这道闸） |
| 平台起不来，`VECTOR_SCOPE_COLUMNS_MISSING` | ① 向量表没建（阶段 7 的 apply 失败或被跳过）；② 表建了但缺 scope 列（`field_mappings` 后来改过）；③ 表建了、但**只读取数账号没被 GRANT**——校验以只读账号身份查 `information_schema`，看不见与没建同一个报错 | ①③ 归平台侧（重跑建表 / 补只读授权；`\dt` 看得到表**不能**证明读得了它）；② 缺列是结构变更，apply **不会**替你改表：人工加列 + 重跑回填，或重建表后重跑 |
| 平台起不来，别名未登记 | 阶段 6 没做，或只在另一套环境做过 | `forge data provision-mart`，确认写进的是**这台机器**的 `config/data_sources.json` |
| 日志 `vector_table_absent`，但表明明建了 | 只读账号没被 GRANT（`ALTER DEFAULT PRIVILEGES` 漏了 `FOR ROLE <etl>`） | 找平台方重做只读账号授权（`GRANT USAGE ON SCHEMA public` + `ALTER DEFAULT PRIVILEGES FOR ROLE <etl>`） |
| 日志 `vector_scope_probe_failed`（带 `declared=N`） | 该别名**连库/取数本身**就不通（凭据、网络、驱动、库维护中） | 先修连通性（平台侧 `forge data check`）。⚠️ **这条不是无害告警**：探测失败时「声明的向量表存在吗」也一并没验，缺表不会再拒绝启动，症状会退化成「检索恒 0 条」 |
| 回填 job fail-closed，报「未构造 ETL 写句柄」 | 老版本里 Admin Console 的按钮是在**网关进程**里跑的 | 平台侧 2026-08-09 起改为「网关排队 / jobs worker 执行」，按钮已可用；仍可用 `forge jobs run ...` 兜底。写凭据按设计不进网关内存 |
| 回填 job 报缺 `FORGE_EMBEDDING_BASE_URL` | 平台没配 embedding 服务 | 配上；同一个配置源也决定 `ctx.retrieval` 是不是 `None` |
| 🅖 **首轮成功、第二轮起必炸**：`Invalid parameter type … param-type=numpy.int64 (HY105)` | 水位是从上一条查询的 **DataFrame** 里取的（`.max()` / `.iloc[]` / `.at[]` 拿到的是 numpy 标量，不是 Python int），拿去查 SQL Server 即 HY105。首轮空表 `max()` 给的是 `None` 所以没事，**有数据之后才暴露**；同一个值写回 mart（PG）却不报错——psycopg 对 int64 收得下，于是问题只在原始库那一侧现形 | **平台侧已在绑参处归一**（`forge-data ≥ 0.1.10`）：升级 SDK 即可，业务代码不用改。老版本上先自己转：`int(wm)` / `wm.item()`，取整列用 `.tolist()` |
| 回填写入报维度不符 | 推理引擎侧没按 MRL 截断到 1024 | 引擎侧配置；向量表建的是 `vector(1024)` |
| **某个模块的定时任务一条都不跑，其他模块正常** | 该模块被隔离了（非法 cron / `jobs()` 抛异常） | 看 `job_collect_failed` 日志与 jobs 能力面板的 `module_jobs` 项；改完**重启 `forge-jobs`** |
| **窄权限用户召回条数远少于 top_n（管理员正常）** | HNSW 后过滤的召回塌陷；服务端 pgvector < 0.8.0 时没有 `iterative_scan` | 升级服务端 pgvector ≥ 0.8.0；验收必须用窄权限账号测召回条数 |
| **带条件（机型/工厂/时间）的检索经常 0 条，不带条件正常** | 模块「全表召回 top_k → 与候选编号求交」：候选窄时相关的几条排不进全表前 top_k | 改用 `ctx.retrieval.search(..., restrict_ids=候选编号)`（精确近邻，候选内召回完整；需 `paxsz-forge-core ≥ 0.3.5` / `paxsz-forge-data ≥ 0.3.1`）；验收用窄条件测 |
| `restrict_ids` 传了编号却 0 条 | 编号与向量行 `id` 对不上：向量行 id 是**源表 id 列转 text**，传的却是别的列 / 拼了前缀 | 传 `manifest.vectorize` 的 `id_column` 那一列的值；float / 整串字符串会直接 `TypeError`，不会走到这里 |
| 换了 embedding 模型后结果变差 | 正常：换模型会触发一次全量重嵌，重嵌完成前新旧向量并存 | 等回填跑完，或手动 `forge jobs run` 催一轮 |

---

## 相关文档

- [04 权限与受控取数](04-permissions-and-data-access.md) —— 权限透传规则、`ctx.data`/`ctx.retrieval` 红线
- [06 forge CLI 速查](06-cli-reference.md) —— 业务仓本地能跑的命令
- [07 能力 Profile 指引](07-capability-profiles.md) —— `semantic-retrieval` / `governance-etl` 的声明/依赖/代码/DoD
- [08 发布与装配触发](08-release-and-assembly.md) —— 发测试包 / 正式包

> B 轨那几步的运维侧操作手册在**平台仓**（服务器命令手册），你仓里读不到——那几步本来就不归你做，
> 需要时找平台方。

> **存量业务仓拿不到本文的更新**：`docs/dev/` 是平台仓的单一信源，建仓时经
> `scripts/create_module.py` 快照进业务仓。已经建好的仓需要从平台仓重新落盘一次
> （`docs/dev/` 整目录覆盖），否则看到的仍是建仓那天的版本。
