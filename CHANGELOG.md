## Changelog ##

Unreleased (fork RiON69/lackey)
* `InputDriver.type_text(char_delay=...)`: one character per `SendInput` with a pause - Windows 11 Notepad garbles faster Unicode input (repeated characters, Enter overtaking the text).
* `lackey.engine.windows`: `display_affinity()`, `is_capture_protected()` and `WindowInfo.capture_protected` - windows that capture as black (`WDA_MONITOR`) or are left out of captures (`WDA_EXCLUDEFROMCAPTURE`); `protected_windows()` lists the visible ones cheaply.
* Packaging: `pyproject.toml` (setup.py and requirements.txt removed), Python >= 3.12. The engine needs numpy >= 2, `opencv-python-headless` (instead of `opencv-python`) and mss; the Sikuli API moved to `lackey.sikuli` with its dependencies in the `sikuli` extra (keyboard, mouse, pillow, pyperclip, pytesseract, requests). `import lackey` re-exports it when they are installed; without them it imports nothing more and leaves the DPI mode alone.
* `lackey.engine.match`: `Matcher` interface and `TemplateMatcher` - gray `TM_CCOEFF_NORMED` with a half-scale pass whose candidates are scored exactly at full scale; all matches without duplicates; the score gap to the next distinct candidate; NaN/inf scores of flat screen areas never win; flat needles are refused; a mean-color check catches look-alikes in another color. The Sikuli-era `TemplateMatchers` stay for `RegionMatching` until the facade is reworked.
* `lackey.engine.system.environment()`: theme of apps and system, high contrast, text scale, accent color, transparency and HDR (advanced color) - the settings that change pixels at the same DPI, recorded with image patterns.
* `lackey.engine`: typed Windows engine (DPI v2, mss capture, `SendInput` input with tags, windows, launch, system state) without side effects on import.

v0.4.0a1
* Merged Sikuli shim into Lackey main code

v0.3.1a1
* Implemented pyramid matcher to improve image search efficiency

v0.3.0a1
* Implemented the rest of the main Sikuli classes, including `App`, `Settings`, and `Debug`

v0.2.2a1
* Fixed #14 TypeError on doubleClick()

v0.2.1a1
* Fixed #5 bad region validation
* Fixed #7 findAll() listiterator error
* Fixed #9 _convert_sikuli_wildcards should be a class method
* Fixed #10 Region.below(), Region.right() getScreen error
* Fixed #11 clipRegionToScreen() errors
* Fixed #12 memory leak

v0.2.0a1
* Added multi-monitor support (Screen() class should be fully functional and Sikuli-compatible, except for interactive functions)
* Moved `capture()` method to `Screen` class instead of `Region` (where it had incorrectly been placed)
* Screen class now properly inherits Region
* Added lastMatch shortcut for click()
* Implemented raster functions for Region

v0.1.0a1
* Initial build with basic Sikuli support