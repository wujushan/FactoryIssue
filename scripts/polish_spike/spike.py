"""AI 润色内网实测（决策 2026-11-09「AI 润色技术设计」§12.3）。用法见同目录 README.md。

两部分：
- cases：`docs/testcases/polish/cases.json` 的合成样例，各跑 `--repeats` 次，量检查通过率；
- ladder：合成段落拼成 500–6000 字的原问（原因分析栏），各跑 `--ladder-repeats` 次，量耗时，定原文长度上限与超时。
只连内网本地模型服务，不连库，不用真实业务数据。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "planner_spike"))

from forge_platform.policy import PolicyLLM  # noqa: E402  与线上 ctx.llm 同一段合并 system 的代码

import polish_core as core  # noqa: E402
from common import ROOT, RUNTIME, check_out_dir, load_env_file  # noqa: E402

CASES_FILE = ROOT / "docs" / "testcases" / "polish" / "cases.json"
DEFAULT_OUT_ROOT = RUNTIME / "polish_spike"
LADDER = (500, 1000, 2000, 3000, 4000, 6000)
#: 设计 §12.3 的门槛
FIRST_PASS = 0.80
FINAL_PASS = 0.95
TOTAL_P90 = 60.0
LADDER_PASS = 0.90
SMOKE_CASES = ("PL-01", "PL-04", "PL-16")

#: 长度阶梯的版本：拼法改了就递增（续跑、目录核对都认它）。l1 用 12 句循环，1000 字以上整段重复，模型把重复的
#: 几段并掉了，输出只有原文的三分之一（2026-11-10 冒烟 LD-1000），l2 起每句都不同
LADDER_VERSION = "l2"
#: 长度阶梯的合成句子由这几组词按句号轮换拼出（原因分析的口吻，口语多一些才有东西可润色）。每句带批次号与数量，
#: 句句不同，事实检查也有东西可查
_LINES = ("一线", "二线", "三线", "四线", "五线", "六线", "七线")
_PARTS = ("外壳", "卡扣", "螺丝", "按键", "屏幕支架", "电池盖", "扬声器", "排线", "天线", "USB座", "摄像头模组")
_DEFECTS = ("毛刺", "缩水", "划伤", "松动", "偏位", "虚焊", "异响", "变形", "断裂")
_CAUSES = ("治具定位销磨得差不多了", "注塑温度设得偏低", "扭力枪设定偏小没人改", "作业员没按SOP来",
           "来料尺寸超差了一点", "钢网开孔开小了", "换班的时候首件确认漏做了", "点检表上压根没这一项")
_ACTIONS = ("线上的已经返工了", "库存的正在全检", "已经让供应商整改", "治具已经换了新的", "工艺参数已经调过",
            "来料检验已经加严")


@dataclass
class Cfg:
    base_url: str
    api_key: str
    model: str
    concurrency: int
    timeout: float


def load_cases() -> tuple[str, list[dict[str, Any]]]:
    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = data["cases"]
    for case in cases:
        if "q_pad" in case:
            text, times = case["q_pad"]
            case["query"] = case["query"].replace("{pad}", text * times)
    return str(data.get("version") or ""), cases


def _ladder_sentence(i: int) -> str:
    return (f"{_LINES[i % len(_LINES)]}的{_PARTS[i % len(_PARTS)]}出现{_DEFECTS[i % len(_DEFECTS)]}，"
            f"第{i + 1}批抽检了{20 + i * 3}台，有{i % 5 + 1}台不良，原因是{_CAUSES[i % len(_CAUSES)]}，"
            f"{_ACTIONS[i % len(_ACTIONS)]}。")


def ladder_query(target: int) -> str:
    """拼到去掉标签后不少于 `target` 字的富文本：每段两句，句句不同（批次号逐句递增）。"""
    paras: list[str] = []
    n = 0
    i = 0
    while n < target:
        para = _ladder_sentence(i) + _ladder_sentence(i + 1)
        paras.append(f"<p>{para}</p>")
        n += len(para)
        i += 2
    return "".join(paras)


def ladder_cases(repeats: int) -> list[dict[str, Any]]:
    return [{"id": f"LD-{n}", "note": f"长度阶梯 {n} 字", "query": ladder_query(n),
             "ext_param": {"task": core.TASK_CODE, "field": "reason"}, "expect": {"no_error": True},
             "ladder": n} for n in LADDER]


def with_policy(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """平台 PolicyLLM 把红线段并进首条 system；这里直接调它的同一段代码。"""
    return PolicyLLM(None)._prepare(messages)


def first_messages(prep: core.Prepared, rules: core.Rules) -> list[dict[str, str]]:
    return with_policy([{"role": "system", "content": core.system(prep.split.style)},
                        {"role": "user", "content": core.user(prep, rules)}])


# ---------------------------------------------------------------------------- 调模型


class Caller:
    def __init__(self, cfg: Cfg, client: httpx.AsyncClient) -> None:
        self.cfg = cfg
        self.client = client
        self.sem = asyncio.Semaphore(cfg.concurrency)
        self.url = cfg.base_url.rstrip("/") + "/chat/completions"

    async def chat(self, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
        """与线上 `ctx.llm.chat(messages, temperature=0, response_format=json_object, max_tokens=…)` 同一个请求。"""
        payload = {"model": self.cfg.model, "messages": messages, "temperature": 0.0, "stream": False,
                   "response_format": {"type": "json_object"}, "max_tokens": max_tokens}
        rec: dict[str, Any] = {"error": None, "content": "", "usage": {}, "finish_reason": None, "latency": None,
                               "retries": 0}
        headers = {"Authorization": f"Bearer {self.cfg.api_key or 'EMPTY'}"}
        async with self.sem:
            for attempt in range(3):
                started = time.monotonic()
                try:
                    r = await self.client.post(self.url, json=payload, headers=headers)
                except httpx.TimeoutException:
                    rec.update(error="超时", latency=time.monotonic() - started)
                    return rec
                except httpx.TransportError as exc:
                    rec.update(error=f"连接出错：{type(exc).__name__}", retries=attempt + 1)
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                rec["latency"] = time.monotonic() - started
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    rec["retries"] = attempt + 1
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                if r.status_code >= 400:
                    rec["error"] = f"HTTP {r.status_code}：{r.text[:300]}"
                    return rec
                data = r.json()
                choice = (data.get("choices") or [{}])[0]
                rec.update(content=(choice.get("message") or {}).get("content") or "", usage=data.get("usage") or {},
                           finish_reason=choice.get("finish_reason"), error=None)
                return rec
        return rec


async def polish_once(caller: Caller, case: dict[str, Any], rules: core.Rules) -> dict[str, Any]:
    """一条样例跑一次：判参数与原文 → 调模型 → 检查 → 不过修一次（同线上 §4）。"""
    prep, code, reason = core.prepare(case["query"], case.get("ext_param"), rules, ignore_cap="ladder" in case)
    out: dict[str, Any] = {"attempts": [], "outcome": code or None, "reason": reason, "output": None, "text": None}
    if prep is None:
        return out
    out["input_chars"] = prep.input_chars
    out["limit"] = prep.request.max_length
    messages = first_messages(prep, rules)
    mt = core.max_tokens(prep.input_chars)
    for attempt in (1, 2):
        rec = await caller.chat(messages, mt)
        step: dict[str, Any] = {k: rec[k] for k in ("latency", "error", "finish_reason", "usage", "retries")}
        if rec["error"]:
            step["failed"] = []
            out["attempts"].append(step)
            out["outcome"] = core.FAILED
            out["reason"] = "call_failed"
            return out
        v = core.check(rec["content"], prep)
        step.update(failed=v.failed, detail=v.detail, content_head=rec["content"][:300])
        out["attempts"].append(step)
        if v.ok:
            out.update(outcome="ok", output=v.output, text=v.text)
            return out
        if attempt == 2:
            out.update(outcome=core.FAILED, reason="check_failed", output=v.output, text=v.text)
            return out
        messages = with_policy([*messages, {"role": "assistant", "content": rec["content"]},
                                {"role": "user", "content": core.repair(v, prep)}])
    return out


def expect_problems(case: dict[str, Any], res: dict[str, Any]) -> list[str]:
    """与样例 `expect` 对照（模型之外的那几条：预期的错误代码、必须保留的串、不该出现的串、最多几个字符）。"""
    expect = case.get("expect") or {}
    probs: list[str] = []
    want = expect.get("error_code")
    if want:
        if res["outcome"] != want:
            probs.append(f"预期 {want}，实际 {res['outcome']}")
        return probs
    output = res.get("output") or ""
    if res["outcome"] != "ok":
        return probs
    for s in expect.get("answer_preserves") or []:
        if s not in output:
            probs.append(f"缺「{s}」")
    for s in expect.get("answer_not_contains") or []:
        if s in output:
            probs.append(f"不该有「{s}」")
    if (most := expect.get("answer_max_chars")) is not None and len(output) > most:
        probs.append(f"{len(output)} 字符，超过 {most}")
    return probs


async def run_jobs(cfg: Cfg, jobs: list[tuple[str, dict[str, Any], int]], raw_path: Path, rules: core.Rules,
                   version: str) -> None:
    done = set()
    if raw_path.exists():
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["part"], r["id"], r["rep"]))
    todo = [j for j in jobs if (j[0], j[1]["id"], j[2]) not in done]
    print(f"共 {len(jobs)} 项，已完成 {len(jobs) - len(todo)}，本次跑 {len(todo)}", flush=True)
    lock = asyncio.Lock()
    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        caller = Caller(cfg, client)

        async def one(part: str, case: dict[str, Any], rep: int) -> None:
            res = await polish_once(caller, case, rules)
            rec = {"part": part, "id": case["id"], "rep": rep, "field": (case.get("ext_param") or {}).get("field"),
                   "ladder": case.get("ladder"), "cases_version": version, "ladder_version": LADDER_VERSION, **res,
                   "expect_problems": expect_problems(case, res)}
            async with lock:
                with raw_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"  {part} {case['id']} #{rep + 1}: {res['outcome']}", flush=True)

        await asyncio.gather(*(one(p, c, r) for p, c, r in todo))


def build_jobs(args: argparse.Namespace, cases: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], int]]:
    parts = args.parts.split(",")
    only = set(args.only.split(",")) if args.only else None
    jobs: list[tuple[str, dict[str, Any], int]] = []
    if "cases" in parts:
        for c in cases:
            if only is None or c["id"] in only:
                reps = 1 if (c.get("expect") or {}).get("error_code") else args.repeats
                jobs += [("cases", c, r) for r in range(reps)]
    if "ladder" in parts:
        for c in ladder_cases(args.ladder_repeats):
            if only is None or c["id"] in only:
                jobs += [("ladder", c, r) for r in range(args.ladder_repeats)]
    return jobs


# ---------------------------------------------------------------------------- 汇总


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def _fmt(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def _rate(n: int, d: int) -> str:
    return "—" if d == 0 else f"{n / d:.1%}（{n}/{d}）"


def _total(r: dict[str, Any]) -> float:
    return sum(a.get("latency") or 0 for a in r["attempts"])


def write_report(out_dir: Path) -> None:
    raw = [json.loads(x) for x in (out_dir / "raw.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    info = json.loads((out_dir / "run_info.json").read_text(encoding="utf-8")) if (out_dir / "run_info.json").exists() else {}
    cases_by_id = {c["id"]: c for c in load_cases()[1]}
    model_runs = [r for r in raw if r["part"] == "cases" and r["attempts"]]
    pre_runs = [r for r in raw if r["part"] == "cases" and not r["attempts"]]
    first_ok = sum(1 for r in model_runs if r["outcome"] == "ok" and len(r["attempts"]) == 1)
    final_ok = sum(1 for r in model_runs if r["outcome"] == "ok")
    expect_ok = sum(1 for r in model_runs if r["outcome"] == "ok" and not r["expect_problems"])
    pre_ok = sum(1 for r in pre_runs if not r["expect_problems"])
    truncated = sum(1 for r in raw for a in r["attempts"] if a.get("finish_reason") == "length")
    call_errors = sum(1 for r in raw for a in r["attempts"] if a.get("error"))

    ladder: dict[int, list[dict[str, Any]]] = {}
    for r in raw:
        if r["part"] == "ladder":
            ladder.setdefault(int(r["ladder"]), []).append(r)
    cap, cap_timeout = None, None
    ladder_rows = []
    for n in sorted(ladder):
        runs = ladder[n]
        singles = [a["latency"] for r in runs for a in r["attempts"] if a.get("latency") is not None]
        totals = [_total(r) for r in runs]
        passed = sum(1 for r in runs if r["outcome"] == "ok")
        ratios = [len(r["text"] or "") / r["input_chars"] for r in runs if r.get("text") and r.get("input_chars")]
        p90 = _pct(totals, 0.9)
        ok = p90 is not None and p90 <= TOTAL_P90 and runs and passed / len(runs) >= LADDER_PASS
        if ok:
            cap, cap_timeout = n, (max(singles) * 1.5 if singles else None)
        ladder_rows.append(
            f"| {n} | {len(runs)} | {_rate(passed, len(runs))} | {_fmt(_pct(singles, 0.5))} | {_fmt(_pct(singles, 0.9))} | "
            f"{_fmt(max(singles) if singles else None)} | {_fmt(p90)} | "
            f"{sum(1 for r in runs for a in r['attempts'] if a.get('finish_reason') == 'length')} | "
            f"{_fmt(statistics.mean(ratios) if ratios else None, 2)} | {'✓' if ok else '✗'} |")

    first_fail: dict[str, int] = {}
    final_fail: dict[str, int] = {}
    for r in model_runs:
        for c in r["attempts"][0].get("failed") or []:
            first_fail[c] = first_fail.get(c, 0) + 1
        if r["outcome"] != "ok":
            for c in r["attempts"][-1].get("failed") or []:
                final_fail[c] = final_fail.get(c, 0) + 1
    checks = [core.CHECK_FORMAT, core.CHECK_MARKS, core.CHECK_ADDED, core.CHECK_REMOVED, core.CHECK_LENGTH,
              core.CHECK_PREFACE, core.CHECK_LANG]

    def mark(ok: bool) -> str:
        return "✓" if ok else "✗"

    n_model = len(model_runs)
    lines = [
        "# AI 润色实测汇总", "",
        f"- 模型：{info.get('model', '?')}；提示 {info.get('prompt', '?')}；样例 {info.get('cases_version', '?')}；"
        f"并发 {info.get('concurrency', '?')}；超时 {info.get('timeout', '?')} 秒",
        f"- 出汇总时间：{dt.datetime.now():%Y-%m-%d %H:%M}", "",
        "## 结论", "",
        "| 指标 | 结果 | 门槛 | 达标 |", "|---|---|---|---|",
        f"| 一次通过检查 | {_rate(first_ok, n_model)} | ≥ {FIRST_PASS:.0%} | {mark(n_model > 0 and first_ok / n_model >= FIRST_PASS)} |",
        f"| 修一次后通过检查 | {_rate(final_ok, n_model)} | ≥ {FINAL_PASS:.0%} | {mark(n_model > 0 and final_ok / n_model >= FINAL_PASS)} |",
        f"| 通过检查且样例要求都满足 | {_rate(expect_ok, final_ok)} | 全部 | {mark(expect_ok == final_ok)} |",
        f"| 不调模型的样例判对 | {_rate(pre_ok, len(pre_runs))} | 全部 | {mark(pre_ok == len(pre_runs))} |",
        f"| 因 max_tokens 截断 | {truncated} 次 | 0 | {mark(truncated == 0)} |",
        f"| 调用出错 | {call_errors} 次 | — | — |",
        f"| 建议的原文长度上限 | {cap if cap else '—'} 字 | 修一次的总耗时 P90 ≤ {TOTAL_P90:.0f} 秒、通过率 ≥ {LADDER_PASS:.0%} 的最长一档 | — |",
        f"| 建议的单次超时 | {_fmt(cap_timeout)} 秒 | 该档单次最长 × 1.5 | — |", "",
        "「通过检查」只说明程序认得出的几类事实（数字、编码、英文词）、占位、长度没问题；人名、工位、原因措施的意思要看「抽看.md」。", "",
        "## 各检查项不过的次数", "",
        "| 检查 | 第一次 | 修一次后仍不过 |", "|---|---|---|",
        *[f"| {c} | {first_fail.get(c, 0)} | {final_fail.get(c, 0)} |" for c in checks], "",
        "## 长度阶梯（原因分析栏，富文本）", "",
        "| 字数 | 次数 | 通过 | 单次 P50 | 单次 P90 | 单次最长 | 修一次总耗时 P90 | 截断 | 输出/输入 | 达标 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *ladder_rows, "",
        "## 各样例", "",
        "| 样例 | 说明 | 次数 | 通过 | 一次过 | 不过的检查 | 样例要求没满足 | 平均总耗时 |", "|---|---|---|---|---|---|---|---|",
    ]
    by_case: dict[str, list[dict[str, Any]]] = {}
    for r in raw:
        if r["part"] == "cases":
            by_case.setdefault(r["id"], []).append(r)
    for cid in sorted(by_case):
        runs = by_case[cid]
        fails = sorted({c for r in runs for a in r["attempts"] for c in a.get("failed") or []})
        probs = sorted({p for r in runs for p in r["expect_problems"]})
        totals = [_total(r) for r in runs if r["attempts"]]
        lines.append(
            f"| {cid} | {cases_by_id.get(cid, {}).get('note', '')} | {len(runs)} | "
            f"{sum(1 for r in runs if r['outcome'] in ('ok', (cases_by_id.get(cid, {}).get('expect') or {}).get('error_code')))} | "
            f"{sum(1 for r in runs if r['outcome'] == 'ok' and len(r['attempts']) == 1)} | {'、'.join(fails) or '—'} | "
            f"{'；'.join(probs) or '—'} | {_fmt(statistics.mean(totals) if totals else None)} |")
    (out_dir / "汇总.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (out_dir / "错例.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["部分", "样例", "第几次", "第几次调用", "不过的检查", "多出", "缺少", "占位", "长度", "出错", "样例要求没满足",
                    "输出开头"])
        for r in raw:
            for i, a in enumerate(r["attempts"], start=1):
                if not a.get("failed") and not a.get("error"):
                    continue
                d = a.get("detail") or {}
                w.writerow([r["part"], r["id"], r["rep"] + 1, i, "、".join(a.get("failed") or []),
                            json.dumps(d.get("多出") or {}, ensure_ascii=False),
                            json.dumps(d.get("缺少") or {}, ensure_ascii=False),
                            json.dumps(d.get("占位") or {}, ensure_ascii=False), d.get("长度") or "", a.get("error") or "",
                            "；".join(r["expect_problems"]), (a.get("content_head") or "")[:200]])
            if not r["attempts"] and r["expect_problems"]:
                w.writerow([r["part"], r["id"], r["rep"] + 1, 0, "", "", "", "", "", "", "；".join(r["expect_problems"]), ""])

    sample = [r for r in raw if r["part"] == "cases" and r["outcome"] == "ok" and r["rep"] == 0]
    extra = [r for r in raw if r["part"] == "cases" and r["outcome"] == "ok" and r["rep"] == 1]
    picked = (sample + extra)[:30]
    review = ["# 抽看：通过检查的润色结果", "",
              "每条看一遍，在「改掉了意思」后面写「否」，或写出改掉的地方（人名、工位、原因、措施、数量的意思等）。看完把本文件发回。", ""]
    for r in picked:
        case = cases_by_id.get(r["id"], {})
        review += [f"## {r['id']} {case.get('note', '')}（第 {r['rep'] + 1} 次）", "", "原文：", "", "```text",
                   case.get("query", ""), "```", "", "润色后：", "", "```text", r.get("output") or "", "```", "",
                   "- 改掉了意思：", ""]
    (out_dir / "抽看.md").write_text("\n".join(review), encoding="utf-8")


# ---------------------------------------------------------------------------- 自检（不连模型）


def self_check() -> int:
    rules = core.load_rules()
    version, cases = load_cases()
    by_id = {c["id"]: c for c in cases}
    problems: list[str] = []
    six = {"problem_desc", "reason", "five_why_question", "five_why_answer", "measures", "prevention"}
    codes = {f.code for f in rules.fields}
    if codes != six:
        problems.append(f"润色规则的栏目不是初始的六种：{sorted(codes)}")
    if rules.max_input != 3000:
        problems.append(f"原文长度上限不是 3000：{rules.max_input}")

    for c in cases:
        prep, code, reason = core.prepare(c["query"], c.get("ext_param"), rules)
        want = (c.get("expect") or {}).get("error_code")
        if (code or None) != want:
            problems.append(f"{c['id']}：预期 {want}，实际 {code or '可以润色'}（{reason}）")
            continue
        if prep is None:
            continue
        echo = json.dumps({"text": prep.split.text}, ensure_ascii=False)
        v = core.check(echo, prep)
        if not v.ok:
            problems.append(f"{c['id']}：照抄原文也没过检查 {v.failed} {v.detail}")
            continue
        res = {"outcome": "ok", "output": v.output}
        for p in expect_problems(c, res):
            problems.append(f"{c['id']}：照抄原文时样例要求没满足：{p}")
        for mark, raw in prep.split.tokens:
            if (v.output or "").count(raw) != 1:
                problems.append(f"{c['id']}：拼回后 {mark} 的原样 HTML 出现 {(v.output or '').count(raw)} 次")
        msgs = first_messages(prep, rules)
        if [m["role"] for m in msgs] != ["system", "user"] or core.MARKER not in msgs[0]["content"]:
            problems.append(f"{c['id']}：提示的形状不对 {[m['role'] for m in msgs]}")

    def neg(cid: str, change: Any, want: str) -> None:
        c = by_id[cid]
        prep, _, _ = core.prepare(c["query"], c.get("ext_param"), rules)
        assert prep is not None
        text = change(prep.split.text)
        if text is None:
            problems.append(f"反例 {cid}/{want}：样例里没有要改的那段")
            return
        content = text if want == core.CHECK_FORMAT else json.dumps({"text": text}, ensure_ascii=False)
        v = core.check(content, prep)
        if want == "通过":
            if not v.ok:
                problems.append(f"反例 {cid}：分条序号不该算多出的数字 {v.failed} {v.detail}")
        elif want not in v.failed:
            problems.append(f"反例 {cid}：应当查出「{want}」，实际 {v.failed}")

    def swap(old: str, new: str):
        return lambda t: t.replace(old, new, 1) if old in t else None

    neg("PL-04", lambda t: t.replace("[[表1]]", "", 1), core.CHECK_MARKS)
    neg("PL-04", lambda t: t + "[[图9]]", core.CHECK_MARKS)
    neg("PL-01", lambda t: t + "，另有999台待查", core.CHECK_ADDED)
    neg("PL-01", swap("一共测了200台", "一共测了若干台"), core.CHECK_REMOVED)
    neg("PL-07", swap("NFC", "近场通信"), core.CHECK_REMOVED)
    neg("PL-12", swap("三个", "3个"), core.CHECK_ADDED)
    neg("PL-01", lambda t: "以下是润色后的内容：\n" + t, core.CHECK_PREFACE)
    neg("PL-19", lambda t: t * 3, core.CHECK_LENGTH)
    neg("PL-10", lambda t: "不是 JSON", core.CHECK_FORMAT)
    neg("PL-11", lambda t: "\n".join(f"{i}. {ln}" for i, ln in enumerate(t.split("\n"), start=1)), "通过")
    neg("PL-21", lambda t: t + "，钢网开孔0.25mm", core.CHECK_ADDED)
    # r1 实测里出现过的两种（2026-11-10）：全英文原文被译成中文；开头加了栏目名作标题
    neg("PL-08", lambda t: "上电后屏幕闪烁，100台中有5台不良，型号A999。", core.CHECK_LANG)
    neg("PL-12", lambda t: "原因分析：\n" + t, "通过")  # r2 起程序去掉这一行（设计 §9 第 6 项）
    c12 = by_id["PL-12"]
    p12, _, _ = core.prepare(c12["query"], c12.get("ext_param"), rules)
    v12 = core.check(json.dumps({"text": "原因分析：\n" + p12.split.text}, ensure_ascii=False), p12) if p12 else None
    if v12 is None or (v12.output or "").startswith("<p>原因分析"):
        problems.append("PL-12：开头单独一行的栏目名没有被去掉")
    # 原文第一行本来就是栏目名时不去掉
    p_head, _, _ = core.prepare("<p>原因分析：</p><p>治具松动了</p>", {"task": core.TASK_CODE, "field": "reason"}, rules)
    v_head = core.check(json.dumps({"text": "原因分析：\n治具松动。"}, ensure_ascii=False), p_head) if p_head else None
    if v_head is None or not v_head.ok or not (v_head.output or "").startswith("<p>原因分析"):
        problems.append("原文第一行就是栏目名时，润色结果里的这一行不该被去掉")
    c08 = by_id["PL-08"]
    p08, _, _ = core.prepare(c08["query"], c08.get("ext_param"), rules)
    if p08 is None or "【原文语言】英文" not in core.user(p08, rules):
        problems.append("PL-08：全英文原文的提示里没有「【原文语言】英文」")

    alt = by_id["PL-33"]
    prep, _, _ = core.prepare(alt["query"], alt.get("ext_param"), rules)
    if prep is None or prep.split.style != core.ALT:
        problems.append("PL-33：原文有 [[ 时占位标记没有换写法")

    for n in LADDER:
        q = ladder_query(n)
        prep, code, _ = core.prepare(q, {"task": core.TASK_CODE, "field": "reason"}, rules, ignore_cap=True)
        if prep is None or prep.input_chars < n:
            problems.append(f"长度阶梯 {n}：拼出来不够长或判错 {code}")
            continue
        sentences = [s for s in prep.split.text.replace("\n", "").split("。") if s]
        if len(sentences) != len(set(sentences)):
            problems.append(f"长度阶梯 {n}：有重复的句子，模型会把重复的并掉，长度比必然不过")
        v = core.check(json.dumps({"text": prep.split.text}, ensure_ascii=False), prep)
        if not v.ok:
            problems.append(f"长度阶梯 {n}：照抄原文也没过检查 {v.failed} {v.detail}")

    print(f"样例 {version}，{len(cases)} 条；润色规则栏目 {len(rules.fields)} 种，原文长度上限 {rules.max_input}")
    if problems:
        print("自检没通过：")
        for p in problems:
            print(f"- {p}")
        return 1
    print("自检通过：参数与原文的判错、拆拼往返、程序检查（含反例）、提示形状、长度阶梯都对。")
    return 0


# ---------------------------------------------------------------------------- 冒烟


def write_smoke(smoke_dir: Path, full_jobs: list[tuple[str, dict[str, Any], int]], concurrency: int) -> None:
    raw = [json.loads(x) for x in (smoke_dir / "raw.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    lines = ["# 冒烟", "", "| 部分 | 样例 | 结果 | 调用次数 | 总耗时（秒） | 出错 |", "|---|---|---|---|---|---|"]
    for r in raw:
        lines.append(f"| {r['part']} | {r['id']} | {r['outcome']} | {len(r['attempts'])} | {_fmt(_total(r))} | "
                     f"{'；'.join(a['error'] for a in r['attempts'] if a.get('error')) or '—'} |")
    each = [_total(r) for r in raw if r["attempts"]]
    model_jobs = sum(1 for p, c, _ in full_jobs if not (c.get("expect") or {}).get("error_code"))
    if each:
        minutes = model_jobs * statistics.mean(each) / max(concurrency, 1) / 60
        lines += ["", f"按冒烟的平均耗时估算：全量 {model_jobs} 项要调模型，并发 {concurrency}，约 {minutes:.0f} 分钟（长文多，实际会更久）。"]
    (smoke_dir / "冒烟.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------- 入口


async def fetch_models(cfg: Cfg) -> Any:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(cfg.base_url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {cfg.api_key or 'EMPTY'}"})
            return r.json() if r.status_code == 200 else f"HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001 —— 只是记录，取不到不影响实测
        return f"取不到：{type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 润色内网实测")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true", help="不连模型，核对样例、拆拼、检查与提示")
    mode.add_argument("--smoke", action="store_true", help="每类跑一两条，估算全量用时")
    mode.add_argument("--run", action="store_true", help="全量，可续跑")
    mode.add_argument("--report", action="store_true", help="只按 raw.jsonl 重出汇总")
    ap.add_argument("--confirm-local", action="store_true", help="确认 FI_LLM_BASE_URL 是内网本地模型服务")
    ap.add_argument("--out", type=Path, help="输出目录，必须在 runtime/ 下")
    ap.add_argument("--parts", default="cases,ladder")
    ap.add_argument("--only", default="", help="只跑这几条，逗号分隔（如 PL-01,LD-3000）")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--ladder-repeats", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=120.0, help="单次请求超时，默认同线上 LLMClient")
    args = ap.parse_args()

    if args.self_check:
        return self_check()

    out_dir = check_out_dir(args.out or DEFAULT_OUT_ROOT / f"{dt.date.today():%Y%m%d}-{core.PROMPT_VERSION}")
    if out_dir is None:
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.report:
        write_report(out_dir)
        print(f"已重出汇总：{out_dir / '汇总.md'}")
        return 0

    load_env_file()
    base = os.environ.get("FI_LLM_BASE_URL", "")
    if not base or not os.environ.get("FI_LLM_MODEL"):
        print("缺 FI_LLM_BASE_URL 或 FI_LLM_MODEL，见 README「准备」", file=sys.stderr)
        return 2
    if not args.confirm_local:
        print(f"会把合成样例发给 {base}。确认这是内网本地模型服务后加 --confirm-local 再运行。", file=sys.stderr)
        return 2
    cfg = Cfg(base_url=base, api_key=os.environ.get("FI_LLM_API_KEY", ""), model=os.environ["FI_LLM_MODEL"],
              concurrency=args.concurrency, timeout=args.timeout)
    rules = core.load_rules()
    version, cases = load_cases()
    info_path = out_dir / "run_info.json"
    if info_path.exists():
        old = json.loads(info_path.read_text(encoding="utf-8"))
        now = (cfg.model, core.PROMPT_VERSION, version, LADDER_VERSION)
        before = (old.get("model"), old.get("prompt"), old.get("cases_version"), old.get("ladder_version"))
        # 冒烟不续跑（每次重来）；只有目录里已有全量结果时才要求同一套设置，免得新旧结果混在一起
        if args.run and (out_dir / "raw.jsonl").exists() and before != now:
            print(f"{out_dir} 里是模型 {before[0]}、提示 {before[1]}、样例 {before[2]}、长度阶梯 {before[3]} 的结果，"
                  f"本次是 {'、'.join(now)}。请用 --out 指一个新目录。", file=sys.stderr)
            return 2
    models = asyncio.run(fetch_models(cfg))
    info_path.write_text(json.dumps(
        {"models": models, "model": cfg.model, "concurrency": cfg.concurrency, "timeout": cfg.timeout,
         "prompt": core.PROMPT_VERSION, "cases_version": version, "ladder_version": LADDER_VERSION,
         "repeats": args.repeats,
         "ladder_repeats": args.ladder_repeats}, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.smoke:
        by_id = {c["id"]: c for c in cases}
        jobs = [("cases", by_id[i], 0) for i in SMOKE_CASES]
        jobs += [("ladder", c, 0) for c in ladder_cases(1) if c["ladder"] == 1000]
        smoke_dir = out_dir / "smoke"
        smoke_dir.mkdir(exist_ok=True)
        (smoke_dir / "raw.jsonl").unlink(missing_ok=True)  # 冒烟每次重来，不续跑
        asyncio.run(run_jobs(cfg, jobs, smoke_dir / "raw.jsonl", rules, version))
        write_smoke(smoke_dir, build_jobs(args, cases), cfg.concurrency)
        print(f"冒烟完成：{smoke_dir / '冒烟.md'}")
        return 0

    asyncio.run(run_jobs(cfg, build_jobs(args, cases), out_dir / "raw.jsonl", rules, version))
    write_report(out_dir)
    print(f"完成：{out_dir / '汇总.md'}、{out_dir / '错例.csv'}、{out_dir / '抽看.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
