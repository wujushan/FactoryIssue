# 平台反馈：INFO 网页前端把按钮的 `query` 当按钮文字显示，`label` 没有用上

| 项 | 内容 |
|---|---|
| 提出方 | 制程问题查询助手（模块编码 `FACTORY_ISSUE`）业务仓 |
| 日期 | 2026-10-30 |
| 类型 | 前端渲染与事件协议文档不一致（缺陷）。不阻塞上线，影响所有带按钮的回答 |
| 涉及版本 | `paxsz-forge-core` 0.3.7、`paxsz-forge-data` 0.3.2、`paxsz-forge-platform` 0.3.7 |
| 涉及代码 | INFO 网页前端的按钮组件（渲染 `clarify` / `suggestions` 事件的 `recommendations`，以及历史回读时解析 `<intent_routing_clarify>` 数据块，平台代码注释里称 `parseStoredAnswer`）；平台侧只作对照：`forge_core/events.py` 的 `Event.clarify`、`Event.suggestions`、`Event.to_sse`，`forge_platform/gateway/pipeline.py` 的 `render_clarify_answer`、`render_suggestions_answer`，`forge_platform/router.py` 的 `QwenClarifyPlanner`、`_fallback_recommendations`，`forge_platform/suggest.py` 的 `QwenSuggestionPlanner` |
| 验证方式 | INFO 网页前端实际使用中看到的现象；平台下发与落库的数据用本地脚本复现（不连库、不调真模型，脚本与输出见文末）；业务仓把 `query` 改短后发包，在 INFO 网页前端上复核（见「业务仓的临时做法」末条） |
| 期望答复 | 是否按下文方案 1 改 INFO 网页前端（按钮显示 `label`），由哪一方改、预计什么时候上线；改不了的话是否按方案 2 改开发者文档 |

## 一句话

平台下发和落库的按钮数据里，`label`（按钮文字）和 `query`（点了自动发出的消息）是两个字段，开发者文档也这么写；INFO 网页前端却把 `query` 当按钮文字显示，`label` 没有用上，于是按文档把 `query` 写成说全的问句，按钮就成了一长句，真正的选项被挤到句末看不见。

## 业务场景

- 本助手回答制程问题之后给几个「接着问」的按钮（`Event.suggestions`），名称、取值对不上时给可点的选项（`Event.clarify`）。按开发者文档，`label` 写成短的按钮文字（「看原因与措施」「惠州百富」），`query` 写成点了之后能单独发送、能路由回本助手的完整问句（本轮原话加选定的那一项）。
- 开发者在 INFO 网页前端看到：
  - 按钮上显示的是 `query`，例如「这单的 5Why 和库存处理数量是什么（看原因与措施）」。按钮宽度有限，前半句是用户刚问过的话，真正的选项「看原因与措施」在末尾，被截掉看不见。
  - 点了之后发出去的也是这一整句，作为用户的一条新消息出现在对话里。
- 本助手已经把自己能改的按钮改短了（见下文「业务仓的临时做法」），但还有几类按钮必须发说全的问句：模型写的追问（「其他」指什么、现象说得太泛）和缺时间时的追问。这几类点了之后要重新理解问题，问句里必须带着原话。在 INFO 网页前端上，它们仍显示成「按工厂统计一下问题数量（今年）」这样的长句。

## 当前行为

- 开发者文档写的是 `label` 显示、`query` 发送：
  - `docs/dev/02-sdk-reference.md`「事件协议」`recommendations` 的形状：

    > `# label : 按钮文字，宜短（平台自己生成的追问截到 15 字）`
    >
    > `# query : 点击后自动发送的完整消息——要能被路由回你，别写成「这个」「上面那个」`

  - `docs/dev/03-events-and-streaming.md`「澄清引导（clarify）」：

    > `recommendations[*].label` = 按钮文字，`query` = 点击后自动发送的完整消息。

  - 同一文件「追问建议（suggestions）」：

    > `query` 是点击后自动发送的完整消息，要写成**离开上下文也能看懂、能被路由回来**的问法；

- 平台下发与落库的数据里两个字段都在、取值不同（复现输出第 1、2 段）：v2 实时流 `Event.to_sse()` 的 `data.recommendations[*]` 带着 `label` 和 `query`；落库正文 `render_clarify_answer` / `render_suggestions_answer` 投影成 `<intent_routing_clarify>` 数据块，块里同样两个字段都在。所以问题不在平台下发，而在前端取了哪个字段。
- 平台自己生成的按钮同样是 `label` 短、`query` 长（复现输出第 3 段）：
  - 路由澄清（`router.QwenClarifyPlanner`）提示模型「label 不超过 15 字、query 是用户点击后自动发送的完整、明确的问题」，代码把 `label` 截到 15 字；确定性兜底 `_fallback_recommendations` 的 `label` 是模块名称、`query` 是模块的示例问题。
  - 答后建议兜底（`suggest.QwenSuggestionPlanner`，部署侧开关）同样如此。
  - 照 INFO 网页前端现在的显示法，这些按钮上显示的都是长问句；路由澄清的兜底按钮上显示的是示例问题，看不出它代表哪个助手。
