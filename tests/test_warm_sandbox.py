"""常驻沙箱与平台一次性沙箱的结果对照。

真起几次子进程，用来卡住对 harness 私有函数的依赖：成功结果、报错、数据帧必须一致。
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from forge_sandbox import run_script

import warm_sandbox

_SUCCESS = """\
def run(data):
    print("hi")
    return {"n": len(data["issues"]), "x": 1.0}
"""

_BOOM = """\
def run(data):
    return {"n": 1 / 0}
"""

_IMPORT = """\
def run(data):
    import os
    return {"n": 1}
"""

_FRAMES = """\
def run(data):
    return {"note": "留下", "kept": data["issues"]}
"""

_OK = """\
def run(data):
    return {"n": 2}
"""

_SLEEP = """\
def run(data):
    import time
    time.sleep(5)
    return {"n": 1}
"""


def _pair(script: str, datasets: dict[str, Any] | None = None, **kw: Any):
    warm = warm_sandbox.run(script, datasets, **kw)
    real = run_script(script, datasets, **kw)
    return warm, real


def test_warm_worker_matches_the_platform_sandbox():
    frame = pd.DataFrame({"数量": [1, 2], "说明": ["甲", "乙"]})
    warm, real = _pair(_SUCCESS, {"issues": frame})
    pid = warm_sandbox.worker_pid()
    assert pid is not None
    assert warm.ok, warm.error
    assert real.ok, real.error
    assert warm.result == real.result == {"n": 2, "x": 1}
    assert warm.stdout == real.stdout and "hi" in warm.stdout

    warm, real = _pair(_BOOM)
    assert not warm.ok and not real.ok
    assert "<sandbox-script>" in warm.error and "<sandbox-script>" in real.error
    assert "ZeroDivisionError" in warm.error and "ZeroDivisionError" in real.error

    warm, real = _pair(_IMPORT)
    assert not warm.ok and not real.ok
    assert "沙箱禁止 import：os" in warm.error and "沙箱禁止 import：os" in real.error

    warm, real = _pair(_FRAMES, {"issues": frame}, return_frames=True)
    assert warm.ok, warm.error
    assert real.ok, real.error
    assert warm.result == real.result == {"note": "留下"}
    pd.testing.assert_frame_equal(warm.frames["kept"], real.frames["kept"])
    assert warm_sandbox.worker_pid() == pid


def test_warm_worker_restarts_after_a_timeout():
    assert warm_sandbox.run(_OK).ok
    before = warm_sandbox.worker_pid()
    assert before is not None
    out = warm_sandbox.run(_SLEEP, timeout=1)
    assert out.error == "执行超时（>1s），子进程已强制终止"
    assert warm_sandbox.worker_pid() is None
    again = warm_sandbox.run(_OK)
    assert again.ok and again.result == {"n": 2}
    after = warm_sandbox.worker_pid()
    assert after is not None and after != before
