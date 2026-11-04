"""manifest 的纯声明（设计 §2、§2.1、§2.2、§3、§11；mart 别名与 `vectorize` 随 S6 加）。

S6 起声明 mart 别名 `forge_mart_factory_issue`（9 张表：三域各文字表、分段表、向量表）与 `vectorize`
（三张向量表，来源是各域按意思找的段表，G2「向量表」）。平台没登记这个别名、或连得上而向量表不存在时，
本助手在那个环境整个被隔离下线（设计 §2），所以这一版只在测试环境建库、登记别名之后发。
权限前置按 `Domain.mart_tables` 判断各域文字查找是否可用（`privileges.md`「域闸门」）。
"""

from __future__ import annotations

from enum import StrEnum

from forge_core.config_files import ConfigFileSpec
from forge_core.dataquery import JoinType
from forge_core.module import DataSourceRef, JoinEdge, VectorizeSpec

from factory_issue_module import landed

MODULE_CODE = "FACTORY_ISSUE"
NAME = "制程问题查询助手"
DESCRIPTION = (
    "只读查询国内、巴西、海外的制程质量问题。可以按时间、加工厂、机型、物料、问题类型、状态、"
    "跟进部门或单号查问题单；点明某一域只查该域，没点明时三个域分别查再汇总。也可以打开一张单看"
    "处理进度、原因和改善措施，按机型、工厂、问题类型或时间段做汇总，或用缺陷现象描述查找类似问题。"
)
PROFILES = ["structured-query", "semantic-retrieval", "governance-etl", "stats-sandbox"]

# §2.1：只收本助手独有、用户真会说的词；「机型」「物料」这类通用词不收。接平台路由后再调。
KEYWORDS = [
    "制程问题", "制程单", "问题单", "国内制程", "巴西制程", "海外制程", "停线", "重启", "结案",
    "不良率", "跟进部门", "当前责任人", "加工厂", "CAR 编号", "8D", "投诉单号", "发货单号",
    "问题现象", "类似问题",
]

INFO = "info"
ERP = "erp"
MART = "forge_mart_factory_issue"


# ---------------------------------------------------------------- 三个域


class Domain(StrEnum):
    """三个域。值只在代码与工作区里用，给用户看的是 `label`（总述「三个域」）。"""

    DOMESTIC = "domestic"
    BRAZIL = "brazil"
    OVERSEAS = "overseas"

    @property
    def prefix(self) -> str:
        return _PREFIX[self]

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def master_table(self) -> str:
        return _MASTER[self]

    @property
    def sub_tables(self) -> tuple[str, ...]:
        return _SUBS[self]

    @property
    def mart_tables(self) -> tuple[str, str, str]:
        """本域文字查找要读的三张 mart 表：文字表、分段表、向量表（G2；不带 `public.`）。"""
        return (self.text_table, self.seg_table, self.vec_table)

    @property
    def text_table(self) -> str:
        return f"{self.value}_issue_text"

    @property
    def seg_table(self) -> str:
        return f"{self.value}_issue_seg"

    @property
    def vseg_table(self) -> str:
        """按意思找的段表：只由治理任务写、平台向量化任务读，不进 `data_sources[].tables`（G2）。"""
        return f"{self.value}_issue_vseg"

    @property
    def vec_table(self) -> str:
        return f"{self.value}_issue_vec"


DOMAINS: tuple[Domain, ...] = (Domain.DOMESTIC, Domain.BRAZIL, Domain.OVERSEAS)

_PREFIX = {Domain.DOMESTIC: "ZC", Domain.BRAZIL: "BR", Domain.OVERSEAS: "HW"}
_by_prefix = {d.prefix: d.name for d in landed.domains()}
if set(_by_prefix) != set(_PREFIX.values()):
    raise landed.LandedParseError(
        f"总述「三个域」的单号前缀 {sorted(_by_prefix)} 与代码约定的 {sorted(_PREFIX.values())} 不一致"
    )
_LABELS = {d: _by_prefix[p] for d, p in _PREFIX.items()}

