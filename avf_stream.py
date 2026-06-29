"""
AVFoundation screen capture for connected iOS/iPadOS devices (macOS only).

Uses the same CoreMediaIO + AVCaptureSession pipeline as QuickTime Player,
giving matching latency (~50-100 ms) with no tunnel or sudo required.

Requires pyobjc:  pip install pyobjc-framework-AVFoundation
                              pyobjc-framework-CoreMedia
                              pyobjc-framework-CoreVideo
"""
import ctypes
import ctypes.util
import sys
from typing import Callable


# ---------------------------------------------------------------------------
# CoreMediaIO — tell the DAL to surface iOS screen-mirror devices
# ---------------------------------------------------------------------------

def _cmio_allow_screen_capture() -> None:
    """Set kCMIOHardwarePropertyAllowScreenCaptureDevices = 1."""
    lib = ctypes.util.find_library("CoreMediaIO")
    if not lib:
        return
    try:
        cmio = ctypes.CDLL(lib)

        class _Addr(ctypes.Structure):
            _fields_ = [("sel",   ctypes.c_uint32),
                        ("scope", ctypes.c_uint32),
                        ("elem",  ctypes.c_uint32)]

        pa  = _Addr(0x73637265, 0x676C6F62, 0)  # 'scre' / 'glob' / 0
        val = ctypes.c_uint32(1)
        cmio.CMIOObjectSetPropertyData(
            ctypes.c_uint32(1),                       # kCMIOObjectSystemObject
            ctypes.byref(pa),
            ctypes.c_uint32(0), None,
            ctypes.c_uint32(ctypes.sizeof(val)),
            ctypes.byref(val),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Dispatch queue helper
# ---------------------------------------------------------------------------

def _background_queue():
    """
    Return a dispatch_queue_t for background frame processing.
    Uses dispatch_get_global_queue via ctypes, wrapped as an ObjC object
    via objc.objc_object(c_void_p=...) — tested to work with pyobjc 12+.
    Falls back to None (main thread) if anything fails.
    """
    try:
        import objc
        lib = ctypes.CDLL("/usr/lib/system/libdispatch.dylib")
        lib.dispatch_get_global_queue.restype  = ctypes.c_void_p
        lib.dispatch_get_global_queue.argtypes = [ctypes.c_long, ctypes.c_ulong]
        ptr = lib.dispatch_get_global_queue(2, 0)   # DISPATCH_QUEUE_PRIORITY_HIGH = 2
        if ptr:
            return objc.objc_object(c_void_p=ptr)
    except Exception:
        pass

    return None  # fallback: AVFoundation dispatches to the main thread


# ---------------------------------------------------------------------------
# AVFStream
# ---------------------------------------------------------------------------

class AVFStream:
    """
    Streams frames from a connected iOS device via AVFoundation.
    on_frame(bgra_bytes, width, height) is called on a background thread.
    """

    def __init__(self, on_frame: Callable[[bytes, int, int], None]):
        self._on_frame  = on_frame
        self._session   = None
        self._delegate  = None  # keep reference so ARC doesn't free it

    # ------------------------------------------------------------------

    def start(self) -> str:
        """
        Find the iPad, set up AVCaptureSession, start streaming.
        Returns the device's display name on success.
        Raises RuntimeError with a human-readable message on failure.
        """
        if sys.platform != "darwin":
            raise RuntimeError("AVFoundation capture is macOS-only")

        _cmio_allow_screen_capture()

        import objc
        import AVFoundation as AVF
        import CoreMedia   as CM
        import Quartz      as CV    # CoreVideo functions live in pyobjc's Quartz package

        # ── 1. find the iOS device ────────────────────────────────────
        all_devs = AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo)
        device   = next(
            (d for d in (all_devs or [])
             if any(k in d.localizedName() for k in ("iPad", "iPhone"))),
            None,
        )
        if device is None:
            raise RuntimeError(
                "No iPad/iPhone found as AVCaptureDevice.\n"
                "Make sure the iPad is connected via USB, 'Trust' was accepted,\n"
                "and that no other app (QuickTime, Xcode) has it locked."
            )

        device_name = device.localizedName()

        # ── 2. session ────────────────────────────────────────────────
        session = AVF.AVCaptureSession.alloc().init()
        session.beginConfiguration()
        session.setSessionPreset_(AVF.AVCaptureSessionPresetHigh)

        inp, err = AVF.AVCaptureDeviceInput.deviceInputWithDevice_error_(device, None)
        if not inp:
            raise RuntimeError(f"Cannot open AVCaptureDeviceInput: {err}")
        if not session.canAddInput_(inp):
            raise RuntimeError("Session cannot accept this input device")
        session.addInput_(inp)

        # ── 3. output ─────────────────────────────────────────────────
        output = AVF.AVCaptureVideoDataOutput.alloc().init()
        output.setAlwaysDiscardsLateVideoFrames_(True)
        # Request BGRA — QImage.Format_BGRA8888 can consume it directly
        try:
            output.setVideoSettings_({
                "PixelFormatType": 1111970369,   # kCVPixelFormatType_32BGRA
            })
        except Exception:
            pass

        # ── 4. delegate ───────────────────────────────────────────────
        callback = self._on_frame   # strong ref inside the closure

        class _Delegate(objc.lookUpClass("NSObject")):
            def captureOutput_didOutputSampleBuffer_fromConnection_(
                    self, _out, sbuf, _conn):
                pb = CM.CMSampleBufferGetImageBuffer(sbuf)
                if pb is None:
                    return
                lock_flag = getattr(CV, "kCVPixelBufferLock_ReadOnly", 1)
                CV.CVPixelBufferLockBaseAddress(pb, lock_flag)
                try:
                    w   = int(CV.CVPixelBufferGetWidth(pb))
                    h   = int(CV.CVPixelBufferGetHeight(pb))
                    bpr = int(CV.CVPixelBufferGetBytesPerRow(pb))
                    ptr = CV.CVPixelBufferGetBaseAddress(pb)
                    raw = (ctypes.c_uint8 * (h * bpr)).from_address(int(ptr))
                    callback(bytes(raw), w, h, bpr)
                except Exception:
                    pass
                finally:
                    CV.CVPixelBufferUnlockBaseAddress(pb, lock_flag)

        self._delegate = _Delegate.alloc().init()

        q = _background_queue()
        if not session.canAddOutput_(output):
            raise RuntimeError("Session cannot accept video output")
        output.setSampleBufferDelegate_queue_(self._delegate, q)
        session.addOutput_(output)

        session.commitConfiguration()
        session.startRunning()

        if not session.isRunning():
            raise RuntimeError("AVCaptureSession failed to start")

        self._session = session
        return device_name

    # ------------------------------------------------------------------

    def stop(self) -> None:
        if self._session is not None:
            self._session.stopRunning()
            self._session  = None
            self._delegate = None
