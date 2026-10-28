"""规划结果的校验、归一与打分。

- `parse_reply`：从模型回复里取出 JSON（先剥 <think>）。
- `validate_plan`：按规划提示里定的格式校验（技能、条件名、比较方式、日期依据、引用），返回错误列表。
- `score_plan`：拿模型的计划对照集里的期望，按参数类别给出对错。期望只写关键字段，
  比较按归一后的值，不比措辞。期望的写法见同目录 README.md「对照集怎么写」。
- `plan_signature`：同一问句多次运行是否一致，用它比。
- `render_expected`：把期望写成一份合格的计划，`--self-check` 用它冒充模型，检验打分本身。
"""

from __future__ import annotations

import itertools
import json
import re
from typing import Any

from common import DOMAINS, norm, norm_field, norm_value
from prompts import (
    BASES, FILTER_FIELDS, GROUP_DIMS, METRICS, OPS, REF_OUTPUTS, SKILLS, SORT_FIELDS, SORT_ORDERS, TEXT_MODES,
)

COND_SKILLS = {"list_issues", "aggregate", "text_search", "custom_stats"}
CATEGORIES = (
    "技能", "域", "时间原话", "日期依据", "条件", "分组与指标", "排序与条数", "号码与单号", "详情内容",
    "文字查找", "列与导出", "依赖", "沿用与替换", "其他",
)

_THINK = re.compile(r"<think>.*?</think>", re.S)


def parse_reply(text: str) -> dict:
    body = _THINK.sub("", text or "").strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回复里没有 JSON 对象")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("回复的 JSON 不是对象")
    return data


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

_REF = re.compile(r"^s(\d+)\.([a-z_0-9]+)$")


def _is_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"ref"} and isinstance(value["ref"], str)


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


# 提示词「条件参数」「其他参数」里写到的参数名。不在这里的键打回重写（设计稿 §5.3 第 12 条）：
# 照忽略处理的话，错层的参数（p2-校验 CN-002 把整套参数又包了一层 params）或模型自造的条件键会被静默丢掉，
# 查出来的是没加条件的结果。
PARAM_KEYS = frozenset({
    "domains", "time", "filters", "columns", "add_columns", "export", "sort", "limit", "group_by", "metrics",
    "ranking", "top", "compare", "numbers", "issue", "aspects", "mode", "terms", "logic", "fields", "topic",
    "phenomenon", "ask", "approach", "describe", "chart", "kind", "reason", "question", "options", "within",
})
# 实测里出现过、无害的两个：参数层的 from（from 只挂在各参数上，这一层没有意义）；topic_scope（由代码判，
# 多轮时模型从上文抄来）。直接丢掉，不打回。
PARAM_KEYS_DROPPED = frozenset({"from", "topic_scope"})


def validate_plan(plan: dict) -> list[str]:
    errors: list[str] = []
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["缺少 steps，或 steps 为空"]
    if len(steps) > 6:
        errors.append(f"步骤太多（{len(steps)} 步，上限 6 步）")
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
        unknown = sorted(k for k in params if k not in PARAM_KEYS and k not in PARAM_KEYS_DROPPED)
        if unknown:
            errors.append(f"{sid}：params 里有格式之外的键 {'、'.join(unknown)}（参数直接写在 params 下，名字照格式说明）")
        if step.get("when") is not None:
            if _is_ref(step["when"]):
                _check_ref(step["when"], ids, skills, i, errors)
            else:
                errors.append(f"{sid}：when 只能是 {{\"ref\": ...}} 或 null")
        for t in _as_list(params.get("time")):
            if not isinstance(t, dict) or not t.get("said"):
                errors.append(f"{sid}：time 每项要有 said")
            elif t.get("basis", "建单") not in BASES:
                errors.append(f"{sid}：日期依据 {t.get('basis')!r} 不在 {'、'.join(BASES)} 里")
        for f in _as_list(params.get("filters")):
            if not isinstance(f, dict):
                errors.append(f"{sid}：filters 每项要是对象")
                continue
            if f.get("field") not in FILTER_FIELDS:
                errors.append(f"{sid}：条件名 {f.get('field')!r} 不在条件清单里")
            # 清单外的常见同义写法（等于、大于等于…）代码照收，不为它打回重写
            if f.get("op", "是") not in OPS and f.get("op") not in _OP:
                errors.append(f"{sid}：比较方式 {f.get('op')!r} 不在 {'、'.join(OPS)} 里")
            if _is_ref(f.get("value")):
                _check_ref(f["value"], ids, skills, i, errors)
        for g in _as_list(params.get("group_by")):
            if g not in GROUP_DIMS:
                errors.append(f"{sid}：分组维度 {g!r} 不在维度清单里")
        for m in _as_list(params.get("metrics")):
            if m not in METRICS:
                errors.append(f"{sid}：指标 {m!r} 不在指标清单里")
        c = params.get("compare")
        # p2 起只认 "时段"；p0、p1 的对象写法（dict）照收，由代码统一成筛选加分组
        if c is not None and not isinstance(c, dict):
            if c != "时段":
                errors.append(f"{sid}：compare 只能写 \"时段\"（对象对比改用筛选加分组）")
            elif len([t for t in _as_list(params.get("time")) if isinstance(t, dict)]) < 2:
                errors.append(f"{sid}：比较两个时段时 time 要按先后写两项")
        s = params.get("sort")
        if s is not None:
            if not isinstance(s, dict) or s.get("by") not in SORT_FIELDS or s.get("order", "降序") not in SORT_ORDERS:
                errors.append(f"{sid}：sort 写 {{\"by\": 排序项, \"order\": 升序或降序}}，排序项取 {'、'.join(SORT_FIELDS)}")
        lim = params.get("limit")
        if lim is not None and (not isinstance(lim, int) or isinstance(lim, bool) or lim <= 0):
            errors.append(f"{sid}：limit 要写正整数")
        if skill == "text_search":
            if params.get("mode") not in TEXT_MODES:
                errors.append(f"{sid}：文字查找方式 {params.get('mode')!r} 不在 {'、'.join(TEXT_MODES)} 里")
        for key in ("within", "issue"):
            value = _unwrap_ref(params.get(key))
            if _is_ref(value):
                _check_ref(value, ids, skills, i, errors)
    return errors


