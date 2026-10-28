"""规划器实测用的提示词。规划、写分析、反思、临时统计四种调用各一套。

- 业务口径的信源是 docs/2_landed：术语表、说法清单、初步分析维度在运行时从那里读，不在这里复写。
- 规划提示只拼术语表（`glossary_section`），不拼「必要澄清项」：那张表里重名、多工厂、系列对不上等
  情形要查库才知道，由程序判断，交给模型只会让它乱追问。
- 平台红线段由 `forge_platform.policy.PolicyLLM` 并进首条 system，与线上 `ctx.llm` 完全一样（见 spike.py）。
"""

from __future__ import annotations

import json
import re

from forge_core.module import AnalysisDimension, GlossaryTerm, ModuleManifest
from forge_core.prompting import analysis_section, glossary_section

from common import LANDED

# p0 → p1（2026-10-27，按 p0 实测的固定错法改）：话题范围改由程序对照话题清单判断，模型不再填；
# 加 approach（问做法时用户说的具体做法）；补结案日期、「X 各型号」、同一统计不拆步、
# 后半句沿用时间、「其他」追问的说法；写分析加「不自己合计、不设门槛、不换算单位」。
# p1 → p2（2026-10-27，开发者同意）：同一个意思只留一种写法（对象对比改成筛选加分组、时段对比写成
# compare: "时段"、ask 默认现象、没说要看什么不写 aspects、issue 一律 {value, from}）；清单加 sort / limit，
# 统计加引用 top_values；规划输入去掉「本轮可查的域」；问做法加现象按 G59 建议写；
# 按 p1 回退补「时间修饰哪件事」「条件不写进现象」「没给条件的清单不追问」「如果…就…拆两步」。
PROMPT_VERSION = "p2"

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


def load_topics() -> list[dict]:
    md = (LANDED / "topic_terms.md").read_text(encoding="utf-8")
    out = []
    for cells in _md_table(md, "## 清单"):
        if len(cells) < 4:
            continue
        terms = [t.strip().lstrip("＊*") for t in cells[2].split("、") if t.strip()]
        out.append({"name": cells[0], "desc": cells[1], "terms": terms})
    return out


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
# 规划
# ---------------------------------------------------------------------------

SKILLS = (
    "list_issues", "lookup_numbers", "issue_detail", "aggregate", "text_search",
    "custom_stats", "verify_previous", "rerender", "introduce", "clarify",
)
FILTER_FIELDS = (
    "机型", "系列", "加工厂", "国内工厂", "物料名称", "料号", "PN", "供应商", "问题类型", "问题等级", "状态",
    "跟进部门", "跟进人", "当前责任人", "责任人", "责任归属部门", "产品在制属性", "不良率", "不良数量",
    "影响数量", "发现工位", "是否设计变更", "是否需要回复8D", "IQC意见", "原因分类", "处理结果", "其他",
)
OPS = ("是", "不是", "属于", "不属于", "包含", "大于", "小于", "不小于", "不大于", "介于")
BASES = ("建单", "现场发现", "停线", "重启", "结案", "统计日期")
GROUP_DIMS = (
    "域", "问题类型", "机型", "系列", "加工厂", "国内工厂", "结案与否", "处理环节", "问题等级", "年", "季度",
    "月", "周", "跟进部门", "跟进人", "当前责任人", "责任人", "责任归属部门", "原因分类", "处理结果",
    "产品在制属性", "停线状态", "状态",
)
METRICS = ("单数", "占比", "未结案数", "合计不良率", "结案周期", "停线时长", "费用美元", "费用雷亚尔", "扣款")
TEXT_MODES = ("关键词", "话题", "类似问题", "点名字段")
TOPIC_SCOPES = ("话题本身", "比话题小", "组合说法")
SORT_FIELDS = ("建单时间", "现场发现日期", "停线日期", "结案时间", "不良率", "不良数量", "影响数量")
SORT_ORDERS = ("升序", "降序")
REF_OUTPUTS = {
    "aggregate": ("top1", "top_values", "increased", "total"),
    "list_issues": ("issues", "max_defect_rate_issue", "count"),
    "text_search": ("issues", "count"),
    "lookup_numbers": ("issues",),
    "custom_stats": (),
}

_FEW_SHOTS = [
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
]


def _join(items) -> str:
    return "、".join(items)


