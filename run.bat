@echo off
setlocal
title DiskScope CLI

if not exist ".venv\Scripts\python.exe" (
    echo  Virtual environment not found. Running install.bat first...
    call install.bat
)

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONLEGACYWINDOWSSTDIO=0"

call ".venv\Scripts\activate.bat"
python main.py %*
if errorlevel 1 pause
