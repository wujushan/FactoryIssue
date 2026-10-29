"""问句预匹配：规划之前，代码先读一遍问句，找出能核对的号码与名字，写成一段提示附在问句后。

只报告「这个词在库里是什么」，不建议用哪种查法；条件仍由模型照抄原话填写，代码规划后照常对库。
认号与找名字 S1 起调 src（`factory_issue_module.plan.prematch`），这里只给合成主数据与「附提示」那一组的写法。

- 号码：按总述「按编号查单」的认号表，只看写法（闭集）。
- 名字：在合成主数据（mockdata.py）里找整串相同的名字，只查工厂、部门、人员、机型、系列、供应商、地区说法；
  物料名称不查（存货档案 9.5 万条，「喇叭」这种词会对上一大片）。英文与数字组成的名字前后不能紧挨字母或数字。
  长的优先：「A920PRO」不再报「A920」，号码里的「A35-000-RD6-00E0」不再报机型「A35」。
"""

from __future__ import annotations

from factory_issue_module.plan import prematch as _src

from mockdata import CATALOG

find_numbers = _src.find_numbers


def find_entities(query: str, exclude: list[tuple[int, int]] | None = None) -> list[tuple[str, list[str], tuple[int, int]]]:
    """[(名字, 在库里属于哪几类, 位置)]：整串相同、长的优先、不与号码重叠。"""
    return _src.find_entities(query, CATALOG, exclude)


HEADER = ("【问句里能对上的名称与号码】（程序对照库里的取值找出来的，只说明这些词在库里是什么；"
          "用不用、放进哪个条件由你判断，条件里仍照抄用户的原话）")


def hints(query: str) -> list[str]:
    nums = find_numbers(query)
    lines = [f"- 「{raw}」：" + (kind if kind.startswith("认不出") else f"样子像{kind}") for raw, kind, _ in nums]
    for text, kinds, _ in find_entities(query, [s for *_, s in nums]):
        lines.append(f"- 「{text}」：{'；'.join(kinds)}" + ("（同名）" if len(kinds) > 1 else ""))
    return lines


def hint_text(query: str) -> str | None:
    lines = hints(query)
    return "\n".join([HEADER, *lines]) if lines else None
