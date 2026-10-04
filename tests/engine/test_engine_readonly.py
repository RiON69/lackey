"""Read-only checks on the real machine: they query state and capture the screen into
memory, but never send input or change windows."""

import subprocess
import sys

from lackey.engine import system
from lackey.engine.desktop import Desktop
from lackey.engine.monitors import list_monitors, primary_monitor, virtual_screen
from lackey.engine.windows import current_integrity, list_windows


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True, timeout=60)


def test_import_has_no_output_and_claims_per_monitor_v2() -> None:
    result = _run("import lackey\nfrom lackey.engine.dpi import current_mode\nprint(current_mode().value)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "per_monitor_v2"  # nothing else printed on import


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


def test_environment_reads_the_display_settings() -> None:
    env = system.environment()
    assert env.apps_theme in ("light", "dark") and env.system_theme in ("light", "dark")
    assert 100 <= env.text_scale <= 225
    assert env.accent is None or (env.accent.startswith("#") and len(env.accent) == 7)
    assert env.hdr in (True, False, None)
    assert set(env.as_dict()) == {
        "apps_theme", "system_theme", "high_contrast", "text_scale", "accent", "transparency", "hdr"
    }
