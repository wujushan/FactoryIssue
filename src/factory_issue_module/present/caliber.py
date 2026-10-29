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


def time_range(spans_text: str | None, basis: str, missing: Iterable[tuple[str, int]] = (),
               domain: str = "") -> str:
    """「2026-01-01 至 2026-03-31，按建单时间」；按建单以外的日期筛时写明该日期没填而未计入的张数。

    几域一起、按域分别给的那几段，`domain` 写上域名（「巴西结案时间没填的 1 张未计入」，XC-027 按域写明）。
    """
    head = f"{spans_text}，按{BASIS_TEXT.get(basis, '建单时间')}" if spans_text else "不限建单时间"
    extra = [f"{domain}{BASIS_TEXT.get(b, b)}没填的 {n} 张未计入" for b, n in missing if n]
    return "，".join([head, *extra])


# ---------------------------------------------------------------------------- 各项的模板
# 每项按本段计入的域写（`ds` 是域名的集合）；只有国内时与 S2 的写法逐字相同（下面几个常量）。

_CN, _BR, _OS = "国内", "巴西", "海外"


def _in(ds: Iterable[str], *names: str) -> list[str]:
    have = set(ds)
    return [n for n in names if n in have]


def closed(ds: Iterable[str]) -> str:
    parts = []
    cn_os = _in(ds, _CN, _OS)
    if cn_os:
        parts.append(f"{'、'.join(cn_os)}以「已完成」为结案，「结案确认」仍算未结案")
    if _BR in set(ds):
        parts.append("巴西以「已结案」为结案，未结案不含待提交、已终止")
    return "结案：" + "；".join(parts)


def stopped(ds: Iterable[str]) -> str:
    parts = []
    if _CN in set(ds):
        parts.append("国内「停线中」含停线中、重启审核中、重启审核通过、责任人填写重启方案，按停线状态算，不看是否结案")
    if _BR in set(ds):
        parts.append("巴西「停线中」指是否停线为「是」、还没有标记停线重启，不看是否结案")
    if _OS in set(ds):
        parts.append("海外「停线中」指停线状态为「停线中」，不看是否结案")
    return "停线：" + "；".join(parts)


def close_time(ds: Iterable[str]) -> str:
    parts = []
    cn_os = _in(ds, _CN, _OS)
    if cn_os:
        parts.append(f"{'、'.join(cn_os)}取处理步骤里最新一条结案确认的时间")
    if _BR in set(ds):
        parts.append("巴西取最新一条处理过程上的结案日期")
    return "结案时间：" + "，".join(parts) + "；结案周期 = 结案时间的日期 − 建单时间的日期，按天计"


def close_split(ds: Iterable[str]) -> str:
    """巴西与别的域一起要结案周期时（总述「结案时间与结案周期」）：结案时间取法不同，分域给、合计不算。"""
    others = _in(ds, _CN, _OS)
    return f"巴西的结案时间取法与{'、'.join(others) or '其他域'}不同，结案周期分域给出，不合成跨域的结案周期"


def stop_days(ds: Iterable[str]) -> str:
    text = "停线时长 = 重启日期 − 停线日期，按天计，只算两个日期都有的单"
    if _BR in set(ds):
        text += "；巴西没有停线重启时间，未计入"
    if _OS in set(ds):
        text += "；海外按停线重启时间算，没填的单不计入"
    return text


def follow(ds: Iterable[str]) -> str:
    parts = []
    if _CN in set(ds):
        parts.append("国内物料问题、工厂制程、资料问题不指定问题跟进人与跟进部门，统计不到")
    if _BR in set(ds):
        parts.append("巴西按最新一条处理过程上的问题跟进人计，跟进部门按跟进人现在所在的部门计，"
                     "尚无处理过程的单为「未指定」，未计入")
    if _OS in set(ds):
        parts.append("海外问题跟进部门、问题跟进人为空的单未计入")
    return "跟进部门 / 跟进人：" + "；".join(parts)


def resp_dept(ds: Iterable[str]) -> str:
    parts = []
    if _CN in set(ds):
        parts.append("国内物料问题不按责任部门统计，未计入")
    others = _in(ds, _BR, _OS)
    if others:
        parts.append(f"{'、'.join(others)}没有责任归属部门，按问题跟进部门计")
    return "责任归属部门：" + "；".join(parts)


def responsible(ds: Iterable[str]) -> str:
    parts = []
    if _CN in set(ds):
        parts.append("按问题类型取对应环节最新一步的操作人")
    if _BR in set(ds):
        parts.append("巴西的责任人即问题跟进人")
    if _OS in set(ds):
        parts.append("海外按当前责任人")
    return "责任人：" + "；".join(parts)


def current(ds: Iterable[str]) -> str:
    parts = []
    if _CN in set(ds):
        parts.append("国内按当前状态各行的人")
    if _OS in set(ds):
        parts.append("海外取单上的当前责任人")
    return "当前责任人：" + "，".join(parts) + "，「已完成」的单不计入"


