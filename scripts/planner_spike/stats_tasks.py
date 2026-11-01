"""临时统计（custom_stats）的实测题目：合成数据 + 题目 + 参考脚本。

数据是按固定种子生成的假数据（单号年份 99、工厂叫工厂A…），与真实业务无关。列名、类型与线上输入帧相同
（`src/factory_issue_module/skills/custom_stats.py::COLUMNS` 里的一部分；结案周期、停线时长、不良率已按口径派生，
生产数量只有国内有、不良率只有国内与巴西有）。题目与输出照设计 §5.5 的固定形状
`{"columns", "rows", "chart"}`；参考脚本同样在沙箱里跑、过线上同一套 AST 与形状检查，结果就是期望值；
`--self-check` 时直接把参考脚本当作模型的回答。只比 `rows`（与列数），图型由模型挑，线上也只作首选。
"""

from __future__ import annotations

import datetime as dt
import random

import pandas as pd

from factory_issue_module.declarations import DOMAINS
from factory_issue_module.skills import custom_stats

#: 合成帧用到的列（线上帧的一部分，名字取自 src）
NAMES = ("问题编号", "所属域", "建单时间", "机型", "加工厂", "问题类型", "问题等级", "已结案", "结案时间", "结案周期",
         "曾经停线", "停线日期", "重启日期", "停线时长", "不良数量", "生产数量", "影响数量", "不良率（%）")

MODELS = ["A920", "A920PRO", "A920MAX", "A8900", "L1400", "Q80", "IM30"]
TYPES = ["硬件问题", "软件问题", "物料问题", "结构问题", "工厂制程", "制程优化", "资料问题"]


def frame_columns() -> list[dict]:
    by_name = {c.name: c for c in custom_stats.COLUMNS}
    missing = [n for n in NAMES if n not in by_name]
    if missing:
        raise RuntimeError(f"线上输入帧没有这几列，stats_tasks.NAMES 要跟着改：{missing}")
    return [{"name": n, "kind": by_name[n].kind, "src": dict(by_name[n].src)} for n in NAMES]


def columns_text() -> list[tuple[str, str, str]]:
    """【数据列】：与线上同一个函数（`custom_stats.describe_columns`），三域都在。"""
    return custom_stats.describe_columns(frame_columns(), list(DOMAINS))


def _days(a, b) -> int | None:
    if a is None or b is None:
        return None
    return int((pd.Timestamp(b).normalize() - pd.Timestamp(a).normalize()).days)


def make_issues(n: int = 300, seed: int = 20261026) -> pd.DataFrame:
    rnd = random.Random(seed)
    start = dt.datetime(2024, 1, 1)
    span = (dt.datetime(2026, 10, 20) - start).days
    rows = []
    for i in range(n):
        dom = rnd.choices(["国内", "巴西", "海外"], weights=[80, 15, 5])[0]
        prefix = {"国内": "ZC", "巴西": "BR", "海外": "HW"}[dom]
        created = start + dt.timedelta(days=rnd.randrange(span), hours=rnd.randrange(8, 20))
        model = rnd.choice(MODELS)
        if rnd.random() < 0.1:
            model = "A920、A920PRO"
        closed = rnd.random() < 0.7
        closed_at = created + dt.timedelta(days=rnd.randint(1, 200)) if closed and rnd.random() > 0.03 else None
        bad = None if rnd.random() < 0.08 else float(rnd.randint(0, 500))
        base = None if rnd.random() < 0.05 else (0.0 if rnd.random() < 0.02 else float(rnd.randint(100, 5000)))
        impact = None if rnd.random() < 0.1 else float(rnd.randint(10, 3000))
        stop = created + dt.timedelta(days=rnd.randint(0, 5)) if rnd.random() < 0.15 else None
        restart = stop + dt.timedelta(days=rnd.randint(1, 60)) if stop is not None and rnd.random() < 0.8 else None
        if dom == "巴西":
            restart = None  # 巴西没有停线重启时间
        prod = base if dom == "国内" else None
        if dom == "国内":
            rate = round(bad / prod * 100, 2) if bad is not None and prod else None
        elif dom == "巴西":
            rate = (0.0 if impact == 0 else round(bad * 100 / impact, 2)) if bad is not None and impact is not None else None
        else:
            rate = None
        rows.append({
            "问题编号": f"{prefix}99{(i // 99) + 1:02d}{(i % 99) + 1:03d}",
            "所属域": dom,
            "建单时间": created,
            "机型": model,
            "加工厂": f"工厂{rnd.choice('ABCDE')}",
            "问题类型": rnd.choice(TYPES),
            "问题等级": rnd.choice(["A", "B", "C", None, None]),
            "已结案": closed,
            "结案时间": closed_at,
            "结案周期": _days(created, closed_at),
            "曾经停线": stop is not None,
            "停线日期": stop,
            "重启日期": restart,
            "停线时长": _days(stop, restart),
            "不良数量": bad,
            "生产数量": prod,
            "影响数量": impact,
            "不良率（%）": rate,
        })
    df = pd.DataFrame(rows, columns=list(NAMES))
    for col in ("建单时间", "结案时间", "停线日期", "重启日期"):
        df[col] = pd.to_datetime(df[col])
    for col in ("结案周期", "停线时长"):
        df[col] = pd.to_numeric(df[col]).astype("Int64")
    for col in ("不良数量", "生产数量", "影响数量", "不良率（%）"):
        df[col] = pd.to_numeric(df[col]).astype("float64")
    for col in ("问题等级",):
        df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df