_MASTER = {
    Domain.DOMESTIC: "CoreINFO.dbo.ZCTracking_ProblemList",
    Domain.BRAZIL: "CoreINFO.dbo.BrazilProblemList",
    Domain.OVERSEAS: "CoreINFO.dbo.OverseasProblemDetail",
}
_SUBS = {
    Domain.DOMESTIC: tuple(
        f"CoreINFO.dbo.{t}"
        for t in (
            "ZCTracking_ProductNames", "ZCTracking_ProblemSteplog", "ZCTracking_ProblemOrders",
            "ZCTracking_XBOrders", "ZCTracking_OtherOrder", "ZCTracking_RiskStream",
            "ZCTracking_CheckReason", "ZCTracking_PossibleInvCode", "ZCTracking_ProblemFiveWhy",
        )
    ),
    Domain.BRAZIL: (
        "CoreINFO.dbo.BrazilProblemProcess", "CoreINFO.dbo.BrazilProblemCost",
        "CoreINFO.dbo.BrazilProblemPO",
    ),
    Domain.OVERSEAS: ("CoreINFO.dbo.OverseasProblem_StepLog", "CoreINFO.dbo.OverseasProblem_DeliveryOrder"),
}
#: 主表 ↔ 子表的关联列（左 = 主表列，右 = 子表列），同 `privileges.md` 的 relation
_JOIN_KEYS = {
    Domain.DOMESTIC: ("ID", "ProblemId"),
    Domain.BRAZIL: ("ID", "ProblemID"),
    Domain.OVERSEAS: ("Id", "ProblemId"),
}

#: 各域查表：现象分类（国内）、现象主数据与可能原因（国内、海外）、巴西工厂与申请单（巴西）
LOOKUP_TABLES = (
    "CoreINFO.dbo.AfterSaleIssueClass",
    "CoreINFO.dbo.AfterSaleIssueClassPhenomenon",
    "CoreINFO.dbo.AfterSaleIssueClassPhenomenonReason",
    "info.dbo.Brazil_Factory",
    "info.dbo.Brazil_RequestList",
)
#: 共用主数据（info 实例 7 张；国内工厂在 erp）
SHARED_TABLES = (
    "info.dbo.Employee", "info.dbo.Department", "info.dbo.DocumentList", "info.dbo.Inventory",
    "info.dbo.tbIQCvendor", "info.dbo.ProductName", "info.dbo.NewProduct",
)
TASK_TABLE = "info.dbo.tbTask"
CAR_TABLE = "info.dbo.tbIQCreportOut"
FACTORY_TABLE = "paxbase.dbo.PaxFactory"

INFO_TABLES: tuple[str, ...] = (
    *(_MASTER[d] for d in DOMAINS),
    *(t for d in DOMAINS for t in _SUBS[d]),
    *LOOKUP_TABLES,
    *SHARED_TABLES,
    TASK_TABLE,
    CAR_TABLE,
)

#: §2.2：主表 ↔ 本域每张子表，共 14 条，只允许 INNER。用途只有一个：子表取数带上主表的筛选条件。
JOINS: list[JoinEdge] = [
    JoinEdge(left=_MASTER[d], right=sub, on=[_JOIN_KEYS[d]], types=[JoinType.INNER])
    for d in DOMAINS
    for sub in _SUBS[d]
]

DATA_SOURCES: list[DataSourceRef] = [
    DataSourceRef(
        alias=INFO,
        kind="sqlserver",
        description="INFO 实例：三域制程问题单与子表、各域查表、人员部门等共用主数据、流程待办任务、CAR 报告",
        tables=list(INFO_TABLES),
        joins=JOINS,
    ),
    DataSourceRef(alias=ERP, kind="sqlserver", description="ERP 实例：国内工厂主数据", tables=[FACTORY_TABLE]),
    DataSourceRef(
        alias=MART,
        kind="postgres",
        description="本助手的产物库：三域剥净后的叙述文字（文字表）、按词找的分段表、按意思找的向量表",
        tables=[t for d in DOMAINS for t in d.mart_tables],
    ),
]

