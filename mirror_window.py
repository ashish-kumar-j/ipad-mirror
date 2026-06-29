"""
iPad Mirror – main window.

Layout (controls always visible – no show/hide tricks):
  ┌─ Header ──────────────────────── status ─┐  52 px  #1c1c1e
  │  Mirror display (black, fills everything) │  stretch
  └─ Controls bar ── Start · Fill · Pin · ⛶ ─┘  60 px  #1c1c1e
"""

from PyQt6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QDialog, QDialogButtonBox,
    QLineEdit, QFormLayout, QMessageBox, QTextEdit, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QThread, QObject, QEvent, pyqtSignal
from PyQt6.QtGui import QPixmap, QKeySequence, QShortcut

import sys

from device_stream import DeviceStream
from tunnel_manager import TunnelManager

_POLL_MS = 8

# Status colours
_C_IDLE  = "#636366"
_C_WAIT  = "#ffd60a"
_C_OK    = "#32d74b"
_C_ERR   = "#ff453a"

# Button fills
_B_PRIMARY = "#0a84ff"
_B_STOP    = "#ff453a"
_B_ON      = "#32d74b"
_B_OFF     = "#2c2c2e"


def _dot(colour):
    return (f"background:{colour}; border-radius:5px;"
            " min-width:10px; max-width:10px;"
            " min-height:10px; max-height:10px;")


