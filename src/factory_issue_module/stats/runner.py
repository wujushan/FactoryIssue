"""沙箱调用（设计 §8.1）：每步一次 `ctx.stats.run(script, datasets)`。

`script` = 公共库源码（`textnorm.py`、`stats/lib/*.py`）+ 本技能的任务模板（`stats/tasks/*.py`）。各文件之间的
`from factory_issue_module… import` 与 `from __future__` 在拼接时去掉（名字已在同一个命名空间里，沙箱也不许
import 业务包）；任务模板里的 `PARAMS = {}` 换成本步参数的 JSON 字面量。派生规则因此只有一份：单测直接
import `stats/lib` 测，运行时按源码文本拼进沙箱。`src` 里只有这个文件 import 了 `stats.lib`、`stats.tasks`
的源码（护栏测试查）。
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_PKG = Path(__file__).resolve().parents[1]
#: 拼接顺序：被引用的在前
LIB_FILES = (
    "textnorm.py",
    "stats/lib/common.py",
    "stats/lib/views.py",
    "stats/lib/derive_domestic.py",
    "stats/lib/derive_brazil.py",
    "stats/lib/derive_overseas.py",
    "stats/lib/domains.py",
)
TASK_FILES = {"list": "stats/tasks/list.py", "aggregate": "stats/tasks/aggregate.py", "detail": "stats/tasks/detail.py",
              "lookup": "stats/tasks/lookup.py", "verify": "stats/tasks/verify.py"}
#: 只有某个任务要的公共库（详情的各块只在详情脚本里拼，清单与统计的脚本不带它）
TASK_LIBS = {"detail": ("stats/lib/detail.py",)}
_PLACEHOLDER = "PARAMS = {}"
_INTERNAL = re.compile(r"^(from\s+(__future__|factory_issue_module)\b|import\s+factory_issue_module\b)")


def _strip_internal(source: str) -> str:
    out: list[str] = []
    skipping = False
    for line in source.splitlines():
        if skipping:
            if ")" in line:
                skipping = False
            continue
        if _INTERNAL.match(line):
            skipping = "(" in line and ")" not in line
            continue
        out.append(line)
    return "\n".join(out)


@cache
def _source(rel: str) -> str:
    return _strip_internal((_PKG / rel).read_text(encoding="utf-8"))


def script(task: str, params: dict[str, Any]) -> str:
    """本步的沙箱脚本全文。"""
    body = _source(TASK_FILES[task])
    if body.count(_PLACEHOLDER) != 1:
        raise RuntimeError(f"任务模板 {task} 里要有且只有一行 {_PLACEHOLDER}")
    literal = repr(json.dumps(params, ensure_ascii=False, default=str))
    body = body.replace(_PLACEHOLDER, f"PARAMS = json.loads({literal})")
    libs = (*LIB_FILES, *TASK_LIBS.get(task, ()))
    return "\n\n".join(["import json", *(_source(f) for f in libs), body])


async def run(ctx: Any, task: str, datasets: dict[str, Any], params: dict[str, Any],
              *, return_frames: bool = False) -> Any:
    """跑一步；返回 `SandboxOutcome`（`ok`、`result`、`error`、`frames`）。失败时只记脚本错误的开头。"""
    outcome = await ctx.stats.run(script(task, params), datasets, return_frames=return_frames)
    if not outcome.ok:
        logger.error("factory_issue_sandbox_failed", task=task, error=(outcome.error or "")[:300])
    return outcome
