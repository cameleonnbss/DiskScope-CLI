@echo off
setlocal EnableExtensions
title DiskScope CLI
cd /d "%~dp0"

rem ============================================================
rem  DiskScope CLI - one-file launcher.
rem  Bootstraps everything itself: finds Python, creates the
rem  virtual environment on first run, installs dependencies if
rem  they are missing, then starts the app. No separate install
rem  step needed. Double-click it and it just works.
rem ============================================================

set "PAUSE_ON_FAIL=1"
if /i "%~1"=="--selftest" set "PAUSE_ON_FAIL="

rem ---- 1) find a Python interpreter (PATH not required) ----------------- --
set "PYTHON="
py -3 --version >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON (
    where python >nul 2>nul && set "PYTHON=python"
)
if not defined PYTHON (
    where python3 >nul 2>nul && set "PYTHON=python3"
)
if not defined PYTHON (
    echo  [ERROR] Python 3.10+ not found.
    echo  Install it from https://www.python.org/downloads/
    echo  ^(check "Add python.exe to PATH"^), then open this file again.
    pause
    exit /b 1
)

rem ---- 2) create the venv on first run ---------------------------------- --
if not exist ".venv\Scripts\python.exe" (
    echo  First run: creating the virtual environment...
    %PYTHON% -m venv .venv >nul 2>nul
    if not exist ".venv\Scripts\python.exe" (
        echo  [ERROR] Could not create .venv - run this file from a folder
        echo  where you have write access, then try again.
        pause
        exit /b 1
    )
)

rem ---- 3) install dependencies only when they are actually missing ------ --
".venv\Scripts\python.exe" -c "import rich, send2trash" >nul 2>nul
if errorlevel 1 (
    echo  First run: installing dependencies ^(rich, send2trash^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo  [ERROR] Dependency installation failed - check your internet
        echo  connection and run this file again.
        pause
        exit /b 1
    )
)

rem ---- 4) start the app --------------------------------------------------- --
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONLEGACYWINDOWSSTDIO=0"

".venv\Scripts\python.exe" main.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" if defined PAUSE_ON_FAIL pause
exit /b %RC%
