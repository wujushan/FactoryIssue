"""AI 润色实测工具的转接层（决策 2026-11-09「AI 润色技术设计」§5、§6、§8、§9、§10）。

做法 A（开发者 2026-11-09 同意）：G4a 期间这几部分先放在实测工具里，实测结果回填设计稿；G4b 移进
`src/factory_issue_module/polish/` 与 `config/polish_rules.py`，本文件改成转接，规则只留一份。两边不一致时以设计稿为准。

G4b 进度：P1 起润色规则取 `src` 的 `config/polish_rules.py`；P2 起参数（`polish/params.py`）、拆拼与判空判长
（`polish/rich.py`）、检查（`polish/check.py`）取 `src`；P3 起提示（`polish/prompt.py`）与调用参数（`polish/steps.py`）取 `src`；P4 起页面发来的参考内容（`polish/reference.py`）取 `src`；本文件只剩转接。

只用标准库与 `src`；不连库、不调模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from factory_issue_module.config import files as config_files
from factory_issue_module.config.polish_rules import PolishField, PolishRules
from factory_issue_module.declarations import POLISH_RULES, POLISH_TASK_CODE
from factory_issue_module.polish import check as _check
from factory_issue_module.polish import params as _params
from factory_issue_module.polish import prompt as _prompt
from factory_issue_module.polish import reference as _reference
from factory_issue_module.polish import rich as _rich
from factory_issue_module.polish import steps as _steps
from factory_issue_module.polish.check import (  # noqa: F401 —— spike.py 经本模块取这几个名字
    CHECK_ADDED,
    CHECK_FORMAT,
    CHECK_LANG,
    CHECK_LENGTH,
    CHECK_MARKS,
    CHECK_PREFACE,
    CHECK_REMOVED,
    Verdict,
)
from factory_issue_module.polish.rich import ALT, BRACKET, Split  # noqa: F401
from factory_issue_module.turn import errors

TASK_CODE = POLISH_TASK_CODE
#: 提示的版本与假模型认调用的那段文字（设计 §8），取 src；常量在 src 里叫 `POLISH_PROMPT_VERSION`、`POLISH_MARKER`
PROMPT_VERSION = _prompt.POLISH_PROMPT_VERSION
MARKER = _prompt.POLISH_MARKER

EMPTY = errors.POLISH_EMPTY_CODE
TOO_LONG = errors.POLISH_TOO_LONG_CODE
BAD_PARAM = errors.POLISH_BAD_PARAM_CODE
FAILED = errors.POLISH_FAILED_CODE

#: 设计 §4，取 src 的 `polish/steps.py`
CALL_TIMEOUT = _steps.CALL_TIMEOUT
HEARTBEAT = _steps.HEARTBEAT
max_tokens = _steps.max_tokens


# ---------------------------------------------------------------- 润色规则（设计 §10，G4b P1 起取 src）

#: 规则的解析与校验只在 `src/factory_issue_module/config/polish_rules.py`（任务单规矩第 2 条）
Field = PolishField
Rules = PolishRules


def load_rules() -> Rules:
    """内置默认：`2_landed/domestic/ai_polish.md`「润色规则（初始版本）」，经 `src` 的同一个解析函数。"""
    return config_files.default(POLISH_RULES)


# ---------------------------------------------------------------- 请求参数（设计 §5，G4b P2 起取 src）


@dataclass(frozen=True)
class Request:
    field: Field
    #: 这次的字数上限（页面给的或栏目默认，`params.limit_of`）
    max_length: int | None
    issue_no: str | None
    context: dict[str, Any]
    dropped: int = 0


def parse_request(ext: Any, rules: Rules) -> tuple[Request | None, str]:
    """(请求, 不合格时的原因)。原因写成日志里的 `reason`。"""
    if not isinstance(ext, dict):
        return None, "ext_param"
    try:
        req = _params.parse(ext, rules)
    except _params.BadParam as exc:
        return None, exc.reason
    fld = rules.field(req.field)
    assert fld is not None
    return Request(field=fld, max_length=_params.limit_of(req, fld), issue_no=req.issue_no,
                   context=dict(req.context), dropped=req.dropped), ""


# ---------------------------------------------------------------- 判空、判长（设计 §4 第 ③ 步，G4b P2 起取 src）


@dataclass(frozen=True)
class Prepared:
    request: Request
    core: _rich.Prepared

    @property
    def split(self) -> Split:
        return self.core.split

    @property
    def k(self) -> int | None:
        return self.core.k

    @property
    def input_chars(self) -> int:
        return self.core.input_chars


def prepare(query: str, ext: Any, rules: Rules, *, ignore_cap: bool = False) -> tuple[Prepared | None, str, str]:
    """(准备好的, 错误代码, 原因)。`ignore_cap`：实测的长度阶梯要越过原文长度上限量耗时。"""
    req, reason = parse_request(ext, rules)
    if req is None:
        return None, BAD_PARAM, reason
    try:
        core = _rich.prepare(query, rich=req.field.rich, max_input=rules.max_input, limit=req.max_length,
                             ignore_cap=ignore_cap)
    except _rich.NotPolishable as exc:
        return None, exc.code, exc.reason
    return Prepared(request=req, core=core), "", ""


# ---------------------------------------------------------------- 同单参考内容（设计 §7，G4b P4 起取 src；实测不查库）


def reference(req: Request) -> dict[str, Any]:
    """页面发来的同单内容 → 提示里的「同一张单的其他内容」（`src` 的 `polish/reference.py`，不带编号查库）。"""
    values = _reference.page_values(req.context)
    items, _used = _reference.render(values, req.field.code, str(req.context.get("current_question") or ""))
    return items


# ---------------------------------------------------------------- 提示（设计 §8，G4b P3 起取 src）


def system(style: tuple[str, str]) -> str:
    return _prompt.system(style)


def user(prep: Prepared, rules: Rules) -> str:
    """参考内容仍用本文件的 `reference`（页面发来的；P4 换成 `src` 的 `polish/reference.py`）。"""
    return _prompt.user(prep.core, prep.request.field, rules, reference(prep.request))


# ---------------------------------------------------------------- 程序检查（设计 §9，G4b P2 起取 src）


def check(content: str, prep: Prepared) -> Verdict:
    return _check.check(content, prep.core, prep.request.field.name)


def repair(v: Verdict, prep: Prepared) -> str:
    return _check.repair(v, prep.core)
