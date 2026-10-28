"""规整与校验（设计 §5.3，确定性）。原型是 `scripts/planner_spike/resolve.py`，S1 起 spike 改调这里。

规则编号同设计 §5.3：
- 不改口径、直接改写：第 1 条话题范围（`topic_scope`）；第 2 条合并重复统计；第 3 条追问与取数混在一起时只留追问；
  第 4 条写法统一；第 5 条后半「沿用的清单并进后一步」（`fold_previous_list`）；第 6 条检索文字里去掉条件值。
  第 5 条前半「详情并进前一步」在执行层（S2 起）。
- 改口径、判据可证明：第 7 条名字归类；第 8 条写成时间的状态改回条件；第 9 条「X 各款」；第 10 条栏目要点名；
  第 11 条安全问题两路；第 17 条汇总缺时间改为追问；第 18 条上一轮没有结果时「其中」改为追问。
- 校验、打回重写：第 12 条格式在 `plan/schema.py`；第 7 条的校验一半、第 13、14、15 条在 `tagged_checks`
  （第 14 条在对照集期望计划上误拒为 0，已启用）；第 16 条 `values_not_in_query` 只记日志。

名字归类要的「库里的取值」由调用方给（`classes`：类 → 名字）：线上是可查的域的主数据，spike 是它的示意名单。
每次改写记一条 `RuleHit`（规则编号、技能、改前改后的条件名），由规划器打日志 `factory_issue_plan_rule`。
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

from factory_issue_module.config.files import TopicTerms
from factory_issue_module.plan import timespan
from factory_issue_module.plan.prematch import ISSUE_NUMBER, find_entities, find_numbers

# ---------------------------------------------------------------------------- 归一


_STRIP = re.compile(r"[\s\-_·'\"「」『』“”‘’《》]+")


def norm(text: object) -> str:
    """比较用的归一：全角转半角（NFKC）、小写、去空白与常见引号连字符。"""
    if text is None:
        return ""
    return _STRIP.sub("", unicodedata.normalize("NFKC", str(text)).lower())


_FIELD_SYNONYMS = {
    "问题跟进人": "跟进人", "问题跟进部门": "跟进部门", "责任部门": "责任归属部门",
    "当前处理人": "当前责任人", "问题等级": "问题等级", "等级": "问题等级",
    "类型": "问题类型", "问题分类": "问题类型", "工厂": "加工厂",
}


def norm_field(name: object) -> str:
    key = norm(name)
    return norm(_FIELD_SYNONYMS.get(key, key))


def _as_list(v: Any) -> list:
    return [] if v is None else (v if isinstance(v, list) else [v])


# ---------------------------------------------------------------------------- 改写记录


@dataclass(frozen=True)
class RuleHit:
    rule: int
    skill: str
    before: tuple[str, ...]
    after: tuple[str, ...]
    #: 「改写」，或第 17 条「有的步骤有时间、有的没有」那种「只记日志」
    action: str = "改写"


@dataclass(frozen=True)
class Inferred:
    """第 7 条按库里的取值定了类（用户只给了名称，或说的类别对不上而改到另一类）：回答开头要写「按 X 理解」。

    模型本来就放对了类时计划不变，也要记下来，否则执行时看不出这是推断的（S2 起由呈现层用它）。
    """

    step: str
    field: str
    values: tuple[str, ...]


def _fields(obj: Any) -> tuple[str, ...]:
    """一步或几步里用到的条件名，去重排序（日志只记条件名，不记取值）。"""
    found: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for f in _as_list(x.get("filters")):
                if isinstance(f, dict) and isinstance(f.get("field"), str):
                    found.add(f["field"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return tuple(sorted(found))


def _snap(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def _skills(obj: Any) -> str:
    steps = obj.get("steps") if isinstance(obj, dict) and "steps" in obj else [obj]
    return "+".join(str(s.get("skill")) for s in _as_list(steps) if isinstance(s, dict))


class _Recorder:
    def __init__(self, hits: list[RuleHit] | None) -> None:
        self.hits = hits

    def run(self, rule: int, target: Any, fn: Any, *args: Any) -> Any:
        if self.hits is None:
            return fn(*args)
        before, skill, fields = _snap(target), _skills(target), _fields(target)
        out = fn(*args)
        if _snap(target) != before:
            self.hits.append(RuleHit(rule, skill, fields, _fields(target)))
        return out


# ---------------------------------------------------------------------------- 第 1 条 话题范围


@lru_cache(maxsize=8)
def _topic_index(topics: TopicTerms) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    names = {norm(t.name): t.name for t in topics.topics}
    terms: dict[str, set[str]] = {}
    for t in topics.topics:
        for term in t.terms:
            terms.setdefault(norm(term.text), set()).add(t.name)
    return names, {k: frozenset(v) for k, v in terms.items()}


_PAREN = re.compile(r"[（(].*?[)）]")
_TAIL = re.compile(r"(相关的?|有关的?|方面的?|类的?|的)?(问题|单|不良|异常)?$")


def topic_scope(topic: str | None, topics: TopicTerms) -> str | None:
    """用户说的话题 → 话题本身 / 比话题小 / 组合说法 / 清单外（对照说法清单判断，不用模型填的值）。

    - 带括号例子（「音频（喇叭、蜂鸣器）」），或去掉「相关的问题」一类尾巴后与话题名相同：话题本身。
    - 与清单里某个说法相同（「磁卡」「eSIM」「喇叭」「漏电」）：比话题小。
    - 含几个说法、同属一个话题（「电池鼓包」）：比话题小；分属不同话题、没有共同话题（「电池卡扣」）：组合说法。
    - 一个说法都不含：清单外（由助手临时提说法）。
    """
    if not topic:
        return None
    names, term_topics = _topic_index(topics)
    raw = str(topic)
    if _PAREN.search(raw):
        return "话题本身"
    core = norm(_TAIL.sub("", _PAREN.sub("", raw).strip()))
    if not core:
        return None
    if core in names:
        return "话题本身"
    if core in term_topics:
        return "比话题小"
    hits = [set(ts) for term, ts in term_topics.items() if len(term) >= 2 and term in core]
    if not hits:
        return "清单外"
    common = set.intersection(*hits)
    return "比话题小" if common else "组合说法"


# ---------------------------------------------------------------------------- 第 7 条 名字归类

#: 同一组里的几类存的是同一批名字（同一批人、同一批部门），组内换不换由语义定，代码不动
NAME_GROUPS: dict[str, tuple[str, ...]] = {
    "工厂": ("加工厂", "国内工厂"),
    "人": ("跟进人", "当前责任人", "责任人"),
    "部门": ("跟进部门", "责任归属部门"),
    "供应商": ("供应商",),
    "系列": ("系列",),
}
_FIELD_GROUP = {norm_field(f): g for g, fields in NAME_GROUPS.items() for f in fields}
GROUP_LABEL = {"工厂": "加工厂", "人": "人员", "部门": "部门", "供应商": "供应商", "系列": "系列"}

#: 类别词：用户说了是哪一类。「跟进」同时是人员与部门的类别词（总述「某部门跟进的」即跟进部门）
CLASS_WORDS: dict[str, tuple[str, ...]] = {
    "工厂": ("工厂", "加工厂"),
    "人": ("跟进人", "跟进", "负责", "责任人", "处理人", "经办", "手上", "手里"),
    "部门": ("部门", "跟进"),
    "供应商": ("供应商", "厂商", "供方", "供应"),
    "系列": ("系列",),
}
_WORD_GROUPS: dict[str, set[str]] = {}
for _g, _ws in CLASS_WORDS.items():
    for _w in _ws:
        _WORD_GROUPS.setdefault(norm(_w), set()).add(_g)
_WORDS_LONGEST_FIRST = sorted(_WORD_GROUPS, key=len, reverse=True)

#: 类 → 库里的名字（可查的域）。部门简称、国内工厂的地区说法也放进对应的类：它们与配置整串相同也算完全相同
NameClasses = Mapping[str, Sequence[str]]


def _class_words_in(q: str) -> set[str]:
    """问句（已归一）里出现的类别词。长词先认、认过的去掉：「跟进人」不再算一次「跟进」。"""
    found: set[str] = set()
    for w in _WORDS_LONGEST_FIRST:
        if w in q:
            found.add(w)
            q = q.replace(w, "\x00")
    return found


def _name_key(text: str, group: str) -> str:
    key = norm(text)
    if group == "工厂":
        key = re.sub(r"工厂$", "", key)
    elif group == "系列":
        key = re.sub(r"系列$", "", key)
    return key


def _found(value: str, group: str, classes: NameClasses) -> bool:
    """整串相同才算对上（G65：不用包含匹配）。工厂、系列比较前去掉末尾的「工厂」「系列」。"""
    v = _name_key(value, group)
    if len(v) < 2 and group != "系列":
        return False
    return any(v == _name_key(c, group) for c in classes.get(group, ()))


def _move(p: dict, f: dict, group: str) -> None:
    new_field = NAME_GROUPS[group][0]
    old_field = f.get("field")
    f["field"] = new_field
    gb = p.get("group_by")
    if isinstance(gb, list):
        p["group_by"] = [new_field if norm_field(g) == norm_field(old_field) else g for g in gb]


def _regroup(step: dict, query: str | None, classes: NameClasses,
             inferred: list[Inferred] | None = None) -> dict | None:
    """就地改类；只给名称、完全相同的不止一类时返回追问步骤（选项另由 §6.5 补）。

    按库里的取值定了类的（只对上一类，或改到另一类）记进 `inferred`，回答开头写「按 X 理解」。
    """
    if not query:
        return None

    def note(f: dict, values: list[str]) -> None:
        if inferred is not None:
            inferred.append(Inferred(str(step.get("id")), str(f.get("field")), tuple(values)))

    words = _class_words_in(norm(query))
    p = step.get("params") or {}
    for f in p.get("filters") or []:
        if not isinstance(f, dict):
            continue
        group = _FIELD_GROUP.get(norm_field(f.get("field")))
        values = f.get("value")
        if group is None or isinstance(values, dict) or values in (None, ""):
            continue
        values = values if isinstance(values, list) else [values]
        if not all(isinstance(v, str) for v in values):
            continue
        if not words:
            matched = [g for g in NAME_GROUPS if all(_found(v, g, classes) for v in values)]
            if len(matched) >= 2:
                said = "、".join(values)
                return {"id": "s1", "skill": "clarify", "when": None, "params": {
                    "reason": "名称对上多类", "question": f"「{said}」指的是哪一个？",
                    "options": [f"{said}：{GROUP_LABEL[g]}" for g in matched]}}
            if len(matched) == 1:
                if matched[0] != group:
                    _move(p, f, matched[0])
                note(f, values)
            continue
        if all(_found(v, group, classes) for v in values):
            continue
        own = {w for w in words if group in _WORD_GROUPS[w]}
        # 有所选那一类的类别词：不改类，只有「跟进」这种同时指两类的词在两类之间改；只有别的类的类别词：照旧
        candidates = {g for w in own for g in _WORD_GROUPS[w]} if own else set(NAME_GROUPS)
        others = [g for g in candidates if g != group and all(_found(v, g, classes) for v in values)]
        if len(others) == 1:
            _move(p, f, others[0])
            note(f, values)
    return None


_BRIDGE = r"(?:是|为|:)?$"


def _adjacent_groups(q: str, value: str) -> tuple[str, set[str]] | None:
    v = norm(value)
    if len(v) < 2:
        return None
    for m in re.finditer(re.escape(v), q):
        after, before = q[m.end():], q[:m.start()]
        for w in _WORDS_LONGEST_FIRST:
            if after.startswith(w) or re.search(re.escape(w) + _BRIDGE, before):
                return w, _WORD_GROUPS[w]
    return None


def _class_checks(steps: list[dict], query: str) -> list[str]:
    """第 7 条的校验一半：名字紧挨着某一类的类别词，计划却放进另一类。"""
    q = norm(query)
    errors: list[str] = []
    for s in steps:
        for f in _as_list((s.get("params") or {}).get("filters")):
            if not isinstance(f, dict):
                continue
            group = _FIELD_GROUP.get(norm_field(f.get("field")))
            if group is None:
                continue
            for v in _as_list(f.get("value")):
                hit = _adjacent_groups(q, v) if isinstance(v, str) else None
                if hit and group not in hit[1]:
                    said = "或".join(GROUP_LABEL[g] for g in sorted(hit[1]))
                    errors.append(f"问句里「{v}」紧挨着「{hit[0]}」，用户说的是{said}，{s.get('id')} 却把它放进了{f.get('field')}")
    return errors


# ---------------------------------------------------------------------------- 第 2 条 合并重复统计

_REF = re.compile(r"^s(\d+)\.(\w+)$")
_OP = {"是": "eq", "等于": "eq", "为": "eq", "属于": "eq", "包含": "has", "不是": "ne", "不属于": "ne", "不包含": "ne"}


def _has_ref(obj: Any) -> bool:
    if isinstance(obj, dict):
        return "ref" in obj or any(_has_ref(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_ref(v) for v in obj)
    return False


def _scope(step: dict) -> tuple | None:
    """统计的范围与分组；带步骤引用的不合并，返回 None。在 `_canonical` 之后调用。"""
    if step.get("skill") != "aggregate" or step.get("when") is not None:
        return None
    p = step.get("params") or {}
    if _has_ref(p):
        return None
    d = p.get("domains")
    dv = d.get("value") if isinstance(d, dict) else d
    domains = frozenset(norm(x) for x in _as_list(dv))
    time = frozenset((norm(t.get("said")), norm(t.get("basis") or "建单")) for t in _as_list(p.get("time")) if isinstance(t, dict))
    if p.get("compare") == "时段":
        time = time | {("compare", "时段")}
    filters = set()
    for f in _as_list(p.get("filters")):
        if isinstance(f, dict):
            filters.add((norm_field(f.get("field")), _OP.get(str(f.get("op") or "是"), norm(f.get("op"))),
                         frozenset(norm(v) for v in _as_list(f.get("value")))))
    group = {norm_field(g) for g in _as_list(p.get("group_by"))}
    return (domains, time, frozenset(filters), frozenset(group))


# ---------------------------------------------------------------------------- 第 4、8、9、10、6、11 条

#: 有这件事的日期条件时，同义的状态条件多余（结案时间只对已结案的单有，停线、重启日期同理）
_IMPLIED_STATUS = {"停线": {"曾经停线", "停过线"}, "结案": {"已结案", "结案"}, "重启": {"已重启", "重启"}}

#: 第 8 条：时间原话里没有时间词、日期依据却是停线 / 结案 / 重启时，改回状态条件
_TIME_WORD = re.compile(r"[0-9０-９一二三四五六七八九十两]|年|月|周|星期|天|日|号|季|今|去|昨|前|本|上|下|近|以来|至今|现在|q",
                        re.IGNORECASE)
_STATUS_OF_BASIS = {"停线": "曾经停线", "结案": "已结案", "重启": "已重启"}

#: 第 13 条（校验）：时间原话后面紧跟的事件词定日期依据
_SKIP_AFTER_TIME = re.compile(r"^(?:内|里|以来|已经|有|共|一共|总共|都|被|发生(?:了|过)?|出现(?:了|过)?)*")
_EVENT_BASIS = (("现场发现", "现场发现"), ("停过线", "停线"), ("停线", "停线"), ("停产", "停线"), ("重启", "重启"),
                ("结案", "结案"), ("关闭", "结案"), ("关掉", "结案"), ("建单", "建单"), ("新建", "建单"), ("创建", "建单"))


def _event_basis(query: str, said: str) -> str | None:
    at = query.find(said)
    if at < 0:
        return None
    rest = _SKIP_AFTER_TIME.sub("", query[at + len(said):].lstrip(" ，,的"))
    return next((b for w, b in _EVENT_BASIS if rest.startswith(w)), None)


def _time_rules(p: dict, query: str | None) -> None:
    items = [t for t in _as_list(p.get("time")) if isinstance(t, dict)]
    if not items:
        return
    keep = []
    for t in items:
        said, basis = str(t.get("said") or ""), norm(t.get("basis") or "建单")
        if said and basis in _STATUS_OF_BASIS and not _TIME_WORD.search(said):
            status = _STATUS_OF_BASIS[basis]
            filters = [f for f in _as_list(p.get("filters")) if isinstance(f, dict)]
            if not any(norm_field(f.get("field")) == "状态" and norm(status) in {norm(v) for v in _as_list(f.get("value"))}
                       for f in filters):
                filters.append({"field": "状态", "op": "是", "value": status, "from": t.get("from") or "user"})
            p["filters"] = filters
            continue
        keep.append(t)
    if keep:
        p["time"] = keep
    else:
        p.pop("time", None)


_EACH_MODEL = re.compile(r"\s*(?:各款|各型号|各个型号|所有型号|各种型号|全系列各型号)")


def _each_model_rule(p: dict, query: str | None) -> None:
    if not query:
        return
    for f in _as_list(p.get("filters")):
        if not isinstance(f, dict) or norm_field(f.get("field")) not in ("系列", "机型"):
            continue
        v = f.get("value")
        if not isinstance(v, str) or not v:
            continue
        at = query.find(v)
        if at >= 0 and _EACH_MODEL.match(query[at + len(v):]):
            old = f.get("field")
            f["field"], f["op"] = "机型", "包含"
            group = [("机型" if norm_field(g) == norm_field(old) else g) for g in _as_list(p.get("group_by"))]
            p["group_by"] = group if any(norm_field(g) == "机型" for g in group) else group + ["机型"]


_FIELD_CORE = re.compile(r"^问题|(?:分析|结果|内容|里|中)$")


def _named_fields_rule(step: dict, query: str | None) -> None:
    p = step.get("params") or {}
    if not query or step.get("skill") != "text_search" or norm(p.get("mode")) == "点名字段":
        return
    fields = _as_list(p.get("fields"))
    if not fields:
        return
    q = norm(query)
    kept = [f for f in fields if isinstance(f, str)
            and (norm(f) in q or (len(_FIELD_CORE.sub("", f)) >= 2 and norm(_FIELD_CORE.sub("", f)) in q))]
    if kept:
        p["fields"] = kept
    else:
        p.pop("fields")


_STRIPPABLE = {norm_field(f) for f in ("机型", "系列", "加工厂", "国内工厂", "供应商", "跟进人", "当前责任人", "责任人",
                                       "跟进部门", "责任归属部门")}


def _strip_condition_values(step: dict) -> None:
    p = step.get("params") or {}
    if step.get("skill") != "text_search":
        return
    values = []
    for f in _as_list(p.get("filters")):
        if isinstance(f, dict) and norm_field(f.get("field")) in _STRIPPABLE:
            values += [v for v in _as_list(f.get("value")) if isinstance(v, str) and len(v) >= 2]
    for key in ("phenomenon", "topic"):
        text = p.get(key)
        if not isinstance(text, str) or not values:
            continue
        new = text
        for v in values:
            new = re.sub(re.escape(v), "", new, flags=re.IGNORECASE)
        new = re.sub(r"^[\s的，,、]+|[\s，,、]+$", "", re.sub(r"\s{2,}", " ", new))
        if len(new) >= 2 and new != text:
            p[key] = new


_SAFETY = re.compile(r"安全问题|涉及安全|安全相关|安全方面|安全类")
_APLUS = re.compile(r"a\s*\+", re.IGNORECASE)


def _safety_rule(plan: dict, query: str | None) -> None:
    if not query or not _SAFETY.search(query) or _APLUS.search(query):
        return
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    if len(steps) != 1 or steps[0].get("skill") not in ("text_search", "list_issues"):
        return
    p = steps[0].get("params") or {}
    cond = {k: copy.deepcopy(p[k]) for k in ("domains", "time") if k in p}
    filters = [f for f in _as_list(p.get("filters")) if isinstance(f, dict) and norm_field(f.get("field")) != "问题等级"]
    plan["steps"] = [
        {"id": "s1", "skill": "list_issues", "when": None,
         "params": {**copy.deepcopy(cond), "filters": copy.deepcopy(filters)
                    + [{"field": "问题等级", "op": "是", "value": "A+", "from": "user"}]}},
        {"id": "s2", "skill": "text_search", "when": None,
         "params": {**cond, **({"filters": filters} if filters else {}), "mode": "话题", "topic": "安全", "ask": "现象",
                    "topic_scope": "话题本身"}},
    ]


# ---------------------------------------------------------------------------- 第 17、18 条

_CURRENT_STATUS = {norm(v) for v in ("未结案", "停线中", "进行中", "没结案", "未完成", "待处理", "待提交", "草稿")}
#: 用户明说不限时间（总述「必要澄清项」时间范围一行列出的说法都在其中）
#: 「累计」后接指标名时说的是怎么算（「累计不良率」「累计停线时长」），不是不限时间
ALL_TIME = re.compile(r"(?:所有|全部)(?:的)?(?:问题)?单|(?:不限|所有|全部)(?:的)?(?:时间|日期)|历来|至今|迄今|有史以来"
                      r"|一直以来|累计(?!的?(?:不良|停线|结案周期|费用|扣款|影响|金额))|历史上"
                      r"|都(?:出过|有过|有哪些|有什么|是哪些)")
_CURRENT_FIELDS = {norm_field(f) for f in ("当前责任人",)}
_CURRENT_GROUPS = {norm_field(f) for f in ("当前责任人", "处理环节", "状态", "停线状态", "结案与否")}
UNLIMITED_TIME = "不限时间"


def missing_time_clarify(today: date | None = None) -> dict:
    """追问时间的选项由代码给（总述「必要澄清项」示例回答）：上半年 7 月起为今年的、1–6 月为去年的。"""
    today = today or date.today()
    half = f"{today.year if today.month >= 7 else today.year - 1} 年上半年"
    return {"reason": "缺时间", "question": "要统计哪个时间段？", "options": ["今年", "近 30 天", half, UNLIMITED_TIME]}


def _is_current_state(p: dict) -> bool:
    for f in _as_list(p.get("filters")):
        if not isinstance(f, dict):
            continue
        name = norm_field(f.get("field"))
        if name in _CURRENT_FIELDS:
            return True
        if name == "状态" and {norm(v) for v in _as_list(f.get("value")) if isinstance(v, str)} & _CURRENT_STATUS:
            return True
    if [norm(m) for m in _as_list(p.get("metrics"))] == [norm("未结案数")]:
        return True
    return any(norm_field(g) in _CURRENT_GROUPS for g in _as_list(p.get("group_by")))


def _uses_previous(obj: Any) -> bool:
    if isinstance(obj, dict):
        return obj.get("from") == "previous" or any(_uses_previous(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_uses_previous(v) for v in obj)
    return False


def _has_time(plan: dict | None) -> bool:
    steps = [s for s in (plan or {}).get("steps") or [] if isinstance(s, dict)]
    return any(_as_list((s.get("params") or {}).get("time")) for s in steps)


_COND_SKILLS = ("list_issues", "aggregate", "text_search", "custom_stats")


def partial_time(plan: dict) -> bool:
    """第 17 条「有的步骤有时间、有的没有」：多半是模型漏写了共用条件，只记日志，G5 看了再定要不要校验。

    在前一步结果里算的（`within`、引用前一步、`when`）不算没时间。
    """
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict) and s.get("skill") in _COND_SKILLS]
    timed = [bool(_as_list((s.get("params") or {}).get("time"))) for s in steps]
    if not any(timed) or all(timed):
        return False
    return any(not t and s.get("when") is None and (s.get("params") or {}).get("within") is None
               and not _has_ref(s.get("params") or {}) for s, t in zip(steps, timed, strict=True))


def _missing_time_rule(plan: dict, query: str | None, previous: dict | None, today: date | None) -> None:
    if not query or ALL_TIME.search(query):
        return
    if _has_time(plan):
        return
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    # 沿用上一轮、而上一轮本来就没有时间：按不限建单时间统计；上一轮读不到时照常追问
    if previous is not None and _uses_previous(steps) and not _has_time(previous):
        return
    for s in steps:
        p = s.get("params") or {}
        if s.get("skill") not in ("aggregate", "custom_stats") or s.get("when") is not None:
            continue
        if p.get("within") is not None or _has_ref(p) or _is_current_state(p):
            continue
        plan["steps"] = [{"id": "s1", "skill": "clarify", "when": None, "params": missing_time_clarify(today)}]
        return


_IN_PREVIOUS = re.compile(r"其中|这些|这几张|这批|里面|里头|刚才那些|上面那些|刚才的")
NO_RESULT_REASON = "上一轮没有结果"
NO_RESULT_CLARIFY = {"reason": NO_RESULT_REASON, "question": "上一轮没有查到结果，没有可以接着统计的范围。", "options": []}


def _no_result_rule(plan: dict, query: str | None, previous_outcome: str | None, earlier_query: str | None) -> bool:
    if not query or not previous_outcome or not _IN_PREVIOUS.search(query):
        return False
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    if not any(_uses_previous(s) or (s.get("params") or {}).get("within") is not None for s in steps):
        return False
    params = copy.deepcopy(NO_RESULT_CLARIFY)
    if earlier_query:
        # 「查询今年 A920 的记录，其中按状态统计一下」：那句原话接上本轮原话（§5.3 第 18 条）
        params["options"] = [f"{earlier_query.rstrip('。？?！! ')}，{query}"]
    plan["steps"] = [{"id": "s1", "skill": "clarify", "when": None, "params": params}]
    return True


# ---------------------------------------------------------------------------- 第 4 条写法统一（汇总）


def _canonical(step: dict, query: str | None, rec: _Recorder) -> None:
    p = step.get("params")
    if not isinstance(p, dict):
        return
    rec.run(8, step, _time_rules, p, query)
    rec.run(9, step, _each_model_rule, p, query)
    rec.run(10, step, _named_fields_rule, step, query)
    rec.run(4, step, _unify, p, step)


def _unify(p: dict, step: dict) -> None:
    c = p.get("compare")
    if isinstance(c, dict):
        items = [x for x in _as_list(c.get("items")) if isinstance(x, str)]
        if norm(c.get("kind")) == "对象" and c.get("field"):
            fld = c["field"]
            filters = [f for f in _as_list(p.get("filters")) if isinstance(f, dict)]
            if not any(norm_field(f.get("field")) == norm_field(fld) for f in filters):
                filters.append({"field": fld, "op": "属于", "value": items, "from": "user"})
            p["filters"] = filters
            group = _as_list(p.get("group_by"))
            if not any(norm_field(g) == norm_field(fld) for g in group):
                group.append(fld)
            p["group_by"] = group
            p.pop("compare")
        else:
            if not _as_list(p.get("time")) and items:
                p["time"] = [{"said": it, "basis": "建单", "from": "user"} for it in items]
            p["compare"] = "时段"
    # 分组的取值是用户点名的几个时，排不排名结果一样
    named = {norm_field(f.get("field")) for f in _as_list(p.get("filters"))
             if isinstance(f, dict) and isinstance(f.get("value"), list) and len(f["value"]) >= 2
             and _OP.get(str(f.get("op") or "是"), "eq") == "eq"}
    if p.get("ranking") and p.get("top") is None and named & {norm_field(g) for g in _as_list(p.get("group_by"))}:
        p.pop("ranking")
    if len(_as_list(p.get("terms"))) <= 1:
        p.pop("logic", None)
    if step.get("skill") == "text_search" and not p.get("ask"):
        p["ask"] = "现象"
    issue = p.get("issue")
    if isinstance(issue, str):
        p["issue"] = {"value": issue, "from": "user"}
    elif isinstance(issue, dict) and set(issue) == {"ref"}:
        p["issue"] = {"value": issue, "from": "user"}
    bases = {norm(t.get("basis")) for t in _as_list(p.get("time")) if isinstance(t, dict)}
    implied = set().union(*(_IMPLIED_STATUS[b] for b in bases if b in _IMPLIED_STATUS)) if bases else set()
    if implied and isinstance(p.get("filters"), list):
        p["filters"] = [f for f in p["filters"] if not (
            isinstance(f, dict) and norm_field(f.get("field")) == "状态"
            and _OP.get(str(f.get("op") or "是"), "eq") == "eq"
            and {norm(v) for v in _as_list(f.get("value"))} <= {norm(x) for x in implied})]
        if not p["filters"]:
            p.pop("filters")


def _rewrite_refs(obj: Any, mapping: dict[str, str]) -> Any:
    if isinstance(obj, dict):
        if set(obj) == {"ref"} and isinstance(obj["ref"], str):
            m = _REF.match(obj["ref"].strip())
            if m and f"s{m.group(1)}" in mapping:
                return {"ref": f"{mapping['s' + m.group(1)]}.{m.group(2)}"}
            return obj
        return {k: _rewrite_refs(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_refs(v, mapping) for v in obj]
    return obj


def _merge_into(keep: dict, drop: dict) -> None:
    kp, dp = keep.setdefault("params", {}), drop.get("params") or {}
    if dp.get("ranking"):
        kp["ranking"] = True
    if kp.get("top") is None and dp.get("top") is not None:
        kp["top"] = dp["top"]
    metrics = _as_list(kp.get("metrics")) + [m for m in _as_list(dp.get("metrics")) if m not in _as_list(kp.get("metrics"))]
    if metrics:
        kp["metrics"] = metrics
    if kp.get("compare") is None and dp.get("compare") is not None:
        kp["compare"] = dp["compare"]


def merge_duplicate_aggregates(plan: dict) -> None:
    """第 2 条：几步统计的范围与分组都相同时合成一步。"""
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    kept: list[dict] = []
    mapping: dict[str, str] = {}
    scopes: list[tuple | None] = []
    for s in steps:
        sc = _scope(s)
        hit = next((i for i, other in enumerate(scopes) if sc is not None and other == sc), None)
        if hit is None:
            kept.append(s)
            scopes.append(sc)
            mapping[str(s.get("id"))] = str(s.get("id"))
        else:
            _merge_into(kept[hit], s)
            mapping[str(s.get("id"))] = str(kept[hit].get("id"))
    if len(kept) == len(steps):
        return
    renumber = {str(s.get("id")): f"s{i + 1}" for i, s in enumerate(kept)}
    final = {old: renumber[new] for old, new in mapping.items()}
    new_steps = []
    for s in kept:
        s = _rewrite_refs(s, final)
        s["id"] = final[str(s.get("id"))]
        new_steps.append(s)
    plan["steps"] = new_steps


# ---------------------------------------------------------------------------- 第 5 条后半

_LIST_ONLY_KEYS = {"domains", "time", "filters"}


def _all_previous(p: dict) -> bool:
    items = [p["domains"]] if p.get("domains") else []
    items += [x for key in ("time", "filters") for x in _as_list(p.get(key))]
    return bool(items) and all(isinstance(x, dict) and x.get("from") == "previous" for x in items)


def fold_previous_list(plan: dict) -> None:
    """清单只为后一步提供范围、条件又全是沿用上一轮的：把清单的条件并进后一步、去掉清单。"""
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    for lst in steps[:-1]:
        lp = lst.get("params") or {}
        if lst.get("skill") != "list_issues" or lst.get("when") is not None or set(lp) - _LIST_ONLY_KEYS:
            continue
        if not _all_previous(lp):
            continue
        ref = f"{lst.get('id')}.issues"
        users = [s for s in steps if s is not lst and ref in json.dumps(s, ensure_ascii=False)]
        if len(users) != 1:
            continue
        nxt = users[0]
        np_ = nxt.get("params") or {}
        if (nxt.get("skill") not in ("aggregate", "list_issues") or np_.get("within") != {"ref": ref}
                or json.dumps(np_, ensure_ascii=False).count(ref) != 1 or np_.get("time") or np_.get("domains")):
            continue
        np_.pop("within")
        for key in ("domains", "time"):
            if lp.get(key):
                np_[key] = copy.deepcopy(lp[key])
        np_["filters"] = copy.deepcopy(_as_list(lp.get("filters"))) + _as_list(np_.get("filters"))
        if not np_["filters"]:
            np_.pop("filters")
        kept = [s for s in steps if s is not lst]
        mapping = {str(s.get("id")): f"s{k + 1}" for k, s in enumerate(kept)}
        new_steps = []
        for s in kept:
            s = _rewrite_refs(s, mapping)
            s["id"] = mapping[str(s.get("id"))]
            new_steps.append(s)
        plan["steps"] = new_steps
        return


def _time_options(out: dict, today: date | None) -> dict:
    """模型自己写的「缺时间」追问，选项也换成代码给的那一套（第 17 条）。"""
    for s in out.get("steps") or []:
        if isinstance(s, dict) and s.get("skill") == "clarify" and isinstance(s.get("params"), dict) \
                and norm(s["params"].get("reason")) == norm("缺时间"):
            s["params"]["options"] = missing_time_clarify(today)["options"]
    return out


# ---------------------------------------------------------------------------- 入口


@dataclass
class Context:
    """规整要看的本轮信息。没给的项只是不做依赖它的那几条。"""

    query: str | None = None
    #: 上一轮的执行计划（工作区 `turn`），第 17 条用
    previous: dict | None = None
    #: 上一轮没有查到结果时的结局（工作区 `last`：追问、查出 0 张、出错），第 18 条用
    previous_outcome: str | None = None
    #: 最近一次查到结果的问句原话（工作区 `last`），第 18 条拼选项用
    earlier_query: str | None = None
    classes: NameClasses = field(default_factory=dict)
    topics: TopicTerms | None = None
    today: date | None = None
    hits: list[RuleHit] | None = None
    #: 第 7 条按库里的取值定的类（回答开头「按 X 理解」）
    inferred: list[Inferred] | None = None


def apply(plan: dict | None, ctx: Context) -> dict | None:
    """返回规整后的计划副本（不改原计划）。"""
    if plan is None:
        return None
    rec = _Recorder(ctx.hits)
    query = ctx.query
    out = copy.deepcopy(plan)
    clarify = next((s for s in out.get("steps") or [] if isinstance(s, dict) and s.get("skill") == "clarify"), None)
    if clarify is not None and len(out.get("steps") or []) > 1:
        if ctx.hits is not None:
            ctx.hits.append(RuleHit(3, _skills(out), _fields(out), ()))
        out["steps"] = [{**clarify, "id": "s1", "when": None}]
        return rec.run(17, out, _time_options, out, ctx.today)
    for step in out.get("steps") or []:
        if not isinstance(step, dict):
            continue
        p = step.get("params")
        if not isinstance(p, dict):
            continue
        _canonical(step, query, rec)
        rec.run(6, step, _strip_condition_values, step)
        if step.get("skill") == "text_search" and p.get("topic") and ctx.topics is not None:
            p["topic_scope"] = topic_scope(p["topic"], ctx.topics)
        ask = rec.run(7, step, _regroup, step, query, ctx.classes, ctx.inferred)
        if ask is not None:
            if ctx.hits is not None:
                ctx.hits.append(RuleHit(7, _skills(out), _fields(out), ()))
            out["steps"] = [ask]
            return out
    rec.run(11, out, _safety_rule, out, query)
    rec.run(5, out, fold_previous_list, out)
    rec.run(2, out, merge_duplicate_aggregates, out)
    if rec.run(18, out, _no_result_rule, out, query, ctx.previous_outcome, ctx.earlier_query):
        return out
    rec.run(17, out, _missing_time_rule, out, query, ctx.previous, ctx.today)
    if ctx.hits is not None and partial_time(out):
        ctx.hits.append(RuleHit(17, _skills(out), _fields(out), _fields(out), action="只记日志"))
    return rec.run(17, out, _time_options, out, ctx.today)


def time_checks(steps: list[dict], query: str, today: date) -> list[str]:
    """第 14 条：换算模块认得出的时间说法，不在任何一步的 `time` 里时打回。"""
    said = [str(t["said"]) for s in steps for t in _as_list((s.get("params") or {}).get("time"))
            if isinstance(t, dict) and t.get("said")]
    return [f"问句里的时间「{p}」没有写进计划的 time" for p in timespan.find_in(query, today)
            if not any(timespan.same_time(p, s, today) for s in said)]


def tagged_checks(
    plan: dict, query: str, entities: Mapping[str, Sequence[str]], today: date | None = None
) -> list[tuple[int, str]]:
    """第 7 条的校验一半、第 13、14、15 条：[(规则编号, 打回时交给模型的错误说明)]。`plan` 用规整后的。

    `entities` 是预匹配用的「名字 → 它在库里属于哪几类」（可查的域的主数据）。
    """
    errors: list[tuple[int, str]] = []
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    for s in steps:
        for t in _as_list((s.get("params") or {}).get("time")):
            if not isinstance(t, dict) or not t.get("said"):
                continue
            hit = _event_basis(query, str(t["said"]))
            if hit and norm(t.get("basis") or "建单") != norm(hit):
                errors.append((13, f"问句里「{t['said']}」后面是「{hit}」这件事，{s.get('id')} 这项时间的日期依据应为{hit}"))
    if any(s.get("skill") in ("introduce", "clarify") for s in steps):
        return errors
    errors += [(7, e) for e in _class_checks(steps, query)]
    errors += [(14, e) for e in time_checks(steps, query, today or date.today())]
    blob = norm(json.dumps(plan.get("steps"), ensure_ascii=False))
    nums = find_numbers(query)
    for raw, kind, _ in nums:
        if kind == ISSUE_NUMBER and norm(raw) not in blob:
            errors.append((15, f"问句里有问题编号「{raw}」，计划里没有用到它"))
    for text, kinds, _ in find_entities(query, entities, [s for *_, s in nums]):
        if "机型" in kinds and norm(text) not in blob:
            errors.append((15, f"问句里的「{text}」是机型，计划里没有这个条件"))
    return errors


def query_checks(
    plan: dict, query: str, entities: Mapping[str, Sequence[str]], today: date | None = None
) -> list[str]:
    """`tagged_checks` 只留错误说明；空表示通过。"""
    return [msg for _, msg in tagged_checks(plan, query, entities, today)]


#: 第 16 条只看这几类：照抄用户原话的名字
_NAMED_FIELDS = {norm_field(f) for f in ("机型", "加工厂", "国内工厂", "跟进部门", "责任归属部门", "跟进人",
                                         "当前责任人", "责任人", "供应商")}


def values_not_in_query(plan: dict, query: str) -> list[str]:
    """第 16 条：标为本轮说的机型、工厂、部门、人员、供应商取值，在问句里找不到的条件名（只记日志，不打回）。"""
    q = norm(query)
    missed: list[str] = []
    for s in plan.get("steps") or []:
        for f in _as_list((s.get("params") or {}).get("filters") if isinstance(s, dict) else None):
            if not isinstance(f, dict) or f.get("from", "user") != "user":
                continue
            if norm_field(f.get("field")) not in _NAMED_FIELDS:
                continue
            values = [v for v in _as_list(f.get("value")) if isinstance(v, str)]
            if any(norm(v) and norm(v) not in q for v in values):
                missed.append(str(f.get("field")))
    return sorted(set(missed))
