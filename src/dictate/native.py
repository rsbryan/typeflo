import json
from pathlib import Path
import plistlib
import subprocess
import sys

import AppKit as AK
from Foundation import NSObject, NSURL, NSMakeRect
import WebKit
import objc

RESOURCES = Path(__file__).parent / "resources"
FRAME_NAME = "TypefloMain"


def permissions():
    from ApplicationServices import AXIsProcessTrusted
    from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

    return {"accessibility": bool(AXIsProcessTrusted()),
            "microphone": int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)) == 3}


def request_permission(kind):
    if kind == "microphone":
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        if int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)) == 0:
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda allowed: None)
            return
        open_settings("Privacy_Microphone")
    elif kind == "accessibility":
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

        if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
            open_settings("Privacy_Accessibility")
    elif kind == "keyboard":
        AK.NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(
            "x-apple.systempreferences:com.apple.Keyboard-Settings.extension"))


def open_settings(pane):
    AK.NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(
        "x-apple.systempreferences:com.apple.preference.security?" + pane))


def microphones():
    import sounddevice as sd

    return [{"id": "default", "name": "System default"}] + [
        {"id": device["name"], "name": device["name"]}
        for device in sd.query_devices() if device["max_input_channels"] > 0]


def launch_at_login(enabled):
    bundle = Path(sys.executable).resolve().parents[2] if getattr(sys, "frozen", False) else None
    if not bundle or bundle.suffix != ".app":
        raise ValueError("Install Typeflo.app before enabling launch at login")
    path = Path.home() / "Library/LaunchAgents/local.typeflo.login.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    if enabled:
        with path.open("wb") as file:
            plistlib.dump({"Label": "local.typeflo.login", "ProgramArguments": ["/usr/bin/open", "-g", str(bundle)],
                          "RunAtLoad": True}, file)
    elif path.exists():
        path.unlink()


class Bridge(NSObject):
    def userContentController_didReceiveScriptMessage_(self, controller, message):
        if not message.frameInfo().isMainFrame():
            return
        body = message.body()
        if isinstance(body, dict) or hasattr(body, "objectForKey_"):
            self.host.handle(dict(body))

    def webView_didFinishNavigation_(self, webview, navigation):
        self.host.ready = True
        self.host.on_ready()

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, decision):
        url = action.request().URL()
        allowed = url.isFileURL() and Path(str(url.path())).resolve().is_relative_to(RESOURCES.resolve())
        decision(WebKit.WKNavigationActionPolicyAllow if allowed else WebKit.WKNavigationActionPolicyCancel)

    def windowShouldClose_(self, window):
        self.host.hide()
        return False


