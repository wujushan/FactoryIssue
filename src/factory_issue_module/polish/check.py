"""程序检查与修一次的说明（润色设计 §9）。

模型输出的 JSON 解析自己写一份，不复用 `plan.schema.parse_reply`（§9，评审 2026-11-10 第 12 条）。
逻辑照 r1、r2 实测时的 `scripts/polish_spike/polish_core.py`（`e773011` 及之前的版本）搬来，只改结构与命名；
此后实测工具反过来调这里。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from factory_issue_module.polish.rich import Prepared, assemble, english_only, has_cjk, mark_re, strip_marks, \
    text_chars
from factory_issue_module.textnorm import to_halfwidth

_THINK = re.compile(r"<think>.*?</think>", re.S)
#: 不贴着字母与数字的数（同 `present/narrative._NUM` 的写法）
_NUM = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_CODE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9\-_./]*")
_WORD = re.compile(r"(?<![A-Za-z])[A-Za-z]{2,}(?![A-Za-z])")
#: 每行开头的分条序号：`1.`、`2、`、`（1）`、`①`
_NUMBERING = re.compile(r"^\s*(?:[（(]\s*\d{1,2}\s*[)）]|\d{1,2}\s*[.、．)）](?!\d)|[①-⑳])\s*")
_PREFACE = ("以下是", "润色后", "好的", "润色结果")

# 检查项（§9 表的编号；日志 `failed_checks` 记它）
CHECK_FORMAT = "1 格式"
CHECK_MARKS = "2 占位"
CHECK_ADDED = "3 多出"
CHECK_REMOVED = "4 缺少"
CHECK_LENGTH = "5 长度"
CHECK_PREFACE = "6 说明"
CHECK_LANG = "7 语言"
#: 第 5 项：原文不足这么多字时，上限放宽为原文加 `SHORT_SLACK` 字
SHORT_INPUT = 50
SHORT_SLACK = 20


def parse_reply(content: str) -> str | None:
    """去掉 `<think>`，取第一个 `{` 到最后一个 `}`，要 `text` 是字符串。"""
    body = _THINK.sub("", content or "")
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(body[start:end + 1])
    except ValueError:
        return None
    text = data.get("text") if isinstance(data, dict) else None
    return text if isinstance(text, str) else None


def _norm_num(s: str) -> str:
    """按数值比：`01` 与 `1`、`1.50` 与 `1.5` 相同。"""
    if "." in s:
        whole, frac = s.split(".", 1)
        whole, frac = whole.lstrip("0") or "0", frac.rstrip("0")
        return whole if not frac else f"{whole}.{frac}"
    return s.lstrip("0") or "0"


def mostly_chinese(text: str) -> bool:
    """汉字数不少于英文词数：中文句子里夹几个英文术语（PL-07）算中文，整段英文（PL-08）不算。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk > 0 and cjk >= len(_WORD.findall(text))


def facts(text: str, style: tuple[str, str], words: bool) -> dict[str, set[str]]:
    """数字（按数值）、编码（逐字）、英文词（不分大小写，只在 `words` 为真时）。每行开头的分条序号不算。"""
    flat = to_halfwidth(strip_marks(text, style))
    flat = "\n".join(_NUMBERING.sub("", ln, count=1) for ln in flat.split("\n"))
    nums = {_norm_num(m.group(0)) for m in _NUM.finditer(flat)}
    codes = set()
    for m in _CODE.finditer(flat):
        tok = m.group(0).rstrip("-_./")
        if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok):
            codes.add(tok)
    ws = {m.group(0).lower() for m in _WORD.finditer(flat)} if words else set()
    return {"数字": nums, "编码": codes, "英文": ws}


@dataclass
class Verdict:
    ok: bool
    failed: list[str] = field(default_factory=list)
    #: 不过的细节（给修一次的说明用；含原文里的数字与编码，不进日志）
    detail: dict[str, Any] = field(default_factory=dict)
    #: 解析出的正文（去掉了开头单独一行的栏目名）
    text: str | None = None
    #: 拼回后的整段（§6.3）
    output: str | None = None


def _head(line: str) -> str:
    return line.strip().rstrip("：:").strip()


