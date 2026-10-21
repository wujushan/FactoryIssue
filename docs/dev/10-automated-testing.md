# 10 业务问答自动化测试（/test 通道）

> 面向**业务模块仓**：在接了真实测试数据的环境上，把 `docs/testcases/golden/` 里的用例集
> 全量跑一遍，回答一个问题——**这个模块答得对不对**。
>
> 平台侧对应实现：`gateway/qa_api.py`（端点）+ `qa_keys.py`（凭据）。本文是交付业务仓的
> 唯一信源，端点行为变更必须同步本文。

---

## 1. 它是什么，不是什么

这条通道只为一件事存在：**校验问答数据的正确性**。为此它刻意砍掉了三样东西。

| | 说明 |
|---|---|
| ✅ **非流式** | 一轮问答一个 JSON。自动化要的是「跑完之后是什么」，不是逐帧到达顺序。事件序列仍原样回传，但你多半用不到。 |
| ✅ **结构化产物摊平** | 表格在 `tables`（`columns`/`rows`），图表在 `charts`（数值 spec），引用在 `citations`。**断言直接吃数组**，不必去 Markdown 正文里正则抠数字。 |
| ✅ **零持久化** | 测试流量不进会话/审计/统计/反馈，也不写归档目录。跑一千条用例，平台数据库零增量。 |
| 🚫 **不验权限** | 凭 api-key 换到的是**权限绿灯**授权树（跳过 INFO 授权、无行/列过滤）。权限用例由平台侧用真实 INFO token 覆盖，**不在业务仓这条线上**。 |
| 🚫 **不是终端用户链路** | 它跳过了 INFO 鉴权这一整段。「用户 A 能不能看到这条数据」这类问题，这里问不出来，也不该在这里问。 |
| 🚫 **不测 SSE / 前端体验** | 首字节延迟、逐帧渲染、断连恢复都属平台侧，与业务数据正确性无关。 |

> ⚠️ **绿灯的含义要清楚**：模块在测试通道里拿到的是「所有表、所有行、所有列都放行」的权限。
> 因此**在生产上会被权限裁掉的数据，在测试里会全部返回**。用例的预期值要按「全量可见」写，
> 别拿生产上某个人看到的结果当预期。

**知识库模块同样绿灯**（2026-08-10 补）：模块 `manifest.knowledge_bases` 里声明的每个库都会
被授权，且**不限库内目录**。唯一前提是平台的 `knowledge_bases.json` 给该别名配了 `agent_code`
——库级授权靠它对齐，缺配时该库不进绿灯范围，检索会照常 fail-closed 并提示补配置（这是配置
问题，不该被测试通道掩盖）。反过来，**没在 manifest 里声明的库不会因为绿灯而被顺手授权**。

**你依赖的模块同样绿灯**（2026-09-21 补）：你的模块在 manifest 里声明的依赖——问答式的
`dependencies` 与能力调用的 `capability_deps`，连同它们再依赖的——都会进这把 key 的授权范围，
否则你的一轮调到对方时会被「未授权」拒绝，编排根本测不了。但它们**只能经你的模块被调到**：
`target` 写对方编码仍是 403，不带 `target` 走路由也不会路由到对方（见 §3.1）。
闭包按**平台上装配的**那一版 manifest 算——新加的依赖要等你的新版本装配上测试环境才生效。

---

## 2. 前置：两道闸

调用成功需要同时满足：

1. **平台开了这个通道**：目标环境的 `.env` 设 `FORGE_ENABLE_TEST_API=true`（默认关）。
   测试环境常开；**正式环境默认不开**，是否开由平台运维决定。
2. **你有一把没过期的 api-key**，且它授权了你要测的模块。

两道闸互不替代——key 再新，平台没开也是 404。

### 申请 api-key

找**平台管理员**在 Admin Console → 「测试」页签发，告诉他三件事：

| 要告诉管理员的 | 例 | 说明 |
|---|---|---|
| 名称 | `物料助手回归` | 能认出用途即可，会显示在 key 列表里 |
| **模块编码**（可多个） | `MAT` | **这就是这把 key 的爆炸半径**：只填你自己的模块，别要「不限」。你依赖的模块**不用填**，会自动带上（§1） |
| 有效期（天） | `90` | 上限 365，没有「永不过期」。到期前管理员可续期 |

