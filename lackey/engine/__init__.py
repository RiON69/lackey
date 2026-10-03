"""Modern Windows engine for lackey.

Typed, instance-based building blocks that replace the global Sikuli-era
internals step by step:

- ``dpi``: per-monitor DPI awareness (v2) for the whole process;
- ``geometry`` and ``monitors``: physical-pixel rectangles and displays;
- ``capture``: screen capture (mss);
- ``input``: mouse and keyboard through ``SendInput`` with pre-checks;
- ``windows``: top-level windows, activation and integrity levels;
- ``system``: desktop/session state and user idle time;
- ``launch``: starting applications without a shell.

All coordinates are physical pixels of the virtual desktop. Call
``dpi.ensure_per_monitor_v2()`` before anything else touches DPI.
"""
