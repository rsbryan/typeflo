from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dictate.hotkey import HoldHotkey, hotkey_label, parse_hotkey

FLAGS_CHANGED, KEY_DOWN, KEY_UP = 12, 10, 11
FN_FLAG = 1 << 23
FN, SPACE, ESC, ALT_R, CTRL_L = 63, 49, 53, 61, 59


def make_key(hotkey="fn", toggle="fn+space"):
    key = HoldHotkey.__new__(HoldHotkey)
    key._keys = parse_hotkey(hotkey)
    key._toggle_keys = parse_hotkey(toggle)
    key._on_press, key._on_release, key._on_toggle = Mock(), Mock(), Mock()
    key._on_cancel = Mock(return_value=False)
    key._on_capture = Mock()
    key._held = key._toggle_held = False
    key._pressed, key._consumed = set(), set()
    key._capture = None
    key._lock = Lock()
    return key


class HotkeyTests(unittest.TestCase):
    def setUp(self):
        self.physical = {}
        quartz = SimpleNamespace(
            CGEventGetIntegerValueField=lambda event, field: event["code"],
            CGEventGetFlags=lambda event: event.get("flags", 0),
            CGEventSourceKeyState=lambda state, code: self.physical.get(code, False),
            kCGKeyboardEventKeycode=0, kCGEventFlagsChanged=FLAGS_CHANGED,
            kCGEventKeyDown=KEY_DOWN, kCGEventKeyUp=KEY_UP,
            kCGEventSourceStateHIDSystemState=1, kCGEventFlagMaskSecondaryFn=FN_FLAG,
        )
        patcher = patch.dict("sys.modules", {"Quartz": quartz})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fn(self, key, pressed):
        return key._intercept(FLAGS_CHANGED, {"code": FN, "flags": FN_FLAG if pressed else 0})

    def tap(self, key, code, pressed):
        return key._intercept(KEY_DOWN if pressed else KEY_UP, {"code": code})

    def test_repeats_and_stray_releases(self):
        key = make_key()
        for pressed in (False, True, True, True, False, False, True, False):
            key.transition(pressed)
        self.assertEqual(key._on_press.call_count, 2)
        self.assertEqual(key._on_release.call_count, 2)

    def test_fn_hold_is_consumed(self):
        key = make_key()
        self.assertIsNone(self.fn(key, True))
        key._on_press.assert_called_once()
        self.assertIsNone(self.fn(key, False))
        key._on_release.assert_called_once()
        key._on_toggle.assert_not_called()

    def test_hands_free_combination_fires_once_and_swallows_space(self):
        key = make_key()
        self.fn(key, True)
        self.assertIsNone(self.tap(key, SPACE, True))
        self.assertIsNone(self.tap(key, SPACE, True))
        key._on_toggle.assert_called_once()
        self.assertIsNone(self.tap(key, SPACE, False))
        self.fn(key, False)
        event = {"code": SPACE}
        self.assertIs(key._intercept(KEY_DOWN, event), event)
        key._on_toggle.assert_called_once()

    def test_unrelated_keys_pass_through(self):
        key = make_key()
        event = {"code": 0}
        self.assertIs(key._intercept(KEY_DOWN, event), event)
        self.assertIs(key._intercept(KEY_UP, event), event)
        key._on_press.assert_not_called()

    def test_sided_modifier_uses_physical_key_state(self):
        key = make_key("alt_r", "ctrl+space")
        self.physical[ALT_R] = True
        self.assertIsNone(key._intercept(FLAGS_CHANGED, {"code": ALT_R}))
        other = {"code": 58}
        self.assertIs(key._intercept(FLAGS_CHANGED, other), other)
        self.physical[ALT_R] = False
        self.assertIsNone(key._intercept(FLAGS_CHANGED, {"code": ALT_R}))
        key._on_press.assert_called_once()
        key._on_release.assert_called_once()

    def test_escape_cancels_only_while_active(self):
        key = make_key()
        event = {"code": ESC}
        self.assertIs(key._intercept(KEY_DOWN, event), event)
        key._on_cancel.return_value = True
        self.assertIsNone(key._intercept(KEY_DOWN, event))

    def test_capture_reports_combination_and_escape_aborts(self):
        key = make_key()
        key.capture()
        self.physical[CTRL_L] = True
        self.assertIsNone(key._intercept(FLAGS_CHANGED, {"code": CTRL_L}))
        self.assertIsNone(self.tap(key, SPACE, True))
        self.tap(key, SPACE, False)
        self.physical[CTRL_L] = False
        key._intercept(FLAGS_CHANGED, {"code": CTRL_L})
        key._on_capture.assert_called_once_with("ctrl_l+space")
        key._on_press.assert_not_called()
        key.capture()
        self.assertIsNone(self.tap(key, ESC, True))
        key._on_capture.assert_called_with(None)
        self.assertIsNone(key._capture)


class ParseTests(unittest.TestCase):
    def test_accepted_shortcuts(self):
        self.assertEqual(parse_hotkey("fn"), frozenset({FN}))
        self.assertEqual(parse_hotkey("Fn + Space"), frozenset({FN, SPACE}))
        self.assertEqual(parse_hotkey("ctrl+alt+space"), frozenset({59, 58, SPACE}))
        self.assertEqual(parse_hotkey("f18"), frozenset({79}))

    def test_rejected_shortcuts(self):
        for name in ("", "esc", "space", "a", "cmd+v", "cmd+space", "cmd+cmd_r", "alt_l+alt_r", "fn+fn", "unknown"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_hotkey(name)

    def test_labels(self):
        self.assertEqual(hotkey_label("fn+space"), "fn + Space")
        self.assertEqual(hotkey_label("ctrl_r+f5"), "Right ⌃ + F5")
