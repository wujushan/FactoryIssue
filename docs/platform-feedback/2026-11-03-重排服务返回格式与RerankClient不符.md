# 平台反馈：测试环境的重排服务返回 SGLang 格式，`RerankClient` 解析失败，重排每次都静默退回向量顺序

| 项 | 内容 |
|---|---|
| 提出方 | 制程问题查询助手（模块编码 `FACTORY_ISSUE`）业务仓 |
| 日期 | 2026-11-03 |
| 类型 | SDK 与部署不匹配（缺陷）。不报错、用户看不出来，但语义检索的重排完全失效 |
| 涉及版本 | `paxsz-forge-core` 0.3.7、`paxsz-forge-data` 0.3.2 |
| 涉及代码 | `forge_core/llm.py`：`RerankClient.rerank`；`forge_data/retrieval/rerank.py`：`rerank_candidates`；`forge_data/retrieval/pipeline.py`：`retrieve` |
| 验证方式 | 测试环境平台日志 + 开发者在测试环境 curl 重排服务；本机脚本回放该响应（不连任何服务），脚本与输出见文末 |
| 期望答复 | 采用下文哪个方案、预计版本；顺带确认文末「顺带确认」两点 |

## 一句话

测试环境 `FORGE_RERANKER_BASE_URL` 指向的重排服务按 SGLang 的格式返回一个**裸数组**，分数键叫 `score`；`RerankClient.rerank` 按 `resp.json()["results"]` 读、分数键按 `relevance_score` 读，于是每次都抛 `TypeError`，`rerank_candidates` 捕获后退回向量顺序，所有命中的 `rerank_score` 都是 `None`。

## 业务场景

本模块用 `ctx.retrieval.search(...)` 按意思找制程问题单：用户描述一个缺陷现象（「有没有出现过开机花屏，当时怎么处理的」），模块在国内、巴西、海外三张向量表里各检索一次，每域取最相近的 10 张列给用户，排序按 `rerank_score`。另有一类查询（「有没有涉及非接的问题」）把按意思找到的候选按 `rerank_score` 排好，再交本地大模型逐张判断。

手工测试时，这类回答混进很多明显不相近的单。为了按重排分定一个去噪门槛，模块在日志里记下了每张候选的重排分与向量分，结果重排分全是 `None`。

## 当前行为

1. 测试环境平台日志，每次检索都有一条（2026-11-03 摘录，去掉了与本问题无关的字段）：

   ```text
   [warning  ] rerank_fallback  component=gateway module=FACTORY_ISSUE error='TypeError: list indices must be integers or slices, not str'
   ```

   同一请求里模块记下的 50 张候选，重排分全为 `None`，向量分在 0.80 到 0.60 之间。

