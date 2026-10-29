"""制程问题查询助手 业务模块（设计 §1.4、§2）。

`handle()` 只调编排（`turn/orchestrator.py`）；manifest 的声明在 `declarations.py`，从 `2_landed`
生成的部分（`intents`、`glossary`、`clarify_dimensions`、`analysis_dimensions`）在 `landed.py`。
S6 之前的测试包不声明 mart 别名、`vectorize` 与 `jobs()`（设计 §2）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

from forge_core.events import Event
from forge_core.module import ForgeModule, ModuleContext, ModuleManifest, ModuleRequest

from factory_issue_module import landed
from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import (
    CONFIG_FILES,
    DATA_SOURCES,
    DESCRIPTION,
    FIELD_MAPPINGS,
    KEYWORDS,
    MODULE_CODE,
    NAME,
    PROFILES,
)
from factory_issue_module.turn import orchestrator

__all__ = ["MODULE_CODE", "MODULE_VERSION", "FactoryIssueModule"]

#: 版本号只有一个真源：pyproject.toml 的 [project].version（`forge release` 改的就是它，wheel 元数据
#: 由它生成）。这里读已装 wheel 的元数据，不手写字面量；源码树里未安装时退回 0.0.0。
try:
    MODULE_VERSION = _installed_version("forge-module-factory-issue")
except PackageNotFoundError:  # pragma: no cover —— 未安装即本仓未 uv sync
    MODULE_VERSION = "0.0.0"


class FactoryIssueModule(ForgeModule):
    manifest = ModuleManifest(
        code=MODULE_CODE,
        name=NAME,
        description=DESCRIPTION,
        version=MODULE_VERSION,  # 跟随 pyproject.toml，勿改回字面量
        profiles=PROFILES,
        intents=landed.intents(),
        keywords=KEYWORDS,
        dependencies=[],
        require_privileges=True,  # 决策 2026-10-18「没拉到权限时拒绝本轮」
        data_sources=DATA_SOURCES,
        field_mappings=FIELD_MAPPINGS,
        config_files=CONFIG_FILES,
        clarify_dimensions=landed.clarify_dimensions(),
        analysis_dimensions=landed.analysis_dimensions(),
        glossary=landed.glossary(),
    )

    async def handle(self, request: ModuleRequest, ctx: ModuleContext) -> AsyncIterator[Event]:
        async for event in orchestrator.run_turn(self.manifest, request, ctx):
            yield event

    def validate_config(self, name: str, text: str) -> None:
        config_files.validate(name, text)
