"""Template matching: find an image (the needle) in a captured frame (the haystack).

Scores are the normalized cross-correlation of gray images (``TM_CCOEFF_NORMED``, -1..1):
it ignores uniform changes of brightness and contrast, so a mean-color check runs on top
of it (a red and a green button of the same shape correlate perfectly in gray).

Large searches run a half-scale pass first and score only its candidates at full scale,
so every reported score is exact. A needle without contrast is refused: correlation is
undefined on a flat image, and such a pattern matches any flat area.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

from .geometry import Point, Rect

DEFAULT_THRESHOLD = 0.85
DEFAULT_MAX_COLOR_DELTA = 40.0  # 0..255: largest difference of a channel's mean
MIN_CONTRAST = 4.0  # gray standard deviation below which a needle is "flat"
PYRAMID_MIN_SIDE = 16  # a smaller needle loses too much detail at half scale
PYRAMID_MIN_AREA = 200_000  # haystack pixels below which the full search is cheap anyway
COARSE_MARGIN = 0.2  # how far below the best (or the threshold) a coarse peak may score
CANDIDATES = 8  # coarse peaks always scored at full scale
MAX_REFINED = 64  # at most this many coarse peaks are scored at full scale
REFINE_PAD = 3  # full-scale pixels searched around a coarse peak
_SUPPRESSED = -2.0  # below any correlation score


@dataclass(frozen=True)
class Match:
    rect: Rect  # where the needle lies (haystack pixels moved by ``origin``)
    score: float  # gray correlation, -1..1
    color_delta: float  # largest difference of a channel's mean color, 0..255

    @property
    def center(self) -> Point:
        return self.rect.center


@dataclass(frozen=True)
class MatchResult:
    matches: tuple[Match, ...]  # accepted: score and colors pass, best first, no overlaps
    best: Match | None  # the first match, or else the best candidate seen (diagnostics)
    second_score: float | None  # best score of a candidate that does not overlap ``best``
    threshold: float
    max_color_delta: float

    @property
    def found(self) -> bool:
        return bool(self.matches)

    @property
    def gap(self) -> float | None:
        """How far the best stands out from the next distinct candidate."""
        if self.best is None or self.second_score is None:
            return None
        return self.best.score - self.second_score


class Matcher(Protocol):
    def find(
        self,
        haystack: np.ndarray,
        needle: np.ndarray,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        max_color_delta: float = DEFAULT_MAX_COLOR_DELTA,
        find_all: bool = False,
        limit: int = 100,
        origin: tuple[int, int] = (0, 0),
    ) -> MatchResult: ...


def _bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(_bgr(image), cv2.COLOR_BGR2GRAY)


def contrast(image: np.ndarray) -> float:
    """Gray standard deviation; below MIN_CONTRAST an image is too flat to search for."""
    return float(_gray(image).std())


def _scores(haystack: np.ndarray, needle: np.ndarray) -> np.ndarray:
    scores = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    # Flat windows of the haystack can give NaN or infinities; they must never win.
    return np.nan_to_num(scores, copy=False, nan=-1.0, posinf=-1.0, neginf=-1.0)


def _peaks(
    scores: np.ndarray, size: tuple[int, int], keep: Callable[[int, float], bool]
) -> list[tuple[int, int, float]]:
    """Greedy non-maximum suppression: the highest score, then the highest whose box does
    not overlap any taken one, ... while ``keep(count_so_far, score)`` says so."""
    scores = scores.copy()
    width, height = size
    rows, cols = scores.shape
    peaks: list[tuple[int, int, float]] = []
    while True:
        _, best, _, (x, y) = cv2.minMaxLoc(scores)
        if best <= _SUPPRESSED or not keep(len(peaks), best):
            return peaks
        peaks.append((x, y, float(best)))
        scores[max(0, y - height + 1) : min(rows, y + height), max(0, x - width + 1) : min(cols, x + width)] = (
            _SUPPRESSED
        )


def _overlap(a: Rect, b: Rect) -> bool:
    return a.intersect(b) is not None


class TemplateMatcher:
    """The default Matcher: gray correlation with a half-scale pass, then a color check."""

    def __init__(self, *, pyramid: bool = True) -> None:
        self.pyramid = pyramid

    def find(
        self,
        haystack: np.ndarray,
        needle: np.ndarray,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        max_color_delta: float = DEFAULT_MAX_COLOR_DELTA,
        find_all: bool = False,
        limit: int = 100,
        origin: tuple[int, int] = (0, 0),
    ) -> MatchResult:
        """Find ``needle`` in ``haystack`` (BGR, BGRA or gray arrays).

        A match scores at least ``threshold`` and its mean colors differ from the needle's
        by at most ``max_color_delta`` per channel. Without ``find_all`` only the best
        match is returned. Raises ValueError for a flat needle or one larger than the
        haystack.
        """
        hay_bgr, needle_bgr = _bgr(haystack), _bgr(needle)
        hay_gray, needle_gray = _gray(hay_bgr), _gray(needle_bgr)
        height, width = needle_gray.shape
        if height > hay_gray.shape[0] or width > hay_gray.shape[1]:
            raise ValueError(
                f"the image to find ({width}x{height}) is larger than the search area "
                f"({hay_gray.shape[1]}x{hay_gray.shape[0]})"
            )
        if float(needle_gray.std()) < MIN_CONTRAST:
            raise ValueError("the image to find is flat (almost one color): it would match any flat area")
        wanted = max(1, limit) if find_all else 1

        if self._use_pyramid(hay_gray, needle_gray):
            candidates = self._coarse_candidates(hay_gray, needle_gray, threshold, wanted)
        else:
            full = _scores(hay_gray, needle_gray)
            # Always two (the best and the runner-up for the gap); more while they pass, so
            # look-alikes in other colors cannot crowd out the right one.
            candidates = _peaks(
                full,
                (width, height),
                lambda n, s: n < 2 or (n < wanted + CANDIDATES and s >= threshold),
            )

        needle_mean = needle_bgr.reshape(-1, 3).mean(axis=0)
        ox, oy = origin
        found: list[Match] = []
        for x, y, score in candidates:
            patch = hay_bgr[y : y + height, x : x + width]
            delta = float(np.abs(patch.reshape(-1, 3).mean(axis=0) - needle_mean).max())
            found.append(Match(Rect(ox + x, oy + y, width, height), score, delta))
        found.sort(key=lambda m: m.score, reverse=True)
        distinct: list[Match] = []  # coarse peaks can converge on the same spot
        for match in found:
            if not any(_overlap(match.rect, kept.rect) for kept in distinct):
                distinct.append(match)

        accepted = tuple(
            m for m in distinct if m.score >= threshold and m.color_delta <= max_color_delta
        )[:wanted]
        best = accepted[0] if accepted else (distinct[0] if distinct else None)
        second = next(
            (m.score for m in distinct if best is not None and not _overlap(m.rect, best.rect)), None
        )
        return MatchResult(accepted, best, second, threshold, max_color_delta)

    def _use_pyramid(self, haystack: np.ndarray, needle: np.ndarray) -> bool:
        return (
            self.pyramid
            and min(needle.shape) >= PYRAMID_MIN_SIDE
            and haystack.size >= PYRAMID_MIN_AREA
        )

    def _coarse_candidates(
        self, haystack: np.ndarray, needle: np.ndarray, threshold: float, wanted: int
    ) -> list[tuple[int, int, float]]:
        """Peaks of a half-scale search, each scored exactly at full scale nearby."""
        height, width = needle.shape
        small_hay = cv2.resize(
            haystack, (haystack.shape[1] // 2, haystack.shape[0] // 2), interpolation=cv2.INTER_AREA
        )
        small_needle = cv2.resize(needle, (width // 2, height // 2), interpolation=cv2.INTER_AREA)
        coarse = _scores(small_hay, small_needle)
        top = float(coarse.max())
        floor = min(top - COARSE_MARGIN, threshold - COARSE_MARGIN)
        cap = max(MAX_REFINED, wanted + 1)
        peaks = _peaks(
            coarse,
            (width // 2, height // 2),
            lambda n, s: n < CANDIDATES or (n < cap and s >= floor),
        )
        rows, cols = haystack.shape[0] - height, haystack.shape[1] - width  # last valid y, x
        refined: list[tuple[int, int, float]] = []
        for cx, cy, _ in peaks:
            x0, x1 = max(0, 2 * cx - REFINE_PAD), min(cols, 2 * cx + REFINE_PAD)
            y0, y1 = max(0, 2 * cy - REFINE_PAD), min(rows, 2 * cy + REFINE_PAD)
            local = _scores(haystack[y0 : y1 + height, x0 : x1 + width], needle)
            _, score, _, (lx, ly) = cv2.minMaxLoc(local)
            refined.append((x0 + lx, y0 + ly, float(score)))
        return refined
