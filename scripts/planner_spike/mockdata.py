"""规划实测用的合成主数据：条数与真实库同一量级，名字都是编的，不含真实员工、供应商。

只给问句预匹配（prematch.py）用，量的是「附预匹配提示」会不会带来噪声与撞名。
`resolve.py` 的名字归类仍用它自己那份示意名单，两者互不影响。

- 人员 15,091、部门 50、供应商 978、国内工厂 10、巴西工厂 12，与总述「数据量声明」的行数相同；
  机型约 500 个（国内机型子表 2,720 行、产品主数据 480 行，去重后的机型名在这个量级）。
- 对照集问句里出现的名字（李飞、惠州百富、TT、普瑞特……）都放进来；它们来自测试案例集与 2_landed。
- 故意放了几种撞名：「亮亮」既是国内工厂又是供应商；机型「A35」是 PN 名称「A35-000-RD6-00E0」的开头；
  人员按常见姓与名用字随机组合，会自然撞上「高明」「黎明」这类常用词。
"""

from __future__ import annotations

import random

from common import LANDED
from prompts import _md_table

SEED = 20261027

_SURNAMES = ("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任"
             "沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史黎贺顾毛郝龚邵万钱覃武戴孔汤庞樊兰殷施"
             "陶洪翟安颜倪严牛温季俞章鲁葛伍申尤毕聂柴焦向柳邢岳齐梅莫庄辛管祝左涂谷祁时舒耿卜路詹关苗凌费纪靳盛童欧")
_GIVEN = ("伟芳娜敏静丽强磊军洋勇艳杰涛明超秀霞平刚桂英华玉萍红娟建文辉力林斌宇浩凯健俊帆鹏飞鑫波琳婷雪颖晨阳峰海"
          "亮宁欣怡佳晶倩璐丹萌诗梦妍思雨涵琪志国庆春秋冬梅兰竹松柏东南北新永福禄寿喜乐安康泰")

# 对照集与 2_landed 里出现的名字；另放几个与常用词同形的人名（真实名册里一定有这类撞名）
_KNOWN_PEOPLE = ("李飞", "马万军", "张三", "高明", "黎明", "金华", "安康", "高峰", "文明", "海平", "洪涛", "江海")
DOMESTIC_FACTORIES = ("柯洱斯", "亮亮", "惠州百富", "华拓", "恒泰", "鼎越", "新锐", "联创", "宏远")  # 柯洱斯有两个码，名称 9 个
BRAZIL_FACTORIES = ("CA", "TT", "SP", "MN", "RJ", "BH", "PA", "CT", "MX", "GV", "LD", "FZ")
OVERSEAS_FACTORIES = ("雅加达厂", "蒙特雷厂", "钦奈厂")
_KNOWN_SUPPLIERS = ("普瑞特", "高展光电", "亮亮")
_KNOWN_MACHINES = ("A920", "A920PRO", "A920MAX", "A930", "A8900", "L1400", "Q80", "IM30", "A6650", "A960", "A800",
                   "A35", "A8700", "S920", "D190")
SERIES = ("A系列", "L系列", "Q系列", "底座")
_DEPT_SUFFIX = ("部", "中心", "组", "科")
_DEPT_BASE = ("质量管理", "采购", "计划", "工艺", "测试", "市场", "销售一", "销售二", "售后服务", "物流", "仓储", "设备",
              "生产一", "生产二", "生产三", "品质保证", "供应链管理", "项目管理", "产品", "硬件研发", "软件研发", "结构设计",
              "认证", "客户服务", "制造工程", "SMT", "组装", "包装", "IQC", "SQE", "OQC", "研发三", "研发四", "海外业务",
              "巴西业务", "国内业务", "人力资源", "法务", "审计", "安全环保", "基建", "总裁办")
