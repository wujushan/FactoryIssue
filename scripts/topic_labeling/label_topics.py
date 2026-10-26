"""离线评测工具：用本地大模型给全部制程问题单打话题标签，并与说法清单的按词结果对照。

不是模块代码，`src/` 不引用它。只在内网运行，只允许连内网的本地模型服务（OpenAI 兼容接口）。
用法与输出见同目录 README.md。

一张单的处理：
1. 从正式镜像库取比对范围内的文字，剥图片与 HTML（与探测 T4 同一套 SQL）。
2. 按 docs/2_landed/topic_terms.md 的说法清单按词匹配，给每个话题分组（1 问题本身涉及 / 2 处理中提到 /
   3 待判断 / 4 带＊说法只在第二组栏目 / - 未命中），规则与线上口径一致。
3. 把单上文字交本地模型，判断它与 14 个话题各是什么关系（问题本身 / 顺带提到 / 无关）。
4. 两边对照，输出汇总、说法精度、抽查清单与应命中集草稿。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
TOPIC_TERMS_MD = ROOT / "docs" / "2_landed" / "topic_terms.md"
DEFAULT_OUT_ROOT = ROOT / "runtime" / "topic_labeling"

RELATIONS = ("问题本身", "顺带提到", "无关")
_REL_RANK = {"问题本身": 0, "顺带提到": 1, "无关": 2}
# 提示词版本。v1：14 个话题自由输出，模型常把次要话题整个漏掉（T4 对照里人工判是、模型没输出的有 4 张）。
# v2：把文字里出现过说法的话题列给模型，要求逐个给出判断，其余话题照常可补。换版本后旧结果自动作废、重标。
PROMPT_VERSION = "v2"
GROUP_NAMES = {
    "1": "1 问题本身涉及",
    "2": "2 处理中提到",
    "3": "3 待判断",
    "4": "4 带＊说法只在第二组栏目",
    "-": "- 未命中",
}
EVIDENCE_MAX = 12

# 探测 T4 人工判定的更正（业务方 2026-10-24 复核：两张单是外观上的鼓包，不是电池鼓包安全问题）
T4_OVERRIDES = {
    ("CN-045", "ZC2508042"): "不是",
    ("CN-045", "ZC2508043"): "不是",
}
# 探测 T4 的案例对应哪个话题；CN-056（只按漏电找）不是整个话题，不参与对照
T4_CASE_TOPIC = {"CN-039": "音频", "CN-045": "安全", "CN-055、XC-031": "非接", "XC-031": "非接"}

# ---------------------------------------------------------------------------
# 取数 SQL（PostgreSQL 正式镜像库 ai-info，schema public；只读）
# ---------------------------------------------------------------------------

BASE_SQL = """
SELECT '国内' AS dom, m."ID"::text AS pid, m."Numbers"::text AS no, m."AddDate"::date AS add_date
FROM "ZCTracking_ProblemList" m
WHERE COALESCE(m."IsDelete"::int, 0) <> 1
UNION ALL
SELECT '巴西', b."ID"::text, b."OrderNumber"::text, b."AddDate"::date
FROM "BrazilProblemList" b
WHERE b."Status"::int <> -1
UNION ALL
SELECT '海外', o."Id"::text, o."Numbers"::text, o."AddDate"::date
FROM "OverseasProblemDetail" o
WHERE COALESCE(o."IsDelete"::int, 0) = 0
"""

TEXT_SQL = """
WITH base AS (
""" + BASE_SQL + """
),
src AS (
    SELECT '国内' AS dom, m."ID"::text AS pid, c.grp, c.col, c.x
    FROM "ZCTracking_ProblemList" m
    CROSS JOIN LATERAL (VALUES
        (1, '问题描述', m."ProblemDesc"::text), (1, '原因分析', m."Reason"::text),
        (2, '改善建议', m."Improve"::text), (2, '改善措施', m."Measures"::text),
        (2, '预防对策', m."Prevention"::text)
    ) AS c(grp, col, x)
    UNION ALL
    SELECT '国内', r."ProblemId"::text, 1, '问题现象', string_agg(DISTINCT p."PhenomenonDesc"::text, '；')
    FROM "ZCTracking_CheckReason" r
    JOIN "AfterSaleIssueClassPhenomenon" p ON p."ID" = r."PhenomenonID"
    GROUP BY r."ProblemId"
    UNION ALL
    SELECT '国内', s."ProblemId"::text, 2,
        '处理步骤·' || CASE s."Step"::int
            WHEN 3 THEN '责任人确认' WHEN 4 THEN '工程确认' WHEN 6 THEN '工厂制程分析'
            WHEN 10 THEN 'SQE跟进' WHEN 11 THEN '设计变更' WHEN 13 THEN '设计变更后SQE确认'
            WHEN 14 THEN 'IQC意见' WHEN 35 THEN '预防对策确认' END,
        c.x
    FROM (SELECT x.*, row_number() OVER (PARTITION BY x."ProblemId", x."Step"::int ORDER BY x."ID" DESC) AS rn
          FROM "ZCTracking_ProblemSteplog" x
          WHERE x."Step"::int IN (3, 4, 6, 10, 11, 13, 14, 35)) s
    CROSS JOIN LATERAL (VALUES
        (s."Opinon"::text), (s."Measures"::text),
        (CASE WHEN s."Step"::int = 6 THEN s."Result"::text END)
    ) AS c(x)
    WHERE s.rn = 1
    UNION ALL
    SELECT '巴西', b."ID"::text, c.grp, c.col, c.x
    FROM "BrazilProblemList" b
    LEFT JOIN LATERAL (SELECT p."DisposeResult", p."ReasonAnalysis", p."ImprovementMeasure", p."PrecautionPolicy"
                       FROM "BrazilProblemProcess" p
                       WHERE p."ProblemID" = b."ID"
                       ORDER BY p."ID" DESC
                       LIMIT 1) lp ON true
    CROSS JOIN LATERAL (VALUES
        (1, '问题现象', (SELECT string_agg(mm[1], '；')
                        FROM regexp_matches(COALESCE(b."ProblemPhenomenon"::text, ''),
                             '"(?:Value|parentType|otherVal)"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"', 'g') AS mm)),
        (1, '问题描述', b."ProblemDesc"::text),
        (1, '原因分析', lp."ReasonAnalysis"::text),
        (2, '改善措施', lp."ImprovementMeasure"::text),
        (2, '预防对策', lp."PrecautionPolicy"::text),
        (2, 'SQE跟进结果', lp."DisposeResult"::text)
    ) AS c(grp, col, x)
    UNION ALL
    SELECT '海外', o."Id"::text, c.grp, c.col, c.x
    FROM "OverseasProblemDetail" o
    CROSS JOIN LATERAL (VALUES
        (1, '已选问题现象', (SELECT string_agg(mm[1], '；')
                            FROM regexp_matches(COALESCE(o."hasCheckedPhenomenon"::text, ''),
                                 '"(?:Value|parentType|otherVal)"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"', 'g') AS mm)),
        (1, '问题描述', o."ProblemDesc"::text),
        (1, '原因分析', o."Reason"::text),
        (2, '改善建议', o."Improve"::text),
        (2, '改善措施', o."Measures"::text),
        (2, '预防对策', o."Prevention"::text)
    ) AS c(grp, col, x)
    UNION ALL
    SELECT '海外', s."ProblemId"::text, 2, '处理步骤·' || btrim(s."StepStr"::text), c.x
    FROM (SELECT x.*, row_number() OVER (PARTITION BY x."ProblemId", btrim(x."StepStr"::text) ORDER BY x."Id" DESC) AS rn
          FROM "OverseasProblem_StepLog" x
          WHERE btrim(x."StepStr"::text) IN ('SQE跟进', 'IQC意见', 'IQC填写意见', '工厂制程分析', '责任人确认',
                                            '工程确认', '设计变更', '设计变更后SQE确认', '预防对策确认')) s
    CROSS JOIN LATERAL (VALUES
        (s."Opinon"::text), (s."Measures"::text),
        (CASE WHEN btrim(s."StepStr"::text) = '工厂制程分析' THEN s."Result"::text END)
    ) AS c(x)
    WHERE s.rn = 1
)
SELECT s.dom, s.pid, s.grp, s.col, z.t
FROM src s
JOIN base b ON b.dom = s.dom AND b.pid = s.pid
CROSS JOIN LATERAL (SELECT btrim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
        COALESCE(s.x, ''),
        'base64,[^"'']*', '', 'gi'),
        '<[^>]*>', ' ', 'g'),
        '&(nbsp|amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-f]+);', ' ', 'gi'),
        '[\\s\\u00a0\\u3000]+', ' ', 'g')) AS t) z
