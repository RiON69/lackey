"""Read-only checks on the real machine: they query state and capture the screen into
memory, but never send input or change windows."""

import ctypes
import subprocess
import sys
from ctypes import wintypes

import pytest

from lackey.engine import system
from lackey.engine.desktop import Desktop
from lackey.engine.monitors import list_monitors, primary_monitor, virtual_screen
from lackey.engine.windows import (
    WDA_EXCLUDEFROMCAPTURE,
    WDA_MONITOR,
    WDA_NONE,
    current_integrity,
    display_affinity,
    get_window,
    list_windows,
    protected_windows,
)


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True, timeout=60)


def _sikuli_installed() -> bool:
    return _run("import keyboard, mouse, pyperclip, pytesseract, requests, PIL").returncode == 0


def test_import_has_no_output() -> None:
    result = _run("import lackey\nimport lackey.engine.match")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_the_sikuli_api_claims_per_monitor_v2_on_import() -> None:
    if not _sikuli_installed():
        pytest.skip("the Sikuli API needs lackey[sikuli]")
    result = _run("import lackey\nfrom lackey.engine.dpi import current_mode\nprint(current_mode().value)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "per_monitor_v2"  # nothing else printed on import


def test_the_engine_alone_leaves_the_dpi_mode_to_its_caller() -> None:
    """Without the Sikuli extra, `import lackey` changes nothing (T1.2): the program claims
    per-monitor v2 itself, or the capture backend does when it starts."""
    if _sikuli_installed():
        pytest.skip("with lackey[sikuli] the classic API claims per-monitor v2 on import")
    code = (
        "import lackey\n"
        "from lackey.engine.dpi import current_mode\n"
        "before = current_mode().value\n"
        "from lackey.engine.capture import MssCapture\n"
        "MssCapture()\n"
        "print(before, current_mode().value)\n"
        "try:\n"
        "    lackey.Region\n"
        "except ImportError as error:\n"
        "    print('sikuli' in str(error))"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    first, second = result.stdout.strip().splitlines()
    assert first.split()[0] != "per_monitor_v2" and first.split()[1] == "per_monitor_v2"
    assert second == "True"


def test_import_does_not_override_an_existing_dpi_mode() -> None:
    code = (
        "import ctypes\n"
        "ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))\n"
        "import lackey\n"
        "from lackey.engine.dpi import current_mode, ensure_per_monitor_v2\n"
        "print(current_mode().value, ensure_per_monitor_v2())"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "system False"


def test_monitors_fit_in_the_virtual_screen() -> None:
    monitors = list_monitors()
    assert monitors and any(m.primary for m in monitors)
    screen = virtual_screen()
    for monitor in monitors:
        assert screen.contains(monitor.rect.left, monitor.rect.top)
        assert monitor.dpi >= 96


def test_capture_primary_monitor_in_physical_pixels() -> None:
    desktop = Desktop()
    try:
        frame = desktop.screenshot()
        monitor = primary_monitor()
        assert frame.image.shape == (monitor.rect.height, monitor.rect.width, 3)
        assert not frame.is_black
    finally:
        desktop.capture.close()


def test_session_state_is_readable() -> None:
    assert system.input_desktop_name() == "Default"
    state = system.session_state()
    assert state is not None and state[0] == system.WTS_ACTIVE
    assert system.idle_ms() >= 0


def test_windows_listing() -> None:
    windows = list_windows()
    assert windows
    assert all(w.hwnd and w.title for w in windows)
    assert any(w.process for w in windows)
    assert current_integrity() >= 0x2000


def test_capture_protection_is_read_from_the_display_affinity() -> None:
    """A hidden window of this process: nothing appears on the screen."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]  # fmt: skip
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    hwnd = user32.CreateWindowExW(0, "STATIC", "lackey affinity", 0, 0, 0, 10, 10, None, None, None, None)
    assert hwnd
    try:
        assert display_affinity(hwnd) == WDA_NONE and not get_window(hwnd).capture_protected
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            assert user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)  # before Windows 10 2004
        assert display_affinity(hwnd) in (WDA_MONITOR, WDA_EXCLUDEFROMCAPTURE)
        assert get_window(hwnd).capture_protected
        assert hwnd not in [w.hwnd for w in protected_windows()]  # hidden: nothing to hide
    finally:
        user32.DestroyWindow(hwnd)
    assert display_affinity(hwnd) == WDA_NONE  # gone: unreadable


def test_environment_reads_the_display_settings() -> None:
    env = system.environment()
    assert env.apps_theme in ("light", "dark") and env.system_theme in ("light", "dark")
    assert 100 <= env.text_scale <= 225
    assert env.accent is None or (env.accent.startswith("#") and len(env.accent) == 7)
    assert env.hdr in (True, False, None)
    assert set(env.as_dict()) == {
        "apps_theme", "system_theme", "high_contrast", "text_scale", "accent", "transparency", "hdr"
    }
