"""时间说法换算（设计 §6.1「日期」；总述「时间说法怎么换算」）。"""

from __future__ import annotations

from datetime import date

import pytest

from factory_issue_module.plan.timespan import convert, find_in, same_time

#: 总述的例子：「今天是 10 月 21 日时，『最近 14 天』= 10 月 8 日至 10 月 21 日」；这天是周三
TODAY = date(2026, 10, 21)


def span(said: str, today: date = TODAY):
    got = convert(said, today)
    assert got is not None, said
    return got


@pytest.mark.parametrize(
    ("said", "days", "start"),
    [
        ("最近 1 天", 1, date(2026, 10, 21)),
        ("最近 14 天", 14, date(2026, 10, 8)),
        ("近 30 天", 30, date(2026, 9, 22)),
        ("最近", 30, date(2026, 9, 22)),
        ("最近一周", 7, date(2026, 10, 15)),
        ("近两周", 14, date(2026, 10, 8)),
        ("近三个月", 90, date(2026, 7, 24)),
        ("最近 3 个月内", 90, date(2026, 7, 24)),
        ("过去 7 天", 7, date(2026, 10, 15)),
        ("30 天内", 30, date(2026, 9, 22)),
        ("近一年", 365, date(2025, 10, 22)),
        ("近半年", 180, date(2026, 4, 25)),
        ("近半个月", 15, date(2026, 10, 7)),
    ],
)
def test_rolling_window_counts_today(said: str, days: int, start: date) -> None:
    got = span(said)
    assert got.rolling_days == days
    assert (got.start, got.end) == (start, TODAY)
    assert got.relative() == {"$relative": f"-{days - 1}d"}
    assert got.to_today


@pytest.mark.parametrize(
    ("said", "start", "end", "to_today"),
    [
        ("今年", date(2026, 1, 1), TODAY, True),
        ("去年", date(2025, 1, 1), date(2025, 12, 31), False),
        ("前年", date(2024, 1, 1), date(2024, 12, 31), False),
        ("26 年", date(2026, 1, 1), TODAY, True),
        ("2025 年", date(2025, 1, 1), date(2025, 12, 31), False),
        ("本月", date(2026, 10, 1), TODAY, True),
        ("这个月", date(2026, 10, 1), TODAY, True),
        ("上个月", date(2026, 9, 1), date(2026, 9, 30), False),
        ("上上个月", date(2026, 8, 1), date(2026, 8, 31), False),
        ("本周", date(2026, 10, 19), TODAY, True),
        ("上周", date(2026, 10, 12), date(2026, 10, 18), False),
        ("上上周", date(2026, 10, 5), date(2026, 10, 11), False),
        ("今天", TODAY, TODAY, True),
        ("昨天", date(2026, 10, 20), date(2026, 10, 20), False),
        ("今年 Q2", date(2026, 4, 1), date(2026, 6, 30), False),
        ("2025 年第四季度", date(2025, 10, 1), date(2025, 12, 31), False),
        ("第四季度", date(2026, 10, 1), TODAY, True),
        ("本季度", date(2026, 10, 1), TODAY, True),
        ("上季度", date(2026, 7, 1), date(2026, 9, 30), False),
        ("2026 年上半年", date(2026, 1, 1), date(2026, 6, 30), False),
        ("2026 上半年", date(2026, 1, 1), date(2026, 6, 30), False),
        ("下半年", date(2026, 7, 1), TODAY, True),
        ("2026 年 6 月", date(2026, 6, 1), date(2026, 6, 30), False),
        ("6 月份", date(2026, 6, 1), date(2026, 6, 30), False),
        ("去年 11 月", date(2025, 11, 1), date(2025, 11, 30), False),
        ("2026 年 1 到 6 月", date(2026, 1, 1), date(2026, 6, 30), False),
        ("2026 年 1 月到 3 月", date(2026, 1, 1), date(2026, 3, 31), False),
        ("截止 2026 年 6 月", None, date(2026, 6, 30), False),
        ("25 年到现在", date(2025, 1, 1), TODAY, True),
        ("2024 年以来", date(2024, 1, 1), TODAY, True),
        ("2026-10-01 至今", date(2026, 10, 1), TODAY, True),
        ("2026 年 10 月 1 日", date(2026, 10, 1), date(2026, 10, 1), False),
        ("24 年和 25 年", date(2024, 1, 1), date(2025, 12, 31), False),
        ("今年截止 6 月", date(2026, 1, 1), date(2026, 6, 30), False),
    ],
)
def test_natural_periods(said: str, start: date | None, end: date, to_today: bool) -> None:
    got = span(said)
    assert (got.start, got.end, got.to_today) == (start, end, to_today)
    assert got.relative() is None


