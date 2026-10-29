"""单测用的假 `ctx`（设计 §15）。

- `ctx.data` 用真的 `ScopedDataAccess`，配一个只记 SQL 的假连接器：按 SQL 里 `FROM` 的表名返回构造好的
  数据帧，并记下每条 SQL。权限用 `AgentNode(privileges=…)` 注入，走平台真实的 `describe()`、
  `TableDenied` 与 WHERE 编译。假连接器不执行 WHERE。
- `ctx.stats` 用平台的 `StatsRunner`（同一个沙箱库，本机子进程跑）。
- `ctx.llm` 按调用顺序回放写好的回复；没给回放就调用时报错，用来断言「不调模型」。每次调用都检查
  只有一条 system 且在最前。
- `ctx.workspace`、`ctx.config`、`ctx.files`、`ctx.retrieval` 用字典实现；给了 `history` 时 `ctx.session`
  回放这几轮落库的问答（`conversation_messages` 从它取最近几轮）。
- 假数据照 `docs/testcases/seed/单测夹具清单.md`：假单号（年份 99）、「测试甲」「测试乙」、15 个 9 的编码。
"""

from __future__ import annotations

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
from forge_platform.stats import StatsRunner

from factory_issue_module.declarations import ERP, INFO, MART, MODULE_CODE
from factory_issue_module.module import FactoryIssueModule

MANIFEST = FactoryIssueModule.manifest

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


class FakeLLM:
    """按顺序回放回复。回放用完还被调用 = 不该调模型的地方调了。"""

    def __init__(self, replies: list[Any] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[list[dict[str, Any]]] = []

    @staticmethod
    def check_messages(messages: list[dict[str, Any]]) -> None:
        systems = [i for i, m in enumerate(messages) if m.get("role") == "system"]
        assert systems == [0], f"只能有一条 system 且在最前，实际位置 {systems}"

    async def chat(self, messages: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        self.check_messages(messages)
        self.calls.append(messages)
        if not self.replies:
            raise AssertionError("不该调模型：没有准备回放")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}}

    async def chat_stream(self, messages: list[dict[str, Any]], **kw: Any):
        resp = await self.chat(messages, **kw)
        yield resp["choices"][0]["message"]["content"]


class RecordingStats:
    """平台的 StatsRunner 外面包一层，记下每次调用的脚本与数据集名。"""

    def __init__(self) -> None:
        self._runner = StatsRunner()
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def run(self, script: str, datasets: dict[str, Any] | None = None, **kw: Any) -> Any:
        self.calls.append((script, tuple(sorted(datasets or {}))))
        return await self._runner.run(script, datasets, **kw)

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
    module: FactoryIssueModule = field(default_factory=FactoryIssueModule)

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
        user=UserContext(user_id="u-test", name="测试甲", department="测试部"),
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

    不含规划前取的主数据（机型取值清单、部门、工厂、供应商、按姓名取人，`domains/shared.py`）：那是第 4–6 步
    对库要的取值清单，不算「取数」。
    """
    from factory_issue_module.declarations import CAR_TABLE, DOMAINS, TASK_TABLE

    masters = {table_tail(d.master_table) for d in DOMAINS}
    subs = {table_tail(t) for d in DOMAINS for t in d.sub_tables}
    others = {table_tail(TASK_TABLE), table_tail(CAR_TABLE), "Inventory"}
    out = []
    for q in harness.queries:
        head = q.tables[0] if q.tables else ""
        if head in masters or head in others or (head in subs and " JOIN " in q.sql.upper()):
            out.append(q)
    return out


async def run(harness: Harness, query: str) -> list[Any]:
    from forge_core.module import ModuleRequest

    request = ModuleRequest(query=query, conversation_id=harness.ctx.conversation_id)
    return [event async for event in harness.module.handle(request, harness.ctx)]
