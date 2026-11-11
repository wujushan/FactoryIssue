"""润色请求参数：`ext_param` → `PolishRequest`（润色设计 §5）。

`ext_param` 来自客户端，不参与权限判断，只决定怎么润色。逻辑照实测工具 `scripts/polish_spike/polish_core.py`
的 `parse_request`（r1、r2 两轮实测用的就是它）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from factory_issue_module.config.polish_rules import PolishField, PolishRules

FIVE_WHY_ANSWER = "five_why_answer"
#: `context` 里认得的字符串键（§7.1）；`five_why` 另外处理
CONTEXT_TEXT_KEYS = ("problem_type", "model", "material", "problem_desc", "reason", "measures", "prevention",
                     "current_question")
CONTEXT_FIVE_WHY = "five_why"

# 日志 `factory_issue_polish_bad_param` 的 reason（§5 表）
REASON_FIELD = "field"
REASON_UNKNOWN_FIELD = "unknown_field"
REASON_MAX_LENGTH = "max_length"
REASON_CURRENT_QUESTION = "current_question"
#: 不报错、只记日志：`issue_no` 不是字符串时当没给
REASON_ISSUE_NO_IGNORED = "issue_no_ignored"


class BadParam(ValueError):
    """参数不合格，按 `POLISH_BAD_PARAM` 答；`reason` 只进日志。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PolishRequest:
    field: str                       # 栏目代码（已去掉首尾空白，规则里有）
    max_length: int | None           # 页面给的字数上限；None 用栏目默认
    issue_no: str | None             # 原样，规整在 §7 做
    context: Mapping[str, Any]       # 只留认得的键、类型对的值
    #: 日志用：`context` 里丢掉了几项；`issue_no` 给了但不是字符串
    dropped: int = 0
    issue_no_ignored: bool = False


def parse(ext: Mapping[str, Any], rules: PolishRules) -> PolishRequest:
    """不合格抛 `BadParam`（§5 表的前四行）；其余不合格的只丢掉那一项。"""
    code = ext.get("field")
    if not isinstance(code, str) or not code.strip():
        raise BadParam(REASON_FIELD)
    code = code.strip()
    fld = rules.field(code)
    if fld is None:
        raise BadParam(REASON_UNKNOWN_FIELD)
    raw_max = ext.get("max_length")
    if raw_max is not None and (type(raw_max) is not int or raw_max <= 0):
        raise BadParam(REASON_MAX_LENGTH)
    raw_issue = ext.get("issue_no")
    issue = raw_issue if isinstance(raw_issue, str) else None
    context, dropped = _context(ext.get("context"))
    if fld.code == FIVE_WHY_ANSWER and not str(context.get("current_question") or "").strip():
        raise BadParam(REASON_CURRENT_QUESTION)
    return PolishRequest(field=fld.code, max_length=raw_max, issue_no=issue, context=context, dropped=dropped,
                         issue_no_ignored=raw_issue is not None and issue is None)


def limit_of(request: PolishRequest, fld: PolishField) -> int | None:
    """这次的字数上限：页面给了就用页面的，没给才用栏目默认；两者不取较小的一个（§5，评审 2026-11-10 第 3 条）。"""
    return request.max_length if request.max_length is not None else fld.default_max


def _context(raw: Any) -> tuple[dict[str, Any], int]:
    """(认得的项, 丢掉了几项)。`context` 不是对象时整个丢掉，算一项。"""
    if raw is None:
        return {}, 0
    if not isinstance(raw, Mapping):
        return {}, 1
    out: dict[str, Any] = {}
    dropped = 0
    for key, value in raw.items():
        if key in CONTEXT_TEXT_KEYS and isinstance(value, str):
            out[key] = value
        elif key == CONTEXT_FIVE_WHY and isinstance(value, list):
            # 缺的键按空串（同实测工具）；问与答都为空的项丢掉（同 §7.2 库里的 5Why，评审 P0 第 2 条）
            items = [{"question": str(x.get("question") or ""), "answer": str(x.get("answer") or "")}
                     for x in value if isinstance(x, Mapping)
                     and all(isinstance(x.get(k, ""), str) for k in ("question", "answer"))]
            items = [x for x in items if x["question"].strip() or x["answer"].strip()]
            dropped += len(value) - len(items)
            out[key] = items
        else:
            dropped += 1
    return out, dropped
