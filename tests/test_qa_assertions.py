"""qa_test.check 的断言分支。不打平台、不连库。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("qa_test", ROOT / "scripts" / "qa_test.py")
qa = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(qa)


def test_clarify_round_is_expected_when_asked():
    case = {"expect": {"clarify": True, "max_queries": 0, "module": "FACTORY_ISSUE"}}
    ok = {
        "module": "FACTORY_ISSUE",
        "error": None,
        "clarify": {"question": "请选择时间"},
        "query_count": 0,
        "answer": "",
        "tables": [],
    }
    assert qa.check(case, ok) == []
    missing = dict(ok, clarify=None)
    assert any("追问" in item for item in qa.check(case, missing))


def test_data_case_still_rejects_unexpected_clarify():
    case = {"expect": {"module": "FACTORY_ISSUE", "min_queries": 1}}
    body = {
        "module": "FACTORY_ISSUE",
        "error": None,
        "clarify": {"question": "哪个域？"},
        "query_count": 1,
        "answer": "",
        "tables": [],
    }
    assert any("澄清" in item for item in qa.check(case, body))


def test_columns_present_and_forbidden_scan_every_table():
    case = {
        "expect": {
            "tables": {
                "columns_present": ["问题编号"],
                "forbidden_columns": ["ID", "IsDelete"],
                "cell_contains": ["ZC2604018"],
            }
        }
    }
    body = {
        "error": None,
        "module": "FACTORY_ISSUE",
        "clarify": None,
        "query_count": 1,
        "answer": "共 1 张",
        "tables": [
            {"columns": ["域"], "rows": []},
            {"columns": ["问题编号", "机型"], "rows": [{"问题编号": "ZC2604018"}]},
        ],
    }
    assert qa.check(case, body) == []
    leaked = {
        **body,
        "tables": [{"columns": ["问题编号", "ID"], "rows": [["ZC2604018"]]}],
    }
    assert any("不许给用户" in item for item in qa.check(case, leaked))


def test_suggestions_check_shape_not_count():
    case = {"expect": {"suggestions": True, "suggestion_contains": ["看该部门跟进的单"]}}
    body = {
        "error": None,
        "clarify": None,
        "query_count": 0,
        "answer": "",
        "tables": [],
        "suggestions": [
            {
                "id": "follow",
                "name": "跟进",
                "label": "看该部门跟进的单",
                "query": "看生产工程部跟进的单",
            }
        ],
    }
    assert qa.check(case, body) == []
    wrapped = {
        **body,
        "suggestions": {
            "guide_text": "",
            "recommendations": body["suggestions"],
        },
    }
    assert qa.check(case, wrapped) == []
    broken = {**body, "suggestions": [{"label": "看该部门跟进的单"}]}
    assert any("缺" in item for item in qa.check(case, broken))
    empty = {**body, "suggestions": {"guide_text": "", "recommendations": []}}
    assert any("没有可点的建议按钮" in item for item in qa.check(case, empty))


def test_chart_type_needs_one_match():
    case = {"expect": {"charts": {"min_count": 1, "types": ["bar"]}}}
    body = {
        "error": None,
        "clarify": None,
        "query_count": 1,
        "answer": "",
        "tables": [],
        "charts": [{"chart_type": "bar", "series": []}],
    }
    assert qa.check(case, body) == []
    pie = {**body, "charts": [{"chart_type": "pie"}]}
    assert any("图类型" in item for item in qa.check(case, pie))


def test_issue_link_path_is_not_treated_as_shown_text():
    """问题编号链接的地址含页面路径，前端只显示单号。正文里写出表名仍然要失败。"""
    case = {"expect": {"answer_not_contains": ["BrazilProblem", "OverseasProblem"]}}
    body = {
        "error": None,
        "clarify": None,
        "query_count": 1,
        "tables": [],
        "suggestions": None,
        "answer": (
            "**巴西 [BR2609001](https://br.example/#/BrazilProblem/AddBrazilProblemPage?type=AB&ID=CD)**\n"
            "**海外 [HW2512001](https://info.example/#/QualityManage/OverseasProblemAllDetail?id=9)**"
        ),
    }
    assert qa.check(case, body) == []
    leaked = {**body, "answer": body["answer"] + "\n查的是 BrazilProblemList。"}
    assert any("BrazilProblem" in item for item in qa.check(case, leaked))
    labeled = {**body, "answer": "见 [BrazilProblem](https://info.example/detail)"}
    assert any("BrazilProblem" in item for item in qa.check(case, labeled))


def test_case_turns_defaults_to_one_query():
    turns = qa.case_turns({"query": "你好", "target": "FACTORY_ISSUE"})
    assert turns == [{"query": "你好", "target": "FACTORY_ISSUE"}]


def test_golden_files_stay_inside_g3_rules():
    payload = json.loads((ROOT / "docs/testcases/golden/cases.json").read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) == 115  # 2026-10-31 加临时统计的 XC-040（开发者同意）
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    permission_ids = {"XC-017", "XC-030", "XC-032", "XC-033", "XC-034"}
    assert permission_ids.isdisjoint(ids)
    manual = (ROOT / "docs/testcases/manual/其余.md").read_text(encoding="utf-8")
    for case_id in permission_ids:
        assert case_id in manual
    multi = [case for case in cases if case.get("turns")]
    assert len(multi) == 11
    for case in cases:
        assert case["target"] == "FACTORY_ISSUE"
        assert case.get("query")
        expect = case["expect"]
        assert "answer_min_length" not in expect
        tables = expect.get("tables") or {}
        assert "count" not in tables
        if case.get("turns"):
            assert [turn["query"] for turn in qa.case_turns(case)][-1] == case["query"]
            assert len(case["turns"]) == 2
        sql_path = ROOT / "docs/testcases/golden/sql" / f"{case['id']}.sql"
        text = sql_path.read_text(encoding="utf-8")
        upper = text.upper()
        assert "SELECT *" not in upper
        assert "STRING_SPLIT" not in upper
        assert "TRY_CONVERT" not in upper
        assert "PAXBASE" not in upper
        assert "1_user_input" not in text
