"""临时统计在沙箱里用的函数（设计 §5.5、§8.1）。只拼进临时统计的两次脚本（`stats/runner.py`）。

- `cs_rows`、`cs_typed`、`cs_sample`：第一次调用里，把一域筛好的「一单一行」视图整理成显示名列的行、合成一张
  跨域的帧（加「所属域」一列），再取几行样例。哪些列、从视图的哪一列来、是什么类型，由 `handle()` 一侧作为参数
  给出（`skills/custom_stats.py::frame_columns`）；单 ID、权限承载列、内部编码与 `_` 开头的辅助列都不进这张帧。
- 口径函数 `拆多值`、`合计不良率`：给模型写的脚本调用。合计不良率与统计用同一个 `views.vw_rate`，按域算，几个域
  混在一起时报错（国内、巴西的分母不同，总述「汇总不良率」）；海外的单不参与（不良率是单上原文）。名字照写给模型
  的说法，用中文。帧的列名由外壳在运行前写进 `CS_NAMES`（`stats/tasks/custom_run.py`）。
- `cs_finish`：模型脚本的返回值整理成可回传的值（numpy 标量转原生、NaN 与 NaT 转 None、日期转文本、是否转
  「是」「否」、行写成字典或元组的转成列表）。形状对不对由 `handle()` 一侧查（`stats/custom.py::check_result`）。
"""

import datetime as cs_dt
import math

import numpy as np
import pandas as pd

from factory_issue_module.stats.lib.common import fi_blank, fi_num, fi_ts, fi_unique
from factory_issue_module.stats.lib.views import vw_rate

#: 视图里表示「没有」的展示文字：进帧时一律写成空值
CS_BLANK = ("未填", "—", "未指定", "未识别机型")
#: 帧里几列的显示名（所属域、不良数量与两域的分母），由外壳按参数写入
CS_NAMES = {}


def cs_value(x, kind):
    """视图里的一格 → 帧里的一格。多值（列表）用「、」连接；没有的写空值。"""
    if isinstance(x, (list, tuple)):
        parts = [str(v).strip() for v in x if not fi_blank(v)]
        x = "、".join(parts) if parts else None
    if kind == "bool":
        return None if x is None else bool(x)
    if fi_blank(x):
        return None
    if kind == "date":
        return fi_ts(x)
    if kind in ("num", "int"):
        n = fi_num(x)
        return None if n is None else (int(n) if kind == "int" else n)
    text = str(x).strip()
    return None if text in CS_BLANK else text


def cs_rows(view, dom, cols):
    """一域的视图 → 行（字典，键是显示名）。`cols`：[{"name", "kind", "src": {域: 视图列}}]；`kind` 为 domain 的
    那一列写域名；本域没有来源的列写空值。"""
    out = []
    if view is None or len(view) == 0:
        return out
    have = set(view.columns)
    for _, r in view.iterrows():
        row = {}
        for c in cols:
            if c["kind"] == "domain":
                row[c["name"]] = dom
                continue
            key = (c.get("src") or {}).get(dom)
            row[c["name"]] = cs_value(r[key], c["kind"]) if key and key in have else None
        out.append(row)
    return out


def cs_typed(rows, cols):
    """几域的行合成一张帧：日期列是日期，数值列是数，整数列是可空整数，是否列是布尔（本域没有的为空）。"""
    names = [c["name"] for c in cols]
    df = pd.DataFrame(rows, columns=names)
    for c in cols:
        name = c["name"]
        if c["kind"] == "date":
            df[name] = pd.to_datetime(df[name], errors="coerce")
        elif c["kind"] == "num":
            df[name] = pd.to_numeric(df[name], errors="coerce").astype("float64")
        elif c["kind"] == "int":
            df[name] = pd.to_numeric(df[name], errors="coerce").astype("Int64")
        elif c["kind"] == "bool":
            if len(df) and df[name].notna().all():
                df[name] = df[name].astype(bool)
            else:
                df[name] = df[name].astype(object).where(df[name].notna(), None)
        else:
            df[name] = df[name].astype(object).where(df[name].notna(), None)
    return df


