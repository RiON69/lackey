"""Starting applications without a shell and waiting for their windows."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import winreg
from pathlib import Path

from . import windows

_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
_SCRIPT_SUFFIXES = frozenset({".bat", ".cmd", ".ps1", ".vbs", ".js", ".wsf"})


class LaunchError(RuntimeError):
    code = "LAUNCH_FAILED"


def _checked(path: Path) -> Path:
    suffix = path.suffix.lower()
    if suffix in _SCRIPT_SUFFIXES:
        raise LaunchError(f"script targets run through a shell and are not allowed: {path}")
    if suffix != ".exe":
        raise LaunchError(f"not an executable: {path}")
    return path


def resolve(app: str) -> Path:
    """Absolute path -> App Paths registry (HKCU, HKLM) -> PATH; .exe only."""
    candidate = Path(os.path.expandvars(app))
    if candidate.is_absolute():
        if not candidate.is_file():
            raise LaunchError(f"executable not found: {candidate}")
        return _checked(candidate)
    name = app if app.lower().endswith(".exe") else f"{app}.exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"{_APP_PATHS}\{name}") as key:
                value, _ = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        path = Path(os.path.expandvars(str(value).strip().strip('"')))
        if path.is_file():
            return _checked(path)
    found = shutil.which(name)
    if found:
        return _checked(Path(found))
    raise LaunchError(f"cannot resolve application: {app}")


def snapshot() -> set[int]:
    """Handles of the top-level windows that exist right now."""
    return {w.hwnd for w in windows.list_windows(include_cloaked=True, include_untitled=True)}


def start(app: str, args: list[str] | None = None, *, cwd: str | None = None) -> subprocess.Popen:
    path = resolve(app)
    try:
        return subprocess.Popen(  # noqa: S603 - resolved .exe, argument list, no shell
            [str(path), *(args or [])],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as error:
        raise LaunchError(f"failed to start {path}: {error}") from error


def wait_new_window(
    before: set[int],
    *,
    title: str | None = None,
    process: str | None = None,
    class_name: str | None = None,
    timeout: float = 15.0,
) -> windows.WindowInfo:
    """Wait for a visible, non-cloaked top-level window that was not in ``before``.

    Matching is by window, not PID: many apps start a stub process or hand the
    request to an already running instance (Windows 11 Notepad, VS Code, browsers).
    """
    title_re = re.compile(title, re.IGNORECASE) if title else None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for info in windows.list_windows():
            if info.hwnd in before:
                continue
            if title_re and not title_re.search(info.title):
                continue
            if process and info.process.lower() != process.lower():
                continue
            if class_name and info.class_name != class_name:
                continue
            return info
        time.sleep(0.1)
    raise windows.WindowNotFoundError("no new window matched within the timeout")
