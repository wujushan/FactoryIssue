"""追问与「其他理解」的按钮（设计 §4.4、§9.5、§5.3 第 7、17、18 条、§6.1「日期」）。

按钮的 `query` 由代码拼成，不靠规划提示要求模型写成问句（开发者 2026-10-29 定：提示里这样要求会让别的问句
回退，设计 §19「拆开量」）。INFO 网页前端把 `query` 当按钮文字显示、点了照发（设计 §19「S5 提交后 INFO 前端
按钮显示问题的处理」），所以能短就短：

- 代码追问、`pending_clarify` 写进去了（`short_recommendations`）：`query` 就是选项本身（「惠州百富」「是」
  「近 30 天」）。点了按工作区直填，不重新规划；问句全文（原话加这一项，`recommendations`）另存在
  `pending_clarify` 里，本轮按它理解（`turn/workspace.py::fill`）。
- 工作区写不进去（没有会话号、超限）时的退路，以及模型写的追问（「其他」指什么、现象太泛）、第 17 条缺时间
  （`recommendations`）：本轮原话加选定的那一项，「上个月惠州工厂的问题有哪些（惠州百富）」。这几种点了要
  重新规划，问句得自己说全；选项多是「问题类型为『其他』」「开机花屏」这类短语，单独发出去不成问句。
  - 接不上上一轮：原话多是「？？？」、乱码或「帮我看一下详情」，拼上去没有意义，`query` 直接用选项文字。
  - 时间认不出：把原话里那段说法换成选定的时间，免得新问句里仍带着认不出的说法、再追问一次。
  - 第 18 条「上一轮没有结果」：选项已是更早那次的原话接上本轮原话，`label`「按更早那次的条件查」。
- 计划的 `alternatives`（其他理解）做成答后按钮（`alternative_recommendations`）：「换个理解：这条理解」。
  规划器从历史与上一轮计划知道是哪一问（`turn/execute.py` 交 `present/suggestions.py` 合并）。两种不做按钮
  （`alternative_problem`，决策 2026-11-06「其他理解与接着问的按钮不自相矛盾」）：带着规划器自己的判断（「但」
  「更可能」「结合」一类，多是在说为什么不按这条查）；计划已按其余类型查（问题类型「不是」某几类），这条却把
  「其他」读成问题类型「其他」（总述「『其他』『剩下的』指什么」，这种问法读法已定）。
- 按钮至多 4 个。`label` 是一句说完的话，不超过 30 个字：不超过就用原文，超过则换成另一句完整短说法，
  不用省略号截断（决策 2026-11-04「按钮文字不截断」）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import structlog
from forge_core.events import Event

from factory_issue_module.plan import schema
from factory_issue_module.plan.normalize import NO_RESULT_REASON

logger = structlog.get_logger(__name__)

#: 选项文字直接作问句的追问原因（原话本身没有可接的意思）
DIRECT_REASONS = ("接不上上一轮",)
#: 时间说法换算不出起止日期（§6.1；总述「必要澄清项」）
TIME_UNKNOWN_REASON = "时间认不出"
TIME_UNKNOWN_OPTIONS = ("近 30 天", "今年")
EARLIER_LABEL = "按更早那次的条件查"
ALTERNATIVE_NAME = "其他理解"
#: 其他理解按钮的问句开头
ALTERNATIVE_PREFIX = "换个理解："
#: 其他理解里带着规划器自己的判断（哪种更可能、为什么先按另一种查）。「也可能指」是在说这条理解，不算
_JUDGED = re.compile(r"但|不过|然而|可是|更可能|最可能|可能性|更像|大概率|倾向|结合")
#: 把「其他」读成问题类型「其他」这一个取值（「叫『其他』的取值」「问题类型为其他的单」）
_LITERAL_OTHER = re.compile(r"[「『“\"]其[他它][」』”\"]|问题类型(?:为|是|叫)其[他它](?!类型)")

MAX_OPTIONS = 4
#: 按钮文字的上限。INFO 网页前端显示 `label`，截断加省略号会把选项切成读不成的半句（决策 2026-11-04）
LABEL_MAX = 30
_END_PUNCT = "？?。.！!，, "


def button_label(text: str) -> str:
    """去掉句末标点。不截断。"""
    return text.strip().rstrip(_END_PUNCT)


def fit_label(text: str, fallback: str) -> str:
    """能放进 30 字就用原文，否则用一句说完的 `fallback`（调用方保证它不超过 30 字、不以省略号结尾）。"""
    shown = button_label(text)
    return shown if len(shown) <= LABEL_MAX else fallback


def with_choice(query: str, choice: str) -> str:
    """本轮原话加选定的一项：「按工厂统计一下问题数量（今年）」。"""
    return f"{query.strip().rstrip(_END_PUNCT)}（{choice.strip().rstrip(_END_PUNCT)}）"


def time_unknown_step(said: str) -> dict:
    """时间说法认不出时的追问步骤（总述「必要澄清项」：请用户给出起止日期，并给「近 30 天」「今年」）。"""
    return {"id": "s1", "skill": "clarify", "when": None, "params": {
        "reason": TIME_UNKNOWN_REASON, "said": said,
        "question": f"「{said}」具体是从哪天到哪天？请给出起止日期，如「2026-10-01 至今」。",
        "options": list(TIME_UNKNOWN_OPTIONS)}}


def _texts(items: Sequence[object] | None) -> list[str]:
    return [str(o).strip() for o in (items or []) if isinstance(o, str | int | float) and str(o).strip()]


def recommendations(params: dict, query: str) -> list[dict[str, str]]:
    """追问步骤的参数 → 按钮（`{id, name, label, query}`）；`query` 是能单独发送的问句全文。"""
    reason = str(params.get("reason") or "")
    out: list[dict[str, str]] = []
    for option in _texts(params.get("options"))[:MAX_OPTIONS]:
        if reason in DIRECT_REASONS:
            label, ask = button_label(option), option
        elif reason == NO_RESULT_REASON:
            label, ask = EARLIER_LABEL, option
        elif reason == TIME_UNKNOWN_REASON and params.get("said") and str(params["said"]) in query:
            label, ask = button_label(option), query.replace(str(params["said"]), option, 1)
        else:
            label, ask = button_label(option), with_choice(query, option)
        out.append({"id": str(len(out) + 1), "name": reason or "追问", "label": label, "query": ask})
    return out


def short_recommendations(params: dict) -> list[dict[str, str]]:
    """代码追问、`pending_clarify` 写进去了时的按钮：`query` 就是选项本身，与 `recommendations` 同一顺序。"""
    reason = str(params.get("reason") or "")
    return [{"id": str(i), "name": reason or "追问", "label": button_label(option),
             "query": option.rstrip(_END_PUNCT)}
            for i, option in enumerate(_texts(params.get("options"))[:MAX_OPTIONS], start=1)]


def _excludes_types(plan: Mapping | None) -> bool:
    """计划里有一步按问题类型「不是」某几类筛（按其余类型查）。"""
    for step in schema.as_list((plan or {}).get("steps")):
        params = step.get("params") if isinstance(step, Mapping) else None
        for f in schema.as_list((params or {}).get("filters") if isinstance(params, Mapping) else None):
            if isinstance(f, Mapping) and f.get("field") == "问题类型" and schema.OP_KINDS.get(str(f.get("op"))) == "ne":
                return True
    return False


def alternative_problem(alt: str, plan: Mapping | None = None) -> str | None:
    """这条其他理解不做按钮的原因；能用时 None。"""
    if _JUDGED.search(alt):
        return "带判断"
    if _LITERAL_OTHER.search(alt) and _excludes_types(plan):
        return "与口径相反"
    return None


def alternative_recommendations(alternatives: Sequence[object] | None, limit: int = MAX_OPTIONS, *,
                                plan: Mapping | None = None) -> list[dict[str, str]]:
    """计划的 `alternatives` → 答后按钮：`query` 是「换个理解：」加这条理解，规划器拿到时按这条理解重新规划。
    `alternative_problem` 挑出的不做按钮，只记原因（不记原文）。"""
    out: list[dict[str, str]] = []
    for alt in _texts(alternatives):
        why = alternative_problem(alt, plan)
        if why is not None:
            logger.info("factory_issue_alternative_dropped", reason=why)
            continue
        if len(out) >= limit:
            break
        out.append({"id": str(len(out) + 1), "name": ALTERNATIVE_NAME, "label": button_label(alt),
                    "query": ALTERNATIVE_PREFIX + alt.rstrip(_END_PUNCT)})
    return out


def event(params: dict, query: str, recs: list[dict[str, str]] | None = None) -> Event:
    """追问事件；`recs` 不给时按 `recommendations(params, query)`。"""
    recs = recommendations(params, query) if recs is None else recs
    question = str(params.get("question") or "").strip() or "能再说具体一点吗？"
    return Event.clarify(question, [r["label"] for r in recs], recommendations=recs)
