"""规划器实测用的提示词。规划、写分析、反思、临时统计四种调用各一套。

- 业务口径的信源是 docs/2_landed：术语表、说法清单、初步分析维度在运行时从那里读，不在这里复写。
- 规划提示 S1 起由 `src/factory_issue_module/plan/prompt.py` 持有（设计 §1.3 末条），这里只转接；
  写分析、反思、临时统计三套仍在这里，随 G4b 各片迁到 src。
- 规划提示只拼术语表（`glossary_section`），不拼「必要澄清项」：那张表里重名、多工厂、系列对不上等
  情形要查库才知道，由程序判断，交给模型只会让它乱追问。
- 平台红线段由 `forge_platform.policy.PolicyLLM` 并进首条 system，与线上 `ctx.llm` 完全一样（见 spike.py）。
"""

from __future__ import annotations

import json
import re

from forge_core.module import AnalysisDimension, GlossaryTerm, ModuleManifest
from forge_core.prompting import analysis_section

from factory_issue_module.config import files as _config_files
from factory_issue_module.declarations import TOPIC_TERMS
from factory_issue_module.module import FactoryIssueModule
from factory_issue_module.plan import prompt as _plan_prompt
from factory_issue_module.plan.schema import (  # noqa: F401  scoring 从这里取枚举
    BASES, FILTER_FIELDS, GROUP_DIMS, METRICS, OPS, REF_OUTPUTS, SKILLS, SORT_FIELDS, SORT_ORDERS, TEXT_MODES,
)

from common import LANDED

# p0 → p1（2026-10-27，按 p0 实测的固定错法改）：话题范围改由程序对照话题清单判断，模型不再填；
# 加 approach（问做法时用户说的具体做法）；补结案日期、「X 各型号」、同一统计不拆步、
# 后半句沿用时间、「其他」追问的说法；写分析加「不自己合计、不设门槛、不换算单位」。
# p1 → p2（2026-10-27，开发者同意）：同一个意思只留一种写法（对象对比改成筛选加分组、时段对比写成
# compare: "时段"、ask 默认现象、没说要看什么不写 aspects、issue 一律 {value, from}）；清单加 sort / limit，
# 统计加引用 top_values；规划输入去掉「本轮可查的域」；问做法加现象按 G59 建议写；
# 按 p1 回退补「时间修饰哪件事」「条件不写进现象」「没给条件的清单不追问」「如果…就…拆两步」。
# 规划提示 S1 起在 src（`plan/prompt.py`），版本号随它。
PROMPT_VERSION = _plan_prompt.PROMPT_VERSION

# ---------------------------------------------------------------------------
# 从 2_landed 读术语表、说法清单、初步分析维度
# ---------------------------------------------------------------------------


def _md_table(md: str, heading: str) -> list[list[str]]:
    """取某个标题下的第一张 Markdown 表（去掉表头与分隔行）。"""
    lines = md.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().startswith("#") and heading in line), None)
    if start is None:
        raise ValueError(f"找不到标题：{heading}")
    rows: list[list[str]] = []
    seen_table = False
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("#") and seen_table:
            break
        if not stripped.startswith("|"):
            if seen_table:
                break
            continue
        seen_table = True
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows[1:]  # 去掉表头


def load_glossary() -> list[GlossaryTerm]:
    md = (LANDED / "glossary.md").read_text(encoding="utf-8")
    terms: list[GlossaryTerm] = []
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith("|") or s.startswith("| 规范词") or set(s) <= set("|-: "):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        aliases = [] if cells[1] in ("", "—", "-") else [a.strip() for a in cells[1].split("、") if a.strip()]
        terms.append(GlossaryTerm(term=cells[0], aliases=aliases, definition=cells[2]))
    return terms


_CHART = {"柱状": "bar", "饼图": "pie", "折线": "line"}


def load_analysis_dimensions() -> list[AnalysisDimension]:
    md = (LANDED / "business_description.md").read_text(encoding="utf-8")
    dims = []
    for cells in _md_table(md, "## 初步分析维度"):
        if len(cells) >= 3:
            dims.append(AnalysisDimension(name=cells[0], description=cells[1], chart=_CHART.get(cells[2], "")))
    return dims


def draft_manifest() -> ModuleManifest:
    """实测用的 manifest 草案：只填提示要用的三项，其余随 G4b。"""
    return ModuleManifest(
        code="FACTORY_ISSUE",
        name="制程问题查询助手",
        glossary=load_glossary(),
        analysis_dimensions=load_analysis_dimensions(),
    )


