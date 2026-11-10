# 国内填单内容润色：INFO 前端对接说明

> 读者：INFO 前端开发者。润色口径见 `ai_polish.md`，谁能用见 `privileges.md`「国内填单内容润色」。依据：决策 2026-11-09「AI 润色任务接口设计」。

## 一句话

INFO 管理页面国内制程问题单上某一栏的【AI润色】按钮被点击时，页面调 `POST /v2/tasks`，把这一栏的原文放进 `query`、栏目种类等参数放进 `ext_param`；本助手返回润色后的内容，页面在填写人确认后用它替换原文。本助手不写回问题单。

## 常量

| 项 | 值 |
|---|---|
| 接口 | `POST /v2/tasks` |
| `target` | `FACTORY_ISSUE` |
| `ext_param.task` | `domestic_polish` |

请求头、请求体的通用字段、SSE 事件格式、停止与断线续接，都与对话接口 `/v2/chat` 相同，流式解析代码可以直接复用。

## 按钮显不显示

调 `GET /v2/modules`，列表里有 `FACTORY_ISSUE`、且它的 `tasks` 里有 `code` 为 `domestic_polish` 的一项时才显示按钮。没有开通本助手的用户列表里没有它，强行调用会得到 `403 NOT_AUTHORIZED_FOR_MODULE`。

## 请求

```json
POST /v2/tasks
Authorization: Bearer <点按钮的人本人的 INFO token>
Content-Type: application/json

{
  "query": "<这一栏当前的内容>",
  "user_id": "<点按钮的人的工号>",
  "target": "FACTORY_ISSUE",
  "ext_param": {
    "task": "domestic_polish",
    "field": "measures",
    "max_length": 2000,
    "issue_no": "ZC2026110001",
    "context": { "reason": "<同一表单里刚写的原因分析，纯文字>" }
  }
}
```

- `query`：这一栏当前的内容，只放这一段。富文本栏放编辑器里的 HTML 原样（TinyMCE `getContent()`），图片是已上传的链接 `<img src="…">`；5Why 的问或答放纯文字。
- 不传 `conversation_id`：每次润色互不相关。共用一个会话号时，同一会话同时只能有一轮，第二次点会得到 `409 CONVERSATION_BUSY`。
- 不传 `file_ids`、`attributes`。

### `ext_param` 的键

| 键 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `task` | ✅ | string | 固定 `domestic_polish` |
| `field` | ✅ | string | 栏目种类，见下表 |
| `max_length` | 建议传 | 正整数 | 这一栏最多能存多少字符，润色结果不会超过它。按内容原样数字符，富文本栏连 HTML 标记一起数。没传时用下表的默认值 |
| `issue_no` | ✕ | string | 问题编号（`ZC` 开头）。传了，本助手按编号查这张单已保存的内容作参考；建单页还没有编号时不传 |
| `context` | ✕ | object | 同一张单其他栏的当前内容，见下文；和按编号查到的内容冲突时以它为准 |

其余的键本助手忽略。整个 `ext_param` 序列化后不能超过 64KB、嵌套不能超过 6 层，否则平台在开流前返回 `400 invalid_param`。

### `field` 的取值

| 取值 | 栏目 | `query` 与结果的格式 | 默认字数上限 |
|---|---|---|---|
| `problem_desc` | 问题描述 | HTML | 不限 |
| `reason` | 原因分析 | HTML | 不限 |
| `five_why_question` | 5Why 的问 | 纯文字 | 不限 |
| `five_why_answer` | 5Why 的答 | 纯文字 | 不限 |
| `measures` | 改善措施 | HTML | 2000 |
| `prevention` | 预防对策 | HTML | 900 |

5Why 一次润色一条：提问时用 `five_why_question` 润色这一问，答复时用 `five_why_answer` 润色这一答。栏目种类由本助手的管理员维护，以后新增栏目会另行通知取值。

### `context` 的键

都可选，只传页面上有的；正在润色的这一栏不用传。内容请传纯文字（TinyMCE `getContent({format: "text"})`）：参考用不到图片，带 HTML 容易超过 64KB。

| 键 | 类型 | 说明 |
|---|---|---|
| `problem_type` | string | 问题类型，如「硬件问题」 |
| `model` | string | 机型；「物料」单不传 |
| `material` | string | 物料名称或料号 |
| `problem_desc`、`reason`、`measures`、`prevention` | string | 同单这几栏的当前内容 |
| `five_why` | array | 已有的 5Why，按先后排列，每项 `{"question": "…", "answer": "…"}`，待答复的 `answer` 为空串；不含正在润色的这一条 |
| `current_question` | string | 润色 5Why 的答时，这一答对应的问。`field` 为 `five_why_answer` 时**必传** |