def check(content: str, prep: Prepared, field_name: str) -> Verdict:
    """§9 的七项，全部通过才 `ok`。`field_name` 是这一栏在规则里的名称（第 6 项去掉栏目名标题用）。"""
    split = prep.split
    text = parse_reply(content)
    if text is None or text_chars(text, split.style) == 0:
        return Verdict(ok=False, failed=[CHECK_FORMAT], detail={"格式": "不是 {\"text\": …} 或正文为空"})
    v = Verdict(ok=True, text=text)
    # 第一行单独是这一栏的名称（「原因分析：」）而原文第一行不是：程序去掉这一行，不算不过。r2 实测 PL-12
    # 「有三个原因：一是…」3 次都改成以「原因分析：」开头，修一次也照旧，提示管不住（§9 第 6 项、§12.3）
    lines = text.strip().split("\n")
    if len(lines) > 1 and _head(lines[0]) == field_name and _head(split.text.split("\n")[0]) != field_name:
        v.detail["去掉的标题"] = lines[0].strip()
        text = "\n".join(lines[1:])
        v.text = text
    want = [m for m, _ in split.tokens]
    got = [m.group(0) for m in mark_re(split.style).finditer(text)]
    if got != want:
        v.failed.append(CHECK_MARKS)
        v.detail["占位"] = {"应有": want, "实际": got}
    words = mostly_chinese(split.text)
    src, out = facts(split.text, split.style, words), facts(text, split.style, words)
    added = {k: sorted(out[k] - src[k]) for k in src if out[k] - src[k]}
    removed = {k: sorted(src[k] - out[k]) for k in src if src[k] - out[k]}
    if added:
        v.failed.append(CHECK_ADDED)
        v.detail["多出"] = added
    if removed:
        v.failed.append(CHECK_REMOVED)
        v.detail["缺少"] = removed
    assembled = assemble(text, split)
    v.output = assembled
    limit = prep.limit
    n_in, n_out = prep.input_chars, text_chars(text, split.style)
    if limit is not None and len(assembled) > limit:
        v.failed.append(CHECK_LENGTH)
        v.detail["长度"] = f"整段 {len(assembled)} 字符，超过上限 {limit}"
    elif n_in >= SHORT_INPUT and not (n_in * 0.5 <= n_out <= n_in * 2):
        v.failed.append(CHECK_LENGTH)
        v.detail["长度"] = f"正文 {n_out} 字，原文 {n_in} 字，超出一半到两倍"
    elif n_in < SHORT_INPUT and n_out > n_in + SHORT_SLACK:
        v.failed.append(CHECK_LENGTH)
        v.detail["长度"] = f"正文 {n_out} 字，原文只有 {n_in} 字"
    if text.strip().startswith(_PREFACE):
        v.failed.append(CHECK_PREFACE)
        v.detail["说明"] = "开头是说明"
    if english_only(split.text, split.style) and has_cjk(strip_marks(text, split.style)):
        v.failed.append(CHECK_LANG)
        v.detail["语言"] = "原文是英文，结果里有中文"
    v.ok = not v.failed
    return v


def repair(v: Verdict, prep: Prepared) -> str:
    """修一次的说明（§9 表的第三列），只写不过的几项。"""
    lines = ["上面的输出不合格："]
    d = v.detail
    if CHECK_FORMAT in v.failed:
        lines.append('- 请只输出 {"text": "润色后的全文"}，正文不能为空')
    if CHECK_MARKS in v.failed:
        lines.append(f"- 标记要与原文一致、按原文顺序各出现一次：{'、'.join(d['占位']['应有']) or '（原文没有标记）'}")
    if CHECK_ADDED in v.failed:
        lines.append(f"- 多出了原文没有的：{'、'.join(x for xs in d['多出'].values() for x in xs)}。数字照原文的写法，不补原文没有的内容")
    if CHECK_REMOVED in v.failed:
        lines.append(f"- 少了原文里的：{'、'.join(x for xs in d['缺少'].values() for x in xs)}。原文的内容不能删")
    if CHECK_LENGTH in v.failed:
        if prep.k is not None and "超过上限" in str(d.get("长度")):
            lines.append(f"- 太长了，正文请精简到 {prep.k} 字以内")
        else:
            lines.append("- 改动太大，请只润色，不删减、不扩写")
    if CHECK_PREFACE in v.failed:
        lines.append("- 只输出润色后的正文，不要开头的说明，也不要以这一栏的名称作标题")
    if CHECK_LANG in v.failed:
        lines.append("- 原文是英文，请用英文润色，不要翻译成中文")
    lines.append('请按要求重新输出，只输出 {"text": "…"}。')
    return "\n".join(lines)