def test_month_or_quarter_not_yet_reached_means_last_year() -> None:
    march = date(2026, 3, 10)
    assert (span("11 月", march).start, span("11 月", march).end) == (date(2025, 11, 1), date(2025, 11, 30))
    assert span("Q3", march).start == date(2025, 7, 1)
    assert span("下半年", march).start == date(2025, 7, 1)
    assert span("上半年", march).to_today


@pytest.mark.parametrize(
    "said", ["国庆以来", "春节前后", "年中", "6 月之前", "6 月以后", "2027 年以来", "24 年和 26 年", "", "随便"]
)
def test_unknown_phrases_are_not_guessed(said: str) -> None:
    assert convert(said, TODAY) is None


# 评审 M1：期末还没到的说法照样认得出，没结束的止于今天（总述「还没结束的期间」）；单测不只钉一个日期
MARCH, MAY, MID_JUNE = date(2026, 3, 10), date(2026, 5, 1), date(2026, 6, 15)


@pytest.mark.parametrize(
    ("said", "today", "start", "end", "to_today"),
    [
        ("今年截止 6 月", MARCH, date(2026, 1, 1), MARCH, True),
        ("今年截止 6 月", MAY, date(2026, 1, 1), MAY, True),
        ("今年截止 6 月", MID_JUNE, date(2026, 1, 1), MID_JUNE, True),
        ("今年截止 6 月", TODAY, date(2026, 1, 1), date(2026, 6, 30), False),
        ("截止 2026 年 6 月", MARCH, None, MARCH, True),
        ("截止 2026 年 6 月", MID_JUNE, None, MID_JUNE, True),
        ("截止 2026 年 6 月", TODAY, None, date(2026, 6, 30), False),
        ("2026 年 1 到 6 月", MARCH, date(2026, 1, 1), MARCH, True),
        ("2026 年 1 到 6 月", TODAY, date(2026, 1, 1), date(2026, 6, 30), False),
        ("2026 年 1 月到 12 月", TODAY, date(2026, 1, 1), TODAY, True),
        ("2026 年上半年", MAY, date(2026, 1, 1), MAY, True),
    ],
)
def test_period_ending_later_is_converted_and_stops_today(said, today, start, end, to_today) -> None:
    got = span(said, today)
    assert (got.start, got.end, got.to_today) == (start, end, to_today)
    assert not got.future


@pytest.mark.parametrize(
    ("said", "today", "start", "end"),
    [("2026 年 12 月", TODAY, date(2026, 12, 1), date(2026, 12, 31)),
     ("2027 年", TODAY, date(2027, 1, 1), date(2027, 12, 31)),
     ("2026 年第三季度", MAY, date(2026, 7, 1), date(2026, 9, 30))],
)
def test_period_not_started_is_kept_as_said(said, today, start, end) -> None:
    """写明了年份、整段还没到：照原样给起止并标 future，不当认不出去追问（没写年份的仍指去年的）。"""
    got = span(said, today)
    assert (got.start, got.end, got.future) == (start, end, True)
    assert span("12 月", TODAY).start == date(2025, 12, 1)


def test_unlimited() -> None:
    got = span("不限时间")
    assert got.unlimited and got.start is None and got.end is None
    assert got.describe() == "不限时间"


def test_describe_prints_both_ends() -> None:
    assert span("最近 14 天").describe() == "2026-10-08 至 2026-10-21（截至今天）"
    assert span("上个月").describe() == "2026-09-01 至 2026-09-30"
    assert span("截止 2026 年 6 月").describe() == "截至 2026-06-30"


@pytest.mark.parametrize(
    ("query", "phrases"),
    [
        ("截止 2026 年 6 月，A8900 今年在亮亮工厂有多少单？", ["截止2026年6月", "今年"]),
        ("上周国内没结案的单有哪些？巴西的也看看", ["上周"]),
        ("软件、硬件、结构三类，24 年和 25 年国内数量的环比增减怎么样？", ["24年和25年"]),
        ("Q1400 的问题有哪些", []),
        ("ZC2012001 的原因是什么", []),
        ("结案周期 30 天以内、31 到 90 天的各几张", []),
        ("现在还有多少单停线", []),
        # 评审 M3：「以来」「来」是滚动窗口，要找；「以内」才是时长
        ("三个月以来国内有多少单", ["三个月以来"]),
        ("30 天来新建的单", ["30天来"]),
    ],
)
def test_find_in_query(query: str, phrases: list[str]) -> None:
    assert find_in(query, TODAY) == phrases


def test_same_time() -> None:
    assert same_time("2026 年 Q2", "今年第二季度", TODAY)
    assert same_time("截止2026年6月", "截止 2026 年 6 月", TODAY)
    assert not same_time("上个月", "本月", TODAY)
