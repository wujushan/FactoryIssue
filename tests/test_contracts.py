"""模块间能力调用（`ctx.bus.invoke`）的契约测试。写法详见 docs/dev/02「测试模式」。

本模块既不调用别的模块的能力、也不对外提供能力时（`manifest.capability_deps` 与
`manifest.capabilities` 都为空），本文件的用例全部 skip，什么都不用改。用上了再回来看：

- **调用方**（`capability_deps` 非空）：被调方的签名快照放在 `tests/contracts/<被调方编码>.json`，
  用 `uv run forge capabilities pull` 从平台拉取、**提交入库**（目录约定见 tests/contracts/README.md）。
  `ContractBus` 是按快照校验的假 bus：实参不合对方签名、你挂的桩数据不合对方签名，都在这里就报。
  本地起平台端到端调试时，被调方用桩顶上：`uv run forge dev serve --capability-stubs tests/contracts`；
- **被调方**（`capabilities` 非空）：`assert_capability` 按你自己的签名走一遍「校实参 → invoke() →
  校返回」——返回少一列、类型不对在自己仓里就炸，而不是在调用方的沙箱里 KeyError。

`test_example_*` 是写法示例：把尖括号占位换成你的编码 / 能力名 / 实参 / 断言，再删掉 skip 那一行。
"""

from pathlib import Path

import pytest
from forge_core.module import ForgeModule, ModuleContext, ModuleRequest, UserContext
from forge_core.permissions.agentnode import AgentNode
from forge_core.testing import ContractBus, assert_capability

from factory_issue_module.module import MODULE_CODE, FactoryIssueModule

#: 被调方签名快照的目录（`forge capabilities pull` 的缺省 --out）
CONTRACTS = Path(__file__).parent / "contracts"
MANIFEST = FactoryIssueModule.manifest
EXAMPLE = "写法示例：换成你的业务后删掉这个 skip"

calls_capabilities = pytest.mark.skipif(
    not MANIFEST.capability_deps, reason="本模块没有声明 capability_deps（不调用别的模块的能力）"
)
provides_capabilities = pytest.mark.skipif(
    not MANIFEST.capabilities, reason="本模块没有声明 capabilities（不对外提供能力）"
)


# ── 调用方：ContractBus ─────────────────────────────────────────────────────────


@calls_capabilities
def test_every_capability_dep_has_a_snapshot():
    """声明了能力依赖却没有对方的签名快照 = 漏跑了 `uv run forge capabilities pull`（或拉了没提交）。"""
    bus = ContractBus(FactoryIssueModule(), CONTRACTS)
    assert bus.missing_contracts() == []


@calls_capabilities
@pytest.mark.skip(reason=EXAMPLE)
async def test_example_invokes_the_capability_with_valid_arguments():
    module = FactoryIssueModule()
    bus = ContractBus(module, CONTRACTS)
    # 挂桩：rows 按对方签名的返回列写（不给 columns 即按快照填）。编的数据不合对方签名
    # （少一列、类型不对）同样报 CapabilityResultInvalid——那正是上线后会炸的地方。
    # tests/contracts/fixtures/ 里给本地桩写的数据也能直接复用：bus.stub(..., **json.loads(文件内容))
    bus.stub(
        "<被调方编码>", "<能力名>",
        rows=[{"<连接键>": "P1", "<数值列>": 3}], as_of="2026-01-01", notes="<口径说明>",
    )
    # handle() 要用的其余句柄（llm / data / stats…）经 bus.context(...) 传你自己的 fake
    request = ModuleRequest(query="<会触发该能力调用的问题>")
    events = [e async for e in module.handle(request, bus.context())]

    (call,) = bus.invocations  # 形状与平台 trace.invocations / 归档 invocations.json 相同
    assert call["error_code"] == ""
    assert call["arguments"] == {"<参数名>": ["P1"]}  # 被调方实际收到的（已按签名归一化）
    assert any(e.type.value == "delta" for e in events)


# ── 被调方：assert_capability ──────────────────────────────────────────────────


@provides_capabilities
def test_declared_capabilities_are_implemented():
    """声明了 capabilities 就必须实现 invoke()——装配期查不出来，只会在被调到时报 CAPABILITY_NOT_IMPLEMENTED。"""
    assert FactoryIssueModule.invoke is not ForgeModule.invoke


@provides_capabilities
@pytest.mark.skip(reason=EXAMPLE)
async def test_example_capability_satisfies_its_own_signature():
    ctx = ModuleContext(
        user=UserContext(user_id="test"),
        agent_node=AgentNode(agent=MODULE_CODE),
        # invoke() 要用的句柄（data 等）在这里注入你自己的 fake
    )
    result = await assert_capability(
        FactoryIssueModule(), "<能力名>", {"<参数名>": ["P1"]}, ctx
    )
    assert result.as_of  # 数据时点，别省
