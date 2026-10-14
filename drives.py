"""DiskScope CLI - drives.py

Enumerates every usable Windows volume and reports totals, free space,
filesystem and drive kind (fixed / removable / network / optical).

Pure stdlib: GetLogicalDrives + GetDriveTypeW + GetVolumeInformationW via
ctypes, with shutil.disk_usage for the numbers. Works on Win10/Win11 and
degrades cleanly under non-Windows dev environments.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import string
import shutil
import sys
from typing import Any

import i18n

# GetDriveTypeW return codes
DRIVE_TYPES = {
    0: "Unknown",
    1: "No Root Dir",
    2: "Removable",
    3: "Fixed",
    4: "Network",
    5: "CD/DVD",
    6: "RAM Disk",
}

_KIND_STYLE = {
    "Fixed": "dv_fixed",
    "Removable": "dv_removable",
    "Network": "dv_network",
    "CD/DVD": "dv_optical",
    "RAM Disk": "dv_ram",
}


def drive_kind(mount: str) -> str:
    t = DRIVE_TYPES.get(_get_drive_type(mount), "Unknown")
    key = _KIND_STYLE.get(t)
    return i18n.t(key) if key else t


def _is_windows() -> bool:
    return sys.platform == "win32" or os.name == "nt"


def _get_drive_type(root: str) -> int:
    if not _is_windows():
        return 3
    try:
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        return int(k32.GetDriveTypeW(ctypes.c_wchar_p(root)))
    except Exception:
        return 0


def _volume_info(root: str) -> tuple[str, str, int]:
    """Return (label, fstype, serial) for a drive root."""
    if not _is_windows():
        return "", "", 0
    vol_buf = wt.WCHAR * 261
    fs_buf = wt.WCHAR * 64
    vol = vol_buf()
    fs = fs_buf()
    serial = wt.DWORD(0)
    maxc = wt.DWORD(0)
    flags = wt.DWORD(0)
    try:
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        ok = k32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), vol, len(vol),
            ctypes.byref(serial), ctypes.byref(maxc), ctypes.byref(flags),
            fs, len(fs))
        if ok:
            return vol.value or "", fs.value or "", serial.value
    except Exception:
        pass
    return "", "", 0


def logical_drives() -> list[str]:
    """['C:\\\\', 'D:\\\\', ...] - every letter with a root directory."""
    if _is_windows():
        bitmask = 0
        try:
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            bitmask = k32.GetLogicalDrives() & 0xFFFFFFFF
        except Exception:
            bitmask = 0
        letters = [f"{ch}:\\" for i, ch in enumerate(string.ascii_uppercase) if bitmask >> i & 1]
        if not letters:  # fallback if the API call failed
            letters = [f"{ch}:\\" for ch in string.ascii_uppercase
                       if os.path.exists(f"{ch}:\\")]
    else:
        letters = ["/"]
    out = []
    for l in letters:
        # filter phantom letters (card readers, empty CD trays...)
        if _get_drive_type(l) in (1,):
            continue
        out.append(l)
    return out


def list_drives(include_unreadable: bool = False) -> list[dict[str, Any]]:
    """Full inventory of usable drives with real usage numbers."""
    drives: list[dict[str, Any]] = []
    for mount in logical_drives():
        label, fstype, serial = _volume_info(mount)
        try:
            usage = shutil.disk_usage(mount)
            total, free = usage.total, usage.free
        except (OSError, ValueError):
            if not include_unreadable:
                continue
            total = free = 0
        if total == 0 and not include_unreadable:
            continue
        drives.append({
            "mount": mount,
            "label": label,
            "fstype": fstype or "?",
            "kind": drive_kind(mount),
            "serial": f"{serial:08X}" if serial else "-",
            "total": total,
            "free": free,
            "used": max(0, total - free),
            "pct": (total - free) / total if total else 0.0,
        })
    return drives


def biggest_drives(drives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(drives, key=lambda d: d.get("used", 0), reverse=True)


def drive_for_path(path: str, drives: list[dict[str, Any]]) -> dict[str, Any] | None:
    p = os.path.abspath(path).upper()
    best = None
    for d in drives:
        m = d["mount"].upper()
        if p.startswith(m) and (best is None or len(m) > len(best["mount"])):
            best = d
    return best


def home_paths() -> dict[str, str]:
    """Well-known user folders that exist (Downloads, Desktop...)."""
    names = ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos")
    home = os.path.expanduser("~")
    return {n: os.path.join(home, n) for n in names if os.path.isdir(os.path.join(home, n))}
