"""Screen capture into numpy arrays (BGR, uint8)."""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
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


Jobs = queue.SimpleQueue  # (mss area, Future) pairs; None stops the thread


class MssCapture:
    """GDI capture through mss on one long-lived thread of its own.

    mss is not thread-safe, and its GDI handles - two DCs and a DIB the size of the last
    grab - go only on close(): an instance per calling thread leaked them each time a
    pooled thread ended (some 16 MB and three GDI objects per thread for 2560x1600).
    Here one thread owns one instance; grabs from any thread run there, one at a time.
    """

    def __init__(self) -> None:
        # mss requests per-monitor v1 when its first instance is created; claim v2 first.
        ensure_per_monitor_v2()
        self._jobs: Jobs = queue.SimpleQueue()  # of the current thread
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _serve(jobs: Jobs) -> None:
        sct = None
        try:
            while True:
                job = jobs.get()
                if job is None:
                    return
                area, done = job
                if not done.set_running_or_notify_cancel():
                    continue
                try:
                    if sct is None:
                        import mss

                        factory = getattr(mss, "MSS", None) or mss.mss
                        sct = factory()
                    done.set_result(sct.grab(area))
                except BaseException as error:  # noqa: BLE001 - handed to the caller
                    done.set_exception(error)
        finally:
            if sct is not None:
                sct.close()

    def grab(self, rect: Rect) -> Frame:
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"empty capture rectangle: {rect}")
        area = {
            "left": rect.left,
            "top": rect.top,
            "width": rect.width,
            "height": rect.height,
        }
        done: Future[object] = Future()
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._jobs = queue.SimpleQueue()
                self._thread = threading.Thread(
                    target=self._serve,
                    args=(self._jobs,),
                    name="lackey-capture",
                    daemon=True,
                )
                self._thread.start()
            self._jobs.put((area, done))
        bgra = np.asarray(done.result())
        return Frame(
            image=np.ascontiguousarray(bgra[:, :, :3]),
            rect=rect,
            captured_at=time.monotonic(),
        )

    def grab_virtual_screen(self) -> Frame:
        return self.grab(virtual_screen())

    def close(self) -> None:
        """Release the GDI handles; a later grab starts over."""
        with self._lock:
            thread, self._thread = self._thread, None
            if thread is not None:
                self._jobs.put(None)
        if thread is not None:
            thread.join(timeout=5.0)
