"""临时统计（custom_stats）的实测题目：合成数据 + 题目 + 参考脚本。

数据是按固定种子生成的假数据（单号年份 99、工厂叫工厂A…），与真实业务无关。
参考脚本同样在沙箱里跑，结果就是期望值；`--self-check` 时直接把参考脚本当作模型的回答。
"""

from __future__ import annotations

import datetime as dt
import random

import pandas as pd

COLUMNS = [
    ("问题编号", "str", "单号，如 ZC9901001"),
    ("域", "str", "国内、巴西、海外"),
    ("建单时间", "datetime64", "建单的时间"),
    ("机型", "str", "一单多个时用「、」连接，如「A920、A920PRO」"),
    ("加工厂", "str", "工厂名称"),
    ("问题类型", "str", "如硬件问题、物料问题"),
    ("是否结案", "bool", "True 为已结案"),
    ("结案时间", "datetime64", "已结案的单才可能有；少数已结案的单为空"),
    ("不良数量", "float", "可能为空"),
    ("生产数量", "float", "不良率的分母，可能为空或 0"),
    ("问题等级", "str", "A、B、C，可能为空（None）"),
    ("停线日期", "datetime64", "停过线的单才有"),
    ("重启日期", "datetime64", "已经重启的单才有"),
]

MODELS = ["A920", "A920PRO", "A920MAX", "A8900", "L1400", "Q80", "IM30"]
TYPES = ["硬件问题", "软件问题", "物料问题", "结构问题", "工厂制程", "制程优化", "资料问题"]


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
        stop = created + dt.timedelta(days=rnd.randint(0, 5)) if rnd.random() < 0.15 else None
        restart = stop + dt.timedelta(days=rnd.randint(1, 60)) if stop is not None and rnd.random() < 0.8 else None
        rows.append({
            "问题编号": f"{prefix}99{(i // 99) + 1:02d}{(i % 99) + 1:03d}",
            "域": dom,
            "建单时间": created,
            "机型": model,
            "加工厂": f"工厂{rnd.choice('ABCDE')}",
            "问题类型": rnd.choice(TYPES),
            "是否结案": closed,
            "结案时间": closed_at,
            "不良数量": bad,
            "生产数量": base,
            "问题等级": rnd.choice(["A", "B", "C", None, None]),
            "停线日期": stop,
            "重启日期": restart,
        })
    df = pd.DataFrame(rows)
    for col in ("建单时间", "结案时间", "停线日期", "重启日期"):
        df[col] = pd.to_datetime(df[col])
    return df


def sample_rows(df: pd.DataFrame, k: int = 3) -> list[dict]:
    out = []
    for rec in df.head(k).to_dict("records"):
        out.append({key: (None if pd.isna(v) else (v.isoformat() if hasattr(v, "isoformat") else v)) for key, v in rec.items()})
    return out


