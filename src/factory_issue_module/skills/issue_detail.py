"""单张单详情（设计 §4.3 `issue_detail` 一行、§6.3、§13；各域「单张单详情」；总述「原因与措施怎么给」「按编号查单」）。

事件顺序：`delta`（抬头）→ 各块 `delta`，处理过程、订单、发货单、费用明细、5Why 用 `table` → `suggestions`（整轮）。
没有数字结论时不附统计口径；给了合计（发货单订单数量、费用）、驳回次数时附一段。

- 要看哪张单：计划里的单号（写法统一后按前缀定域），或前一步的结果（`s1.issues`、`s2.max_defect_rate_issue`）。
  前一步给的单多于 `DETAIL_MAX` 张时只给前几张并写明。号只可能在一个域、该域无权时只答「您没有该域的查看权限」，
  不查、不说有没有这张单（J-P05）。
- 取数：一域一次，主表含叙述列、全部子表、文档、主数据；有 CAR 报告权限、物料问题且 CAR 报告 ID 有值时才读
  CAR 报告（J-P07）。剥图、派生、各块显示条件都在沙箱里（`stats/lib/detail.py`）。
- 要看什么（`aspects`）对到各块；没说要看什么时给该域的整张详情（各域「单张单详情」的块与顺序）。本域没有的项
  按 `errors.DETAIL_ABSENT` 说明；「其他:X」先对显示名与术语表、再对块名与环节名、本域不在查询范围的几项，最后在各块的
  标签里找，都对不上才说制程问题单上没有这项信息（`_other`）。
- 问「完整信息」「所有字段」时（`asks_everything`）给整张详情，另给问句里点到的、整张详情里没有的项；模型列出、
  用户没点到的项不给、也不逐条说明本域有没有（`named_aspects`，决策 2026-11-06「问完整信息时给整张详情」）。
- 链接在这里拼：问题编号、CAR 报告（对所有用户生成）、附件（摘要要的值不进沙箱脚本）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd
import structlog
from forge_core.errors import TableDenied
from forge_core.events import Event

from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import DOMAINS, SEGMENTATION, Domain
from factory_issue_module.domains import brazil, domestic, enums, numbers, overseas
from factory_issue_module.plan import schema
from factory_issue_module.present import columns, links
from factory_issue_module.stats import runner
from factory_issue_module.turn import errors

logger = structlog.get_logger(__name__)

ADAPTERS: dict[Domain, Any] = {Domain.DOMESTIC: domestic, Domain.BRAZIL: brazil, Domain.OVERSEAS: overseas}
_BY_LABEL = {d.label: d for d in DOMAINS}
#: 前一步给了好几张单时详情最多给几张
DETAIL_MAX = 3

#: 要看的内容 → 块（各域的块名相同，本域没有的那块按 `errors.DETAIL_ABSENT` 说明）
ASPECT_BLOCKS: dict[str, tuple[str, ...]] = {
    "概况": ("header",), "当前状态": ("current",), "当前责任人": ("current",), "跟进人": ("follow",),
    "责任人": ("responsible",), "原因": ("reasons",), "措施": ("reasons",), "处理结果": ("reasons",),
    "完整处理过程": ("process",), "驳回": ("process",), "停线与重启": ("stop",), "CAR": ("car",),
    "订单": ("orders",), "其他在线订单": ("other_orders",), "发货单": ("delivery",), "费用": ("cost",),
    "8D": ("eight_d",), "附件": ("all_attachments",), "问题现象": ("phenomena",), "可能原因": ("possible_reasons",),
    "5Why": ("five_why",), "PN": ("pn",), "机型": ("machine",), "物料": ("material",), "补料": ("supplement",),
    "库存处理": ("stock",), "设计更改": ("design",),
}
#: 海外说「订单」指涉及发货单（总述「三域共用的说法」：只说订单时国内订单与海外发货单、PO 都查）
_DOMAIN_ALIAS = {(Domain.OVERSEAS, "orders"): "delivery"}
#: 第 5 条前半：详情只要这几项时并进前一步的清单（设计 §5.3 第 5 条）
REASON_ASPECTS = ("原因", "措施", "处理结果")
#: 「其他:X」里说到这几项、又是「物料」单时，按「物料」单的规则说明（国内「物料标识与关联订单」）
_MATERIAL_WORDS = ("物料", "机型", "影响数量", "产品在制属性")

#: 问「完整信息」「所有字段」（决策 2026-11-06「问完整信息时给整张详情」）。「完整处理过程」不在其中
_EVERYTHING = re.compile(r"(完整|全部|所有|整张|详细)的?(信息|字段|内容|详情|资料|栏目)")
#: 看用户有没有点到某一项：问句里的说法（缺省就是这一项本身）
_SAID_AS: dict[str, tuple[str, ...]] = {
    "可能原因": ("可能原因", "可能问题原因", "可能的问题原因"), "5Why": ("5Why", "五问"),
    "完整处理过程": ("处理过程", "操作记录", "流转记录", "处理步骤"), "设计更改": ("设计更改", "设计变更"),
    "停线与重启": ("停线", "重启"),
}
#: 包含这一项、意思却不同的说法，先从问句里去掉（「可能问题原因」不是「原因」，「可能问题物料」不是「物料」）
_SHADOWED: dict[str, tuple[str, ...]] = {
    "原因": ("可能问题原因", "可能的问题原因", "可能原因", "原因分类"),
    "物料": ("可能问题物料", "可能的问题物料"),
    "订单": ("其他在线订单",),
    "责任人": ("当前责任人",),
}
#: 「其他:X」说到的块（不在 ASPECTS 里的叫法，长的在前）：说法 → 块。本域没有这一块时按 `DETAIL_ABSENT` 说明
_BLOCK_WORDS: tuple[tuple[str, str], ...] = (
    ("可能的问题物料", "possible_inv"), ("可能问题物料", "possible_inv"), ("可能的问题原因", "possible_reasons"),
    ("可能问题原因", "possible_reasons"), ("生产订单", "orders"), ("小板订单", "orders"),
)
_DOMAIN_BLOCK_WORDS: dict[Domain, tuple[tuple[str, str], ...]] = {Domain.BRAZIL: (("库存", "stock"),)}
#: 本域不在查询范围的几项（国内「查询范围」、海外「不做」）：(说到的词, 同时出现就不算的词) → 说明
_OUT_OF_SCOPE: dict[Domain, tuple[tuple[str, tuple[str, ...], str], ...]] = {
    Domain.DOMESTIC: (("库存", (), errors.CN_IQC_STOCK), ("CKD", (), errors.CN_IQC_STOCK),
                      ("在线", ("订单", "数量"), errors.CN_IQC_STOCK), ("风险订单", (), errors.CN_RISK_ORDERS)),
    Domain.OVERSEAS: (("库存", (), errors.OS_OUT_OF_SCOPE), ("在线", ("订单",), errors.OS_OUT_OF_SCOPE),
                      ("退货单号", (), errors.OS_OUT_OF_SCOPE)),
}
#: 各域单张单详情的环节名（说到环节、这张单上没有这一块时说这张单上没有它的内容）
_STAGE_NAMES = tuple(dict.fromkeys([*enums.CN_DETAIL_STAGES.values(), *errors.DETAIL_TEXTS["br_stages"],
                                    *enums.OS_STAGES]))


def _norm(text: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).lower()


def asks_everything(query: str) -> bool:
    """问句要这张单的完整信息、所有字段（决策 2026-11-06「问完整信息时给整张详情」）。"""
    return bool(_EVERYTHING.search(unicodedata.normalize("NFKC", query or "")))


def named_aspects(aspects: Sequence[str], query: str) -> list[str]:
    """问完整信息时只留用户点到的项：「其他:X」与列表外的词照留（模型照用户的话写的）；列表里的项要在问句里说到，
    模型把整份列表抄上的不算。"""
    q = _norm(query)
    out: list[str] = []
    for a in aspects:
        if a not in ASPECT_BLOCKS:
            out.append(a)
            continue
        text = q
        for longer in _SHADOWED.get(a, ()):
            text = text.replace(_norm(longer), "")
        if any(_norm(w) in text for w in _SAID_AS.get(a, (a,))):
            out.append(a)
    return out


@dataclass
class Target:
    domain: Domain
    number: str | None = None
    pid: int | None = None


def aspects_of(step: dict) -> list[str]:
    return [str(a).strip() for a in schema.as_list((step.get("params") or {}).get("aspects")) if str(a).strip()]


def issue_value(step: dict) -> Any:
    raw = (step.get("params") or {}).get("issue")
    return schema.unwrap_ref(raw.get("value") if isinstance(raw, dict) and "value" in raw else raw)


def only_reasons(step: dict) -> bool:
    """只要原因或措施（第 5 条前半的判据）。"""
    asp = aspects_of(step)
    return bool(asp) and all(a in REASON_ASPECTS for a in asp)


def literal_targets(step: dict) -> tuple[list[Target], list[str]]:
    """计划里写的单号（可能写成几个）：(要看的单, 写法不对的提示)。"""
    value = issue_value(step)
    if schema.is_ref(value):
        return [], []
    out: list[Target] = []
    problems: list[str] = []
    for raw in schema.as_list(value):
        got = numbers.issue_number(str(raw))
        if isinstance(got, str):
            problems.append(got)
        else:
            out.append(Target(domain=got[1], number=got[0]))
    return out, problems


def ref_targets(step: dict, refs: Mapping[str, Any]) -> tuple[list[Target], bool]:
    """前一步给的单：(要看的单, 是否还有没给出详情的)。"""
    value = issue_value(step)
    got = refs.get(value["ref"]) if schema.is_ref(value) else None
    out: list[Target] = []
    if isinstance(got, dict) and "domain" in got and "id" in got:  # max_defect_rate_issue
        dom = _BY_LABEL.get(str(got["domain"]))
        if dom is not None:
            out.append(Target(domain=dom, number=str(got.get("number") or "") or None, pid=int(got["id"])))
        return out, False
    if isinstance(got, dict):  # issues：{域: {ids, numbers}}
        for label, item in got.items():
            dom = _BY_LABEL.get(str(label))
            if dom is None or not isinstance(item, dict):
                continue
            out += [Target(domain=dom, pid=int(i)) for i in item.get("ids") or []]
    return out[:DETAIL_MAX], len(out) > DETAIL_MAX


# ---------------------------------------------------------------------------- 取数与沙箱


def _put(frames: dict[str, pd.DataFrame], name: str, frame: pd.DataFrame) -> None:
    have = frames.get(name)
    if have is None or len(have) == 0:
        frames[name] = frame
    elif len(frame) and have is not frame:
        frames[name] = pd.concat([have, frame], ignore_index=True)


async def gather_frames(T: Any, jobs: Mapping[Domain, Any]) -> tuple[dict[str, pd.DataFrame], list[Domain],
                                                                       list[Domain], list[Domain]]:
    """各域并行取数：(帧, 取到的域, 撞上 TableDenied 的域, 取数出错的域)。几个域都取的帧拼成一个。"""
    async def one(d: Domain, job: Any) -> tuple[Domain, Any]:
        try:
            return d, await job
        except TableDenied as exc:
            logger.warning("factory_issue_table_denied", domain=d.value, error=type(exc).__name__)
            return d, "denied"
        except Exception as exc:  # noqa: BLE001 —— 权限配置漂移、spec 缺陷等：这一域答查不到，异常只进日志
            logger.error("factory_issue_fetch_failed", domain=d.value, error=type(exc).__name__,
                         detail=str(getattr(exc, "detail", ""))[:200])
            return d, "failed"

    frames: dict[str, pd.DataFrame] = {}
    ok, denied, failed = [], [], []
    for d, got in await asyncio.gather(*(one(d, job) for d, job in jobs.items())):
        if isinstance(got, dict):
            for name, frame in got.items():
                _put(frames, name, frame)
            ok.append(d)
        elif got == "denied":
            denied.append(d)
        else:
            failed.append(d)
    return frames, ok, denied, failed


async def _analysis(ctx: Any) -> dict[str, list[Any]]:
    seg = await config_files.load(ctx, SEGMENTATION)
    return {"codes": list(seg.domestic_codes), "names": list(seg.overseas_names)}


async def detail_params(T: Any, domains: Sequence[Domain], targets: Sequence[Target], mode: str = "detail"
                        ) -> dict[str, Any]:
    by: dict[str, dict[str, list[Any]]] = {}
    for t in targets:
        item = by.setdefault(t.domain.label, {"numbers": [], "ids": []})
        if t.pid is not None:
            item["ids"].append(int(t.pid))
        elif t.number:
            item["numbers"].append(t.number.upper())
    return {"mode": mode, "domains": [d.label for d in domains], "targets": by,
            "enums": {d.label: ADAPTERS[d].enum_params() for d in domains},
            "names": {d.label: columns.view_columns(d) for d in domains},
            "desc": {d.label: columns.DESC_UNAVAILABLE for d in domains},
            "labels": columns.DETAIL, "texts": errors.DETAIL_TEXTS, "car": bool(T.access.car),
            "analysis": await _analysis(T.ctx), "table_rows": T.answer.table_rows}


async def fetch_tickets(T: Any, targets: Sequence[Target], mode: str = "detail"
                        ) -> tuple[list[dict[str, Any]] | None, list[Domain], list[Domain]]:
    """取数并跑一次沙箱：(各单的块或 reasons 结果；沙箱失败为 None, 撞上 TableDenied 的域, 取数出错的域)。"""
    doms = [d for d in DOMAINS if any(t.domain is d for t in targets)]
    jobs = {}
    for d in doms:
        mine = [t for t in targets if t.domain is d]
        ids = [int(t.pid) for t in mine if t.pid is not None]
        nums = [str(t.number) for t in mine if t.pid is None and t.number]
        if ids and nums:  # 编号与单 ID 混着给时（不常见）分两次取再拼
            jobs[d] = _two(T, d, nums, ids)
        else:
            jobs[d] = ADAPTERS[d].detail_fetch(T.ctx, ADAPTERS[d].issue_step(nums, ids), T.master,
                                               car=bool(T.access.car))
    frames, ok, denied, failed = await gather_frames(T, jobs)
    for d in denied:
        T.access = T.access.without(d)
    if domestic.CAR_DENIED in frames:  # 报告表取数时被拒：以拒绝为准，只当没有 CAR 报告权限
        T.access = dataclasses.replace(T.access, car=False)
    if not ok:
        return [], denied, failed
    P = await detail_params(T, ok, [t for t in targets if t.domain in ok], mode)
    outcome = await runner.run(T.ctx, "detail", frames, P)
    if not outcome.ok:
        return None, denied, failed
    res = outcome.result or {}
    return list(res.get("reasons" if mode == "reasons" else "tickets") or []), denied, failed


async def _two(T: Any, d: Domain, nums: Sequence[str], ids: Sequence[int]) -> dict[str, pd.DataFrame]:
    A = ADAPTERS[d]
    a, b = await asyncio.gather(A.detail_fetch(T.ctx, A.issue_step(nums, ()), T.master, car=bool(T.access.car)),
                                A.detail_fetch(T.ctx, A.issue_step((), ids), T.master, car=bool(T.access.car)))
    out: dict[str, pd.DataFrame] = {}
    for got in (a, b):
        for name, frame in got.items():
            _put(out, name, frame)
    return out


# ---------------------------------------------------------------------------- 呈现


def blocks_for(ticket: dict[str, Any], aspects: Sequence[str], full: bool = False
               ) -> tuple[list[str], list[str], list[str]]:
    """(要给的块, 本域没有的项的说明, 「其他:X」里对上的标签)。没说要看什么时给整张详情；`full`（问完整信息）时先给
    整张详情，再按 `aspects`（已经只留用户点到的，`named_aspects`）补上整张详情里没有的。"""
    dom = _BY_LABEL[ticket["domain"]]
    blocks = ticket["blocks"]
    if not aspects:
        return list(ticket["order"]), [], []
    keys: list[str] = list(ticket["order"]) if full else []
    notes: list[str] = []
    labels: list[str] = []
    for a in aspects:
        if a not in ASPECT_BLOCKS:  # 「其他在线订单」也以「其他」开头，先认列表里的项
            said = (a.partition(":")[2] or a.partition("：")[2] or a) if a.startswith("其他") else a
            _other(ticket, dom, said, keys, notes, labels)
            continue
        for key in ASPECT_BLOCKS[a]:
            key = _DOMAIN_ALIAS.get((dom, key), key)
            if key == "process" and dom is Domain.BRAZIL:
                keys += ["process", *[k for k in ticket["order"] if k.startswith("stage:")]]
            elif key in blocks:
                keys.append(key)
            else:
                notes.append(errors.DETAIL_ABSENT.get((dom.label, key), errors.ticket_lacks(a)))
    return list(dict.fromkeys(keys)), list(dict.fromkeys(notes)), labels


#: 只说「供应商」时连供应商编号一起给（总述「三域共用的说法」）
_ALONG = {"ven_name": ("ven_code",)}


def _other(ticket: dict[str, Any], dom: Domain, said: str, keys: list[str], notes: list[str],
           labels: list[str]) -> None:
    """「其他:X」与不在 ASPECT_BLOCKS 里的项（总述「本助手管不着的问题、看不懂的输入」点名数据项一条）：

    1. 对上显示名或术语表（`columns.resolve`）：本域有就给这张单上的值，各块里没有这一栏时（没填就不显示的栏）
       照「一单一行」的值给，物料问题的责任归属部门说明不展示；本域没有就说明本域没有，巴西、海外的责任归属部门
       按问题跟进部门给。
    2. 本域不在查询范围的几项（国内 IQC 部分的库存、在线、CKD 机型，风险订单；海外的其他在线、库存、退货单号）
       说明请到管理页面查看。
    3. 说到块名（「生产订单」「可能问题物料」）或环节名（「SQE跟进」）：这张单有这一块就给，没有就说明。
    4. 再在各块的标签里找说到的栏（「影响数量为何为空」），「物料」单说到机型、影响数量等按「物料」单的规则说明。
    5. 都对不上才说制程问题单上没有这项信息。
    """
    material_words = bool(ticket.get("material")) and any(w in said for w in _MATERIAL_WORDS)
    key = columns.resolve(said)
    if key is None and _special(ticket, dom, said, keys, notes):
        return
    if key is not None:
        names = columns.view_columns(dom)
        values = ticket.get("values") or {}
        shown = {f[0] for b in ticket["blocks"].values() for f in b["fields"]}
        if key == "resp_dept" and dom is not Domain.DOMESTIC:
            notes.append(errors.RESP_DEPT_AS_FOLLOW.format(domain=dom.label))
            key = "follow_dept"
        if key not in names:
            notes.append(errors.domain_lacks(dom.label, columns.shown(key)))
        elif key == "resp_dept" and values.get(names[key]) == "—":
            notes.append(errors.RESP_DEPT_MATERIAL)
        else:
            for k in (key, *_ALONG.get(key, ())):
                label = names.get(k)
                # 「物料」单不展示的栏（影响数量等）不从「一单一行」的值里补，按「物料」单的规则说明
                if label is not None and (label in shown or (label in values and not material_words)) \
                        and label not in labels:
                    labels.append(label)
        if material_words and "machine" not in keys:
            keys.append("machine")
        return
    hit = [f[0] for b in ticket["blocks"].values() for f in b["fields"] if f[0] and f[0] in said]
    if hit:
        labels += [x for x in hit if x not in labels]
    elif not material_words:
        notes.append(errors.not_available(said))
    if material_words and "machine" not in keys:
        keys.append("machine")


def _special(ticket: dict[str, Any], dom: Domain, said: str, keys: list[str], notes: list[str]) -> bool:
    """`_other` 第 2、3 步：不在查询范围的项、块名与环节名。对上了返回 True。"""
    s = _norm(said)
    for word, unless, note in _OUT_OF_SCOPE.get(dom, ()):
        if _norm(word) in s and not any(_norm(u) in s for u in unless):
            notes.append(note)
            return True
    blocks = ticket["blocks"]
    for word, key in (*_DOMAIN_BLOCK_WORDS.get(dom, ()), *_BLOCK_WORDS):
        if _norm(word) in s:
            if key in blocks:
                keys.append(key)
            else:
                notes.append(errors.DETAIL_ABSENT.get((dom.label, key), errors.ticket_lacks(said)))
            return True
    stages = [k for k, b in blocks.items() if k.startswith("stage:") and b.get("title") and _norm(b["title"]) in s]
    if stages:
        keys += stages
        return True
    if any(_norm(n) in s for n in _STAGE_NAMES):
        notes.append(errors.ticket_lacks(said))
        return True
    return False


def _value(field: Sequence[Any], sites: Any) -> str:
    if len(field) > 2 and field[2]:
        return "、".join(links.attachment(sites, name, doc_id) for doc_id, name in field[2])
    return str(field[1])


def _field_line(field: Sequence[Any], sites: Any, car: tuple[Any, Any] | None) -> str:
    label = str(field[0])
    value = _value(field, sites)
    if car is not None and value == str(car[1]) and label == columns.shown("car"):
        value = links.car(sites, car[1], car[0])
    if "\n" in value:
        body = "\n".join("  " + line for line in value.split("\n"))
        return f"- **{label}**：\n{body}"
    return f"- **{label}**：{value}"


def _car_note(item: Mapping[str, Any]) -> bool:
    return item.get("car_id") is not None and errors.CAR_NOT_PERMITTED in str(item.get("text") or "")


def reason_body(item: Mapping[str, Any]) -> str:
    """表格里「原因与措施」一格要浓缩的那部分（沙箱 `mode=reasons` 的一项）：要附报告链接的那句说明不在里面，
    由 `reason_cell` 照原样接上（决策 2026-11-04「表格里的原因与措施给摘要」）。"""
    text = str(item.get("text") or "")
    if not _car_note(item):
        return text
    parts = [p for p in text.split("；") if p.strip() and p.strip() != errors.CAR_NOT_PERMITTED]
    return "；".join(parts)


def reason_cell(item: Mapping[str, Any], sites: Any, body: str | None = None) -> str:
    """表格里「原因与措施」一格：`body` 是摘要（不给时用沙箱合成的原文）；没有 CAR 报告权限时那句说明后附报告链接，
    与详情块同一做法（总述「原因与措施怎么给」）。"""
    text = str(item.get("text") or "") if body is None else body
    if not _car_note(item):
        return text
    link = links.car(sites, item.get("car_text") or columns.shown("car"), item.get("car_id"))
    note = f"{errors.CAR_NOT_PERMITTED}：{link}"
    if errors.CAR_NOT_PERMITTED in text:
        return text.replace(errors.CAR_NOT_PERMITTED, note, 1)
    return f"{text}；{note}" if text else note


def _table_event(table: dict[str, Any], title: str, sites: Any) -> Event:
    rows = [list(r) for r in table.get("rows") or []]
    col = table.get("link_col")
    for row, docs in zip(rows, table.get("docs") or [], strict=False):
        if col is not None and docs:
            row[col] = "、".join(links.attachment(sites, name, doc_id) for doc_id, name in docs)
    return Event.table(list(table.get("columns") or []), rows, title=title)


def render(ticket: dict[str, Any], keys: Sequence[str], notes: Sequence[str], labels: Sequence[str],
           aspects: Sequence[str], sites: Any, head_note: str | None = None, full: bool = False) -> list[Event]:
    """一张单的事件：抬头一行，再按块给；表格单独成事件。`full`（问完整信息）时点到的栏放在整张详情之后，
    各块里已经给过的不再给。"""
    dom = _BY_LABEL[ticket["domain"]]
    blocks = ticket["blocks"]
    lines = [f"**{dom.label} {links.issue(sites, dom, ticket['number'], ticket['id'])}**"]
    if head_note:
        lines.append(head_note)
    events: list[Event] = []

    def flush() -> None:
        if lines:
            events.append(Event.delta("\n".join(lines) + "\n\n"))
            lines.clear()

    seen: set[str] = set()  # 几块里重复的同一项（同标签同值）、同一张表只给一次

    def once(text: str) -> bool:
        if text in seen:
            return False
        seen.add(text)
        return True

    def named_fields() -> None:  # 各块里的栏优先（带附件、链接）；块里没有的取「一单一行」的值（`blocks_for`）
        fields: dict[str, Sequence[Any]] = {k: [k, v] for k, v in (ticket.get("values") or {}).items()}
        fields.update({f[0]: f for b in blocks.values() for f in b["fields"]})
        got = [line for line in (_field_line(fields[x], sites, None) for x in labels if x in fields) if once(line)]
        if got and full and lines and lines[-1]:
            lines.append("")
        lines.extend(got)

    if labels and not full:
        named_fields()
    for key in keys:
        b = blocks.get(key)
        if b is None:
            continue
        car = (b.get("car_id"), b.get("car_text")) if b.get("car_id") is not None else None
        body = [line for line in (_field_line(f, sites, car) for f in b["fields"]) if once(line)]
        notes_b = []
        for note in b["notes"]:
            has_car_field = any(f[0] == columns.shown("car") for f in b["fields"])
            if car is not None and note == errors.CAR_NOT_PERMITTED and not has_car_field:
                note = f"{note}：{links.car(sites, car[1], car[0])}"
            if once(note):
                notes_b.append(note)
        tables = [t for t in b["tables"] if once(repr((t.get("title"), t.get("columns"), t.get("rows"))))]
        if b.get("title") and key != "header" and (body or notes_b):
            lines.append(f"\n**{b['title']}**")
        lines += body
        if notes_b:
            _gap(lines)
            lines += notes_b
        for table in tables:
            if table.get("total", 0) > table.get("shown", 0):
                lines.append(f"共 {table['total']} 条，表格列出前 {table['shown']} 条。")
            flush()
            events.append(_table_event(table, f"{dom.label} {ticket['number']} {table['title']}", sites))
        lines += _tail_lines(b, key, keys, blocks, sites, once)
    if labels and full:
        named_fields()
    tail: list[str] = []
    if "驳回" in aspects:
        n = (ticket.get("facts") or {}).get("驳回次数")
        if isinstance(n, int):
            tail.append(f"处理过程里驳回过 {n} 次。" if n else "处理过程里没有驳回记录。")
    tail += [_sentence(n) for n in notes if once(n)]
    if tail:  # 另起一段；几句时列成要点，不接在上一块最后一项后面
        if lines and lines[-1]:
            lines.append("")
        lines += tail if len(tail) == 1 else [f"- {x}" for x in tail]
    flush()
    return events


def _gap(lines: list[str]) -> None:
    """上一行是列表项（或列表项里换行的内容）时空一行，免得接下来的说明被并进那一项。"""
    if lines and lines[-1].startswith(("- ", "  ")):
        lines.append("")


def _sentence(text: str) -> str:
    return text if text.endswith(("。", "！", "？", "）", "」")) else f"{text}。"


def _tail_lines(b: dict[str, Any], key: str, keys: Sequence[str], blocks: Mapping[str, Any], sites: Any,
                once: Any) -> list[str]:
    """块的 `tail`（排在表格之后的几行，现在只有巴西费用下的扣款）。本轮要给的别的块里已有同一栏时不给，
    留给那一块（整张详情时扣款在责任人确认里与费用转嫁、扣款单号一起给）。"""
    tail = b.get("tail") or {}
    elsewhere = {f[0] for k in keys if k != key and k in blocks for f in blocks[k]["fields"]}
    fields = [f for f in tail.get("fields") or [] if f[0] not in elsewhere]
    out = [line for line in (_field_line(f, sites, None) for f in fields) if once(line)]
    return (out + [n for n in tail.get("notes") or [] if once(n)]) if out else []


def caliber_items(ticket: dict[str, Any], keys: Sequence[str]) -> list[str]:
    """给了合计、次数时的统计口径（没有数字结论时不附，设计 §4.3）。"""
    out = []
    blocks = ticket["blocks"]
    if "delivery" in keys and blocks.get("delivery", {}).get("tables"):
        out.append("订单数量合计：该单各行发货单的订单数量之和")
    cost = blocks.get("cost", {})
    if "cost" in keys and cost.get("tables"):
        debit = "；扣款单独列出、未计入费用" if (cost.get("tail") or {}).get("fields") else ""
        out.append(f"费用：只合计费用明细，美元、雷亚尔分别合计，不换算、不相加{debit}")
    return out


def prefix_note(target: Target, asked: Sequence[Domain] | None) -> str | None:
    """单号前缀与用户点的域不一致时点出这是哪个域的单（总述「按编号查单」）。"""
    if not asked or target.domain in asked or not target.number:
        return None
    return f"{target.number} 是{target.domain.label}的单，按{target.domain.label}查。"
