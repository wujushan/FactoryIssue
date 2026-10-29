"""名字对库（设计 §6.5；总述「机型与系列怎么对」「部门名称怎么对」，各域「加工厂」）。名字是示意的。"""

from __future__ import annotations

import pytest

from factory_issue_module.config import files
from factory_issue_module.declarations import DEPT_ALIASES, FACTORY_REGIONS
from factory_issue_module.plan import names

MACHINES = ["A920", "A920PRO", "A920MAX", "A80", "A800", "M30", "IM30", "A80S"]
SERIES = ["A系列", "L系列", "底座", "其它"]
DEPTS = ["研发一部", "研发二部", "生产工程部", "行政人事部", "惠州-行政人事部", "质量管理部"]
CN_FACTORIES = ["柯洱斯", "柯洱斯", "亮亮", "惠州百富", "华拓"]


def test_machines_exact_and_normalized():
    assert names.machines("a920 pro", MACHINES) == ("A920PRO",)
    assert names.machines("A920", MACHINES) == ("A920",)
    assert names.machines("A921", MACHINES) == ()


def test_each_model_takes_letters_only():
    assert names.machines("A920", MACHINES, each=True) == ("A920", "A920PRO", "A920MAX")
    assert names.machines("A80", MACHINES, each=True) == ("A80", "A80S")  # A800 后接数字，不算
    assert names.machines("M30", MACHINES, each=True) == ("M30",)  # IM30 名称里夹着 M30，不算


def test_series_ignore_trailing_word_and_other():
    assert names.series("A 系列", SERIES) == ("A系列",)
    assert names.series("A", SERIES) == ("A系列",)
    assert names.series("底座", SERIES) == ("底座",)
    assert names.series("其他", SERIES) == ()
    assert names.series("其它系列", SERIES) == ("其它",)
    assert names.series("A920 系列", SERIES) == ()


def test_departments_in_order():
    aliases = files.default(DEPT_ALIASES)
    assert names.departments("行政人事部", DEPTS, aliases) == ("行政人事部",)  # 完整名称先对，不并入惠州-行政人事部
    assert names.departments("工程部", DEPTS, aliases) == ("生产工程部",)  # 部门简称
    assert names.departments("一部", DEPTS, aliases) == ("研发一部",)
    assert names.departments("研发", DEPTS, aliases) == ("研发一部", "研发二部")  # 包含匹配，对上多个
    assert names.departments("销售部", DEPTS, aliases) == ()


def test_domestic_factories():
    regions = files.default(FACTORY_REGIONS)
    assert names.factories("柯洱斯", CN_FACTORIES, regions) == ("柯洱斯",)  # 同名的两个码合成一个
    assert names.factories("亮亮工厂", CN_FACTORIES, regions) == ("亮亮",)
    assert names.factories("百富", CN_FACTORIES, regions) == ("惠州百富",)
    assert names.factories("惠州", CN_FACTORIES, regions) == ("柯洱斯", "亮亮", "惠州百富")
    assert names.factories("惠州的工厂", CN_FACTORIES, regions) == ("柯洱斯", "亮亮", "惠州百富")
    assert names.factories("鼎越", CN_FACTORIES, regions) == ()


@pytest.mark.parametrize("said", [
    "惠州的三个工厂",  # 规划器对 CN-011 的原样写法（对照集 p2.2 五次都是这样）
    "惠州的3个工厂", "惠州那几家工厂", "惠州地区全部工厂", "惠州所有的加工厂", "惠州地区的工厂", "惠州工厂",
])
def test_region_said_with_a_tail(said):
    """国内业务描述「加工厂」：「惠州的工厂」「惠州的三个工厂」都按地区说法对照。"""
    assert names.factories(said, CN_FACTORIES, files.default(FACTORY_REGIONS)) == ("柯洱斯", "亮亮", "惠州百富")


def test_region_tail_needs_the_rest_to_be_a_region():
    regions = files.default(FACTORY_REGIONS)
    assert names.factories("惠州百富工厂", CN_FACTORIES, regions) == ("惠州百富",)  # 去掉「工厂」是工厂名，不是地区
    assert names.region_items("深圳的三个工厂", regions) is None
    assert names.factories("深圳的三个工厂", CN_FACTORIES, regions) == ()


def test_brazil_factories_whole_name():
    assert names.brazil_factories("tt 工厂", ["CA", "TT"]) == ("TT",)
    assert names.brazil_factories("T", ["CA", "TT"]) == ()


def test_people_with_same_name_need_a_department():
    staff = [("张三", "生产工程部"), ("张三", "质量管理部"), ("李飞", "研发一部")]
    matched = names.people("张三", staff)
    assert len(matched) == 2
    assert names.person_options(matched) == ["生产工程部的张三", "质量管理部的张三"]


def test_check_options_whole_name_only():
    index = {"TT": ["巴西的加工厂"], "TT2": ["机型"], "亮亮": ["国内的加工厂", "供应商"]}
    assert names.check_options("TT", index, skip="机型") == ["TT：巴西的加工厂"]
    assert names.check_options("亮亮", index) == ["亮亮：国内的加工厂", "亮亮：供应商"]
    assert names.check_options("T", index) == []
