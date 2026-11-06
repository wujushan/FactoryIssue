# 08 发布与装配触发（发测试包 / 发正式包）

> 面向**业务模块仓开发者**：你在业务仓打一个版本 tag 之后，wheel 怎么发、平台测试/正式运行环境怎么随之更新，全流程在此。
>
> 一句话分工：**业务仓 CI 只负责「发布 wheel」；把 wheel 装进平台运行环境是平台侧「装配驱动」**——两件事解耦。你打 tag 触发发布，平台侧按环境把对应版本装进去（**测试环境自动、正式环境需平台仓管理员手动确认**）。
>
> ⚠️ 别和「平台 SDK 五包发布」搞混：那是平台仓把 `paxsz-forge-*` 发到 Registry 供你 `uv sync` 依赖（见 [升级 SDK 版本](01-getting-started.md#升级-sdk-版本已建好的仓)）。**本文说的是你的业务模块打 tag 发自己那一个 wheel。**

## 测试包 vs 正式包：由版本号后缀决定

你发的是「测试包」还是「正式包」，**不看 tag 打在哪个分支，只看版本号有没有预发布后缀**：

| 版本号 | tag 例 | 算什么 | 去哪个平台环境 | 是否自动 |
|---|---|---|---|---|
| 带 `aN` / `bN` / `rcN` / `.devN` 后缀 | `v0.1.0a1` | 预发布（**测试包**） | 平台**测试环境** | ✅ 自动装配 |
| 基础三段 `X.Y.Z`、无后缀 | `v0.1.0` | 正式（**生产包**） | 平台**正式环境** | ⛔ 平台仓管理员**手动确认**后才装 |

> tag 必须匹配 `v` + [PEP 440](https://peps.python.org/pep-0440/)：正则为 `^v\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?$`。不匹配的 tag 既不建流水线、也不发布（见本仓 `.gitlab-ci.yml` 的 `workflow.rules`）。各段位数不限（`v0.10.2`、`v0.1.0a12` 均合法）。
>
> ⚠️ 版本号必须写 **PEP 440 规范形式**：`0.1.0a1` ✅，`0.1.0-alpha1` / `0.1.0.a1` ❌。后两种虽然 PEP 440 也认，但下面那道版本一致性门禁做的是**严格字符串比对**、不做归一化，写了就会被拦。用 `uv version` / `forge release` 设版本，写入的天然就是规范形式。

## ⛔ 一条铁律：tag 版本必须 == `pyproject.toml` 版本

**wheel 的版本号只由 `pyproject.toml` 决定，tag 只是「你声明要发哪个版本」。** 两者必须一字不差。

2026-07-30 真实踩过一次，两个人各踩一种，症状都是「平台装配失败」，但错因离现场很远：

| | 打的 tag | 忘了做的事 | 实际发生 |
|---|---|---|---|
| 开发者 A | `v0.0.1a1` | 没 bump，pyproject 停在 `0.1.0` | 发出去的 wheel 是 **0.1.0**，而平台被告知去装 `0.0.1a1` → 平台装配红灯 |
| 开发者 B | `v0.1.0a1` | 同上 | `0.1.0` 已被 A 发过 → `uv publish --check-url` 判定「版本已存在」而**幂等跳过** → **publish 绿灯却什么都没发**，平台照样找不到 `0.1.0a1` |

B 那条尤其阴险：CI 是绿的，看起来发成功了。**现在这两种都会在发布前被拦下**（见下方 §四门禁），
但最省事的做法是根本不给自己犯错的机会 —— 用 `forge release`，版本号只写一次：

```bash
uv run forge release --alpha     # 版本号根本不用你写，见下一节
```

---

## 版本号规则（读这一节就够）

### 规则一：分支上的版本号，永远是**正式版号**

`pyproject.toml` 里写的始终是「当前/下一个正式版」（如 `0.1.0`），**不带任何预发布后缀**。
预发布号（`0.1.0a1`）只在发版那一瞬间存在于 tag 指向的那个 commit 里，**不进任何分支**。

所以你在 develop 上随时看到的都是 `0.1.0`，哪怕已经发过 a1/a2/a3。这不是漏了改，是设计如此 ——
预发布号是一次性的试发标记，把它们逐个写进分支历史只会让「这个分支到底是什么版本」变得没法回答。

### 规则二：发预发布时，版本号完全不用你写

**基线取自 `pyproject.toml`，序号取自已有 tag** —— 你只说要发哪一类：

```bash
uv run forge release --alpha     # → 0.1.0a1、再跑 → 0.1.0a2、再跑 → 0.1.0a3
uv run forge release --rc        # → 0.1.0rc1（rc 是独立一条线，不受 alpha 影响）
uv run forge release --beta      # → 0.1.0b1
uv run forge release --dev       # → 0.1.0.dev1
```

命令会先打印**这次要发哪个版本**、**这条线已经发过哪些**，等你确认后才动手；不确定就加
`--dry-run` 先看一眼。

每个正式版号开一条**全新**的预发布线，互不干扰；同一正式版下 `a` / `b` / `rc` / `.dev` 也各自独立：

| `pyproject` 是 | 已发过 | `--alpha` 给你 | `--rc` 给你 |
|---|---|---|---|
| `0.1.0` | （空） | `0.1.0a1` | `0.1.0rc1` |
| `0.1.0` | `0.1.0a1` `0.1.0a2` | `0.1.0a3` | `0.1.0rc1` |
| `0.2.0`（经 MR 推进后） | `0.1.0a1`…`0.1.0a3` | `0.2.0a1` | `0.2.0rc1` |

序号取「已有最大值 **+1**」，不填空洞：手工跳号过（有 a1、a5）时下一个是 a6 而不是 a2 ——
填洞发出的 a2 内容比 a5 新却排在更前，任何按版本号排序的地方都会误导人。

> **发版必须连得上 GitLab。** 命令开头会先跑
> `git fetch --tags --prune --prune-tags origin` 把本地 tag 与远端对齐，再据此定序号：
> 队友发过的版本你不用先 fetch 也算得对，**上次 push 失败残留在本地的孤儿 tag 也会被清掉**
> （不清的话序号会在反复重试中一路虚涨）。
>
> 连不上就**直接失败**，不会退回「用本地 tag 凑合算一个」—— 那种降级等于在没有权威数据的
> 情况下编版本号。访问 GitLab 的 git 命令全程不捕获输出，所以 **SSH 密钥密码提示、账号口令
> 提问会原样出现在你面前**，git 的原始报错也照直显示。任何一步失败都会回滚：已打的本地 tag
> 会被删掉，工作分支不受影响，「这次什么都没发生」。

<details>
<summary>也可以自己写全版本号（<code>forge release 0.1.0a7</code>），但基线必须对得上</summary>

补发某个特定序号时可以写全。但**其基线必须等于 `pyproject.toml` 的版本号** —— 在
`pyproject = 0.1.0` 的分支上发 `0.9.0a1` 会被拒绝。

因为换基线意味着「我们要进下一个正式版了」，那是要经 MR 审的决定（规则三），不该由一条发版
命令顺手完成。否则测试环境会跑着 `0.9.0a1`，而代码库里从没有人审过这件事。

</details>

### 规则三：一个正式版的完整生命周期

| 时点 | 分支上的 `pyproject` | 你敲的命令 | 产生的 tag |
|---|---|---|---|
| 开发中，想验一版 | `0.1.0` | `forge release --alpha` | `v0.1.0a1` |
| 再验几版 | `0.1.0`（**没被改过**） | `forge release --alpha` | `v0.1.0a2`、`v0.1.0a3` |
| 准备转正 | `0.1.0` | `forge release --rc` | `v0.1.0rc1` |
| 发正式版 | `0.1.0` | 在 main 上 `forge release 0.1.0` | `v0.1.0` |
| 开下一轮 | 经 MR bump 到 `0.2.0` | —— | —— |

最后一行要留意：**正式版发完，分支上的版本号不会自己前进**。要开下一轮，得经 MR 把 `pyproject`
bump 到 `0.2.0`（时机自己定，可以并进正式发版那个 MR）。命令不会替你决定下一个正式版该是
`0.1.1` 还是 `0.2.0` —— 那是产品决策，所以正式版号必须你显式给出。

---

## 一、发测试包 → 平台测试环境自动更新（你可直接做）

```bash
uv run forge release --alpha     # 发哪个版本由仓库状态决定，你不用写版本号
```

它会依次做：**切到 detached HEAD**（你的分支从此刻起不被改动）→ 改 `pyproject.toml` 版本 →
`chore: release 0.1.0a1` 提交 → 打 `v0.1.0a1` → 推 tag（commit 随 tag 上远端）→ **切回你的分支**。
推送前会打印全部步骤并要你确认一次。全程离线，不需要连内网 Registry（只有查序号会摸一下远端）。

### 为什么要绕 detached HEAD 这一圈

因为那笔 `chore: release` 提交**不该留在你的工作分支上**。早期版本就是直接提交在当前分支的，
后果是：

- 本地分支领先远端一个 commit，下次 push 时这笔会混进你的 MR；
- 连发 a1/a2/a3 会**累积**成三个 commit（每次都在上一次的基础上再 bump）；
- 在受保护的 `main` 上发预发布更糟：commit 推不上去，本地 main 与 `origin/main` 就此永久分叉。

绕一圈之后：**你的分支纹丝不动，工作区回到发版前的样子**（`pyproject` 还是 `0.1.0`），
而 tag 指向的那个 commit 里版本号是正确的 —— wheel 版本就是从那里来的。

常用开关：`--dry-run` 只看会做什么；`--no-push` 只在本地打 tag；`--yes` 跳过确认（供脚本用）。

<details>
<summary>等价的手工步骤（`forge release` 要 <code>paxsz-forge-platform>=0.1.9</code>，旧仓可用这个）</summary>

```bash
# 0) 工作区必须干净；序号自己数（看 git tag --list "v0.1.0a*" 里最大的那个 +1）

# 1) 切到 detached HEAD —— 下面这笔 bump 提交就不会落在你的分支上
git switch --detach

# 2) bump 到预发布号并提交（--frozen：只改版本号，不 re-lock、不需要连 Registry）
uv version 0.1.0a1 --frozen
git commit -am "chore: release 0.1.0a1"

# 3) 打 tag 并推送（commit 随 tag 上远端，被 tag 引用）
git tag v0.1.0a1
git push origin v0.1.0a1

# 4) 切回你的分支 —— 工作区恢复到发版前，pyproject 还是 0.1.0
git switch -
```

**一步都不能少**：漏掉第 2 步就是上面表格里那两种事故；漏掉第 1/4 步则会把 `chore: release`
留在你的工作分支上（本地领先远端、下次 push 混进 MR，在 main 上还会导致永久分叉）。

</details>

**打完 tag 后自动发生（你无需干预）**：

1. 本仓 CI 的 `publish` job 构建并发 wheel 到**本模块仓** Package Registry；
2. `trigger-platform-assembly` job 识别出这是预发布版 → curl 平台触发 API（携带 `TARGET_ENV=test`）；
3. 平台仓流水线的 `assembly-apply-test` **自动**跑：在测试机 bump 装配 overlay + `uv pip install` 该版本 wheel + 重启平台/jobs（秒级）→ 健康检查；
4. 几十秒后测试环境即运行你这个预发布版，去测试环境验证即可。

**权限**：打 `v*` tag 需要业务仓 **Developer** 角色（建仓时已配 `v*` create = Developer），你自己就能发，无需平台侧介入。

---

## 二、发正式包 → 平台正式环境（平台仓管理员手动审核后装配）

前提：对应预发布版已在测试环境验过，且代码已经过 `develop → main` 的 MR（main 禁直推、只收来自
develop 的 MR、合并需 Maintainer —— 这本身就是那道人工 review）。

```bash
git switch main && git pull
uv run forge release 0.1.0        # 正式版路径下它只打 tag + push，不产生任何提交
```

按「规则一」，分支上的版本号本来就是正式版号 `0.1.0`，所以**通常不需要额外 bump 什么** ——
代码合进 main 的那一刻，正式发版的准备就已经就绪了。

### 什么时候才需要先 bump 一次

只有当你要发的正式版号**不等于**分支上当前的版本号时（例如分支上是 `0.1.0`，但这次要发 `0.2.0`）。
这种情况下命令会拒绝，并要求你先经 MR 把 `pyproject` 改到 `0.2.0`。

### 正式版为什么不能像预发布那样就地 bump

正式版会进**正式环境**，其代码必须已经过 MR 审核。就地 bump 出来的 commit 不在 main 上，
CI 的 `guard-tag-on-main` 一定会拦 —— 白折腾。所以 `forge release` 在正式路径下只做后一半：
校验你确实在 main 上、`pyproject` 确实已是目标版本，然后打 tag + push。

<details>
<summary>等价的手工做法</summary>

```bash
git switch main && git pull
git tag v0.1.0
git push origin v0.1.0
```

</details>

**打完正式 tag 后发生**：

1. 本仓 CI 的 `publish` job 发**正式 wheel** 到 Registry；
2. `trigger-platform-assembly` 识别出正式版 → curl 平台触发 API（携带 `TARGET_ENV=prod`）；
3. 平台仓建一条流水线，其中 `assembly-apply-prod` 是**手动（manual）job**：**阻塞、等待平台仓管理员手动点 ▶ 确认**；
4. **平台仓管理员审核这次正式发布**，确认无误后点 ▶ → 正式机 bump 装配 + `uv pip install` 正式 wheel + 重启 → 健康检查。

### ⚠️ 关键：正式 tag 打完，正式环境不会自动更新

正式环境的装配被**平台仓管理员在平台仓流水线里的手动确认**这一步 gate 住——这是设计上刻意保留的**审核关口**，防止未经审核的版本直接上正式。对你（业务仓开发者）而言：

- **这一步你无需、也无权限操作**：你在业务仓做完「打正式 tag」就到此为止，平台仓流水线你通常没有操作权限；
- **但正式发布的「真正完成」取决于平台侧那次点击**——别以为 push 完 tag 正式环境就自动好了；push 后正式环境仍是旧版，直到管理员确认装配；
- **需要加急上线，联系平台仓负责人**去点确认，而不是在业务仓反复打 tag / 重发。

> **附带保障：预发布版永远进不了正式环境**（双保险）。① 链路层——预发布 tag 只触发测试环境装配，平台正式流水线里根本不会出现那个手动按钮；② 平台正式环境 `allow_prerelease = false`，即便有人手动把预发布版塞给正式装配也会被 fail-closed 拒绝。

### 平台流水线上怎么认出「这是你这次发版触发的」

你的 tag 触发的是**平台仓**的流水线，而那条流水线没有自己的 commit —— GitLab 列表页默认只能显示平台仓
ref 的提交标题（`Merge branch 'develop' into 'main'` 之类），十几个业务仓的装配触发在那里长得一模一样。
所以本仓 CI 在 curl 触发时会一并上报几个「自报家门」的变量（2026-09-07 起的模板）：

- 平台流水线**标题**直接显示：`<你的分发名> · <版本> → prod（来自 <group/你的仓> #<本仓流水线号>）`；
- 平台流水线里的 `assembly-note-prod` job（恒运行、无需点击、几秒钟）日志里有来源仓、来源 tag，以及
  **回跳到本仓这条发布流水线的链接**。

实际用处：找平台管理员点确认时报一句流水线标题就够了；对方也能从 note job 点回你的仓核对版本。

> **存量仓补丁（CI 模板早于 2026-09-07 的仓）**：不上报也照样装配，平台列表页会显示**你的模块分发名**
> （那是链路本来就在传的 `MODULE_NAME`），但看不出版本、环境和来源仓，note job 的来源栏写「未上报」。
> 补法是在本仓 `.gitlab-ci.yml` 的 `trigger-platform-assembly` job 里给 curl 补四个变量：
> `variables[PIPELINE_NAME_SUFFIX]`（名字的后半截，以空格开头；模块名那半截由平台自己拼）、
> `variables[SOURCE_PROJECT]`、`variables[SOURCE_PIPELINE_URL]`、`variables[SOURCE_TAG]`
> —— 照抄平台仓模板 `templates/module/template/.gitlab-ci.yml.jinja` 的现状即可。
> 这几个变量在平台侧全是 best-effort：不传不影响装配，也不会让流水线变红。

---

## 三、从测试验证到正式发布（晋级路径）

**打正式 `v0.1.0` tag 不会顺便更新测试环境**——正式 tag 只走正式环境路径。所以测试环境里跑的仍是你之前发的预发布版，「晋级」不是自动的：

- **晋级 = 重新 bump 到正式号 → 经 MR 合入 main → 打正式 tag**（即上面第二节）。
- 想让测试环境先跑一版「与正式候选一致」的东西再上正式，就多发一个 `rc`：`uv version 0.1.0rc1` → `v0.1.0rc1`（进测试环境）→ 验过 → 再发 `v0.1.0` 正式。

---

## 四、发布门禁：CI 在发包前会拦什么

打了 tag 之后，本仓 CI 的 `guard` 阶段先跑两道闸，**任一红灯则 `publish` 不起跑、平台装配也不会被触发**（"不发包、更不触发装配"）。它们只在 tag 流水线上运行，日常 MR 不受影响。

| 门禁 | 跑在哪些 tag 上 | 判据 | 红灯说明什么 |
|---|---|---|---|
| `guard-tag-version` | 全部版本 tag | tag 版本 **严格等于** `pyproject.toml` 版本 | 你漏了 bump（或 tag 打错版本号）—— 就是上面那条铁律 |
| `guard-tag-on-main` | 仅**正式** tag（无后缀） | tag 指向的 commit 已在 `main` 上 | 这坨代码没走 `develop → main` 的 MR 审核，不该进正式环境 |

两道闸的日志都会直接给出可执行的修复命令，照着敲即可。本地还有一道可选的前置：

```bash
python scripts/install_hooks.py     # ★ 每个 clone 装一次
```

装上后 `git push` 推 `v*` tag 前会先在本地比一遍版本，不一致直接拦住 —— 省掉「推上去才发现、还得删远端 tag」那一圈。只拦 tag 推送，普通分支 push 零打扰。它是**本地 opt-in、可用 `--no-verify` 绕过的提醒**，不是保障；真正 fail-closed 的是上面 CI 那两道。

### ⚠️ 存量仓补丁：2026-07-30 之前建的仓没有这两道闸

模板改动只对**将来新建**的仓生效。你的仓若建于 2026-07-30 之前，`.gitlab-ci.yml` 里没有 `guard-tag-*`，
`.githooks/` 与 `scripts/install_hooks.py` 也不存在 —— 也就是说**上面那两种事故在你的仓里仍会发生**。
二选一补上：

**做法一（推荐）：用 copier 重新渲染模板**，一次拿全（两道闸 + 钩子 + `.copier-answers.yml`）。

⚠️ **必须带 `-x` 保护你自己改过的文件，尤其是 `src/**` 和 `tests/**`**。`--overwrite` 会把
**模板生成过的每一个文件**整份换成模板的样子 —— 包括 `src/<你的包>/module.py` 和
`tests/test_module.py`，也就是你的模块主文件和测试。**你已经提交在 develop 上的定制照样会被冲掉**：
工作区干净并不能防止这件事，它只保证「被冲掉」这件事会出现在 `git diff` 里、能被看见。

实测过：不加 `-x` 时业务依赖（`pandas`、`openpyxl`）、自定义 CI job、`CLAUDE.md` 业务规则、
**`module.py` 里的全部业务逻辑**、`tests/` 里的用例统统消失，而 `git diff --stat` 可能只显示十几行
删除，小到很容易被当成无害直接提交。

> 判断哪些要排除的方法：**凡是模板生成过、而你后来改过的文件，都要排除**。你**新增**的文件
> （模板里没有的，如 `src/<包>/report.py`、`docs/2_landed/` 落盘文档）不受影响 —— 实测确认过。
> 万一漏排了，改动都还没提交，`git checkout -- <路径>` 就能全部恢复。

**在业务仓目录下执行**（不是在平台仓）。平台仓只出现在命令里、作为模板的来源：

```
cd <你的业务仓>                            # ← 全程在业务仓里操作
git switch -c chore/sync-module-template   # 别在 develop 上直接改
git status                                 # 必须干净
```

同步命令**写成一行**（下面这条 PowerShell / CMD / bash 都能直接粘贴）：

```
uvx copier copy --trust --overwrite -x 'src/**' -x 'tests/**' -x pyproject.toml -x uv.lock -x CLAUDE.md -x AGENTS.md -x README.md -x 'docs/**' <平台仓路径>/templates/module .
```

末尾两个位置参数分别是**源**（平台仓的模板）与**目标**（`.`，即当前的业务仓）。跑完 copier 会
**逐项提问**建仓参数（存量仓还没有 `.copier-answers.yml`，没有可复用的答案），照下面的表填。

> ⚠️ **别把它拆成多行用 `\` 续行**：那是 bash 写法，**PowerShell 不认 `\`**，会把它当成一个字面
> 参数传进去，报 `Error: Expected at least 2 positional arguments, got ['\\']`，后续几行还会被
> 当成独立命令各报一个错。要换行请用 PowerShell 的反引号 `` ` ``；不确定就用上面这条单行的。

```
git diff                                   # 现在只剩 .gitlab-ci.yml 要看（见下）
```

> **用 `uvx copier`，不是 `uv run copier`**。`copier` 是平台仓的开发依赖，业务仓的环境里没有 ——
> `uv run copier` 会报 `Failed to spawn: copier / program not found`，而且它还会顺手给业务仓
> 创建 `.venv` 并解析一遍依赖（迁移时并不想要这个副作用）。
>
> `uvx` 拉不到 copier（内网镜像不通）时，退回借平台仓的环境跑 —— **CWD 仍然是业务仓**，
> `--project` 只是告诉 uv「去哪个项目的环境里找 copier 这个程序」，与操作目标无关：
>
> ```
> uv run --project <平台仓路径> copier copy --trust --overwrite -x … <平台仓路径>/templates/module .
> ```

**关于 `--defaults`**：它的作用是「对**有默认值**的问题取默认值、不问」。而 `module_code`、
`package_name` 这些问题**没有默认值**，于是：

| 怎么跑 | 结果 |
|---|---|
| 不带 `--defaults`（上面那条） | copier 逐项问你，手填 ✅ |
| 带 `--defaults` **且**用 `--data` 给全无默认值的答案 | 不问，一条命令跑完 ✅ |
| 只带 `--defaults`、不给 `--data` | ❌ `Question "module_code" is required` |

想一条命令跑完就用第二种（同样**必须写成一行**，理由见上面那条 ⚠️）：

```
uvx copier copy --trust --overwrite --defaults -x 'src/**' -x 'tests/**' -x pyproject.toml -x uv.lock -x CLAUDE.md -x AGENTS.md -x README.md -x 'docs/**' --data module_code=XXX --data package_name=xxx_module --data distribution_name=forge-module-xxx --data module_name=XX助手 --data description=一句话业务描述 --data profiles=structured-query <平台仓路径>/templates/module .
```

这次同步完，仓里就有了 `.copier-answers.yml`，那些答案有了来源 —— **以后**再同步单带
`--defaults` 就能跑（不用再写一堆 `--data`）。

被 `-x` 排除的文件不会被碰，所以 **`pyproject.toml` 的 SDK 依赖下界要手工改**（`paxsz-forge-platform>=0.1.9`），
这是有意的取舍：那个文件里有你的业务依赖，宁可手改一行，也不能整份覆盖。

**`.gitlab-ci.yml` 无法排除** —— 它正是这次要更新的目标。如果你仓里给它加过自定义 job（夜间任务、
额外检查等），那些会被覆盖掉，需要从 `git diff` 里把它们合回去。好在排除了其他文件之后，
diff 面就只剩这一个文件，看起来很快。

copier 问的参数，答案全在你仓里现成的 —— 分别来自**两个文件**：

**① `pyproject.toml`**

```toml
[project]
name = "forge-module-hr"                      # ← distribution_name

[project.entry-points."forge.modules"]
HR = "hr_module.module:HrModule"
# ↑ module_code    ↑ package_name（只取 `.module:` 之前那段，也就是 src/ 下的目录名）

[[tool.uv.index]]
url = "http://code.example.com/api/v4/projects/195/packages/pypi/simple"
#      └──── gitlab_url ────┘              └─ sdk_registry_project_id
```

`package_name` 是 **`hr_module`**，不是整串 `hr_module.module:HrModule`；类名（`HrModule`）不用填，
模板会从 `module_code` 自动推出来。

**② `src/<package_name>/module.py`** 的 `ModuleManifest(...)`

```python
manifest = ModuleManifest(
    code=MODULE_CODE,
    name="人事查询助手",                              # ← module_name
    description="查询员工与组织信息",                  # ← description
    profiles=["structured-query", "stats-sandbox"],   # ← profiles
```

⚠️ `profiles` 要**转成逗号分隔的字符串**再填：上面这个填 `structured-query,stats-sandbox`
（不带引号、方括号，逗号后不加空格）。

填完会落成 `.copier-answers.yml`，**下次再同步就不用回答了**。

**做法二：只贴 CI 那两道闸**（改动面最小，不碰其他文件）。把平台仓模块模板（`.gitlab-ci.yml.jinja`，找平台方要最新版）里
`guard-tag-version` 与 `guard-tag-on-main` 两个 job 整段复制进你仓的 `.gitlab-ci.yml`（该文件里那两段不含
jinja 变量，可原样粘贴），并给 `publish` job 加上：

```yaml
publish:
  needs:
    - job: guard-tag-version
    - job: guard-tag-on-main
      optional: true          # 预发布 tag 的流水线里没有这个 job，不能让 needs 因其缺席而报错
```

**别忘了顺手清理**：若你的 Registry 里已经因为这个 bug 躺着来源不明的版本（比如没人 bump 却出现的 `0.1.0`），
在 GitLab 的 Packages 页面删掉它 —— 否则将来有人可能把它装进正式环境。删包需 Maintainer 权限。

---

## 四点五、向量化模块的额外前置（`semantic-retrieval` / `governance-etl` 才需要）

上面整篇讲的是**wheel 怎么进运行环境**。装配链路只搬 wheel —— **库、账号、向量表、库里的数据
一样都不跟着走**。所以启用了 `semantic-retrieval` / `governance-etl` 的模块，发版之外还有三步，
**测试环境和正式环境各要做一遍**：

| # | 谁做 | 做什么 | 漏了会怎样 |
|---|---|---|---|
| 1 | 平台运维 | 建 `forge_mart_<编码>` 库 + 一对账号 + 登记别名（`forge data provision-mart`） | 该模块启动期被**隔离下线**（别名未登记；平台照常起，`/healthz` 报 `degraded`） |
| 2 | 平台运维 | 建向量表（`forge vectorize apply`；装配时部署脚本自动执行） | 该模块启动期被**隔离下线**（`VECTOR_SCOPE_COLUMNS_MISSING`） |
| 3 | 平台运维 | **首轮全量回填**（`forge jobs run <编码>.vectorize:<向量表>`） | 检索**恒返回 0 条**，直到次日 cron 到点；**平台不报错、日志干净** |

⚠️ **第 3 步是三步里唯一连「模块被隔离」都不会报的**，也因此最容易被漏掉：平台启动期校验只查向量表的
列结构、不查行数，所以「表建好了、一行数据没有」在平台看来完全正常。前两步漏了，模块会出现在
`/healthz` 的 `failed_modules` 与 Console 模块页的失败清单里（平台本身照常起、systemd 不会报警）。发测试包之后功能「静默不
工作」，绝大多数是这一步。

⚠️ **顺序硬约束**：第 1 步必须先于模块进入该环境的装配清单。装配是自动的（测试）或一键 gated
（正式），一旦触发就会装 wheel + 重启平台，此时才发现库没建，该模块就被隔离、上不了线了。

→ **完整时序、执行者分工与排查表见 [11 mart 库模块端到端时序](11-vectorization-and-governance.md)**。
你在业务仓这侧要做的，仍然只有本文其余部分讲的发版。

---

## 五、前置与权限速查

| 事项 | 说明 |
|---|---|
| tag 命名 | `v<PEP440>`：正式 `v0.1.0`；预发布 `v0.1.0a1` / `v0.1.0b1` / `v0.1.0rc1`；开发版 `v0.1.0.dev1` |
| 打 tag 权限 | 业务仓 **Developer+**（`v*` create = Developer，建仓已配） |
| 正式 tag 的位置 | 必须打在 **main** 上（`guard-tag-on-main` 强制）。预发布 tag 不限分支 |
| 版本号一致性 | tag 版本必须 == `pyproject.toml` 版本（`guard-tag-version` 强制，严格字符串比对） |
| 触发装配的前提 | 需 group 级 CI/CD 变量 `PLATFORM_ASSEMBLY_TRIGGER_TOKEN`（平台侧一次性配、组内继承）。**未配则只发 wheel、不触发平台装配**（`trigger-platform-assembly` job 干净跳过，日志会打印「跳过平台装配触发」） |
| 谁审核正式装配 | 平台仓管理员（在平台仓流水线点 `assembly-apply-prod` 的手动确认） |
| 部署 ≠ 发布 | 本仓 CI **不**直接往平台运行环境部署；merge 只跑门禁，运行环境更新一律走上面的 tag → 装配链路 |

---

## 六、常见问题排查

- **`guard-tag-version` 红灯：tag 版本 ≠ pyproject 版本**：你漏了 bump（或 tag 打错）。删掉 tag 重发即可 —— `git tag -d v0.1.0a1 && git push origin :refs/tags/v0.1.0a1`，然后 `uv run forge release --alpha`（版本号交给它算）。job 日志里有针对你这次情况的完整命令。
- **`预发布基线 X 与 pyproject.toml 的版本 Y 不一致`**：你想发的预发布跨到了另一个正式版线上。要发 `Y` 线的用 `--alpha`；确实要进 `X`，先经 MR 把 `pyproject.toml` 的 `version` 改成 `X` 再发（正式版号的推进必须经审核，见规则三）。
- **`guard-tag-on-main` 红灯：正式 tag 不在 main 上**：正式版必须先把 bump 经 MR 合入 main，再在 main 上打 tag。想快速验一版就改发预发布（`0.1.0rc1`），它不受这道闸约束。
- **打了 tag 但 wheel 没发**：先看 `guard` 阶段那两个 job 是不是红的（最常见）。都绿的话，再确认 tag 匹配 `^v\d+\.\d+\.\d+…$` 正则、本仓 CI runner 已启用、SDK 拉包凭据在（`uv sync` 拉 `paxsz-forge-*` 若报 401，本仓 `.gitlab-ci.yml` 的门禁 job 会给出定位提示）。
- **publish 绿灯但 Registry 里没有新版本**：`uv publish --check-url` 对**已存在的版本**是幂等跳过的 —— 说明这个版本号早就发过了。换个版本号重发（`a1` → `a2`）。publish job 日志里的 `ls -l dist/` 那行会告诉你实际构建出的 wheel 到底是哪个版本。
- **`forge release` 报「invalid choice: 'release'」**：你仓里的 `paxsz-forge-platform` 低于 0.1.8（那时还没有这个命令）。把下界改到 `>=0.1.9` 后 `uv lock --upgrade-package paxsz-forge-platform && uv sync`，或直接用 §一/§二 折叠块里的手工步骤，功能上不缺什么。
- **`forge release` 报 `permission denied`、或反复重试后版本号越跳越高**：你装的是 `paxsz-forge-platform` **0.1.8**。那一版在带密码的 SSH 密钥下会把 git 的密码提示吞掉（只剩一句 permission denied），失败后还会残留本地 tag 让下次序号虚涨。升到 **>=0.1.9**。残留的孤儿 tag 不用手工清，0.1.9 每次发版开头都会 prune 掉。
- **wheel 发了但平台毫无动静**：多半是 `PLATFORM_ASSEMBLY_TRIGGER_TOKEN` 没配（`trigger-platform-assembly` job 日志显示「跳过平台装配触发」），或平台仓项目 ID 不对——找平台负责人核对。
- **测试环境自动更新了、正式环境迟迟不动**：这是**正常**的——正式环境在等平台仓管理员手动确认装配。联系平台负责人。
- **想确认某版本到底装没装进平台环境**：这在平台侧查（`forge assembly list`），业务仓侧看不到；找平台负责人。

---

## 相关文档

> 下面标了**平台仓**的都在你仓里读不到，列在这里只为让你知道它们存在、需要时找平台方要。

- mart 库模块的端到端时序（上面「四点五」的展开）：[11 mart 库模块端到端时序](11-vectorization-and-governance.md)
- 平台侧装配清单与触发链路的完整操作手册：**平台仓**「装配与触发链路指引」
- 业务仓分支模型与「发布 / 部署分工」：**平台仓**「新建业务模块仓指引」§D
- 平台 SDK 五包（`paxsz-forge-*`）的发布——**与本文是两回事**：**平台仓**「发包指引」