class Hub:
    def __init__(self, handle, on_ready):
        self.handle, self.on_ready = handle, on_ready
        self.ready = False
        self.delegate = Bridge.alloc().init()
        self.delegate.host = self
        settings = WebKit.WKWebViewConfiguration.alloc().init()
        settings.userContentController().addScriptMessageHandler_name_(self.delegate, "typeflo")
        settings.preferences().setJavaScriptCanOpenWindowsAutomatically_(False)
        self.web = WebKit.WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 1080, 760), settings)
        self.web.setNavigationDelegate_(self.delegate)
        mask = AK.NSWindowStyleMaskTitled | AK.NSWindowStyleMaskClosable | AK.NSWindowStyleMaskMiniaturizable | AK.NSWindowStyleMaskResizable
        self.window = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 1080, 760), mask, AK.NSBackingStoreBuffered, False)
        self.window.setTitle_("Typeflo")
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setBackgroundColor_(AK.NSColor.colorWithCalibratedRed_green_blue_alpha_(.974, .971, .96, 1))
        self.window.setMinSize_((880, 640))
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self.delegate)
        self.window.setContentView_(self.web)
        self.window.setCollectionBehavior_(AK.NSWindowCollectionBehaviorFullScreenPrimary | AK.NSWindowCollectionBehaviorManaged)
        self.placed = False
        self.web.loadFileURL_allowingReadAccessToURL_(NSURL.fileURLWithPath_(str(RESOURCES / "index.html")),
                                                    NSURL.fileURLWithPath_(str(RESOURCES)))

    def show(self, page=None):
        if not self.placed:
            self.placed = True
            if not self.window.setFrameUsingName_(FRAME_NAME):
                self.place_on_active_screen()
            self.window.setFrameAutosaveName_(FRAME_NAME)
        self.window.makeKeyAndOrderFront_(None)
        AK.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if page:
            self.evaluate(f"window.Typeflo?.navigate({json.dumps(page)})")

    def hide(self):
        self.window.orderOut_(None)

    def place_on_active_screen(self):
        point = AK.NSEvent.mouseLocation()
        screen = next((screen for screen in AK.NSScreen.screens() if AK.NSPointInRect(point, screen.frame())),
                      AK.NSScreen.mainScreen())
        visible = screen.visibleFrame()
        size = self.window.frame().size
        width = min(size.width, visible.size.width - 40)
        height = min(size.height, visible.size.height - 40)
        self.window.setFrame_display_(NSMakeRect(
            visible.origin.x + (visible.size.width - width) / 2,
            visible.origin.y + (visible.size.height - height) / 2, width, height), True)

    def evaluate(self, script, callback=None):
        if self.ready:
            self.web.evaluateJavaScript_completionHandler_(script, callback)

    def send(self, data):
        self.evaluate("window.Typeflo.receive(" + json.dumps(data, ensure_ascii=True) + ")")

    def snapshot(self, path, callback):
        def complete(image, error):
            if image:
                bitmap = AK.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
                bitmap.representationUsingType_properties_(AK.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(str(path), True)
            callback(error)
        self.web.takeSnapshotWithConfiguration_completionHandler_(None, complete)


class OverlayTarget(NSObject):
    def stop_(self, sender):
        self.action("stop")

    def cancel_(self, sender):
        self.action("cancel")


class Overlay:
    WIDTH = 240
    HEIGHT = 36
    BAR_X = 14
    BAR_SPACING = 5
    BAR_WIDTH = 3
    BAR_MIN = 4
    BAR_MAX = 16
    BUTTON = 26

    def __init__(self, action):
        self.target = OverlayTarget.alloc().init()
        self.target.action = action
        rect = NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        self.panel = AK.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, AK.NSWindowStyleMaskBorderless | AK.NSWindowStyleMaskNonactivatingPanel,
            AK.NSBackingStoreBuffered, False)
        self.panel.setLevel_(AK.NSFloatingWindowLevel)
        self.panel.setCollectionBehavior_(AK.NSWindowCollectionBehaviorCanJoinAllSpaces | AK.NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(AK.NSColor.clearColor())
        self.panel.setHasShadow_(True)
        self.panel.setHidesOnDeactivate_(False)
        view = AK.NSView.alloc().initWithFrame_(rect)
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(self.HEIGHT / 2)
        view.layer().setBackgroundColor_(AK.NSColor.colorWithCalibratedRed_green_blue_alpha_(.13, .14, .14, .97).CGColor())
        label_x = self.BAR_X + 4 * self.BAR_SPACING + 8
        buttons_x = self.WIDTH - 2 * self.BUTTON - 6
        self.label = AK.NSTextField.labelWithString_("Listening")
        self.label.setFrame_(NSMakeRect(label_x, (self.HEIGHT - 16) / 2, buttons_x - label_x, 16))
        self.label.setFont_(AK.NSFont.systemFontOfSize_weight_(12, AK.NSFontWeightMedium))
        self.label.setTextColor_(AK.NSColor.whiteColor())
        view.addSubview_(self.label)
        self.bars = []
        for i in range(4):
            bar = AK.NSView.alloc().initWithFrame_(self._bar_frame(i, self.BAR_MIN))
            bar.setWantsLayer_(True)
            bar.layer().setCornerRadius_(self.BAR_WIDTH / 2)
            bar.layer().setBackgroundColor_(AK.NSColor.colorWithCalibratedRed_green_blue_alpha_(.92, .62, .49, 1).CGColor())
            view.addSubview_(bar)
            self.bars.append(bar)
        for index, (title, selector) in enumerate((("■", "stop:"), ("×", "cancel:"))):
            button = AK.NSButton.alloc().initWithFrame_(NSMakeRect(
                buttons_x + index * (self.BUTTON + 2), (self.HEIGHT - self.BUTTON) / 2, self.BUTTON, self.BUTTON))
            button.setTitle_(title)
            button.setBordered_(False)
            button.setFont_(AK.NSFont.systemFontOfSize_(15))
            button.setContentTintColor_(AK.NSColor.whiteColor())
            button.setTarget_(self.target)
            button.setAction_(selector)
            view.addSubview_(button)
        self.panel.setContentView_(view)

    def _bar_frame(self, index, height):
        return NSMakeRect(self.BAR_X + index * self.BAR_SPACING, (self.HEIGHT - height) / 2, self.BAR_WIDTH, height)

    def update(self, state, level=0, enabled=True, locked=False):
        if not enabled or state not in {"recording", "processing", "cancelling"}:
            self.panel.orderOut_(None)
            return
        point = AK.NSEvent.mouseLocation()
        screen = next((screen for screen in AK.NSScreen.screens() if AK.NSPointInRect(point, screen.frame())), AK.NSScreen.mainScreen())
        frame = screen.visibleFrame()
        self.panel.setFrameOrigin_((frame.origin.x + (frame.size.width - self.WIDTH) / 2, frame.origin.y + 20))
        self.panel.orderFrontRegardless()
        self.label.setStringValue_(("Listening · hands-free" if locked else "Listening…") if state == "recording" else "Polishing your words…")
        for i, bar in enumerate(self.bars):
            height = self.BAR_MIN + level * (self.BAR_MAX - self.BAR_MIN - abs(i - 1.5) * 3)
            bar.setFrame_(self._bar_frame(i, height))


def install_edit_menu():
    menu = AK.NSMenu.alloc().initWithTitle_("Main")
    for title, actions in (("Typeflo", (("About Typeflo", "orderFrontStandardAboutPanel:", ""),
                                      ("Quit Typeflo", "terminate:", "q"))),
                           ("Edit", (("Undo", "undo:", "z"), ("Redo", "redo:", "Z"),
                                     ("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                                     ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")))):
        top = AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        submenu = AK.NSMenu.alloc().initWithTitle_(title)
        for name, selector, key in actions:
            submenu.addItem_(AK.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(name, selector, key))
        top.setSubmenu_(submenu)
        menu.addItem_(top)
    AK.NSApplication.sharedApplication().setMainMenu_(menu)