#: G2「向量表」的 3 条，原样：每域一张，来源是本域按意思找的段表；`metadata_columns` 建表后不能再改
VECTORIZE: list[VectorizeSpec] = [
    VectorizeSpec(
        source=MART,
        vector_table=d.vec_table,
        origin_table=d.vseg_table,
        id_column="seg_id",
        text_columns=["seg_text"],
        default_cron="10,40 * * * *",
        metadata_columns=["issue_id", "field"],
    )
    for d in DOMAINS
]

#: §3：待办任务表的固定行规则字段 `ftable` 用表级映射（同一别名下其他表没有这一列）。mart 别名不填（G2）。
FIELD_MAPPINGS: dict[str, dict[str, str | dict[str, str]]] = {
    INFO: {TASK_TABLE: {"ftable": "ftable"}},
}


# ---------------------------------------------------------------- 配置文件槽位（§11）

TOPIC_TERMS = "topic_terms.md"
SEGMENTATION = "segmentation.toml"
DEPT_ALIASES = "dept_aliases.md"
FACTORY_REGIONS = "factory_regions.md"
ANSWER_PARAMS = "answer_params.toml"
LINK_SITES = "link_sites.toml"

CONFIG_FILES: list[ConfigFileSpec] = [
    ConfigFileSpec(
        name=TOPIC_TERMS,
        description=(
            "「涉及某个话题」的说法清单。Markdown，读「## 清单」下的第一张表，表头四列："
            "话题 | 一句话说明 | 算的说法（＊ = 有歧义） | 不算的说法；说法之间用「、」分隔。"
            "「## 说明」里点名带 ＊ 说法的条目（如「漏电」一条）交助手判断时参考，其中「问『X』：…」写的那种问法，"
            "用户正这样问时回答里照写；这一节可以没有。"
            "可直接拿随版本发布的 topic_terms.md 改。没上传时用随版本发布的那份；改了下一次提问生效"
        ),
    ),
    ConfigFileSpec(
        name=SEGMENTATION,
        description=(
            "文字查找的分段规则（whole / field / field_split 与切段长度）、各字段归哪一组、"
            "国内环节编码清单与海外环节名称清单。TOML；只写要改的项，其余用内置默认值。"
            "改了要手动跑一次全量重建"
        ),
    ),
    ConfigFileSpec(
        name=DEPT_ALIASES,
        description="部门简称。Markdown 两列表：正式部门名称 | 简称、日常说法；简称之间用「、」分隔",
    ),
    ConfigFileSpec(
        name=FACTORY_REGIONS,
        description="国内工厂的地区说法。Markdown 两列表：地区说法 | 对到的工厂；工厂之间用「、」分隔",
    ),
    ConfigFileSpec(
        name=ANSWER_PARAMS,
        description=(
            "回答参数。TOML：top_n（排名条数）、export_threshold（某域列出的超过多少张就导出，默认 20）、table_rows（表格给几张）、"
            "judge_max（「可能相关」每域最多判断几张）、rerank_max（每域最多重排几张）、"
            "rerank_score_threshold（「可能相关」的重排分阈值，不写即不启用）、"
            "similar_rerank_floor（类似问题的重排分下限，默认 0.2，写 0 即不按分数筛）、"
            "similar_rows（类似问题每域列几张，默认 5，最多 10）、custom_stats_enabled（是否允许临时统计）、"
            "points_max（结论至多几条要点，默认 4，写 0 即不给）、focus_max（「需关注」至多几张，默认 3，写 0 即不给）、"
            "concentrate_share（「集中」的占比门槛，百分数，默认 40）、repeat_min（「重复」至少几张，默认 3）、"
            "trend_months（「时间」至少跨几个月，默认 3）、close_min（「时效」某域至少几张已结案的单，默认 5）"
        ),
    ),
    ConfigFileSpec(
        name=LINK_SITES,
        description=(
            "本环境 INFO 站点的地址，用来生成问题编号、CAR 报告、附件的跳转链接；测试环境与正式环境各传各的。"
            "TOML：issue = \"主机名\"（国内、海外制程单与国内 CAR 报告页面，必写）；brazil（巴西制程单）、"
            "attachment（附件预览）两项不写时与 issue 相同。值写主机名，可带端口，不带末尾的 /；"
            "站点只有 http 时写成 http://主机名。没传时不生成链接，问题编号照常显示为文字"
        ),
        required=True,
    ),
]