- 我们只在 INFO 网页前端上看到了现象，没有它的源码，不确定实时流渲染和刷新后的历史回读两条路是否都这样；请前端两条路都核对。

## 期望

**方案 1（倾向）**：INFO 网页前端的按钮显示 `label`，点了发送 `query`；`label` 为空时退回显示 `query`。实时的 `clarify` / `suggestions` 事件与历史回读的 `<intent_routing_clarify>` 数据块两条路都改。这与开发者文档、平台自己生成按钮的写法一致，模块与平台都不用改。

**方案 2**：前端暂时改不了的话，在 `docs/dev/02`「事件协议」与 `docs/dev/03`「澄清引导」「追问建议」写明：INFO 网页前端把 `query` 当按钮文字显示、点了照发，`query` 宜短。这与 03 里「`query` 要写成离开上下文也能看懂、能被路由回来的问法」相冲突，需要平台给一个取舍；平台自己生成的路由澄清按钮也要跟着改短。

方案 1 改好后，请告知上线时间，我们会在 INFO 网页前端上复核一遍各类按钮。

## 影响范围

- 所有发 `clarify` / `suggestions` 的模块：按文档把 `query` 写全，按钮就显示成长句、选项被截掉；点了之后用户自己的那条消息也是一长句。
- 平台自己的路由澄清按钮（多个助手都可能答时出现）、答后建议兜底（开启时）。
- 历史回读：刷新后从落库正文里的 `<intent_routing_clarify>` 还原按钮，如果这条路同样取 `query`，刷新前后都是长句。

## 业务仓的临时做法（前端改好前，改好后也保留）

- 答后按钮的 `query` 改成短的、动作在前的说法，不再拼本轮原话：「按问题类型统计这些单」「把这些单全部导出」「列出惠州百富的单」「ZC2610001 的原因与措施」「换个理解：按 A920 系列查」。接的是哪一问由本助手从会话历史和上一轮的执行记录里看出来；这类短问句点了之后依赖平台路由的「上一轮路由过谁就粘回谁」回到本助手。
- 本助手代码给的追问（名称对上多个、取值对不上、认不出的号、时间说法认不出），按钮的 `query` 就是选项本身（「惠州百富」「是」「订单号」「近 30 天」）。问句全文存在会话工作区里，点了之后直接把选项填回上一轮的计划，不重新理解问题；会话工作区写不进去时退回发问句全文。
- 模型写的追问、缺时间的追问仍发问句全文（原因见「业务场景」最后一条），在前端改好前会显示成长句。
- 本助手的按钮 `label` 一直按文档写（不超过 15 字）。前端改好后，上面几条改短的 `query` 也不恢复：点了之后它就是用户那条消息，短的看着更自然。
- 2026-10-30 发包后在 INFO 网页前端上复核：改短后的按钮显示正常。这只说明临时做法有效，前端仍需按「期望」改：仍发问句全文的那几类按钮不受临时做法影响。

## 复现

不连库、不调真模型：模块发的按钮直接构造事件；平台的两个规划器用假模型喂一份照平台提示写的回复。导入 `forge_platform` 需要 `greenlet`（见 2026-10-28 的另一份反馈「业务仓 `uv sync` 之后 `uv run forge dev serve` 起不来」），所以用 `uv run --with greenlet python repro_button_label.py` 执行。

