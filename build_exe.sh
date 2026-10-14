#!/usr/bin/env bash
# ===========================================================================
#  DiskTop - build a single self-contained executable for Linux/macOS.
#  Uses PyInstaller. Best-effort compiles the native C accelerator first.
#  Result: dist/DiskTop
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")"

# ---- 1) find a python ------------------------------------------------------
PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "[x] No python3 found. Install Python 3.10+"; exit 1; }

# ---- 2) venv + build deps --------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "[.] Creating virtual environment..."
    "$PY" -m venv .venv
fi
VPY=".venv/bin/python"
[ -x "$VPY" ] || VPY=".venv/Scripts/python.exe"
echo "[.] Installing runtime + PyInstaller..."
"$VPY" -m pip install --upgrade pip >/dev/null 2>&1 || true
"$VPY" -m pip install -r requirements.txt pyinstaller

# ---- 3) optional native accelerator (never fails the build) ---------------
if [ ! -x "native/dufast" ]; then
    for cc in cc gcc clang; do
        if command -v "$cc" >/dev/null 2>&1; then
            echo "[.] Compiling native accelerator (dufast)..."
            "$cc" -O2 -o native/dufast native/dufast.c >/dev/null 2>&1 && break
        fi
    done
fi

# ---- 4) freeze -------------------------------------------------------------
echo "[.] Building dist/DiskTop with PyInstaller..."
"$VPY" -m PyInstaller DiskTop.spec --noconfirm

echo
echo "[OK] Built: $(pwd)/dist/DiskTop"
