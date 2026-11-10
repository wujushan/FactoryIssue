"""制程问题查询助手 业务模块（设计 §1.4、§2）。

`handle()` 只调编排（`turn/orchestrator.py`）；manifest 的声明在 `declarations.py`，从 `2_landed`
生成的部分（`intents`、`glossary`、`clarify_dimensions`、`analysis_dimensions`）在 `landed.py`。
S6 起声明 mart 别名、`vectorize` 与 `jobs()`（两个治理任务，`jobs/text_sync.py`）；这一版只在环境建好 mart 库、
登记别名之后发（设计 §2）。`ext_param.task` 为 `domestic_polish` 的轮次交 `polish/`（决策 2026-11-09「AI 润色技术设计」§3）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

import structlog
from forge_core.events import Event, EventType
from forge_core.jobs import JobBinding
from forge_core.module import ForgeModule, ModuleContext, ModuleManifest, ModuleRequest

from factory_issue_module import landed, polish
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
    TASKS,
    VECTORIZE,
)
from factory_issue_module.jobs import text_sync
from factory_issue_module.present import pacing
from factory_issue_module.turn import orchestrator

__all__ = ["MODULE_CODE", "MODULE_VERSION", "FactoryIssueModule"]

logger = structlog.get_logger(__name__)

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
        vectorize=VECTORIZE,
        config_files=CONFIG_FILES,
        tasks=TASKS,  # 润色设计 §2.1：INFO 页面【AI润色】经 /v2/tasks 调用
        clarify_dimensions=landed.clarify_dimensions(),
        analysis_dimensions=landed.analysis_dimensions(),
        glossary=landed.glossary(),
    )

    #: 面向前端的呈现：正文分小段陆续发出（打字机效果）、发进度事件（`present/pacing.py`）。单测关掉，看的是
    #: 编排产出的完整事件；分段与进度另有单测
    live: bool = True

    async def handle(self, request: ModuleRequest, ctx: ModuleContext) -> AsyncIterator[Event]:
        # 润色设计 §3：按任务码分派，润色不走查询编排、不经打字机分段（结果一次发出）
        if polish.is_polish(request):
            async for event in polish.run(self.manifest, request, ctx):
                if self.live or event.type is not EventType.PROGRESS:
                    yield event
            return
        task = polish.task_of(request)
        if task:  # 别的任务码：照常走查询流程，ext_param 不用（经 /v2/tasks 来的平台已按 UNKNOWN_TASK 拒了）
            logger.info("factory_issue_unknown_task", task=task)
        events = orchestrator.run_turn(self.manifest, request, ctx)
        if self.live:
            async for event in pacing.paced(events):
                yield event
            return
        async for event in events:
            if event.type is not EventType.PROGRESS:
                yield event

    def validate_config(self, name: str, text: str) -> None:
        config_files.validate(name, text)

    def jobs(self) -> list[JobBinding]:
        """两个治理任务（设计 §12）。句柄在运行时从 `JobContext` 取，这里不预绑任何句柄。"""
        return text_sync.bindings()
