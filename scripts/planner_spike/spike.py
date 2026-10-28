"""规划器实测（G4a）：用内网本地模型跑规划、写分析、反思、临时统计四项，量准确率、稳定性与耗时。

不是模块代码，`src/` 不引用它，不随 wheel 发布。用法、输出与能发回什么，见同目录 README.md。

    uv run python scripts/planner_spike/spike.py --self-check                 # 不连模型，用期望冒充模型，检验打分本身
    uv run python scripts/planner_spike/spike.py --smoke --confirm-local      # 冒烟：连得上吗、默认带不带思考、多快
    uv run python scripts/planner_spike/spike.py --run --confirm-local        # 全量
    uv run python scripts/planner_spike/spike.py --report --out <目录>        # 只按已有 raw.jsonl 重出汇总
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import re
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forge_platform.policy import PolicyLLM  # noqa: E402  与线上 ctx.llm 同一段合并 system 的代码
from forge_sandbox import run_script  # noqa: E402

import prompts  # noqa: E402
import resolve  # noqa: E402
import scoring  # noqa: E402
import stats_tasks  # noqa: E402
from common import CASES_DIR, DEFAULT_OUT_ROOT, check_out_dir, load_env_file  # noqa: E402

# 与线上一致：forge_core.llm.LLMClient 默认超时 120 秒、默认不传 max_tokens；
# stats-sandbox 资源档 60 秒 / 1024MB / 20 万字符
LLM_TIMEOUT = 120.0
SANDBOX = {"timeout": 60, "memory_mb": 1024, "max_output_chars": 200_000}

# 各组设置。「现状」= 线上 ctx.llm 能发出的请求：只有 temperature、max_tokens、response_format，
# 其余三组直接发 HTTP，多带 ctx.llm 目前传不了的参数，作对比。
GROUPS: dict[str, dict[str, Any]] = {
    "现状": {"extra": {}},
    # 请求与「现状」相同，只在本轮问题后面附「问句里能对上的名称与号码」（prematch.py），用来比较附与不附
    "现状+预匹配": {"extra": {}, "prematch": True},
    # 请求同「现状」，计划过格式校验后再过设计稿 §5.3 第 13、15 条校验（resolve.query_checks），不过就打回重写一次；
    # 重写后仍不过，照用重写的计划（设计稿：按模型的计划执行，开头写明按什么理解）
    "现状+校验": {"extra": {}, "query_checks": True},
    "现状+预匹配+校验": {"extra": {}, "prematch": True, "query_checks": True},
    "关思考": {"extra": {"chat_template_kwargs": {"enable_thinking": False}}},
    "思考low": {"extra": {"reasoning_effort": "low"}},
    "推荐采样": {"temperature": 0.7,
                 "extra": {"top_p": 0.8, "top_k": 20, "presence_penalty": 1.5,
                           "chat_template_kwargs": {"enable_thinking": False}}},
}

THRESHOLDS = [
    ("计划 JSON 合格（含改一次）", "json_ok", ">=", 0.99),
    ("选对技能", "skill", ">=", 0.95),
    ("关键参数正确（最差的一类）", "param_min", ">=", 0.90),
    ("必须追问：漏问", "miss_clarify", "<=", 0.02),
    ("必须追问：多问", "extra_clarify", "<=", 0.05),
    ("多段拆分与依赖", "multi", ">=", 0.85),
    ("同一问句多次计划一致", "consistent", ">=", 0.95),
    ("规划单次耗时 P90（秒）", "p90", "<=", 10.0),
]


@dataclass
class Cfg:
    base_url: str
    api_key: str
    model: str
    concurrency: int
    timeout: float
    self_check: bool = False


def _load_cases(name: str) -> list[dict]:
    return json.loads((CASES_DIR / name).read_text(encoding="utf-8"))["cases"]


PLAN_CASES = _load_cases("plan_cases.json")
PLAN_CASES_VERSION = json.loads((CASES_DIR / "plan_cases.json").read_text(encoding="utf-8"))["version"]
NARRATIVE_CASES = _load_cases("narrative_cases.json")
REFLECT_CASES = _load_cases("reflect_cases.json")
PLAN_BY_ID = {c["id"]: c for c in PLAN_CASES}
NARR_BY_ID = {c["id"]: c for c in NARRATIVE_CASES}
REFL_BY_ID = {c["id"]: c for c in REFLECT_CASES}
TASK_BY_ID = {t["id"]: t for t in stats_tasks.TASKS}


def with_policy(system: str, user_msgs: list[dict]) -> list[dict]:
    """平台 PolicyLLM 把红线段并进首条 system；这里直接调它的同一段代码。"""
    return PolicyLLM(None)._prepare([{"role": "system", "content": system}, *user_msgs])


# ---------------------------------------------------------------------------
# 调模型
# ---------------------------------------------------------------------------


class Caller:
    def __init__(self, cfg: Cfg, client: httpx.AsyncClient) -> None:
        self.cfg = cfg
        self.client = client
        self.sem = asyncio.Semaphore(cfg.concurrency)
        self.url = cfg.base_url.rstrip("/") + "/chat/completions"

    def _headers(self, part: str, case: str) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.cfg.api_key or 'EMPTY'}"}
        if self.cfg.self_check:
            h.update({"X-Spike-Part": part, "X-Spike-Case": case})
        return h

    def _payload(self, group: str, messages: list[dict], *, temperature: float, max_tokens: int | None,
                 json_mode: bool, stream: bool) -> dict:
        g = GROUPS[group]
        payload: dict[str, Any] = {"model": self.cfg.model, "messages": messages,
                                   "temperature": g.get("temperature", temperature), "stream": stream}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        payload.update(g["extra"])
        return payload

    async def chat(self, group: str, messages: list[dict], *, part: str, case: str, temperature: float = 0.0,
                   max_tokens: int | None = None, json_mode: bool = True) -> dict:
        payload = self._payload(group, messages, temperature=temperature, max_tokens=max_tokens,
                                json_mode=json_mode, stream=False)
        rec: dict[str, Any] = {"status": None, "error": None, "content": "", "reasoning_chars": 0,
                               "reasoning_head": "", "think_in_content": False, "usage": {}, "finish_reason": None,
                               "latency": None, "retries": 0}
        async with self.sem:
            for attempt in range(3):
                started = time.monotonic()
                try:
                    r = await self.client.post(self.url, json=payload, headers=self._headers(part, case))
                except httpx.TimeoutException:
                    rec.update(error="超时", latency=time.monotonic() - started)
                    return rec
                except httpx.TransportError as exc:
                    rec.update(error=f"连接出错：{type(exc).__name__}", retries=attempt + 1)
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                rec["latency"] = time.monotonic() - started
                rec["status"] = r.status_code
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    rec["retries"] = attempt + 1
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                if r.status_code >= 400:
                    rec["error"] = f"HTTP {r.status_code}：{r.text[:300]}"
                    return rec
                data = r.json()
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
                rec.update(content=content, reasoning_chars=len(reasoning), reasoning_head=reasoning[:3000],
                           think_in_content="<think>" in content, usage=data.get("usage") or {},
                           finish_reason=choice.get("finish_reason"), error=None)
                return rec
        return rec

    async def stream(self, group: str, messages: list[dict], *, part: str, case: str,
                     temperature: float = 0.2, max_tokens: int | None = None) -> dict:
        payload = self._payload(group, messages, temperature=temperature, max_tokens=max_tokens,
                                json_mode=False, stream=True)
        rec: dict[str, Any] = {"status": None, "error": None, "content": "", "reasoning_chars": 0,
                               "reasoning_head": "", "think_in_content": False, "usage": {}, "finish_reason": None,
                               "latency": None, "ttft": None, "retries": 0}
        async with self.sem:
            for _ in range(2):
                started = time.monotonic()
                parts: list[str] = []
                reasoning: list[str] = []
                try:
                    async with self.client.stream("POST", self.url, json=payload, headers=self._headers(part, case)) as r:
                        rec["status"] = r.status_code
                        if r.status_code >= 400:
                            body = (await r.aread()).decode("utf-8", "replace")
                            # 与 LLMClient.chat_stream 一致：端点不认 stream_options 时去掉重试一次
                            if r.status_code == 400 and "stream_options" in payload:
                                payload.pop("stream_options")
                                continue
                            rec.update(error=f"HTTP {r.status_code}：{body[:300]}", latency=time.monotonic() - started)
                            return rec
                        async for line in r.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            chunk = line[5:].strip()
                            if chunk == "[DONE]":
                                break
                            try:
                                data = json.loads(chunk)
                            except json.JSONDecodeError:
                                continue
                            if data.get("usage"):
                                rec["usage"] = data["usage"]
                            for choice in data.get("choices") or []:
                                delta = choice.get("delta") or {}
                                if delta.get("reasoning_content") or delta.get("reasoning"):
                                    reasoning.append(delta.get("reasoning_content") or delta.get("reasoning"))
                                if delta.get("content"):
                                    if rec["ttft"] is None:
                                        rec["ttft"] = time.monotonic() - started
                                    parts.append(delta["content"])
                                if choice.get("finish_reason"):
                                    rec["finish_reason"] = choice["finish_reason"]
                except httpx.TimeoutException:
                    rec.update(error="超时", latency=time.monotonic() - started)
                    return rec
                except httpx.TransportError as exc:
                    rec.update(error=f"连接出错：{type(exc).__name__}")
                    return rec
                content = "".join(parts)
                joined = "".join(reasoning)
                rec.update(content=content, reasoning_chars=len(joined), reasoning_head=joined[:3000],
                           think_in_content="<think>" in content, latency=time.monotonic() - started)
                return rec
        return rec


# ---------------------------------------------------------------------------
# 四项实测
# ---------------------------------------------------------------------------

PLAN_SYSTEM = prompts.planner_system()


async def run_plan(caller: Caller, case: dict, group: str) -> dict:
    user = prompts.planner_user(case, prematch=bool(GROUPS[group].get("prematch")))
    messages = with_policy(PLAN_SYSTEM, [{"role": "user", "content": user}])
    attempts = []
    first = await caller.chat(group, messages, part="plan", case=case["id"])
    attempts.append(first)
    plan, errors, parsed_first = None, [], False
    # 「现状+校验」类的组：格式合格后再过 §5.3 第 13、15 条校验（resolve.query_checks），不过也打回重写一次
    checks = bool(GROUPS[group].get("query_checks"))
    query_errors: list[str] = []
    if first["error"] is None:
        try:
            plan = scoring.parse_reply(first["content"])
            parsed_first = True
            errors = scoring.validate_plan(plan)
        except (ValueError, json.JSONDecodeError) as exc:
            errors = [f"不是合格的 JSON：{exc}"]
        if not errors and checks:
            query_errors = resolve.query_checks(resolve.apply(plan, case["q"]), case["q"])
        if errors or query_errors:
            first_plan = plan if not errors else None
            repair_msgs = [*messages, {"role": "assistant", "content": first["content"]},
                           {"role": "user", "content": prompts.repair_user(errors or query_errors)}]
            second = await caller.chat(group, repair_msgs, part="plan", case=case["id"])
            attempts.append(second)
            plan, errors2 = None, ["修正那次调用出错"]
            if second["error"] is None:
                try:
                    plan = scoring.parse_reply(second["content"])
                    errors2 = scoring.validate_plan(plan)
                except (ValueError, json.JSONDecodeError) as exc:
                    errors2 = [f"不是合格的 JSON：{exc}"]
            if errors2:
                # 只因校验打回、重写的又不合格时，照用第一次的计划（它格式是合格的）
                plan = first_plan
            errors = errors + query_errors + ["（修正后）" + e for e in errors2]
    return {"attempts": attempts, "parsed_first": parsed_first, "valid_first": parsed_first and len(attempts) == 1,
            "plan": plan, "errors": errors, "query_errors": query_errors}


_NUM = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_CN_NUM = re.compile(r"([两三四五六七八九十][零一二两三四五六七八九十]*)(?=[张个条起项家类次天倍名成])")
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_LEAK = re.compile(r"[A-Za-z]+_[A-Za-z0-9_]+|dbo\.|\bSELECT\b|\bFROM\s", re.I)
_ISSUE_NO = re.compile(r"(?<![A-Za-z0-9])(?:ZC|BR|HW)\d{7}(?![0-9])", re.I)


def _cn_to_int(s: str) -> int | None:
    if "十" not in s:
        return _CN_DIGIT.get(s) if len(s) == 1 else None
    left, _, right = s.partition("十")
    tens = _CN_DIGIT.get(left, 1) if left else 1
    ones = _CN_DIGIT.get(right, 0) if right else 0
    return tens * 10 + ones


def allowed_numbers(case: dict) -> set[float]:
    """问句、说明、表格、事实里出现过的数，阿拉伯数字与汉字数（「三个域」）都算。"""
    text = " ".join([case["q"], case.get("note", ""), case.get("table", ""), json.dumps(case["facts"], ensure_ascii=False)])
    allowed = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)}
    allowed |= {float(v) for v in (_cn_to_int(x) for x in _CN_NUM.findall(text)) if v is not None}
    return allowed


# 「这两类」「那两张」是指代前文点过名的几项，不是统计出来的数，不查
_CN_NUM_CLAIM = re.compile(r"(?<![这那])" + _CN_NUM.pattern)
# 「前两名」「前 3 名」是表格里的名次；「A 和 B 两类」数的是本句刚点过名的几项。都不是统计出来的数，不查
_ORDINAL = re.compile(r"前\s*(?:\d+|[两三四五六七八九十]+)\s*[名位]")
_ENUM_TWO = re.compile(r"([^，。；]*[和与、][^，。；]*?)两(?=[个类张家项名])")


def _ordinal_free(sentence: str) -> str:
    return _ENUM_TWO.sub(r"\1", _ORDINAL.sub("", sentence))


def check_narrative(case: dict, text: str) -> dict:
    allowed = allowed_numbers(case)
    body = scoring._THINK.sub("", text or "")
    sentences = [s for s in re.split(r"[。！？；\n]+", body) if s.strip()]
    with_numbers, bad = 0, []
    for s in sentences:
        values = [float(x) for x in _NUM.findall(_ordinal_free(s))]
        values += [v for v in (_cn_to_int(x) for x in _CN_NUM_CLAIM.findall(_ordinal_free(s))) if v is not None]
        if not values:
            continue
        with_numbers += 1
        unsupported = [v for v in values if not any(abs(v - a) < 1e-9 for a in allowed)]
        if unsupported:
            bad.append({"句子": s.strip(), "事实里没有的数": unsupported})
    # 问题编号里的数字不在上面查（前面紧挨字母），单独查：正文里点名的单号必须出现在问句、表格或事实里（设计稿 §8.3）
    source = " ".join([case["q"], case.get("table", ""), json.dumps(case["facts"], ensure_ascii=False)]).upper()
    for s in sentences:
        fake = [n for n in _ISSUE_NO.findall(s) if n.upper() not in source]
        if fake:
            bad.append({"句子": s.strip(), "事实里没有的数": fake})
    # 线上按设计会把含出处不明数字的句子删掉：首句（直接回应用户的那句）被删、或删完剩不下几句，回答就残了
    bad_set = {b["句子"] for b in bad}
    first_bad = bool(sentences) and sentences[0].strip() in bad_set
    return {"sentences": len(sentences), "with_numbers": with_numbers, "bad": bad,
            "leaks": _LEAK.findall(body), "chars": len(body),
            "first_bad": first_bad, "left": len(sentences) - len(bad)}


async def run_narrative(caller: Caller, case: dict, group: str) -> dict:
    messages = with_policy(prompts.narrative_system(), [{"role": "user", "content": prompts.narrative_user(case)}])
    rec = await caller.stream(group, messages, part="narrative", case=case["id"])
    check = check_narrative(case, rec["content"]) if rec["error"] is None else None
    return {"attempts": [rec], "check": check}


async def run_reflect(caller: Caller, case: dict, group: str) -> dict:
    messages = with_policy(prompts.REFLECT_SYSTEM, [{"role": "user", "content": prompts.reflect_user(case)}])
    rec = await caller.chat(group, messages, part="reflect", case=case["id"])
    action, ok, err = None, False, None
    if rec["error"] is None:
        try:
            action = str(scoring.parse_reply(rec["content"]).get("action", "")).strip()
            ok = action in case["expect"]
        except (ValueError, json.JSONDecodeError) as exc:
            err = str(exc)
    return {"attempts": [rec], "action": action, "ok": ok, "parse_error": err}


_ISSUES = stats_tasks.make_issues()
_REF_RESULTS: dict[str, Any] = {}


def _extract_code(text: str) -> str:
    body = scoring._THINK.sub("", text or "")
    m = re.search(r"```(?:python)?\s*\n(.*?)```", body, re.S)
    return (m.group(1) if m else body).strip()


# Windows 上十几个沙箱子进程同时跑时，偶有子进程直接崩掉（exit=3221227274，即 0xC000070A，无 stderr），
# 与脚本内容无关：12 核机器上不限个数时 60 次崩 2～4 次，限 8、4、2 个时各 60 次都没崩。
# 线上一个请求一次只跑一个脚本，这里也限住同时跑的个数，并把「沙箱异常退出」重试两次，免得算到模型头上。
_SANDBOX_SLOTS = threading.BoundedSemaphore(2)
_SANDBOX_CRASH = "沙箱异常退出"


def _run_sandbox(script: str):
    out = None
    for attempt in range(3):
        with _SANDBOX_SLOTS:
            out = run_script(script, {"issues": _ISSUES}, **SANDBOX)
        if out.ok or not out.error.startswith(_SANDBOX_CRASH):
            break
        time.sleep(1 + attempt)
    return out


async def _sandbox(code: str):
    return await asyncio.to_thread(_run_sandbox, prompts.STATS_HELPERS + "\n\n" + code)


async def reference_result(task: dict) -> Any:
    if task["id"] not in _REF_RESULTS:
        out = await _sandbox(task["ref"])
        if not out.ok:
            raise RuntimeError(f"参考脚本 {task['id']} 跑不通：{out.error[:500]}")
        _REF_RESULTS[task["id"]] = out.result
    return _REF_RESULTS[task["id"]]


def prepare_references(tasks: list[dict]) -> list[str]:
    """开跑前先把参考结果逐题算好：参考脚本有问题时，在调模型之前就停下。返回跑不通的说明。"""
    problems = []
    for task in tasks:
        try:
            asyncio.run(reference_result(task))
        except RuntimeError as exc:
            problems.append(str(exc))
    return problems


async def run_stats(caller: Caller, task: dict, group: str) -> dict:
    want = await reference_result(task)
    user = prompts.stats_user(task, stats_tasks.COLUMNS, stats_tasks.sample_rows(_ISSUES))
    messages = with_policy(prompts.STATS_SYSTEM, [{"role": "user", "content": user}])
    attempts, results = [], []
    rec = await caller.chat(group, messages, part="stats", case=task["id"], json_mode=False)
    attempts.append(rec)
    if rec["error"] is not None:
        return {"attempts": attempts, "first_ok": False, "final_ok": False, "results": results}
    out = await _sandbox(_extract_code(rec["content"]))
    first_ok = bool(out.ok and stats_tasks.results_equal(out.result, want))
    results.append({"ok": out.ok, "error": (out.error or "")[:800], "match": first_ok})
    final_ok = first_ok
    if not out.ok:
        repair = [*messages, {"role": "assistant", "content": rec["content"]},
                  {"role": "user", "content": f"脚本运行出错：\n{(out.error or '')[:1500]}\n请修正后重新给出完整脚本，只输出代码。"}]
        rec2 = await caller.chat(group, repair, part="stats", case=task["id"], json_mode=False)
        attempts.append(rec2)
        if rec2["error"] is None:
            out2 = await _sandbox(_extract_code(rec2["content"]))
            final_ok = bool(out2.ok and stats_tasks.results_equal(out2.result, want))
            results.append({"ok": out2.ok, "error": (out2.error or "")[:800], "match": final_ok})
    return {"attempts": attempts, "first_ok": first_ok, "final_ok": final_ok, "results": results}


# ---------------------------------------------------------------------------
# 编排与续跑
# ---------------------------------------------------------------------------


def _key(part: str, case: str, group: str, rep: int) -> str:
    return f"{part}|{case}|{group}|{rep}"


def load_raw(path: Path) -> dict[str, dict]:
    done: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["key"]] = rec
    return done


def _call_failed(rec: dict) -> bool:
    return any(a.get("error") for a in rec.get("attempts") or [])


async def run_jobs(cfg: Cfg, jobs: list[tuple[str, str, str, int]], raw_path: Path,
                   transport: httpx.AsyncBaseTransport | None = None) -> None:
    done = load_raw(raw_path)
    todo = [j for j in jobs if _key(*j) not in done or _call_failed(done[_key(*j)])]
    print(f"待跑 {len(todo)} 项（已完成 {len(jobs) - len(todo)} 项）", flush=True)
    lock = asyncio.Lock()
    started, finished = time.monotonic(), 0
    crashed: list[str] = []
    async with httpx.AsyncClient(timeout=cfg.timeout, transport=transport) as client:
        caller = Caller(cfg, client)

        async def one(part: str, cid: str, group: str, rep: int) -> None:
            nonlocal finished
            # 一项出了工具自己的错，不拖垮其余各项；这一项不记入 raw.jsonl，下次运行同一命令会重跑
            try:
                if part == "plan":
                    res = await run_plan(caller, PLAN_BY_ID[cid], group)
                elif part == "narrative":
                    res = await run_narrative(caller, NARR_BY_ID[cid], group)
                elif part == "reflect":
                    res = await run_reflect(caller, REFL_BY_ID[cid], group)
                else:
                    res = await run_stats(caller, TASK_BY_ID[cid], group)
            except Exception as exc:  # noqa: BLE001
                msg = f"{_key(part, cid, group, rep)}：{type(exc).__name__}：{str(exc)[:300]}"
                async with lock:
                    crashed.append(msg)
                    print(f"  ⚠ 工具内部出错，这一项跳过：{msg}", flush=True)
                return
            rec = {"key": _key(part, cid, group, rep), "part": part, "case": cid, "group": group, "rep": rep,
                   "prompt": prompts.PROMPT_VERSION, "at": dt.datetime.now().isoformat(timespec="seconds"), **res}
            async with lock:
                with raw_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                finished += 1
                if finished % 25 == 0 or finished == len(todo):
                    rate = finished / max(time.monotonic() - started, 1e-6)
                    left = (len(todo) - finished) / rate if rate else 0
                    print(f"  {finished}/{len(todo)}，约 {rate * 60:.0f} 项/分钟，剩约 {left / 60:.0f} 分钟", flush=True)

        await asyncio.gather(*(one(*j) for j in todo))
    if crashed:
        print(f"有 {len(crashed)} 项因工具内部出错没有记录（见上面 ⚠ 行）。再运行同一条命令会补跑这些项；"
              "反复出现请把 ⚠ 行发回。", flush=True)


def build_jobs(args: argparse.Namespace) -> list[tuple[str, str, str, int]]:
    jobs: list[tuple[str, str, str, int]] = []
    parts = args.parts.split(",")
    groups = args.groups.split(",")
    aux = args.aux_groups.split(",")
    plan_cases = PLAN_CASES[: args.limit] if args.limit else PLAN_CASES
    core = [c for c in plan_cases if c.get("core")]
    if "plan" in parts:
        for g in groups:
            cases, reps = (plan_cases, args.repeats) if g == groups[0] else (core, args.sub_repeats)
            jobs += [("plan", c["id"], g, r) for c in cases for r in range(reps)]
    lim = args.limit or None
    if "narrative" in parts:
        jobs += [("narrative", c["id"], g, r) for g in aux for c in NARRATIVE_CASES[:lim] for r in range(args.aux_repeats)]
    if "reflect" in parts:
        jobs += [("reflect", c["id"], g, r) for g in aux for c in REFLECT_CASES[:lim] for r in range(args.aux_repeats)]
    if "stats" in parts:
        jobs += [("stats", t["id"], g, r) for g in aux for t in stats_tasks.TASKS[:lim] for r in range(args.aux_repeats)]
    return jobs


async def fetch_models(cfg: Cfg, transport: httpx.AsyncBaseTransport | None = None) -> Any:
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport) as client:
            r = await client.get(cfg.base_url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {cfg.api_key or 'EMPTY'}"})
            if r.status_code >= 400:
                return {"error": f"HTTP {r.status_code}"}
            data = r.json()
            keep = ("id", "root", "owned_by", "max_model_len")
            return [{k: m.get(k) for k in keep if k in m} for m in data.get("data") or []]
    except httpx.HTTPError as exc:
        return {"error": type(exc).__name__}


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vs = sorted(values)
    idx = min(len(vs) - 1, max(0, int(round(q * (len(vs) - 1)))))
    return vs[idx]


def _rate(n: int, d: int) -> float | None:
    return None if d == 0 else n / d


def _fmt(v: float | None, pct: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%" if pct else f"{v:.2f}"


def _tag(case: dict) -> str:
    alt0 = scoring._alt_steps(case["expect"][0])[0]
    if case["id"].startswith("M-"):
        return "不整齐输入"
    if case.get("history"):
        return "多轮"
    if case.get("clarify") in ("model", "rule"):
        return "追问"
    if len(alt0) > 1:
        return "多步"
    skill = alt0[0]["skill"] if isinstance(alt0[0]["skill"], str) else alt0[0]["skill"][0]
    return {"list_issues": "清单", "lookup_numbers": "按号查单", "issue_detail": "单张详情", "aggregate": "统计",
            "text_search": "文字查找", "custom_stats": "统计", "introduce": "寒暄与边界", "clarify": "追问",
            "rerender": "多轮", "verify_previous": "多轮"}.get(skill, skill)


def _replan(rec: dict) -> dict | None:
    """运行时判为不合格的计划，按当前的校验规则再认一次（校验规则放宽后，旧记录也照新规则算）。"""
    for a in reversed(rec.get("attempts") or []):
        if a.get("error"):
            continue
        try:
            plan = scoring.parse_reply(a.get("content") or "")
        except (ValueError, json.JSONDecodeError):
            continue
        if not scoring.validate_plan(plan):
            return plan
    return None


def summarize_plan(records: list[dict]) -> tuple[dict[str, dict], list[list]]:
    by_group: dict[str, list[dict]] = {}
    for r in records:
        by_group.setdefault(r["group"], []).append(r)
    out: dict[str, dict] = {}
    errors_rows: list[list] = []
    for group, recs in by_group.items():
        cat_n: dict[str, int] = {}
        cat_ok: dict[str, int] = {}
        tags: dict[str, list[int]] = {}
        lat_first, lat_total, prompt_tok, comp_tok, reason_chars = [], [], [], [], []
        n = len(recs)
        json_ok = valid_first = parsed_first = all_ok = skill_ok = raw_ok = 0
        miss_n = miss = extra_n = extra = multi_n = multi_ok = 0
        reasoning_runs = think_runs = length_cut = http_err = query_bounced = 0
        sigs: dict[str, list[str]] = {}
        for r in recs:
            case = PLAN_BY_ID[r["case"]]
            a0 = r["attempts"][0]
            if a0.get("latency") is not None and not a0.get("error"):
                lat_first.append(a0["latency"])
            lat_total.append(sum(a.get("latency") or 0 for a in r["attempts"]))
            for a in r["attempts"]:
                u = a.get("usage") or {}
                if u.get("prompt_tokens"):
                    prompt_tok.append(u["prompt_tokens"])
                if u.get("completion_tokens"):
                    comp_tok.append(u["completion_tokens"])
                if a.get("reasoning_chars"):
                    reasoning_runs += 1
                    reason_chars.append(a["reasoning_chars"])
                think_runs += bool(a.get("think_in_content"))
                length_cut += a.get("finish_reason") == "length"
                http_err += bool(a.get("error"))
            parsed_first += bool(r.get("parsed_first"))
            valid_first += bool(r.get("valid_first"))
            plan = r.get("plan")
            if plan is None:
                plan = _replan(r)
            resolved = resolve.apply(plan, case["q"])
            if r.get("query_errors") or (not GROUPS.get(group, {}).get("query_checks") and resolved is not None
                                         and resolve.query_checks(resolved, case["q"])):
                query_bounced += 1
            if plan is not None:
                json_ok += 1
                # 打分与一致性都按代码处理后的计划（线上执行的就是它）；另记模型原样的全对率作对照
                res = scoring.score_plan(case, resolved)
                raw_ok += int(scoring.score_plan(case, plan)["all_ok"])
                sigs.setdefault(r["case"], []).append(scoring.plan_signature(resolved))
            else:
                blank = scoring.score_alt(case["expect"][0], {}, [])
                res = {"categories": {k: False for k in blank}, "all_ok": False, "alt": 0,
                       "clarify": "漏问" if case.get("clarify") in ("model", "rule") else None}
            cats = res["categories"]
            for cat, ok in cats.items():
                cat_n[cat] = cat_n.get(cat, 0) + 1
                cat_ok[cat] = cat_ok.get(cat, 0) + int(ok)
            skill_ok += int(cats.get("技能", False))
            all_ok += int(res["all_ok"])
            tags.setdefault(_tag(case), []).append(int(res["all_ok"]))
            kind = case.get("clarify", "none")
            if kind in ("model", "rule"):
                miss_n += 1
                miss += res["clarify"] == "漏问"
            else:
                extra_n += 1
                extra += res["clarify"] == "多问"
            if len(scoring._alt_steps(case["expect"][0])[0]) > 1:
                multi_n += 1
                multi_ok += int(cats.get("技能", False) and cats.get("依赖", True))
            if not res["all_ok"]:
                wrong = [c for c, ok in cats.items() if not ok]
                if res["clarify"]:
                    wrong.append(res["clarify"])
                exp_json = json.dumps(case["expect"][res["alt"]], ensure_ascii=False)
                got_json = json.dumps(plan, ensure_ascii=False) if plan is not None else "；".join(r.get("errors") or [])[:600]
                fixed = "" if resolved == plan else json.dumps(resolved, ensure_ascii=False)[:1500]
                errors_rows.append(["plan", group, r["case"], r["rep"], "、".join(wrong), case["q"], exp_json[:1500],
                                    got_json[:1500], fixed])
        consistent_n = sum(1 for v in sigs.values() if len(v) >= 2)
        consistent = sum(1 for v in sigs.values() if len(v) >= 2 and len(set(v)) == 1)
        params = {c: _rate(cat_ok[c], cat_n[c]) for c in scoring.CATEGORIES if c in cat_n and c != "技能"}
        out[group] = {
            "runs": n, "http_err": http_err,
            "parsed_first": _rate(parsed_first, n), "valid_first": _rate(valid_first, n), "json_ok": _rate(json_ok, n),
            "skill": _rate(skill_ok, n), "all_ok": _rate(all_ok, n), "raw_all_ok": _rate(raw_ok, n),
            "params": params, "param_min": min((v for v in params.values() if v is not None), default=None),
            "miss_clarify": _rate(miss, miss_n), "extra_clarify": _rate(extra, extra_n),
            "multi": _rate(multi_ok, multi_n), "consistent": _rate(consistent, consistent_n),
            "consistent_n": consistent_n, "query_bounced": query_bounced,
            "p50": _pct(lat_first, 0.5), "p90": _pct(lat_first, 0.9), "p99": _pct(lat_first, 0.99),
            "total_p90": _pct(lat_total, 0.9),
            "prompt_tok": statistics.mean(prompt_tok) if prompt_tok else None,
            "comp_tok": statistics.mean(comp_tok) if comp_tok else None,
            "reasoning_runs": reasoning_runs, "reason_chars": statistics.mean(reason_chars) if reason_chars else None,
            "think_runs": think_runs, "length_cut": length_cut,
            "tags": {t: (_rate(sum(v), len(v)), len(v)) for t, v in sorted(tags.items())},
        }
    return out, errors_rows


def _common_cases_table(records: list[dict], groups: list[str]) -> list[str]:
    """各组跑的问句不一样多（第一组跑全部，其余只跑 core），比较时只看各组都跑了的问句。"""
    by: dict[str, dict[str, list[dict]]] = {}
    for r in records:
        by.setdefault(r["group"], {}).setdefault(r["case"], []).append(r)
    common = set.intersection(*(set(by.get(g, {})) for g in groups))
    if not common:
        return []
    lines = ["", f"**只看各组都跑了的 {len(common)} 条问句**", "", "| 指标 | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
    rows: dict[str, list[str]] = {"整份计划全对": [], "同一问句多次一致": [], "其中「不整齐输入」整份全对": []}
    for g in groups:
        ok = n = m_ok = m_n = cons = cons_n = 0
        for cid in common:
            case = PLAN_BY_ID[cid]
            sigs = []
            for r in by[g][cid]:
                plan = r.get("plan") or _replan(r)
                good = plan is not None and scoring.score_plan(case, resolve.apply(plan, case["q"]))["all_ok"]
                ok, n = ok + good, n + 1
                if cid.startswith("M-"):
                    m_ok, m_n = m_ok + good, m_n + 1
                if plan is not None:
                    sigs.append(scoring.plan_signature(resolve.apply(plan, case["q"])))
            if len(sigs) >= 2:
                cons_n += 1
                cons += len(set(sigs)) == 1
        rows["整份计划全对"].append(_fmt(_rate(ok, n)))
        rows["同一问句多次一致"].append(_fmt(_rate(cons, cons_n)))
        rows["其中「不整齐输入」整份全对"].append(_fmt(_rate(m_ok, m_n)))
    lines += [f"| {k} | " + " | ".join(v) + " |" for k, v in rows.items()]
    return lines


def _offline_code_sections() -> list[str]:
    """不调模型的两项：号码直通命中了哪些问句、对不对；预匹配提示附了什么、有没有疑似噪声。"""
    import prematch

    lines = ["", "## 号码直通（代码规则，不调模型）", "",
             "问句只有号码（加上号的种类与「查一下」「是哪张单」这类套话）时不调规划，代码直接查单。下表是对照集里命中直通的问句。", "",
             "| 编号 | 问句 | 直通后对不对 |", "|---|---|---|"]
    hit = bad = 0
    for case in PLAN_CASES:
        plan = resolve.number_shortcut(case["q"])
        if plan is None:
            continue
        good = scoring.score_plan(case, plan)["all_ok"]
        hit, bad = hit + 1, bad + (not good)
        lines.append(f"| {case['id']} | {case['q']} | {'对' if good else '错'} |")
    lines += ["", f"共 {hit} 条命中直通，{bad} 条直通后不对。没列出的问句照常交规划器。", ""]

    lines += ["## 预匹配提示（「现状+预匹配」组附在问句后的内容）", "",
              "名字按合成主数据（mockdata.py：人员 15,091、供应商 978、机型 500 等）整串匹配。"
              "「期望里没用到」的提示不一定错（如沿用上一轮的条件），但可能把模型带偏，请逐条看。", ""]
    with_hint = total = 0
    unused: list[str] = []
    for case in PLAN_CASES:
        nums = prematch.find_numbers(case["q"])
        ents = prematch.find_entities(case["q"], [s for *_, s in nums])
        if not nums and not ents:
            continue
        with_hint += 1
        total += len(nums) + len(ents)
        expect_text = json.dumps(case["expect"], ensure_ascii=False).lower()
        for text, kinds, _ in ents:
            if text.lower() not in expect_text:
                unused.append(f"| {case['id']} | {case['q']} | {text} | {'；'.join(kinds)} |")
    lines += [f"- 有提示的问句 {with_hint} 条（共 {len(PLAN_CASES)} 条），共 {total} 条提示。",
              f"- 名字提示里期望没用到的 {len(unused)} 条：", "", "| 编号 | 问句 | 提示的词 | 提示说它是 |", "|---|---|---|---|", *unused, ""]
    return lines


def _passes(v: float | None, op: str, thr: float) -> str:
    if v is None:
        return "—"
    return "✓" if (v >= thr if op == ">=" else v <= thr) else "✗"


def write_report(out_dir: Path, models: Any = None) -> dict:
    raw = list(load_raw(out_dir / "raw.jsonl").values())
    parts: dict[str, list[dict]] = {}
    for r in raw:
        parts.setdefault(r["part"], []).append(r)
    md = ["# 规划器实测汇总", "",
          f"- 生成时间：{dt.datetime.now().isoformat(timespec='seconds')}；提示词 {prompts.PROMPT_VERSION}；"
          f"对照集 {PLAN_CASES_VERSION}，{len(PLAN_CASES)} 条（core {sum(1 for c in PLAN_CASES if c.get('core'))} 条）",
          "- 本文件只有计数、比例、耗时与问句编号，不含业务数据，可以发回。", ""]
    info_path = out_dir / "run_info.json"
    if info_path.exists():
        info = json.loads(info_path.read_text(encoding="utf-8"))
        md += [f"- 模型服务：{json.dumps(info.get('models'), ensure_ascii=False)}",
                f"- 模型名：{info.get('model')}；并发 {info.get('concurrency')}；超时 {info.get('timeout')} 秒", ""]
    err_rows: list[list] = []
    summary: dict[str, Any] = {}

    if parts.get("plan"):
        plan_sum, rows = summarize_plan(parts["plan"])
        summary["plan"] = plan_sum
        err_rows += rows
        groups = list(plan_sum)
        md += ["## 规划", "", "| 指标 | 门槛 | " + " | ".join(groups) + " |", "|---|---|" + "---|" * len(groups)]
        for label, key, op, thr in THRESHOLDS:
            cells = []
            for g in groups:
                v = plan_sum[g][key]
                txt = _fmt(v, pct=key != "p90")
                cells.append(f"{txt} {_passes(v, op, thr)}")
            thr_txt = f"{op} {thr * 100:.0f}%" if key != "p90" else f"{op} {thr:.0f}"
            md.append(f"| {label} | {thr_txt} | " + " | ".join(cells) + " |")
        md += ["", "| 其他 | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
        extra_rows = [
            ("运行次数", lambda s: str(s["runs"])),
            ("调用出错次数（超时、HTTP 错误）", lambda s: str(s["http_err"])),
            ("首次回复能解析成 JSON", lambda s: _fmt(s["parsed_first"])),
            ("首次就合格", lambda s: _fmt(s["valid_first"])),
            ("被 §5.3 第 13、15 条校验拦下的运行（不打回的组为「按现规则会拦下」）", lambda s: str(s["query_bounced"])),
            ("整份计划全对（经代码处理，上面各项都按这个算）", lambda s: _fmt(s["all_ok"])),
            ("整份计划全对（模型原样）", lambda s: _fmt(s["raw_all_ok"])),
            ("参与一致性比较的问句数", lambda s: str(s["consistent_n"])),
            ("首次调用耗时 P50 / P99（秒）", lambda s: f"{_fmt(s['p50'], False)} / {_fmt(s['p99'], False)}"),
            ("含修正的总耗时 P90（秒）", lambda s: _fmt(s["total_p90"], False)),
            ("平均输入 / 输出 token", lambda s: f"{_fmt(s['prompt_tok'], False)} / {_fmt(s['comp_tok'], False)}"),
            ("带思考内容的调用次数（平均思考字数）", lambda s: f"{s['reasoning_runs']}（{_fmt(s['reason_chars'], False)}）"),
            ("正文里混进 <think> 的次数", lambda s: str(s["think_runs"])),
            ("因长度截断的次数", lambda s: str(s["length_cut"])),
        ]
        for label, fn in extra_rows:
            md.append(f"| {label} | " + " | ".join(fn(plan_sum[g]) for g in groups) + " |")
        md += ["", "**各类参数正确率**", "", "| 类别 | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
        for cat in scoring.CATEGORIES:
            if cat == "技能":
                continue
            md.append(f"| {cat} | " + " | ".join(_fmt(plan_sum[g]["params"].get(cat)) for g in groups) + " |")
        tags = sorted({t for g in groups for t in plan_sum[g]["tags"]})
        md += ["", "**按问法（每格：整份全对 / 运行次数）**", "", "| 问法 | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
        for tag in tags:
            cells = []
            for g in groups:
                rate, cnt = plan_sum[g]["tags"].get(tag, (None, 0))
                cells.append(f"{_fmt(rate)} / {cnt}" if cnt else "—")
            md.append(f"| {tag} | " + " | ".join(cells) + " |")
        if len(groups) > 1:
            md += _common_cases_table(parts["plan"], groups)
        md.append("")
        md += _offline_code_sections()

    if parts.get("narrative"):
        md += ["## 写分析", "", "| 组 | 运行次数 | 出错 | 含数字的句子 | 其中数字都出自事实 | 有不合格句子的运行 | 删掉不合格句后：首句被删的运行 / 平均剩几句 | 疑似露表名字段名 | 首字耗时 P50/P90（秒） | 总耗时 P90（秒） |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        by_g: dict[str, list[dict]] = {}
        for r in parts["narrative"]:
            # 按当前的核对规则重算，不用运行时存下的结果（核对规则改了，旧记录也照新规则算）
            a0 = r["attempts"][0]
            r["check"] = None if a0.get("error") else check_narrative(NARR_BY_ID[r["case"]], a0.get("content") or "")
            by_g.setdefault(r["group"], []).append(r)
        samples = ["# 分析段样例", "", "合成事实下模型写的分析段，每组每条取第一次运行。⚠ 标出的句子含事实里没有的数。可以发回。", ""]
        summary["narrative"] = {}
        for g, recs in by_g.items():
            sent = sum((r["check"] or {}).get("with_numbers", 0) for r in recs)
            bad = sum(len((r["check"] or {}).get("bad", [])) for r in recs)
            bad_runs = sum(1 for r in recs if (r["check"] or {}).get("bad"))
            leaks = sum(len((r["check"] or {}).get("leaks", [])) for r in recs)
            errs = sum(1 for r in recs if r["check"] is None)
            ttft = [r["attempts"][0]["ttft"] for r in recs if r["attempts"][0].get("ttft") is not None]
            tot = [r["attempts"][0]["latency"] for r in recs if r["attempts"][0].get("latency") is not None]
            rate = _rate(sent - bad, sent)
            summary["narrative"][g] = {"sentence_ok": rate}
            checks = [r["check"] for r in recs if r["check"]]
            first_bad = sum(1 for c in checks if c.get("first_bad"))
            left = statistics.mean(c["left"] for c in checks) if checks else None
            md.append(f"| {g} | {len(recs)} | {errs} | {sent} | {_fmt(rate)} {_passes(rate, '>=', 0.98)} | {bad_runs} | "
                      f"{first_bad} / {_fmt(left, False)} | {leaks} | "
                      f"{_fmt(_pct(ttft, 0.5), False)} / {_fmt(_pct(ttft, 0.9), False)} | {_fmt(_pct(tot, 0.9), False)} |")
            for r in recs:
                for b in (r["check"] or {}).get("bad", []):
                    err_rows.append(["narrative", g, r["case"], r["rep"], "数字不在事实里", NARR_BY_ID[r["case"]]["q"], "", f"{b['句子']}｜{b['事实里没有的数']}"])
                if r["check"] is None:
                    err_rows.append(["narrative", g, r["case"], r["rep"], "调用出错", NARR_BY_ID[r["case"]]["q"], "", r["attempts"][0].get("error")])
            seen = set()
            for r in sorted(recs, key=lambda x: (x["case"], x["rep"])):
                if r["case"] in seen or r["check"] is None:
                    continue
                seen.add(r["case"])
                text = scoring._THINK.sub("", r["attempts"][0]["content"])
                for b in r["check"]["bad"]:
                    text = text.replace(b["句子"], f"⚠【{b['句子']}】")
                samples += [f"## {g} · {r['case']}：{NARR_BY_ID[r['case']]['q']}", "", text.strip(), ""]
        (out_dir / "分析段样例.md").write_text("\n".join(samples), encoding="utf-8")
        md += ["", "门槛：含数字的句子里，数字都出自事实的 ≥ 98%。", ""]

    if parts.get("reflect"):
        md += ["## 反思", "", "| 组 | 运行次数 | 选对动作 | 回复解析失败 |", "|---|---|---|---|"]
        by_g = {}
        for r in parts["reflect"]:
            by_g.setdefault(r["group"], []).append(r)
        summary["reflect"] = {}
        for g, recs in by_g.items():
            ok = sum(r["ok"] for r in recs)
            rate = _rate(ok, len(recs))
            summary["reflect"][g] = {"ok": rate}
            md.append(f"| {g} | {len(recs)} | {_fmt(rate)} {_passes(rate, '>=', 0.90)} | {sum(1 for r in recs if r.get('parse_error'))} |")
            for r in recs:
                if not r["ok"]:
                    err_rows.append(["reflect", g, r["case"], r["rep"], "动作不对", REFL_BY_ID[r["case"]]["q"],
                                     "、".join(REFL_BY_ID[r["case"]]["expect"]), r.get("action") or r.get("parse_error") or r["attempts"][0].get("error")])
        md += ["", "门槛：选对动作 ≥ 90%。", ""]

    if parts.get("stats"):
        md += ["## 临时统计", "", "| 组 | 运行次数 | 一次跑对 | 改一次后跑对 |", "|---|---|---|---|"]
        by_g = {}
        for r in parts["stats"]:
            by_g.setdefault(r["group"], []).append(r)
        summary["stats"] = {}
        for g, recs in by_g.items():
            first = _rate(sum(r["first_ok"] for r in recs), len(recs))
            final = _rate(sum(r["final_ok"] for r in recs), len(recs))
            summary["stats"][g] = {"first": first, "final": final}
            md.append(f"| {g} | {len(recs)} | {_fmt(first)} {_passes(first, '>=', 0.70)} | {_fmt(final)} {_passes(final, '>=', 0.85)} |")
            for r in recs:
                if not r["final_ok"]:
                    last = (r.get("results") or [{}])[-1]
                    why = "结果不对" if last.get("ok") else ("脚本出错：" + (last.get("error") or r["attempts"][-1].get("error") or "")[:300])
                    err_rows.append(["stats", g, r["case"], r["rep"], why, TASK_BY_ID[r["case"]]["ask"], "", ""])
        md += ["", "门槛：一次跑对 ≥ 70%，改一次后 ≥ 85%。", ""]

    (out_dir / "汇总.md").write_text("\n".join(md), encoding="utf-8")
    with (out_dir / "错例.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["项", "组", "编号", "第几次", "错在哪", "问句或题目", "期望", "模型给的", "代码处理后（有改动时）"])
        w.writerows(err_rows)
    return summary


# ---------------------------------------------------------------------------
# 自检（不连模型）
# ---------------------------------------------------------------------------


MOCK_BROKEN_PLANS = {c["id"] for c in PLAN_CASES[::20]}
MOCK_THINK_PLANS = {c["id"] for c in PLAN_CASES[3::20]}
MOCK_BROKEN_STATS = "S-02"


def _mock_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "mock-model"}]})
    body = json.loads(request.content)
    part, cid = request.headers.get("x-spike-part"), request.headers.get("x-spike-case")
    # 是不是「改一次」那次调用：消息里已经有模型上一次的回复
    repairing = any(m.get("role") == "assistant" for m in body.get("messages") or [])
    if part == "plan":
        content = json.dumps(scoring.render_expected(PLAN_BY_ID[cid]), ensure_ascii=False)
        if cid in MOCK_BROKEN_PLANS and not repairing:
            content = "<think>先想一想</think>计划如下：{\"steps\": ["  # 坏 JSON，走「改一次」
        elif cid in MOCK_THINK_PLANS:
            content = "<think>用户问的是清单还是统计？{先排除}</think>\n" + content
    elif part == "reflect":
        content = json.dumps({"action": REFL_BY_ID[cid]["expect"][0], "say": "按程序列出的动作处理"}, ensure_ascii=False)
    elif part == "stats":
        content = "```python\n" + TASK_BY_ID[cid]["ref"].strip() + "\n```"
        if cid == MOCK_BROKEN_STATS and not repairing:
            content = "```python\ndef run(data):\n    return 1 / 0\n```"
    else:
        facts = json.dumps(NARR_BY_ID[cid]["facts"], ensure_ascii=False)
        first = re.search(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9])", facts)
        content = f"共找到 {first.group(0) if first else '若干'} 张单。详细情况见上表。"
    if body.get("stream"):
        lines = [f"data: {json.dumps({'choices': [{'delta': {'content': content}}]}, ensure_ascii=False)}",
                 f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})}",
                 "data: [DONE]", ""]
        return httpx.Response(200, content="\n".join(lines).encode("utf-8"), headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def self_check() -> int:
    out_dir = check_out_dir(DEFAULT_OUT_ROOT / "selfcheck")
    assert out_dir is not None
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "raw.jsonl"
    if raw.exists():
        raw.unlink()
    cfg = Cfg(base_url="http://mock/v1", api_key="", model="mock-model", concurrency=8, timeout=30, self_check=True)
    args = argparse.Namespace(parts="plan,narrative,reflect,stats", groups="现状,现状+预匹配,现状+校验,关思考", aux_groups="现状",
                              repeats=2, sub_repeats=2, aux_repeats=1, limit=0)
    transport = httpx.MockTransport(_mock_handler)
    bad = prepare_references(stats_tasks.TASKS)
    if bad:
        print("自检不通过（参考脚本跑不通）：\n- " + "\n- ".join(bad))
        return 1
    asyncio.run(run_jobs(cfg, build_jobs(args), raw, transport))
    summary = write_report(out_dir)
    problems = []
    for g, s in summary["plan"].items():
        if s["all_ok"] != 1.0 or s["json_ok"] != 1.0 or s["consistent"] != 1.0:
            problems.append(f"规划 {g}：全对 {_fmt(s['all_ok'])}，合格 {_fmt(s['json_ok'])}，一致 {_fmt(s['consistent'])}")
        if g == "现状" and not (s["valid_first"] or 0) < 1.0:
            problems.append("规划「改一次」那条路没走到（冒充模型给了坏 JSON，首次合格率却是 100%）")
    st = summary.get("stats", {}).get("现状")
    if st and not (st["first"] or 0) < 1.0:
        problems.append("临时统计「改一次」那条路没走到")
    for part, key in (("narrative", "sentence_ok"), ("reflect", "ok"), ("stats", "final")):
        for g, s in summary.get(part, {}).items():
            if s[key] != 1.0:
                problems.append(f"{part} {g}：{_fmt(s[key])}")
    if problems:
        print("自检不通过（期望冒充模型时应当全对）：\n- " + "\n- ".join(problems))
        print(f"明细见 {out_dir / '错例.csv'}")
        return 1
    counts, problems = offline_checks()
    if problems:
        print("自检不通过（打分该判错的没判错，或该判对的没判对）：\n- " + "\n- ".join(problems[:40]))
        return 1
    print(f"自检通过：对照集 {len(PLAN_CASES)} 条、分析 {len(NARRATIVE_CASES)} 条、反思 {len(REFLECT_CASES)} 条、"
          f"临时统计 {len(stats_tasks.TASKS)} 题，期望冒充模型时全部判对；"
          f"改坏的计划 {counts['neg']} 份全部判错，只改写法的 {counts['harmless']} 份全部判对；"
          f"写分析与临时统计的反例 {counts['aux']} 条全部判错。输出在 {out_dir}")
    return 0


def _perturb(value: Any) -> tuple[Any, bool]:
    """把结果里第一个数字改大 1，用来检验比较函数会判错。"""
    if isinstance(value, bool):
        return value, False
    if isinstance(value, (int, float)):
        return value + 1, True
    if isinstance(value, list):
        out = list(value)
        for i, v in enumerate(out):
            out[i], hit = _perturb(v)
            if hit:
                return out, True
        return out, False
    if isinstance(value, dict):
        out = dict(value)
        for k in out:
            out[k], hit = _perturb(out[k])
            if hit:
                return out, True
        return out, False
    return value, False


def _resolve_checks(counts: dict[str, int]) -> list[str]:
    """代码一侧处理（resolve.py）的几条固定用例。"""
    problems: list[str] = []
    scopes = {"磁卡": "比话题小", "eSIM": "比话题小", "音频（喇叭、蜂鸣器）": "话题本身", "非接相关问题": "话题本身",
              "电池卡扣": "组合说法", "电池鼓包": "比话题小", "外壳开裂": "比话题小", "换料": "清单外"}
    for text, want in scopes.items():
        counts["aux"] += 1
        if resolve.topic_scope(text) != want:
            problems.append(f"话题范围：「{text}」应为{want}，得到{resolve.topic_scope(text)}")

    def agg(sid: str, **params: Any) -> dict:
        return {"id": sid, "skill": "aggregate", "when": None, "params": params}

    t = [{"said": "今年", "basis": "建单"}]
    cases = [
        ("名字改到对得上的一类",
         {"steps": [agg("s1", time=t, filters=[{"field": "跟进人", "op": "属于", "value": ["柯洱斯", "亮亮"]}], group_by=["跟进人"])]},
         lambda p: p["steps"][0]["params"]["filters"][0]["field"] == "加工厂" and p["steps"][0]["params"]["group_by"] == ["加工厂"]),
        ("对得上的不动",
         {"steps": [agg("s1", time=t, filters=[{"field": "跟进人", "op": "是", "value": "李飞"}])]},
         lambda p: p["steps"][0]["params"]["filters"][0]["field"] == "跟进人"),
        ("对比一步、排名一步合成一步",
         {"steps": [agg("s1", time=t, group_by=["机型"], compare={"kind": "对象", "field": "机型", "items": ["A920", "A920PRO"]}),
                    agg("s2", time=t, group_by=["机型"], ranking=True,
                        filters=[{"field": "机型", "op": "属于", "value": ["A920", "A920PRO"]}])]},
         lambda p: len(p["steps"]) == 1),
        ("对象对比统一成筛选加分组",
         {"steps": [agg("s1", time=t, compare={"kind": "对象", "field": "机型", "items": ["A930", "A8900"]})]},
         lambda p: p["steps"][0]["params"].get("compare") is None
         and p["steps"][0]["params"]["group_by"] == ["机型"]
         and p["steps"][0]["params"]["filters"][0]["value"] == ["A930", "A8900"]),
        ("时段对比旧写法补出时间",
         {"steps": [agg("s1", compare={"kind": "时段", "items": ["这个月", "上个月"]})]},
         lambda p: p["steps"][0]["params"]["compare"] == "时段"
         and [x["said"] for x in p["steps"][0]["params"]["time"]] == ["这个月", "上个月"]),
        ("有停线日期时去掉曾经停线",
         {"steps": [agg("s1", time=[{"said": "今年", "basis": "停线"}],
                        filters=[{"field": "状态", "op": "是", "value": "曾经停线"}], group_by=["加工厂"])]},
         lambda p: "filters" not in p["steps"][0]["params"]),
        ("分组不同的不合并",
         {"steps": [agg("s1", time=t, group_by=["问题类型"]), agg("s2", time=t, group_by=["加工厂"])]},
         lambda p: len(p["steps"]) == 2),
        ("合并后引用改指",
         {"steps": [agg("s1", time=t, group_by=["机型"], ranking=True), agg("s2", time=t, group_by=["机型"]),
                    {"id": "s3", "skill": "list_issues", "when": None,
                     "params": {"time": t, "filters": [{"field": "机型", "value": {"ref": "s2.top1"}}]}}]},
         lambda p: len(p["steps"]) == 2 and p["steps"][1]["id"] == "s2"
         and p["steps"][1]["params"]["filters"][0]["value"] == {"ref": "s1.top1"}),
    ]
    for label, plan, ok in cases:
        counts["aux"] += 1
        got = resolve.apply(plan)
        if not ok(got):
            problems.append(f"代码处理「{label}」不对：{json.dumps(got, ensure_ascii=False)[:300]}")

    def lst(sid: str, **params: Any) -> dict:
        return {"id": sid, "skill": "list_issues", "when": None, "params": params}

    def txt(sid: str, **params: Any) -> dict:
        return {"id": sid, "skill": "text_search", "when": None, "params": params}

    with_query = [
        ("「停过线」写成时间改回状态", "再看看里面停过线的",
         {"steps": [lst("s1", time=[{"said": "今年", "basis": "建单", "from": "previous"},
                                     {"said": "停过线", "basis": "停线", "from": "user"}])]},
         lambda p: [x["said"] for x in p["steps"][0]["params"]["time"]] == ["今年"]
         and p["steps"][0]["params"]["filters"][0]["value"] == "曾经停线"),
        ("事件词与日期依据不一致时不改写（交校验打回）", "今年结案了多少单",
         {"steps": [agg("s1", time=[{"said": "今年", "basis": "建单"}], filters=[{"field": "状态", "value": "已结案"}])]},
         lambda p: p["steps"][0]["params"]["time"][0]["basis"] == "建单"),
        ("检索文字里去掉同一步的机型", "国内 A960 煲机时屏幕显示异常，是哪张单？",
         {"steps": [txt("s1", mode="类似问题", phenomenon="A960 煲机时屏幕显示异常",
                        filters=[{"field": "机型", "op": "是", "value": "A960"}])]},
         lambda p: p["steps"][0]["params"]["phenomenon"] == "煲机时屏幕显示异常"),
        ("物料名称不从话题里去掉", "喇叭的问题有哪些",
         {"steps": [txt("s1", mode="话题", topic="喇叭", filters=[{"field": "物料名称", "op": "包含", "value": "喇叭"}])]},
         lambda p: p["steps"][0]["params"]["topic"] == "喇叭"),
        ("「X 各款」按机型包含", "A930 各款去年各有多少问题",
         {"steps": [agg("s1", time=[{"said": "去年"}], filters=[{"field": "系列", "op": "是", "value": "A930"}],
                        group_by=["机型"])]},
         lambda p: p["steps"][0]["params"]["filters"][0] == {"field": "机型", "op": "包含", "value": "A930"}
         and p["steps"][0]["params"]["group_by"] == ["机型"]),
        ("没点名的栏目去掉", "搜一下含USB或打印的问题",
         {"steps": [txt("s1", mode="关键词", terms=["USB", "打印"], logic="或", fields=["问题描述"])]},
         lambda p: "fields" not in p["steps"][0]["params"]),
        ("点名的栏目留着", "搜索描述中有「打印」和「USB」的问题",
         {"steps": [txt("s1", mode="关键词", terms=["打印", "USB"], logic="和", fields=["问题描述"])]},
         lambda p: p["steps"][0]["params"]["fields"] == ["问题描述"]),
        ("安全问题拆成等级与话题两路", "国内有没有电池起火这类安全问题？",
         {"steps": [txt("s1", mode="话题", topic="电池起火", domains={"value": ["国内"], "from": "user"})]},
         lambda p: [s["skill"] for s in p["steps"]] == ["list_issues", "text_search"]
         and p["steps"][0]["params"]["filters"][-1]["value"] == "A+" and p["steps"][1]["params"]["topic"] == "安全"),
        ("明说 A+ 时不拆", "安全问题里 A+ 的单有哪些",
         {"steps": [lst("s1", filters=[{"field": "问题等级", "value": "A+"}])]},
         lambda p: len(p["steps"]) == 1),
    ]
    for label, query, plan, ok in with_query:
        counts["aux"] += 1
        got = resolve.apply(plan, query)
        if not ok(got):
            problems.append(f"代码处理「{label}」不对：{json.dumps(got, ensure_ascii=False)[:300]}")

    # 校验第 13、15 条：期望计划（任一种写法）一律不能被拦（被拦就是误拒）；几种该拦的必须拦下
    for case in PLAN_CASES:
        for k, alt in enumerate(case["expect"]):
            counts["aux"] += 1
            exp = scoring.render_expected({**case, "expect": [alt]})
            errs = resolve.query_checks(resolve.apply(exp, case["q"]), case["q"])
            if errs:
                problems.append(f"校验误拒期望计划 {case['id']}（第 {k + 1} 种写法）：{errs}")
    must_bounce = [
        ("日期依据与事件词不一致", "今年结案了多少单", {"steps": [agg("s1", time=[{"said": "今年", "basis": "建单"}])]}),
        ("两件事的时间写反了", "6 月建单、7 月结案的有几张",
         {"steps": [agg("s1", time=[{"said": "6 月", "basis": "结案"}, {"said": "7 月", "basis": "建单"}])]}),
        ("问句里的机型没进计划", "A960 屏幕闪烁以前有过吗", {"steps": [txt("s1", mode="类似问题", phenomenon="屏幕闪烁")]}),
        ("问句里的问题编号没进计划", "ZC2608038 现在谁在处理", {"steps": [lst("s1")]}),
    ]
    for label, query, plan in must_bounce:
        counts["aux"] += 1
        if not resolve.query_checks(resolve.apply(plan, query), query):
            problems.append(f"校验该拦没拦「{label}」")

    # 校验第 12 条：params 里格式之外的键打回（错层、自造的条件键）；参数层的 from、topic_scope 丢掉不打回
    key_cases = [
        ("参数错层包了一层 params", {"steps": [{"id": "s1", "skill": "list_issues", "when": None, "params": {
            "domains": None, "params": {"domains": {"value": ["国内"], "from": "user"},
                                        "filters": [{"field": "问题类型", "op": "是", "value": "软件问题"}]}}}]}, True),
        ("自造条件键", {"steps": [{"id": "s1", "skill": "list_issues", "when": None,
                              "params": {"status": "未结案"}}]}, True),
        ("参数层的 from 与 topic_scope", {"steps": [{"id": "s1", "skill": "text_search", "when": None, "params": {
            "mode": "话题", "topic": "音频", "from": "user", "topic_scope": "话题本身"}}]}, False),
    ]
    for label, plan, should_reject in key_cases:
        counts["aux"] += 1
        if bool(scoring.validate_plan(plan)) != should_reject:
            problems.append(f"格式校验「{label}」{'该拦没拦' if should_reject else '误拦'}")
    counts["aux"] += 1
    if resolve.query_checks(resolve.apply({"steps": [agg("s1", time=[{"said": "今年", "basis": "建单"}])]}, "今年国内结案的单有多少"),
                            "今年国内结案的单有多少"):
        problems.append("校验误拦「事件词不紧跟时间」")

    # 号码直通：命中的必须恰好是这些问句，且直通出的计划判对
    want_shortcut = {f"M-0{i}" for i in range(1, 10)} | {"CN-042", "CN-048", "CN-059", "BR-010", "XC-012", "V-36", "V-37"}
    got_shortcut = set()
    for case in PLAN_CASES:
        counts["aux"] += 1
        plan = resolve.number_shortcut(case["q"])
        if plan is None:
            continue
        got_shortcut.add(case["id"])
        if not scoring.score_plan(case, plan)["all_ok"]:
            problems.append(f"号码直通「{case['id']}」直通出的计划不对：{json.dumps(plan['steps'], ensure_ascii=False)[:200]}")
    if got_shortcut != want_shortcut:
        problems.append(f"号码直通命中的问句不对：多了 {sorted(got_shortcut - want_shortcut)}，少了 {sorted(want_shortcut - got_shortcut)}")

    import prematch

    pm_checks = [
        ("PN 名称不再报成机型", "A35-000-RD6-00E0 是哪些单的PN", lambda h: len(h) == 1 and "PN 名称" in h[0]),
        ("长的机型名优先", "柯洱斯 A920PRO", lambda h: any("A920PRO" in x for x in h) and not any("「A920」" in x for x in h)),
        ("同名两类都报", "亮亮供应的物料出过哪些问题", lambda h: len(h) == 1 and "供应商" in h[0] and "加工厂" in h[0]),
        ("英文代号要整词", "SPK 异响", lambda h: not h),
        ("部门简称", "工程部跟进的单", lambda h: len(h) == 1 and "生产工程部" in h[0]),
    ]
    for label, query, ok in pm_checks:
        counts["aux"] += 1
        got = prematch.hints(query)
        if not ok(got):
            problems.append(f"预匹配「{label}」不对：{got}")
    return problems


def offline_checks() -> tuple[dict[str, int], list[str]]:
    """不连模型：改坏的计划必须判错、只改写法的必须判对；写分析与临时统计的判定也各做反例。"""
    problems: list[str] = []
    counts = {"neg": 0, "harmless": 0, "aux": 0}
    for case in PLAN_CASES:
        # 改坏的计划不带问句过代码处理：看问句的几条规则会把部分改坏处改回来，那样验不到打分本身
        for label, plan in scoring.mutations(case):
            counts["neg"] += 1
            if scoring.score_plan(case, resolve.apply(plan))["all_ok"]:
                problems.append(f"{case['id']} 改坏「{label}」后仍判对")
        # 只改写法的带问句：同时验证看问句的规则不会把对的计划改错
        for label, plan in scoring.harmless(case):
            counts["harmless"] += 1
            errs = scoring.validate_plan(plan)
            res = scoring.score_plan(case, resolve.apply(plan, case["q"]))
            if errs or not res["all_ok"]:
                wrong = [k for k, v in res["categories"].items() if not v]
                problems.append(f"{case['id']} 只改写法「{label}」却判错：{errs or wrong or res['clarify']}")
    problems += _resolve_checks(counts)
    for case in NARRATIVE_CASES:
        counts["aux"] += 3
        if not check_narrative(case, "共 98765 张单，集中在前几家工厂。")["bad"]:
            problems.append(f"{case['id']} 写分析里编了数没查出来")
        if not check_narrative(case, "其中有九十九张单还没结案。")["bad"]:
            problems.append(f"{case['id']} 写分析里用汉字编了数没查出来")
        if not check_narrative(case, "按 fdefect_rate 排序后看前几张。")["leaks"]:
            problems.append(f"{case['id']} 写分析里露字段名没查出来")
        counts["aux"] += 2
        if check_narrative(case, "前两名之后依次是甲和乙，这两张单最需要关注。")["bad"]:
            problems.append(f"{case['id']} 写分析里名次、指代被误判成编了数")
        if not check_narrative(case, "硬件和结构两类合计 98765 张。")["bad"]:
            problems.append(f"{case['id']} 写分析里「两类」之后编的数没查出来")
        counts["aux"] += 1
        if not check_narrative(case, "最需要关注的是 ZC9909999。")["bad"]:
            problems.append(f"{case['id']} 写分析里编的问题编号没查出来")
    for task in stats_tasks.TASKS:
        want = asyncio.run(reference_result(task))
        bad, hit = _perturb(want)
        counts["aux"] += 1
        if not hit or stats_tasks.results_equal(bad, want):
            problems.append(f"{task['id']} 临时统计结果改了一个数仍判对")
    return counts, problems


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="规划器实测：规划、写分析、反思、临时统计")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true", help="不连模型，用期望冒充模型检验打分")
    mode.add_argument("--smoke", action="store_true", help="冒烟：每组跑几条，看连通、思考与耗时")
    mode.add_argument("--run", action="store_true", help="全量实测")
    mode.add_argument("--report", action="store_true", help="只按 --out 目录里的 raw.jsonl 重出汇总")
    ap.add_argument("--confirm-local", action="store_true", help="确认 FI_LLM_BASE_URL 是内网本地模型服务")
    ap.add_argument("--out", type=Path, help="输出目录，默认 runtime/planner_spike/<日期>-<提示词版本>")
    ap.add_argument("--parts", default="plan,narrative,reflect,stats")
    ap.add_argument("--groups", default="现状,关思考,思考low,推荐采样", help="规划跑哪几组；第一组跑全部问句，其余只跑 core")
    ap.add_argument("--aux-groups", default="现状,关思考", help="写分析、反思、临时统计跑哪几组")
    ap.add_argument("--repeats", type=int, default=5, help="第一组每条问句跑几次")
    ap.add_argument("--sub-repeats", type=int, default=3, help="其余各组每条 core 问句跑几次")
    ap.add_argument("--aux-repeats", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="每项只取前 N 条（试跑用）")
    ap.add_argument("--concurrency", type=int, default=2, help="同时发几个请求；耗时按这个负载量")
    ap.add_argument("--timeout", type=float, default=LLM_TIMEOUT, help="单次调用超时秒数，默认同线上 120")
    args = ap.parse_args(argv)

    if args.self_check:
        return self_check()

    out_dir = check_out_dir(args.out or DEFAULT_OUT_ROOT / f"{dt.date.today():%Y%m%d}-{prompts.PROMPT_VERSION}")
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
        print(f"会把问句与合成数据发给 {base}。确认这是内网本地模型服务后加 --confirm-local 再运行。", file=sys.stderr)
        return 2
    # 并发与超时不读 .env 里话题标注用的 FI_LLM_CONCURRENCY / FI_LLM_TIMEOUT：这里量的是线上设置下的耗时
    cfg = Cfg(base_url=base, api_key=os.environ.get("FI_LLM_API_KEY", ""), model=os.environ["FI_LLM_MODEL"],
              concurrency=args.concurrency, timeout=args.timeout)
    # 续跑按「问句 + 组 + 第几次」认已完成的项，不认模型：换了模型还写进同一目录，新旧结果会混在一起
    info_path = out_dir / "run_info.json"
    if info_path.exists():
        old = json.loads(info_path.read_text(encoding="utf-8"))
        if (old.get("model"), old.get("prompt")) != (cfg.model, prompts.PROMPT_VERSION):
            print(f"{out_dir} 里是模型 {old.get('model')}、提示词 {old.get('prompt')} 的结果，"
                  f"本次是 {cfg.model}、{prompts.PROMPT_VERSION}。请用 --out 指一个新目录。", file=sys.stderr)
            return 2
    models = asyncio.run(fetch_models(cfg))
    (out_dir / "run_info.json").write_text(json.dumps(
        {"models": models, "model": cfg.model, "concurrency": cfg.concurrency, "timeout": cfg.timeout,
         "groups": args.groups, "aux_groups": args.aux_groups, "prompt": prompts.PROMPT_VERSION},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"模型服务：{json.dumps(models, ensure_ascii=False)}", flush=True)

    if args.smoke:
        smoke_ids = ["CN-001", "XC-022", "V-14"]
        jobs = [("plan", cid, g, 0) for g in args.groups.split(",") for cid in smoke_ids]
        jobs += [("narrative", "N-02", g, 0) for g in args.groups.split(",")]
        smoke_dir = out_dir / "smoke"
        smoke_dir.mkdir(exist_ok=True)
        asyncio.run(run_jobs(cfg, jobs, smoke_dir / "raw.jsonl"))
        write_smoke(smoke_dir, build_jobs(args), cfg.concurrency)
        print(f"冒烟完成：{smoke_dir / '冒烟.md'}")
        return 0

    if "stats" in args.parts.split(","):
        print("先在本机沙箱里算临时统计的参考结果……", flush=True)
        bad = prepare_references(stats_tasks.TASKS[: args.limit or None])
        if bad:
            print("参考脚本跑不通，还没调模型就停下了：\n- " + "\n- ".join(bad), file=sys.stderr)
            print("可以先加 --parts plan,narrative,reflect 跑其余三项，再把上面的报错发回。", file=sys.stderr)
            return 1
    asyncio.run(run_jobs(cfg, build_jobs(args), out_dir / "raw.jsonl"))
    write_report(out_dir)
    print(f"完成：{out_dir / '汇总.md'}、{out_dir / '错例.csv'}")
    return 0


def _smoke_estimate(raw: list[dict], full_jobs: list[tuple[str, str, str, int]], concurrency: int) -> list[str]:
    """按冒烟里每组的平均耗时，估算同样参数跑 --run 要多久。反思、临时统计没冒烟，借用同组规划的耗时。"""
    lat: dict[tuple[str, str], list[float]] = {}
    rejected: set[str] = set()
    for r in raw:
        a = r["attempts"][0]
        if a.get("error"):
            if str(a["error"]).startswith("HTTP 4"):
                rejected.add(r["group"])
            continue
        if a.get("latency") is not None:
            lat.setdefault((r["part"], r["group"]), []).append(sum(x.get("latency") or 0 for x in r["attempts"]))
    count: dict[tuple[str, str], int] = {}
    for part, _cid, group, _rep in full_jobs:
        count[(part, group)] = count.get((part, group), 0) + 1
    lines = ["", "## 按冒烟耗时估算全量用时", "",
             f"按本次命令行的 --groups、--aux-groups、--repeats 等参数与并发 {concurrency} 估算；反思、临时统计借用同组规划的耗时，只是量级。", "",
             "| 组 | 项 | 次数 | 每次约（秒） | 约需（分钟） |", "|---|---|---|---|---|"]
    total = 0.0
    for (part, group), n in sorted(count.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        src = lat.get((part, group)) or lat.get(("plan", group))
        if group in rejected or not src:
            lines.append(f"| {group} | {part} | {n} | — | 冒烟时请求被拒或出错，建议从 --groups / --aux-groups 去掉 |")
            continue
        each = statistics.mean(src)
        minutes = n * each / max(concurrency, 1) / 60
        total += minutes
        lines.append(f"| {group} | {part} | {n} | {each:.1f} | {minutes:.0f} |")
    lines += ["", f"合计约 {total / 60:.1f} 小时（不含失败重试与「改一次」的额外调用）。"]
    return lines


def write_smoke(out_dir: Path, full_jobs: list[tuple[str, str, str, int]] | None = None, concurrency: int = 2) -> None:
    raw = list(load_raw(out_dir / "raw.jsonl").values())
    md = ["# 冒烟", "", "每组跑 3 条规划、1 条写分析。只有状态、耗时、token 与是否带思考，可以发回。", "",
          "| 组 | 项 | 编号 | 结果 | 耗时（秒） | 首字（秒） | 输入 / 输出 token | 思考字数 | 正文含 <think> | 结束原因 | 计划合格 | 计划全对 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(raw, key=lambda x: (x["group"], x["part"], x["case"])):
        a = r["attempts"][0]
        u = a.get("usage") or {}
        ok_plan = full = "—"
        if r["part"] == "plan":
            ok_plan = "是" if r.get("plan") is not None else "否"
            full = "是" if r.get("plan") is not None and scoring.score_plan(
                PLAN_BY_ID[r["case"]], resolve.apply(r["plan"], PLAN_BY_ID[r["case"]]["q"]))["all_ok"] else "否"
        md.append(f"| {r['group']} | {r['part']} | {r['case']} | {a.get('error') or 'ok'} | {_fmt(a.get('latency'), False)} | "
                  f"{_fmt(a.get('ttft'), False)} | {u.get('prompt_tokens', '—')} / {u.get('completion_tokens', '—')} | "
                  f"{a.get('reasoning_chars', 0)} | {'是' if a.get('think_in_content') else '否'} | {a.get('finish_reason')} | {ok_plan} | {full} |")
    if full_jobs:
        md += _smoke_estimate(raw, full_jobs, concurrency)
    (out_dir / "冒烟.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
