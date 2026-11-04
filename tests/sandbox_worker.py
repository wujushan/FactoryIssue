"""常驻沙箱子进程（只由 `warm_sandbox` 用 `python -I` 拉起，不是用例）。

进程里 import pandas 一次，再收紧网络和文件读写。收紧会改掉这个进程里的 pandas，所以读数据集用事先留
下的 `read_pickle`。不设 CPU 时间上限：这是长驻进程，加上去整轮测试跑不完。

执行方式与 `forge_sandbox.harness.main` 对齐：受限 builtins、`"<sandbox-script>"`、数字归一、数据帧通道、
超限时的原句。协议走真正的 stdout（`READY` / `DONE`），脚本的 `print` 改记到 `stdout.txt`。
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from forge_sandbox.harness import (
    SandboxViolation,
    _SAFE_BUILTIN_NAMES,
    _OutputRejected,
    _harden,
    _normalize_numbers,
    _restricted_import,
    _split_frames,
)


def _execute(job: Path, max_chars: int, max_frame_bytes: int, pd: Any, np: Any,
             read_pickle: Any) -> tuple[str, str | None]:
    """跑一次，返回 result.json 正文，以及数据帧正文或 None。"""
    frames_payload = None
    try:
        data: dict[str, Any] = {}
        datasets_dir = job / "datasets"
        if datasets_dir.is_dir():
            for path in sorted(datasets_dir.glob("*.pkl")):
                data[path.stem] = read_pickle(path)
        script = (job / "script.py").read_text(encoding="utf-8")
        safe_builtins = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}
        safe_builtins["__import__"] = _restricted_import
        safe_builtins["True"] = True
        safe_builtins["False"] = False
        safe_builtins["None"] = None
        scope = {"__builtins__": safe_builtins, "__name__": "__sandbox__", "pd": pd, "np": np}
        exec(compile(script, "<sandbox-script>", "exec"), scope)  # noqa: S102 — 与 harness 同一处执行
        fn = scope.get("run")
        if not callable(fn):
            raise SandboxViolation("脚本必须定义 run(data) 函数")
        result = fn(data)
        if result is None or not isinstance(result, (dict, list)):
            raise SandboxViolation(
                f"run(data) 必须返回非空 dict（实际返回 {type(result).__name__}）；"
                "请确保函数以 return 一个含统计结果的 dict 结束"
            )
        if max_frame_bytes > 0 and isinstance(result, dict):
            frames, result = _split_frames(result, pd, np)
            frames_payload = json.dumps({"frames": frames}, ensure_ascii=False)
            size = len(frames_payload.encode("utf-8"))
            if size > max_frame_bytes:
                raise _OutputRejected(
                    f"数据帧过大（{size} 字节 > {max_frame_bytes}，按每次调用计），"
                    "请在脚本内进一步聚合，或只回传需要的列"
                )
        result = _normalize_numbers(result)
        payload = json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
        if len(payload) > max_chars:
            frames_payload = None
            hint = "请在脚本内聚合后再返回"
            if max_frame_bytes > 0:
                hint += "；要回传明细帧，请把 DataFrame 直接放在返回 dict 的顶层（走数据帧通道）"
            payload = json.dumps(
                {"ok": False, "error": f"结果过大（{len(payload)} 字符 > {max_chars}），{hint}"},
                ensure_ascii=False,
            )
        return payload, frames_payload
    except _OutputRejected as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), None
    except BaseException:  # noqa: BLE001 — 脚本失败留下 traceback，进程继续接下一次
        return json.dumps(
            {"ok": False, "error": traceback.format_exc(limit=20)}, ensure_ascii=False
        ), None


def _run_job(job: Path, max_chars: int, max_frame_bytes: int, pd: Any, np: Any, read_pickle: Any) -> None:
    protocol = sys.stdout
    buffer = io.StringIO()
    sys.stdout = buffer
    try:
        payload, frames_payload = _execute(job, max_chars, max_frame_bytes, pd, np, read_pickle)
    finally:
        sys.stdout = protocol
        (job / "stdout.txt").write_text(buffer.getvalue(), encoding="utf-8")
    (job / "result.json").write_text(payload, encoding="utf-8")
    if frames_payload is not None:
        (job / "frames.json").write_text(frames_payload, encoding="utf-8")


def main() -> None:
    import numpy as np
    import pandas as pd

    # 收紧之后 pd.read_pickle 会变成拒绝函数；数据集是父进程写的，用原来的函数读。
    read_pickle = pd.read_pickle
    _harden(pd)
    anchor = Path(tempfile.gettempdir())
    protocol = sys.stdout
    try:
        protocol.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    protocol.write("READY\n")
    protocol.flush()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        job: Path | None = None
        try:
            job_s, chars_s, frames_s = line.split("\t")
            job = Path(job_s)
            # 与一次性 harness 一样，脚本的当前目录是这次的作业目录。删目录前必须走出去，否则 Windows 删不掉。
            os.chdir(job)
            try:
                _run_job(job, int(chars_s), int(frames_s), pd, np, read_pickle)
            finally:
                os.chdir(anchor)
        except Exception:
            if job is not None and not (job / "result.json").is_file():
                (job / "result.json").write_text(
                    json.dumps(
                        {"ok": False, "error": traceback.format_exc(limit=20)}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
        protocol.write("DONE\n")
        protocol.flush()


if __name__ == "__main__":
    main()
