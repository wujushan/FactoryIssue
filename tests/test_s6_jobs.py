"""S6a 治理任务（设计 §12、§15「其余单测」）：清洗、去人名前缀、分段、指纹列与文字表列一致、建表后核对列、
写入 SQL 能被 pglast 解析，以及整条流水线在假 `JobContext` 上跑增量、全量、删单。

假 `ctx.etl`：`read("info")` 按 SQL 的形状（指纹 / 按单读原文 / 取姓名）回放内存里的源表；`read(MART)` 回放
`information_schema` 与文字表的指纹；`write(MART)` 记下每条 SQL，并把写入语句的 JSON 参数应用到内存里的三张表。
假数据照 `docs/testcases/seed/单测夹具清单.md`：假单号（年份 99）、「测试甲」「测试乙」。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import pandas as pd
import pglast
import pytest
from fakes import MANIFEST, FakeConfig
from forge_core.jobs import JobContext

from factory_issue_module import landed, textnorm
from factory_issue_module.config import defaults
from factory_issue_module.config import files as config_files
from factory_issue_module.declarations import INFO, MART, SEGMENTATION, Domain
from factory_issue_module.jobs import clean, ddl, fingerprint, read, segment, steps, text_sync, write
from factory_issue_module.jobs.spec import BY_DOMAIN, SOURCES

CN, BR, OS = (BY_DOMAIN[d] for d in (Domain.DOMESTIC, Domain.BRAZIL, Domain.OVERSEAS))
SEG = config_files.segmentation_from({})
_PARAM = re.compile(r"(?<![:\w]):([a-zA-Z_]\w*)")


# ---------------------------------------------------------------- 清洗


def test_strip_rich_drops_all_images_and_tags_but_keeps_paragraphs():
    raw = ('<p>屏幕<b>花屏</b></p><img src="data:image/png;base64,AAAA"><p>USB 接口&nbsp;松动</p>'
           '<img src="https://x/a.png"><div>data:image/jpeg;base64,BBBB 换线</div>')
    assert textnorm.strip_rich(raw) == "屏幕花屏\nUSB 接口 松动\n换线"
    assert "![图片](https://x/a.png)" in textnorm.rich_display(raw)[0]  # 详情展示仍留外链图片
    assert textnorm.strip_rich(None) == textnorm.strip_rich(float("nan")) == textnorm.strip_rich("<p></p>") == ""


@pytest.mark.parametrize(("content", "name", "want", "cut"), [
    ("测试乙，需要设计变更，责任人：测试甲", "测试乙", "需要设计变更，责任人：测试甲", True),
    ("测试乙,原因分析：焊接温度偏低", "测试乙", "原因分析：焊接温度偏低", True),
    ("测试乙：同意", "测试乙", "同意", True),
    ("测试乙、确认", "测试乙", "确认", True),
    ("测试乙 确认改善", "测试乙", "确认改善", True),
    ("测试乙确认改善，更换排线", "测试乙", "确认改善，更换排线", True),  # 责任人确认：姓名后直接接正文
    ("预防对策由测试乙确认", "测试乙", "预防对策由测试乙确认", False),  # 姓名不在开头不动
    ("将任务转移给测试甲", "测试乙", "将任务转移给测试甲", False),
    ("测试乙确认", None, "测试乙确认", False),  # 查不到操作人
])
def test_strip_name_prefix(content, name, want, cut):
    assert clean.strip_name(content, name) == (want, cut)


def test_short_counts_characters_without_spaces():
    assert clean.is_short("O K 同意")
    assert clean.is_short("一二三四五六七八九十")
    assert not clean.is_short("一二三四五六七八九十一")


def test_phenomenon_json_is_flattened_once_for_detail_and_jobs():
    raw = ('[{"Key":39,"Value":"黑屏、白屏"},{"Key":-1,"parentType":"功能问题","Value":"花屏","otherVal":" 夜间 "},'
           '{"Key":"-2","parentType":"外观","Value":"划伤","otherVal":""}]')
    assert textnorm.phen_parts(raw, "overseas") == [
        ("黑屏、白屏", False), ("功能问题 -> 花屏 (夜间)", True), ("外观 -> 划伤", True)]
    assert textnorm.phen_text(raw, "brazil") == "黑屏、白屏；功能问题->花屏  夜间 ；外观->划伤"
    assert textnorm.phen_parts("not json", "brazil") == [] and textnorm.phen_parts(None, "brazil") == []
    assert textnorm.json_items('[{"Value":"a\\q"}]') == [{"Value": "a\\q"}]  # 非法转义容错


# ---------------------------------------------------------------- 处理步骤


def _step(rid, code, name, user, *, result=None, opinion=None, content=None):
    return {"ID": rid, "Step": code, "StepStr": name, "AddUser": user, "Result": result, "Opinon": opinion,
            "Measures": content}


DOMESTIC_STEPS = [
    _step(1, 1, "填写问题", 1, content="测试甲提交了问题"),
    _step(2, 3, "责任人确认", 2, opinion="需要设计变更", content="测试乙，旧的一条"),
    _step(3, 6, "工厂制程分析", 1, result="焊接温度偏低", opinion="调整炉温",
          content="测试甲,原因分析：焊接温度偏低，制定对策：调整炉温"),
    _step(4, 3, "责任人确认", 2, opinion="改为更换排线", content="测试乙确认改善，原因为排线虚焊，更换排线"),
    _step(5, 28, "驳回", 1, content="驳回任务,驳回说明:资料不全"),
    _step(6, 10, "SQE跟进", 2, result="0", opinion="OK", content="测试乙,OK"),
]
NAMES = {1: "测试甲", 2: "测试乙"}


def test_steps_text_columns_take_every_step_latest_and_result_only_from_factory_analysis():
    st = steps.build(DOMESTIC_STEPS, CN.steps, SEG.domestic_codes, NAMES)
    assert st.result == "工厂制程分析：焊接温度偏低"  # SQE跟进 的结论是代码，不进
    assert st.opinion.split("\n") == ["工厂制程分析：调整炉温", "责任人确认：改为更换排线", "SQE跟进：OK"]
    assert st.content.split("\n") == [
        "填写问题：提交了问题", "工厂制程分析：原因分析：焊接温度偏低，制定对策：调整炉温",
        "责任人确认：确认改善，原因为排线虚焊，更换排线", "驳回：驳回任务,驳回说明:资料不全", "SQE跟进：OK"]


def test_steps_analysis_entries_follow_the_comparison_scope():
    st = steps.build(DOMESTIC_STEPS, CN.steps, SEG.domestic_codes, NAMES)
    assert st.entries == [
        ("工厂制程分析：", "原因分析：焊接温度偏低，制定对策：调整炉温"),  # 内容已含意见与结论，只留内容
        ("责任人确认：", "改为更换排线；确认改善，原因为排线虚焊，更换排线"),  # 意见不在内容里，两样都留
        ("SQE跟进：", "OK"),
    ]
    assert st.outside == {"1", "28"}
    dup = [*DOMESTIC_STEPS, _step(7, 35, "预防对策确认", 2, content="测试乙OK")]
    assert ("预防对策确认：", "OK") in steps.build(dup, CN.steps, SEG.domestic_codes, NAMES).entries


def test_name_prefix_counts_every_step_with_content():
    """S6a 评审 A1：全部环节的内容都去姓名、都进文字表，统计行里每个环节都报。"""
    st = steps.build(DOMESTIC_STEPS, CN.steps, SEG.domestic_codes, NAMES)
    assert st.prefix == {"填写问题": [1, 0], "工厂制程分析": [1, 0], "责任人确认": [1, 0], "驳回": [0, 1],
                         "SQE跟进": [1, 0]}  # 驳回的内容不以操作人姓名开头


def test_reject_named_like_prevention_confirm_is_still_reject():
    """国内按编码认环节：编码 28 的记录名称写成「预防对策确认」，仍是驳回，不进分析类条目（总述「比对范围」）。"""
    rows = [_step(1, 28, "预防对策确认", 2, opinion="资料不全", content="驳回任务,驳回说明:资料不全")]
    st = steps.build(rows, CN.steps, SEG.domestic_codes, NAMES)
    assert st.entries == [] and st.outside == {"28"}
    assert st.content == "预防对策确认：驳回任务,驳回说明:资料不全"  # 文字表的处理步骤内容照收，名称取那一条上的


def test_identical_entries_within_an_issue_are_kept_once():
    rows = [_step(1, 10, "SQE跟进", 2, content="测试乙,已跟进供应商"), _step(2, 13, "SQE跟进", 2, content="测试乙,已跟进供应商")]
    st = steps.build(rows, CN.steps, SEG.domestic_codes, NAMES)
    assert st.entries == [("SQE跟进：", "已跟进供应商")]


def test_overseas_steps_are_keyed_by_name():
    rows = [{"Id": 1, "StepStr": "责任人确认", "AddUser": 2, "Measures": "测试乙,确认", "Opinon": None, "Result": None},
            {"Id": 2, "StepStr": "工厂制程分析", "AddUser": 1, "Result": "炉温低", "Opinon": "调炉温",
             "Measures": "测试甲,结论:炉温低"},
            {"Id": 3, "StepStr": "效果确认", "AddUser": 1, "Measures": "测试甲,有效", "Opinon": "有效", "Result": None}]
    st = steps.build(rows, OS.steps, SEG.overseas_names, NAMES)
    assert st.result == "工厂制程分析：炉温低"
    assert [h for h, _ in st.entries] == ["责任人确认：", "工厂制程分析："]
    assert st.entries[1][1] == "调炉温；结论:炉温低"  # 结论已在内容里
    assert st.outside == {"效果确认"}


# ---------------------------------------------------------------- 分段


def _long(n_sentences: int) -> str:
    return "".join(f"第{i:02d}句说明换料之后测试正常并且已经复测三轮没有再出现问题。" for i in range(n_sentences))


def test_field_split_cuts_long_text_with_one_sentence_overlap():
    text = _long(12) + "\n" + _long(8)  # 每句 30 字，共约 600 字
    chunks = segment.split(text, SEG)
    assert len(chunks) >= 2 and all(len(c) <= SEG.seg_max for c in chunks)
    assert all(len(c) >= SEG.seg_min for c in chunks[:-1])
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        last = re.findall(r"[^。]+。", prev)[-1]
        assert nxt.startswith(last)  # 相邻段重叠一句
    assert "".join(chunks).count("第00句") == 2  # 两个段落各有一个第 00 句，没有丢
    assert segment.split("短文字", SEG) == ["短文字"]


def test_field_split_hard_cuts_a_sentence_longer_than_seg_max():
    """单句超过 seg_max 时硬切；硬切出来的块之间不重叠（重叠一整块会超过 seg_max），也不丢字。"""
    chunks = segment.split("长" * 1200, SEG)
    assert [len(c) for c in chunks] == [500, 500, 200]


def test_seg_rows_one_per_field_with_title_prefix():
    rows = segment.seg_rows("9901", {"desc": "USB 接口　松动", "reason": "", "step": "SQE跟进：OK"},
                            CN.seg_fields())
    assert [r["seg_id"] for r in rows] == ["9901:desc:0", "9901:step:0"]
    assert rows[0]["seg_text"] == "问题描述：USB 接口　松动"
    assert rows[0]["seg_norm"] == "usb 接口 松动" and rows[0]["seg_compact"] == "usb接口松动"


@pytest.mark.parametrize("rule", ["whole", "field", "field_split"])
def test_vseg_rules(rule):
    cfg = config_files.segmentation_from({"rule": rule})
    texts = {"desc": "刷卡失败，天线脱落", "measure": _long(20)}
    rows = segment.vseg_rows("9911", texts, BR.seg_fields(), cfg)
    if rule == "whole":
        assert [r["seg_id"] for r in rows] == ["9911:whole:0"]
        assert rows[0]["seg_text"].startswith("问题描述：刷卡失败") and "\n改善措施：" in rows[0]["seg_text"]
    elif rule == "field":
        assert [r["seg_id"] for r in rows] == ["9911:desc:0", "9911:measure:0"]
    else:
        assert rows[0]["seg_id"] == "9911:desc:0" and len(rows) > 2
        assert all(r["seg_text"].startswith("改善措施：") for r in rows[1:])
    assert set(rows[0]) == set(ddl.VSEG_COLUMNS)


# ---------------------------------------------------------------- 指纹、SQL 与建表


def _sqlserver_sqls() -> list[str]:
    out = []
    for spec in SOURCES:
        out.append(fingerprint.main_sql(spec))
        out += fingerprint.sub_sqls(spec).values()
        out.append(read.main_sql(spec, [1, 2])[0])
        out += [q for q, _p in read.sub_sqls(spec, [1, 2]).values()]
    out += [q for q, _p in read.employee_sqls([1, 2])]
    return out


def test_sqlserver_sql_avoids_functions_missing_at_compatibility_level_100():
    for sql in _sqlserver_sqls():
        for bad in ("TRY_CONVERT", "STRING_SPLIT", "CONCAT(", "STRING_AGG", "CONCAT_WS"):
            assert bad not in sql.upper(), (bad, sql)


def test_fingerprint_covers_every_text_column_source():
    """「指纹列与文字表列一致」：文字表每列在 `2_landed` 写的来源列，都进了指纹（或是拼条目用的键、行 ID）。"""
    for spec in SOURCES:
        hashed = fingerprint.hashed_columns(spec)
        everything = {c for cols in hashed.values() for c in cols}
        sql = " ".join([fingerprint.main_sql(spec), *fingerprint.sub_sqls(spec).values()])
        for cols in hashed.values():
            for col in cols:
                assert f"[{col}]" in sql, (spec.domain, col)
        label = spec.domain.label
        for column in landed.text_columns():
            cell = column.sources.get(label)
            if cell is None:
                continue
            named = set(re.findall(r"`([A-Za-z_]+)`", cell))
            # 行 ID 决定先后与「最新一条」，现象主数据的文字靠凌晨全量兜底（设计 §12 第 2 步）
            assert named <= everything | {"ID", "Id", "PhenomenonDesc"}, (label, column.name, named - everything)
        assert set(spec.text_columns()) == {c.name for c in landed.text_columns() if label in c.sources}


def test_fingerprint_combines_main_and_sorted_sub_rows():
    main = pd.DataFrame([{"issue_id": 9901, "issue_no": "ZC9901001", "fp": b"\x01", "size": 10}])
    a = pd.DataFrame([{"issue_id": 9901, "row_id": 2, "k1": 3, "k2": "责任人确认", "k3": 2, "fp": b"\x02", "size": 5},
                      {"issue_id": 9901, "row_id": 1, "k1": 1, "k2": "填写问题", "k3": 1, "fp": b"\x03", "size": 1}])
    one = fingerprint.combine(main, {"steps": a})
    two = fingerprint.combine(main, {"steps": a.iloc[::-1]})
    assert one == two and one["9901"].size == 16 and one["9901"].issue_no == "ZC9901001"
    changed = a.copy()
    changed.loc[0, "k3"] = 1  # 换了操作人：去人名前缀的结果可能变，指纹要变
    assert fingerprint.combine(main, {"steps": changed})["9901"].fingerprint != one["9901"].fingerprint


def _pg(sql: str) -> Any:
    names: list[str] = []

    def sub(m: re.Match) -> str:
        if m.group(1) not in names:
            names.append(m.group(1))
        return f"${names.index(m.group(1)) + 1}"

    return pglast.parse_sql(_PARAM.sub(sub, sql))


def test_write_and_ddl_sql_parse_with_pglast():
    for spec in SOURCES:
        for sql in (write.upsert_sql(spec), write.delete_sql(spec), *ddl.statements(spec), ddl.columns_sql(spec)[0]):
            assert "%" not in sql, sql  # PG 一侧经 psycopg 的 %(name)s 绑定
            assert _pg(sql), sql
        upsert = write.upsert_sql(spec)
        assert set(_PARAM.findall(upsert)) == {"text_rows", "ids", "seg_rows", "seg_ids", "vseg_rows", "vseg_ids"}
        for col in spec.text_columns():
            assert f" {col} text" in upsert and f"{col} = EXCLUDED.{col}" in upsert


def test_upsert_params_reject_duplicate_segment_ids_and_drop_nul():
    row = {"seg_id": "1:desc:0", "issue_id": "1", "field": "desc", "seq": 0, "seg_text": "x"}
    with pytest.raises(ValueError):
        write.upsert_params([], [], [row, dict(row)])
    params = write.upsert_params([], [{**row, "seg_text": "a\x00b"}], [])
    assert json.loads(params["seg_rows"])[0]["seg_text"] == "ab" and "\\u0000" not in params["seg_rows"]


def test_ddl_check_reports_missing_and_extra_columns():
    cols = ddl.expected(CN)
    ok = pd.DataFrame([{"table_name": t, "column_name": c} for t, cs in cols.items() for c in cs])
    ddl.check(CN, ok)
    broken = ok[~((ok.table_name == "domestic_issue_text") & (ok.column_name == "f_restart"))]
    broken = pd.concat([broken, pd.DataFrame([{"table_name": "domestic_issue_seg", "column_name": "old"}])])
    with pytest.raises(ddl.MartTableMismatch, match=r"domestic_issue_text 缺列 \['f_restart'\].*多出 \['old'\]"):
        ddl.check(CN, broken)
    with pytest.raises(ddl.MartTableMismatch, match="读不到列"):
        ddl.check(CN, pd.DataFrame(columns=["table_name", "column_name"]))


def test_batches_by_bytes_and_count():
    sizes = {"1": 15_000_000, "2": 10_000_000, "3": 50_000_000, "4": 1}
    assert read.batches(["4", "3", "2", "1"], sizes) == [["1"], ["2"], ["3"], ["4"]]
    many = [str(i) for i in range(1, 451)]
    assert [len(b) for b in read.batches(many, {})] == [200, 200, 50]


# ---------------------------------------------------------------- 假 JobContext 上的整条流水线

ALIVE = {
    Domain.DOMESTIC: lambda r: (r.get("IsDelete") or 0) == 0,
    Domain.BRAZIL: lambda r: r.get("Status") != -1,
    Domain.OVERSEAS: lambda r: r.get("IsDelete") == 0,
}


def _digest(values: list[Any]) -> bytes:
    return hashlib.sha256("\x1f".join("" if v is None else str(v) for v in values).encode()).digest()


class FakeInfo:
    """源库替身：按 SQL 的形状回放。指纹按 `hashed_columns` 现算，改了源数据指纹就跟着变。"""

    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self.tables = tables
        self.log: list[tuple[str, dict[str, Any]]] = []

    def _spec(self, table: str):
        for spec in SOURCES:
            if table in fingerprint.hashed_columns(spec) or table == spec.master:
                yield spec

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        params = params or {}
        self.log.append((sql, params))
        table = re.search(r"FROM (\S+) AS \w", sql).group(1)
        if table == read.EMPLOYEE_TABLE:
            wanted = set(params.values())
            return pd.DataFrame([r for r in self.tables[table] if r["ID"] in wanted], columns=["ID", "Name"])
        spec = next(s for s in SOURCES if table in fingerprint.hashed_columns(s))
        master = self.tables[spec.master]
        alive = {r[spec.id_col] for r in master if ALIVE[spec.domain](r)}
        if " IN (:" in sql:
            return self._read(spec, table, set(params.values()) & alive)
        return self._fingerprint(spec, table, alive)

    def _parent(self, spec, table: str) -> str:
        for sub in (spec.steps, spec.process, spec.cost, spec.phen_rows):
            if sub is not None and sub.table == table:
                return sub.parent_col
        raise KeyError(table)

    def _fingerprint(self, spec, table: str, alive: set[int]) -> pd.DataFrame:
        cols = fingerprint.hashed_columns(spec)[table]
        if table == spec.master:
            narrative = [c for _, c in spec.main] + ([spec.phen_json] if spec.phen_json else [])
            return pd.DataFrame([
                {"issue_id": r[spec.id_col], "issue_no": r[spec.no_col], "fp": _digest([r.get(c) for c in cols]),
                 "size": sum(len(str(r.get(c) or "")) for c in narrative)}
                for r in self.tables[table] if r[spec.id_col] in alive])
        parent = self._parent(spec, table)
        rid = next(sub.id_col for sub in (spec.steps, spec.process, spec.cost, spec.phen_rows)
                   if sub is not None and sub.table == table)
        out = []
        for r in self.tables[table]:
            if r[parent] not in alive:
                continue
            row = {"issue_id": r[parent], "row_id": r[rid], "fp": _digest([r.get(c) for c in cols]), "size": 1}
            keys = re.findall(r"\.\[(\w+)\] AS (k\d)", next(q for n, q in fingerprint.sub_sqls(spec).items()
                                                           if table in q))
            row |= {k: r.get(c) for c, k in keys}
            out.append(row)
        return pd.DataFrame(out)

    def _read(self, spec, table: str, ids: set[int]) -> pd.DataFrame:
        if table == spec.master:
            return pd.DataFrame([{"issue_id": r[spec.id_col], "issue_no": r[spec.no_col], **r}
                                 for r in self.tables[table] if r[spec.id_col] in ids])
        parent = self._parent(spec, table)
        rows = [{"issue_id": r[parent], **r} for r in self.tables[table] if r[parent] in ids]
        if spec.phen_rows is not None and table == spec.phen_rows.table:
            text = {p["ID"]: p["PhenomenonDesc"] for p in self.tables[spec.phen_rows.master]}
            rows = [{**r, "PhenomenonDesc": text.get(r["PhenomenonID"])} for r in rows]
        return pd.DataFrame(rows)


class FakeMart:
    """产物库替身：写句柄把写入语句的 JSON 参数应用到内存里的三张表；读句柄回放列与文字表指纹。"""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, dict[str, Any]]] = {}
        self.log: list[tuple[str, dict[str, Any]]] = []
        self.columns_override: pd.DataFrame | None = None

    # 写句柄
    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        params = params or {}
        self.log.append((sql, params))
        if sql.startswith("WITH t AS (INSERT INTO "):
            text_table, seg_table, vseg_table = re.findall(r"INSERT INTO (\w+)", sql)
            ids = json.loads(params["ids"])
            for name, key, rows_key, keep_key in ((seg_table, "seg_id", "seg_rows", "seg_ids"),
                                                   (vseg_table, "seg_id", "vseg_rows", "vseg_ids")):
                keep = set(json.loads(params[keep_key]))
                table = self.store.setdefault(name, {})
                for k in [k for k, r in table.items() if r["issue_id"] in ids and k not in keep]:
                    del table[k]
                for r in json.loads(params[rows_key]):
                    table[r[key]] = r
            for r in json.loads(params["text_rows"]):
                self.store.setdefault(text_table, {})[r["issue_id"]] = r
        elif sql.startswith("WITH a AS (DELETE"):
            ids = set(json.loads(params["ids"]))
            for name in re.findall(r"DELETE FROM (\w+)", sql):
                table = self.store.setdefault(name, {})
                for k in [k for k, r in table.items() if r["issue_id"] in ids]:
                    del table[k]
        return 1

    # 读句柄
    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        params = params or {}
        if "information_schema" in sql:
            if self.columns_override is not None:
                return self.columns_override
            spec = next(s for s in SOURCES if s.domain.text_table in params.values())
            return pd.DataFrame([{"table_name": t, "column_name": c} for t, cs in ddl.expected(spec).items() for c in cs])
        table = re.search(r"FROM (\w+)", sql).group(1)
        rows = self.store.get(table, {}).values()
        return pd.DataFrame([{"issue_id": r["issue_id"], "text_fingerprint": r["text_fingerprint"]} for r in rows],
                            columns=["issue_id", "text_fingerprint"])

    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        return [(s, p) for s, p in self.log if s.startswith("WITH")]


class FakeEtl:
    def __init__(self, info: FakeInfo, mart: FakeMart) -> None:
        self.info, self.mart = info, mart

    def read(self, alias: str) -> Any:
        return {INFO: self.info, MART: self.mart}[alias]

    def write(self, alias: str) -> Any:
        assert alias == MART
        return self.mart


LONG_MEASURE = _long(25)


def source_tables() -> dict[str, list[dict[str, Any]]]:
    return {
        CN.master: [
            {"ID": 9901, "Numbers": "ZC9901001", "IsDelete": 0,
             "ProblemDesc": '<p>屏幕<b>花屏</b></p><img src="data:image/png;base64,AAAA"><p>USB 接口松动&nbsp;需要更换</p>',
             "Reason": "排线虚焊", "Improve": "OK", "Measures": LONG_MEASURE, "Prevention": None,
             "Confirmation": "返工后正常", "Remark": None, "ProduceConfirmRemark": "", "ReasonClassRemark": None,
             "ReStartScheme": "<p>先返工再重启</p>"},
            {"ID": 9902, "Numbers": "ZC9901002", "IsDelete": 1, "ProblemDesc": "已删除的单"},
            {"ID": 9903, "Numbers": "ZC9901003", "IsDelete": None, "ProblemDesc": "OK"},
        ],
        CN.steps.table: [{**s, "ProblemId": 9901} for s in DOMESTIC_STEPS],
        CN.phen_rows.table: [{"ID": 1, "ProblemId": 9901, "PhenomenonID": 11},
                             {"ID": 2, "ProblemId": 9901, "PhenomenonID": 11},
                             {"ID": 3, "ProblemId": 9901, "PhenomenonID": 12}],
        CN.phen_rows.master: [{"ID": 11, "PhenomenonDesc": "花屏"}, {"ID": 12, "PhenomenonDesc": "无法开机"}],
        BR.master: [{"ID": 9911, "OrderNumber": "BR9901001", "Status": 20,
                     "ProblemPhenomenon": '[{"Key":5,"Value":"花屏"},{"Key":-1,"parentType":"功能问题",'
                                          '"Value":"刷卡无反应，按键也失灵","otherVal":"夜间"}]',
                     "ProblemDesc": "<p>刷卡失败</p>", "Memo": None, "SupplementMemo": "补 3 台"},
                    {"ID": 9912, "OrderNumber": "BR9901002", "Status": -1, "ProblemDesc": "已删除"}],
        BR.process.table: [{"ID": 1, "ProblemID": 9911, "ReasonAnalysis": "旧原因"},
                           {"ID": 2, "ProblemID": 9911, "ReasonAnalysis": "天线脱落导致刷卡失败",
                            "DisposeResult": "SQE 已跟进供应商", "ImprovementMeasure": "更换天线并点胶固定"}],
        BR.cost.table: [{"ID": 1, "ProblemID": 9911, "CostType": "返工费", "CostMemo": "<p>返工 3 台</p>"},
                        {"ID": 2, "ProblemID": 9911, "CostType": "物料费", "CostMemo": ""}],
        OS.master: [{"Id": 9921, "Numbers": "HW9901001", "IsDelete": 0,
                     "hasCheckedPhenomenon": '[{"Key":39,"Value":"黑屏、白屏"},{"Key":-1,"parentType":"功能问题",'
                                             '"Value":"花屏","otherVal":"夜间"}]',
                     "ProblemDesc": "夜间巡检发现花屏", "Reason": "屏线松动", "ProblemRemark": None}],
        OS.steps.table: [{"Id": 1, "ProblemId": 9921, "StepStr": "责任人确认", "AddUser": 2,
                          "Measures": "测试乙,确认原因为屏线松动", "Opinon": None, "Result": None}],
        read.EMPLOYEE_TABLE: [{"ID": 1, "Name": "测试甲"}, {"ID": 2, "Name": "测试乙"}],
    }


class Progress:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int | None, str]] = []

    def __call__(self, p: Any) -> None:
        self.calls.append((p.done, p.total, p.message))


def job_ctx(info: FakeInfo, mart: FakeMart, config: dict[str, str] | None = None) -> tuple[JobContext, Progress]:
    progress = Progress()
    ctx = JobContext(module_code="FACTORY_ISSUE", etl=FakeEtl(info, mart),
                     config=FakeConfig(MANIFEST, config), on_progress=progress)
    return ctx, progress


async def test_first_run_writes_cleaned_text_segments_and_vectors_source():
    info, mart = FakeInfo(source_tables()), FakeMart()
    ctx, progress = job_ctx(info, mart)
    stats = await text_sync.run(ctx, full=False)

    creates = [s for s, _ in mart.log if s.startswith("CREATE")]
    assert len(creates) == 12  # 每域三张表加分段表的索引
    text = mart.store["domestic_issue_text"]
    assert set(text) == {"9901", "9903"}  # 已删除的单不进
    row = text["9901"]
    assert row["issue_no"] == "ZC9901001"
    assert row["f_desc"] == "屏幕花屏\nUSB 接口松动 需要更换"
    assert row["f_phen"] == "花屏；无法开机"
    assert row["f_restart"] == "先返工再重启" and row["f_prev"] == "" and row["f_improve"] == "OK"
    assert row["f_step_result"] == "工厂制程分析：焊接温度偏低"
    assert "责任人确认：确认改善，原因为排线虚焊，更换排线" in row["f_step_content"].split("\n")
    assert set(row) == {*ddl.text_columns(CN)} - {"synced_at"}

    seg = mart.store["domestic_issue_seg"]
    assert {k for k in seg if k.startswith("9901:")} == {
        "9901:phen:0", "9901:desc:0", "9901:reason:0", "9901:improve:0", "9901:measure:0", "9901:step:0"}
    assert seg["9901:phen:0"]["seg_text"] == "问题现象：花屏；无法开机"
    vseg = mart.store["domestic_issue_vseg"]
    fields = {r["field"] for r in vseg.values() if r["issue_id"] == "9901"}
    assert fields == {"desc", "measure", "step"}  # 国内问题现象、不超过 10 个字的原因与改善建议都不进
    assert len([k for k in vseg if k.startswith("9901:measure:")]) > 1  # 长的改善措施切成几段
    step_v = vseg["9901:step:0"]["seg_text"]
    assert "SQE跟进" not in step_v and step_v.startswith("处理步骤：工厂制程分析：")  # 「OK」条目不进按意思找
    assert not any(r["issue_id"] == "9903" for r in vseg.values())  # 只有「OK」的单没有按意思找的段

    br = mart.store["brazil_issue_text"]["9911"]
    assert br["f_reason"] == "天线脱落导致刷卡失败" and br["f_sqe"] == "SQE 已跟进供应商"
    assert br["f_cost_memo"] == "返工费：返工 3 台"
    assert br["f_phen"] == "花屏；功能问题->刷卡无反应，按键也失灵 夜间"
    assert mart.store["brazil_issue_vseg"]["9911:phen:0"]["seg_text"] == "问题现象：功能问题->刷卡无反应，按键也失灵 夜间"
    assert "9911:sqe:0" in mart.store["brazil_issue_seg"]
    os_v = mart.store["overseas_issue_vseg"]
    assert os_v["9921:phen:0"]["seg_text"] == "已选问题现象：功能问题 -> 花屏 (夜间)"
    assert mart.store["overseas_issue_text"]["9921"]["f_step_content"] == "责任人确认：确认原因为屏线松动"

    cn = stats["domestic"]
    assert (cn.issues, cn.pulled, cn.removed) == (2, 2, 0)
    assert cn.with_inline_images == 1 and cn.no_vseg == 1 and cn.empty_text == 0
    assert cn.name_prefix["责任人确认"] == [1, 0] and cn.name_prefix["填写问题"] == [1, 0]
    assert cn.outside_steps == {"1", "28"}
    last = progress.calls[-1][2]
    assert last.startswith(f"明细见日志 {text_sync.STATS_EVENT}｜国内 单2 整理2 段")
    assert "含图1" in last and "去姓名" in last and "清单外2" in last and len(last) <= text_sync.PROGRESS_MESSAGE_MAX


def test_raw_chars_and_images_count_only_what_is_written():
    """S6a 评审 A3：同一环节没被采用的旧记录不算清洗前的字数，它带的内嵌图片也不让这张单算「含图」。"""
    main = {"issue_no": "HW9901002", "ProblemDesc": "屏幕闪烁"}
    old = {"Id": 1, "StepStr": "责任人确认", "AddUser": 2, "Result": None, "Opinon": None,
           "Measures": '测试乙,<img src="data:image/png;base64,' + "A" * 5000 + '">旧的'}
    new = {"Id": 2, "StepStr": "责任人确认", "AddUser": 2, "Result": None, "Opinon": None, "Measures": "测试乙,确认"}
    built = text_sync.build_issue(OS, "9922", main, {"steps": [old, new]}, NAMES, SEG,
                                  fingerprint.Print("HW9901002", "fp", 0))
    assert built.has_images is False
    assert built.chars_raw == len("屏幕闪烁") + len("测试乙,确认")
    assert built.text_row["f_step_content"] == "责任人确认：确认"


def _stats(issues: int, segs: int, raw: int, clean_: int, images: int, no_vseg: int, steps_: int,
           *, removed: int = 0, empty: int = 0) -> text_sync.DomainStats:
    return text_sync.DomainStats(
        issues=issues, pulled=issues, removed=removed, seg_rows=segs, vseg_rows=segs - segs // 10, chars_raw=raw,
        chars_clean=clean_, with_inline_images=images, empty_text=empty, no_vseg=no_vseg,
        name_prefix={f"环节{i}": [400, 3] for i in range(steps_)}, outside_steps={str(i) for i in range(steps_)},
        ms={"ddl": 100, "fingerprint": 2_000, "read": 90_000, "clean": 30_000, "write": 60_000},
    )


def test_progress_summary_fits_the_task_page_column():
    """S6a 评审 A2：Console 任务页的进度句只存 256 字。照本助手首轮全量的量级（G2「涉及数据与数据量」「整理规则」
    的估算）放得下，核对清单的各项都在（去人名前缀、耗时给合计，为 0 的项不写）；明细日志名在最前；
    真放不下时自己截并写「…」。"""
    first_round = {"domestic": _stats(2474, 9500, 31_000_000, 2_300_000, 9, 966, 22, removed=3),
                   "brazil": _stats(203, 1000, 84_000_000, 200_000, 44, 20, 0),
                   "overseas": _stats(12, 90, 600_000, 30_000, 1, 2, 18, empty=1)}
    text = text_sync.summary(first_round)
    assert len(text) <= text_sync.PROGRESS_MESSAGE_MAX and not text.endswith("…"), len(text)
    assert text.startswith(f"明细见日志 {text_sync.STATS_EVENT}｜国内 单2474 整理2474 段9500/8550 字3100万→230万 删3")
    for part in ("无向量966", "含图9", "清单外22", "去姓名8800/8866", "182秒", "巴西 单203", "含图44", "海外 单12", "空1"):
        assert part in text, part
    assert "巴西 单203 整理203 段1000/900 字8400万→20万 无向量20 含图44 182秒" in text  # 巴西没有处理步骤表
    huge = text_sync.summary({d: _stats(123_456, 1_234_567, 999_000_000, 99_000_000, 99, 99, 99, removed=9, empty=9)
                              for d in first_round})
    assert len(huge) == text_sync.PROGRESS_MESSAGE_MAX and huge.endswith("…")
    assert huge.startswith(f"明细见日志 {text_sync.STATS_EVENT}｜")


async def test_incremental_run_only_rewrites_changed_issues_and_deletes_removed():
    tables = source_tables()
    info, mart = FakeInfo(tables), FakeMart()
    await text_sync.run(job_ctx(info, mart)[0], full=False)
    first = len(mart.writes())

    await text_sync.run(job_ctx(info, mart)[0], full=False)
    assert len(mart.writes()) == first  # 没有变化：只建表与核对列，不写

    tables[CN.master][2]["ProblemDesc"] = "改过的问题描述，屏幕闪烁"
    await text_sync.run(job_ctx(info, mart)[0], full=False)
    (sql, params), = mart.writes()[first:]
    assert json.loads(params["ids"]) == ["9903"] and "domestic_issue_text" in sql
    assert mart.store["domestic_issue_text"]["9903"]["f_desc"] == "改过的问题描述，屏幕闪烁"
    assert "9903:desc:0" in mart.store["domestic_issue_vseg"]  # 超过 10 个字了，进按意思找

    tables[CN.master][2]["IsDelete"] = 1
    tables[CN.steps.table].append({**_step(7, 3, "责任人确认", 2, content="测试乙,再确认一次"), "ProblemId": 9901})
    stats = await text_sync.run(job_ctx(info, mart)[0], full=False)
    assert stats["domestic"].removed == 1 and stats["domestic"].pulled == 1
    assert "9903" not in mart.store["domestic_issue_text"]
    assert not any(r["issue_id"] == "9903" for r in mart.store["domestic_issue_seg"].values())
    assert "责任人确认：再确认一次" in mart.store["domestic_issue_text"]["9901"]["f_step_content"]

    before = len(mart.writes())
    stats = await text_sync.run(job_ctx(info, mart)[0], full=True)
    assert stats["domestic"].pulled == 1 and len(mart.writes()) == before + 3  # 全量：三域各写一批


async def test_segmentation_config_is_read_from_ctx_config():
    info, mart = FakeInfo(source_tables()), FakeMart()
    await text_sync.run(job_ctx(info, mart, {SEGMENTATION: 'rule = "whole"'})[0], full=True)
    assert {r["field"] for r in mart.store["domestic_issue_vseg"].values()} == {"whole"}
    assert {r["field"] for r in mart.store["domestic_issue_seg"].values()} >= {"desc", "step"}  # 分段表不受分段规则影响


async def test_mismatched_mart_table_fails_the_job_before_writing():
    info, mart = FakeInfo(source_tables()), FakeMart()
    mart.columns_override = pd.DataFrame([{"table_name": "domestic_issue_text", "column_name": "issue_id"}])
    with pytest.raises(ddl.MartTableMismatch):
        await text_sync.run(job_ctx(info, mart)[0], full=False)
    assert mart.writes() == [] and not any("HASHBYTES" in s for s, _ in info.log)


def test_job_never_reads_through_ctx_data_or_calls_a_model():
    """治理任务只经 `ctx.etl`（设计 §12）：源码里没有 `ctx.data`、`ctx.llm`、自己连库或读环境变量。"""
    from pathlib import Path

    folder = Path(text_sync.__file__).parent
    for path in folder.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        for bad in ("ctx.data", "ctx.llm", "os.environ", "getenv", "import psycopg", "import pyodbc",
                    "PgVectorIndex(", "EmbeddingClient("):
            assert bad not in src, (path.name, bad)


def test_default_segmentation_steps_match_comparison_scope_text():
    scope = landed.comparison_scope_section()
    for code in defaults.SEGMENTATION["steps"]["domestic_codes"]:
        assert f"- {code} " in scope
