"""Deterministic test window for desktop tests ("Svetoch TestApp").

Usage: python testapp.py <state.json> [--dpi-unaware]

The window has a multi-line text box, a button and a click canvas. After every
event it writes its state (widget rectangles in screen pixels, recorded clicks,
text, button presses) to the JSON file so tests can check what really arrived.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
import tkinter as tk
from pathlib import Path

TITLE = "Svetoch TestApp"


def main() -> None:
    state_path = Path(sys.argv[1])
    if "--dpi-unaware" not in sys.argv:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

    root = tk.Tk()
    root.title(TITLE)
    root.geometry("+200+150")
    state: dict = {"clicks": [], "button_presses": 0, "text": "", "widgets": {}, "ready": False}

    text = tk.Text(root, width=48, height=6, font=("Segoe UI", 12))
    text.grid(row=0, column=0, columnspan=2, padx=12, pady=12)
    button = tk.Button(root, text="Press me", width=16)
    button.grid(row=1, column=0, padx=12, pady=6, sticky="w")
    canvas = tk.Canvas(root, width=360, height=160, background="#f2e6c9", highlightthickness=0)
    canvas.grid(row=2, column=0, columnspan=2, padx=12, pady=12)

    def rect(widget: tk.Misc) -> list[int]:
        return [widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()]

    def save() -> None:
        state["text"] = text.get("1.0", "end-1c")
        state["widgets"] = {"text": rect(text), "button": rect(button), "canvas": rect(canvas)}
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        for _ in range(50):  # the reader may hold the file open for a moment (Windows)
            try:
                tmp.replace(state_path)
                return
            except PermissionError:
                time.sleep(0.01)
        tmp.replace(state_path)

    def on_canvas_click(event: tk.Event) -> None:
        state["clicks"].append([event.x_root, event.y_root, int(event.num)])
        canvas.create_oval(event.x - 3, event.y - 3, event.x + 3, event.y + 3, fill="#c47f17")
        save()

    def on_button() -> None:
        state["button_presses"] += 1
        save()

    def on_ready() -> None:
        state["ready"] = True
        save()
        poll()

    def poll() -> None:
        current = text.get("1.0", "end-1c")
        if current != state["text"]:
            save()
        root.after(50, poll)

    canvas.bind("<Button-1>", on_canvas_click)
    canvas.bind("<Button-3>", on_canvas_click)
    button.configure(command=on_button)
    root.after(300, on_ready)
    root.mainloop()


if __name__ == "__main__":
    main()