签发后你会拿到一串 `fdt_<前缀>.<密钥>` 形式的明文——**它只显示这一次**，平台只存哈希。
存进你 CI 的 secret 变量（如 GitLab CI/CD Variables，勾选 Masked + Protected），**绝不提交进仓库**。

丢了怎么办：找管理员重新签发一把（不能找回）。key 的 `fdt_<前缀>` 部分在 Console 列表里可见，
报障时报这个前缀即可定位到是哪把。

---

## 3. API 参考

基址即平台地址（例：`http://<平台主机>:8090`）。鉴权头两种写法等价：

```
Authorization: Bearer fdt_xxxxxxxx.yyyyyyyy
X-Forge-Test-Key: fdt_xxxxxxxx.yyyyyyyy
```

### 3.1 `POST /test/chat` —— 跑一轮问答

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | ✅ | 用户问题原文 |
| `target` | string | | 直达模块编码，**跳过路由**。数据用例建议都带上（理由见 §4.1）。只能是 key 授权的模块——你依赖的模块虽然进了授权范围（§1），但只能经你的模块被调到，直接 target 它是 403；不带 `target` 时路由同样只在 key 授权的模块里挑 |
| `conversation_id` | string | | 多轮用例：带上一轮返回的值即续聊。省略 = 新会话 |
| `user_id` | string | | 测试身份。权限不看它（绿灯），但模块内部若按 user_id 走业务逻辑则有用。默认 `qa-<key前缀>` |
| `user_name` / `department` | string | | 注入 `ctx.user.name` / `.department`。测试轮**不查用户档案**，依赖姓名/部门的业务分支只能靠这里显式给；不给即空串（与真实环境「查无档案」一致） |
| `attributes` | object | | 透传给 `UserContext.attributes` |
| `ext_param` | object | | 客户端定制参数，原样交给模块（必带保留键 `task`）。**任务式模块的用例靠它**——不传就只覆盖得到「没给任务码」的分支。字段口径见 02 · SDK 参考的「客户端定制参数」 |
| `include_trace` | bool | | 回传本轮 SQL/LLM 明细，默认 `false`（见 §3.3） |
| `files` | array | | 本轮附带的文件，**base64 内联**：`[{"filename": "单据.png", "content_base64": "..."}]`。带文件的模块靠它做回归（见 §3.4）|

