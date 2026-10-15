#!/usr/bin/env python3
"""安装/卸载本业务模块仓的 git 钩子（跨平台，仅用标准库）。

做的事只有一件：把仓库的 `core.hooksPath` 指到仓内的 `.githooks/`。

**为什么需要这一步、且无法自动化**：git 刻意不允许仓库在 clone 时自动安装钩子——那等于
「clone 即执行任意代码」，是 git 有意的安全设计。所以每个 clone 必须显式 opt-in 一次。

**为什么用 core.hooksPath 而不是往 .git/hooks/ 里拷贝**：`.git/hooks/` 是本地私有、不版本化的，
钩子改了得挨个通知所有人重拷。指到仓内 `.githooks/` 后，钩子本体随 `git pull` 自动更新，
`.git/config` 里只留一个指针。

装上后有什么用：push `v*` tag 之前，本地先比一遍 tag 版本与该 commit 的 pyproject 版本，
不一致就拦下（这是 CI `guard-tag-version` 的本地前置，省掉「推上去才发现、还得删远端 tag」）。
普通分支的 push 不受任何影响。

用法：
    python scripts/install_hooks.py              # 安装（等价于 git config core.hooksPath .githooks）
    python scripts/install_hooks.py --uninstall  # 卸载（git config --unset core.hooksPath）
    python scripts/install_hooks.py --status     # 只看当前配置，不改
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR_NAME = ".githooks"


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8"
    )


def current_hooks_path() -> str:
    return git("config", "--get", "core.hooksPath").stdout.strip()


def main() -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    p = argparse.ArgumentParser(prog="install_hooks", description="安装本业务模块仓 git 钩子")
    p.add_argument("--uninstall", action="store_true", help="取消 core.hooksPath 设置")
    p.add_argument("--status", action="store_true", help="只显示当前配置，不做修改")
    args = p.parse_args()

    if not (REPO_ROOT / ".git").exists():
        print(f"✗ {REPO_ROOT} 不是 git 仓库根", file=sys.stderr)
        return 1

    if args.status:
        cur = current_hooks_path()
        print(f"core.hooksPath = {cur or '（未设置，用默认 .git/hooks）'}")
        print("状态：已安装" if cur == HOOKS_DIR_NAME else "状态：未安装")
        return 0

    if args.uninstall:
        git("config", "--unset", "core.hooksPath")
        print("✓ 已卸载（core.hooksPath 已清除，回到默认 .git/hooks）")
        return 0

    hooks_dir = REPO_ROOT / HOOKS_DIR_NAME
    if not hooks_dir.is_dir():
        print(f"✗ 未找到 {hooks_dir}", file=sys.stderr)
        return 1

    proc = git("config", "core.hooksPath", HOOKS_DIR_NAME)
    if proc.returncode != 0:
        print(f"✗ 设置失败：{proc.stderr.strip()}", file=sys.stderr)
        return 1

    hooks = sorted(h.name for h in hooks_dir.iterdir() if h.is_file())
    print(f"✓ 已安装：core.hooksPath = {HOOKS_DIR_NAME}")
    print(f"  生效的钩子：{', '.join(hooks) or '（空）'}")
    print("  pre-push 会在推送 v* tag 前校验 tag 版本 == pyproject 版本，不一致即拦下。")
    print("  卸载：python scripts/install_hooks.py --uninstall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
