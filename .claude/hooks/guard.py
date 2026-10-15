#!/usr/bin/env python3
"""G1 闸门 guard（PreToolUse hook，移植 DataForge 设计的精简版）。

拦截规则（命中 exit 2 阻断，理由回灌给编程助手）：
- A. 写 src/**：G1 未完成（docs/2_landed 无实质文档，或 docs/open-questions.md 仍有未决项）
     且无显式放行标记 docs/.g1-cleared 时阻断。
- B. 写 .env / .env.*（.env.example 除外）。

设计原则：**失败放行**——guard 自身出错时放行（绝不因 guard bug 卡死工作流），
本 hook 是软约束文档（CLAUDE.md/AGENTS.md）之上的硬兜底。
"""

import json
import re
import sys
from pathlib import Path

# db_description 表文件的 source 声明标记：CN 标签「数据源别名」或前缀式 `source:` / `- source：`
_SOURCE_RE = re.compile(r"数据源别名|^\s*[-*]?\s*\**\s*source\b\s*[:：]", re.IGNORECASE | re.MULTILINE)


def deny(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


def g1_passed(root: Path) -> bool:
    if (root / "docs" / ".g1-cleared").exists():
        return True  # 显式放行（留痕，操作者主动跳过）
    landed = root / "docs" / "2_landed"
    # 实质文档：business_description.md，或 db_description/ 下非 README 的 .md
    has_landed_docs = (
        (landed / "business_description.md").exists()
        or any(
            f.suffix == ".md" and f.name != "README.md"
            for f in landed.rglob("*.md")
        )
    ) if landed.is_dir() else False
    if not has_landed_docs:
        return False
    oq = root / "docs" / "open-questions.md"
    if oq.exists():
        body = oq.read_text(encoding="utf-8", errors="ignore")
        # 存在未勾选的清单项（行首 `- [ ]`）视为未清零；行内/引用块里的解释性文本不算
        if any(line.lstrip().startswith("- [ ]") for line in body.splitlines()):
            return False
    return True


def db_desc_missing_source(root: Path) -> list[str]:
    """列出 db_description 下缺 source（所属实例/数据源别名）声明的表文件（一表一 source）。

    每张 db_description 表文件须标注它属于哪个数据源别名（info/erp/forge_mart_<模块编码>），
    别名并集要与 manifest.data_sources 一致。缺声明的返回相对路径列表（供 G1 gate 阻断）。
    """
    desc_dir = root / "docs" / "2_landed" / "db_description"
    if not desc_dir.is_dir():
        return []
    missing: list[str] = []
    for f in sorted(desc_dir.rglob("*.md")):
        if f.name == "README.md":
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        if not _SOURCE_RE.search(text):
            missing.append(f.relative_to(root).as_posix())
    return missing


def main() -> None:
    # Windows 控制台/管道默认 locale 编码可能打不出中文理由（退化成 \uXXXX 转义），强制 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Write", "Edit"):
        sys.exit(0)
    raw = data.get("tool_input", {}).get("file_path") or ""
    if not raw:
        sys.exit(0)
    root = Path(__file__).resolve().parents[2]
    try:
        rel = Path(raw).resolve().relative_to(root)
    except (ValueError, OSError):
        sys.exit(0)  # 仓库之外的路径不归本 guard 管
    posix = rel.as_posix()

    if posix.startswith(".env") and posix != ".env.example":
        deny("硬约束：.env 永不入库、不由编程助手直接写入。改用 .env.example 说明配置项。")

    if posix.startswith("src/"):
        if not g1_passed(root):
            deny(
                "G1 闸门：业务逻辑梳理未完成（docs/2_landed 缺实质文档——需 business_description.md 或 "
                "db_description/*.md，或 docs/open-questions.md 存在未决项 '- [ ]'），不得编写 src/ 业务代码。\n"
                "正道：先完成 G1 梳理落盘并清零歧义清单；确需跳过时创建 docs/.g1-cleared（留痕放行）。"
            )
        # 显式放行（docs/.g1-cleared）时跳过 source 硬拦，尊重操作者主动放行意图
        if not (root / "docs" / ".g1-cleared").exists():
            missing = db_desc_missing_source(root)
            if missing:
                deny(
                    "G1 闸门：以下 db_description 表文件缺【数据源别名（source）】声明，不得编写 src/：\n  - "
                    + "\n  - ".join(missing)
                    + "\n每张表须标注所属实例/数据源别名（info/erp/forge_mart_<模块编码>），别名并集须与 "
                    "manifest.data_sources 一致（模块源数据可横跨多实例）。"
                )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # 失败放行