响应（HTTP 200）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_id` | string | 本轮标识（报障时给它） |
| `conversation_id` | string | 续聊用 |
| `module` | string \| null | **路由主目标**。null = 澄清轮或路由前就出错 |
| `modules` | string[] | 本轮实际触达的全部模块（含被 `bus.call` 的） |
| `route_reason` | string | 路由依据（`keyword` / `llm` / `explicit_target` …） |
| `answer` | string | 答案正文（Markdown）。**只含 delta**，表格/图表不在其中 |
| `tables` | object[] | `{title, columns, rows}`，**结构化断言首选** |
| `charts` | object[] | `{chart_type, title, x, series, unit[, style]}`，数值来自沙箱；`style` 只在模块传了时出现 |
| `citations` | object[] | 引用溯源条目（整轮聚合） |
| `clarify` | object \| null | 非 null = **本轮没有实质回答**（问题不明确被答前阻断） |
| `suggestions` | object \| null | 答后追问建议 |
| `error` | object \| null | `{code, message, fatal}`；模块报错走这里，HTTP 仍是 200 |
| `usage` | object | 本轮 token 汇总；`{}` = 未知（≠ 0） |
| `duration_ms` | number | 整轮耗时 |
| `query_count` | number | 本轮执行的 SQL 条数（0 = 根本没取数，常是「答错」的第一线索） |
| `events` | object[] | 事件原始序列（`{type, source, ts, data}`），要更细的断言时用 |

> **`error` 非 null 时 HTTP 仍是 200**：模块报错是一条**用例结果**，不是接口故障。
> 只有凭据/参数问题才给 4xx（见下表）。用例里请断言 `body["error"] is None`，别只看状态码。

### 3.2 `GET /test/modules` —— 这把 key 能测什么

CI 的第一步建议先打它：凭据问题当场暴露，而不是等到第一条用例莫名 401。

```json
{
  "key": { "id": "…", "name": "物料助手回归", "expires_ts": 1767225600.0, "modules": ["MAT"] },
  "modules": [ {
    "code": "MAT", "name": "物料助手", "description": "…", "intents": ["…"],
    "capabilities": [ { "name": "stock_by_part_numbers", "version": 1, "description": "…" } ]
  } ]
}
```

`key.modules` 为空数组 = 不限模块。`expires_ts` 是 Unix 秒，CI 里可以顺手判一句
「剩余不足 7 天就在流水线里告警」，免得某天早上突然全红。`capabilities` 是该模块提供的能力摘要
（完整签名见 §3.6）。这里只列能直接 `target` 的模块，你依赖的模块不在其中。

### 3.3 `include_trace`：失败时才开

本通道不写归档，所以**这是本轮 SQL/LLM 明细唯一的出口**：

```json
{
  "trace": {
    "queries":   [{"source": "erp", "sql": "SELECT …", "params": [...], "rows": 12, "duration_ms": 34, "flags": []}],
    "llm_calls": [{"purpose": "sql_generation", "prompt_tokens": 900, "completion_tokens": 60, "duration_ms": 1200}],
    "retrievals":[{"kb_alias": "pdc", "hits": 5, "top_score": 0.82}],
    "configs":   [{"agent": "MAT", "file": "params.json", "version": 3, "sha256": "…", "updated_by": "admin"}],
    "invocations": [{
      "caller": "SHIPMENT", "target": "MATERIAL_QUERY",
      "capability": "stock_by_part_numbers", "version": 1,
      "arguments": {"part_nos": ["P1", "P2"]},
      "columns": ["part_no", "qty"], "rows": 2, "truncated": false, "total": null,
      "as_of": "2026-09-21", "notes": "其中 1 个是替代料…", "citation_count": 0,
      "duration_ms": 85.3, "error_code": "", "error": "", "problems": [],
      "chain": ["SHIPMENT", "MATERIAL_QUERY"], "invoked_at": "2026-09-21T10:00:00.123"
    }]
  }
}
```

`configs` 是本轮 `ctx.config` 实际读到的版本（`version: 0` = 那份配置还没上传过，模块走的是
自己的兜底分支）。**配置相关的用例值得顺手断言它**：阈值类参数改过之后同一个问题会给出不同
答案，不断言版本的话，用例挂了你只会看到一句莫名其妙的业务断言失败。

`invocations` 是本轮每次模块间结构化能力调用（`ctx.bus.invoke`），**成功与失败都在**，按完成
顺序排（嵌套调用里内层先完成、先出现）。几个字段的读法：

- `arguments`：成功时是被调方**实际收到的**（校验归一化后，日期已是 ISO 串）；实参不合签名时
  是你**原样传的**那份——对照 `problems` 就知道该改哪里；
- `rows` / `columns` 等为 `null` = 没走到那一步（比如被权限闸或实参校验拦下），不是 0 行；
  返回不合签名（`CAPABILITY_RESULT_INVALID`）时它们照样有值，是被调方**实际给的**；
- `problems`：契约校验的逐条问题。响应顶层的 `error` 只有脱敏后的一句话，看不出是哪个参数；
- 调用方模块捕获了失败、降级作答时，`error` 为空、答案看着正常——**那次失败只在这里看得见**。

调用方的回归值得断言一句「确实向对方取过数、拿回了行」：

```python
inv = body["trace"]["invocations"]
assert [(i["target"], i["capability"], i["error_code"]) for i in inv] == [
    ("MATERIAL_QUERY", "stock_by_part_numbers", ""),
]
assert inv[0]["rows"] > 0
```

不含 prompt / 模型输出正文（那会让响应体涨到几 MB）。**默认关**：全量回归时它是纯负载，
真要排错就对着失败的那一条单独重跑一次。

### 3.4 `files`：带文件的用例

模块要处理用户上传的文件（图片识别、PDF 解读）时，用例把文件**内联**进同一个 JSON：

```python
import base64, pathlib

