"""计划格式（设计 §5.1、§5.2、§5.3 第 12 条）。计划格式只在这里定义一次。

- 枚举是唯一信源：规划提示（`plan/prompt.py`）、格式校验、规整与执行都从这里取。
- 计划在规整前后都以 JSON 对象（dict）流转：规整要改写结构（合并步骤、拆两路、改为追问），
  dict 上做最直接，也与规划器实测（`scripts/planner_spike/`）的分数同一套处理。下面的 pydantic 模型描述
  合格计划的形状，`params` 用 `extra="forbid"` 拦下格式之外的键（第 12 条）。
- 格式校验的报错文字会原样发回给模型重写，改一个字都要重跑对照集。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

SKILLS = (
    "list_issues", "lookup_numbers", "issue_detail", "aggregate", "text_search",
    "custom_stats", "verify_previous", "rerender", "introduce", "clarify",
)
#: 带条件参数（domains、time、filters）的技能
COND_SKILLS = ("list_issues", "aggregate", "text_search", "custom_stats")
FILTER_FIELDS = (
    "机型", "系列", "加工厂", "国内工厂", "物料名称", "料号", "PN", "供应商", "问题类型", "问题等级", "状态",
    "跟进部门", "跟进人", "当前责任人", "责任人", "责任归属部门", "产品在制属性", "不良率", "不良数量",
    "影响数量", "发现工位", "是否设计变更", "是否需要回复8D", "IQC意见", "原因分类", "处理结果", "其他",
)
OPS = ("是", "不是", "属于", "不属于", "包含", "大于", "小于", "不小于", "不大于", "介于")
#: 比较方式的同义写法（模型偶尔写出来的），格式校验照收，规整与执行按右侧的类别处理
OP_KINDS = {
    "是": "eq", "等于": "eq", "为": "eq", "属于": "eq", "包含": "has",
    "不是": "ne", "不等于": "ne", "不属于": "ne", "不包含": "nhas",
    "大于": "gt", "小于": "lt", "不小于": "ge", "大于等于": "ge", "不大于": "le", "小于等于": "le",
    "介于": "between", "区间": "between",
}
BASES = ("建单", "现场发现", "停线", "重启", "结案", "统计日期")
GROUP_DIMS = (
    "域", "问题类型", "机型", "系列", "加工厂", "国内工厂", "结案与否", "处理环节", "问题等级", "年", "季度",
    "月", "周", "跟进部门", "跟进人", "当前责任人", "责任人", "责任归属部门", "原因分类", "处理结果",
    "产品在制属性", "停线状态", "状态",
)
METRICS = ("单数", "占比", "未结案数", "合计不良率", "结案周期", "停线时长", "费用美元", "费用雷亚尔", "扣款")
TEXT_MODES = ("关键词", "话题", "类似问题", "点名字段")
TOPIC_SCOPES = ("话题本身", "比话题小", "组合说法", "清单外")
SORT_FIELDS = ("建单时间", "现场发现日期", "停线日期", "结案时间", "不良率", "不良数量", "影响数量")
SORT_ORDERS = ("升序", "降序")
ASPECTS = (
    "概况", "当前状态", "当前责任人", "跟进人", "责任人", "原因", "措施", "完整处理过程", "驳回", "停线与重启",
    "CAR", "订单", "其他在线订单", "发货单", "费用", "8D", "附件", "问题现象", "可能原因", "5Why", "PN", "机型",
    "物料", "补料", "库存处理", "设计更改",
)
CHARTS = ("柱状", "折线", "饼图", "不要图")
INTRODUCE_KINDS = ("寒暄", "能力", "只读请求", "超出范围")
CLARIFY_REASONS = ("「其他」指什么", "接不上上一轮", "现象太泛", "缺时间")
#: 步骤间引用能用的输出名
REF_OUTPUTS: dict[str, tuple[str, ...]] = {
    "aggregate": ("top1", "top_values", "increased", "total"),
    "list_issues": ("issues", "max_defect_rate_issue", "count"),
    "text_search": ("issues", "count"),
    "lookup_numbers": ("issues",),
    "custom_stats": (),
}
#: 步数上限：规划器实测（§1.3）按 6 步校验，设计 §5.1 写的「最多 5 步」是提示里的期望
MAX_STEPS = 6


class StepParams(BaseModel):
    """一步的参数。只列名字，取值的合法性由 `check_format` 逐项查（报错文字要发回给模型）。"""

    model_config = ConfigDict(extra="forbid")

    domains: Any = None
    time: Any = None
    filters: Any = None
    columns: Any = None
    add_columns: Any = None
    export: Any = None
    sort: Any = None
    limit: Any = None
    group_by: Any = None
    metrics: Any = None
    ranking: Any = None
    top: Any = None
    compare: Any = None
    numbers: Any = None
    issue: Any = None
    aspects: Any = None
    mode: Any = None
    terms: Any = None
    logic: Any = None
    fields: Any = None
    topic: Any = None
    phenomenon: Any = None
    ask: Any = None
    approach: Any = None
    describe: Any = None
    chart: Any = None
    kind: Any = None
    reason: Any = None
    question: Any = None
    options: Any = None
    within: Any = None


PARAM_KEYS = frozenset(StepParams.model_fields)
#: 实测里出现过、无害的两个，直接丢掉不打回：参数层的 `from`（`from` 只挂在各参数上）；
#: `topic_scope`（由代码判，第 1 条；多轮时模型从上文抄来）。规整时由代码重新写上 `topic_scope`。
PARAM_KEYS_DROPPED = frozenset({"from", "topic_scope"})


class Step(BaseModel):
    id: str
    skill: str
    when: Any = None
    params: StepParams


class Plan(BaseModel):
    understanding: str = ""
    alternatives: list[Any] = []
    steps: list[Step]


_THINK = re.compile(r"<think>.*?</think>", re.S)
_REF = re.compile(r"^s(\d+)\.([a-z_0-9]+)$")


def parse_reply(text: str) -> dict:
    """从模型回复里取出 JSON 对象（先剥 <think>）。取不出抛 ValueError。"""
    body = _THINK.sub("", text or "").strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回复里没有 JSON 对象")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("回复的 JSON 不是对象")
    return data


def is_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"ref"} and isinstance(value["ref"], str)


def unwrap_ref(value: Any) -> Any:
    """{"value": {"ref": "s2.issues"}, "from": "user"} 与 {"ref": "s2.issues"} 同义：模型常把引用包在 value 里。"""
    if isinstance(value, dict) and is_ref(value.get("value")):
        return value["value"]
    return value


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _check_ref(value: dict, ids: list[str], skills: dict[str, str], here: int, errors: list[str]) -> None:
    m = _REF.match(value["ref"].strip())
    if not m:
        errors.append(f"引用写法不对：{value['ref']}（应为 s1.输出名）")
        return
    sid, out = f"s{m.group(1)}", m.group(2)
    if sid not in ids[:here]:
        errors.append(f"引用 {value['ref']} 指向的步骤不在本步之前")
        return
    allowed = REF_OUTPUTS.get(skills[sid], ())
    if out not in allowed:
        errors.append(f"引用 {value['ref']}：{skills[sid]} 没有输出 {out}（可用：{'、'.join(allowed) or '无'}）")


def _extra_keys(params: dict) -> list[str]:
    try:
        StepParams.model_validate({k: v for k, v in params.items() if k not in PARAM_KEYS_DROPPED})
    except ValidationError as exc:
        return sorted(str(e["loc"][0]) for e in exc.errors() if e.get("type") == "extra_forbidden")
    return []


def check_format(plan: dict) -> list[str]:
    """第 12 条：格式校验。返回错误说明（发回给模型重写），空表示合格。"""
    errors: list[str] = []
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["缺少 steps，或 steps 为空"]
    if len(steps) > MAX_STEPS:
        errors.append(f"步骤太多（{len(steps)} 步，上限 {MAX_STEPS} 步）")
    ids: list[str] = []
    skills: dict[str, str] = {}
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"第 {i + 1} 步不是对象")
            ids.append("")
            continue
        sid = str(step.get("id") or "")
        if sid in ids:
            errors.append(f"步骤编号重复：{sid}")
        ids.append(sid)
        skill = step.get("skill")
        if skill not in SKILLS:
            errors.append(f"{sid}：技能 {skill!r} 不在技能清单里")
            continue
        skills[sid] = skill
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("skill") not in SKILLS:
            continue
        sid, skill = ids[i], step["skill"]
        params = step.get("params") or {}
        if not isinstance(params, dict):
            errors.append(f"{sid}：params 不是对象")
            continue
        unknown = _extra_keys(params)
        if unknown:
            errors.append(f"{sid}：params 里有格式之外的键 {'、'.join(unknown)}（参数直接写在 params 下，名字照格式说明）")
        if step.get("when") is not None:
            if is_ref(step["when"]):
                _check_ref(step["when"], ids, skills, i, errors)
            else:
                errors.append(f"{sid}：when 只能是 {{\"ref\": ...}} 或 null")
        for t in as_list(params.get("time")):
            if not isinstance(t, dict) or not t.get("said"):
                errors.append(f"{sid}：time 每项要有 said")
            elif t.get("basis", "建单") not in BASES:
                errors.append(f"{sid}：日期依据 {t.get('basis')!r} 不在 {'、'.join(BASES)} 里")
        for f in as_list(params.get("filters")):
            if not isinstance(f, dict):
                errors.append(f"{sid}：filters 每项要是对象")
                continue
            if f.get("field") not in FILTER_FIELDS:
                errors.append(f"{sid}：条件名 {f.get('field')!r} 不在条件清单里")
            # 清单外的常见同义写法（等于、大于等于…）照收，不为它打回重写
            if f.get("op", "是") not in OPS and f.get("op") not in OP_KINDS:
                errors.append(f"{sid}：比较方式 {f.get('op')!r} 不在 {'、'.join(OPS)} 里")
            if is_ref(f.get("value")):
                _check_ref(f["value"], ids, skills, i, errors)
        for g in as_list(params.get("group_by")):
            if g not in GROUP_DIMS:
                errors.append(f"{sid}：分组维度 {g!r} 不在维度清单里")
        for m in as_list(params.get("metrics")):
            if m not in METRICS:
                errors.append(f"{sid}：指标 {m!r} 不在指标清单里")
        c = params.get("compare")
        # 只认 "时段"；早期提示的对象写法（dict）照收，由规整统一成筛选加分组（第 4 条）
        if c is not None and not isinstance(c, dict):
            if c != "时段":
                errors.append(f"{sid}：compare 只能写 \"时段\"（对象对比改用筛选加分组）")
            elif len([t for t in as_list(params.get("time")) if isinstance(t, dict)]) < 2:
                errors.append(f"{sid}：比较两个时段时 time 要按先后写两项")
        s = params.get("sort")
        if s is not None:
            if not isinstance(s, dict) or s.get("by") not in SORT_FIELDS or s.get("order", "降序") not in SORT_ORDERS:
                errors.append(f"{sid}：sort 写 {{\"by\": 排序项, \"order\": 升序或降序}}，排序项取 {'、'.join(SORT_FIELDS)}")
        lim = params.get("limit")
        if lim is not None and (not isinstance(lim, int) or isinstance(lim, bool) or lim <= 0):
            errors.append(f"{sid}：limit 要写正整数")
        if skill == "text_search" and params.get("mode") not in TEXT_MODES:
            errors.append(f"{sid}：文字查找方式 {params.get('mode')!r} 不在 {'、'.join(TEXT_MODES)} 里")
        for key in ("within", "issue"):
            value = unwrap_ref(params.get(key))
            if is_ref(value):
                _check_ref(value, ids, skills, i, errors)
    return errors


def drop_ignored_keys(plan: dict) -> dict:
    """丢掉 `PARAM_KEYS_DROPPED` 里的键（就地，返回同一个对象）。在格式校验通过之后、规整之前调。"""
    for step in plan.get("steps") or []:
        params = step.get("params") if isinstance(step, dict) else None
        if isinstance(params, dict):
            for key in PARAM_KEYS_DROPPED:
                params.pop(key, None)
    return plan
