@echo off
setlocal
title DiskScope CLI - Installation

echo.
echo  ============================================
echo    DiskScope CLI - Installation
echo  ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo  [ERROR] Python not found in PATH.
    echo  Install Python 3.10+ from https://www.python.org/downloads/
    echo  and check "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

python --version

if not exist ".venv" (
    echo  Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

echo  Installing dependencies...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

python main.py --selftest
if errorlevel 1 (
    echo  [ERROR] Self-test failed.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo    Installation complete!
echo    Launch the app with run.bat
echo  ============================================
echo.
pause
