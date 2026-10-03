"""Display monitors with physical bounds and per-monitor DPI."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from .geometry import Rect

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shcore = ctypes.WinDLL("shcore", use_last_error=True)

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
MONITORINFOF_PRIMARY = 0x1
MDT_EFFECTIVE_DPI = 0


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)
_user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    _MONITORENUMPROC,
    wintypes.LPARAM,
]
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFOEXW)]
_shcore.GetDpiForMonitor.argtypes = [
    wintypes.HMONITOR,
    ctypes.c_int,
    ctypes.POINTER(wintypes.UINT),
    ctypes.POINTER(wintypes.UINT),
]


@dataclass(frozen=True)
class Monitor:
    index: int
    rect: Rect
    work_area: Rect
    dpi: int
    primary: bool
    device: str

    @property
    def scale(self) -> float:
        """Scale factor relative to 96 DPI (1.5 for 150 %)."""
        return self.dpi / 96


def _rect(r: wintypes.RECT) -> Rect:
    return Rect.from_ltrb(r.left, r.top, r.right, r.bottom)


def list_monitors() -> list[Monitor]:
    """All monitors in enumeration order; physical pixels require per-monitor DPI awareness."""
    handles: list[int] = []

    def collect(hmonitor, _hdc, _rect_ptr, _data):
        handles.append(hmonitor)
        return True

    _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(collect), 0)
    monitors: list[Monitor] = []
    for index, handle in enumerate(handles):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not _user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            continue
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        dpi = 96
        if _shcore.GetDpiForMonitor(handle, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            dpi = int(dpi_x.value)
        monitors.append(
            Monitor(
                index=index,
                rect=_rect(info.rcMonitor),
                work_area=_rect(info.rcWork),
                dpi=dpi,
                primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                device=info.szDevice,
            )
        )
    return monitors


def virtual_screen() -> Rect:
    """Bounding rectangle of all monitors (its origin can be negative)."""
    metric = _user32.GetSystemMetrics
    return Rect(
        metric(SM_XVIRTUALSCREEN),
        metric(SM_YVIRTUALSCREEN),
        metric(SM_CXVIRTUALSCREEN),
        metric(SM_CYVIRTUALSCREEN),
    )


def monitor_at(x: int, y: int) -> Monitor | None:
    for monitor in list_monitors():
        if monitor.rect.contains(x, y):
            return monitor
    return None


def primary_monitor() -> Monitor:
    monitors = list_monitors()
    for monitor in monitors:
        if monitor.primary:
            return monitor
    return monitors[0]
