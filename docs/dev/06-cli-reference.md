# 06 · forge CLI 速查（业务模块仓本地）

`forge` 命令随 `paxsz-forge-platform`（业务模块的 **dev 依赖**）安装。统一用 `uv run forge <command>` 调用。

**本篇只收「在你的业务模块仓本地跑」的命令。** 有一批 `forge` 子命令是**平台服务器运维**用的
（`config check-env`、`admin reset-password`、`profiles refresh-all`、`migrate dify-history`、
`history dedupe`），它们要读平台机的 `config/.env`（PG 连接、INFO 凭据）才跑得起来，在业务仓
本地既跑不通也没有意义——那些收在平台仓的服务器命令手册里，由平台方运维使用。

三类命令场景（本地业务仓 / 本地平台仓 / 平台服务器）的完整地图在平台仓，需要时找平台方。

> 🤖 标记 = **日常由 CI 自动跑**，不必手敲；列出来是为了让你知道流水线在做什么、以及需要时怎么本地复现。

| 命令 | 什么时候用 |
|---|---|
| [`dev serve`](#dev--开发工具) | 天天用：起本地迷你平台调自己的模块 |
| [`modules list`](#modules--模块) | 确认模块被 entry-point 发现了 |
| [`capabilities pull` / `export`](#capabilities--能力签名快照) | 用了别的模块的能力（拉对方签名写契约测试）/ 提供能力给别人（导出自己的签名）；`pull --check` 🤖 CI 查签名漂移 |
| [`jobs list` / `run` / `serve`](#jobs--定时任务) | 写了 ETL / 向量化回填时 |
| [`vectorize ddl`](#vectorize--声明式向量化semantic-retrieval) | 声明了 `manifest.vectorize` 后生成建表 DDL |
| [`eval routing`](#eval--路由评测) | 🤖 写完 `intents` 跑冒烟；CI 门禁 |
| [`data check`](#data--数据源冒烟g1-收口仅内网) | 🤖 CI 在内网跑；**你本机通常跑不了**（没有数据库账号，这是有意的） |

## dev —— 开发工具

```bash
uv run forge dev serve [--host 127.0.0.1] [--port 8090] [--tree <授权树JSON>] [--capability-stubs <快照目录>]
```

起本地迷你平台（dev harness）+ 轻量 dev console（`/ui`，debug chat + trace 视图）。
`--tree` 缺省时**授权全部已装配模块**（本地开发免配授权）；要模拟真实授权就传一份授权树 JSON。

### 本地能力桩 `--capability-stubs`

你的模块调别的模块的能力（`ctx.bus.invoke`）时，对方的 wheel 不在你的仓里，本地一调就是「模块未装配」。
给 dev serve 一个签名快照目录，它为每个被调方注册一个**本地桩**：

```bash
uv run forge capabilities pull                                  # 先把对方的签名拉进 tests/contracts/（见下节）
uv run forge dev serve --capability-stubs tests/contracts
```

```text
[forge dev] 本地能力桩 MATERIAL_QUERY 物料查询助手（桩）
    stock_by_part_numbers@v1  ← tests/contracts/fixtures/MATERIAL_QUERY.stock_by_part_numbers.v1.json
    lead_time@v1  无 fixture，返回空行集（tests/contracts/fixtures/MATERIAL_QUERY.lead_time.v1.json）
```

- 桩按快照里的签名**校实参、校返回**，与线上总线同一道校验：返回的是 `tests/contracts/fixtures/
  <被调方编码>.<能力名>.v<版本>.json` 里你写的数据（格式见仓内 `tests/contracts/README.md`），**数据不合
  对方签名同样报 `CAPABILITY_RESULT_INVALID`**。没有 fixture 的能力返回带列声明的空行集。
- fixture 每次被调到时现读，改了不用重启；启动时逐个体检，不合签名、文件名对不上任何能力的都会提示。
- Console 模块页里桩的来源显示「本地桩」，名字带「（桩）」，同样有「试调用」按钮（直调返回 fixture）。
- 桩**不参与自动路由**：不带 target 的问题照旧直达你自己的模块，桩只经 `ctx.bus.invoke` 被调到。
- 你的仓里若真装了同编码的模块，**真模块优先**，桩不注册（启动时提示）。
- 给了 `--tree` 时，授权树里要带上桩的编码——总线照常校验「用户有没有被授权访问被调方」。
- 快照读不进来（目录不存在、被手改过）直接退出，不会带着缺桩的注册表起来。

桩只回放你编的样例数据，验的是**你这一侧**的链路（调没调、实参对不对、拿到数据后怎么答）。对方口径对不对，
要在测试环境用真数据看（[10 自动化测试](10-automated-testing.md) 的 `/test/chat` + `trace.invocations`）。

日志相关环境变量（排错时用，详见 [01 · 排错：看日志](01-getting-started.md#排错卡住了或没反应时看日志)）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `FORGE_LOG_LEVEL` | `info` | `critical`(=`fatal`)/`error`/`warning`/`info`/`debug`，别名 `crit`/`err`/`warn` 也认 |
| `FORGE_LOG_PAYLOADS` | `auto` | 原始报文（SQL 全文、prompt、HTTP body）。`auto`=跟随级别（debug 即开）；`off`/`truncated`/`full` 可显式控制。开启时落 `runtime/logs/payload-*.log`，**含真实业务数据** |
| `FORGE_LOG_FORMAT` | `console` | `console`（人读）/ `json`（喂 `jq`）|
| `FORGE_LOG_QUEUE` | `true` | 日志渲染与写盘走独立线程。仅排查日志管道本身时才关 |

## modules —— 模块

```bash
uv run forge modules list          # 列出当前已装配（entry-points 发现）的模块
```

看不到自己的模块 = entry-point 没注册成功（`pyproject.toml` 的 `[project.entry-points."forge.modules"]`
写错，或改完没重跑 `uv sync`）。这是「模块跑不起来」最常见的第一现场。

## capabilities —— 能力签名快照

模块间能力调用（`ctx.bus.invoke`）的契约以 JSON 快照的形态在两个仓之间流通：调用方把被调方的签名
提交进自己仓的 `tests/contracts/`，契约测试 `ContractBus` 读它（见 [02 · 测试模式](02-sdk-reference.md#测试模式)）。
两个仓之间**只有这份数据文件，没有代码依赖**。

> 旧版 `paxsz-forge-platform` 没有这个命令（报 `invalid choice: 'capabilities'`），升级 dev 依赖即可；
> `pull` 还要求目标平台已提供 `GET /test/capabilities`（旧平台会报「平台版本早于该端点」）。

```bash
# 调用方仓（manifest.capability_deps 非空）
uv run forge capabilities pull                     # 拉取并写入 tests/contracts/<被调方编码>.json
uv run forge capabilities pull --check             # 🤖 只比对不写：签名漂移即 exit 1（CI 用）
uv run forge capabilities pull --module <编码>     # 仓里有多个模块时只看这一个调用方
uv run forge capabilities pull --out <目录>        # 换快照目录（缺省 tests/contracts）

# 被调方仓（manifest.capabilities 非空）
uv run forge capabilities export                   # 自己的签名输出到 stdout
uv run forge capabilities export --out <目录>      # 写成 <目录>/<编码>.json
```

**pull**：汇总本地模块的 `capability_deps`，向平台 `GET /test/capabilities`（见
[10 §3.6](10-automated-testing.md)）要被调方的签名，每个被调方写一个文件，**只含你引用到的能力**。

- 平台地址与 key 缺省读 `FORGE_TEST_BASE_URL` / `FORGE_TEST_API_KEY`（与 `scripts/qa_test.py` 同名，
  `.env` 里配一次两处共用），也可 `--base-url` / `--api-key` 显式给。key 授权**你自己的模块**即可，
  你依赖的模块自动在可达范围内。
- **签名没变就不重写文件**：判断看显示名与每个能力的完整签名（含说明文字），不看导出时间 / 来源 /
  对方 wheel 版本。所以反复 pull 不会让入库的快照出无意义的 diff。
- 签名变了会逐条列出哪里变了（`返回列 qty：integer → number`、`新增参数 plant（string，必填）`），
  并标出是**兼容变更**（只新增了返回列 / 可选参数：你的代码不用改）还是**破坏性变更**（其余一切）。
  **先改代码跟上、再连同快照一起提交**。
- 目录里有不再被任何依赖引用的快照：只警告，不替你删。

**`--check`** 不写任何文件，只和已入库的快照比对：

| 情况 | 结果 |
|---|---|
| 签名一致 | ✓，exit 0 |
| 只有说明文字 / 显示名不同 | ⚠ 警告，exit 0（指纹不含说明，改说明不该让你的 CI 变红） |
| 签名变了（参数 / 返回列的名称、类型、数组、必填） | ✗ exit 1（兼容变更同样失败：快照是你的书面记录，漂移就得重新 pull；输出里标明兼容 / 破坏性） |
| 你引用的能力平台上没有 / 快照文件缺失 / 快照被手改过 | ✗ exit 1 |
| 连不上平台、key 无效或过期 | ✗ exit 1（打印平台给的错误码） |

接进 CI：模板生成的仓**已自带** `contracts-check` job（MR 上、仓里有 `tests/contracts/*.json` 才跑）。
存量仓照下面加一个（凭据同 [10 §6](10-automated-testing.md)，`FORGE_TEST_BASE_URL` / `FORGE_TEST_API_KEY`
配成 CI/CD Variables）：

```yaml
contracts-check:
  stage: check
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      exists:
        - tests/contracts/*.json
  script:
    - uv sync --all-groups
    - uv run forge capabilities pull --check
```

key 勾了 Protect variable 时，feature 分支的 MR 流水线拿不到它——模板里的 job 这时跳过（不是失败），
develop → main 的 MR 照常检查。

**「平台上拿不到 X 的签名」**：可达范围是 key 授权的模块及其依赖闭包，而闭包按**平台上装配的**你那一版
manifest 算——刚加的依赖要等你的新版本装配上测试环境才进得来。等不及就请对方 `export` 一份给你。
输出末尾若还列了「这把 key 授权的模块在平台上没在服务」，那才是真因：多半是对方删了你依赖的能力，
平台把**你的模块**隔离了。

**export**：从本地注册表导出你提供的能力（全量，不按任何调用方裁剪），不连平台、不连库。用于对方还没
装配上平台、或平台上还是旧版本时，把签名先交给调用方。stdout 只输出一份快照（本地有多个模块提供能力时用
`--module` 选一个，或用 `--out`）；**写文件优先用 `--out`**——它按字节写、恒 LF，签名没变不重写。

## jobs —— 定时任务

```bash
uv run forge jobs list             # 列出任务与生效 cron
uv run forge jobs run <name>       # 手动执行一次任务（name = <模块编码>.<job名>）
uv run forge jobs serve            # 启动 jobs worker（APScheduler 常驻调度 + Console 手动触发队列 + 后台导出任务）
```

任务两个来源：模块 `jobs()` 自己注册的（治理 ETL 等），+ 平台按 `manifest.vectorize` **生成**的
向量化回填（名为 `<模块编码>.vectorize:<向量表>`，见下）。两者在 `list` / `run` / 调度里一视同仁，
cron 都可经 `FORGE_JOB_CRON_OVERRIDES` 覆盖。

`run` 跑的过程中会**打印进度**（约 2 秒一次，终端下原地刷新，重定向到文件则逐行追加）：

```text
[forge jobs] KB.vectorize:issues_vec 1200/2860（42%） 向量化回填 issues_vec，已用 96s
```

进度**走 stderr**，stdout 仍然只有结束时那份结果 JSON（管道里的脚本不受影响）。
数字来自任务自己的 `ctx.progress(...)`（见 [02 §定时任务](02-sdk-reference.md#定时任务-forge_corejobs)）：
不上报的任务这里如实打「该任务未上报进度，已用 Ns」，不会编一个百分比出来；向量化回填自带进度。
Admin Console 任务页显示的是同一份进度。

> **要落数的 job 必须在 jobs worker 进程里跑**（本命令就是）：写连接只在那个进程构造
> （该源的 `write_user`/`write_password_env`），别的进程没有写句柄，落数 job 在那里会 fail-closed。
> 生产上同理，由平台方在服务器执行；平台 Console 任务页的「运行」按钮也是排队交给 jobs worker 跑的，
> 不是在网关里就地执行。

## vectorize —— 声明式向量化（semantic-retrieval）

```bash
uv run forge vectorize ddl                      # 打印向量表 DDL
uv run forge vectorize ddl --module <模块编码>   # 同上，显式限定模块
```

按 `manifest.vectorize` 生成建表 + HNSW 索引 + 每个 scope 列与 `metadata_columns` 列的 btree 索引 DDL。
**scope 列由平台从 `manifest.field_mappings` 自动算出**——这正是重点：建表、回填 SQL、
启动期校验三处的列定义同一个信源，不会漂移。**别手写向量表 DDL**，手写等于把「scope 列该有
哪些」又交回给人记。
⚠️ 全部语句都是 `IF NOT EXISTS`：**给已存在的向量表新增 `metadata_columns` 不会被它补上**，
需手工 `ALTER TABLE … ADD COLUMN … text` + 建 btree 并重跑回填，否则平台启动期隔离该模块（见 [11](11-vectorization-and-governance.md) 排查表）。

> **在你仓里，带不带 `--module` 输出一模一样**。缺省是「打印全部已装配模块」，而业务仓的 venv 里
> 只装配了你自己一个模块（`pyproject.toml` 只注册一个 entry point；平台内置的 EchoModule 没有
> `vectorize` 声明，不产出任何 DDL）。**别以为仓里还有别人的模块**——「全部已装配模块」是平台
> 服务器上才有多个的说法。

**这条命令只打印、不连库**（你本机也连不到 mart 库）。真正建表由平台运维在服务器上跑
`forge vectorize apply`，走正常装配链路时由部署脚本自动执行。
→ **完整时序（谁在哪台机器上按什么顺序做什么）见 [11 mart 库模块端到端时序](11-vectorization-and-governance.md)**；
声明怎么写见 [07 · semantic-retrieval](07-capability-profiles.md)。

## eval —— 路由评测

```bash
uv run forge eval routing [--dataset <JSON>] [--threshold 0.9] [--use-intents]
```

🤖 也是 CI 门禁：accuracy 低于阈值退出非零。不给 `--dataset` 时自动启用 `--use-intents`
（拿各模块 `manifest.intents` 当冒烟集）。写好 intents 后可直接跑冒烟。

平台仓另有一份落盘基线 `evalsets/routing-baseline.json`（撞车与跨域回归集，绑定存量 13 个模块）：

```bash
uv run forge eval routing --dataset evalsets/routing-baseline.json --use-intents --threshold 0.9
```

> ⚠️ **未配 `FORGE_LLM_BASE_URL` 时评的只是关键词兜底那一格**，而基线里大半条目正是「只有
> 语义答得对」的题——离线跑分低是预期，不是回归。要当门禁必须在配好本地 Qwen 的环境里跑。
> 关键词自 2026-09-03 起**不再抢在语义之前**（平台决策「关键词路由降级为信号」），
> 所以 `keywords` 写得糙不再会把问题一票路由错，但仍决定 LLM 故障期的兜底质量——**别拿泛词
> 占坑**（「部门」「通用」「分布」这类两字词平台挡不住）。

## data —— 数据源冒烟（G1 收口，仅内网）

```bash
uv run forge data check [--strict] [--source <别名>]... [--db-description-dir <目录>]
```

G1 收口检查：据 `docs/2_landed/db_description/*.md` 声明，验证 **info/erp 可达**（`SELECT 1`）+ 声明的
**表/字段在库中真实存在**（查 `information_schema`）。只读元数据、不碰业务数据行。默认 **advisory**
（打印报告、退出 0）；`--strict` 时任一不可达/表列缺失即退出非零。`--source` 限定只探哪些别名
（缺省 = db_description 声明的源）。

表坐标优先取文件内的 `- **物理表名（table）**：库.schema.表` 一行；没有这一行才从文件名拆——文件名里出现 `dbo` /
`public` 段时以它为界（`db_UFDATA_999_2021_dbo_Vendor.md` → `UFDATA_999_2021.dbo.Vendor`），否则按
「前两段是库和 schema」拆。**表族**文件（同构分库/动态分表一族一份，带 `- **表族（family）**：…` 声明）
只校验文件指定的代表成员，报告里该表带 `family` / `family_note` 字段。约定全文见模块仓
`docs/2_landed/db_description/README.md`。

> 🤖 **不用你本机跑、也跑不了**：日常由模块仓 MR 上的 `g1-datasource-check` job 执行（内网 runner、
> 元数据专用低权账号、凭据走 group 级 CI 变量）。**开发者不接触数据库账号是有意的设计**，不是缺失。
> 本地看到「连不上」属正常，看 CI 上那次的结果即可。

---

## release —— 发版（bump + commit + 打 tag + push）

```bash
uv run forge release --alpha              # 发下一个 alpha（--beta / --rc / --dev 同理）
uv run forge release --alpha --dry-run    # 只看会发哪个版本，不动任何东西
uv run forge release --alpha --no-push    # 只在本地打 tag（之后需自己 git push origin v0.1.0a1）
uv run forge release --alpha --yes        # 跳过交互确认（供脚本调用）
uv run forge release 0.1.0                # 正式版（须在 main 上）
```

**发预发布不用写版本号**：基线取自 `pyproject.toml`（那里始终是 `0.1.0` 这样的正式版号），序号取自
已有 tag。命令会先打印这次要发哪个版本、这条线已发过哪些，确认后才动手。

序号按「正式版 + 类型」分线，各自从 1 起（`0.1.0a*` 与 `0.2.0a*`、`0.1.0rc*` 互不干扰）。预发布号
只存在于 tag 指向的那个 commit 里、**不进任何分支**。完整规则见
[08 · 版本号规则](08-release-and-assembly.md#版本号规则读这一节就够)。

> **要连得上 GitLab**：命令开头先 `git fetch --tags --prune --prune-tags` 与远端对齐（顺带清掉
> 上次失败残留的本地孤儿 tag），再定序号；连不上就直接失败，不会拿本地 tag 凑合。访问远端时
> 不捕获输出，SSH 密钥密码提示会原样显示给你。中途失败会回滚已打的本地 tag。

> 也可以自己写全（`forge release 0.1.0a7`）补发特定序号，但**基线必须等于 `pyproject.toml` 的
> 版本号** —— 在 `0.1.0` 的分支上发 `0.9.0a1` 会被拒绝：换基线是「要进下一个正式版了」的决定，
> 得经 MR，不能由一条发版命令顺手完成。

**你的分支不会被改动**：预发布的 bump 提交做在 detached HEAD 上，命令跑完自动切回，工作区回到
发版前的样子。连发 a1/a2/a3 也不会在分支上积累任何 commit。

**为什么要用它而不是手敲三条命令**：wheel 的版本号只由 `pyproject.toml` 决定，tag 只是「声明要发
哪个版本」，两者必须一字不差。手敲时最容易漏掉 bump 那步 —— 2026-07-30 就真出过：两个人都只打了
tag、都没 bump，一个发出了版本号对不上的 wheel，另一个的 publish 因幂等跳过而**绿灯却什么都没发**，
最后都以「平台装配找不到版本」暴雷。本命令让版本号只写一次，从源头消除这个断层。

两条路径不对称（对齐 CI 的两道 tag 门禁）：

| 怎么发 | 分支要求 | bump 提交做在哪 | 推什么 |
|---|---|---|---|
| `--alpha` / `--beta` / `--rc` / `--dev` | 任意分支 | detached HEAD（**你的分支不动**） | 只推 tag，不推分支 |
| 正式版号 `0.1.0` | **必须 main**，且 pyproject **已经**是该版本 | 不产生提交 —— bump 须先经 MR 合入 main | 只推 tag |

> 要 `paxsz-forge-platform>=0.1.9`。低于 0.1.8 会报 `invalid choice: 'release'`（还没这个命令）；
> 0.1.8 有命令但在带密码的 SSH 密钥下会以 `permission denied` 静默失败、失败后残留本地 tag 让
> 版本号在重试中虚涨 —— 都在 0.1.9 修掉了。装不了新版就按下面那份文档里的手工步骤走。

完整发版流程（打什么 tag、平台侧怎么装配、正式环境的人工审核环、CI 会拦什么、存量仓怎么补上门禁）见
**[08 · 发布与装配触发](08-release-and-assembly.md)**。

## 平台服务器上的 forge 命令（你用不到，知道有就行）

`config check-env`（比对 `.env` 与模板）、`admin reset-password`、`profiles refresh-all`（工号→姓名/部门
批量回填）、`migrate dify-history`、`history dedupe`、`assembly *`——都在平台仓的服务器命令手册里，
需要时找平台方。你的模块在生产上跑出问题，通常先看平台 Admin Console 的审计页，而不是这些命令。
