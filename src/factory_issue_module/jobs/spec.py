"""治理任务每域读哪些源列、写进文字表的哪一列（设计 §12；文字表表族文件「成员差异」，分段表表族文件「字段代号」）。

列名与哪些域有它以 `2_landed` 为准（`landed.text_columns()`、`landed.seg_fields()`）；这里只补「从哪一列来、
怎么整理」。导入时逐列核对两边：这里多一列、少一列，或某个栏目在这里没有来源，模块加载即失败。
"""

from __future__ import annotations

from dataclasses import dataclass

from factory_issue_module import landed
from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.domains import enums

#: 处理步骤三列（文字表）
STEP_COLUMNS = ("f_step_result", "f_step_opinion", "f_step_content")
COST_COLUMN = "f_cost_memo"
PHEN_COLUMN = "f_phen"


@dataclass(frozen=True)
class StepSource:
    """处理步骤表：国内按环节编码认环节，海外按环节名称认（总述「比对范围」）。"""

    table: str
    id_col: str
    parent_col: str
    key_col: str  # 认环节的列：国内 Step（编码），海外 StepStr（名称）
    factory_key: int | str  # 工厂制程分析：只有它的结论是文字
    name_col: str = "StepStr"
    user_col: str = "AddUser"
    result_col: str = "Result"
    opinion_col: str = "Opinon"
    content_col: str = "Measures"


@dataclass(frozen=True)
class ProcessSource:
    """巴西处理过程：只取最新一条（`ID` 最大，巴西处理过程表「只取最新一条」）。"""

    table: str = "CoreINFO.dbo.BrazilProblemProcess"
    id_col: str = "ID"
    parent_col: str = "ProblemID"
    columns: tuple[tuple[str, str], ...] = ()  # (文字表列, 源列)


@dataclass(frozen=True)
class CostSource:
    """巴西费用明细：全部费用行的备注，每条带费用类型。"""

    table: str = "CoreINFO.dbo.BrazilProblemCost"
    id_col: str = "ID"
    parent_col: str = "ProblemID"
    type_col: str = "CostType"
    memo_col: str = "CostMemo"


@dataclass(frozen=True)
class PhenRowsSource:
    """国内已选现象：已选现象表 → 现象主数据的现象文字（按现象去重）。"""

    table: str = "CoreINFO.dbo.ZCTracking_CheckReason"
    id_col: str = "ID"
    parent_col: str = "ProblemId"
    key_col: str = "PhenomenonID"
    master: str = "CoreINFO.dbo.AfterSaleIssueClassPhenomenon"
    master_id: str = "ID"
    master_text: str = "PhenomenonDesc"


@dataclass(frozen=True)
class DomainSource:
    domain: Domain
    id_col: str
    no_col: str
    #: 未删除的单（主表别名 m），与查询期同一口径（G2「整理规则」末条）
    alive_sql: str
    #: 主表叙述列：(文字表列, 源列)
    main: tuple[tuple[str, str], ...]
    #: 问题现象：主表 JSON 列名与展平写法（巴西、海外）；国内取已选现象表
    phen_json: str | None = None
    phen_style: str | None = None
    phen_rows: PhenRowsSource | None = None
    steps: StepSource | None = None
    process: ProcessSource | None = None
    cost: CostSource | None = None

    @property
    def master(self) -> str:
        return self.domain.master_table

    def text_columns(self) -> tuple[str, ...]:
        """本域文字表的叙述列，顺序同 `2_landed` 那张表。"""
        mine = {PHEN_COLUMN, *(c for c, _ in self.main)}
        if self.process is not None:
            mine |= {c for c, _ in self.process.columns}
        if self.cost is not None:
            mine.add(COST_COLUMN)
        if self.steps is not None:
            mine |= set(STEP_COLUMNS)
        return tuple(c.name for c in landed.text_columns() if c.name in mine) + tuple(
            sorted(mine - {c.name for c in landed.text_columns()})
        )

    def seg_fields(self) -> dict[str, str]:
        """本域分段表的栏目：代号 → 栏目名（分段表表族文件「字段代号」）。"""
        label = self.domain.label
        return {code: names[label] for code, names in landed.seg_fields().items() if label in names}


