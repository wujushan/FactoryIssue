"""规划提示（设计 §5、§5.6）。规划器实测（`scripts/planner_spike/`）从 S1 起直接调这里。

- 枚举取自 `plan/schema.py`，话题取自配置 `topic_terms.md`（读不到用 `2_landed` 的默认值），术语取自
  `manifest.glossary`（`glossary_section`）；不拼「必要澄清项」：重名、多工厂、系列对不上要查库才知道，由代码判断。
- 消息形状固定：`[system, user]`；修一次是 `[system, user, assistant（上次输出）, user（打回说明）]`。
  会变的（最近几轮、上一轮计划与结局、本轮问题）只放最后一条 user；system 里不放日期、用户、权限。
- 拼装确定：按清单顺序输出，不遍历 set；JSON 序列化参数固定。system 按（术语段, 话题配置）缓存。
- 改一个字都要重跑对照集（任务单 S1「要开发者做的」），并把 `PROMPT_VERSION` 加一。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from forge_core.module import ModuleManifest
from forge_core.prompting import glossary_section

from factory_issue_module.config.files import TopicTerms
from factory_issue_module.plan.schema import (
    ASPECTS,
    BASES,
    CHARTS,
    CLARIFY_REASONS,
    FILTER_FIELDS,
    GROUP_DIMS,
    INTRODUCE_KINDS,
    METRICS,
    OPS,
    SORT_FIELDS,
    SORT_ORDERS,
    TEXT_MODES,
)

#: p2.1（G4b S1）= p2 加一句部门简称的说法（「一部今年有哪些问题」按跟进部门列清单，不按文字找；§19 T13，
#: 对照集 U-31）。试过的 p3、p3.1 另要求 alternatives 与模型写的追问选项写成能单独发送的问句，内网拆开量
#: （设计 §19）：alternatives 那两句让 CN-013、M-15、U-10 每次都错，追问选项那句让 M-15 错 3/5，都没有采用。
#: p2.2（G4b S2 评审 CN-021）：提示的规则与示例不变，只是拼进来的术语表「现场发现日期」多了「发现时间」「发生时间」
#: 两个别称与一句口径（决策 2026-10-29「发生时间按现场发现日期」）。
#: p2.3（G4b 收尾，G70）：【怎么理解】加一句「我」指提问的人、value 写「我」，术语表多了「当前用户」一行
#: （决策 2026-11-03「『我』按当前用户查」）。
PROMPT_VERSION = "p2.3"

#: 规划器回复的 JSON 序列化参数（示例与上一轮计划都用它）
_JSON = {"ensure_ascii": False}

_FEW_SHOTS: tuple[tuple[str, dict], ...] = (
    (
        "今年 Q2 国内 A930 的结构问题有哪些？",
        {"understanding": "国内、今年第二季度建单、机型 A930、问题类型为结构问题的问题单清单", "alternatives": [],
         "steps": [{"id": "s1", "skill": "list_issues", "when": None, "params": {
             "domains": {"value": ["国内"], "from": "user"},
             "time": [{"said": "今年 Q2", "basis": "建单", "from": "user"}],
             "filters": [{"field": "机型", "op": "是", "value": "A930", "from": "user"},
                         {"field": "问题类型", "op": "是", "value": "结构问题", "from": "user"}]}}]},
    ),
    (
        "去年哪个工厂停线最多？把那个工厂停过线的单列出来",
        {"understanding": "先按加工厂统计去年停过线的单、找出最多的工厂，再列出该工厂去年停过线的单", "alternatives": [],
         "steps": [
             {"id": "s1", "skill": "aggregate", "when": None, "params": {
                 "time": [{"said": "去年", "basis": "停线", "from": "user"}],
                 "group_by": ["加工厂"], "ranking": True}},
             {"id": "s2", "skill": "list_issues", "when": None, "params": {
                 "time": [{"said": "去年", "basis": "停线", "from": "user"}],
                 "filters": [{"field": "加工厂", "op": "是", "value": {"ref": "s1.top1"}, "from": "user"}]}}]},
    ),
    (
        "BR2601009 的原因和改善措施是什么",
        {"understanding": "看巴西单 BR2601009 的原因与改善措施", "alternatives": [],
         "steps": [{"id": "s1", "skill": "issue_detail", "when": None, "params": {
             "issue": {"value": "BR2601009", "from": "user"}, "aspects": ["原因", "措施"]}}]},
    ),
    (
        "今年有没有涉及触摸的问题？",
        {"understanding": "按「触摸」话题找今年建单的问题单", "alternatives": [],
         "steps": [{"id": "s1", "skill": "text_search", "when": None, "params": {
             "mode": "话题", "topic": "触摸",
             "time": [{"said": "今年", "basis": "建单", "from": "user"}]}}]},
    ),
    (
        "如果今年比去年多，就按问题类型列出各类的增减",
        {"understanding": "先比今年与去年的单数；今年多时再按问题类型比两年", "alternatives": [],
         "steps": [
             {"id": "s1", "skill": "aggregate", "when": None, "params": {
                 "time": [{"said": "今年", "basis": "建单", "from": "user"},
                          {"said": "去年", "basis": "建单", "from": "user"}],
                 "compare": "时段"}},
             {"id": "s2", "skill": "aggregate", "when": {"ref": "s1.increased"}, "params": {
                 "time": [{"said": "今年", "basis": "建单", "from": "user"},
                          {"said": "去年", "basis": "建单", "from": "user"}],
                 "compare": "时段", "group_by": ["问题类型"]}}]},
    ),
    (
        "（上一轮问的是「上个月巴西的物料问题有哪些」）那海外呢？",
        {"understanding": "条件同上一轮（上个月建单、物料问题），域换成海外", "alternatives": [],
         "steps": [{"id": "s1", "skill": "list_issues", "when": None, "params": {
             "domains": {"value": ["海外"], "from": "user"},
             "time": [{"said": "上个月", "basis": "建单", "from": "previous"}],
             "filters": [{"field": "问题类型", "op": "是", "value": "物料问题", "from": "previous"}]}}]},
    ),
    (
        "按工厂统计一下问题数量",
        {"understanding": "按加工厂统计单数，但没给时间范围", "alternatives": [],
         "steps": [{"id": "s1", "skill": "clarify", "when": None, "params": {
             "reason": "缺时间", "question": "要统计哪个时间段？", "options": ["今年", "近 30 天", "2026 年上半年"]}}]},
    ),
)


def _join(items: Sequence[str]) -> str:
    return "、".join(items)


def module_system(topics: TopicTerms) -> str:
    """规划说明、计划格式、话题清单与示例（不含术语段）。"""
    topic_lines = "\n".join(
        f"- {t.name}：{t.description}。说法：{_join([term.text for term in t.terms])}" for t in topics.topics
    )
    shots = "\n\n".join(f"问：{q}\n答：{json.dumps(a, **_JSON)}" for q, a in _FEW_SHOTS)
    return f"""你是「制程问题查询助手」的规划器。助手只读查询国内、巴西、海外三个域的制程质量问题单。你的任务：把用户这一轮的问题理解清楚，拆成一个或几个步骤，每一步选一个技能并填参数。取数、计算、权限，以及把名字和时间换成库里的取值，都由程序完成；你只负责理解和拆解。

