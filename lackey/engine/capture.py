"""Screen capture into numpy arrays (BGR, uint8)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .dpi import ensure_per_monitor_v2
from .geometry import Rect
from .monitors import virtual_screen


@dataclass(frozen=True)
class Frame:
    """A captured image and where it came from."""

    image: np.ndarray  # H x W x 3, BGR, uint8
    rect: Rect  # physical pixels of the virtual desktop
    captured_at: float  # time.monotonic()

    @property
    def is_black(self) -> bool:
        """Exactly black everywhere: a hint (not proof) that the desktop is unavailable."""
        return is_black(self.image)


def is_black(image: np.ndarray) -> bool:
    return image.size > 0 and not image.any()


class CaptureBackend(Protocol):
    def grab(self, rect: Rect) -> Frame: ...


class MssCapture:
    """GDI capture through mss; one mss instance per thread (mss is not thread-safe)."""

    def __init__(self) -> None:
        # mss requests per-monitor v1 when its first instance is created; claim v2 first.
        ensure_per_monitor_v2()
        self._local = threading.local()

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            factory = getattr(mss, "MSS", None) or mss.mss
            sct = factory()
            self._local.sct = sct
        return sct

    def grab(self, rect: Rect) -> Frame:
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"empty capture rectangle: {rect}")
        shot = self._sct().grab(
            {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        )
        bgra = np.asarray(shot)
        return Frame(image=np.ascontiguousarray(bgra[:, :, :3]), rect=rect, captured_at=time.monotonic())

    def grab_virtual_screen(self) -> Frame:
        return self.grab(virtual_screen())

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            sct.close()
            self._local.sct = None
