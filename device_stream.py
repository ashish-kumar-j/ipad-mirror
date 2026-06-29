"""
iPad screen capture — two paths tried in order:

  1. HEVC via com.apple.coredevice.displayservice   (iOS 17+, ~30 ms lag, ~60 fps)
     RTP/HEVC over UDP, decoded by VideoToolbox (macOS) or PyAV/FFmpeg (Windows).

  2. DVT PNG screenshots fallback                   (~150 ms lag, ~10-15 fps)
     com.apple.instruments.server.services.screenshot, always-PNG, serial capture.
"""

import asyncio
import contextlib
import random
import struct
import threading
import time

from PyQt6.QtGui import QImage


# HEVC NAL unit types (ITU-T H.265 Table 7-1)
_NAL_VPS = 32
_NAL_SPS = 33
_NAL_PPS = 34
_KEY_NAL_TYPES = {19, 20, 21}   # IDR_W_RADL, IDR_N_LP, CRA_NUT


class DeviceStream:
    def __init__(self):
        self.running = False
        self._raw: QImage | None = None        # latest decoded frame (unscaled)
        self._raw_id: int = 0                  # incremented on every new raw frame
        self._lock = threading.Lock()
        self._thread = None
        self._fps = 0.0
        self._frame_count = 0
        self._fps_timer = 0.0
        self._error = None
        self._streaming_mode = "connecting"    # "hevc" | "dvt" | "connecting"
        # HEVC decoder (HevcToBgraTranscoder, created lazily)
        self._transcoder = None
        # RTCP bookkeeping
        self._local_ssrc = random.randint(1, 0xFFFF_FFFF)
        self._remote_ssrc = 0
        self._rtp_highest_seq = 0
        self._rtp_packets_received = 0

    # ------------------------------------------------------------------
    # Public API (called from the Qt main thread)
    # ------------------------------------------------------------------

    def set_display_size(self, size: QSize):
        pass   # scaling now happens in the Qt tick — nothing to do here

    def set_fill_mode(self, fill: bool):
        pass   # fill mode is read by mirror_window directly

    def start(self, rsd_host=None, rsd_port=None):
        self._error = None
        self._fps = 0.0
        self._frame_count = 0
        self._fps_timer = time.monotonic()
        self._rsd_host = rsd_host
        self._rsd_port = rsd_port
        self._streaming_mode = "connecting"
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def get_latest_frame(self) -> tuple[QImage | None, int]:
        """Return (raw_QImage, frame_id). frame_id increments on every new frame."""
        with self._lock:
            return self._raw, self._raw_id

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def streaming_mode(self) -> str:
        return self._streaming_mode

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tick_fps(self):
        self._frame_count += 1
        t = time.monotonic()
        elapsed = t - self._fps_timer
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_timer = t

    # ------------------------------------------------------------------
    # Background thread entry point
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
            try:
                await self._capture_hevc_stream(rsd)
            except Exception:
                if not self.running:
                    return
                self._streaming_mode = "dvt"
                await self._capture_dvt(rsd)

    # ==================================================================
    # Path 1 — HEVC streaming (low-latency)
    # ==================================================================

    async def _capture_hevc_stream(self, rsd):
        from pymobiledevice3.remote.core_device.display_service import DisplayService
        from pymobiledevice3.remote.core_device.screen_stream import (
            depacketize_hevc,
            open_media_receiver,
        )
        import uuid as _uuid

        sender_ip = rsd.service.address[0]

        async with DisplayService(rsd) as service:
            transport, receiver_ip = open_media_receiver(
                service, (4 * 1024 * 1024, 1 * 1024 * 1024)
            )
            client_session_id = None
            rtcp_task = None
            try:
                answer = await service.start_video_stream(
                    receiver_ip=receiver_ip,
                    receiver_port=transport.port,
                    sender_ip=sender_ip,
                    ltrp_enabled=False,   # off = no mid-stream tearing on UDP loss
                )

                conn = answer["connection"]
                raw_sid = conn["options"]["avcMediaStreamOptionClientSessionID"]["uuid"]
                client_session_id = (
                    raw_sid if isinstance(raw_sid, _uuid.UUID) else _uuid.UUID(raw_sid)
                )
                sender_port = (conn.get("sender") or {}).get("port", 0)

                self._streaming_mode = "hevc"
                self._fps_timer = time.monotonic()
                self._frame_count = 0

                rtcp_task = asyncio.create_task(
                    self._rtcp_loop(transport, sender_ip, sender_port)
                )

                fu_buffer = bytearray()
                current_au: list[bytes] = []
                au_is_key = False
                nals: list[bytes] = []
                vps = sps = pps = None
                first_frame_seen = False

                while self.running:
                    try:
                        data = await asyncio.wait_for(transport.recv(65535), timeout=8.0)
                    except asyncio.TimeoutError:
                        if not first_frame_seen:
                            raise RuntimeError(
                                "No HEVC frames in 8 s — falling back to DVT screenshots"
                            )
                        continue

                    if len(data) < 12:
                        continue
                    # Drop RTCP packets (payload types 64-95)
                    if 64 <= (data[1] & 0x7F) <= 95:
                        continue

                    # RTP header: V(2) P(1) X(1) CC(4) | M(1) PT(7) | SEQ(16) | TS(32) | SSRC(32)
                    marker = (data[1] >> 7) & 1
                    cc = data[0] & 0x0F
                    hdr = 12 + cc * 4
                    if data[0] & 0x10:   # extension present
                        if hdr + 4 <= len(data):
                            hdr += 4 + int.from_bytes(data[hdr + 2: hdr + 4], "big") * 4

                    # Track sequence number and SSRC for RTCP RR
                    seq = int.from_bytes(data[2:4], "big")
                    ssrc = int.from_bytes(data[8:12], "big")
                    if not self._remote_ssrc:
                        self._remote_ssrc = ssrc
                    self._rtp_packets_received += 1
                    cyc = (self._rtp_highest_seq >> 16) & 0xFFFF
                    lo16 = self._rtp_highest_seq & 0xFFFF
                    if seq < lo16 and (lo16 - seq) > 0x8000:
                        cyc = (cyc + 1) & 0xFFFF
                    ext = (cyc << 16) | seq
                    if not self._rtp_highest_seq or (
                        (ext - self._rtp_highest_seq) & 0xFFFF_FFFF
                    ) < 0x8000_0000:
                        self._rtp_highest_seq = ext

                    # RFC 7798 RTP/HEVC depacketisation
                    payload = data[hdr:]
                    nals.clear()
                    depacketize_hevc(payload, fu_buffer, nals)

                    for nal in nals:
                        if not nal:
                            continue
                        nt = (nal[0] >> 1) & 0x3F
                        if nt == _NAL_VPS:
                            vps = bytes(nal)
                        elif nt == _NAL_SPS:
                            sps = bytes(nal)
                        elif nt == _NAL_PPS:
                            pps = bytes(nal)
                        if nt in _KEY_NAL_TYPES:
                            au_is_key = True
                        current_au.append(nal)

                    if marker and current_au:
                        # End of access unit — create decoder on first IDR
                        if self._transcoder is None and vps and sps and pps:
                            self._transcoder = self._make_transcoder(vps, sps, pps)
                        if self._transcoder is not None:
                            first_frame_seen = True
                            annexb = b"".join(b"\x00\x00\x00\x01" + n for n in current_au)
                            self._transcoder.feed(annexb)
                        current_au.clear()
                        au_is_key = False

            finally:
                transport.close()
                if rtcp_task is not None:
                    rtcp_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await rtcp_task
                tr, self._transcoder = self._transcoder, None
                if tr is not None:
                    with contextlib.suppress(Exception):
                        tr.close()
                if client_session_id is not None:
                    with contextlib.suppress(Exception):
                        await service.stop_media_stream(client_session_id)

    def _make_transcoder(self, vps: bytes, sps: bytes, pps: bytes):
        """Create platform-appropriate HEVC → BGRA transcoder.

        macOS: VideoToolbox (hardware, via vt_jpeg).
        Windows/other: PyAV / libavcodec (software, ~0.9 ms/frame on modern CPUs).
        """
        import sys
        if sys.platform == "darwin":
            try:
                from pymobiledevice3.remote.core_device.vt_jpeg import HevcToBgraTranscoder
                return HevcToBgraTranscoder(
                    vps=vps, sps=sps, pps=pps, on_frame=self._on_bgra_frame
                )
            except Exception:
                pass   # fall through to PyAV
        from pymobiledevice3.remote.core_device.hevc_av import HevcToBgraTranscoder
        return HevcToBgraTranscoder(
            vps=vps, sps=sps, pps=pps, on_frame=self._on_bgra_frame
        )

    def _on_bgra_frame(self, bgra: bytes) -> None:
        """Fires on the HevcToBgraTranscoder worker thread for each decoded frame."""
        tr = self._transcoder
        if tr is None:
            return
        # Wrap buffer then .copy() so the BGRA bytes can be freed immediately.
        raw = QImage(
            bgra, tr.width, tr.height, tr.width * 4, QImage.Format.Format_BGRA8888
        ).copy()
        with self._lock:
            self._raw = raw
            self._raw_id += 1
        self._tick_fps()

    async def _rtcp_loop(self, transport, sender_ip: str, sender_port: int) -> None:
        """Send RTCP Receiver Reports every second — keeps the device encoder alive."""
        if not sender_port:
            return
        while self.running:
            await asyncio.sleep(1.0)
            if not self._remote_ssrc:
                continue
            with contextlib.suppress(Exception):
                await transport.sendto(self._build_rtcp_rr(), sender_ip, sender_port)

    def _build_rtcp_rr(self) -> bytes:
        """Minimal RFC 3550 §6.4.2 Receiver Report (32 bytes, one report block)."""
        return struct.pack(
            "!BBHIIIIIII",
            0x81, 201, 7,               # V=2 P=0 RC=1 | PT=RR | length=7 (8 words)
            self._local_ssrc,           # SSRC of this sender
            self._remote_ssrc,          # report block: source SSRC
            0,                          # fraction lost | cumulative lost
            self._rtp_highest_seq,      # extended highest sequence number received
            0, 0, 0,                    # jitter | LSR | DLSR
        )

    # ==================================================================
    # Path 2 — DVT PNG screenshot fallback
    # ==================================================================

    async def _capture_dvt(self, rsd):
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot
        async with DvtProvider(rsd) as dvt:
            async with Screenshot(dvt) as screen:
                await self._frame_loop_dvt(screen.get_screenshot)

    async def _frame_loop_dvt(self, take_fn):
        import concurrent.futures
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._fps_timer = time.monotonic()
        self._frame_count = 0

        try:
            png = await take_fn()
            fut = loop.run_in_executor(executor, self._decode_png, png)

            while self.running:
                cap = asyncio.create_task(take_fn())
                raw = await fut
                with self._lock:
                    self._raw = raw
                    self._raw_id += 1
                self._tick_fps()
                png = await cap
                fut = loop.run_in_executor(executor, self._decode_png, png)
        finally:
            executor.shutdown(wait=False)

    def _decode_png(self, png_bytes: bytes) -> QImage:
        img = QImage()
        img.loadFromData(png_bytes, "PNG")
        return img
