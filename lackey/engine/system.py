"""Desktop and session state: input desktop, remote session, idle time, cursor."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .geometry import Point

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2
SM_REMOTESESSION = 0x1000

_user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_user32.OpenInputDesktop.restype = wintypes.HANDLE
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_user32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_kernel32.GetTickCount.restype = wintypes.DWORD


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]  # noqa: RUF012


_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]


def input_desktop_name() -> str | None:
    """Name of the desktop that receives input ('Default' when the user's desktop is active).

    None means it cannot be opened, which is what a locked workstation or the UAC
    secure desktop looks like from a user-session process.
    """
    desktop = _user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not desktop:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not _user32.GetUserObjectInformationW(
            desktop, UOI_NAME, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)
        ):
            return None
        return buffer.value
    finally:
        _user32.CloseDesktop(desktop)


def desktop_available() -> bool:
    return input_desktop_name() == "Default"


def is_remote_session() -> bool:
    return bool(_user32.GetSystemMetrics(SM_REMOTESESSION))


def last_input_tick() -> int:
    """GetTickCount() value of the last input event in this session (any source)."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    _user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def tick_count() -> int:
    return int(_kernel32.GetTickCount())


def idle_ms() -> int:
    """Milliseconds since the last input event of any source (ours included)."""
    return (tick_count() - last_input_tick()) & 0xFFFFFFFF


def cursor_position() -> Point:
    point = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return Point(point.x, point.y)


# --- Session state (WTS) -------------------------------------------------------

_wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
_wtsapi32.WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.DWORD),
]
_wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]

WTS_CURRENT_SERVER_HANDLE = None
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_SESSION_INFO_EX = 25
WTS_ACTIVE = 0
WTS_DISCONNECTED = 4
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1


def session_state() -> tuple[int, int] | None:
    """(connect state, lock flags) of the current session, or None when unavailable.

    Connect state: 0 active, 4 disconnected (see WTS_CONNECTSTATE_CLASS).
    Lock flags: 0 locked, 1 unlocked, -1 unknown.
    """
    buffer = ctypes.c_void_p()
    size = wintypes.DWORD()
    if not _wtsapi32.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTS_SESSION_INFO_EX, ctypes.byref(buffer), ctypes.byref(size)
    ):
        return None
    try:
        raw = ctypes.string_at(buffer, size.value)
        # WTSINFOEXW: DWORD Level; then an 8-byte aligned union whose LEVEL1 starts with
        # SessionId, SessionState, SessionFlags.
        state = int.from_bytes(raw[12:16], "little", signed=True)
        flags = int.from_bytes(raw[16:20], "little", signed=True)
        return state, flags
    finally:
        _wtsapi32.WTSFreeMemory(buffer)


def session_locked() -> bool:
    state = session_state()
    return state is not None and state[1] == WTS_SESSIONSTATE_LOCK


def session_disconnected() -> bool:
    state = session_state()
    return state is not None and state[0] == WTS_DISCONNECTED
