"""国内填单内容润色（决策 2026-11-09「AI 润色技术设计」§1）。

`handle()` 开头按任务码分派到这里（§3），查询编排一行不走：不判域、不读多轮历史与工作区、不规划、不进沙箱。
本包只依赖 `config`、`domains`、`textnorm`、`turn/errors`，不 import `turn/orchestrator`、`plan`、`present`、
`skills`、`stats`（§1.2，`tests/test_polish_dispatch.py` 核对）。
"""

from __future__ import annotations

from forge_core.module import ModuleRequest

from factory_issue_module.declarations import POLISH_TASK_CODE
from factory_issue_module.polish.steps import ext_param, run

__all__ = ["TASK_CODE", "is_polish", "run", "task_of"]

TASK_CODE = POLISH_TASK_CODE


def task_of(request: ModuleRequest) -> str:
    """本轮 `ext_param.task`（去掉首尾空白）；没带为空串。"""
    task = ext_param(request).get("task")
    return task.strip() if isinstance(task, str) else ""


def is_polish(request: ModuleRequest) -> bool:
    """只认任务码、不认入口：`/v2/tasks`、`/v2/chat`、`/test/chat` 带同样的 `ext_param` 都润色（§3）。"""
    return task_of(request) == TASK_CODE
