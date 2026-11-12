"""显式请求时按本轮最后一个已执行结果补充证据分析（G106）。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from forge_core.events import Event

from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.present import deep_analysis as present_deep
from factory_issue_module.skills import issue_detail

logger = structlog.get_logger(__name__)
_BY_LABEL = {domain.label: domain for domain in DOMAINS}
ANALYZABLE_SKILLS = ("list_issues", "aggregate", "text_search", "custom_stats", "lookup_numbers", "issue_detail")

_SKILL_NAMES = {
    "list_issues": "清单",
    "aggregate": "汇总统计",
    "text_search": "按文字查找",
    "custom_stats": "临时统计",
    "lookup_numbers": "按编号查单",
    "issue_detail": "单张单详情",
}


def _targets(run: Any, out: Any, access: Any) -> list[issue_detail.Target]:
    """依据本步已返回的单据 ID 选证据：确定性关注单优先，再按结果顺序补齐。"""
    if run.skill == "issue_detail":
        raw = (out.refs or {}).get(f"{run.sid}.shown") or []
        candidates: dict[str, list[tuple[int, str]]] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            domain = str(item.get("domain") or "")
            try:
                record_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            number = str(item.get("number") or "")
            candidates.setdefault(domain, []).append((record_id, number))
    else:
        raw = (out.refs or {}).get(f"{run.sid}.issues") or {}
        if not isinstance(raw, Mapping):
            return []
        # 文字查找的「可能相关」组不作证据；类似问题只传回本轮展示的相近问题。
        selected = (out.digest or {}).get("analysis_issues")
        use_selected = isinstance(selected, Mapping)
        candidates = {}
        for label, result in raw.items():
            if not isinstance(result, Mapping):
                continue
            domain = str(label)
            ids = list(result.get("ids") or [])
            numbers = list(result.get("numbers") or [])
            keep = ({int(x) for x in (selected.get(domain) or []) if _is_int(x)}
                    if use_selected else None)
            members: list[tuple[int, str]] = []
            for index, record_id in enumerate(ids):
                if not _is_int(record_id) or (keep is not None and int(record_id) not in keep):
                    continue
                number = str(numbers[index]) if index < len(numbers) else ""
                members.append((int(record_id), number))
            candidates[domain] = members

    focus_raw = (out.digest or {}).get("focus") or []
    focus: list[tuple[str, int]] = []
    if isinstance(focus_raw, Sequence) and not isinstance(focus_raw, (str, bytes)):
        for item in focus_raw:
            if not isinstance(item, Mapping):
                continue
            domain = str(item.get("dom") or item.get("域") or item.get("domain") or "")
            record_id = item.get("id")
            if _is_int(record_id):
                focus.append((domain, int(record_id)))

    output: list[issue_detail.Target] = []
    selected: dict[str, set[int]] = {domain.label: set() for domain in DOMAINS}
    by_domain = {domain.label: {record_id: number for record_id, number in candidates.get(domain.label, [])}
                 for domain in DOMAINS}

    def add(domain: Domain, record_id: int) -> bool:
        if (record_id not in by_domain[domain.label]
                or record_id in selected[domain.label]
                or len(selected[domain.label]) >= present_deep.MAX_TICKETS_PER_DOMAIN
                or len(output) >= present_deep.MAX_TICKETS):
            return False
        selected[domain.label].add(record_id)
        output.append(issue_detail.Target(
            domain=domain, pid=record_id, number=by_domain[domain.label][record_id] or None,
        ))
        return True

    # 先严格保留 insights.focus 的全局顺序，再按域与结果顺序补齐稳定样本。
    for label, record_id in focus:
        domain = _BY_LABEL.get(label)
        if domain is not None and access.can(domain):
            add(domain, record_id)
        if len(output) >= present_deep.MAX_TICKETS:
            return output
    for domain in DOMAINS:
        if not access.can(domain):
            continue
        for record_id, _number in candidates.get(domain.label) or []:
            add(domain, record_id)
            if len(output) >= present_deep.MAX_TICKETS:
                return output
    return output


def _is_int(value: Any) -> bool:
    return isinstance(value, int) or (isinstance(value, str) and value.isdigit())


def _stats(run: Any, out: Any) -> Any:
    digest = out.digest or {}
    if digest.get("analysis_stats") is not None:
        return digest["analysis_stats"]
    segments = digest.get("segs") or []
    if segments:
        return [
            {key: segment.get(key) for key in ("domain", "title", "name", "found", "facts") if key in segment}
            for segment in segments if isinstance(segment, Mapping)
        ]
    tickets = digest.get("tickets") or []
    if tickets:
        return [{"domain": ticket.get("domain"), "number": ticket.get("number"),
                 "facts": ticket.get("facts") or {}}
                for ticket in tickets if isinstance(ticket, Mapping)]
    found = (out.refs or {}).get(f"{run.sid}.found")
    return {"各域单数": dict(found)} if isinstance(found, Mapping) else {}


def _ordered_tickets(targets: Sequence[issue_detail.Target], tickets: Sequence[Mapping[str, Any]]) \
        -> list[Mapping[str, Any]]:
    by_key: dict[tuple[str, int], Mapping[str, Any]] = {}
    for ticket in tickets:
        try:
            key = (str(ticket.get("domain") or ""), int(ticket.get("id")))
        except (TypeError, ValueError):
            continue
        by_key[key] = ticket
    return [by_key[(target.domain.label, int(target.pid))]
            for target in targets if target.pid is not None and (target.domain.label, int(target.pid)) in by_key]


async def events_for(T: Any, run: Any, out: Any, request: present_deep.Request) -> list[Event]:
    """给当前步骤的记录证据附加一段；出错只降级，不影响已发出的正式结果。"""
    if not request.active or not out.ok:
        return []
    try:
        if not out.found_any:
            # 全域无权时原结果已说明权限限制，不再补一句看似「查无记录」的分析结论。
            if not out.domains:
                return []
            return [present_deep.no_results(request)]
        if run.stored is not None:
            return [present_deep.skipped_previous(request)]

        targets = _targets(run, out, T.access)
        if not targets:
            return [present_deep.no_evidence(request)]

        denied, failed = (), ()
        if run.skill == "issue_detail":
            tickets = _ordered_tickets(targets, (out.digest or {}).get("tickets") or [])
        else:
            fetched, denied, failed = await issue_detail.fetch_tickets(T, targets)
            if denied or failed:
                logger.info("factory_issue_deep_analysis_evidence_incomplete", denied=len(denied), failed=len(failed))
            tickets = _ordered_tickets(targets, fetched or [])

        evidence = present_deep.evidence_from_tickets(tickets)
        ticket_keys = {(str(ticket.get("domain") or ""), int(ticket["id"])) for ticket in tickets}
        evidence_keys = {(item.domain, item.record_id) for item in evidence}

        def label(target: issue_detail.Target) -> str:
            return f"{target.domain.label} {target.number}" if target.number else f"{target.domain.label}所选记录"

        not_read = list(dict.fromkeys(
            label(target) for target in targets
            if target.pid is not None and (target.domain.label, int(target.pid)) not in ticket_keys
        ))
        no_text = list(dict.fromkeys(
            label(target) for target in targets
            if target.pid is not None and (target.domain.label, int(target.pid)) in ticket_keys
            and (target.domain.label, int(target.pid)) not in evidence_keys
        ))
        gap_parts = []
        denied_domains = [domain.label for domain in (getattr(run, "denied", None) or [])]
        if denied_domains:
            gap_parts.append("受权限限制未纳入分析的域：" + "、".join(dict.fromkeys(denied_domains)))
        if not_read:
            gap_parts.append("详情未能读取：" + "、".join(not_read))
        if no_text:
            gap_parts.append("没有可引用原文：" + "、".join(no_text))
        gap_notice = ("证据缺口：" + "；".join(gap_parts) + "。以下内容仅基于已取得的原文。"
                      if gap_parts else None)
        if not evidence:
            return [present_deep.no_evidence(request, gap_notice)]

        llm = getattr(T.ctx, "llm", None)
        generated = await present_deep.generate(
            llm, T.query, _SKILL_NAMES.get(run.skill, "查询结果"), _stats(run, out), evidence, T.entities, request,
        )
        return [present_deep.render(request, evidence, generated, T.sites, gap_notice)]
    except Exception as exc:  # noqa: BLE001 — 分析与建议是可选增补
        logger.warning("factory_issue_deep_analysis_evidence_failed", error=type(exc).__name__)
        return [present_deep.no_evidence(request, "本轮取证过程未能完整完成，未对不完整证据作判断。")]
