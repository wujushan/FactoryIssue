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


def test_skip_keeps_the_case_out_of_the_run():
    active, skipped = qa.split_skipped(
        [
            {"id": "CN-001"},
            {"id": "XC-041", "skip": "  平台侧暂时不跑  "},
            {"id": "CN-002", "skip": ""},
            {"id": "CN-003", "skip": "   "},
        ]
    )
    assert [case["id"] for case in active] == ["CN-001", "CN-002", "CN-003"]
    assert [(case["id"], reason) for case, reason in skipped] == [("XC-041", "平台侧暂时不跑")]


def test_case_turns_defaults_to_one_query():
    turns = qa.case_turns({"query": "你好", "target": "FACTORY_ISSUE"})
    assert turns == [{"query": "你好", "target": "FACTORY_ISSUE"}]


def test_golden_files_stay_inside_g3_rules():
    payload = json.loads((ROOT / "docs/testcases/golden/cases.json").read_text(encoding="utf-8"))
    cases = payload["cases"]
    # 2026-10-31 加临时统计的 XC-040；2026-11-02 加三轮的 XC-041（都经开发者同意）
    assert len(cases) == 116
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    permission_ids = {"XC-017", "XC-030", "XC-032", "XC-033", "XC-034"}
    assert permission_ids.isdisjoint(ids)
    manual = (ROOT / "docs/testcases/manual/其余.md").read_text(encoding="utf-8")
    for case_id in permission_ids:
        assert case_id in manual
    multi = [case for case in cases if case.get("turns")]
    # 2026-11-02：XC-015 改为两轮（开发者要求）
    assert len(multi) == 13
    #: 多轮用例都是两轮，只有 XC-041 是三轮（追问 → 点一个选项 → 问另外的，2026-11-02 开发者同意）
    three_turns = {"XC-041"}
    for case in cases:
        assert case["target"] == "FACTORY_ISSUE"
        assert case.get("query")
        expect = case["expect"]
        assert "answer_min_length" not in expect
        tables = expect.get("tables") or {}
        assert "count" not in tables
        if case.get("turns"):
            assert [turn["query"] for turn in qa.case_turns(case)][-1] == case["query"]
            assert len(case["turns"]) == (3 if case["id"] in three_turns else 2)
        sql_path = ROOT / "docs/testcases/golden/sql" / f"{case['id']}.sql"
        text = sql_path.read_text(encoding="utf-8")
        upper = text.upper()
        assert "SELECT *" not in upper
        assert "STRING_SPLIT" not in upper
        assert "TRY_CONVERT" not in upper
        assert "PAXBASE" not in upper
        assert "1_user_input" not in text


# ---------------------------------------------------------------- 润色样例（润色设计 §12.2）

_POLISH_OK = {"error": None, "clarify": None, "query_count": 0, "tables": [], "suggestions": None,
              "answer": '<p>测试机型A999开机花屏，共200台。</p><p><img src="https://info.example.invalid/a.png"></p>'}


def test_ext_param_is_sent_with_each_turn():
    ext = {"task": "domestic_polish", "field": "reason"}
    assert qa.case_turns({"query": "x", "target": "FACTORY_ISSUE", "ext_param": ext}) == [
        {"query": "x", "target": "FACTORY_ISSUE", "ext_param": ext}]
    multi = qa.case_turns({"query": "b", "ext_param": ext, "turns": ["a", {"query": "b", "ext_param": {"task": "t"}}]})
    assert [t["ext_param"] for t in multi] == [ext, {"task": "t"}]


def test_run_case_posts_ext_param():
    sent: list[dict] = []

    class Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {**_POLISH_OK, "conversation_id": "c1"}

    class Client:
        def post(self, path, json):
            sent.append(json)
            return Resp()

    import threading

    ext = {"task": "domestic_polish", "field": "reason"}
    result = qa.run_case(Client(), {"id": "PL-X", "query": "x", "target": "FACTORY_ISSUE", "ext_param": ext,
                                    "expect": {"answer_preserves": ["A999"]}}, False, threading.Event())
    assert result.passed and sent == [{"query": "x", "include_trace": False, "target": "FACTORY_ISSUE",
                                       "ext_param": ext}]