2. 开发者用测试环境的 `FORGE_RERANKER_BASE_URL` 拼上 `/rerank` 实测（请求体与 `RerankClient` 发的一致，文字是编的）：

   ```bash
   curl -X POST '<FORGE_RERANKER_BASE_URL>/rerank' -H 'Content-Type: application/json' -H 'Authorization: Bearer <key>' \
     -d '{"model":"Qwen3-Reranker-8B","query":"开机花屏","documents":["开机后屏幕花屏","外壳划伤"],"top_n":2}'
   ```

   返回：

   ```json
   [{"score":0.8080672135527632,"document":"开机后屏幕花屏","index":0,"meta_info":null},
    {"score":0.02442309005410721,"document":"外壳划伤","index":1,"meta_info":null}]
   ```

   这正是 [SGLang 文档「Rerank models」](https://lmsysorg.mintlify.app/docs/supported-models/rerank_models)写的 `/v1/rerank` 响应格式（内容经转述）：返回按分数降序的对象列表，每项有 `score`、`document`（`return_documents` 为真时才带，缺省为真）、`index`、`meta_info`。

3. `RerankClient.rerank` 的解析（0.3.7）：

   ```python
   results = resp.json()["results"]
   return [(r["index"], r["relevance_score"]) for r in results]
   ```

   对一个 list 取 `["results"]` 就是日志里的 `TypeError: list indices must be integers or slices, not str`。即使服务包了一层 `results`，分数键 `score` 也对不上 `relevance_score`（会变成 `KeyError`）。

4. `rerank_candidates` 捕获异常、记 `rerank_fallback`、返回入参（向量）顺序，`on_score` 不调用，`VectorHit.rerank_score` 保持 `None`。这本是为「重排服务偶尔挂掉」设计的兜底；格式不匹配时它每次都触发，表现成一个看不见的永久降级。

同一环境里另一台重排服务（infinity，`bge-reranker-v2-m3`）返回 `{"object":"rerank","results":[{"relevance_score":…,"index":…}]}`，与 `RerankClient` 期望一致，说明 `RerankClient` 的格式只覆盖了一部分常见实现。

## 影响范围

- 测试环境上所有经 `ctx.retrieval` 的检索都只有向量近邻、没有重排，`rerank_score` 恒为 `None`。依赖它的地方全部失效：按重排分排序、跨表按重排分合并（`VectorHit` 文档写明向量分跨表不可比）、模块按重排分设的阈值。
- 重排请求照常发出、服务照常打分，结果被丢掉：每次检索多花一次重排的耗时，换不来任何效果。
- 用户看不到报错，回答也不出错，只是排序变差，很难从回答上发现。本模块是因为特意记了分数才看出来。
- 正式环境若与测试环境部署方式相同，会有同样的问题。

## 期望

**方案 1（倾向）**：`RerankClient.rerank` 两种格式都认。

- 响应是对象：取 `results`，分数取 `relevance_score`（现有行为）。
- 响应是数组：直接当结果列表，分数取 `score`。
- 每项都按 `index` 对回入参；两个键都没有时照旧抛错，由 `rerank_candidates` 兜底。
- 请求体加 `"return_documents": false`：SGLang 缺省把每段文档原样回传，一次检索最多 200 段，纯属多余流量。其他实现多半忽略这个键，请平台确认部署的那几种都不因多一个键报错。

**方案 2**：部署侧改，让 `FORGE_RERANKER_BASE_URL` 指向返回 `results` 格式的服务，或在 SGLang 前加一层转换。SDK 不动，但以后换推理框架还会再撞一次。

另建议（不论选哪个方案）：格式不匹配是**每次都会失败**的配置错误，不该只在每次请求时各记一条 warning。可以在启动期能力检查里对重排服务发一次探测请求，解析失败就在能力报告里标出来，与「没配 `FORGE_RERANKER_BASE_URL`」一样显眼。

修好后请告知版本号，业务仓抬依赖下界并 `uv sync`。

## 业务仓的临时做法（平台修好前）

- 不在模块里自己解析重排响应：`ctx.retrieval` 是平台注入的句柄，模块绕开它就绕开了权限下推与审计。
- 模块已按 `rerank_score` 为 `None` 时退回向量分排序，回答不出错，只是排序是向量顺序。
- 按重排分定去噪门槛的测量暂停，等重排修好后再测。

## 顺带确认

1. **Qwen3-Reranker 的模板**：本业务仓 2026-10-20 的反馈「语义检索查询侧缺少任务说明」问过重排服务是否套用了 Qwen3-Reranker 的模板。按上面的 SGLang 文档，部署 Qwen3-Reranker 时必须带 `--chat-template examples/chat_template/qwen3_reranker.jinja`，否则 `/v1/rerank` 直接返回 400；测试环境的服务能正常打分（相关的 0.81、不相关的 0.02），看起来是带了。请平台确认测试、正式两个环境都是这样部署的。
2. **查询侧任务说明**：同一份 SGLang 文档写明 Qwen3-Reranker 的 `/v1/rerank` 接受可选的 `instruct` 字段。那份反馈要的「重排查询侧带任务说明」在这个部署上有现成的入口，方案 1 改 `RerankClient` 时可一并考虑是否开放这个参数。

## 复现

在业务仓里执行 `uv run python repro_rerank_sglang.py`（不连任何服务；用 `httpx.MockTransport` 按两种格式回放响应，打分取上面 curl 的实测值）：

```python
"""复现：重排服务按 SGLang 的 /v1/rerank 格式返回（裸数组、分数键 score），RerankClient 解析失败，
检索静默退回向量顺序、rerank_score 全为 None。不连任何服务：用 httpx.MockTransport 按两种格式回放响应。"""

import asyncio
import importlib.metadata as md
import json

import httpx
from structlog.testing import capture_logs

from forge_core.llm import RerankClient
from forge_data.retrieval.index import VectorHit
from forge_data.retrieval.pipeline import retrieve

# 打分照测试环境 curl 实测（2026-11-03，query「开机花屏」）：「开机后屏幕花屏」0.808，「外壳划伤」0.024
SCORES = {"开机后屏幕花屏": 0.8080672135527632, "外壳划伤": 0.02442309005410721}


def sglang_body(docs):
    """测试环境重排服务的返回形状：裸数组，按分数降序，键为 score/document/index/meta_info。"""
    rows = [{"score": SCORES[d], "document": d, "index": i, "meta_info": None} for i, d in enumerate(docs)]
    return sorted(rows, key=lambda r: -r["score"])


def results_body(docs):
    """RerankClient 期望的形状：{"results": [{"index", "relevance_score"}]}。"""
    rows = [{"index": i, "relevance_score": SCORES[d]} for i, d in enumerate(docs)]
    return {"results": sorted(rows, key=lambda r: -r["relevance_score"])}


_original_init = httpx.AsyncClient.__init__


def use(make_body):
    def handler(req):
        return httpx.Response(200, json=make_body(json.loads(req.content)["documents"]))

    def patched(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        _original_init(self, *a, **kw)

    httpx.AsyncClient.__init__ = patched


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.0] * 4 for _ in texts]


class FakeIndex:
    """向量近邻把不相关的「外壳划伤」排在前面（向量分 0.71 对 0.70），正是要靠重排纠正的情形。"""

    def search(self, embedding, top_k, **kw):
        return [VectorHit(id="1", text="外壳划伤", score=0.71), VectorHit(id="2", text="开机后屏幕花屏", score=0.70)]


async def main():
    for pkg in ("paxsz-forge-core", "paxsz-forge-data"):
        print(f"{pkg}=={md.version(pkg)}")
    client = RerankClient("http://rerank.invalid/v1", "Qwen3-Reranker-8B")
    for name, make in (("SGLang 格式（测试环境实际返回）", sglang_body), ("results 格式（SDK 期望）", results_body)):
        use(make)
        print(f"\n== {name}")
        print("响应体:", json.dumps(make(["开机后屏幕花屏", "外壳划伤"]), ensure_ascii=False))
        try:
            print("RerankClient.rerank:", await client.rerank("开机花屏", ["开机后屏幕花屏", "外壳划伤"], top_n=2))
        except Exception as exc:  # noqa: BLE001
            print("RerankClient.rerank:", f"{type(exc).__name__}: {exc}")
        with capture_logs() as logs:
            hits = await retrieve("开机花屏", embedder=FakeEmbedder(), index=FakeIndex(), reranker=client, top_n=2)
        print("retrieve 结果 (文字, 向量分, 重排分):", [(h.text, h.score, h.rerank_score) for h in hits])
        print("日志:", [(x["event"], x.get("error")) for x in logs])
    httpx.AsyncClient.__init__ = _original_init


asyncio.run(main())
```

实际输出（2026-11-03）：

```text
paxsz-forge-core==0.3.7
paxsz-forge-data==0.3.2

== SGLang 格式（测试环境实际返回）
响应体: [{"score": 0.8080672135527632, "document": "开机后屏幕花屏", "index": 0, "meta_info": null}, {"score": 0.02442309005410721, "document": "外壳划伤", "index": 1, "meta_info": null}]
RerankClient.rerank: TypeError: list indices must be integers or slices, not str
retrieve 结果 (文字, 向量分, 重排分): [('外壳划伤', 0.71, None), ('开机后屏幕花屏', 0.7, None)]
日志: [('rerank_fallback', 'TypeError: list indices must be integers or slices, not str')]

== results 格式（SDK 期望）
响应体: {"results": [{"index": 0, "relevance_score": 0.8080672135527632}, {"index": 1, "relevance_score": 0.02442309005410721}]}
RerankClient.rerank: [(0, 0.8080672135527632), (1, 0.02442309005410721)]
retrieve 结果 (文字, 向量分, 重排分): [('开机后屏幕花屏', 0.7, 0.8080672135527632), ('外壳划伤', 0.71, 0.02442309005410721)]
日志: []
```

第一段与测试环境日志里的报错一字不差：不相关的「外壳划伤」因为向量分高 0.01 排在前面，重排分为空。第二段是同样的打分换成 `results` 格式，重排把相关的那段排到了第一。
