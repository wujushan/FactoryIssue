"""分析段核数与写、删、重写一次、模板句（设计 §8.1、§8.3）；沙箱脚本拼接；问题编号链接取本环境的站点配置（§9.1、§11）。"""

from __future__ import annotations

import ast

from fakes import MANIFEST, FakeLLM

from factory_issue_module.config import files
from factory_issue_module.declarations import LINK_SITES, Domain
from factory_issue_module.present import links, narrative
from factory_issue_module.stats import runner

FACTS = {"时间范围": "2026-01-01 至 2026-06-30", "总单数": 37, "按机型": [["A920", 12], ["L1400", 8], ["Q80", 5]],
         "按机型（项数）": 3}
Q = "2026 上半年国内哪个机型问题最多"


def _bad(text: str, entities=None) -> list[str]:
    return [b["句子"] for b in narrative.check(Q, None, None, FACTS, text, entities or {})["bad"]]


def test_happen_time_is_found_date_column():
    """决策 2026-10-29「发生时间按现场发现日期」（CN-021）：术语表的别称接到列上，代码里没有特例。"""
    from factory_issue_module.present import columns

    assert columns.resolve("发生时间") == columns.resolve("发现时间") == "found_date"
    assert columns.shown("found_date") == "现场发现日期"


def test_list_item_count_and_nth_rank_are_not_made_up_numbers():
    """T10：引用事实里列表的项数、「第 N 名」（N 不超过最长的列表）不算编数。"""
    assert _bad("共列出 3 个机型，第二名是 L1400。") == []
    assert _bad("它排在第九名。") == ["它排在第九名"]
    assert _bad("合计 99 张。") == ["合计 99 张"]
    assert _bad("超过一半集中在 A920。") == ["超过一半集中在 A920"]
    assert _bad("最需要关注的是 ZC9909999。") == ["最需要关注的是 ZC9909999"]
    assert _bad("问题集中在 A8700。", {"A8700": ["机型"]}) == ["问题集中在 A8700"]


def test_system_is_template_plus_analysis_dimensions():
    system = narrative.narrative_system(MANIFEST)
    assert system.startswith(narrative.NARRATIVE_MODULE_SYSTEM) and "初步分析维度" in system or "维度" in system
    assert narrative.narrative_system(MANIFEST) == system  # 不随问句变


async def test_write_drops_bad_sentence_and_keeps_the_rest():
    llm = FakeLLM(["共 37 张，A920 最多。其次是 L1400。超过一半集中在 A920。"])
    text = await narrative.write(llm, MANIFEST, Q, None, None, FACTS, {}, "模板句。")
    assert text == "共 37 张，A920 最多。其次是 L1400。"
    assert len(llm.calls) == 1 and llm.calls[0][0]["role"] == "system"


async def test_write_retries_once_then_falls_back_to_template():
    llm = FakeLLM(["合计 99 张。", "合计 98 张。"])
    assert await narrative.write(llm, MANIFEST, Q, None, None, FACTS, {}, "共 37 张。") == "共 37 张。"
    assert len(llm.calls) == 2 and len(llm.calls[1]) == 4 and "99" in llm.calls[1][-1]["content"]


async def test_write_falls_back_when_model_errors():
    llm = FakeLLM([TimeoutError("超时")])
    assert await narrative.write(llm, MANIFEST, Q, None, None, FACTS, {}, "共 37 张。") == "共 37 张。"


def test_sandbox_script_strips_internal_imports_and_compiles():
    script = runner.script("list", {"x": 1})
    assert "factory_issue_module" not in script and "__future__" not in script
    assert script.count("PARAMS = json.loads(") == 1
    tree = ast.parse(script)
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"run", "cn_view", "vw_filter", "fi_rank", "compact"} <= names
    for node in ast.walk(tree):
        assert not isinstance(node, ast.ClassDef)
        if isinstance(node, ast.Import | ast.ImportFrom):
            mod = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            assert mod.split(".")[0] in {"re", "math", "json", "pandas", "datetime"}, mod


def test_issue_link_uses_configured_site():
    assert links.issue(None, Domain.DOMESTIC, "ZC9901001", 1) == "ZC9901001"  # 没配站点时只给编号文字
    assert links.issue(files.LinkSites(), Domain.DOMESTIC, "ZC9901001", 1) == "ZC9901001"
    sites = files.parse_link_sites('issue = "info-test.example.test:8080"\n')
    assert links.issue(sites, Domain.DOMESTIC, "ZC9901001", 7) == \
        "[ZC9901001](https://info-test.example.test:8080/#/QualityManage/ProblemDetail?id=7)"
    assert links.issue(sites, Domain.OVERSEAS, "HW9901001", 3) == \
        "[HW9901001](https://info-test.example.test:8080/#/QualityManage/OverseasProblemAllDetail?id=3)"
    # 巴西链接 S3 接上：brazil 没写时与 issue 相同；两个参数是大写十六进制
    brazil = links.issue(sites, Domain.BRAZIL, "BR9901001", 7)
    assert brazil.startswith("[BR9901001](https://info-test.example.test:8080/#/BrazilProblem/AddBrazilProblemPage?type=")
    kind, ident = brazil.split("type=")[1].rstrip(")").split("&ID=")
    assert kind.isupper() and ident.isupper() and len(kind) == 32 and kind != ident


async def test_list_links_follow_the_uploaded_config_per_environment():
    """站点地址随环境不同：同一轮问答，测试环境传的是测试站点、正式环境传的是正式站点，链接跟着配置走。"""
    import cn_data
    import scopes
    from fakes import make_harness, run

    plan = {"understanding": "x", "alternatives": [], "steps": [{"id": "s1", "skill": "list_issues", "when": None,
            "params": {"domains": {"value": ["国内"], "from": "user"},
                       "time": [{"said": "近 30 天", "basis": "建单", "from": "user"}]}}]}
    for host in ("info-test.example.test", "info.example.test"):
        files._cache.clear()  # 两个假环境的版本号都是 1；线上一个进程只连一个环境，（文件名, 版本）不会撞
        h = make_harness(scopes.account_jia(), llm_replies=[plan, "共 4 张。最需要关注的是 ZC9901001。"],
                         config_files={LINK_SITES: f'issue = "{host}"\n'})
        cn_data.load(h)
        events = await run(h, "近 30 天国内的问题有哪些")
        table = next(e for e in events if e.type.value == "table")
        assert table.data["rows"][0][0] == f"[ZC9901001](https://{host}/#/QualityManage/ProblemDetail?id=1)"
        assert LINK_SITES in h.config.reads
    h = make_harness(scopes.account_jia(), llm_replies=[plan, "共 4 张。最需要关注的是 ZC9901001。"])
    cn_data.load(h)
    events = await run(h, "近 30 天国内的问题有哪些")
    assert next(e for e in events if e.type.value == "table").data["rows"][0][0] == "ZC9901001"  # 没传：纯文字
