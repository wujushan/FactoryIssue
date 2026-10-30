"""时间说法换算（设计 §6.1「日期」、§5.3 第 14、17 条；总述「时间说法怎么换算」）。纯函数。

- 规划器只照抄用户的时间原话（`said`），这里按总述的规则换成起止日期：开发者 2026-10-27 定，这是参数换算，
  与把机型名对到库里的取值同类，不算越过数字红线。统计口径里打印的起止日期也由这里给（`describe`）。
- 滚动窗口「最近 N 天」含今天，取数写 `GE {"$relative": "-(N-1)d"}`（`$relative` 的日单位对齐到当天 0 点）；
  「最近 / 近 N 周」按 7N 天、「最近 / 近 N 个月」按 30N 天、「近 N 年」按 365N 天、「近半年」「近半个月」
  按 180、15 天、只说「最近」按 30 天。
- 自然期间（今年、上个月、2026 年上半年、Q2、本周……）`$relative` 表达不了，换成起止日期字面量。
  没写年份的月份、季度、半年指今年的；今年这一段还没到时指去年的。期间没结束时止于今天（「截至今天」）。
  写明了年份、整段都还没到的照原样给起止并标 `future`，查不到单时答这段时间还没到，不追问（G77）。
- 起止说法（「25 年到现在」「截止 2026 年 6 月」「2026 年 1 到 6 月」「今年截止 6 月」「24 年和 25 年」）取前一段的
  期初到后一段的期末，期末还没到时止于今天（G76、G77）；「和」只合相连的两段；「6 月之前」「6 月以后」不换算，
  追问起止日期。
- 认不出的说法（「国庆以来」「年中」）返回 None，由编排产生追问（§4.2 第 6 步），不估日期。
- 「不限时间」一类认作不限，不产生日期条件（§5.3 第 17 条）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

#: 滚动窗口的天数换算（G75）
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365
#: 只说「最近」「近期」
DEFAULT_RECENT_DAYS = 30


@dataclass(frozen=True)
class Span:
    """一项时间换算的结果。`start`、`end` 都含当天；None 表示这一头不限。"""

    said: str
    start: date | None
    end: date | None
    #: 滚动窗口的天数（含今天）；取数写 `GE {"$relative": "-(N-1)d"}`
    rolling_days: int | None = None
    #: 期间还没结束，止于今天（回答写「截至今天」）
    to_today: bool = False
    unlimited: bool = False
    #: 整段都还没到（期初在今天之后）
    future: bool = False
    #: 被截到今天之前本来的期末；起止说法拼后一段的期末时用它
    period_end: date | None = None

    def relative(self) -> dict | None:
        """滚动窗口的下界写法（`fetch` 的 `$relative`）；不是滚动窗口时为 None。"""
        if self.rolling_days is None:
            return None
        return {"$relative": f"-{self.rolling_days - 1}d"}

    def describe(self) -> str:
        """统计口径里的时间范围：一律写出起止日期。"""
        if self.unlimited or (self.start is None and self.end is None):
            return "不限时间"
        if self.start is None:
            return f"截至 {self.end:%Y-%m-%d}"
        end = f"{self.end:%Y-%m-%d}" if self.end is not None else "今天"
        if self.start == self.end:
            text = f"{self.start:%Y-%m-%d}"
        else:
            text = f"{self.start:%Y-%m-%d} 至 {end}"
        return text + ("（截至今天）" if self.to_today else "")


# ---------------------------------------------------------------------------- 数字


_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"(?:\d{1,3}|[零〇一二两三四五六七八九十]{1,3})"


def _int(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    if "十" not in text:
        return _CN_DIGIT.get(text) if len(text) == 1 else None
    left, _, right = text.partition("十")
    if len(left) > 1 or len(right) > 1:
        return None
    tens = _CN_DIGIT.get(left, -1) if left else 1
    ones = _CN_DIGIT.get(right, -1) if right else 0
    if tens < 0 or ones < 0:
        return None
    return tens * 10 + ones


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).lower()


# ---------------------------------------------------------------------------- 日期运算


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)


def _shift_month(y: int, m: int, k: int) -> tuple[int, int]:
    n = y * 12 + (m - 1) + k
    return n // 12, n % 12 + 1


def _period(start: date | None, end: date | None, today: date, said: str) -> Span:
    """一段起止：没结束的止于今天（总述「还没结束的期间」写「截至今天」）；整段还没到的照原样给，标 `future`
    （写明了年份的「2026 年 12 月」在 10 月问，查出来没有单，回答说这段时间还没到，不当认不出去追问）。"""
    if start is not None and start > today:
        return Span(said, start, end, future=True)
    if end is None or end >= today:
        return Span(said, start, today, to_today=True, period_end=end)
    return Span(said, start, end)


def _full_end(span: Span) -> date | None:
    """这一段本来的期末（没被截到今天的）。"""
    return span.period_end or span.end


# ---------------------------------------------------------------------------- 年份前缀

_YEAR = r"(?P<year>今年|本年|去年|上一?年|前年|(?:19|20)?\d{2}年|(?:19|20)\d{2}(?=[上下q第一二三四1-9]))"


def _year_of(token: str | None, today: date) -> int | None:
    """年份前缀 → 年；None 表示没写年份。"""
    if not token:
        return None
    if token in ("今年", "本年"):
        return today.year
    if token in ("去年", "上年", "上一年"):
        return today.year - 1
    if token == "前年":
        return today.year - 2
    digits = token.rstrip("年")
    year = int(digits)
    return year + 2000 if len(digits) == 2 else year


def _implied_year(year: int | None, first_day_this_year: date, today: date) -> int:
    """没写年份：今年这一段还没到时指去年的。"""
    if year is not None:
        return year
    return today.year if first_day_this_year <= today else today.year - 1


# ---------------------------------------------------------------------------- 单段说法

_UNLIMITED = re.compile(r"^(?:不限时间|不限日期|不限|所有时间|全部时间|所有日期|全部日期|有史以来|历来|一直以来|至今|迄今|累计|全部|所有)$")
_RECENT = re.compile(r"^(?:最近|近期|近来|最近一段时间)$")
_ROLLING = re.compile(
    rf"^(?:最近|近|过去)(?P<n>{_NUM}|半)?(?P<unit>天|日|周|个?星期|个?礼拜|个月|月|年)(?:内|以内|以来|来|里)?$"
    rf"|^(?P<n2>{_NUM}|半)(?P<unit2>天|日|周|个星期|个礼拜|个月|年)(?:内|以内|以来|来)$"
)
_DAY_WORDS = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}
_THIS_WEEK = re.compile(r"^(?:本周|这周|这一周|这个?星期|本星期|这个?礼拜)$")
_LAST_WEEK = re.compile(r"^(?P<up>上+)(?:一)?(?:周|个?星期|个?礼拜)$")
_THIS_MONTH = re.compile(r"^(?:本月|这个?月|当月|本月份)$")
_LAST_MONTH = re.compile(r"^(?P<up>上+)(?:一)?个?月$")
#: 「上月同期」：上月 1 日到上月的今天这一天（上月没有这一天时到上月月底；总述「这个月比上个月」的选项）
_LAST_MONTH_SAME = re.compile(r"^上(?:一)?个?月(?:的)?同期$")
_THIS_QUARTER = re.compile(r"^(?:本季度?|这个?季度|当季度?)$")
_LAST_QUARTER = re.compile(r"^上(?:一)?个?季度?$")
_QUARTER = re.compile(rf"^{_YEAR}?(?:的)?(?:q(?P<q1>[1-4])|第?(?P<q2>[一二三四1-4])季度?)$")
_HALF = re.compile(rf"^{_YEAR}?(?:的)?(?P<half>上|下)半年$")
_MONTH = re.compile(rf"^{_YEAR}?(?:的)?(?P<m>{_NUM})月份?$")
_MONTH_RANGE = re.compile(rf"^{_YEAR}?(?:的)?(?P<m1>{_NUM})月?(?:到|至|~|-|—|－)(?P<m2>{_NUM})月份?$")
_YEAR_ONLY = re.compile(rf"^{_YEAR}(?:全年|一年|整年)?$|^(?P<y4>(?:19|20)\d{{2}})$")
_DATE = re.compile(
    r"^(?:(?P<y>(?:19|20)\d{2})[-/.年])?(?P<m>\d{1,2})[-/.月](?P<d>\d{1,2})[日号]?$"
)
_YM = re.compile(r"^(?P<y>(?:19|20)\d{2})[-/.](?P<m>\d{1,2})$")


def _rolling(n_text: str | None, unit: str, said: str, today: date) -> Span | None:
    if n_text == "半":
        if "年" in unit:
            days = 6 * DAYS_PER_MONTH
        elif "月" in unit:
            days = 15
        else:
            return None
    else:
        n = 1 if not n_text else _int(n_text)
        if not n:
            return None
        if unit in ("天", "日"):
            days = n
        elif "周" in unit or "星期" in unit or "礼拜" in unit:
            days = n * DAYS_PER_WEEK
        elif "月" in unit:
            days = n * DAYS_PER_MONTH
        else:
            days = n * DAYS_PER_YEAR
    return Span(said, today - timedelta(days=days - 1), today, rolling_days=days, to_today=True)


def is_this_month(said: str) -> bool:
    """「本月」「这个月」这类说法（不含写明了年月的「2026 年 10 月」）。"""
    return bool(_THIS_MONTH.match(_compact(str(said or ""))))


def is_last_month(said: str) -> bool:
    """「上个月」「上月」这类说法（只往前一个月；不含写明了年月的「9 月」）。"""
    m = _LAST_MONTH.match(_compact(str(said or "")))
    return m is not None and len(m.group("up")) == 1


def _single(s: str, said: str, today: date) -> Span | None:
    """一段说法（已压缩、小写）→ 起止日期。"""
    if _UNLIMITED.match(s):
        return Span(said, None, None, unlimited=True)
    if _RECENT.match(s):
        return Span(said, today - timedelta(days=DEFAULT_RECENT_DAYS - 1), today,
                    rolling_days=DEFAULT_RECENT_DAYS, to_today=True)
    m = _ROLLING.match(s)
    if m:
        n_text, unit = (m.group("n"), m.group("unit")) if m.group("unit") else (m.group("n2"), m.group("unit2"))
        return _rolling(n_text, unit, said, today)
    if s in _DAY_WORDS:
        d = today - timedelta(days=_DAY_WORDS[s])
        return Span(said, d, d, to_today=d == today)
    if _THIS_WEEK.match(s):
        return Span(said, today - timedelta(days=today.weekday()), today, to_today=True)
    m = _LAST_WEEK.match(s)
    if m:
        k = len(m.group("up"))
        monday = today - timedelta(days=today.weekday() + 7 * k)
        return Span(said, monday, monday + timedelta(days=6))
    if _THIS_MONTH.match(s):
        return Span(said, today.replace(day=1), today, to_today=True)
    m = _LAST_MONTH.match(s)
    if m:
        y, mo = _shift_month(today.year, today.month, -len(m.group("up")))
        return Span(said, date(y, mo, 1), _month_end(y, mo))
    if _LAST_MONTH_SAME.match(s):
        y, mo = _shift_month(today.year, today.month, -1)
        return Span(said, date(y, mo, 1), date(y, mo, min(today.day, _month_end(y, mo).day)))
    if _THIS_QUARTER.match(s):
        q0 = (today.month - 1) // 3 * 3 + 1
        return Span(said, date(today.year, q0, 1), today, to_today=True)
    if _LAST_QUARTER.match(s):
        y, mo = _shift_month(today.year, (today.month - 1) // 3 * 3 + 1, -3)
        return Span(said, date(y, mo, 1), _month_end(y, mo + 2))
    m = _QUARTER.match(s)
    if m:
        q = _int(m.group("q1") or m.group("q2"))
        first = (q - 1) * 3 + 1
        y = _implied_year(_year_of(m.group("year"), today), date(today.year, first, 1), today)
        return _period(date(y, first, 1), _month_end(y, first + 2), today, said)
    m = _HALF.match(s)
    if m:
        first = 1 if m.group("half") == "上" else 7
        y = _implied_year(_year_of(m.group("year"), today), date(today.year, first, 1), today)
        return _period(date(y, first, 1), _month_end(y, first + 5), today, said)
    m = _MONTH_RANGE.match(s)
    if m:
        m1, m2 = _int(m.group("m1")), _int(m.group("m2"))
        if not (m1 and m2 and 1 <= m1 <= m2 <= 12):
            return None
        y = _implied_year(_year_of(m.group("year"), today), date(today.year, m1, 1), today)
        return _period(date(y, m1, 1), _month_end(y, m2), today, said)
    m = _MONTH.match(s)
    if m:
        mo = _int(m.group("m"))
        if not mo or not 1 <= mo <= 12:
            return None
        y = _implied_year(_year_of(m.group("year"), today), date(today.year, mo, 1), today)
        return _period(date(y, mo, 1), _month_end(y, mo), today, said)
    m = _YEAR_ONLY.match(s)
    if m:
        y = int(m.group("y4")) if m.group("y4") else _year_of(m.group("year"), today)
        return _period(date(y, 1, 1), date(y, 12, 31), today, said)
    m = _YM.match(s)
    if m:
        y, mo = int(m.group("y")), int(m.group("m"))
        if not 1 <= mo <= 12:
            return None
        return _period(date(y, mo, 1), _month_end(y, mo), today, said)
    m = _DATE.match(s)
    if m:
        mo, d = int(m.group("m")), int(m.group("d"))
        try:
            this_year = date(today.year, mo, d)
        except ValueError:
            return None
        y = int(m.group("y")) if m.group("y") else (today.year if this_year <= today else today.year - 1)
        try:
            day = date(y, mo, d)
        except ValueError:
            return None
        return _period(day, day, today, said)
    return None


# ---------------------------------------------------------------------------- 起止组合

_NOW = r"(?:现在|今天|目前|当前|如今|至今|今)"
_SINCE = re.compile(rf"^(?:从|自)?(?P<a>.+?)(?:(?:到|至|~|～|-|—|－)(?:{_NOW})|以来|至今|迄今|起|开始)(?:为止)?$")
_UNTIL = re.compile(r"^(?:截止到?|截至|到|直到)(?P<b>.+?)(?:为止|底|末)?$")
_RANGE = re.compile(r"^(?:从|自)?(?P<a>.+?)(?:到|至|~|～|—|－)(?P<b>.+)$")
#: 「今年截止 6 月」：前一段的期初到后一段的期末
_A_UNTIL_B = re.compile(r"^(?P<a>.+?)(?:截止到?|截至)(?P<b>.+?)(?:为止|底|末)?$")
#: 「24 年和 25 年」写成一项时
_BOTH = re.compile(r"^(?P<a>.+?)(?:和|与|及|、)(?P<b>.+)$")
_FILLER = re.compile(r"(?:的|内|以内|里|期间|这段时间|左右)$")


def _inherit_year(a: str, b: str) -> str:
    """「2026 年 1 到 6 月」拆成「2026年1」「6月」后，后半段补上前半段的年份。"""
    m = re.match(rf"^{_YEAR}", a)
    return (m.group("year") + b) if m and not re.match(rf"^{_YEAR}", b) else b


def convert(said: str, today: date) -> Span | None:
    """一项时间原话 → 起止日期；认不出返回 None。"""
    if not said or not str(said).strip():
        return None
    raw = _compact(str(said))
    single = _single(raw, said, today)
    if single is not None:
        return single
    s = _FILLER.sub("", raw)
    if not s:
        return None
    single = _single(s, said, today)
    if single is not None:
        return single
    # 起止说法（G76）：前一段的期初到后一段本来的期末，再照单段的规矩截到今天
    m = _SINCE.match(s)
    if m:
        a = _single(m.group("a"), said, today)
        if a is not None and a.start is not None and not a.unlimited and not a.future:
            return Span(said, a.start, today, to_today=True)
    m = _UNTIL.match(s)
    if m:
        b = _single(m.group("b"), said, today)
        if b is not None and _full_end(b) is not None and not b.unlimited:
            return _period(None, _full_end(b), today, said)
    m = _A_UNTIL_B.match(s)
    if m:
        a = _single(m.group("a"), said, today)
        b = _single(_inherit_year(m.group("a"), m.group("b")), said, today)
        if a is not None and b is not None and a.start and _full_end(b) and a.start <= _full_end(b):
            return _period(a.start, _full_end(b), today, said)
    m = _BOTH.match(s)
    if m:
        a = _single(m.group("a"), said, today)
        b = _single(_inherit_year(m.group("a"), m.group("b")), said, today)
        # 两段相连时合成一段（「24 年和 25 年」）；不相连的合不成一段起止日期，认不出
        if (a is not None and b is not None and _full_end(a) and b.start
                and b.start == _full_end(a) + timedelta(days=1)):
            return _period(a.start, _full_end(b), today, said)
    m = _RANGE.match(s)
    if m:
        a_text, b_text = m.group("a"), m.group("b")
        if re.fullmatch(_NUM, a_text) and re.search(r"月份?$", b_text):
            a_text += "月"
        a = _single(a_text, said, today)
        b = _single(_inherit_year(a_text, b_text), said, today)
        if a is not None and b is not None and a.start and _full_end(b) and a.start <= _full_end(b):
            return _period(a.start, _full_end(b), today, said)
    return None


# ---------------------------------------------------------------------------- 计划里的时间（§4.2 第 6 步）


def plan_spans(plan: dict, today: date) -> tuple[dict[str, list[Span]], str | None]:
    """计划每一步的时间换算结果（按步骤编号），以及第一项认不出的时间原话（有就要追问，本轮不取数）。"""
    out: dict[str, list[Span]] = {}
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        items = (step.get("params") or {}).get("time")
        items = items if isinstance(items, list) else [items] if items else []
        spans: list[Span] = []
        bases: list[str] = []
        for t in items:
            if not isinstance(t, dict) or not t.get("said"):
                continue
            span = convert(str(t["said"]), today)
            if span is None:
                return out, str(t["said"])
            spans.append(span)
            bases.append(str(t.get("basis") or "建单"))
        if (step.get("params") or {}).get("compare") != "时段":
            spans = _intersect_same_basis(spans, bases, today)
        out[str(step.get("id"))] = spans
    return out, None


def _intersect_same_basis(spans: list[Span], bases: list[str], today: date) -> list[Span]:
    """同一依据写了几项时间、又不是比较两个时段：几项都要满足，合成一段（与原列表一一对应，同组的位置放同一段）。

    「截止 2026 年 6 月，A8900 今年……」规划器写成「截止 2026 年 6 月」「今年」两项，取数本来就是两项都满足
    （= 总述「今年截止 6 月」），合成之后统计口径只写一段「2026-01-01 至 2026-06-30」。滚动窗口（取数写
    `$relative`）、不限时间、没有重叠的几段不合，照原样。
    """
    out = list(spans)
    for basis in dict.fromkeys(bases):
        idx = [i for i, b in enumerate(bases) if b == basis]
        group = [spans[i] for i in idx]
        if len(group) < 2 or any(s.unlimited or s.rolling_days is not None for s in group):
            continue
        starts = [s.start for s in group if s.start is not None]
        ends = [s.end for s in group if s.end is not None]
        start, end = (max(starts) if starts else None), (min(ends) if ends else None)
        if start is not None and end is not None and start > end:
            continue
        merged = Span(said="、".join(s.said for s in group), start=start, end=end,
                      to_today=any(s.to_today and s.end == end for s in group),
                      future=start is not None and start > today)
        for i in idx:
            out[i] = merged
    return out


# ---------------------------------------------------------------------------- 问句里的时间（第 14 条）

#: 一段时间说法最长几个字（「2025年12月1日至2026年1月31日」压缩后 21 个字）
_MAX_PHRASE = 24
#: 问句超过这个长度不扫（超长输入里的日期多半是正文里的，不是查询条件）
_MAX_QUERY = 400
#: 不带「最近」「近」的「30 天以内」在问句里多半说的是时长（结案周期分档），不当时间条件找；
#: 「三个月以来」「30 天来」是滚动窗口，照常找（§5.3 第 14 条）
_DURATION = re.compile(rf"^{_NUM}(?:天|日|周|个星期|个礼拜|个月|年)(?:内|以内)")


def _ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def find_in(query: str, today: date) -> list[str]:
    """问句里认得出的时间说法（压缩后的原文片段），从左到右、取最长的、不重叠。

    「不限时间」一类不算（第 17 条另有词表）；英文字母与数字开头或结尾的片段前后不能紧挨字母或数字
    （「Q1400」里不认「Q1」，单号「ZC2012001」里不认「2012」）。
    """
    q = _compact(query)
    if len(q) > _MAX_QUERY:
        return []
    found: list[str] = []
    i = 0
    while i < len(q):
        hit = None
        for j in range(min(len(q), i + _MAX_PHRASE), i + 1, -1):
            piece = q[i:j]
            if _ascii_alnum(piece[0]) and i > 0 and _ascii_alnum(q[i - 1]):
                break
            if _ascii_alnum(piece[-1]) and j < len(q) and _ascii_alnum(q[j]):
                continue
            if _DURATION.match(piece):
                continue
            span = convert(piece, today)
            if span is not None and not span.unlimited:
                hit = piece
                break
        if hit is None:
            i += 1
            continue
        found.append(_FILLER.sub("", hit) or hit)
        i += len(hit)
    return found


def same_time(a: str, b: str, today: date) -> bool:
    """两种写法是不是同一段时间：压缩后一个包含另一个，或换算出的起止日期相同。"""
    ca, cb = _compact(a), _compact(b)
    if ca and cb and (ca in cb or cb in ca):
        return True
    sa, sb = convert(a, today), convert(b, today)
    return sa is not None and sb is not None and (sa.start, sa.end) == (sb.start, sb.end)
