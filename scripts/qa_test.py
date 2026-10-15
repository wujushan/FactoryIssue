#!/usr/bin/env python
"""业务问答自动化测试 runner —— 把用例集全量跑一遍，回答「这个模块答得对不对」。

用法：
    export FORGE_TEST_BASE_URL=http://<平台主机>:8090
    export FORGE_TEST_API_KEY=fdt_xxxxxxxx.yyyyyyyy
    uv run python scripts/qa_test.py docs/testcases/golden/cases.example.json

    # 只跑某几条 / 失败时看 SQL 明细
    uv run python scripts/qa_test.py cases.json --only mat-001 --trace

平台侧协议、api-key 怎么申请、断言该锚在哪：见 docs/dev/10-automated-testing.md。
本脚本是**起点不是终点**——用例的 expect 只覆盖最常用的几类断言，业务上更精细的口径
（合计=分项之和、换个问法结果一致…）请直接在这里加分支，或另写自己的 runner。

⚠️ 它打的是真实模型与真实库：慢、有并发上限，别拿它当压测工具。
"""

from __future__ import annotations

import argparse
import json
import os
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


def check(case: dict[str, Any], body: dict[str, Any]) -> list[str]:
    """跑一条用例的断言，返回失败原因列表（空 = 通过）。

    每条失败信息都带上**实际值**：CI 日志里只说「断言失败」等于没说。
    """
    expect = case.get("expect") or {}
    failures: list[str] = []

    if expect.get("no_error", True) and body.get("error"):
        failures.append(f"模块报错：{body['error']}")
    if (want := expect.get("module")) and body.get("module") != want:
        failures.append(f"路由到 {body.get('module')!r}，预期 {want!r}")
    if expect.get("no_clarify", True) and body.get("clarify"):
        # 澄清 = 本轮压根没答（答前阻断）。默认视为失败：数据用例的前提是它真的答了。
        failures.append(f"被判为问题不明确（澄清轮），未产出答案：{body['clarify'].get('question', '')}")
    if (least := expect.get("min_queries")) is not None and body.get("query_count", 0) < least:
        failures.append(f"只执行了 {body.get('query_count', 0)} 条 SQL，预期至少 {least} 条")

    tables = body.get("tables") or []
    if table_spec := expect.get("tables"):
        if (count := table_spec.get("count")) is not None and len(tables) != count:
            failures.append(f"产出 {len(tables)} 张表，预期 {count} 张")
        if tables:
            first = tables[0]
            for column in table_spec.get("columns") or []:
                if column not in first.get("columns", []):
                    failures.append(f"表缺列 {column!r}（实际列：{first.get('columns')}）")
            if (rows := table_spec.get("row_count")) is not None:
                actual = len(first.get("rows") or [])
                if actual != rows:
                    failures.append(f"表有 {actual} 行，预期 {rows} 行")
            if (least_rows := table_spec.get("min_rows")) is not None:
                actual = len(first.get("rows") or [])
                if actual < least_rows:
                    failures.append(f"表只有 {actual} 行，预期至少 {least_rows} 行")
        elif table_spec:
            failures.append("本轮没有产出任何表格")

    answer = body.get("answer") or ""
    for needle in expect.get("answer_contains") or []:
        if needle not in answer:
            failures.append(f"答案未包含 {needle!r}")
    # 呈现规范（docs/dev/09）：表名/字段名/数据源别名不许出现在给用户的正文里
    for needle in expect.get("answer_not_contains") or []:
        if needle in answer:
            failures.append(f"答案不该出现 {needle!r}（呈现规范，见 docs/dev/09）")
    if (least_len := expect.get("answer_min_length")) is not None and len(answer) < least_len:
        failures.append(f"答案仅 {len(answer)} 字，预期至少 {least_len} 字（数据之外要给分析）")

    return failures


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
        payload = {
            "query": case["query"],
            "include_trace": trace,
        }
        # 数据用例一律带 target 直达模块：路由是独立变量，混进来会让失败原因有两种可能
        for field in ("target", "conversation_id", "user_id"):
            if case.get(field):
                payload[field] = case[field]

        started = time.monotonic()
        resp = client.post("/test/chat", json=payload)
        elapsed = time.monotonic() - started
        if resp.status_code != 200:
            failed.append((case_id, [f"HTTP {resp.status_code}: {resp.text[:300]}"], None))
            print(f"✗ {case_id}  HTTP {resp.status_code}")
            continue

        body = resp.json()
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
