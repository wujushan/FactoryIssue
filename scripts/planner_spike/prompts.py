"""规划器实测用的提示词。规划、写分析、反思、临时统计四种调用各一套。

- 业务口径的信源是 docs/2_landed：术语表、说法清单、初步分析维度由 src 在导入时从那里读，这里不复写。
- 规划提示 S1 起由 `src/factory_issue_module/plan/prompt.py` 持有（设计 §1.3 末条），这里只转接；
  写分析 S2 起同样由 `src/factory_issue_module/present/narrative.py` 持有；反思、临时统计两套仍在这里，随 S7 迁到 src。
- 规划提示只拼术语表（`glossary_section`），不拼「必要澄清项」：那张表里重名、多工厂、系列对不上等
  情形要查库才知道，由程序判断，交给模型只会让它乱追问。
- 平台红线段由 `forge_platform.policy.PolicyLLM` 并进首条 system，与线上 `ctx.llm` 完全一样（见 spike.py）。
"""

from __future__ import annotations

import json
import re


from factory_issue_module.config import files as _config_files
from factory_issue_module.declarations import TOPIC_TERMS
from factory_issue_module.module import FactoryIssueModule
from factory_issue_module.plan import prompt as _plan_prompt
from factory_issue_module.present import narrative as _narrative
from factory_issue_module.skills import custom_stats as _custom
from factory_issue_module.plan.schema import (  # noqa: F401  scoring 从这里取枚举
    BASES, FILTER_FIELDS, GROUP_DIMS, METRICS, OPS, REF_OUTPUTS, SKILLS, SORT_FIELDS, SORT_ORDERS, TEXT_MODES,
)


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


def repair_user(errors: list[str], verify: list[str] | tuple[str, ...] = ()) -> str:
    return _plan_prompt.repair_user(errors, verify)


# ---------------------------------------------------------------------------
# 写分析
# ---------------------------------------------------------------------------

# 写分析的提示 S2 起由 src 持有（`factory_issue_module.present.narrative`，设计 §8.3），这里只转接；
# system 与迁移前 spike 自己拼的逐字相同（迁移时核对过）。
NARRATIVE_MODULE_SYSTEM = _narrative.NARRATIVE_MODULE_SYSTEM


def narrative_system() -> str:
    return _narrative.narrative_system(FactoryIssueModule.manifest)


def narrative_user(case: dict) -> str:
    return _narrative.narrative_user(case["q"], case.get("table"), case.get("note"), case["facts"])


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

# 临时统计的提示 S7 起由 src 持有（`factory_issue_module.skills.custom_stats`，设计 §5.5），这里只转接。
# 迁移时先逐字搬（system、口径函数与 10 题的 user 与迁移前逐字相同、自检通过），再改成 §5.5 的固定形状：
# 口径函数改为 `stats/lib/custom.py` 里的真函数（提示里只给签名与说明），列说明改由线上同一个函数从术语表生成。
STATS_SYSTEM = _custom.stats_system()
stats_user = _custom.stats_user
stats_repair = _custom.repair_user
