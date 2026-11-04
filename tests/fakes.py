"""单测用的假 `ctx`（设计 §15）。

- `ctx.data` 用真的 `ScopedDataAccess`，配一个只记 SQL 的假连接器：按 SQL 里 `FROM` 的表名返回构造好的
  数据帧，并记下每条 SQL。权限用 `AgentNode(privileges=…)` 注入，走平台真实的 `describe()`、
  `TableDenied` 与 WHERE 编译。假连接器不执行 WHERE。
- `ctx.stats` 用常驻沙箱（`warm_sandbox`，与平台 harness 同一套限制，进程只起一次）。
  `to_chart` 仍用平台的 `StatsRunner`。
- `ctx.llm` 按调用顺序回放写好的回复；没给回放就调用时报错，用来断言「不调模型」。每次调用都检查
  只有一条 system 且在最前。
- `ctx.workspace`、`ctx.config`、`ctx.files`、`ctx.retrieval` 用字典实现；给了 `history` 时 `ctx.session`
  回放这几轮落库的问答（`conversation_messages` 从它取最近几轮）。
- 假数据照 `docs/testcases/seed/单测夹具清单.md`：假单号（年份 99）、「测试甲」「测试乙」、15 个 9 的编码。
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from forge_core import FileRef
from forge_core.errors import ConfigFileNotDeclared, WorkspaceQuotaExceeded
from forge_core.module import ModuleContext, ModuleManifest, UserContext
from forge_core.permissions.agentnode import AgentNode
from forge_data import DataSourceRegistry, ScopedDataAccess
from forge_data.datasources.base import ParamStyle
from forge_data.scopefilter import Dialect
from forge_platform.stats import (
    STATS_MAX_FRAME_BYTES,
    STATS_MAX_OUTPUT_CHARS,
    STATS_TIMEOUT_SECONDS,
    StatsRunner,
)

import warm_sandbox
from factory_issue_module.declarations import ERP, INFO, MART, MODULE_CODE
from factory_issue_module.module import FactoryIssueModule
from factory_issue_module.present.suggest import MARKER as SUGGEST_MARKER
from factory_issue_module.present.summaries import REASON_MARKER

MANIFEST = FactoryIssueModule.manifest


def _quiet_module() -> FactoryIssueModule:
    """单测看编排产出的完整事件：正文不分段、不发进度（`module.live`；分段与进度另有单测）。"""
    module = FactoryIssueModule()
    module.live = False
    return module

_IDENT = r'(?:\[[^\]]+\]|"[^"]+"|[A-Za-z_][\w]*)'
_TABLE_REF = re.compile(rf"\b(?:FROM|JOIN)\s+({_IDENT}(?:\.{_IDENT})*)", re.IGNORECASE)


def table_tail(ref: str) -> str:
    return ref.split(".")[-1].strip('[]"')


@dataclass
class Query:
    source: str
    sql: str
    params: dict[str, Any]
    tables: tuple[str, ...]  # 尾段表名，FROM 在前、JOIN 在后


class FakeConnector:
    """只读连接器的替身：不连库，按 FROM 表名回构造的数据帧，记下每条 SQL。"""

    def __init__(self, name: str, dialect: Dialect, log: list[Query]) -> None:
        self.name = name
        self.dialect = dialect
        self.param_style = ParamStyle.QMARK if dialect is Dialect.SQLSERVER else ParamStyle.PYFORMAT
        self.frames: dict[str, Any] = {}
        self.errors: dict[str, Exception] = {}
        self._log = log

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        tables = tuple(table_tail(m.group(1)) for m in _TABLE_REF.finditer(sql))
        self._log.append(Query(self.name, sql, dict(params or {}), tables))
        head = tables[0] if tables else ""
        if head in self.errors:
            raise self.errors[head]
        frame = self.frames.get(head)
        if callable(frame):
            return frame(sql, params or {})
        return frame.copy() if frame is not None else pd.DataFrame()


_CANDIDATE_LINE = re.compile(r"^(c\d+)｜[^｜]+｜默认问句：([^｜]+)")


def candidates_in(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """答后建议那次调用里列出的候选：(编号, 默认问句)。"""
    text = str(messages[-1].get("content") or "")
    return [(m.group(1), m.group(2)) for m in (_CANDIDATE_LINE.match(line) for line in text.splitlines()) if m]


def pick_first_two(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """答后建议的默认回放：照默认问句挑前两条（要写现象的那条不挑）。"""
    text = str(messages[-1].get("content") or "")
    slots = {line.split("｜", 1)[0] for line in text.splitlines() if line.endswith("要写现象")}
    picks = [(cid, q) for cid, q in candidates_in(messages) if cid not in slots][:2]
    return {"suggestions": [{"ids": [cid], "query": q} for cid, q in picks]}


class FakeLLM:
    """按顺序回放回复。回放用完还被调用 = 不该调模型的地方调了。

    回复也可以是函数 `(messages) -> 回复`（按本次输入现给）。`routes` 按 system 里的一段文字认调用（文字查找的
    挑说法、判断、摘要），认出的不占顺序回放、可以调多次；几批并行时各批按输入作答，与先后无关。"""

    def __init__(self, replies: list[Any] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[list[dict[str, Any]]] = []
        self.routes: dict[str, Any] = {}
        #: 答后建议那次调用（设计 §9.5）单独记、单独回放，不占 `calls` 与顺序回放：每个取数轮都有这一次，
        #: 混进 `calls` 会让「调了几次」「最后一次是分析段」的断言都跟着变。默认照代码的默认问句挑前两条
        self.suggest_calls: list[list[dict[str, Any]]] = []
        self.suggest_reply: Any = pick_first_two
        #: 表格里「原因与措施」一格的摘要（决策 2026-11-04）同样单独记、单独回放：清单接着问原因、文字查找每轮都可能
        #: 有这一次。默认不给摘要（代码退回原文前约 60 个字）
        self.reason_calls: list[list[dict[str, Any]]] = []
        self.reason_reply: Any = {"items": []}

    @staticmethod
    def check_messages(messages: list[dict[str, Any]]) -> None:
        systems = [i for i, m in enumerate(messages) if m.get("role") == "system"]
        assert systems == [0], f"只能有一条 system 且在最前，实际位置 {systems}"

    def routed(self, marker: str) -> list[list[dict[str, Any]]]:
        """system 里含 `marker` 的那几次调用。"""
        return [m for m in self.calls if marker in str(m[0].get("content") or "")]

    async def chat(self, messages: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        self.check_messages(messages)
        system = str(messages[0].get("content") or "")
        if SUGGEST_MARKER in system:
            self.suggest_calls.append(messages)
            reply = self.suggest_reply(messages) if callable(self.suggest_reply) else self.suggest_reply
            if isinstance(reply, Exception):
                raise reply
            content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
            return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}}
        if REASON_MARKER in system:
            self.reason_calls.append(messages)
            reply = self.reason_reply(messages) if callable(self.reason_reply) else self.reason_reply
            if isinstance(reply, Exception):
                raise reply
            content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
            return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}}
        self.calls.append(messages)
        route = next((fn for marker, fn in self.routes.items() if marker in system), None)
        if route is not None:
            reply = route(messages)
        else:
            if not self.replies:
                raise AssertionError("不该调模型：没有准备回放")
            reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}}

    async def chat_stream(self, messages: list[dict[str, Any]], **kw: Any):
        resp = await self.chat(messages, **kw)
        yield resp["choices"][0]["message"]["content"]


class RecordingStats:
    """常驻沙箱外面包一层，记下每次调用的脚本与数据集名。

    执行走 `warm_sandbox`（进程只起一次）。`to_chart` 仍用平台 `StatsRunner`，只搬数字。
    """

    def __init__(self) -> None:
        self._runner = StatsRunner()
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def run(self, script: str, datasets: dict[str, Any] | None = None, **kw: Any) -> Any:
        self.calls.append((script, tuple(sorted(datasets or {}))))
        timeout = kw.get("timeout")
        limit = (STATS_TIMEOUT_SECONDS if timeout is None
                 else max(1, min(timeout, STATS_TIMEOUT_SECONDS)))
        return await asyncio.to_thread(
            warm_sandbox.run,
            script,
            datasets or {},
            timeout=limit,
            max_output_chars=STATS_MAX_OUTPUT_CHARS,
            return_frames=bool(kw.get("return_frames", False)),
            max_frame_bytes=STATS_MAX_FRAME_BYTES,
        )

    def to_chart(self, outcome: Any, **kw: Any) -> dict[str, Any]:
        return self._runner.to_chart(outcome, **kw)


class FakeWorkspace:
    def __init__(self, quota_bytes: int | None = None) -> None:
        self.store: dict[str, Any] = {}
        self.quota_bytes = quota_bytes

    async def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    async def put(self, key: str, value: Any) -> None:
        if self.quota_bytes is not None and len(repr(value).encode()) > self.quota_bytes:
            raise WorkspaceQuotaExceeded("工作区超限", detail={"key": key})
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def keys(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self.store if k.startswith(prefix))

    async def clear(self) -> None:
        self.store.clear()


class FakeConfig:
    """`ctx.config` 的替身：每个文件一串版本（下标 + 1 即版本号），取最后一版。"""

    def __init__(self, manifest: ModuleManifest, files: dict[str, str | list[str]] | None = None):
        self.declared = {spec.name for spec in manifest.config_files}
        self.versions: dict[str, list[str]] = {
            k: (v if isinstance(v, list) else [v]) for k, v in (files or {}).items()
        }
        self.reads: list[str] = []

    def _check(self, name: str) -> None:
        if name not in self.declared:
            raise ConfigFileNotDeclared(f"没声明的配置文件：{name}")

    async def text(self, name: str, default: str | None = None) -> str | None:
        self._check(name)
        self.reads.append(name)
        versions = self.versions.get(name)
        return versions[-1] if versions else default

    async def path(self, name: str) -> Path | None:
        text = await self.text(name)
        if text is None:
            return None
        path = Path(tempfile.mkdtemp()) / name
        path.write_text(text, encoding="utf-8")
        return path

    async def version(self, name: str) -> int:
        self._check(name)
        return len(self.versions.get(name, []))


class FakeFiles:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    async def save_bytes(self, data: bytes, filename: str) -> FileRef:
        token = f"t{len(self.saved) + 1}"
        self.saved[filename] = data
        return FileRef(token=token, filename=filename, url=f"/f/{token}", size=len(data),
                       expires_ts=time.time() + 86400)


class FakeSession:
    """`ctx.session` 的替身：落库的历史，每轮 user、assistant 各一条（同轮共用 message_id）。"""

    def __init__(self, turns: list[tuple[str, str]] | None = None) -> None:
        self.rows: list[dict[str, Any]] = []
        for i, (user, assistant) in enumerate(turns or []):
            self.rows += [{"role": "user", "content": user, "message_id": f"m{i}"},
                          {"role": "assistant", "content": assistant, "message_id": f"m{i}"}]

    async def history(self, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.rows[-limit:]


class FakeRetrieval:
    def __init__(self, hits: list[list[Any]] | None = None) -> None:
        self.hits = list(hits or [])
        self.calls: list[dict[str, Any]] = []

    async def search(self, query: str, **kw: Any) -> list[Any]:
        self.calls.append({"query": query, **kw})
        return self.hits.pop(0) if self.hits else []


@dataclass
class Harness:
    ctx: ModuleContext
    queries: list[Query]
    connectors: dict[str, FakeConnector]
    llm: FakeLLM
    stats: RecordingStats
    workspace: FakeWorkspace | None
    config: FakeConfig
    files: FakeFiles
    retrieval: FakeRetrieval
    module: FactoryIssueModule = field(default_factory=lambda: _quiet_module())

    def tables_queried(self) -> set[str]:
        return {t for q in self.queries for t in q.tables}


def make_harness(
    privileges: dict[str, Any] | None,
    *,
    resolved: bool = True,
    llm_replies: list[Any] | None = None,
    config_files: dict[str, str | list[str]] | None = None,
    workspace: bool = True,
    manifest: ModuleManifest = MANIFEST,
    field_mappings: dict[str, Any] | None = None,
    history: list[tuple[str, str]] | None = None,
    user: UserContext | None = None,
) -> Harness:
    """`privileges=None` 表示授权树里没带权限；`resolved=False` 表示平台没按需解析（旁路授权树）。"""
    queries: list[Query] = []
    connectors = {
        INFO: FakeConnector(INFO, Dialect.SQLSERVER, queries),
        ERP: FakeConnector(ERP, Dialect.SQLSERVER, queries),
        MART: FakeConnector(MART, Dialect.POSTGRES, queries),
    }
    registry = DataSourceRegistry()
    for connector in connectors.values():
        registry.register(connector)
    node = AgentNode.model_validate({"agent": MODULE_CODE, "privileges": privileges or {}})
    data = ScopedDataAccess(
        registry=registry,
        agent_node=node,
        field_mappings=manifest.field_mappings if field_mappings is None else field_mappings,
        collection_fields=manifest.collection_fields,
        allowed_sources=manifest.source_aliases or None,
        require_privileges=manifest.require_privileges,
        data_sources=manifest.data_sources,
        privileges_resolved=resolved,
    )
    llm = FakeLLM(llm_replies)
    stats = RecordingStats()
    ws = FakeWorkspace() if workspace else None
    config = FakeConfig(manifest, config_files)
    files = FakeFiles()
    retrieval = FakeRetrieval()
    ctx = ModuleContext(
        user=user or UserContext(user_id="u-test", name="测试甲", department="测试部"),
        agent_node=node,
        conversation_id="c-test" if workspace else None,
        llm=llm,
        data=data,
        stats=stats,
        retrieval=retrieval,
        files=files,
        workspace=ws,
        config=config,
        session=FakeSession(history) if history is not None else None,
    )
    return Harness(ctx=ctx, queries=queries, connectors=connectors, llm=llm, stats=stats,
                   workspace=ws, config=config, files=files, retrieval=retrieval)


def data_queries(harness: Harness) -> list[Query]:
    """取业务数据的 SQL：各域主表、子表（连主表的）、待办任务、存货、CAR 报告。

    不含规划前取的主数据（机型取值清单、部门、工厂、供应商、产品、按姓名取人，`domains/shared.py`）：那是第 4–6 步
    对库要的取值清单，不算「取数」。海外加工厂的取值清单取自海外主表（只取去重的加工厂一列），同样不算。
    """
    from factory_issue_module.declarations import CAR_TABLE, DOMAINS, TASK_TABLE

    masters = {table_tail(d.master_table) for d in DOMAINS}
    subs = {table_tail(t) for d in DOMAINS for t in d.sub_tables}
    others = {table_tail(TASK_TABLE), table_tail(CAR_TABLE), "Inventory"}
    out = []
    for q in harness.queries:
        head = q.tables[0] if q.tables else ""
        if is_factory_list(q):
            continue
        if head in masters or head in others or (head in subs and " JOIN " in q.sql.upper()):
            out.append(q)
    return out


def is_factory_list(q: Query) -> bool:
    """海外加工厂的取值清单（`shared.overseas_factory_spec`）：只取去重的加工厂一列。"""
    sql = re.sub(r"\s+", " ", q.sql.upper())
    return bool(q.tables) and q.tables[0] == "OverseasProblemDetail" and "SELECT DISTINCT" in sql \
        and re.search(r"SELECT DISTINCT \S*\[?FACTORY\]? FROM", sql) is not None


def headed_tables(events: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    """每张表和它前面那个小标题（去掉粗体记号）。表格不带标题，小标题写在正文里（决策 2026-11-03「回答骨架与排版」）。"""
    out: list[tuple[str, dict[str, Any]]] = []
    head = ""
    for event in events:
        kind = getattr(event.type, "value", event.type)
        if kind == "delta" and str(event.data.get("text") or "").strip().startswith("**"):
            head = str(event.data["text"]).strip().strip("*")
        elif kind == "table":
            out.append((head, event.data))
    return out


async def run(harness: Harness, query: str) -> list[Any]:
    from forge_core.module import ModuleRequest

    request = ModuleRequest(query=query, conversation_id=harness.ctx.conversation_id)
    return [event async for event in harness.module.handle(request, harness.ctx)]