def _unwrap_ref(value: Any) -> Any:
    """{"value": {"ref": "s2.issues"}, "from": "user"} 与 {"ref": "s2.issues"} 同义：模型常把引用包在 value 里。"""
    if isinstance(value, dict) and _is_ref(value.get("value")):
        return value["value"]
    return value


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------------------------------------------------------------------------
# 归一
# ---------------------------------------------------------------------------

_OP = {
    "是": "eq", "等于": "eq", "为": "eq", "属于": "eq", "包含": "has",
    "不是": "ne", "不等于": "ne", "不属于": "ne", "不包含": "nhas",
    "大于": "gt", "小于": "lt", "不小于": "ge", "大于等于": "ge", "不大于": "le", "小于等于": "le",
    "介于": "between", "区间": "between",
}
_POSITIVE = {"eq", "has"}
_NEGATIVE = {"ne", "nhas"}
_ASPECT = {
    "进度": "当前状态", "状态": "当前状态", "现状": "当前状态", "原因分析": "原因", "改善措施": "措施",
    "处理措施": "措施", "解决办法": "措施", "处理过程": "完整处理过程", "操作记录": "完整处理过程",
    "发货": "发货单", "涉及发货单": "发货单", "可能问题原因": "可能原因", "现象": "问题现象",
    "已选问题现象": "问题现象", "停线": "停线与重启", "重启": "停线与重启", "car报告": "car",
    "生产订单": "订单", "关联订单": "订单", "问题跟进人": "跟进人", "处理人": "当前责任人",
}
_GROUP = {"类型": "问题类型", "问题分类": "问题类型", "工厂": "加工厂", "月份": "月", "等级": "问题等级", "部门": "跟进部门"}
_METRIC = {"不良率": "合计不良率", "平均结案天数": "结案周期", "结案天数": "结案周期", "张数": "单数", "数量": "单数"}


def _ref_of(value: Any, id_index: dict[str, int]) -> tuple[int, str] | None:
    if not _is_ref(value):
        return None
    m = _REF.match(value["ref"].strip())
    if not m:
        return None
    return id_index.get(f"s{m.group(1)}", -1), m.group(2)


def _values(value: Any) -> frozenset[str]:
    if isinstance(value, list):
        return frozenset(norm_value(v) for v in value)
    return frozenset([norm_value(value)])


def _param_from(item: Any) -> str:
    return (item.get("from") if isinstance(item, dict) else None) or "user"


def canon_step(step: dict, id_index: dict[str, int]) -> dict:
    p = step.get("params") or {}
    out: dict[str, Any] = {"skill": step.get("skill")}
    d = p.get("domains")
    dv = d.get("value") if isinstance(d, dict) else d
    dset = frozenset(norm(x) for x in _as_list(dv))
    out["domains"] = None if not dset or dset == frozenset(norm(x) for x in DOMAINS) else dset
    out["domains_from"] = _param_from(d) if d else None
    out["time"] = [
        {"said": norm(t.get("said")), "basis": norm(t.get("basis") or "建单"), "from": _param_from(t)}
        for t in _as_list(p.get("time")) if isinstance(t, dict)
    ]
    filters = []
    for f in _as_list(p.get("filters")):
        if not isinstance(f, dict):
            continue
        ref = _ref_of(f.get("value"), id_index)
        filters.append({
            "field": norm_field(f.get("field")),
            "column": norm(f.get("column")),
            "op": _OP.get(str(f.get("op") or "是"), norm(f.get("op"))),
            "values": frozenset() if ref else _values(f.get("value")),
            "ref": ref,
            "from": _param_from(f),
        })
    out["filters"] = filters
    out["group_by"] = frozenset(_GROUP.get(norm(g), norm(g)) for g in _as_list(p.get("group_by")))
    out["metrics"] = frozenset(_METRIC.get(norm(m), norm(m)) for m in _as_list(p.get("metrics")))
    out["ranking"] = bool(p.get("ranking")) or p.get("top") is not None
    out["top"] = p.get("top")
    c = p.get("compare")
    if isinstance(c, dict):
        kind = norm(c.get("kind"))
        out["compare"] = ({"kind": kind} if kind == "时段" else
                          {"kind": kind, "field": norm_field(c.get("field")), "items": [norm(x) for x in _as_list(c.get("items"))]})
    else:
        out["compare"] = {"kind": norm(c)} if c else None
    s = p.get("sort")
    out["sort"] = (norm(s.get("by")), norm(s.get("order") or "降序")) if isinstance(s, dict) else None
    out["limit"] = p.get("limit")
    out["numbers"] = [norm(n.get("raw") if isinstance(n, dict) else n) for n in _as_list(p.get("numbers"))]
    issue = _unwrap_ref(p.get("issue"))
    issue_ref = _ref_of(issue, id_index)
    if issue_ref:
        out["issue"] = ("ref", *issue_ref)
    else:
        raw = issue.get("value") if isinstance(issue, dict) else issue
        out["issue"] = norm(raw) if raw else None
    out["issue_from"] = _param_from(issue) if isinstance(issue, dict) and not issue_ref else None
    aspects: set[str] = set()
    for a in _as_list(p.get("aspects")):
        key = norm(a)
        if key in ("原因与措施", "原因和措施"):
            aspects |= {"原因", "措施"}
            continue
        if key.startswith("其他:"):
            aspects.add(key)
            key = key[3:]
        aspects.add(_ASPECT.get(key, key))
    out["aspects"] = frozenset(aspects)
    out["mode"] = norm(p.get("mode"))
    out["terms"] = frozenset(norm(t) for t in _as_list(p.get("terms")))
    out["logic"] = norm(p.get("logic"))
    out["topic"] = norm(p.get("topic"))
    out["topic_scope"] = norm(p.get("topic_scope"))
    out["phenomenon"] = norm(p.get("phenomenon"))
    out["approach"] = norm(p.get("approach"))
    out["fields"] = frozenset(norm(x) for x in _as_list(p.get("fields")))
    out["ask"] = norm(p.get("ask"))
    out["columns"] = frozenset(norm(x) for x in _as_list(p.get("columns")) + _as_list(p.get("add_columns")))
    out["export"] = bool(p.get("export"))
    out["chart"] = norm(p.get("chart"))
    out["kind"] = norm(p.get("kind"))
    out["reason"] = norm(p.get("reason"))
    out["within"] = _ref_of(p.get("within"), id_index)
    out["when"] = _ref_of(step.get("when"), id_index)
    refs = set()
    for f in filters:
        if f["ref"]:
            refs.add(f["ref"])
    if issue_ref:
        refs.add(issue_ref)
    if out["within"]:
        refs.add(out["within"])
    if out["when"]:
        refs.add(out["when"])
    out["refs"] = frozenset(refs)
    return out


