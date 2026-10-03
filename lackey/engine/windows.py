"""Top-level windows: enumeration, activation, integrity levels."""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .geometry import Rect

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GA_ROOT = 2
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25

# Mandatory integrity level RIDs.
INTEGRITY_LOW = 0x1000
INTEGRITY_MEDIUM = 0x2000
INTEGRITY_HIGH = 0x3000
INTEGRITY_SYSTEM = 0x4000

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsHungAppWindow.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
_advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
_advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)


class WindowError(RuntimeError):
    code = "WINDOW_ERROR"


class WindowNotFoundError(WindowError):
    code = "WINDOW_NOT_FOUND"


class WindowNotRespondingError(WindowError):
    code = "WINDOW_NOT_RESPONDING"


class FocusError(WindowError):
    code = "FOCUS_LOST"


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int
    process: str
    rect: Rect
    visible: bool
    minimized: bool
    cloaked: bool
    foreground: bool


def _text(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def process_path(pid: int) -> str:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def window_rect(hwnd: int) -> Rect:
    """Visible frame bounds without the invisible resize borders of Windows 10/11."""
    rect = wintypes.RECT()
    if _dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
    ) != 0:
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return Rect.from_ltrb(rect.left, rect.top, rect.right, rect.bottom)


def is_cloaked(hwnd: int) -> bool:
    """Cloaked windows sit on another virtual desktop or are suspended UWP frames."""
    cloaked = wintypes.DWORD()
    if _dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    ) != 0:
        return False
    return bool(cloaked.value)


def get_window(hwnd: int) -> WindowInfo:
    if not _user32.IsWindow(hwnd):
        raise WindowNotFoundError(f"window {hwnd} does not exist")
    pid = window_pid(hwnd)
    return WindowInfo(
        hwnd=int(hwnd),
        title=_text(hwnd),
        class_name=_class_name(hwnd),
        pid=pid,
        process=Path(process_path(pid)).name,
        rect=window_rect(hwnd),
        visible=bool(_user32.IsWindowVisible(hwnd)),
        minimized=bool(_user32.IsIconic(hwnd)),
        cloaked=is_cloaked(hwnd),
        foreground=_user32.GetForegroundWindow() == hwnd,
    )


def list_windows(*, include_cloaked: bool = False, include_untitled: bool = False) -> list[WindowInfo]:
    """Visible top-level windows in z-order (topmost first)."""
    handles: list[int] = []

    def collect(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            handles.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(collect), 0)
    result: list[WindowInfo] = []
    for hwnd in handles:
        try:
            info = get_window(hwnd)
        except WindowNotFoundError:
            continue
        if info.cloaked and not include_cloaked:
            continue
        if not info.title and not include_untitled:
            continue
        result.append(info)
    return result


def foreground_window() -> int:
    return int(_user32.GetForegroundWindow() or 0)


def root_window(hwnd: int) -> int:
    return int(_user32.GetAncestor(hwnd, GA_ROOT) or hwnd)


def window_from_point(x: int, y: int) -> int:
    """Top-level window under a physical point (0 when none)."""
    hwnd = _user32.WindowFromPoint(wintypes.POINT(x, y))
    return root_window(hwnd) if hwnd else 0


def is_hung(hwnd: int) -> bool:
    return bool(_user32.IsHungAppWindow(hwnd))


def _token_integrity(token: int) -> int | None:
    needed = wintypes.DWORD()
    _advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(needed))
    if not needed.value:
        return None
    buffer = ctypes.create_string_buffer(needed.value)
    if not _advapi32.GetTokenInformation(
        token, TOKEN_INTEGRITY_LEVEL, buffer, needed, ctypes.byref(needed)
    ):
        return None
    sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_MANDATORY_LABEL.Label.Sid
    count = _advapi32.GetSidSubAuthorityCount(sid).contents.value
    return int(_advapi32.GetSidSubAuthority(sid, count - 1).contents.value)


def _process_handle_integrity(process: int) -> int | None:
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        return _token_integrity(token.value)
    finally:
        _kernel32.CloseHandle(token)


def current_integrity() -> int:
    level = _process_handle_integrity(_kernel32.GetCurrentProcess())
    return level if level is not None else INTEGRITY_MEDIUM


def process_integrity(pid: int) -> int | None:
    """Integrity RID of a process, or None when it cannot be read (treat as higher)."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _process_handle_integrity(handle)
    finally:
        _kernel32.CloseHandle(handle)


def input_blocked_by_uipi(hwnd: int) -> bool:
    """True when Windows would silently drop our input to this window (UIPI)."""
    if not hwnd:
        return False
    target = process_integrity(window_pid(hwnd))
    return target is None or target > current_integrity()


def show(hwnd: int, how: str) -> None:
    commands = {"maximize": SW_MAXIMIZE, "minimize": SW_MINIMIZE, "restore": SW_RESTORE}
    if how not in commands:
        raise ValueError(f"unknown show command: {how}")
    _user32.ShowWindow(hwnd, commands[how])


def close(hwnd: int) -> None:
    """Ask the window to close (WM_CLOSE); the application may show a dialog."""
    _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def activate(
    hwnd: int,
    *,
    unlock_foreground: Callable[[], None] | None = None,
    timeout: float = 2.0,
) -> None:
    """Bring a window to the foreground and verify that it got there.

    ``unlock_foreground`` sends a harmless tagged keystroke (masked Alt) so the
    foreground-lock rules let this process call SetForegroundWindow.
    """
    if not _user32.IsWindow(hwnd):
        raise WindowNotFoundError(f"window {hwnd} does not exist")
    if is_hung(hwnd):
        raise WindowNotRespondingError(f"window {hwnd} is not responding")
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
    target = root_window(hwnd)
    if foreground_window() == target:
        return
    if unlock_foreground is not None:
        unlock_foreground()
    _user32.SetForegroundWindow(target)
    _user32.BringWindowToTop(target)
    if _wait_foreground(target, timeout / 2):
        return
    # Fallback: share input state with the current foreground thread.
    current = foreground_window()
    if current and is_hung(current):
        raise WindowNotRespondingError(f"foreground window {current} is not responding")
    our_thread = _kernel32.GetCurrentThreadId()
    their_thread = _user32.GetWindowThreadProcessId(current, None) if current else 0
    attached = bool(their_thread) and bool(_user32.AttachThreadInput(our_thread, their_thread, True))
    try:
        _user32.SetForegroundWindow(target)
        _user32.BringWindowToTop(target)
    finally:
        if attached:
            _user32.AttachThreadInput(our_thread, their_thread, False)
    if not _wait_foreground(target, timeout / 2):
        raise FocusError(f"window {hwnd} did not become the foreground window")


def _wait_foreground(hwnd: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if foreground_window() == hwnd:
            return True
        time.sleep(0.02)
    return foreground_window() == hwnd
