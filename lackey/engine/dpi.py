"""Process DPI awareness.

Windows fixes a process's DPI awareness on the first call that sets it, so the
application must request per-monitor v2 before any library (mss, old lackey)
sets a weaker mode.
"""

from __future__ import annotations

import ctypes
import enum
from ctypes import wintypes

_HANDLE = ctypes.c_void_p

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetDpiAwarenessContextForProcess.restype = _HANDLE
_user32.GetDpiAwarenessContextForProcess.argtypes = [wintypes.HANDLE]
_user32.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
_user32.AreDpiAwarenessContextsEqual.argtypes = [_HANDLE, _HANDLE]
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
_user32.SetProcessDpiAwarenessContext.argtypes = [_HANDLE]


class DpiMode(enum.Enum):
    UNAWARE = "unaware"
    SYSTEM = "system"
    PER_MONITOR = "per_monitor"
    PER_MONITOR_V2 = "per_monitor_v2"
    UNAWARE_GDI_SCALED = "unaware_gdi_scaled"
    UNKNOWN = "unknown"


# DPI_AWARENESS_CONTEXT pseudo-handles are small negative integers.
_CONTEXTS = (
    (-4, DpiMode.PER_MONITOR_V2),
    (-3, DpiMode.PER_MONITOR),
    (-2, DpiMode.SYSTEM),
    (-1, DpiMode.UNAWARE),
    (-5, DpiMode.UNAWARE_GDI_SCALED),
)


class DpiAwarenessError(RuntimeError):
    """The process is already locked into a DPI mode other than per-monitor v2."""


def current_mode() -> DpiMode:
    """Return the DPI awareness mode of the current process."""
    context = _user32.GetDpiAwarenessContextForProcess(None)
    for value, mode in _CONTEXTS:
        if _user32.AreDpiAwarenessContextsEqual(context, _HANDLE(value)):
            return mode
    return DpiMode.UNKNOWN


def ensure_per_monitor_v2(*, strict: bool = False) -> bool:
    """Make the process per-monitor DPI aware (v2) if nobody has chosen a mode yet.

    Returns True when the process ends up in per-monitor v2. If another mode
    was set earlier, Windows does not allow changing it: return False, or raise
    DpiAwarenessError when ``strict`` is set.
    """
    mode = current_mode()
    if mode is DpiMode.PER_MONITOR_V2:
        return True
    if mode in (DpiMode.UNAWARE, DpiMode.UNKNOWN) and _user32.SetProcessDpiAwarenessContext(
        _HANDLE(-4)
    ):
        return True
    if strict:
        raise DpiAwarenessError(
            f"process DPI mode is '{current_mode().value}'; per-monitor v2 must be requested "
            "before any library sets DPI awareness"
        )
    return current_mode() is DpiMode.PER_MONITOR_V2
