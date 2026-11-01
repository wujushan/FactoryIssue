"""临时统计的检查（设计 §5.5）：模型写的脚本运行前做 AST 检查，运行后检查返回值的形状。都只查不算。

- AST 检查：只许沙箱白名单里的 import；不许定义 class、访问双下划线开头的属性与名字；不许用沙箱里没有的内建函数
  （`open`、`exec`、`eval`、`compile`、`getattr`、`hasattr`、`vars`、`globals`、`type` 等，运行了才报 NameError 的
  提前拦下）；不许重新定义口径函数。报错是一句能照着改的话，交模型修一次（只给模型看、只进日志）。
- 形状检查：`{"columns", "rows", "chart"}` 三个键齐；列名是不重复的中文业务说法（不是英文或代码名，护栏「不露字段
  名」在这里拦）；每行的值个数等于列数，值是原生数字、字符串或 None；行数不超过 `ROWS_MAX`；`chart` 的 `x`、`series`
  是表里有的列，`series` 是数值列。
- 运行时不 import `forge_sandbox`（它在本仓只是 dev 依赖，§8.2），白名单抄一份在这里，单测断言它与沙箱的一致。
"""

from __future__ import annotations

import ast
import builtins
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

#: 沙箱 import 白名单（`forge_sandbox/harness.py::_ALLOWED_IMPORTS`，sandbox 0.2.0）
ALLOWED_IMPORTS = frozenset({
    "pandas", "numpy", "math", "statistics", "json", "datetime", "collections", "itertools", "functools", "re",
    "decimal", "time", "_strptime", "dateutil",
})
#: 沙箱里有的内建函数（`forge_sandbox/harness.py::_SAFE_BUILTIN_NAMES`，sandbox 0.2.0）；其余内建名字运行时都没有
SAFE_BUILTINS = frozenset({
    "abs", "all", "any", "bool", "bytes", "callable", "chr", "complex", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "hash", "hex", "int", "isinstance", "issubclass", "iter", "len", "list", "map",
    "max", "min", "next", "object", "oct", "ord", "pow", "print", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "tuple", "zip", "ArithmeticError", "AttributeError", "BaseException",
    "Exception", "IndexError", "KeyError", "LookupError", "NotImplementedError", "OverflowError", "RuntimeError",
    "StopIteration", "TypeError", "ValueError", "ZeroDivisionError", "True", "False", "None",
})
#: 口径函数（`stats/lib/custom.py`）：已经定义好，脚本不许重新定义
HELPERS = ("拆多值", "合计不良率")
#: 返回值的行数上限：按月看五年（60 个月）不被拦，再多就请模型按更粗的粒度汇总（§19「G4b S7」）
ROWS_MAX = 60
CHART_TYPES = ("bar", "line", "pie", "none")
KEYS = ("columns", "rows", "chart")
#: 列名里可以照写的英文缩写（与护栏「不露字段名」的豁免相同：显示名里本来就是这几个）
ASCII_OK = frozenset({"CAR", "PN", "PO"})
_ASCII_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CODE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S)


def extract_code(text: str) -> str:
    """模型回复里的代码：取第一个 ```python 代码块；没有代码块时整段当代码。"""
    body = _THINK.sub("", text or "")
    m = _CODE.search(body)
    return (m.group(1) if m else body).strip()


