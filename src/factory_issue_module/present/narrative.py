"""分析段与核数（设计 §8.3、§1.3「写分析」）。

写分析提示由这里持有（S2 起），`scripts/planner_spike/` 反过来 import：提示原文、`narrative_user` 的拼法与核数
`check` 都从 spike 逐字搬来，搬过来之后 spike 的自检与离线重算分数不变（任务单 S2）。

- 输入：用户问题、已展示表格的说明、代码的说明（「按 X 理解」）、`facts`（沙箱产出，列表已附项数）。
- 核数逐句做：数、约数与比值、日期、点名的问题编号与机型 / 系列 / 工厂 / 部门 / 供应商都要能在事实、表格、问句里
  找到（§8.3）。「前 N 名」不查；「第 N 名」N 不超过事实里最长的列表时不查；「A 和 B 两类」不查；「这三张」照查；
  「这 / 那 + 两」本句前文用「和」「与」「、」点过名时不查。
- 不合格的句子删掉；删了第一句或剩不到 2 句时带着错处重写一次；仍不合格就用调用方给的模板句（数字取自 `facts`）。
- 温度 0.2，与写分析实测（`20261028-n2-fast`）相同；模型调用出错也走模板句。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from forge_core.module import ModuleManifest
from forge_core.prompting import analysis_section

from factory_issue_module.plan.prematch import find_entities

logger = structlog.get_logger(__name__)

NARRATIVE_MODULE_SYSTEM = """你是「制程问题查询助手」的回答撰写人。程序已经查好数据、算好数字，并已把表格和图表展示给用户。你只写表格下面的一段分析文字。

要求：
1. 第一句直接回应用户的问题：有几张、有没有、哪个最多、是否增加。
2. 只能使用【事实】里出现的数字，不自己做任何计算：不求和、不求差、不算百分比、不数行数。事实里没有的数字就不说。下面几种也算自己计算，不要写：
   - 把几项加起来说（「两类合计七成以上」「后三类不足四分之一」）；
   - 自己定一个整数当门槛（「连续三个月 30 单以上」「均超过 10 单」「超过一半」）；
   - 换算单位（把「91 天及以上」说成「超过三个月」）。
   要说集中程度时，用【事实】里给的占比或合计；没有就只说「主要集中在物料问题和硬件问题」，不带数。
   - 「一半」「三成」「翻倍」「几个百分点」这类约数与比值，【事实】里没有同样的说法就不写；
   - 日期只用【事实】里的年、月、日，不写「中旬」「月初」这类更细的说法。
