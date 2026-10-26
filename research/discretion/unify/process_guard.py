"""Is the PID holding a lock still running? Dead-holder takeover, live-holder refusal."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


def process_alive(pid) -> bool:
    """宁可误判存活（要求人工 --take-over），绝不误判死亡（自动抢活进程）。"""
    if type(pid) is not int or pid <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return kernel32.GetLastError() == 5      # ACCESS_DENIED ⇒ 进程存在但不属本用户
        try:
            code = ctypes.wintypes.DWORD()
            if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == 259             # STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def lock_holder(lock: Path):
    """读锁文件里的 PID；解析失败返回 None（按死亡处理，但调用方须再确认）。"""
    try:
        text = lock.read_text("ascii", errors="ignore").strip()
        return int(text) if text else None
    except OSError:
        return None