def _bound_names(tree: ast.AST) -> set[str]:
    """脚本自己定义或赋值过的名字（参数、变量、函数、import 的别名、推导式与 except 的变量）。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
    return out


def check_script(code: str) -> list[str]:
    """运行前的 AST 检查。返回问题（空 = 通过），每条是一句能照着改的话。"""
    if not code.strip():
        return ["没有给出代码，请把脚本放在一个 ```python 代码块里"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"脚本有语法错误（第 {exc.lineno} 行）：{exc.msg}"]
    problems: list[str] = []

    def add(text: str) -> None:
        if text not in problems:
            problems.append(text)

    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" and n.args.args for n in tree.body):
        add("脚本要在最外层定义 def run(data):")
    bound = _bound_names(tree)
    unsafe = {n for n in dir(builtins) if n not in SAFE_BUILTINS}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.level:
                add("不能用相对 import")
                continue
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for mod in mods:
                if mod.split(".")[0] not in ALLOWED_IMPORTS:
                    add(f"不能 import {mod}：只能 import {'、'.join(sorted(ALLOWED_IMPORTS - {'_strptime'}))}")
        elif isinstance(node, ast.ClassDef):
            add(f"不能定义 class（{node.name}），请改用函数或字典")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            add(f"不能访问双下划线开头的属性：{node.attr}")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                add(f"不能使用双下划线开头的名字：{node.id}")
            elif isinstance(node.ctx, ast.Load) and node.id in unsafe and node.id not in bound:
                add(f"沙箱里没有 {node.id}，请换一种写法")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in HELPERS:
            add(f"口径函数 {node.name} 已经定义好，不要重新定义")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            add("不要用 global、nonlocal")
    for name in HELPERS:
        if any(isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store) for n in ast.walk(tree)):
            add(f"口径函数 {name} 已经定义好，不要给它重新赋值")
    return problems


def referenced(code: str) -> set[str]:
    """脚本里出现的字符串常量与名字（统计口径按它补写用到的派生列与口径函数，§5.5）。解析不了时为空。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
        elif isinstance(node, ast.Name):
            out.add(node.id)
    return out


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_result(out: Any, rows_max: int = ROWS_MAX) -> list[str]:
    """运行后的形状检查（`out` 是沙箱外壳整理过的返回值）。返回问题（空 = 通过）。"""
    if not isinstance(out, Mapping):
        return ['run(data) 要返回 dict：{"columns": [...], "rows": [[...]], "chart": {...}}']
    problems: list[str] = []
    missing = [k for k in KEYS if k not in out]
    extra = [str(k) for k in out if k not in KEYS]
    if missing:
        problems.append(f"返回值缺键：{'、'.join(missing)}")
    if extra:
        problems.append(f"返回值只要 columns、rows、chart 三个键，多了：{'、'.join(extra)}")
    cols = out.get("columns")
    if not isinstance(cols, list) or not cols:
        problems.append("columns 要是非空的列名列表")
        cols = []
    names = [c for c in cols if isinstance(c, str) and c.strip()]
    if len(names) != len(cols):
        problems.append("每个列名都要是非空的文本")
    if len(set(names)) != len(names):
        problems.append("列名不能重复")
    english = [c for c in names if _ASCII_NAME.fullmatch(c.strip()) and c.strip() not in ASCII_OK]
    if english:
        problems.append(f"列名要用中文业务说法（如「单数」），不要用英文或代码名：{'、'.join(english)}")
    if any(c.startswith("_") for c in names):
        problems.append("列名不能以下划线开头")
    rows = out.get("rows")
    if not isinstance(rows, list):
        problems.append("rows 要是列表，每行也是列表")
        rows = []
    if len(rows) > rows_max:
        problems.append(f"结果有 {len(rows)} 行，超过 {rows_max} 行；请按更粗的粒度汇总，或只给最需要看的部分")
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, list):
            problems.append(f"第 {i} 行不是列表")
            break
        if len(row) != len(cols):
            problems.append(f"第 {i} 行有 {len(row)} 个值，columns 有 {len(cols)} 个")
            break
        bad = [v for v in row if not (v is None or isinstance(v, str) or _is_number(v))]
        if bad:
            problems.append(f"第 {i} 行有不是数字、文本或 None 的值（{type(bad[0]).__name__}），请先转换")
            break
        if any(isinstance(v, float) and not math.isfinite(v) for v in row):
            problems.append(f"第 {i} 行有无穷大的值")
            break
    problems += _check_chart(out.get("chart"), names, rows)
    return problems


def _check_chart(chart: Any, cols: Sequence[str], rows: Sequence[Any]) -> list[str]:
    if not isinstance(chart, Mapping):
        return ['chart 要是 {"type": "bar|line|pie|none", "x": 列名, "series": [列名]}']
    kind = chart.get("type")
    if kind not in CHART_TYPES:
        return [f"chart.type 只能是 {'、'.join(CHART_TYPES)}"]
    if kind == "none":
        return []
    x, series = chart.get("x"), chart.get("series")
    out = []
    if x not in cols:
        out.append(f"chart.x 要是 columns 里的一列，现在是 {x!r}")
    if not isinstance(series, list) or not series:
        return [*out, "chart.series 要是非空的列名列表"]
    for s in series:
        if s not in cols:
            out.append(f"chart.series 里的 {s!r} 不在 columns 里")
            continue
        if s == x:
            out.append("chart.series 不能包含横轴那一列")
            continue
        at = list(cols).index(s)
        values = [r[at] for r in rows if isinstance(r, list) and len(r) == len(cols)]
        if any(not (v is None or _is_number(v)) for v in values) or not any(_is_number(v) for v in values):
            out.append(f"chart.series 里的 {s!r} 要是数值列")
    return out


_FRAME = re.compile(r'^(\s*File "<sandbox-script>", line )(\d+)(.*)$')


def model_error(error: str, offset: int, lines: int, limit: int = 1500) -> str:
    """沙箱报错交模型修：模型代码里的那几帧行号换成模型自己代码里的行号；外壳与口径函数的帧（行号不在模型代码
    `offset + 1` 到 `offset + lines` 之间）整行去掉，免得换算出模型代码里不存在的行号。只留末尾一段（异常类型与原因
    在最后）。"""
    out: list[str] = []
    for line in (error or "").splitlines():
        m = _FRAME.match(line)
        if m is None:
            out.append(line)
            continue
        n = int(m.group(2)) - offset
        if 1 <= n <= lines:
            out.append(f"{m.group(1)}{n}{m.group(3)}")
    return "\n".join(out)[-limit:]
