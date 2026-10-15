# tests/contracts —— 被调方的能力签名快照 + 本地桩数据

只有**调用别的模块的能力**（`manifest.capability_deps` 非空）时这个目录才有内容；用不到就让它空着
（留着这份 README 即可）。完整说明见 `docs/dev/02-sdk-reference.md`「测试模式」与
`docs/dev/06-cli-reference.md` 的 `capabilities` / `dev serve` 两节。

```text
tests/contracts/
  <被调方编码>.json                          ← 签名快照：forge capabilities pull 生成，提交入库，别手改
  fixtures/
    <被调方编码>.<能力名>.v<版本>.json        ← 本地桩的数据：你自己写，提交入库
```

## `<被调方编码>.json`：签名快照

- **由命令生成**：`uv run forge capabilities pull`（按你的 `capability_deps` 从平台拉，每个被调方一个
  文件，只含你引用到的能力）。对方还没装配上平台时，请对方在他的仓里 `uv run forge capabilities export`
  给你一份。
- **提交入库**：它是「我依赖的契约长什么样」的书面记录。对方改了签名，diff 里就看得到；CI 的
  `contracts-check` 用 `pull --check` 查漂移（签名变了即失败）。
- **别手改**：每个能力带签名指纹，手改过签名的快照读不进来（契约测试、本地桩、CI 一律报错）。
  签名变了就重新 `pull`，先改你的代码跟上，再连同快照一起提交（输出会标明是兼容变更——只新增了
  返回列 / 可选参数，代码不用改——还是破坏性变更）。
- 契约测试 `tests/test_contracts.py` 的 `ContractBus` 读的就是这里。

## `fixtures/`：本地桩的数据

`uv run forge dev serve --capability-stubs tests/contracts` 会为每个快照注册一个**本地桩**（Console
模块页显示「本地桩」）：你的模块在本地调 `ctx.bus.invoke(...)` 时，桩按快照校验实参、回放这里的数据，
不用把对方的 wheel 装进来。

文件名 `<被调方编码>.<能力名>.v<版本>.json`，内容是一个 JSON 对象，键全部可省：

```json
{
  "rows": [{"part_no": "P1", "qty": 3}],
  "notes": "其中 1 个是替代料，PMC 口径不计入缺料",
  "as_of": "2026-09-21",
  "truncated": false,
  "total": 1
}
```

| 键 | 含义 |
|---|---|
| `rows` | 返回的行集。**必须合对方签名**：少一列、类型不对，调用时就是 `CAPABILITY_RESULT_INVALID`（与线上同一道校验） |
| `columns` | 实际返回列的声明。不给即按快照的返回列填——通常不用写 |
| `notes` / `as_of` / `truncated` / `total` / `citations` | 与 `CapabilityResult` 同名字段 |

- 没有 fixture 的能力返回**带列声明的空行集**（顺便测你的「查无数据」分支）。
- fixture **每次被调到时现读**，改了数据不用重启；启动时会逐个体检并提示不合签名、对不上任何能力的文件。
- 数据是静态的：不管实参是什么都返回同一份。要按实参变化的数据，写在契约测试里（`bus.stub(..., handler=...)`）。
- 键与 `ContractBus.stub()` 的参数同名，契约测试里可以直接复用：
  `bus.stub("<编码>", "<能力名>", **json.loads(path.read_text(encoding="utf-8")))`。
- 这里的数据是**你编的样例**，别从生产库导真实数据进来——它会被提交入库。
