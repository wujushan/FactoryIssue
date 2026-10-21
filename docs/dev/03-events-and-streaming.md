# 03 · 事件协议与流式输出

`handle()` 是一条**事件流**：你 `yield` 的每个 `Event` 经平台网关多路复用、以 SSE 透传到前端，
不管中间隔了多少层模块调用，事件一路流到底。这一章讲该 `yield` 什么、按什么节奏。

## 全链路流式是红线

平台要求**全链路流式输出**（SSE 事件协议贯穿网关→模块→前端）。不要「攒完再一次性返回」——
边算边 `yield`，让用户尽早看到进度与正文。

## 事件类型速查

| 事件 | 构造器 | 用途 |
|---|---|---|
| `delta` | `Event.delta(text)` | 正文 token 流（回答主体，可多次） |
| `progress` | `Event.progress(stage, detail="")` | 阶段进度（取数中/统计中/生成中…） |
| `tool_call` | `Event.tool_call(tool, arguments=None)` | 工具调用开始（含参数摘要） |
| `tool_result_meta` | `Event.tool_result_meta(tool, meta=None)` | 工具结果元信息（行数/耗时，**不含大数据体**） |
| `table` | `Event.table(columns, rows, *, title="")` | 结构化表格产物 |
| `chart` | `Event.chart(chart_type, series, *, title="", x=None, unit="", style=None)` | 图表产物（抽象 spec，数字须来自沙箱；`style` 是 echarts 样式直通位，只管长相，见 [02](02-sdk-reference.md#事件协议-forge_coreevents)；[见下](#表格与图表产出事件别再往正文里抄一遍)） |
| `citation` | `Event.citation(items)` | 引用溯源（知识/检索结果出处） |
| `clarify` | `Event.clarify(question, options=None, *, recommendations=None, guide_text="")` | 澄清引导（**答前阻断**：意图/参数不明确） |
| `suggestions` | `Event.suggestions(recommendations, *, guide_text="")` | 追问建议（**答后非阻断**：引导下一步；[见下](#追问建议suggestions)） |
| `error` | `Event.error(code, message, *, fatal=True)` | 错误（`fatal=False` 表示可恢复） |
| `end` | `Event.end(...)` | **流结束——平台补发，模块不要产出** |

> 📎 **要给用户一个可下载的文件**：没有对应的事件类型，走 `ctx.files` 拿链接后自己嵌进
> `delta` 正文（[见下](#文件下载没有-file-事件链接自己嵌进正文)）。

## 铁律：END 由平台补发

模块内部**绝不** `yield Event.end()`。每次请求恰好一个 END，由平台网关统一补发（附加 request_id/conversation_id/usage 等请求级元数据）。模块只管产出「主体事件」。

## 典型流式骨架

一个「取数 → 统计 → 生成回答」的数据查询模块，事件节奏大致如下：

```python
async def handle(self, request: ModuleRequest, ctx: ModuleContext) -> AsyncIterator[Event]:
    yield Event.progress("routing", "已定位到销售查询")

    # 1) 取数（受控句柄，权限自动注入）
    yield Event.progress("fetch", "正在取数")
    yield Event.tool_call("sql_query", {"table": "sales", "region": "华东"})
    df = ctx.data.fetch(QuerySpec.model_validate({          # 受控取数一等形态，见 04
        "source": "sales_db", "from": "fact_sales",
        "select": ["region", "amount", "sale_date"],
        "filter": {"groups": [{"conditions": [
            {"field": "region", "operator": "EQ", "value": "华东"}]}]},
    }))
    yield Event.tool_result_meta("sql_query", {"rows": len(df)})

    # 2) 数字处理走沙箱（禁止 LLM 直算）
    yield Event.progress("compute", "正在统计")
    outcome = run_script(SUM_SCRIPT, datasets={"sales": df})
    if not outcome.ok:
        yield Event.error("sandbox_failed", outcome.error)
        return
    total = outcome.result["total"]

    # 3) 表格产物 + 流式正文
    yield Event.table(columns=["区域", "销售额"], rows=[["华东", total]], title="本月销售额")
    async for piece in ctx.llm.chat_stream([
        {"role": "user", "content": f"用一句话播报：华东本月销售额 {total}"}
    ]):
        yield Event.delta(piece)
    # 不 yield end()
```

## 表格与图表：产出事件，别再往正文里抄一遍

`table` / `chart` 是**一等事件**，不是「顺手也写进 `delta` 正文」的东西：

```python
yield Event.table(columns=["区域", "销售额"], rows=[["华东", total]], title="本月销售额")
yield Event.delta("华东领先，环比 +12%。")   # 正文只说结论，不重复那张表
```

平台会把这两类事件**确定性地投影进落库正文**（`table` → Markdown 表格、`chart` → ` ```echarts `
代码块；`chart` 带了 `style` 时，围栏里的 option 已经把样式合并进去，历史回读直接渲染即可），
让历史回读（`GET /v2/conversations/{id}/messages`）也看得到表和图 —— 位置就在事件到达的那个位置。所以：

- **自己再往 `delta` 里写一份 Markdown 表格 = 用户看到两张表**（实时流一张来自事件、历史里
  两张都在正文）。
- 表格数据别先转成字符串再 `Event.delta` —— 那样前端只能当纯文本渲染，也进不了后续的结构化消费。

> 🔁 **投影的另一面：读回来时要剥掉**。这些渲染块是给前端的，回灌进 LLM 上下文是纯噪声（一张
> 几百行的表能把上下文预算一次吃光）。取多轮历史时用
> [`conversation_messages`](02-sdk-reference.md#多轮上下文-forge_coreconversation)，它按同一套
> 标记把表格折成「表头 + 前几行」、图表折成 `［图表］`。「拼」与「剥」共用一个常量信源
> （`forge_core.conversation.ECHARTS_FENCE_LANG` / `CLARIFY_BLOCK_TAG`），不会改了一半。

### 文件下载：**没有** `file` 事件，链接自己嵌进正文

导出文件是唯一一处**刻意不做成一等事件**的产物：

```python
ref = await ctx.files.save_dataframe(df, "明细.xlsx")
yield Event.delta(f"\n\n全部 {len(df)} 条见 {ref.markdown}")   # 就是一条普通正文
```

理由与上面那条投影正相反：`table`/`chart` 需要前端**结构化渲染**，所以必须是事件（再另投影进
正文）；而下载链接**本身就是 Markdown 的原生能力**，做成事件反倒要回答「v1 兼容面怎么投影、
历史回读怎么办、INFO 前端认不认」三个问题，换不来任何东西。正文链接 v1/v2 同时生效、随会话
历史天然留存，前端零改动。

用法与三种错误（扩展名白名单 / 单文件上限 / 磁盘配额）见
[02 · 文件导出](02-sdk-reference.md#文件导出-forge_corefilesctxfiles-出站)，展示与全量的分工见
[09 · 答案呈现](09-answer-presentation.md)。

## 澄清引导（clarify）

路由/参数不明确时，用 `clarify` 给出可点选的结构化推荐（对齐原 Dify「意图澄清与引导助手」）：

```python
yield Event.clarify(
    question="你想查哪个区域？",
    recommendations=[
        {"id": "1", "name": "华东", "label": "查华东区销售额", "query": "查华东区本月销售额"},
        {"id": "2", "name": "华南", "label": "查华南区销售额", "query": "查华南区本月销售额"},
    ],
    guide_text="请选择要查询的区域",
)
```

- `recommendations[*].label` = 按钮文字，`query` = 点击后自动发送的完整消息。
- `options`（`list[str]`）是纯文本兜底展示。
- **澄清就是这一轮的完整回答**：平台把它投影成 `<intent_routing_clarify>` 数据块写进落库正文
  （同 `table`/`chart` 的投影范式），历史回读与 v1 兼容面都看得到；所以**只发 `clarify`、
  一条 `delta` 都不发是合法形态**，不必为了「留个记录」再补一句正文。同理这一轮平台不会追加
  追问建议——澄清是答前阻断，本轮还没回答。

## 追问建议（suggestions）

回答**已经完整产出之后**，用 `suggestions` 给出下一步可点的追问按钮：

```python
yield Event.suggestions(
    [
        {"id": "1", "name": "按机型看", "label": "按机型看分布", "query": "上个月制程问题单按机型的分布"},
        {"id": "2", "name": "看明细", "label": "看未关闭的单", "query": "上个月还没关闭的制程问题单有哪些"},
    ],
    guide_text="您还可以继续问：",
)
```

- **第一个参数就是 `recommendations`，是 `list[dict]`，不是 `list[str]`**——每项的形状与
  `clarify` 的 `recommendations` 完全相同（`id` / `name` / `label` / `query`，见
  [02 · 事件协议](02-sdk-reference.md#事件协议-forge_coreevents)）。传字符串列表**不会报错**，
  但前端渲染不出按钮，框架拦不住。
- 与 `clarify` 的区别在生命周期，不在形状：`clarify` 是**答前阻断**（本轮就停在这组按钮上）；
  `suggestions` 是**答后附加**，跟在正文/表格/图表之后，流照常结束。
- `query` 是点击后自动发送的完整消息，要写成**离开上下文也能看懂、能被路由回来**的问法；
  只推荐本模块真答得了的问题。
- 投影方式与 `clarify` 相同：平台把它投影成 `<intent_routing_clarify>` 数据块写进落库正文，
  历史回读与 v1 兼容面都看得到。
- 可选；一轮发一组即可（测试通道的 `suggestions` 字段只取第一组）。出错的那一轮别发（「您还可以问……」跟在一句报错后面很荒唐）。模块没发时，
  平台**可能**用本轮问答自动补一组（部署侧开关，默认关）——模块自己发了，平台就不补。

## 错误处理

- 可预期的业务失败（无权限、无数据、沙箱失败）→ `Event.error(code, message, fatal=...)` 后 `return`。
- `fatal=True`（默认）表示终止性错误；`fatal=False` 表示流可继续（如某子步骤降级）。
- 不要把权限拒绝「吞掉」当成空结果——fail-closed，如实报错。

## 引用溯源（citation）

知识/检索类回答要带出处，供前端渲染引用、历史回读。

**用 `ctx.knowledge` 检索的，别自己拼 items**——平台给了构造器：

```python
payload = await ctx.knowledge.retrieve("pdc", request.query)
yield Event.citation(ctx.knowledge.citations("pdc", payload))
```

它负责 doc_id→文件名映射、**文件名里权限标签前缀的剥离**、预览 URL 拼装、按文档去重。
⚠️ 第二步是安全相关的：RAGFlow 里文档的 `permission_code` = 其库内目录路径，按管理规范同样
编进文件名前缀。自己从 chunks 拼引用 = 把该文档的授权目录路径随答案发给终端用户。

**手写 items 时的规范字段**（决策 2026-07-28，完整表见 `docs/api/INFO对接-v2-API协议.md` §3.3.1）：

```python
yield Event.citation([
    {
        "document_id": "0000097012",      # 正文角标 <sup>[document_id]</sup> 按它回指
        "document_name": "2024 销售制度.pdf",  # 已剥离权限标签的文件名
        "url": "http://kb.internal/document/0000097012?ext=pdf&prefix=public",
        "content": "第三条……",             # 命中切片正文（可选）
    },
])
```

平台在网关出口**统一归一化**（`forge_core.citations`）：补齐缺失的规范键、并把 `url` 同值
双写进 `data_source_type`（当年 v1 Dify 兼容面靠它渲染链接；/v1 已于 2026-10-12 下线，双写保留以免存量消费方断）。故旧形状 `{title, source, snippet}`
仍然能用（映射到 `document_name` / `url` / `content`），但新代码请直接写规范字段。

`citation` 的 items 也会随 assistant 记录落库（`session.append(..., citations=...)`），历史回读时还原。

### 让角标真的出现：doc_id 必须先进模型的上下文

正文里打 `<sup>[document_id]</sup>` 角标，前端就渲染成可点引用（**方括号不能少**），并按引用
清单里的次序给它编号——模块不必自己编号。但角标是**模型写出来的**，而模型只能引用它看得见的
东西，所以要两步，**缺一个角标就永远不会出现**：

**1. 把 doc_id 拼进喂给模型的切片正文**（平台不做这件事：`retrieve()` 只做权限编译与响应回验，
chunk 正文原样返回，改动它就成了平台在替业务组织 prompt）：

```python
payload = await ctx.knowledge.retrieve("pdc", request.query)
context = "\n\n".join(
    f"doc_id: [{c['document_id']}]\ndoc_name: [{name_of(c)}]\n{c['content']}"
    for c in payload["data"]["chunks"]
)
```

`doc_name` 一并给是为答案质量（模型知道这段出自哪份文件，措辞更准），**但别把带权限标签前缀的
原始文件名喂进去**——它会被模型抄进正文。要用就用 `ctx.knowledge.citations(...)` 里那份已剥离的
`document_name`（按 `document_id` 对上即可）。

**2. 系统提示词里约定引用格式**，例如：

```text
凡是使用了知识库检索内容的地方，必须在对应句子末尾以上标标注引用文档的 ID：
格式为 <sup>[doc_id]</sup>，例如 <sup>[1234332012]</sup>。
只在需要解释的长句上标注；短句不必标；同一个 doc_id 标注一两处即可，不要每句都标。
```

> 「只标长句 / 同一 doc_id 标一两处」不是可有可无的客套话：不写这句，模型会满篇打角标，
> 一段话里挂七八个上标，读起来比不标还糟。这套措辞在存量生产应用上已验证，可直接照搬
> （`references/当前Dify入口应用DSL/百富知识库.yml`「引用标注强制规则」）。

**排查**：引用卡片/参考清单都对、就是**一个角标都不出现** → 十有八九是第 1 步漏了（模型压根不知道
doc_id 长什么样）。反过来，角标出现但**前端渲染成暗色不可点** → 该 doc_id 没出现在 citation items 里，
对一下两边用的是不是同一个 `document_id`。

## 事件 `source` 与多层调用

`Event.source` 标记产生事件的模块编码（默认 `"platform"`）。你用便捷构造器时可不管；
经 `ctx.bus.call(...)` 透传子模块事件时，平台会自动打标来源，多层调用下的溯源不丢失。
直接把子模块事件转发即可：`async for ev in ctx.bus.call(ctx, "KNOWLEDGE_QA", sub_req): yield ev`。

> ⚠️ **转发只是 `call` 的一种用法，不是模块间协作的全部**。要的是对方的**数据**而不是对方的
> 回答时，走 `ctx.bus.invoke`（结构化能力调用，非流式）——事件流里的表格按
> [09 呈现规范](09-answer-presentation.md) 是裁剪过的，连接键被砍、只给前 N 条，
> 拿它做跨域关联会静默算错。见 [02 · 结构化能力调用](02-sdk-reference.md)。
