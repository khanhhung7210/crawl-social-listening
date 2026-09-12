"""Helpers for pipeline/continuous subprocesses (live logs + Windows process trees)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Mapping, Sequence


def terminate_process_tree(proc: subprocess.Popen, *, grace_s: float = 3.0) -> None:
    """Kill *proc* and descendants. Critical on Windows where kill() is not recursive."""
    if proc.poll() is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        deadline = time.time() + max(1.0, grace_s)
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        return

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except Exception:
            pass
    deadline = time.time() + max(1.0, grace_s)
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.2)
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:
                pass


def run_streaming(
    cmd: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> int:
    """
    Run a child with stdout/stderr inherited (live logs in the parent console).

    On timeout, kills the whole process tree (needed for nested Selenium children).
    """
    popen_kwargs: dict = {
        "cwd": str(cwd),
        "env": dict(env) if env is not None else None,
        "stdout": None,
        "stderr": None,
    }
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(list(cmd), **popen_kwargs)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_tree(proc)
        raise
