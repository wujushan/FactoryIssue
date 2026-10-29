"""护栏测试（设计 §15）：单测照样能过、却会直接变成用户看到的东西的几类错，单独查。每片都跑。

- 不露字段名：每条用户可见的路径用假 `ctx` 跑一遍，正文、表头、图表、按钮、错误话术里不含
  `db_description` 的物理表名、列名、JSON 键名与数据源别名。按英文词边界匹配；显示名里本来就有的
  （CAR、PN、PO）不算；链接地址里的参数不算。
- 不直算：AST 检查 `src`，`stats/lib/`、`stats/tasks/`、`jobs/` 之外没有聚合类的属性调用；除
  `stats/runner.py` 外不 import `stats.lib`、`stats.tasks`。内建的 `len`、`max`、`sorted`、`sum`
  查不出来，列在任务单每片的评审清单里。
- 取数写法：`src` 里没有 `ctx.data.query(` 与 `ctx.data.raw(`（`jobs/` 经 `ctx.etl`，不在此列）。
- 按钮形状：`suggestions` 与 `clarify` 的每个选项都是带 id、name、label、query 的对象，label 不超过 15 字。
- 只有一条 system 且在最前：假模型每次调用都查（`fakes.FakeLLM.check_messages`），这里再兜一遍。

盐值、密钥的片段不进日志（§9.1）随 S3、S4 用到它们时加进来；站点地址来自模块配置 `link_sites.toml`，不是凭据。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import cn_data
import pytest
import scopes
from fakes import MANIFEST, FakeLLM, Harness, make_harness, run
from forge_core.events import Event, EventType

from factory_issue_module import landed
from factory_issue_module.declarations import DOMAINS, ERP, INFO, MART, Domain
from factory_issue_module.turn import gate, greeting

SRC = Path(__file__).resolve().parents[1] / "src" / "factory_issue_module"

# ---------------------------------------------------------------- 跑一遍每条用户可见的路径

#: （说明, 权限, 问句）。每片把新接上的技能加进来。
SCENARIOS: list[tuple[str, dict | None, str]] = [
    ("三域都无权·问数据", scopes.no_domain(), "帮我查下制程问题"),
    ("三域都无权·寒暄", scopes.no_domain(), "你好，你能帮我查什么？"),
    ("没拿到权限", None, "你好"),
    ("三域都无权·空问句", scopes.no_domain(), "？？？"),
    ("只国内·空问句", scopes.account_jia(), "……"),
    ("只国内·规划层接上之前", scopes.account_jia(), "上个月国内的问题有哪些"),
    ("全放开·规划层接上之前", scopes.GREEN, "6 月总共发生多少制程问题？"),
]


_CN = {"value": ["国内"], "from": "user"}
_T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
_NARR = "共 4 张，硬件问题最多。最需要关注的是 ZC9901001。"


def _plan(skill: str, **params) -> dict:
    return {"understanding": "x", "alternatives": [],
            "steps": [{"id": "s1", "skill": skill, "when": None, "params": params}]}


#: S2 起接上的技能：（说明, 权限, 问句, 模型回复）。用国内假数据（`tests/cn_data.py`）跑。
EXEC_SCENARIOS: list[tuple[str, dict, str, list]] = [
    ("国内清单", scopes.account_jia(), "近 30 天国内的问题有哪些", [_plan("list_issues", domains=_CN, time=_T30), _NARR]),
    ("国内清单·点名列", scopes.account_jia(), "列出近 30 天国内的单号、处理人、当前状态、责任人、结案时间、手机号",
     [_plan("list_issues", domains=_CN, time=_T30, columns=["单号", "处理人", "当前状态", "责任人", "结案时间", "手机号"]),
      _NARR]),
    ("国内按类型统计", scopes.account_jia(), "近 30 天国内按问题类型统计",
     [_plan("aggregate", domains=_CN, time=_T30, group_by=["问题类型"], metrics=["单数", "占比"]), _NARR]),
    ("国内按工厂与责任部门", scopes.account_jia(), "近 30 天国内按工厂、责任部门统计",
     [_plan("aggregate", domains=_CN, time=_T30, group_by=["加工厂", "责任归属部门"]), _NARR, _NARR]),
    ("国内概况", scopes.account_jia(), "近 30 天国内平均多久结案、停了多久",
     [_plan("aggregate", domains=_CN, time=_T30, metrics=["结案周期", "停线时长", "合计不良率"]), _NARR]),
    ("全放开·不点域", scopes.GREEN, "近 30 天的问题有哪些", [_plan("list_issues", time=_T30), _NARR]),
    ("国内·机型对不上", scopes.account_jia(), "国内 Z999 的问题",
     [_plan("list_issues", domains=_CN, filters=[{"field": "机型", "op": "是", "value": "Z999", "from": "user"}])]),
]


async def _all_events() -> list[tuple[str, Harness, list[Event]]]:
    out = []
    for name, privileges, query in SCENARIOS:
        h = make_harness(privileges, resolved=privileges is not None)
        out.append((name, h, await run(h, query)))
    for name, privileges, query, replies in EXEC_SCENARIOS:
        h = make_harness(privileges, llm_replies=replies)
        cn_data.load(h)
        events = await run(h, query)
        assert any(e.type in (EventType.TABLE, EventType.CLARIFY) for e in events), name
        out.append((name, h, events))
    for domains in ([], [Domain.DOMESTIC], list(DOMAINS)):
        access = gate.DomainAccess(
            domains=frozenset(domains), car=False, text_search=frozenset(domains)
        )
        out.append((f"能力介绍·{len(domains)} 域", None, greeting.introduce(MANIFEST, access)))
    return out


def _visible_strings(event: Event) -> list[str]:
    d = event.data
    out: list[str] = []
    if event.type is EventType.DELTA:
        out.append(d.get("text", ""))
    elif event.type is EventType.TABLE:
        out += [d.get("title", ""), *map(str, d.get("columns", []))]
        out += [str(c) for row in d.get("rows", []) for c in (row.values() if isinstance(row, dict) else row)]
    elif event.type is EventType.CHART:
        x = d.get("x") or {}
        out += [d.get("title", ""), d.get("unit", ""), str(x.get("name", "")), *map(str, x.get("data", []))]
        out += [str(s.get("name", "")) for s in d.get("series", [])]
    elif event.type in (EventType.CLARIFY, EventType.SUGGESTIONS):
        out += [d.get("question", ""), d.get("guide_text", ""), *map(str, d.get("options", []))]
        for rec in d.get("recommendations", []):
            if isinstance(rec, dict):
                out += [str(rec.get(k, "")) for k in ("name", "label", "query")]
            else:
                out.append(str(rec))
    elif event.type is EventType.ERROR:
        out += [d.get("code", ""), d.get("message", "")]
    return out


def _physical_names() -> tuple[set[str], set[str]]:
    """（禁出现的名字, 显示名里本来就有、因而豁免的名字）。"""
    names: set[str] = {INFO, ERP, MART, "dbo", "CoreINFO", "paxbase", "public"}
    for doc in landed.table_docs().values():
        names |= {doc.table, *doc.table.split("."), *doc.columns, *doc.keys}
    names |= {t for d in DOMAINS for t in d.mart_tables}
    shown: set[str] = set()
    for doc in landed.table_docs().values():
        for display in [*doc.columns.values(), *doc.keys.values()]:
            shown |= {w.lower() for w in re.findall(r"[A-Za-z0-9_]+", display or "")}
    for term in landed.glossary():
        for s in (term.term, *term.aliases):
            shown |= {w.lower() for w in re.findall(r"[A-Za-z0-9_]+", s)}
    exempt = {n for n in names if n.lower() in shown}
    return names - exempt, exempt


_URL = re.compile(r"\]\([^)]*\)|https?://\S+|/f/\S+")


def test_exempt_names_are_only_the_ones_shown_as_is():
    _forbidden, exempt = _physical_names()
    assert exempt == {"CAR", "PN", "PO"}


def _leaks(events: list[Event]) -> list[tuple[str, str]]:
    forbidden, _ = _physical_names()
    out = []
    for event in events:
        for text in _visible_strings(event):
            text = _URL.sub("", text)
            for n in forbidden:
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text, re.I):
                    out.append((n, text[:60]))
    return out


def test_leak_check_catches_names_and_skips_links():
    caught = _leaks([
        Event.delta("按 ZCTracking_ProblemList 查"),
        Event.table(["问题编号", "Status"], [["ZC9901001", "已完成"]]),
        Event.error("X", "info 连不上"),
        Event.suggestions([{"id": "1", "name": "a", "label": "a", "query": "看 AddDate"}]),
    ])
    assert {n for n, _ in caught} >= {"ZCTracking_ProblemList", "Status", "info", "AddDate"}
    assert _leaks([Event.delta("CAR 编号、PN、PO 照给；[ZC9901001](https://x/a?id=1&Status=2)")]) == []
    assert _leaks([Event.delta("国内单号ID")]) != []  # 汉字后面紧跟英文也算边界


async def test_no_table_or_column_names_reach_the_user():
    leaks = []
    for name, _h, events in await _all_events():
        leaks += [(name, *leak) for leak in _leaks(events)]
    assert leaks == []


async def test_buttons_are_objects_with_short_labels():
    seen = 0
    for name, _h, events in await _all_events():
        for event in events:
            assert event.type is not EventType.END, name
            if event.type not in (EventType.CLARIFY, EventType.SUGGESTIONS):
                continue
            recs = event.data.get("recommendations", [])
            ids = [r.get("id") for r in recs]
            assert len(ids) == len(set(ids)), name
            for rec in recs:
                seen += 1
                assert isinstance(rec, dict), (name, rec)
                for key in ("id", "name", "label", "query"):
                    assert isinstance(rec.get(key), str) and rec[key].strip(), (name, key, rec)
                assert len(rec["label"]) <= 15, (name, rec)
    assert seen > 0


async def test_every_model_call_has_one_leading_system():
    for name, h, _events in await _all_events():
        if h is None:
            continue
        for messages in h.llm.calls:
            FakeLLM.check_messages(messages)


def test_fake_llm_rejects_a_second_system():
    with pytest.raises(AssertionError):
        FakeLLM.check_messages([{"role": "system", "content": "a"}, {"role": "system", "content": "b"}])
    with pytest.raises(AssertionError):
        FakeLLM.check_messages([{"role": "user", "content": "a"}, {"role": "system", "content": "b"}])


# ---------------------------------------------------------------- 静态检查 src

_COMPUTE_ALLOWED = ("stats/lib/", "stats/tasks/", "jobs/")
_AGGREGATES = {
    "groupby", "value_counts", "nunique", "agg", "aggregate", "pivot_table", "pivot", "crosstab",
    "sum", "mean", "median", "std", "var", "quantile", "cumsum", "cumcount", "idxmax", "idxmin",
    "rank", "nlargest", "nsmallest", "max", "min", "prod", "mode",
}


def _sources() -> list[tuple[str, ast.Module]]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        out.append((rel, ast.parse(path.read_text(encoding="utf-8"), filename=rel)))
    return out


def test_src_tree_is_found():
    rels = [rel for rel, _ in _sources()]
    assert "module.py" in rels and "turn/gate.py" in rels


def _aggregation_hits(sources: list[tuple[str, ast.Module]]) -> list[str]:
    hits = []
    for rel, tree in sources:
        if rel.startswith(_COMPUTE_ALLOWED):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _AGGREGATES
            ):
                hits.append(f"{rel}:{node.lineno} .{node.func.attr}(")
    return hits


def _executor_import_hits(sources: list[tuple[str, ast.Module]]) -> list[str]:
    hits = []
    for rel, tree in sources:
        # runner 按源码文本拼脚本；lib、tasks 自己之间的 import 在拼接时去掉，本来就是执行器的代码
        if rel == "stats/runner.py" or rel.startswith(("stats/lib/", "stats/tasks/")):
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level and rel.startswith("stats/"):
                    base = f"stats.{base}" if base else "stats"
                mods = [base, *(f"{base}.{a.name}" for a in node.names)]
            for mod in mods:
                if re.search(r"(^|\.)stats\.(lib|tasks)(\.|$)", mod):
                    hits.append(f"{rel}:{node.lineno} {mod}")
    return hits


def _raw_query_hits(sources: list[tuple[str, ast.Module]]) -> list[str]:
    hits = []
    for rel, tree in sources:
        if rel.startswith("jobs/"):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"query", "raw"}
            ):
                owner = node.func.value
                if (isinstance(owner, ast.Attribute) and owner.attr == "data") or (
                    isinstance(owner, ast.Name) and owner.id == "data"
                ):
                    hits.append(f"{rel}:{node.lineno} data.{node.func.attr}(")
    return hits


def test_no_aggregation_outside_executors():
    assert _aggregation_hits(_sources()) == []


def test_stats_lib_and_tasks_only_imported_by_runner():
    assert _executor_import_hits(_sources()) == []


def test_no_raw_query_on_data_handle():
    assert _raw_query_hits(_sources()) == []


def test_static_checks_catch_crafted_violations():
    bad = ast.parse(
        "import pandas as pd\n"
        "from factory_issue_module.stats.lib import derive\n"
        "n = df.groupby('a').size()\n"
        "total = df['x'].sum()\n"
        "rows = ctx.data.query('info', 't', select=['a'])\n"
        "more = data.raw('select 1', source='info', scope_on=[], table='t')\n"
    )
    assert len(_aggregation_hits([("skills/x.py", bad)])) == 2
    assert _aggregation_hits([("stats/lib/x.py", bad)]) == []
    assert len(_executor_import_hits([("present/x.py", bad)])) >= 1
    assert _executor_import_hits([("stats/runner.py", bad)]) == []
    rel_import = ast.parse("from .lib import derive\nfrom . import tasks\n")
    lines = {h.split()[0] for h in _executor_import_hits([("stats/custom.py", rel_import)])}
    assert lines == {"stats/custom.py:1", "stats/custom.py:2"}
    assert len(_raw_query_hits([("domains/x.py", bad)])) == 2
    assert _raw_query_hits([("jobs/x.py", bad)]) == []
