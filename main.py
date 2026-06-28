import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from mirror_window import MirrorWindow

# ---------------------------------------------------------------------------
# Global dark stylesheet (applied to the whole application)
# ---------------------------------------------------------------------------
_STYLESHEET = """
* {
    font-family: "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif;
}
QWidget {
    background-color: #1c1c1e;
    color: #f2f2f7;
    font-size: 13px;
}
QMainWindow  { background-color: #000000; }
QDialog      { background-color: #1c1c1e; }
QLabel       { background-color: transparent; color: #f2f2f7; }
QLineEdit {
    background-color: #2c2c2e;
    color: #f2f2f7;
    border: 1px solid #3a3a3c;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #0a84ff;
}
QLineEdit:focus { border-color: #0a84ff; }
QPushButton {
    background-color: #2c2c2e;
    color: #f2f2f7;
    border: none;
    border-radius: 8px;
    padding: 6px 18px;
    min-height: 28px;
}
QPushButton:hover    { background-color: #3a3a3c; }
QPushButton:pressed  { background-color: #48484a; }
QPushButton:disabled { color: #48484a; background-color: #1c1c1e; }
QTextEdit {
    background-color: #2c2c2e;
    color: #f2f2f7;
    border: 1px solid #3a3a3c;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: #0a84ff;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #3a3a3c;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
QStatusBar {
    background-color: #1c1c1e;
    color: #636366;
    font-size: 11px;
    border-top: 1px solid #2c2c2e;
}
QMessageBox { background-color: #1c1c1e; }
QMessageBox QPushButton { min-width: 80px; }
"""


def _assets_dir() -> str:
    # PyInstaller extracts data into sys._MEIPASS; fall back to source tree
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("iPad Mirror")
    app.setApplicationDisplayName("iPad Mirror")
    app.setStyleSheet(_STYLESHEET)

    assets = _assets_dir()
    for name in ("icon.icns", "icon.ico", "icon_1024.png"):
        p = os.path.join(assets, name)
        if os.path.exists(p):
            app.setWindowIcon(QIcon(p))
            break

    window = MirrorWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
