# INFO 系统对接 —— DataForge2 平台 v2 API 协议

> **本文档是交付 INFO 前端团队的对接唯一信源**（2026-07-06 定稿 v1.0）。
> 协议由平台方定义与维护（决策记录：[2026-07-06-INFO对接v2-API协议定稿.md](../decisions/2026-07-06-INFO对接v2-API协议定稿.md)）；
> 平台侧实现位于 `packages/forge-platform/src/forge_platform/gateway/api_v2.py`，
> 行为变更必须同步本文档并更新文末变更记录。

## 1. 概述

- **定位**：INFO 系统聊天 UI ↔ DataForge2 Agent Platform 的原生接口。用户在 INFO 页面提问，
  平台完成 鉴权 → 权限白名单路由 → 业务模块执行 → **SSE 流式**回传全过程。
- **与 Dify 兼容接口（/v1）的关系**：`/v1/*` 曾是过渡期兼容 facade，INFO 前端全部迁到本 v2
  协议后已于 **2026-10-12 整体下线**（[决策](../decisions/2026-10-12-下线Dify兼容面v1.md)），
  请求 `/v1/*` 一律 404。本 v2 协议是平台唯一的终端用户接口。下文出现的 `/v1` 字样仅作迁移对照。
- **与测试通道（/test）的关系**：`/test/*` 是业务模块仓跑问答准确性回归的内部通道
  （非流式、权限绿灯、不落库，默认关闭），**与 INFO 前端无关**，任何终端用户链路都不得使用它。
  见 [业务仓自动化测试指引](../dev/10-automated-testing.md)。
- **基址**：`http://<平台服务器>:8090`（端口按部署 `.env` 的 `FORGE_PORT` 而定；生产建议经
  Nginx 反代，走反代时基址以运维提供为准）。
- **编码**：请求/响应一律 UTF-8 JSON；SSE 为 `text/event-stream`。

## 2. 通用约定

### 2.1 身份与鉴权（除 app-info 外每个端点都要求）

| 项 | 说明 |
|---|---|
| `user_id` | 终端用户工号/账号，由 INFO 前端传入（GET/DELETE 端点放 query 参数，POST/PATCH 端点放请求体）。**必须是 token 本人的工号**（见下） |
| token | 该用户的 INFO 访问令牌。**规范载体：`Authorization: Bearer <token>` 请求头**；POST/PATCH 端点也兼容请求体 `token` 字段（二者同时给时请求体优先） |

> **唯一例外**：`GET /v2/app-info`（第 8 节）不要求身份 —— 它只返回固定展示文案、不含任何
> 用户数据，前端在拿到 token 之前就要用它渲染欢迎语。其余端点一律 fail-closed。

平台收到请求后，持该 token 调 INFO 授权接口获取用户的 AgentNode 授权树：

- 取树失败（token 无效/过期、INFO 接口异常）→ 一律 **401**，请求不被处理（fail-closed）。
- **`user_id` 与 token 绑定**（2026-10-13 起）：平台把请求里的 `user_id` 与授权接口回显的 token
  归属（`GetAgentMenu2` 响应的 `Data.UserId`）比对，**去首尾空白后逐字符相等、区分大小写**；
  不一致或 INFO 未回显 → **401 `USER_TOKEN_MISMATCH`**。会话/分享/反馈/上传的归属都按 `user_id`
  判定，不绑定的话持自己 token 填别人工号即可冒充对方。前端照常传当前登录用户的工号即可，
  **无需改动**；若收到该错误，说明传入的 `user_id` 与登录态不是同一人（多为账号切换后未刷新）。
- 授权树同时是路由与模块访问的**硬白名单**：用户无权的助手既不可被路由到，也不可直达。

### 2.2 错误响应格式（非 SSE 端点及 SSE 建立前）

```json
{ "code": "PERMISSION_DENIED", "message": "您没有执行该操作的权限，或授权信息已失效，请重新登录后重试。" }
```

> `message` 是**面向用户的安全文案**，不含后台实现明细（协议/校验/SQL 等）；排障请依据平台服务端日志
> （按 `X-Request-Id` 检索），前端仅展示 `message` 即可。`code` 用于前端分支处理。

| HTTP 状态 | 场景 |
|---|---|
| 401 | token 无效/授权获取失败；`user_id` 与 token 归属不一致（`USER_TOKEN_MISMATCH`） |
| 403 | 访问/反馈/续聊**他人会话**（`CONVERSATION_FORBIDDEN`） |
| 404 | 会话不存在（`CONVERSATION_NOT_FOUND`） |
| 422 | 请求体字段校验失败（FastAPI 默认格式） |

SSE 流建立**之后**发生的错误不再改变 HTTP 状态码，而是以 `error` 事件流回（见 3.3），
且流仍以 `end` 事件正常收尾。

### 2.3 服务可用性探测（`/v1/info` 的平替）

Dify 兼容面上有个 `GET /v1/info`，前端拿它的 `200` 当「后端还活着」的判据。v2 有两个平替，
按你真正想知道的那件事选：

| 想知道的事 | 用 | 要不要凭据 |
|---|---|---|
| **服务在不在**（最小替换） | `GET /v2/app-info`（§8） | **不要** |
| **服务健不健康**（模块是否全部就位） | `GET /healthz` | **不要** |

**推荐 `GET /v2/app-info`**，理由不是它更像 `/v1/info`，而是**前端启动时本来就要调它**拉开场白
（§8）——把「拉开场白成功」直接当作「后端可用」，等于零额外请求。它也是 v2 唯一免鉴权的端点，
在拿到用户 token 之前就能调，正好覆盖「登录前先探一下」的场景。
> 顺带一提：`/v1/*`（含 `/v1/info`）已于 2026-10-12 下线，仍在调它的代码会拿到 404。

**`GET /healthz`** 是平台自带的存活探针（**不在 `/v2` 之下**，是平台级端点，同样免鉴权、
已在 CORS 白名单内）。它比 `app-info` 多回一层运行状态：

```json
{ "status": "ok", "modules": ["MATERIAL_QUERY", "PAX_KB"], "failed_modules": [], "capabilities": {…}, "log": {…} }
```

用它时三件事必须知道：

1. ⚠️ **`degraded` 也回 200**，不是 5xx。这是刻意的——「20 个助手里挂了 1 个、其余全部正常服务」
   的进程不该被判死重启。**所以不要只看状态码**：要区分健康与降级，看 `status` 字段
   （`ok` / `degraded`）与 `failed_modules`。
2. 它会回**模块编码清单**与**平台能力开关名**（不含库名、内网地址这类明细，那些刻意排除了）。
   要不要把这些暴露到终端用户的浏览器里，请与平台运维确认——必要时由反代限制来源网段。
3. 平台的访问日志**刻意跳过 `/healthz`**（探针按秒来），高频调用不会污染排查线索。

**但两者都回答不了「现在能不能正常问答」**：`/v1/info` 与 `/v2/app-info` 返回的都是固定文案，
进程活着就回 200；它们证明不了 INFO 授权接口通不通、数据库通不通。`/healthz` 更近一步
（模块装载状态是真的），但也不代表下游数据源此刻可用。

故**不建议前端做运行期轮询探活**。真实的可用性以那一次 `/v2/chat` 的结果为准，按三种失败
分别提示即可：网络层失败（连不上/超时）→「服务暂时不可用」；`401` → 引导重新登录；
流内 `error` 事件 → 展示它的 `message`。启动时探一次用于渲染首屏，就够了。

## 3. POST /v2/chat —— 流式问答（核心端点）

### 3.1 请求

```http
POST /v2/chat
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "query": "查一下料号 X100 最近的到货情况",
  "user_id": "10024001",
  "conversation_id": null,
  "attributes": { "departmentId": "D012" }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | ✅ | 用户问题原文 |
| `user_id` | string | ✅ | 用户工号/账号 |
| `conversation_id` | string \| null | ✕ | 续聊传上一轮返回的值；**首轮不传/传 null**，平台自动新建。传了则校验归属：他人会话 `403 CONVERSATION_FORBIDDEN`、本人已删除的会话 `404 CONVERSATION_NOT_FOUND`；平台从未见过的会话号（如 §8.2 上传时预分配的）视为新会话 |
| `attributes` | object | ✕ | 用户属性（如 `departmentId`）；INFO 有则传，作用户元数据（日志/扩展）。**不参与权限判断**——数据权限完全由 INFO 按用户下发的 `privileges` 字面量规则驱动 |
| `token` | string | ✕ | 兼容载体，等价于 Authorization 头 |
| `target` | string \| null | ✕ | 直达指定模块编码、跳过语义路由。普通对话界面不传（由平台路由）；**带 `ext_param` 的调用请传**（见 3.1.1）。业务页面的任务调用请改走 §3.8 `/v2/tasks`，那里它是必填 |
| `ext_param` | object \| null | ✕ | **客户端定制参数**（2026-09-08 新增），原样交给业务模块。见 3.1.1 |
| `file_ids` | string[] | ✕ | **本轮引用的上传文件**（2026-09-09 新增）：先经 §8.2 `POST /v2/files` 换到 `file_id`，在这里按数组引用。平台逐个硬校验归属，任一不通过即拒绝整轮。见 §8.2 |

#### 3.1.1 `ext_param` —— 客户端定制参数（2026-09-08 新增）

给「不只是查询、还要**加工**客户端给的正文」的助手用（润色问题描述、对解决方案提建议……）：
这类调用得告诉助手「本轮要干的是哪件事」，而这件事是**调用方与该业务模块之间的私有约定**，
平台不预先知道、也不解释。

```json
{
  "query": "屏幕偶发闪烁",
  "user_id": "10024001",
  "target": "CUSTOMER_ISSUE",
  "ext_param": { "task": "polish_issue", "style": "正式" }
}
```

- **`task` 是唯一的保留键，且必填**（非空字符串，**≤ 64 字符、不含控制字符**）：取值由
  调用方与业务模块约定，平台不枚举、不识别、不据它分支，只把它记进日志与归档用于「这轮在
  干什么」的归因（**不入库**）。其余键名与结构**完全由业务模块自定**，平台不解析、不校验、
  不改写。
- 上限：序列化后 **64KB**、嵌套 **6 层**；不合法一律 `400 invalid_param` 并说明原因，
  **不会静默丢弃**。
- ⚠️ **不参与权限判断**（同 `attributes`）：它是客户端输入，数据权限只认 INFO 下发的授权树
  与 `privileges`。
- 用它时**请显式传 `target`**：平台的语义路由吃的是 `query`，正文挪进 `ext_param` 后
  `query` 若只剩一个短词，路由会失准。
- **主体正文永远放 `query`，不要放进信封**：`query` 是会话历史落库的用户正文、语义路由的
  输入、审计页显示的那一列，而 `ext_param` **不入库、不进历史回读**（只进平台侧归档，供联调
  排查）。一次要传多段正文时，**被加工的那段仍在 `query`**，其余作为上下文进 `ext_param`。
  上例即：`query` = 待润色的问题描述，信封里只有任务码与选项。
- v1 兼容面同名参数放在 `inputs.ext_param`（也接受其 JSON 字符串形式）。
- **业务页面的任务调用（自动审核、填单助手……）请走 §3.8 `/v2/tasks`**：请求体与本端点完全相同，
  但不进用户的会话列表、在统计里单独计为「业务调用」。`/v2/chat` 上的 `ext_param` 保持可用，
  未切换的页面不受影响。

### 3.2 响应

- 成功：`200`，`Content-Type: text/event-stream`，按 SSE 协议持续推送事件（见 3.3）。
- **响应头**（流开始前即可读取，跨域场景已在 CORS `expose_headers` 放开）：
  - `X-Conversation-Id`：本轮会话 ID。首轮问答由平台生成，**前端必须保存**并在续聊时传回。
  - `X-Request-Id`：本次问答的请求 ID，**反馈接口（第 7 节）按它定位这次问答**；
    停止（§3.6）与断线续接（§3.7）也按它。
- 失败（流开始前，2.2 错误格式）：鉴权 `401`；续聊他人会话 `403`、续聊已删除会话 `404`；
  以及 2026-10-15 起的几种开工拒绝（[决策](../decisions/2026-10-15-问答后台生成与断线续接.md)）：

  | HTTP | code | 含义 | 前端建议 |
  |---|---|---|---|
  | `409` | `CONVERSATION_BUSY` | 该会话上一轮回复还在生成中（同一会话同时只允许一轮） | 提示等待，或先停止上一轮（§3.6） |
  | `429` | `TOO_MANY_RUNNING_TURNS` | 该用户同时在生成的回复已达上限（默认 3 个，跨会话计） | 提示等其他会话答完 |
  | `503` | `TURNS_SATURATED` | 全平台同时在生成的回复已达上限 | 稍后重试 |
  | `503` | `PLATFORM_RESTARTING` | 平台正在重启 | 稍后重试 |

- ⚠️ **断开连接不会停止生成**（2026-10-15 起）：本轮在平台后台生成，这条 SSE 只是「订阅」。
  用户关页、切到别的会话、`abort()` 掉请求，生成都照常跑完并落库；要停止请调 §3.6。

### 3.3 SSE 事件协议

wire 格式（标准 SSE，事件之间空行分隔）：

```
id: <seq>
event: <type>
data: {"type":"<type>","source":"<模块编码>","ts":1751780000.123,"data":{...}}
```

`id` 行（2026-10-15 新增）是本轮内的**事件序号**，从 1 起逐个递增。断线后拿最后收到的序号
续接（§3.7）。只按 `data` 行解析的既有实现不受影响（§3.5 参考实现即如此）。

`data` 行是完整 JSON：`type` 与 event 行一致；`source` 是产生该事件的模块编码
（平台自身事件为 `"platform"`）；`ts` 为 Unix 秒；业务负载在内层 `data` 字段。

**事件类型总表**（内层 `data` 结构）：

| type | 内层 data | 说明 |
|---|---|---|
| `delta` | `{"text": "…"}` | 正文 token 流，**按序拼接即答案正文**（Markdown） |
| `tool_call` | `{"tool": "…", "arguments": {…}}` | 模块开始调用工具（展示「执行中」过程用） |
| `tool_result_meta` | `{"tool": "…", …}` | 工具结果元信息（行数/耗时等，不含数据体） |
| `table` | `{"title": "…", "columns": ["…"], "rows": [[…]]}` | 结构化表格产物，前端渲染为表格 |
| `chart` | `{"chart_type": "line\|bar\|pie", "title": "…", "x": {"name": "…", "data": […]}, "series": [{"name": "…", "data": […]}], "unit": "…", "style": {…}}` | 图表产物，**平台无关的抽象 spec**（只说「画什么」）。`pie` 可省 `x`。数值一律来自沙箱计算，前端直接照画、不要再算。**可选** `style`（缺省不出现）是模块给的 **echarts option 片段**（如 `{"series": {"smooth": true}}` 平滑曲线、`{"series": {"radius": ["40%","70%"]}}` 环形图）：用 echarts 渲染的前端把 spec 转成 option 后把它深合并进去（`style.series` 为 dict 套到每条序列、为 list 按下标对齐；**不要**让它覆盖 `series[].data` / `series[].type` / `xAxis.data`——平台侧已丢弃这些键，前端同样别认）。历史回读的 ```echarts 代码块里 option 已经合并好，直接渲染即可 |
| `citation` | `{"items": [{…}]}` | 引用溯源列表（item 字段见下方 §3.3.1，**渲染方式与 table/chart 不同**） |
| `progress` | `{"stage": "…", "detail": "…"}` | 阶段进度（如「正在生成 SQL」） |
| `clarify` | `{"question": "…", "options": ["…"], "guide_text": "…", "recommendations": [{"id": "…", "name": "…", "label": "…", "query": "…"}]}` | 澄清引导（**答前阻断**：问题不明确，本轮不分发模块）。`recommendations` 非空时渲染为可点按钮（`label` = 按钮文字，`query` = 点击后**作为新 query 再次调用 /v2/chat，带同一 conversation_id**）；`options` 是纯文本兜底 |
| `suggestions` | `{"guide_text": "…", "recommendations": [{"id": "…", "name": "…", "label": "…", "query": "…"}]}` | 追问建议（**答后附加**：回答已完整，引导下一步）。payload 与 `clarify` 的 `recommendations` 同构，前端可复用同一按钮组件；**但生命周期不同，别与 clarify 混为一谈**（见下方说明） |
| `error` | `{"code": "…", "message": "…", "fatal": true}` | 错误事件；`fatal: true` 表示本轮终止（随后仍有 `end`） |
| `end` | `{"status": "completed", "usage": {…}, "request_id": "…", "conversation_id": "…", "conversation_title": "…"}` | **流结束标志，每次请求恰好一个、必为最后一个事件**；携带的 `request_id` 供反馈接口引用；`status`、`usage` 与 `conversation_title` 见下方说明 |

