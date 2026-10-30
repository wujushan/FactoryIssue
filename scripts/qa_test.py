#!/usr/bin/env python
"""业务问答自动化测试 runner —— 把用例集全量跑一遍，回答「这个模块答得对不对」。

用法：
    export FORGE_TEST_BASE_URL=http://<平台主机>:8090
    export FORGE_TEST_API_KEY=fdt_xxxxxxxx.yyyyyyyy
    uv run python scripts/qa_test.py docs/testcases/golden/cases.example.json

    # 只跑某几条 / 失败时看 SQL 明细
    uv run python scripts/qa_test.py cases.json --only mat-001 --trace

平台侧协议、api-key 怎么申请、断言该锚在哪：见 docs/dev/10-automated-testing.md。
本脚本覆盖 golden 常用断言：路由、澄清、取数条数上下限、列名（含禁列）、
单元格包含、图表类型、正文包含/排除、建议按钮形状。合计＝分项之和这类关系
若还要对表内数字验算，请在 `check()` 里加分支。

⚠️ 它打的是真实模型与真实库：慢、有并发上限，别拿它当压测工具。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# 真实模型 + 真实库，单轮几十秒是常态。默认 5 秒的超时会把好用例判成失败。
DEFAULT_TIMEOUT = 180.0


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise SystemExit(f"用例集格式不对：{path} 应是数组或 {{\"cases\": [...]}}")
    return cases


# Markdown 链接的地址。巴西、海外问题编号的页面路径里含 BrazilProblem、OverseasProblem，
# 前端只显示方括号里的文字，扫描「不许出现表名」时去掉地址。
_MD_LINK_TARGET = re.compile(r"\]\([^)]*\)")


def _visible_text(body: dict[str, Any]) -> str:
    """用户看得到的文字：正文、澄清、建议按钮。表格单元格另走 `_table_text`。"""
    parts = [body.get("answer") or ""]
    for key in ("clarify", "suggestions"):
        if body.get(key) is not None:
            parts.append(json.dumps(body[key], ensure_ascii=False))
    return "\n".join(parts)


def _without_link_targets(text: str) -> str:
    """去掉 Markdown 链接地址，只留可点击文字。"""
    return _MD_LINK_TARGET.sub("]", text)


def _table_text(tables: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for table in tables:
        chunks.extend(str(column) for column in table.get("columns") or [])
        for row in table.get("rows") or []:
            if isinstance(row, dict):
                chunks.extend(str(value) for value in row.values())
            elif isinstance(row, (list, tuple)):
                chunks.extend(str(value) for value in row)
            else:
                chunks.append(str(row))
    return "\n".join(chunks)


def _table_requires_output(table_spec: dict[str, Any]) -> bool:
    return any(
        table_spec.get(key) is not None
        for key in ("count", "columns", "columns_present", "row_count", "min_rows", "cell_contains")
    )


def check(case: dict[str, Any], body: dict[str, Any]) -> list[str]:
    """跑一条用例的断言，返回失败原因列表（空 = 通过）。

    每条失败信息都带上**实际值**：CI 日志里只说「断言失败」等于没说。
    `clarify: true` 表示本轮就该追问。`columns_present` / `cell_contains` /
    `forbidden_columns` 看全部表，不锚定第几张、列顺序。`suggestions: true`
    只检查按钮形状，不检查个数。
    """
    expect = case.get("expect") or {}
    failures: list[str] = []

    if expect.get("no_error", True) and body.get("error"):
        failures.append(f"模块报错：{body['error']}")
    if (want := expect.get("module")) and body.get("module") != want:
        failures.append(f"路由到 {body.get('module')!r}，预期 {want!r}")
    if expect.get("clarify") is True:
        if not body.get("clarify"):
            failures.append("预期本轮追问，但没有给出澄清")
    elif expect.get("no_clarify", True) and body.get("clarify"):
        # 澄清 = 本轮压根没答（答前阻断）。默认视为失败：数据用例的前提是它真的答了。
        question = body["clarify"].get("question", "") if isinstance(body["clarify"], dict) else ""
        failures.append(f"被判为问题不明确（澄清轮），未产出答案：{question}")
    query_count = body.get("query_count", 0)
    if (least := expect.get("min_queries")) is not None and query_count < least:
        failures.append(f"只执行了 {query_count} 条 SQL，预期至少 {least} 条")
    if (most := expect.get("max_queries")) is not None and query_count > most:
        failures.append(f"执行了 {query_count} 条 SQL，预期至多 {most} 条")

    tables = body.get("tables") or []
    if table_spec := expect.get("tables"):
        if (count := table_spec.get("count")) is not None and len(tables) != count:
            failures.append(f"产出 {len(tables)} 张表，预期 {count} 张")
        if tables:
            first = tables[0]
            for column in table_spec.get("columns") or []:
                if column not in first.get("columns", []):
                    failures.append(f"表缺列 {column!r}（实际列：{first.get('columns')}）")
            names = [column for table in tables for column in (table.get("columns") or [])]
            for column in table_spec.get("columns_present") or []:
                if column not in names:
                    failures.append(f"各表列名都没有 {column!r}（实际列：{names}）")
            forbidden = set(table_spec.get("forbidden_columns") or [])
            leaked = [column for column in names if column in forbidden]
            if leaked:
                failures.append(f"表头出现不许给用户的列 {leaked}")
            if (rows := table_spec.get("row_count")) is not None:
                actual = len(first.get("rows") or [])
                if actual != rows:
                    failures.append(f"表有 {actual} 行，预期 {rows} 行")
            if (least_rows := table_spec.get("min_rows")) is not None:
                actual = len(first.get("rows") or [])
                if actual < least_rows:
                    failures.append(f"表只有 {actual} 行，预期至少 {least_rows} 行")
            rendered = _table_text(tables)
            for needle in table_spec.get("cell_contains") or []:
                if needle not in rendered:
                    failures.append(f"表格里没有 {needle!r}")
        elif _table_requires_output(table_spec):
            failures.append("本轮没有产出任何表格")

    charts = body.get("charts") or []
    if chart_spec := expect.get("charts"):
        if (least_charts := chart_spec.get("min_count")) is not None and len(charts) < least_charts:
            failures.append(f"产出 {len(charts)} 张图，预期至少 {least_charts} 张")
        allowed = chart_spec.get("types")
        if allowed and charts and not any(chart.get("chart_type") in allowed for chart in charts):
            got = [chart.get("chart_type") for chart in charts]
            failures.append(f"图类型 {got}，预期至少一张属于 {allowed}")

    answer = body.get("answer") or ""
    visible = _visible_text(body)
    for needle in expect.get("answer_contains") or []:
        if needle not in answer:
            failures.append(f"答案未包含 {needle!r}")
    for needle in expect.get("visible_contains") or []:
        if needle not in visible:
            failures.append(f"用户可见内容未包含 {needle!r}")
    anywhere = visible + "\n" + _table_text(tables)
    if anywhere_needles := expect.get("anywhere_contains"):
        for needle in anywhere_needles:
            if needle not in anywhere:
                failures.append(f"正文和表格里都没有 {needle!r}")
    if any_needles := expect.get("anywhere_contains_any"):
        if not any(needle in anywhere for needle in any_needles):
            failures.append(f"正文和表格里都没有其中任一项 {any_needles!r}")
    if expect.get("no_tables") and tables:
        failures.append(f"本轮不该出表，实际 {len(tables)} 张")
    if (cap := expect.get("max_total_rows")) is not None:
        total_rows = sum(len(table.get("rows") or []) for table in tables)
        if total_rows > cap:
            failures.append(f"各表合计 {total_rows} 行，预期不超过 {cap} 行")
    # 呈现规范（docs/dev/09）：表名/字段名/数据源别名不许出现在给用户的文字里。
    # 链接地址不算给用户看的文字（问题编号点进去的页面路径）。
    shown = _without_link_targets(visible)
    for needle in expect.get("answer_not_contains") or []:
        if needle in shown:
            failures.append(f"答案不该出现 {needle!r}（呈现规范，见 docs/dev/09）")
    if (least_len := expect.get("answer_min_length")) is not None and len(answer) < least_len:
        failures.append(f"答案仅 {len(answer)} 字，预期至少 {least_len} 字（数据之外要给分析）")

    if expect.get("suggestions") is True:
        items = body.get("suggestions")
        if not isinstance(items, list) or not items:
            failures.append(f"没有可点的建议按钮（实际：{items!r}）")
        else:
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    failures.append(f"建议按钮第 {index + 1} 项不是对象")
                    continue
                missing = [key for key in ("id", "name", "label", "query") if not item.get(key)]
                if missing:
                    failures.append(f"建议按钮第 {index + 1} 项缺 {missing}")
    if suggestion_needles := expect.get("suggestion_contains"):
        suggestion_text = json.dumps(body.get("suggestions"), ensure_ascii=False)
        for needle in suggestion_needles:
            if needle not in suggestion_text:
                failures.append(f"建议按钮里没有 {needle!r}")

    return failures


def case_turns(case: dict[str, Any]) -> list[dict[str, Any]]:
    """一条用例要依次发送的轮次。没有 `turns` 时就是本条 `query` 一轮。"""
    raw = case.get("turns")
    if not raw:
        turn: dict[str, Any] = {"query": case["query"]}
        for field in ("target", "user_id"):
            if case.get(field):
                turn[field] = case[field]
        return [turn]
    turns: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            item = {"query": item}
        turn = {"query": item["query"]}
        for field in ("target", "user_id"):
            value = item.get(field, case.get(field))
            if value:
                turn[field] = value
        turns.append(turn)
    return turns


def run(cases: list[dict[str, Any]], *, base: str, key: str, trace: bool) -> int:
    client = httpx.Client(
        base_url=base.rstrip("/"),
        headers={"Authorization": f"Bearer {key}"},
        timeout=DEFAULT_TIMEOUT,
    )
    # 先确认凭据与可测模块：凭据问题当场暴露，而不是等第一条用例莫名 401
    probe = client.get("/test/modules")
    if probe.status_code != 200:
        raise SystemExit(f"[凭据/通道不可用] HTTP {probe.status_code} {probe.text}")
    info = probe.json()
    codes = [m["code"] for m in info["modules"]]
    left_days = (info["key"]["expires_ts"] - time.time()) / 86400
    print(f"key「{info['key']['name']}」可测模块 {codes}，剩余有效期 {left_days:.0f} 天")
    if left_days < 7:
        print("⚠️  该 api-key 一周内到期，尽快找平台管理员续期", file=sys.stderr)

    passed, failed = 0, []
    for case in cases:
        case_id = case.get("id") or case.get("query", "")[:20]
        # 多轮用例按顺序发，后一轮带上一轮返回的 conversation_id。断言只看最后一轮。
        conversation_id = None
        body = None
        problems: list[str] = []
        started = time.monotonic()
        for index, turn in enumerate(case_turns(case)):
            payload: dict[str, Any] = {"query": turn["query"], "include_trace": trace}
            for field in ("target", "user_id"):
                if turn.get(field):
                    payload[field] = turn[field]
            if conversation_id:
                payload["conversation_id"] = conversation_id
            resp = client.post("/test/chat", json=payload)
            if resp.status_code != 200:
                problems = [f"第 {index + 1} 轮 HTTP {resp.status_code}: {resp.text[:300]}"]
                body = None
                break
            body = resp.json()
            conversation_id = body.get("conversation_id")
            if index < len(case_turns(case)) - 1 and body.get("error"):
                problems = [f"前置轮报错：{body['error']}"]
                break
        elapsed = time.monotonic() - started
        if problems:
            failed.append((case_id, problems, body))
            print(f"✗ {case_id}  ({elapsed:.1f}s)")
            for problem in problems:
                print(f"    - {problem}")
            continue
        assert body is not None
        problems = check(case, body)
        if problems:
            failed.append((case_id, problems, body))
            print(f"✗ {case_id}  ({elapsed:.1f}s)")
            for problem in problems:
                print(f"    - {problem}")
        else:
            passed += 1
            print(f"✓ {case_id}  ({elapsed:.1f}s, {body.get('query_count', 0)} SQL)")

    print(f"\n{'=' * 60}\n通过 {passed} / {len(cases)}，失败 {len(failed)}")
    if trace and failed:
        print("\n失败用例的 SQL/LLM 明细：")
        for case_id, _problems, body in failed:
            if body and body.get("trace"):
                print(f"\n--- {case_id} ---")
                print(json.dumps(body["trace"], ensure_ascii=False, indent=2)[:4000])
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="业务问答自动化测试 runner")
    parser.add_argument("cases", type=Path, help="用例集 JSON")
    parser.add_argument("--base-url", default=os.getenv("FORGE_TEST_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("FORGE_TEST_API_KEY", ""))
    parser.add_argument("--only", nargs="*", help="只跑这些用例 id")
    parser.add_argument("--trace", action="store_true", help="回传并打印失败用例的 SQL/LLM 明细")
    args = parser.parse_args()

    if not args.base_url or not args.api_key:
        raise SystemExit(
            "缺少平台地址或 api-key：设置 FORGE_TEST_BASE_URL / FORGE_TEST_API_KEY "
            "（key 由平台管理员在 Admin Console「测试」页签发，见 docs/dev/10-automated-testing.md）"
        )

    cases = load_cases(args.cases)
    if args.only:
        wanted = set(args.only)
        cases = [c for c in cases if c.get("id") in wanted]
        if not cases:
            raise SystemExit(f"--only 没匹配到任何用例：{sorted(wanted)}")
    return run(cases, base=args.base_url, key=args.api_key, trace=args.trace)


if __name__ == "__main__":
    sys.exit(main())
