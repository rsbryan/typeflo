from time import perf_counter


class Injector:
    def __init__(self, pasteboard=None, restore_delay: float = 0.35):
        from AppKit import NSPasteboard

        self.board = pasteboard if pasteboard is not None else NSPasteboard.generalPasteboard()
        self.delay = restore_delay
        self._saved = None
        self._owned_count = None
        self._deadline = 0.0

    @property
    def pending(self) -> bool:
        return self._saved is not None

    def _snapshot(self):
        from AppKit import NSPasteboardItem

        count = self.board.changeCount()
        saved = []
        for item in self.board.pasteboardItems() or []:
            clone = NSPasteboardItem.alloc().init()
            for kind in item.types():
                data = item.dataForType_(kind)
                if data is None or not clone.setData_forType_(data, kind):
                    raise RuntimeError("Cannot preserve this clipboard format; paste cancelled")
            saved.append(clone)
        if self.board.changeCount() != count:
            raise RuntimeError("Clipboard changed while reading it; paste cancelled")
        return saved

    def paste(self, text: str) -> None:
        from ApplicationServices import AXIsProcessTrusted
        from AppKit import NSPasteboardTypeString
        import Quartz

        if self.pending:
            raise RuntimeError("Previous paste is still waiting for clipboard restoration")
        if not AXIsProcessTrusted():
            raise RuntimeError("Enable Accessibility for Typeflo in System Settings")
        source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStatePrivate)
        down = Quartz.CGEventCreateKeyboardEvent(source, 9, True)
        up = Quartz.CGEventCreateKeyboardEvent(source, 9, False)
        if down is None or up is None:
            raise RuntimeError("macOS could not create paste events")
        self._saved = self._snapshot()
        self._owned_count = self.board.clearContents()
        try:
            if not self.board.setString_forType_(text, NSPasteboardTypeString):
                raise RuntimeError("Cannot write dictation to the clipboard")
            self._owned_count = self.board.changeCount()
            for event in (down, up):
                Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            self._deadline = perf_counter() + self.delay
        except Exception:
            self.restore(force=True)
            raise

    def restore(self, force: bool = False) -> bool:
        if not self.pending or (not force and perf_counter() < self._deadline):
            return False
        saved, self._saved = self._saved, None
        if self.board.changeCount() == self._owned_count:
            self.board.clearContents()
            if saved and not self.board.writeObjects_(saved):
                raise RuntimeError("macOS could not restore the clipboard")
        return True
