from __future__ import annotations

import pytest

from factory_issue_module.config import files


@pytest.fixture(autouse=True)
def _fresh_config_cache():
    """配置解析结果按（文件名, 版本号）缓存在进程内；各用例的假配置版本号会撞，用例之间清掉。"""
    files._cache.clear()
    yield
    files._cache.clear()


def pytest_sessionfinish() -> None:
    """常驻沙箱跟整次 pytest 走，结束时关掉，避免留下子进程。"""
    import warm_sandbox

    warm_sandbox.close()
