# 平台反馈：`/test/chat` 的 `query` 非空校验挡掉任务面模块的「空输入」回归用例

| 项 | 内容 |
|---|---|
| 提出方 | 制程问题查询助手（模块编码 `FACTORY_ISSUE`）业务仓 |
| 日期 | 2026-11-11 |
| 类型 | 测试通道行为与任务面模块需求不一致。不阻塞业务开发，有临时做法（用例标 skip + 单测兜底） |
| 涉及版本 | `paxsz-forge-platform` 0.3.9 |
| 涉及代码 | `forge_platform/gateway/qa_api.py` 的 `TestChatRequest.query: str = Field(min_length=1)`（第 109 行） |
| 验证方式 | dev 平台 `dataforge-dev.paxsz.com` 实测，复现脚本与输出见文末 |
| 期望答复 | 是否按下文方案 1 放宽任务面场景的 `query` 校验，以及预计版本 |

## 一句话

`/test/chat` 把 `query` 当「用户问题原文」做了 `min_length=1` 校验。但文档 §3.1 又指定**任务式模块**用 `/test/chat` + `ext_param.task` 来回归，此时 `query` 的语义是任务自己的入参——本仓润色任务的 `query` 是「被润色的原文」，可以为空（空原文应走模块的 `POLISH_EMPTY` 分支）。空串请求在入口就被 422 掉，模块逻辑够不到，「空输入」这条报错路径在 `/test/chat` 通道无法覆盖。

## 业务场景

- 本仓 `FACTORY_ISSUE` 声明了一个任务面任务 `domestic_polish`（`manifest.tasks`，走 `POST /v2/tasks`，业务页面「某栏旁的【AI润色】」调用）。它的 `query` 是**被润色的那一栏原文**，业务上允许为空（用户没填内容就点润色），模块对空原文返回 `POLISH_EMPTY`（错误码 + fatal，提示「请先填写内容再润色」）。
- 回归要覆盖这条报错路径，用例 `docs/testcases/polish/cases.json` 的 PL-26 就是一条 `query: ""`、预期 `error_code: POLISH_EMPTY` 的用例。
- 按 `docs/dev/10-automated-testing.md` §3.1 的口径，任务式模块的用例靠 `/test/chat` 带 `ext_param` 来跑（「任务式模块的用例靠它」），平台没有单独的 `/test/tasks` 端点。

## 当前行为

- `POST /test/chat` 的 `TestChatRequest.query` 声明为 `str = Field(min_length=1)`（`qa_api.py:109`）。
- 发 `query: ""` 的请求，FastAPI/Pydantic 在路由前就返回 HTTP 422，detail 是 `string_too_short`（`loc: ["body","query"]`），**根本没进到模块的 `handle()`**。
- 于是 PL-26 在 `qa_test.py`（走 `/test/chat`）里恒失败，而模块侧空 query 逻辑本身正确（本机 `forge dev serve` 走 `/v2/tasks` 实测，空原文返回 `POLISH_EMPTY`、进度正常、日志 `outcome` 记错）。

## 期望

**方案 1（倾向）**：`/test/chat` 在请求**带了 `ext_param.task`**（即任务面调用）时，放宽 `query` 的非空校验，允许空串透传给模块。理由：此时 `query` 不是「用户问题原文」而是任务入参，非空与否该由模块自己判（本仓模块对空原文有明确的 `POLISH_EMPTY` 分支）。不带 `ext_param.task` 的普通问答仍保留 `min_length=1`（空问题走 `is_blank` 答「没看懂」，那是现有行为）。

**方案 2**：新增一个任务面专用测试端点（如 `POST /test/tasks`），`query` 不做强非空校验、只透传 `ext_param`，供任务面模块回归。`/test/chat` 维持现状。

**方案 3**：若平台认为 `query` 就该恒非空，请在 `10-automated-testing.md` §3.1 写明「`/test/chat` 不能测空 `query`」，并说明任务面「空输入」类用例该走哪条通道，免得每个任务面模块都在这卡一下。

## 影响范围

- 所有「任务入参可以为空」的任务式模块回归：空输入类报错用例在 `/test/chat` 通道无法覆盖，只能靠单测（`tests/` 内）或手工 `POST /v2/tasks` 补。
- 本仓当前只有 PL-26 一条受影响，已标 `skip` 临时跳过（见「业务仓的临时做法」），逻辑由单测 `tests/test_polish_run.py::test_empty_and_too_long_do_not_call_the_model` 的真空串断言兜底。

## 业务仓的临时做法（平台答复前）

- `docs/testcases/polish/cases.json` 的 PL-26 加 `skip` 字段（一句话原因 + 日期），`qa_test.py` 现有机制会把它单列、不算失败。
- 单测补一条真空串 `""` → `POLISH_EMPTY` 的断言（`test_empty_and_too_long_do_not_call_the_model` 的参数化里加 `("", POLISH_EMPTY_CODE)`），让回归跳过的那条逻辑仍有覆盖。
- 平台放宽 `/test/chat` 空 `query` 校验后，去掉 PL-26 的 `skip` 字段再跑。

## 复现

在装配了本模块的平台上（dev：`dataforge-dev.paxsz.com`，用 key 授权的 `FACTORY_ISSUE`）执行：

```python
import httpx, os

client = httpx.Client(
    base_url="https://dataforge-dev.paxsz.com",
    headers={"Authorization": f"Bearer {os.environ['FORGE_TEST_API_KEY']}"},
    timeout=60,
)
payload = {
    "query": "",  # 空原文
    "target": "FACTORY_ISSUE",
    "ext_param": {"task": "domestic_polish", "field": "problem_desc"},
}
resp = client.post("/test/chat", json=payload)
print(resp.status_code)
print(resp.json())
```

实际输出（2026-11-11）：

```text
422
{'detail': [{'type': 'string_too_short', 'loc': ['body', 'query'],
             'msg': 'String should have at least 1 character',
             'input': '', 'ctx': {'min_length': 1}}]}
```

对照：把 `query` 换成非空但内容为空的 `<p>&nbsp;</p>`，同一条用例返回 HTTP 200、`error.code = POLISH_EMPTY`（模块逻辑正确，只是空串这条够不到）。模块侧真空串 `""` 的 `POLISH_EMPTY` 行为另见单测 `tests/test_polish_run.py::test_empty_and_too_long_do_not_call_the_model`。
