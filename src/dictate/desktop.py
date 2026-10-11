from dataclasses import asdict
import fcntl
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
from time import perf_counter

import AppKit as AK
from Foundation import NSURL
import objc
import rumps

from .audio import MAX_SECONDS
from .config import DATA_PATH, save_config, validate_config
from .engine import Worker
from .history import History
from .hotkey import HoldHotkey, hotkey_label
from .context import fit_to_context, read_context
from .inject import Injector
from .models import CATALOG, catalog
from .native import Hub, Overlay, RESOURCES, install_edit_menu, launch_at_login, microphones, permissions, request_permission


def reopen_application(self, application, visible):
    self._app["hub"].show()
    return True


def should_terminate(self, application):
    self._app["on_terminate"]()
    return AK.NSTerminateNow


objc.classAddMethods(rumps.rumps.NSApp, [
    objc.selector(reopen_application, selector=b"applicationShouldHandleReopen:hasVisibleWindows:", signature=b"B@:@B"),
    objc.selector(should_terminate, selector=b"applicationShouldTerminate:", signature=b"Q@:@"),
])


class TypefloApp(rumps.App):
    def __init__(self, config, config_path, smoke_dir=None):
        super().__init__("Typeflo", title="◌", quit_button=None)
        self.config, self.config_path = config, config_path
        self.smoke_dir = smoke_dir
        data_path = Path(smoke_dir) if smoke_dir else DATA_PATH
        data_path.mkdir(parents=True, exist_ok=True)
        self.instance_lock = (data_path / "app.lock").open("w")
        try:
            fcntl.flock(self.instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Typeflo is already running. Open it from the menu bar.") from error
        log = RotatingFileHandler(data_path / "typeflo.log", maxBytes=2_000_000, backupCount=2)
        log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(log)
        self.history = History(data_path / "history.sqlite3")
        self.incoming = Queue()
        self.worker = Worker()
        self.worker.start()
        self.worker.commands.put(("load", config))
        self.state, self.error = "loading", ""
        self.session = 0
        self.cancelled = set()
        self.locked = False
        self.pressed_at = 0.0
        self.capture_start_ms = 0.0
        self.paste_finished_at = None
        self.application = ""
        self.startup = {}
        self.memory_gb = 0
        self.hotkey = None
        self.capture_field = None
        self.last_external = None
        self.last_permissions = {}
        self.deferred = []
        self.download = None
        self.download_process = None
        self.download_thread = None
        self.pending_config = None
        self.model_catalog = catalog(config)
        self.devices = microphones()
        self.injector = Injector()
        self.hub = Hub(self.handle, self.publish)
        self.overlay = Overlay(lambda action: self.incoming.put((action, perf_counter())))
        self.status_item = rumps.MenuItem("Loading models…")
        self.menu = [rumps.MenuItem("Open Typeflo", callback=lambda _: self.hub.show()), self.status_item,
                     None, rumps.MenuItem("Start / Stop Dictation", callback=lambda _: self.toggle()),
                     rumps.MenuItem("Paste Last Transcript", callback=lambda _: self.paste_last()),
                     rumps.MenuItem("Models", callback=lambda _: self.hub.show("models")),
                     rumps.MenuItem("Settings…", callback=lambda _: self.hub.show("settings")),
                     None, rumps.MenuItem("Quit Typeflo", callback=self.quit)]
        AK.NSApplication.sharedApplication().setActivationPolicy_(AK.NSApplicationActivationPolicyRegular)
        self.on_terminate = self.cleanup
        install_edit_menu()
        self.timer = rumps.Timer(self.tick, .025)
        self.timer.start()
        self.last_refresh = 0
        self.smoke_started = False
        self.closed = False
        rumps.events.before_start.register(self.hub.show)
        rumps.events.before_quit.register(self.cleanup)
        rumps.events.on_sleep.register(self.cancel)

    def snapshot(self):
        return {"config": asdict(self.config), "history": self.history.list(), "stats": self.history.stats(),
                "models": self.model_catalog, "microphones": self.devices, "permissions": permissions(),
                "status": self.state, "error": self.error, "memory_gb": self.memory_gb,
                "startup": self.startup, "download": self.download,
                "hotkey_label": hotkey_label(self.config.hotkey),
                "hands_free_label": hotkey_label(self.config.hands_free_hotkey),
                "conflict": any(str(app.localizedName()) == "Wispr Flow" for app in AK.NSWorkspace.sharedWorkspace().runningApplications())}

    def publish(self):
        self.hub.send({"state": self.snapshot()})

    def toast(self, text, error=False):
        self.hub.send({"toast": text, "error": error})

    def ensure_hotkey(self):
        if self.smoke_dir or self.hotkey or not permissions()["accessibility"]:
            return
        self.hotkey = HoldHotkey(self.config.hotkey,
                                 lambda: self.incoming.put(("press", perf_counter())),
                                 lambda: self.incoming.put(("release", perf_counter())),
                                 self.config.hands_free_hotkey,
                                 lambda: self.incoming.put(("toggle", perf_counter())),
                                 self.cancel_from_hotkey,
                                 lambda key: self.incoming.put(("captured", key)))
        self.hotkey.start()
        logging.info("hotkey listener started: hold %s, hands-free %s", self.config.hotkey, self.config.hands_free_hotkey)

    def cancel_from_hotkey(self):
        if self.state in {"recording", "processing"}:
            self.incoming.put(("cancel", perf_counter()))
            return True
        return False

    def restart_hotkey(self):
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey = None
        self.ensure_hotkey()

    def start(self, timestamp=None, locked=False):
        if self.state != "idle" or self.capture_field:
            return
        grants = permissions()
        if not grants["microphone"] or not grants["accessibility"]:
            self.error = "Enable Microphone and Accessibility to start dictating."
            self.hub.show("settings")
            self.publish()
            return
        self.session += 1
        self.state, self.error, self.locked = "recording", "", locked
        self.pressed_at = timestamp or perf_counter()
        front = AK.NSWorkspace.sharedWorkspace().frontmostApplication()
        self.application = str(front.localizedName()) if front else ""
        self.worker.commands.put(("start", (self.session, self.pressed_at, self.config)))
        self.publish()

    def stop(self, timestamp=None, force=False):
        if self.state != "recording" or (self.locked and not force):
            return
        released = timestamp or perf_counter()
        self.state = "processing"
        self.worker.commands.put(("stop", (self.session, released, (released - self.pressed_at) * 1000)))
        self.publish()

    def toggle(self, timestamp=None):
        if self.state == "recording":
            if self.locked:
                self.stop(timestamp, force=True)
            else:
                self.locked = True
        elif self.state == "idle":
            self.start(timestamp, locked=True)

    def cancel(self):
        if self.state == "recording":
            self.cancelled.add(self.session)
            self.state = "cancelling"
            self.worker.commands.put(("cancel", self.session))
        elif self.state == "processing":
            self.cancelled.add(self.session)
            self.state = "cancelling"
        self.publish()

    def update_settings(self, values):
        if self.state not in {"idle", "error"}:
            raise ValueError("Finish your current dictation or model load first")
        updated = validate_config(asdict(self.config) | dict(values))
        model_fields = ("asr_model", "llm_model", "llm_enabled", "personal_dictionary", "style")
        reload = self.worker.pipeline is None or any(getattr(updated, key) != getattr(self.config, key) for key in model_fields)
        if updated.launch_at_login != self.config.launch_at_login:
            launch_at_login(updated.launch_at_login)
        if reload:
            self.pending_config = updated
            self.state, self.error = "loading", ""
            self.worker.commands.put(("load", updated))
        else:
            self.commit_config(updated)
            self.worker.pipeline.config = updated
        self.publish()

    def commit_config(self, config):
        changed_hotkey = (config.hotkey, config.hands_free_hotkey) != (self.config.hotkey, self.config.hands_free_hotkey)
        save_config(config, self.config_path)
        self.config = config
        self.pending_config = None
        self.model_catalog = catalog(config)
        if changed_hotkey:
            self.restart_hotkey()

    def copy(self, text):
        if self.injector.pending:
            raise ValueError("Wait for the current paste to finish")
        board = AK.NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_(text, AK.NSPasteboardTypeString)

    def restore_focus(self):
        self.hub.hide()
        if self.last_external and not self.last_external.isTerminated():
            self.last_external.activateWithOptions_(AK.NSApplicationActivateIgnoringOtherApps)

    def paste_last(self):
        rows = [row for row in self.history.list() if row["kind"] == "dictation" and row["text"]]
        if not rows:
            self.toast("There is no saved transcript to paste yet.")
            return
        if self.state != "idle":
            self.toast("Finish the current dictation first.", True)
            return
        self.restore_focus()
        self.deferred.append((perf_counter() + .2, lambda: self.paste_text(rows[0]["text"])))

    def paste_text(self, text):
        front = AK.NSWorkspace.sharedWorkspace().frontmostApplication()
        if front and front.processIdentifier() != os.getpid():
            context = read_context(front.processIdentifier())
            logging.info("context %s", "read" if context else "unavailable")
            if context:
                text = fit_to_context(text, *context, self.config.personal_dictionary)
        self.injector.paste(text)
        self.paste_finished_at = perf_counter()
        self.state = "processing"
        return text

    def download_model(self, identifier):
        if self.download and self.download["active"]:
            raise ValueError("A model download is already running")
        if not isinstance(identifier, str) or len(identifier) > 300:
            raise ValueError("Enter a Hugging Face model ID")
        from huggingface_hub.utils import validate_repo_id

        validate_repo_id(identifier)
        self.download = {"id": identifier, "active": True, "message": "Downloading model weights…"}
        self.publish()
        command = [sys.executable] + ([] if getattr(sys, "frozen", False) else ["-m", "dictate"])
        command += ["--config", str(self.config_path), "--download-model", identifier]

        def download():
            try:
                self.download_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                output = []
                for line in self.download_process.stdout:
                    output.append(line)
                    output = output[-15:]
                code = self.download_process.wait()
                self.incoming.put(("download_done", (identifier, code, "".join(output)[-1500:])))
            except Exception as error:
                self.incoming.put(("download_done", (identifier, 1, str(error))))
        self.download_thread = Thread(target=download, name="typeflo-download", daemon=True)
        self.download_thread.start()

    def handle(self, message):
        identifier = message.get("id")
        payload = message.get("payload") or {}
        action = message.get("action")
        try:
            if not isinstance(payload, dict):
                payload = dict(payload)
            if action == "refresh":
                self.devices = microphones()
                self.publish()
            elif action == "save_settings":
                self.update_settings(payload)
            elif action == "permission":
                request_permission(payload.get("kind"))
            elif action == "capture_shortcut":
                if self.state != "idle":
                    raise ValueError("Wait until Typeflo is ready")
                self.ensure_hotkey()
                if not self.hotkey:
                    raise ValueError("Enable Accessibility first, or enter the shortcut manually")
                self.capture_field = payload.get("field")
                if self.capture_field not in {"hotkey", "hands_free_hotkey"}:
                    raise ValueError("Unknown shortcut")
                self.hotkey.capture()
            elif action == "cancel_capture":
                if self.hotkey:
                    self.hotkey.cancel_capture()
                self.capture_field = None
            elif action == "download_model":
                self.download_model(payload.get("id"))
            elif action == "benchmark":
                if self.state != "idle":
                    raise ValueError("Wait for Typeflo to finish loading or dictating")
                self.state = "benchmarking"
                self.worker.commands.put(("benchmark", RESOURCES / "benchmark.wav"))
                self.publish()
            elif action == "record":
                if self.state == "recording":
                    self.stop(force=True)
                elif self.state == "idle":
                    self.restore_focus()
                    self.deferred.append((perf_counter() + .2, lambda: self.start(locked=True)))
            elif action == "cancel":
                self.cancel()
            elif action == "copy":
                row = next((row for row in self.history.list(5000) if row["id"] == int(payload.get("id", 0))), None)
                if not row or not row["text"]:
                    raise ValueError("This transcript was not saved")
                self.copy(row["text"])
            elif action == "delete_history":
                self.history.delete(int(payload["id"]))
                self.publish()
            elif action == "clear_history":
                self.history.clear()
                self.publish()
            elif action == "export_history":
                panel = AK.NSSavePanel.savePanel()
                panel.setNameFieldStringValue_("typeflo-history.json")
                if panel.runModal() == AK.NSModalResponseOK:
                    Path(str(panel.URL().path())).write_text(json.dumps(self.history.list(5000), ensure_ascii=False, indent=2))
            elif action == "open_data":
                AK.NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(DATA_PATH)))
            elif action == "retry":
                self.state, self.error = "loading", ""
                self.worker.commands.put(("load", self.config))
                self.publish()
            else:
                raise ValueError("Unknown action")
            self.hub.send({"reply": identifier, "ok": True})
        except Exception as error:
            logging.exception("Interface action failed: %s", action)
            self.hub.send({"reply": identifier, "ok": False, "error": str(error)})

    def process_event(self, kind, payload):
        if kind == "ready":
            self.commit_config(payload["config"])
            self.startup, self.memory_gb = payload["startup"], payload["memory_gb"]
            self.state, self.error = "idle", ""
            self.ensure_hotkey()
        elif kind == "started":
            _, self.capture_start_ms = payload
        elif kind == "result":
            session, result, released_at, ready_at = payload
            if session in self.cancelled:
                self.cancelled.discard(session)
                self.state = "idle"
            else:
                result.timings["capture_start_ms"] = round(self.capture_start_ms, 2)
                paste_started = perf_counter()
                result.timings["ui_wait_ms"] = round((paste_started - ready_at) * 1000, 2)
                try:
                    if result.text:
                        result.text = self.paste_text(result.text)
                    else:
                        self.state = "idle"
                        self.toast("No speech detected. Try speaking a little closer to your microphone.")
                except Exception as error:
                    self.state, self.error = "idle", str(error)
                    self.toast("Your transcript is in History. " + str(error), True)
                finally:
                    result.timings["paste_dispatch_ms"] = round((perf_counter() - paste_started) * 1000, 2)
                    result.timings["release_to_dispatch_ms"] = round((perf_counter() - released_at) * 1000, 2)
                    if result.text:
                        self.history.add(result, self.config, self.application)
                    logging.info("dictation %s", json.dumps(result.timings))
        elif kind == "cancelled":
            self.cancelled.discard(payload)
            self.state = "idle"
        elif kind == "benchmark":
            for result in payload:
                self.history.add(result, self.config, "Benchmark", "benchmark")
                logging.info("benchmark %s", json.dumps(result.timings))
            self.state = "idle"
            self.toast("Benchmark complete. Three runs saved to Insights.")
        elif kind == "error":
            command, self.error = payload
            self.pending_config = None
            self.state = "idle" if self.worker.pipeline else "error"
            self.toast(self.error, True)
        self.publish()

    def tick(self, timer):
        if self.closed:
            return
        try:
            now = perf_counter()
            deferred, self.deferred = self.deferred, []
            for when, callback in deferred:
                if now >= when:
                    callback()
                else:
                    self.deferred.append((when, callback))
            if self.injector.restore():
                logging.info("clipboard restore_wait_ms=%.2f", (now - self.paste_finished_at) * 1000)
                self.paste_finished_at = None
                self.state = "idle"
                self.publish()
            for source in (self.incoming, self.worker.events):
                while True:
                    try:
                        kind, payload = source.get_nowait()
                    except Empty:
                        break
                    if source is self.worker.events:
                        self.process_event(kind, payload)
                    elif kind == "press":
                        self.start(payload)
                    elif kind == "release":
                        self.stop(payload)
                    elif kind == "toggle":
                        self.toggle(payload)
                    elif kind == "stop":
                        self.stop(force=True)
                    elif kind == "cancel":
                        self.cancel()
                    elif kind == "captured":
                        field, self.capture_field = self.capture_field, None
                        if payload and field:
                            try:
                                self.update_settings({field: payload})
                                self.hub.send({"shortcut": payload, "field": field})
                            except ValueError as error:
                                self.toast(str(error), True)
                        else:
                            self.hub.send({"shortcut": None})
                    elif kind == "download_done":
                        identifier, code, error = payload
                        self.download = {"id": identifier, "active": False, "message": "Ready to use" if not code else error}
                        self.model_catalog = catalog(self.config)
                        self.toast("Model downloaded. Select Use model to load it." if not code else "Download failed. " + error, bool(code))
                        self.publish()
            if self.state == "recording" and now - self.pressed_at >= MAX_SECONDS:
                self.stop(force=True)
            level = self.worker.recorder.level if self.worker.recorder else 0
            self.overlay.update(self.state, level, self.config.show_overlay, self.locked)
            if now - self.last_refresh > .5:
                self.last_refresh = now
                front = AK.NSWorkspace.sharedWorkspace().frontmostApplication()
                if front and front.processIdentifier() != os.getpid():
                    self.last_external = front
                grants = permissions()
                if grants != self.last_permissions:
                    self.last_permissions = grants
                    self.ensure_hotkey()
                    self.publish()
                if self.hotkey and not self.hotkey.is_alive():
                    self.hotkey = None
                    self.error = "Keyboard listener stopped. Check Accessibility in System Settings, then retry."
                    self.cancel()
                title = {"loading": "◌", "idle": "◉", "recording": "●", "processing": "…", "benchmarking": "…", "error": "!"}.get(self.state, "…")
                if title != self.title:
                    self.title = title
                self.status_item.title = f"Hold {hotkey_label(self.config.hotkey)} to dictate" if self.state == "idle" else self.state.capitalize()
                self.hub.send({"status": self.state, "level": level})
                if self.smoke_dir and self.hub.ready and self.state in {"idle", "error"} and not self.smoke_started:
                    self.smoke_started = True
                    self.smoke_next(iter(["home", "insights", "dictionary", "snippets", "style", "models", "settings"]))
        except Exception as error:
            logging.exception("Typeflo event failed")
            self.error = str(error)

    def smoke_next(self, pages):
        page = next(pages, None)
        if page is None:
            self.deferred.append((perf_counter() + .3, lambda: self.quit(None)))
            return
        self.hub.show(page)
        def capture():
            self.hub.snapshot(Path(self.smoke_dir) / f"{page}.png", lambda error: self.smoke_next(pages))
        self.deferred.append((perf_counter() + .4, capture))

    def cleanup(self):
        if self.closed:
            return
        self.closed = True
        if self.hotkey:
            self.hotkey.stop()
        if self.download_process and self.download_process.poll() is None:
            self.download_process.terminate()
        self.worker.commands.put(("quit", None))
        self.worker.join(timeout=2)
        self.history.close()
        self.instance_lock.close()

    def quit(self, _):
        if self.injector.pending:
            self.deferred.append((perf_counter() + .4, lambda: self.quit(None)))
            return
        self.cleanup()
        rumps.quit_application()
