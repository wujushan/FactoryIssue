"""测试用的常驻沙箱。

平台 `run_script` 每次都新起解释器并 import pandas，单次就要一秒多。这里整次 pytest 只起一个子进程，
作业目录和回读方式与它相同。限制跑在子进程里（`sandbox_worker`），不改本进程的 pandas。

多路放宽统计会同时进来，一个子进程用锁串成一队。超时或协议断了就杀掉，下次调用再起一个。
"""

from __future__ import annotations

import atexit
import json
import queue
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge_sandbox.frames import decode_frames
from forge_sandbox.runner import DEFAULT_MAX_FRAME_BYTES, SandboxOutcome, _STDOUT_LIMIT, _minimal_env

_WORKER = Path(__file__).with_name("sandbox_worker.py")
_READY_TIMEOUT = 60


@dataclass
class _Proc:
    proc: subprocess.Popen[str]
    lines: queue.Queue[str | None]
    stderr: list[str]
    threads: list[threading.Thread] = field(default_factory=list)


@dataclass
class _State:
    worker: _Proc | None = None
    registered: bool = False


_state = _State()
_lock = threading.Lock()


def _stdout_lines(proc: subprocess.Popen[str], lines: queue.Queue[str | None]) -> None:
    if proc.stdout is None:
        lines.put(None)
        return
    for line in proc.stdout:
        lines.put(line.strip())
    lines.put(None)


def _stderr_text(proc: subprocess.Popen[str], bucket: list[str]) -> None:
    if proc.stderr is None:
        return
    bucket.append(proc.stderr.read())


def _kill(worker: _Proc) -> str:
    proc = worker.proc
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    for thread in worker.threads:
        thread.join(timeout=2)
    return "".join(worker.stderr)


def _stop(worker: _Proc) -> str:
    """空闲时先关上 stdin，让子进程自己退出。"""
    proc = worker.proc
    if proc.poll() is None:
        try:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return _kill(worker)
    for thread in worker.threads:
        thread.join(timeout=2)
    return "".join(worker.stderr)


def _discard(worker: _Proc, *, kill: bool) -> str:
    detail = _kill(worker) if kill else _stop(worker)
    if _state.worker is worker:
        _state.worker = None
    return detail


def _boot() -> _Proc:
    # bufsize=1：父进程要是攒着不读，子进程写出 READY 之后会堵在 stdin 上。
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-I", str(_WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_minimal_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines: queue.Queue[str | None] = queue.Queue()
    stderr: list[str] = []
    worker = _Proc(proc=proc, lines=lines, stderr=stderr)
    worker.threads = [
        threading.Thread(target=_stdout_lines, args=(proc, lines), name="warm-sandbox-stdout", daemon=True),
        threading.Thread(target=_stderr_text, args=(proc, stderr), name="warm-sandbox-stderr", daemon=True),
    ]
    for thread in worker.threads:
        thread.start()
    try:
        line = lines.get(timeout=_READY_TIMEOUT)
    except queue.Empty:
        detail = _kill(worker).strip()
        raise RuntimeError(f"常驻沙箱没有就绪：{detail[-2000:] or '无 stderr'}") from None
    if line != "READY":
        detail = _kill(worker).strip()
        extra = detail if line is None else f"{line} {detail}".strip()
        raise RuntimeError(f"常驻沙箱没有就绪：{extra[-2000:] or '无 stderr'}")
    return worker


def _worker() -> _Proc:
    if not _state.registered:
        atexit.register(close)
        _state.registered = True
    current = _state.worker
    if current is not None and current.proc.poll() is None:
        return current
    if current is not None:
        _discard(current, kill=False)
    current = _boot()
    _state.worker = current
    return current


def _crash(worker: _Proc, stdout: str) -> SandboxOutcome:
    proc = worker.proc
    alive = proc.poll() is None
    if alive:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        alive = proc.poll() is None
    detail = _discard(worker, kill=alive).strip()
    rc = proc.returncode
    return SandboxOutcome(
        ok=False,
        error=f"沙箱异常退出（exit={rc}）：{detail[-2000:] or '无 stderr'}",
        stdout=stdout,
        meta={"returncode": rc},
    )


