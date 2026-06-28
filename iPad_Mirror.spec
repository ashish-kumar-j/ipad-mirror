# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for iPad Mirror.
Build with:
  macOS  →  bash build_mac.sh
  Windows →  build_windows.bat
"""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# Collect everything pymobiledevice3 needs (it uses dynamic imports heavily)
pm3_data, pm3_bins, pm3_hidden = collect_all("pymobiledevice3")

# pytun_pmd3 ships wintun.dll (Windows TUN driver) as package data —
# collect_all("pymobiledevice3") misses it because it's a separate package
pytun_data, pytun_bins, pytun_hidden = collect_all("pytun_pmd3")

# Include dist-info for packages that call importlib.metadata.version() on
# themselves at import time (fails in bundles without this)
meta_data = copy_metadata("pymobiledevice3")

# Additional hidden imports that PyInstaller may miss
extra_hidden = [
    "pymobiledevice3.remote.tunnel_service",
    "pymobiledevice3.remote.module_imports",
    "pymobiledevice3.remote.remote_service_discovery",
    "pymobiledevice3.remote.common",
    "pymobiledevice3.services.dvt.instruments.dvt_provider",
    "pymobiledevice3.services.dvt.instruments.screenshot",
    "cryptography",
    "construct",
    "ifaddr",
    "click",
    "typer",
]

# ── Main app ────────────────────────────────────────────────────────────────

main_a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=pm3_bins + pytun_bins,
    datas=[("assets", "assets")] + pm3_data + pytun_data + meta_data,
    hiddenimports=pm3_hidden + pytun_hidden + extra_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy"],
    noarchive=False,
)

main_pyz = PYZ(main_a.pure)

# ── Tunnel helper (separate CLI binary, called with sudo) ────────────────────

helper_a = Analysis(
    ["tunnel_helper.py"],
    pathex=["."],
    binaries=pm3_bins + pytun_bins,
    datas=pm3_data + pytun_data + meta_data,
    hiddenimports=pm3_hidden + pytun_hidden + extra_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt6", "matplotlib", "numpy"],
    noarchive=False,
)

helper_pyz = PYZ(helper_a.pure)

# ── macOS .app bundle ────────────────────────────────────────────────────────

if sys.platform == "darwin":
    helper_exe = EXE(
        helper_pyz,
        helper_a.scripts,
        [],
        exclude_binaries=True,
        name="tunnel_helper",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
    )

    helper_coll = COLLECT(
        helper_exe,
        helper_a.binaries,
        helper_a.datas,
        strip=False,
        upx=False,
        name="tunnel_helper_collect",
    )

    main_exe = EXE(
        main_pyz,
        main_a.scripts,
        [],
        exclude_binaries=True,
        name="iPad Mirror",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon="assets/icon.icns",
    )

    coll = COLLECT(
        main_exe,
        main_a.binaries,
        main_a.datas,
        helper_exe,
        helper_a.binaries,
        helper_a.datas,
        strip=False,
        upx=False,
        name="iPad Mirror",
    )

    app = BUNDLE(
        coll,
        name="iPad Mirror.app",
        icon="assets/icon.icns",
        bundle_identifier="com.ipadmirror.app",
        info_plist={
            "CFBundleName": "iPad Mirror",
            "CFBundleDisplayName": "iPad Mirror",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "12.0",
            "LSBackgroundOnly": False,
        },
    )

# ── Windows .exe ──────────────────────────────────────────────────────────────

else:
    # tunnel_helper as a standalone onefile exe — placed next to iPad Mirror.exe
    helper_exe = EXE(
        helper_pyz,
        helper_a.scripts,
        helper_a.binaries,
        helper_a.datas,
        [],
        name="tunnel_helper",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True,
        onefile=True,
    )

    main_exe = EXE(
        main_pyz,
        main_a.scripts,
        main_a.binaries,
        main_a.datas,
        [],
        name="iPad Mirror",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon="assets/icon.ico",
        uac_admin=True,
        manifest="uac_manifest.xml",
        onefile=True,
    )
