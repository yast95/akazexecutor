from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

import FAPI


APP_NAME = "AkazExecutor"
APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
APP_DIR = APPDATA / APP_NAME
TABS_FILE = APP_DIR / "tabs.json"
UI_DIR = Path(__file__).resolve().parent / "ui"
APP_DIR.mkdir(parents=True, exist_ok=True)


class AppController(QObject):
    statusChanged = Signal(str, str)
    logMessage = Signal(str, str)

    def __init__(self, window=None, parent=None):
        super().__init__(parent)
        self.window = window
        self.executor = None
        self.sdk = None
        self._load_lock = threading.Lock()
        self._action_lock = threading.Lock()
        self._loading = False
        self._busy = False

    def _set_status(self, state: str, detail: str):
        self.statusChanged.emit(state, detail)

    def _log(self, message: str, level: str = "info"):
        self.logMessage.emit(message, level)

    def start(self):
        threading.Thread(
            target=self._load_worker,
            daemon=True,
            name="AkazLoad"
        ).start()

    def _load_worker(self):
        if not self._load_lock.acquire(blocking=False):
            return
        self._loading = True
        self._set_status("loading", "Preparing runtime")
        try:
            if not FAPI.roblox_open():
                self._set_status("offline", "Roblox not detected")
                return

            if self.executor is not None and self.sdk is not None:
                try:
                    if not _pid_exists(self.sdk.mem.process_id):
                        self.executor = None
                        self.sdk = None
                except Exception:
                    self.executor = None
                    self.sdk = None

            if self.executor is None or self.sdk is None:
                self.executor = FAPI.Executor()
                self.sdk = self.executor.sdk
                self._log("Runtime connected", "success")

            self._publish_status()
        except Exception as exc:
            self.executor = None
            self.sdk = None
            self._set_status("error", "Runtime initialization failed")
            self._log(f"{type(exc).__name__}: {exc}", "error")
        finally:
            self._loading = False
            self._load_lock.release()

    def _publish_status(self):
        try:
            if not FAPI.roblox_open():
                self._set_status("offline", "Roblox not detected")
                return
            if self.executor is not None and self.executor.injected:
                self._set_status("attached", "Runtime attached")
            elif self.executor is not None:
                self._set_status("ready", "Roblox detected")
            else:
                self._set_status("loading", "Preparing runtime")
        except Exception:
            self._set_status("offline", "Runtime unavailable")

    @Slot()
    def inject(self):
        if not self._action_lock.acquire(blocking=False):
            return
        self._busy = True
        self._set_status("injecting", "Attaching runtime")
        self._log("Attach requested", "info")

        def worker():
            try:
                if not FAPI.roblox_open():
                    raise RuntimeError("Roblox is not running")
                if self.executor is None or self.sdk is None:
                    self._load_worker()
                if self.executor is None:
                    raise RuntimeError("Runtime could not be initialized")

                self.executor.inject()

                if self.executor.injected:
                    self._set_status("attached", "Runtime attached")
                    self._log("Runtime attached", "success")
                else:
                    self._set_status("ready", "Attach did not complete")
                    self._log("Attach did not complete", "warning")
            except Exception as exc:
                self._set_status("error", "Attach failed")
                self._log(f"{type(exc).__name__}: {exc}", "error")
            finally:
                self._busy = False
                self._action_lock.release()

        threading.Thread(target=worker, daemon=True, name="AkazInject").start()

    @Slot(str)
    def execute(self, source: str):
        if not self._action_lock.acquire(blocking=False):
            return

        self._busy = True

        def worker():
            try:
                if self.executor is None or not self.executor.injected:
                    raise RuntimeError("Attach the runtime before running a script")
                if not source.strip():
                    raise ValueError("The current script is empty")

                self._set_status("executing", "Compiling and sending")
                started = time.perf_counter()
                self.executor.execute(source)
                elapsed_ms = (time.perf_counter() - started) * 1000
                self._log(f"Executed in {elapsed_ms:.0f} ms", "success")
                self._set_status("attached", "Runtime attached")
            except Exception as exc:
                self._set_status("error", "Execution failed")
                self._log(f"{type(exc).__name__}: {exc}", "error")
            finally:
                self._busy = False
                self._action_lock.release()

        threading.Thread(target=worker, daemon=True, name="AkazExecute").start()

    @Slot(str, result=str)
    def open_file(self, title: str):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            None,
            title or "Open Luau script",
            str(APP_DIR),
            "Luau source (*.lua *.luau);;Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return ""

        try:
            return Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Path(path).read_text(encoding="utf-8", errors="replace")

    @Slot(str, str, result=str)
    def save_file(self, content: str, suggested_name: str):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            None,
            "Export Luau script",
            str(APP_DIR / (suggested_name or "Script.luau")),
            "Luau source (*.lua *.luau);;All files (*.*)",
        )
        if not path:
            return ""

        try:
            Path(path).write_text(content, encoding="utf-8")
            return path
        except OSError as exc:
            self._log(f"Export failed: {exc}", "error")
            return ""

    @Slot(result=str)
    def load_tabs(self):
        default = [{
            "id": "script-1",
            "name": "Script 1",
            "content": 'print("Hello, World!")',
        }]

        try:
            data = json.loads(TABS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                clean = []
                for tab in data:
                    if not isinstance(tab, dict):
                        continue
                    clean.append({
                        "id": str(tab.get("id") or f"script-{len(clean)+1}"),
                        "name": str(tab.get("name") or f"Script {len(clean)+1}"),
                        "content": str(tab.get("content") or ""),
                    })
                if clean:
                    return json.dumps(clean, ensure_ascii=False)
        except (OSError, ValueError, TypeError):
            pass

        return json.dumps(default)

    @Slot(str, result=bool)
    def save_tabs(self, payload: str):
        try:
            data = json.loads(payload)
            if not isinstance(data, list):
                return False
            temp = TABS_FILE.with_suffix(".tmp")
            temp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(TABS_FILE)
            return True
        except (OSError, ValueError, TypeError):
            return False

    @Slot(result=str)
    def runtime_info(self):
        result = {
            "state": "offline",
            "roblox": False,
            "pid": None,
            "version": None,
            "injected": False,
        }

        try:
            result["roblox"] = bool(FAPI.roblox_open())
        except Exception:
            pass

        if self.sdk is not None:
            try:
                result["pid"] = self.sdk.mem.process_id
                result["version"] = self.sdk.version
            except Exception:
                pass

        try:
            result["injected"] = bool(self.executor and self.executor.injected)
        except Exception:
            result["injected"] = False

        if result["injected"]:
            result["state"] = "attached"
        elif result["roblox"]:
            result["state"] = "ready"

        return json.dumps(result)

    @Slot()
    def minimize(self):
        if self.window:
            self.window.showMinimized()

    @Slot()
    def maximize_restore(self):
        if not self.window:
            return
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    @Slot()
    def close(self):
        if self.window:
            self.window.close()

    @Slot(bool)
    def set_topmost(self, enabled: bool):
        if not self.window:
            return
        flags = self.window.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.window.setWindowFlags(flags)
        self.window.show()

    @Slot(result=bool)
    def is_busy(self):
        return self._loading or self._busy

    def shutdown(self):
        try:
            FAPI.bridge.stop_bridge()
        except Exception:
            pass


class WebView(QWebEngineView):
    def __init__(self, controller: AppController, parent=None):
        super().__init__(parent)

        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            False,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.ErrorPageEnabled,
            False,
        )

        self.page().setBackgroundColor(QColor("#0c0e11"))

        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", controller)
        self.page().setWebChannel(self.channel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        controller.statusChanged.connect(self._forward_status)
        controller.logMessage.connect(self._forward_log)

        self.load(QUrl.fromLocalFile(str(UI_DIR / "index.html")))

    @Slot(str, str)
    def _forward_status(self, state: str, detail: str):
        payload = json.dumps({"state": state, "detail": detail})
        self.page().runJavaScript(
            f"window.__akazStatus && window.__akazStatus({payload});"
        )

    @Slot(str, str)
    def _forward_log(self, message: str, level: str):
        payload = json.dumps({"message": message, "level": level})
        self.page().runJavaScript(
            f"window.__akazLog && window.__akazLog({payload});"
        )


def _pid_exists(pid):
    try:
        import psutil
        return bool(pid and psutil.pid_exists(pid))
    except Exception:
        return False
