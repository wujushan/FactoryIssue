# docs/testcases —— 测试案例集（G3 产物，自动 + 手动双产物）

当前进度（2026-10-26）：种子里能进 golden 的 109 条已写成断言和参考 SQL。权限 5 条只在人工手册。多轮案例用 `turns`，断言看最后一轮。

| 路径 | 内容 |
|---|---|
| `golden/cases.json` | 109 条自动化断言。数据用例都带 `target` |
| `golden/sql/` | 同编号的参考 SQL。只读、按口径写，不写死行数 |
| `golden/cases.example.json` | 脚手架样例，不要覆盖 `cases.json` |
| `manual/首批.md` | 首批 33 条 |
| `manual/其余.md` | 其余 76 条，以及权限 5 条 |
| `seed/` | G3 之前的输入，不是本目录的验收产物 |

流程：开发者提供**种子测试问题集** → 编程助手基于 docs/2_landed 扩展完善 →
每条案例附**参考 SQL**。本模块不把调用次数、事件顺序写成验收标准。

两份产物：

1. **自动化 golden 评测集**（`golden/`）：CI 回归用（确定性断言 + 本地 LLM judge）。
2. **人工测试手册**（`manual/`）：人工验收时在 Admin Console debug chat 的 trace 视图中，
   对照实际取数条件和结果集是否与参考 SQL、口径一致。

案例格式建议：问题、预期路由/意图、参考 SQL（参数化）、预期数字口径、**预期呈现**、备注。

**「预期呈现」写什么**（对应 `docs/dev/09-answer-presentation.md` 的三条，人工验收/golden 断言都用它）：
预期出现的**列名**（业务名，如「项目编号/延期天数」）、**不该出现的串**（表名、字段名如
`prj_dly_days`、数据源别名、自增 ID 列）、以及**数据之外该给的分析**（总量/分档/Top N/结论）。
这三样都能写成确定性断言（字符串在不在正文/列名里），不必依赖 judge。

---

## golden/ 怎么跑起来

`golden/` 的用例集由 `scripts/qa_test.py` 驱动，经平台 `/test` 通道在**接了真实测试数据的
环境**上全量回归。完整协议、api-key 申请、断言原则见 **`docs/dev/10-automated-testing.md`**。

```bash
export FORGE_TEST_BASE_URL=http://<平台测试机>:8090
export FORGE_TEST_API_KEY=fdt_xxxxxxxx.yyyyyyyy   # 平台管理员在 Admin Console「测试」页签发
uv run python scripts/qa_test.py docs/testcases/golden/cases.json

# 失败时对着那一条单独重跑，带上 SQL/LLM 明细
uv run python scripts/qa_test.py docs/testcases/golden/cases.json --only <用例id> --trace
```

起步：把 `golden/cases.example.json` 复制成 `cases.json` 按业务改写。

三条最容易踩的（详见 `docs/dev/10` §4）：

- **断言锚在结构化产物**（`tables` / `charts` / `module`），**别锚在 LLM 的措辞上**——
  正文每次都不一样，锚在它上面的用例迟早会红，而且是没有意义的红。
- **数据用例一律带 `target`**，路由另写用例。混在一起时，一条失败你要先分辨是哪一种失败。
- **预期按口径写、不按快照写**：列构成/非空/排序/区间/「合计=分项之和」都稳；
  硬编某天的行数不稳（测试库数据会变）。

> ⚠️ 测试通道是**权限绿灯**（跳过 INFO 授权、无行/列过滤），故预期值按「全量可见」写，
> 别拿生产上某个人看到的结果当预期。权限本身不在业务仓这条线上验证。
