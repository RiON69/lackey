"""Pure unit tests: no input is sent, nothing on screen changes."""

import ctypes
from pathlib import Path

import numpy as np
import pytest

from lackey.engine.capture import is_black
from lackey.engine.geometry import Rect
from lackey.engine.input import (
    EXTENDED_VKS,
    INPUT,
    TAG_AGENT,
    TAG_OPERATOR,
    is_own_tag,
    normalize_absolute,
    parse_keys,
    utf16_units,
)
from lackey.engine.launch import LaunchError, _checked


@pytest.mark.parametrize(
    "screen",
    [Rect(0, 0, 2560, 1600), Rect(-1920, -200, 4480, 1800), Rect(0, 0, 1366, 768)],
)
def test_absolute_coordinates_land_on_the_target_pixel(screen: Rect) -> None:
    xs = [screen.left, screen.left + 1, screen.left + screen.width // 2, screen.right - 2, screen.right - 1]
    ys = [screen.top, screen.top + 1, screen.top + screen.height // 2, screen.bottom - 1]
    for x in xs:
        for y in ys:
            nx, ny = normalize_absolute(x, y, screen)
            assert 0 <= nx <= 65535 and 0 <= ny <= 65535
            assert screen.left + nx * screen.width // 65536 == x
            assert screen.top + ny * screen.height // 65536 == y


def test_utf16_units_cover_cyrillic_and_surrogate_pairs() -> None:
    assert utf16_units("a") == [0x61]
    assert utf16_units("Я") == [0x042F]
    assert utf16_units("😀") == [0xD83D, 0xDE00]


def test_parse_keys() -> None:
    assert parse_keys("ctrl+shift+esc") == [0xA2, 0xA0, 0x1B]
    assert parse_keys(["ctrl", "s"]) == [0xA2, 0x53]
    assert parse_keys("F12") == [0x7B]
    with pytest.raises(ValueError):
        parse_keys("ctrl+")
    with pytest.raises(ValueError):
        parse_keys("hyper")


def test_navigation_keys_are_extended() -> None:
    for name in ("left", "right", "up", "down", "home", "end", "pageup", "pagedown", "insert", "delete"):
        assert parse_keys(name)[0] in EXTENDED_VKS


def test_input_struct_matches_win64_layout() -> None:
    assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def test_own_tags() -> None:
    assert is_own_tag(TAG_AGENT) and is_own_tag(TAG_OPERATOR)
    assert not is_own_tag(0) and not is_own_tag(0x12345678)


def test_black_frame_detection() -> None:
    assert is_black(np.zeros((4, 4, 3), np.uint8))
    almost = np.zeros((4, 4, 3), np.uint8)
    almost[0, 0, 0] = 1
    assert not is_black(almost)


def test_rect_geometry() -> None:
    rect = Rect(10, 20, 100, 50)
    assert (rect.right, rect.bottom) == (110, 70)
    assert rect.contains(10, 20) and not rect.contains(110, 70)
    assert rect.intersect(Rect(100, 60, 50, 50)) == Rect(100, 60, 10, 10)
    assert rect.intersect(Rect(500, 500, 5, 5)) is None


@pytest.mark.parametrize("name", ["run.bat", "run.cmd", "x.ps1", "readme.txt"])
def test_launch_rejects_non_executables(name: str) -> None:
    with pytest.raises(LaunchError):
        _checked(Path(name))


def test_accent_color_reads_as_rgb_hex() -> None:
    from lackey.engine.system import accent_hex

    assert accent_hex(0xFFD47800) == "#0078d4"  # DWM stores 0xAABBGGRR
    assert accent_hex(0x00000000) == "#000000"


def test_environment_defaults_when_settings_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from lackey.engine import system

    monkeypatch.setattr(system, "_reg_dword", lambda _path, _name: None)
    monkeypatch.setattr(system, "high_contrast", lambda: False)

    def no_hdr() -> bool:
        raise OSError(87, "QueryDisplayConfig failed")

    monkeypatch.setattr(system, "hdr_enabled", no_hdr)
    env = system.environment()
    assert (env.apps_theme, env.system_theme, env.text_scale) == ("light", "light", 100)
    assert env.accent is None and env.transparency is True and env.hdr is None
    values = {("Personalize", "AppsUseLightTheme"): 0, ("Accessibility", "TextScaleFactor"): 125}
    monkeypatch.setattr(
        system, "_reg_dword", lambda path, name: values.get((path.rsplit("\\", 1)[-1], name))
    )
    env = system.environment()
    assert env.apps_theme == "dark" and env.text_scale == 125