def planner_module_system() -> str:
    topics = "\n".join(
        f"- {t['name']}：{t['desc']}。说法：{_join(t['terms'])}" for t in load_topics()
    )
    shots = "\n\n".join(
        f"问：{q}\n答：{json.dumps(a, ensure_ascii=False)}" for q, a in _FEW_SHOTS
    )
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
- list_issues：用户要按某一项排、只要前几张时写 sort 与 limit。sort 写 {{"by": "排序项", "order": "降序"}}，by 取 {_join(SORT_FIELDS)}，order 取 升序、降序；limit 写张数。例：「不良率最高的 5 张单」写 sort {{"by": "不良率", "order": "降序"}}、limit 5。没说怎么排时不写，程序按建单时间从新到旧列。
- aggregate：
  - group_by 分组维度数组，取：{_join(GROUP_DIMS)}。按两个维度各分一次（「按类型统计，再按工厂统计」）要拆成两步，不要写在同一个 group_by 里。
  - 同一个统计只写一步：分组、排名、几个指标都写进这一步。「哪个多」「各多少」「增减怎么样」是同一个统计的不同看法，不要拆成两步。只有分组维度不同、条件不同，或「如果…就…」要先算条件再决定时才拆。
  - 「A 和 B 哪个多」「A、B 各多少」：filters 写该维 属于 [A, B]，group_by 写该维，不用写 ranking。
  - 「X 各型号」「X 各款」：机型 包含 X，按机型分组。X 是机型名时不按系列查。
  - metrics 指标数组，取：{_join(METRICS)}。只是数单数时可以不写。
  - ranking: true 用户问「哪个最多」「排名」「前几」；用户给了名次数时另写 top（「前 3」写 3）。
  - compare 只用于比较两个时段，写 "compare": "时段"，两个时段写在 time 里。
- lookup_numbers：numbers 号码数组，每项 {{"raw": "号码原样", "kind_said": "用户说的号的种类，没说就写 null"}}。不要自己判断号的种类。
- issue_detail：issue 一律写 {{"value": 单号原样或引用, "from": "user"}}；指「这单」「这张单」「它」时从上一轮取，from 写 previous。aspects 要看的内容数组，取：概况、当前状态、当前责任人、跟进人、责任人、原因、措施、完整处理过程、驳回、停线与重启、CAR、订单、其他在线订单、发货单、费用、8D、附件、问题现象、可能原因、5Why、PN、机型、物料、补料、库存处理、设计更改；都对不上时写「其他:要看的内容」。没说要看什么（「这张单帮我查一下」）时不写 aspects，程序给默认的详情。
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
- rerender：chart 取 柱状、折线、饼图、不要图。
- introduce：kind 取 寒暄、能力、只读请求、超出范围。
- clarify：reason 取 「其他」指什么、接不上上一轮、现象太泛、缺时间；question 追问的话；options 可点的选项数组。

【步骤之间的引用】
- 后一步要用前一步的结果时写 {{"ref": "s1.输出名"}}，程序执行时替换。能引用的输出：aggregate 的 top1（第一名的分组取值）、top_values（前 top 名的分组取值，没写 top 时同 top1）、increased（比较两个时段时，前一个时段是否多于后一个）、total（总数）；list_issues 的 issues（结果里的全部单）、max_defect_rate_issue（其中不良率最高的单）、count；text_search 与 lookup_numbers 的 issues。例：「问题最多的三个工厂各有哪些单」写成 s1 按加工厂统计、ranking、top 3，s2 列单，加工厂 属于 {{"ref": "s1.top_values"}}。
- 「在上面的结果里再找」写 "within": {{"ref": "s1.issues"}}。
- 只在条件成立时才做的步骤写 "when": {{"ref": "s1.increased"}}。
- 你不比大小、不算数：第一名、最高、是否增加都由程序算。

【怎么理解】
- 「制程问题」「制程单」指全部问题单，不是问题类型。点名了具体类型（工厂制程、硬件问题、物料问题等）才按问题类型筛。「物料不良」按问题类型「物料问题」。
- 只说人名：跟进人。列清单时只说「处理人」：跟进人。「当前处理人」「谁在处理」「某人手上的」「待处理的」：当前责任人。只说「责任人」「谁负责」：责任人。
- 只说部门：跟进部门。说「责任部门」「定责」「责任归属于」「责任在」：责任归属部门。
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
{topics}

【示例】
{shots}"""


def planner_system() -> str:
    return planner_module_system() + "\n\n" + glossary_section(draft_manifest())


def planner_user(case: dict, prematch: bool = False) -> str:
    # p2 起不给规划器看权限：理解与权限无关，权限由程序在规划前后施加（对照集里的 perms 只留作说明）
    # prematch：在本轮问题后面附「问句里能对上的名称与号码」（prematch.py），系统提示不变，用来比较附与不附
    lines = ["【最近几轮】"]
    history = case.get("history") or []
    if history:
        for turn in history:
            lines.append(f"用户：{turn['user']}")
            lines.append(f"助手：{turn['assistant']}")
    else:
        lines.append("（无）")
    lines.append("【上一轮计划】")
    prev = case.get("previous_plan")
    lines.append(json.dumps(prev, ensure_ascii=False) if prev else "（无）")
    # 上一轮是追问、查出 0 张或出错时，线上从工作区 last 带出这一行（设计稿 §10，G74）；查到结果时不带，
    # 所以其余问句的输入与 p2 一字不差
    if case.get("previous_outcome"):
        lines.append(f"【上一轮结局】{case['previous_outcome']}，没有查到结果")
    lines.append(f"【本轮问题】{case['q']}")
    if prematch:
        from prematch import hint_text

        hint = hint_text(case["q"])
        if hint:
            lines.append(hint)
    return "\n".join(lines)


def repair_user(errors: list[str]) -> str:
    return (
        "上面的计划不合格：\n- " + "\n- ".join(errors[:8])
        + "\n请按规定的格式重新输出完整的计划，只输出 JSON。"
    )


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