TASKS = [
    {
        "id": "S-01",
        "ask": "按建单时间是星期几统计单数，周一到周日都要给，没有单的给 0。",
        "format": '{"rows": [{"星期": "周一", "单数": 整数}, … 依次到周日]}',
        "ref": '''
def run(data):
    df = data["issues"]
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    counts = df["建单时间"].dt.dayofweek.value_counts()
    return {"rows": [{"星期": names[i], "单数": int(counts.get(i, 0))} for i in range(7)]}
''',
    },
    {
        "id": "S-02",
        "ask": "统计 2026 年 1 月 1 日到 3 月 31 日之间建单的单，按 ISO 周（周一开始）计数，只给有单的周，按周升序。",
        "format": '{"rows": [{"周": "2026-W01", "单数": 整数}, …]}',
        "ref": '''
def run(data):
    df = data["issues"]
    s = df[(df["建单时间"] >= "2026-01-01") & (df["建单时间"] < "2026-04-01")]["建单时间"]
    iso = s.dt.isocalendar()
    keys = iso["year"].astype(str) + "-W" + iso["week"].astype(int).map(lambda w: f"{w:02d}")
    counts = keys.value_counts().sort_index()
    return {"rows": [{"周": k, "单数": int(v)} for k, v in counts.items()]}
''',
    },
    {
        "id": "S-03",
        "ask": "机型 A920 与 A920PRO 各自的合计不良率。机型是一单多值的列，一单在它的每个机型下各计一次。用口径函数「合计不良率」。",
        "format": '{"rows": [{"机型": "A920", "合计不良率": 小数或 None, "参与张数": 整数}, {"机型": "A920PRO", …}]}',
        "ref": '''
def run(data):
    df = 拆多值(data["issues"], "机型")
    rows = []
    for m in ["A920", "A920PRO"]:
        rate, ok, _ = 合计不良率(df[df["机型"] == m])
        rows.append({"机型": m, "合计不良率": rate, "参与张数": ok})
    return {"rows": rows}
''',
    },
    {
        "id": "S-04",
        "ask": "已结案、且有结案时间的单：结案周期 = 结案时间的日期 − 建单时间的日期（按天）。给平均值（保留 1 位小数）、中位数与张数。",
        "format": '{"平均": 小数, "中位数": 数, "张数": 整数}',
        "ref": '''
def run(data):
    df = data["issues"]
    ok = df[df["是否结案"] & df["结案时间"].notna()]
    days = (ok["结案时间"].dt.normalize() - ok["建单时间"].dt.normalize()).dt.days
    return {"平均": round(float(days.mean()), 1), "中位数": float(days.median()), "张数": int(len(days))}
''',
    },
    {
        "id": "S-05",
        "ask": "各加工厂的单数、未结案张数，以及未结案占比（未结案 ÷ 单数 × 100，保留 1 位小数），按单数降序，单数相同按加工厂名称升序。",
        "format": '{"rows": [{"加工厂": "工厂A", "单数": 整数, "未结案": 整数, "占比": 小数}, …]}',
        "ref": '''
def run(data):
    df = data["issues"]
    g = df.groupby("加工厂").agg(单数=("问题编号", "count"), 未结案=("是否结案", lambda s: int((~s).sum()))).reset_index()
    g["占比"] = (g["未结案"] / g["单数"] * 100).round(1)
    g = g.sort_values(["单数", "加工厂"], ascending=[False, True])
    return {"rows": [{"加工厂": r.加工厂, "单数": int(r.单数), "未结案": int(r.未结案), "占比": float(r.占比)} for r in g.itertuples()]}
''',
    },
    {
        "id": "S-06",
        "ask": "2026 年 1 月到 9 月每月的建单数，以及环比变化率（(本月 − 上月) ÷ 上月 × 100，保留 1 位小数；1 月写 None；上月为 0 时写 None）。没有单的月份单数给 0。",
        "format": '{"rows": [{"月份": "2026-01", "单数": 整数, "环比": 小数或 None}, … 到 "2026-09"]}',
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
        rows.append({"月份": key, "单数": n, "环比": rate})
        prev = n
    return {"rows": rows}
''',
    },
    {
        "id": "S-07",
        "ask": "停线时长 = 重启日期 − 停线日期（按天），只算两个日期都有的单；按「7 天及以内」「8–30 天」「30 天以上」三档计数，另给不计入的张数（停过线但没有重启日期的单）。",
        "format": '{"rows": [{"档": "7 天及以内", "单数": 整数}, {"档": "8–30 天", "单数": 整数}, {"档": "30 天以上", "单数": 整数}], "不计入": 整数}',
        "ref": '''
def run(data):
    df = data["issues"]
    stopped = df[df["停线日期"].notna()]
    ok = stopped[stopped["重启日期"].notna()]
    days = (ok["重启日期"].dt.normalize() - ok["停线日期"].dt.normalize()).dt.days
    rows = [
        {"档": "7 天及以内", "单数": int((days <= 7).sum())},
        {"档": "8–30 天", "单数": int(((days >= 8) & (days <= 30)).sum())},
        {"档": "30 天以上", "单数": int((days > 30).sum())},
    ]
    return {"rows": rows, "不计入": int(len(stopped) - len(ok))}
''',
    },
    {
        "id": "S-08",
        "ask": "问题等级为空的单，按建单年份计数，按年份升序。",
        "format": '{"rows": [{"年份": 整数, "单数": 整数}, …]}',
        "ref": '''
def run(data):
    df = data["issues"]
    s = df[df["问题等级"].isna()]["建单时间"].dt.year.value_counts().sort_index()
    return {"rows": [{"年份": int(k), "单数": int(v)} for k, v in s.items()]}
''',
    },
    {
        "id": "S-09",
        "ask": "不良数量最多的 5 张单（不良数量为空的不算；不良数量相同时按问题编号升序）。",
        "format": '{"rows": [{"问题编号": "…", "不良数量": 数}, … 共 5 行]}',
        "ref": '''
def run(data):
    df = data["issues"]
    ok = df[df["不良数量"].notna()].sort_values(["不良数量", "问题编号"], ascending=[False, True]).head(5)
    return {"rows": [{"问题编号": r.问题编号, "不良数量": float(r.不良数量)} for r in ok.itertuples()]}
''',
    },
    {
        "id": "S-10",
        "ask": "每个问题类型的平均不良数量（不良数量为空的单不参与，保留 2 位小数），按问题类型名称升序。",
        "format": '{"rows": [{"问题类型": "…", "平均不良数量": 小数}, …]}',
        "ref": '''
def run(data):
    df = data["issues"]
    g = df[df["不良数量"].notna()].groupby("问题类型")["不良数量"].mean().sort_index()
    return {"rows": [{"问题类型": k, "平均不良数量": round(float(v), 2)} for k, v in g.items()]}
''',
    },
]


def results_equal(got, want, tol: float = 0.051) -> bool:
    """沙箱结果与参考结果比较：数字允许舍入误差，其余逐项相等，列表顺序要一致。"""
    if isinstance(want, dict):
        return isinstance(got, dict) and set(got) == set(want) and all(results_equal(got[k], want[k], tol) for k in want)
    if isinstance(want, list):
        return isinstance(got, list) and len(got) == len(want) and all(results_equal(g, w, tol) for g, w in zip(got, want))
    if isinstance(want, bool) or isinstance(got, bool):
        return got == want
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(float(got) - float(want)) <= tol
    if want is None or got is None:
        return got is None and want is None
    return str(got).strip() == str(want).strip()