def _shade(hex_color: str, delta: int) -> str:
    """Lighten (+) or darken (-) a #rrggbb colour by delta (0-255)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = max(0, min(255, r + delta))
    g = max(0, min(255, g + delta))
    b = max(0, min(255, b + delta))
    return f"#{r:02x}{g:02x}{b:02x}"


def _btn_qss(bg, fg="#f2f2f7"):
    hover   = _shade(bg, +18)
    pressed = _shade(bg, -22)
    return (
        f"QPushButton {{ background:{bg}; color:{fg}; border:none;"
        f" border-radius:8px; font-size:13px; font-weight:500;"
        f" padding:0 18px; min-height:34px; }}"
        f"QPushButton:hover {{ background:{hover}; }}"
        f"QPushButton:pressed {{ background:{pressed}; }}"
        f"QPushButton:disabled {{ background:#2c2c2e; color:#48484a; }}"
    )


def _mk(text, slot, min_w=0):
    b = QPushButton(text)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.clicked.connect(slot)
    if min_w:
        b.setMinimumWidth(min_w)
    return b


# ---------------------------------------------------------------------------
# Header widget
# ---------------------------------------------------------------------------

class _Header(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet("background:#1c1c1e; border-bottom:1px solid #2c2c2e;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(10)

        icon = QLabel("📱")
        icon.setStyleSheet("font-size:20px;")
        lay.addWidget(icon)

        title = QLabel("iPad Mirror")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#f2f2f7;")
        lay.addWidget(title)
        lay.addStretch()

        self._dot = QLabel()
        self._dot.setStyleSheet(_dot(_C_IDLE))
        lay.addWidget(self._dot)

        self._msg = QLabel("Waiting for iPad…")
        self._msg.setStyleSheet(f"color:{_C_IDLE}; font-size:12px;")
        lay.addWidget(self._msg)

    def set_status(self, text, colour):
        self._dot.setStyleSheet(_dot(colour))
        self._msg.setStyleSheet(f"color:{colour}; font-size:12px;")
        self._msg.setText(text)


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------

class _VersionChecker(QObject):
    result = pyqtSignal(int)
    error  = pyqtSignal(str)

    def start(self):
        import asyncio, threading
        def _run():
            async def _check():
                from pymobiledevice3.lockdown import create_using_usbmux
                lc = await create_using_usbmux()
                return int(lc.product_version.split(".")[0])
            try:
                self.result.emit(asyncio.run(_check()))
            except Exception as e:
                self.error.emit(str(e))
        threading.Thread(target=_run, daemon=True).start()


class TunnelThread(QThread):
    ready  = pyqtSignal(str, int)
    failed = pyqtSignal(str)

    def __init__(self, password):
        super().__init__()
        self._mgr = TunnelManager(password)

    def run(self):
        self._mgr.start()
        ok = self._mgr.wait_ready(timeout=25)
        if ok and self._mgr.host and self._mgr.port:
            self.ready.emit(self._mgr.host, self._mgr.port)
        else:
            self.failed.emit(self._mgr.error or "Tunnel timed out.")

    def stop_tunnel(self):
        self._mgr.stop()


# ---------------------------------------------------------------------------
# Password dialog
# ---------------------------------------------------------------------------

class PasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Admin Password Required")
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        info = QLabel(
            "<b>A secure tunnel is needed for iOS 17+.</b><br><br>"
            "Enter your Mac login password — it is passed directly to <tt>sudo</tt>"
            " and is never stored."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        form = QFormLayout()
        self._pw = QLineEdit()
        self._pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw.setPlaceholderText("Mac login password")
        self._pw.returnPressed.connect(self._validate)
        form.addRow("Password:", self._pw)
        lay.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Start Tunnel")
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _validate(self):
        if not self._pw.text():
            QMessageBox.warning(self, "Required", "Please enter your Mac password.")
            return
        self.accept()

    @property
    def password(self):
        return self._pw.text()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MirrorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("iPad Mirror")
        self.setMinimumSize(400, 560)
        self.resize(500, 760)

        self._stream          = None
        self._tunnel_thread   = None
        self._rsd_host        = None
        self._rsd_port        = None
        self._ios_version     = None
        self._is_fullscreen   = False
        self._pin_active      = False
        self._fill_active     = False
        self._last_frame_id   = -1     # dedup: skip setPixmap if frame hasn't changed

        self._build_ui()
        # Slow watchdog — only checks for stream errors, not frame delivery
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._watchdog)
        self._start_version_check()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet("background:#000000;")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._header = _Header()
        root.addWidget(self._header)

        # Mirror display
        self._screen = QLabel("Connect iPad via USB, then press  Start Mirroring.")
        self._screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._screen.setWordWrap(True)
        self._screen.setStyleSheet("background:#000000; color:#636366; font-size:14px;")
        root.addWidget(self._screen, stretch=1)

        # Controls bar
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 0, 14, 0)
        bar.setSpacing(10)

        self._start_btn = _mk("▶  Start Mirroring", self._toggle_mirroring, min_w=160)
        self._start_btn.setStyleSheet(_btn_qss(_B_PRIMARY))

        self._fill_btn = _mk("⬜  Fit", self._toggle_fill)
        self._fill_btn.setStyleSheet(_btn_qss(_B_OFF))
        self._fill_btn.setToolTip(
            "Fit: show full iPad screen with black bars (no cropping)\n"
            "Fill: crop edges to cover the whole window"
        )

        self._pin_btn = _mk("Pin: OFF", self._toggle_pin)
        self._pin_btn.setStyleSheet(_btn_qss(_B_OFF))

        self._fs_btn = _mk("⛶  Fullscreen", self._toggle_fullscreen)
        self._fs_btn.setStyleSheet(_btn_qss(_B_OFF))

        for b in (self._start_btn, self._fill_btn, self._pin_btn, self._fs_btn):
            bar.addWidget(b)

        ctrl = QWidget()
        ctrl.setStyleSheet("background:#1c1c1e; border-top:1px solid #2c2c2e;")
        ctrl.setLayout(bar)
        ctrl.setFixedHeight(60)
        root.addWidget(ctrl)

        # Keyboard shortcuts
        QShortcut(QKeySequence("F"),               self, self._toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+F"),          self, self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._exit_fullscreen)

    # ------------------------------------------------------------------
    # Version detection
    # ------------------------------------------------------------------

    def _start_version_check(self):
        self._vc = _VersionChecker()
        self._vc.result.connect(self._on_version)
        self._vc.error.connect(self._on_version_error)
        self._vc.start()

    def _on_version(self, ver):
        self._ios_version = ver
        if ver >= 17:
            self._header.set_status(
                f"iPad detected  •  iOS {ver}  •  password needed for tunnel", _C_WAIT)
        else:
            self._header.set_status(f"iPad detected  •  iOS {ver}  •  ready", _C_OK)

    def _on_version_error(self, _):
        self._ios_version = 17
        self._header.set_status("iPad detected  •  click Start Mirroring", _C_WAIT)

    # ------------------------------------------------------------------
    # Mirroring
    # ------------------------------------------------------------------

    def _toggle_mirroring(self):
        if self._stream and self._stream.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        # macOS 15 (Sequoia) changed the CMIO DAL plugin behaviour — iOS devices
        # no longer surface as AVCaptureDevice screen-mirror sources without
        # QuickTime actively brokering the session.  Skip AVF and go straight to
        # the tunnel path so we don't accidentally grab the iPhone Continuity
        # Camera instead of the iPad screen.
        if not self._rsd_host:
            if sys.platform == "win32":
                self._start_tunnel_windows()
            else:
                self._prompt_tunnel()
            return
        self._begin_capture(try_avf=False)

    def _start_tunnel_windows(self):
        """On Windows no password is needed — the app must run as Administrator."""
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            QMessageBox.warning(
                self, "Administrator Required",
                "Starting the tunnel requires Administrator privileges.\n\n"
                "Please right-click the app and choose 'Run as administrator', then try again."
            )
            return
        self._start_btn.setEnabled(False)
        self._header.set_status("Starting tunnel…", _C_WAIT)
        self._tunnel_thread = TunnelThread("")   # empty password — not used on Windows
        self._tunnel_thread.ready.connect(self._on_tunnel_ready)
        self._tunnel_thread.failed.connect(self._on_tunnel_failed)
        self._tunnel_thread.start()

    def _begin_capture(self, try_avf: bool = False):
        self._stream = DeviceStream()
        self._stream.set_display_size(self._screen.size())
        self._stream.set_fill_mode(self._fill_active)
        self._stream.frame_ready.connect(self._on_frame)
        self._stream.start(rsd_host=self._rsd_host, rsd_port=self._rsd_port)
        self._timer.start(500)   # watchdog: check for errors every 500 ms
        self._start_btn.setText("⏹  Stop Mirroring")
        self._start_btn.setStyleSheet(_btn_qss(_B_STOP))
        self._header.set_status("Connecting…", _C_WAIT)

    def _stop(self):
        self._timer.stop()
        self._last_frame_id = -1
        if self._stream:
            self._stream.stop()
            self._stream = None
        self._screen.clear()
        self._screen.setText("Mirroring stopped.  Press Start Mirroring to reconnect.")
        self._start_btn.setText("▶  Start Mirroring")
        self._start_btn.setStyleSheet(_btn_qss(_B_PRIMARY))
        self._header.set_status("Stopped", _C_IDLE)

    # ------------------------------------------------------------------
    # Toggles
    # ------------------------------------------------------------------

    def _toggle_fill(self):
        self._fill_active = not self._fill_active
        if self._fill_active:
            self._fill_btn.setText("⬛  Fill")
            self._fill_btn.setStyleSheet(_btn_qss(_B_PRIMARY))
        else:
            self._fill_btn.setText("⬜  Fit")
            self._fill_btn.setStyleSheet(_btn_qss(_B_OFF))
        if self._stream:
            self._stream.set_fill_mode(self._fill_active)

    def _toggle_pin(self):
        self._pin_active = not self._pin_active
        if self._pin_active:
            self._pin_btn.setText("Pin: ON")
            self._pin_btn.setStyleSheet(_btn_qss(_B_ON, "#000000"))
        else:
            self._pin_btn.setText("Pin: OFF")
            self._pin_btn.setStyleSheet(_btn_qss(_B_OFF))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._pin_active)
        self.showFullScreen() if self._is_fullscreen else self.show()

    # ------------------------------------------------------------------
    # Fullscreen  (controls ALWAYS visible)
    # ------------------------------------------------------------------

    def _toggle_fullscreen(self):
        self._exit_fullscreen() if self._is_fullscreen else self._enter_fullscreen()

    def _enter_fullscreen(self):
        self._is_fullscreen = True
        self._fs_btn.setText("⛶  Exit Full")
        self.showFullScreen()
        QTimer.singleShot(0, self._sync_size)

    def _exit_fullscreen(self):
        actually_fs = bool(self.windowState() & Qt.WindowState.WindowFullScreen)
        if not self._is_fullscreen and not actually_fs:
            return
        self._is_fullscreen = False
        self._fs_btn.setText("⛶  Fullscreen")
        self.showNormal()
        QTimer.singleShot(0, self._sync_size)

    def _sync_size(self):
        if self._stream:
            self._stream.set_display_size(self._screen.size())

    def mouseDoubleClickEvent(self, event):
        self._toggle_fullscreen()

    # ------------------------------------------------------------------
    # Tunnel
    # ------------------------------------------------------------------

    def _prompt_tunnel(self):
        dlg = PasswordDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_btn.setEnabled(False)
        self._header.set_status("Starting tunnel  (≈10 s)…", _C_WAIT)
        self._tunnel_thread = TunnelThread(dlg.password)
        self._tunnel_thread.ready.connect(self._on_tunnel_ready)
        self._tunnel_thread.failed.connect(self._on_tunnel_failed)
        self._tunnel_thread.start()

    def _on_tunnel_ready(self, host, port):
        self._rsd_host = host
        self._rsd_port = port
        self._start_btn.setEnabled(True)
        self._header.set_status(f"Tunnel ready  •  {host}:{port}", _C_OK)
        self._begin_capture()

    def _on_tunnel_failed(self, error):
        self._start_btn.setEnabled(True)
        raw = self._tunnel_thread._mgr.raw_error if self._tunnel_thread else None
        self._show_tunnel_error(error, raw)
        self._header.set_status("Tunnel failed  •  try again", _C_ERR)

    def _show_tunnel_error(self, summary, full):
        dlg = QDialog(self)
        dlg.setWindowTitle("Tunnel Failed")
        dlg.setMinimumWidth(520)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lay.addWidget(QLabel(
            "<b>Could not start the secure tunnel.</b><br><br>"
            "Check:<br>"
            "• iPad connected via USB and <i>Trust</i> accepted<br>"
            "• Developer Mode ON  (Settings → Privacy & Security → Developer Mode)<br>"
            "• Mac password correct<br>"
            "• No other tunnel running  (<tt>sudo pkill -f start-tunnel</tt>)"
        ))
        err_box = QTextEdit(); err_box.setReadOnly(True)
        err_box.setFixedHeight(72); err_box.setPlainText(summary)
        lay.addWidget(err_box)
        if full:
            show_btn = QPushButton("Show full error")
            full_area = QTextEdit(); full_area.setReadOnly(True)
            full_area.setFixedHeight(160); full_area.setPlainText(full); full_area.hide()
            def _tog():
                v = full_area.isVisible()
                full_area.setVisible(not v)
                show_btn.setText("Hide" if not v else "Show full error")
            show_btn.clicked.connect(_tog)
            lay.addWidget(show_btn); lay.addWidget(full_area)
            cp = QPushButton("Copy to clipboard")
            cp.clicked.connect(lambda: QApplication.clipboard().setText(full))
            lay.addWidget(cp)
        ok = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok.accepted.connect(dlg.accept)
        lay.addWidget(ok)
        dlg.exec()

    # ------------------------------------------------------------------
    # Frame update
    # ------------------------------------------------------------------

    def _watchdog(self):
        """500 ms timer — only used to catch stream errors after connect."""
        if self._stream and self._stream.error:
            self._stop()
            self._header.set_status(f"Error: {self._stream.error}", _C_ERR)

    def _on_frame(self, raw: QImage, frame_id: int):
        """Called instantly on the Qt main thread the moment a frame is decoded."""
        if frame_id == self._last_frame_id or raw.isNull():
            return
        self._last_frame_id = frame_id

        size = self._screen.size()
        if self._fill_active:
            scaled = raw.scaled(size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.FastTransformation)
            if scaled.width() > size.width() or scaled.height() > size.height():
                x = (scaled.width()  - size.width())  // 2
                y = (scaled.height() - size.height()) // 2
                scaled = scaled.copy(x, y, size.width(), size.height())
        else:
            scaled = raw.scaled(size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation)
        self._screen.setPixmap(
            QPixmap.fromImage(scaled, Qt.ImageConversionFlag.ColorOnly)
        )
        if self._stream:
            mode = self._stream.streaming_mode.upper()
            self._header.set_status(
                f"Mirroring  •  {self._stream.fps:.1f} fps  •  {mode}", _C_OK)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._exit_fullscreen(); event.accept(); return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self._is_fullscreen and not (
                    self.windowState() & Qt.WindowState.WindowFullScreen):
                self._is_fullscreen = False
                self._fs_btn.setText("⛶  Fullscreen")
                QTimer.singleShot(0, self._sync_size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._stream:
            self._stream.set_display_size(self._screen.size())

    def closeEvent(self, event):
        if self._stream and self._stream.running:
            self._stream.stop()
        if self._tunnel_thread:
            self._tunnel_thread.stop_tunnel()
        event.accept()
