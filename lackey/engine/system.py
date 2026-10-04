"""Desktop and session state: input desktop, remote session, idle time, cursor, and the
settings that change how windows look (theme, contrast, text size, accent, HDR)."""

from __future__ import annotations

import ctypes
import winreg
from ctypes import wintypes
from dataclasses import asdict, dataclass

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


# --- Settings that change pixels at the same DPI ----------------------------------

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
DWM = r"Software\Microsoft\Windows\DWM"
ACCESSIBILITY = r"Software\Microsoft\Accessibility"
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x0001


@dataclass(frozen=True)
class Environment:
    """Settings that change how the same window looks at the same DPI. An image pattern
    taken under one of them may not match under another."""

    apps_theme: str  # "light" or "dark" (Settings > Personalization > Colors)
    system_theme: str
    high_contrast: bool
    text_scale: int  # percent, 100..225 (Settings > Accessibility > Text size)
    accent: str | None  # "#rrggbb"
    transparency: bool
    hdr: bool | None  # an active display shows advanced color (HDR); None: unknown

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class _HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("lpszDefaultScheme", wintypes.LPWSTR)]  # noqa: RUF012


_user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
_user32.SystemParametersInfoW.restype = wintypes.BOOL


def _reg_dword(path: str, name: str) -> int | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return int(value) & 0xFFFFFFFF if kind == winreg.REG_DWORD else None


def accent_hex(abgr: int) -> str:
    """DWM's AccentColor (0xAABBGGRR) as "#rrggbb"."""
    return f"#{abgr & 0xFF:02x}{(abgr >> 8) & 0xFF:02x}{(abgr >> 16) & 0xFF:02x}"


def high_contrast() -> bool:
    info = _HIGHCONTRASTW()
    info.cbSize = ctypes.sizeof(_HIGHCONTRASTW)
    if not _user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, info.cbSize, ctypes.byref(info), 0):
        return False
    return bool(info.dwFlags & HCF_HIGHCONTRASTON)


def environment() -> Environment:
    """Read the current settings (registry and system parameters; nothing changes)."""
    accent = _reg_dword(DWM, "AccentColor")
    hdr: bool | None
    try:
        hdr = hdr_enabled()
    except OSError:
        hdr = None
    return Environment(
        apps_theme="dark" if _reg_dword(PERSONALIZE, "AppsUseLightTheme") == 0 else "light",
        system_theme="dark" if _reg_dword(PERSONALIZE, "SystemUsesLightTheme") == 0 else "light",
        high_contrast=high_contrast(),
        text_scale=_reg_dword(ACCESSIBILITY, "TextScaleFactor") or 100,
        accent=accent_hex(accent) if accent is not None else None,
        transparency=_reg_dword(PERSONALIZE, "EnableTransparency") != 0,
        hdr=hdr,
    )


# --- Advanced color (HDR) through the display configuration API ---------------------

QDC_ONLY_ACTIVE_PATHS = 0x00000002
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9
_MODE_INFO_SIZE = 64  # sizeof(DISPLAYCONFIG_MODE_INFO); only counted, never read


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]  # noqa: RUF012


class _PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("statusFlags", ctypes.c_uint32),
    ]


class _PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("scaling", ctypes.c_uint32),
        ("refreshNumerator", ctypes.c_uint32),
        ("refreshDenominator", ctypes.c_uint32),
        ("scanLineOrdering", ctypes.c_uint32),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", ctypes.c_uint32),
    ]


class _PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", _PATH_SOURCE_INFO), ("targetInfo", _PATH_TARGET_INFO), ("flags", ctypes.c_uint32)]  # noqa: RUF012


class _DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("type", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
    ]


class _ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("header", _DEVICE_INFO_HEADER),
        ("value", ctypes.c_uint32),  # bit 0 supported, bit 1 enabled
        ("colorEncoding", ctypes.c_uint32),
        ("bitsPerColorChannel", ctypes.c_uint32),
    ]


_user32.GetDisplayConfigBufferSizes.argtypes = [
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_uint32),
]
_user32.GetDisplayConfigBufferSizes.restype = ctypes.c_long
_user32.QueryDisplayConfig.argtypes = [
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_user32.QueryDisplayConfig.restype = ctypes.c_long
_user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
_user32.DisplayConfigGetDeviceInfo.restype = ctypes.c_long


def hdr_enabled() -> bool:
    """True when an active display has advanced color (HDR) on; OSError if Windows says no."""
    paths, modes = ctypes.c_uint32(), ctypes.c_uint32()
    error = _user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths), ctypes.byref(modes))
    if error:
        raise OSError(error, "GetDisplayConfigBufferSizes failed")
    path_buffer = (_PATH_INFO * max(1, paths.value))()
    mode_buffer = ctypes.create_string_buffer(_MODE_INFO_SIZE * max(1, modes.value))
    error = _user32.QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS, ctypes.byref(paths), path_buffer, ctypes.byref(modes), mode_buffer, None
    )
    if error:
        raise OSError(error, "QueryDisplayConfig failed")
    for path in path_buffer[: paths.value]:
        info = _ADVANCED_COLOR_INFO()
        info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
        info.header.size = ctypes.sizeof(_ADVANCED_COLOR_INFO)
        info.header.adapterId = path.targetInfo.adapterId
        info.header.id = path.targetInfo.id
        if _user32.DisplayConfigGetDeviceInfo(ctypes.byref(info.header)) == 0 and info.value & 0x2:
            return True
    return False
