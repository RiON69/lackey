"""Lackey: desktop automation for Python.

``lackey.engine`` is the typed Windows engine (DPI, capture, input, windows, template
matching); it needs only numpy, OpenCV and mss. The classic Sikuli-style API
(``Region``, ``Screen``, ``click()``...) lives in ``lackey.sikuli`` and is re-exported
here when its extra dependencies are installed: ``pip install lackey[sikuli]``.
"""

import importlib

from ._version import __version__

try:
    from .sikuli import *  # noqa: F403  (the classic API, if its dependencies are there)
    from .sikuli import _abort_script, _exit, _input, _type  # noqa: F401
except ImportError as _sikuli_error:  # engine-only installation
    _SIKULI_ERROR = _sikuli_error

    def __getattr__(name):
        if name.startswith("__"):
            raise AttributeError(name)
        try:  # submodules such as lackey.engine still import on attribute access
            return importlib.import_module(f"{__name__}.{name}")
        except ImportError:
            pass
        raise ImportError(
            f"lackey.{name} belongs to the Sikuli API, which needs its extra dependencies: "
            f"pip install lackey[sikuli] ({_SIKULI_ERROR})"
        ) from _SIKULI_ERROR
