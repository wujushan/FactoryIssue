"""制程问题查询助手 业务模块。

⚠️ G1 闸门：先完成 docs/2_landed/ 业务逻辑梳理落盘（歧义清单清零或显式放行），
再开始实现本文件（.claude/hooks/guard.py 会硬拦）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.metadata import PackageNotFoundError, version as _installed_version

from forge_core.events import Event
from forge_core.module import ForgeModule, ModuleContext, ModuleManifest, ModuleRequest

MODULE_CODE = "FACTORY_ISSUE"

#: 版本号只有**一个**真源：pyproject.toml 的 [project].version（`forge release` 就改那里，
#: wheel 元数据即由它生成）。这里读已装 wheel 的元数据，而不是再手写一遍字面量——手写的那份
#: 发版时没人会跟着改，最后就是「机器上装的是 0.1.0a5、manifest 却一直自称 0.1.0」。
#: 源码树里未安装时（极少见，正常开发也是 `uv sync` 装好的）退回 0.0.0，不让 import 失败。
try:
    MODULE_VERSION = _installed_version("forge-module-factory-issue")
except PackageNotFoundError:  # pragma: no cover —— 未安装即本仓未 uv sync
    MODULE_VERSION = "0.0.0"


class FactoryIssueModule(ForgeModule):
    manifest = ModuleManifest(
        code=MODULE_CODE,
        name="制程问题查询助手",
        description="只读查询国内、巴西、海外的制程质量问题。可以按时间、加工厂、机型、物料、问题类型、状态、跟进部门或单号查问题单；点明某一域只查该域，没点明时三个域分别查再汇总。也可以打开一张单看处理进度、原因和改善措施，按机型、工厂、问题类型或时间段做汇总，或用缺陷现象描述查找类似问题。",
        version=MODULE_VERSION,  # 跟随 pyproject.toml，勿改回字面量
        # 能力 profile：初始化选 / 追加某能力前先读 docs/dev/07-capability-profiles.md 对应小节
        # （追加 ≠ 只加字符串：semantic-retrieval/governance-etl 跨 G2 决策、需平台侧建 mart 库并登记数据源）。
        profiles=['structured-query', 'semantic-retrieval', 'governance-etl', 'stats-sandbox', 'analysis-report'],
        # 路由素材（G1 产物）：示例问题与关键词，直接影响入口路由质量
        intents=[],
        keywords=[],
        # 模块总线依赖声明（需要调用其他模块能力时填写，装配期做 DAG 校验）
        dependencies=[],
        # 数据源声明（G1 定源/G2 定形态）：本模块要用的平台数据源别名（实例/库句柄）。
        # 一别名=一台 SQLServer 实例 / 一个 PG 库 / 一个 MySQL 库；多实例就多条（如 info + erp）。
        # ⛔ MySQL 源（kind="mysql"）**禁手写 SQL**：.raw()、query(where=...)、QuerySpec.raw_where
        #    一律拒绝，只能走结构化 fetch(spec)（支持 JOIN/GROUP BY/聚合）。见 docs/dev/02。
        # 平台启动校验声明的别名都已在 data_sources.json 登记，运行期 ctx.data 只放行已声明别名。
        # 别名须与 docs/2_landed/db_description 各表的 source 一致。用到时：
        #   from forge_core.module import DataSourceRef, JoinEdge
        #   data_sources=[DataSourceRef(alias="info", kind="sqlserver",
        #                               description="INFO 主数据", tables=["INFODB.dbo.Xxx"])],
        # 要多表联查时再加 joins（**可连接表图**）：你审过哪些连接，fetch(spec) 才能连哪些，
        # 越界即 JoinNotDeclared；不声明 = 该源不支持 JOIN。它同时是 ctx.data.describe() 的目录。
        #   data_sources=[DataSourceRef(alias="erp", tables=["ERPDB.dbo.orders",
        #                                                    "ERPDB.dbo.customers"],
        #                               joins=[JoinEdge(left="ERPDB.dbo.orders",
        #                                               right="ERPDB.dbo.customers",
        #                                               on=[("customer_id", "id")])])],
        data_sources=[],
        # 权限字段映射（G4 产物）：数据源别名 -> {协议权限字段 -> 物理列}
        # 缺失映射时 DataScopeFilter fail-closed 拒绝查询
        field_mappings={},
        # 声明式向量化（semantic-retrieval profile）：声明「哪张治理后表的哪些文本列 → 哪张向量表」，
        # 平台据此生成建表 DDL（`forge vectorize ddl`）、回填 job、启动期校验——**你不写向量化代码**。
        # 权限承载列不在这里声明：平台从 field_mappings[source] 自动算出并透传（这正是重点）。
        # 表达力边界是「单表 + 列拼接」；复杂拼装先用 governance-etl 落成一张干净表，本声明只读它。
        #   from forge_core.module import VectorizeSpec
        #   vectorize=[VectorizeSpec(source="forge_mart_factory_issue", vector_table="issues_vec",
        #                            origin_table="issues", id_column="issue_id",
        #                            text_columns=["defect_desc", "handling"])],
        vectorize=[],
        # 引导式交互与初步分析能力字段（软性 opt-in，缺省即不启用、平台不报错；
        # 契约 docs/decisions/2026-07-09-引导式交互与初步分析能力-平台契约.md）。G1 采集、G4 用：
        # 缺关键参数即追问（Req1）——handle() 据此发 CLARIFY，不盲目取数：
        #   from forge_core.module import ClarifyDimension
        #   clarify_dimensions=[ClarifyDimension(name="time_range", question="要查哪个时间段？",
        #                                        examples=["近30天", "2026年"])],
        # 本域初步分析维度 + 图型（Req3）——驱动 table→ctx.stats→chart 范式：
        #   from forge_core.module import AnalysisDimension
        #   analysis_dimensions=[AnalysisDimension(name="机型", description="按机型统计台数", chart="bar")],
        # 业务术语表（Req4）——**唯一信源是 docs/2_landed/glossary.md**，此处结构与该文档保持一致：
        #   from forge_core.module import GlossaryTerm
        #   glossary=[GlossaryTerm(term="ECN", aliases=["工程变更"], definition="工程变更通知单")],
        # 注意：用 ctx.stats 做数字统计需在 profiles 里含 "stats-sandbox"（平台按此 profile 注入 ctx.stats）。
    )

    async def handle(
        self, request: ModuleRequest, ctx: ModuleContext
    ) -> AsyncIterator[Event]:
        # TODO(G4): 实现业务逻辑。标准范式与红线（对应 manifest 上面四个能力字段）：
        # 1. 缺关键参数先澄清（Req1）：manifest.clarify_dimensions 里的必填项缺失时，
        #    yield Event.clarify(question, recommendations=[...])，不要盲目取数。
        # 2. 取数经受控句柄（红线）：df = ctx.data.fetch(spec)（同步，别 await）
        #    ——DataScopeFilter 取数前阻断，无权数据不出库；模块只认 manifest.data_sources 声明的别名。
        #        from forge_core.dataquery import QuerySpec
        #        df = ctx.data.fetch(QuerySpec.model_validate({
        #            "source": "erp", "from": "<物理表名>",
        #            "select": ["col_a", "col_b"],        # **必填**，禁全列选取（防越权红线）
        #            "filter": {"groups": [{"conditions": [
        #                {"field": "status", "operator": "EQ", "value": "OPEN"},
        #                {"field": "d", "operator": "GE", "value": {"$relative": "-30d"}},
        #            ]}]},
        #            "order_by": [{"field": "d", "direction": "DESC"}], "limit": 500,
        #        }))
        #    列级权限管到 spec 的**每一个**列引用位置；请求无权列**抛 ColumnNotPermitted**（不是静默
        #    少一列），据 detail 改列重试。表级无权**抛 TableDenied**（fetch/query/raw 一律抛，不是返回
        #    空 DataFrame）、不给 limit 时超平台上限**报错**（不是静默截断）。
        #    日期区间用 {"$relative": "-30d"} 交框架算——让 LLM 自己算日期是数字红线。
        #    filter 里**只有比较、没有计算**：算术交 ctx.stats 沙箱或 mart 派生列。
        #    ⚠️ ctx.data.query(src, table, select=[...], where="...") 是保留的单表简写，它的裸 `where`
        #    **不过列级白名单**（禁列可被当 oracle 反推）且打 raw_where 审计 flag——新代码用 fetch。
        #    多表联查写进 spec.joins（INNER/LEFT），但只能连 manifest.data_sources[].joins 声明过的边：
        #        "from": {"table": "ERPDB.dbo.orders", "alias": "o"},   # 多表时每张表都要 alias
        #        "joins": [{"table": {"table": "ERPDB.dbo.customers", "alias": "c"}, "type": "LEFT",
        #                   "on": [{"left": "o.customer_id", "right": "c.id"}]}],
        #        "select": ["o.amount", "c.name"],                      # 多表时列引用必须限定别名
        #    让 LLM 组 spec 前把 ctx.data.describe() 的目录拼进提示词（as_prompt()），它就不用猜。
        #    ⚠️ 被连接表的 scope 进它自己的 ON，所以 LEFT JOIN 不会因关联表无权而退化成 INNER；但
        #    你写的 filter 仍进 WHERE、引用被 LEFT JOIN 表的列时仍会退化——那是你要的过滤，框架不改。
        #    跨 source（跨实例）不做 join，仍是逐源 fetch + pandas 关联。
        #    聚合能用「已有列 + COUNT/SUM/AVG/MIN/MAX」表达完的就下推 SQL（不违反数字红线，见第 3 条）：
        #        "select": ["region", {"field": "amount", "agg": "SUM"}, {"agg": "COUNT"}],
        #        "group_by": ["region"],
        #        "having": {"groups": [{"conditions": [
        #                   {"field": "amount", "agg": "SUM", "operator": "GT", "value": 100000}]}]},
        #        "order_by": [{"field": "amount", "agg": "SUM", "direction": "DESC"}], "limit": 10,
        #    结果列名由框架生成并恒定发 AS：df["sum_amount"] / df["count_star"]（给 label 就用 label）。
        #    ⚠️ 聚合参数与投影列**同权**：AVG(禁列) 抛 ColumnNotPermitted（分组键够细时聚合就是投影）。
        #    既非聚合、又不在 group_by 里的列 → GroupByIncomplete；按聚合结果过滤只能写 having
        #    （filter 进 WHERE、在分组之前执行，那时聚合值还不存在）。
        #    确实下推不了才用 ctx.data.raw()（不稳定逃生阀，受审计高亮监控，尽量别用）。
        #    非结构化字段的语义检索同理走 ctx.retrieval（需 semantic-retrieval profile）：
        #        hits = await ctx.retrieval.search(request.query, source="forge_mart_<模块编码>",
        #                                          table="<向量表>")  # 召回 + 本地 rerank
        #    行级权限随检索一并下推（无权向量不出库）。别自己 new PgVectorIndex/EmbeddingClient、
        #    别自己读 env——那样绕开平台配置 = 绕开权限与检索审计；ctx.retrieval 为 None 说明
        #    profile 没声明或平台没配 embedding 服务，找平台侧解决（见 docs/dev/07）。
        # 3. 一切数字走确定性执行器（红线，Req3）：禁止在 handle() 里用 pandas/sum/sorted 直算、更禁
        #    LLM 直算。禁的是「谁产出数字」不是「哪里出现算术」——SQL 引擎与 ctx.stats 沙箱同属确定性
        #    执行器，都不在禁止之列。能用「已有列 + COUNT/SUM/AVG/MIN/MAX」表达完的优先下推 SQL（见
        #    第 2 条），表达不完的（同比环比/分档/加权/跨源）交沙箱。两条路的不变量一样：LLM 只能
        #    引用执行器的产出，永远不许自己报数（包括「顺手心算一下百分比」）。
        #    统计交给 ctx.stats（需 stats-sandbox profile）：
        #        outcome = await ctx.stats.run(script, {"rows": df})   # script 可由 LLM 生成，沙箱内算数字
        #        yield Event.table(columns=[...], rows=outcome.result[...])
        #        yield Event.chart(**ctx.stats.to_chart(outcome, chart_type="bar",
        #                                               x_key="机型", series_keys=["台数"]))
        #    CHART 只产平台无关抽象 spec（平台转 echarts）；spec 里的数字必须来自 outcome。
        # 4. 术语理解（Req4）：构建 LLM 提示时拼接本域术语表/分析维度/澄清项——
        #        from forge_core.prompting import domain_prompt_section
        #        system = MY_SYSTEM + domain_prompt_section(self.manifest)
        #    （数字走沙箱、不臆造等平台红线 policy 已由 ctx.llm 自动前置，无需在此重复写。）
        # 5. 答后引导（Req2）：可 yield Event.suggestions([...]) 给下一步追问按钮（基于本轮结果精修）；
        #    每项是 {"id","name","label","query"} 对象，不是字符串（见 docs/dev/02 事件协议）。
        # 6. 需要其他模块时，ctx.bus 有**两条通道**，按你要的是「数据」还是「回答」选：
        #    - 要**数据**做再加工（跨域关联/综合判定）→ 结构化能力调用，非流式：
        #        stock = await ctx.bus.invoke(ctx, "<模块编码>", "<能力名>", {"part_nos": [...]})
        #        df = pd.DataFrame(stock.data)   # 带连接键、类型明确、截断显式告知
        #      先在 manifest.capability_deps 声明；自己对外提供能力则声明 manifest.capabilities
        #      并实现 invoke()。见 docs/dev/02「结构化能力调用」。
        #    - 要把对方的**回答**转给用户看 → 问答式，事件流透传：
        #        async for ev in ctx.bus.call(ctx, "<模块编码>", request): yield ev
        #      先在 manifest.dependencies 声明。
        #    ⚠️ 别用 call 去解析对方正文里的数字：事件流里的表格按呈现规范是裁剪过的
        #      （连接键被砍、只给前 N 条），且从自然语言里「读出」数字 = LLM 直算，撞红线。
        # 6.5 多轮上下文：**读历史并注入 LLM 是模块的事**（平台不塞进 request），用 SDK helper：
        #        from forge_core.conversation import conversation_messages
        #        history = await conversation_messages(ctx, request, turns=3)
        #        resp = await ctx.llm.chat([{"role": "system", "content": system}, *history,
        #                                   {"role": "user", "content": request.query}])
        #    它已剥掉平台投影的表格/图表/按钮块（喂模型是噪声）、排除了当前轮（平台在分发前
        #    就落了 user 行）、按轮而非按条截取。**别自己撸这段**。
        #    ⚠️ `request.query` 恒为用户原话，平台不替你消解指代。历史进了 messages 数组，
        #    消解就是模型的默认行为——**唯一必须显式消解的是「query 被当检索输入」时**：
        #    ctx.retrieval.search / ctx.knowledge.retrieve 拿「那上个月呢」去算 embedding 毫无
        #    意义。规则：**检索前的 query 必须是自足的**。
        # 7. 呈现规范（回给用户的东西，详版 + 自检清单见 docs/dev/09-answer-presentation.md）：
        #    - **取到 ≠ 返回**：取数集 ⊃ 展示集。自增 ID/代理主键/状态码原值/软删标记/权限承载列/
        #      连接键不进 Event.table 的列、也不进正文；业务标识（工单号/料号/项目编号）必须给全。
        #      要序号就在展示层现生成 1..N，别拿 id 冒充序号。
        #    - **不许露表名/字段名**：columns、delta 正文、图表轴、Event.error 的 message 一律业务
        #      语言（prj_dly_days → 「延期天数」）；显示名取自 docs/2_landed/db_description 的
        #      「用户可见显示名」+ glossary.md（别每处即兴翻译）。数据源别名/SQL/脚本同样不外露。
        #    - **给数据也给分析**（默认要，用户明说只要数据才免）：总量 → 分档/分布 → 最需关注的
        #      Top N（点名）→ 一句结论；维度声明在 manifest.analysis_dimensions，数字全走 ctx.stats。
        #    - **寒暄要报本板块能力**：「你好/你是谁/你能帮我查什么」会落到这里——平台路由没有闲聊
        #      分支，这种问题不含模块关键词、分类器多半弃权，于是**单候选时直通本模块**、**上一轮
        #      路由过谁就粘回谁**。下面那句回声留着，用户第一句话拿到的就是它。答法 = 一句话说明
        #      本板块管哪个域 + 列举常用场景 + 每个场景一句简短介绍，配 Event.suggestions 做成可点
        #      按钮。场景取自 manifest.intents / docs/2_landed/business_description.md（别即兴编，
        #      编的场景与 intents 对不上，用户照着问却路由不回来），且**只讲本板块**——别列举其他
        #      模块的能力，用户不一定有那些权限。
        yield Event.progress("todo", "模块骨架尚未实现业务逻辑")
        yield Event.delta(f"[{MODULE_CODE}] 收到: {request.query}")

    # 定时任务示例（governance-etl profile）：把源库数据治理干净、落成 mart 里的一张表。
    #
    # ⚠️ **向量化回填不用你写**：它 100% 定型（扫缺 embedding 的行 → embed → upsert），由平台按
    #    manifest.vectorize 声明生成——包括权限承载列的透传。你的治理 ETL 只负责把数据弄干净、
    #    落成一张「可直接向量化」的表（含 content 文本列 + 权限承载列），向量化只读那张表。
    #    见 docs/dev/07-capability-profiles.md 的 semantic-retrieval 小节。
    #
    # 句柄一律从 JobContext 取，**别自己 new 连接、别自己读 env**（与 handle() 的 ctx 同款）。
    # ⚠️ ETL 期没有 AgentNode，ctx.etl 的句柄**不受权限过滤管辖**（系统级全量读写）——所以你的
    #    SELECT **必须带上权限承载列**（field_mappings 里那些物理列）并原样落进 mart 表，
    #    否则查询期编译不出行级 WHERE，平台启动时就会拒绝（TABLE_SCOPE_COLUMNS_MISSING；
    #    向量表那侧是 VECTOR_SCOPE_COLUMNS_MISSING）。
    #
    # ⚠️ **治理后表的建表 DDL 归你写，就写在这个 job 里**（向量表才是平台生成+平台建的）：
    #    它每个模块都不一样，平台无从生成。写成 `CREATE TABLE IF NOT EXISTS` 放在 job 开头，
    #    每轮重放都是空操作，首轮自动把表建出来——**不需要 Alembic，模板里也没有**。
    #    建表语句与下面那条 SELECT **必须一致**：加一列就两处都加，这也正是把它放在一起的理由。
    #    别忘了权限承载列（下例的 dept_id），它是查询期能施加行级过滤的唯一前提。
    #
    # from forge_core.jobs import JobBinding, JobContext, JobSpec
    # from forge_data.etl import run_incremental_sync
    #
    # def jobs(self) -> list[JobBinding]:
    #     return [JobBinding(
    #         spec=JobSpec(name="sync", description="每日增量同步", default_cron="30 2 * * *"),
    #         run=self._sync,
    #     )]
    #
    # async def _sync(self, ctx: JobContext) -> None:
    #     src = ctx.etl.read("info")          # 只读连接器（仅 manifest.data_sources 声明的别名）
    #     dst = ctx.etl.write("forge_mart_factory_issue")  # 写句柄（源上需配 write_user/write_password_env）
    #     dst.execute(
    #         "CREATE TABLE IF NOT EXISTS issues ("
    #         "  id text PRIMARY KEY,"
    #         "  content text,"
    #         "  dept_id text,"          # ← 权限承载列：漏了平台启动期就拒绝
    #         "  ts timestamptz"
    #         ")"
    #     )
    #     await run_incremental_sync(
    #         read_watermark=lambda: ...,
    #         fetch_since=lambda wm: src.query("SELECT id, content, dept_id FROM ... WHERE ts > :wm",
    #                                          {"wm": wm}),   # ← dept_id 就是那个「必须带上」的权限列
    #         upsert=lambda rows: ...,        # 写进 mart 的治理后表
    #         watermark_of=lambda r: r["ts"],
    #         save_watermark=lambda v: ...,
    #     )