def sample_rows(df: pd.DataFrame, k: int = custom_stats.SAMPLE_ROWS) -> list[dict]:
    out = []
    for rec in df.head(k).to_dict("records"):
        out.append({key: (None if pd.isna(v) else (v.isoformat() if hasattr(v, "isoformat") else v)) for key, v in rec.items()})
    return out


TASKS = [
    {
        "id": "S-01",
        "ask": "按建单时间是星期几统计单数，周一到周日都要给，没有单的给 0。表头为「星期」「单数」，周一在前。",
        "ref": '''
def run(data):
    df = data["issues"]
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    counts = df["建单时间"].dt.dayofweek.value_counts()
    rows = [[names[i], int(counts.get(i, 0))] for i in range(7)]
    return {"columns": ["星期", "单数"], "rows": rows, "chart": {"type": "bar", "x": "星期", "series": ["单数"]}}
''',
    },
    {
        "id": "S-02",
        "ask": "统计 2026 年 1 月 1 日到 3 月 31 日之间建单的单，按 ISO 周（周一开始）计数，只给有单的周，按周升序；周写成「2026-W01」这样。表头为「周」「单数」。",
        "ref": '''
def run(data):
    df = data["issues"]
    s = df[(df["建单时间"] >= "2026-01-01") & (df["建单时间"] < "2026-04-01")]["建单时间"]
    iso = s.dt.isocalendar()
    keys = iso["year"].astype(str) + "-W" + iso["week"].astype(int).map(lambda w: f"{w:02d}")
    counts = keys.value_counts().sort_index()
    rows = [[k, int(v)] for k, v in counts.items()]
    return {"columns": ["周", "单数"], "rows": rows, "chart": {"type": "line", "x": "周", "series": ["单数"]}}
''',
    },
    {
        "id": "S-03",
        "ask": "国内的单里，机型 A920 与 A920PRO 各自的合计不良率。机型是一单多值的列，一单在它的每个机型下各计一次。表头为「机型」「合计不良率（%）」「参与张数」，A920 在前。",
        "ref": '''
def run(data):
    df = 拆多值(data["issues"][data["issues"]["所属域"] == "国内"], "机型")
    rows = []
    for m in ["A920", "A920PRO"]:
        rate, ok, _ = 合计不良率(df[df["机型"] == m])
        rows.append([m, rate, ok])
    return {"columns": ["机型", "合计不良率（%）", "参与张数"], "rows": rows,
            "chart": {"type": "bar", "x": "机型", "series": ["合计不良率（%）"]}}
''',
    },
    {
        "id": "S-04",
        "ask": "已结案、且有结案周期的单：结案周期的平均值（保留 1 位小数）、中位数与张数。只要一行，表头为「平均（天）」「中位数（天）」「张数」。",
        "ref": '''
def run(data):
    df = data["issues"]
    ok = df[df["已结案"] & df["结案周期"].notna()]
    days = ok["结案周期"].astype(float)
    return {"columns": ["平均（天）", "中位数（天）", "张数"],
            "rows": [[round(float(days.mean()), 1), float(days.median()), int(len(days))]],
            "chart": {"type": "none"}}
''',
    },
    {
        "id": "S-05",
        "ask": "各加工厂的单数、未结案张数，以及未结案占比（未结案 ÷ 单数 × 100，保留 1 位小数），按单数降序，单数相同按加工厂名称升序。表头为「加工厂」「单数」「未结案」「占比（%）」。",
        "ref": '''
def run(data):
    df = data["issues"]
    g = df.groupby("加工厂").agg(单数=("问题编号", "count"), 未结案=("已结案", lambda s: int((~s.astype(bool)).sum()))).reset_index()
    g["占比"] = (g["未结案"] / g["单数"] * 100).round(1)
    g = g.sort_values(["单数", "加工厂"], ascending=[False, True])
    rows = [[r.加工厂, int(r.单数), int(r.未结案), float(r.占比)] for r in g.itertuples()]
    return {"columns": ["加工厂", "单数", "未结案", "占比（%）"], "rows": rows,
            "chart": {"type": "bar", "x": "加工厂", "series": ["单数", "未结案"]}}
''',
    },
    {
        "id": "S-06",
        "ask": "2026 年 1 月到 9 月每月的建单数，以及环比变化率（(本月 − 上月) ÷ 上月 × 100，保留 1 位小数；1 月与上月为 0 时写 None）。没有单的月份单数给 0。表头为「月份」「单数」「环比（%）」，月份写成「2026-01」这样。",
        "ref": '''
def run(data):
    df = data["issues"]
    s = df[(df["建单时间"] >= "2026-01-01") & (df["建单时间"] < "2026-10-01")]["建单时间"].dt.strftime("%Y-%m")
    counts = s.value_counts()
    rows, prev = [], None
    for m in range(1, 10):
        key = f"2026-{m:02d}"
        n = int(counts.get(key, 0))
        rate = None if prev in (None, 0) else round((n - prev) / prev * 100, 1)
        rows.append([key, n, rate])
        prev = n
    return {"columns": ["月份", "单数", "环比（%）"], "rows": rows, "chart": {"type": "line", "x": "月份", "series": ["单数"]}}
''',
    },
    {
        "id": "S-07",
        "ask": "曾经停线的单，按停线时长分「7 天及以内」「8–30 天」「30 天以上」三档计数；最后一行「不计入」写停过线但没有停线时长的张数。表头为「档」「单数」。",
        "ref": '''
def run(data):
    df = data["issues"]
    stopped = df[df["曾经停线"].astype(bool)]
    days = stopped["停线时长"].dropna().astype(int)
    rows = [["7 天及以内", int((days <= 7).sum())], ["8–30 天", int(((days >= 8) & (days <= 30)).sum())],
            ["30 天以上", int((days > 30).sum())], ["不计入", int(len(stopped) - len(days))]]
    return {"columns": ["档", "单数"], "rows": rows, "chart": {"type": "none"}}
''',
    },
    {
        "id": "S-08",
        "ask": "问题等级为空的单，按建单年份计数，按年份升序。表头为「年份」「单数」，年份写整数。",
        "ref": '''
def run(data):
    df = data["issues"]
    s = df[df["问题等级"].isna()]["建单时间"].dt.year.value_counts().sort_index()
    rows = [[int(k), int(v)] for k, v in s.items()]
    return {"columns": ["年份", "单数"], "rows": rows, "chart": {"type": "bar", "x": "年份", "series": ["单数"]}}
''',
    },
    {
        "id": "S-09",
        "ask": "不良数量最多的 5 张单（不良数量为空的不算；不良数量相同时按问题编号升序）。表头为「问题编号」「不良数量」。",
        "ref": '''
def run(data):
    df = data["issues"]
    ok = df[df["不良数量"].notna()].sort_values(["不良数量", "问题编号"], ascending=[False, True]).head(5)
    rows = [[r.问题编号, float(r.不良数量)] for r in ok.itertuples()]
    return {"columns": ["问题编号", "不良数量"], "rows": rows, "chart": {"type": "none"}}
''',
    },
    {
        "id": "S-10",
        "ask": "每个问题类型的平均不良数量（不良数量为空的单不参与，保留 2 位小数），按问题类型名称升序。表头为「问题类型」「平均不良数量」。",
        "ref": '''
def run(data):
    df = data["issues"]
    g = df[df["不良数量"].notna()].groupby("问题类型")["不良数量"].mean().sort_index()
    rows = [[k, round(float(v), 2)] for k, v in g.items()]
    return {"columns": ["问题类型", "平均不良数量"], "rows": rows,
            "chart": {"type": "bar", "x": "问题类型", "series": ["平均不良数量"]}}
''',
    },
]


def _equal(got, want, tol: float) -> bool:
    if isinstance(want, list):
        return isinstance(got, list) and len(got) == len(want) and all(_equal(g, w, tol) for g, w in zip(got, want))
    if isinstance(want, bool) or isinstance(got, bool):
        return got == want
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(float(got) - float(want)) <= tol
    if want is None or got is None:
        return got is None and want is None
    return str(got).strip() == str(want).strip()


def results_equal(got, want, tol: float = 0.051) -> bool:
    """沙箱结果与参考结果比较：只比 `rows`（数字允许舍入误差，其余逐项相等，行的顺序要一致）与列数；列名、图型
    由模型起，不比。"""
    if not isinstance(got, dict) or not isinstance(want, dict):
        return False
    if len(got.get("columns") or []) != len(want.get("columns") or []):
        return False
    return _equal(got.get("rows"), want.get("rows"), tol)