WHERE z.t <> ''
ORDER BY s.dom, s.pid, s.grp, s.col
"""

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Topic:
    name: str
    desc: str
    terms: list[str]
    fuzzy: list[str]
    excludes: list[str]


@dataclass
class Order:
    dom: str
    pid: str
    no: str
    add_date: dt.date
    cols: list[tuple[int, str, str]] = field(default_factory=list)  # (组, 栏目, 剥净后的文字)


@dataclass
class TermResult:
    group: str  # 1 / 2 / 3 / 4 / -
    hits: list[tuple[str, str, int, str]]  # (说法, 类别 算/＊, 栏目组, 栏目)


# ---------------------------------------------------------------------------
# 说法清单与按词匹配（与线上口径、探测 T4 的 SQL 一致）
# ---------------------------------------------------------------------------

_FW_SRC = "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９－"
_FW_DST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
_FW = str.maketrans(_FW_SRC, _FW_DST)
_ASCII_TERM = re.compile(r"^[A-Za-z0-9 .-]+$")
MASK = "\x00"  # 屏蔽「不算的说法」用的占位符
PHENOMENON_COLS = {"问题现象", "已选问题现象"}
SHORT_TEXT = 10  # 剥净后不超过 10 个字的内容不参与按意思找（问题现象除外），总述「比对范围」


def norm(text: str) -> str:
    return text.translate(_FW).lower()


def parse_topic_terms(md: str) -> tuple[list[Topic], list[str]]:
    """读 topic_terms.md 的「清单」表与「说明」里和判断有关的条目。"""
    topics: list[Topic] = []
    notes: list[str] = []
    section = ""
    for raw in md.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section == "清单" and line.startswith("|") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4 or cells[0] == "话题":
                continue
            name, desc, terms_cell, ex_cell = cells[:4]
            terms, fuzzy = [], []
            for item in (t.strip() for t in terms_cell.split("、")):
                if not item:
                    continue
                if item.startswith("＊"):
                    fuzzy.append(item[1:].strip())
                else:
                    terms.append(item)
            excludes = [] if ex_cell in ("—", "-", "") else [t.strip() for t in ex_cell.split("、") if t.strip()]
            topics.append(Topic(name, desc, terms, fuzzy, excludes))
        elif section == "说明" and line.startswith("- ") and "总述" not in line:
            notes.append(line[2:].strip())
    if not topics:
        raise SystemExit(f"没有从 {TOPIC_TERMS_MD} 读到说法清单，检查表格格式")
    return topics, notes


class TopicMatcher:
    def __init__(self, topic: Topic):
        self.topic = topic
        self.ex_re = (
            re.compile("|".join(re.escape(norm(e)) for e in topic.excludes)) if topic.excludes else None
        )
        self.items: list[tuple[str, str, re.Pattern[str] | None, str]] = []
        for kind, words in (("算", topic.terms), ("＊", topic.fuzzy)):
            for w in words:
                if _ASCII_TERM.match(w):
                    rx = re.compile(r"(?:^|[^a-z0-9])" + re.escape(norm(w)) + r"(?:[^a-z0-9]|$)")
                    self.items.append((w, kind, rx, ""))
                else:
                    self.items.append((w, kind, None, norm(w).replace(" ", "")))

    def match(self, order: Order) -> TermResult:
        hits: list[tuple[str, str, int, str]] = []
        for grp, col, text in order.cols:
            tx = norm(text)
            # 屏蔽处换成占位符：去空格时不会被删掉，屏蔽处两侧的文字不会拼成新词
            mt = self.ex_re.sub(MASK, tx) if self.ex_re else tx
            mt_ns = mt.replace(" ", "")
            for word, kind, rx, word_ns in self.items:
                ok = rx.search(mt) is not None if rx is not None else (word_ns in mt_ns)
                if ok:
                    hits.append((word, kind, grp, col))
        a1 = any(k == "算" and g == 1 for _, k, g, _ in hits)
        a2 = any(k == "算" and g == 2 for _, k, g, _ in hits)
        s1 = any(k == "＊" and g == 1 for _, k, g, _ in hits)
        s2 = any(k == "＊" and g == 2 for _, k, g, _ in hits)
        group = "1" if a1 else "2" if a2 else "3" if s1 else "4" if s2 else "-"
        return TermResult(group, hits)


def hits_text(hits: list[tuple[str, str, int, str]]) -> str:
    return "；".join(sorted({f"{w}@{c}" for w, _, _, c in hits}))


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------


def fetch_orders(dsn: str) -> list[Order]:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise SystemExit('缺 psycopg：用 uv run --with "psycopg[binary]>=3.2,<4" 运行') from exc
    orders: dict[tuple[str, str], Order] = {}
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(BASE_SQL)
            for dom, pid, no, add_date in cur.fetchall():
                orders[(dom, pid)] = Order(dom, pid, (no or "").strip(), add_date)
            cur.execute(TEXT_SQL)
            for dom, pid, grp, col, text in cur.fetchall():
                o = orders.get((dom, pid))
                if o is not None and text:
                    o.cols.append((int(grp), col, text))
    return list(orders.values())


# ---------------------------------------------------------------------------
# 本地模型
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    disable_thinking: bool
    concurrency: int
    timeout: float
    max_tokens: int
    retries: int = 5


def build_system_prompt(topics: list[Topic], notes: list[str]) -> str:
    lines = [
        "你在给制程质量问题单做话题标注。下面是话题清单：每个话题有一句话说明；"
        "常见说法只作参考，写法不同但意思相同也算；不算的说法是指这些写法不属于该话题。",
        "",
    ]
    for t in topics:
        parts = [f"- {t.name}：{t.desc}。常见说法：{'、'.join(t.terms)}"]
        if t.fuzzy:
            parts.append(f"；有歧义、要看上下文的说法：{'、'.join(t.fuzzy)}")
        if t.excludes:
            parts.append(f"；不算的说法：{'、'.join(t.excludes)}")
        lines.append("".join(parts))
    if notes:
        lines += ["", "补充说明："] + [f"- {n}" for n in notes]
    lines += [
        "",
        "判断一个话题和这张单的关系，取下面三种之一：",
        "- 问题本身：这张单的不良现象属于这个话题，也就是坏的正是这个功能或部件。例：非接读卡失败；喇叭无声；外壳开裂。",
        "- 顺带提到：文字提到了这个话题，但这张单坏的不是它。"
        "例：检验时顺带测了非接；问题是按键失灵，措施里写了更换喇叭；部件名里带这个词，问题却是别的；"
        "它只是另一个问题的原因（如某部件的信号干扰导致磁头不良，这张单算磁卡与IC卡，该部件只算顺带提到）。",
        "- 无关：这个话题和这张单没有关系（例如说法在这里是别的意思）。",
        "一张单可以同时属于几个话题的「问题本身」，例如喇叭无声且外壳开裂，两个都是问题本身。",
        "",
        "要求：",
        "1. 用户会列出「文字里出现过说法的话题」，这些话题每一个都必须输出，relation 取三种之一，不能省略。",
        "2. 没列出的话题，只要属于问题本身或顺带提到，也要输出；无关的不输出。",
        f"3. 只根据给出的文字判断，不要推测。evidence 从原文摘一个最能说明判断的词或短语，不超过 {EVIDENCE_MAX} 个字。",
        "4. 只输出一个 JSON 对象，不要输出其他内容，格式：",
        '{"topics": [{"topic": "话题名", "relation": "问题本身", "evidence": "原文短语"}]}',
        '没有任何话题要输出时输出 {"topics": []}。',
    ]
    return "\n".join(lines)


def build_doc(order: Order, per_col: int, total: int) -> tuple[str, bool]:
    seen: set[str] = set()
    parts: list[str] = []
    used = 0
    truncated = False
    for grp in (1, 2):
        for g, col, text in order.cols:
            if g != grp or text in seen:
                continue
            if col not in PHENOMENON_COLS and len(text.replace(" ", "")) <= SHORT_TEXT:
                continue
            seen.add(text)
            s = text
            if len(s) > per_col:
                s = s[:per_col] + "…"
                truncated = True
            if used + len(s) > total:
                truncated = True
                break
            parts.append(f"【{col}】{s}")
            used += len(s)
    return "\n".join(parts), truncated


_THINK = re.compile(r"<think>.*?</think>", re.S)


def parse_reply(reply: str, topic_names: set[str]) -> list[dict]:
    text = _THINK.sub("", reply or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回复里没有 JSON")
    data = json.loads(text[start : end + 1])
    out: dict[str, dict] = {}
    for item in data.get("topics", []) or []:
        name = str(item.get("topic", "")).strip()
        rel = str(item.get("relation", "")).strip()
        if name not in topic_names or rel not in RELATIONS:
            continue
        ev = str(item.get("evidence", "")).strip()[:EVIDENCE_MAX]
        # 同一话题出现两次时取更强的那个：问题本身 > 顺带提到 > 无关
        if name not in out or _REL_RANK[rel] < _REL_RANK[out[name]["relation"]]:
            out[name] = {"topic": name, "relation": rel, "evidence": ev}
    return list(out.values())


def candidate_hint(order: Order, matchers: dict[str, TopicMatcher]) -> tuple[str, list[str]]:
    """文字里出现过说法的话题（含有歧义的说法），交给模型逐个判断。"""
    parts: list[str] = []
    names: list[str] = []
    for name, m in matchers.items():
        words = sorted({w for w, _, _, _ in m.match(order).hits})
        if words:
            names.append(name)
            parts.append(f"{name}（{'、'.join(words)}）")
    return "；".join(parts), names


async def label_orders(
    orders: list[Order],
    cfg: LLMConfig,
    system_prompt: str,
    topic_names: set[str],
    labels_path: Path,
    done: dict[str, dict],
    per_col: int,
    total: int,
    matchers: dict[str, TopicMatcher],
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    todo = [o for o in orders if f"{o.dom}|{o.pid}" not in done]
    print(f"待标注 {len(todo)} 张（已完成 {len(done)} 张）", flush=True)
    sem = asyncio.Semaphore(cfg.concurrency)
    lock = asyncio.Lock()
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    started = time.monotonic()
    finished = 0

    async with httpx.AsyncClient(timeout=cfg.timeout, transport=transport) as client:

        async def one(o: Order) -> None:
            nonlocal finished
            doc, truncated = build_doc(o, per_col, total)
            hint, cand = candidate_hint(o, matchers)
            rec = {"key": f"{o.dom}|{o.pid}", "dom": o.dom, "no": o.no, "truncated": truncated,
                   "prompt": PROMPT_VERSION, "model": cfg.model, "candidates": cand}
            if not doc:
                rec.update(topics=[], error=None, empty=True)
            else:
                ask = (f"文字里出现过说法的话题（每个都要判断）：{hint}" if hint
                       else "文字里没有出现说法清单里的说法。")
                body = {
                    "model": cfg.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"问题单（{o.dom}）：\n{doc}\n\n{ask}"},
                    ],
                    "temperature": 0,
                    "max_tokens": cfg.max_tokens,
                }
                if cfg.disable_thinking:
                    body["chat_template_kwargs"] = {"enable_thinking": False}
                last_err = None
                topics_out = None
                async with sem:
                    for attempt in range(cfg.retries):
                        try:
                            r = await client.post(url, json=body, headers=headers)
                            r.raise_for_status()
                            reply = r.json()["choices"][0]["message"]["content"]
                            topics_out = parse_reply(reply, topic_names)
                            break
                        except Exception as exc:  # noqa: BLE001
                            last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
                            # 服务过载（5xx）时退避得更久：2、4、8、16、32 秒……
                            await asyncio.sleep(min(2 ** (attempt + 1), 60))
                rec.update(topics=topics_out or [], error=None if topics_out is not None else last_err)
            async with lock:
                with labels_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done[rec["key"]] = rec
                finished += 1
                if finished % 50 == 0 or finished == len(todo):
                    rate = finished / max(time.monotonic() - started, 1e-6)
                    left = (len(todo) - finished) / rate if rate > 0 else 0
                    print(f"  {finished}/{len(todo)}，约 {rate * 60:.0f} 张/分钟，剩约 {left / 60:.0f} 分钟", flush=True)

        await asyncio.gather(*(one(o) for o in todo))


def load_done(labels_path: Path, model: str = "") -> dict[str, dict]:
    done: dict[str, dict] = {}
    if labels_path.exists():
        for line in labels_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("prompt", "v1") != PROMPT_VERSION:  # 旧版提示词的结果作废
                    continue
                if model and rec.get("model") not in (None, model):  # 换了模型也重标
                    continue
                if rec.get("error") is None:  # 失败的下次重跑
                    done[rec["key"]] = rec
    return done


# ---------------------------------------------------------------------------
# 探测 T4 人工判定（可选，作模型标签的标尺）
# ---------------------------------------------------------------------------


def load_t4(path: Path) -> list[dict]:
    rows: list[dict] = []
    header: list[str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        rec = dict(zip(header, cells, strict=False))
        if not rec.get("段", "").startswith("T4b"):
            continue
        case, no = rec.get("案例", ""), rec.get("问题编号", "")
        label = rec.get("判定", "")
        if (case, no) in T4_OVERRIDES:
            label = T4_OVERRIDES[(case, no)]
        elif not label and "只是提及" in rec.get("备注", ""):
            label = "不是"
        if label in ("是", "相关"):
            human = True
        elif label in ("不是", "不相关"):
            human = False
        else:
            continue
        topic = T4_CASE_TOPIC.get(case)
        if topic:
            rows.append({"case": case, "dom": rec.get("域", ""), "no": no, "topic": topic,
                         "group": rec.get("组别", ""), "human": human})
    return rows


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def md_table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def t4_scope_check(orders: list[Order], matchers: dict[str, TopicMatcher], t4_date: dt.date) -> list[str]:
    """按探测 T4 的范围重算按词分组，与 T4a 的计数对照，检验本脚本的匹配与 SQL 一致。"""
    leak = TopicMatcher(Topic("漏电", "", [], ["漏电"], []))
    year_start = (t4_date.replace(year=t4_date.year - 1) + dt.timedelta(days=1))
    scopes = [
        ("CN-039 音频（国内，近一年）", "国内", year_start, t4_date, matchers.get("音频"), "421 / 16 / 1 / 3 / 0"),
        ("CN-045 安全（国内，不限时间）", "国内", None, None, matchers.get("安全"), "2474 / 1 / 0 / 15 / 5"),
        ("CN-055 非接（国内，2026 年）", "国内", dt.date(2026, 1, 1), None, matchers.get("非接"), "347 / 14 / 0 / 1 / 2"),
        ("CN-056 漏电（国内，不限时间）", "国内", None, None, leak, "2474 / 0 / 0 / 9 / 4"),
        ("XC-031 非接（巴西，2026 年）", "巴西", dt.date(2026, 1, 1), None, matchers.get("非接"), "58 / 1 / 0 / 0 / 0"),
    ]
    rows = []
    for label, dom, start, end, m, expect in scopes:
        if m is None:
            rows.append([label, "话题不在清单里", expect, "—"])
            continue
        scope = [o for o in orders if o.dom == dom and (start is None or o.add_date >= start)
                 and (end is None or o.add_date <= end)]
        c = Counter(m.match(o).group for o in scope)
        got = f"{len(scope)} / {c['1']} / {c['2']} / {c['3']} / {c['4']}"
        rows.append([label, got, expect, "一致" if got == expect else "不一致"])
    lines = ["## 与探测 T4 的计数对照（检验按词匹配与 SQL 一致）", "",
             "格式：范围内单数 / 问题本身涉及 / 处理中提到 / 待判断 / 带＊只在第二组。"
             "镜像数据更新过时，不一致可能只是数据变了。", ""]
    return lines + md_table(["范围", "本次", "T4a", "结果"], rows) + [""]


def analyze(
    orders: list[Order],
    scope_orders: list[Order],
    topics: list[Topic],
    matchers: dict[str, TopicMatcher],
    labels: dict[str, dict] | None,
    t4_rows: list[dict],
    out_dir: Path,
    t4_date: dt.date,
    sample_cap: int,
    seed: int,
    run_info: list[str],
) -> None:
    term: dict[tuple[str, str], TermResult] = {}
    for o in orders:
        for t in topics:
            term[(f"{o.dom}|{o.pid}", t.name)] = matchers[t.name].match(o)

    def rel_of(key: str, topic: str) -> str:
        rec = (labels or {}).get(key)
        if rec is None:
            return "未标注"
        for it in rec.get("topics", []):
            if it["topic"] == topic:
                return it["relation"]
        return "无关"

    def ev_of(key: str, topic: str) -> str:
        rec = (labels or {}).get(key) or {}
        for it in rec.get("topics", []):
            if it["topic"] == topic:
                return it.get("evidence", "")
        return ""

    if labels:
        # 提示词要求逐个判断的候选话题，模型漏掉没判的次数（越少越好）
        n_cand = n_missed = 0
        for o in orders:
            rec = labels.get(f"{o.dom}|{o.pid}")
            if not rec or rec.get("empty"):
                continue
            judged = {it["topic"] for it in rec.get("topics", [])}
            for t in topics:
                if term[(f"{o.dom}|{o.pid}", t.name)].hits:
                    n_cand += 1
                    n_missed += t.name not in judged
        run_info = run_info + [f"- 候选话题（文字里出现过说法）共 {n_cand} 个，模型没给判断的 {n_missed} 个"]
    md: list[str] = ["# 话题标注汇总", ""] + run_info + [""]
    md += t4_scope_check(scope_orders, matchers, t4_date)

    # 1) 每个话题：按词分组 × 模型判断
    rel_cols = ["问题本身", "顺带提到", "无关"] + ([] if labels else ["未标注"])
    md += ["## 每个话题：说法清单分组 × 模型判断（三域合计，张数）", ""]
    per_dom_rows = []
    for t in topics:
        grid: dict[str, Counter] = defaultdict(Counter)
        dom_self: Counter = Counter()
        for o in orders:
            key = f"{o.dom}|{o.pid}"
            g = term[(key, t.name)].group
            r = rel_of(key, t.name)
            grid[g][r] += 1
            if r == "问题本身":
                dom_self[o.dom] += 1
        md += [f"### {t.name}", ""]
        rows = []
        for g in ("1", "2", "3", "4", "-"):
            rows.append([GROUP_NAMES[g]] + [grid[g][c] for c in rel_cols])
        md += md_table(["说法清单分组"] + rel_cols, rows) + [""]
        per_dom_rows.append([t.name, dom_self["国内"], dom_self["巴西"], dom_self["海外"]])
    if labels:
        md += ["## 每个话题：模型判为「问题本身」的张数（分域）", ""]
        md += md_table(["话题", "国内", "巴西", "海外"], per_dom_rows) + [""]

    # 2) 与 T4 人工判定对照
    if labels and t4_rows:
        idx = {(o.dom, o.no): f"{o.dom}|{o.pid}" for o in orders}
        conf: dict[str, Counter] = defaultdict(Counter)
        detail = []
        n_unlabeled = 0
        for r in t4_rows:
            key = idx.get((r["dom"], r["no"]))
            if key is None:
                continue
            if rel_of(key, r["topic"]) == "未标注":  # 模型调用失败的单不算进一致率
                n_unlabeled += 1
                continue
            model_self = rel_of(key, r["topic"]) == "问题本身"
            cell = ("人工是" if r["human"] else "人工不是") + ("·模型是" if model_self else "·模型不是")
            conf[r["case"]][cell] += 1
            detail.append([r["case"], r["dom"], r["no"], r["topic"], r["group"],
                           "是" if r["human"] else "不是", rel_of(key, r["topic"]), ev_of(key, r["topic"])])
        md += ["## 与探测 T4 人工判定对照", "",
               "人工「是 / 相关」记为是；模型「问题本身」记为是。CN-056 只按漏电找，不是整个话题，不参与。"
               f"模型调用失败、没有标注的 {n_unlabeled} 张不计入。", ""]
        rows = []
        for case, c in conf.items():
            n = sum(c.values())
            agree = c["人工是·模型是"] + c["人工不是·模型不是"]
            rows.append([case, n, c["人工是·模型是"], c["人工是·模型不是"], c["人工不是·模型是"],
                         c["人工不是·模型不是"], f"{agree}/{n}"])
        md += md_table(["案例", "已判张数", "都是", "人工是·模型不是", "人工不是·模型是", "都不是", "一致"], rows)
        md += [""]
        write_csv(out_dir / "T4对照.csv",
                  ["案例", "域", "问题编号", "话题", "T4 组别", "人工判定", "模型判断", "模型依据"], detail)

    # 3) 说法精度：每个说法在第一组栏目命中的单里，模型判为问题本身的比例
    if labels:
        prec_rows = []
        for t in topics:
            stat: dict[tuple[str, str], Counter] = defaultdict(Counter)
            for o in orders:
                key = f"{o.dom}|{o.pid}"
                tr = term[(key, t.name)]
                if not tr.hits:
                    continue
                r = rel_of(key, t.name)
                g1 = {(w, k) for w, k, g, _ in tr.hits if g == 1}
                g2 = {(w, k) for w, k, g, _ in tr.hits if g == 2} - g1
                for wk in g1:
                    stat[wk]["g1"] += 1
                    stat[wk]["g1_self"] += r == "问题本身"
                for wk in g2:
                    stat[wk]["g2"] += 1
                    stat[wk]["g2_self"] += r == "问题本身"
            for (w, k), c in stat.items():
                share = c["g1_self"] / c["g1"] if c["g1"] else None
                prec_rows.append([t.name, w, k, c["g1"], c["g1_self"],
                                  f"{share:.0%}" if share is not None else "—", c["g2"], c["g2_self"]])
        prec_rows.sort(key=lambda r: (r[0], -r[3]))
        header = ["话题", "说法", "类别", "第一组栏目命中单数", "其中模型判为问题本身",
                  "比例", "只在第二组栏目命中单数", "其中模型判为问题本身"]
        write_csv(out_dir / "说法精度.csv", header, prec_rows)
        weak = [r for r in prec_rows if r[3] >= 3 and r[2] == "算" and r[4] / r[3] < 0.5]
        md += ["## 可能太宽的说法（算的说法，第一组栏目命中 ≥ 3 张，模型判为问题本身不到一半）", "",
               "完整表见 说法精度.csv。", ""]
        md += (md_table(header, weak) if weak else ["没有。"]) + [""]

        # 4) 漏掉的写法：模型判为问题本身、说法清单前三组都没找到
        miss_rows = []
        phrase_rows = []
        known = {t.name: {norm(x) for x in t.terms + t.fuzzy} for t in topics}
        for t in topics:
            n_miss = 0
            phrases: Counter = Counter()
            for o in orders:
                key = f"{o.dom}|{o.pid}"
                if rel_of(key, t.name) != "问题本身":
                    continue
                if term[(key, t.name)].group in ("-", "4"):
                    n_miss += 1
                ev = norm(ev_of(key, t.name)).replace(" ", "")
                if ev and not any(k.replace(" ", "") in ev for k in known[t.name]):
                    phrases[ev] += 1
            miss_rows.append([t.name, n_miss])
            for p, n in phrases.most_common():
                if n >= 2:
                    phrase_rows.append([t.name, p, n])
        md += ["## 说法清单没找到、模型判为问题本身的张数", ""]
        md += md_table(["话题", "张数"], miss_rows) + [""]
        # 说法候选的短语摘自原文，只写进 说法候选.csv（只在内网看），不进 汇总.md
        md += ["## 说法候选", "", f"共 {len(phrase_rows)} 个，见 说法候选.csv（短语摘自原文，只在内网看，不发回）。", ""]
        write_csv(out_dir / "说法候选.csv", ["话题", "短语", "单数"], phrase_rows)

        # 5) 抽查清单与应命中集草稿
        rng = random.Random(seed)
        t4_keys = {(r["dom"], r["no"]) for r in t4_rows}
        sample_rows = []
        draft_rows = []
        for t in topics:
            buckets: dict[str, list[Order]] = defaultdict(list)
            for o in orders:
                key = f"{o.dom}|{o.pid}"
                g = term[(key, t.name)].group
                r = rel_of(key, t.name)
                if r == "问题本身" or g in ("1", "2"):
                    draft_rows.append([t.name, o.dom, o.no, o.add_date, GROUP_NAMES[g], r])
                if (o.dom, o.no) in t4_keys:
                    continue
                if g in ("1", "2") and r != "问题本身":
                    buckets["A 说法命中、模型说不是问题本身"].append(o)
                elif g in ("-", "4") and r == "问题本身":
                    buckets["B 说法没找到、模型说是问题本身"].append(o)
                elif g == "3":
                    buckets["C 待判断"].append(o)
                elif g == "1" and r == "问题本身":
                    buckets["D 两边一致（抽查）"].append(o)
            for name in sorted(buckets):
                picked = buckets[name]
                if len(picked) > sample_cap:
                    picked = rng.sample(picked, sample_cap)
                for o in sorted(picked, key=lambda x: (x.dom, x.add_date), reverse=True):
                    key = f"{o.dom}|{o.pid}"
                    tr = term[(key, t.name)]
                    sample_rows.append([t.name, name, len(buckets[name]), o.dom, o.no, o.add_date,
                                        GROUP_NAMES[tr.group], hits_text(tr.hits), rel_of(key, t.name),
                                        ev_of(key, t.name), "", ""])
        write_csv(out_dir / "抽查清单.csv",
                  ["话题", "类别", "该类总张数", "域", "问题编号", "建单日期", "说法清单分组", "命中（说法@栏目）",
                   "模型判断", "模型依据", "人工判定（是/不是/拿不准）", "备注"], sample_rows)
        write_csv(out_dir / "应命中集草稿.csv",
                  ["话题", "域", "问题编号", "建单日期", "说法清单分组", "模型判断"], draft_rows)
        md += ["## 抽查清单", "",
               f"见 抽查清单.csv：每个话题按 A–D 四类各抽最多 {sample_cap} 张，已在 T4 判过的单不再抽。", ""]

    (out_dir / "汇总.md").write_text("\n".join(md) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 改清单之前先估算：草稿 vs 现行清单（复用已有模型标签，不调模型）
# ---------------------------------------------------------------------------


def load_label_set(labels_dir: Path) -> dict[str, dict]:
    """读一个输出目录里的 labels.jsonl：每张单取最后一条成功的记录，不管提示词版本。"""
    path = labels_dir / "labels.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} 不存在")
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("error") is None:
                out[rec["key"]] = rec
    return out


def word_kinds(topic: Topic | None) -> dict[str, str]:
    if topic is None:
        return {}
    kinds = {w: "算" for w in topic.terms}
    kinds.update({w: "＊" for w in topic.fuzzy})
    kinds.update({w: "不算" for w in topic.excludes})
    return kinds


def read_table_any(path: Path) -> list[dict]:
    """读人工填过的抽查清单：Excel 另存后可能是 GBK 或 UTF-8、逗号或制表符分隔。"""
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit(f"{path} 读不出来（既不是 UTF-8 也不是 GBK）")
    text = text.lstrip("\ufeff")
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") > first.count(",") else ","
    rd = csv.DictReader(text.splitlines(), delimiter=delim)
    rd.fieldnames = [c.strip().lstrip("\ufeff") for c in (rd.fieldnames or [])]
    return list(rd)


def load_judged(paths: list[Path], t4_rows: list[dict]) -> list[dict]:
    """人工判定：抽查清单里填了「人工判定」的行，加上探测 T4 的判定。只取话题、域、单号、判定。"""
    out: list[dict] = []
    for p in paths:
        for r in read_table_any(p):
            label = (r.get("人工判定（是/不是/拿不准）") or "").strip()
            if label in ("是", "不是", "拿不准") and r.get("话题") and r.get("问题编号"):
                out.append({"src": p.name, "topic": r["话题"].strip(), "dom": (r.get("域") or "").strip(),
                            "no": r["问题编号"].strip(), "human": label})
    for r in t4_rows:
        out.append({"src": "T4", "topic": r["topic"], "dom": r["dom"], "no": r["no"],
                    "human": "是" if r["human"] else "不是"})
    return out


def what_if(
    orders: list[Order],
    base_topics: list[Topic],
    draft_topics: list[Topic],
    label_sets: list[tuple[str, dict[str, dict]]],
    draft_name: str,
    out_path: Path,
    judged: list[dict] | None = None,
) -> None:
    base = {t.name: t for t in base_topics}
    draft = {t.name: t for t in draft_topics}
    names = [t.name for t in base_topics] + [t.name for t in draft_topics if t.name not in base]
    set_names = [n for n, _ in label_sets]

    def rel(labels: dict[str, dict], key: str, topic: str) -> str:
        rec = labels.get(key)
        if rec is None:
            return "未标注"
        for it in rec.get("topics", []):
            if it["topic"] == topic:
                return it["relation"]
        return "无关"

    def self_share(keys: list[str], topic: str) -> str:
        if not keys:
            return "—"
        parts = []
        for _, labels in label_sets:
            n = sum(rel(labels, k, topic) == "问题本身" for k in keys)
            parts.append(f"{n / len(keys):.0%}")
        return " / ".join(parts)

    md = [
        f"# 说法清单对比：{draft_name} vs 现行清单", "",
        f"- 单数：{len(orders)}；模型标签：{'、'.join(set_names)}（不重新调模型）",
        "- 「模型判为问题本身」的比例按标签集分别给，用「/」隔开，顺序同上。",
        "- 标签是按现行清单生成的；草稿新加的话题没有模型标签。比例只作线索，定不定以人工抽查为准。",
        "",
    ]
    summary_rows = []
    for name in names:
        bt, dt_ = base.get(name), draft.get(name)
        bk, dk = word_kinds(bt), word_kinds(dt_)
        changes = [(w, bk.get(w, "—"), dk.get(w, "—")) for w in sorted(set(bk) | set(dk)) if bk.get(w) != dk.get(w)]
        if not changes and (bt and dt_ and bt.desc == dt_.desc):
            continue
        bm = TopicMatcher(bt) if bt else None
        dm = TopicMatcher(dt_) if dt_ else None
        before: Counter = Counter()
        after: Counter = Counter()
        moves: dict[tuple[str, str], list[str]] = defaultdict(list)
        word_g1: dict[tuple[str, str], list[str]] = defaultdict(list)  # (版本, 说法) -> 第一组栏目命中的单
        for o in orders:
            key = f"{o.dom}|{o.pid}"
            rb = bm.match(o) if bm else TermResult("-", [])
            ra = dm.match(o) if dm else TermResult("-", [])
            before[rb.group] += 1
            after[ra.group] += 1
            if rb.group != ra.group:
                moves[(rb.group, ra.group)].append(key)
            for ver, res in (("现行", rb), ("草稿", ra)):
                for w in {w for w, _, g, _ in res.hits if g == 1}:
                    word_g1[(ver, w)].append(key)
        md += [f"## {name}", "", "**改了什么**", ""]
        rows = []
        for w, k0, k1 in changes:
            ver = "草稿" if k1 in ("算", "＊") else "现行"
            keys = word_g1.get((ver, w), [])
            rows.append([w, k0, k1, len(keys), self_share(keys, name)])
        md += md_table(["说法", "现行", "草稿", "第一组栏目命中单数（按草稿；删去的按现行）", "其中模型判为问题本身"], rows)
        md += ["", "**各组张数**", ""]
        md += md_table(["", *[GROUP_NAMES[g] for g in ("1", "2", "3", "4")]],
                       [["现行", *[before[g] for g in ("1", "2", "3", "4")]],
                        ["草稿", *[after[g] for g in ("1", "2", "3", "4")]]])
        if moves:
            md += ["", "**换了组的单**", ""]
            mrows = []
            for (g0, g1), keys in sorted(moves.items(), key=lambda kv: -len(kv[1])):
                mrows.append([GROUP_NAMES[g0], GROUP_NAMES[g1], len(keys), self_share(keys, name)])
            md += md_table(["现行", "草稿", "张数", "其中模型判为问题本身"], mrows)
        md += [""]
        summary_rows.append([name, before["1"] + before["2"], after["1"] + after["2"], before["3"], after["3"]])
    if judged:
        idx = {(o.dom, o.no): o for o in orders}
        md += ["## 人工判定过的单：现行与草稿各落在哪一组", "",
               "人工判「是」的单应落在前两组或待判断；判「不是」的单最好不在前两组。只列单号与分组，不含文字。", ""]
        rows = []
        bad = []
        for j in judged:
            o = idx.get((j["dom"], j["no"]))
            if o is None:
                continue
            bt, dt_ = base.get(j["topic"]), draft.get(j["topic"])
            gb = TopicMatcher(bt).match(o).group if bt else "-"
            ga = TopicMatcher(dt_).match(o).group if dt_ else "-"
            rows.append([j["topic"], j["src"], j["no"], j["human"], GROUP_NAMES[gb], GROUP_NAMES[ga]])
            if (j["human"] == "是" and ga in ("-", "4")) or (j["human"] == "不是" and ga in ("1", "2")):
                bad.append(j)
        rows.sort(key=lambda r: (r[0], r[3], r[2]))
        md += md_table(["话题", "来源", "问题编号", "人工判定", "现行", "草稿"], rows) + [""]
        tally: dict[str, Counter] = defaultdict(Counter)
        for j in bad:
            tally[j["topic"]][j["human"]] += 1
        md += ["**草稿仍不对的**：" + ("；".join(
            f"{t} 判「是」却没找到 {c['是']} 张、判「不是」仍在前两组 {c['不是']} 张" for t, c in tally.items())
            if tally else "没有。"), ""]
    if summary_rows:
        md[6:6] = ["## 总览", ""] + md_table(
            ["话题", "前两组（现行）", "前两组（草稿）", "待判断（现行）", "待判断（草稿）"], summary_rows) + [""]
    else:
        md += ["草稿与现行清单没有差别。"]
    out_path.write_text("\n".join(md) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def check_out_dir(path: Path) -> Path | None:
    """输出含真实单号与原文短语，只允许写在仓库的 runtime/ 下（已被 .gitignore 忽略）。"""
    resolved = path.resolve()
    runtime = (ROOT / "runtime").resolve()
    if resolved != runtime and runtime not in resolved.parents:
        print(f"输出目录必须在 {runtime} 下：{resolved}", file=sys.stderr)
        return None
    return resolved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用本地大模型给制程问题单打话题标签，并与说法清单对照")
    ap.add_argument("--dry-run", action="store_true", help="不调模型，只做按词匹配与 T4 计数对照")
    ap.add_argument("--confirm-local", action="store_true", help="确认模型服务是内网本地服务（不调模型时不需要）")
    ap.add_argument("--limit", type=int, default=0, help="只标注前 N 张（试跑用）")
    ap.add_argument("--domain", choices=["国内", "巴西", "海外"], help="只处理一个域")
    ap.add_argument("--out", type=Path, help="输出目录，默认 runtime/topic_labeling/<日期>-<提示词版本>")
    ap.add_argument("--t4", type=Path, help="探测 T4 的判定结果文件（可选，用作标尺）")
    ap.add_argument("--t4-date", default="2026-10-24", help="探测 T4 的执行日期，用于重算「近一年」")
    ap.add_argument("--per-col", type=int, default=1000, help="每个栏目交给模型的最多字数")
    ap.add_argument("--total", type=int, default=6000, help="每张单交给模型的最多字数")
    ap.add_argument("--sample-cap", type=int, default=10, help="抽查清单每个话题每类最多张数")
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--what-if", type=Path, metavar="草稿.md",
                    help="说法清单草稿（格式同 topic_terms.md）：与现行清单对比，复用已有模型标签，不调模型")
    ap.add_argument("--labels-dir", type=Path, action="append", default=[],
                    help="--what-if 用哪次运行的模型标签（输出目录），可给多次")
    ap.add_argument("--judged", type=Path, action="append", default=[],
                    help="--what-if 时附上人工填过的抽查清单，检查草稿把这些单分到哪一组，可给多次")
    args = ap.parse_args(argv)

    load_env_file(ROOT / ".env")
    dsn = os.environ.get("FI_PG_DSN", "")
    if not dsn:
        print("缺 FI_PG_DSN（正式镜像库连接串），见 README", file=sys.stderr)
        return 2

    topics, notes = parse_topic_terms(TOPIC_TERMS_MD.read_text(encoding="utf-8"))
    matchers = {t.name: TopicMatcher(t) for t in topics}

    if args.what_if:
        if not args.labels_dir:
            print("--what-if 要配 --labels-dir（之前某次运行的输出目录）", file=sys.stderr)
            return 2
        draft_topics, _ = parse_topic_terms(args.what_if.read_text(encoding="utf-8"))
        label_sets = [(p.name, load_label_set(p)) for p in args.labels_dir]
        out_dir = check_out_dir(args.out or DEFAULT_OUT_ROOT / f"{dt.date.today().strftime('%Y%m%d')}-whatif")
        if out_dir is None:
            return 2
        out_dir.mkdir(parents=True, exist_ok=True)
        orders = fetch_orders(dsn)
        if args.domain:
            orders = [o for o in orders if o.dom == args.domain]
        out_path = out_dir / f"清单对比-{args.what_if.stem}.md"
        judged = load_judged(args.judged, load_t4(args.t4) if args.t4 else [])
        what_if(orders, topics, draft_topics, label_sets, args.what_if.name, out_path, judged)
        print(f"完成，输出在 {out_path}", flush=True)
        return 0

    out_dir = check_out_dir(args.out or DEFAULT_OUT_ROOT / f"{dt.date.today().strftime('%Y%m%d')}-{PROMPT_VERSION}")
    if out_dir is None:
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    orders = fetch_orders(dsn)
    all_orders = orders
    if args.domain:
        orders = [o for o in orders if o.dom == args.domain]
    print(f"取到未删除的单 {len(orders)} 张，用时 {time.monotonic() - t0:.0f} 秒", flush=True)
    t4_rows = load_t4(args.t4) if args.t4 else []
    t4_date = dt.date.fromisoformat(args.t4_date)
    dom_count = Counter(o.dom for o in orders)
    run_info = [
        f"- 运行日期：{dt.date.today().isoformat()}",
        f"- 单数：国内 {dom_count['国内']}，巴西 {dom_count['巴西']}，海外 {dom_count['海外']}",
        f"- 说法清单：{len(topics)} 个话题（docs/2_landed/topic_terms.md）",
    ]

    labels: dict[str, dict] | None = None
    if not args.dry_run:
        base_url = os.environ.get("FI_LLM_BASE_URL", "")
        model = os.environ.get("FI_LLM_MODEL", "")
        if not base_url or not model:
            print("缺 FI_LLM_BASE_URL 或 FI_LLM_MODEL，见 README", file=sys.stderr)
            return 2
        if not args.confirm_local:
            print(f"将把单上文字发给 {base_url}。确认它是内网本地模型服务后，加 --confirm-local 再运行。",
                  file=sys.stderr)
            return 2
        cfg = LLMConfig(
            base_url=base_url,
            api_key=os.environ.get("FI_LLM_API_KEY", ""),
            model=model,
            disable_thinking=os.environ.get("FI_LLM_DISABLE_THINKING", "1") == "1",
            concurrency=int(os.environ.get("FI_LLM_CONCURRENCY", "4")),
            timeout=float(os.environ.get("FI_LLM_TIMEOUT", "120")),
            max_tokens=int(os.environ.get("FI_LLM_MAX_TOKENS", "800")),
            retries=int(os.environ.get("FI_LLM_RETRIES", "5")),
        )
        labels_path = out_dir / "labels.jsonl"
        done = load_done(labels_path, model)
        target = orders[: args.limit] if args.limit else orders
        system_prompt = build_system_prompt(topics, notes)
        (out_dir / "提示词.txt").write_text(system_prompt, encoding="utf-8")
        n_todo = sum(1 for o in target if f"{o.dom}|{o.pid}" not in done)
        t1 = time.monotonic()
        asyncio.run(label_orders(target, cfg, system_prompt, {t.name for t in topics},
                                 labels_path, done, args.per_col, args.total, matchers))
        secs = time.monotonic() - t1
        labels = load_done(labels_path, model)
        all_recs = [json.loads(x) for x in labels_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        latest: dict[str, dict] = {}
        for rec in all_recs:
            if rec.get("prompt", "v1") == PROMPT_VERSION and rec.get("model") in (None, model):
                latest[rec["key"]] = rec
        failed = sum(1 for r in latest.values() if r.get("error"))
        truncated = sum(1 for r in latest.values() if r.get("truncated"))
        if args.limit:
            orders = [o for o in orders if f"{o.dom}|{o.pid}" in labels]
        run_info += [
            f"- 模型：{model}（temperature 0，并发 {cfg.concurrency}，提示词 {PROMPT_VERSION}）；本次新标注 {n_todo} 张，用时 {secs:.0f} 秒"
            + (f"，约 {n_todo / secs * 60:.0f} 张/分钟" if n_todo and secs > 0 else ""),
            f"- 标注成功 {len(labels)} 张，失败 {failed} 张，文字超长截断 {truncated} 张",
        ]
        if args.limit:
            run_info.append(f"- 试跑：只统计已标注的 {len(orders)} 张")

    analyze(orders, all_orders, topics, matchers, labels, t4_rows, out_dir, t4_date, args.sample_cap, args.seed,
            run_info)
    print(f"完成，输出在 {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
