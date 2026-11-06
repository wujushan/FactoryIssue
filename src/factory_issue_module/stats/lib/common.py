"""沙箱公共函数（设计 §8.1）：取值清洗、翻译表、排序带次键、列表附项数。只用沙箱白名单里的库。"""

import math
import re

import pandas as pd

from factory_issue_module.textnorm import json_items, to_halfwidth

_FI_DATE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})")


def fi_blank(v):
    """None、NaN、NaT、空串都算空。"""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str):
        return not v.strip()
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def fi_int(v):
    """整数或 None：文本型员工 ID、部门 ID 转整数，无效值按空（`dirty_data.md`「类型不一致」）。"""
    if fi_blank(v):
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v == int(v) else None
    s = str(v).strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def fi_num(v):
    """数值或 None。"""
    if fi_blank(v):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def fi_split(v):
    """逗号分隔的多值：逐段去首尾空格（`dirty_data.md`「逗号分隔的多值列」）。"""
    if fi_blank(v):
        return []
    return [s.strip() for s in re.split(r"[,，]", str(v)) if s.strip()]


def fi_ids(v):
    out = []
    for s in fi_split(v):
        n = fi_int(s)
        if n is not None and n not in out:
            out.append(n)
    return out


def fi_ts(v):
    """日期时间 → pandas Timestamp（不带时区）；空或解析不了按空。"""
    if fi_blank(v):
        return None
    try:
        ts = pd.Timestamp(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def fi_date_in_text(v):
    """文字里的第一个日期（处理步骤「停线重启」的结论存的是日期）。"""
    if fi_blank(v):
        return None
    m = _FI_DATE.search(str(v))
    if not m:
        return None
    try:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


_FI_TEXT_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def fi_text_date(v):
    """文本存的日期（巴西、海外）：只认 `YYYY-MM-DD`，空串或别的写法按空，不猜（`dirty_data.md`「文本存日期」）。"""
    if fi_blank(v):
        return None
    m = _FI_TEXT_DATE.match(str(v).strip())
    if not m:
        return None
    try:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fi_json_list(v):
    """JSON 数组列（海外物料、巴西与海外的问题现象）：空、不以 `[` 开头、解析不了都按空数组。

    解析规则只有一份，在 `textnorm.json_items`（治理任务也用）；这里先按沙箱的口径判空（含 NaT、NA）。
    """
    if fi_blank(v):
        return []
    return json_items(v)


def fi_day(ts):
    return None if ts is None else ts.strftime("%Y-%m-%d")


def fi_show(v, empty="未填"):
    """展示用：空写「未填」；整数样子的浮点去掉小数点。"""
    if fi_blank(v):
        return empty
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def fi_percent_text(v):
    """单上已存的百分数：46.4 → 46.4%，100 → 100%。"""
    x = fi_num(v)
    if x is None:
        return "未填"
    return f"{round(x, 2):g}%"


def fi_lookup(df, key, value, cast=None):
    """两列表 → 翻译字典；`cast` 给 int 时键转整数。"""
    out = {}
    if df is None or len(df) == 0 or key not in df.columns or value not in df.columns:
        return out
    for k, v in zip(df[key].tolist(), df[value].tolist()):
        kk = fi_int(k) if cast == "int" else (None if fi_blank(k) else str(k).strip())
        if kk is not None and not fi_blank(v) and kk not in out:
            out[kk] = str(v).strip()
    return out


def fi_records(df):
    """一行一个 dict；空值（NaN、NaT）一律给 None。pandas 3 的文本列空值是 NaN 而不是 None，不转的话
    `str(x or "")` 一类写法会把没填的写成「nan」。"""
    if df is None or len(df) == 0:
        return []
    return df.astype(object).where(df.notna(), None).to_dict("records")


def fi_group(records, key):
    out = {}
    for r in records:
        k = fi_int(r.get(key))
        if k is not None:
            out.setdefault(k, []).append(r)
    return out


def fi_unique(items):
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def fi_key(text):
    """名字比较：去空格、连字符、下划线，转小写（与 `plan/names.py::key` 同一种写法，不做 NFKC）。"""
    if fi_blank(text):  # NaN 不写成「nan」（pandas 3 文本列的空值是 NaN）
        return ""
    return re.sub(r"[\s\-_]+", "", to_halfwidth(str(text or ""))).lower()


def fi_rank(pairs, top=None):
    """[(名称, 数)] → 按数降序、同数按名称升序；给了 `top` 时取前 top 名，第 top 名并列的一起留下。

    返回 (留下的, 第一名的名称们, 第 top 名处并列的名称们)。
    """
    rows = sorted(pairs, key=lambda p: (-(p[1] or 0), str(p[0])))
    if not rows:
        return [], [], []
    first = [p[0] for p in rows if p[1] == rows[0][1]]
    tied = []
    if top is not None and len(rows) > top:
        edge = rows[top - 1][1]
        kept = [p for p in rows if (p[1] or 0) >= (edge or 0)]
        if len(kept) > top:
            tied = [p[0] for p in kept if p[1] == edge]
        rows = kept
    return rows, first, tied


#: 不参加排名的取值（总述「排名、长清单与导出」，G87、G88）；与 `domains/base.py::UNRANKED` 同一份，单测比对
FI_UNRANKED = ("未填", "未识别机型", "其他（未识别）")


def fi_rank_named(pairs, top=None):
    """分布（按问题类型、按加工厂）→ (排名的, 不参加排名的)：占位取值（`FI_UNRANKED`）不参加排名，按 `FI_UNRANKED`
    的顺序另给，交写结论的模型时放在「不参加排名的 X」里，免得它把「未填」说成最多。"""
    named = [p for p in pairs if p[0] not in FI_UNRANKED and not fi_blank(p[0])]
    blanks = sorted([list(p) for p in pairs if p[0] in FI_UNRANKED], key=lambda p: FI_UNRANKED.index(p[0]))
    ranked, _f, _t = fi_rank(named, top)
    return ranked, blanks


def fi_named_facts(facts, key, title, pairs, top=None):
    """把一个分布写进事实：「按 X」只放排名的，占位取值放「不参加排名的 X」（有才写）。返回排名的。"""
    ranked, blanks = fi_rank_named(pairs, top)
    facts[key] = [list(p) for p in (ranked[:top] if top else ranked)]
    if blanks:
        facts["不参加排名的" + title] = blanks
    return ranked


def fi_with_counts(facts):
    """`facts` 里每个列表附上项数，键名为「列表名（项数）」（设计 §8.1）。只处理 dict 里的列表值，递归。"""
    if isinstance(facts, dict):
        out = {}
        for k, v in facts.items():
            out[k] = fi_with_counts(v)
            if isinstance(v, list):
                out[str(k) + "（项数）"] = len(v)
        return out
    if isinstance(facts, list):
        return [fi_with_counts(x) for x in facts]
    return facts


def fi_round(x, n=2):
    return None if x is None else round(float(x), n)


def fi_median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return float(vals[mid]) if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
