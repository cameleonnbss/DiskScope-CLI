@echo off
setlocal EnableExtensions
title DiskScope CLI - Installation
cd /d "%~dp0"

echo.
echo  ============================================
echo    DiskScope CLI - Installation / check
echo  ============================================
echo.
echo  run.bat already bootstraps everything on its own; this
echo  script just does it up-front and runs the self-test.
echo.

call run.bat --selftest
if errorlevel 1 (
    echo.
    echo  [ERROR] Installation check failed - see messages above.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo    Installation complete!
echo    Launch the app with run.bat (or run.sh)
echo  ============================================
echo.
pause
