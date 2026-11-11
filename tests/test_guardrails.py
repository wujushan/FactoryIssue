"""护栏测试（设计 §15）：单测照样能过、却会直接变成用户看到的东西的几类错，单独查。每片都跑。

- 不露字段名：每条用户可见的路径用假 `ctx` 跑一遍，正文、表头、图表、按钮、错误话术里不含
  `db_description` 的物理表名、列名、JSON 键名与数据源别名。按英文词边界匹配；显示名里本来就有的
  （CAR、PN、PO）不算；链接地址里的参数不算。
- 不直算：AST 检查 `src`，`stats/lib/`、`stats/tasks/`、`jobs/` 之外没有聚合类的属性调用；除
  `stats/runner.py` 外不 import `stats.lib`、`stats.tasks`。内建的 `len`、`max`、`sorted`、`sum`
  查不出来，列在任务单每片的评审清单里。
- 取数写法：`src` 里没有 `ctx.data.query(` 与 `ctx.data.raw(`（`jobs/` 经 `ctx.etl`，不在此列）。
- 按钮形状：`suggestions` 与 `clarify` 的每个选项都是带 id、name、label、query 的对象，label 不超过 30 字、不以省略号结尾；
  答后按钮的 query 不是「原话（这一项）」（INFO 网页前端把 query 当按钮文字显示，设计 §19）。
- 只有一条 system 且在最前：假模型每次调用都查（`fakes.FakeLLM.check_messages`），这里再兜一遍。

- 巴西链接用的两项值（§9.1）的片段不进日志、不进事件，出错时日志只有异常类型（S3 起；附件摘要的盐值随 S4）。
  站点地址来自模块配置 `link_sites.toml`，不是凭据。
- 临时统计（S7）：模型起的列名、图表轴同样过「不露字段名」；英文列名在运行时被形状检查拦下、修一次（`S7_SCENARIOS`）。
  包装脚本与口径函数在 `stats/` 下，`handle()` 一侧不算数，上面「不直算」那条照查 `skills/custom_stats.py`、`stats/custom.py`。
- AI 润色（润色设计 §12.1）：一次过、修一次、两次都不过、模型出错、5Why 的答、原文为空、太长、参数有误各走一遍
  （`POLISH_SCENARIOS`），同样查不露表名字段名、只有一条 system。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import s3_data
import s4_data
import s6_data
import scopes
import structlog
from fakes import MANIFEST, FakeLLM, Harness, make_harness, run
from forge_core.events import Event, EventType
from forge_core.module import ModuleRequest

from factory_issue_module import landed, polish
from factory_issue_module.declarations import DOMAINS, ERP, INFO, MART, Domain
from factory_issue_module.skills import custom_stats
from factory_issue_module.turn import gate, greeting

SRC = Path(__file__).resolve().parents[1] / "src" / "factory_issue_module"

# ---------------------------------------------------------------- 跑一遍每条用户可见的路径

#: （说明, 权限, 问句）。每片把新接上的技能加进来。
SCENARIOS: list[tuple[str, dict | None, str]] = [
    ("三域都无权·问数据", scopes.no_domain(), "帮我查下制程问题"),
    ("三域都无权·寒暄", scopes.no_domain(), "你好，你能帮我查什么？"),
    ("没拿到权限", None, "你好"),
    ("三域都无权·空问句", scopes.no_domain(), "？？？"),
    ("只国内·空问句", scopes.account_jia(), "……"),
    ("只国内·规划层接上之前", scopes.account_jia(), "上个月国内的问题有哪些"),
    ("全放开·规划层接上之前", scopes.GREEN, "6 月总共发生多少制程问题？"),
    ("对话框里说润色", scopes.account_jia(), "帮我润色这段原因分析：治具松动"),
    ("三域都无权·说润色", scopes.no_domain(), "帮我润色一下"),
]


_CN = {"value": ["国内"], "from": "user"}
_T30 = [{"said": "近 30 天", "basis": "建单", "from": "user"}]
_NARR = "共 4 张，硬件问题最多。最需要关注的是 ZC9901001。"
_SITES = 'issue = "info.test.local"'


def _plan(skill: str, **params) -> dict:
    return {"understanding": "x", "alternatives": [],
            "steps": [{"id": "s1", "skill": skill, "when": None, "params": params}]}


#: S2 起接上的技能：（说明, 权限, 问句, 模型回复）。用国内假数据（`tests/cn_data.py`）跑。
EXEC_SCENARIOS: list[tuple[str, dict, str, list]] = [
    ("国内清单", scopes.account_jia(), "近 30 天国内的问题有哪些", [_plan("list_issues", domains=_CN, time=_T30), _NARR]),
    ("国内清单·点名列", scopes.account_jia(), "列出近 30 天国内的单号、处理人、当前状态、责任人、结案时间、手机号",
     [_plan("list_issues", domains=_CN, time=_T30, columns=["单号", "处理人", "当前状态", "责任人", "结案时间", "手机号"]),
      _NARR]),
    ("国内按类型统计", scopes.account_jia(), "近 30 天国内按问题类型统计",
     [_plan("aggregate", domains=_CN, time=_T30, group_by=["问题类型"], metrics=["单数", "占比"]), _NARR]),
    ("国内按工厂与责任部门", scopes.account_jia(), "近 30 天国内按工厂、责任部门统计",
     [_plan("aggregate", domains=_CN, time=_T30, group_by=["加工厂", "责任归属部门"]), _NARR, _NARR]),
    ("国内概况", scopes.account_jia(), "近 30 天国内平均多久结案、停了多久",
     [_plan("aggregate", domains=_CN, time=_T30, metrics=["结案周期", "停线时长", "合计不良率"]), _NARR]),
    ("全放开·不点域", scopes.GREEN, "近 30 天的问题有哪些", [_plan("list_issues", time=_T30), _NARR]),
    ("国内·机型对不上", scopes.account_jia(), "国内 Z999 的问题",
     [_plan("list_issues", domains=_CN, filters=[{"field": "机型", "op": "是", "value": "Z999", "from": "user"}])]),
    # S3：巴西、海外与跨域合并（三域假数据 `tests/s3_data.py`）
    ("巴西清单·点名列", scopes.GREEN, "近 30 天巴西的单号、投诉单号、加工厂、跟进人、当前状态、当前责任人、PN",
     [_plan("list_issues", domains={"value": ["巴西"], "from": "user"}, time=_T30,
            columns=["单号", "投诉单号", "加工厂", "跟进人", "当前状态", "当前责任人", "PN"]), _NARR]),
    ("海外清单·点名列", scopes.GREEN, "近 30 天海外的单号、物料、国内工厂、当前责任人、责任人",
     [_plan("list_issues", domains={"value": ["海外"], "from": "user"}, time=_T30,
            columns=["单号", "物料", "国内工厂", "当前责任人", "责任人"]), _NARR]),
    ("巴西费用", scopes.GREEN, "近 30 天巴西花了多少美元、雷亚尔，扣款多少",
     [_plan("aggregate", domains={"value": ["巴西"], "from": "user"}, time=_T30,
            metrics=["费用美元", "费用雷亚尔", "扣款"]), _NARR]),
    ("三域按类型", scopes.GREEN, "近 30 天按问题类型统计",
     [_plan("aggregate", time=_T30, group_by=["问题类型"], metrics=["单数", "占比"]), _NARR]),
    ("三域概况·不良率", scopes.GREEN, "近 30 天三个域多少单、不良率多少、多久结案",
     [_plan("aggregate", time=_T30, metrics=["合计不良率", "结案周期"]), _NARR]),
    ("三域按状态", scopes.GREEN, "近 30 天各状态多少单",
     [_plan("aggregate", time=_T30, group_by=["状态"]), _NARR]),
    ("三域对比时段", scopes.GREEN, "近 30 天与去年对比",
     [_plan("aggregate", compare="时段", group_by=["问题类型"],
            time=[{"said": "去年", "basis": "建单", "from": "user"}, {"said": "近 30 天", "basis": "建单",
                                                                    "from": "user"}]), _NARR]),
    ("三域·伊朗工厂", scopes.GREEN, "伊朗工厂的问题有哪些？",
     [_plan("list_issues", filters=[{"field": "加工厂", "op": "是", "value": "伊朗工厂", "from": "user"}])]),
]


def _detail(number: str, *aspects: str) -> dict:
    params: dict = {"issue": {"value": number, "from": "user"}}
    if aspects:
        params["aspects"] = list(aspects)
    return _plan("issue_detail", **params)


#: S4 接上的详情与按号查单（假数据 `tests/s4_data.py`）：（说明, 权限, 问句, 模型回复）；回复为空表示号码直通
S4_SCENARIOS: list[tuple[str, dict, str, list]] = [
    ("国内详情·整张", scopes.GREEN, "ZC9901001", []),
    ("国内详情·各项", scopes.GREEN, "ZC9901006 的处理过程、5Why、原因、责任人、设计更改、附件、订单",
     [_detail("ZC9901006", "完整处理过程", "驳回", "5Why", "原因", "责任人", "设计更改", "附件", "订单", "费用",
              "其他:手机号")]),
    ("国内详情·重启审核中", scopes.GREEN, "ZC9901005 停线", [_detail("ZC9901005", "停线与重启", "完整处理过程")]),
    ("国内详情·物料单与 CAR", scopes.account_jia(), "ZC9901002 的 CAR 和订单",
     [_detail("ZC9901002", "CAR", "订单", "其他在线订单", "机型", "物料", "PN", "原因")]),
    ("国内详情·有 CAR 权限", scopes.privileges([Domain.DOMESTIC], car=True), "ZC9901002", []),
    ("巴西详情·整张", scopes.GREEN, "BR9901001", []),
    ("巴西详情·各项", scopes.GREEN, "BR9901001 的费用、8D、补料、库存处理、5Why、PN、处理过程",
     [_detail("BR9901001", "费用", "8D", "补料", "库存处理", "5Why", "PN", "完整处理过程", "当前责任人", "订单")]),
    ("海外详情·整张", scopes.GREEN, "HW9901002", []),
    ("海外详情·各项", scopes.GREEN, "HW9901001 的现象、原因、处理过程、附件",
     [_detail("HW9901001", "问题现象", "可能原因", "原因", "完整处理过程", "附件", "责任人", "费用", "设计更改")]),
    ("按号·15 位", scopes.GREEN, "999999999999999", []),
    ("按号·订单", scopes.GREEN, "订单 990001 关联了哪些单", [_plan("lookup_numbers", numbers=[
        {"raw": "990001", "kind_said": "订单号"}, {"raw": "2406648", "kind_said": None},
        {"raw": "CLAIM-0099/99", "kind_said": None}, {"raw": "AB9900001", "kind_said": None}])]),
    ("按号·CAR 无报告权限", scopes.account_jia(), "CAR999999999", []),
    ("按号·几个问题编号", scopes.account_jia(), "ZC9901001、BR9901002、ZC9909999", []),
    ("按号·认不出", scopes.GREEN, "202501011234 是什么单", [_plan("lookup_numbers", numbers=[
        {"raw": "202501011234", "kind_said": None}])]),
]


_LIST30 = _plan("list_issues", time=_T30)
_ODD_TYPE = [{"field": "问题类型", "op": "是", "value": "外观问题", "from": "user"}]

#: S5 接上的多轮与交互：（说明, 权限, 假数据, [(问句, 模型回复)…]）；问句为 None 表示点上一轮第一个按钮
S5_SCENARIOS: list[tuple[str, dict, object, list[tuple[str | None, list]]]] = [
    ("质疑重查·有变化", scopes.GREEN, s3_data,
     [("近 30 天的问题有哪些", [_LIST30, _NARR]), ("你确定吗", [_plan("verify_previous")])]),
    ("质疑重查·详情", scopes.GREEN, s4_data, [("ZC9901001", []), ("好像不对吧", [_plan("verify_previous")])]),
    ("质疑重查·没有上一轮", scopes.GREEN, s3_data, [("你确定吗", [_plan("verify_previous")])]),
    ("换图·存下的图", scopes.GREEN, s3_data,
     [("近 30 天按问题类型统计", [_plan("aggregate", time=_T30, group_by=["问题类型"]), _NARR]),
      ("换成饼图", [_plan("rerender", chart="饼图")])]),
    ("换图·清单", scopes.GREEN, s3_data, [("近 30 天的问题有哪些", [_LIST30, _NARR]),
                                       ("换成柱状图", [_plan("rerender", chart="柱状")])]),
    ("导出·三域", scopes.GREEN, s3_data, [("把近 30 天的问题全部导出", [_plan("list_issues", time=_T30, export=True),
                                                                   _NARR])]),
    ("直填·类型", scopes.account_jia(), s3_data,
     [("近 30 天国内外观问题", [_plan("list_issues", domains=_CN, time=_T30, filters=_ODD_TYPE)]), (None, [_NARR])]),
    ("沿用·那今年呢", scopes.account_jia(), s3_data,
     [("近 30 天国内的问题有哪些", [_plan("list_issues", domains=_CN, time=_T30), _NARR]),
      ("那今年呢", [_plan("list_issues", domains={"value": ["国内"], "from": "previous"},
                         time=[{"said": "今年", "basis": "建单", "from": "user"}]), _NARR])]),
    ("本月比上月", scopes.account_jia(), s3_data,
     [("国内这个月比上个月多了吗", [_plan("aggregate", domains=_CN, compare="时段", time=[
         {"said": "这个月", "basis": "建单", "from": "user"}, {"said": "上个月", "basis": "建单", "from": "user"}]),
         _NARR])]),
    # S7：临时统计之后质疑、换图（照存下的脚本重算、重画；脚本按 `_custom_route` 给）
    ("临时统计·质疑与换图", scopes.GREEN, s3_data,
     [("近 30 天的问题按星期几分布看看", [_plan("custom_stats", time=_T30, describe="按星期几统计单数"), _NARR]),
      ("你确定吗", [_plan("verify_previous")]), ("换成饼图", [_plan("rerender", chart="饼图")])]),
]

# ---------------------------------------------------------------- S7 临时统计

_WEEKDAY = ('```python\ndef run(data):\n    df = data["issues"]\n    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]\n'
            '    counts = df["建单时间"].dt.dayofweek.value_counts()\n'
            '    rows = [[names[i], int(counts.get(i, 0))] for i in range(7)]\n'
            '    return {"columns": ["星期", "单数"], "rows": rows, "chart": {"type": "bar", "x": "星期", "series": ["单数"]}}\n```')
#: 模型起了英文列名：形状检查拦下、修一次（护栏「不露字段名」在运行时这一关）
_ENGLISH = ('```python\ndef run(data):\n    return {"columns": ["weekday", "ProblemType"], "rows": [["Mon", 1], ["Tue", 2]],'
            ' "chart": {"type": "bar", "x": "weekday", "series": ["ProblemType"]}}\n```')
_RATES = ('```python\ndef run(data):\n    df = data["issues"]\n    rows = []\n    for dom in ["国内", "巴西"]:\n'
          '        rate, ok, _ = 合计不良率(df[df["所属域"] == dom])\n        rows.append([dom, rate, ok])\n'
          '    return {"columns": ["所属域", "合计不良率（%）", "参与张数"], "rows": rows,'
          ' "chart": {"type": "bar", "x": "所属域", "series": ["合计不良率（%）"]}}\n```')
_TOO_MANY = ('```python\ndef run(data):\n    return {"columns": ["序号", "单数"], "rows": [[i, 1] for i in range(80)],'
             ' "chart": {"type": "none"}}\n```')
_CUSTOM = _plan("custom_stats", time=_T30, describe="按星期几统计单数")


def _custom_route(*replies: str):
    queue = list(replies)
    return lambda _m: queue.pop(0) if len(queue) > 1 else queue[0]


#: （说明, 权限, 问句, 规划与分析的回放, 脚本的回放, 模块配置）
S7_SCENARIOS: list[tuple[str, dict, str, list, list[str], dict]] = [
    ("临时统计·三域", scopes.GREEN, "近 30 天的问题按星期几分布看看", [_CUSTOM, _NARR], [_WEEKDAY], {}),
    ("临时统计·英文列名修一次", scopes.GREEN, "近 30 天的问题按星期几分布看看", [_CUSTOM, _NARR], [_ENGLISH, _WEEKDAY], {}),
    ("临时统计·海外不良率", scopes.GREEN, "近 30 天各域的合计不良率",
     [_plan("custom_stats", time=_T30, describe="各域的合计不良率")], [_RATES], {}),
    ("临时统计·没算出来", scopes.GREEN, "近 30 天每张单编个号", [_CUSTOM], [_TOO_MANY], {}),
    ("临时统计·关掉", scopes.account_jia(), "近 30 天国内按星期几分布看看",
     [_plan("custom_stats", domains=_CN, time=_T30, describe="按星期几统计单数")], [],
     {"answer_params.toml": "custom_stats_enabled = false"}),
]


def _judge_all(messages: list[dict]) -> dict:
    return {"results": [{"no": c["no"], "related": True} for c in json.loads(messages[-1]["content"])["候选"]]}


def _summary_all(messages: list[dict]) -> dict:
    return {"items": [{"no": x["no"], "summary": "触摸屏偶发失灵"} for x in json.loads(messages[-1]["content"])]}


#: 文字查找三种模型调用按 system 认（`fakes.FakeLLM.routes`）
_S6_ROUTES = {"是否与用户要找的话题有关": _judge_all, "与用户描述的问题现象是不是同一类问题": _judge_all,
              "浓缩成一两句话": _summary_all,
              "定按文字找单时用哪些说法": lambda m: {"terms": ["TP"]}}
_S6_LONG = {1: {"desc": "客户现场反馈 A920 在批量 300 台中有 12 台开机后触摸屏偶发失灵，点击图标无反应，重启后恢复，影响出货",
                "reason": "TP 排线压伤"},
            2: {"desc": "外壳开裂，扣位断裂", "measure": "换料后正常，顺带更换排线"}, 3: {"desc": "电池起火冒烟"},
            4: {"desc": "", "measure": "NFC天线换料"}}
_HITS = [[s6_data.hit(2, "desc", "问题描述：外壳开裂，扣位断裂"), s6_data.hit(4, "measure", "改善措施：NFC天线换料")]]


def _ts(**params) -> dict:
    return _plan("text_search", **params)


#: S6b 接上的文字查找、摘要与导出（假数据 `tests/s6_data.py`）：（说明, 权限, 问句, 模型回复, 按意思找的命中；None 表示
#: 没有 `ctx.retrieval`）
S6_SCENARIOS: list[tuple[str, dict, str, list, list | None]] = [
    ("话题·两组加可能相关", scopes.account_jia(), "国内近 30 天有没有涉及触摸的问题",
     [_ts(domains=_CN, time=_T30, mode="话题", topic="触摸")], _HITS),
    ("安全问题两路", scopes.account_jia(), "近 30 天国内有没有安全问题", [_ts(domains=_CN, time=_T30, mode="话题", topic="安全")],
     []),
    ("关键词·点名栏目", scopes.account_jia(), "国内重启方案里写了换电池的单",
     [_ts(domains=_CN, mode="点名字段", fields=["重启方案"], terms=["换电池"])], []),
    ("点名字段·可能相关", scopes.account_jia(), "国内改善措施里提到换料的单",
     [_ts(domains=_CN, mode="点名字段", fields=["改善措施"], topic="换料")], _HITS),
    ("类似问题·只国内有权", scopes.account_jia(), "以前有没有出现过电池起火冒烟",
     [_ts(mode="类似问题", phenomenon="电池起火冒烟")], [[s6_data.hit(3, "desc", "问题描述：电池起火冒烟")]]),
    ("做法加现象·两个按钮", scopes.account_jia(), "国内近 30 天有没有用换料解决过电池起火",
     [_ts(domains=_CN, time=_T30, mode="话题", topic="电池起火", approach="换料", ask="做法")], []),
    ("比话题小·按整个话题找", scopes.account_jia(), "国内近 30 天有没有 TP 排线的问题",
     [_ts(domains=_CN, time=_T30, mode="话题", topic="TP 排线")], []),
    ("清单外·只看问题本身涉及的", scopes.account_jia(), "国内近 30 天有没有涉及排线的问题",
     [_ts(domains=_CN, time=_T30, mode="话题", topic="排线")], []),
    ("文字查找表无权", scopes.privileges([Domain.DOMESTIC], mart=False), "搜一下国内描述里有起火的单",
     [_ts(domains=_CN, mode="关键词", terms=["起火"])], []),
    ("按意思找用不了", scopes.account_jia(), "国内以前有没有电池起火冒烟的",
     [_ts(domains=_CN, mode="类似问题", phenomenon="电池起火冒烟")], None),
    ("导出·文字查找", scopes.account_jia(), "把国内描述里有触摸或起火的单导出",
     [_ts(domains=_CN, mode="关键词", terms=["触摸", "起火"], export=True)], []),
    ("清单·摘要与导出全文", scopes.account_jia(), "把近 30 天国内的问题全部导出",
     [_plan("list_issues", domains=_CN, time=_T30, export=True), _NARR], []),
    ("按号查单·摘要", scopes.account_jia(), "ZC9901001、ZC9901003 现在什么状态",
     [_plan("lookup_numbers", numbers=[{"raw": "ZC9901001", "kind_said": None},
                                       {"raw": "ZC9901003", "kind_said": None}])], []),
]


def _export_headers(h: Harness) -> list[Event]:
    """导出文件的页名与表头当成一张表查（设计 §15：导出表头同样不露字段名）。"""
    import io

    from openpyxl import load_workbook

    out = []
    for data in h.files.saved.values():
        for ws in load_workbook(io.BytesIO(data)).worksheets:
            header = [str(c.value) for c in next(ws.iter_rows(max_row=1))]
            out.append(Event.table(header, [], title=ws.title))
    return out


async def _conversation(privileges: dict, data: object, turns: list[tuple[str | None, list]]) -> tuple[
        Harness, list[Event]]:
    h = make_harness(privileges, history=[], config_files={"link_sites.toml": _SITES})
    data.load(h)
    h.llm.routes[custom_stats.ROUTE_MARKER] = _custom_route(_WEEKDAY)
    events: list[Event] = []
    last: list[Event] = []
    for k, (query, replies) in enumerate(turns):
        if query is None:
            query = next(e for e in last if e.type in (EventType.CLARIFY, EventType.SUGGESTIONS)).data[
                "recommendations"][0]["query"]
        h.llm.replies = list(replies)
        last = await run(h, query)
        text = "".join(e.data.get("text", "") for e in last if e.type is EventType.DELTA)
        h.ctx.session.rows += [{"role": "user", "content": query, "message_id": f"g{k}"},
                               {"role": "assistant", "content": text, "message_id": f"g{k}"}]
        events += last
    return h, events + _export_headers(h)


_ALL: list[tuple[str, Harness | None, list[Event]]] | None = None


async def _all_events() -> list[tuple[str, Harness | None, list[Event]]]:
    """每条路径跑一遍，几条检查共用这一份（只读事件与模型调用记录；跑一遍要几分钟）。"""
    global _ALL
    if _ALL is None:
        _ALL = await _collect()
    return _ALL


async def _collect() -> list[tuple[str, Harness | None, list[Event]]]:
    out: list[tuple[str, Harness | None, list[Event]]] = []
    for name, privileges, data, turns in S5_SCENARIOS:
        h, events = await _conversation(privileges, data, turns)
        assert events and not any(e.type is EventType.ERROR for e in events), name
        out.append((name, h, events))
    for name, privileges, query in SCENARIOS:
        h = make_harness(privileges, resolved=privileges is not None)
        out.append((name, h, await run(h, query)))
    for name, privileges, query, replies in EXEC_SCENARIOS:
        h = make_harness(privileges, llm_replies=replies, config_files={"link_sites.toml": _SITES})
        s3_data.load(h)
        events = await run(h, query)
        assert any(e.type in (EventType.TABLE, EventType.CLARIFY) for e in events), name
        out.append((name, h, events))
    for name, privileges, query, replies in S4_SCENARIOS:
        h = make_harness(privileges, llm_replies=replies, config_files={"link_sites.toml": _SITES})
        s4_data.load(h)
        events = await run(h, query)
        assert any(e.type is not EventType.ERROR for e in events) and events, name
        out.append((name, h, events))
    for name, privileges, query, replies, hits in S6_SCENARIOS:
        h = make_harness(privileges, llm_replies=replies, config_files={"link_sites.toml": _SITES})
        s6_data.load(h, texts=_S6_LONG, missing=(4,))
        h.llm.routes.update(_S6_ROUTES)
        if hits is None:
            h.ctx.retrieval = None
        else:
            h.retrieval.hits = [list(x) for x in hits]
        events = await run(h, query)
        assert events and not any(e.type is EventType.ERROR for e in events), name
        out.append((name, h, events + _export_headers(h)))
    for name, privileges, query, replies, script_replies, config in S7_SCENARIOS:
        h = make_harness(privileges, llm_replies=replies, config_files={"link_sites.toml": _SITES, **config})
        s3_data.load(h)
        h.llm.routes[custom_stats.ROUTE_MARKER] = _custom_route(*(script_replies or [_WEEKDAY]))
        events = await run(h, query)
        assert events and not any(e.type is EventType.ERROR for e in events), name
        out.append((name, h, events))
    for name, query, ext, replies, want in POLISH_SCENARIOS:
        h = make_harness(scopes.account_jia(), llm_replies=replies)
        request = ModuleRequest(query=query, conversation_id=h.ctx.conversation_id,
                                inputs={"ext_param": {"task": polish.TASK_CODE, **ext}})
        events = [e async for e in h.module.handle(request, h.ctx)]
        got = [("delta" if e.type is EventType.DELTA else e.data["code"]) for e in events]
        assert got == [want], (name, got)
        assert not h.llm.replies, name  # 准备的回放都用上了：调用次数对
        out.append((name, h, events))
    for domains in ([], [Domain.DOMESTIC], list(DOMAINS)):
        access = gate.DomainAccess(
            domains=frozenset(domains), car=False, text_search=frozenset(domains)
        )
        out.append((f"能力介绍·{len(domains)} 域", None, greeting.introduce(MANIFEST, access)))
    return out


#: AI 润色（润色设计 §12.1）：（说明, 原文, ext_param 里 task 以外的键, 模型回复, 最终结果）。最终结果是 "delta" 或错误
#: 代码：模型调用违规（比如多一条 system）时假模型抛的错会被润色吞成 POLISH_FAILED，所以要断言结果（P3 评审第 2 条）
_P_IMG = '<img src="https://example.test/a.png">'
POLISH_SCENARIOS: list[tuple[str, str, dict, list, str]] = [
    ("润色·一次过", f"<p>治具松动导致定位偏移{_P_IMG}</p>", {"field": "reason"},
     [{"text": "治具松动，导致定位偏移[[图1]]"}], "delta"),
    ("润色·修一次", "<p>更换治具并全检库存</p>", {"field": "measures", "max_length": 2000},
     ["以下是润色后的内容：\n更换治具并全检库存。", {"text": "更换治具，并全检库存。"}], "delta"),
    ("润色·两次都不过", "<p>更换治具</p>", {"field": "prevention"},
     [{"text": "更换治具，另有999台"}, {"text": "更换治具，另有999台"}], "POLISH_FAILED"),
    ("润色·模型出错", "为啥扭力不够", {"field": "five_why_question"}, [RuntimeError("x")], "POLISH_FAILED"),
    ("润色·5Why 的答", "扭力枪设定没改回来", {"field": "five_why_answer",
                                    "context": {"current_question": "为什么扭力不够？"}},
     [{"text": "扭力枪的设定没有改回来。"}], "delta"),
    ("润色·原文为空", "<p>&nbsp;</p>", {"field": "reason"}, [], "POLISH_EMPTY"),
    ("润色·太长", "<p>" + "字" * 3001 + "</p>", {"field": "reason"}, [], "POLISH_TOO_LONG"),
    ("润色·参数有误", "测试", {"field": "remark"}, [], "POLISH_BAD_PARAM"),
]


def _visible_strings(event: Event) -> list[str]:
    d = event.data
    out: list[str] = []
    if event.type is EventType.DELTA:
        out.append(d.get("text", ""))
    elif event.type is EventType.TABLE:
        out += [d.get("title", ""), *map(str, d.get("columns", []))]
        out += [str(c) for row in d.get("rows", []) for c in (row.values() if isinstance(row, dict) else row)]
    elif event.type is EventType.CHART:
        x = d.get("x") or {}
        out += [d.get("title", ""), d.get("unit", ""), str(x.get("name", "")), *map(str, x.get("data", []))]
        out += [str(s.get("name", "")) for s in d.get("series", [])]
    elif event.type in (EventType.CLARIFY, EventType.SUGGESTIONS):
        out += [d.get("question", ""), d.get("guide_text", ""), *map(str, d.get("options", []))]
        for rec in d.get("recommendations", []):
            if isinstance(rec, dict):
                out += [str(rec.get(k, "")) for k in ("name", "label", "query")]
            else:
                out.append(str(rec))
    elif event.type is EventType.ERROR:
        out += [d.get("code", ""), d.get("message", "")]
    return out


def _physical_names() -> tuple[set[str], set[str]]:
    """（禁出现的名字, 显示名里本来就有、因而豁免的名字）。"""
    names: set[str] = {INFO, ERP, MART, "dbo", "CoreINFO", "paxbase", "public"}
    for doc in landed.table_docs().values():
        names |= {doc.table, *doc.table.split("."), *doc.columns, *doc.keys}
    names |= {t for d in DOMAINS for t in d.mart_tables}
    shown: set[str] = set()
    for doc in landed.table_docs().values():
        for display in [*doc.columns.values(), *doc.keys.values()]:
            shown |= {w.lower() for w in re.findall(r"[A-Za-z0-9_]+", display or "")}
    for term in landed.glossary():
        for s in (term.term, *term.aliases):
            shown |= {w.lower() for w in re.findall(r"[A-Za-z0-9_]+", s)}
    exempt = {n for n in names if n.lower() in shown}
    return names - exempt, exempt


_URL = re.compile(r"\]\([^)]*\)|https?://\S+|/f/\S+")


def test_exempt_names_are_only_the_ones_shown_as_is():
    _forbidden, exempt = _physical_names()
    assert exempt == {"CAR", "PN", "PO"}


def _leaks(events: list[Event]) -> list[tuple[str, str]]:
    forbidden, _ = _physical_names()
    out = []
    for event in events:
        for text in _visible_strings(event):
            text = _URL.sub("", text)
            for n in forbidden:
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text, re.I):
                    out.append((n, text[:60]))
    return out


def test_leak_check_catches_names_and_skips_links():
    caught = _leaks([
        Event.delta("按 ZCTracking_ProblemList 查"),
        Event.table(["问题编号", "Status"], [["ZC9901001", "已完成"]]),
        Event.error("X", "info 连不上"),
        Event.suggestions([{"id": "1", "name": "a", "label": "a", "query": "看 AddDate"}]),
    ])
    assert {n for n, _ in caught} >= {"ZCTracking_ProblemList", "Status", "info", "AddDate"}
    assert _leaks([Event.delta("CAR 编号、PN、PO 照给；[ZC9901001](https://x/a?id=1&Status=2)")]) == []
    assert _leaks([Event.delta("国内单号ID")]) != []  # 汉字后面紧跟英文也算边界


async def test_no_table_or_column_names_reach_the_user():
    leaks = []
    for name, _h, events in await _all_events():
        leaks += [(name, *leak) for leak in _leaks(events)]
    assert leaks == []


async def test_buttons_are_objects_with_short_labels():
    seen = 0
    for name, _h, events in await _all_events():
        for event in events:
            assert event.type is not EventType.END, name
            if event.type not in (EventType.CLARIFY, EventType.SUGGESTIONS):
                continue
            recs = event.data.get("recommendations", [])
            ids = [r.get("id") for r in recs]
            assert len(ids) == len(set(ids)), name
            for rec in recs:
                seen += 1
                assert isinstance(rec, dict), (name, rec)
                for key in ("id", "name", "label", "query"):
                    assert isinstance(rec.get(key), str) and rec[key].strip(), (name, key, rec)
                assert len(rec["label"]) <= 30 and not rec["label"].endswith("…"), (name, rec)
                if event.type is EventType.SUGGESTIONS:  # 答后按钮不拼「原话（这一项）」（设计 §9.5、§19）
                    assert not rec["query"].endswith(f"（{rec['label']}）"), (name, rec)
    assert seen > 0


async def test_every_model_call_has_one_leading_system():
    for name, h, _events in await _all_events():
        if h is None:
            continue
        for messages in h.llm.calls:
            FakeLLM.check_messages(messages)


def test_fake_llm_rejects_a_second_system():
    with pytest.raises(AssertionError):
        FakeLLM.check_messages([{"role": "system", "content": "a"}, {"role": "system", "content": "b"}])
    with pytest.raises(AssertionError):
        FakeLLM.check_messages([{"role": "user", "content": "a"}, {"role": "system", "content": "b"}])


# ---------------------------------------------------------------- 静态检查 src

_COMPUTE_ALLOWED = ("stats/lib/", "stats/tasks/", "jobs/")
_AGGREGATES = {
    "groupby", "value_counts", "nunique", "agg", "aggregate", "pivot_table", "pivot", "crosstab",
    "sum", "mean", "median", "std", "var", "quantile", "cumsum", "cumcount", "idxmax", "idxmin",
    "rank", "nlargest", "nsmallest", "max", "min", "prod", "mode",
}


def _sources() -> list[tuple[str, ast.Module]]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        out.append((rel, ast.parse(path.read_text(encoding="utf-8"), filename=rel)))
    return out


def test_src_tree_is_found():
    rels = [rel for rel, _ in _sources()]
    assert "module.py" in rels and "turn/gate.py" in rels


def _aggregation_hits(sources: list[tuple[str, ast.Module]]) -> list[str]:
    hits = []
    for rel, tree in sources:
        if rel.startswith(_COMPUTE_ALLOWED):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _AGGREGATES
            ):
                hits.append(f"{rel}:{node.lineno} .{node.func.attr}(")
    return hits


def _executor_import_hits(sources: list[tuple[str, ast.Module]]) -> list[str]:
    hits = []
    for rel, tree in sources:
        # runner 按源码文本拼脚本；lib、tasks 自己之间的 import 在拼接时去掉，本来就是执行器的代码
        if rel == "stats/runner.py" or rel.startswith(("stats/lib/", "stats/tasks/")):
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level and rel.startswith("stats/"):
                    base = f"stats.{base}" if base else "stats"
                mods = [base, *(f"{base}.{a.name}" for a in node.names)]
            for mod in mods:
                if re.search(r"(^|\.)stats\.(lib|tasks)(\.|$)", mod):
                    hits.append(f"{rel}:{node.lineno} {mod}")
    return hits


def _raw_query_hits(sources: list[tuple[str, ast.Module]]) -> list[str]:
    hits = []
    for rel, tree in sources:
        if rel.startswith("jobs/"):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"query", "raw"}
            ):
                owner = node.func.value
                if (isinstance(owner, ast.Attribute) and owner.attr == "data") or (
                    isinstance(owner, ast.Name) and owner.id == "data"
                ):
                    hits.append(f"{rel}:{node.lineno} data.{node.func.attr}(")
    return hits


def test_no_aggregation_outside_executors():
    assert _aggregation_hits(_sources()) == []


def test_stats_lib_and_tasks_only_imported_by_runner():
    assert _executor_import_hits(_sources()) == []


def test_no_raw_query_on_data_handle():
    assert _raw_query_hits(_sources()) == []


def test_static_checks_catch_crafted_violations():
    bad = ast.parse(
        "import pandas as pd\n"
        "from factory_issue_module.stats.lib import derive\n"
        "n = df.groupby('a').size()\n"
        "total = df['x'].sum()\n"
        "rows = ctx.data.query('info', 't', select=['a'])\n"
        "more = data.raw('select 1', source='info', scope_on=[], table='t')\n"
    )
    assert len(_aggregation_hits([("skills/x.py", bad)])) == 2
    assert _aggregation_hits([("stats/lib/x.py", bad)]) == []
    assert len(_executor_import_hits([("present/x.py", bad)])) >= 1
    assert _executor_import_hits([("stats/runner.py", bad)]) == []
    rel_import = ast.parse("from .lib import derive\nfrom . import tasks\n")
    lines = {h.split()[0] for h in _executor_import_hits([("stats/custom.py", rel_import)])}
    assert lines == {"stats/custom.py:1", "stats/custom.py:2"}
    assert len(_raw_query_hits([("domains/x.py", bad)])) == 2
    assert _raw_query_hits([("jobs/x.py", bad)]) == []


# ---------------------------------------------------------------- 巴西链接用的两项值不进日志（§9.1）

#: 还没写进代码时用这一组测（不是十六进制字母，免得与链接里的结果偶然重合）
_STAND_IN = (b"QxQyQzQwQvQuQtQsQrQqQpQoQnQmQlQk", b"ZyZxZwZvZuZtZsZr")


def _fragments(pair: tuple[bytes, bytes], size: int = 6) -> list[str]:
    out = []
    for value in pair:
        text = value.decode("ascii")
        out += [text[i : i + size] for i in range(len(text) - size + 1)]
    return out


async def test_link_values_never_reach_logs_or_events(monkeypatch, caplog, capsys):
    """巴西链接：走正常路径与出错路径各一次，日志（structlog、标准 logging、标准输出）与事件里都没有这两项值的片段；
    出错时日志只记异常类型。代码里已经有值时测真值，没有时用一组替身。"""
    from factory_issue_module.present import _blk, _p7

    pair = _p7.pair() or _STAND_IN
    monkeypatch.setattr(_p7, "pair", lambda: pair)
    reply = [_plan("list_issues", domains={"value": ["巴西"], "from": "user"}, time=_T30), _NARR]
    sites = 'issue = "info.test.local"\nbrazil = "br.test.local"'
    events: list[Event] = []
    with structlog.testing.capture_logs() as logs:
        h = make_harness(scopes.GREEN, llm_replies=list(reply), config_files={"link_sites.toml": sites})
        s3_data.load(h)
        ok_events = await run(h, "近 30 天巴西的问题有哪些")
        events += ok_events

        def broken(data: bytes, a: bytes, b: bytes) -> bytes:
            raise ValueError(f"坏了 {a!r} {b!r}")

        monkeypatch.setattr(_blk, "seal", broken)
        h2 = make_harness(scopes.GREEN, llm_replies=list(reply), config_files={"link_sites.toml": sites})
        s3_data.load(h2)
        events += await run(h2, "近 30 天巴西的问题有哪些")
    assert any("BrazilProblem/AddBrazilProblemPage" in str(c) for t in (e for e in ok_events if e.type is EventType.TABLE)
               for row in t.data["rows"] for c in row)
    failed = [r for r in logs if r.get("event") == "factory_issue_link_param_failed"]
    assert failed and all(set(r) <= {"event", "log_level", "error", "timestamp"} and r["error"] == "ValueError"
                          for r in failed)
    seen = repr(logs) + caplog.text + "".join(capsys.readouterr()) + repr([e.data for e in events])
    assert [f for f in _fragments(pair) if f in seen] == []


# ---------------------------------------------------------------- 附件摘要用的那一项值不进日志与事件（§9.1，S4）

_SALT_STAND_IN = "QxSaltStandInValueForTestOnlyQx"


async def test_attachment_value_never_reaches_logs_or_events(monkeypatch, caplog, capsys):
    """附件预览链接：正常与出错两条路径，日志与事件里都没有那一项值的片段；出错时日志只记异常类型、只给文档名称。
    代码里已经有值时测真值，没有时用一组替身。"""
    from factory_issue_module.present import _q3, links

    word = _q3.word() or _SALT_STAND_IN
    monkeypatch.setattr(_q3, "word", lambda: word)
    events: list[Event] = []
    with structlog.testing.capture_logs() as logs:
        h = make_harness(scopes.GREEN, config_files={"link_sites.toml": _SITES})
        s4_data.load(h)
        ok_events = await run(h, "ZC9901001")
        events += ok_events

        def broken(*_a, **_k):
            raise ValueError(f"坏了 {word}")

        monkeypatch.setattr(links.hashlib, "md5", broken)
        h2 = make_harness(scopes.GREEN, config_files={"link_sites.toml": _SITES})
        s4_data.load(h2)
        bad_events = await run(h2, "ZC9901001")
        events += bad_events
    ok_text = "".join(e.data.get("text", "") for e in ok_events if e.type is EventType.DELTA)
    assert "/#/DocumentBusinessView?id=901&digest=" in ok_text
    bad_text = "".join(e.data.get("text", "") for e in bad_events if e.type is EventType.DELTA)
    assert "测试照片" in bad_text and "DocumentBusinessView" not in bad_text
    failed = [r for r in logs if r.get("event") == "factory_issue_link_param_failed"]
    assert failed and all(r["error"] == "ValueError" and set(r) <= {"event", "log_level", "error", "timestamp"}
                          for r in failed)
    seen = repr(logs) + caplog.text + "".join(capsys.readouterr()) + repr([e.data for e in events])
    frags = [word[i : i + 6] for i in range(len(word) - 5)]
    assert [f for f in frags if f in seen] == []


def test_attachment_value_is_in_code():
    """附件摘要的那一项值已写进代码（开发者 2026-10-30 给出）：只查形状，不在测试里重复这个值。"""
    from factory_issue_module.present import _q3, links

    word = _q3.word()
    assert links.attachment_ready() and word is not None and len(word) >= 16
    assert all(32 < ord(c) < 127 for c in word)


def test_attachment_digest_follows_link_rules(monkeypatch):
    """`link_rules.md`「GetDigest」：两头各接一段、UTF-8 取 MD5、Base64，去掉末尾的 `=` 与所有 `+`。"""
    import base64
    import hashlib

    from factory_issue_module.config.files import LinkSites
    from factory_issue_module.present import _q3, links

    monkeypatch.setattr(_q3, "word", lambda: "s+")
    raw = base64.b64encode(hashlib.md5(b"s+901s+").digest()).decode().rstrip("=").replace("+", "")
    sites = LinkSites(issue="https://a", brazil="https://a", attachment="https://b")
    assert links.attachment(sites, "照片[1]", 901) == f"[照片\\[1\\]](https://b/#/DocumentBusinessView?id=901&digest={raw})"
    monkeypatch.setattr(_q3, "word", lambda: None)
    assert links.attachment(sites, "照片", 901) == "照片"
    assert links.car(sites, "CAR999999999", 5) == \
        "[CAR999999999](https://a/QualityManage/Vendor/VendorReportOutDetail.aspx?VendorReportOutID=5)"
    assert links.car(None, "CAR999999999", 5) == "CAR999999999"