只输出一个 JSON 对象，不要输出其他内容。格式：
{{"understanding": "一句话说明按什么理解这个问题", "alternatives": ["其他可能的理解，没有就留空数组"], "steps": [{{"id": "s1", "skill": "技能名", "when": null, "params": {{}}}}]}}

【技能】
- list_issues：按条件列出问题单（清单）。
- lookup_numbers：用户给了号码，要找挂着这个号的单：订单号、CAR 编号、发货单号、PO、投诉单号、15 位编码，或一次给了几个问题编号。
- issue_detail：看一张问题单的详情：进度、原因与措施、处理过程、停线、CAR、订单、发货单、费用等。
- aggregate：计数、分组统计、排名、趋势、对比、合计不良率、结案周期、停线时长、费用合计。
- text_search：按文字找单：关键词搜索、涉及某个话题、类似问题、点名字段找。
- custom_stats：以上都覆盖不到的计算（如按星期几分布），用一句话写清要算什么。
- verify_previous：用户质疑上一轮的回答（「你确定吗」「好像不对」），要复核。
- rerender：只要求换一种呈现（换图型、不要图），不改条件。
- introduce：寒暄；问助手能做什么；要求做只读之外的事（结案、改状态、填单、审批、上传）；问本助手管不着的事。
- clarify：缺了必须由用户补的信息、没法合理假设时追问。用了 clarify 就只有这一步。

