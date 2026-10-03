"""High-level desktop facade: capture + input + windows with safety pre-checks."""

from __future__ import annotations

from . import launch, system, windows
from .capture import Frame, MssCapture
from .dpi import ensure_per_monitor_v2
from .geometry import Point, Rect
from .input import (
    TAG_AGENT,
    InputBlockedUIPIError,
    InputDriver,
    InputError,
    ModifiersHeldError,
)
from .monitors import Monitor, list_monitors, primary_monitor, virtual_screen


class DesktopUnavailableError(InputError):
    code = "DESKTOP_UNAVAILABLE"


class ScreenLockedError(DesktopUnavailableError):
    code = "SCREEN_LOCKED"


class SecureDesktopError(DesktopUnavailableError):
    code = "SECURE_DESKTOP"


class SessionDisconnectedError(DesktopUnavailableError):
    code = "SESSION_DISCONNECTED"


def check_desktop_state() -> None:
    """Raise when the user's desktop cannot be captured or driven right now."""
    state = system.session_state()
    if state is not None:
        connect, lock = state
        if connect == system.WTS_DISCONNECTED:
            raise SessionDisconnectedError("the session is disconnected")
        if lock == system.WTS_SESSIONSTATE_LOCK:
            raise ScreenLockedError("the workstation is locked")
    if system.input_desktop_name() != "Default":
        raise SecureDesktopError("another desktop (UAC prompt or logon screen) has the input")


class Desktop:
    """The user's desktop as seen and driven by one client role."""

    def __init__(self, *, tag: int = TAG_AGENT, check_uipi: bool = True, check_modifiers: bool = True):
        ensure_per_monitor_v2()
        self.check_uipi = check_uipi
        self.check_modifiers = check_modifiers
        self.capture = MssCapture()
        self.input = InputDriver(tag=tag, precheck=self._precheck)

    # -- pre-checks --

    def _precheck(self, kind: str, point: Point | None) -> None:
        check_desktop_state()
        if kind == "mouse" and point is not None:
            target = windows.window_from_point(point.x, point.y)
        else:
            target = windows.foreground_window()
        if kind == "keyboard" and self.check_modifiers:
            held = self.input.modifiers_held_by_user()
            if held:
                raise ModifiersHeldError(f"modifiers held by the user: {', '.join(held)}")
        if self.check_uipi and windows.input_blocked_by_uipi(target):
            raise InputBlockedUIPIError(f"window {target} runs at a higher integrity level")

    # -- observation --

    def monitors(self) -> list[Monitor]:
        return list_monitors()

    def screenshot(self, rect: Rect | None = None) -> Frame:
        """Capture a rectangle (default: the primary monitor)."""
        return self.capture.grab(rect or primary_monitor().rect)

    def virtual_screen(self) -> Rect:
        return virtual_screen()

    # -- windows and apps --

    def activate(self, hwnd: int, *, timeout: float = 2.0) -> None:
        check_desktop_state()
        windows.activate(hwnd, unlock_foreground=self.input.unlock_foreground, timeout=timeout)

    def launch(
        self,
        app: str,
        args: list[str] | None = None,
        *,
        title: str | None = None,
        process: str | None = None,
        timeout: float = 15.0,
    ) -> windows.WindowInfo:
        """Start an application and return its new window."""
        check_desktop_state()
        before = launch.snapshot()
        launch.start(app, args)
        return launch.wait_new_window(before, title=title, process=process, timeout=timeout)

    def close(self) -> None:
        self.input.release_all()
        self.capture.close()