# ---------------------------------------------------------------------------
# 规划：S1 起调 src（`factory_issue_module.plan.prompt`、`plan.schema`），这里只按对照集的形状转接
# ---------------------------------------------------------------------------

#: 话题清单用内置默认值（`2_landed/topic_terms.md`），与线上没上传配置时相同
TOPICS = _config_files.default(TOPIC_TERMS)


#: S1 起在 p2 之上的几处改动：名字 → [(现在的原文, p2 的原文)]。`--prompt-changes` 只保留其中几项时，其余照 p2
#: 还原，用来拆开量每处改动的作用。只在 spike 里还原，`src` 的提示仍只有一份；`src` 改了这几句，这里找不到原文就报错
#: 2026-10-29 拆开量过的「备选」「追问选项」两处没有采用，已从 src 删掉；以后再试新改动时照这个格式加进来
PROMPT_CHANGES: dict[str, list[tuple[str, str]]] = {
    "部门": [
        ("：责任归属部门。部门的简称、日常说法（「一部」「工程部」）也是部门：「一部今年有哪些问题」写成 list_issues，"
         "跟进部门 是 一部，不按文字找。",
         "：责任归属部门。"),
    ],
}
_kept: tuple[str, ...] = tuple(PROMPT_CHANGES)


def keep_prompt_changes(names: list[str]) -> None:
    """只保留这几处改动（空列表 = 全部还原成 p2）；提示词版本号随之标上保留了哪几处。"""
    global _kept, PROMPT_VERSION
    unknown = [n for n in names if n not in PROMPT_CHANGES]
    if unknown:
        raise SystemExit(f"--prompt-changes 只认 {'、'.join(PROMPT_CHANGES)}（或「无」），不认 {'、'.join(unknown)}")
    _kept = tuple(n for n in PROMPT_CHANGES if n in names)
    PROMPT_VERSION = f"{_plan_prompt.PROMPT_VERSION}-只留{'+'.join(_kept) or '无（即 p2）'}"


def planner_module_system() -> str:
    return _plan_prompt.module_system(TOPICS)


def planner_system() -> str:
    text = _plan_prompt.planner_system(FactoryIssueModule.manifest, TOPICS)
    for name, pairs in PROMPT_CHANGES.items():
        if name in _kept:
            continue
        for new, old in pairs:
            if text.count(new) != 1:
                raise RuntimeError(f"规划提示里找不到改动「{name}」的原文，`src/.../plan/prompt.py` 改过了，请同步 PROMPT_CHANGES")
            text = text.replace(new, old)
    return text


def history_messages(case: dict) -> list[dict]:
    """对照集的 history（每轮 user、assistant 各一句）→ `conversation_messages` 的形状。"""
    out: list[dict] = []
    for turn in case.get("history") or []:
        out += [{"role": "user", "content": turn["user"]}, {"role": "assistant", "content": turn["assistant"]}]
    return out


def planner_user(case: dict, prematch: bool = False) -> str:
    # p2 起不给规划器看权限：理解与权限无关，权限由程序在规划前后施加（对照集里的 perms 只留作说明）
    # prematch：在本轮问题后面附「问句里能对上的名称与号码」（prematch.py），系统提示不变，用来比较附与不附
    text = _plan_prompt.planner_user(case["q"], history_messages(case), case.get("previous_plan"),
                                     case.get("previous_outcome"))
    if prematch:
        from prematch import hint_text

        hint = hint_text(case["q"])
        if hint:
            text += "\n" + hint
    return text


def repair_user(errors: list[str]) -> str:
    return _plan_prompt.repair_user(errors)


# ---------------------------------------------------------------------------
# 写分析
# ---------------------------------------------------------------------------

NARRATIVE_MODULE_SYSTEM = """你是「制程问题查询助手」的回答撰写人。程序已经查好数据、算好数字，并已把表格和图表展示给用户。你只写表格下面的一段分析文字。

要求：
1. 第一句直接回应用户的问题：有几张、有没有、哪个最多、是否增加。
2. 只能使用【事实】里出现的数字，不自己做任何计算：不求和、不求差、不算百分比、不数行数。事实里没有的数字就不说。下面几种也算自己计算，不要写：
   - 把几项加起来说（「两类合计七成以上」「后三类不足四分之一」）；
   - 自己定一个整数当门槛（「连续三个月 30 单以上」「均超过 10 单」「超过一半」）；
   - 换算单位（把「91 天及以上」说成「超过三个月」）。
   要说集中程度时，用【事实】里给的占比或合计；没有就只说「主要集中在物料问题和硬件问题」，不带数。
   - 「一半」「三成」「翻倍」「几个百分点」这类约数与比值，【事实】里没有同样的说法就不写；
   - 日期只用【事实】里的年、月、日，不写「中旬」「月初」这类更细的说法。
3. 说重点：集中在哪、最需要关注的是哪几张（点名问题编号）、一句结论。不要把表格逐行复述。点名的机型、系列、工厂、部门只用【事实】或表格里出现过的，不自己归纳（如把几个机型说成「A 系列」）。
4. 用业务说法，不出现英文代码、数据库表名或字段名。
5. 不写统计口径，程序会另附。
6. 写 3 到 6 句话，不用标题，不用列表，不用 Markdown。
7. 【说明】里有程序做过的调整（如放宽了时间范围、按什么理解），要在开头一句说清楚。"""


