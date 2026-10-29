"""统计口径（设计 §8.4；总述「统计口径说明」）。

每轮最后一段，合并各段：一项一个代码模板，数字只取沙箱给的 `caliber`，域的范围取自权限前置，条件回显取自第 6 步
（用户原话与对上的取值）。只写与本次统计相关的项，用业务语言。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

BASIS_TEXT = {"建单": "建单时间", "现场发现": "现场发现日期", "停线": "停线日期", "重启": "重启日期", "结案": "结案时间",
              "统计日期": "统计日期"}


@dataclass
class Caliber:
    """一轮的统计口径，各段往里加，最后 `text()` 合成一段。"""

    times: list[str] = field(default_factory=list)
    counted: list[str] = field(default_factory=list)
    not_counted: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)

    def _add(self, bucket: list[str], text: str) -> None:
        if text and text not in bucket:
            bucket.append(text)

    def time(self, text: str) -> None:
        self._add(self.times, text)

    def domains(self, counted: Iterable[str], not_counted: Iterable[str]) -> None:
        for d in counted:
            self._add(self.counted, d)
        for t in not_counted:
            self._add(self.not_counted, t)

    def condition(self, name: str, value: str) -> None:
        self._add(self.filters, f"{name}：{value}")

    def item(self, text: str) -> None:
        self._add(self.items, text)

    def text(self) -> str:
        lines = ["**统计口径**"]
        lines.append(f"- 时间范围：{'；'.join(self.times) or '不限建单时间'}")
        scope = "、".join(self.counted) or "无"
        if self.not_counted:
            scope += "；" + "；".join(self.not_counted)
        lines.append(f"- 统计范围：{scope}")
        lines.append("- 计数单位：按问题单张数计，一张单计一次")
        lines.append("- 排除：已删除的单未计入")
        if self.filters:
            lines.append(f"- 筛选条件：{'；'.join(self.filters)}")
        lines += [f"- {t}" for t in self.items]
        return "\n".join(lines)


def time_range(spans_text: str | None, basis: str, missing: Iterable[tuple[str, int]] = ()) -> str:
    """「2026-01-01 至 2026-03-31，按建单时间」；按建单以外的日期筛时写明该日期没填而未计入的张数。"""
    head = f"{spans_text}，按{BASIS_TEXT.get(basis, '建单时间')}" if spans_text else "不限建单时间"
    extra = [f"{BASIS_TEXT.get(b, b)}没填的 {n} 张未计入" for b, n in missing if n]
    return "，".join([head, *extra])


# ---------------------------------------------------------------------------- 各项的模板（国内）

CLOSED = "结案：国内以「已完成」为结案，「结案确认」仍算未结案"
STOPPED = "停线：国内「停线中」含停线中、重启审核中、重启审核通过、责任人填写重启方案，按停线状态算，不看是否结案"
STOPPED_EVER = "停线：「曾经停线」指停过线的单，已经重启的仍算"
CLOSE_TIME = "结案时间：国内取处理步骤里最新一条结案确认的时间；结案周期 = 结案时间的日期 − 建单时间的日期，按天计"
STOP_DAYS = "停线时长 = 重启日期 − 停线日期，按天计，只算两个日期都有的单"
FOLLOW = "跟进部门 / 跟进人：国内物料问题、工厂制程、资料问题不指定问题跟进人与跟进部门，统计不到"
RESP_DEPT = "责任归属部门：国内物料问题不按责任部门统计，未计入"
RESPONSIBLE = "责任人：按问题类型取对应环节最新一步的操作人"
CURRENT = "当前责任人：国内按当前状态各行的人，「已完成」的单不计入"
STAGES = "处理环节：按当前状态的每一行计，一单可落在多个环节"
LEVEL = "问题等级：国内 2024-04-17 之前建的单没有问题等级，记为未填；「A 级及以上」含 A+、A"
RATE = "不良率 = 合计不良数量 ÷ 合计生产数量 × 100，保留 2 位小数"


def multi(total_rows: int, issues: int) -> str:
    return f"多值归属：一单在它所属的每个分组下各计一次，各组合计 {total_rows} 张，去重后问题单 {issues} 张"


def rejected(n: int) -> str:
    return f"国内未结案中 {n} 张为生产角色驳回、流程已结束"


def stopped_done(n: int) -> str:
    return f"停线中的单里 {n} 张已完成"


def no_close_time(n: int) -> str:
    return f"已完成但没有结案确认记录的 {n} 张未计入"


def no_restart_date(n: int) -> str:
    return f"已经重启但没有重启日期的 {n} 张未计入"


def rate_excluded(n: int) -> str:
    return f"不良数量为空、生产数量为 0 或空的 {n} 张不参与"


def without(dim: str, n: int) -> str:
    return f"没有{dim}的 {n} 张未计入"


def resp_blank(no_need: int, undecided: int) -> str:
    return f"责任归属部门为空的单未归入部门：无需定责 {no_need} 张、未定责 {undecided} 张"