def stages(ds: Iterable[str]) -> str:
    parts = []
    if _CN in set(ds):
        parts.append("按当前状态的每一行计，一单可落在多个环节")
    others = _in(ds, _BR, _OS)
    if others:
        parts.append(f"{'、'.join(others)}按单上的状态计；各域环节不同，按域分别给")
    return "处理环节：" + "；".join(parts)


def level(ds: Iterable[str]) -> str:
    head = "国内 2024-04-17 之前建的单没有问题等级，记为未填；" if _CN in set(ds) else ""
    return f"问题等级：{head}「A 级及以上」含 A+、A"


def rate(ds: Iterable[str]) -> str:
    """不良率（总述「汇总不良率」）：国内分母为生产数量、巴西为影响数量，分域给；海外是单上原文，不汇总。"""
    parts = []
    if _CN in set(ds):
        parts.append("国内不良率 = 合计不良数量 ÷ 合计生产数量 × 100" if len(set(ds)) > 1
                     else "不良率 = 合计不良数量 ÷ 合计生产数量 × 100，保留 2 位小数")
    if _BR in set(ds):
        parts.append("巴西不良率 = 合计不良数量 ÷ 合计影响数量 × 100" if len(set(ds)) > 1
                     else "不良率 = 合计不良数量 ÷ 合计影响数量 × 100，保留 2 位小数")
    if len(_in(ds, _CN, _BR)) == 2:
        parts.append("保留 2 位小数；国内、巴西分母不同，分域给出，不合成跨域不良率")
    elif len(set(ds)) > 1 and _in(ds, _CN, _BR):
        parts[-1] += "，保留 2 位小数"
    if _OS in set(ds):
        parts.append("海外不良率为单上原文，未汇总")
    return "；".join(parts)


def rate_excluded(n: int, domain: str = _CN, *, named: bool = False) -> str:
    """不参与汇总不良率的单（总述「汇总不良率」）；几域一起时 `named` 写上域名。"""
    den = "影响数量" if domain == _BR else "生产数量"
    head = domain if named else ""
    return f"{head}不良数量为空、{den}为 0 或空的 {n} 张不参与"


#: 只有国内时的写法（S2 起这样写，单测按它比）
CLOSED = closed([_CN])
STOPPED = stopped([_CN])
STOPPED_EVER = "停线：「曾经停线」指停过线的单，已经重启的仍算"
CLOSE_TIME = close_time([_CN])
STOP_DAYS = stop_days([_CN])
FOLLOW = follow([_CN])
RESP_DEPT = resp_dept([_CN])
RESPONSIBLE = responsible([_CN])
CURRENT = current([_CN])
STAGES = stages([_CN])
LEVEL = level([_CN])
RATE = rate([_CN])
#: 巴西费用（巴西业务描述「费用」）
COST = "费用：涉及费用按费用明细合计大于 0 认定，不看「是否涉及费用」标记；美元、雷亚尔分别合计，不换算"
DEBIT = "扣款：最新一条处理过程上的扣款费用（美元），单独列出，未计入费用"


def cost_issues(n: int) -> str:
    return f"涉及费用的单 {n} 张（按费用明细认定）"


def merged(name: str | None) -> str:
    """跨域归并（总述「跨域归并」「统计口径说明」跨域归并一行）。"""
    if name == "问题类型":
        return "跨域归并：各域问题类型不完全相同，同名类型合并统计，名称不同各占一行；「—」表示该域没有此类型"
    if name == "问题等级":
        return "跨域归并：问题等级三域相同，按等级同名合并；某域某级没有单时为 0"
    if name in ("机型", "系列"):
        return "跨域归并：国内的机型与巴西、海外的大机型按名称同名合并，名称不同各占一行"
    if name == "结案与否":
        return "跨域归并：状态跨域只分已结案、未结案；巴西的待提交、已终止另列，「—」表示该域没有此项"
    return "跨域归并：三域按名称同名合并，名称不同各占一行；先给各域小计，再给合计"


def set_aside(items: Iterable[tuple[str, int]]) -> str:
    """巴西已结案 + 未结案少于巴西总单数，差额是另列的待提交、已终止（总述「跨域归并」）。"""
    text = "、".join(f"{label} {n} 张" for label, n in items)
    return f"巴西另列：{text}，不算已结案也不算未结案"


def small_sample(domain: str, n: int) -> str:
    return f"样本量：{domain}仅 {n} 张单，占比与趋势仅供参考"


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


def without(dim: str, n: int) -> str:
    return f"没有{dim}的 {n} 张未计入"


def resp_blank(no_need: int, undecided: int) -> str:
    return f"责任归属部门为空的单未归入部门：无需定责 {no_need} 张、未定责 {undecided} 张"
