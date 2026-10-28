"""模拟线上代码在执行计划前做的确定性处理。打分前先过这一道，量的是「模型 + 代码」一起的结果。

规划实测 p0 里有几类错法模型每次都犯、而代码能确定地纠正，p1 起改由代码做（设计稿里写进代码职责）：

1. **话题范围**：话题本身 / 比话题小 / 组合说法 / 清单外，对照话题清单（`docs/2_landed/topic_terms.md`）判断，
   不用模型填的值。规则见 `topic_scope()`。
2. **名字归哪一类**：模型把名字放进某个条件（如跟进人），库里这一类对不上、另一类恰好对得上时，改到对得上的那一类。
   线上查的是库里的取值；这里用 `CATALOG` 示意几类取值，只放对照集问句里出现的名字。
3. **同一统计拆成几步**：几步统计的范围（域、时间、条件、对比对象）与分组都相同时，合成一步。
4. **追问与取数混在一份计划里**：只留追问（p1 实测里模型会写「追问缺的时间」再加一步统计）。
5. **同一个意思统一成一种写法**（p2 起；p1 实测 Qwen3-Fast 不一致的问句里约三成只是写法不同）：
   对象对比 → 按该维筛这几个值再按该维分组；时段对比的旧写法 → time 两项加 `compare: "时段"`；
   分组取值是点名的几个时去掉 ranking；只有一个词时去掉 logic；文字查找没写 ask 即问现象；
   issue 统一成 `{value, from}`；有停线、结案、重启日期条件时去掉同义的状态条件。
6–10（p2 实测后加，要看本轮问句原话）：时间原话里没有时间词的（「停过线」）改回状态条件；时间原话后面紧跟的事件词
   （「今年结案了」）定日期依据；「X 各款」按机型包含 X；文字查找没在问句里点名的栏目去掉；问「安全问题」拆成
   问题等级 A+ 与话题「安全」两路。都是 2_landed 已写明的规则，模型偶尔不照做。

不是模块代码，`src/` 不引用它。
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from common import norm, norm_field
from prompts import load_topics

# ---------------------------------------------------------------------------
# 1. 话题范围
# ---------------------------------------------------------------------------

_TOPICS = load_topics()
_TOPIC_NAMES = {norm(t["name"]): t["name"] for t in _TOPICS}
_TERM_TOPICS: dict[str, set[str]] = {}
for _t in _TOPICS:
    for _term in _t["terms"]:
        _TERM_TOPICS.setdefault(norm(_term), set()).add(_t["name"])

_PAREN = re.compile(r"[（(].*?[)）]")
_TAIL = re.compile(r"(相关的?|有关的?|方面的?|类的?|的)?(问题|单|不良|异常)?$")


def topic_scope(topic: str | None) -> str | None:
    """用户说的话题 → 话题本身 / 比话题小 / 组合说法 / 清单外。

    - 带括号例子（「音频（喇叭、蜂鸣器）」），或去掉「相关的问题」一类尾巴后与话题名相同：话题本身。
    - 与清单里某个说法相同（「磁卡」「eSIM」「喇叭」「漏电」）：比话题小。
    - 含几个说法、同属一个话题（「电池鼓包」）：比话题小；分属不同话题、没有共同话题（「电池卡扣」）：组合说法。
    - 一个说法都不含：清单外（由助手临时提说法）。
    """
    if not topic:
        return None
    raw = str(topic)
    if _PAREN.search(raw):
        return "话题本身"
    core = norm(_TAIL.sub("", _PAREN.sub("", raw).strip()))
    if not core:
        return None
    if core in _TOPIC_NAMES:
        return "话题本身"
    if core in _TERM_TOPICS:
        return "比话题小"
    hits = [topics for term, topics in _TERM_TOPICS.items() if len(term) >= 2 and term in core]
    if not hits:
        return "清单外"
    common = set.intersection(*hits)
    return "比话题小" if common else "组合说法"


# ---------------------------------------------------------------------------
# 2. 名字归哪一类
# ---------------------------------------------------------------------------

# 同一组里的几类存的是同一批名字（同一批人、同一批部门），组内换不换由语义定，代码不动
_NAME_GROUPS = {
    "工厂": ("加工厂", "国内工厂"),
    "人": ("跟进人", "当前责任人", "责任人"),
    "部门": ("跟进部门", "责任归属部门"),
    "供应商": ("供应商",),
    "系列": ("系列",),
}
_FIELD_GROUP = {norm_field(f): g for g, fields in _NAME_GROUPS.items() for f in fields}

# 示意的「库里的取值」：只放对照集问句里出现的名字（来自测试案例集与 2_landed，非真实明细）
CATALOG = {
    "工厂": ["柯洱斯", "亮亮", "惠州百富", "TT", "CA"],
    "人": ["李飞", "马万军", "张三"],
    "部门": ["工程部", "生产工程部", "研发一部", "研发二部"],
    "供应商": ["普瑞特", "高展光电", "亮亮"],  # 亮亮与国内工厂同名（c4 加，见 mockdata.py）
    "系列": ["底座", "A"],
}


def _found(value: str, group: str) -> bool:
    v = norm(value)
    if len(v) < 2 and group != "系列":
        return False
    return any(v == norm(c) or (len(norm(c)) >= 2 and (norm(c) in v or v in norm(c))) for c in CATALOG[group])


def _regroup(step: dict) -> None:
    p = step.get("params") or {}
    for f in p.get("filters") or []:
        if not isinstance(f, dict):
            continue
        field = norm_field(f.get("field"))
        group = _FIELD_GROUP.get(field)
        values = f.get("value")
        if group is None or isinstance(values, dict) or values in (None, ""):
            continue
        values = values if isinstance(values, list) else [values]
        if not all(isinstance(v, str) for v in values) or all(_found(v, group) for v in values):
            continue
        others = [g for g in CATALOG if g != group and all(_found(v, g) for v in values)]
        if len(others) != 1:
            continue
        new_field = _NAME_GROUPS[others[0]][0]
        old_field = f.get("field")
        f["field"] = new_field
        gb = p.get("group_by")
        if isinstance(gb, list):
            p["group_by"] = [new_field if norm_field(g) == norm_field(old_field) else g for g in gb]


# ---------------------------------------------------------------------------
# 3. 同一统计拆成几步 → 合成一步
# ---------------------------------------------------------------------------

_REF = re.compile(r"^s(\d+)\.(\w+)$")
_OP = {"是": "eq", "等于": "eq", "为": "eq", "属于": "eq", "包含": "has", "不是": "ne", "不属于": "ne", "不包含": "ne"}


def _as_list(v: Any) -> list:
    return [] if v is None else (v if isinstance(v, list) else [v])


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


# ---------------------------------------------------------------------------
# 5. 同一个意思统一成一种写法
# ---------------------------------------------------------------------------

# 有这件事的日期条件时，同义的状态条件多余（结案时间只对已结案的单有，停线、重启日期同理）
_IMPLIED_STATUS = {"停线": {"曾经停线", "停过线"}, "结案": {"已结案", "结案"}, "重启": {"已重启", "重启"}}

# p2 实测后加（2026-10-27）：以下几条都是把 2_landed 已写明的说法交给代码判，模型偶尔不照做

# 6. 时间原话里没有时间词、日期依据却是停线 / 结案 / 重启：模型把「停过线的」写成了时间，改回状态条件
_TIME_WORD = re.compile(r"[0-9０-９一二三四五六七八九十两]|年|月|周|星期|天|日|号|季|今|去|昨|前|本|上|下|近|以来|至今|现在|q",
                        re.IGNORECASE)
_STATUS_OF_BASIS = {"停线": "曾经停线", "结案": "已结案", "重启": "已重启"}

# 7. 时间原话后面紧跟的事件词定日期依据（总述「按哪个日期筛」：按问的那件事取日期）。
#    2026-10-27 起不改写，改为校验（query_checks）：判据靠词的位置，可能误判，打回让模型重写
_SKIP_AFTER_TIME = re.compile(r"^(?:内|里|以来|已经|有|共|一共|总共|都|被|发生(?:了|过)?|出现(?:了|过)?)*")
_EVENT_BASIS = (("现场发现", "现场发现"), ("停过线", "停线"), ("停线", "停线"), ("停产", "停线"), ("重启", "重启"),
                ("结案", "结案"), ("关闭", "结案"), ("关掉", "结案"), ("建单", "建单"), ("新建", "建单"), ("创建", "建单"))


def _event_basis(query: str, said: str) -> str | None:
    """问句里这项时间原话后面紧跟的事件词对应的日期依据；没有紧跟事件词时返回 None。"""
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


# 8. 「X 各款」「X 各型号」：机型包含 X、按机型分组，不按系列查（总述「机型与系列怎么对」）
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


# 9. 文字查找的栏目要是用户点名的：问句里没出现栏目名时去掉（总述「关键词搜索与类似问题」：没说栏目时在比对范围里找）
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


# 11. 检索用的文字里去掉同一步的条件值（「A960 煲机时屏幕显示异常」→「煲机时屏幕显示异常」）；条件仍在 filters 里。
#     物料名称不去（「喇叭」既是物料也是现象）；去掉后不足 2 个字时不动
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


# 10. 问「安全问题」：问题等级 A+ 与话题「安全」两路分开查（总述「三域共用的说法」安全问题一行）；明说 A+ 时只按等级
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


def _canonical(step: dict, query: str | None = None) -> None:
    p = step.get("params")
    if not isinstance(p, dict):
        return
    _time_rules(p, query)
    _each_model_rule(p, query)
    _named_fields_rule(step, query)
    c = p.get("compare")
    if isinstance(c, dict):
        items = [x for x in _as_list(c.get("items")) if isinstance(x, str)]
        if norm(c.get("kind")) == "对象" and c.get("field"):
            field = c["field"]
            filters = [f for f in _as_list(p.get("filters")) if isinstance(f, dict)]
            if not any(norm_field(f.get("field")) == norm_field(field) for f in filters):
                filters.append({"field": field, "op": "属于", "value": items, "from": "user"})
            p["filters"] = filters
            group = _as_list(p.get("group_by"))
            if not any(norm_field(g) == norm_field(field) for g in group):
                group.append(field)
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
    renumber = {}
    for i, s in enumerate(kept):
        renumber[str(s.get("id"))] = f"s{i + 1}"
    final = {old: renumber[new] for old, new in mapping.items()}
    new_steps = []
    for s in kept:
        s = _rewrite_refs(s, final)
        s["id"] = final[str(s.get("id"))]
        new_steps.append(s)
    plan["steps"] = new_steps


# ---------------------------------------------------------------------------
# 号码直通：问句只有号码（加上号的种类、「查一下」「是哪张单」这类套话）时不调规划，代码直接查单
# ---------------------------------------------------------------------------

# 号的种类词：用户说了是什么号时按说的查（总述「按编号查单」）
_KIND_WORDS = re.compile(r"(?i)小板订单号?|生产订单号?|订单号?|CAR\s*编号|CAR报告编号|发货单号?|PO号?|投诉单号?|料号|PN编码|PN|"
                         r"问题编号|制程单号|单号|编号|号码")
# 只有在去掉号码与种类词之后才认的套话；认不全就交规划器，不硬判
_FILLER = re.compile(r"帮我|帮忙|麻烦|请|查一下|查查|查询|查|看一下|看看|一下|这张单|这几张单|这些单|这个|这几个|这些|"
                     r"(?:是|对应|关联了?|挂着?)(?:的)?(?:哪张|哪些|哪个|什么|哪几张)(?:制程)?(?:问题)?单?|"
                     r"(?:关联|对应)(?:了)?(?:哪些|哪张)?(?:制程)?问题|的问题|有哪些|是什么|的|和|与|及|以及|还有|"
                     r"[\s，,、；;。？?！!：:]")


def number_shortcut(query: str) -> dict | None:
    """返回直通的计划；问句里除了号码还有别的意思时返回 None，照常规划。"""
    from prematch import find_numbers

    nums = find_numbers(query)
    if not nums:
        return None
    q = unicodedata_half(query)
    rest = "".join(ch for i, ch in enumerate(q) if not any(a <= i < b for *_, (a, b) in nums))
    kinds = _KIND_WORDS.findall(rest)
    rest = _FILLER.sub("", _KIND_WORDS.sub("", rest))
    if rest:
        return None
    if len(nums) == 1 and nums[0][1] == "问题编号":
        return {"understanding": "（号码直通）看这张单的详情", "alternatives": [],
                "steps": [{"id": "s1", "skill": "issue_detail", "when": None,
                           "params": {"issue": {"value": nums[0][0], "from": "user"}}}]}
    kind_said = kinds[0] if len(kinds) == 1 and len(nums) == 1 else None
    return {"understanding": "（号码直通）按号码找单", "alternatives": [],
            "steps": [{"id": "s1", "skill": "lookup_numbers", "when": None,
                       "params": {"numbers": [{"raw": raw, "kind_said": kind_said} for raw, *_ in nums]}}]}


# ---------------------------------------------------------------------------
# 校验：判据靠位置或要查库，可能误判，不改写，打回让模型重写（设计稿 §5.3 第 13、15 条）
# ---------------------------------------------------------------------------


def query_checks(plan: dict, query: str) -> list[str]:
    """返回打回时交给模型的错误说明；空表示通过。plan 用规整后的。"""
    from prematch import find_entities, find_numbers

    errors: list[str] = []
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    for s in steps:
        for t in _as_list((s.get("params") or {}).get("time")):
            if not isinstance(t, dict) or not t.get("said"):
                continue
            hit = _event_basis(query, str(t["said"]))
            if hit and norm(t.get("basis") or "建单") != norm(hit):
                errors.append(f"问句里「{t['said']}」后面是「{hit}」这件事，{s.get('id')} 这项时间的日期依据应为{hit}")
    if any(s.get("skill") in ("introduce", "clarify") for s in steps):
        return errors
    blob = norm(json.dumps(plan.get("steps"), ensure_ascii=False))
    nums = find_numbers(query)
    for raw, kind, _ in nums:
        if kind == "问题编号" and norm(raw) not in blob:
            errors.append(f"问句里有问题编号「{raw}」，计划里没有用到它")
    for text, kinds, _ in find_entities(query, [s for *_, s in nums]):
        if "机型" in kinds and norm(text) not in blob:
            errors.append(f"问句里的「{text}」是机型，计划里没有这个条件")
    return errors


def unicodedata_half(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------------------


def apply(plan: dict | None, query: str | None = None) -> dict | None:
    """返回处理后的计划副本（不改原计划）。`query` 是本轮用户原话；不给时只做不看问句的那几条。"""
    if plan is None:
        return None
    out = copy.deepcopy(plan)
    clarify = next((s for s in out.get("steps") or [] if isinstance(s, dict) and s.get("skill") == "clarify"), None)
    if clarify is not None and len(out.get("steps") or []) > 1:
        out["steps"] = [{**clarify, "id": "s1", "when": None}]
        return out
    for step in out.get("steps") or []:
        if not isinstance(step, dict):
            continue
        p = step.get("params")
        if not isinstance(p, dict):
            continue
        _canonical(step, query)
        _strip_condition_values(step)
        if step.get("skill") == "text_search" and p.get("topic"):
            p["topic_scope"] = topic_scope(p["topic"])
        _regroup(step)
    _safety_rule(out, query)
    merge_duplicate_aggregates(out)
    return out
