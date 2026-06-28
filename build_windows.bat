@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM build_windows.bat  –  Build "iPad_Mirror_Setup.exe" on Windows
REM
REM Run this script on a Windows PC with Python 3.10+ in PATH.
REM Optionally install Inno Setup to produce a proper installer:
REM   https://jrsoftware.org/isdl.php
REM ─────────────────────────────────────────────────────────────────────────

echo.
echo ╔═══════════════════════════════════╗
echo ║   iPad Mirror  -  Windows Build   ║
echo ╚═══════════════════════════════════╝
echo.

REM ── 1. Install Python dependencies ───────────────────────────────────────
echo ^> Installing Python dependencies...
python -m pip install -q --upgrade pillow pyinstaller pymobiledevice3 PyQt6
if %errorlevel% neq 0 (
    echo ERROR: pip install failed
    pause & exit /b 1
)

REM ── 2. Generate icons ────────────────────────────────────────────────────
echo ^> Generating icons...
python assets\make_icons.py
if %errorlevel% neq 0 (
    echo ERROR: icon generation failed
    pause & exit /b 1
)

REM ── 3. Clean previous build ──────────────────────────────────────────────
echo ^> Cleaning previous build...
if exist build rmdir /s /q build
if exist "dist\iPad Mirror.exe" del /f /q "dist\iPad Mirror.exe"

REM ── 4. Run PyInstaller ───────────────────────────────────────────────────
echo ^> Running PyInstaller (this takes a few minutes)...
python -m PyInstaller iPad_Mirror.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller failed
    pause & exit /b 1
)

echo.
echo [OK] iPad Mirror.exe built successfully.

REM ── 5. Build installer with Inno Setup (if installed) ────────────────────
echo.
echo ^> Looking for Inno Setup...

set ISCC=""
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe"       set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"

if %ISCC%=="" (
    echo   Inno Setup not found – skipping installer build.
    echo   To build an installer, install Inno Setup from:
    echo   https://jrsoftware.org/isdl.php
    echo   Then re-run this script.
    echo.
    echo ============================================================
    echo  Portable exe:  dist\iPad Mirror.exe
    echo ============================================================
) else (
    echo ^> Building installer with Inno Setup...
    %ISCC% setup_windows.iss
    if %errorlevel% neq 0 (
        echo ERROR: Inno Setup failed
        pause & exit /b 1
    )
    echo.
    echo ============================================================
    echo  Portable exe :  dist\iPad Mirror.exe
    echo  Installer    :  dist\iPad_Mirror_Setup.exe
    echo ============================================================
)

echo.
echo NOTE: iTunes must be installed on the target PC for USB iPad detection.
echo       Get it from the Microsoft Store or apple.com/itunes
echo.
pause
