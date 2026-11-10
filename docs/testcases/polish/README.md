# AI 润色样例

`cases.json` 是 AI 润色的合成样例（决策 2026-11-09「AI 润色技术设计」§12.2，open-questions D53），34 条（`p2`）：27 条要调模型，7 条不调模型就该报错（空原文、只有图片、超长、参数错误、图片占满字数上限）。

- **全部是编写的内容**：单号用不存在的 99 年号，图片与链接用保留域名 `info.example.invalid`，人名、机型都是编的。不往里放真实单据的内容；真实单据的效果由业务方在测试环境试用（D53）。
- **现在**：内网实测 `scripts/polish_spike/` 用它（见那里的 README）。
- **G4b 之后**：`scripts/qa_test.py` 补上 `ext_param`、`q_pad` 与三个新断言后，在测试环境跑 `uv run python scripts/qa_test.py docs/testcases/polish/cases.json`。它与 G3 的 116 条 golden 分开，不进 `golden/`。
- 改了样例就把 `version` 递增（`p1` → `p2`），实测汇总会记下用的是哪一版。
