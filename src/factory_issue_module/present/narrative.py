"""结论段与核数（设计 §8.3、§1.3「写分析」）。

写结论的提示由这里持有（S2 起），`scripts/planner_spike/` 反过来 import：`narrative_user` 的拼法与核数 `check` 从
spike 搬来。2026-11-03 起这一段是回答最前面的结论，由它一个作者写，程序的模板句只作退路（决策 2026-11-03
「回答骨架与排版」）：提示改了开头与第 1、7 条，加了第 8、9 条；spike 的写分析一项要重跑才知道分数。

- 输入：用户问题、表格的说明、程序写在上面的提示行（【说明】）、`facts`（沙箱产出，列表已附项数）；按文字找单另有
  每域前几张单的内容（【列出的单】）与这类问法的写法（【写法】）。类似问题的 system 不带分析维度（`dims=False`）。
- 问「哪个最多」时第一名（并列的全部）必须点到（`must`），没点全按不合格重写一次。
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

NARRATIVE_MODULE_SYSTEM = """你是「制程问题查询助手」的回答撰写人。程序已经查好数据、算好数字。你写回答最前面的一段结论，程序会在它下面接着给出各域的表格、图表和统计口径。

要求：
1. 第一句直接回答用户的问题：有没有、有几张、哪个最多、是否增加。各域的张数程序会写在各域表格的小标题上，不要逐域报张数；需要时说合计，或点名最多的域。
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
7. 【说明】是程序已经写在你这段上面的提示（如按什么理解、哪个域没计入），不要重复，但结论要与它一致。
8. 有【列出的单】时，点名的问题编号从里面挑；不要引用单上文字里的数字和日期。
9. 有【写法】时按【写法】写。"""

#: 结论句与要点（决策 2026-11-03「结论的要点与需关注的单」）：要点是程序挑好、算好的，模型只照着写成句子；
#: 需关注的单由程序写。不拼 `analysis_section`：分析什么由程序按「结论里的要点」判断，不让模型照维度自由发挥
POINTS_SYSTEM = """你是「制程问题查询助手」的回答撰写人。程序已经查好数据、算好数字，并挑出了这次值得说的几点（【要点】）。你写回答最前面的结论；程序会在它下面接着给出需关注的单、各域的表格和统计口径。

只写下面两部分，不写别的：
- 第一行：一句话结论，前后用 ** 加粗。直接回答用户的问题：有没有、合计几张、未结案几张、哪个最多、是否增加。
- 之后每行一条要点，以「- 」开头，接着写这一项的「名称」和冒号。【要点】里有几项就写几条，按顺序一项一条，每条只写那一项里的内容。【要点】为空时只写第一行。

要求：
1. 只能使用【事实】【要点】里出现的数字，不自己做任何计算：不求和、不求差、不算百分比、不数行数。下面几种也算自己计算，不要写：
   - 把几项加起来说（「两类合计七成以上」「后三类不足四分之一」）；
   - 自己定一个整数当门槛（「连续三个月 30 单以上」「均超过 10 单」「超过一半」）；
   - 换算单位（把「91 天及以上」说成「超过三个月」）；
   - 「一半」「三成」「翻倍」「几个百分点」这类约数与比值，【事实】【要点】里没有同样的说法就不写；
   - 日期只用【事实】【要点】里的年、月、日，不写「中旬」「月初」这类更细的说法。
