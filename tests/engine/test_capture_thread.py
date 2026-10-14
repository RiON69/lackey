"""MssCapture runs every grab on its own thread with one mss instance, so threads that come
and go (a server's pool) leave no GDI handles behind; close() releases the instance."""

import sys
import threading
import types
from typing import ClassVar

import numpy as np

from lackey.engine.capture import MssCapture
from lackey.engine.geometry import Rect


class FakeMss:
    made: ClassVar[list["FakeMss"]] = []

    def __init__(self) -> None:
        self.closed = False
        self.threads: set[str] = set()
        FakeMss.made.append(self)

    def grab(self, area):
        self.threads.add(threading.current_thread().name)
        return np.zeros((area["height"], area["width"], 4), np.uint8)

    def close(self) -> None:
        self.closed = True


def test_grabs_from_many_threads_share_one_instance(monkeypatch) -> None:
    FakeMss.made = []
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(MSS=FakeMss))
    capture = MssCapture()
    frames = []

    def grab() -> None:
        frames.append(capture.grab(Rect(0, 0, 8, 4)))

    workers = [threading.Thread(target=grab) for _ in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert len(frames) == 6 and frames[0].image.shape == (4, 8, 3)
    assert len(FakeMss.made) == 1 and FakeMss.made[0].threads == {"lackey-capture"}

    capture.close()
    assert FakeMss.made[0].closed
    capture.grab(Rect(0, 0, 2, 2))  # starts over
    assert len(FakeMss.made) == 2
    capture.close()


def test_a_failed_grab_reaches_the_caller(monkeypatch) -> None:
    class Broken(FakeMss):
        def grab(self, area):
            raise RuntimeError("BitBlt failed")

    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(MSS=Broken))
    capture = MssCapture()
    try:
        capture.grab(Rect(0, 0, 2, 2))
    except RuntimeError as error:
        assert "BitBlt" in str(error)
    else:
        raise AssertionError("no error")
    finally:
        capture.close()