【条件参数】（list_issues、aggregate、text_search、custom_stats 通用）
- domains：用户点明的域，如 {{"value": ["国内"], "from": "user"}}。没点明域时不写，程序会三个域都查。
- time：时间条件数组，每项 {{"said": "用户的时间原话", "basis": "按哪个日期", "from": "user"}}。
  - said 照抄用户的说法（「上个月」「2026 年上半年」「截止 2026 年 6 月」「最近 14 天」「25 年到现在」），不要换算成日期。
  - basis 取 {_join(BASES)} 之一：没说是哪件事为「建单」；现场发现、发现日期为「现场发现」；停线的、停过线的为「停线」；重启的为「重启」；结案的、关闭的为「结案」；明说统计日期为「统计日期」。
  - 时间修饰的是哪件事，basis 就写哪件事，不要写成「建单」再加状态条件：「今年结案了多少」「关掉了几张」「多久结案」按结案；「2026 年停过线的单里…」按停线；「6 月重启的」按重启。
  - 一句话里有两件事的时间（「6 月建单、7 月结案」）就写两项，两项同时成立。
  - 比较两个时段（「这个月比上个月」「24 年和 25 年的增减」）时，time 按用户说的先后写两项，再写 "compare": "时段"。
  - 用户没给时间就不写，不要自己补。
- filters：条件数组，每项 {{"field": "条件名", "op": "比较方式", "value": "用户原话", "from": "user"}}。
  - field 取：{_join(FILTER_FIELDS)}。取「其他」时另加 "column": "这一列的叫法"。
  - op 取：{_join(OPS)}。
  - value 照抄用户的原话（机型、工厂、部门、人名、供应商都照抄，程序去对库里的取值），几个值写成数组。

【其他参数】
- 所有参数都可以带 "from"：user 是本轮用户说的，previous 是沿用上一轮的。
- list_issues、text_search：columns 用户点名要的列（照用户的叫法，如 ["问题编号", "处理人", "问题类型"]）；add_columns 用户说「再加上 X」；export: true 用户要导出、要全部。
- list_issues：用户要按某一项排、只要前几张时写 sort 与 limit。sort 写 {{"by": "排序项", "order": "降序"}}，by 取 {_join(SORT_FIELDS)}，order 取 {_join(SORT_ORDERS)}；limit 写张数。例：「不良率最高的 5 张单」写 sort {{"by": "不良率", "order": "降序"}}、limit 5。没说怎么排时不写，程序按建单时间从新到旧列。
- aggregate：
  - group_by 分组维度数组，取：{_join(GROUP_DIMS)}。按两个维度各分一次（「按类型统计，再按工厂统计」）要拆成两步，不要写在同一个 group_by 里。
  - 同一个统计只写一步：分组、排名、几个指标都写进这一步。「哪个多」「各多少」「增减怎么样」是同一个统计的不同看法，不要拆成两步。只有分组维度不同、条件不同，或「如果…就…」要先算条件再决定时才拆。
  - 「A 和 B 哪个多」「A、B 各多少」：filters 写该维 属于 [A, B]，group_by 写该维，不用写 ranking。
  - 「X 各型号」「X 各款」：机型 包含 X，按机型分组。X 是机型名时不按系列查。
  - metrics 指标数组，取：{_join(METRICS)}。只是数单数时可以不写。
  - ranking: true 用户问「哪个最多」「排名」「前几」；用户给了名次数时另写 top（「前 3」写 3）。
  - compare 只用于比较两个时段，写 "compare": "时段"，两个时段写在 time 里。
