import logging
from threading import Lock, Thread

KEY_CODES = {
    "fn": 63, "cmd": 55, "cmd_l": 55, "cmd_r": 54,
    "shift": 56, "shift_l": 56, "shift_r": 60,
    "alt": 58, "alt_l": 58, "alt_r": 61,
    "ctrl": 59, "ctrl_l": 59, "ctrl_r": 62,
    "space": 49, "tab": 48, "esc": 53,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5,
    "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
    "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37,
    "j": 38, "k": 40, "n": 45, "m": 46,
}
KEY_CODES.update(dict(zip((f"f{i}" for i in range(1, 21)),
                         (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90))))
MODIFIERS = {54, 55, 56, 58, 59, 60, 61, 62, 63}
REVERSE_CODES = {code: name for name, code in KEY_CODES.items()}
LABELS = {"fn": "fn", "cmd": "⌘", "cmd_l": "⌘", "cmd_r": "Right ⌘", "ctrl": "⌃",
          "ctrl_l": "⌃", "ctrl_r": "Right ⌃", "alt": "⌥", "alt_l": "⌥", "alt_r": "Right ⌥",
          "shift": "⇧", "shift_l": "⇧", "shift_r": "Right ⇧", "space": "Space", "tab": "Tab"}


def parse_hotkey(name: str) -> frozenset[int]:
    parts = name.lower().replace(" ", "").split("+")
    if not 1 <= len(parts) <= 4 or any(part not in KEY_CODES for part in parts):
        raise ValueError("Use Fn, a modifier or F-key, or a combination such as ctrl+alt+space")
    codes = frozenset(KEY_CODES[part] for part in parts)
    if len(codes) != len(parts) or 53 in codes:
        raise ValueError("Duplicate keys and Escape are not available as dictation shortcuts")
    if not (codes & MODIFIERS) and not (len(parts) == 1 and parts[0] in {f"f{i}" for i in range(1, 21)}):
        raise ValueError("A shortcut must include a modifier or a function key")
    for pair in ({54, 55}, {56, 60}, {58, 61}, {59, 62}):
        if pair <= codes:
            raise ValueError("Choose one side of each modifier")
    if codes in ({55, 9}, {55, 8}, {55, 49}, {55, 12}, {55, 13}):
        raise ValueError("That shortcut is reserved by macOS")
    return codes


def hotkey_label(name: str) -> str:
    return " + ".join(LABELS.get(part, part.upper()) for part in name.split("+"))


class HoldHotkey:
    def __init__(self, name: str, on_press, on_release, toggle="fn+space", on_toggle=None,
                 on_cancel=None, on_capture=None):
        self._keys = parse_hotkey(name)
        self._toggle_keys = parse_hotkey(toggle)
        self._on_press, self._on_release = on_press, on_release
        self._on_toggle = on_toggle or (lambda: None)
        self._on_cancel = on_cancel or (lambda: False)
        self._on_capture = on_capture or (lambda value: None)
        self._held = False
        self._toggle_held = False
        self._pressed = set()
        self._consumed = set()
        self._capture = None
        self._lock = Lock()
        self._tap = None
        self._loop = None
        self._thread = None
        self._failed = False

    def capture(self):
        self._capture = set()
        self._pressed.clear()
        self._held = self._toggle_held = False

    def cancel_capture(self):
        self._capture = None
        self._pressed.clear()

    def _intercept(self, event_type, event):
        import Quartz

        code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if event_type == Quartz.kCGEventFlagsChanged:
            pressed = bool(Quartz.CGEventGetFlags(event) & Quartz.kCGEventFlagMaskSecondaryFn) if code == 63 else bool(
                Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateHIDSystemState, code))
        elif event_type in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
            pressed = event_type == Quartz.kCGEventKeyDown
        else:
            return event
        if code == 53 and pressed:
            if self._capture is not None:
                self.cancel_capture()
                self._on_capture(None)
                return None
            return None if self._on_cancel() else event
        consumed = code in self._consumed
        if pressed:
            self._pressed.add(code)
        else:
            self._pressed.discard(code)
            self._consumed.discard(code)
        if self._capture is not None:
            if pressed:
                self._capture.add(code)
            elif not self._pressed and self._capture:
                codes, self._capture = self._capture, None
                names = [REVERSE_CODES.get(key, f"key{key}") for key in sorted(codes, key=lambda key: (key not in MODIFIERS, key))]
                self._on_capture("+".join(names))
            return None
        hold = self._keys <= self._pressed
        toggle = self._toggle_keys <= self._pressed
        self.transition(hold)
        if toggle and not self._toggle_held:
            self._on_toggle()
        self._toggle_held = toggle
        single = code in self._keys and len(self._keys) == 1
        if pressed and (hold or toggle) and code in (self._keys | self._toggle_keys):
            self._consumed.add(code)
            consumed = True
        return None if consumed or single else event

    def transition(self, pressed: bool):
        with self._lock:
            if pressed == self._held:
                return
            self._held = pressed
        (self._on_press if pressed else self._on_release)()

    def _callback(self, proxy, event_type, event, refcon):
        import Quartz

        if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        try:
            return self._intercept(event_type, event)
        except Exception:
            logging.exception("Hotkey event failed")
            return event

    def _run(self):
        import Quartz

        mask = (1 << Quartz.kCGEventKeyDown) | (1 << Quartz.kCGEventKeyUp) | (1 << Quartz.kCGEventFlagsChanged)
        self._tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                            Quartz.kCGEventTapOptionDefault, mask, self._callback, None)
        if self._tap is None:
            self._failed = True
            logging.error("macOS refused the keyboard event tap; Accessibility permission is missing")
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(self._tap, True)
        Quartz.CFRunLoopRun()

    def start(self):
        self._thread = Thread(target=self._run, name="typeflo-hotkey", daemon=True)
        self._thread.start()

    def stop(self):
        if self._tap is not None:
            import Quartz

            Quartz.CGEventTapEnable(self._tap, False)
        if self._loop is not None:
            import Quartz

            Quartz.CFRunLoopStop(self._loop)

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
