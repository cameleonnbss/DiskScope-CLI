@echo off
rem ===========================================================================
rem  DiskTop - build a SINGLE self-contained Windows executable (dist\DiskTop.exe)
rem  Uses PyInstaller. Best-effort compiles the native C accelerator first.
rem  Just double-click this file. Requires a Python 3.10+ on PATH or via `py`.
rem ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

rem ---- 1) find a python -----------------------------------------------------
set "PYTHON="
py -3 --version >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON ( where python >nul 2>nul && set "PYTHON=python" )
if not defined PYTHON ( echo [x] No Python found. Install Python 3.10+ & exit /b 1 )

rem ---- 2) build the venv + install build deps -------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [.] Creating virtual environment...
    %PYTHON% -m venv .venv
)
echo [.] Installing runtime + PyInstaller...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller || (echo [x] pip install failed & exit /b 1)

rem ---- 3) optional native accelerator (never fails the build) ---------------
where gcc >nul 2>nul
if not errorlevel 1 if not exist "native\dufast.exe" (
    echo [.] Compiling native accelerator \(dufast\)...
    gcc -O2 -o native\dufast.exe native\dufast.c >nul 2>nul
)

rem ---- 4) freeze ------------------------------------------------------------
echo [.] Building dist\DiskTop.exe with PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller DiskTop.spec --noconfirm
if errorlevel 1 ( echo [x] BUILD FAILED & exit /b 1 )

echo.
echo [OK] Built: %cd%\dist\DiskTop.exe
endlocal