3. 说重点：集中在哪、最需要关注的是哪几张（点名问题编号）、一句结论。不要把表格逐行复述。点名的机型、系列、工厂、部门只用【事实】或表格里出现过的，不自己归纳（如把几个机型说成「A 系列」）。
4. 用业务说法，不出现英文代码、数据库表名或字段名。
5. 不写统计口径，程序会另附。
6. 写 3 到 6 句话，不用标题，不用列表，不用 Markdown。
7. 【说明】里有程序做过的调整（如放宽了时间范围、按什么理解），要在开头一句说清楚。"""

_CHAT_KW: dict[str, Any] = {"temperature": 0.2}


def narrative_system(manifest: ModuleManifest) -> str:
    """system 串只随 manifest 的分析维度变（§5.6：不放日期、用户、权限）。"""
    return NARRATIVE_MODULE_SYSTEM + "\n\n" + analysis_section(manifest)


def narrative_user(question: str, table: str | None, note: str | None, facts: Any) -> str:
    parts = [f"【用户问题】{question}"]
    if table:
        parts.append(f"【已展示的表格】{table}")
    if note:
        parts.append(f"【说明】{note}")
    parts.append("【事实】" + json.dumps(facts, ensure_ascii=False))
    return "\n".join(parts)


# ---------------------------------------------------------------------------- 核数（自 spike 逐字搬来）

_THINK = re.compile(r"<think>.*?</think>", re.S)
_NUM = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_CN_NUM = re.compile(r"([两三四五六七八九十][零一二两三四五六七八九十]*)(?=[张个条起项家类次天倍名成])")
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_LEAK = re.compile(r"[A-Za-z]+_[A-Za-z0-9_]+|dbo\.|\bSELECT\b|\bFROM\s", re.I)
_ISSUE_NO = re.compile(r"(?<![A-Za-z0-9])(?:ZC|BR|HW)\d{7}(?![0-9])", re.I)


def _cn_to_int(s: str) -> int | None:
    if "十" not in s:
        return _CN_DIGIT.get(s) if len(s) == 1 else None
    left, _, right = s.partition("十")
    tens = _CN_DIGIT.get(left, 1) if left else 1
    ones = _CN_DIGIT.get(right, 0) if right else 0
    return tens * 10 + ones


def _list_lengths(obj: Any) -> set[int]:
    """事实里每个列表的项数（沙箱模板已附在 facts 里，这里与 spike 一样再从列表本身数一遍）。"""
    out: set[int] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _list_lengths(v)
    elif isinstance(obj, list):
        out.add(len(obj))
        for v in obj:
            out |= _list_lengths(v)
    return out


def _source(question: str, note: str | None, table: str | None, facts: Any) -> str:
    return " ".join([question, note or "", table or "", json.dumps(facts, ensure_ascii=False)])


def allowed_numbers(question: str, note: str | None, table: str | None, facts: Any) -> set[float]:
    """问句、说明、表格、事实里出现过的数，阿拉伯数字与汉字数（「三个域」）都算；事实里各列表的项数也算。"""
    text = _source(question, note, table, facts)
    allowed = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)}
    allowed |= {float(v) for v in (_cn_to_int(x) for x in _CN_NUM.findall(text)) if v is not None}
    allowed |= {float(n) for n in _list_lengths(facts)}
    return allowed


_CN_NUM_CLAIM = re.compile(r"(?<![这那])" + _CN_NUM.pattern)
_CN_NUM_AFTER_DEM = re.compile(r"(?<=[这那])([两三四五六七八九十][零一二两三四五六七八九十]*)(?=[张个条起项家类次天倍名成])")


def _demonstrative_values(plain: str) -> list[int]:
    out = []
    for m in _CN_NUM_AFTER_DEM.finditer(plain):
        if m.group(1) == "两" and re.search(r"[和与、]", plain[:m.start()]):
            continue
        v = _cn_to_int(m.group(1))
        if v is not None:
            out.append(v)
    return out


_APPROX = re.compile(r"[\d一二两三四五六七八九十]+(?:\.\d+)?\s*(?:倍|成(?![为功本品果立员熟型绩长交都分])|个?百分点)"
                     r"|翻倍|翻了?[一两]?[番倍]|(?:一|过|近|大|超过?|将近|接近)半(?![年月天])|半数|[上中下]旬")
_DATE_TOKEN = re.compile(r"(\d{4})\s*年|(\d{1,2})\s*月(?:\s*(\d{1,2})\s*[日号])?")
_SRC_DATE = re.compile(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?")
_SRC_RANGE = re.compile(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?\s*(?:至|到|~|-)\s*(\d{4})-(\d{1,2})")
_ENTITY_KINDS = ("机型", "系列", "加工厂", "部门", "供应商")


def _date_sources(source: str) -> tuple[set[int], set[int], set[int]]:
    years = {int(y) for y in re.findall(r"(\d{4})\s*年", source)}
    months = {int(m) for m in re.findall(r"(?<!\d)(\d{1,2})\s*月", source)}
    days = {int(d) for d in re.findall(r"(?<!\d)(\d{1,2})\s*[日号]", source)}
    for y, m, d in _SRC_DATE.findall(source):
        years.add(int(y))
        months.add(int(m))
        if d:
            days.add(int(d))
    for y1, m1, y2, m2 in _SRC_RANGE.findall(source):
        start, end = int(y1) * 12 + int(m1) - 1, int(y2) * 12 + int(m2) - 1
        for k in range(start, min(end, start + 36) + 1):
            years.add(k // 12)
            months.add(k % 12 + 1)
    return years, months, days


_ORDINAL = re.compile(r"前\s*(?:\d+|[两三四五六七八九十]+)\s*[名位]")
_NTH = re.compile(r"第\s*(\d+|[一二两三四五六七八九十]+)\s*[名位]")
_ENUM_TWO = re.compile(r"([^，。；]*[和与、][^，。；]*?)两(?=[个类张家项名])")


def _ordinal_free(sentence: str, max_rank: int = 0) -> str:
    def nth(m: re.Match) -> str:
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else _cn_to_int(raw)
        return "" if n is not None and 1 <= n <= max_rank else m.group(0)

    return _ENUM_TWO.sub(r"\1", _NTH.sub(nth, _ORDINAL.sub("", sentence)))


def check(question: str, note: str | None, table: str | None, facts: Any, text: str,
          entities: Mapping[str, Sequence[str]]) -> dict:
    """逐句核数。`entities` 是「名字 → 在库里属于哪几类」（本轮可查的域的主数据；spike 传它的合成主数据）。"""
    allowed = allowed_numbers(question, note, table, facts)
    max_rank = max(_list_lengths(facts), default=0)
    body = _THINK.sub("", text or "")
    sentences = [s for s in re.split(r"[。！？；\n]+", body) if s.strip()]
    raw_source = _source(question, note, table, facts)
    source = raw_source.upper()
    years, months, days = _date_sources(raw_source)
    with_numbers, bad = 0, []
    for s in sentences:
        found: list[Any] = []
        for m in _DATE_TOKEN.finditer(s):
            y, mo, d = m.group(1), m.group(2), m.group(3)
            if (y and int(y) not in years) or (mo and int(mo) not in months) or (d and int(d) not in days):
                found.append(m.group(0).replace(" ", ""))
        plain = _DATE_TOKEN.sub(" ", s)
        free = _ordinal_free(plain, max_rank)
        values = [float(x) for x in _NUM.findall(free)]
        values += [v for v in (_cn_to_int(x) for x in _CN_NUM_CLAIM.findall(free)) if v is not None]
        values += _demonstrative_values(plain)
        if values or _DATE_TOKEN.search(s):
            with_numbers += 1
        found += [v for v in values if not any(abs(v - a) < 1e-9 for a in allowed)]
        found += [m.group(0) for m in _APPROX.finditer(s) if m.group(0) not in raw_source]
        if found:
            bad.append({"句子": s.strip(), "事实里没有的数": found})
    for s in sentences:
        fake = [n for n in _ISSUE_NO.findall(s) if n.upper() not in source]
        fake += [name for name, kinds, _ in find_entities(s, entities)
                 if any(k.startswith(_ENTITY_KINDS) or k.endswith("加工厂") for k in kinds)
                 and name.upper() not in source]
        if fake:
            bad.append({"句子": s.strip(), "事实里没有的数": fake})
    bad_set = {b["句子"] for b in bad}
    first_bad = bool(sentences) and sentences[0].strip() in bad_set
    return {"sentences": len(sentences), "with_numbers": with_numbers, "bad": bad,
            "leaks": _LEAK.findall(body), "chars": len(body),
            "first_bad": first_bad, "left": len(sentences) - len(bad_set)}


# ---------------------------------------------------------------------------- 线上：写、核、删、重写一次、模板句

_PIECES = re.compile(r"[^。！？；\n]+[。！？；]?")


def _kept_text(text: str, result: dict) -> tuple[str, int]:
    bad = {b["句子"] for b in result["bad"]} | ({"__leak__"} if result["leaks"] else set())
    kept = []
    for piece in _PIECES.findall(_THINK.sub("", text or "")):
        core = re.sub(r"[。！？；]$", "", piece).strip()
        if not core:
            continue
        if core in bad or _LEAK.search(core):
            continue
        kept.append(piece.strip())
    return "".join(kept), len(kept)


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


async def write(llm: Any, manifest: ModuleManifest, question: str, table: str | None, note: str | None,
                facts: Any, entities: Mapping[str, Sequence[str]], fallback: str) -> str:
    """一段分析。核数不过的句子删掉；删了首句或剩不到 2 句时重写一次；仍不行用 `fallback`。"""
    if llm is None:
        return fallback
    messages = [{"role": "system", "content": narrative_system(manifest)},
                {"role": "user", "content": narrative_user(question, table, note, facts)}]
    for attempt in (1, 2):
        try:
            text = _content(await llm.chat(messages, **_CHAT_KW))
        except Exception as exc:  # noqa: BLE001 —— 模型出错走模板句，异常只进日志
            logger.warning("factory_issue_narrative_failed", attempt=attempt, error=type(exc).__name__)
            return fallback
        result = check(question, note, table, facts, text, entities)
        kept, n = _kept_text(text, result)
        if not result["first_bad"] and n >= 2:
            if result["bad"]:
                logger.info("factory_issue_narrative_dropped", sentences=len(result["bad"]))
            return kept
        logger.info("factory_issue_narrative_rejected", attempt=attempt, bad=len(result["bad"]))
        wrong = "；".join(f"「{b['句子']}」里的「{'、'.join(map(str, b['事实里没有的数']))}」" for b in result["bad"])
        ask = (f"下面这些在【事实】里找不到，请只用【事实】里的数字和名称重写整段：{wrong}" if wrong
               else "请按要求写 3 到 6 句，第一句直接回应用户的问题。")
        messages = [*messages[:2], {"role": "assistant", "content": text}, {"role": "user", "content": ask}]
    return fallback