SOURCES: tuple[DomainSource, ...] = (
    DomainSource(
        domain=Domain.DOMESTIC,
        id_col="ID",
        no_col="Numbers",
        alive_sql="ISNULL(m.[IsDelete], 0) = 0",
        main=(
            ("f_desc", "ProblemDesc"), ("f_reason", "Reason"), ("f_improve", "Improve"),
            ("f_measure", "Measures"), ("f_prev", "Prevention"), ("f_confirm", "Confirmation"),
            ("f_remark", "Remark"), ("f_produce", "ProduceConfirmRemark"),
            ("f_rclass", "ReasonClassRemark"), ("f_restart", "ReStartScheme"),
        ),
        phen_rows=PhenRowsSource(),
        steps=StepSource(
            table="CoreINFO.dbo.ZCTracking_ProblemSteplog", id_col="ID", parent_col="ProblemId",
            key_col="Step", factory_key=enums.CN_STEP_FACTORY,
        ),
    ),
    DomainSource(
        domain=Domain.BRAZIL,
        id_col="ID",
        no_col="OrderNumber",
        alive_sql=f"m.[Status] <> {enums.BR_DELETED}",
        main=(("f_desc", "ProblemDesc"), ("f_remark", "Memo"), ("f_supply", "SupplementMemo")),
        phen_json="ProblemPhenomenon",
        phen_style="brazil",
        process=ProcessSource(columns=(
            ("f_sqe", "DisposeResult"), ("f_reason", "ReasonAnalysis"), ("f_measure", "ImprovementMeasure"),
            ("f_batch", "ImprovementBatch"), ("f_prev", "PrecautionPolicy"), ("f_unshift", "UnCostShiftReason"),
            ("f_owner_memo", "ProcessMemo"), ("f_design_memo", "DesignMemo"), ("f_sqe_memo", "SQEMemo"),
            ("f_confirm_memo", "ConfirmMemo"), ("f_finish_memo", "FinishMemo"),
        )),
        cost=CostSource(),
    ),
    DomainSource(
        domain=Domain.OVERSEAS,
        id_col="Id",
        no_col="Numbers",
        alive_sql="m.[IsDelete] = 0",
        main=(
            ("f_desc", "ProblemDesc"), ("f_reason", "Reason"), ("f_improve", "Improve"),
            ("f_measure", "Measures"), ("f_prev", "Prevention"), ("f_confirm", "Confirmation"),
            ("f_remark", "Remark"), ("f_other", "ProblemRemark"),
        ),
        phen_json="hasCheckedPhenomenon",
        phen_style="overseas",
        steps=StepSource(
            table="CoreINFO.dbo.OverseasProblem_StepLog", id_col="Id", parent_col="ProblemId",
            key_col="StepStr", factory_key=enums.OS_STEP_FACTORY,
        ),
    ),
)
BY_DOMAIN = {s.domain: s for s in SOURCES}


def _check() -> None:
    """这里的来源与 `2_landed` 的列、栏目逐个对上；对不上模块加载失败（设计 §2.3 的防漂移）。"""
    if tuple(s.domain for s in SOURCES) != DOMAINS:
        raise landed.LandedParseError("治理任务的来源要按国内、巴西、海外各一份")
    for spec in SOURCES:
        label = spec.domain.label
        documented = {c.name for c in landed.text_columns() if label in c.sources}
        mine = set(spec.text_columns())
        if documented != mine:
            raise landed.LandedParseError(
                f"{label}文字表的列与 {landed.MART_TEXT_DOC} 不一致：文件里多 {sorted(documented - mine)}，"
                f"代码里多 {sorted(mine - documented)}"
            )
        for code in spec.seg_fields():
            if code == "step":
                if spec.steps is None:
                    raise landed.LandedParseError(f"{label}有「处理步骤」栏目，但没有处理步骤表")
            elif f"f_{code}" not in mine:
                raise landed.LandedParseError(f"{label}的栏目 {code} 在文字表里没有对应的 f_{code} 列")
        if spec.steps is not None and "step" not in spec.seg_fields():
            raise landed.LandedParseError(f"{label}有处理步骤表，但分段表没有「处理步骤」栏目")


_check()