**`end.status` —— 本轮回复的终态**（2026-10-15 新增，[决策](../decisions/2026-10-15-问答后台生成与断线续接.md)）：

| 值 | 含义 | 前端建议 |
|---|---|---|
| `completed` | 正常答完（含澄清轮、出错轮——错误文案本身就是这一轮的回答） | 正常渲染 |
| `stopped` | 用户主动停止（§3.6），正文是停下那一刻的部分 | 标「已停止」 |
| `interrupted` | 非用户意愿的中断：超时、平台重启。正文**可能缺尾巴**；流里在 `end` 之前会先有一个 `error`（`code: TURN_INTERRUPTED`） | 标「内容可能不完整」，可提供「重新提问」 |

历史回读（§6）每条消息的 `status` 与这里同一套取值，刷新后照样标得出来。

**`end.usage` —— 本轮 LLM 用量**（2026-07-15 起真实下发，此前恒为空对象）：

| 情形 | `usage` |
|---|---|
| 本轮用量已知 | `{"prompt_tokens": 1033, "completion_tokens": 135, "total_tokens": 1168}` |
| 本轮用量未知 | `{}`（空对象） |

- 统计口径 = 本轮**全部** LLM 调用之和（平台路由分类/澄清 + 业务模块内部调用）。
- **未知 ≠ 0**：本轮没调用模型（如澄清轮），或模块未上报用量时，一律给空对象而**不是一串 0**。
  前端不得把缺失当零展示，建议显示「—」或直接不展示。
- 字段是**增量**的：`usage` 键本就在协议里（此前恒为空），既有前端不受影响；后续可能新增
  子字段（如分模块拆分），按「未识别字段必须忽略」处理即可。

**`end.conversation_title` —— 本轮刚生成的会话标题**（2026-09-23 起，可选字段）：

平台会在**首轮**（以及第 3/6 轮、本轮路由换了助手时）用本地模型把会话标题从「首问截断」
改写成一句尽可能短、不带标点的标题（详见 §5）。生成任务与本轮回答并发，完成得及时就随 `end`
一起下发。

- **这个键经常不出现**，不出现是正常状态，绝不是错误：本轮没到刷新时机、用户手动改过名、
  生成失败或没赶上本轮收尾，都不会带它。前端按「有就用、没有就别动侧边栏」处理。
- 带了就是**已经落库的最终值**，前端可以直接用它更新侧边栏那一条，
  不必为此重拉 `GET /v2/conversations`。
- 没带而标题其实变了（生成晚于本轮收尾）时，下次拉会话列表自然会拿到新标题。

**`clarify` 与 `suggestions` 的区别**（payload 同构，语义与生命周期完全不同）：

| | `clarify` | `suggestions` |
|---|---|---|
| 时机 | **答前阻断**：路由/参数不明确 | **答后附加**：回答已完整 |
| 本轮有无实质回答 | 无（网关直接收尾，不分发模块） | 有 |
| 前端语义 | 「我得先问清楚才能答」 | 「答完了，你可能还想问」 |

两者都以 `recommendations[].query` 作为**下一轮的新 query**（带同一 `conversation_id` 重新调用
`/v2/chat`），故按钮组件可复用；但**不要把 suggestions 渲染成「还没答」的样子**。

**前端处理保证与建议**：

- 事件流**必以恰好一个 `end` 收尾**（包括 clarify/error 路径），前端以收到 `end` 作为本轮结束。
- **收到 `end` 时，本轮已落库**（2026-10-12 起保证）：本轮的助手回复（`GET …/messages` 可读）与
  「最近使用」记录（`GET /v2/recent-modules` 可读）都在 `end` 下发**之前**写入。前端若想在 `end`
  后立刻刷新历史或最近使用菜单，不必延时或重试。（2026-10-15 起客户端断开不影响生成，
  本轮照样走到 `end` 才算结束，这条保证对断开后续接 / 回来读历史同样成立。）
- 未识别的事件类型**必须忽略**（协议向后兼容：平台可能新增事件类型）。
- `delta` 只增不改；`table`/`chart` 独立于正文，建议以卡片形式插入消息流。
  **它们与 `delta` 是交错下发的**（模块可能先说一句、给张表、再说一句），按到达顺序插入才
  是模块想表达的次序；把正文拼成一整块、把表格图表甩到末尾会读错。
  ⚠️ **`citation` 不在此列**：它是整轮聚合的一份参考清单，渲染在回答**末尾**（见 §3.3.1）。
  到达顺序仍然重要——它决定的是清单里的次序，而不是插入正文的位置。
- 最小实现只需处理 `delta` / `clarify` / `error` / `end` 四类，即可获得完整可用的对话体验；
  其余类型用于过程可视化增强。
- **`table` / `chart` 在实时流里只有事件、正文里没有它们的文本形态**：平台另把它们投影进
  **落库正文**（`table` → Markdown 表格，`chart` → ` ```echarts ` 代码块），故 §6 历史回读
  拿得到表和图，既有前端零改造即可渲染。实时流请直接消费这两个事件的抽象结构自行渲染。
  ⚠️ 两处同源但载体不同，**别在实时流里等一个不会来的 Markdown 表格 / echarts 代码块**，
  也别把事件与正文里的投影**渲染两遍**（同一轮里两者不会同时出现在同一载体上）。

### 3.3.1 `citation` 事件与引用角标渲染（2026-07-28 定稿）

**item 字段**（平台已归一化，故不论后端是存量 Dify 应用还是迁移后的平台模块，形状一致）：

| 字段 | 必有 | 说明 |
|---|---|---|
| `document_id` | ✅ | 文档 ID。正文里的引用角标按它回指本条 |
| `document_name` | ✅ | 文件名（**已剥离权限标签前缀**，可直接展示） |
| `url` | ✕ | 文档预览地址。**没有这个键 = 这篇文档没有可点链接**（不会给空串） |
| `data_source_type` | ✕ | 与 `url` **同值**。v1 Dify 兼容面遗留，v2 前端**忽略它**，只认 `url` |
| `content` | ✕ | 命中切片正文（做悬浮预览用） |
| `score` / `dataset_id` / `dataset_name` | ✕ | 相关度与来源库 |

未列出的键一律忽略（协议向后兼容）。

**三条渲染规则**（三者环环相扣，做一半会得到对不上号的编号）：

1. **聚合成一份清单**：把本轮所有 `citation` 事件的 items 合并，**按 `document_id` 去重、
   保留首次到达顺序**。⚠️ 这一步不能省：items 是**按命中切片**给的，一篇文档命中 3 个切片
   就有 3 条（可能还分散在多个事件里）。去重后才是「参考了哪几篇文档」，也才让第 3 条的
   「角标数字 = 清单序号」有唯一解。
2. **回答末尾按该顺序列出全部 `document_name`**（有 `url` 的做成链接）。这份清单的序号
   （1、2、3…）是下一条的依据。
3. **正文里的 `<sup>[document_id]</sup>` 渲染成可点角标**：按 `document_id` 匹配到清单里的
   那一条，**角标显示的数字 = 它在末尾清单里的序号**，点击跳 `url`。
   - ⚠️ 角标格式**带方括号**：`<sup>[0000097012]</sup>`。
   - 正文是 Markdown，但这个标签**不要**靠开启「解析裸 HTML」来渲染（那会连带放开 XSS 面）；
     推荐在送进 Markdown 渲染器前正则替换成自己的角标组件。平台的 Admin Console 调试页就是
     这么做的，可直接参考 `MarkdownView.tsx`。
   - **匹配不到 `document_id`** 时不要把 `<sup>[…]</sup>` 原样漏成文本给用户看；按无链接角标
     渲染或整体隐去。

历史回读（§6）的 `citations` 字段与实时流的 items 是**同一份数据**，正文里的角标也照样落库，
故按同样三步渲染即可 —— 刷新页面后引用不会断。

### 3.4 响应示例（完整一轮）

```
event: progress
data: {"type":"progress","source":"MATERIAL_QUERY","ts":1751780000.1,"data":{"stage":"routing","detail":"已路由到物料助手"}}

event: delta
data: {"type":"delta","source":"MATERIAL_QUERY","ts":1751780000.6,"data":{"text":"料号 X100 最近 30 天"}}

event: delta
data: {"type":"delta","source":"MATERIAL_QUERY","ts":1751780000.7,"data":{"text":"共到货 12 批……"}}

