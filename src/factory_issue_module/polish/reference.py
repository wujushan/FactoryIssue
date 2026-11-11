"""同单参考内容（润色设计 §7）：页面发来的与按编号查库的合并、截断，进提示的「同一张单的其他内容」。

参考内容只为前后一致，不进结果，也不进检查的「原文事实」。取的是库里保存的原值，不套单张单详情的显示规则
（`2_landed/domestic/ai_polish.md`「参考同一张单的内容」）。按编号取数照调用人的权限：查不到、没权限、出错都只是
不参考库里的内容，照样润色，不报错。

页面发来的那部分（`render` 的写法、标签、截断）照 r1、r2 实测时 `scripts/polish_spike/polish_core.py` 的
`reference()`（`569a027` 及之前的版本），逐字不改。
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from forge_core.errors import PermissionDenied

from factory_issue_module.declarations import INFO, Domain
from factory_issue_module.domains import base, domestic, enums, numbers
from factory_issue_module.polish.params import CONTEXT_FIVE_WHY, FIVE_WHY_ANSWER
from factory_issue_module.textnorm import strip_rich

logger = structlog.get_logger(__name__)

#: `context` 的键 → 提示里的名称（§7.1），也是输出的先后
LABELS: dict[str, str] = {
    "problem_type": "问题类型", "model": "机型", "material": "物料", "problem_desc": "问题描述",
    "reason": "原因分析", "measures": "改善措施", "prevention": "预防对策",
}
FIVE_LABEL = "已有的 5Why"
QUESTION_LABEL = "这一答对应的问"
PENDING = "（待答复）"
#: 截断（§7.3）：四栏叙述各 800 字，5Why 最多 10 条、问与答各 200 字，其余各 100 字
LONG_KEYS = frozenset({"problem_desc", "reason", "measures", "prevention"})
LONG_MAX = 800
SHORT_MAX = 100
FIVE_MAX_ITEMS = 10
FIVE_TEXT_MAX = 200
#: 「物料」单：机型一栏写「物料」（国内主表 `MHead`）
MATERIAL_UNIT = "物料"

# 日志 `db` 的取值（§14）
DB_SKIPPED = "skipped"
DB_OK = "ok"
DB_NOT_FOUND = "not_found"
DB_DENIED = "denied"
DB_FAILED = "failed"
# 日志 `reference` 的取值（§14）
REF_NONE, REF_PAGE, REF_DB, REF_BOTH = "none", "page", "db", "both"

#: 按编号查库最多等几秒（§7.2）：参考内容可有可无，库慢时不为它拖住整次润色；这段时间里没有心跳，
#: 要小于 `steps.HEARTBEAT`（10 秒）的量级，第一个「正在润色」刚在它之前发出
DB_TIMEOUT = 10.0

#: 按编号取的主表列（§7.2）
MAIN_SELECT = ("ID", "ProblemType", "MHead", "CInvCode", "ProblemDesc", "Reason", "Measures", "Prevention")
FIVE_SELECT = ("ID", "Question", "Reason", "Status", "AddDate")


@dataclass(frozen=True)
class Reference:
    items: dict[str, Any]
    #: 进了提示的内容来自哪里：none / page / db / both
    source: str
    #: 按编号查库的结果：skipped / ok / not_found / denied / failed
    db: str
    #: 机型、5Why、存货那几条里出错的（只少那一项）
    missing: tuple[str, ...] = ()


def _cut(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n] + "…"


def _text(value: Any) -> str:
    """库里取出的一格 → 去首尾空白的字符串；空值（None、NaN）为空串。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _same(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", strip_rich(a)) == re.sub(r"\s+", "", strip_rich(b))


# ---------------------------------------------------------------- 页面发来的（§7.1）


def page_values(context: Mapping[str, Any]) -> dict[str, Any]:
    """`context` 里认得的项（`params.parse` 已筛过类型）：文字栏、`five_why`。键在即算页面给了，空串也是。"""
    out: dict[str, Any] = {k: context[k] for k in LABELS if k in context}
    if CONTEXT_FIVE_WHY in context:
        out[CONTEXT_FIVE_WHY] = list(context[CONTEXT_FIVE_WHY])
    return out


def render(values: Mapping[str, Any], field: str, current_question: str) -> tuple[dict[str, Any], set[str]]:
    """(提示里的「同一张单的其他内容」, 实际写进去的键)。正在润色的这一栏不放（§7.3）。"""
    out: dict[str, Any] = {}
    used: set[str] = set()
    for key, label in LABELS.items():
        if key == field or key not in values:
            continue
        text = strip_rich(values[key])
        if text:
            out[label] = _cut(text, LONG_MAX if key in LONG_KEYS else SHORT_MAX)
            used.add(key)
    five = values.get(CONTEXT_FIVE_WHY) or []
    if five:
        out[FIVE_LABEL] = [{"问": _cut(strip_rich(x["question"]), FIVE_TEXT_MAX),
                            "答": _cut(strip_rich(x["answer"]), FIVE_TEXT_MAX) or PENDING}
                           for x in five[:FIVE_MAX_ITEMS]]
        used.add(CONTEXT_FIVE_WHY)
    if field == FIVE_WHY_ANSWER:
        out[QUESTION_LABEL] = _cut(strip_rich(current_question or ""), FIVE_TEXT_MAX)
    return out, used


# ---------------------------------------------------------------- 按编号查库（§7.2）


def _main_spec(step: Any) -> dict[str, Any]:
    return {**domestic.main_spec(step), "select": [f"m.{c}" for c in MAIN_SELECT]}


def _models_spec(step: Any) -> dict[str, Any]:
    return domestic.child_spec(domestic.MODELS, ("ProductName",), step)


def _five_spec(step: Any) -> dict[str, Any]:
    # 排序交 SQL；排序用的两列也放进 select（日后加了列级规则也不会只因排序列被拒，§7.2）
    return {**domestic.child_spec(domestic.FIVE, FIVE_SELECT, step),
            "order_by": [{"field": "c.AddDate", "direction": "ASC"}, {"field": "c.ID", "direction": "ASC"}]}


def _inventory_spec() -> dict[str, Any]:
    return {"source": INFO, "from": domestic.INVENTORY, "select": ["cInvCode", "cInvName"]}


def _rows(frame: Any) -> list[dict[str, Any]]:
    return [] if frame is None or len(frame) == 0 else frame.to_dict("records")


def _five_items(rows: Sequence[Mapping[str, Any]], field: str, current_question: str) -> list[dict[str, str]]:
    """库里的 5Why：去掉问与答都为空的；润色 5Why 的答时，问与 `current_question` 相同、答为空的那一行就是正在答的，
    不放进「已有的 5Why」（§7.3）。"""
    items = [{"question": _text(r.get("Question")), "answer": _text(r.get("Reason"))} for r in rows]
    items = [x for x in items if x["question"] or x["answer"]]
    if field == FIVE_WHY_ANSWER and current_question.strip():
        hit = next((i for i, x in enumerate(items) if not x["answer"] and _same(x["question"], current_question)),
                   None)
        if hit is not None:
            del items[hit]
    return items


async def db_values(ctx: Any, issue_no: str | None, field: str,
                    current_question: str) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    """(库里的项, `db`, 出错的项)。至多 4 条查询：主表、机型、5Why 并行，有料号时再取存货（§7.2）。"""
    if not issue_no:
        return {}, DB_SKIPPED, ()
    got = numbers.issue_number(issue_no)
    if isinstance(got, str) or got[1] is not Domain.DOMESTIC:  # 格式不对，或不是国内单
        return {}, DB_SKIPPED, ()
    if getattr(ctx, "data", None) is None:
        logger.warning("factory_issue_polish_db_failed", error="no_data_handle")
        return {}, DB_FAILED, ()
    step = domestic.issue_step([got[0]])
    main, models, five = await asyncio.gather(
        base.fetch(ctx, _main_spec(step)), base.fetch(ctx, _models_spec(step)), base.fetch(ctx, _five_spec(step)),
        return_exceptions=True)
    if isinstance(main, BaseException):
        if not isinstance(main, Exception):
            raise main
        logger.warning("factory_issue_polish_db_failed", error=type(main).__name__)
        return {}, DB_DENIED if isinstance(main, PermissionDenied) else DB_FAILED, ()
    rows = _rows(main)
    if not rows:
        return {}, DB_NOT_FOUND, ()
    row = rows[0]
    out: dict[str, Any] = {}
    missing: list[str] = []

    def part_failed(part: str, exc: BaseException) -> None:
        if not isinstance(exc, Exception):
            raise exc
        missing.append(part)
        logger.warning("factory_issue_polish_db_part_failed", part=part, error=type(exc).__name__)

    kind = _text(row.get("ProblemType"))
    try:
        type_name = enums.CN_PROBLEM_TYPES.get(int(float(kind))) if kind else None
    except ValueError:
        type_name = None
    if type_name:
        out["problem_type"] = type_name
    if _text(row.get("MHead")) == MATERIAL_UNIT:
        out["model"] = MATERIAL_UNIT
    elif isinstance(models, BaseException):
        part_failed("model", models)
    else:
        names = list(dict.fromkeys(n for n in (_text(r.get("ProductName")) for r in _rows(models)) if n))
        if names:
            out["model"] = "、".join(names)
    code = _text(row.get("CInvCode"))
    if code:
        name = ""
        try:
            inv = await base.fetch_in(ctx, _inventory_spec(), "cInvCode", [code])
            name = next((_text(r.get("cInvName")) for r in _rows(inv) if _text(r.get("cInvCode")) == code), "")
        except Exception as exc:  # noqa: BLE001 —— 只少物料名称，料号照写
            part_failed("inventory", exc)
        out["material"] = f"{name}（{code}）" if name else code
    for key, column in (("problem_desc", "ProblemDesc"), ("reason", "Reason"), ("measures", "Measures"),
                        ("prevention", "Prevention")):
        text = _text(row.get(column))
        if text:
            out[key] = text  # 富文本，`render` 里过 strip_rich
    if isinstance(five, BaseException):
        part_failed("five_why", five)
    else:
        items = _five_items(_rows(five), field, current_question)
        if items:
            out[CONTEXT_FIVE_WHY] = items
    return out, DB_OK, tuple(missing)


# ---------------------------------------------------------------- 合并（§7.3）


async def build(ctx: Any, context: Mapping[str, Any], issue_no: str | None, field: str) -> Reference:
    """页面发来的为准，其余用库里的；截断后交提示。不抛异常（取数出错只是少了参考）。"""
    current_question = str(context.get("current_question") or "")
    page = page_values(context)
    try:
        db, status, missing = await asyncio.wait_for(db_values(ctx, issue_no, field, current_question),
                                                     timeout=DB_TIMEOUT)
    except TimeoutError:
        # 到时不再等（`to_thread` 里的查询取消不掉，线程跑完自己结束），照样润色（P4 评审第 1 条）
        logger.warning("factory_issue_polish_db_failed", error="timeout")
        db, status, missing = {}, DB_FAILED, ()
    except Exception as exc:  # noqa: BLE001 —— 兜底：不让参考内容挡住润色
        logger.warning("factory_issue_polish_db_failed", error=type(exc).__name__)
        db, status, missing = {}, DB_FAILED, ()
    merged = {**db, **page}
    items, used = render(merged, field, current_question)
    from_page = any(k in page for k in used) or QUESTION_LABEL in items
    from_db = any(k not in page for k in used)
    source = REF_BOTH if from_page and from_db else REF_PAGE if from_page else REF_DB if from_db else REF_NONE
    return Reference(items=items, source=source, db=status, missing=missing)
