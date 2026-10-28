"""规划器实测：路径、环境变量、文本归一化。不是模块代码，`src/` 不引用。"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LANDED = ROOT / "docs" / "2_landed"
CASES_DIR = HERE / "cases"
RUNTIME = ROOT / "runtime"
DEFAULT_OUT_ROOT = RUNTIME / "planner_spike"

DOMAINS = ("国内", "巴西", "海外")


def load_env_file(path: Path = ROOT / ".env") -> None:
    """读仓库根目录 .env（已在 .gitignore）。已有同名环境变量时以环境变量为准。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def check_out_dir(path: Path) -> Path | None:
    """输出只允许写在仓库的 runtime/ 下（不入库）。"""
    resolved = path.resolve()
    runtime = RUNTIME.resolve()
    if resolved != runtime and runtime not in resolved.parents:
        print(f"输出目录必须在 {runtime} 下：{resolved}", file=sys.stderr)
        return None
    return resolved


_STRIP = re.compile(r"[\s\-_·'\"「」『』“”‘’《》]+")


def norm(text: object) -> str:
    """比较用的归一：全角转半角、小写、去空白与常见引号连字符。"""
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).lower()
    return _STRIP.sub("", value)


# 取值的同义写法（只收规划器常见的几种，归一到同一个词再比）
VALUE_SYNONYMS = {
    "硬件": "硬件问题", "软件": "软件问题", "物料": "物料问题", "结构": "结构问题",
    "资料": "资料问题", "设计": "设计问题", "生产": "生产问题",
    "已完成": "已结案", "结案": "已结案", "已关闭": "已结案",
    "没结案": "未结案", "未完成": "未结案", "进行中": "未结案", "没完成": "未结案",
    "a级": "a", "a类": "a", "a+级": "a+",
    "有": "是", "涉及": "是", "需要": "是", "true": "是", "yes": "是",
    "无": "否", "不涉及": "否", "不需要": "否", "false": "否", "no": "否",
    "5why": "5why", "5why分析": "5why",
}


def norm_value(value: object) -> str:
    key = norm(value)
    return VALUE_SYNONYMS.get(key, key)


FIELD_SYNONYMS = {
    "问题跟进人": "跟进人", "问题跟进部门": "跟进部门", "责任部门": "责任归属部门",
    "当前处理人": "当前责任人", "问题等级": "问题等级", "等级": "问题等级",
    "类型": "问题类型", "问题分类": "问题类型", "工厂": "加工厂",
}


def norm_field(field: object) -> str:
    key = norm(field)
    return norm(FIELD_SYNONYMS.get(key, key))
