#!/usr/bin/env bash
# ============================================================
#  DiskScope CLI - one-file launcher (bash twin of run.bat).
#  Bootstraps everything itself: finds Python 3.10+, creates
#  .venv on first run, installs missing dependencies, starts
#  the app. Works under Git Bash / WSL / Linux / macOS
#  (the app itself is Windows-focused; elsewhere it degrades).
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

# ---- 1) find a Python interpreter -------------------------------------- --
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 &&
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
if [ -z "$PY" ]; then
    echo " [ERROR] Python 3.10+ not found. Install it and reopen this file." >&2
    exit 1
fi

# ---- 2) create the venv on first run ------------------------------------ --
if [ ! -x ".venv/bin/python" ] && [ ! -x ".venv/Scripts/python.exe" ]; then
    echo " First run: creating the virtual environment..."
    "$PY" -m venv .venv
fi
if [ -x ".venv/bin/python" ]; then
    VPY=".venv/bin/python"
else
    VPY=".venv/Scripts/python.exe"   # Git Bash layout
fi

# ---- 3) install dependencies only when actually missing ----------------- --
if ! "$VPY" -c "import rich, send2trash" >/dev/null 2>&1; then
    echo " First run: installing dependencies (rich, send2trash)..."
    "$VPY" -m pip install --upgrade pip >/dev/null
    "$VPY" -m pip install -r requirements.txt
fi

# ---- 4) start the app ----------------------------------------------------- --
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
exec "$VPY" main.py "$@"
