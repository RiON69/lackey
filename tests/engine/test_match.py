"""Template matching on synthetic screens: exact positions, look-alikes, duplicates, flat
areas, and what changes of theme, accent color and text scale do to a match."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from lackey.engine.geometry import Rect
from lackey.engine.match import (
    DEFAULT_THRESHOLD,
    MIN_CONTRAST,
    TemplateMatcher,
    _scores,
    contrast,
)

FONT = cv2.FONT_HERSHEY_SIMPLEX
BLUE = (192, 103, 0)  # BGR accent colors
PURPLE = (184, 100, 135)


def screen(
    *, theme: str = "light", accent: tuple[int, int, int] = BLUE, text_scale: float = 1.0
) -> tuple[np.ndarray, dict[str, Rect]]:
    """A 1600x1000 window-like frame and where its elements are."""
    background, text, panel = (
        ((243, 243, 243), (20, 20, 20), (255, 255, 255))
        if theme == "light"
        else ((32, 32, 32), (235, 235, 235), (45, 45, 45))
    )
    image = np.full((1000, 1600, 3), background, np.uint8)
    rects: dict[str, Rect] = {}

    def label(name: str, origin: tuple[int, int], words: str, scale: float, color, thick: int = 1) -> None:
        (w, h), base = cv2.getTextSize(words, FONT, scale * text_scale, thick)
        x, y = origin
        cv2.putText(image, words, (x, y + h), FONT, scale * text_scale, color, thick, cv2.LINE_AA)
        rects[name] = Rect(x - 4, y - 4, w + 8, h + base + 8)

    label("title", (40, 30), "Svetoch TestApp - Settings", 0.9, text, 2)
    cv2.rectangle(image, (40, 120), (760, 940), panel, -1)  # a flat panel: windows of zero variance
    for row in range(1, 21):
        label(f"item{row:02d}", (60, 130 + (row - 1) * 40), f"Item {row:02d} - report.txt", 0.7, text)
    for index, (name, words, primary) in enumerate(
        [("save", "Save", True), ("cancel", "Cancel", False), ("apply", "Apply", False)]
    ):
        left = 900 + index * 220
        fill = accent if primary else ((225, 225, 225) if theme == "light" else (70, 70, 70))
        ink = (255, 255, 255) if primary else text
        cv2.rectangle(image, (left, 860), (left + 180, 920), fill, -1)
        cv2.rectangle(image, (left, 860), (left + 180, 920), (128, 128, 128), 1)
        (w, h), _ = cv2.getTextSize(words, FONT, 0.8 * text_scale, 2)
        cv2.putText(
            image, words, (left + 90 - w // 2, 890 + h // 2), FONT, 0.8 * text_scale, ink, 2, cv2.LINE_AA
        )
        rects[name] = Rect(left - 2, 858, 185, 65)
    for index in range(5):  # the same icon five times
        cx = 950 + index * 110
        cv2.circle(image, (cx, 300), 26, accent, -1)
        cv2.line(image, (cx - 14, 300), (cx + 14, 300), (255, 255, 255), 4)
        cv2.line(image, (cx, 286), (cx, 314), (255, 255, 255), 4)
        rects[f"icon{index}"] = Rect(cx - 30, 270, 61, 61)
    return image, rects


def crop(image: np.ndarray, rect: Rect) -> np.ndarray:
    return image[rect.top : rect.bottom, rect.left : rect.right].copy()


@pytest.fixture(scope="module")
def light() -> tuple[np.ndarray, dict[str, Rect]]:
    return screen()


@pytest.mark.parametrize("pyramid", [True, False])
@pytest.mark.parametrize("name", ["save", "cancel", "title", "item07", "icon2"])
def test_an_element_is_found_where_it_is(light, name: str, pyramid: bool) -> None:
    image, rects = light
    result = TemplateMatcher(pyramid=pyramid).find(image, crop(image, rects[name]), find_all=False)
    if name.startswith("icon"):  # five identical icons: any of them is right
        assert result.found and result.matches[0].rect in [rects[f"icon{i}"] for i in range(5)]
        return
    assert result.found and result.best is not None
    assert result.best.rect == rects[name]
    assert result.best.score > 0.99 and result.best.color_delta < 1


@pytest.mark.parametrize("dx, dy", [(0, 0), (1, 0), (0, 1), (1, 1), (3, 5)])
def test_the_half_scale_pass_finds_what_the_full_search_finds(light, dx: int, dy: int) -> None:
    """Odd offsets put the target between the pixels of the half-scale image."""
    image, rects = light
    canvas = np.full((image.shape[0] + 8, image.shape[1] + 8, 3), 243, np.uint8)
    canvas[dy : dy + image.shape[0], dx : dx + image.shape[1]] = image
    for name in ("save", "title", "item13"):
        needle = crop(image, rects[name])
        fast = TemplateMatcher(pyramid=True).find(canvas, needle)
        exact = TemplateMatcher(pyramid=False).find(canvas, needle)
        assert fast.best is not None and exact.best is not None
        assert fast.best.rect == exact.best.rect == Rect(
            rects[name].left + dx, rects[name].top + dy, rects[name].width, rects[name].height
        )
        assert fast.best.score == pytest.approx(exact.best.score, abs=1e-4)  # DFT vs direct sums


def test_one_row_among_look_alikes(light) -> None:
    image, rects = light
    result = TemplateMatcher().find(image, crop(image, rects["item17"]))
    assert result.found and result.best is not None and result.best.rect == rects["item17"]
    assert result.gap is not None and 0 < result.gap < 0.2  # unique, but only just


def test_all_matches_come_once_each_best_first(light) -> None:
    image, rects = light
    needle = crop(image, rects["icon0"])
    result = TemplateMatcher().find(image, needle, find_all=True)
    assert sorted((m.rect for m in result.matches), key=lambda r: r.left) == [
        rects[f"icon{i}"] for i in range(5)
    ]
    scores = [m.score for m in result.matches]
    assert scores == sorted(scores, reverse=True)
    for i, a in enumerate(result.matches):
        assert all(a.rect.intersect(b.rect) is None for b in result.matches[i + 1 :])
    assert len(TemplateMatcher().find(image, needle, find_all=True, limit=3).matches) == 3
    assert result.gap is not None and result.gap < 0.01  # repeated: no margin over the next


def test_a_unique_element_stands_out(light) -> None:
    image, rects = light
    result = TemplateMatcher().find(image, crop(image, rects["save"]))
    assert result.gap is not None and result.gap > 0.2


def test_a_missing_element_reports_the_best_candidate(light) -> None:
    image, rects = light
    other, other_rects = screen(text_scale=1.0)
    cv2.putText(other, "Delete", (1300, 700), FONT, 1.2, (0, 0, 200), 3, cv2.LINE_AA)
    needle = other[670:715, 1290:1430].copy()
    result = TemplateMatcher().find(image, needle)
    assert not result.found and result.best is not None
    assert result.best.score < DEFAULT_THRESHOLD
    del other_rects, rects


def test_a_flat_needle_is_refused(light) -> None:
    image, _ = light
    flat = np.full((30, 60, 3), (255, 255, 255), np.uint8)
    flat[0, 0] = (250, 250, 250)  # a speck of noise is still flat
    assert contrast(flat) < MIN_CONTRAST
    with pytest.raises(ValueError, match="flat"):
        TemplateMatcher().find(image, flat)


def test_flat_areas_of_the_screen_never_win(light) -> None:
    image, rects = light
    flat_screen = np.full((400, 600, 3), 255, np.uint8)
    scores = _scores(cv2.cvtColor(flat_screen, cv2.COLOR_BGR2GRAY), cv2.cvtColor(crop(image, rects["save"]), cv2.COLOR_BGR2GRAY))
    assert np.isfinite(scores).all()
    result = TemplateMatcher().find(flat_screen, crop(image, rects["save"]))
    assert not result.found
    assert result.best is None or result.best.score < 0.5


def test_another_accent_color_is_caught_by_the_color_check(light) -> None:
    image, rects = light
    purple, _ = screen(accent=PURPLE)
    needle = crop(image, rects["save"])
    result = TemplateMatcher().find(purple, needle)
    assert not result.found and result.best is not None
    assert result.best.rect == rects["save"]  # the shape is there...
    assert result.best.color_delta > 40  # ...in another color
    lenient = TemplateMatcher().find(purple, needle, max_color_delta=255)
    assert lenient.found and lenient.best is not None and lenient.best.rect == rects["save"]


def test_a_dark_theme_does_not_match_a_light_pattern(light) -> None:
    image, rects = light
    dark, _ = screen(theme="dark")
    for name in ("cancel", "title", "item03"):
        result = TemplateMatcher().find(dark, crop(image, rects[name]))
        assert not result.found


def test_a_larger_text_scale_does_not_match_at_one_scale(light) -> None:
    """Patterns are taken at one scale; searching other scales comes with T8.4."""
    image, rects = light
    larger, _ = screen(text_scale=1.25)
    result = TemplateMatcher().find(larger, crop(image, rects["title"]))
    assert not result.found


def test_inputs_and_origin(light) -> None:
    image, rects = light
    needle = crop(image, rects["cancel"])
    bgra = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    result = TemplateMatcher().find(bgra, cv2.cvtColor(needle, cv2.COLOR_BGR2BGRA), origin=(-1920, 100))
    assert result.best is not None
    assert result.best.rect == Rect(rects["cancel"].left - 1920, rects["cancel"].top + 100, 185, 65)
    gray = TemplateMatcher().find(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY))
    assert gray.found and gray.best is not None and gray.best.rect == rects["cancel"]
    with pytest.raises(ValueError, match="larger than the search area"):
        TemplateMatcher().find(needle, image)
