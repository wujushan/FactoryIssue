"""临时统计与执行中的信号（S7，设计 §5.4、§5.5、§8.1；总述「回答怎么组织」「临时统计」）。

前半不跑沙箱：AST 检查与形状检查的正反例、白名单与沙箱一致、口径函数、列说明、图型、第三种信号那一句。
后半端到端：假 `ctx`、真沙箱、三域假数据（`tests/s3_data.py`）；模型写的脚本按 system 认（`FakeLLM.routes`），
规划与分析按顺序回放。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import cn_data
import numpy as np
import pandas as pd
import pytest
import s3_data
import s6_data
import scopes
from fakes import data_queries, make_harness, run
from forge_core.events import EventType

from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.present import charts
from factory_issue_module.skills import custom_stats, text_search
from factory_issue_module.stats import custom as checks
from factory_issue_module.stats import runner
from factory_issue_module.stats.lib import custom as lib
from factory_issue_module.turn import errors, workspace

T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
SITES = 'issue = "info.test.local"'
MARK = custom_stats.ROUTE_MARKER
NARR = "以上是近 30 天按星期几的分布。周三最多。其余几天比较平均。"

WEEKDAY = '''```python
def run(data):
    df = data["issues"]
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    counts = df["建单时间"].dt.dayofweek.value_counts()
    rows = [[names[i], int(counts.get(i, 0))] for i in range(7)]
    return {"columns": ["星期", "单数"], "rows": rows, "chart": {"type": "bar", "x": "星期", "series": ["单数"]}}
```'''


def plan(*steps: dict) -> dict:
    return {"understanding": "临时统计", "alternatives": [], "steps": list(steps)}


def step(skill: str = "custom_stats", sid: str = "s1", **params) -> dict:
    params.setdefault("describe", "按建单时间是星期几统计单数")
    return {"id": sid, "skill": skill, "when": None, "params": params}


def _types(events) -> list[EventType]:
    return [e.type for e in events]


def _text(events) -> str:
    return "".join(e.data.get("text", "") for e in events if e.type is EventType.DELTA)


def _tables(events) -> list[dict]:
    return [e.data for e in events if e.type is EventType.TABLE]


def scripts(*replies: str):
    """按顺序给出模型写的脚本（写一次、修一次）；多调了就是测错了。"""
    queue = list(replies)

    def reply(_messages):
        assert queue, "临时统计多调了一次模型"
        return queue.pop(0)

    return reply


def harness(*replies, script_replies=(), config: dict | None = None, privileges=None, **kw):
    h = make_harness(scopes.GREEN if privileges is None else privileges, llm_replies=list(replies),
                     config_files={"link_sites.toml": SITES, **(config or {})}, **kw)
    s3_data.load(h)
    h.llm.routes[MARK] = scripts(*script_replies)
    return h


def script_calls(h) -> list:
    return h.llm.routed(MARK)


# ---------------------------------------------------------------------------- 白名单与 AST 检查


def test_allowed_imports_and_builtins_match_the_sandbox():
    """运行时不 import `forge_sandbox`（只是 dev 依赖），白名单抄在代码里：与沙箱 0.2.0 的相同。"""
    from forge_sandbox import harness

    assert checks.ALLOWED_IMPORTS <= set(harness._ALLOWED_IMPORTS)
    assert checks.ALLOWED_IMPORTS == set(harness._ALLOWED_IMPORTS)
    assert checks.SAFE_BUILTINS - {"True", "False", "None"} == set(harness._SAFE_BUILTIN_NAMES)


GOOD = '''
import collections
import pandas as pd
from datetime import date


def run(data):
    df = 拆多值(data["issues"], "机型")
    type = "按机型"  # 自己定义的名字可以与内建函数同名
    rate, ok, bad = 合计不良率(df[df["所属域"] == "国内"])
    c = collections.Counter(df["机型"].tolist())
    return {"columns": ["机型", "单数"], "rows": [[k, v] for k, v in sorted(c.items())],
            "chart": {"type": "bar", "x": "机型", "series": ["单数"]}}
'''


def test_check_script_accepts_a_plain_script():
    assert checks.check_script(GOOD) == []


@pytest.mark.parametrize(("code", "needle"), [
    ("import os\ndef run(data):\n    return {}", "不能 import os"),
    ("from os import path\ndef run(data):\n    return {}", "不能 import os"),
    ("from __future__ import annotations\ndef run(data):\n    return {}", "不能 import __future__"),
    ("from . import x\ndef run(data):\n    return {}", "相对 import"),
    ("def run(data):\n    return open('a').read()", "沙箱里没有 open"),
    ("def run(data):\n    return data.__class__", "双下划线开头的属性：__class__"),
    ("def run(data):\n    return getattr(data, 'x')", "沙箱里没有 getattr"),
    ("def run(data):\n    return hasattr(data, 'x')", "沙箱里没有 hasattr"),
    ("def run(data):\n    return vars(data)", "沙箱里没有 vars"),
    ("def run(data):\n    return eval('1')", "沙箱里没有 eval"),
    ("def run(data):\n    return type(data)", "沙箱里没有 type"),
    ("def run(data):\n    return __import__('os')", "双下划线开头的名字"),
    ("class A:\n    pass\ndef run(data):\n    return {}", "不能定义 class"),
    ("def main(data):\n    return {}", "def run(data)"),
    ("def run(data)\n    return {}", "语法错误"),
    ("def 合计不良率(df):\n    return 1\ndef run(data):\n    return {}", "不要重新定义"),
    ("合计不良率 = None\ndef run(data):\n    return {}", "不要给它重新赋值"),
    ("", "没有给出代码"),
])
def test_check_script_rejects(code, needle):
    problems = checks.check_script(code)
    assert problems and any(needle in p for p in problems), problems


def test_extract_code_takes_the_python_block():
    assert checks.extract_code("<think>想一想</think>好的：\n```python\ndef run(data):\n    return 1\n```\n说明") == \
        "def run(data):\n    return 1"
    assert checks.extract_code("def run(data):\n    return 1") == "def run(data):\n    return 1"


def test_model_error_points_at_the_model_lines():
    error = 'Traceback:\n  File "<sandbox-script>", line 905, in run\nZeroDivisionError: division by zero'
    assert 'line 5, in run' in checks.model_error(error, 900, 10)


def test_model_error_drops_frames_outside_the_model_code():
    """外壳与口径函数那几帧不在模型的代码里：不换算成模型代码里不存在的行号，整行去掉（spike 实测里出现过「第 66 行」）。"""
    error = ('Traceback (most recent call last):\n'
             '  File "/x/harness.py", line 305, in main\n'
             '  File "<sandbox-script>", line 966, in run\n'
             '  File "<sandbox-script>", line 919, in run\n'
             '  File "<sandbox-script>", line 120, in 合计不良率\n'
             'ValueError: 合计不良率只能算一个域')
    text = checks.model_error(error, 900, 30)
    assert 'line 19, in run' in text and "line 66" not in text and "line 120" not in text
    assert "ValueError: 合计不良率只能算一个域" in text


def test_custom_script_offset_is_the_line_before_model_code():
    text, offset = runner.custom_script("def run(data):\n    return 1", {"names": custom_stats.NAMES})
    lines = text.splitlines()
    assert lines[offset] == "def run(data):"  # 第 offset + 1 行（从 1 数）是模型代码的第一行
    assert f"{runner.USER_RUN} = run" in text and text.rstrip().endswith("}  # noqa: F821 —— 拼接时由模型的 run 改名而来")


# ---------------------------------------------------------------------------- 形状检查


def _out(**kw):
    base = {"columns": ["星期", "单数"], "rows": [["周一", 1], ["周二", 2]],
            "chart": {"type": "bar", "x": "星期", "series": ["单数"]}}
    return {**base, **kw}


def test_check_result_accepts_the_fixed_shape():
    assert checks.check_result(_out()) == []
    assert checks.check_result(_out(chart={"type": "none"})) == []
    # 显示名里本来就有的缩写
    assert checks.check_result(_out(columns=["PN", "单数"], chart={"type": "bar", "x": "PN", "series": ["单数"]})) == []


@pytest.mark.parametrize(("out", "needle"), [
    ([["a", 1]], "要返回 dict"),
    ({"columns": ["星期", "单数"], "rows": []}, "缺键：chart"),
    (_out(note="x"), "多了：note"),
    (_out(columns=["weekday", "count"]), "中文业务说法"),
    (_out(columns=["星期", "星期"]), "列名不能重复"),
    (_out(rows=[["周一", 1, 2]]), "第 1 行有 3 个值"),
    (_out(rows=[["周一", [1]]]), "不是数字、文本或 None"),
    (_out(rows=[["周一", math.inf]]), "无穷大"),
    (_out(rows=[[f"第{i}天", i] for i in range(61)]), "超过 60 行"),
    (_out(chart={"type": "area", "x": "星期", "series": ["单数"]}), "chart.type"),
    (_out(chart={"type": "bar", "x": "日期", "series": ["单数"]}), "chart.x"),
    (_out(chart={"type": "bar", "x": "星期", "series": ["星期"]}), "横轴那一列"),
    (_out(chart={"type": "bar", "x": "单数", "series": ["星期"]}), "数值列"),
])
def test_check_result_rejects(out, needle):
    problems = checks.check_result(out)
    assert problems and any(needle in p for p in problems), problems


def test_rows_max_does_not_stop_two_years_by_month():
    """按月看两年是 24 行：表格条数（20）当上限会误拦，上限另设（§19「G4b S7」）。"""
    assert checks.check_result(_out(rows=[[f"2025-{i:02d}", i] for i in range(24)])) == []


# ---------------------------------------------------------------------------- 口径函数与整理（沙箱里的函数，直接 import 测）


@pytest.fixture
def names():
    lib.CS_NAMES.clear()
    lib.CS_NAMES.update(custom_stats.NAMES)
    yield
    lib.CS_NAMES.clear()


def _frame(rows):
    return pd.DataFrame(rows, columns=["所属域", "机型", "不良数量", "生产数量", "影响数量"])


def test_rate_helper_uses_each_domains_denominator_and_skips_overseas(names):
    cn = _frame([["国内", "A920", 2.0, 100.0, 10.0], ["国内", "A920", 1.0, 0.0, 10.0], ["海外", "A920", 9.0, None, 9.0]])
    assert lib.合计不良率(cn) == (2.0, 1, 2)  # 生产数量为 0 的、海外的都不参与
    br = _frame([["巴西", "A920", 5.0, None, 100.0], ["巴西", "A920", None, None, 50.0]])
    assert lib.合计不良率(br) == (5.0, 1, 1)  # 巴西分母是影响数量
    assert lib.合计不良率(_frame([["海外", "A920", 9.0, None, 9.0]])) == (None, 0, 1)


def test_rate_helper_refuses_mixed_domains(names):
    mixed = _frame([["国内", "A920", 2.0, 100.0, 10.0], ["巴西", "A920", 5.0, None, 100.0]])
    with pytest.raises(ValueError, match="分母不同"):
        lib.合计不良率(mixed)


def test_split_helper_counts_each_value_once():
    df = pd.DataFrame({"机型": ["A920、A920PRO", None, "Q92"], "n": [1, 2, 3]})
    out = lib.拆多值(df, "机型")
    assert out["机型"].tolist() == ["A920", "A920PRO", "Q92"] and out["n"].tolist() == [1, 1, 3]


def test_finish_turns_values_into_plain_ones():
    out = lib.cs_finish({"columns": ["日期", "单数", "已结案", "比例"],
                         "rows": [[pd.Timestamp("2026-10-01"), np.int64(3), True, float("nan")]],
                         "chart": {"type": "none", "series": (np.str_("单数"),)}})
    assert out["rows"] == [["2026-10-01", 3, "是", None]] and out["chart"]["series"] == ["单数"]
    rows = lib.cs_finish({"columns": ["a", "b"], "rows": [{"a": "x", "b": 1}, ("y", 2)], "chart": {}})["rows"]
    assert rows == [["x", 1], ["y", 2]]
    frame = pd.DataFrame({"a": ["x"], "b": [1]})
    assert lib.cs_finish({"columns": ["a", "b"], "rows": frame, "chart": {}})["rows"] == [["x", 1]]


def test_frame_columns_keep_only_counted_domains_and_drop_blind_ones():
    cols = custom_stats.frame_columns([Domain.DOMESTIC], {"国内": ["factory"]})
    names = [c["name"] for c in cols]
    assert "加工厂" not in names  # 工厂主数据没取到：不进帧，不写成一列「未填」
    assert "费用（美元）" not in names and "生产数量" in names  # 费用只有巴西有
    assert {c["name"] for c in custom_stats.frame_columns(list(DOMAINS), {})} >= {"费用（美元）", "不良率（%）", "所属域"}
    assert all(not c["name"].startswith("_") for c in cols)


def test_column_notes_come_from_the_glossary():
    assert custom_stats.glossary_note("已结案") == "国内、海外为「已完成」，巴西为「已结案」"
    assert custom_stats.glossary_note("停线时长") == "停线时长 = 重启日期 − 停线日期"
    assert custom_stats.glossary_note("不良率（%）").startswith("单张单的不良比例")
    assert custom_stats.glossary_note("所属域") == ""
    notes = dict((n, d) for n, _k, d in custom_stats.describe_columns(
        custom_stats.frame_columns(list(DOMAINS), {}), list(DOMAINS)))
    assert notes["不良率（%）"].startswith("只有国内、巴西有，其余为空")
    assert notes["所属域"] == "本次有：国内、巴西、海外"


def test_helper_doc_shows_signatures_not_bodies():
    doc = runner.helper_doc(checks.HELPERS)
    assert "def 拆多值(df, col, sep='、'):" in doc and "def 合计不良率(df):" in doc
    assert "vw_rate" not in doc and "CS_NAMES" not in doc
    assert doc in custom_stats.stats_system()


def test_system_is_the_same_for_every_question():
    """§5.6：system 固定，列说明、样例与要算什么都在 user。"""
    system = custom_stats.stats_system()
    assert system == custom_stats.stats_system()
    assert "【样例行】" not in system and "问题编号（文本）" not in system and "本次有：" not in system


def test_choose_custom_follows_the_chart_rules():
    assert charts.choose_custom("pie", 9, user_chart=None) == ("bar", None)  # 饼图超过 8 组改柱状
    assert charts.choose_custom("line", 2, user_chart=None) == ("bar", None)  # 时间点少于 3 个用柱状
    assert charts.choose_custom("bar", 1, user_chart=None) == (None, None)  # 只有一组不画
    assert charts.choose_custom("none", 5, user_chart=None) == (None, None)
    assert charts.choose_custom("bar", 5, user_chart="饼图") == ("pie", None)  # 用户点名照用户的


def test_crowded_hint_names_only_missing_conditions():
    bare = text_search.crowded_hint({"params": {}})
    assert "可以加上时间、机型等条件再查" in bare and "来不及逐张看完" in bare
    timed = text_search.crowded_hint({"params": {"time": T30}})
    assert "可以加上机型、加工厂等条件再查" in timed
    full = text_search.crowded_hint({"params": {"time": T30, "filters": [{"field": "机型"}, {"field": "加工厂"}]}})
    assert "收窄" in full


# ---------------------------------------------------------------------------- 端到端


async def test_custom_stats_answers_with_table_chart_and_caliber():
    h = harness(plan(step(time=T30)), NARR, script_replies=[WEEKDAY])
    events = await run(h, "近 30 天的问题按星期几分布看看")
    # 提示行（以下为临时统计）→ 结论 → 小标题 → 表 → 图 → 统计口径（决策 2026-11-03「回答骨架与排版」）；
    # 接着问只有换时间（§9.5）
    assert _types(events) == [EventType.DELTA, EventType.DELTA, EventType.DELTA, EventType.TABLE, EventType.CHART,
                              EventType.DELTA, EventType.SUGGESTIONS]
    assert [r["query"] for r in events[-1].data["recommendations"]] == ["换成近 90 天看看", "换成今年看看"]
    assert events[0].data["text"] == f"{errors.CUSTOM_HEAD}。"
    assert NARR.split("。")[0] in events[1].data["text"]
    assert events[2].data["text"] == "\n\n**临时统计结果（计入 10 张单：国内 4 张、巴西 4 张、海外 2 张）**"
    text = _text(events)
    table = _tables(events)[0]
    assert table["columns"] == ["星期", "单数"] and len(table["rows"]) == 7
    assert "统计口径" in text and errors.CUSTOM_METHOD in text and "按建单时间" in text
    assert NARR in text
    assert len(script_calls(h)) == 1
    user = script_calls(h)[0][-1]["content"]
    assert "【要算什么】按建单时间是星期几统计单数" in user and "【样例行】" in user and "问题编号（文本）" in user
    # 帧里不带单 ID、辅助列（样例行只给显示名列）
    assert '"_id"' not in user and "_add" not in user
    step_rec = h.workspace.store["turn"]["steps"]["s1"]
    assert step_rec["custom"]["describe"] == "按建单时间是星期几统计单数" and "def run" in step_rec["custom"]["script"]
    assert h.workspace.store["turn"]["v"] == workspace.VERSION == 3


async def test_script_that_imports_os_is_fixed_once_without_running_it():
    bad = "```python\nimport os\ndef run(data):\n    return {}\n```"
    h = harness(plan(step(time=T30)), NARR, script_replies=[bad, WEEKDAY])
    events = await run(h, "近 30 天的问题按星期几分布看看")
    calls = script_calls(h)
    assert len(calls) == 2 and "不能 import os" in calls[1][-1]["content"]
    assert calls[1][-2] == {"role": "assistant", "content": bad}  # 修一次：前两条原样沿用（§5.6）
    assert len(h.stats.calls) == 2  # 沙箱 ① 一次、合格的脚本一次；没过 AST 检查的不进沙箱
    assert _tables(events)[0]["columns"] == ["星期", "单数"]


@pytest.mark.parametrize(("bad", "needle"), [
    ("def run(data):\n    return open('x')", "沙箱里没有 open"),
    ("def run(data):\n    return data.__class__", "__class__"),
    ("def run(data):\n    return getattr(data, 'issues')", "沙箱里没有 getattr"),
    ("class A:\n    pass\n\ndef run(data):\n    return {}", "不能定义 class"),
])
async def test_forbidden_scripts_are_stopped_before_the_sandbox(bad, needle):
    h = harness(plan(step(time=T30)), NARR, script_replies=[f"```python\n{bad}\n```", WEEKDAY])
    events = await run(h, "近 30 天的问题按星期几分布看看")
    assert needle in script_calls(h)[1][-1]["content"]
    assert len(h.stats.calls) == 2 and _tables(events)


async def test_runtime_error_is_shown_to_the_model_with_its_own_line_numbers():
    crash = "```python\ndef run(data):\n    x = 1\n    return 1 / 0\n```"
    h = harness(plan(step(time=T30)), NARR, script_replies=[crash, WEEKDAY])
    events = await run(h, "近 30 天的问题按星期几分布看看")
    repair = script_calls(h)[1][-1]["content"]
    assert "脚本运行出错" in repair and "ZeroDivisionError" in repair and "line 3" in repair
    assert "ZeroDivisionError" not in _text(events) and _tables(events)  # 报错原文只给模型看


async def test_wrong_shape_is_fixed_once():
    shapeless = '```python\ndef run(data):\n    return {"星期": ["周一"], "单数": [1]}\n```'
    h = harness(plan(step(time=T30)), NARR, script_replies=[shapeless, WEEKDAY])
    events = await run(h, "近 30 天的问题按星期几分布看看")
    assert "缺键" in script_calls(h)[1][-1]["content"] and _tables(events)


async def test_still_wrong_after_one_fix_says_so_with_buttons_and_no_error():
    too_many = ('```python\ndef run(data):\n    return {"columns": ["序号", "单数"], "rows": [[i, 1] for i in range(80)],'
                ' "chart": {"type": "none"}}\n```')
    h = harness(plan(step(time=T30)), script_replies=[too_many, too_many])
    events = await run(h, "近 30 天每张单编个号")
    assert "超过 60 行" in script_calls(h)[1][-1]["content"]
    assert EventType.ERROR not in _types(events) and EventType.TABLE not in _types(events)
    assert errors.CUSTOM_FAILED in _text(events)
    recs = next(e for e in events if e.type is EventType.SUGGESTIONS).data["recommendations"]
    assert len(recs) == 3 and all(isinstance(r, dict) for r in recs)
    assert h.workspace.store["last"]["outcome"] == workspace.OUTCOME_FAILED


async def test_model_call_error_says_not_computed():
    h = harness(plan(step(time=T30)))
    h.llm.routes[MARK] = lambda _m: TimeoutError("超时")
    events = await run(h, "近 30 天的问题按星期几分布看看")
    assert errors.CUSTOM_FAILED in _text(events) and EventType.ERROR not in _types(events)


async def test_disabled_answers_without_fetching_or_writing_a_script():
    h = harness(plan(step(time=T30)), config={"answer_params.toml": "custom_stats_enabled = false"})
    events = await run(h, "近 30 天的问题按星期几分布看看")
    assert errors.CUSTOM_DISABLED in _text(events) and EventType.ERROR not in _types(events)
    assert data_queries(h) == [] and script_calls(h) == []
    assert any(e.type is EventType.SUGGESTIONS for e in events)


async def test_no_issues_means_no_script():
    h = make_harness(scopes.account_jia(), llm_replies=[plan(step(time=T30, domains={"value": ["国内"], "from": "user"}))],
                     config_files={"link_sites.toml": SITES})
    cn_data.load(h, main=lambda _sql, _params: pd.DataFrame())
    events = await run(h, "近 30 天国内的问题按星期几分布看看")
    assert "国内，" in _text(events) and "没有查到单" in _text(events)
    assert script_calls(h) == [] and EventType.ERROR not in _types(events)


async def test_empty_recent_offers_relaxed_time_counted_without_a_script():
    """结果为空、只说「最近」：照统计那一套预查放宽选项的张数，临时统计只跑沙箱 ①、不写脚本（§5.4）。"""
    cutoff = datetime.combine(date.today() - timedelta(days=40), datetime.min.time())

    def main(_sql: str, params: dict) -> pd.DataFrame:
        starts = [v for v in params.values() if isinstance(v, datetime)]
        return pd.DataFrame() if starts and min(starts) > cutoff else pd.DataFrame(cn_data.main_rows())

    recent = [{"said": "最近", "basis": "建单", "from": "user"}]
    h = make_harness(scopes.account_jia(), llm_replies=[plan(step(time=recent, domains={"value": ["国内"], "from": "user"}))],
                     config_files={"link_sites.toml": SITES})
    cn_data.load(h, main=main)
    events = await run(h, "国内最近的问题按星期几分布看看")
    assert "没有查到单" in _text(events) and script_calls(h) == []
    labels = [r["label"] for r in next(e for e in events if e.type is EventType.SUGGESTIONS).data["recommendations"]]
    # 2026-11-03 起：只放宽一个条件（总述「结果为空时」）；临时统计不写「最近建单的一张」
    assert labels == ["看近 90 天（4 张）", "不限时间（4 张）"]
    assert "只放宽一个条件时：时间放到近 90 天有 4 张；不限时间有 4 张。" in _text(events)


async def test_second_custom_stats_in_one_turn_is_asked_again():
    two = plan(step(time=T30), step(sid="s2", time=T30, describe="按小时统计单数"))
    h = harness(two, NARR, script_replies=[WEEKDAY])
    events = await run(h, "近 30 天按星期几、按小时分别看看")
    assert len(script_calls(h)) == 1 and errors.CUSTOM_SECOND in _text(events)
    assert len(_tables(events)) == 1


async def test_overseas_rate_is_listed_as_written_when_the_script_uses_rates():
    by_domain = '''```python
def run(data):
    df = data["issues"]
    rows = []
    for dom in ["国内", "巴西"]:
        rate, ok, _ = 合计不良率(df[df["所属域"] == dom])
        rows.append([dom, rate, ok])
    return {"columns": ["所属域", "合计不良率（%）", "参与张数"], "rows": rows,
            "chart": {"type": "bar", "x": "所属域", "series": ["合计不良率（%）"]}}
```'''
    h = harness(plan(step(time=T30, describe="各域的合计不良率")), script_replies=[by_domain])
    events = await run(h, "近 30 天各域的合计不良率")
    text = _text(events)
    assert "海外不良率为单上原文（% 与 ‰ 混用），不汇总" in text
    titles = [t["title"] for t in _tables(events)]
    assert any("海外不良率（单上原文）" in t for t in titles)
    assert "不良率 = " in text or "国内不良率" in text  # 统计口径照统计那一套写不良率


async def test_mixed_domain_rate_is_refused_and_fixed():
    mixed = '''```python
def run(data):
    rate, ok, _ = 合计不良率(data["issues"])
    return {"columns": ["合计不良率（%）"], "rows": [[rate]], "chart": {"type": "none"}}
```'''
    split = '''```python
def run(data):
    df = data["issues"]
    rate, ok, _ = 合计不良率(df[df["所属域"] == "国内"])
    return {"columns": ["国内合计不良率（%）"], "rows": [[rate]], "chart": {"type": "none"}}
```'''
    h = harness(plan(step(time=T30, describe="合计不良率")), script_replies=[mixed, split])
    events = await run(h, "近 30 天三个域合起来的不良率")
    assert "分母不同" in script_calls(h)[1][-1]["content"] and _tables(events)


async def test_caliber_follows_the_derived_columns_the_script_uses():
    closed = '''```python
def run(data):
    df = data["issues"]
    done = df[df["已结案"].astype(bool) & df["结案周期"].notna()]
    rows = [[d, int((done["所属域"] == d).sum())] for d in ["国内", "巴西", "海外"]]
    return {"columns": ["所属域", "单数"], "rows": rows, "chart": {"type": "none"}}
```'''
    h = harness(plan(step(time=T30, describe="各域已结案的单数")), NARR, script_replies=[closed])
    events = await run(h, "近 30 天各域已结案的有多少")
    text = _text(events)
    assert "结案：" in text and "结案时间：" in text and errors.CUSTOM_METHOD in text


def _cn_with_unclosed_done() -> pd.DataFrame:
    """国内假单再加一张：已完成、近期建单，却没有结案确认记录（结案时间定不出）。"""
    extra = {**cn_data.main_rows()[1], "ID": 5, "Numbers": "ZC9901005", "Status": 32, "MHead": None,
             "AddDate": cn_data._ts(6)}
    return pd.DataFrame([*cn_data.main_rows(), extra])


CLOSED_DAYS = '''```python
def run(data):
    df = data["issues"]
    done = df[df["已结案"].astype(bool) & df["结案周期"].notna()]
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    counts = done["结案时间"].dt.dayofweek.value_counts()
    rows = [[names[i], int(counts.get(i, 0))] for i in range(7)]
    return {"columns": ["结案日", "单数"], "rows": rows, "chart": {"type": "bar", "x": "结案日", "series": ["单数"]}}
```'''


def _cn_harness(*replies, script_replies=()):
    h = make_harness(scopes.account_jia(), llm_replies=list(replies), config_files={"link_sites.toml": SITES})
    cn_data.load(h, main=_cn_with_unclosed_done())
    h.llm.routes[MARK] = scripts(*script_replies)
    return h


async def test_review_m1_basis_other_than_add_date_with_blank_dates_does_not_fail():
    """S7 评审 M1：按结案时间筛、范围内有已完成却定不出结案时间的单时，口径照统计写「结案时间没填的 N 张未计入」，
    不因「未计入」的形状不对抛异常、整轮失败。"""
    closed30 = [{"said": "近 30 天", "basis": "结案", "from": "user"}]
    h = _cn_harness(plan(step(time=closed30, domains={"value": ["国内"], "from": "user"},
                              describe="按结案日是星期几统计单数")), NARR, script_replies=[CLOSED_DAYS])
    events = await run(h, "近 30 天国内结案的单按结案日是星期几看看")
    assert EventType.ERROR not in _types(events) and _tables(events)
    text = _text(events)
    assert "按结案时间" in text and "结案时间没填的 1 张未计入" in text


async def test_review_m2_closed_without_close_record_is_said_in_the_caliber():
    """S7 评审 M2：脚本用到结案时间、结案周期，又有已完成却没有结案确认记录的单时，统计口径照统计写出这几张未计入。"""
    h = _cn_harness(plan(step(time=T30, domains={"value": ["国内"], "from": "user"},
                              describe="已结案的单按结案日是星期几统计")), NARR, script_replies=[CLOSED_DAYS])
    events = await run(h, "近 30 天国内已结案的单按结案日是星期几看看")
    text = _text(events)
    assert "结案时间：" in text and "已完成但没有结案确认记录的 1 张未计入" in text


async def test_verify_and_rerender_replay_the_stored_script_without_the_model():
    h = make_harness(scopes.GREEN, history=[], config_files={"link_sites.toml": SITES})
    s3_data.load(h)
    h.llm.routes[MARK] = scripts(WEEKDAY)

    async def ask(query, *replies):
        h.llm.replies += list(replies)
        events = await run(h, query)
        h.ctx.session.rows += [{"role": "user", "content": query, "message_id": query},
                               {"role": "assistant", "content": _text(events), "message_id": query}]
        return events

    await ask("近 30 天的问题按星期几分布看看", plan(step(time=T30)), NARR)
    verify = await ask("你确定吗", plan(step("verify_previous", describe=None)))
    assert "与上一轮一致" in _text(verify) and EventType.ERROR not in _types(verify)
    assert len(script_calls(h)) == 1  # 重查照存下的脚本，没再调模型
    redraw = await ask("换成饼图", plan(step("rerender", chart="饼图", describe=None)))
    chart = next(e.data for e in redraw if e.type is EventType.CHART)
    assert chart["chart_type"] == "pie" and len(script_calls(h)) == 1


async def test_follow_up_with_the_same_describe_reuses_the_script():
    h = make_harness(scopes.GREEN, history=[], config_files={"link_sites.toml": SITES})
    s3_data.load(h)
    h.llm.routes[MARK] = scripts(WEEKDAY)
    for query, replies in (("近 30 天的问题按星期几分布看看", [plan(step(time=T30)), NARR]),
                           ("那今年呢", [plan(step(time=[{"said": "今年", "basis": "建单", "from": "user"}])), NARR])):
        h.llm.replies += replies
        events = await run(h, query)
        h.ctx.session.rows += [{"role": "user", "content": query, "message_id": query},
                               {"role": "assistant", "content": _text(events), "message_id": query}]
        assert _tables(events)
    assert len(script_calls(h)) == 1


async def test_custom_stats_is_not_ready_no_more():
    """S1 起的过渡话术「这一类查询暂时还答不了」随 S7 去掉。"""
    h = harness(plan(step(time=T30)), NARR, script_replies=[WEEKDAY])
    events = await run(h, "近 30 天的问题按星期几分布看看")
    assert "暂时还答不了" not in _text(events) and not hasattr(errors, "NOT_READY")


# ---------------------------------------------------------------------------- 第三种信号：候选太多（文字查找）


def _ts_harness(n_hits: int):
    h = make_harness(scopes.account_jia(), llm_replies=[plan(step("text_search", mode="话题", topic="触摸",
                                                                    domains={"value": ["国内"], "from": "user"},
                                                                    describe=None))],
                     config_files={"link_sites.toml": SITES, "answer_params.toml": "judge_max = 1"})
    s6_data.load(h)
    h.retrieval.hits = [[s6_data.hit(i, "desc", f"问题描述：第 {i} 张") for i in range(1, n_hits + 1)]]
    h.llm.routes["是否与用户要找的话题有关"] = lambda m: {"results": [{"no": 1, "related": True}]}
    h.llm.routes["浓缩成一两句话"] = lambda m: {"items": []}
    return h


async def test_crowded_third_group_suggests_more_conditions():
    """取回的张数到了上限（`judge_max` 为 1 时上限是 `THIRD_MAX` 的 10 张）：建议加条件，只点用户没给的。"""
    h = _ts_harness(text_search.THIRD_MAX)
    events = await run(h, "国内有没有涉及触摸的问题")
    assert "来不及逐张看完" in _text(events) and "可以加上时间、机型等条件再查" in _text(events)


async def test_third_group_within_limit_says_nothing_more():
    h = _ts_harness(2)
    events = await run(h, "国内有没有涉及触摸的问题")
    assert "来不及逐张看完" not in _text(events)
