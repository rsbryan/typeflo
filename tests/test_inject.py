from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dictate.inject import Injector


class Item:
    def __init__(self, data=None):
        self.data = dict(data or {})

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    def types(self):
        return list(self.data)

    def dataForType_(self, kind):
        return self.data[kind]

    def setData_forType_(self, value, kind):
        self.data[kind] = bytes(value)
        return True


class Board:
    def __init__(self, items):
        self.items = items
        self.count = 0

    def pasteboardItems(self):
        return self.items

    def changeCount(self):
        return self.count

    def clearContents(self):
        self.count += 1
        self.items = []
        return self.count

    def setString_forType_(self, text, kind):
        self.items = [Item({kind: text.encode()})]
        self.count += 1
        return True

    def writeObjects_(self, items):
        self.items = items
        self.count += 1
        return True


class InjectionTests(unittest.TestCase):
    def setUp(self):
        self.quartz = SimpleNamespace(
            AXIsProcessTrusted=Mock(return_value=True),
            CGEventSourceCreate=Mock(return_value=object()),
            CGEventCreateKeyboardEvent=Mock(side_effect=lambda *args: object()),
            CGEventSetFlags=Mock(), CGEventPost=Mock(),
            kCGEventSourceStatePrivate=0, kCGEventFlagMaskCommand=1, kCGHIDEventTap=0,
        )
        self.patch = patch.dict("sys.modules", {
            "AppKit": SimpleNamespace(NSPasteboard=object(), NSPasteboardItem=Item, NSPasteboardTypeString="text"),
            "ApplicationServices": SimpleNamespace(AXIsProcessTrusted=self.quartz.AXIsProcessTrusted),
            "Quartz": self.quartz,
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_all_formats_and_items_restored(self):
        board = Board([Item({"text": b"old", "rtf": b"{rich}"}), Item({"png": b"\x89PNG"})])
        original = [item.data.copy() for item in board.items]
        injector = Injector(board)
        injector.paste("new")
        self.assertEqual(board.items[0].data, {"text": b"new"})
        self.assertEqual(self.quartz.CGEventPost.call_count, 2)
        self.assertFalse(injector.restore())
        self.assertTrue(injector.restore(force=True))
        self.assertEqual([item.data for item in board.items], original)

    def test_empty_clipboard_restored_to_empty(self):
        board = Board([])
        injector = Injector(board)
        injector.paste("new")
        self.assertTrue(injector.pending)
        injector.restore(force=True)
        self.assertEqual(board.items, [])

    def test_newer_copy_is_preserved(self):
        board = Board([Item({"text": b"old"})])
        injector = Injector(board)
        injector.paste("new")
        board.setString_forType_("user copy", "text")
        injector.restore(force=True)
        self.assertEqual(board.items[0].data, {"text": b"user copy"})

    def test_unreadable_format_does_not_clear_clipboard(self):
        board = Board([Item({"promised": None})])
        with self.assertRaisesRegex(RuntimeError, "preserve"):
            Injector(board).paste("new")
        self.assertEqual(board.count, 0)
        self.quartz.CGEventPost.assert_not_called()

    def test_missing_permission_does_not_clear_clipboard(self):
        self.quartz.AXIsProcessTrusted.return_value = False
        board = Board([Item({"text": b"old"})])
        with self.assertRaisesRegex(RuntimeError, "Accessibility"):
            Injector(board).paste("new")
        self.assertEqual(board.count, 0)

    def test_post_failure_restores_clipboard(self):
        board = Board([Item({"text": b"old"})])
        self.quartz.CGEventPost.side_effect = RuntimeError("post failed")
        injector = Injector(board)
        with self.assertRaisesRegex(RuntimeError, "post failed"):
            injector.paste("new")
        self.assertFalse(injector.pending)
        self.assertEqual(board.items[0].data, {"text": b"old"})
