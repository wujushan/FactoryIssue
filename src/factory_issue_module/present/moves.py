"""答后建议的候选（设计 §9.5「候选」「去重」，决策 2026-11-02「答后建议改由模型挑」）。

对本轮实际执行的每一步套几种「走一步」（下钻、换角度、收窄、换时间、比较、换域、导出、看另一面、上卷、找类似、
下一张），参数取自计划格式（`plan/schema.py`）与本轮沙箱产物，不另取数。动作作用在计划上，不按场景写模板。
结果为空的步骤只有「放宽」一种：只放宽一项的计划由 `relax_options` 拼出，执行层预查张数（`turn/execute.py::
_relax_neighbors`，决策 2026-11-03「结果为空时放宽一个条件」），张数不为 0 的才做成候选。

- 每条候选带意图键（去重用）、点了执行的计划、默认问句、问句里必须原样出现的取值（必带）、给模型看的依据。
  依据里的数（张数、驳回次数）原样取自沙箱，这里不算。
- 同一个底的候选可以两两叠加（`compose`），不能改同一处；叠加出的计划过一遍 `check_format`。
- 意图键：清单、统计、文字查找、临时统计按计划算（域、时间说法与日期依据、条件；统计另加分组、指标与比较）；
  详情按「单号 + 块」。本会话执行过的、推荐过的意图键与问句都在工作区 `suggest.seen`（§10），在里面的不进候选。
- 纯函数，不取数、不调模型。
"""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from factory_issue_module.declarations import DOMAINS
from factory_issue_module.domains import enums
from factory_issue_module.plan import clarify, names, schema, timespan
from factory_issue_module.present import columns
from factory_issue_module.text import terms as text_terms

DRILL = "下钻"
ANGLE = "换角度"
NARROW = "收窄"
RETIME = "换时间"
COMPARE = "比较"
REDOMAIN = "换域"
EXPORT = "导出"
ASPECT = "看另一面"
UP = "上卷"
SIMILAR = "找类似"
NEXT = "下一张"
#: 结果为空时只放宽一个条件（总述「结果为空时」，决策 2026-11-03「结果为空时放宽一个条件」）
RELAX = "放宽"
#: 默认顺序（模型出错、超时、关掉时按它取；交给模型的候选也按它截）：各动作轮流取一条
MOVE_ORDER = (RELAX, ASPECT, DRILL, ANGLE, NEXT, NARROW, EXPORT, UP, SIMILAR, COMPARE, RETIME, REDOMAIN)
#: 问句离不开本轮的上下文（「那近 90 天呢」）：同样的字在别的轮次是另一件事，只按意图键去重，不按问句
CONTEXT_MOVES = (RELAX,)
#: 放宽时间：第一个把原来的时间范围包含在内的；不限时间只在这几种日期依据下试（按停线、重启、结案日期筛时，
#: 不限时间就丢了「停过线」「重启过」「结案了」这层意思）
RELAX_LADDER = ("近 90 天", "近半年", "近一年")
UNLIMITED_TIME = "不限时间"
UNLIMITED_BASES = ("建单", "现场发现", "统计日期")

#: 换角度的维度（总述「初步分析维度」里能拿来分组的几个）；按月另给
ANGLE_DIMS = ("问题类型", "加工厂", "机型", "状态", "问题等级", "跟进部门")
ANGLE_MAX = 3
#: 换时间的说法与个数；只说「最近」的已有纠偏类按钮（`turn/execute.py::_recent_buttons`）
TIME_OPTIONS = ("近 30 天", "近 90 天", "今年", "去年")
TIME_MAX = 2
RECENT_WORDS = ("最近", "近期", "近来", "最近一段时间")
#: 比较：本期 → 上一期
PREVIOUS_PERIOD = {"今年": "去年", "本年": "去年", "去年": "前年", "本月": "上个月", "这个月": "上个月",
                   "本季度": "上季度", "这个季度": "上季度", "本周": "上周", "这周": "上周"}
#: 换域只在条件都是这几种时给（名字类条件到别的域多半对不上）
DOMAIN_FREE_FIELDS = ("问题类型", "问题等级", "状态")
DOMAIN_MAX = 2
#: 下钻到单：清单至多几张、文字查找与按号查单列出的前几张
DRILL_MAX = 3
DRILL_LIST_MAX = 2
#: 统计下钻到清单的前几组
DRILL_GROUPS = 2
#: 上卷用的时间
UP_TIME = "近 90 天"
#: 取值本身是常用字（问题类型「其他」、系列「其它」）：问句写明是哪一维的取值、这一维也算必带。只写「列出其他的单」
#: 读不出是问题类型「其他」还是上文以外的其余类型（总述「『其他』『剩下的』指什么」，决策 2026-11-06
#: 「其他理解与接着问的按钮不自相矛盾」）
GENERIC_VALUES = ("其他", "其它")
#: 不是用户能拿来筛的取值
PLACEHOLDERS = ("", "未填", "—", "-", "无", "未指定", "未识别机型", "物料", enums.OS_UNKNOWN_TYPE)
#: 块里的这些值不算有内容
_EMPTY_VALUES = ("", "未填", "—", "-", "无", "否")
#: 分组维度 → 条件名（统计下钻到清单时加的条件）；「域」改的是域
_DIM_FIELD = {d: d for d in schema.GROUP_DIMS if d in schema.FILTER_FIELDS}
_DIM_FIELD.update({"结案与否": "状态", "停线状态": "状态"})
_PERIODS = ("年", "季度", "月", "周")
_LIST_ONLY = ("columns", "add_columns", "export", "sort", "limit")
_AGG_ONLY = ("group_by", "metrics", "ranking", "top", "compare", "chart")
#: 看另一面：（按钮上的叫法，计划里的 aspects，块）
DETAIL_ASPECTS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("完整处理过程", ("完整处理过程",), "process"),
    ("原因与措施", ("原因", "措施"), "reasons"),
    ("其他在线订单", ("其他在线订单",), "other_orders"),
    ("附件", ("附件",), "all_attachments"),
    ("8D 报告", ("8D",), "eight_d"),
    ("费用", ("费用",), "cost"),
    ("发货单", ("发货单",), "delivery"),
    ("补料", ("补料",), "supplement"),
    ("库存处理", ("库存处理",), "stock"),
    ("设计更改", ("设计更改",), "design"),
)
#: 整张详情的意图键里的块名
WHOLE = "*"
_BY_LABEL = {d.label: d for d in DOMAINS}
_ISSUE_NO = re.compile(r"(?<![A-Za-z0-9])(?:ZC|BR|HW)\d{7}(?![0-9])", re.I)
_PAREN = re.compile(r"（[^）]*）|\([^)]*\)")


