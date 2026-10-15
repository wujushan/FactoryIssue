from forge_core.module import ModuleContext, ModuleRequest, UserContext
from forge_core.permissions.agentnode import AgentNode

from factory_issue_module.module import MODULE_CODE, FactoryIssueModule


def make_ctx() -> ModuleContext:
    return ModuleContext(
        user=UserContext(user_id="test"),
        agent_node=AgentNode(agent=MODULE_CODE),
    )


def test_manifest_sanity():
    m = FactoryIssueModule.manifest
    assert m.code == MODULE_CODE
    assert m.name


async def test_handle_yields_events():
    module = FactoryIssueModule()
    events = [e async for e in module.handle(ModuleRequest(query="测试"), make_ctx())]
    assert events, "handle 必须产出事件流"
    assert all(e.type.value != "end" for e in events), "END 由平台补发，模块不产出"