payload = {
    "query": "这张单据的编号是多少？",
    "target": "invoice_reader",
    "files": [{
        "filename": "单据.png",
        "content_base64": base64.b64encode(
            pathlib.Path("fixtures/单据.png").read_bytes()
        ).decode(),
    }],
}
```

**为什么内联而不是先上传再引用**：回归用例是一条条独立的 JSON，内联让每条用例自包含；
两步走还得在用例之间传递 `file_id`，那是编排不是断言。

平台照常把它变成模块手上的 `request.files`，模块侧的读法与线上完全一致
（`ctx.files.as_content_part()`，见 02 · SDK 参考）。**这条路径会落盘**——与本通道
「零持久化」不冲突：ephemeral 管的是会话/消息/审计/归档这些记账数据，
而文件内容不落盘模块就无从读起。它们受兜底 TTL 与清理任务管辖。

> 固定资产提示：把 fixture 图片放进仓里时留意体积与敏感性。**别放真实业务单据**——
> 那会让一份真实数据长期躺在代码仓里，而红线只允许它待在内网数据库与 runtime 目录。
> 用脱敏样本或自己造一张。

### 3.5 错误码

| HTTP | code | 含义 / 该做什么 |
|---|---|---|
| 404 | `TEST_API_DISABLED` | 平台没开这条通道 → 找运维设 `FORGE_ENABLE_TEST_API=true` 并重启 |
| 401 | `TEST_KEY_MISSING` | 没带鉴权头 |
| 401 | `TEST_KEY_INVALID` | key 不存在/已删除/串写错了 |
| 401 | `TEST_KEY_EXPIRED` | 过期 → 找管理员续期 |
| 401 | `TEST_KEY_DISABLED` | 被停用 → 找管理员 |
| 403 | `TEST_MODULE_NOT_ALLOWED` | 这把 key 没授权这个模块 → 对照 `GET /test/modules`（`/test/invoke` 直调依赖闭包里的模块同样是它） |
| 403 | `TEST_NO_MODULE_AVAILABLE` | key 授权的模块在该平台一个都没装配 → 多半是发版没上去 |
| 404 | `MODULE_NOT_FOUND` | `target`（或 `/test/invoke` 的 `module`）写的模块平台上没有 |

### 3.6 `GET /test/capabilities` —— 被调方的能力签名

给**调用方**（用了别的模块的能力、`manifest.capability_deps` 非空）拿对方签名用的。你一般不直接打它，
而是跑 `forge capabilities pull`（见 [06](06-cli-reference.md)），它按你声明的依赖把签名写进
`tests/contracts/`，契约测试 `ContractBus` 读的就是那几个文件（见 [02 · 测试模式](02-sdk-reference.md#测试模式)）。

```json
{
  "format": "forge-capabilities/1",
  "modules": ["SHIPMENT", "MATERIAL_QUERY"],
  "unavailable": [],
  "snapshots": [{
    "format": "forge-capabilities/1",
    "module": "MATERIAL_QUERY", "module_name": "物料查询",
    "source": "http://<平台主机>:8090", "dist_version": "0.3.1", "exported_at": "2026-09-21T10:00:00",
    "capabilities": [{
      "name": "stock_by_part_numbers", "version": 1, "description": "…",
      "params":  [{"name": "part_nos", "type": "string", "repeated": true, "required": true, "description": "…"}],
      "returns": [{"name": "part_no", "type": "string", "description": "…"}, {"name": "qty", "type": "integer", "description": "…"}],
      "fingerprint": "…"
    }]
  }]
}
```

- **看得到谁**：`modules` 是这把 key 的可达范围——key 授权的模块及其依赖闭包（与 §1 绿灯同一个口径），
  不限模块的 key 即全部已装配模块。`snapshots` 只含其中**提供了能力**的模块，每个一份完整签名
  （不按你的引用裁剪，裁剪是 `pull` 的事）。与你无关的模块的签名拿不到。
- **`unavailable`**：key 授权、平台上却没在服务的模块及原因（`{code, reason, detail}`）。最常见的一种：
  被调方删了你依赖的能力 → 平台启动期把**你的模块**按 `capability_dep_unsatisfied` 隔离 → 你的
  闭包是空的，对方签名也就拿不到了——真因只在这一项里。
- `fingerprint` 是签名指纹（参数与返回列的名称 / 类型 / 数组 / 必填，**不含说明文字**），`pull --check`
  靠它判断签名变没变。

### 3.7 `POST /test/invoke` —— 直调自己的一个能力

给**被调方**（`manifest.capabilities` 非空）测自己的能力用：不经问答、不经路由、没有调用方，
直接按签名调一次 `invoke()`，拿回行集。不必先找一个调用方模块来驱动。

```json
{
  "module": "MATERIAL_QUERY",
  "name": "stock_by_part_numbers",
  "version": 1,
  "arguments": {"part_nos": ["P1", "P2"]},
  "include_trace": false
}
```

- `module`：**必须是这把 key 授权的模块**——测的是你自己的能力。你依赖的模块虽在绿灯树里（§1），
  也只能经你的模块被调到，直调它们是 403；
- `version`：不给时，你的模块只提供一个版本就用它；提供了多个（老版本按约定保留一个发布周期）
  即报错并列出可选版本——**不替你挑最新的**，那样测的恰好不是调用方在用的那个；
- `user_id` / `user_name` / `department` / `attributes`：同 §3.1，可选（`name` 已是能力名，故姓名字段叫 `user_name`）。

响应：

```json
{
  "request_id": "…", "conversation_id": "inv_…",
  "module": "MATERIAL_QUERY", "capability": "stock_by_part_numbers", "version": 1,
  "result": {
    "data": [{"part_no": "P1", "qty": 7}, {"part_no": "P2", "qty": 0}],
    "columns": [{"name": "part_no", "type": "string", "description": "…"}, {"name": "qty", "type": "integer", "description": "…"}],
    "notes": "其中 1 个是替代料…", "citations": [], "truncated": false, "total": null,
    "as_of": "2026-09-21", "meta": {}
  },
  "rows": 2, "preview_truncated": false,
  "error": null,
  "duration_ms": 85.3
}
```

**它走的是与 `ctx.bus.invoke` 同一段执行代码**：实参按签名校、返回也按签名校（少给一列、类型不对
都是 `CAPABILITY_RESULT_INVALID`），你的行列权限照常编译（绿灯树下即全放开）。唯一跳过的是
「调用方声明过没有」那一道——直调没有调用方。所以**这里调得通，就等于调用方按同样的实参调得通**。

业务失败（实参不合、返回不合、模块抛错）HTTP 仍是 200，放在 `error`：

```json
{"result": null, "rows": null,
 "error": {"code": "CAPABILITY_ARGUMENT_INVALID",
           "message": "能力 stock_by_part_numbers@v1 的实参不合签名: 参数 'part_nos' 声明为数组，得到 str",
           "problems": ["参数 'part_nos' 声明为数组，得到 str"]}}
