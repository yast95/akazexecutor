from __future__ import annotations

import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow

from webview import APP_NAME, AppController, WebView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.setMinimumSize(1050, 680)
        self.setStyleSheet("QMainWindow { background: #0c0e11; }")

        self.controller = AppController(self)
        self.webview = WebView(self.controller, self)
        self.setCentralWidget(self.webview)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_runtime)
        self._timer.start(1200)

        self.controller.start()

    def _refresh_runtime(self):
        if self.controller.is_busy():
            return

        self.controller._publish_status()
        info = self.controller.runtime_info()
        self.webview.page().runJavaScript(
            f"window.__akazRuntime && window.__akazRuntime({info});"
        )

    def closeEvent(self, event):
        self.controller.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0c0e11"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e7ebef"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0f1115"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e7ebef"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#171b20"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e7ebef"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