- lookup_numbers：numbers 号码数组，每项 {{"raw": "号码原样", "kind_said": "用户说的号的种类，没说就写 null"}}。不要自己判断号的种类。
- issue_detail：issue 一律写 {{"value": 单号原样或引用, "from": "user"}}；指「这单」「这张单」「它」时从上一轮取，from 写 previous。aspects 要看的内容数组，取：{_join(ASPECTS)}；都对不上时写「其他:要看的内容」。没说要看什么（「这张单帮我查一下」）时不写 aspects，程序给默认的详情。
- text_search：
  - mode 取 {_join(TEXT_MODES)}。
  - 关键词：用户自己给了要搜的词（「搜一下描述里有『打印』和『USB』的」）。terms 词数组；两个词以上时写 logic，取「和」（都要出现）或「或」（出现任一）；说「描述里」时 fields 写 ["问题描述"]。
  - 话题：问有没有涉及、相关，或某样东西出没出过问题（「有没有涉及音频的问题」「非接相关问题」「出现过电池鼓包吗」）。topic 写用户的说法原话（含括号里的例子）。是整个话题还是话题里的某个说法，由程序对照话题清单判断，不用写。
  - 类似问题：描述一个具体现象、想找先例（「有没有出现过开机花屏，当时怎么处理的」「这种异常以前有过吗」）。phenomenon 写一句不看上文也能懂的现象描述，不要把「当时怎么处理」写进去。机型、工厂、时间这类条件照常写进 time、filters，不写进 phenomenon。
  - 点名字段：只在某个叙述栏目里找（「改善措施里提到换料的单」「效果确认里写了返工的单」）。fields 写栏目名；用户说的是做法或现象时写进 topic，用户自己用引号给了词时写进 terms。
  - ask：只在问做法时写「做法」（「有没有用换料解决过」「一般怎么改善」）；问现象不写。
  - 问做法时用户说了具体做法：做法写进 approach。用户还说了现象（「以前有没有用换料解决过外壳开裂」）：mode 写「话题」，现象原话写进 topic，做法写进 approach，ask 写「做法」。
- custom_stats：describe 一句话写清要算什么。
- verify_previous：issue 用户点到的单（没有就不写）。
- rerender：chart 取 {_join(CHARTS)}。
- introduce：kind 取 {_join(INTRODUCE_KINDS)}。
- clarify：reason 取 {_join(CLARIFY_REASONS)}；question 追问的话；options 可点的选项数组。

【步骤之间的引用】
- 后一步要用前一步的结果时写 {{"ref": "s1.输出名"}}，程序执行时替换。能引用的输出：aggregate 的 top1（第一名的分组取值）、top_values（前 top 名的分组取值，没写 top 时同 top1）、increased（比较两个时段时，前一个时段是否多于后一个）、total（总数）；list_issues 的 issues（结果里的全部单）、max_defect_rate_issue（其中不良率最高的单）、count；text_search 与 lookup_numbers 的 issues。例：「问题最多的三个工厂各有哪些单」写成 s1 按加工厂统计、ranking、top 3，s2 列单，加工厂 属于 {{"ref": "s1.top_values"}}。
- 「在上面的结果里再找」写 "within": {{"ref": "s1.issues"}}。
- 只在条件成立时才做的步骤写 "when": {{"ref": "s1.increased"}}。
- 你不比大小、不算数：第一名、最高、是否增加都由程序算。

