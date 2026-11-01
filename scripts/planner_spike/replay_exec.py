"""把对照集一次运行里模型给的计划逐条交给执行层，找出「对照集判对、执行层却追问」的（设计 §19「S3 提交后
golden 实测补的」：CN-025、BR-004 都是这样漏到 golden 的）。

spike 只给计划打分、不执行；这里接着往下走一步：用 `tests/` 的假 `ctx`、假连接器与假数据（`tests/s3_data.py`，
单号年份 99 的合成数据）跑 `handle()`，不连库、不调模型，分析段用回放的固定句子。

- 只看与库里取值无关的追问：类型、取值、状态、等级对不上。这几类出现一条就退出码 1。
- 名字对不上（机型、工厂、人员、供应商、部门、系列）受假数据影响，只列出、不判。
- 期望本来就是追问的、带上文的多轮条跳过。
- 写成临时统计的计划（S7 起执行层接上）：模型写脚本那一次用一份固定脚本顶上（`FIXED_SCRIPT`），只看执行层认不认得。

用法（仓库根目录）：

    uv run python scripts/planner_spike/replay_exec.py                     # 最近一次有计划的运行
    uv run python scripts/planner_spike/replay_exec.py --raw runtime/planner_spike/<运行>/raw.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import s3_data  # noqa: E402
import scopes  # noqa: E402
from fakes import make_harness, run  # noqa: E402
from forge_core.events import EventType  # noqa: E402

from factory_issue_module.skills import custom_stats  # noqa: E402

#: 与库里取值无关的追问原因（`domains/*.py` 里 `Ask(reason=…)`）：出现即执行层没认出对照集判对的写法
VALUE_REASONS = ("类型对不上", "取值对不上", "状态对不上", "等级对不上")
NARRATIVE = "共 1 张。"
#: 写成临时统计的计划（V-32 等）在执行层要模型写脚本：这里给一份固定的（按所属域计数），只看执行层认不认得计划，
#: 不看脚本写得对不对（那是 spike 临时统计一项量的）
FIXED_SCRIPT = '''```python
def run(data):
    df = data["issues"]
    counts = df["所属域"].value_counts()
    rows = [[k, int(v)] for k, v in counts.items()]
    return {"columns": ["所属域", "单数"], "rows": rows, "chart": {"type": "bar", "x": "所属域", "series": ["单数"]}}
```'''


def _latest_raw() -> Path | None:
    """最近一次（按文件时间）有计划的运行。自检的输出不算：那里的计划是代码按期望拼的，不是模型写的。"""
    runs = sorted((p for p in (ROOT / "runtime" / "planner_spike").glob("*/raw.jsonl")
                   if not p.parent.name.startswith("selfcheck")), key=lambda p: p.stat().st_mtime)
    for raw in reversed(runs):
        if '"part": "plan"' in raw.read_text(encoding="utf-8")[:200_000]:
            return raw
    return None


def _cases() -> dict[str, dict]:
    data = json.loads((HERE / "cases" / "plan_cases.json").read_text(encoding="utf-8"))
    items = data["cases"] if isinstance(data, dict) else data
    return {c["id"]: c for c in items}


def _skip(case: dict) -> bool:
    return "clarify" in json.dumps(case.get("expect"), ensure_ascii=False) or bool(case.get("history"))


async def _one(query: str, plan: dict) -> tuple[str, str] | None:
    h = make_harness(scopes.GREEN, llm_replies=[plan] + [NARRATIVE] * 12)
    s3_data.load(h)
    h.llm.routes[custom_stats.ROUTE_MARKER] = lambda _m: FIXED_SCRIPT
    try:
        events = await run(h, query)
    except Exception as exc:  # noqa: BLE001 —— 执行层抛异常本身就是要报的
        return "异常", type(exc).__name__
    first = events[0] if events else None
    if first is None or first.type is not EventType.CLARIFY:
        return None
    recs = first.data.get("recommendations") or []
    return str(recs[0].get("name") if recs else "名字对不上"), str(first.data.get("question"))[:160]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, help="对照集一次运行的 raw.jsonl；不给就用最近一次有计划的运行")
    args = ap.parse_args()
    raw = args.raw or _latest_raw()
    if raw is None or not raw.exists():
        print("没有找到对照集运行的 raw.jsonl", file=sys.stderr)
        return 2
    cases, seen = _cases(), set()
    found: dict[str, list[str]] = defaultdict(list)
    for line in raw.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        cid = rec.get("case")
        if rec.get("part") != "plan" or cid in seen or cid not in cases or not rec.get("plan"):
            continue
        seen.add(cid)
        if _skip(cases[cid]):
            continue
        got = await _one(cases[cid]["q"], rec["plan"])
        if got is not None:
            found[got[0]].append(f"{cid}｜{cases[cid]['q'][:60]}｜{got[1]}")
    bad = [r for r in found if r in VALUE_REASONS or r == "异常"]
    print(f"运行：{raw.parent.name}；看过 {len(seen)} 条")
    for reason in sorted(found, key=lambda r: (r not in bad, r)):
        tag = "要修" if reason in bad else "只列出（受假数据影响或本该追问）"
        print(f"\n## {reason}（{len(found[reason])}，{tag}）")
        for item in found[reason]:
            print("-", item)
    print("\n结论：" + ("执行层没认出的写法见上面「要修」各节" if bad else "没有对照集判对、执行层却追问的取值"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