按编号只查得到已保存的内容。同一表单里刚写、还没提交的栏目，请放进 `context`。

### 典型调用

| 场景 | `field` | 要带的 |
|---|---|---|
| 建单页润色问题描述 | `problem_desc` | 没有 `issue_no`；`context` 带问题类型、机型或物料 |
| 责任人确认表单里润色改善措施 | `measures` | `max_length`；表单里刚写的原因分析放进 `context.reason`；`issue_no` |
| 答复一条 5Why | `five_why_answer` | `context.current_question`；前面的问答放 `context.five_why`，或只带 `issue_no` |

## 响应

### 事件

| 顺序 | 事件 | 内容 | 页面怎么用 |
|---|---|---|---|
| 1 | `progress` | 「正在润色」；等待期间每 10 秒再发一次 | 显示等待状态（见下文「要等多久」） |
| 2 | `delta`（一条或几条） | 润色结果。**按序拼起来就是完整结果** | 拼起来给填写人看、确认后替换原文；不要按 Markdown 渲染 |
| — | `error`（出错时代替 2） | `code`、`message`，见下文 | 显示 `message`，不动原文 |
| 末 | `end` | `status` 等 | 本次结束 |

结果在本助手检查通过后才发出，不会出现显示了一半又作废的情况。

**只在收到 `end`、`end.status` 为 `completed`、并且没有收到 `error` 时，才可以用结果替换原文。** `stopped`（调了停止）或 `interrupted`（超时、平台重启）时结果可能不完整，不要用。

### 结果格式

- HTML 栏：每段一个 `<p>…</p>`，可以直接 `setContent()`；原文里的图片（含内嵌的图片）、表格、超链接原样放回原来的位置；加粗、颜色、字号不保留，编号列表改成分条的段落。
- 纯文字栏：段落之间用换行。
- 原文不需要修改时，原样返回。

### 错误

开流前由平台以 JSON 返回（`{code, message}`，`message` 可直接显示）：

| HTTP | code | 场景 |
|---|---|---|
| 400 | `invalid_param` | 缺 `target` 或 `task`，或 `ext_param` 超过 64KB、6 层 |
| 400 | `UNKNOWN_TASK` | 任务码拼错；响应里的 `available_tasks` 列出正确写法 |
| 401 | — | token 无效，或 `user_id` 与 token 不是同一人 |
| 403 | `NOT_AUTHORIZED_FOR_MODULE` | 当前用户没开通本助手 |
| 404 | `MODULE_NOT_REGISTERED` | 本助手当前未上线 |
| 409 | `CONVERSATION_BUSY` | 带了会话号、且这个会话上一次润色还没结束 |
| 429 | `TOO_MANY_RUNNING_TURNS` | 这个人同时进行中的回复已达上限（默认 3 个，与对话共用） |
| 503 | `TURNS_SATURATED`、`PLATFORM_RESTARTING` | 平台繁忙或重启中，稍后重试 |

开流后由本助手以 `error` 事件返回（`fatal: true`，随后仍有 `end`）：

| code | 场景 | message |
|---|---|---|
| `POLISH_EMPTY` | 原文为空，或去掉图片、表格后没有文字 | 请先填写内容再润色 |
| `POLISH_TOO_LONG` | 去掉图片、表格后的文字超过上限（初始 3,000 字，由本助手的管理员调整） | 内容较长，请分段润色 |
| `POLISH_BAD_PARAM` | `field` 不认识、`max_length` 不是正整数、润色 5Why 的答没给 `current_question` | 润色参数有误，请联系系统管理员 |
| `POLISH_FAILED` | 这次没能润色成功 | 这次没有润色成功，请稍后重试或手动修改 |

## 要等多久

- 一般十几秒以内：大约每千字 10 秒，原文 3,000 字（上限）约 30–40 秒。
- 模型繁忙时会更慢。本助手每次调模型最多等 110 秒，结果没通过检查时会再调一次，最坏约 4 分钟后收到结果或 `POLISH_FAILED`。
- 页面不要自设比这更短的超时，否则会在本助手拿到结果之前先放弃。等待期间每 10 秒有一个 `progress`，可据此确认连接还在。

## 页面要注意的

- 一栏润色进行中时，禁用这一栏的按钮；收到 `429` 时提示稍后再试。
- 用户关掉弹窗不会停止生成。要停止，调 `POST /v2/chat/{request_id}/stop`（`request_id` 取响应头 `X-Request-Id`）；不调也不影响结果。
- 每次润色在平台留一个任务会话，不出现在用户的会话列表里。
- 本助手的对话框里不做润色，用户在对话框里要求润色时会被引导回问题单页面。

## 什么时候可以切换

本助手发布含这个任务的版本、平台部署 0.3.9 及以上之后。