```

与 `/test/chat` 的 `error` 不同，这里的 `message` 是**后台原文**（过脱敏、截 500 字）而不是给终端
用户的那句「服务处理请求时出现问题」——直调只对持 key 的开发者开放，而同一段文字本就在 trace 里。
`problems` 与 §3.3 `trace.invocations` 里那一条逐字一致。

`include_trace: true` 时带回 `trace`（形状同 §3.3）：`queries` 是你的能力执行的 SQL；
`invocations` 第一条（按完成顺序是**最后**一条）`caller` 为空串的就是这次直调本身，其余是你的能力
里又向别的模块要的能力。零持久化同 `/test/chat`：不进审计、不写归档。

被调方的能力回归就可以这样写（与 `assert_capability` 单测互补：那边用假 ctx 测逻辑，这边在真实
测试数据上测口径）：

```python
body = requests.post(f"{base}/test/invoke", headers=headers, json={
    "module": "MATERIAL_QUERY", "name": "stock_by_part_numbers",
    "arguments": {"part_nos": ["P1"]},
}, timeout=120).json()
assert body["error"] is None, body["error"]
assert body["result"]["as_of"], "数据时点别省"
assert {r["part_no"] for r in body["result"]["data"]} == {"P1"}
```

> Console 里有同一件事的点选版：模块页展开你的模块 → 能力卡片右上角「试调用」（需要调试页权限，且角色的调试模块里含你的模块；
> 本地 `forge dev serve` 的 dev console 同样有）。那边会取到真实数据，因此**会留痕**——落一条来源为
> 「调试对话」的审计行与归档，与这里的零持久化不同。

---

## 4. 测试原则（比 API 更重要的部分）

### 4.1 数据用例一律带 `target`，路由单独测

路由是**独立的随机变量**。混在数据用例里，一条失败你要先分辨「是没路由到我」还是「路由对了但答错」。

- **数据用例**：带 `target="<你的模块编码>"`。失败即模块问题，定位一步到位。
- **路由用例**：不带 `target`，断言返回的 `module` 是否为预期编码。
  路由质量另有平台侧的评测工具（`forge eval routing --dataset cases.json --threshold 0.9`，见 [06](06-cli-reference.md)），
  它能直接给准确率并在低于阈值时让 CI 失败，比在问答用例里零散断言更合适。

### 4.2 断言锚在结构化产物上，别锚在正文措辞上

LLM 的自然语言输出**每次都不一样**，锚在它上面的用例迟早会红——而且是没有意义的红。

| 好的断言 | 坏的断言 |
|---|---|
| `tables[0]["rows"]` 里某行某列 == 预期数值 | `"共有 12 条" in answer` |
| `set(tables[0]["columns"]) == {"项目编号", "延期天数"}` | `answer.startswith("根据您的问题")` |
| `charts[0]["series"][0]["data"] == [11, 7]` | 正则从正文里抠数字 |
| `body["module"] == "MAT"` | `"物料" in answer` |
| `body["query_count"] > 0`（确实取了数，不是编的） | — |

正文只适合做**包含性/排除性**断言，而这恰好就是 [09 答案呈现规范](09-answer-presentation.md) 那几条的检查方式：

```python
assert "prj_dly_days" not in answer          # 不许露字段名
assert "dbo." not in answer                  # 不许露表名/数据源别名
assert "项目编号" in "".join(tables[0]["columns"])   # 该有的业务列名在
assert len(answer) > 40                      # 数据之外要给分析，不能只甩一张表
```

「你好」这类寒暄同样值得放一条用例（09 §5）：断言正文里出现本模块的常用场景说法、**没有**
出现模块编码回声，就把「用户第一句话拿到什么」钉住了。

### 4.3 预期值要按「口径」写，不要按「快照」写

测试库的数据会变（同步、清洗、补数）。把某天的行数硬编成 `== 137`，一周后它就是个假失败。
稳的写法：

- **口径断言**：列名/字段构成、非空、类型、排序方向、Top N 的长度、数值区间。
- **关系断言**：合计 == 分项之和；同一问题换个问法结果一致；筛选后行数 ≤ 筛选前。
- **金标准（golden）用例**：确实需要精确值时，把参考 SQL 一并写进用例，让用例自己去取当下的
  期望值再比对——参考 SQL 就是 `docs/testcases/` 里要求的那一份。

### 4.4 一条用例只回答一个问题

失败时你希望立刻知道它坏在哪一层。建议把断言按层分开写，并让报告显示是哪层挂的：

| 层 | 断言什么 | 挂了说明 |
|---|---|---|
| 路由 | `module` | 意图识别/关键词配置问题 |
| 取数 | `query_count > 0`、`trace.queries` 的 SQL | SQL 生成/参数绑定问题 |
| 数字 | `tables` / `charts` 的数值 | 口径错或沙箱计算错 |
| 呈现 | `answer` 的包含/排除、列名 | 违反 [09 答案呈现规范](09-answer-presentation.md) |

### 4.5 别用它做压测

它跑的是真实模型与真实库。并发建议 ≤ 4，用例之间不要互相依赖（每条自带 `target`、不共用
`conversation_id`），这样失败可以单独重跑。

### 4.6 多轮用例（上下文理解）

把上一轮响应里的 `conversation_id` 原样带进下一轮即续聊。两层上下文都能测：

| 层 | 怎么测 | 断言 |
|---|---|---|
| 路由粘性 | 两轮都**不带** `target`，第二轮问省略式追问（「那上个月呢」） | `module` 仍是第一轮那个 |
| 模块理解 | 两轮都带同一个 `target`，第二轮用指代（「这批物料的到货情况呢」） | 答案确实接着上一轮说 |

模块侧读历史的标准姿势是 `forge_core.conversation.conversation_messages(ctx, request)`
（见 [02 SDK 参考](02-sdk-reference.md)）——它拿到的就是本会话前几轮，与真实用户请求同一套。

几条硬性质，用例设计时得知道：

- 历史只存在平台**进程内存**里（不落库），与真实会话完全隔离：`conversation_id` 填一个真实
  会话的 id 也读不到那边的历史，只会得到一个空会话。
- 平台重启 → 历史没了。多轮用例要能独立重跑，别跨流水线复用会话。
- 一条多轮用例的几轮之间不要并发，按顺序发。
- 进程内会话有上限（500 个，按创建序淘汰）。串行跑不会踩到；真踩到的表现是老会话
  「突然变成第一轮」，此时把多轮用例挪到跑批靠后的位置即可。

---

## 5. 参考实现

建仓脚手架已经带了一份可直接跑的 runner 与用例集样例：

| 文件 | 作用 |
|---|---|
| `scripts/qa_test.py` | 读用例集 → 逐条调 `/test/chat` → 断言 → 打印报告，失败退出码非零 |
| `docs/testcases/golden/cases.example.json` | 用例集格式样例 |

跑法：

```bash
export FORGE_TEST_BASE_URL=http://<平台主机>:8090
export FORGE_TEST_API_KEY=fdt_xxxxxxxx.yyyyyyyy
uv run python scripts/qa_test.py docs/testcases/golden/cases.example.json
```

最小调用（自己写 runner 时的核心就这几行）：

```python
import httpx