event: end
data: {"type":"end","source":"platform","ts":1751780001.2,"data":{"usage":{"prompt_tokens":1033,"completion_tokens":135,"total_tokens":1168},"request_id":"f5a…","conversation_id":"9c2…"}}
```

### 3.5 前端参考实现（fetch 流式解析）

POST + 自定义头无法用 `EventSource`，用 `fetch` + `ReadableStream`：

```javascript
async function chat({ query, userId, token, conversationId, onEvent }) {
  const resp = await fetch(`${BASE}/v2/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ query, user_id: userId, conversation_id: conversationId }),
  });
  if (!resp.ok) throw await resp.json();          // 401 等：{code, message}
  const nextConversationId = resp.headers.get("X-Conversation-Id");
  const requestId = resp.headers.get("X-Request-Id");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {     // SSE 事件以空行分隔
      const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const dataLine = block.split("\n").find((l) => l.startsWith("data:"));
      if (dataLine) onEvent(JSON.parse(dataLine.slice(5)));
    }
  }
  return { conversationId: nextConversationId, requestId };
}
```

### 3.6 停止生成

> **2026-10-15 起改为显式接口**（[决策](../decisions/2026-10-15-问答后台生成与断线续接.md)，取代本节原文「直接 abort 掉请求即可、
> v2 不需要单独的 stop 接口」）。**abort 从此只代表「这个页面不看了」，不再停止生成。**

```http
POST /v2/chat/{request_id}/stop
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{ "user_id": "10024001" }
```

```json
{ "request_id": "f5a…", "stopping": true }
```

- `request_id` 取 `/v2/chat` 的响应头 `X-Request-Id`（流开始前即可拿到）。
- **立即返回**；本轮在事件之间收住，事件流随后以 `end`（`status: "stopped"`）结束，已产出的部分
  按 stopped 落库（§6 的 `status`）。还连着流的话等 `end` 即可；已经断开的不必管它。
- `stopping: false` = 本轮此刻**已经结束**了（答完了 / 已停过）。不是错误，按已结束处理即可。
- 只认本人；不存在、已过保留期、或不是你的 → `404 TURN_NOT_FOUND`。
- ⚠️ 生效粒度是**事件之间**：模块若正卡在一步慢操作里（比如一条已经发出去的慢查询），平台会在
  几秒宽限后强制收住本轮；那一步在数据库侧照样跑完，只是结果不再被使用。

```javascript
await fetch(`${BASE}/v2/chat/${requestId}/stop`, {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  body: JSON.stringify({ user_id: userId }),
});
// 不要再 controller.abort() 当作停止——那只会让你看不到收尾的 end
```

### 3.7 后台生成与断线续接（2026-10-15 新增）

一轮回复在平台后台生成，与浏览器连接无关：用户可以切到别的页面、看别的会话、关掉浏览器，
回来时回复照样完整。前端需要做的是「回来时接上」：

```http
GET /v2/chat/{request_id}/events?user_id=10024001&after=17
Authorization: Bearer <token>
```

- 响应与 `/v2/chat` 同为 SSE：先补发序号 `after` 之后的全部事件，再跟实时事件，直到 `end`。
  `after` 不传时认 `Last-Event-ID` 请求头，都没有 = 从头重放整轮。
- **本轮生成中**、以及**结束后 10 分钟内**（部署可调）可续接；之后 `404 TURN_NOT_FOUND`，
  改读历史（§6）即可——那里是同一份完整内容。只认本人，他人的 request_id 同样 404。

**推荐的回到会话流程**：

1. 读历史 `GET /v2/conversations/{id}/messages`（§6）。
2. 最后一条 `assistant` 若 `status == "generating"`：它的 `content` 是**此刻的快照**，`stream_seq`
   是快照对应的序号。先渲染快照，再 `GET /v2/chat/{message_id}/events?after={stream_seq}` 接着
   渲染后续事件——两者恰好拼成完整一轮，不重不漏。（也可以忽略快照，`after=0` 从头重放。）
3. 收到 `end` 后，若用户此刻正看着这个会话，调 `POST /v2/conversations/{id}/read`（§5.4）。

> 只有正在生成的那一轮才需要续接。切回一个已答完的会话，读历史就够了。

## 3.8 POST /v2/tasks —— 业务任务调用（2026-11-03 新增）

给**嵌在业务页面里**的助手用：自动审核流程里的审核助手、填单页面的分析/润色助手等——调用方是
页面程序，不是用户在对话框里提问（[决策](../decisions/2026-11-03-任务面端点与任务级数据范围声明.md)）。

**与 `/v2/chat` 同构**：请求体字段、SSE 事件、响应头、`conversation_id` 续聊、断线续接
（`GET /v2/chat/{request_id}/events`）、停止（`POST /v2/chat/{request_id}/stop`）全部一样，
前端的流式解析代码可原样复用。差别只有三处：

| | `/v2/chat` | `/v2/tasks` |
|---|---|---|
| `target` | 可选（不传走语义路由） | **必填**，不路由 |
| `ext_param.task` | 有 `ext_param` 时必填 | **必填**，且须是该助手**声明过**的任务码 |
| 会话 | 出现在 §5 会话列表 | **不出现在会话列表**（§6 历史回读、改名、删除、反馈、分享照常可用） |

```http
POST /v2/tasks
Authorization: Bearer <处理者 / 审核者本人的 INFO token>
Content-Type: application/json
```

```json
{
  "query": "<待审核的合同正文>",
  "user_id": "10024001",
  "target": "CONTRACT_REVIEW",
  "ext_param": { "task": "review_contract", "contract_type": "采购" }
}
```

- **身份**：用触发这次任务的**处理者 / 审核者本人**的 token 与工号；平台照常按他的授权树判断能否
  使用该助手。没有「服务账号」这回事。
- **`target` 与 `task` 从哪来**：由业务助手的开发方给出（其对接说明列出每个任务的 `target`、
  `task`、`query` 放什么、`ext_param` 里还有哪些键）。业务页面**写成常量**即可；运行期可读 §4
  `/v2/modules` 里该助手的 `tasks` 判断当前用户能否使用（决定按钮显隐）。
- **主体正文放 `query`**（被审核 / 被润色的那段），其余参数进 `ext_param`，规则同 3.1.1。
- **续聊**：要对同一张单据追问时带上一次响应头里的 `conversation_id`，与 chat 完全相同。
  `/v2/tasks` 与 `/v2/chat` 可以互相续接对方建的会话；会话属于哪一类由**第一轮**的入口决定，
  之后不变（所以老会话被 `/v2/tasks` 续上后仍留在会话列表里，不会消失）。

**错误（全部在 SSE 建立之前，以 §2.2 JSON 返回）**：

| HTTP | `code` | 场景 |
|---|---|---|
| 400 | `invalid_param` | 缺 `target`，或 `ext_param` 缺 `task` / 不合法 |
| 401 | （同 §2.2） | token 无效 / 与 `user_id` 不符 |
| 403 | `NOT_AUTHORIZED_FOR_MODULE` | 当前用户无权使用该助手 |
| 404 | `MODULE_NOT_REGISTERED` | 有权限但该助手当前未上线 |
| 400 | `UNKNOWN_TASK` | 该助手没有声明这个任务码；响应另带 `available_tasks`（该助手可用任务码数组），便于排查拼写 |

被拒的调用不产生任何会话与记录。远程（Dify）助手不支持任务调用，一律得到 `UNKNOWN_TASK`。

## 4. GET /v2/modules —— 当前用户可用助手清单

渲染助手入口/切换列表用。返回 = 用户授权树 ∩ 平台已装配模块（无权或未上线的不出现）。

```http
GET /v2/modules?user_id=10024001
Authorization: Bearer <token>
```

```json
{
  "modules": [
    {
      "code": "MATERIAL_QUERY",
      "name": "物料助手",
      "description": "物料到货/库存/质量查询",
      "intents": ["查料号 X 的到货情况", "料号 X 最近的检验结果"],
      "tasks": []
    }
  ]
}
```

`intents` 是该助手的示例问题，可用作输入框提示/引导语。

`tasks`（2026-11-03 新增）是该助手可经 §3.8 `/v2/tasks` 调用的任务，没有则为空数组。每项：

```json
{
  "code": "review_contract",
  "name": "合同自动审核",
  "description": "审核流程节点调用：对合同正文给出风险点与修改建议",
  "query": "待审核的合同正文",
  "ext_param_schema": null
}
```

`code` 即 `ext_param.task` 的取值；`query` 说明 `query` 字段里放什么；`ext_param_schema` 是
`ext_param` 其余键的 JSON Schema（助手开发方提供，可能为 `null`，仅供参考，平台不据它校验）。
业务页面可据「该助手在列表里、且 `tasks` 里有这个 `code`」决定任务按钮显不显示。

## 4.1 GET /v2/recent-modules —— 最近使用的助手（2026-08-26 新增）

把该用户常用的助手顶到菜单前面用。返回 **最多 5 个**，按最近使用时间**降序**。

```http
GET /v2/recent-modules?user_id=10024001
Authorization: Bearer <token>
```

```json
{
  "modules": [
    {
      "code": "MATERIAL_QUERY",
      "name": "物料助手",
      "description": "物料到货/库存/质量查询",
      "intents": ["查料号 X 的到货情况"],
      "last_used_ts": 1751780100.9
    }
  ]
}
```

- 每项的字段与 §4 `/v2/modules` **逐字段一致**，只多一个 `last_used_ts`（epoch 秒，浮点，
  与会话列表的 `updated_ts` 同款）——同一套渲染代码可以画两个列表。
- **什么算「用过」**：用户在请求里**显式指定了** `target`（v1 面是 `inputs.selected_agent`），
  **且这一轮成功跟它对话了**。平台自动路由选中的模块**不算**（那是平台替他挑的，
  不是他点的），「点了但没权限 / 助手已下线 / 助手报错」的轮次也不算。
- **不足 5 个就返回不足 5 个**，新用户返回空数组 `[]` —— 这是合法状态，不是错误，
  前端按「暂无最近使用」渲染即可。平台不会拿更早的记录补足。
- 返回前按 **当前授权树 ∩ 平台已装配** 过滤：期间被收走权限、或已下线的助手当场消失，
  故本端点的返回**恒是 §4 `/v2/modules` 的子集**。
- **为什么是独立端点而不是并进 `/v2/modules`**：那份清单答的是「你能用哪些」（随授权变），
  本端点答的是「你最近用了哪些」（随行为变），前端可以按各自的时机分别刷新。

> Dify 兼容面（/v1）曾有对应端点 `GET /v1/recent-agents?user=<工号>`（无授权过滤），
> 已随 /v1 于 2026-10-12 下线；本端点是唯一入口。

## 5. GET /v2/conversations —— 我的会话列表

> 只列**对话**产生的会话；§3.8 `/v2/tasks` 发起的任务会话不在列表里（按 id 回读照常可用）。

```http
GET /v2/conversations?user_id=10024001&limit=50
Authorization: Bearer <token>
```

```json
{
  "conversations": [
    {
      "conversation_id": "9c2…",
      "user_id": "10024001",
      "title": "查一下料号 X100 最近的到货情况",
      "created_ts": 1751780000.1,
      "updated_ts": 1751780100.9,
      "generating": false,
      "has_unread": true
    }
  ],
  "has_more": false,
  "limit": 50
}
```

- 按 `updated_ts` 倒序（最近活跃在前）；`limit` 默认 50，最大 200。
- 只返回该 `user_id` 名下会话。
- **`generating`（2026-10-15 新增）**：该会话此刻有一轮回复正在生成。侧边栏可据此显示「生成中」。
- **`has_unread`（2026-10-15 新增）**：该会话有**用户还没看过的回复**——最近一轮答完（或被中断）
  晚于前端上次调 §5.4 标已读的时刻。换设备也认得出（记在平台侧）。用户自己点停止的那一轮不算。
  存量会话一律 `false`。

**`title` 的来源**（2026-09-23 起）：

| 情形 | 标题 |
|---|---|
| 会话刚创建 | 首个问题截断（≤64 字符），**立即可见** |
| 平台已生成（开关开启时的常态） | 本地模型概括的一句话，尽可能短、不带标点；**不设字数上限、平台不截断**，侧边栏放不下时请前端自行省略显示 |
| 用户手动改过名 | 用户给的那个，**此后平台永不覆盖** |

- 生成时机是**收敛**的：第 1/3/6 轮，以及本轮路由到了别的助手时，此后不再变动。
  前端不必担心标题每轮都在跳。
- 标题变化**不会**改 `updated_ts`，不会把老会话顶到列表最前面。
- 生成是与回答并发的旁路，失败即保持原标题；该能力可按部署关闭（关闭时标题恒为首问截断）。
- 最新值随 `end.conversation_title` 下发（§3.2），也可从本接口读到。

### 5.1 游标分页（2026-08-04 新增）

会话多于一页时用 `last_id` 游标向后翻，**不是页码**：

| 参数 | 默认 | 说明 |
|---|---|---|
| `limit` | 50（最大 200） | 每页条数 |
| `last_id` | 空 | 上一页**最后一条**的 `conversation_id`；**空 = 第一页** |
| `sort_by` | `-updated_at` | `updated_at` / `-updated_at` / `created_at` / `-created_at`（`-` = 倒序） |

- 响应的 `has_more` 表示**还有没有下一页**，前端据它决定是否继续翻；`false` 即停止。
- ⚠️ **游标失效（`last_id` 指向的会话已被删除或不属于本人）→ 返回空列表 + `has_more: false`**，
  即干净停止，而**不会**回落到第一页。前端不要在拿到空页时重试同一个 `last_id`。
- 不传 `last_id` 时行为与加分页之前完全一致，`conversations` 键的形状也没变——
  只用第一页的既有前端**零改造**。

### 5.2 DELETE /v2/conversations/{conversation_id} —— 删除会话

```http
DELETE /v2/conversations/9c2…?user_id=10024001
Authorization: Bearer <token>
```

成功返回 `{"status": "ok"}`。

- **逻辑软删**：会话与消息对用户立即不可见（不再出现在列表、历史读取返回 404），
  底层保留以供审计/恢复，平台不做物理删除。
- 删过的会话再次删除 → `404`（视为不存在）。前端如需幂等，按 404 当作「已删除」处理即可。
- 归属硬校验：他人会话 `403`，不存在 `404`。

### 5.3 PATCH /v2/conversations/{conversation_id} —— 重命名会话

```http
PATCH /v2/conversations/9c2…
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{ "user_id": "10024001", "title": "X100 到货追踪" }
```

```json
{ "conversation_id": "9c2…", "title": "X100 到货追踪" }
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `user_id` | ✅ | 操作人 |
| `title` | ✅ | 新标题；**超长按 64 字符截断**（与首问截断同一套规则），空串 422 |
| `token` | ✕ | 兼容载体，等价于 Authorization 头 |

响应回显的 `title` 是**截断后**的实际值，前端应以它为准刷新列表，而不是回显自己发出去的原串。
归属硬校验同 5.2。

**改名是一次性的、不可逆的「锁定」**：调过本接口的会话，平台此后不再自动生成它的标题
（即使这次改名把它改回了原来的值）。这是刻意的——用户自己起的名字不该被模型盖掉。

### 5.4 POST /v2/conversations/{conversation_id}/read —— 标为已读（2026-10-15 新增）

```http
POST /v2/conversations/9c2…/read
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{ "user_id": "10024001" }
```

成功返回 `{"status": "ok"}`，该会话的 `has_unread`（§5）随即变 `false`。归属硬校验同 5.2。

- **平台只认这个显式上报**：拉历史不算已读（预取、后台标签页都会拉，不代表用户看到了）。
- 调用时机：会话**真正展示给用户**时——打开会话时，以及停在该会话期间收到 `end` 时。
  页面在后台（`document.hidden`）时不要调。

## 6. GET /v2/conversations/{conversation_id}/messages —— 会话历史

```http
GET /v2/conversations/9c2…/messages?user_id=10024001&limit=50
Authorization: Bearer <token>
```

```json
{
  "conversation_id": "9c2…",
  "messages": [
    { "role": "user", "content": "查一下料号 X100 最近的到货情况", "ts": 1751780000.2,
      "message_id": "f5a…", "sources": [], "source_name": "", "citations": [],
      "files": [ { "file_id": "3f9c…", "filename": "来料检验报告.pdf",
                   "media_type": "application/pdf", "size": 348219 } ] },
    { "role": "assistant", "content": "料号 X100 最近 30 天共到货 12 批……", "ts": 1751780001.2,
      "message_id": "f5a…", "sources": ["MATERIAL_QUERY"], "source_name": "物料查询助手",
      "citations": [], "files": [], "status": "completed" }
  ],
  "ratings": { "f5a…": "up" }
}
```

- `role` ∈ `user` / `assistant`；按时间正序；`limit` 默认 50，最大 500。
- `content` 为正文文本（`delta` 拼接结果）；`progress`/`tool_call` 等**过程**事件不落历史
  （引用另经 `citations` 字段回读，见下），历史页回放文本即可。
  **答案产物则一律以文本块的形式出现在 `content` 里**：
  - `table` → **GFM Markdown 表格**（2026-07-30 起；有 `title` 时前面多一行 `**标题**`）；
  - `chart` → ` ```echarts ` 代码块（平台从抽象 spec 确定性拼装的 echarts option）；
  - `clarify` / `suggestions` → `<intent_routing_clarify>` 数据块（与原 Dify 入口同款载体）。

  这是**刻意的**：历史回读只有 `content` 一个正文载体，表格/图表/引导按钮若不投影进去，
  用户翻历史就会看到一个缺了表、缺了图、缺了按钮的残缺回答。前端按这几个标记解析即可，
  与实时流渲染出的东西同源；三者都**留在正文里的原位**（表格夹在两段正文之间就还在那儿，
  前后各隔一个空行）。
- **`citations`** = 本条回复的引用溯源，**字段与顺序同实时流的 `citation` 事件 items**
  （已按文档去重）。正文里的 `<sup>[document_id]</sup>` 角标也照样落在 `content` 里，
  故历史回读按 §3.3.1 的同一套三步渲染即可 —— **不接这个字段，刷新一次角标就全断了**。
  只有 `assistant` 行有值；`user` 行恒为 `[]`。
- `message_id` = 该问答轮的 `request_id`（同一轮的 user/assistant 两条共用）。
- **`sources`（2026-07-15 新增）—— 本条回复由哪些模块参与**，供历史页按消息标注模块
  （一个会话中切换过模块时，用户翻历史才不困惑）：
  - **数组**，`sources[0]` 是路由主目标，其余为该轮经模块间调用触达的模块；
    一条回复允许多个模块参与，前端至少渲染 `sources[0]`。
  - **只有 `assistant` 行有值**；`user` 行恒为 `[]`（用户的话没有「谁答的」可言）。
  - **空数组 = 平台自身答的**（澄清轮），或历史消息未标注（见下）。
  - ⚠️ **历史数据**：本次变更前落库的消息，模块信息尽力从审计回填；**从 Dify 迁移来的
    历史无法回填**（那批数据没有审计记录），一律为空数组，前端按「未标注」处理即可。
- **`source_name`（2026-08-13 新增）—— `sources[0]` 的展示名**，即「这条消息由哪个助手回复」
  直接可渲染的那个字符串（如 `"物料查询助手"`）。**空串 = 平台自身答的 / 未标注**，
  与 `sources` 为空数组同义。
  - **为什么不让前端自己拿 `sources[0]` 去 join `GET /v2/modules`**：那份清单只覆盖该用户
    **当前**授权到的模块。翻半年前的历史时，那个模块可能已经不在他的菜单里了，标签就地
    消失——而历史标注恰恰是给「当时用过、现在未必还有」的场景准备的。故由平台直接给名字。
  - 名字取自模块 manifest（远程 Dify 模块取 `remote_modules.json` 的 `name`）；该模块已从
    平台下线时**退回模块编码**，故这个字段非空即可直接渲染，前端不必再准备一套兜底。
  - 与 Dify 兼容面的 `<sub>[app:助手名]</sub>` 正文落款是**同一个名字、同一个判据**，
    只是载体不同：v2 的 `content` 保持干净正文，标签怎么渲染由前端定。
- **`files`（2026-10-14 新增）—— 这一轮提问附带的上传文件**（§8.2），供历史页在用户气泡里
  渲染「已附件 xxx.pdf」（**不接这个字段，刷新或换设备后附件标记就全丢**）：
  - 每项 `{file_id, filename, media_type, size}`，与 `POST /v2/files` 响应里的同名字段同值；
    顺序 = 当轮 `file_ids` 的顺序。
  - **只有 `user` 行有值**；`assistant` 行恒为 `[]`（附件属于提问，不属于回答）。没附文件的轮次也是 `[]`。
  - 只记**归属校验通过**的文件。引用被拒的那一轮（`FILE_NOT_ACCESSIBLE` 等），`files` 为 `[]`。
  - 只有元信息、不含内容。要取回文件本身，拿 `file_id` 调 §8.2.6 的下载端点（2026-10-14 起）。
  - `file_id` 在原会话内、有效期（默认 72 小时）内仍可在 `/v2/chat` 再次引用；过期后引用会得到
    `FILE_EXPIRED` 或 `FILE_NOT_ACCESSIBLE`（文件已被清理）。所以**历史里的附件标记应当恒显示**，
    不要拿「能否再引用」来决定显不显示它。
  - ⚠️ **历史数据**：本次变更前的消息一律为 `[]`，无法回填（此前从未记录「哪一轮引用了哪个文件」）。
- **`status`（2026-10-15 新增）—— 这条回复生成到哪一步了**（[决策](../decisions/2026-10-15-问答后台生成与断线续接.md)）：
  - `completed` / `stopped` / `interrupted` 与 `end.status`（§3.3）同义：`stopped` 标「已停止」，
    `interrupted` 标「内容可能不完整」（超时、平台重启、进程异常时，正文是中断前最后保存的那部分）。
  - `generating` = **这一轮还在生成**。此时 `content` / `citations` 是此刻的快照，并额外带
    `stream_seq`（快照对应的事件序号），按 §3.7 续接即可。生成中的这一轮不能评价、不能分享
    （`409 TURN_IN_PROGRESS`）。
  - `user` 行恒为 `completed`；本次变更前的历史一律 `completed`。
- **`ratings`（2026-09-20 新增）—— 本会话已有的赞/踩**，形如 `{message_id: "up"|"down"}`，
  供历史页恢复赞踩按钮的高亮态（**不接这个字段，刷一次页面赞踩状态就全丢**）。
  - **与消息分开给**，不糊进消息行：赞踩是另一张表的、可随时被改写的状态，不是消息的一部分。
  - **只含有评价的轮次**；没评价过的、以及**已撤销的**（见 §7）一律不出现在这个对象里，
    前端按「无评价」渲染即可，不必区分「从没点过」和「点了又取消」。
  - 键是 `message_id`（= 该轮 `request_id`），与 `POST /v2/feedback` 的 `request_id` 同一个值。
- **归属硬校验**：非本人会话返回 403，不存在返回 404（fail-closed，无权数据不出库）。

## 6.1 会话分享（2026-09-20 新增）

> 这一节是 **v1 那套「URL 带分享人工号」分享的替代**。迁移到 v2 时它必须一起改——照搬 v1
> 的做法在 v2 下一定打不开，原因见下面第一段。
>
> 📘 **本节是字段与行为的信源；动手改前端时另有一份操作指引**：
> [INFO前端-会话分享改造指引.md](INFO前端-会话分享改造指引.md)（改哪三处界面、代码片段、
> 要同步给业务方的行为差异、自测清单）。两者若有出入**以本节为准**。

### 6.1.1 为什么 v1 那套在 v2 下不成立

v1 的分享是前端拼 URL：`会话ID + 分享人工号 + 分享日期 + 勾选的 messageId`，被分享人打开后，
前端把 **URL 里的分享人工号**原样当 `user` 参数发给 `GET /v1/messages`。它能工作只有一个
原因——**v1 的归属比对认的是客户端自报的工号字符串，不验用户身份**（`/v1` 只有一把全体共用的
app key）。等于一张无签名、无时效、无法撤销、转给谁都生效的通行证。

v2 每个端点都拿 INFO token 向 INFO 换授权树，且会话按归属 403（§6 最后一条）。所以：

- ❌ **别把 `user_id` 改成 URL 里的分享人工号**去调 `/v2/conversations/{id}/messages`。
  那是在冒用他人身份，平台会按越权处理；这条路即便某一刻"能通"也会被堵上，不要依赖它。
- ✅ 用下面这组分享端点：**身份归身份**（被分享人用自己的登录态），**授权归票据**
  （`share_id` 决定能看哪份内容）。

### 6.1.2 一次分享的完整流程

```
分享人：勾选消息 → POST /v2/shares ──► 拿到 share_id
                                         │
                                         ├─ 前端把它拼成自家路由，如
                                         │  https://info.example.com/ai/share?share_id=<share_id>
                                         ▼
被分享人：打开链接 → （INFO 登录态）→ GET /v2/shares/{share_id}?user_id=<他自己的工号>
                                         │
                                         ▼
                                   只读快照（冻结正文）
```

**关键差别**：URL 里只有 `share_id` 一个不可枚举的随机串，**不带工号、不带会话 ID、不带
messageId**。被分享人是谁，由他自己的 INFO 登录态说了算。

### 6.1.3 POST /v2/shares —— 签发分享（分享人调）

```http
POST /v2/shares
Authorization: Bearer <分享人的 token>
Content-Type: application/json
```

```json
{
  "user_id": "10024001",
  "conversation_id": "9c2…",
  "message_ids": ["f5a…", "a71…"],
  "audience": ["10024002"],
  "ttl_hours": 168
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `user_id` | ✅ | 分享人工号。**必须是该会话的所有者**，否则 403 |
| `conversation_id` | ✅ | 被分享的会话 |
| `message_ids` | ✅ | 勾选的消息，即 §6 里每条消息的 `message_id`。**一个 id = 一问一答那一轮**，问题与回答会一起进快照（只给答案不给问题，对方看到的是没有上下文的一段话）。最多 200 条 |
| `audience` | ✕ | 接收人工号白名单，最多 50 个。**留空 = 任意通过 INFO 鉴权的内网用户凭票可看**（注意：不是免登录）。想"只发给某几个人"就填这里 |
| `ttl_hours` | ✕ | 有效期（小时）。默认 168（7 天），上限 720（30 天）；不给、给 0 或负数都回落到默认值 |
| `token` | ✕ | 兼容载体，等价于 Authorization 头 |

响应（= 「我发出的分享」列表里的同一形状）：

```json
{
  "share_id": "Xc9K…（43 字符随机串）",
  "conversation_id": "9c2…",
  "title": "X100 到货追踪",
  "message_ids": ["f5a…", "a71…"],
  "message_count": 2,
  "audience": ["10024002"],
  "created_ts": 1758300000.0,
  "expires_ts": 1758904800.0,
  "expired": false,
  "revoked": false,
  "status": "active",
  "view_count": 0,
  "last_viewed_ts": null
}
```

- **`message_ids` 回显的是实际命中的那些**：勾了 5 条但其中 2 条不属于该会话时，票上只记
  命中的 3 条（不会让计数与正文对不上）。一条都没命中 → 400 `SHARE_MESSAGES_NOT_FOUND`，
  **不会签出一张空票**。
- 错误：`403 CONVERSATION_FORBIDDEN`（不是你的会话）、`404 CONVERSATION_NOT_FOUND`、
  `400 SHARE_EMPTY`（没勾）、`400 SHARE_TOO_LARGE`、`400 SHARE_AUDIENCE_TOO_LARGE`、
  `409 TURN_IN_PROGRESS`（勾选的某一轮还在生成中，2026-10-15 起；快照是冻结的，冻进去就永远是半截）。

### 6.1.4 GET /v2/shares/{share_id} —— 打开分享（被分享人调）

```http
GET /v2/shares/Xc9K…?user_id=10024002
Authorization: Bearer <被分享人自己的 token>
```

```json
{
  "share_id": "Xc9K…",
  "title": "X100 到货追踪",
  "owner_id": "10024001",
  "owner_name": "张三",
  "created_ts": 1758300000.0,
  "expires_ts": 1758904800.0,
  "messages": [
    { "role": "user", "content": "查一下料号 X100 最近的到货情况", "ts": 1751780000.2,
      "message_id": "f5a…", "sources": [], "source_name": "", "citations": [],
      "files": [ { "file_id": "3f9c…", "filename": "来料检验报告.pdf",
                   "media_type": "application/pdf", "size": 348219 } ] },
    { "role": "assistant", "content": "料号 X100 最近 30 天共到货 12 批……", "ts": 1751780001.2,
      "message_id": "f5a…", "sources": ["MATERIAL_QUERY"], "source_name": "物料查询助手",
      "citations": [], "files": [] }
  ]
}
```

- **`messages` 与 §6 会话历史逐字段同形**（含 `citations` / `sources` / `source_name` / `files`，正文里
  的 Markdown 表格、` ```echarts ` 代码块照旧）。**分享页可以直接复用历史页的渲染组件**，
  不需要为它写第二套解析。
- **仍然要求 `user_id` + token**（fail-closed，与其余端点同一套）。去掉它就退回成 v1 那条
  谁转发都生效的链接。
- **`owner_name` 可能为空**（档案服务取不到时不阻断签发），前端退回展示 `owner_id`。
- **快照里的附件可下载**（2026-10-14 起）：`files` 里的文件用 §8.2.6 的分享下载端点
  `GET /v2/shares/{share_id}/files/{file_id}` 取回，授权随这张票（撤销/过期后一并失效）。
- **刻意不回 `conversation_id`**：票解锁的是这几条，不是那个会话。被分享人拿会话 ID 去调
  §6 必然 403，协议不主动递出一把打不开的钥匙。

| 状态码 | 错误码 | 前端该怎么提示 |
|---|---|---|
| 401 | （鉴权类） | 引导登录 INFO —— **这是"你没登录"，不是"你没权限看"**，两者提示必须分开 |
| 404 | `SHARE_NOT_FOUND` | 「分享不存在或链接不完整」，引导检查链接是否被截断 |
| 410 | `SHARE_EXPIRED` | 「分享已过期，请向分享人重新索取」 |
| 410 | `SHARE_REVOKED` | 「分享已被撤销」 |
| 403 | `SHARE_FORBIDDEN` | 「该分享未授予当前用户」，引导找分享人把自己加进接收人 |

> 这四种拒绝**刻意不合并成一个码**：过期/撤销要去找分享人重发，无权要去申请授权，链接不全
> 要重新复制——混成一个「打不开」等于把用户唯一能采取的下一步动作抹掉了。

### 6.1.5 GET /v2/shares —— 我发出的分享（分享人调）

```http
GET /v2/shares?user_id=10024001&limit=20&offset=40&status=active
Authorization: Bearer <token>
```

```json
{ "shares": [ …6.1.3 的响应形状… ], "total": 137, "limit": 20, "offset": 40 }
```

按创建时间倒序，只含本人发出的。**页码分页**（2026-09-21 起）：

| 参数 | 默认 | 说明 |
|---|---|---|
| `limit` | 50 | 每页条数，1~200 |
| `offset` | 0 | 跳过前多少条。越界不报错，回空页 + 照实的 `total` |
| `status` | `all` | `all` / `active`（有效）/ `revoked`（已撤销）/ `expired`（已过期）。拼错回 400 `invalid_param`，**不会回落到 `all`** |

- **`total` 是按 `status` 筛选后的总数**，不是全部票数。做「只看有效的」这类页签时，
  **请把 `status` 传给服务端**，不要拿全量再在前端过滤——那样 `total` 与页内条数对不上，
  末页会出现空页。
- 三个具体状态**两两互斥**，`active` + `revoked` + `expired` 的 `total` 相加恰好等于 `all`。
  一张先撤销、后到期的票算 `revoked`（与被分享人打开时拿到 `SHARE_REVOKED` 是同一个判定顺序）。
- 每条的 **`status` 字段**就是这个口径下的状态，渲染状态标签直接用它。不要自己拿
  `revoked` / `expired` 拼：先撤销后到期的票这两个值会同时为 `true`。
- 排序完全确定（同一时刻签出的票也有固定的先后），逐页翻完**不重不漏**。
- 不带 `offset` / `status` = 第一页、全部状态，与加分页之前返回同一批条目。
- 与 §5.1 会话列表的**游标**分页不同，这里刻意用页码：会话列表是侧边栏无限滚动，这里是
  要跳页、要看总数的管理表格。

**这个列表是撤销权的前提**：分享人必须随时看得见自己散出去了多少张票、哪些还有效、各被看了
几次，否则"可撤销"只是名义上的。建议前端给一个「我的分享」入口，而不是只在分享成功的
toast 里给一次链接。

### 6.1.6 DELETE /v2/shares/{share_id} —— 撤销（分享人调）

```http
DELETE /v2/shares/Xc9K…?user_id=10024001
Authorization: Bearer <token>
```

- **幂等**：已撤销的再撤一次照样 200，前端不必分情况处理。
- 撤销后被分享人再打开得到 `410 SHARE_REVOKED`。
- 非本人撤销得到 **404**（不是 403）—— 那是别人的票，对当前用户来说本就"不存在"。
- **撤销不删除记录**：这张票被谁看过仍然查得到（见下）。

### 6.1.7 GET /v2/shares/{share_id}/views —— 谁看过（分享人调）

```http
GET /v2/shares/Xc9K…/views?user_id=10024001
Authorization: Bearer <token>
```

```json
{ "share_id": "Xc9K…", "views": [ { "viewer_id": "10024002", "ts": 1758300600.0 } ], "limit": 200 }
```

倒序，仅分享人本人可见（他人一律 404）。只记**成功打开**，被拒的尝试不进这张表。

### 6.1.8 数据权限：分享是授权的扩散，这是业务方拍过板的

会话正文里是按**分享人的行列权限**取到的真实业务数据。快照已是渲染好的正文，平台**无法**
按被分享人的权限重新过滤——也就是说被分享人会看到他自己未必有权取的数据。

业务方 2026-09-20 明确拍板：**允许分享即视为分享人主动授予该份内容的查看权。**
2026-10-14 起这份「内容」**包括被勾选轮次附带的上传文件**——接收人可下载它们（§8.2.6）。
代价由这组补偿控制兜着（都已在协议里）：票据不可枚举 · 有效期封顶 30 天 · 分享人可随时撤销 ·
可限定接收人 · **每次打开都留痕**。

**前端据此要做的两件事**：

1. **分享动作要有明确的确认**，不能做成"点一下就复制了链接"的轻量操作。建议在确认框里
   写清：「对方将看到这 N 条消息的完整内容，包括其中的业务数据，以及这些轮次附带的文件（对方可下载）」。
2. **不要把 `share_id` 写进任何会被二次转发的地方**（邮件正文里的明文链接、群公告、
   带 share_id 的截图）。它是凭据，转发一次就多一个能打开的人——虽然每次打开都留痕，
   但留痕是事后追溯，不是事前阻拦。填 `audience` 才是事前阻拦。

### 6.1.9 从 v1 迁移的对照表

| v1 做法 | v2 做法 |
|---|---|
| 前端拼 URL：`会话ID + 分享人工号 + 分享人姓名 + 分享日期 + messageId` | `POST /v2/shares` 拿 `share_id`，URL 里**只放 `share_id`** |
| 分享人姓名、日期由 URL 参数携带 | 由 `GET /v2/shares/{id}` 回的 `owner_name` / `created_ts` 携带（**随票冻结**，不可篡改） |
| 被分享人的请求里 `user` = 分享人工号 | `user_id` = **被分享人自己的工号** + 他自己的 token |
| 调 `GET /v1/messages?conversation_id=…&user=…` | 调 `GET /v2/shares/{share_id}?user_id=…` |
| 分享后会话继续聊，被分享人**会看到新消息** | 快照冻结，**只能看到分享那一刻勾选的那几条** |
| 无法撤销、无有效期 | `DELETE /v2/shares/{id}` 撤销；默认 7 天、最长 30 天 |
| 无法知道谁看过 | `GET /v2/shares/{id}/views` |

## 7. POST /v2/feedback —— 问答反馈（赞/踩）

对**某一次问答**（以 `end` 事件或响应头携带的 `request_id` 标识）提交反馈：

```http
POST /v2/feedback
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "request_id": "f5a…",
  "user_id": "10024001",
  "conversation_id": "9c2…",
  "rating": "up",
  "comment": "答案准确"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `request_id` | ✅ | 本次问答的请求 ID（`X-Request-Id` 响应头 / `end` 事件的 `data.request_id`） |
| `user_id` | ✅ | 反馈人 |
| `rating` | ✅ | `"up"` / `"down"` / `"none"`（撤销，见下）。其余值 422 |
| `conversation_id` | ✕ | 所属会话；传了会做归属校验（他人会话 403） |
| `comment` | ✕ | 文字补充 |

> 该轮回复**还在生成中**时评价 → `409 TURN_IN_PROGRESS`（2026-10-15 起）。生成中的那一轮不显示赞踩按钮即可。

成功返回 `{"status": "ok"}`。

- **一条消息只有一个当前评价**：同一 `request_id` 重复提交是**覆盖**，不会留下多行
  （前端不必为「改主意」做特殊处理，点踩直接覆盖此前的赞即可）。
- **撤销（取消赞/踩）发 `rating: "none"`**：用户再点一次已高亮的按钮时用它。撤销同样是
  覆盖而非删除，`GET …/messages` 的 `ratings` 会据此不再返回这一轮，前端自然回到未评价态。
  ⚠️ **撤销会连同 `comment` 一起被覆盖**——评价都撤了，备注不该留在表里；故撤销时不要
  为了"保住备注"把旧 `comment` 回传。
- 对应 v1（Dify 兼容面）的 `POST /messages/{id}/feedbacks`：`like`/`dislike`/`null`
  依次对应 v2 的 `"up"`/`"down"`/`"none"`。

## 8. GET /v2/app-info —— 应用信息（开场白）

前端启动时拉一次，用于渲染欢迎语。**本端点不要求身份**（见 2.1 的例外说明）：
返回的是固定展示文案、不含任何用户数据，故拿到 token 之前就能调。

```http
GET /v2/app-info
```

```json
{
  "name": "INFO综合路由智能体",
  "description": "INFO助手智能路由聚合体（DataForge2 平台承载）",
  "opening_statement": "您好，我是INFO系统助手，提供企业内部知识库与 INFO 业务数据查询服务，……",
  "capabilities": {
    "file_upload": {
      "enabled": true,
      "max_bytes": 20971520,
      "max_files_per_turn": 8,
      "allowed_extensions": ["bmp", "csv", "doc", "docx", "gif", "jpeg", "jpg", "json", "log", "md", "pdf", "png", "ppt", "pptx", "tsv", "txt", "webp", "xls", "xlsx", "xml", "yaml", "yml"]
    }
  }
}
```

- `opening_statement` 是**多行文本**（含 `\n\n` 段落分隔），按纯文本渲染即可，不含 Markdown 语法。
- **兼作可用性探测**：本端点免鉴权且前端启动时本来就要调，故「拉开场白成功」即可当作
  「后端可用」，不必另发探活请求。要更细的健康状态见 §2.3。
- 与已下线的 Dify 兼容面 `GET /v1/parameters` 的 `opening_statement` 同值，切换入口时文案没变。
- 原 `/v1/parameters` 里的其余字段在 v2 **不再需要**：`user_input_form` 的两个变量
  （`selected_agent` / `token`）已是 v2 的一等入参（`target` / `Authorization` 头）；
  `suggested_questions` 由 §4 `/v2/modules` 的 `intents` 按模块提供（更细）；
  `retriever_resource` 恒开（即 `citation` 事件）；`speech_to_text` / `text_to_speech` /
  `annotation_reply` 等特性平台一律不支持，前端按恒关处理。
  `file_upload` 则有对应物——即下面的 `capabilities.file_upload`。
- **`capabilities`（2026-09-20 新增）—— 平台级能力声明**，前端据它决定显不显示上传入口、
  `accept` 写什么、大小提示怎么写：

  | 字段 | 说明 |
  |---|---|
  | `file_upload.enabled` | 本环境是否启用了上传通道（§8.2）。`false` 时**只有这一个键**——阈值不会给，因为给了也传不上去 |
  | `file_upload.max_bytes` | 单文件字节上限 |
  | `file_upload.max_files_per_turn` | 单轮可引用的文件数上限 |
  | `file_upload.allowed_extensions` | 允许的扩展名全量（已排序，可直接拼 `<input accept>`） |

  四件事值得说清：
  1. **这几个阈值请直接用，不要在前端硬编码**——它们都是部署侧可配的，各写一份迟早漂移（§8.2.2）。
  2. **声明与实际同源**：`enabled` 与 `POST /v2/files` 是否 404 出自同一个判据，不会出现
     「说开着、真传却 404」。故按它显示入口即可，不必再用「先传一次看看」来试探。
  3. `capabilities` 里只会有**不随用户变**的开关（否则本端点就需要鉴权了）。
     「这个用户能用哪些助手」那类信息在 §4 `/v2/modules`，不在这里。
  4. 未识别的能力键**必须忽略**：后续新增能力会往 `capabilities` 里加键，届时不要求前端同步发版。

## 8.1 GET /f/{token} —— 导出文件下载（2026-08-09 新增）

业务模块生成 Excel/CSV 等文件时，会把下载链接**直接嵌在回答正文里**（Markdown 链接或
HTML `<a>`）。前端**不需要做任何事**——正文本就按 Markdown 渲染，链接自然可点。

本节写在这里只为说清三件事：

1. **不是 `/v2` 下的端点，也不要求任何请求头**。用户点的是普通 `<a href>`，浏览器发的是裸
   GET，带不了 `Authorization`。当前阶段**任何人拿到链接都能下载**（保护 = 不可猜的随机
   token + 24 小时有效期）。
   > 🔒 后续会补鉴权，届时**需要前端配合**：在下载请求上带用户的 INFO 登录 token，平台换出
   > user_id 与文件归属比对。方案未定稿，落地前会另行沟通——现在无需改动。
2. **链接 24 小时后失效，返回 HTTP 410**（不是 404）。浏览器直接打开时会看到一个「链接已过期，
   请重新提问生成」的提示页；若前端以 `Accept: application/json` 请求，则得到
   `{"code": "FILE_EXPIRED", "message": "..."}`。用户翻**历史会话**点旧链接必然落到这里，
   属预期行为。链接失效不等于文件被删（平台侧仍留档）。
3. **响应恒为 `Content-Disposition: attachment`**，即浏览器一律下载、不内联打开；文件名走
   RFC 5987（中文名不乱码）。故前端不要试图 `<iframe>`/新标签页"预览"它。

| 状态码 | 含义 |
|---|---|
| 200 | 正常下载（响应体即文件字节）|
| 410 | 链接已过期（24 小时），提示用户重新提问生成 |
| 404 | token 不存在或链接不完整 |

## 8.2 POST /v2/files —— 上传文件（问答附件，2026-09-09 新增）

用户在对话框里附一张图或一份文档时用。**两步**：先把文件传到本端点换回 `file_id`，
再在 `POST /v2/chat` 的 `file_ids` 里引用它（§3.1）。

> **与 §8.1 方向相反、鉴权也相反，别照抄那一节的心智**：§8.1 是模块产出交给用户下载
> （拿到链接即可下载），本节是用户把材料交给模块读（**每一轮都重新校验归属**，见下）。
> 共用「文件」二字，不共用任何策略。

```http
POST /v2/files
Content-Type: multipart/form-data
Authorization: Bearer <token>
```

| 表单字段 | 必填 | 说明 |
|---|---|---|
| `file` | ✅ | 文件本体 |
| `user_id` | ✅ | 上传人工号 |
| `conversation_id` | ✕ | 归属会话；**不传则平台新开一个会话号并在响应里回给你** |
| `token` | ✕ | 兼容载体，等价于 Authorization 头 |

```json
{
  "file_id": "3f9c…",
  "filename": "来料检验报告.pdf",
  "media_type": "application/pdf",
  "size": 348219,
  "conversation_id": "9c2…",
  "created_ts": 1757400000.1,
  "expires_ts": 1757659200.1
}
```

**`conversation_id` 可以不传**，这一点是刻意的：用户常常是「先拖进来一个文件，再开始打字」，
此时前端手里还没有会话号。不传时平台新开一个号给你，**后续的 `/v2/chat` 带上同一个号**即可；
传了则该文件从此锁死在那个会话里。

### 8.2.1 归属规则（每一轮都校验，fail-closed）

文件同时绑定 **`user_id` + `conversation_id`**，`/v2/chat` 引用它时两者都要对得上：

- **不是你的文件 / 不存在的 `file_id`** → 同一个 `FILE_NOT_ACCESSIBLE`。⚠️ 两种情况**刻意合并**
  成同一个码与同一句文案，以免它变成一台「猜 id 试探别人传了什么」的探测器。前端照 `message` 展示即可。
- **是你的文件、但属于另一个会话** → 同样 `FILE_NOT_ACCESSIBLE`。把 A 会话的附件带进 B 会话是**不允许**的，
  用户要在新会话里用同一份材料，请**重新上传**（前端可自行缓存本地文件做「一键重传」，平台侧不提供搬运）。
- **任一文件不通过，整轮被拒绝**，而不是跳过它继续作答——「少了一份材料的回答」用户看不出来，
  但那正是最危险的一种错答。

### 8.2.2 限制与错误

| 项 | 默认值 | 说明 |
|---|---|---|
| 单文件大小 | 20 MB | 超出 `413` |
| 单轮可引用文件数 | 8 | 超出时 `/v2/chat` 流内 `error` 事件 `TOO_MANY_INPUT_FILES` |
| 有效期 | 72 小时 | 兜底清理，**不表达「会话结束即失效」**；过期后引用得到 `FILE_EXPIRED` |
| 扩展名白名单 | 见下 | 白名单外一律拒绝 |

> 上述四项均由平台部署侧配置（`.env`），**实际值以运维交付的环境为准**，前端不要把 20MB / 8 个
> 硬编码进校验逻辑——建议只做宽松的前置提示，以服务端返回为准。

**允许的扩展名**（白名单，不在其中一律拒绝）：

- 图片：`png` `jpg` `jpeg` `webp` `gif` `bmp`
- 文档：`pdf` `docx` `doc` `xlsx` `xls` `pptx` `ppt`
- 文本：`txt` `csv` `tsv` `md` `json` `log` `xml` `yaml` `yml`

压缩包（zip/rar）、`html` / `svg` / `js`、音视频**均不支持**，这是安全边界不是待办。

**上传端点的错误**（2.2 的 `{code, message}` 格式，`message` 可直接展示给用户）：

| 状态 | code | 场景 |
|---|---|---|
| 400 | `UPLOAD_EXT_NOT_ALLOWED` | 扩展名不在白名单 |
| 400 | `UPLOAD_EMPTY` | 0 字节的空文件 |
| 400 | `UPLOAD_QUOTA_EXCEEDED` | 平台上传目录配额已满（运维介入，不是用户能解决的） |
| 401 | — | token 无效（同 2.1） |
| 403 | `CONVERSATION_FORBIDDEN` | 往他人会话里传文件 |
| 413 | `UPLOAD_TOO_LARGE` | 超过单文件上限 |
| 404 | `FILE_UPLOAD_DISABLED` | **本平台环境未启用上传通道**（见 8.2.4） |

**引用阶段的错误**（`/v2/chat` 流内的 `error` 事件，`fatal: true`，随后仍有 `end`）：

| code | 场景 |
|---|---|
| `FILE_NOT_ACCESSIBLE` | 归属不符 / `file_id` 不存在 / 执行期间被清理 |
| `FILE_EXPIRED` | 超过有效期 |
| `TOO_MANY_INPUT_FILES` | 本轮引用数超上限 |

### 8.2.3 上传成功 ≠ 这一轮一定读得懂它

这三件事请在交互设计上分开，否则用户会把「模型没看懂」当成「文件没传上去」：

1. **图片**直接以原始字节交给模型识别，平台不做任何解析。
   实测对清晰印刷体有效；拍照、截图、手写、低分辨率、复杂表格的识别效果**未经充分验证**，
   请勿在产品文案里承诺「能看懂任何图」。
2. **文档由平台抽取文本**后交给模型（Office / PDF / 纯文本各有对应解析）。
   两类情况会明确报错而不是静默给出空内容：**扫描件 PDF**（整页都是图像、抽不出文字，
   当前不做 OCR）与**加密或损坏的文件**。这类错误出现在**问答流里**（`error` 事件），
   不是上传时——上传只管收下和校验，解析发生在模块真正读它的时候。
   ⚠️ **旧版二进制格式 `.doc` / `.ppt` / `.xls` 当前读不了**：白名单放行、上传会成功，
   但读取时同样在问答流里报错。请在上传入口提示用户另存为 `.docx` / `.pptx` / `.xlsx` 再传。
3. **读不读附件，取决于本轮路由到的助手**。附件是交给业务模块的输入，模块可以不消费它。
   把文件附给一个只查数据库的取数助手，它多半会忽略。若要「就这份文件聊」，
   建议引导用户显式选择支持文件的助手（`target`），或在提示语里说明。

附件在气泡里的展示：实时那一轮用本地文件对象渲染即可；**翻历史、打开分享时用 §6 / §6.1.4
消息行的 `files` 字段**（只有文件名/类型/大小等元信息）。**要取回文件本身**，用 §8.2.6 的下载
端点（2026-10-14 起）。平台**不提供内联预览或缩略图**，下载响应恒为附件。
> 本段此前写的是「平台不提供上传文件的回读/预览端点」，已由
> [2026-10-14 决策](../decisions/2026-10-14-上传文件历史回显与回下载.md) 取代（预览仍不提供）。

### 8.2.4 上传能力是否启用

**读 `GET /v2/app-info` 的 `capabilities.file_upload`**（§8，2026-09-20 起提供）：

```json
{ "enabled": true, "max_bytes": 20971520, "max_files_per_turn": 8, "allowed_extensions": ["pdf", "png", "…"] }
```

`enabled` 为 `false` 时隐藏上传入口即可；为 `true` 时用同一份声明里的阈值写 `accept`
与大小提示，**不要在前端硬编码**（阈值是部署侧可配的，各写一份迟早漂移）。

该端点免鉴权，前端启动拉开场白时顺带就拿到了，不需要额外请求，也**不必**再用
「先传一次看看是不是 404」来试探——`enabled` 与上传端点是否 404 出自同一个判据。

> 本节此前写的是「平台没有能力开关查询接口，请前端用配置常量或按 404 降级」。
> 该字段落地后此写法作废；两种旧做法仍然能用，只是没有必要了。

### 8.2.5 从 v1 迁移

| v1（Dify 兼容面） | v2 |
|---|---|
| `POST /v1/files/upload`，响应 `{id, name, size, extension, mime_type, …}` | `POST /v2/files`，响应 `{file_id, filename, media_type, size, conversation_id, …}` |
| 鉴权只有 app key + 表单 `user` | 与问答同一套：`user_id` + 用户 token（fail-closed） |
| 上传时**无会话归属**（Dify 协议没有该字段），首次被引用时才锁定 | 上传即绑定会话（不传则平台新开并回传） |
| 在 `chat-messages.files[]` 里按 `{type, transfer_method, upload_file_id}` 引用 | 在 `chat.file_ids` 里按字符串数组引用 |
| `GET /v1/files/{id}/preview` 恒 404 | 无预览端点；下载用 `GET /v2/files/{file_id}`（§8.2.6，强制下载、不内联） |

### 8.2.6 下载已上传的文件（2026-10-14 新增）

两个端点，分别给上传人本人与分享接收人（[决策](../decisions/2026-10-14-上传文件历史回显与回下载.md)）：

| 谁 | 端点 |
|---|---|
| 上传人本人（历史页） | `GET /v2/files/{file_id}?user_id=<本人工号>` |
| 分享接收人（分享页） | `GET /v2/shares/{share_id}/files/{file_id}?user_id=<接收人自己的工号>` |

`file_id` 取自 §6 / §6.1.4 消息行的 `files`。两个端点都要 `Authorization: Bearer <调用人自己的 token>`。

**必须用 `fetch` 带头取回再保存**：浏览器的 `<a href>` 带不了 `Authorization`，直接放链接必然 401。
（平台刻意不发「拿到即可下载」的签名链接——入站文件的 `file_id` 是标识符不是凭据，见 §8.2.1。）

```js
async function downloadUpload(url, filename) {
  const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!resp.ok) {
    const { code, message } = await resp.json();   // message 可直接展示
    throw Object.assign(new Error(message), { code, status: resp.status });
  }
  const href = URL.createObjectURL(await resp.blob());
  const a = Object.assign(document.createElement('a'), { href, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);  // 立即 revoke 个别浏览器会中断保存
}
// 历史页：downloadUpload(`/v2/files/${f.file_id}?user_id=${me}`, f.filename)
// 分享页：downloadUpload(`/v2/shares/${shareId}/files/${f.file_id}?user_id=${me}`, f.filename)
```

**规则**

- **上传人端点只认上传人本人**；文件所属会话已被本人删除 → `404 CONVERSATION_NOT_FOUND`（与 §6 同口径：删了即不存在）。
- **分享端点先过兑换同一套闸**（`SHARE_NOT_FOUND` / `SHARE_REVOKED` / `SHARE_EXPIRED` / `SHARE_FORBIDDEN`，
  见 §6.1.4），**且文件必须在这张票冻结的消息的 `files` 里**——附件随它所在的那一轮一起被授予，
  同会话里没被勾选的轮次的附件拿不到。2026-10-14 之前签的票快照里没有 `files`，无附件可下。
  下载**不计入** `view_count`。分享人删掉原会话不影响接收人下载（快照独立，同 §6.1 的既有口径）。
- **只下载、不预览**：响应恒为 `Content-Disposition: attachment`，并带 `X-Content-Type-Options: nosniff`、
  `Content-Security-Policy: sandbox`、`Cache-Control: private, no-store`；`Content-Type` 由平台按扩展名给出。
  **不要**用 `<iframe>` / 新标签页 / `<img src>` 内联展示它，平台也不提供缩略图。
- **文件有效期独立于分享票**：上传文件自上传起约 72 小时（部署可配）过期，随后被清理任务删除；
  分享票默认 7 天。**票还有效、文件已没了**时分享端点得到 `410 FILE_EXPIRED`。
- ⚠️ **上传人端点上，「已被清理」与「不存在」同为 `404 FILE_NOT_ACCESSIBLE`**：清理会把文件记录整行删掉，
  删掉之后平台无从区分「你传过但已清理」和「从没有过这个 id」——而分开报会让任何人能借此探测别人传过什么。
  只有「已过期、还没被清理」的那段时间是 `410`。**所以历史页对附件下载的 `404 FILE_NOT_ACCESSIBLE` 与
  `410 FILE_EXPIRED` 一视同仁**：下载按钮置灰、提示「文件已过期，无法下载」。
- 不论哪种失败，**附件标记照常显示**（它来自历史/快照，不随文件清理而消失）。
  不要按 72 小时在前端自行推算，以响应为准。

| 状态 | code | 场景 |
|---|---|---|
| 200 | — | 响应体即文件字节 |
| 401 | — | token 无效，或 `user_id` 与 token 不是同一人（同 §2.1） |
| 404 | `FILE_NOT_ACCESSIBLE` | 文件不存在 / 不是你的 / 不在这张分享票里 / （上传人端点）已被清理——**刻意同码同文案**，防止借此探测别人传了什么 |
| 404 | `CONVERSATION_NOT_FOUND` | （上传人端点）文件所属会话已被你删除 |
| 410 | `FILE_EXPIRED` | 文件已过期；（分享端点）已过期或已被清理 |
| 404 | `FILE_UPLOAD_DISABLED` | 本环境未启用上传通道（§8.2.4） |
| 403 / 404 / 410 | `SHARE_*` | （分享端点）票被拒，四种码与提示同 §6.1.4 |

## 9. 跨域（CORS）

INFO 前端页面与平台不同源时，平台需在 `.env` 配置
`FORGE_CORS_ORIGINS=["http://info.internal"]`（INFO 页面的 origin，交给平台运维配置）。
已放开 `Authorization` 等请求头，并在 `expose_headers` 暴露 `X-Conversation-Id` / `X-Request-Id` /
`Content-Disposition`（最后这个供 §8.2.6 下载时读取文件名，2026-10-14 起）。

## 10. 对接自测清单（INFO 前端）

- [ ] 首轮 chat 不传 `conversation_id`，从响应头取回并在续聊传回；两轮后 GET 会话列表能看到该会话且 `title` 正确。
- [ ] `end` 事件带 `conversation_title` 时就地刷新侧边栏那一条；**不带这个键时什么都不做**（不是错误，见 §3.2）。
- [ ] SSE 解析：`delta` 拼接成正文；收到 `clarify` 渲染选项并将用户选择作为新 query 重发；收到 `error` 展示 `message`；以 `end` 收尾。
- [ ] `table` / `chart` 按**到达顺序**插进消息流（与 `delta` 交错，不是全部甩到正文末尾）。
- [ ] `citation` 按 §3.3.1 三步渲染：去重聚合 → 末尾列出文件名 → 正文 `<sup>[document_id]</sup>`
      成可点角标且**数字与末尾清单序号一致**；匹配不到的角标不漏成裸文本。
- [ ] 历史回读也接 `citations` 字段 —— 刷新页面后角标与参考清单照旧。
- [ ] `suggestions` 渲染成「答完了，你可能还想问」，**不要**渲染成 `clarify` 那种「还没答」的样子。
- [ ] 历史回读：`content` 里的 Markdown 表格、` ```echarts ` 代码块与 `<intent_routing_clarify>`
      数据块能解析出表/图/按钮，且**同一张表不会既按事件渲染一遍、又按正文渲染一遍**。
- [ ] 无效 token 时各端点均得到 401 并引导用户重新登录 INFO（`/v2/app-info` 除外，它本就不校验）。
- [ ] 赞/踩按钮携带 `end` 事件的 `request_id` 调 feedback 接口成功；**再点一次已高亮的按钮
      发 `rating: "none"` 取消**（不是不发、也不是发空串）。
- [ ] 历史回读接 `ratings` 字段恢复赞踩高亮 —— 刷新页面后此前点过的赞/踩还在，撤销过的不在。
- [ ] 用另一账号访问他人 `conversation_id` 得到 403（平台侧硬校验，前端无需特殊处理，但不应报错崩溃）。
- [ ] 切换登录账号后，各端点带的 `user_id` 随之更新 —— 旧工号配新 token 会得到 `401 USER_TOKEN_MISMATCH`。
- [ ] 会话列表翻页：带 `last_id` 能一直翻到 `has_more: false` 停下；**拿到空页不重试同一个 `last_id`**。
- [ ] 删除会话后它从列表消失，且再点历史得到 404 而不是崩溃。
- [ ] 重命名后列表标题按**响应回显的** `title` 刷新（超长时它是截断后的值，与你发出去的原串可能不同）。
- [ ] 重命名过的会话：后续几轮问答里 `end` 不应再带 `conversation_title`，列表标题保持用户给的那个。
- [ ] 「停止生成」按钮调 `POST /v2/chat/{request_id}/stop`（§3.6），**不再**靠 abort 请求——
      abort 之后平台照样生成到底。停止后流以 `end`（`status: "stopped"`）收尾，消息标「已停止」。
- [ ] 回复生成到一半时**关掉页面**，过一会儿重新打开该会话 → 看到的是完整回复（§3.7）。
- [ ] 回复生成到一半时**切到别的会话**再切回来 → 历史里那条 `status: "generating"`，渲染快照后
      按 `stream_seq` 续接，后续文字不重复、不缺（§3.7）。
- [ ] 会话列表：生成中的会话显示「生成中」（`generating`）；答完但用户没看过的显示未读标记
      （`has_unread`）；打开它后调 `POST …/read`（§5.4）标记消失，换一台设备登录同样不再显示。
- [ ] `status: "interrupted"` 的历史消息显示「内容可能不完整」（可模拟：生成中让平台重启）。
- [ ] 上一轮还在生成时在同一会话再发问 → 得到 `409 CONVERSATION_BUSY` 并给出提示（或先停止上一轮），
      不是静默失败。
- [ ] 启动时拉 `/v2/app-info` 渲染开场白（无需 token）。
- [ ] 服务可用性：以「`/v2/app-info` 拉取成功」作为后端可用的判据（§2.3），**没有**为探活
      另起一个轮询；`/v2/chat` 的网络失败 / `401` / 流内 `error` 三种情况给出不同提示。
- [ ] 拉 `/v2/recent-modules` 渲染「最近使用」：新账号得到空数组时按「暂无」渲染而不是报错；
      用过某助手后它出现在首位；返回**恒是** `/v2/modules` 的子集（不必自己再过滤一遍）。
- [ ] 上传入口的显示与否读 `/v2/app-info` 的 `capabilities.file_upload.enabled`（§8.2.4），
      `accept` 与大小提示用同一份声明里的阈值，**没有**在前端硬编码 20MB / 8 个。
- [ ] 文件上传（若开放该入口）：`POST /v2/files` 换回 `file_id`，在 `/v2/chat` 的 `file_ids` 里
      引用后模型确实读到了内容；**不传 `conversation_id` 上传时**，后续 chat 用的是响应里回的那个号。
- [ ] 把上一个会话的 `file_id` 带进新会话 → 得到 `FILE_NOT_ACCESSIBLE` 的 `error` 事件且**整轮终止**
      （不是「少了附件照样答」），前端展示 `message` 并引导重新上传。
- [ ] 上传一份扫描件 PDF → 错误出现在**问答流**里而不是上传时，且文案能让用户看懂是扫描件（§8.2.3）。
- [ ] 带附件问一轮后刷新页面 → 历史里那条用户消息仍显示附件名（读 §6 的 `files`，不是本地缓存）。
- [ ] 历史页点附件能下载（`fetch` 带 token 取 `GET /v2/files/{file_id}`，**不是**裸 `<a href>`），
      中文文件名正常；文件过期/被清理后（410 `FILE_EXPIRED` 或 404 `FILE_NOT_ACCESSIBLE`，§8.2.6）
      下载按钮置灰但附件名仍在。
- [ ] 分享页点附件能下载（`GET /v2/shares/{share_id}/files/{file_id}`，接收人自己的 token）；
      票撤销后再点得到 410 `SHARE_REVOKED`。
- [ ] 上传入口对 `.doc` / `.ppt` / `.xls` 有「请另存为新格式」的提示（§8.2.3）。
- [ ] 会话分享（§6.1）：勾选消息 → `POST /v2/shares` → 用**另一个账号**打开
      `GET /v2/shares/{share_id}?user_id=<他自己的工号>` 能看到内容；分享 URL 里**只有
      `share_id`**，不含工号、会话 ID、messageId。
- [ ] 分享后原会话继续聊两轮 → 旧链接打开**看不到新消息**（快照是冻结的，不是实时订阅）。
- [ ] 撤销后打开得到 410 `SHARE_REVOKED`、过期得到 410 `SHARE_EXPIRED`、不在 `audience`
      得到 403 `SHARE_FORBIDDEN`，三种提示文案各不相同（不要合并成一句「打不开」）。
- [ ] **没有**把被分享人的 `user_id` 填成分享人工号去调 §6 的会话历史端点（那是冒用身份，
      平台按越权处理）。
- [ ] 分享确认框写清了「对方将看到这 N 条消息的完整内容，包括其中的业务数据，以及这些轮次附带的文件（对方可下载）」（§6.1.8）。
- [ ] 业务页面（自动审核 / 填单助手）的调用走 `POST /v2/tasks`（§3.8），带 `target` 与
      `ext_param.task`，token 是处理者 / 审核者**本人**的；调用后这次任务**不出现**在该用户的会话列表里。
- [ ] 任务码拼错时得到 `400 UNKNOWN_TASK`，响应里的 `available_tasks` 能看出正确写法。
- [ ] 任务按钮的显隐读 `/v2/modules` 里该助手的 `tasks`，没有该任务时不显示按钮而不是点了才报错。

## 变更记录

> **版本号暂不递增**：INFO 前端尚未开始对接 v2（切换排期待内网联调窗口），协议仍在定稿态内
> 打磨，**没有消费方需要据版本号判断兼容性**——此时递增只会造出一段「谁都没用过的版本史」。
> 待 INFO 实际开始对接后，任何变更再按 v1.1 / v2.0 递增并保证向后兼容。
> 变更本身仍逐条记录在案（本表按日期追加）。

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-07-06 | v1.0 | 协议定稿：chat（SSE 全事件）/ modules / conversations / messages / feedback；`end` 事件与响应头携带 `request_id` |
| 2026-07-15 | v1.0 | `end.usage` 开始真实下发本轮 token 用量（此前恒为空对象）；用量未知时仍为空对象，**未知 ≠ 0** |
| 2026-07-15 | v1.0 | `GET /messages` 每条消息新增 `sources`（本条回复由哪些模块参与，数组，`assistant` 行才有值），供历史页按消息标注模块。Dify 兼容面（`/v1/messages`）同步经 `inputs.selected_agent` 回显主目标（原 Dify 的同款载体，存量前端零改造即恢复该标签） |
| 2026-07-16 | v1.0 | **文档补漏，非行为变更**：事件类型总表此前遗漏 `chart` 与 `suggestions` 两类（平台自契约 §5 起就在下发，只是没写进总表）。一并写明：① `clarify`（答前阻断）与 `suggestions`（答后附加）payload 同构但语义/生命周期不同；② `clarify.recommendations` 结构；③ `chart` 实时流只发事件、echarts 代码块只投影进落库正文；④ §6 历史 `content` 里 `chart`/`clarify`/`suggestions` 三类会以文本块出现（原文「过程事件不落历史」对它们不成立） |
| 2026-07-28 | v1.0 | **`citation` 事件 item 字段定稿 + 引用角标渲染规则**（新增 §3.3.1）：item 必带 `document_id` / `document_name`（已剥离权限标签）/ `url`，并同值双写 `data_source_type`（v1 Dify 兼容遗留，v2 忽略）。三条渲染规则：按 `document_id` 去重聚合 → 回答末尾按顺序列文件名 → 正文 `<sup>[document_id]</sup>` 成可点角标且数字 = 末尾清单序号。同步澄清 `citation` **不按到达顺序插进正文**（与 `table`/`chart` 不同），以及 §6 `citations` 字段的口径。归一化由平台统一做，故存量模块给旧形状（`title`/`source`/`snippet`）也照样得到规范字段 |
| 2026-07-30 | v1.0 | **`table` 事件补上落库正文投影**（[决策](../decisions/2026-07-30-TABLE事件投影进落库正文与v1兼容.md)）：此前 `table` 只在实时流里存在，历史回读的 `content` 里没有它——刷新页面表格整张消失（v1 兼容面更是从未收到过表格）。现与 `chart` 同款处理，投影为 **Markdown 表格**、留在正文原位。**实时流不变**（照旧发一等 `table` 事件，正文里不重复），前端不必改；改的是 §6 那句「`table` 不落历史」。⚠️ 存量历史数据无法回填 |
| 2026-08-04 | v1.0 | **补齐会话管理与应用信息，v2 功能面覆盖 INFO 前端现有全部能力**（此前这几项只有 Dify 兼容面有，摘除 /v1 会丢功能）：① `GET /v2/conversations` 新增 `last_id` 游标分页（§5.1，响应增量新增 `has_more`/`limit`，不传 `last_id` 与此前逐字节一致）；② 新增 `DELETE /v2/conversations/{id}` 删除（软删，§5.2）与 `PATCH /v2/conversations/{id}` 重命名（§5.3），归属硬校验同历史读取；③ 新增 `GET /v2/app-info` 下发开场白（§8，**v2 唯一免鉴权端点**，与 `/v1/parameters` 同源）；④ 写明「停止生成 = abort 该请求」（§3.6），v2 不设 stop 接口——Dify 那个 stop 内部也只是事件间置取消位，粒度与 abort 一致。`/v1/parameters` 的其余字段在 v2 已被一等入参/`modules.intents`/恒关特性取代，不再需要 |
| 2026-08-13 | v1.0 | **§6 每条消息新增 `source_name`（答复助手的展示名）**（[决策](../decisions/2026-08-13-历史消息答复助手落款.md)）：`sources` 给的是模块编码，前端要渲染标签还得拿它 join `GET /v2/modules`——而那份清单只覆盖**当前**授权到的模块，翻旧历史时标签会就地消失。现直接给名字，空串 = 平台自答/未标注。**纯增量字段，既有字段一字未变。** 同期修复 Dify 兼容面的同一件事：`GET /v1/messages` 的 `answer` 末尾此前不补 `<sub>[app:助手名]</sub>` 落款（流式一直在补），导致存量 INFO 前端翻历史时每条消息的助手标签整片消失 |
| 2026-11-03 | v1.0 | **新增业务任务调用端点 `POST /v2/tasks`**（§3.8，[决策](../decisions/2026-11-03-任务面端点与任务级数据范围声明.md)）：自动审核、填单助手等嵌在业务页面里的调用改走它——请求体与 SSE 与 `/v2/chat` 完全相同，但 `target` 与 `ext_param.task` 必填（任务码须是助手声明过的），任务会话**不进 §5 会话列表**、在统计里单独计为业务调用。`/v2/modules` 每项新增 `tasks` 数组（纯增量）。§3.1 `target` 一行改写：此前写「调试用、普通界面不要传」，与 3.1.1「用 `ext_param` 时请传」矛盾。**`/v2/chat` 行为不变**，未切换的页面不受影响 |
| 2026-08-09 | v1.0 | **导出文件下载端点 `GET /f/{token}`**（新增 §8.1，[决策](../decisions/2026-08-09-模块文件导出与下载链接.md)）：模块生成 Excel/CSV 等文件时把链接嵌进回答正文，**前端零改动**（正文本就按 Markdown 渲染）。三点需知会：① 该端点不在 `/v2` 之下、不要求任何请求头，当前**任何人拿到链接即可下载**（保护 = 随机 token + 24 小时有效期），后续补鉴权时需前端在下载请求上带 INFO token，方案落地前另行沟通；② 链接过期返回 **410**（不是 404），浏览器直开会看到「请重新提问生成」提示页，翻历史点旧链接必然落到这里；③ 响应恒 `attachment`，不要试图内联预览。同期无任何既有端点行为变更 |
| 2026-08-26 | v1.0 | **新增 §4.1 `GET /v2/recent-modules`（最近使用的助手，最多 5 个、按最近使用时间降序）**（[决策](../decisions/2026-08-26-最近使用助手记录与前端拉取.md)）：供前端把常用助手顶到菜单前面。记录口径是「用户**显式指定**了该助手（`target` / v1 的 `inputs.selected_agent`）**且**这一轮成功对话了」——自动路由选中的、以及没权限/已下线/报错的轮次都不记。读侧按当前授权 ∩ 已装配过滤，**过滤后不足 5 个即返回不足 5 个**（新用户为空数组，属合法状态），不补足。**纯新增端点，既有端点一字未变**；Dify 兼容面同期新增对应的 `GET /v1/recent-agents`（同数据、Dify 字段惯例、无授权过滤） |
| 2026-09-09 | v1.0 | **补文档：用户文件输入通道**（新增 §8.2，`POST /v2/files` + `chat.file_ids`，[决策](../decisions/2026-09-09-对话模型切换为Qwen-3.8-27B与多模态输入.md)）。⚠️ **这不是新功能上线，是文档追平实现**——该通道自 2026-09-09 起就已可用，只是此前从未写进本协议，INFO 前端照文实现时看不到它。一并写清：① §3.1 请求字段表补 `file_ids` 行；② 归属是 `user_id` + `conversation_id` **双绑定**，跨会话引用一律拒绝**整轮**，「不存在」与「不是你的」刻意合并成同一个 `FILE_NOT_ACCESSIBLE`（避免存在性探测）；③ 上传成功 ≠ 读得懂（图片零解析直传、文档由平台抽文本、扫描件 PDF 明确报错、**读不读取决于本轮路由到的助手**）；④ 与 §8.1 导出下载**方向相反、鉴权相反**，两节不可互相照抄。同时**订正 §8 的一处过时陈述**：原文把 `file_upload` 与语音/标注并列为「平台一律不支持」，该句在上传通道落地后已不成立；v2 不下发能力开关字段，启用与否按 §8.2.4 处理 |
| 2026-09-20 | v1.0 | **补文档：服务可用性探测**（新增 §2.3）。回答 INFO 前端迁移期的提问「`/v1/info` 在 v2 有没有平替」：推荐 `GET /v2/app-info`（免鉴权，且前端启动本来就要调它拉开场白，**零额外请求**），要更细的运行状态则用平台级的 `GET /healthz`（免鉴权、已在 CORS 内，回模块清单与能力开关）。三条要点写明：① **`/healthz` 的 `degraded` 也回 200**（刻意如此，避免「20 个模块挂 1 个」被判死重启），故不能只看状态码、要读 `status` 与 `failed_modules`；② `/healthz` 会回模块编码与能力开关名（不含库名/内网地址），是否暴露给终端用户浏览器请与运维确认；③ **两者都证明不了「现在能不能正常问答」**，故不建议运行期轮询探活，真实可用性以那一次 `/v2/chat` 的结果为准（网络失败 / 401 / 流内 `error` 三种分别提示）。同期 §8 补一句交叉引用、自测清单补一条。**平台行为一字未改** |
| 2026-09-20 | v1.0 | **`GET /v2/app-info` 新增 `capabilities.file_upload`**（§8，§8.2.4 随之改写）：声明本环境是否启用上传通道，以及 `max_bytes` / `max_files_per_turn` / `allowed_extensions` 三个阈值。**这是本批唯一的平台行为变更**（其余为补文档）。起因是 INFO 前端迁移期发现：上传入口显不显示此前只能靠前端配置常量或「先传一次看是不是 404」来猜，而那几个阈值又都是部署侧可配的，前端硬编码一份迟早与服务端漂移。两条设计约束写进文档：① **声明与实际同源**——`enabled` 与 `POST /v2/files` 是否 404 出自同一个判据（`state.uploads` 在不在），不会出现「说开着、真传却 404」，契约测试钉住了这一点；② `capabilities` 里只放**不随用户变**的开关，随用户变的属于 `/v2/modules`（本端点免鉴权，加了随用户变的字段它就得鉴权了）。**纯增量字段**，既有字段一字未变；未识别的能力键前端必须忽略 |
| 2026-09-20 | v1.0 | **新增会话分享（§6.1，[决策](../decisions/2026-09-20-会话分享与只读快照.md)）：`POST /v2/shares` 签票 · `GET /v2/shares/{id}` 兑换 · `GET /v2/shares` 我的分享 · `DELETE /v2/shares/{id}` 撤销 · `GET /v2/shares/{id}/views` 谁看过**。起因是 INFO 前端迁移期发现 v1 那套分享在 v2 下打不开：v1 靠「URL 带分享人工号 + `/v1/messages` 认自报工号」实现，而 v2 每个端点都验 INFO token 并按归属 403。**替代方案把身份与授权拆开**——`share_id` 决定能看哪份内容，被分享人用**自己的**登录态证明自己是谁，URL 里不再出现工号/会话 ID/messageId。四条设计约束写进文档：① **冻结快照而非指针**，分享后原会话新增的消息永不顺着旧票流出（v1 那条 URL 实为长期订阅）；② 兑换仍需鉴权，**没有免登录形态**（对照 §8.1 导出链接的相反取舍）；③ 有效期默认 7 天、上限 30 天，**不提供永不过期**；④ 每次成功打开都留痕，分享人可查、可随时撤销。数据权限上业务方明确拍板「**允许分享即视为分享人主动授予该份内容的查看权**」（§6.1.8），平台无法按被分享人权限重过滤已渲染的正文，故以上四条 + `audience` 白名单是这条决策的补偿控制。**纯新增端点，既有端点一字未变**；§6.1.9 给了 v1→v2 的逐项对照 |
| 2026-09-21 | v1.0 | **`GET /v2/shares` 支持分页与状态筛选**（§6.1.5）：新增 `offset` / `status` 两个 query 参数，响应新增 `total` / `offset`，每条分享新增 `status` 字段（`active` / `revoked` / `expired`）。**这是补漏**：此前该接口只有 `limit`、不给总数，前端无法翻页，只能看到最近 N 张（最多 200），而撤销和过期的票不会从列表里消失，票一多更早的就翻不到了。三条要点：① `total` 计的是**筛选后**的集合，状态页签必须把 `status` 交给服务端，不要本地过滤；② 三个状态两两互斥、撤销优先于过期，每条的 `status` 与筛选同一口径；③ 用页码而非 §5.1 那样的游标，因为这是要跳页、要看总数的管理表格。**纯增量**：不带新参数时返回同一批条目，既有字段一字未变 |
| 2026-09-23 | v1.0 | **会话标题改由本地模型生成**（[决策](../decisions/2026-09-23-会话标题LLM生成.md)）：`title` 不再恒等于「首问截断的 64 字符」，而是本地模型概括的一句 **≤12 汉字**短标题（§5）；`end` 事件随之新增可选字段 `conversation_title`（§3.2），生成及时的那一轮直接带回新标题，前端可就地刷新侧边栏而不必重拉列表。三条要点：① **`conversation_title` 经常不出现**——没到刷新时机（生成只发生在第 1/3/6 轮及切助手时）、用户改过名、生成失败或没赶上本轮收尾都不带它，不带 ≠ 出错，按「有就用、没有别动」处理；② **改名即锁定**，调过 `PATCH /v2/conversations/{id}` 的会话此后永不被自动生成覆盖（§5.3）；③ 标题变化**不动 `updated_ts`**，不会把老会话顶到列表最前。生成是与回答并发的旁路，失败即保持原标题，且可按部署关闭（关闭时行为与此前逐字一致）。**纯增量**：既有字段一字未变，`title` 的位置与语义不变，只是内容更短更概括 |
| 2026-09-23 | v1.0 | **会话标题取消 12 汉字硬截断**（[决策修订](../decisions/2026-09-23-会话标题取消字数硬截断.md)）：实测按显示宽度硬截会把标题截成半句、表义不清。现改为只在提示词里要求「一句话、尽可能短、不带标点」，**平台不再截断**，`title` / `end.conversation_title` 长度不固定。侧边栏放不下时请前端用 CSS 省略（如 `text-overflow: ellipsis`）并在悬停时显示全文。字段与语义不变 |
| 2026-09-20 | v1.0 | **`POST /v2/feedback` 放行 `rating: "none"`（撤销赞/踩），`GET …/messages` 新增 `ratings` 回显**（§7、§6，[决策](../decisions/2026-09-20-v2反馈撤销与历史回显.md)）。起因是 INFO 前端迁移期发现「取消点赞/取消点踩」一律 422：撤销语义（存储层的 `REVOKED` 标记）此前在三个写入入口各声明一次——Dify 兼容面收 `rating=null`、Admin 调试台收 `"none"`，**唯独 `/v2/feedback` 的字面量漏了它**，而该端点又是 v2 下唯一的反馈入口。同时补上配套的读侧：v1 的 `GET /v1/messages` 一直回显 `feedback.rating`，v2 的历史端点却不回任何评分字段，前端刷新一次赞踩高亮就全丢。两项均为**纯增量**：既有的 `"up"`/`"down"` 请求与既有响应字段一字未变。平台侧同步把三个入口的 rating 取值收口到共享的 `RatingInput` 别名，杜绝同类漂移复发 |
| 2026-10-12 | v1.0 | **Dify 兼容面 `/v1/*` 整体下线**（[决策](../decisions/2026-10-12-下线Dify兼容面v1.md)）：INFO 前端已全部迁到 v2，平台删除 `/v1/*` 全部端点（问答/停止生成/历史/反馈/会话管理/应用信息/上传/最近使用助手/特性禁用类）与 `FORGE_DIFY_APP_KEYS` 配置，请求 `/v1/*` 一律 404。**v2 端点一字未变**；§1、§2.3、§4.1、§8 中对 /v1 的说明改为迁移对照口径。审计/统计里存量的 `dify` 入口记录照常可查
| 2026-10-12 | v1.0 | **新增保证：收到 `end` 时本轮已落库**（§3.3「前端处理保证与建议」，[决策](../decisions/2026-10-12-下线Dify兼容面v1.md) 遗留事项）：此前助手回复与「最近使用」记录在 `end` 下发**之后**才写入，前端在 `end` 回调里立刻拉 `GET …/messages` / `GET /v2/recent-modules` 有概率读不到刚答完的这一轮（v1 当年在兼容面里规避过，v2 一直没有）。现两者都在 `end` 之前写入，`end` 晚到的只是一次写库的耗时（毫秒级）。**事件与字段一字未变**
| 2026-10-13 | v1.0 | **两处鉴权收紧**（[决策](../decisions/2026-10-13-v2用户身份与token绑定.md)，关闭 [open-questions #16](../open-questions.md)）：① **`user_id` 与 token 绑定**（§2.1）：平台比对请求 `user_id` 与 `GetAgentMenu2` 回显的 `Data.UserId`，不一致或未回显一律 `401 USER_TOKEN_MISMATCH`——此前 `user_id` 只是自报标签，持自己合法 token 填别人工号即可读/删/改名他人会话、撤销他人分享、以他人身份反馈；② **`/v2/chat` 续聊校验会话归属**（§3.1）：他人会话 `403`、本人已删会话 `404`，此前它是会话端点里唯一不校验归属的，知道会话号即可往别人会话里追加消息。两者都是**收紧**，照规矩传「当前登录用户工号 + 本人会话号」的前端**无需改动** |
| 2026-10-14 | v1.0 | **§6 历史消息新增 `files`（这一轮附带的上传文件）**：此前附件只在 `upload_files` 表里按会话登记，消息行上没有任何痕迹，`GET …/messages` 也就回不出「这一轮附了哪个文件」。§8.2.3 原先让前端「用本地文件对象自行渲染」，这只在当前页面里成立，刷新或换设备后附件标记就丢了。现由平台把**归属校验通过**的文件元信息 `{file_id, filename, media_type, size}` 记在当轮 `user` 行上，`assistant` 行与没附文件的轮次为 `[]`；引用被拒的轮次也是 `[]`，别人文件的名字不会写进你的历史。只有元信息，不含内容与下载地址。会话分享快照（§6.1）与历史同形，也会带上这个字段。**纯增量字段**，既有字段一字未变；本次之前的历史无法回填，一律为 `[]` |
| 2026-10-14 | v1.0 | **新增上传文件下载**（新增 §8.2.6，[决策](../decisions/2026-10-14-上传文件历史回显与回下载.md)，取代 §8.2.3 原文「平台不提供上传文件的回读/预览端点」）：上传人本人 `GET /v2/files/{file_id}`；分享接收人 `GET /v2/shares/{share_id}/files/{file_id}`，准入 = 兑换该票的全部闸 + 文件在票冻结的消息里（附件随它所在的那一轮一起被授予，§6.1.8 同步补一句、分享确认框文案随之加长）。鉴权与其余端点同一套，**不发签名链接**，前端须 `fetch` 带头取 blob 再保存；响应恒为附件、带 nosniff + CSP sandbox，**不提供预览/缩略图**。文件有效期独立于分享票，过期得 `410 FILE_EXPIRED`。CORS 新增暴露 `Content-Disposition`（§9）。同期 §8.2.3 补写：`.doc` / `.ppt` / `.xls` 旧格式上传成功但当前读不了。**纯新增端点**，既有端点一字未变 |
| 2026-10-15 | v1.0 | **问答改为后台生成：断开连接不再停止生成**（[决策](../decisions/2026-10-15-问答后台生成与断线续接.md)，**取代 §3.6 原文「停止 = abort 请求、不需要 stop 接口」**，⚠️ 前端须同步改造，不设兼容期）：① 关页 / 切会话 / abort 请求都**不影响**生成，回来时回复完整（§3.2）；② **停止生成改为** `POST /v2/chat/{request_id}/stop`（§3.6）；③ 新增断线续接 `GET /v2/chat/{request_id}/events?after=`（§3.7），SSE 每帧新增 `id: <seq>` 行（§3.3），只按 `data` 行解析的实现不受影响；④ `end` 新增 `status`（completed / stopped / interrupted，§3.3），历史消息新增同义的 `status`，生成中的那一轮为 `generating` 并带 `stream_seq` 快照序号（§6）；⑤ 会话列表新增 `generating` / `has_unread`（§5），新增 `POST /v2/conversations/{id}/read` 标已读（§5.4）；⑥ 新增开工拒绝 `409 CONVERSATION_BUSY` / `429 TOO_MANY_RUNNING_TURNS` / `503 TURNS_SATURATED` / `503 PLATFORM_RESTARTING`（§3.2），生成中的那一轮评价 / 分享得 `409 TURN_IN_PROGRESS`（§6.1.3、§7）。同期修复：断开后回复整条丢失、历史只剩提问（根因是断连时落库跑在已被取消的任务里） |