# ---------------------------------------------------------------------------- 写法与意图键


def compact(text: Any) -> str:
    """比较用的写法：NFKC、去空白、小写。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).lower()


def question_key(text: Any) -> str:
    return "问句|" + compact(text)


def _domains_of(p: Mapping[str, Any]) -> list[str]:
    raw = p.get("domains")
    value = raw.get("value") if isinstance(raw, dict) else raw
    return sorted(str(x) for x in schema.as_list(value) if str(x) in _BY_LABEL)


def cond_sig(step: Mapping[str, Any]) -> str:
    """条件的写法（域、时间说法与日期依据、条件），名字按 `names.key` 归一。"""
    p = step.get("params") or {}
    times = sorted([compact(t.get("said")), str(t.get("basis") or "建单")]
                   for t in schema.as_list(p.get("time")) if isinstance(t, dict) and t.get("said"))
    filters = sorted([str(f.get("field")), str(f.get("column") or ""), schema.OP_KINDS.get(str(f.get("op") or "是"), "eq"),
                      sorted(names.key(v) for v in schema.as_list(f.get("value")))]
                     for f in schema.as_list(p.get("filters"))
                     if isinstance(f, dict) and not schema.is_ref(f.get("value")))
    return json.dumps([_domains_of(p), times, filters], ensure_ascii=False)


def step_key(step: Mapping[str, Any]) -> str | None:
    """一步的意图键；详情、按号查单另算（`detail_key`）。"""
    skill = step.get("skill")
    p = step.get("params") or {}
    if skill == "list_issues":
        if p.get("export") is True:
            return "导出|" + cond_sig(step)
        sort = p.get("sort") if isinstance(p.get("sort"), dict) else {}
        return "清单|" + cond_sig(step) + json.dumps([sort.get("by"), sort.get("order"), p.get("limit")],
                                                    ensure_ascii=False)
    if skill == "aggregate":
        metrics = sorted(str(m) for m in schema.as_list(p.get("metrics")) if m not in ("单数", "占比"))
        group_by = sorted(str(g) for g in schema.as_list(p.get("group_by")))
        return "统计|" + cond_sig(step) + json.dumps([group_by, metrics, p.get("compare")], ensure_ascii=False)
    if skill == "text_search":
        return "找|" + text_terms.key(step)
    if skill == "custom_stats":
        return "临时|" + compact(p.get("describe")) + cond_sig(step)
    return None


def plan_key(plan: Mapping[str, Any]) -> str | None:
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    if len(steps) == 2 and steps[0].get("skill") == "text_search" and steps[1].get("skill") == "aggregate":
        group_by = sorted(str(g) for g in schema.as_list((steps[1].get("params") or {}).get("group_by")))
        return "统计|找:" + text_terms.key(steps[0]) + json.dumps(group_by, ensure_ascii=False)
    if len(steps) != 1:
        return None
    step = steps[0]
    if step.get("skill") == "issue_detail":
        p = step.get("params") or {}
        raw = p.get("issue")
        number = str(raw.get("value") if isinstance(raw, dict) else raw or "")
        aspects = [str(a) for a in schema.as_list(p.get("aspects"))]
        block = next((b for _l, asp, b in DETAIL_ASPECTS if list(asp) == aspects), WHOLE if not aspects else None)
        return detail_key(number, block or "、".join(aspects))
    return step_key(step)


def detail_key(number: str, block: str) -> str:
    return f"详情|{str(number).strip().upper()}|{block}"


# ---------------------------------------------------------------------------- 一步执行完的样子


@dataclass
class Done:
    """本轮执行完的一步（`turn/execute.py` 照 `StepRun`、`StepOut` 填）。"""

    sid: str
    skill: str
    step: dict
    #: 实际取了数的域
    domains: list[str] = field(default_factory=list)
    found: bool = False
    truncated: bool = False
    exported: bool = False
    #: 清单、统计：沙箱给的各段（domain、kind、title、name、found、empty、facts）
    segs: list[dict[str, Any]] = field(default_factory=list)
    #: 本步的引用值（键去掉了步骤编号）
    refs: dict[str, Any] = field(default_factory=dict)
    #: 详情：给出的单（沙箱块）与每张给出的块
    tickets: list[dict[str, Any]] = field(default_factory=list)
    shown: dict[str, list[str]] = field(default_factory=dict)
    spans: list[Any] = field(default_factory=list)
    #: 条件引用了前一步的结果（不套条件类动作）
    deferred: bool = False
    #: 结果为空时执行层预查过的放宽（张数不为 0 的）：{kind, what, value, count, plan, key}
    relax: list[dict[str, Any]] = field(default_factory=list)


def _car_content(ticket: Mapping[str, Any]) -> bool:
    """单上有 CAR 报告内容（有报告权限、报告有字）：整张详情只给了 CAR 编号。"""
    car = (ticket.get("blocks") or {}).get("car")
    return isinstance(car, Mapping) and has_content(car)


def asked_keys(d: Done) -> list[str]:
    """这一步执行过的意图键（与用户怎么说无关）。整张详情另记「原因与措施」，单上有 CAR 报告内容时不记（决策
    2026-11-02 第 3 条）。"""
    if d.skill == "issue_detail":
        out: list[str] = []
        aspects = [str(a) for a in schema.as_list((d.step.get("params") or {}).get("aspects"))]
        for t in d.tickets:
            number = str(t.get("number") or "")
            out += [detail_key(number, b) for b in d.shown.get(number, [])]
            if not aspects:
                out.append(detail_key(number, WHOLE))
                if not _car_content(t):
                    out.append(detail_key(number, "reasons"))
        return out
    if d.skill == "lookup_numbers":
        return [f"按号|{n.upper()}" for item in (d.refs.get("issues") or {}).values() if isinstance(item, Mapping)
                for n in item.get("numbers") or []]
    if d.deferred:
        return []
    key = step_key(d.step)
    return [key] if key else []


# ---------------------------------------------------------------------------- 候选


@dataclass
class Candidate:
    move: str
    key: str
    #: 代码写的默认问句（模型不写或写的不合格时用）
    query: str
    #: 问句里必须原样出现的取值
    must: tuple[str, ...] = ()
    #: 给模型看的依据（数取自沙箱）
    hint: str = ""
    plan: dict | None = None
    #: 能叠加时：同一个底（`Pool.bases`）与相对它的改动、改了哪几处
    base: str | None = None
    patch: dict | None = None
    parts: frozenset[str] = frozenset()
    #: 找类似：要模型写现象；没写时用的现象；这张单的问题描述（核对现象里的数）
    slot: bool = False
    slot_default: str | None = None
    source: str = ""
    #: 下钻到单：没用上的留给下一轮（§10 `suggest.carry`）
    carry: bool = False
    #: 默认的按钮文字（放宽：带预先查好的张数）；张数（模型写的按钮文字里要有它）
    label: str = ""
    count: int | None = None

    @property
    def by_context(self) -> bool:
        return self.move in CONTEXT_MOVES

    def to_carry(self) -> dict[str, Any]:
        return {"move": self.move, "key": self.key, "query": self.query, "must": list(self.must), "hint": self.hint,
                "plan": self.plan}


@dataclass
class Pool:
    items: list[Candidate] = field(default_factory=list)
    bases: dict[str, dict] = field(default_factory=dict)


@dataclass
class Context:
    today: date
    #: 可查的域、文字查找可用的域（域名）
    access: Sequence[str]
    text_access: Sequence[str]
    #: 本会话执行过、推荐过的意图键与问句（含本轮执行的）
    seen: set[str]
    #: 上一份清单、文字查找里没点开的单（工作区 `suggest.carry`）
    carry: Sequence[Mapping[str, Any]] = ()
    #: 本步各域能不能按这个维度统计：(维度, 域名列表, 日期依据) → bool
    dims_ok: Callable[[str, Sequence[str], str], bool] = lambda _d, _ds, _b: True


def has_content(block: Mapping[str, Any]) -> bool:
    if any((t or {}).get("rows") for t in block.get("tables") or []):
        return True
    return any(len(f) > 1 and str(f[1]).strip() not in _EMPTY_VALUES for f in block.get("fields") or [])


def _carried(step: Mapping[str, Any]) -> dict:
    """底：这一步的副本，条件都标沿用上一轮（`from: previous`），去掉步间引用。"""
    p = copy.deepcopy(dict(step.get("params") or {}))
    p.pop("within", None)
    if isinstance(p.get("domains"), dict):
        p["domains"]["from"] = "previous"
    for item in [*schema.as_list(p.get("time")), *schema.as_list(p.get("filters"))]:
        if isinstance(item, dict):
            item["from"] = "previous"
    return {"id": "s1", "skill": str(step.get("skill")), "when": None, "params": p}


def show_all_plan(step: Mapping[str, Any]) -> dict | None:
    """「看全部」按钮点了执行的计划（张数是程序定的那一步，规整第 20 条，G95）：同样的条件与排法，去掉张数、全部
    导出。条件标沿用上一轮，开头会写明沿用了哪些。"""
    base = _carried(step)
    base["params"].pop("limit", None)
    return build(base, [{"export": True}])


def build(base: Mapping[str, Any], patches: Sequence[Mapping[str, Any]]) -> dict | None:
    """底加上几处改动 → 一步的计划；过不了 `check_format` 时 None。有分组、指标、比较时是统计。"""
    step = copy.deepcopy(dict(base))
    p = step["params"]
    skill = str(step["skill"])
    for patch in patches:
        if patch.get("skill"):
            skill = str(patch["skill"])
        for f in patch.get("filters") or []:
            kept = [x for x in schema.as_list(p.get("filters")) if not (isinstance(x, dict) and x.get("field") == f["field"])]
            p["filters"] = [*kept, copy.deepcopy(dict(f))]
        if "time" in patch:
            p["time"] = copy.deepcopy(list(patch["time"]))
            p.pop("compare", None)
        if patch.get("compare"):
            p["compare"] = patch["compare"]
        if patch.get("domains"):
            p["domains"] = {"value": list(patch["domains"]), "from": "user"}
        if patch.get("group_by"):
            p["group_by"] = list(patch["group_by"])
        if patch.get("metrics"):
            p["metrics"] = list(patch["metrics"])
        if patch.get("export"):
            p["export"] = True
    if any(patch.get(k) for patch in patches for k in ("group_by", "metrics", "compare")):
        skill = "aggregate"
    if skill == "aggregate" and step["skill"] != "aggregate":
        for k in _LIST_ONLY:
            p.pop(k, None)
    if skill == "list_issues" and step["skill"] != "list_issues":
        for k in _AGG_ONLY:
            p.pop(k, None)
    step["skill"] = skill
    plan = {"understanding": "", "alternatives": [], "steps": [step]}
    return None if schema.check_format(plan) else plan


def compose(pool: Pool, a: Candidate, b: Candidate) -> Candidate | None:
    """同一个底、改的不是同一处的两条合成一条。"""
    if a is b or not (a.base and a.base == b.base and a.patch is not None and b.patch is not None):
        return None
    if a.parts & b.parts:
        return None
    plan = build(pool.bases[a.base], [a.patch, b.patch])
    key = plan_key(plan) if plan else None
    if plan is None or key is None:
        return None
    query = f"{a.query}，{b.query}"
    joined = f"{_face(a)}，{_face(b)}"
    fallback = joined if len(clarify.button_label(joined)) <= clarify.LABEL_MAX else "一起看这两项"
    return Candidate(move=f"{a.move}+{b.move}", key=key, query=query, must=(*a.must, *b.must),
                     hint="；".join(x for x in (a.hint, b.hint) if x), plan=plan,
                     label=_short_label(query, fallback))


def detail_plan(number: str, aspects: Sequence[str] = ()) -> dict:
    params: dict[str, Any] = {"issue": {"value": number, "from": "user"}}
    if aspects:
        params["aspects"] = list(aspects)
    return {"understanding": "", "alternatives": [], "steps": [{"id": "s1", "skill": "issue_detail", "when": None,
                                                                 "params": params}]}


def similar_plan(phenomenon: str) -> dict:
    return {"understanding": "", "alternatives": [], "steps": [{"id": "s1", "skill": "text_search", "when": None,
                                                                 "params": {"mode": "类似问题",
                                                                            "phenomenon": phenomenon}}]}


def with_phenomenon(plan: Mapping[str, Any], phenomenon: str) -> dict:
    out = copy.deepcopy(dict(plan))
    out["steps"][0]["params"]["phenomenon"] = phenomenon
    return out


def _face(c: Candidate) -> str:
    """按钮上的字：候选准备了短标签就用它，否则用问句。"""
    return c.label or clarify.button_label(c.query)


def _short_label(query: str, fallback: str) -> str:
    """问句不超过 30 字时不另写标签（`follow_up` 用问句）；超过时用一句说完的短标签。"""
    shown = clarify.fit_label(query, fallback)
    return "" if shown == clarify.button_label(query) else shown


def _words(*parts: str) -> str:
    """把几段拼成一句：汉字与字母数字之间空一格（「国内 A920 近 90 天的问题」）。"""
    out = ""
    for part in parts:
        part = str(part).strip()
        if not part:
            continue
        if out and (out[-1].isascii() and out[-1].isalnum() or part[0].isascii() and part[0].isalnum()):
            out += " "
        out += part
    return out


class _Adder:
    def __init__(self, pool: Pool, C: Context) -> None:
        self.pool, self.C = pool, C
        self.keys: set[str] = set()

    def __call__(self, c: Candidate | None) -> None:
        if c is None or not c.key or c.key in self.keys:
            return
        if c.key in self.C.seen or (not c.by_context and question_key(c.query) in self.C.seen):
            return
        self.keys.add(c.key)
        self.pool.items.append(c)

    def patched(self, move: str, base_id: str, patch: dict, parts: Iterable[str], query: str,
                must: Sequence[str], hint: str = "", label: str = "") -> None:
        plan = build(self.pool.bases[base_id], [patch])
        key = plan_key(plan) if plan else None
        if plan is None or key is None:
            return
        self(Candidate(move=move, key=key, query=query, must=tuple(must), hint=hint, plan=plan, base=base_id,
                       patch=patch, parts=frozenset(parts), label=label))


def _filters(step: Mapping[str, Any]) -> list[dict]:
    return [f for f in schema.as_list((step.get("params") or {}).get("filters")) if isinstance(f, dict)]


def _single_value_fields(step: Mapping[str, Any]) -> set[str]:
    """按单个取值筛的条件名（按它分组没有意义）。"""
    out = set()
    for f in _filters(step):
        values = schema.as_list(f.get("value"))
        if schema.OP_KINDS.get(str(f.get("op") or "是")) == "eq" and len(values) == 1 and not schema.is_ref(values[0]):
            out.add(str(f.get("field")))
    return out


def _basis(step: Mapping[str, Any]) -> str:
    for t in schema.as_list((step.get("params") or {}).get("time")):
        if isinstance(t, dict) and t.get("basis"):
            return str(t["basis"])
    return "建单"


def _angle_dims(d: Done, C: Context) -> list[str]:
    p = d.step.get("params") or {}
    used = {str(g) for g in schema.as_list(p.get("group_by"))} | _single_value_fields(d.step)
    return [dim for dim in ANGLE_DIMS if dim not in used and C.dims_ok(dim, d.domains, _basis(d.step))]


def _months(spans: Sequence[Any]) -> int:
    """时间跨几个月（只看第一项；不限时间、只有一头的算 0）。"""
    if not spans:
        return 0
    s = spans[0]
    if getattr(s, "start", None) is None or getattr(s, "end", None) is None:
        return 0
    return (s.end.year - s.start.year) * 12 + s.end.month - s.start.month + 1


def _time_moves(d: Done, C: Context, add: _Adder, base_id: str, *, compare_ok: bool) -> None:
    p = d.step.get("params") or {}
    times = [t for t in schema.as_list(p.get("time")) if isinstance(t, dict) and t.get("said")]
    if len(times) != 1 or p.get("compare"):
        return
    t = times[0]
    said, basis = str(t["said"]).strip(), str(t.get("basis") or "建单")
    if compact(said) in {compact(w) for w in RECENT_WORDS}:
        return
    n = 0
    for option in TIME_OPTIONS:
        if n >= TIME_MAX:
            break
        try:
            same = timespan.same_time(said, option, C.today)
        except Exception:  # noqa: BLE001 —— 认不出的说法当作不同
            same = False
        if same or compact(option) == compact(said):
            continue
        add.patched(RETIME, base_id, {"time": [{"said": option, "basis": basis, "from": "user"}]}, ["time"],
                    f"换成{option}看看", [option])
        n += 1
    previous = PREVIOUS_PERIOD.get(compact(said))
    if compare_ok and previous and timespan.convert(previous, C.today) is not None:
        add.patched(COMPARE, base_id, {"time": [{**t, "from": "previous"},
                                                {"said": previous, "basis": basis, "from": "user"}],
                                       "compare": "时段"}, ["time"], f"和{previous}比一下", [previous])


def _domain_moves(d: Done, C: Context, add: _Adder, base_id: str) -> None:
    named = _domains_of(d.step.get("params") or {})
    if not named or any(str(f.get("field")) not in DOMAIN_FREE_FIELDS for f in _filters(d.step)):
        return
    n = 0
    for label in C.access:
        if label in named or n >= DOMAIN_MAX:
            continue
        add.patched(REDOMAIN, base_id, {"domains": [label]}, ["domains"], f"看看{label}的", [label])
        n += 1


def _drill_issue(number: str, hint: str) -> Candidate:
    return Candidate(move=DRILL, key=detail_key(number, WHOLE), query=f"{number} 的详情", must=(number,), hint=hint,
                     plan=detail_plan(number), carry=True)


def _numbers(issues: Mapping[str, Any]) -> list[str]:
    return [str(n) for item in issues.values() if isinstance(item, Mapping) for n in item.get("numbers") or []]


def _usable(value: Any) -> bool:
    if isinstance(value, float) and math.isnan(value):  # 空值别写成「nan」拿去当条件
        return False
    text = str(value or "").strip()
    return bool(text) and text not in PLACEHOLDERS and "、" not in text


def _named_value(dim: str, value: str) -> str | None:
    """取值本身是「其他」「其它」时写成「问题类型为『其他』」（`GENERIC_VALUES`），其余 None（问句里只写取值）。"""
    return f"{dim}为「{value}」" if value in GENERIC_VALUES else None


def _after_list(d: Done, C: Context, pool: Pool, add: _Adder) -> None:
    if not d.found:
        return
    segs = [s for s in d.segs if not s.get("empty") and (s.get("found") or 0)]
    total = sum(int(s.get("found") or 0) for s in segs)
    marked: list[tuple[str, str]] = []
    for s in segs:
        f = s.get("facts") or {}
        marked += [(str(n), "停线中") for n in f.get("停线中的单") or []]
        marked += [(str(x[0]), f"不良率最高（{x[1]}）") for x in f.get("不良率最高的单") or [] if x]
    if total <= DRILL_MAX:
        marked += [(n, "列出的单") for n in _numbers(d.refs.get("issues") or {})]
    picked: dict[str, str] = {}
    for number, hint in marked:  # 同一张单只留第一个依据
        picked.setdefault(number, hint)
    for number, hint in list(picked.items())[:DRILL_MAX]:
        add(_drill_issue(number, hint))
    if d.deferred:
        return
    base_id = f"b:{d.sid}"
    pool.bases[base_id] = _carried(d.step)
    p = d.step.get("params") or {}
    limited = p.get("limit") is not None
    filtered = {str(f.get("field")) for f in _filters(d.step)}
    if not limited and total >= 3:
        for dim in _angle_dims(d, C)[:ANGLE_MAX]:
            add.patched(ANGLE, base_id, {"group_by": [dim]}, ["group"], f"按{dim}统计这些单", [dim])
    if not limited:
        if "状态" not in filtered:
            unclosed = sum(int((s.get("facts") or {}).get("未结案") or 0) for s in segs)
            stopped = sum(int((s.get("facts") or {}).get("停线中") or 0) for s in segs)
            if 0 < unclosed < total:
                add.patched(NARROW, base_id, {"filters": [_eq("状态", "未结案")]}, ["filter:状态"], "只看还没结案的",
                            ["结案"], f"其中未结案 {unclosed} 张")
            if 0 < stopped < total:
                add.patched(NARROW, base_id, {"filters": [_eq("状态", "停线中")]}, ["filter:状态"], "只看还在停线的",
                            ["停线"], f"其中停线中 {stopped} 张")
        for fld, fact in (("问题类型", "按问题类型"), ("加工厂", "按加工厂"), ("机型", "按机型（前五）")):
            if fld in filtered:
                continue
            for s in segs:
                pairs = [x for x in (s.get("facts") or {}).get(fact) or [] if x]
                if len(pairs) < 2 or not _usable(pairs[0][0]):
                    continue
                value, n = str(pairs[0][0]), pairs[0][1]
                patch: dict[str, Any] = {"filters": [_eq(fld, value)]}
                parts = [f"filter:{fld}"]
                if fld == "加工厂" and len(segs) > 1:  # 加工厂只在一域：域也限定到它
                    patch["domains"], parts = [str(s.get("domain"))], [*parts, "domains"]
                named = _named_value(fld, value)
                if named:
                    query = f"只看{named}的单"
                else:
                    query = f"只看{value}" if fld == "问题类型" else _words("只看", value, "的")
                add.patched(NARROW, base_id, patch, parts, query, [fld, value] if named else [value],
                            f"{fact}最多的是{value}（{n} 张）", _short_label(query, f"只看该{fld}"))
                break
    if d.truncated and not d.exported:
        plan = build(pool.bases[base_id], [{"export": True}])
        if plan is not None:
            add(Candidate(move=EXPORT, key="导出|" + cond_sig(plan["steps"][0]), query="把这些单全部导出",
                          must=("导出",), hint=f"共 {total} 张，表格没列全", plan=plan))
    _time_moves(d, C, add, base_id, compare_ok=not limited)
    _domain_moves(d, C, add, base_id)


def _eq(field_name: str, value: str) -> dict[str, Any]:
    return {"field": field_name, "op": "是", "value": value, "from": "user"}


def _group_seg(d: Done) -> dict[str, Any] | None:
    return next((s for s in d.segs if s.get("kind") == "group" and (s.get("found") or 0)), None)


def _after_aggregate(d: Done, C: Context, pool: Pool, add: _Adder) -> None:
    if not d.found or d.deferred:
        return
    p = d.step.get("params") or {}
    group_by = [str(g) for g in schema.as_list(p.get("group_by"))]
    compare = p.get("compare")
    base_id = f"b:{d.sid}"
    pool.bases[base_id] = _carried(d.step)
    if len(group_by) == 1 and group_by[0] not in _PERIODS and not compare:
        dim = group_by[0]
        seg = _group_seg(d)
        title = str((seg or {}).get("title") or dim)
        pairs = [x for x in ((seg or {}).get("facts") or {}).get("按" + title) or [] if x and _usable(x[0])]
        for value, n in [(str(x[0]), x[1]) for x in pairs][:DRILL_GROUPS]:
            if dim == "域":
                patch: dict[str, Any] = {"skill": "list_issues", "domains": [value]}
                parts = ["domains"]
            elif dim in _DIM_FIELD:
                patch, parts = {"skill": "list_issues", "filters": [_eq(_DIM_FIELD[dim], value)]}, [f"filter:{_DIM_FIELD[dim]}"]
            else:
                continue
            named = _named_value(dim, value)
            if named:
                query = f"列出{named}的单"
            else:
                query = _words("列出", value, "级的单") if dim == "问题等级" else _words("列出", value, "的单")
            add.patched(DRILL, base_id, patch, parts, query, [dim, value] if named else [value],
                        f"{title}为{value}的 {n} 张", _short_label(query, f"列出该{dim}"))
    if compare:
        _domain_moves(d, C, add, base_id)
        return
    for dim in _angle_dims(d, C)[:ANGLE_MAX]:
        add.patched(ANGLE, base_id, {"group_by": [dim]}, ["group"], f"按{dim}统计", [dim])
    if not any(g in _PERIODS for g in group_by) and _months(d.spans) >= 3:
        add.patched(ANGLE, base_id, {"group_by": ["月"]}, ["group"], "按月看趋势", ["月"])
    metrics = [str(m) for m in schema.as_list(p.get("metrics"))]
    if group_by and "结案周期" not in metrics:
        add.patched(ANGLE, base_id, {"metrics": [*metrics, "结案周期"]}, ["metric"], "各组平均多久结案", ["结案"])
    _time_moves(d, C, add, base_id, compare_ok=True)
    _domain_moves(d, C, add, base_id)


def _field_values(ticket: Mapping[str, Any]) -> dict[str, str]:
    """各块里的「显示名 → 值」（先出现的为准）。"""
    out: dict[str, str] = {}
    for block in (ticket.get("blocks") or {}).values():
        for f in (block or {}).get("fields") or []:
            if len(f) > 1:
                out.setdefault(str(f[0]), str(f[1]))
    return out


def _phenomenon(ticket: Mapping[str, Any], values: Mapping[str, str]) -> str | None:
    """这张单的第一个预设现象（国内）或巴西的问题现象，去掉括号里的归类，太长的不用。"""
    for label in (columns.detail("phen.PhenomenonDesc"), columns.detail("br.ProblemPhenomenon")):
        text = str(values.get(label) or "").strip()
        if not text or text in PLACEHOLDERS:
            continue
        first = _PAREN.sub("", text.split("\n")[0]).strip(" ，。；")
        if 2 <= len(compact(first)) <= 20:
            return first
    return None


def _block_hint(block: str, b: Mapping[str, Any], ticket: Mapping[str, Any]) -> str:
    if block == "process":
        rows = sum(len((t or {}).get("rows") or []) for t in b.get("tables") or [])
        rejects = int(((ticket.get("facts") or {}).get("驳回次数")) or 0)
        return f"操作记录 {rows} 条" + (f"，驳回过 {rejects} 次" if rejects else "")
    if block == "reasons" and _car_content(ticket):
        return "这张单关联了 CAR 报告，详情里只给了编号"
    return f"这张单有{str(b.get('title') or '这一项')}"


def _after_detail(d: Done, C: Context, pool: Pool, add: _Adder) -> None:
    if len(d.tickets) != 1:
        return
    t = d.tickets[0]
    number, label = str(t.get("number") or ""), str(t.get("domain") or "")
    dom = _BY_LABEL.get(label)
    if not number or dom is None:
        return
    blocks = t.get("blocks") or {}
    shown = set(d.shown.get(number, []))
    aspects = [str(a) for a in schema.as_list((d.step.get("params") or {}).get("aspects"))]
    for name, asp, block in DETAIL_ASPECTS:
        b = blocks.get(block)
        if not isinstance(b, Mapping) or block in shown or not has_content(b):
            continue
        if block == "all_attachments" and "attachments" in shown and len(b.get("fields") or []) <= 1:
            continue  # 只有填写问题那一步的附件，整张详情里已经给了
        add(Candidate(move=ASPECT, key=detail_key(number, block), query=f"{number} 的{name}", must=(number,),
                      hint=_block_hint(block, b, t), plan=detail_plan(number, asp)))
    if aspects:
        add(Candidate(move=ASPECT, key=detail_key(number, WHOLE), query=f"{number} 的详情", must=(number,),
                      hint="这张单还没看整张详情", plan=detail_plan(number)))
    values = _field_values(t)
    base_id = f"up:{number}"
    pool.bases[base_id] = {"id": "s1", "skill": "list_issues", "when": None, "params": {
        "domains": {"value": [label], "from": "user"},
        "time": [{"said": UP_TIME, "basis": "建单", "from": "user"}]}}
    for fld, key in (("机型", "machine"), ("加工厂", "factory"), ("供应商", "ven_name"), ("问题类型", "type")):
        try:
            value = values.get(columns.shown(key, dom))
        except KeyError:
            continue
        if not _usable(value):
            continue
        query = _words(label, str(value), UP_TIME + "的问题")
        add.patched(UP, base_id, {"filters": [_eq(fld, str(value))]}, [f"filter:{fld}"],
                    query, [str(value)], f"这张单的{fld}", _short_label(query, f"同{fld}近 90 天"))
    if label in C.text_access:
        try:
            desc = str(values.get(columns.shown("desc", dom)) or "").strip()
        except KeyError:
            desc = ""
        default = _phenomenon(t, values)
        if desc and desc not in PLACEHOLDERS or default:
            query = f"有没有出现过{default}的问题" if default else _words("和", number, "类似的问题")
            add(Candidate(move=SIMILAR, key=f"类似|{number}", must=(), query=query,
                          label=_short_label(query, "找类似问题"),
                          hint="这张单的问题描述：" + (desc[:120] if desc not in PLACEHOLDERS else "（未填）"),
                          plan=similar_plan(default or ""), slot=True, slot_default=default,
                          source=" ".join(x for x in (desc[:400], default or "") if x)))
    _next_moves(C, add, number)


def _next_moves(C: Context, add: _Adder, number: str | None) -> None:
    for c in C.carry:
        plan = c.get("plan")
        if not isinstance(plan, dict) or not c.get("key") or (number and number.upper() in str(c.get("key"))):
            continue
        add(Candidate(move=NEXT, key=str(c["key"]), query=str(c.get("query") or ""),
                      must=tuple(str(x) for x in c.get("must") or []),
                      hint="上一份清单里的：" + str(c.get("hint") or ""), plan=copy.deepcopy(plan)))


def _after_lookup(d: Done, C: Context, pool: Pool, add: _Adder) -> None:
    numbers = _numbers(d.refs.get("issues") or {})
    if len(numbers) == 1:
        number = numbers[0]
        add(Candidate(move=ASPECT, key=detail_key(number, WHOLE), query=f"{number} 的详情", must=(number,),
                      hint="只给了一行概况", plan=detail_plan(number)))
        for name, asp, block in DETAIL_ASPECTS[:2]:
            add(Candidate(move=ASPECT, key=detail_key(number, block), query=f"{number} 的{name}", must=(number,),
                          plan=detail_plan(number, asp)))
        _next_moves(C, add, number)
        return
    for number in numbers[:DRILL_LIST_MAX]:
        add(_drill_issue(number, "按号找到的单"))


def _after_text(d: Done, C: Context, pool: Pool, add: _Adder) -> None:
    if not d.found:
        return
    numbers = _numbers(d.refs.get("issues") or {})
    for number in numbers[:DRILL_LIST_MAX]:
        add(_drill_issue(number, "找到的单里排在前面的"))
    # 表格里的原因与措施只有一两句摘要（用户没点名列时才有这一列）：给排在最前那张的全文（决策 2026-11-04
    # 「表格里的原因与措施给摘要」）
    if numbers and not (d.step.get("params") or {}).get("columns"):
        name, aspects, block = next(x for x in DETAIL_ASPECTS if x[2] == "reasons")
        add(Candidate(move=ASPECT, key=detail_key(numbers[0], block), query=f"{numbers[0]} 的{name}",
                      must=(numbers[0],), hint="表格里的原因与措施只有一两句摘要",
                      plan=detail_plan(numbers[0], aspects)))
    if d.deferred:
        return
    first = _carried(d.step)
    for dim in ("问题类型", "机型", "加工厂")[:ANGLE_MAX]:
        if not C.dims_ok(dim, d.domains, _basis(d.step)):
            continue
        plan = {"understanding": "", "alternatives": [], "steps": [
            first, {"id": "s2", "skill": "aggregate", "when": None,
                    "params": {"within": {"ref": "s1.issues"}, "group_by": [dim]}}]}
        key = plan_key(plan)
        if key and not schema.check_format(plan):
            add(Candidate(move=ANGLE, key=key, query=f"按{dim}统计这些单", must=(dim,), plan=plan))


def _after_custom(d: Done, C: Context, pool: Pool, add: _Adder) -> None:
    if not d.found or d.deferred:
        return
    base_id = f"b:{d.sid}"
    pool.bases[base_id] = _carried(d.step)
    _time_moves(d, C, add, base_id, compare_ok=False)


_AFTER: dict[str, Callable[[Done, Context, Pool, _Adder], None]] = {
    "list_issues": _after_list, "aggregate": _after_aggregate, "issue_detail": _after_detail,
    "lookup_numbers": _after_lookup, "text_search": _after_text, "custom_stats": _after_custom,
}


# ---------------------------------------------------------------------------- 结果为空时放宽一个条件


@dataclass
class Relax:
    """结果为空时的一种放宽（只放宽一项）：点了执行的计划、意图键；没改时间时预查直接用本轮换算好的起止日期。"""

    kind: str  # time / unlimited / drop
    what: str  # 「近 90 天」「不限时间」，或去掉的条件名
    plan: dict
    key: str
    keep_spans: bool
    value: str = ""


def _contains(outer: Any, inner: Any) -> bool:
    return (outer is not None and inner is not None and outer.start is not None and outer.end is not None
            and outer.start <= inner.start and outer.end >= inner.end
            and (outer.start, outer.end) != (inner.start, inner.end))


def relax_options(step: Mapping[str, Any], spans: Sequence[Any], today: date, seen: set[str]) -> list[Relax]:
    """一步结果为空：时间放长一档、各去掉一个筛选条件、不限时间（按这个顺序），去掉本会话执行过、推荐过的。"""
    p = step.get("params") or {}
    base = _carried(step)
    times = [t for t in schema.as_list(p.get("time")) if isinstance(t, dict) and t.get("said")]
    single = len(times) == 1 and not p.get("compare")
    cur = spans[0] if spans else None
    timed = (single and cur is not None and getattr(cur, "start", None) is not None
             and getattr(cur, "end", None) is not None and not cur.unlimited and not cur.future)
    basis = str(times[0].get("basis") or "建单") if times else "建单"
    out: list[Relax] = []

    def add(kind: str, what: str, s: dict, keep: bool, value: str = "") -> bool:
        plan = {"understanding": "", "alternatives": [], "steps": [s]}
        key = plan_key(plan)
        if schema.check_format(plan) or not key or key in seen or any(x.key == key for x in out):
            return False
        out.append(Relax(kind=kind, what=what, plan=plan, key=key, keep_spans=keep, value=value))
        return True

    def retimed(said: str) -> dict:
        s = copy.deepcopy(base)
        s["params"]["time"] = [{"said": said, "basis": basis, "from": "user"}]
        return s

    if timed:  # 第一个包含原范围、本会话又没查过的那一档（上一轮查过近 90 天时试近半年）
        for option in RELAX_LADDER:
            if _contains(timespan.convert(option, today), cur) and add("time", option, retimed(option), False):
                break
    for i, f in enumerate(schema.as_list(p.get("filters"))):
        if not isinstance(f, dict) or schema.is_ref(f.get("value")) or f.get("value") in (None, "", []):
            continue
        s = copy.deepcopy(base)
        kept = [x for j, x in enumerate(schema.as_list(s["params"].get("filters"))) if j != i]
        if kept:
            s["params"]["filters"] = kept
        else:
            s["params"].pop("filters", None)
        name = str(f.get("column") or "其他") if f.get("field") == "其他" else str(f.get("field") or "")
        add("drop", name, s, True, "、".join(str(v) for v in schema.as_list(f.get("value"))))
    if timed and basis in UNLIMITED_BASES:
        add("unlimited", UNLIMITED_TIME, retimed(UNLIMITED_TIME), False)
    return out


def relax_text(kind: str, what: str) -> str:
    """「时间放到近 90 天」「不限时间」「不限加工厂」（诊断那句与依据里的说法）。"""
    return f"时间放到{what}" if kind == "time" else (UNLIMITED_TIME if kind == "unlimited" else f"不限{what}")


def _relax_candidates(d: Done, add: _Adder) -> None:
    for x in d.relax:
        n, what, kind = int(x["count"]), str(x["what"]), str(x["kind"])
        if kind == "time":
            query, label, must = f"那{what}呢", f"看{what}（{n} 张）", (what,)
            fallback = f"看这一档（{n} 张）"
        elif kind == "unlimited":
            query, label, must = f"{UNLIMITED_TIME}呢", f"{UNLIMITED_TIME}（{n} 张）", (UNLIMITED_TIME,)
            fallback = label
        else:
            query, label, must = f"不限{what}呢", f"不限{what}（{n} 张）", (what,)
            fallback = f"不限这项（{n} 张）"
        hint = f"{relax_text(kind, what)}有 {n} 张" + (f"（去掉「{x['value']}」）" if kind == "drop" and x.get("value")
                                                    else "")
        add(Candidate(move=RELAX, key=str(x["key"]), query=query, must=must, hint=hint, plan=x["plan"],
                      label=clarify.fit_label(label, fallback), count=n))


def collect(done: Sequence[Done], C: Context) -> Pool:
    """本轮各步的候选（去掉会话里执行过、推荐过的），按动作的默认顺序轮流排。结果为空的步骤只有放宽这一种。"""
    pool = Pool()
    add = _Adder(pool, C)
    for d in done:
        if not d.found:
            _relax_candidates(d, add)
            continue
        fn = _AFTER.get(d.skill)
        if fn is not None:
            fn(d, C, pool, add)
    pool.items = ranked(pool.items)
    return pool


def ranked(items: Sequence[Candidate]) -> list[Candidate]:
    """各动作轮流取一条（`MOVE_ORDER`），动作内保持加入的先后。"""
    by_move: dict[str, list[Candidate]] = {}
    for c in items:
        by_move.setdefault(c.move, []).append(c)
    order = [m for m in MOVE_ORDER if m in by_move] + [m for m in by_move if m not in MOVE_ORDER]
    out: list[Candidate] = []
    while any(by_move.get(m) for m in order):
        for m in order:
            if by_move.get(m):
                out.append(by_move[m].pop(0))
    return out


def issue_numbers(text: str) -> list[str]:
    return [m.upper() for m in _ISSUE_NO.findall(text or "")]