resp = httpx.post(
    f"{base}/test/chat",
    headers={"Authorization": f"Bearer {key}"},
    json={"query": "上个月延期最多的三个项目", "target": "MAT"},
    timeout=120,          # 真实模型 + 真实库，别用默认 5 秒
)
resp.raise_for_status()
body = resp.json()

assert body["error"] is None, body["error"]
assert body["module"] == "MAT"
assert body["tables"], "本轮没有产出表格"
assert len(body["tables"][0]["rows"]) == 3
```

### 用例集格式

```json
{
  "cases": [
    {
      "id": "mat-001",
      "query": "上个月延期最多的三个项目",
      "target": "MAT",
      "expect": {
        "module": "MAT",
        "no_error": true,
        "min_queries": 1,
        "tables": {"count": 1, "columns": ["项目编号", "延期天数"], "row_count": 3},
        "answer_contains": ["延期"],
        "answer_not_contains": ["prj_dly_days", "dbo."]
      },
      "note": "口径：按自然月；参考 SQL 见 docs/testcases/golden/mat-001.sql"
    }
  ]
}
```

`expect` 的每个键都是可选的——只写你这条用例真正关心的那几项（§4.4）。

---

## 6. 接进 CI

在业务仓 `.gitlab-ci.yml` 里加一个**手动或定时**的 job（别挂在每次 push 上：它打真实模型，慢且吵）：

```yaml
qa-regression:
  stage: test
  when: manual                      # 或 rules: - if: $CI_PIPELINE_SOURCE == "schedule"
  variables:
    FORGE_TEST_BASE_URL: http://<平台测试机>:8090
  script:
    - uv sync
    - uv run python scripts/qa_test.py docs/testcases/golden/cases.json
