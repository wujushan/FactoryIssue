"""规整与校验（设计 §5.3，确定性）。原型是 `scripts/planner_spike/resolve.py`，S1 起 spike 改调这里。

规则编号同设计 §5.3：
- 不改口径、直接改写：第 1 条话题范围（`topic_scope`）；第 2 条合并重复统计；第 3 条追问与取数混在一起时只留追问；
  第 4 条写法统一；第 5 条后半「沿用的清单并进后一步」（`fold_previous_list`）；第 6 条检索文字里去掉条件值。
  第 5 条前半「详情并进前一步」在执行层（S4 随详情接上）。
- 改口径、判据可证明：第 7 条名字归类；第 8 条写成时间的状态改回条件；第 9 条「X 各款」；第 10 条栏目要点名；
  第 11 条安全问题两路；第 17 条汇总缺时间改为追问；第 18 条上一轮没有结果时「其中」改为追问。
- 校验、打回重写：第 12 条格式在 `plan/schema.py`；第 7 条的校验一半、第 13、14、15、19 条在 `tagged_checks`
  （第 14 条在对照集期望计划上误拒为 0，已启用）；第 16 条 `values_not_in_query` 只记日志。按词的位置判断的两条
  （第 7 条校验一半、第 13 条，`VERIFY_RULES`）打回时请模型核对、允许照原写法保留，说明里只写词的位置与计划写成了
  什么，不替用户下结论（决策 2026-11-06「按词的位置判断的校验改为请核对」）。
- 第 20 条 `reading_rule`（决策 2026-11-04「按什么理解写在开头」）：问题等级、状态、问题类型的取值在问句里找不到
  依据时记成助手的理解；清单张数在问句里找不到时改成默认张数并记下；都进 `inferred`，回答开头写「按 X 理解」。
  认出了程度说法、计划没按落盘的读法写时只记日志。

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

from factory_issue_module.config.defaults import ANSWER_PARAMS as ANSWER_DEFAULTS
from factory_issue_module.config.files import TopicTerms
from factory_issue_module.domains import enums
from factory_issue_module.plan import names, schema, timespan
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


#: `Inferred.kind`：第 7 条定的类；第 20 条助手按意思定的条件取值、程序定的张数
KIND_CLASS = "类"
KIND_VALUE = "取值"
KIND_COUNT = "张数"


@dataclass(frozen=True)
class Inferred:
    """回答开头要写的「按 X 理解」（总述「必要澄清项」之后「拿不准的问法」、「程度说法怎么理解」）。

    - `KIND_CLASS`（第 7 条）：按库里的取值定了类（用户只给了名称，或说的类别对不上而改到另一类）。模型本来就
      放对了类时计划不变，也要记下来，否则执行时看不出这是推断的。`values` 是名称，`field` 是定到的类。
    - `KIND_VALUE`（第 20 条）：问题等级、状态、问题类型的取值在问句里找不到依据，是助手按意思定的。`field` 是
      条件名（否定时带比较方式），`values` 是取值。
    - `KIND_COUNT`（第 20 条）：张数在问句里找不到，改成了默认张数。`field` 是排法（「按不良率从高到低」），
      `values` 是张数。
    `said` 是程序从问句里认出的程度说法原话（「比较严重」），没有为空。
    """

    step: str
    field: str
    values: tuple[str, ...]
    kind: str = KIND_CLASS
    said: str = ""


def inferred_text(inf: Inferred) -> str:
    """开头那一句（设计 §4.3 提示行）。"""
    if inf.kind == KIND_COUNT:
        n = inf.values[0] if inf.values else ""
        if inf.said:
            return f"「{inf.said}」{inf.field}列出前 {n} 张（没说要几张，默认列 {n} 张）"
        return f"没说要几张，{inf.field}列出前 {n} 张"
    if inf.kind == KIND_VALUE:
        shown = "、".join(inf.values)
        body = f"按{inf.field} {shown} 理解" if shown[:1].isascii() else f"按{inf.field}「{shown}」理解"
        return f"「{inf.said}」{body}" if inf.said else body
    return f"「{'、'.join(inf.values)}」按{inf.field}理解"


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


def topic_core(topic: str | None) -> str:
    """话题原话去掉括号里的例子与「相关的问题」一类尾巴，按比较用的写法归一（`topic_scope` 判范围用的同一个样子；
    文字查找定说法时也用它，S6）。"""
    return norm(_TAIL.sub("", _PAREN.sub("", str(topic or "")).strip()))


def topic_index(topics: TopicTerms) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """(归一后的话题名 → 话题名, 归一后的说法 → 它在哪几个话题里)。"""
    return _topic_index(topics)


def topic_display(topic: str | None) -> str:
    """话题原话去掉括号与尾巴、不改写法（回答里「与 X 有关」的 X）；去完为空时用原话。"""
    raw = str(topic or "").strip()
    return _TAIL.sub("", _PAREN.sub("", raw).strip()).strip() or raw


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

#: 类别词：用户说了是哪一类。「跟进」「负责」同时是人员与部门的类别词：总述「某部门跟进的」即跟进部门；国内、巴西
#: 「某部门负责的」按问题跟进部门，总述「某人负责的单」按责任人
CLASS_WORDS: dict[str, tuple[str, ...]] = {
    "工厂": ("工厂", "加工厂"),
    "人": ("跟进人", "跟进", "负责", "责任人", "处理人", "经办", "手上", "手里"),
    "部门": ("部门", "跟进", "负责"),
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


#: 自己的规则里有名称包含的几类（总述「某加工厂」「部门名称怎么对」「某供应商」）；人员、系列只认整串相同
_CONTAINS_GROUPS = ("工厂", "部门", "供应商")


def _contained(value: str, group: str, classes: NameClasses) -> bool:
    """这一类照自己的包含规则对得上（「鸿展光电」之于某家供应商的全称），G91。

    只用来定类：巴西工厂整段相等，合在工厂一类里也按包含看，真正对库仍照各域自己的规则（§6.5）。
    """
    if group not in _CONTAINS_GROUPS:
        return False
    v = _name_key(value, group)
    if len(v) < 2:
        return False
    return any(v in _name_key(c, group) for c in classes.get(group, ()))


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

    def by_contains(f: dict, group: str, values: list[str]) -> None:
        """一类都没有完全相同的（G91）：所选那一类照自己的包含规则对得上就照它，对不上而另外恰好只有一类对得上就
        改过去，两种都写「按 X 理解」。模型爱把没说类别的公司简称放进加工厂，供应商主数据又多是全称。"""
        if all(_contained(v, group, classes) for v in values):
            note(f, values)
            return
        hit = [g for g in NAME_GROUPS if g != group and all(_contained(v, g, classes) for v in values)]
        if len(hit) == 1:
            _move(p, f, hit[0])
            note(f, values)

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
        if any(names.is_self(v) for v in values):  # 「我」指当前用户，不是库里的名字，不改类
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
            elif not matched:
                by_contains(f, group, values)
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
        elif not others and not own:
            by_contains(f, group, values)
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
    """第 7 条的校验一半：名字紧挨着某一类的类别词，计划却放进另一类。

    只看词的位置，会误判（「研发一部经办的单」的「经办」说的是部门怎么处理，不是说研发一部是人），所以说明里只写
    位置与计划写成了什么，由模型核对（`VERIFY_RULES`）。"""
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
                    errors.append(f"问句里「{v}」紧挨着「{hit[0]}」，{s.get('id')} 把「{v}」放进了{f.get('field')}。"
                                  f"「{hit[0]}」若是在说「{v}」是{said}，按{said}写；不是就照原写法")
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


def _event_hit(query: str, said: str) -> tuple[str, str] | None:
    """(时间原话后面紧跟的事件词, 它定的日期依据)。"""
    at = query.find(said)
    if at < 0:
        return None
    rest = _SKIP_AFTER_TIME.sub("", query[at + len(said):].lstrip(" ，,的"))
    return next(((w, b) for w, b in _EVENT_BASIS if rest.startswith(w)), None)


def _event_basis(query: str, said: str) -> str | None:
    hit = _event_hit(query, said)
    return hit[1] if hit else None


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
    _self_values(p)
    _status_values(p)
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


#: 人员条件（取值是员工）
PERSON_FIELDS = ("跟进人", "当前责任人", "责任人")
_PERSON_FIELDS = {norm_field(f) for f in PERSON_FIELDS}


def _self_values(p: dict) -> None:
    """人员条件里指当前用户的写法（「本人」「自己」）统一成「我」（决策 2026-11-03「『我』按当前用户查」）。"""
    for f in _as_list(p.get("filters")):
        if not isinstance(f, dict) or norm_field(f.get("field")) not in _PERSON_FIELDS:
            continue
        v = f.get("value")
        if isinstance(v, str) and names.is_self(v):
            f["value"] = names.SELF
        elif isinstance(v, list) and any(isinstance(x, str) and names.is_self(x) for x in v):
            f["value"] = list(dict.fromkeys(names.SELF if isinstance(x, str) and names.is_self(x) else x for x in v))


#: 状态取值的同义写法（规划提示「『草稿』为 待提交」；执行层 `domains/enums.py` 同样认，这里统一成一种写法）
_STATUS_SYNONYMS = {norm("草稿"): "待提交", norm("未提交"): "待提交"}


def _status_values(p: dict) -> None:
    for f in _as_list(p.get("filters")):
        if not isinstance(f, dict) or norm_field(f.get("field")) != "状态":
            continue
        v = f.get("value")
        if isinstance(v, str) and norm(v) in _STATUS_SYNONYMS:
            f["value"] = _STATUS_SYNONYMS[norm(v)]
        elif isinstance(v, list):
            f["value"] = list(dict.fromkeys(_STATUS_SYNONYMS.get(norm(x), x) if isinstance(x, str) else x for x in v))


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
    #: 第 7 条按库里的取值定的类、第 20 条助手定的取值与张数（回答开头「按 X 理解」）
    inferred: list[Inferred] | None = None
    #: 第 20 条：没说要几张时列几张（模块配置 `top_n`，与「哪个最多」的前 N 名同一个数）；没给用内置默认
    default_limit: int | None = None


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
    out = rec.run(17, out, _time_options, out, ctx.today)
    rec.run(20, out, reading_rule, out, query, ctx.default_limit or DEFAULT_LIMIT,
            ctx.inferred if ctx.inferred is not None else [], ctx.hits)
    return out


def time_checks(steps: list[dict], query: str, today: date) -> list[str]:
    """第 14 条：换算模块认得出的时间说法，不在任何一步的 `time` 里时打回。"""
    said = [str(t["said"]) for s in steps for t in _as_list((s.get("params") or {}).get("time"))
            if isinstance(t, dict) and t.get("said")]
    return [f"问句里的时间「{p}」没有写进计划的 time" for p in timespan.find_in(query, today)
            if not any(timespan.same_time(p, s, today) for s in said)]


def basis_mismatches(plan: dict, query: str) -> list[tuple[str, str, str, str]]:
    """第 13 条：[(步骤编号, 时间原话, 计划里的日期依据, 问句里紧跟的事件词定的依据)]。

    校验与执行共用：修一次仍不一致时按计划执行，开头写明按什么日期理解，并给另一种理解的按钮（S2 起）。
    """
    out: list[tuple[str, str, str, str]] = []
    for s in [s for s in plan.get("steps") or [] if isinstance(s, dict)]:
        for t in _as_list((s.get("params") or {}).get("time")):
            if not isinstance(t, dict) or not t.get("said"):
                continue
            hit = _event_basis(query, str(t["said"]))
            basis = str(t.get("basis") or "建单")
            if hit and norm(basis) != norm(hit):
                out.append((str(s.get("id")), str(t["said"]), basis, hit))
    return out


#: 第 19 条：问句里指一张单的说法（「这张物料单」「这单」「该单」「它」）；「这些单」「这几张单」指一批，不算
_THIS_ISSUE = re.compile(r"(?:这|该|此|那)(?:一)?(?:张|个|条|份)?[^\s，,。？?！!、；;：:些几]{0,4}?单|(?<!其)它")


def previous_issue(previous_plan: Mapping[str, Any] | None, last_user: str | None = None) -> str | None:
    """第 19 条：上一轮单独说到的那张问题单（恰好一个问题编号），没有时为 None。

    有上一轮计划时只看计划的步骤；读不到计划（工作区过期、没有会话号）时看上一轮的用户问句。
    """
    if previous_plan:
        text = json.dumps(previous_plan.get("steps"), ensure_ascii=False)
    else:
        text = last_user or ""
    found = {norm(raw): raw for raw, kind, _ in find_numbers(text) if kind == ISSUE_NUMBER}
    return next(iter(found.values())) if len(found) == 1 else None


def _out_of_scope_on_previous_issue(steps: list[dict], query: str, issue: str | None) -> str | None:
    """第 19 条：问句指上一轮那张单，计划却写成「超出范围」的介绍（CN-053「这张物料单为什么机型显示『物料』」）。"""
    if issue is None or not any(
        s.get("skill") == "introduce" and norm((s.get("params") or {}).get("kind")) == norm("超出范围")
        for s in steps
    ):
        return None
    hit = _THIS_ISSUE.search(query)
    if hit is None:
        return None
    return (f"问句里的「{hit.group(0)}」指上一轮说到的问题单 {issue}，问的是这张单上的内容（某一栏为什么这样显示、"
            f"为什么没有某一项），不是本助手管不着的事：用 issue_detail，issue 写 "
            f'{{"value": "{issue}", "from": "previous"}}，aspects 写要看的内容，都对不上时写「其他:要看的内容」。'
            "问的是本助手没有的数据项，或要做只读之外的事时，仍写 introduce")


#: 按词的位置判断的校验：第 7 条的校验一半、第 13 条。打回时请模型核对，原写法没错就照原样保留；其余校验（第 14、
#: 15、19 条）与格式（第 12 条）写「不合格」、要改（设计 §5.3 准入准则，决策 2026-11-06「按词的位置判断的校验改为
#: 请核对」）。模型核对后照原写法时按它的计划执行，第 13 条照旧在开头写明按什么日期理解
VERIFY_RULES = frozenset({7, 13})


def split_checks(checks: Sequence[tuple[int, str]]) -> tuple[list[str], list[str]]:
    """`tagged_checks` 的结果 → (不合格、要改的说明, 请模型核对的说明)，给 `prompt.repair_user`。"""
    return ([m for r, m in checks if r not in VERIFY_RULES], [m for r, m in checks if r in VERIFY_RULES])


def tagged_checks(
    plan: dict, query: str, entities: Mapping[str, Sequence[str]], today: date | None = None,
    previous_issue: str | None = None,
) -> list[tuple[int, str]]:
    """第 7 条的校验一半、第 13、14、15、19 条：[(规则编号, 打回时交给模型的说明)]。`plan` 用规整后的。

    `entities` 是预匹配用的「名字 → 它在库里属于哪几类」（可查的域的主数据）。`previous_issue` 是上一轮单独
    说到的那张单（`previous_issue()`），第 19 条用。第 7、13 条的说明只写词的位置与计划写成了什么（`VERIFY_RULES`）。
    """
    errors: list[tuple[int, str]] = []
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    for sid, said, basis, hit in basis_mismatches(plan, query):
        word = (_event_hit(query, said) or (hit, hit))[0]
        errors.append((13, f"问句里「{said}」后面紧跟着「{word}」，{sid} 这项时间的日期依据写的是{basis}。"
                           f"若问的是这段时间里{word}的单，日期依据写{hit}；若问的是现在处于某种状态的单"
                           "（如「6 月还没结案的单」），仍按建单"))
    scope = _out_of_scope_on_previous_issue(steps, query, previous_issue)
    if scope is not None:
        errors.append((19, scope))
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
    plan: dict, query: str, entities: Mapping[str, Sequence[str]], today: date | None = None,
    previous_issue: str | None = None,
) -> list[str]:
    """`tagged_checks` 只留错误说明；空表示通过。"""
    return [msg for _, msg in tagged_checks(plan, query, entities, today, previous_issue)]


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


# ---------------------------------------------------------------------------- 第 20 条 助手按意思定的条件与张数
#
# 决策 2026-11-04「按什么理解写在开头」：总述「必要澄清项」之后「拿不准的问法」要求开头一句写明「按 X 理解」，
# 总述「程度说法怎么理解」给「严重」「不良率高」的默认读法与「没说要几张」的默认张数。

#: 没给 `default_limit` 时的默认张数（与模块配置 `top_n` 的内置默认相同）
DEFAULT_LIMIT = int(ANSWER_DEFAULTS["top_n"])
#: 取值由规划器写成库里的叫法（不照抄原话）的几类条件：在问句里找不到依据就是助手按意思定的。名字类不查：
#: 第 16 条在 p2 实测的 345 个值都在问句里找得到
READING_FIELDS = ("问题等级", "状态", "问题类型")
#: 程度说法前面的副词；「最」不算（「不良率最高的单」是排名，不是程度说法）
_DEGREE = "比较|特别|非常|十分|相当|较为|较|很|挺|极其|极|偏"
#: 总述「程度说法怎么理解」：「严重」= 问题等级 A+、A；「不良率高」= 按不良率从高到低列前几张
SEVERE = re.compile(rf"(?:{_DEGREE})?严重")
SEVERE_LEVELS = ("A+", "A")
HIGH_RATE = re.compile(rf"不良率(?:{_DEGREE})?高(?![于过出])|(?:{_DEGREE})?高不良率")
#: 问句里的等级说法（「A 级」「A+」「a类」「B 级及以上」）；字母前后不能紧挨字母数字（A930、A920PRO 不算）
_LEVEL_TOKEN = re.compile(r"(?<![A-Z0-9])[ABC]\+?(?:等级|级|类)?(?:及以上|以上|及更高|或以上)?(?![A-Z0-9+])")
#: 不带「级」「类」也不带「+」的单个字母，只在问句里说到了等级时才算
_LEVEL_WORDS_IN_QUERY = ("等级", "级别", "级", "类")
#: 几种不写字母的等级说法：「安全问题」按 A+（第 11 条）；「未填」见总述「问题等级」
_LEVEL_SAYINGS = {"安全": ("A+",), "未填": ("未填",), "没填": ("未填",), "没有等级": ("未填",)}
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
DATE_SORTS = ("建单时间", "现场发现日期", "停线日期", "结案时间")
#: 按这几项排序的清单只列前几张（总述「程度说法怎么理解」末段「没说要几张」，G95）。看的是规划器写出的排序，
#: 不看问句里的说法：「最高的」「突出的」「不良多的」怎么读成按不良率排，交给规划器（决策 2026-11-04 补记）。
#: 按日期排的不算：按建单时间从新到旧列全部本来就是清单的默认做法
TOP_SORTS = ("不良率", "不良数量", "影响数量")
#: 问句里说张数的写法：数后面跟量词，或前面是「前」（「前十张」「5 条」「三个」）；年份、机型号里的数不算
_COUNT = re.compile(r"前\s*(\d+|[一二两三四五六七八九十百]+)|(\d+|[一二两三四五六七八九十百]+)\s*(?:张|条|个|单|份)")


def sort_text(sort: Any) -> str:
    """排法的说法：「按不良率从高到低」「按建单时间从新到旧」；没写排序为建单时间从新到旧（清单的默认排法）。"""
    s = sort if isinstance(sort, dict) else {}
    by, asc = str(s.get("by") or "建单时间"), s.get("order") == "升序"
    if by in DATE_SORTS:
        return f"按{by}从{'旧到新' if asc else '新到旧'}"
    return f"按{by}从{'低到高' if asc else '高到低'}"


def _cn_int(s: str) -> int | None:
    if "百" in s:
        left, _, right = s.partition("百")
        hundreds = _CN_DIGITS.get(left, 1) if left else 1
        rest = _cn_int(right.lstrip("零")) if right.lstrip("零") else 0
        return None if rest is None else hundreds * 100 + rest
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(s) if len(s) == 1 else None


def numbers_in(text: str) -> set[int]:
    """问句里说到的整数：阿拉伯数字与汉字数（「前十张」「五张」）。"""
    plain = unicodedata.normalize("NFKC", text or "")
    out = {int(x) for x in re.findall(r"\d+", plain)}
    for token in re.findall(r"[零一二两三四五六七八九十百]+", plain):
        value = _cn_int(token)
        if value is not None:
            out.add(value)
    return out


def counts_in(text: str) -> list[int]:
    """问句里说的张数（「前十张」「5 条」），按出现的先后；年份、机型号里的数不算。"""
    plain = unicodedata.normalize("NFKC", text or "")
    out: list[int] = []
    for m in _COUNT.finditer(plain):
        token = m.group(1) or m.group(2)
        value = int(token) if token.isdigit() else _cn_int(token)
        if value:
            out.append(value)
    return out


def levels_in(query: str) -> set[str]:
    """问句里说到的问题等级（与对库同一个换算 `enums.level_codes`）。"""
    raw = re.sub(r"\s+", "", unicodedata.normalize("NFKC", query or "")).upper()
    bare_ok = any(w in raw for w in _LEVEL_WORDS_IN_QUERY)
    out: set[str] = set()
    for m in _LEVEL_TOKEN.finditer(raw):
        token = m.group(0)
        if not bare_ok and len(token) == 1:
            continue
        out |= set(enums.level_codes(token) or [])
    for word, levels in _LEVEL_SAYINGS.items():
        if word in raw:
            out |= set(levels)
    return out


def _type_core(value: str) -> str:
    return re.sub(r"(类问题|问题|类型|类)$", "", value)


def has_basis(field_name: str, value: object, query: str, levels: set[str] | None = None) -> bool:
    """这一个取值在问句里有没有依据：取值本身，或对库时认的说法（状态 `enums.status_sayings`、等级
    `levels_in`、问题类型去掉末尾「问题」「类」后的说法与 `enums.type_sayings`）。"""
    q = norm(query)
    text = str(value)
    if field_name == "问题等级":
        found = levels if levels is not None else levels_in(query)
        return re.sub(r"\s+", "", text).upper() in found
    if field_name == "状态":
        return any(norm(w) and norm(w) in q for w in enums.status_sayings(text))
    core = norm(_type_core(text))
    return (norm(text) in q or (len(core) >= 2 and core in q)
            or any(norm(w) in q for w in enums.type_sayings(text)))


def _add_inferred(inferred: list[Inferred], item: Inferred) -> None:
    if item not in inferred:
        inferred.append(item)


def reading_rule(plan: dict, query: str | None, default_limit: int, inferred: list[Inferred],
                 hits: list[RuleHit] | None = None) -> None:
    """第 20 条（就地改）：

    - 问题等级、状态、问题类型的取值，本轮说的（不是沿用上一轮的），有一个在问句里找不到依据，就把这一条条件记成
      助手按意思定的（`KIND_VALUE`）；「严重」读成 A+、A 时带上原话。
    - 清单张数（G92、G95）。要不要只列前几张看计划结构：规划器写了张数，或按 `TOP_SORTS` 里的一项排序（升降都算）、
      又没要全部（`export`）。几张：问句里说了张数（`counts_in`），用它；规划器写的张数在问句里出现过，或是 1（「哪张」
      「那一单」这类单数说法，模型写成 1；它自己定的数是 10、20 这类），照它；其余改成 `default_limit`，记成
      `KIND_COUNT`，开头写明。判据都在计划与问句里、可证明，按设计 §5.3 准入准则改写。不看问句里的程度说法：
      「最高的」「突出的」怎么读成按不良率排，交给规划器；词表只用来在开头带上原话（「不良率高」一类）。
    - 认出了程度说法、计划却没按落盘的读法写（「严重」没写成 A+、A，「不良率高」没按不良率从高到低排）：
      只记日志，不改不打回。
    """
    if not query:
        return
    raw = unicodedata.normalize("NFKC", query)
    levels = levels_in(query)
    numbers = numbers_in(query)
    counts = counts_in(query)
    severe_ok = high_rate_ok = False
    for step in plan.get("steps") or []:
        if not isinstance(step, dict) or step.get("skill") not in schema.COND_SKILLS:
            continue
        p = step.get("params")
        if not isinstance(p, dict):
            continue
        sid = str(step.get("id"))
        for f in _as_list(p.get("filters")):
            if not isinstance(f, dict) or f.get("from", "user") == "previous" or schema.is_ref(f.get("value")):
                continue
            name = next((x for x in READING_FIELDS if norm_field(x) == norm_field(f.get("field"))), None)
            values = [str(v).strip() for v in _as_list(f.get("value")) if str(v).strip()]
            if name is None or not values:
                continue
            op = str(f.get("op") or "是")
            negated = schema.OP_KINDS.get(op) in ("ne", "nhas")
            is_severe = (name == "问题等级" and not negated
                         and {re.sub(r"\s+", "", v).upper() for v in values} == set(SEVERE_LEVELS))
            severe_ok = severe_ok or is_severe
            if all(has_basis(name, v, query, levels) for v in values):
                continue
            m = SEVERE.search(raw) if is_severe else None
            _add_inferred(inferred, Inferred(sid, name + (op if negated else ""), tuple(values), kind=KIND_VALUE,
                                             said=m.group(0) if m else ""))
        if step.get("skill") != "list_issues":
            continue
        sort = p.get("sort") if isinstance(p.get("sort"), dict) else {}
        by_rate = sort.get("by") == "不良率" and sort.get("order", "降序") != "升序"
        high_rate_ok = high_rate_ok or by_rate
        lim = p.get("limit")
        given = isinstance(lim, int) and not isinstance(lim, bool) and lim > 0
        # 要不要只列前几张：看计划结构，不看问句里的说法（复测 2026-11-05：「不良率高的单有哪些」规划器只写了排序）
        top = given or (sort.get("by") in TOP_SORTS and p.get("export") is not True)
        if not top:
            continue
        if counts:  # 用户说了几张（规划器漏写也照用户的）
            if lim != counts[0]:
                p["limit"] = counts[0]
            continue
        if given and (lim in numbers or lim == 1):
            continue
        p["limit"] = default_limit
        m = HIGH_RATE.search(raw) if by_rate else None
        _add_inferred(inferred, Inferred(sid, sort_text(sort), (str(default_limit),), kind=KIND_COUNT,
                                         said=m.group(0) if m else ""))
    if hits is None:
        return
    skills = _skills(plan)
    if SEVERE.search(raw) and not levels and not severe_ok:
        hits.append(RuleHit(20, skills, ("程度说法：严重",), (), action="只记日志"))
    if HIGH_RATE.search(raw) and not high_rate_ok:
        hits.append(RuleHit(20, skills, ("程度说法：不良率高",), (), action="只记日志"))