"""INFO 数据权限自查：核对 `GetPrivilegesByCode?Code=FACTORY_ISSUE` 的返回结果，不连库。

用平台真实的解析（`forge_platform.auth.parse_privileges_payload`）与取数权限判定（`ScopedDataAccess`，
假连接器只记 SQL），给出本助手据此会放开什么，并对照 `docs/2_landed/privileges.md` 的配置规格指出偏差。

用法：
  uv run python scripts/privileges_check.py <文件> [--expect 国内,CAR]
      文件可以是：接口返回的整段 JSON（含 Status / Code / Data）；只有 Data 里那份权限对象；
      管理台审计页的 permissions.json；平台日志里 `info_privileges_body` 那一行（整行 JSON）。
      --expect 写这个账号申请了什么（国内 / 巴西 / 海外 / CAR，逗号分隔；一个都没有写「无」），
      不写时只按返回结果本身推断，并检查前后是否自洽。
  uv run python scripts/privileges_check.py --print 国内,CAR [--allow-variant]
      按规格生成该组合的完整返回示例（默认拒绝写法；--allow-variant 为默认允许的备选写法）。
  uv run python scripts/privileges_check.py --examples <说明文档.md>
      逐个核对文档里以 `<!-- 自查：国内,CAR -->` 标注的 json 代码块，全部符合才退出码为 0。

退出码：0 = 没有「错误」且与 --expect 一致；1 = 有错误或不一致；2 = 输入读不了。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import structlog
from forge_core.dataquery import QuerySpec
from forge_core.errors import ForgeError, PermissionDenied, TableDenied
from forge_core.permissions.agentnode import AgentNode
from forge_data import DataSourceRegistry, ScopedDataAccess
from forge_data.datasources.base import ParamStyle
from forge_data.scopefilter import Dialect
from forge_platform.auth import parse_privileges_payload

from factory_issue_module.declarations import (
    CAR_TABLE,
    DOMAINS,
    ERP,
    FACTORY_TABLE,
    INFO,
    MART,
    MODULE_CODE,
    SHARED_TABLES,
    TASK_TABLE,
    Domain,
)
from factory_issue_module.module import FactoryIssueModule
from factory_issue_module.turn import gate

MANIFEST = FactoryIssueModule.manifest

CAR = "CAR"
GRANT_LABELS = {Domain.DOMESTIC: "国内", Domain.BRAZIL: "巴西", Domain.OVERSEAS: "海外"}
OPEN_ROW = {"mode": "DENY", "logic": "OR", "rules": []}
OPEN_COLUMN = {"mode": "DENY", "rules": []}
TASK_NAMES = ("ZCTracking_ProblemSoftware3", "ZCTracking_PreventionConfirm")
TASK_ROW = {"mode": "ALLOW", "logic": "OR", "rules": [{"logic": "AND", "conditions": [
    {"field": "ftable", "operator": "IN", "value": list(TASK_NAMES)}]}]}
_RELATION = {Domain.DOMESTIC: ("ID", "ProblemId"), Domain.BRAZIL: ("ID", "ProblemID"),
             Domain.OVERSEAS: ("Id", "ProblemId")}
_INSTANCE = {INFO: "info", ERP: "erp", MART: "mart"}

ERROR, OFF_SPEC, NOTE = "错误", "不符合规格", "提示"


# ---------------------------------------------------------------- 41 张表与「何时给允许」


@dataclass(frozen=True)
class Table:
    name: str  # 四段名（规格写法）
    alias: str  # 本助手取数用的数据源
    query_name: str  # 本助手取数时写的表名
    kind: str  # master / sub / outer
    label: str  # 给人看的说明
    parent: Domain | None = None  # 子表挂在哪个域的主表下

    @property
    def tail(self) -> str:
        return self.name.split(".")[-1]


def _four(alias: str, declared: str) -> str:
    if alias == MART:
        return f"mart.{MART}.public.{declared}"
    return f"{_INSTANCE[alias]}.{declared}"


def _tables() -> list[Table]:
    out: list[Table] = []
    for d in DOMAINS:
        out.append(Table(_four(INFO, d.master_table), INFO, d.master_table, "master", f"{d.label}主表"))
    for d in DOMAINS:
        out += [Table(_four(INFO, t), INFO, t, "sub", f"{d.label}子表", parent=d) for t in d.sub_tables]
    lookups = [
        ("info.dbo.Brazil_Factory", "巴西工厂表"), ("info.dbo.Brazil_RequestList", "巴西申请单表"),
        ("CoreINFO.dbo.AfterSaleIssueClass", "现象分类表"),
        ("CoreINFO.dbo.AfterSaleIssueClassPhenomenon", "现象主数据表"),
        ("CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason", "现象可能原因表"),
    ]
    out += [Table(_four(INFO, t), INFO, t, "outer", label) for t, label in lookups]
    out += [Table(_four(INFO, t), INFO, t, "outer", "共用主数据") for t in SHARED_TABLES]
    out.append(Table(_four(ERP, FACTORY_TABLE), ERP, FACTORY_TABLE, "outer", "共用主数据"))
    out.append(Table(_four(INFO, TASK_TABLE), INFO, TASK_TABLE, "outer", "流程待办任务表"))
    out.append(Table(_four(INFO, CAR_TABLE), INFO, CAR_TABLE, "outer", "CAR 报告表"))
    for d in DOMAINS:
        out += [Table(_four(MART, t), MART, t, "outer", f"{d.label}文字查找表") for t in d.mart_tables]
    return out


TABLES = _tables()
BY_TAIL = {t.tail: t for t in TABLES}
assert len(TABLES) == 41, len(TABLES)


def allowed(t: Table, grants: frozenset[str]) -> bool:
    """`privileges.md`「权限里要列出的表」的「何时给允许」一列。"""
    doms = {d for d in DOMAINS if GRANT_LABELS[d] in grants}
    if t.kind == "master":
        return any(t.query_name == d.master_table for d in doms)
    if t.kind == "sub":
        return t.parent in doms
    tail = t.tail
    if tail in ("Brazil_Factory", "Brazil_RequestList"):
        return Domain.BRAZIL in doms
    if tail == "AfterSaleIssueClass":
        return Domain.DOMESTIC in doms
    if tail in ("AfterSaleIssueClassPhenomenon", "AfterSaleIssueClassPhenomenonReason"):
        return bool(doms & {Domain.DOMESTIC, Domain.OVERSEAS})
    if t.query_name == TASK_TABLE:
        return Domain.DOMESTIC in doms
    if t.query_name == CAR_TABLE:
        return CAR in grants
    if t.alias == MART:
        return any(tail in d.mart_tables for d in doms)
    return bool(doms)  # 共用主数据


# ---------------------------------------------------------------- 按规格生成示例


def _outer_item(t: Table, mode: str = "ALLOW") -> dict[str, Any]:
    body: dict[str, Any] = {"name": t.name, "mode": mode}
    if mode == "ALLOW":
        body["row"] = TASK_ROW if t.query_name == TASK_TABLE else OPEN_ROW
        body["column"] = OPEN_COLUMN
    body |= {"cell": {}, "sub_tables": []}
    return {"type": "DB", "table": body}


def _sub_item(t: Table) -> dict[str, Any]:
    parent, child = _RELATION[t.parent]  # type: ignore[index]
    return {"name": t.name, "mode": "ALLOW", "inherit_parent": True,
            "relation": {"mappings": [{"parent_field": parent, "child_field": child}]},
            "column": OPEN_COLUMN, "cell": {}, "sub_tables": []}


def build(grants: frozenset[str], *, allow_variant: bool = False) -> dict[str, Any]:
    """按规格生成 `Data`（权限对象）。默认拒绝：只列给「允许」的表；默认允许：41 张全列，不给允许的写拒绝。"""
    scope: list[dict[str, Any]] = []
    no_domain = not grants & {"国内", "巴西", "海外"}
    for t in TABLES:
        ok = allowed(t, grants)
        if t.kind == "sub":
            continue
        if not ok and not allow_variant:
            if no_domain and t.kind == "master":
                # 一个域都没申请：不能「默认拒绝 + 一张表都不列」（那等于全放开），三张主表显式写拒绝
                scope.append(_outer_item(t, "DENY"))
            continue
        item = _outer_item(t, "ALLOW" if ok else "DENY")
        if t.kind == "master":
            # 主表被拒时子表照样挂着：默认允许下子表要靠继承随主表被拒，不挂就成了「没列 = 允许」
            item["table"]["sub_tables"] = [_sub_item(s) for s in TABLES if s.kind == "sub"
                                           and s.parent and s.parent.master_table == t.query_name]
        scope.append(item)
    return {"version": "1.3", "defaultEffect": "ALLOW" if allow_variant else "DENY",
            "level": {"code": "A", "description": "可访问全部数据库数据"}, "dataScope": scope}


def envelope(data: dict[str, Any]) -> dict[str, Any]:
    return {"Status": True, "Code": 200, "Message": "", "Data": data}


def compact(obj: Any, indent: int = 0, width: int = 270) -> str:
    """短的对象写一行、长的展开：一张表一行，便于对照。"""
    one = json.dumps(obj, ensure_ascii=False)
    pad = "  " * indent
    if len(pad) + len(one) <= width or not isinstance(obj, (dict, list)) or not obj:
        return one
    inner = "  " * (indent + 1)
    if isinstance(obj, list):
        rows = [inner + compact(v, indent + 1, width) for v in obj]
        return "[\n" + ",\n".join(rows) + "\n" + pad + "]"
    rows = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {compact(v, indent + 1, width)}" for k, v in obj.items()]
    return "{\n" + ",\n".join(rows) + "\n" + pad + "}"


# ---------------------------------------------------------------- 读输入


class InputError(Exception):
    pass


def extract_response(obj: Any) -> tuple[dict[str, Any], str]:
    """返回 (接口返回的整段, 输入是什么)。只给了 Data 时补一个成功的外壳。"""
    if isinstance(obj, dict) and isinstance(obj.get("body"), str):  # 平台日志 info_privileges_body
        try:
            inner = json.loads(obj["body"])
        except ValueError as exc:
            raise InputError(f"日志里的 body 不是完整 JSON（可能被截断，日志只留前 16 KiB）：{exc}") from exc
        return extract_response(inner)[0], "平台日志 info_privileges_body"
    if isinstance(obj, dict) and isinstance(obj.get("privileges"), list):  # 审计页 permissions.json
        hits = [e for e in obj["privileges"] if isinstance(e, dict) and e.get("agent") == MODULE_CODE]
        if not hits:
            raise InputError(f"permissions.json 里没有 {MODULE_CODE} 的权限段（这一轮可能没走到本助手）")
        entry = hits[0]
        if entry.get("source") != "info_api":
            raise InputError(f"这一轮的权限不是向 INFO 拉的（来源 {entry.get('source')!r}），核对不了 INFO 的配置")
        data = entry.get("privileges")
        return envelope(data if data is not None else {}), "审计页 permissions.json（平台解析后的形状）"
    if isinstance(obj, dict) and ("Status" in obj or "Code" in obj or "Data" in obj):
        return obj, "接口返回的整段"
    if isinstance(obj, dict):
        return envelope(obj), "只有权限对象（按成功返回处理）"
    raise InputError("输入不是 JSON 对象")


def load(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    # PowerShell 的 `>` 重定向写出的是 UTF-16
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    text = raw.decode(encoding).strip()
    try:
        obj = json.loads(text)
    except ValueError:
        # 日志行前面可能带时间等前缀：取第一个 { 起的部分
        start = text.find("{")
        if start < 0:
            raise InputError("文件里找不到 JSON") from None
        try:
            obj = json.loads(text[start:])
        except ValueError as exc:
            raise InputError(f"不是合法 JSON：{exc}") from exc
    return extract_response(obj)


def parse_grants(text: str) -> frozenset[str]:
    if text.strip() in ("无", "none", ""):
        return frozenset()
    out = set()
    for part in re.split(r"[,，+、\s]+", text.strip()):
        if not part:
            continue
        key = "CAR" if part.upper().startswith("CAR") else part
        if key not in ("国内", "巴西", "海外", CAR):
            raise InputError(f"认不出「{part}」：只写 国内 / 巴西 / 海外 / CAR")
        out.add(key)
    return frozenset(out)


# ---------------------------------------------------------------- 按平台真实判定看行为


class _Connector:
    def __init__(self, name: str, dialect: Dialect, log: list[tuple[str, str, dict]]) -> None:
        self.name = name
        self.dialect = dialect
        self.param_style = ParamStyle.QMARK if dialect is Dialect.SQLSERVER else ParamStyle.PYFORMAT
        self._log = log

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        self._log.append((self.name, sql, dict(params or {})))
        return pd.DataFrame()


def scoped(privileges: Any) -> tuple[ScopedDataAccess, list[tuple[str, str, dict]]]:
    log: list[tuple[str, str, dict]] = []
    registry = DataSourceRegistry()
    for alias, dialect in ((INFO, Dialect.SQLSERVER), (ERP, Dialect.SQLSERVER), (MART, Dialect.POSTGRES)):
        registry.register(_Connector(alias, dialect, log))
    node = AgentNode(agent=MODULE_CODE, privileges=privileges)
    data = ScopedDataAccess(
        registry=registry, agent_node=node, field_mappings=MANIFEST.field_mappings,
        collection_fields=MANIFEST.collection_fields, allowed_sources=MANIFEST.source_aliases or None,
        require_privileges=MANIFEST.require_privileges, data_sources=MANIFEST.data_sources,
        privileges_resolved=True,  # 与生产一致：平台向 INFO 按需拉到的
    )
    return data, log


@dataclass
class Outcome:
    state: str  # 可查 / 一行都查不到 / 表级拒绝 / 报错
    detail: str = ""
    params: dict[str, Any] = field(default_factory=dict)


def probe(data: ScopedDataAccess, log: list, t: Table) -> Outcome:
    log.clear()
    column = "ftable" if t.query_name == TASK_TABLE else "ID"
    spec = QuerySpec.model_validate({"source": t.alias, "from": t.query_name, "select": [column], "limit": 1})
    try:
        data.fetch(spec)
    except TableDenied:
        return Outcome("表级拒绝")
    except (PermissionDenied, ForgeError) as exc:
        return Outcome("报错", f"{type(exc).__name__}: {getattr(exc, 'message', exc)}")
    sql, params = (log[-1][1], log[-1][2]) if log else ("", {})
    if re.search(r"\b1\s*=\s*0\b", sql):
        return Outcome("一行都查不到", params=params)
    return Outcome("可查", params=params)


# ---------------------------------------------------------------- 规格偏差（看原样的权限对象）


@dataclass
class Finding:
    level: str
    text: str


def _walk(items: list[Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any] | None, int]]:
    """(表, 父表, 层级)；层级 0 = 最外层。"""
    def rec(tb: dict[str, Any], parent: dict[str, Any] | None, depth: int):
        yield tb, parent, depth
        for s in tb.get("sub_tables") or []:
            if isinstance(s, dict):
                yield from rec(s, tb, depth + 1)
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("table"), dict):
            yield from rec(it["table"], None, 0)


def lint(data: Any) -> list[Finding]:
    f: list[Finding] = []
    if not isinstance(data, dict) or not data:
        return f
    if data.get("version") != "1.3":
        f.append(Finding(NOTE, f"version 是 {data.get('version')!r}，规格写 \"1.3\""))
    eff = data.get("defaultEffect")
    if eff not in ("DENY", "ALLOW"):
        f.append(Finding(OFF_SPEC, f"defaultEffect 是 {eff!r}，规格写 \"DENY\"（缺失或写错时平台按 DENY 处理）"))
    elif eff == "ALLOW":
        f.append(Finding(NOTE, "defaultEffect 是 ALLOW（备选写法）：没列出的表一律放开，41 张表必须全列，不给允许的写 mode=DENY"))
    level = data.get("level")
    code = level.get("code") if isinstance(level, dict) else None
    if code != "A":
        f.append(Finding(OFF_SPEC, f"level.code 是 {code!r}，规格要求总是 \"A\"（平台不检查这一项，只能靠约定）"))
    items = data.get("dataScope")
    if isinstance(items, dict):
        return f  # 旧的单对象写法，平台直接拒绝，行为部分会报
    if not items:
        f.append(Finding(ERROR, "dataScope 为空：带级别 A 却一张表都不列，等于全部放开"))
        return f
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        if it.get("type") not in (None, "DB", "KB"):
            f.append(Finding(ERROR, f"第 {i + 1} 项 type={it.get('type')!r}：只能是大写 DB，写错整份权限作废"))
        elif it.get("type") is None:
            f.append(Finding(NOTE, f"第 {i + 1} 项没写 type，按 DB 处理；规格写 \"DB\""))
    seen: dict[str, int] = {}
    known_lower = {t.name.lower(): t for t in TABLES}
    for tb, parent, depth in _walk(items):
        name = str(tb.get("name") or "")
        seen[name] = seen.get(name, 0) + 1
        parts = name.split(".")
        t = BY_TAIL.get(parts[-1]) if parts else None
        if t is None:
            hit = next((k for k in known_lower if k.split(".")[-1] == parts[-1].lower()), None)
            if hit:
                f.append(Finding(ERROR, f"{name}：表名大小写与规格不一致（规格：{known_lower[hit].name}），这张表匹配不上"))
            else:
                f.append(Finding(NOTE, f"{name}：本助手不用这张表，平台会忽略它"))
            continue
        if len(parts) == 4 and name != t.name:
            same_tail3 = ".".join(parts[1:]) == ".".join(t.name.split(".")[1:])
            if same_tail3 or t.alias == MART:
                f.append(Finding(NOTE, f"{name}：四段名与规格（{t.name}）实例段等不同，目前仍能匹配；请照规格写"))
            else:
                f.append(Finding(ERROR, f"{name}：库或架构与规格（{t.name}）不一致，这张表匹配不上"))
        mode = tb.get("mode")
        if mode not in ("ALLOW", "DENY"):
            f.append(Finding(OFF_SPEC, f"{t.name}：mode 是 {mode!r}，规格写 \"ALLOW\" 或 \"DENY\"（不写时按 defaultEffect）"))
        if t.kind == "sub":
            want_parent = t.parent.master_table.split(".")[-1] if t.parent else ""
            ptail = str((parent or {}).get("name") or "").split(".")[-1]
            if depth == 0:
                f.append(Finding(OFF_SPEC, f"{t.name}：{t.label}放在了最外层，规格要求挂在本域主表下并继承父表"))
            elif ptail != want_parent:
                f.append(Finding(ERROR, f"{t.name}：挂在了 {ptail} 下，应挂在 {want_parent} 下"))
            if depth:
                if tb.get("inherit_parent") is not True:
                    f.append(Finding(OFF_SPEC, f"{t.name}：没写 inherit_parent: true，主表被拒时子表不会跟着被拒"))
                pf, cf = _RELATION[t.parent]  # type: ignore[index]
                maps = ((tb.get("relation") or {}).get("mappings") or [])
                got = [(m.get("parent_field"), m.get("child_field")) for m in maps if isinstance(m, dict)]
                if got != [(pf, cf)]:
                    loose = [tuple(str(x).lower() for x in g) for g in got] == [(pf.lower(), cf.lower())]
                    f.append(Finding(OFF_SPEC if loose else ERROR,
                                     f"{t.name}：关联列是 {got}，应为 [{pf!r} → {cf!r}]（逐字是物理列名"
                                     + ("；只差大小写，库按不区分大小写比较时还能用）" if loose else "）")))
            if tb.get("row") not in (None, OPEN_ROW):
                f.append(Finding(OFF_SPEC, f"{t.name}：子表带了行规则 {tb.get('row')}，规格是子表省略行声明"))
        else:
            if depth:
                f.append(Finding(ERROR if t.kind == "master" else OFF_SPEC,
                                 f"{t.name}：{t.label}挂在了 {(parent or {}).get('name')} 下，规格要求放最外层"))
            if mode == "ALLOW":
                want_row = TASK_ROW if t.query_name == TASK_TABLE else OPEN_ROW
                row = tb.get("row")
                if row is None:
                    f.append(Finding(OFF_SPEC, f"{t.name}：没写 row，规格要求显式写 {json.dumps(want_row, ensure_ascii=False)}"))
                elif not isinstance(row, dict) or row.get("mode") not in ("ALLOW", "DENY"):
                    f.append(Finding(ERROR, f"{t.name}：row 没写 mode，平台按 defaultEffect 拒绝这张表的全部行"))
                elif row == OPEN_ROW and t.query_name == TASK_TABLE:
                    pass  # 逐表核对那里已报「没收到固定行规则」
                elif row != want_row and t.query_name == TASK_TABLE:
                    f.append(Finding(ERROR, f"{t.name}：行规则与规格不一致：{json.dumps(row, ensure_ascii=False)}"))
                elif row != want_row:
                    f.append(Finding(ERROR, f"{t.name}：带了行规则 {json.dumps(row, ensure_ascii=False)}，本助手不做行级管控"))
        col = tb.get("column")
        if tb.get("mode") == "ALLOW" or t.kind == "sub":
            if col is None:
                f.append(Finding(OFF_SPEC, f"{t.name}：没写 column，规格要求显式写 {json.dumps(OPEN_COLUMN)}"))
            elif not isinstance(col, dict) or col.get("mode") not in ("ALLOW", "DENY"):
                f.append(Finding(ERROR, f"{t.name}：column 没写 mode，默认拒绝下这张表一查就报错"))
            elif col != OPEN_COLUMN:
                f.append(Finding(ERROR, f"{t.name}：带了列规则 {json.dumps(col, ensure_ascii=False)}，本助手不做列级管控"))
    for name, n in seen.items():
        if n > 1:
            f.append(Finding(ERROR, f"{name} 出现了 {n} 次：同一张表只能出现一次，否则所有查询都被拒"))
    return f


# ---------------------------------------------------------------- 汇总报告


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    errors: int = 0
    mismatches: int = 0
    off_spec: int = 0

    def add(self, text: str = "") -> None:
        self.lines.append(text)


def _grant_text(grants: Iterable[str]) -> str:
    order = ["国内", "巴西", "海外", CAR]
    g = [x for x in order if x in set(grants)]
    return "、".join(g) if g else "无"


def check(response: dict[str, Any], what: str, expect: frozenset[str] | None) -> Report:
    r = Report()
    r.add(f"输入：{what}")
    try:
        priv = parse_privileges_payload(response, code=MODULE_CODE)
    except PermissionDenied as exc:
        r.add(f"[{ERROR}] 平台拒绝这份返回，用户这一轮直接被拒（提示稍后再试）：{exc.message}")
        r.errors += 1
        return r
    if priv is None:
        r.add(f"[{ERROR}] Data 为空：平台当成「本助手无管控」，三个域和 CAR 报告全部放开。本助手不允许返回空权限")
        r.errors += 1
        return r

    findings = lint(response.get("Data"))
    data, log = scoped(priv)
    access = gate.resolve(SimpleNamespace(data=data))
    outcomes = {t.name: probe(data, log, t) for t in TABLES}

    r.add("")
    r.add("一、本助手据此放开什么")
    if access is None:
        r.add(f"  [{ERROR}] 权限判断本身报错，用户每一轮都会得到「暂时无法确认您的查看权限，请稍后再试」")
        r.errors += 1
        got_grants: frozenset[str] = frozenset()
    else:
        doms = [GRANT_LABELS[d] for d in access.allowed()]
        got_grants = frozenset(doms + ([CAR] if access.car else []))
        r.add(f"  可查的域：{'、'.join(doms) or '无（用户会得到「您还没有任何域的查看权限，请先申请」）'}")
        r.add(f"  CAR 报告内容：{'能看' if access.car else '不能看'}")
        ts = [GRANT_LABELS[d] for d in DOMAINS if d in access.text_search]
        r.add(f"  按文字找单（关键词、话题、类似问题）：{'、'.join(ts) or '无'}")
        lost = [GRANT_LABELS[d] for d in access.allowed() if d not in access.text_search]
        if lost:
            r.add(f"  [{ERROR}] {'、'.join(lost)}有权，但文字查找表不全，按文字找单会答「暂不可用」")
            r.errors += 1

    basis = expect if expect is not None else got_grants
    if expect is not None:
        r.add("")
        r.add(f"二、与预期对照（预期申请了：{_grant_text(expect)}）")
        want_doms = [GRANT_LABELS[d] for d in DOMAINS if GRANT_LABELS[d] in expect]
        want = frozenset(want_doms + ([CAR] if CAR in expect and "国内" in expect else []))
        if access is not None and want == got_grants and set(want_doms) == {GRANT_LABELS[d] for d in access.text_search}:
            r.add("  一致")
        else:
            r.add(f"  [{ERROR}] 不一致：预期放开 {_grant_text(want)}（文字查找 {'、'.join(want_doms) or '无'}），实际放开 {_grant_text(got_grants)}")
            r.mismatches += 1
        if CAR in expect and "国内" not in expect:
            r.add(f"  [{NOTE}] 申请了 CAR 报告却没申请国内：CAR 报告只在国内物料问题上出现，没有国内权限时用不上")
    r.add("")
    r.add(f"三、逐表核对（按「{_grant_text(basis)}」该有的结果）")
    bad = 0
    for t in TABLES:
        o = outcomes[t.name]
        want = "可查" if allowed(t, basis) else "表级拒绝"
        note = ""
        if o.state == "可查" and t.query_name == TASK_TABLE:
            vals = sorted({str(v) for v in o.params.values()})
            if vals != sorted(TASK_NAMES):
                note = f"（没收到规格里的固定行规则，取到的范围：{vals or '不限'}）"
        if o.state == want and not note:
            continue
        bad += 1
        level = ERROR if o.state != want else OFF_SPEC
        if o.state == "可查" and want == "表级拒绝":
            if t.kind == "master":
                note = "（这个域对用户放开了）"
            elif t.query_name == CAR_TABLE:
                note = "（没申请 CAR 的用户能看到报告内容）"
            else:
                note = "（本助手按域判断不会去查它，但这张表在权限上是放开的）"
        r.add(f"  [{level}] {t.name}（{t.label}）：应为「{want}」，实际「{o.state}」{o.detail and '：' + o.detail}{note}")
        if level == ERROR:
            r.errors += 1
        else:
            r.off_spec += 1
    if not bad:
        r.add(f"  41 张表全部符合（应可查 {sum(allowed(t, basis) for t in TABLES)} 张）")

    r.add("")
    r.add("四、与配置规格的偏差")
    if not findings:
        r.add("  没有")
    for x in findings:
        r.add(f"  [{x.level}] {x.text}")
        if x.level == ERROR:
            r.errors += 1
        elif x.level == OFF_SPEC:
            r.off_spec += 1
    r.add("")
    verdict = "通过" if not r.errors and not r.mismatches else "不通过"
    r.add(f"结论：{verdict}（错误 {r.errors} 处，与预期不一致 {r.mismatches} 处，不符合规格 {r.off_spec} 处）")
    return r


def check_examples(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"<!--\s*自查：([^>]*?)\s*-->\s*```json\n(.*?)\n```", re.S)
    failed = total = 0
    for m in pattern.finditer(text):
        total += 1
        expect = parse_grants(m.group(1))
        line = text[: m.start()].count("\n") + 1
        try:
            response, what = extract_response(json.loads(m.group(2)))
        except (ValueError, InputError) as exc:
            print(f"第 {line} 行（{_grant_text(expect)}）：读不了：{exc}")
            failed += 1
            continue
        r = check(response, what, expect)
        ok = not r.errors and not r.mismatches and not r.off_spec
        print(f"第 {line} 行（{_grant_text(expect)}）：{'通过' if ok else '不通过'}")
        if not ok:
            failed += 1
            print("\n".join("    " + x for x in r.lines))
    print(f"共 {total} 个示例，不通过 {failed} 个")
    return 0 if total and not failed else 1


def main(argv: list[str] | None = None) -> int:
    structlog.configure(logger_factory=structlog.ReturnLoggerFactory())  # 不打平台与本助手的日志
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", nargs="?", type=Path)
    p.add_argument("--expect", help="这个账号申请了什么：国内,巴西,海外,CAR；一个都没有写「无」")
    p.add_argument("--print", dest="print_grants", help="生成该组合的完整返回示例")
    p.add_argument("--allow-variant", action="store_true", help="与 --print 一起用：默认允许的备选写法")
    p.add_argument("--examples", type=Path, help="核对说明文档里标注的示例")
    a = p.parse_args(argv)
    try:
        if a.print_grants is not None:
            print(compact(envelope(build(parse_grants(a.print_grants), allow_variant=a.allow_variant))))
            return 0
        if a.examples:
            return check_examples(a.examples)
        if not a.file:
            p.error("要给一个文件，或用 --print / --examples")
        response, what = load(a.file)
        expect = parse_grants(a.expect) if a.expect is not None else None
    except (InputError, OSError) as exc:
        print(f"读不了输入：{exc}", file=sys.stderr)
        return 2
    r = check(response, what, expect)
    print("\n".join(r.lines))
    return 0 if not r.errors and not r.mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
