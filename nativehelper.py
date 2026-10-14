"""DiskTop - nativehelper.py

Thin, fail-safe bridge to the optional compiled `dufast` helper (native/dufast.c).

Design guarantees (nothing here can break the app):
  * If the binary was never built, every function degrades to "no native".
  * Any crash, timeout, bad output or the DISKSCOPE_NO_NATIVE=1 kill switch
    makes us fall back to the pure-Python scanner.
  * We only ever TRUST a native size when it is > 0; an empty/failed read
    returns None so the authoritative Python walk still runs (this neutralises
    any exotic path/encoding edge cases on machines that DID build the binary).
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_NATIVE_DIR = os.path.join(_HERE, "native")


def _candidate_dirs() -> list[str]:
    """Where a dufast binary may live: source tree, PyInstaller bundle, or
    alongside a frozen executable. Non-existent dirs are filtered by caller."""
    dirs = [_NATIVE_DIR]
    if getattr(sys, "frozen", False):  # running inside a PyInstaller bundle
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        dirs.append(os.path.join(base, "native"))
        dirs.append(os.path.join(os.path.dirname(sys.executable), "native"))
    return dirs


def binary_path() -> Optional[str]:
    """Absolute path to a built dufast binary, or None."""
    if os.environ.get("DISKSCOPE_NO_NATIVE"):
        return None
    for d in _candidate_dirs():
        for name in ("dufast.exe", "dufast"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None



def available() -> bool:
    return binary_path() is not None


def native_du(path: str, timeout: float = 60.0) -> Optional[tuple[int, int]]:
    """Return (total_bytes, file_count) via the native helper, else None.

    Never raises: any problem returns None so callers fall back to Python.
    """
    b = binary_path()
    if not b:
        return None
    try:
        r = subprocess.run([b, path], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    parts = r.stdout.split()
    if len(parts) < 2:
        return None
    try:
        size = int(parts[0])
        count = int(parts[1])
    except ValueError:
        return None
    if size < 0 or count < 0:
        return None
    # Only a positive size is trusted; 0 could be an unreadable/encoding miss.
    if size == 0:
        return None
    return size, count
