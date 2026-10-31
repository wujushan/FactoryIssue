"""治理任务：把三域的叙述文字整理进 mart（设计 §12；G2「同步策略」「上线首轮核对」）。

`sync_issue_text`（每 30 分钟，按指纹增量）与 `rebuild_issue_text`（每天凌晨，全量）共用这一条流水线，区别只在
第 3 步挑哪些单。三域依次处理，每域：

1. 建表并核对列（`jobs/ddl.py`）；
2. 在源库算每单指纹（`jobs/fingerprint.py`）；
3. 挑单：增量取新增与指纹变了的单，全量取全部未删除的单；源上已删除或不存在的单单独列出；
4. 按单分批读原文（`jobs/read.py`）；
5. 清洗与整理（`jobs/clean.py`、`jobs/steps.py`）；
6. 分段（`jobs/segment.py`）；
7. 写入，每批一条语句（`jobs/write.py`）；最后删掉已删除的单；
8. 每批报进度，结束时最后一次进度与一条结构化日志 `factory_issue_text_sync_stats` 写出各项计数与耗时（只有计数）。

句柄都在 `run(ctx)` 里从 `JobContext` 取（`ctx.etl.read/write`、`ctx.config`），不在 `jobs()` 里预绑，不自己连库。
`ctx.etl` 是系统级句柄、不受权限过滤；mart 表没有权限承载列（G2「权限承载列清单」）。取数与写入是同步调用，
放进线程里跑，免得挡住 jobs worker 上同时到点的其他任务。治理任务里不调模型。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog
from forge_core.jobs import JobBinding, JobContext, JobSpec

from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import INFO, MART, SEGMENTATION
from factory_issue_module.jobs import ddl, fingerprint, read, segment, steps, write
from factory_issue_module.jobs.clean import clean, is_short
from factory_issue_module.jobs.spec import COST_COLUMN, PHEN_COLUMN, SOURCES, STEP_COLUMNS, DomainSource
from factory_issue_module.jobs.steps import StepText, as_int, as_text
from factory_issue_module.textnorm import phen_parts

logger = structlog.get_logger(__name__)

SYNC = JobSpec(
    name="sync_issue_text",
    description="按指纹增量整理三域叙述文字进产物库（文字表、分段表、按意思找的段表），供按文字找单",
    default_cron="*/30 * * * *",
)
REBUILD = JobSpec(
    name="rebuild_issue_text",
    description="全量重建三域叙述文字（兜底指纹漏判；改了分段规则后手动跑一次）",
    default_cron="30 2 * * *",
)
_PHEN_SEP = "；"


def bindings() -> list[JobBinding]:
    async def _sync(ctx: JobContext) -> None:
        await run(ctx, full=False)

    async def _rebuild(ctx: JobContext) -> None:
        await run(ctx, full=True)

    return [JobBinding(spec=SYNC, run=_sync), JobBinding(spec=REBUILD, run=_rebuild)]


# ---------------------------------------------------------------- 统计


@dataclass
class DomainStats:
    issues: int = 0
    pulled: int = 0
    removed: int = 0
    seg_rows: int = 0
    vseg_rows: int = 0
    chars_raw: int = 0
    chars_clean: int = 0
    with_inline_images: int = 0
    empty_text: int = 0
    no_vseg: int = 0
    name_prefix: dict[str, list[int]] = field(default_factory=dict)
    outside_steps: set[str] = field(default_factory=set)
    ms: dict[str, int] = field(default_factory=dict)

    def timed(self, stage: str, started: float) -> None:
        self.ms[stage] = self.ms.get(stage, 0) + int((time.perf_counter() - started) * 1000)

    def as_log(self) -> dict[str, Any]:
        return {
            "issues": self.issues, "pulled": self.pulled, "removed": self.removed,
            "seg_rows": self.seg_rows, "vseg_rows": self.vseg_rows,
            "chars_raw": self.chars_raw, "chars_clean": self.chars_clean,
            "with_inline_images": self.with_inline_images, "empty_text": self.empty_text,
            "no_vseg": self.no_vseg, "name_prefix": self.name_prefix,
            "outside_steps": sorted(self.outside_steps), "ms": self.ms,
        }

    def line(self, label: str) -> str:
        """任务页上的一段摘要：G2「上线首轮核对」的各项都有，去人名前缀与耗时只给合计（逐环节、逐步在日志里）。"""
        cut = sum(c for c, _ in self.name_prefix.values())
        seen = sum(c + k for c, k in self.name_prefix.values())
        parts = [f"{label} 单{self.issues}", f"整理{self.pulled}", f"段{self.seg_rows}/{self.vseg_rows}",
                 f"字{_short_number(self.chars_raw)}→{_short_number(self.chars_clean)}"]
        # 为 0 的几项不写，省出字数（任务页那一列只有 256 字）；日志里照记 0
        optional = (("删", self.removed), ("空", self.empty_text), ("无向量", self.no_vseg),
                    ("含图", self.with_inline_images), ("清单外", len(self.outside_steps)))
        parts += [f"{name}{n}" for name, n in optional if n]
        if seen:
            parts.append(f"去姓名{cut}/{seen}")
        parts.append(f"{sum(self.ms.values()) / 1000:.0f}秒")
        return " ".join(parts)


#: Console 任务页的进度句存进一个 256 字的列（platform 0.3.7 `job_queue.MAX_PROGRESS_MESSAGE_CHARS`），超出截掉
PROGRESS_MESSAGE_MAX = 256
STATS_EVENT = "factory_issue_text_sync_stats"


def _short_number(n: int) -> str:
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.0f}万"
    return str(n)


def summary(stats: Mapping[str, DomainStats]) -> str:
    """最后一次进度的句子：先写明细在哪条日志（截断时也留得住），再按域给摘要。"""
    labels = {s.domain.value: s.domain.label for s in SOURCES}
    body = "；".join(stats[d].line(labels[d]) for d in labels if d in stats)
    text = f"明细见日志 {STATS_EVENT}｜{body}"
    # 照本助手的数据量（国内约 2,500 张、巴西约 200 张、海外十几张）放得下；放不下时自己截、写明截了，
    # 不让平台从中间静默截掉。日志那条总是全的。
    return text if len(text) <= PROGRESS_MESSAGE_MAX else text[: PROGRESS_MESSAGE_MAX - 1] + "…"


# ---------------------------------------------------------------- 一张单


@dataclass
class Built:
    text_row: dict[str, Any]
    seg_rows: list[dict[str, Any]]
    vseg_rows: list[dict[str, Any]]
    chars_raw: int = 0
    has_images: bool = False
    steps: StepText | None = None


def _rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None or len(frame) == 0:
        return []
    return frame.to_dict("records")


def _by_issue(frame: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in _rows(frame):
        pid = as_int(r.get("issue_id"))
        if pid is not None:
            out.setdefault(str(pid), []).append(r)
    return out


def _by_id(rows: list[dict[str, Any]], col: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: as_int(r.get(col)) or 0)


class _Raw:
    """记下本单原文的字符数、有没有内嵌图片（统计行用）。"""

    def __init__(self) -> None:
        self.chars = 0
        self.images = False

    def take(self, value: Any) -> Any:
        text = as_text(value)
        self.chars += len(text)
        self.images = self.images or "data:image" in text.lower()
        return value


def build_issue(
    spec: DomainSource,
    iid: str,
    main: Mapping[str, Any],
    subs: Mapping[str, list[dict[str, Any]]],
    names: Mapping[int, str],
    cfg: Any,
    print_: fingerprint.Print,
) -> Built:
    """一张单 → 文字表一行、分段表与按意思找的段表的行。"""
    raw = _Raw()
    cols: dict[str, str] = {c: "" for c in spec.text_columns()}
    for col, src in spec.main:
        cols[col] = clean(raw.take(main.get(src)))
    manual_phen = ""
    if spec.phen_json:
        parts = phen_parts(raw.take(main.get(spec.phen_json)), spec.phen_style or "")
        cols[PHEN_COLUMN] = _PHEN_SEP.join(seg for seg, _ in parts)
        manual_phen = _PHEN_SEP.join(seg for seg, manual in parts if manual and seg)
    if spec.phen_rows is not None:
        r = spec.phen_rows
        seen, texts = set(), []
        for row in _by_id(subs.get("phen", []), r.id_col):
            key = as_int(row.get(r.key_col))
            if key is None or key in seen:
                continue
            seen.add(key)
            text = clean(raw.take(row.get(r.master_text)))
            if text:
                texts.append(text)
        cols[PHEN_COLUMN] = _PHEN_SEP.join(texts)
    if spec.process is not None:
        rows = _by_id(subs.get("process", []), spec.process.id_col)
        latest = rows[-1] if rows else {}
        for col, src in spec.process.columns:
            cols[col] = clean(raw.take(latest.get(src)))
    if spec.cost is not None:
        c = spec.cost
        lines = []
        for row in _by_id(subs.get("cost", []), c.id_col):
            memo = clean(raw.take(row.get(c.memo_col)))
            if memo:
                kind = as_text(row.get(c.type_col))
                lines.append(f"{kind}：{memo}" if kind else memo)
        cols[COST_COLUMN] = "\n".join(lines)
    st: StepText | None = None
    if spec.steps is not None:
        s = spec.steps
        rows = subs.get("steps", [])
        # 清洗前的字数与含图只数真正整理进文字表的那几条（每个环节最新一条），同一环节的旧记录不算（S6a 评审 A3）
        for row in steps.latest(rows, s):
            for col in (s.result_col, s.opinion_col, s.content_col):
                raw.take(row.get(col))
        keys = cfg.domestic_codes if isinstance(s.factory_key, int) else cfg.overseas_names
        st = steps.build(rows, s, keys, names)
        cols[STEP_COLUMNS[0]], cols[STEP_COLUMNS[1]], cols[STEP_COLUMNS[2]] = st.result, st.opinion, st.content

    fields = spec.seg_fields()
    seg_texts, vseg_texts = {}, {}
    for code in fields:
        if code == "step":
            seg_texts[code] = st.analysis_text() if st else ""
            vseg_texts[code] = "\n".join(h + b for h, b in (st.entries if st else []) if not is_short(b))
            continue
        text = cols[f"f_{code}"]
        seg_texts[code] = text
        if code == "phen":
            text = manual_phen  # 预设的现象只按词找；国内的问题现象全部不参与按意思找（总述「比对范围」）
        vseg_texts[code] = "" if is_short(text) else text
    text_row = {"issue_id": iid, "issue_no": print_.issue_no or as_text(main.get("issue_no")), **cols,
                "text_fingerprint": print_.fingerprint}
    return Built(
        text_row=text_row,
        seg_rows=segment.seg_rows(iid, seg_texts, fields),
        vseg_rows=segment.vseg_rows(iid, vseg_texts, fields, cfg),
        chars_raw=raw.chars,
        has_images=raw.images,
        steps=st,
    )


# ---------------------------------------------------------------- 流水线


async def _call(fn: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.to_thread(fn, *args)


async def _names(info: Any, subs: Mapping[str, list[dict[str, Any]]], spec: DomainSource) -> dict[int, str]:
    """本批处理步骤操作人的姓名（去人名前缀用）。"""
    if spec.steps is None:
        return {}
    users = [as_int(r.get(spec.steps.user_col)) for r in subs.get("steps", [])]
    out: dict[int, str] = {}
    for sql, params in read.employee_sqls(u for u in users if u is not None):
        for r in _rows(await _call(info.query, sql, params)):
            uid, name = as_int(r.get("ID")), as_text(r.get("Name"))
            if uid is not None and name:
                out[uid] = name
    return out


async def _sync_domain(ctx: JobContext, spec: DomainSource, cfg: Any, info: Any, mart: Any, writer: Any,
                       *, full: bool) -> DomainStats:
    stats = DomainStats()
    label = spec.domain.label

    started = time.perf_counter()
    await _call(ddl.ensure, spec, writer, mart)
    stats.timed("ddl", started)

    started = time.perf_counter()
    main_fp = await _call(info.query, fingerprint.main_sql(spec), {})
    subs_fp = {name: await _call(info.query, sql, {}) for name, sql in fingerprint.sub_sqls(spec).items()}
    prints = fingerprint.combine(main_fp, subs_fp)
    existing = {as_text(r.get("issue_id")): as_text(r.get("text_fingerprint"))
                for r in _rows(await _call(mart.query, f"SELECT issue_id, text_fingerprint FROM {spec.domain.text_table}", {}))}
    stats.timed("fingerprint", started)

    todo = sorted(prints) if full else [i for i, p in prints.items() if existing.get(i) != p.fingerprint]
    removed = sorted(set(existing) - set(prints))
    stats.issues, stats.pulled, stats.removed = len(prints), len(todo), len(removed)

    done = 0
    for batch in read.batches(todo, {i: p.size for i, p in prints.items()}):
        ids = [int(i) for i in batch]
        started = time.perf_counter()
        sql, params = read.main_sql(spec, ids)
        mains = {str(as_int(r.get("issue_id"))): r for r in _rows(await _call(info.query, sql, params))}
        subs = {name: _by_issue(await _call(info.query, q, p)) for name, (q, p) in read.sub_sqls(spec, ids).items()}
        flat = {name: [r for rows in by.values() for r in rows] for name, by in subs.items()}
        names = await _names(info, flat, spec)
        stats.timed("read", started)

        started = time.perf_counter()
        built = []
        for iid in batch:
            if iid not in mains:
                continue  # 读原文之前刚被删掉：下一轮按「已删除」处理
            one = build_issue(spec, iid, mains[iid], {n: by.get(iid, []) for n, by in subs.items()},
                              names, cfg, prints[iid])
            built.append(one)
            stats.seg_rows += len(one.seg_rows)
            stats.vseg_rows += len(one.vseg_rows)
            stats.chars_raw += one.chars_raw
            stats.chars_clean += sum(len(one.text_row[c]) for c in spec.text_columns())
            stats.with_inline_images += int(one.has_images)
            stats.empty_text += int(not one.seg_rows)
            stats.no_vseg += int(not one.vseg_rows)
            if one.steps is not None:
                stats.outside_steps |= one.steps.outside
                for step, (cut, kept) in one.steps.prefix.items():
                    pair = stats.name_prefix.setdefault(step, [0, 0])
                    pair[0] += cut
                    pair[1] += kept
        stats.timed("clean", started)

        if built:
            started = time.perf_counter()
            params = write.upsert_params([b.text_row for b in built], [r for b in built for r in b.seg_rows],
                                         [r for b in built for r in b.vseg_rows])
            await _call(writer.execute, write.upsert_sql(spec), params)
            stats.timed("write", started)
        done += len(batch)
        ctx.progress(done, len(todo), f"{label}：整理叙述文字")

    if removed:
        started = time.perf_counter()
        await _call(writer.execute, write.delete_sql(spec), write.delete_params(removed))
        stats.timed("write", started)
    return stats


async def run(ctx: JobContext, *, full: bool) -> dict[str, DomainStats]:
    cfg = await config_files.load(ctx, SEGMENTATION)
    info, mart, writer = ctx.etl.read(INFO), ctx.etl.read(MART), ctx.etl.write(MART)
    out: dict[str, DomainStats] = {}
    for spec in SOURCES:
        out[spec.domain.value] = await _sync_domain(ctx, spec, cfg, info, mart, writer, full=full)
    total = sum(s.pulled for s in out.values())
    ctx.progress(total, total, summary(out))
    logger.info(
        STATS_EVENT,
        mode="rebuild" if full else "sync",
        rule=cfg.rule,
        **{domain: stats.as_log() for domain, stats in out.items()},
    )
    return out
