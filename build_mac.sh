#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_mac.sh  –  Build "iPad Mirror.app" and (optionally) a .dmg installer
#
# Usage:
#   bash build_mac.sh          # build .app only
#   bash build_mac.sh --dmg    # build .app + create .dmg with create-dmg
#
# Requirements (auto-installed if missing):
#   pip3 install pyinstaller cairosvg pillow
#   brew install create-dmg     (only if --dmg is requested)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_NAME="iPad Mirror"
PYTHON=python3

echo "╔══════════════════════════════════╗"
echo "║   iPad Mirror  –  macOS Build    ║"
echo "╚══════════════════════════════════╝"
echo ""

# ── 1. Install Python build dependencies ─────────────────────────────────────
echo "▸ Installing Python dependencies…"
$PYTHON -m pip install -q --upgrade \
    pyinstaller pillow \
    pymobiledevice3 PyQt6

# ── 2. Generate icons ─────────────────────────────────────────────────────────
echo "▸ Generating icons…"
$PYTHON assets/make_icons.py

# ── 3. Clean previous build ───────────────────────────────────────────────────
echo "▸ Cleaning previous build…"
rm -rf build dist

# ── 4. Run PyInstaller ────────────────────────────────────────────────────────
echo "▸ Running PyInstaller…"
$PYTHON -m PyInstaller iPad_Mirror.spec --clean --noconfirm

# ── 5. Code sign (ad-hoc, no Apple Developer account needed for local use) ───
APP_PATH="dist/${APP_NAME}.app"
echo "▸ Ad-hoc code signing…"
codesign --force --deep --sign - "$APP_PATH" 2>/dev/null || \
    echo "  (code signing skipped — codesign not available)"

# ── 6. Optional .dmg ─────────────────────────────────────────────────────────
if [[ "${1:-}" == "--dmg" ]]; then
    echo "▸ Creating .dmg installer…"
    if ! command -v create-dmg &>/dev/null; then
        echo "  Installing create-dmg via Homebrew…"
        brew install create-dmg
    fi
    DMG_OUT="dist/${APP_NAME}.dmg"
    rm -f "$DMG_OUT"
    create-dmg \
        --volname "${APP_NAME}" \
        --volicon "assets/icon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 175 190 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 425 190 \
        "$DMG_OUT" \
        "dist/"
    echo "  ✓  ${DMG_OUT}"
fi

echo ""
echo "✅  Build complete →  ${APP_PATH}"
echo ""
echo "To run:  open \"${APP_PATH}\""
echo ""
echo "NOTE: The first time you open the app macOS may show a security warning."
echo "Go to System Preferences → Security & Privacy → 'Open Anyway'."