def narrative_system() -> str:
    return NARRATIVE_MODULE_SYSTEM + "\n\n" + analysis_section(draft_manifest())


def narrative_user(case: dict) -> str:
    parts = [f"【用户问题】{case['q']}"]
    table = case.get("table")
    if table:
        parts.append(f"【已展示的表格】{table}")
    if case.get("note"):
        parts.append(f"【说明】{case['note']}")
    parts.append("【事实】" + json.dumps(case["facts"], ensure_ascii=False))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 反思
# ---------------------------------------------------------------------------

REFLECT_SYSTEM = """你是「制程问题查询助手」的执行检查员。程序按计划查完了一步，发现了需要处理的情况（信号）。下面给出用户问题、这一步的计划、结果的事实、信号，以及程序允许的下一步动作；每个动作标了程序预先查好的结果。

在允许的动作里选一个最合适的。规则：
- 只能选列出的动作，用它的编号。
- 用户明说的条件不能自己改；只有标为「默认」的条件可以放宽。
- 名字对上多个或对不上时，不猜，按追问或说明的动作处理。
- 某一部分查不出来时，其他部分照常给。
- 你不比大小、不算数。

只输出 JSON：{"action": "动作编号", "say": "给用户的一句说明，不写数字"}"""


def reflect_user(case: dict) -> str:
    lines = [
        f"【用户问题】{case['q']}",
        "【这一步的计划】" + json.dumps(case["plan"], ensure_ascii=False),
        "【结果的事实】" + json.dumps(case["facts"], ensure_ascii=False),
        "【信号】" + "；".join(case["signals"]),
        "【允许的动作】",
    ]
    for action in case["actions"]:
        lines.append(f"- {action['id']}：{action['desc']}（{action.get('result', '—')}）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 临时统计
# ---------------------------------------------------------------------------

STATS_HELPERS = '''import pandas as pd


def 拆多值(df, col, sep="、"):
    """把一单多值的列（如机型「A920、A920PRO」）拆成一值一行，其余列照抄。"""
    out = df.copy()
    out[col] = out[col].fillna("").astype(str).str.split(sep)
    out = out.explode(col)
    out[col] = out[col].str.strip()
    return out[out[col] != ""]


def 合计不良率(df, 不良列="不良数量", 分母列="生产数量"):
    """合计不良数量 ÷ 合计分母 × 100，保留 2 位小数；不良数量为空、分母为 0 或空的单不参与。
    返回 (不良率或 None, 参与张数, 不参与张数)。"""
    ok = df[df[不良列].notna() & df[分母列].notna() & (df[分母列] > 0)]
    if ok.empty:
        return None, 0, int(len(df))
    rate = round(float(ok[不良列].sum()) / float(ok[分母列].sum()) * 100, 2)
    return rate, int(len(ok)), int(len(df) - len(ok))
'''

STATS_SYSTEM = f"""你为「制程问题查询助手」写一段在沙箱里运行的 Python 统计脚本。
- 脚本必须定义 def run(data):，data["issues"] 是一个 pandas DataFrame，列见下。
- 只能 import：pandas、numpy、math、statistics、json、datetime、collections、itertools、functools、re、decimal。不能读写文件，不能联网。
- 下面这些口径函数已经定义好，直接调用即可，不要重新定义：
```python
{STATS_HELPERS}```
- 返回值必须是 dict，严格按【输出格式】的键和结构，不要多返回别的键。数字用 Python 原生的 int、float 或 None。
- 只输出代码，放在一个 ```python 代码块里。"""


def stats_user(task: dict, columns: list[tuple[str, str, str]], sample: list[dict]) -> str:
    cols = "\n".join(f"- {name}（{dtype}）：{desc}" for name, dtype, desc in columns)
    return (
        f"【数据列】\n{cols}\n"
        f"【样例行】{json.dumps(sample, ensure_ascii=False, default=str)}\n"
        f"【要算什么】{task['ask']}\n"
        f"【输出格式】{task['format']}"
    )
