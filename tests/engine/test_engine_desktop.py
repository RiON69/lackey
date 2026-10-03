"""Real input on the real desktop. Run only with the machine owner's consent:

    pytest tests/engine -m desktop

They open the "Svetoch TestApp" window, click and type into it, then close it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lackey.engine import launch, windows
from lackey.engine.desktop import Desktop

pytestmark = pytest.mark.desktop

TESTAPP = Path(__file__).with_name("testapp.py")


def _read_state(path: Path) -> dict:
    for _ in range(50):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.05)
    raise AssertionError("test app state is not available")


def _wait_state(path: Path, predicate, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    state = _read_state(path)
    while time.monotonic() < deadline:
        state = _read_state(path)
        if predicate(state):
            return state
        time.sleep(0.05)
    return state


@pytest.fixture
def testapp(tmp_path: Path):
    state_path = tmp_path / "state.json"
    before = launch.snapshot()
    process = subprocess.Popen([sys.executable, str(TESTAPP), str(state_path)])
    try:
        window = launch.wait_new_window(before, title="Svetoch TestApp", timeout=15)
        _wait_state(state_path, lambda s: s.get("ready"))
        yield window, state_path
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_click_lands_on_the_exact_pixel(testapp) -> None:
    window, state_path = testapp
    desktop = Desktop()
    desktop.activate(window.hwnd)
    left, top, width, height = _read_state(state_path)["widgets"]["canvas"]
    targets = [(left + 10, top + 10), (left + width // 2, top + height // 2), (left + width - 11, top + height - 11)]
    for x, y in targets:
        cursor = desktop.input.click(x, y)
        assert (cursor.x, cursor.y) == (x, y)
    state = _wait_state(state_path, lambda s: len(s["clicks"]) >= len(targets))
    assert [(c[0], c[1]) for c in state["clicks"]] == targets


def test_typing_is_layout_independent_with_newlines(testapp) -> None:
    window, state_path = testapp
    desktop = Desktop()
    desktop.activate(window.hwnd)
    left, top, width, height = _read_state(state_path)["widgets"]["text"]
    desktop.input.click(left + width // 2, top + height // 2)
    text = "Hello, Мир! Ёлка №5 — ok\nВторая строка: ünïcødé 😀"
    desktop.input.type_text(text)
    state = _wait_state(state_path, lambda s: s["text"] == text)
    assert state["text"] == text


def test_shortcut_and_button(testapp) -> None:
    window, state_path = testapp
    desktop = Desktop()
    desktop.activate(window.hwnd)
    left, top, width, height = _read_state(state_path)["widgets"]["text"]
    desktop.input.click(left + width // 2, top + height // 2)
    desktop.input.type_text("to be replaced")
    _wait_state(state_path, lambda s: s["text"] == "to be replaced")
    desktop.input.press("ctrl+a")
    desktop.input.type_text("replaced")
    assert _wait_state(state_path, lambda s: s["text"] == "replaced")["text"] == "replaced"
    bl, bt, bw, bh = _read_state(state_path)["widgets"]["button"]
    desktop.input.click(bl + bw // 2, bt + bh // 2)
    assert _wait_state(state_path, lambda s: s["button_presses"] == 1)["button_presses"] == 1


def test_window_appears_in_listing_with_frame_bounds(testapp) -> None:
    window, _ = testapp
    info = windows.get_window(window.hwnd)
    assert info.title == "Svetoch TestApp"
    assert info.rect.width > 0 and info.rect.height > 0
    assert not info.cloaked
