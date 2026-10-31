"""按号查单（设计 §4.3 `lookup_numbers` 一行、§6.3；总述「按编号查单」、国内「按订单号查单」「按 CAR 编号查单」、
海外「按发货单号、PO 查单」、巴西「投诉单号」；`privileges.md`「域闸门」）。

事件顺序：`delta` → `table` → `suggestions`（整轮）。
- 认号在第 6 步（`domains/numbers.py`）：认不出、位数不对且一个能查的号都没有时追问，不取数。
- 只可能在一个域的号、该域无权：只答「您没有该域的查看权限」，不查、不说有没有（J-P05）。可能在几个域的号只查
  有权的域，写明无权的域未查（J-P06）。
- 几个问题编号合成一张表，一号一行，列用清单默认列另加所属域与当前状态；查不到、无权的在该行注明。其余每种号
  每个域一张表，开头写按什么号找到几张、问题类型与是否结案的分布（数都来自沙箱）；料号、PN 两处都查、分开列
  （J-D03）；号是几种都没有时写明按哪几种号查过。
- 国内手填的带连字符的订单号：给的号查不到、但有以「该号-」开头的号时列出请用户选；只有这一个号时做成追问，
  按钮发回「原话（候选号）」：工作区在时直接把候选号填进计划（设计 §4.4）；工作区读不到时下一轮沙箱按问句
  末尾的号查，同样不再追问。
- 按 CAR 编号查单不需要 CAR 报告权限，不读报告表（J-P08）；CAR 编号的链接对所有用户生成。
- 一次给很多个问题编号（多于表格行数 `table_rows`，总述「按编号查单」超过约 20 个）：按清单呈现，开头给各域张数
  与合计、没找到与无权未查的号，每域一张表（域内按建单时间从新到旧，前 `table_rows` 张），全量导出成文件、
  每域一页，链接在统计口径之后（`present/export.py`）。
- 问题描述一格：本域文字查找表可用时换成摘要，导出文件给剥净后的全文；不可用时写「暂不可用」（设计 §9.2，S6b）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from forge_core.events import Event

from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.domains import base, numbers
from factory_issue_module.domains.numbers import Number
from factory_issue_module.plan import schema
from factory_issue_module.present import columns, export, links, summaries
from factory_issue_module.skills import issue_detail
from factory_issue_module.stats import runner
from factory_issue_module.turn import errors

_BY_LABEL = {d.label: d for d in DOMAINS}
HAND_REASON = "手填订单号"


def numbers_of(step: dict, query: str, asked: Sequence[Domain] | None) -> list[Number]:
    """计划里的号 → 认好的号（用户点了域时，可能在几个域的号只在点的域里查）。"""
    out = []
    for item in schema.as_list((step.get("params") or {}).get("numbers")):
        raw = item.get("raw") if isinstance(item, dict) else item
        said = item.get("kind_said") if isinstance(item, dict) else None
        if raw is None or not str(raw).strip():
            continue
        out.append(numbers.within(numbers.recognize(str(raw), said, query), asked))
    return out


def ask_of(nums: Sequence[Number]) -> base.Ask | None:
    """一个能查的号都没有、又有认不出或位数不对的：追问（§4.2 第 6 步）。"""
    if not nums or any(n.lookups or n.unsupported for n in nums):
        return None
    bad = [n for n in nums if n.problem]
    if not bad:
        return None
    question = "；".join(dict.fromkeys(str(n.problem) for n in bad)) + "。"
    first = next((n for n in bad if n.options), None)
    if first is None:
        return base.Ask(question, [], reason=bad[0].reason, fill=base.FILL_NONE)
    return base.Ask(question, list(first.options), reason=bad[0].reason, said=first.raw, fill=base.FILL_KIND_SAID)


def _plan(nums: Sequence[Number], access: Any) -> tuple[list[dict[str, Any]], dict[int, list[str]], dict[int, bool]]:
    """(要查的 [{i, kind, value, domain}], 号 → 无权未查的域, 号 → 只在一个无权的域里)。"""
    todo: list[dict[str, Any]] = []
    skipped: dict[int, list[str]] = {}
    only_denied: dict[int, bool] = {}
    for i, n in enumerate(nums):
        possible = n.possible
        denied = [d for d in possible if not access.can(d)]
        if possible and len(denied) == len(possible) and len(possible) == 1:
            only_denied[i] = True
            continue
        skipped[i] = [d.label for d in denied]
        for lk in n.lookups:
            for d in lk.domains:
                if access.can(d):
                    todo.append({"i": i, "kind": lk.kind, "value": lk.value, "domain": d.label})
    return todo, skipped, only_denied


async def run_step(T: Any, step: dict, nums: Sequence[Number], C: Any
                   ) -> tuple[list[Event], dict[str, Any], bool, base.Ask | None]:
    """(事件, 给后一步的引用, 这一步答出来了没有, 要追问时的追问)。有追问时本轮到此为止，事件为空，由编排发
    `clarify` 并写工作区 `pending_clarify`（点了候选号直接填进计划，设计 §4.4）。"""
    todo, skipped, only_denied = _plan(nums, T.access)
    events: list[Event] = []
    res: dict[str, Any] = {"sections": [], "refs": {"issues": {}}}
    failed_doms: list[str] = []
    # 问题编号多于表格行数（总述「按编号查单」超过约 20 个）：按清单呈现，全量导出
    as_list = len([n for n in nums if _issue_only(n)]) > T.answer.table_rows
    exports: dict[str, Any] = {}
    if todo:
        doms = [d for d in DOMAINS if any(x["domain"] == d.label for x in todo)]
        jobs = {}
        for d in doms:
            mine = [numbers.Lookup(x["kind"], x["value"], (d,)) for x in todo if x["domain"] == d.label]
            jobs[d] = issue_detail.ADAPTERS[d].lookup_fetch(T.ctx, mine, T.master)
        frames, ok, denied, failed = await issue_detail.gather_frames(T, jobs)
        for d in denied:
            T.access = T.access.without(d)
        failed_doms = [d.label for d in failed]
        lost = {d.label for d in (*denied, *failed)}
        for x in todo:
            if x["domain"] in {d.label for d in denied}:
                skipped.setdefault(x["i"], [])
                if x["domain"] not in skipped[x["i"]]:
                    skipped[x["i"]].append(x["domain"])
        todo = [x for x in todo if x["domain"] not in lost]
        if ok and todo:
            text_ok = [d for d in ok if d in T.access.text_search]
            P = {"domains": [d.label for d in ok], "lookups": todo,
                 "enums": {d.label: issue_detail.ADAPTERS[d].enum_params() for d in ok},
                 "names": {d.label: columns.view_columns(d) for d in ok},
                 # 文字查找表可用的域先留空，下面换成摘要（§9.2）；不可用的写「暂不可用」
                 "desc": {d.label: "" if d in text_ok else columns.DESC_UNAVAILABLE for d in ok},
                 "labels": columns.DETAIL, "chosen": base.trailing(T.query)}
            if as_list:
                P["as_list"] = {"table_rows": T.answer.table_rows}
            outcome = await runner.run(T.ctx, "lookup", frames, P, return_frames=as_list)
            if not outcome.ok:
                return [Event.delta(f"{errors.SECTION_FAILED}。")], {}, False, None
            res = outcome.result or res
            got_frames = getattr(outcome, "frames", None) or {}
            exports = {k: v for k, v in got_frames.items() if k.startswith("export_")}
            await _fill_desc(T, res, text_ok)
            if exports:
                await summaries.fill_exports(T.ctx, {**exports, **{k: v for k, v in got_frames.items()
                                                                   if k.startswith("ids_")}}, text_ok)
    sections = res.get("sections") or []
    # 只有一个号、只有手填订单号的候选：追问
    if len(nums) == 1 and sections and not any(s["found"] for s in sections):
        cands = [c for s in sections for c in s.get("candidates") or []]
        if cands:
            question = errors.hand_orders(nums[0].raw, cands[:12])
            return [], {}, True, base.Ask(question, cands[:4], reason=HAND_REASON, said=nums[0].raw,
                                          fill=base.FILL_NUMBER)
    events += _present(T, nums, sections, skipped, only_denied, failed_doms, res if as_list else None)
    if as_list and res.get("as_list"):
        # 链接放进 `T.record.exports`，在统计口径之后发（与清单导出同一处，§4.3、§9.3）
        T.record.exports.append(await export.save_lists(T.ctx, res.get("as_list_counts") or [], exports,
                                                        export.ISSUE_FILENAME))
    found = [s for s in sections if s["found"]]
    if found:
        C.domains([d for d in dict.fromkeys(s["domain"] for s in sections)],
                  [errors.not_searched(v) for v in dict.fromkeys(tuple(x) for x in skipped.values() if x)])
        C.item(errors.LOOKUP_CALIBER)
    return events, res.get("refs") or {}, True, None


async def _fill_desc(T: Any, res: Mapping[str, Any], text_ok: Sequence[Domain]) -> None:
    """问题描述一格换成摘要（一号一行的合并表、很多个号按清单呈现的表，§9.2）：本域文字查找表可用时才换。"""
    if not text_ok:
        return
    items: list[tuple[list[Any], int, Domain, int | None]] = []
    at_issue = len(_issue_columns()) - 1
    for s in res.get("sections") or []:
        dom = _BY_LABEL.get(str(s.get("domain")))
        if dom is not None:
            items += [(row, at_issue, dom, pid) for row, pid in zip(s.get("issue_rows") or [], s.get("ids") or [],
                                                                    strict=False)]
    for x in res.get("as_list") or []:
        dom = _BY_LABEL.get(str(x.get("domain")))
        cols = list(x.get("columns") or [])
        if dom is not None and columns.shown("desc", dom) in cols:
            at = cols.index(columns.shown("desc", dom))
            items += [(row, at, dom, pid) for row, pid in zip(x.get("rows") or [], x.get("ids_shown") or [],
                                                              strict=False)]
    await summaries.fill_rows(T.ctx, items, text_ok)


def _issue_only(n: Number) -> bool:
    return len(n.lookups) == 1 and n.lookups[0].kind == numbers.ISSUE


def _blank_row(number: str, domain: str, note: str) -> list[str]:
    return [number, domain, note, "—", "—", "—", "—", "—"]


def _issue_columns() -> list[str]:
    s = columns.shown
    return [s("number"), columns.OWNER_DOMAIN, s("current_state"), s("machine"), s("type"), s("rate"), s("bad_qty"),
            s("desc")]


def _distribution(sec: dict[str, Any]) -> str:
    facts = sec.get("facts") or {}
    parts = []
    types = facts.get("按问题类型") or []
    closed = facts.get("是否结案") or []
    if sec["found"] >= 2:
        if types:
            parts.append("、".join(f"{t} {n} 张" for t, n in types))
        if closed:
            parts.append("、".join(f"{t} {n} 张" for t, n in closed))
    return ("：" + "；".join(parts)) if parts else ""


def _as_list(T: Any, nums: Sequence[Number], issue_nums: Sequence[int], by_i: Mapping[int, list[dict[str, Any]]],
             only_denied: Mapping[int, bool], failed: Sequence[str], res: Mapping[str, Any]) -> list[Event]:
    """很多个问题编号按清单呈现（总述「按编号查单」超过约 20 个、「跨域规则」清单呈现）：开头给各域张数与合计，
    再写没找到、无权未查的号；每域一张表，域内按建单时间从新到旧，表格给前 `table_rows` 张（数都来自沙箱）。"""
    counts = res.get("as_list_counts") or []
    head = [f"按问题编号逐个查，共找到 {res.get('as_list_total', 0)} 张"
            + (f"：{'、'.join(f'{d} {n} 张' for d, n in counts)}" if len(counts) > 1 else "")]
    if any(x.get("found", 0) > x.get("shown", 0) for x in res.get("as_list") or []):
        head.append(f"表格每域按建单时间从新到旧列出前 {T.answer.table_rows} 张")
    missing, denied = [], []
    for i in issue_nums:
        value = nums[i].lookups[0].value
        if only_denied.get(i):
            denied.append(value)
        elif nums[i].lookups[0].domains[0].label not in failed and not any(s.get("ids") for s in by_i.get(i, [])):
            missing.append(value)
    lines = ["，".join(head) + "。"]
    if missing:
        lines.append(f"没有找到这些号（已删除的单查不到）：{'、'.join(missing)}。")
    if denied:
        lines.append(f"这些号所在的域您没有查看权限，未查：{'、'.join(denied)}。")
    events: list[Event] = [Event.delta("\n".join(lines) + "\n\n")]
    for k, x in enumerate(res.get("as_list") or []):
        dom = _BY_LABEL[str(x["domain"])]
        rows = [list(r) for r in x.get("rows") or []]
        for row, pid in zip(rows, x.get("ids_shown") or [], strict=False):
            row[0] = links.issue(T.sites, dom, row[0], pid)
        if k:
            events.append(Event.delta("\n\n"))
        events.append(Event.table(list(x.get("columns") or []), rows, title=f"{dom.label}问题单"))
    return events


def _present(T: Any, nums: Sequence[Number], sections: Sequence[dict[str, Any]], skipped: dict[int, list[str]],
             only_denied: dict[int, bool], failed: Sequence[str], as_list: Mapping[str, Any] | None = None
             ) -> list[Event]:
    """问题编号合成一张表、其余每种号每域一张表；`as_list`（沙箱按清单排好的结果）给了时问题编号按清单呈现。"""
    by_i: dict[int, list[dict[str, Any]]] = {}
    for s in sections:
        by_i.setdefault(int(s["i"]), []).append(s)
    events: list[Event] = []
    lines: list[str] = []
    if failed:
        lines.append(f"{'、'.join(failed)}：{errors.SECTION_FAILED}。")
    issue_rows: list[list[str]] = []
    issue_ids: list[tuple[Domain, int | None]] = []
    issue_nums = [i for i, n in enumerate(nums) if _issue_only(n)]
    for i in issue_nums:
        n = nums[i]
        lk = n.lookups[0]
        dom = lk.domains[0]
        sec = next(iter(by_i.get(i, [])), None)
        if only_denied.get(i):
            issue_rows.append(_blank_row(lk.value, dom.label, errors.DOMAIN_NOT_PERMITTED))
            issue_ids.append((dom, None))
        elif sec is not None and sec.get("issue_rows"):
            issue_rows.append(list(sec["issue_rows"][0]))
            issue_ids.append((dom, int(sec["ids"][0])))
        elif dom.label in failed:
            issue_rows.append(_blank_row(lk.value, dom.label, errors.SECTION_FAILED))
            issue_ids.append((dom, None))
        else:
            issue_rows.append(_blank_row(lk.value, dom.label, errors.ROW_NOT_FOUND))
            issue_ids.append((dom, None))
    if len(nums) == 1 and only_denied.get(0):  # 号只可能在一个无权的域：只答这一句，不说有没有这个号（J-P05）
        return [Event.delta(f"{errors.DOMAIN_NOT_PERMITTED}。")]
    if len(issue_nums) == 1 and len(nums) == 1:
        row, (dom, pid) = issue_rows[0], issue_ids[0]
        if only_denied.get(issue_nums[0]):
            return [Event.delta(f"{errors.DOMAIN_NOT_PERMITTED}。")]
        if pid is None:
            return [Event.delta(("\n".join(lines) + "\n\n" if lines else "") + f"{errors.issue_not_found(row[0])}。")]
    if as_list is not None and issue_rows:
        if lines:
            events.append(Event.delta("\n".join(lines) + "\n\n"))
            lines = []
        events += _as_list(T, nums, issue_nums, by_i, only_denied, failed, as_list)
    elif issue_rows:
        for row, (dom, pid) in zip(issue_rows, issue_ids, strict=True):
            row[0] = links.issue(T.sites, dom, row[0], pid)
        lines.append("按问题编号逐个查，一号一行（查不到、无权的在该行注明）：")
        events.append(Event.delta("\n".join(lines) + "\n\n"))
        lines = []
        events.append(Event.table(_issue_columns(), issue_rows, title="问题单当前状态"))
    for i, n in enumerate(nums):
        if i in issue_nums:
            continue
        if n.problem:
            lines.append(f"{n.raw}：{n.problem}。")
            continue
        if n.unsupported:
            lines.append(f"{n.raw}：{n.unsupported}。")
            continue
        if only_denied.get(i):
            lines.append(f"{n.raw}：{errors.DOMAIN_NOT_PERMITTED}。")
            continue
        mine = by_i.get(i, [])
        hit = [s for s in mine if s["found"]]
        for s in hit:
            dom = _BY_LABEL[s["domain"]]
            kind = numbers.KIND_TEXT.get(s["kind"], s["kind"])
            lines.append(errors.spaced("按", kind, f" {s['value']} 找到{dom.label} {s['found']} 张{_distribution(s)}。"))
            events.append(Event.delta("\n".join(lines) + "\n\n"))
            lines = []
            events.append(_section_table(T, s, dom, kind))
        if not hit:
            cands = [c for s in mine for c in s.get("candidates") or []]
            kinds = list(dict.fromkeys(numbers.KIND_TEXT[lk.kind] for lk in n.lookups))
            if cands:
                lines.append(errors.hand_orders(n.raw, cands[:12]))
            elif any(lk.kind == numbers.CAR for lk in n.lookups):
                lines.append(f"{n.raw}：{errors.CAR_NOT_FOUND}。")
            elif any(lk.kind == numbers.CLAIM for lk in n.lookups):
                lines.append(f"{n.raw}：{errors.CLAIM_NOT_FOUND}。")
            elif len(kinds) > 1 and not all(k in (numbers.KIND_TEXT[numbers.PROD_ORDER],
                                                  numbers.KIND_TEXT[numbers.XB_ORDER]) for k in kinds):
                lines.append(f"{errors.searched_kinds(kinds, n.raw)}。")
            else:
                extra = f"；{errors.ORDER_NOT_FOR}" if any(lk.kind == numbers.PROD_ORDER for lk in n.lookups) else ""
                lines.append(f"{n.raw}：{errors.NUMBER_NOT_FOUND}{extra}。")
        if skipped.get(i):
            lines.append(f"（{n.raw}：{errors.not_searched(skipped[i])}）")
    if lines:
        events.append(Event.delta("\n".join(lines)))
    return events


def _section_table(T: Any, s: dict[str, Any], dom: Domain, kind: str) -> Event:
    rows = [list(r) for r in s.get("rows") or []]
    cols = list(s.get("columns") or [])
    car_col = cols.index(columns.shown("car")) if s["kind"] == numbers.CAR and columns.shown("car") in cols else None
    for row, pid, car_id in zip(rows, s.get("ids") or [], s.get("car_ids") or [], strict=False):
        row[0] = links.issue(T.sites, dom, row[0], pid)
        if car_col is not None and car_id is not None:
            row[car_col] = links.car(T.sites, row[car_col], car_id)
    return Event.table(cols, rows, title=f"{kind} {s['value']}（{dom.label}）")
