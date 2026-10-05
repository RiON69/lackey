"""Mouse and keyboard input through SendInput.

- Every event carries a tag in ``dwExtraInfo`` so hooks can tell our input
  from a human's (the ``injected`` flag cannot: remote-desktop tools set it too).
- A click is one SendInput array (move + down + up), which Windows does not
  interleave with other input.
- Text goes as UTF-16 code units with KEYEVENTF_UNICODE, so it does not depend
  on the active keyboard layout; shortcuts go as virtual keys plus scan codes.
- Keys and buttons we press are tracked and released on ``release_all()``.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from ctypes import wintypes

from .geometry import Point, Rect
from .monitors import virtual_screen

_user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

# dwExtraInfo tags: high word "SV", low word = role.
TAG_PREFIX = 0x53560000
TAG_MASK = 0xFFFF0000
TAG_AGENT = TAG_PREFIX | 0x0001
TAG_OPERATOR = TAG_PREFIX | 0x0002


def is_own_tag(extra_info: int) -> bool:
    return (extra_info & TAG_MASK) == TAG_PREFIX


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]  # noqa: RUF012


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]  # noqa: RUF012


_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT
_user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_user32.MapVirtualKeyW.restype = wintypes.UINT
_user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
_user32.VkKeyScanW.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]


class InputError(RuntimeError):
    code = "INPUT_FAILED"


class InputBlockedUIPIError(InputError):
    code = "INPUT_BLOCKED_UIPI"


class ModifiersHeldError(InputError):
    code = "MODIFIERS_HELD"


class FocusLostError(InputError):
    code = "FOCUS_LOST"


# --- Keys -------------------------------------------------------------------

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_RETURN, VK_TAB = 0x0D, 0x09
VK_MASK = 0xE8  # unassigned; masks a bare Alt tap so it does not open menus

_NAMED_KEYS: dict[str, int] = {
    "shift": VK_LSHIFT,
    "lshift": VK_LSHIFT,
    "rshift": VK_RSHIFT,
    "ctrl": VK_LCONTROL,
    "control": VK_LCONTROL,
    "lctrl": VK_LCONTROL,
    "rctrl": VK_RCONTROL,
    "alt": VK_LMENU,
    "lalt": VK_LMENU,
    "ralt": VK_RMENU,
    "altgr": VK_RMENU,
    "win": VK_LWIN,
    "lwin": VK_LWIN,
    "rwin": VK_RWIN,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "tab": VK_TAB,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "space": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "ins": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "apps": 0x5D,
    "menu": 0x5D,
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "pause": 0x13,
}
_NAMED_KEYS.update({f"f{n}": 0x70 + n - 1 for n in range(1, 25)})

# Keys that need KEYEVENTF_EXTENDEDKEY (otherwise e.g. Left with NumLock types '4').
EXTENDED_VKS = frozenset(
    {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, VK_LWIN, VK_RWIN, 0x5D,
     VK_RCONTROL, VK_RMENU, 0x6F, 0x90}
)
MODIFIER_VKS = frozenset({VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU, VK_LWIN, VK_RWIN})


def key_code(name: str) -> int:
    """Virtual-key code for a key name: named keys, a-z, 0-9, or a single character."""
    key = name.strip().lower()
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
        return ord(key.upper())
    if len(name) == 1:
        scan = _user32.VkKeyScanW(name)
        if scan != -1:
            return scan & 0xFF
    raise ValueError(f"unknown key: {name!r}")


def parse_keys(spec: str | Sequence[str]) -> list[int]:
    """'ctrl+shift+esc' or ['ctrl', 's'] -> virtual-key codes in press order."""
    parts = spec.split("+") if isinstance(spec, str) else list(spec)
    if not parts or any(not p.strip() for p in parts):
        raise ValueError(f"bad key combination: {spec!r}")
    return [key_code(p) for p in parts]


def utf16_units(text: str) -> list[int]:
    """UTF-16 code units, surrogate pairs included."""
    data = text.encode("utf-16-le")
    return [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]


def normalize_absolute(x: int, y: int, screen: Rect) -> tuple[int, int]:
    """Map a physical pixel to the 0..65535 range of MOUSEEVENTF_VIRTUALDESK, aiming at its center."""
    nx = round((x - screen.left + 0.5) * 65536 / screen.width)
    ny = round((y - screen.top + 0.5) * 65536 / screen.height)
    return min(max(nx, 0), 65535), min(max(ny, 0), 65535)


# --- Input driver -------------------------------------------------------------

_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

Precheck = Callable[[str, Point | None], None]
"""Called before input: ``kind`` is 'mouse' or 'keyboard'; raise to cancel."""


class InputDriver:
    """Low-level SendInput driver; one instance per role tag."""

    def __init__(self, *, tag: int = TAG_AGENT, chunk_size: int = 64, precheck: Precheck | None = None):
        self.tag = tag
        self.chunk_size = chunk_size
        self.precheck = precheck
        self._lock = threading.RLock()
        self._held_keys: set[int] = set()
        self._held_buttons: set[str] = set()

    # -- plumbing --

    def _send(self, inputs: Sequence[INPUT]) -> None:
        if not inputs:
            return
        array = (INPUT * len(inputs))(*inputs)
        sent = _user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise InputError(f"SendInput sent {sent} of {len(inputs)} events (error {ctypes.get_last_error()})")

    def _mouse(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
        event = INPUT(type=INPUT_MOUSE)
        event.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, self.tag)
        return event

    def _key(self, vk: int, up: bool, *, scancode_only: bool = False) -> INPUT:
        flags = KEYEVENTF_KEYUP if up else 0
        if vk in EXTENDED_VKS:
            flags |= KEYEVENTF_EXTENDEDKEY
        scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        if scancode_only:
            flags |= KEYEVENTF_SCANCODE
        event = INPUT(type=INPUT_KEYBOARD)
        event.ki = KEYBDINPUT(0 if scancode_only else vk, scan, flags, 0, self.tag)
        return event

    def _unicode(self, unit: int, up: bool) -> INPUT:
        event = INPUT(type=INPUT_KEYBOARD)
        event.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, self.tag)
        return event

    def _move_to(self, x: int, y: int) -> INPUT:
        nx, ny = normalize_absolute(x, y, virtual_screen())
        return self._mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)

    def _check(self, kind: str, point: Point | None = None) -> None:
        if self.precheck is not None:
            self.precheck(kind, point)

    # -- mouse --

    def cursor(self) -> Point:
        point = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(point))
        return Point(point.x, point.y)

    def move(self, x: int, y: int) -> Point:
        with self._lock:
            self._check("mouse", Point(x, y))
            self._send([self._move_to(x, y)])
            return self.cursor()

    def click(
        self,
        x: int,
        y: int,
        *,
        button: str = "left",
        count: int = 1,
        modifiers: Iterable[str] = (),
    ) -> Point:
        """Move and click as one atomic batch; returns where the cursor ended up."""
        down, up = _BUTTONS[button]
        mods = [key_code(m) for m in modifiers]
        with self._lock:
            self._check("mouse", Point(x, y))
            events = [self._key(vk, up=False) for vk in mods]
            events.append(self._move_to(x, y))
            for _ in range(max(1, count)):
                events += [self._mouse(down), self._mouse(up)]
            events += [self._key(vk, up=True) for vk in reversed(mods)]
            self._send(events)
            return self.cursor()

    def mouse_down(self, button: str = "left", x: int | None = None, y: int | None = None) -> None:
        with self._lock:
            point = Point(x, y) if x is not None and y is not None else None
            self._check("mouse", point)
            events = [self._move_to(x, y)] if point else []
            events.append(self._mouse(_BUTTONS[button][0]))
            self._send(events)
            self._held_buttons.add(button)

    def mouse_up(self, button: str = "left", x: int | None = None, y: int | None = None) -> None:
        with self._lock:
            events = [self._move_to(x, y)] if x is not None and y is not None else []
            events.append(self._mouse(_BUTTONS[button][1]))
            self._send(events)
            self._held_buttons.discard(button)

    def drag(self, path: Sequence[Point], *, button: str = "left", step_delay: float = 0.01, steps: int = 12) -> None:
        """Press at the first point, move through the path in small steps, release at the last."""
        if len(path) < 2:
            raise ValueError("drag needs at least two points")
        with self._lock:
            self.mouse_down(button, path[0].x, path[0].y)
            try:
                for start, end in zip(path, path[1:], strict=False):
                    for i in range(1, steps + 1):
                        x = round(start.x + (end.x - start.x) * i / steps)
                        y = round(start.y + (end.y - start.y) * i / steps)
                        self._send([self._move_to(x, y)])
                        time.sleep(step_delay)
            finally:
                self.mouse_up(button, path[-1].x, path[-1].y)

    def scroll(self, *, dy: int = 0, dx: int = 0, x: int | None = None, y: int | None = None) -> None:
        """Wheel notches: dy > 0 scrolls up (away from the user), dx > 0 scrolls right."""
        with self._lock:
            point = Point(x, y) if x is not None and y is not None else None
            self._check("mouse", point)
            events = [self._move_to(x, y)] if point else []
            if dy:
                events.append(self._mouse(MOUSEEVENTF_WHEEL, data=dy * WHEEL_DELTA))
            if dx:
                events.append(self._mouse(MOUSEEVENTF_HWHEEL, data=dx * WHEEL_DELTA))
            self._send(events)

    # -- keyboard --

    def press(self, keys: str | Sequence[str], *, repeat: int = 1, hold: float = 0.0, scancode_only: bool = False) -> None:
        """Press a key or a chord (e.g. 'ctrl+s'); each repetition is one atomic batch."""
        codes = parse_keys(keys)
        with self._lock:
            self._check("keyboard")
            for _ in range(max(1, repeat)):
                downs = [self._key(vk, up=False, scancode_only=scancode_only) for vk in codes]
                ups = [self._key(vk, up=True, scancode_only=scancode_only) for vk in reversed(codes)]
                if hold > 0:
                    self._send(downs)
                    self._held_keys.update(codes)
                    try:
                        time.sleep(hold)
                    finally:
                        self._send(ups)
                        self._held_keys.difference_update(codes)
                else:
                    self._send(downs + ups)

    def key_down(self, key: str) -> None:
        vk = key_code(key)
        with self._lock:
            self._check("keyboard")
            self._send([self._key(vk, up=False)])
            self._held_keys.add(vk)

    def key_up(self, key: str) -> None:
        vk = key_code(key)
        with self._lock:
            self._send([self._key(vk, up=True)])
            self._held_keys.discard(vk)

    def type_text(
        self, text: str, *, newline: str = "enter", chunk_delay: float = 0.0, char_delay: float = 0.0
    ) -> None:
        """Type Unicode text independent of the keyboard layout.

        ``newline``: 'enter' presses Enter, 'shift_enter' presses Shift+Enter
        (a line break in chat inputs that submit on Enter), 'literal' sends the
        character itself. Tabs are sent as the Tab key.

        ``char_delay``: send one character at a time with this pause after it. Apps
        that take Unicode input through the text services slowly (Windows 11 Notepad)
        garble faster text: characters repeat, and Enter overtakes them.
        """
        if newline not in ("enter", "shift_enter", "literal"):
            raise ValueError(f"bad newline mode: {newline}")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        chunk_size = 1 if char_delay > 0 else self.chunk_size
        pause = char_delay if char_delay > 0 else chunk_delay
        with self._lock:
            batch: list[INPUT] = []
            units_in_batch = 0

            def flush() -> None:
                nonlocal batch, units_in_batch
                if batch:
                    self._check("keyboard")
                    self._send(batch)
                    batch, units_in_batch = [], 0
                    if pause:
                        time.sleep(pause)

            for char in text:
                if char == "\n" and newline != "literal":
                    flush()
                    self.press("shift+enter" if newline == "shift_enter" else "enter")
                    continue
                if char == "\t":
                    flush()
                    self.press("tab")
                    continue
                for unit in utf16_units(char):
                    batch += [self._unicode(unit, up=False), self._unicode(unit, up=True)]
                    units_in_batch += 1
                if units_in_batch >= chunk_size:  # a surrogate pair stays together
                    flush()
            flush()

    def unlock_foreground(self) -> None:
        """Masked Alt tap: lets this process call SetForegroundWindow without opening menus."""
        with self._lock:
            self._send([
                self._key(VK_LMENU, up=False),
                self._key(VK_MASK, up=False),
                self._key(VK_MASK, up=True),
                self._key(VK_LMENU, up=True),
            ])

    def release_all(self) -> None:
        """Release every key and button this driver is holding (cancel, emergency stop, errors)."""
        with self._lock:
            events = [self._key(vk, up=True) for vk in sorted(self._held_keys)]
            events += [self._mouse(_BUTTONS[b][1]) for b in sorted(self._held_buttons)]
            self._held_keys.clear()
            self._held_buttons.clear()
            self._send(events)

    def release_modifiers(self) -> None:
        """Send key-up for every modifier (e.g. at start-up after a crash left one down)."""
        with self._lock:
            self._send([self._key(vk, up=True) for vk in sorted(MODIFIER_VKS)])

    def modifiers_held_by_user(self) -> list[str]:
        """Modifiers that are down right now and were not pressed by this driver."""
        names = {VK_LSHIFT: "shift", VK_RSHIFT: "shift", VK_LCONTROL: "ctrl", VK_RCONTROL: "ctrl",
                 VK_LMENU: "alt", VK_RMENU: "alt", VK_LWIN: "win", VK_RWIN: "win"}
        held = {
            name
            for vk, name in names.items()
            if vk not in self._held_keys and _user32.GetAsyncKeyState(vk) & 0x8000
        }
        return sorted(held)