```python
"""复现：按钮的 label（按钮文字）与 query（点了自动发出的消息）在平台下发、落库的数据里是两个不同的字段，
模块自己发的（suggestions / clarify）和平台自己生成的（路由澄清兜底、答后建议兜底）都是如此。
INFO 网页前端拿 query 当按钮文字显示。不连库、不调真模型（平台的两个规划器用假模型喂一份固定回复）。"""

import asyncio
import importlib.metadata as md
import json

from forge_core.events import Event
from forge_core.module import ModuleManifest
from forge_platform.gateway.pipeline import render_clarify_answer, render_suggestions_answer
from forge_platform.router import QwenClarifyPlanner, _fallback_recommendations
from forge_platform.suggest import QwenSuggestionPlanner

for pkg in ("paxsz-forge-core", "paxsz-forge-data", "paxsz-forge-platform"):
    print(f"{pkg}=={md.version(pkg)}")


def show(title: str, recs: list[dict]) -> None:
    print(f"\n== {title}")
    for r in recs:
        print(f"label={r['label']!r:<24} query={r['query']!r}")


# 1. 模块发的答后建议（docs/dev/03「追问建议」：label = 按钮文字，query = 点击后自动发送的完整消息）
recs = [
    {"id": "1", "name": "接着问", "label": "看原因与措施", "query": "这单的 5Why 和库存处理数量是什么（看原因与措施）"},
    {"id": "2", "name": "接着问", "label": "看完整处理过程", "query": "这单的 5Why 和库存处理数量是什么（看完整处理过程）"},
]
ev = Event.suggestions(recs, guide_text="您还可以继续问：")
show("模块发的 suggestions", ev.data["recommendations"])
print("v2 实时流（Event.to_sse）：")
print(ev.to_sse().strip())
print("落库正文（render_suggestions_answer）：")
print(render_suggestions_answer(ev.data))

# 2. 模块发的追问（docs/dev/03「澄清引导」同一形状）
ev = Event.clarify("「惠州工厂」对上了两家，查哪一家？", ["惠州百富", "惠州二厂"], recommendations=[
    {"id": "1", "name": "名称对上多个", "label": "惠州百富", "query": "上个月惠州工厂的问题有哪些（惠州百富）"},
    {"id": "2", "name": "名称对上多个", "label": "惠州二厂", "query": "上个月惠州工厂的问题有哪些（惠州二厂）"},
])
show("模块发的 clarify", ev.data["recommendations"])
print("落库正文（render_clarify_answer）：")
print(render_clarify_answer(ev.data))

# 3. 平台自己生成的按钮
manifest = ModuleManifest(code="FACTORY_ISSUE", name="制程问题查询助手", description="查制程质量问题",
                          intents=["上个月惠州工厂的问题有哪些"])
show("平台路由澄清的确定性兜底（router._fallback_recommendations）", _fallback_recommendations([manifest]))


class FakeLLM:
    """按平台提示要的 JSON 回一份固定内容（模型照提示把 label 写短、query 写完整）。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def chat(self, messages, **_kw):
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


async def main() -> None:
    long_query = "请列出上个月惠州百富工厂建单、还没有结案的制程问题单"
    _guide, got = await QwenClarifyPlanner(FakeLLM({"guide_text": "您想查哪一类？", "recommendations": [
        {"id": "rec_1", "name": "制程问题查询助手", "label": "查惠州百富未结案的单", "query": long_query}]})
    ).plan("惠州的问题", [manifest])
    show("平台路由澄清（router.QwenClarifyPlanner，label 截到 15 字）", got)
    ev = await QwenSuggestionPlanner(FakeLLM({"guide_text": "您可能还想了解：", "suggestions": [
        {"label": "看惠州百富未结案的单", "query": long_query}]})).plan("惠州的问题", "共 4 张。", [manifest])
    show("平台答后建议兜底（suggest.QwenSuggestionPlanner）", ev.data["recommendations"])


asyncio.run(main())
```

实际输出（2026-10-30）：

```text
paxsz-forge-core==0.3.7
paxsz-forge-data==0.3.2
paxsz-forge-platform==0.3.7

== 模块发的 suggestions
label='看原因与措施'                 query='这单的 5Why 和库存处理数量是什么（看原因与措施）'
label='看完整处理过程'                query='这单的 5Why 和库存处理数量是什么（看完整处理过程）'
v2 实时流（Event.to_sse）：
event: suggestions
data: {"type":"suggestions","source":"platform","ts":1793365120.8014183,"data":{"guide_text":"您还可以继续问：","recommendations":[{"id":"1","name":"接着问","label":"看原因与措施","query":"这单的 5Why 和库存处理数量是什么（看原因与措施）"},{"id":"2","name":"接着问","label":"看完整处理过程","query":"这单的 5Why 和库存处理数量是什么（看完整处理过程）"}]}}
落库正文（render_suggestions_answer）：
<intent_routing_clarify>
{"guide_text": "您还可以继续问：", "recommendations": [{"id": "1", "name": "接着问", "label": "看原因与措施", "query": "这单的 5Why 和库存处理数量是什么（看原因与措施）"}, {"id": "2", "name": "接着问", "label": "看完整处理过程", "query": "这单的 5Why 和库存处理数量是什么（看完整处理过程）"}]}
</intent_routing_clarify>

== 模块发的 clarify
label='惠州百富'                   query='上个月惠州工厂的问题有哪些（惠州百富）'
label='惠州二厂'                   query='上个月惠州工厂的问题有哪些（惠州二厂）'
落库正文（render_clarify_answer）：
<intent_routing_clarify>
{"guide_text": "「惠州工厂」对上了两家，查哪一家？", "recommendations": [{"id": "1", "name": "名称对上多个", "label": "惠州百富", "query": "上个月惠州工厂的问题有哪些（惠州百富）"}, {"id": "2", "name": "名称对上多个", "label": "惠州二厂", "query": "上个月惠州工厂的问题有哪些（惠州二厂）"}]}
</intent_routing_clarify>

== 平台路由澄清的确定性兜底（router._fallback_recommendations）
label='制程问题查询助手'               query='上个月惠州工厂的问题有哪些'

== 平台路由澄清（router.QwenClarifyPlanner，label 截到 15 字）
label='查惠州百富未结案的单'             query='请列出上个月惠州百富工厂建单、还没有结案的制程问题单'

== 平台答后建议兜底（suggest.QwenSuggestionPlanner）
label='看惠州百富未结案的单'             query='请列出上个月惠州百富工厂建单、还没有结案的制程问题单'
```

每一段里 `label` 都是短的按钮文字、`query` 是长问句。INFO 网页前端上显示的是右边一列。