```

`FORGE_TEST_API_KEY` 配成 GitLab **CI/CD Variables**（Masked + Protected），不要写进 yml。

同一对凭据还有一个用处：模板自带的 `contracts-check` job 用它跑 `forge capabilities pull --check`，查你依赖的
能力签名有没有漂移（仓里有 `tests/contracts/*.json` 才跑，见 [06 · capabilities](06-cli-reference.md#capabilities--能力签名快照)）。
勾了 Protected 时 feature 分支的 MR 流水线拿不到 key，那个 job 会跳过，develop → main 的 MR 照常检查。

建议的时机：**发预发布 tag、测试环境自动装配完成之后**跑一轮全量（发版流程见 [08](08-release-and-assembly.md)）。
这样"这个版本答得对不对"在进正式环境之前就有答案。

---

## 7. 排错

| 现象 | 多半是 |
|---|---|
| 404 `TEST_API_DISABLED` | 目标平台没开通道，或你打到了正式机 |
| 403 `TEST_MODULE_NOT_ALLOWED` | key 没授权这个模块；`GET /test/modules` 看实际清单 |
| `module` 为 null 且 `clarify` 非 null | 问题被判为不明确、答前阻断了。这是**路由/意图**问题，不是取数问题 |
| `error.code` 为 `NOT_AUTHORIZED_FOR_MODULE` | `target` 不在这把 key 的授权树里（同 403，只是走到了管道内） |
| `query_count == 0` 但有答案 | 模块没取数就答了——这通常是**最该修的一类失败** |
| 调用方答案看着正常，却像没用上对方的数据 | 能力调用失败了，而调用方模块自己捕获、降级作答。带 `include_trace` 看 `trace.invocations` 的 `error_code` / `problems` |
| key 只授权了自己的模块，一轮里调对方仍报 `NOT_AUTHORIZED_FOR_MODULE` | 依赖闭包按**平台上装配的**你那一版 manifest 算：新加的依赖要等新版本装配上测试环境；或平台还没升到带依赖闭包的版本 |
| `forge capabilities pull` 报「平台上拿不到 X 的签名」 | 同上一条的两种原因之一；或你的模块在平台上被隔离了——看输出末尾「没在服务」那段（即 §3.6 的 `unavailable`），多半是对方删了你依赖的能力 |
| 调用方报 `CAPABILITY_RESULT_INVALID`，不知道是谁的锅 | 归责被调方（返回不合它自己的签名）。被调方拿自己的 key 用 `/test/invoke`（§3.7）按同样的实参直调一次，`problems` 会指出差哪一列 |
| `/test/invoke` 报 `CAPABILITY_ARGUMENT_INVALID`，`message` 说「提供了多个版本」 | 你的模块同一能力有多个版本在服务，请求里显式给 `version` |
| 结果与 Admin Console 调试对话不一致 | 调试对话走的是管理员身份与另一条 channel；但两者权限都是全放开，若仍不同，看 `trace.queries` 的 SQL 差异 |
| 想在 Admin 审计页找这一轮 | **找不到，这是设计**：测试流量不落库。要明细就带 `include_trace` 重跑 |
| 回归跑完，平台磁盘涨了一截 | 你的模块调了 `ctx.files` 导出文件 —— 见下方说明，这是**唯一**会在测试通道留下真实产物的东西 |

> 📎 **`ctx.files` 是「测试流量不落库」的唯一例外**：模块在本通道里导出文件照样真的落盘、
> 真的签发链接。这是刻意的——回归要验的恰恰是「文件生成得对不对」，给个假句柄等于这条代码
> 路径根本没被测到。代价是**大批量回归会积文件**（24 小时后链接失效并被归档，但**不删除**）。
> 跑上千轮的全量回归前，若你的模块每轮都导出，先跟平台运维打个招呼。

---

## 相关

- [09 答案呈现规范](09-answer-presentation.md) —— §4.2 的正文断言就是在检查它
- [08 发布与装配触发](08-release-and-assembly.md) —— 什么时候跑全量回归
- [06 forge CLI 速查](06-cli-reference.md) —— `forge eval routing` 路由质量评测、`forge capabilities pull` 拉取被调方签名
- `docs/testcases/README.md`（你的仓里）—— 用例集怎么写、golden 与 manual 两份产物
