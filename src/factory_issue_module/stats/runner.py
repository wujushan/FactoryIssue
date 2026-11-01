"""沙箱调用（设计 §8.1）：每步一次 `ctx.stats.run(script, datasets)`。

`script` = 公共库源码（`textnorm.py`、`stats/lib/*.py`）+ 本技能的任务模板（`stats/tasks/*.py`）。各文件之间的
`from factory_issue_module… import` 与 `from __future__` 在拼接时去掉（名字已在同一个命名空间里，沙箱也不许
import 业务包）；任务模板里的 `PARAMS = {}` 换成本步参数的 JSON 字面量。派生规则因此只有一份：单测直接
import `stats/lib` 测，运行时按源码文本拼进沙箱。`src` 里只有这个文件 import 了 `stats.lib`、`stats.tasks`
的源码（护栏测试查）。
"""

from __future__ import annotations

import ast
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
              "lookup": "stats/tasks/lookup.py", "verify": "stats/tasks/verify.py",
              "keyword_match": "stats/tasks/keyword_match.py", "text_merge": "stats/tasks/text_merge.py",
              "custom_frame": "stats/tasks/custom_frame.py", "custom_run": "stats/tasks/custom_run.py"}
#: 只有某个任务要的公共库（详情的各块只在详情脚本里拼，清单与统计的脚本不带它；按词匹配只拼进按词一路；
#: 临时统计的整理与口径函数只拼进临时统计的两次调用）
TASK_LIBS = {"detail": ("stats/lib/detail.py",), "keyword_match": ("stats/lib/textmatch.py",),
             "custom_frame": ("stats/lib/custom.py",)}
#: 临时统计第二次调用拼进的公共库：口径函数要的几份，不带三域派生（输入帧已经整理好）
CUSTOM_RUN_LIBS = ("textnorm.py", "stats/lib/common.py", "stats/lib/views.py", "stats/lib/custom.py")
#: 模型写的 `run` 在拼接时改成这个名字，外壳的 `run` 才是 harness 认的入口（设计 §5.5）
USER_RUN = "cs_user_run"
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
    body = _task_body(task, params)
    libs = (*LIB_FILES, *TASK_LIBS.get(task, ()))
    return "\n\n".join(["import json", *(_source(f) for f in libs), body])


def _task_body(task: str, params: dict[str, Any]) -> str:
    body = _source(TASK_FILES[task])
    if body.count(_PLACEHOLDER) != 1:
        raise RuntimeError(f"任务模板 {task} 里要有且只有一行 {_PLACEHOLDER}")
    literal = repr(json.dumps(params, ensure_ascii=False, default=str))
    return body.replace(_PLACEHOLDER, f"PARAMS = json.loads({literal})")


def helper_doc(names: tuple[str, ...]) -> str:
    """口径函数的签名与说明（交给模型看，不给函数体）：从 `stats/lib/custom.py` 的源码文本里取，不 import。"""
    tree = ast.parse((_PKG / "stats/lib/custom.py").read_text(encoding="utf-8"))
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            doc = ast.get_docstring(node) or ""
            body = "\n    ".join(doc.splitlines())
            out.append(f"def {node.name}({ast.unparse(node.args)}):\n    \"\"\"{body}\"\"\"")
    if len(out) != len(names):
        raise RuntimeError(f"stats/lib/custom.py 里找不到口径函数：{names}")
    return "\n\n\n".join(out)


def custom_script(code: str, params: dict[str, Any]) -> tuple[str, int]:
    """临时统计第二次调用的脚本全文与模型代码之前的行数（报错的行号减去它，才是模型自己代码里的行号）。

    拼接顺序：公共库、模型写的脚本、`cs_user_run = run`、外壳模板（`stats/tasks/custom_run.py`）。"""
    head = "\n\n".join(["import json", *(_source(f) for f in CUSTOM_RUN_LIBS)]) + "\n\n"
    tail = f"\n\n{USER_RUN} = run\n\n" + _task_body("custom_run", params)
    return head + code.strip("\n") + tail, head.count("\n")


async def run_custom(ctx: Any, code: str, frame: Any, params: dict[str, Any]) -> tuple[Any, int]:
    """跑模型写的脚本（输入帧作为数据集 `issues`）；返回 (`SandboxOutcome`, 模型代码之前的行数)。"""
    text, offset = custom_script(code, params)
    outcome = await ctx.stats.run(text, {"issues": frame})
    if not outcome.ok:
        logger.info("factory_issue_custom_script_failed", error=(outcome.error or "")[:300])
    return outcome, offset


async def run(ctx: Any, task: str, datasets: dict[str, Any], params: dict[str, Any],
              *, return_frames: bool = False) -> Any:
    """跑一步；返回 `SandboxOutcome`（`ok`、`result`、`error`、`frames`）。失败时只记脚本错误的开头。"""
    outcome = await ctx.stats.run(script(task, params), datasets, return_frames=return_frames)
    if not outcome.ok:
        logger.error("factory_issue_sandbox_failed", task=task, error=(outcome.error or "")[:300])
    return outcome
