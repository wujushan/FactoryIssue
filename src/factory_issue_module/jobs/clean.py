"""清洗（设计 §12 第 5 步；`dirty_data.md`「富文本」）：剥净叙述文字、去掉处理步骤内容开头的操作人姓名。

剥净与归一化的写法只有一份，在 `textnorm`（查询期与沙箱也用它）；这里只加治理任务自己的两条：
字数门槛（按意思找不收不超过 10 个字的内容）与去人名前缀（探测 W1 的结论）。
"""

from __future__ import annotations

import re

from factory_issue_module.textnorm import strip_rich

#: 剥净后不超过这么多个字（不算空白）的内容不参与按意思找（总述「比对范围」）
SHORT_LIMIT = 10
#: 姓名后紧跟这些字符之一时连它一起去掉
_NAME_SEPARATORS = "，,：:、"
_WS = re.compile(r"\s+")


def clean(value: object) -> str:
    """富文本 → 剥净的文字（图片、标签都去掉，段落留成换行）；空值为空串。"""
    return strip_rich(value)


def is_short(text: str) -> bool:
    """剥净后不超过 10 个字（不算空白）。"""
    return len(_WS.sub("", text)) <= SHORT_LIMIT


def strip_name(content: str, name: str | None) -> tuple[str, bool]:
    """内容以本条操作人姓名开头时去掉姓名；姓名后紧跟「，」「,」「：」「:」「、」或空白时连这一个分隔符一起去掉。

    姓名不在开头的不动（探测 W1：几乎所有内容都以操作人姓名开头，姓名后多是逗号；责任人确认、预防对策确认
    的姓名后直接接正文，所以不要求后面必须是分隔符）。返回 (内容, 是否去掉了)。
    """
    text = content.lstrip()
    who = (name or "").strip()
    if not who or not text.startswith(who):
        return content, False
    rest = text[len(who):]
    if rest[:1] and (rest[0] in _NAME_SEPARATORS or rest[0].isspace()):
        rest = rest[1:]
    return rest.strip(), True
