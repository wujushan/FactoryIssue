# 01 · 从零上手 Getting Started

目标：10 分钟内建出一个业务模块仓、装上 SDK、用 dev harness 把它跑起来、curl 验证流式输出。
全程**离线可做**（不接内网模型/数据库；未配 LLM 时路由退化为关键词匹配 + 澄清引导）。

## 0. 前置

- Python 3.12（`>=3.12,<3.13`）
- [uv](https://docs.astral.sh/uv/)（包管理与虚拟环境）
- 能访问内网 GitLab Package Registry 的凭据（拉 `forge-*` 包用，见第 2 步）
- 可选：Node ≥ 22（仅当你要改 mini dev console 前端；平常不需要）

## 1. 建仓（用平台模板生成）

推荐用 bootstrap 脚手架（copier 生成 + `git init` + 建 `main`/`develop` + 切 `develop`）：

```bash
# 在平台仓目录下
python scripts/create_module.py <新业务仓目录>
# 或直接跑 copier
uvx copier copy <平台仓路径>/templates/module <新业务仓目录> --trust
```

生成时会问模块编码/名称/描述等。以 `SALES_QUERY`（销售查询）为例，生成后你得到：

```
sales-query/
  pyproject.toml            # 已含 paxsz-forge-core 依赖 + entry point + Registry index
  src/sales_query/module.py # 模块骨架（待你实现 handle）
  tests/test_module.py
  tests/test_contracts.py   # 模块间能力调用的契约测试骨架（用不到时整体 skip）
  tests/contracts/          # 被调方的签名快照 + 本地桩数据（用到能力调用时才有内容）
  docs/                     # G 流程落盘目录（2_landed / testcases / decisions / open-questions）
  docs/dev/                 # SDK 权威文档快照（脚手架从平台仓 docs/dev 落盘，供本仓开发者/AI 离线查阅）
  CLAUDE.md / AGENTS.md     # 给编程助手的工作指引（G 流程 v2）
  .gitlab-ci.yml            # MR 门禁 + tag 发 wheel
```

> 用 `scripts/create_module.py` 建仓时，会额外把平台仓 `docs/dev/`（就是你正在读的这套文档）落盘到新仓 `docs/dev/`，
> 并在 README/CLAUDE/AGENTS 里加好指引；随后引导你输入 Deploy Token 环境变量、当场 `uv sync` 拉包（见第 2 步）。
> 直接跑 `copier copy` 则不含这两步，需手工落盘文档与配 index/鉴权。

> **entry point 命名规则**（模板已生成，改模块类名时要对齐）：编码 `SALES_QUERY` → 类名 `SalesQueryModule`，`pyproject.toml` 里：
> ```toml
> [project.entry-points."forge.modules"]
> SALES_QUERY = "sales_query.module:SalesQueryModule"
> ```

## 2. 装 SDK（配好 Registry 鉴权）

因 GitLab「Allow anyone to pull」保持关闭（数据留内网红线），拉包**必须鉴权**。用 Deploy Token（与人无关、可回收），把凭据按 index 名注入环境变量——**不要写进仓库**：

```bash
# 变量名规则：UV_INDEX_<index名大写、'-'换'_'>_USERNAME / _PASSWORD，index 名固定为 dataforge-sdk
export UV_INDEX_DATAFORGE_SDK_USERNAME="<deploy-token-username>"
export UV_INDEX_DATAFORGE_SDK_PASSWORD="<deploy-token>"

cd sales-query
uv sync
```

> 用 `scripts/create_module.py` 建仓时不必手动 export：脚手架会**提示你输入这两个值**并当场 `uv sync`
> （凭据只注入那一次子进程、不写入仓库/shell）。手动或换机器时才需上面的 `export`。

**「index 名」到底指什么、要和哪里一致？** index 名 = `pyproject.toml` 里 `[[tool.uv.index]]` 的 `name`（此处固定 `dataforge-sdk`），
是一个**纯 uv 本地标识**，只出现、且必须彼此一致的地方就两处：

1. `pyproject.toml` 的 `[[tool.uv.index]] name = "dataforge-sdk"`；
2. 鉴权环境变量名 `UV_INDEX_DATAFORGE_SDK_USERNAME/_PASSWORD`（uv 规则：index 名大写、非字母数字换 `_`，加前缀 `UV_INDEX_`）。

它**不出现在 GitLab 上**——GitLab 只认 index url 里的**数字项目 ID** 与 Deploy Token 的**用户名/口令**；GitLab 上的
Deploy Token 名称、项目名都与这个 index 名无关，可任意取。改 index 名（一般不需要）就得同步改上面两处。

模板 `pyproject.toml` 里已经有（生成时填了 gitlab_url / 项目 ID 就自动写好；**内网无 https，url 用 `http://`**）：

```toml
[[tool.uv.index]]
name = "dataforge-sdk"
url = "http://<内网gitlab>/api/v4/projects/<平台仓项目ID>/packages/pypi/simple"
explicit = true                     # 只服务下方 sources 钉到本 index 的 paxsz-forge-*

# paxsz-forge-* 只从内网 registry 取；其它包（pytest/httpx…）走默认源，绝不查内网
[tool.uv.sources]
paxsz-forge-core = { index = "dataforge-sdk" }
paxsz-forge-data = { index = "dataforge-sdk" }
paxsz-forge-sandbox = { index = "dataforge-sdk" }
paxsz-forge-governance = { index = "dataforge-sdk" }
paxsz-forge-platform = { index = "dataforge-sdk" }
```

（分发名带 `paxsz-` 私有命名空间前缀，import 名仍是 `forge_core` 等——两者由各包 wheel target 桥接。）

**为什么要 `explicit = true` + `[tool.uv.sources]`（包路由）？** 内网 GitLab 只发布了 `paxsz-forge-*`，
公网包（`pytest-asyncio`、`httpx` 等）在内网 registry 必然取不到。若只配 `[[tool.uv.index]]` 不钉路由，uv 默认
`first-index` 策略会**对每个包先查内网 registry**、404 再回落到公网源——于是日志里会看到内网 url 拼上 `pytest-asyncio`
这类公网包名。用 `explicit = true` 把内网 index 标成「仅服务被显式钉的包」，再在 `[tool.uv.sources]` 把 `paxsz-forge-*`
钉过去，就实现了：**`paxsz-forge-*` 只走内网 `http://code.paxsz.com`，其余一切包直接走默认源（公网 PyPI 或其镜像），
彼此不越界**。新增 `paxsz-forge-*` 依赖时记得在 `sources` 补一行（钉了但没用到的行 uv 会忽略、不报警）。

> **⚠ 传递依赖也要显式直接声明**：`[tool.uv.sources]` 的内网源路由**只对直接依赖生效，对「依赖的依赖」不生效**。
> 所以一个 `paxsz-forge-*` 若只作为另一个 `paxsz-forge-*` 的传递依赖出现（典型：`paxsz-forge-platform` 传递依赖
> `paxsz-forge-core` / `paxsz-forge-data` / `paxsz-forge-sandbox`），它不会被路由到内网源，会被 uv 拿去默认公网源解析而 404。
> 规则：把本模块 `paxsz-forge-*` 依赖的**传递闭包**都补成**直接依赖**（`[project].dependencies` 或 `dependency-groups`）。
> 模板已按此把 `paxsz-forge-sandbox` 补进 dev 组；将来某个 `paxsz-forge-*` 新增传递依赖时，同样把新出现的补为直接依赖。

> 顺带解释「url 末尾多出包名」：`.../pypi/simple` 是 PyPI Simple 索引（PEP 503）的**根**，uv/pip 解析某个包时会把
> 包名拼成子路径 `<根>/<包名>/` 去取其可下载文件列表——发布页给的是根地址、工具内部逐包追加包名，这个**形状**本身正常。
> 但**公网包名出现在内网 registry 的 url 后**，恰恰是上面「没钉路由」的征兆；钉好后内网 registry 只会被 `forge-*` 命中。
> 另注意协议：日志若是 `https` 而内网只有 `http`，那是连不上的根因——确认 url 是 `http://`（本模板已按 `gitlab_url` 生成）。

> 默认源需可达：`paxsz-forge-*` 之外的包从**默认源**取，所以运行 `uv sync` 的机器（开发机 / CI runner）要能访问公网 PyPI
> 或公司内部 PyPI 镜像。若默认源不是公网 PyPI，用 `UV_DEFAULT_INDEX` / `--default-index` 指到镜像即可（不影响 `paxsz-forge-*` 路由）。

> 若框架当前只发布了**预发布版**（如 `0.1.0a1`），uv 默认不选预发布。要么精确钉版本
> `dependencies = ["paxsz-forge-core==0.1.0a1"]`，要么 `uv sync --prerelease=allow`。正式版发布后去掉即可。

### 升级 SDK 版本（已建好的仓）

**结论先给**：通常**不需要改 `pyproject.toml` 的版本号**，但**只跑 `uv sync` 也升不上去**——要带 `--upgrade-package`。

两件事各管一半：

- `pyproject.toml` 里写的是**下界**（`paxsz-forge-core>=0.1.2`）。平台仓 bump 小版本时**刻意不抬下界**，
  免得把存量业务仓卡在必须升级上——`>=0.1.2` 本来就能解析到 0.1.3、0.2.0。所以版本号一般不用动。
- `uv.lock`（建仓时生成、已提交）钉的是**精确版本**。`uv sync` 的职责是「让环境符合锁文件」，
  它**不会**去 registry 找新版——这也正是锁文件存在的意义。要升级就得先让 uv 重新解析。

```bash
# 拉包凭据同第 2 步（换机器/新 shell 才需要重新 export）
export UV_INDEX_DATAFORGE_SDK_USERNAME="<deploy-token-username>"
export UV_INDEX_DATAFORGE_SDK_PASSWORD="<deploy-token>"

uv sync --upgrade-package paxsz-forge-core \
        --upgrade-package paxsz-forge-platform \
        --upgrade-package paxsz-forge-data \
        --upgrade-package paxsz-forge-sandbox
```

`uv sync` 接受 resolver 的 `--upgrade-package`（简写 `-P`），会先重解析锁文件再同步环境；
想拆两步就 `uv lock --upgrade-package ...` 再 `uv sync`。只升某一个包时只写那一个即可。

几个容易踩的点：

- **别用裸 `uv lock --upgrade`**——那会把 pytest/httpx 等所有第三方依赖一并升级，改动面远超「升 SDK」的本意。逐包指定。
- **升完提交 `uv.lock`**，否则 CI 和其他开发机仍停在旧版本，出现「我本地好的」类问题。
- **只有代码真的依赖新版 API 时才改 `pyproject.toml`**：把 `>=0.1.2` 抬成 `>=0.1.3`，让依赖约束诚实反映代码要求。
  单纯想吃新版不必改。
- **前提是新版 wheel 已发到 registry**。平台仓 commit 里 bump 了版本号 ≠ 包已发布——还要打 `<pkg>-sdk-v<版本>` tag
  触发 CI 发 wheel（**平台方操作**）。升不到新版时先找平台方确认新版是否已发到 Registry。
- 升级只换 SDK 代码，**不会更新本仓 `docs/dev/` 快照**（那是建仓时的一次性拷贝）。需要同步文档时从平台仓
  `docs/dev/` 重新落盘。

## 3. 实现最小模块

编辑 `src/sales_query/module.py`。一个模块 = 一个 `ModuleManifest` + 一个 `handle()` async generator：

```python
from collections.abc import AsyncIterator

from forge_core import Event, ForgeModule, ModuleContext, ModuleManifest, ModuleRequest


class SalesQueryModule(ForgeModule):
    manifest = ModuleManifest(
        code="SALES_QUERY",
        name="销售查询",
        description="按区域/时间查询销售数据",
        intents=["查销售额", "本月华东区销量", "销售同比"],   # 路由分类/rerank 素材
        keywords=["销售", "销量", "销售额"],                    # 仅 LLM 分类器弃权时的兜底
    )

    async def handle(
        self, request: ModuleRequest, ctx: ModuleContext
    ) -> AsyncIterator[Event]:
        yield Event.progress("start", "开始处理")
        # 这里先回显；真实模块在此取数（ctx.data）、算数（沙箱）、调 LLM（ctx.llm）
        yield Event.delta(f"收到你的问题：{request.query}")
        # 注意：END 事件由平台网关统一补发，模块内部不要自己 yield Event.end()
```

关键约定：

- `handle` 是 **async generator**（`async def` + `yield`），流式产出 [`Event`](03-events-and-streaming.md)。
- **不要**在模块里 `yield Event.end()`——END 由平台补发（每次请求恰好一个）。
- 模块之间有两条通道，都要先在 manifest 声明、未声明的调用会被总线拒绝：问答式转调声明
  `manifest.dependencies`（`ctx.bus.call`，收事件流）；取**结构化数据**做再加工声明
  `manifest.capability_deps`（`ctx.bus.invoke`，收带连接键的行集）。见 [02](02-sdk-reference.md)。
  调别的模块的能力时，对方的 wheel 不在你的仓里：先 `uv run forge capabilities pull` 把对方的签名快照拉进
  `tests/contracts/`，单测用 `ContractBus` 按快照写契约测试（[02 · 测试模式](02-sdk-reference.md#测试模式)），
  本地起平台用 `forge dev serve --capability-stubs tests/contracts` 让对方以**本地桩**在线（见 §4）。

## 4. 本地跑起来（dev harness）

`forge dev serve` 起一个本地迷你平台 + 轻量 dev console（`/ui`，含 debug chat + trace 视图），**自动授权当前模块**（免配授权树）：

```bash
uv run forge dev serve                # 默认 127.0.0.1:8090
uv run forge dev serve --port 8123    # 指定运行端口（--host 改绑定地址；端口占用/多模块并行时用）
```

打开 http://127.0.0.1:8090/ui/（换成你的端口）用 debug chat 直接对话并看 trace；或用 curl 验证 SSE 流：

```bash
curl -N -X POST http://127.0.0.1:8090/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"查一下本月销售额", "user_id":"dev", "target":"SALES_QUERY"}'
```

你会看到 `event: progress` / `event: delta` / `event: end` 一路流出来。

> 未配 `FORGE_LLM_BASE_URL` 时路由退化为关键词匹配 + 澄清引导；`target` 显式指定目标模块可跳过路由，
> 适合单模块联调。

你的模块被业务页面调用（自动审核、填单助手……）、在 `manifest.tasks` 里声明了任务？用任务面入口联调，
请求体与上面相同，只是 `target` 与 `ext_param.task` 必填（见 [02 · SDK 参考](02-sdk-reference.md#任务面-v2tasks-与-manifesttasks)）：

```bash
curl -N -X POST http://127.0.0.1:8090/v2/tasks \
  -H 'Content-Type: application/json' \
  -d '{"query":"<待审核的单据正文>", "user_id":"dev", "target":"SALES_QUERY", "ext_param":{"task":"review_order"}}'
```

> 本地 dev serve 用的是全放开的旁路授权树，`data_scope` 声明在本地看不出区别——它的效果只在接了 INFO
> 的平台上体现。

你的模块调了别的模块的能力（`capability_deps`）？对方不在你的仓里，本地一调就是「模块未装配」。
加 `--capability-stubs tests/contracts`，dev serve 按你入库的签名快照给对方起一个**本地桩**，回放
`tests/contracts/fixtures/` 里你写的样例数据（照样按对方签名校验）；桩不抢路由，问题照旧直达你的模块。
详见 [06 · dev serve](06-cli-reference.md#dev--开发工具)。

### 排错：卡住了或没反应时看日志

`forge dev serve` 的日志直接打在终端。每条都带 `module`（你的模块编码）、`request_id`、
`conversation_id`，一轮问答从头到尾可追。**每个可能卡住的环节都有「开工」标记**，找哪一步没
回来就看哪个 `*_started` 没有配对的完成态：

| 有 `_started` 没有完成态 | 卡在哪 |
|---|---|
| `turn_started` 之后什么都没有 | 路由（要调一次本地模型）|
| `llm_call_started` | 本地 Qwen 没返回 |
| `query_started` | 那条 SQL（`sql_fp` 是它的指纹，可去归档 `queries.json` 翻全文）|
| `remote_call_started` | 上游 Dify 应用没返回 |
| `dispatch_entry` 之后什么都没有 | 你的 `handle()` 里（该加日志的地方到了）|

```bash
FORGE_LOG_LEVEL=debug uv run forge dev serve    # 更细的判定明细
```

⚠️ **`debug` 同时会打开「原始报文」**（SQL 全文与参数、LLM prompt 与输出、HTTP 请求体），
落在 `runtime/logs/payload-gateway.log`（JSON，`jq` 可读；不进终端是因为它太吵）。
只想要流程明细不想要正文：再加 `FORGE_LOG_PAYLOADS=off`。

**这些文件含真实业务数据**（本机开发无所谓，但别把它们提交进仓库——模板的 `.gitignore` 已排除
`runtime/`）。生产环境上开这个开关有额外纪律，由平台方掌握。

## 5. 测试

```bash
uv run pytest        # 模板已带 tests/test_module.py 骨架
uv run ruff check
```

模块单测直接构造 `ModuleRequest` + 一个最小 `ModuleContext`，把 `handle()` 产出的事件收集起来断言即可（模式见 [02 · SDK 参考](02-sdk-reference.md#测试模式) 末尾）。

## 6. 接下来

- 真正的业务逻辑先走 **G 流程 v2**（G1 业务落盘 → G2 数据勘察 → G3 测试集 → **G4a 技术设计 →
  G4b 编码** → G5 评测 → G6 发布），见仓内 `README.md` 与 `CLAUDE.md`。G1 未过闸门时 guard hook
  会硬拦编码；**G4a 无 guard**，但 `field_mappings` 这类「错了不报错、只是拒查或越权」的决策
  就该先有一份能被人看一眼的设计稿（模板在仓内 `docs/decisions/README.md`）。
- 要取数/检索 → 读 [04 · 权限与受控取数](04-permissions-and-data-access.md)。
- 要发布上线 → `uv run forge release --alpha`（版本号不用写，基线取自 `pyproject.toml`、序号自动接续；bump + 打 tag + push 一步到位），CI 发 wheel，平台按装配清单更新。完整流程与 CI 的两道 tag 门禁见 [08 · 发布与装配触发](08-release-and-assembly.md)。
- **每个 clone 记得跑一次 `python scripts/install_hooks.py`** —— 装上 pre-push 钩子，推 `v*` tag 前先在本地校验「tag 版本 == pyproject 版本」，省掉推上去才发现、还得删远端 tag 那一圈。