def _read(job: Path, *, return_frames: bool, max_frame_bytes: int) -> SandboxOutcome:
    stdout = ""
    stdout_file = job / "stdout.txt"
    if stdout_file.is_file():
        stdout = stdout_file.read_text(encoding="utf-8", errors="replace")[:_STDOUT_LIMIT]
    result_file = job / "result.json"
    if not result_file.is_file():
        return SandboxOutcome(
            ok=False,
            error="沙箱异常退出（exit=0）：没有写回结果",
            stdout=stdout,
            meta={"returncode": 0},
        )
    text = result_file.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return SandboxOutcome(
            ok=False, error=f"沙箱异常退出（exit=0）：结果不是 JSON（{exc}）", stdout=stdout,
            meta={"returncode": 0},
        )
    if not isinstance(payload, dict):
        return SandboxOutcome(
            ok=False, error="沙箱异常退出（exit=0）：结果不是对象", stdout=stdout, meta={"returncode": 0},
        )
    if not payload.get("ok"):
        return SandboxOutcome(ok=False, error=str(payload.get("error", "")), stdout=stdout)
    meta: dict[str, Any] = {"result_chars": len(text)}
    frames: dict[str, Any] = {}
    frames_file = job / "frames.json"
    if return_frames and frames_file.is_file():
        size = frames_file.stat().st_size
        if size > max_frame_bytes:
            return SandboxOutcome(
                ok=False,
                error=f"数据帧过大（{size} 字节 > {max_frame_bytes}，按每次调用计）",
                stdout=stdout,
                meta={"frame_bytes": size},
            )
        try:
            frames = decode_frames(json.loads(frames_file.read_text(encoding="utf-8")))
        except (ValueError, RecursionError) as exc:
            return SandboxOutcome(
                ok=False, error=f"数据帧回传格式无效：{exc}", stdout=stdout, meta={"frame_bytes": size},
            )
        meta["frame_bytes"] = size
        meta["frame_rows"] = {name: len(df) for name, df in frames.items()}
    return SandboxOutcome(ok=True, result=payload.get("result"), stdout=stdout, meta=meta, frames=frames)


def _submit(worker: _Proc, job: Path, timeout: int, max_chars: int, frame_limit: int, return_frames: bool,
            max_frame_bytes: int) -> SandboxOutcome:
    proc = worker.proc
    try:
        assert proc.stdin is not None
        proc.stdin.write(f"{job}\t{max_chars}\t{frame_limit}\n")
        proc.stdin.flush()
    except OSError:
        return _crash(worker, "")
    try:
        line = worker.lines.get(timeout=timeout)
    except queue.Empty:
        _discard(worker, kill=True)
        return SandboxOutcome(
            ok=False,
            error=f"执行超时（>{timeout}s），子进程已强制终止",
            meta={"timeout": timeout},
        )
    if line is None:
        return _crash(worker, "")
    if line != "DONE":
        detail = _discard(worker, kill=True).strip()
        return SandboxOutcome(
            ok=False,
            error=f"沙箱异常退出（exit=协议）：{line or detail or '无 stderr'}",
            meta={"returncode": proc.returncode},
        )
    return _read(job, return_frames=return_frames, max_frame_bytes=max_frame_bytes)


def run(
    script: str,
    datasets: Mapping[str, Any] | None = None,
    *,
    timeout: int = 60,
    max_output_chars: int = 200_000,
    return_frames: bool = False,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
) -> SandboxOutcome:
    """在常驻子进程里跑脚本。`return_frames` 与字符上限的含义与 `forge_sandbox.run_script` 相同。"""
    if return_frames and max_frame_bytes <= 0:
        raise ValueError("return_frames=True 时 max_frame_bytes 须为正数")
    frame_limit = max_frame_bytes if return_frames else 0
    with _lock:
        worker = _worker()
        with tempfile.TemporaryDirectory(prefix="forge-sandbox-") as directory:
            job = Path(directory)
            (job / "script.py").write_text(script, encoding="utf-8")
            if datasets:
                folder = job / "datasets"
                folder.mkdir()
                for name, frame in datasets.items():
                    frame.to_pickle(folder / f"{name}.pkl")
            return _submit(worker, job, timeout, max_output_chars, frame_limit, return_frames, max_frame_bytes)


def worker_pid() -> int | None:
    with _lock:
        worker = _state.worker
        if worker is None or worker.proc.poll() is not None:
            return None
        return worker.proc.pid


def close() -> None:
    """结束常驻子进程。重复调用没有副作用。"""
    with _lock:
        worker = _state.worker
        _state.worker = None
        if worker is not None:
            _stop(worker)
