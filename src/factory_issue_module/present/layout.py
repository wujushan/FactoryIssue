"""回答骨架与排版（决策 2026-11-03「回答骨架与排版」；总述「先给结论」「一问多段」）。

清单、统计、按文字找单、临时统计的一段按这个顺序：
1. 提示行（有才给）：按什么理解、沿用了哪些条件、哪些域无权或未计入、本次按哪些说法找……一段；
2. 结论：模型写的一段，没写出来时程序的模板句（`turn/execute.py::_narrate`）；
3. 明细：每域（统计每张表）一节，小标题写张数 → 表格与图 → 表格下面一句（没列全、分组的含义）；
4. 结尾（整轮一次）：统计口径或查找说明、导出链接、可点的选项。

表格不带标题：小标题由这里写成正文，实时显示与落库回读是同一个样子（平台把表格标题投影成粗体一行，
INFO 前端实时显示时怎么画表格标题不由本助手定）。

块之间的空行只在这里放（`Spacer`）：各处产出的正文不必管前后要不要空行。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from forge_core.events import Event, EventType

#: 一问多段的段标题："heading" 为 `### 1. …`，"bold" 为 `**1. …**`。开发者 2026-11-03 看样例后选三级标题：
#: 段标题比各域小标题（粗体）高一级，几段一起时看得出层次
SECTION_STYLE: Literal["bold", "heading"] = "heading"
#: 结尾（统计口径 / 查找说明）前加一条分隔线，把结论与明细和口径分开（开发者 2026-11-03 定）
FOOT_RULE = True

_BREAK = "\n\n"


def section_title(i: int, title: str) -> str:
    """一问多段的段标题。"""
    text = f"{i}. {title}"
    return f"### {text}" if SECTION_STYLE == "heading" else f"**{text}**"


def heading(text: str) -> Event:
    """一节的小标题（各域、各表）：写这一节是什么、有几张。"""
    return Event.delta(f"**{text}**")


def sentences(parts: Iterable[str]) -> str:
    """几句话合成一段：去重、去掉各句末尾的句号再用「。」连起来；没有内容时为空串。"""
    kept = list(dict.fromkeys(p.strip().rstrip("。") for p in parts if p and p.strip().rstrip("。")))
    return "。".join(kept) + "。" if kept else ""


def para(parts: Iterable[str]) -> list[Event]:
    """一段正文（提示行、表格下面那句）：没有内容时不出块。"""
    text = sentences(parts)
    return [Event.delta(text)] if text else []


def foot(text: str) -> str:
    """结尾那一段（统计口径 / 查找说明）。分隔线前面一定有空行（`Spacer` 给的）：紧贴在一段文字下面的 `---` 会把
    那段文字变成标题（Markdown 的 setext 标题）。"""
    return f"---{_BREAK}{text}" if FOOT_RULE else text


class Spacer:
    """一轮里块与块之间放一个空行。

    - 每段正文去掉前后的空行；只有空白的正文丢掉；
    - 本轮已经发过东西时，正文前面加一个空行。

    表格、图与其他事件原样放行：平台把表格、图投影进落库正文时前后各自带一个空行（`forge_platform.tables`、
    `charts` 的投影函数），这里不再补。只在 `turn/execute.py::run` 用：那里是一轮正文的唯一出口。
    """

    def __init__(self) -> None:
        self.started = False

    def __call__(self, events: Sequence[Event]) -> list[Event]:
        out: list[Event] = []
        for ev in events:
            if ev.type is not EventType.DELTA:
                out.append(ev)
                if ev.type in (EventType.TABLE, EventType.CHART):
                    self.started = True
                continue
            text = str(ev.data.get("text") or "").strip("\n")
            if not text.strip():
                continue
            out.append(Event.delta((_BREAK if self.started else "") + text, source=ev.source))
            self.started = True
        return out