def canon_plan(plan: dict) -> list[dict]:
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    id_index = {str(s.get("id")): i for i, s in enumerate(steps)}
    return [canon_step(s, id_index) for s in steps]


def _jsonable(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(v) for v in value), key=lambda x: json.dumps(x, ensure_ascii=False))
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in sorted(value.items())}
    return value


def plan_signature(plan: dict) -> str:
    """多次运行比一致用：去掉措辞类字段（现象描述）；理解、追问的话、临时统计说明本来就不在归一结果里。"""
    sig = []
    for c in canon_plan(plan):
        c = dict(c)
        c.pop("phenomenon", None)
        # 「单数」是统计的默认指标，写不写结果一样（规划提示：只是数单数时可以不写）
        c["metrics"] = c["metrics"] - {"单数"}
        sig.append(_jsonable(c))
    return json.dumps(sig, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# 对照期望
# ---------------------------------------------------------------------------


def _any_of(x: Any) -> list:
    return x if isinstance(x, list) else [x]


def _contains_all(text: str, tokens: list[str]) -> bool:
    return all(norm(t) in text for t in tokens)


def _parse_ref_str(s: str) -> tuple[int, str]:
    m = _REF.match(s.strip())
    if not m:
        raise ValueError(f"期望里的引用写错了：{s}")
    return int(m.group(1)) - 1, m.group(2)


def _match_filter(exp: dict, got: dict, mapping: list[int]) -> bool:
    fields = [norm_field(f) for f in _any_of(exp["field"])]
    if got["field"] not in fields:
        return False
    if "column" in exp and norm(exp["column"]) not in got["column"] and got["column"] not in norm(exp["column"]):
        return False
    if "op" in exp:
        want = _OP.get(exp["op"], exp["op"])
        if want in _NEGATIVE:
            if got["op"] not in _NEGATIVE:
                return False
        elif want in _POSITIVE:
            if got["op"] not in _POSITIVE:
                return False
        elif got["op"] != want:
            return False
    elif got["op"] not in _POSITIVE:
        return False
    if "value_ref" in exp:
        idx, out = _parse_ref_str(exp["value_ref"])
        return got["ref"] is not None and _map_idx(got["ref"][0], mapping) == idx and got["ref"][1] == out
    if got["ref"] is not None:
        return False
    if "value" in exp:
        return got["values"] == _values(exp["value"])
    if "value_any" in exp:
        return any(got["values"] == _values(v) for v in exp["value_any"])
    if "value_has" in exp:
        joined = "".join(sorted(got["values"]))
        return _contains_all(joined, exp["value_has"])
    return True


def _map_idx(pred_idx: int, mapping: list[int]) -> int:
    """模型第 pred_idx 步对上期望的第几步（-1 表示没对上）。"""
    for e_idx, p_idx in enumerate(mapping):
        if p_idx == pred_idx:
            return e_idx
    return -1


def _match_set(required: list[dict], optional: list[dict], got: list[dict], mapping: list[int]) -> bool:
    used = [False] * len(got)
    for exp in required:
        hit = next((j for j, g in enumerate(got) if not used[j] and _match_filter(exp, g, mapping)), None)
        if hit is None:
            return False
        used[hit] = True
    for j, g in enumerate(got):
        if used[j]:
            continue
        if not any(_match_filter(o, g, mapping) for o in optional):
            return False
    return True


def _from_ok(required: list[dict], got: list[dict], mapping: list[int]) -> bool | None:
    checks = [e for e in required if "from" in e]
    if not checks:
        return None
    for exp in checks:
        hit = next((g for g in got if _match_filter(exp, g, mapping)), None)
        if hit is None or hit["from"] != exp["from"]:
            return False
    return True


def _said_ok(e: dict, g: dict) -> bool:
    if "said_has" in e:
        return _contains_all(g["said"], e["said_has"])
    return g["said"] in [norm(x) for x in _any_of(e["said"])]


def _match_time(exp_items: list[dict], got: list[dict]) -> tuple[bool, bool | None, bool | None]:
    """返回 (原话对不对, 日期依据对不对, 来源对不对)；None 表示这一项不适用。"""
    wants_from = any("from" in e for e in exp_items)
    if len(exp_items) != len(got):
        return False, (False if exp_items else None), (False if wants_from else None)
    if not exp_items:
        return True, None, None
    said_ok = any(
        all(_said_ok(e, got[j]) for e, j in zip(exp_items, perm))
        for perm in itertools.permutations(range(len(got)))
    )
    basis_ok = sorted(g["basis"] for g in got) == sorted(norm(e.get("basis", "建单")) for e in exp_items)
    from_ok = None
    if wants_from:
        from_ok = sorted(g["from"] for g in got) == sorted(e.get("from", "user") for e in exp_items)
    return said_ok, basis_ok, from_ok


def _score_step(exp: dict, got: dict, mapping: list[int], res: dict[str, bool]) -> None:
    def put(cat: str, ok: bool | None) -> None:
        if ok is None:
            return
        res[cat] = res.get(cat, True) and bool(ok)

    skill = exp["skill"]
    cond = (skill if isinstance(skill, str) else skill[0]) in COND_SKILLS
    # 域
    if exp.get("domains") != "any" and (cond or "domains" in exp):
        want = exp.get("domains")
        wset = None if not want or set(want) == set(DOMAINS) else frozenset(norm(x) for x in want)
        put("域", got["domains"] == wset)
    if "domains_from" in exp:
        put("沿用与替换", got["domains_from"] == exp["domains_from"])
    # 时间
    if exp.get("time") != "any" and (cond or "time" in exp):
        said_ok, basis_ok, from_ok = _match_time(exp.get("time") or [], got["time"])
        put("时间原话", said_ok)
        put("日期依据", basis_ok)
        put("沿用与替换", from_ok)
    # 条件
    if exp.get("filters") != "any" and (cond or "filters" in exp):
        req, opt = exp.get("filters") or [], exp.get("filters_optional") or []
        put("条件", _match_set(req, opt, got["filters"], mapping))
        put("沿用与替换", _from_ok(req, got["filters"], mapping))
    # 分组与指标
    if "group_by" in exp:
        put("分组与指标", got["group_by"] == frozenset(_GROUP.get(norm(g), norm(g)) for g in exp["group_by"]))
    if "group_by_has" in exp:
        put("分组与指标", all(_GROUP.get(norm(g), norm(g)) in got["group_by"] for g in exp["group_by_has"]))
    if "metrics_has" in exp:
        want_m = [_METRIC.get(norm(m), norm(m)) for m in exp["metrics_has"]]
        put("分组与指标", all(m in got["metrics"] for m in want_m))
    if exp.get("ranking"):
        put("分组与指标", got["ranking"])
    if "top" in exp:
        put("分组与指标", got["top"] == exp["top"])
    if "compare" in exp:
        c, gc = exp["compare"], got["compare"]
        ok = gc is not None and gc["kind"] == norm(c["kind"])
        if ok and "field" in c:
            ok = gc.get("field") == norm_field(c["field"])
        if ok and "items_has" in c:
            ok = all(any(norm(t) in item for item in gc.get("items", [])) for t in c["items_has"])
        if ok and "items_count" in c:
            ok = len(gc.get("items", [])) == c["items_count"]
        put("分组与指标", ok)
    if "sort" in exp:
        want_s = (norm(exp["sort"]["by"]), norm(exp["sort"].get("order", "降序")))
        put("排序与条数", got["sort"] == want_s)
    if "limit" in exp:
        put("排序与条数", got["limit"] == exp["limit"])
    # 号码与单号
    if "numbers" in exp:
        put("号码与单号", sorted(got["numbers"]) == sorted(norm(n) for n in exp["numbers"]))
    if "issue" in exp:
        want_i = exp["issue"]
        if isinstance(want_i, dict):
            idx, out = _parse_ref_str(want_i["ref"])
            gi = got["issue"]
            put("号码与单号", isinstance(gi, tuple) and _map_idx(gi[1], mapping) == idx and gi[2] == out)
            put("依赖", isinstance(gi, tuple) and _map_idx(gi[1], mapping) == idx and gi[2] == out)
        else:
            put("号码与单号", got["issue"] == norm(want_i))
    if "issue_from" in exp:
        put("沿用与替换", got["issue_from"] == exp["issue_from"])
    # 详情内容
    if "aspects_has" in exp:
        ok = True
        for a in exp["aspects_has"]:
            options = [_ASPECT.get(norm(x), norm(x)) for x in _any_of(a)]
            ok &= any(o in got["aspects"] for o in options)
        put("详情内容", ok)
    # 文字查找
    if "mode" in exp:
        put("文字查找", got["mode"] in [norm(m) for m in _any_of(exp["mode"])])
    if "terms" in exp:
        put("文字查找", got["terms"] == frozenset(norm(t) for t in exp["terms"]))
    if "logic" in exp:
        put("文字查找", got["logic"] == norm(exp["logic"]))
    if "topic_has" in exp:
        put("文字查找", _contains_all(got["topic"], exp["topic_has"]))
    if "topic_scope" in exp:
        put("文字查找", got["topic_scope"] in [norm(s) for s in _any_of(exp["topic_scope"])])
    if "phenomenon_has" in exp:
        put("文字查找", _contains_all(got["phenomenon"], exp["phenomenon_has"]))
    if "approach_has" in exp:
        put("文字查找", _contains_all(got["approach"], exp["approach_has"]))
    if "fields_has" in exp:
        ok = True
        for f in exp["fields_has"]:
            options = [norm(x) for x in _any_of(f)]
            ok &= any(any(o in g or g in o for g in got["fields"]) for o in options)
        put("文字查找", ok)
    if "ask" in exp:
        put("文字查找", got["ask"] == norm(exp["ask"]))
    if "text_has" in exp:
        # 要找的词写在话题、关键词、做法、现象哪一栏都行，程序都会拿去找
        text = got["topic"] + "".join(sorted(got["terms"])) + got["approach"] + got["phenomenon"]
        put("文字查找", _contains_all(text, exp["text_has"]))
    if "text_not_has" in exp:
        # 条件值（机型、供应商……）已在 filters 里，再写进要找的文字就是把条件混进了现象
        text = got["topic"] + "".join(sorted(got["terms"])) + got["approach"] + got["phenomenon"]
        put("文字查找", not any(norm(t) in text for t in exp["text_not_has"]))
    # 列与导出
    if "columns_has" in exp:
        ok = True
        for col in exp["columns_has"]:
            options = [norm(x) for x in _any_of(col)]
            ok &= any(any(o in g or g in o for g in got["columns"]) for o in options)
        put("列与导出", ok)
    if "export" in exp:
        put("列与导出", got["export"] == bool(exp["export"]))
    # 依赖
    if "within" in exp:
        idx = int(exp["within"][1:]) - 1
        w = got["within"]
        put("依赖", w is not None and _map_idx(w[0], mapping) == idx and w[1] == "issues")
    if "when" in exp:
        idx, out = _parse_ref_str(exp["when"])
        w = got["when"]
        put("依赖", w is not None and _map_idx(w[0], mapping) == idx and w[1] == out)
    if "refs_has" in exp:
        ok = True
        for r in exp["refs_has"]:
            idx, out = _parse_ref_str(r)
            ok &= any(_map_idx(g[0], mapping) == idx and g[1] == out for g in got["refs"])
        put("依赖", ok)
    for f in exp.get("filters") or [] if isinstance(exp.get("filters"), list) else []:
        if isinstance(f, dict) and "value_ref" in f:
            idx, out = _parse_ref_str(f["value_ref"])
            put("依赖", any(
                g["ref"] is not None and _map_idx(g["ref"][0], mapping) == idx and g["ref"][1] == out
                for g in got["filters"]
            ))
    # 其他
    if "chart" in exp:
        put("其他", got["chart"] == norm(exp["chart"]))
    if "kind" in exp:
        put("其他", got["kind"] in [norm(k) for k in _any_of(exp["kind"])])
    if "reason" in exp:
        put("其他", got["reason"] in [norm(k) for k in _any_of(exp["reason"])])


def _alt_steps(alt: Any) -> tuple[list[dict], dict]:
    if isinstance(alt, list):
        return alt, {}
    return alt["steps"], {k: v for k, v in alt.items() if k != "steps"}


def _ordered(exp_steps: list[dict]) -> bool:
    for e in exp_steps:
        if "within" in e or "when" in e or "refs_has" in e:
            return True
        if isinstance(e.get("issue"), dict):
            return True
        if any(isinstance(f, dict) and "value_ref" in f for f in e.get("filters") or []):
            return True
    return False


def _skill_ok(exp: dict, got: dict) -> bool:
    return got["skill"] in _any_of(exp["skill"])


def score_alt(alt: Any, plan: dict, canon: list[dict]) -> dict[str, bool]:
    exp_steps, extra = _alt_steps(alt)
    n, m = len(exp_steps), len(canon)
    candidates: list[list[int]] = []
    if _ordered(exp_steps) or max(n, m) > 4:
        candidates.append(list(range(n)))
    else:
        candidates = [list(p) for p in itertools.permutations(range(m), min(n, m))]
        candidates = [c + [-1] * (n - len(c)) for c in candidates] or [[-1] * n]
    best: dict[str, bool] | None = None
    for mapping in candidates:
        res: dict[str, bool] = {}
        skills_ok = n == m and all(
            mapping[i] < m and mapping[i] >= 0 and _skill_ok(e, canon[mapping[i]]) for i, e in enumerate(exp_steps)
        )
        res["技能"] = skills_ok
        for i, e in enumerate(exp_steps):
            j = mapping[i] if i < len(mapping) else -1
            if j < 0 or j >= m or not _skill_ok(e, canon[j]):
                missing: dict[str, bool] = {}
                _score_step(e, _blank(), mapping, missing)
                for cat in missing:
                    res[cat] = False
                continue
            _score_step(e, canon[j], mapping, res)
        if extra.get("alternatives_nonempty"):
            res["其他"] = res.get("其他", True) and bool(plan.get("alternatives"))
        if best is None or sum(res.values()) > sum(best.values()):
            best = res
    return best or {"技能": False}


def _blank() -> dict:
    return {
        "skill": None, "domains": frozenset(["?"]), "domains_from": None, "time": [{"said": "?", "basis": "?", "from": "?"}],
        "filters": [{"field": "?", "column": "", "op": "?", "values": frozenset(), "ref": None, "from": "?"}],
        "group_by": frozenset(["?"]), "metrics": frozenset(), "ranking": False, "top": -1, "compare": None,
        "sort": ("?", "?"), "limit": -1,
        "numbers": ["?"], "issue": "?", "issue_from": "?", "aspects": frozenset(), "mode": "?", "terms": frozenset(["?"]),
        "logic": "?", "topic": "", "topic_scope": "?", "phenomenon": "", "approach": "", "fields": frozenset(), "ask": "?",
        "columns": frozenset(), "export": None, "chart": "?", "kind": "?", "reason": "?", "within": None, "when": None,
        "refs": frozenset(),
    }


def score_plan(case: dict, plan: dict) -> dict:
    """返回 {categories: {类别: 对错}, all_ok, alt, clarify: 漏问/多问/None}。"""
    canon = canon_plan(plan)
    best: dict[str, bool] | None = None
    best_alt = 0
    for k, alt in enumerate(case["expect"]):
        res = score_alt(alt, plan, canon)
        if best is None or (all(res.values()), sum(res.values())) > (all(best.values()), sum(best.values())):
            best, best_alt = res, k
    assert best is not None
    has_clarify = any(c["skill"] == "clarify" for c in canon)
    kind = case.get("clarify", "none")
    clarify_issue = None
    if kind == "model" and not has_clarify:
        clarify_issue = "漏问"
    elif kind == "rule" and not has_clarify:
        if any(c["skill"] in COND_SKILLS and c["time"] for c in canon):
            clarify_issue = "漏问"
    elif kind in ("none", "db") and has_clarify:
        clarify_issue = "多问"
    # kind == "optional"：问不问都行（口径未定的通用输入），只看计划本身对不对
    return {"categories": best, "all_ok": all(best.values()) and clarify_issue is None,
            "alt": best_alt, "clarify": clarify_issue}


# ---------------------------------------------------------------------------
# 反例（--self-check 用）：把期望计划改坏一处，打分必须判错
# ---------------------------------------------------------------------------

_SKILL_SWAP = ("list_issues", "aggregate", "issue_detail", "text_search", "lookup_numbers", "custom_stats")


def _skills_at(case: dict, pos: int) -> set[str]:
    seen: set[str] = set()
    for alt in case["expect"]:
        steps = _alt_steps(alt)[0]
        if pos < len(steps):
            seen.update(_any_of(steps[pos]["skill"]))
    return seen


def mutations(case: dict) -> list[tuple[str, dict]]:
    """返回 [(改了什么, 改坏的计划)]。只在期望确实约束了那一处时才改。"""
    import copy

    base = render_expected(case)
    exp_steps = _alt_steps(case["expect"][0])[0]
    out: list[tuple[str, dict]] = []

    def variant(label: str, fn) -> None:
        plan = copy.deepcopy(base)
        if fn(plan) is not False:
            out.append((label, plan))

    kind = case.get("clarify", "none")
    used0 = _skills_at(case, 0)
    swap = next((s for s in _SKILL_SWAP if s not in used0), None)
    if swap and kind != "model":
        variant("换技能", lambda p: p["steps"][0].update(skill=swap))
    if len(base["steps"]) > 1:
        variant("删最后一步", lambda p: p["steps"].pop())
    if kind == "model":
        variant("该问不问", lambda p: p.update(steps=[{"id": "s1", "skill": "list_issues", "when": None,
                                                    "params": {"time": [{"said": "最近30天"}]}}]))
    elif not any("clarify" in _skills_at(case, i) for i in range(6)):
        variant("不该问却问", lambda p: p.update(steps=[{"id": "s1", "skill": "clarify", "when": None,
                                                      "params": {"ask": "请问要查哪个机型？"}}]))
    for i, e in enumerate(exp_steps):
        sp = f"第{i + 1}步"
        filters = e.get("filters") if isinstance(e.get("filters"), list) else []
        for j, f in enumerate(filters):
            if any(k in f for k in ("value", "value_any", "value_has")):
                def bad_value(p, i=i, j=j):
                    p["steps"][i]["params"]["filters"][j]["value"] = "不存在的取值"
                variant(f"{sp}改条件值", bad_value)
                break
        if filters:
            def drop_filter(p, i=i):
                p["steps"][i]["params"]["filters"].pop(0)
            variant(f"{sp}少一个条件", drop_filter)
        if isinstance(e.get("time"), list) and e["time"]:
            def bad_time(p, i=i):
                p["steps"][i]["params"]["time"][0]["said"] = "前年冬天"
            variant(f"{sp}改时间原话", bad_time)
            if "basis" in e["time"][0] and e["time"][0]["basis"] != "建单":
                def bad_basis(p, i=i):
                    p["steps"][i]["params"]["time"][0]["basis"] = "建单"
                variant(f"{sp}改日期依据", bad_basis)
        if e.get("domains") not in (None, "any") and set(e["domains"]) != set(DOMAINS):
            def bad_domain(p, i=i):
                p["steps"][i]["params"].pop("domains", None)
            variant(f"{sp}域放宽到三域", bad_domain)
        if "group_by" in e or "group_by_has" in e:
            wanted = set(e.get("group_by") or e.get("group_by_has"))
            other = next(d for d in ("加工厂", "月", "问题等级") if d not in wanted)
            def bad_group(p, i=i, other=other):
                p["steps"][i]["params"]["group_by"] = [other]
            variant(f"{sp}改分组", bad_group)
        if "numbers" in e and e["numbers"]:
            def bad_numbers(p, i=i):
                p["steps"][i]["params"]["numbers"] = p["steps"][i]["params"]["numbers"][:-1] + [{"raw": "ZC0000000"}]
            variant(f"{sp}改号码", bad_numbers)
        if "issue" in e:
            def bad_issue(p, i=i):
                p["steps"][i]["params"]["issue"] = {"value": "ZC0000000", "from": "user"}
            variant(f"{sp}改单号或引用", bad_issue)
        if "aspects_has" in e:
            def bad_aspects(p, i=i):
                p["steps"][i]["params"]["aspects"] = ["其他:无关内容"]
            variant(f"{sp}改详情内容", bad_aspects)
        if "mode" in e:
            other_mode = next(m for m in TEXT_MODES if norm(m) not in [norm(x) for x in _any_of(e["mode"])])
            def bad_mode(p, i=i, other_mode=other_mode):
                p["steps"][i]["params"]["mode"] = other_mode
            variant(f"{sp}改文字查找方式", bad_mode)
        if "within" in e:
            def bad_within(p, i=i):
                p["steps"][i]["params"].pop("within", None)
            variant(f"{sp}丢掉范围引用", bad_within)
        if "when" in e:
            def bad_when(p, i=i):
                p["steps"][i]["when"] = None
            variant(f"{sp}丢掉执行条件", bad_when)
        if e.get("export"):
            def bad_export(p, i=i):
                p["steps"][i]["params"]["export"] = False
            variant(f"{sp}漏导出", bad_export)
        if e.get("ranking"):
            def bad_rank(p, i=i):
                p["steps"][i]["params"].pop("ranking", None)
                p["steps"][i]["params"].pop("top", None)
            variant(f"{sp}漏排名", bad_rank)
        if "sort" in e:
            def bad_sort(p, i=i):
                s = p["steps"][i]["params"]["sort"]
                s["order"] = "升序" if s.get("order", "降序") == "降序" else "降序"
            variant(f"{sp}排序方向反了", bad_sort)
        if "limit" in e:
            def bad_limit(p, i=i):
                p["steps"][i]["params"]["limit"] = p["steps"][i]["params"]["limit"] + 1
            variant(f"{sp}改条数", bad_limit)
        if "approach_has" in e:
            def bad_approach(p, i=i):
                p["steps"][i]["params"].pop("approach", None)
            variant(f"{sp}丢掉做法", bad_approach)
    return out


def harmless(case: dict) -> list[tuple[str, dict]]:
    """返回 [(改了什么, 计划)]：只改写法不改意思，打分必须仍判对。"""
    import copy

    base = render_expected(case)
    exp_steps = _alt_steps(case["expect"][0])[0]
    out: list[tuple[str, dict]] = []

    def variant(label: str, fn) -> None:
        plan = copy.deepcopy(base)
        if fn(plan) is not False:
            out.append((label, plan))

    def spaced(p):
        hit = False
        for s in p["steps"]:
            for t in s["params"].get("time") or []:
                t["said"] = " ".join(t["said"])
                hit = True
        return hit
    variant("时间原话加空格", spaced)

    def op_synonym(p):
        hit = False
        for s in p["steps"]:
            for f in s["params"].get("filters") or []:
                if f.get("op") == "是":
                    f["op"] = "等于"
                    hit = True
        return hit
    variant("比较方式写同义词", op_synonym)

    def all_domains(p):
        hit = False
        for s, e in zip(p["steps"], exp_steps):
            if e.get("domains") is None and _first(e["skill"]) in COND_SKILLS:
                s["params"]["domains"] = {"value": list(DOMAINS), "from": "user"}
                hit = True
        return hit
    variant("三域写全", all_domains)

    def drop_default_from(p):
        hit = False
        for s in p["steps"]:
            for key in ("time", "filters"):
                for item in s["params"].get(key) or []:
                    if item.get("from") == "user":
                        item.pop("from")
                        hit = True
        return hit
    variant("省略默认来源", drop_default_from)

    def upper_values(p):
        hit = False
        for s in p["steps"]:
            for f in s["params"].get("filters") or []:
                if isinstance(f.get("value"), str) and f["value"].lower() != f["value"].upper():
                    f["value"] = unicodedata_fullwidth(f["value"].swapcase())
                    hit = True
        return hit
    variant("取值换大小写与全角", upper_values)

    def bare_ref(p):
        hit = False
        for s in p["steps"]:
            issue = s["params"].get("issue")
            if isinstance(issue, dict) and _is_ref(issue.get("value")):
                s["params"]["issue"] = issue["value"]
                hit = True
        return hit
    variant("单号引用不包 value", bare_ref)

    # 以下几种是 p0、p1 的旧写法或多余写法，代码统一后应与新写法等价
    def old_object_compare(p):
        hit = False
        for s in p["steps"]:
            pr = s["params"]
            if pr.get("compare") is not None:
                continue
            for f in list(pr.get("filters") or []):
                if (isinstance(f.get("value"), list) and len(f["value"]) >= 2
                        and f.get("op", "是") in ("是", "属于")
                        and f.get("field") in (pr.get("group_by") or [])):
                    pr["filters"].remove(f)
                    if not pr["filters"]:
                        pr.pop("filters")
                    pr["compare"] = {"kind": "对象", "field": f["field"], "items": f["value"]}
                    hit = True
                    break
        return hit
    variant("对象对比写成旧写法", old_object_compare)

    def old_period_compare(p):
        hit = False
        for s in p["steps"]:
            pr = s["params"]
            if pr.get("compare") == "时段":
                pr["compare"] = {"kind": "时段", "items": [t["said"] for t in pr.get("time") or []]}
                hit = True
        return hit
    variant("时段对比写成旧写法", old_period_compare)

    def explicit_ask(p):
        hit = False
        for s in p["steps"]:
            if s["skill"] == "text_search" and not s["params"].get("ask"):
                s["params"]["ask"] = "现象"
                hit = True
        return hit
    variant("写上默认的问现象", explicit_ask)

    def implied_status(p):
        hit = False
        for s in p["steps"]:
            pr = s["params"]
            if any(t.get("basis") == "停线" for t in pr.get("time") or []):
                pr.setdefault("filters", []).append({"field": "状态", "op": "是", "value": "曾经停线", "from": "user"})
                hit = True
        return hit
    variant("有停线日期时再加曾经停线", implied_status)

    if len(base["steps"]) > 1 and not _ordered(exp_steps) and len(base["steps"]) <= 4:
        def reverse(p):
            p["steps"].reverse()
            for k, s in enumerate(p["steps"]):
                s["id"] = f"s{k + 1}"
        variant("无依赖的步骤换顺序", reverse)
    return out


def unicodedata_fullwidth(text: str) -> str:
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text)