def cs_jsonable(v):
    if v is None:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.isoformat()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def cs_sample(df, k):
    """样例行（只交本地模型看列长什么样）：日期写 ISO 文本，空值写 None。"""
    return [{c: cs_jsonable(v) for c, v in rec.items()} for rec in df.head(int(k)).to_dict("records")]


def 拆多值(df, col, sep="、"):
    """把一单多值的列（如机型「A920、A920PRO」）拆成一值一行，其余列照抄；这一列为空的单去掉。"""
    out = df.copy()
    out[col] = out[col].apply(lambda x: [] if fi_blank(x) else [s.strip() for s in str(x).split(sep) if s.strip()])
    out = out.explode(col)
    return out[out[col].apply(lambda x: not fi_blank(x))]


def 合计不良率(df):
    """一个域的合计不良率 = 合计不良数量 ÷ 合计分母 × 100，保留 2 位小数，分母国内是生产数量、巴西是影响数量；
    不良数量为空、分母为 0 或空的单不参与；海外的单不参与（不良率是单上原文）。df 里只能有一个域（国内或巴西）
    的单，几个域要按「所属域」分开调用，混在一起会报错。返回 (不良率或 None, 参与张数, 不参与张数)。"""
    dom_col, bad_col = CS_NAMES["domain"], CS_NAMES["bad"]
    doms = [d for d in fi_unique(df[dom_col].tolist()) if d in CS_NAMES["den"]]
    if len(doms) > 1:
        raise ValueError("合计不良率只能算一个域：国内、巴西的分母不同，请按「所属域」分开调用")
    sub = df[df[dom_col].isin(doms)] if doms else df.iloc[0:0]
    if not doms or len(sub) == 0:
        return None, 0, int(len(df))
    rate, excluded = vw_rate(pd.DataFrame({"_bad": sub[bad_col].tolist(), "_den": sub[CS_NAMES["den"][doms[0]]].tolist()}))
    joined = int(len(sub) - excluded)
    return rate, joined, int(len(df) - joined)


def cs_cell(v):
    """返回值里的一格 → 原生值：numpy 标量转原生，NaN、NaT 转 None，日期转文本，是否转「是」「否」。其余原样留给
    形状检查（列表、字典等会被拦下）。"""
    if v is None:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, (int, str)):
        return v
    if isinstance(v, pd.Timestamp):
        if pd.isna(v):
            return None
        return v.strftime("%Y-%m-%d") if v == v.normalize() else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, pd.Period):
        return str(v)
    if isinstance(v, (cs_dt.date, cs_dt.time)):
        return v.isoformat()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def cs_finish(out):
    """整理模型脚本的返回值。行写成 DataFrame、元组或字典（按 columns 取）的转成列表的列表。"""
    if not isinstance(out, dict):
        return out
    res = dict(out)
    cols = res.get("columns")
    if isinstance(cols, (list, tuple)):
        cols = [cs_cell(c) for c in cols]
        res["columns"] = cols
    rows = res.get("rows")
    if isinstance(rows, pd.DataFrame):
        rows = rows.values.tolist()
    if isinstance(rows, (list, tuple)):
        fixed = []
        for row in rows:
            if isinstance(row, dict) and isinstance(cols, list):
                row = [row.get(c) for c in cols]
            if isinstance(row, (list, tuple)):
                row = [cs_cell(v) for v in row]
            fixed.append(row)
        res["rows"] = fixed
    chart = res.get("chart")
    if isinstance(chart, dict):
        res["chart"] = {k: ([cs_cell(x) for x in v] if isinstance(v, (list, tuple)) else cs_cell(v))
                        for k, v in chart.items()}
    return res