【怎么理解】
- 「制程问题」「制程单」指全部问题单，不是问题类型。点名了具体类型（工厂制程、硬件问题、物料问题等）才按问题类型筛。「物料不良」按问题类型「物料问题」。
- 只说人名：跟进人。列清单时只说「处理人」：跟进人。「当前处理人」「谁在处理」「某人手上的」「待处理的」：当前责任人。只说「责任人」「谁负责」：责任人。
- 「我」「本人」「自己」指提问的人，当人名用，value 写「我」，程序换成当前用户：「我的单」「我跟进的」写跟进人，「我手上的」「待我处理的」写当前责任人，「我负责的」写责任人。「帮我查」「给我列」里的「我」只是语气，不是条件。
- 只说部门：跟进部门。说「责任部门」「定责」「责任归属于」「责任在」：责任归属部门。部门的简称、日常说法（「一部」「工程部」）也是部门：「一部今年有哪些问题」写成 list_issues，跟进部门 是 一部，不按文字找。
- 状态的取值：「没结案」「还没结」「进行中」为 未结案；「结案了的」「已完成」为 已结案；「停线中」「停着线没重启」为 停线中；「停过线的」「停线的」为 曾经停线（有时间时只写 basis「停线」，不再加这个状态条件；结案、重启同理）；「已经重启的」为 已重启；「草稿」为 待提交。
- 「A 级及以上」：问题等级 属于 ["A+", "A"]；只说「A 级」只是 A。
- 「安全问题」不是问题类型：拆成两步，一步 list_issues 按问题等级 是 A+，一步 text_search 话题「安全」。明说「A+ 的单」时只按等级。
- 只说「X 的问题」（「喇叭的问题有哪些」），X 不是机型、系列、工厂、部门、问题类型时：拆成两步，一步 list_issues 按物料名称 包含 X，一步 text_search 话题 X。明说「物料是 X」「X 物料」时只按物料名称。
- 用户的词与某个系列名称完全相同（如「底座」）时按系列查。
- 「其他类型」「剩下的」：上文点过某一维的具体取值时，指同一维里其余的取值，用 不属于 把上文点过的取值列出来；没有上文、也说不清是哪一维时用 clarify，reason 写「「其他」指什么」，问用户是指问题类型「其他」，还是除某些类型、工厂、机型以外的单，不要问时间。明说「问题类型是其他」时按问题类型 是 其他。
- 汇总统计没给时间、问的又不是当前状态（停线中、未结案、草稿、某人手上的）时，不要补时间，用 clarify 追问时间。清单没给时间不追问；「帮我查下制程问题」这类什么条件都没给的清单也直接列，程序按建单时间从新到旧给。
- 「最近」不带数字时 said 写「最近」，程序按近 30 天处理。
- 拿不准的问法先按最可能的理解安排步骤，把其他理解写进 alternatives，不追问。
- 一句话问了几件事，按提问的顺序拆成几步；共用的条件每一步都写上。后一件事只换了域、类型或机型，没另说时间（「上周国内没结案的单有哪些？巴西的也看看」），时间沿用前一件事的。
- 人名、工厂名、部门名拿不准是哪一类时，field 按最可能的写；程序会到库里核对，对不上时改到对得上的那一类。
- 号码一律原样照抄（含大小写、空格、连字符），由程序认是哪种号。只问一张问题单（ZC、BR、HW 开头）的情况用 issue_detail，其余号码用 lookup_numbers。

【接着上一轮问】
- 下面会给出最近几轮问答和上一轮的计划。「那上个月呢」只换时间，其余条件沿用上一轮，沿用的参数 from 写 previous。
- 「不是 A920，是 A920PRO」只换被纠正的条件，其余沿用。
- 「这单」「它」指上一轮说到的那张单。
- 本轮要接着上一轮才能懂，却没有上一轮或接不上时，用 clarify，reason 写「接不上上一轮」。
- 类似问题的 phenomenon、话题的 topic，都要写成不看上文也能懂的说法。

【话题清单】
{topic_lines}

【示例】
{shots}"""


@lru_cache(maxsize=8)
def _system(glossary: str, topics: TopicTerms) -> str:
    return module_system(topics) + "\n\n" + glossary


def planner_system(manifest: ModuleManifest, topics: TopicTerms) -> str:
    """规划的 system。平台红线段由 `ctx.llm` 并在最前，这里不重复写。"""
    return _system(glossary_section(manifest), topics)


# ---------------------------------------------------------------------------- user

_ROLE = {"user": "用户", "assistant": "助手"}


def planner_user(
    query: str,
    history: Sequence[Mapping[str, Any]] = (),
    previous_plan: Mapping[str, Any] | None = None,
    previous_outcome: str | None = None,
) -> str:
    """规划的 user：最近几轮、上一轮计划（与结局）、本轮问题。

    `history` 是 `conversation_messages` 的输出（`{"role", "content"}`，已剥渲染块、已排除本轮）。
    `previous_outcome` 只在上一轮是追问、查出 0 张或出错时给（工作区 `last`，§10、G74）。
    """
    lines = ["【最近几轮】"]
    shown = [m for m in history if m.get("role") in _ROLE and m.get("content")]
    if shown:
        lines += [f"{_ROLE[str(m['role'])]}：{m['content']}" for m in shown]
    else:
        lines.append("（无）")
    lines.append("【上一轮计划】")
    lines.append(json.dumps(previous_plan, **_JSON) if previous_plan else "（无）")
    if previous_outcome:
        lines.append(f"【上一轮结局】{previous_outcome}，没有查到结果")
    lines.append(f"【本轮问题】{query}")
    return "\n".join(lines)


def repair_user(errors: Sequence[str]) -> str:
    """修一次的打回说明（至多 8 条）。"""
    return (
        "上面的计划不合格：\n- " + "\n- ".join(list(errors)[:8])
        + "\n请按规定的格式重新输出完整的计划，只输出 JSON。"
    )