# ---------------------------------------------------------------------------
# 期望 → 计划（--self-check 冒充模型用）
# ---------------------------------------------------------------------------


def _first(x: Any) -> Any:
    return x[0] if isinstance(x, list) else x


def render_expected(case: dict) -> dict:
    exp_steps, extra = _alt_steps(case["expect"][0])
    steps = []
    for i, e in enumerate(exp_steps):
        p: dict[str, Any] = {}
        if e.get("domains") not in (None, "any"):
            p["domains"] = {"value": e["domains"], "from": e.get("domains_from", "user")}
        if e.get("time") not in (None, "any"):
            p["time"] = [
                {"said": "".join(t["said_has"]) if "said_has" in t else _first(t["said"]),
                 "basis": t.get("basis", "建单"), "from": t.get("from", "user")}
                for t in e["time"]
            ]
        if e.get("filters") not in (None, "any"):
            fl = []
            for f in e["filters"]:
                item: dict[str, Any] = {"field": _first(f["field"]), "op": f.get("op", "是"), "from": f.get("from", "user")}
                if "column" in f:
                    item["column"] = f["column"]
                if "value_ref" in f:
                    item["value"] = {"ref": f["value_ref"]}
                elif "value" in f:
                    item["value"] = f["value"]
                elif "value_any" in f:
                    item["value"] = f["value_any"][0]
                elif "value_has" in f:
                    item["value"] = "".join(f["value_has"])
                fl.append(item)
            if fl:
                p["filters"] = fl
        for key in ("group_by", "top", "terms", "logic", "topic_scope", "ask", "chart", "reason"):
            if key in e:
                p[key] = _first(e[key]) if key in ("topic_scope", "chart", "reason") else e[key]
        if "group_by_has" in e:
            p["group_by"] = e["group_by_has"]
        if "metrics_has" in e:
            p["metrics"] = e["metrics_has"]
        if e.get("ranking"):
            p["ranking"] = True
        if "compare" in e:
            p["compare"] = "时段"
        if "sort" in e:
            p["sort"] = {"by": e["sort"]["by"], "order": e["sort"].get("order", "降序")}
        if "limit" in e:
            p["limit"] = e["limit"]
        if "approach_has" in e:
            p["approach"] = "".join(e["approach_has"])
        if "numbers" in e:
            p["numbers"] = [{"raw": n, "kind_said": None} for n in e["numbers"]]
        if "issue" in e:
            p["issue"] = {"value": e["issue"], "from": e.get("issue_from", "user")}
        if "aspects_has" in e:
            p["aspects"] = [_first(a) for a in e["aspects_has"]]
        if "mode" in e:
            p["mode"] = _first(e["mode"])
        if "topic_has" in e:
            p["topic"] = "".join(e["topic_has"])
        if "text_has" in e and "topic" not in p:
            p["topic"] = "".join(e["text_has"])
        if "phenomenon_has" in e:
            p["phenomenon"] = "".join(e["phenomenon_has"])
        if "fields_has" in e:
            p["fields"] = [_first(f) for f in e["fields_has"]]
        if "columns_has" in e:
            p["columns"] = [_first(c) for c in e["columns_has"]]
        if e.get("export"):
            p["export"] = True
        if "kind" in e:
            p["kind"] = _first(e["kind"])
        if "within" in e:
            p["within"] = {"ref": f"{e['within']}.issues"}
        step: dict[str, Any] = {"id": f"s{i + 1}", "skill": _first(e["skill"]), "when": None, "params": p}
        if "when" in e:
            step["when"] = {"ref": e["when"]}
        if "refs_has" in e:
            # refs_has 只用于引用已经写在 issue / filters 里的情形，渲染时不另加
            pass
        steps.append(step)
    return {"understanding": "（自检）", "alternatives": ["（自检）"] if extra.get("alternatives_nonempty") else [], "steps": steps}