2. 不写【要点】里没有的发现。不把几张单的文字归纳成共同点（如「均涉及天线装配或来料不良」），不推测原因，不评价，不给建议。点名的机型、工厂、部门、供应商只用【事实】【要点】里出现过的。
3. 第一行不逐域报张数（各域张数程序写在小标题上），需要时说合计或点名最多的域。
4. 用业务说法，不出现英文代码、数据库表名或字段名。
5. 不写统计口径，不写需关注的单，程序会另附。
6. 【说明】是程序已经写在你这段上面的提示（如按什么理解、哪个域没计入），不要重复，但结论要与它一致。"""

_CHAT_KW: dict[str, Any] = {"temperature": 0.2}


def narrative_system(manifest: ModuleManifest, *, dims: bool = True) -> str:
    """system 串只随 manifest 的分析维度变（§5.6：不放日期、用户、权限）。`dims=False`：不按分析维度分析的问法
    （类似问题，决策 2026-11-03「回答骨架与排版」），另一份固定的 system。"""
    return NARRATIVE_MODULE_SYSTEM + ("\n\n" + analysis_section(manifest) if dims else "")


def narrative_user(question: str, table: str | None, note: str | None, facts: Any, *, rows: str | None = None,
                   guide: str | None = None) -> str:
    parts = [f"【用户问题】{question}"]
    if table:
        parts.append(f"【已展示的表格】{table}")
    if note:
        parts.append(f"【说明】{note}")
    if rows:
        parts.append(f"【列出的单】\n{rows}")
    if guide:
        parts.append(f"【写法】{guide}")
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
          entities: Mapping[str, Sequence[str]], rows: str | None = None) -> dict:
    """逐句核数。`entities` 是「名字 → 在库里属于哪几类」（本轮可查的域的主数据；spike 传它的合成主数据）。

    `rows` 是交给模型看的单的内容（【列出的单】）：只用来核点名的问题编号与机型、工厂等名称，不放行其中的数字与日期
    （单上的文字里什么数都有，放行了就核不住模型自己数出来的张数）。"""
    allowed = allowed_numbers(question, note, table, facts)
    max_rank = max(_list_lengths(facts), default=0)
    body = _THINK.sub("", text or "")
    sentences = [s for s in re.split(r"[。！？；\n]+", body) if s.strip()]
    raw_source = _source(question, note, table, facts)
    source = (raw_source + " " + (rows or "")).upper()
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
                facts: Any, entities: Mapping[str, Sequence[str]], fallback: str, *, rows: str | None = None,
                guide: str | None = None, dims: bool = True, must: Sequence[str] = ()) -> str:
    """一段结论。核数不过的句子删掉；删了首句、剩不到 2 句，或 `must` 里的名字没点全时重写一次；仍不行用 `fallback`。

    `must`：结论必须点到的名字（问「哪个最多」时的第一名，并列的全部，总述「排名、长清单与导出」）。"""
    if llm is None:
        return fallback
    messages = [{"role": "system", "content": narrative_system(manifest, dims=dims)},
                {"role": "user", "content": narrative_user(question, table, note, facts, rows=rows, guide=guide)}]
    for attempt in (1, 2):
        try:
            text = _content(await llm.chat(messages, **_CHAT_KW))
        except Exception as exc:  # noqa: BLE001 —— 模型出错走模板句，异常只进日志
            logger.warning("factory_issue_narrative_failed", attempt=attempt, error=type(exc).__name__)
            return fallback
        result = check(question, note, table, facts, text, entities, rows)
        kept, n = _kept_text(text, result)
        missed = [m for m in must if m and m not in kept]
        if not result["first_bad"] and n >= 2 and not missed:
            if result["bad"]:
                logger.info("factory_issue_narrative_dropped", sentences=len(result["bad"]))
            return kept
        logger.info("factory_issue_narrative_rejected", attempt=attempt, bad=len(result["bad"]), missed=len(missed))
        wrong = "；".join(f"「{b['句子']}」里的「{'、'.join(map(str, b['事实里没有的数']))}」" for b in result["bad"])
        if wrong:
            ask = f"下面这些在【事实】里找不到，请只用【事实】里的数字和名称重写整段：{wrong}"
        elif missed:
            ask = f"第一句要点名最多的：{'、'.join(missed)}（并列的都要点到）。请重写整段。"
        else:
            ask = "请按要求写 3 到 6 句，第一句直接回应用户的问题。"
        messages = [*messages[:2], {"role": "assistant", "content": text}, {"role": "user", "content": ask}]
    return fallback


# ---------------------------------------------------------------------------- 结论句与要点（决策 2026-11-03「结论的要点与需关注的单」）


def points_user(question: str, table: str | None, note: str | None, facts: Any, points: Sequence[Any]) -> str:
    return narrative_user(question, table, note, facts) + "\n【要点】" + json.dumps(list(points), ensure_ascii=False)


_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.、])\s*")


def _split(text: str) -> tuple[str, list[str]]:
    """模型写的 → (第一行, 各条要点)。第一行之后不以列表记号开头的行（如它自己写的「需关注」）不要。"""
    lines = [ln.strip() for ln in _THINK.sub("", text or "").splitlines() if ln.strip()]
    if not lines:
        return "", []
    head, rest = lines[0], lines[1:]
    if _BULLET.match(head) and not head.startswith("**"):
        return "", []
    return head, [_BULLET.sub("", ln, count=1) for ln in rest if _BULLET.match(ln) and not ln.startswith("**")]


def _body(item: str, name: str) -> str:
    """一条要点去掉开头的「名称：」与粗体记号，剩下的内容。"""
    core = item.replace("**", "").strip()
    for sep in ("：", ":"):
        if core.startswith(name + sep):
            return core[len(name) + 1:].strip()
    return core


def _ok(question: str, note: str | None, table: str | None, facts: Any, text: str,
        entities: Mapping[str, Sequence[str]]) -> tuple[bool, list[dict]]:
    if not text.strip():
        return False, []
    result = check(question, note, table, facts, text, entities)
    return not result["bad"] and not result["leaks"], result["bad"]


async def write_points(llm: Any, question: str, table: str | None, note: str | None, facts: Any,
                       points: Sequence[Mapping[str, Any]], entities: Mapping[str, Sequence[str]], fallback: str,
                       *, must: Sequence[str] = ()) -> tuple[str, list[str]]:
    """结论句（加粗）与各条要点。

    - 结论句逐句核数，`must` 里的名字（问「哪个最多」时的第一名）要点全；不过时带着错处重写一次，仍不过用 `fallback`。
    - 要点逐条核：模型写的条数与【要点】项数一样时一条对一条，不合格的那一条换成程序的模板句（`point_text`）；
      条数对不上时全部用模板句。模型调用出错时结论句用 `fallback`、要点用模板句。"""
    from factory_issue_module.present import insights

    templates = [insights.point_text(p) for p in points]
    head_fallback = insights.bold(fallback)
    if llm is None:
        return head_fallback, templates
    scope = {**facts, "要点": list(points)} if isinstance(facts, dict) else {"事实": facts, "要点": list(points)}
    messages = [{"role": "system", "content": POINTS_SYSTEM},
                {"role": "user", "content": points_user(question, table, note, facts, points)}]
    bullets = templates
    for attempt in (1, 2):
        try:
            text = _content(await llm.chat(messages, **_CHAT_KW))
        except Exception as exc:  # noqa: BLE001 —— 模型出错走模板句，异常只进日志
            logger.warning("factory_issue_narrative_failed", attempt=attempt, error=type(exc).__name__)
            return head_fallback, bullets
        head, items = _split(text)
        if len(items) == len(points):
            got = []
            for item, point, template in zip(items, points, templates, strict=True):
                name = str(point.get("名称") or point.get("发现"))
                body = _body(item, name)
                good, _bad = _ok(question, note, table, scope, body, entities)
                got.append(insights.bullet(name, body) if good and body else template)
            dropped = sum(1 for g, t in zip(got, templates, strict=True) if g == t)
            if dropped:
                logger.info("factory_issue_points_templated", points=dropped)
            bullets = got
        else:
            logger.info("factory_issue_points_count_mismatch", written=len(items), expected=len(points))
            bullets = templates
        core = head.replace("**", "").strip()
        good, bad = _ok(question, note, table, scope, core, entities)
        missed = [m for m in must if m and m not in core]
        if good and not missed:
            return insights.bold(core), bullets
        logger.info("factory_issue_narrative_rejected", attempt=attempt, bad=len(bad), missed=len(missed))
        wrong = "；".join(f"「{b['句子']}」里的「{'、'.join(map(str, b['事实里没有的数']))}」" for b in bad)
        if wrong:
            ask = f"第一行里这些在【事实】【要点】里找不到，请只用里面的数字和名称重写：{wrong}"
        elif missed:
            ask = f"第一行要点名最多的：{'、'.join(missed)}（并列的都要点到）。请重写。"
        else:
            ask = "请按要求重写：第一行是加粗的一句结论，之后每条要点一行。"
        messages = [*messages[:2], {"role": "assistant", "content": text}, {"role": "user", "content": ask}]
    return head_fallback, bullets