_SUPPLIER_HEAD = "华金鑫盛恒宏晶光精诚创达通泰丰联科新远德隆旭辰合众瑞嘉信源"
_SUPPLIER_TAIL = ("电子", "科技", "光电", "精密", "五金", "塑胶", "电路", "材料", "实业", "电器")


def _people(rng: random.Random, n: int = 15091) -> list[str]:
    names = set(_KNOWN_PEOPLE)
    while len(names) < n:
        given = rng.choice(_GIVEN) + (rng.choice(_GIVEN) if rng.random() < 0.55 else "")
        names.add(rng.choice(_SURNAMES) + given)
    return sorted(names)


def _departments() -> tuple[list[str], dict[str, str]]:
    """部门 50 个：2_landed 部门简称表里的正式名称 + 编的；简称从 2_landed 读。"""
    md = (LANDED / "business_description.md").read_text(encoding="utf-8")
    aliases: dict[str, str] = {}
    formal: list[str] = []
    for row in _md_table(md, "部门名称怎么对"):
        if len(row) >= 2 and row[0]:
            formal.append(row[0])
            for a in row[1].replace("，", "、").split("、"):
                a = a.strip()
                if a and a not in ("—", "-"):
                    aliases[a] = row[0]
    depts = list(dict.fromkeys(formal + ["行政人事部", "财务部", "惠州-行政人事部", "惠州-财务部"]))
    for base in _DEPT_BASE:
        if len(depts) >= 50:
            break
        depts.append(base + ("部" if not base.endswith(("部", "中心", "组", "科")) else ""))
    return depts[:50], aliases


def _suppliers(rng: random.Random, n: int = 978) -> list[str]:
    names = set(_KNOWN_SUPPLIERS)
    while len(names) < n:
        names.add(rng.choice(_SUPPLIER_HEAD) + rng.choice(_SUPPLIER_HEAD) + rng.choice(_SUPPLIER_TAIL))
    return sorted(names)


def _machines(rng: random.Random, n: int = 500) -> list[str]:
    names = set(_KNOWN_MACHINES)
    while len(names) < n:
        prefix = rng.choice(("A", "A", "L", "Q", "IM", "S", "D", "E", "M", "P", "X"))
        code = f"{prefix}{rng.randint(1, 99) * 10 + rng.choice((0, 0, 0, 5))}"
        if rng.random() < 0.25:
            code += rng.choice(("PRO", "MAX", "SE", "S", "C"))
        names.add(code)
    return sorted(names)


def _regions() -> dict[str, list[str]]:
    md = (LANDED / "domestic" / "business_description.md").read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    for row in _md_table(md, "加工厂"):
        if len(row) >= 2 and row[0] and "、" in row[1]:
            out[row[0]] = [x.strip() for x in row[1].split("、") if x.strip()]
    return out


def build_catalog() -> dict[str, dict[str, list[str]]]:
    """名字 → 它在库里属于哪几类（可多类）。"""
    rng = random.Random(SEED)
    depts, dept_aliases = _departments()
    kinds: dict[str, list[str]] = {}

    def put(name: str, kind: str) -> None:
        kinds.setdefault(name, [])
        if kind not in kinds[name]:
            kinds[name].append(kind)

    for n in _people(rng):
        put(n, "人员")
    for n in depts:
        put(n, "部门")
    for a, formal in dept_aliases.items():
        put(a, f"部门简称（对应{formal}）")
    for n in _suppliers(rng):
        put(n, "供应商")
    for n in _machines(rng):
        put(n, "机型")
    for n in SERIES:
        put(n, "系列")
    for n in DOMESTIC_FACTORIES:
        put(n, "加工厂（国内）")
    for n in BRAZIL_FACTORIES:
        put(n, "加工厂（巴西）")
    for n in OVERSEAS_FACTORIES:
        put(n, "加工厂（海外）")
    for region, factories in _regions().items():
        put(region, f"地区说法（对应国内加工厂{'、'.join(factories)}）")
    return {"kinds": kinds}


CATALOG = build_catalog()["kinds"]