def test_q_pad_expands_and_rejects_bad_shapes():
    case = {"id": "PL-28", "query": "<p>{pad}</p>", "q_pad": ["测试", 3]}
    assert qa.expand_pad(case)["query"] == "<p>测试测试测试</p>"
    assert qa.expand_pad({"id": "a", "query": "x"}) == {"id": "a", "query": "x"}
    import pytest

    for bad in (["测试"], ["测试", "3"], ["测试", 0], [3, 3]):
        with pytest.raises(SystemExit):
            qa.expand_pad({"id": "b", "query": "{pad}", "q_pad": bad})
    with pytest.raises(SystemExit):
        qa.expand_pad({"id": "c", "query": "没有占位", "q_pad": ["测试", 2]})
    with pytest.raises(SystemExit):  # 写了 q_pad 却是 null：不把字面的 {pad} 发出去
        qa.expand_pad({"id": "d", "query": "{pad}", "q_pad": None})


def test_timeout_fails_only_that_case():
    """润色一轮最坏约 4 分钟：一条超时只记这一条失败，不中断整次回归。"""
    import threading

    import httpx

    class Client:
        timeout = httpx.Timeout(180.0)

        def post(self, path, json):
            raise httpx.ReadTimeout("x")

    result = qa.run_case(Client(), {"id": "PL-X", "query": "x"}, False, threading.Event())
    assert not result.passed and "180.0 秒没有返回" in result.problems[0] and result.body is None


def test_error_code_assertion():
    case = {"expect": {"no_error": False, "error_code": "POLISH_EMPTY"}}
    err = {**_POLISH_OK, "answer": "", "error": {"code": "POLISH_EMPTY", "message": "请先填写内容再润色", "fatal": True}}
    assert qa.check(case, err) == []
    other = {**err, "error": {**err["error"], "code": "POLISH_FAILED"}}
    assert any("POLISH_FAILED" in p and "POLISH_EMPTY" in p for p in qa.check(case, other))
    assert any("None" in p for p in qa.check(case, _POLISH_OK))  # 预期报错却润色成功
    # 只写 error_code 不写 no_error：不按「不许报错」判
    assert qa.check({"expect": {"error_code": "POLISH_EMPTY"}}, err) == []


def test_answer_preserves_and_max_chars():
    case = {"expect": {"answer_preserves": ["A999", "200", "https://info.example.invalid/a.png"],
                       "answer_max_chars": 200}}
    assert qa.check(case, _POLISH_OK) == []
    lost = {**_POLISH_OK, "answer": "<p>测试机型开机花屏。</p>"}
    problems = qa.check(case, lost)
    assert any("A999" in p for p in problems) and any("200" in p for p in problems)
    long = {**_POLISH_OK, "answer": _POLISH_OK["answer"] * 3}
    assert any("至多 200" in p for p in qa.check(case, long))


def test_answer_not_contains_applies_to_polish_results():
    case = {"expect": {"answer_not_contains": ["3个", "<p>原因分析"]}}
    assert qa.check(case, {**_POLISH_OK, "answer": "<p>有三个原因。</p>"}) == []
    assert any("<p>原因分析" in p for p in qa.check(case, {**_POLISH_OK, "answer": "<p>原因分析：</p><p>x</p>"}))


def test_polish_cases_stay_synthetic_and_on_the_polish_task():
    """润色样例：编号都是 99 年号、任务码都是 domestic_polish、错误代码都是四个之一；与 golden 分开放。"""
    import re

    from factory_issue_module.polish import TASK_CODE
    from factory_issue_module.turn import errors

    path = ROOT / "docs/testcases/polish/cases.json"
    raw = json.loads(path.read_text(encoding="utf-8"))["cases"]
    cases = qa.load_cases(path)
    assert len(cases) == len(raw) >= 30
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and all(i.startswith("PL-") for i in ids)
    numbers = re.compile(r"(?:ZC|BR|HW)\s*-?\s*\d[\d\s-]*", re.IGNORECASE)
    seen = 0
    for case in cases:
        assert case["target"] == "FACTORY_ISSUE", case["id"]
        assert case["ext_param"]["task"] == TASK_CODE, case["id"]
        assert "{pad}" not in case["query"], case["id"]
        blob = json.dumps({k: case.get(k) for k in ("query", "ext_param", "expect")}, ensure_ascii=False)
        for m in numbers.finditer(blob):
            digits = re.sub(r"\D", "", m.group(0))
            assert digits[:2] == "99", (case["id"], m.group(0))
            seen += 1
        code = case["expect"].get("error_code")
        if code:
            assert code in errors.POLISH_MESSAGES and case["expect"].get("no_error") is False, case["id"]
    assert seen >= 2  # PL-17 的 issue_no、PL-09 的 ZC99 等：守卫真的看到了编号
    golden = json.loads((ROOT / "docs/testcases/golden/cases.json").read_text(encoding="utf-8"))["cases"]
    assert not {c["id"] for c in golden} & set(ids)
    assert not any((c.get("ext_param") or {}).get("task") == TASK_CODE for c in golden)
