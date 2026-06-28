import asyncio
import concurrent.futures
import threading
import time
from PyQt6.QtGui import QImage
from PyQt6.QtCore import QByteArray, QSize, Qt


class DeviceStream:
    def __init__(self):
        self.running = False
        self._frame: QImage | None = None
        self._raw: QImage | None = None      # last decoded, unscaled image
        self._lock = threading.Lock()
        self._thread = None
        self._fps = 0.0
        self._error = None
        self._display_size: QSize | None = None
        self._fill_mode = False
        # Incremented on every rendering-parameter change (mode, size).
        # _frame_loop uses it to discard decodes that started before a mode change,
        # preventing stale frames from overwriting the one _rescale_current just set.
        self._mode_stamp = 0

    def set_display_size(self, size: QSize):
        self._display_size = size
        self._mode_stamp += 1
        self._rescale_current()

    def set_fill_mode(self, fill: bool):
        self._fill_mode = fill
        self._mode_stamp += 1
        self._rescale_current()

    def _rescale_current(self):
        with self._lock:
            raw = self._raw
        if raw is not None and not raw.isNull():
            scaled = self._scale(raw)
            with self._lock:
                self._frame = scaled

    def start(self, rsd_host=None, rsd_port=None):
        self._error = None
        self._fps = 0.0
        self._rsd_host = rsd_host
        self._rsd_port = rsd_port
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def get_latest_frame(self) -> QImage | None:
        with self._lock:
            return self._frame

    @property
    def fps(self):
        return self._fps

    @property
    def error(self):
        return self._error

    # ------------------------------------------------------------------
    # Scale helper
    # ------------------------------------------------------------------

    def _scale(self, img: QImage) -> QImage:
        target = self._display_size
        if not target or img.isNull():
            return img
        ratio_mode = (
            Qt.AspectRatioMode.KeepAspectRatioByExpanding
            if self._fill_mode
            else Qt.AspectRatioMode.KeepAspectRatio
        )
        out = img.scaled(target, ratio_mode, Qt.TransformationMode.SmoothTransformation)
        if self._fill_mode and (out.width() > target.width() or out.height() > target.height()):
            x = (out.width()  - target.width())  // 2
            y = (out.height() - target.height()) // 2
            out = out.copy(x, y, target.width(), target.height())
        return out

    # ------------------------------------------------------------------
    # Decode + scale (runs in thread-pool)
    # ------------------------------------------------------------------

    def _decode_and_scale(self, png_bytes: bytes, stamp: int) -> tuple:
        raw = QImage()
        raw.loadFromData(QByteArray(png_bytes), "PNG")
        with self._lock:
            self._raw = raw
        return self._scale(raw), stamp

    # ------------------------------------------------------------------
    # Async capture pipeline
    # ------------------------------------------------------------------

    def _run(self):
        loop = asyncio.new_event_loop()
        loop.set_exception_handler(lambda l, ctx: None)
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._capture_loop())
        finally:
            loop.close()

    async def _capture_loop(self):
        try:
            await self._capture_via_rsd(self._rsd_host, self._rsd_port)
        except Exception as e:
            self._error = str(e)
            self.running = False

    async def _capture_via_rsd(self, host, port):
        from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
        async with RemoteServiceDiscoveryService((host, port)) as rsd:
            await self._capture_dvt(rsd)

    async def _capture_dvt(self, rsd):
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot
        async with DvtProvider(rsd) as dvt:
            async with Screenshot(dvt) as screen:
                await self._frame_loop(screen.get_screenshot)

    async def _frame_loop(self, take_fn):
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        frame_count = 0
        fps_timer = time.monotonic()

        try:
            png_bytes = await take_fn()
            stamp = self._mode_stamp
            decode_future = loop.run_in_executor(executor, self._decode_and_scale, png_bytes, stamp)

            while self.running:
                capture_task = asyncio.create_task(take_fn())

                img, used_stamp = await decode_future
                with self._lock:
                    # Only commit if the rendering parameters haven't changed since
                    # this decode was submitted. If they have, _rescale_current()
                    # already put the correct frame into _frame — don't overwrite it.
                    if used_stamp == self._mode_stamp:
                        self._frame = img

                frame_count += 1
                elapsed = time.monotonic() - fps_timer
                if elapsed >= 1.0:
                    self._fps = frame_count / elapsed
                    frame_count = 0
                    fps_timer = time.monotonic()

                png_bytes = await capture_task
                stamp = self._mode_stamp   # snapshot BEFORE submitting decode
                decode_future = loop.run_in_executor(executor, self._decode_and_scale, png_bytes, stamp)

        finally:
            executor.shutdown(wait=False)
