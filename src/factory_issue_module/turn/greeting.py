"""寒暄与能力介绍（设计 §9.4、§4.2 第 2 步、§14「规划超时或修一次仍不合格」）。

- 场景清单只取总述「常用查询场景」（与 `manifest.intents` 同源），不即兴编；只介绍本助手。
- 三域都介绍，没有权限的域注「申请后可查」；三域都没有权限时另加一句先申请。
- 不取数、不调模型。
"""

from __future__ import annotations

import re

from forge_core.events import Event
from forge_core.module import ModuleManifest

from factory_issue_module import landed
from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.turn import errors
from factory_issue_module.turn.gate import DomainAccess

# ---------------------------------------------------------------- 寒暄判断（代码规则，§4.2 第 2 步）

_GREETINGS = (
    "你好", "您好", "hi", "hello", "hey", "嗨", "哈喽", "哈啰", "在吗", "在不在", "在么",
    "早", "早安", "早上好", "上午好", "中午好", "下午好", "晚上好",
)
_ASKS_ABOUT_YOU = (
    "你能", "你会", "您能", "您会", "能做什么", "可以做什么", "能干什么", "能干嘛", "能查什么",
    "可以查什么", "能帮我查什么", "怎么用", "如何使用", "怎么使用", "有什么功能", "有哪些功能",
    "你是谁", "您是谁", "你是什么", "介绍一下你", "介绍下你", "自我介绍",
)
_PUNCT = re.compile(r"[\W_]+")
_ONLY_GREETINGS = re.compile(
    "^(?:" + "|".join(sorted((re.escape(g) for g in _GREETINGS), key=len, reverse=True)) + ")+$"
)


def _bare(query: str) -> str:
    """去掉标点、空白与下划线，转小写。"""
    return _PUNCT.sub("", query).lower()


def is_blank(query: str) -> bool:
    """去掉标点与空白后为空（「？？？」「……」、只剩空白）：§4.2 第 2 步由代码先接住，不当寒暄。"""
    return not _bare(query)


def is_greeting(query: str) -> bool:
    """问句去掉标点后是问候语，或含「你能」「能做什么」「怎么用」一类问本助手的说法。空问句不算。"""
    bare = _bare(query)
    if not bare:
        return False
    return bool(_ONLY_GREETINGS.match(bare)) or any(p in bare for p in _ASKS_ABOUT_YOU)


# ---------------------------------------------------------------- 能力介绍

_LABEL_MAX = 15
_DOMAIN_MENTION = {d: re.compile(rf"{d.label}|{d.prefix}\d") for d in DOMAINS}
#: 按钮取这三行的示例问题（§9.4）；可查的域都用不了文字查找时，「类似问题」换成「停线查询」
_BUTTON_SCENES = ("问题单清单", "汇总统计", "类似问题")
_TEXT_SEARCH_SCENE = "类似问题"
_TEXT_SEARCH_FALLBACK = "停线查询"


def _first_sentence(text: str) -> str:
    head, sep, _rest = text.partition("。")
    return head + sep


def _mentioned(example: str) -> set[Domain]:
    return {d for d, pattern in _DOMAIN_MENTION.items() if pattern.search(example)}


def _label(example: str, scene: str) -> str:
    short = example.rstrip("？?。.！! ")
    return short if len(short) <= _LABEL_MAX else scene


def buttons(access: DomainAccess) -> list[dict[str, str]]:
    """能力介绍的 3 个按钮。只用可查的域能问的示例；三域都没有权限时不给按钮（点了也只会答请先申请）。"""
    if access.none:
        return []
    by_name = {s.name: s for s in landed.scenes()}
    names = list(_BUTTON_SCENES)
    if not access.text_search:
        names[names.index(_TEXT_SEARCH_SCENE)] = _TEXT_SEARCH_FALLBACK
    out: list[dict[str, str]] = []
    for name in names:
        scene = by_name[name]
        example = next((e for e in scene.examples if _mentioned(e) <= access.domains), None)
        if example is None:
            continue
        out.append(
            {"id": str(len(out) + 1), "name": name, "label": _label(example, name), "query": example}
        )
    return out


def introduction(manifest: ModuleManifest, access: DomainAccess) -> str:
    lines = [f"您好，我是{manifest.name}，{_first_sentence(manifest.description)}", "", "**常用场景**："]
    lines += [f"- **{s.name}**：{s.answers}" for s in landed.scenes()]
    lines += ["", "**三个域**："]
    scopes = {d.prefix: d.scope for d in landed.domains()}
    for d in DOMAINS:
        note = "" if access.can(d) else f"（{errors.APPLY_TO_VIEW}）"
        lines.append(f"- **{d.label}**（单号 {d.prefix} 开头）：{scopes[d.prefix]}{note}")
    if access.none:
        lines += ["", f"{errors.NO_DOMAIN}。"]
    return "\n".join(lines)


def introduce(manifest: ModuleManifest, access: DomainAccess) -> list[Event]:
    events = [Event.delta(introduction(manifest, access))]
    recs = buttons(access)
    if recs:
        events.append(Event.suggestions(recs))
    return events


#: 对话框里要求润色（润色设计 §13.3）：只认这两个字，「改写」「优化措辞」照常规划（答超出范围或只读请求）
POLISH_WORD = "润色"


def asks_to_polish(query: str) -> bool:
    return POLISH_WORD in query


def polish_in_chat(access: DomainAccess) -> list[Event]:
    """引导到问题单页面的【AI润色】，附能力介绍的按钮（同「超出范围」的答法）；不规划、不取数、不调模型。"""
    events = [Event.delta(errors.POLISH_IN_CHAT)]
    recs = buttons(access)
    if recs:
        events.append(Event.suggestions(recs))
    return events


def not_understood(access: DomainAccess) -> list[Event]:
    """§14：规划超时或修一次仍不合格、以及空问句（§4.2 第 2 步）的答法。

    有可查的域时附能力介绍的 3 个按钮；三域都无权时只有这一句（`buttons` 不给按钮）。
    """
    events = [Event.delta(f"{errors.NOT_UNDERSTOOD}。")]
    recs = buttons(access)
    if recs:
        events.append(Event.suggestions(recs))
    return events
