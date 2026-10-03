"""Rectangles and points in physical pixels of the virtual desktop."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        """Exclusive right edge."""
        return self.left + self.width

    @property
    def bottom(self) -> int:
        """Exclusive bottom edge."""
        return self.top + self.height

    @property
    def center(self) -> Point:
        return Point(self.left + self.width // 2, self.top + self.height // 2)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def intersect(self, other: Rect) -> Rect | None:
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return None
        return Rect(left, top, right - left, bottom - top)

    @classmethod
    def from_ltrb(cls, left: int, top: int, right: int, bottom: int) -> Rect:
        return cls(left, top, right - left, bottom - top)
