"""DiskScope CLI - applications.py

Installed-application detection with REAL sizes only.

Sources:
  * Registry uninstall keys (HKLM/HKCU, 32/64-bit views) -> name, publisher,
    version, install location, EstimatedSize (KB, often missing -> then None)
  * Windows Store packages (WindowsApps) via the AppX PowerShell cmdlet,
    falling back to direct enumeration when access is denied
  * Per-user AppData programs (Local\\Programs) measured on disk

Estimated "last used" dates come from file mtimes only and are clearly
labelled as estimates: Windows does not expose true usage dates.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

import scanner

IS_WINDOWS = sys.platform == "win32" or os.name == "nt"

if IS_WINDOWS:
    import winreg
else:  # dev on non-Windows: keep the module importable
    winreg = None  # type: ignore[assignment]

_UNINSTALL_HIVES = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0) if winreg else None,
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_32KEY) if winreg else None,
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0) if winreg else None,
]
_UNINSTALL_HIVES = [h for h in _UNINSTALL_HIVES if h]


def _reg_read(key: Any, name: str) -> Any:
    try:
        v, _ = winreg.QueryValueEx(key, name)
        return v
    except OSError:
        return None


def _reg_enum_keys(root: int, subkey: str, view: int = 0) -> list[str]:
    out: list[str] = []
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break
    except (OSError, FileNotFoundError, PermissionError):
        pass
    return out


def _newest_mtime(folder: str) -> float:
    """Newest mtime among first ~150 executable-ish files (bounded)."""
    best = 0.0
    try:
        n = 0
        with os.scandir(folder) as it:
            for e in it:
                n += 1
                if n > 150:
                    break
                try:
                    if e.is_file(follow_symlinks=False):
                        m = e.stat(follow_symlinks=False).st_mtime
                        if m > best:
                            best = m
                except OSError:
                    continue
    except OSError:
        pass
    return best


# --------------------------------------------------------------------------- #
#  Registry apps
# --------------------------------------------------------------------------- #
def registry_apps(stop=None) -> list[dict[str, Any]]:
    """Apps from the uninstall registry keys. size=None when unknown."""
    apps: dict[str, dict[str, Any]] = {}
    for hive, sub, view in _UNINSTALL_HIVES:
        for guid in _reg_enum_keys(hive, sub, view):
            if stop is not None and stop.is_set():
                break
            path = f"{sub}\\{guid}"
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as k:
                    name = _reg_read(k, "DisplayName")
                    if not name or _reg_read(k, "SystemComponent") == 1:
                        continue
                    if _reg_read(k, "ParentKeyName"):      # update rollups
                        continue
                    loc = _reg_read(k, "InstallLocation") or ""
                    est = _reg_read(k, "EstimatedSize")
                    size = int(est) * 1024 if isinstance(est, int) and est > 0 else None
                    apps[name] = {
                        "name": name,
                        "publisher": _reg_read(k, "Publisher") or "",
                        "version": str(_reg_read(k, "Version") or ""),
                        "location": loc,
                        "size": size,          # None = unknown, never guessed
                        "size_source": "registry" if size else "unknown",
                        "uninstall": _reg_read(k, "UninstallString") or "",
                        "store": False,
                    }
            except (OSError, PermissionError):
                continue
    return sorted(apps.values(), key=lambda a: a["name"].lower())


def _measure_app_sizes(apps: list[dict[str, Any]], stop=None,
                       budget: int = 400) -> None:
    """Measure real size for apps that have a valid InstallLocation.

    Registry EstimatedSize is frequently absent or stale, so the folder is
    measured when it exists. `budget` limits how many folders we measure
    to keep startup snappy.
    """
    done = 0
    for app in apps:
        if stop is not None and stop.is_set() or done >= budget:
            break
        loc = app.get("location") or ""
        if not loc or not os.path.isdir(loc):
            continue
        size, files = scanner.dir_size(loc, stop=stop)
        if size > 0:
            app["size"] = size
            app["size_source"] = "disk"
            app["files"] = files
            app["last_used"] = _newest_mtime(loc)
        done += 1


# --------------------------------------------------------------------------- #
#  Windows Store apps (bounded, best-effort)
# --------------------------------------------------------------------------- #
_PSH_APPX = (
    "powershell -NoProfile -NonInteractive -Command "
    "\"Get-AppxPackage | Select-Object -First 120 Name,PackageFullName,"
    "InstallLocation | ConvertTo-Json -Compress\""
)


def store_apps(stop=None) -> list[dict[str, Any]]:
    """Windows Store apps. Best-effort; sizes measured when accessible."""
    if not IS_WINDOWS:
        return []
    out: list[dict[str, Any]] = []
    try:
        raw = subprocess.run(_PSH_APPX, capture_output=True, text=True,
                             timeout=60, creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
        import json
        data = json.loads(raw.stdout or "[]")
        if isinstance(data, dict):
            data = [data]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        data = []
    for pkg in data[:120]:
        if stop is not None and stop.is_set():
            break
        name = pkg.get("Name") or ""
        loc = pkg.get("InstallLocation") or ""
        if not name:
            continue
        size = None
        if loc and os.path.isdir(loc):
            size, _ = scanner.dir_size(loc, max_files=4000)
        out.append({"name": f"{name} (Store)", "publisher": "Microsoft Store",
                    "version": str(pkg.get("Version", "")), "location": loc,
                    "size": size if size else None, "size_source": "disk" if size else "unknown",
                    "uninstall": "", "store": True})
    return out


# --------------------------------------------------------------------------- #
#  Per-user AppData programs
# --------------------------------------------------------------------------- #
def appdata_programs(stop=None) -> list[dict[str, Any]]:
    home = os.path.expanduser("~")
    roots = [os.path.join(home, r"AppData\Local\Programs"),
             os.path.join(home, r"Scoop\apps"),
             os.path.join(home, "Applications")]
    out: list[dict[str, Any]] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            with os.scandir(root) as it:
                entries = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for e in entries[:80]:
            if stop is not None and stop.is_set():
                break
            size, files = scanner.dir_size(e.path, stop=stop)
            if size > 0:
                out.append({"name": e.name, "publisher": "(AppData)",
                            "version": "", "location": e.path, "size": size,
                            "size_source": "disk", "files": files,
                            "last_used": _newest_mtime(e.path),
                            "uninstall": "", "store": False})
    return out


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
def detect_apps(stop=None, include_store: bool = True) -> list[dict[str, Any]]:
    """All detectable applications, sorted by size desc (unknowns last)."""
    apps = registry_apps(stop=stop)
    apps += appdata_programs(stop=stop)
    if include_store:
        apps += store_apps(stop=stop)
    # dedupe by name keeping the largest known size
    merged: dict[str, dict[str, Any]] = {}
    for a in apps:
        key = (a["name"] or "").lower()
        cur = merged.get(key)
        if cur is None:
            merged[key] = a
        else:
            if (a.get("size") or 0) > (cur.get("size") or 0):
                merged[key] = a
    out = list(merged.values())
    # Registry EstimatedSize is frequently missing/stale; the helper that
    # measures those InstallLocations on disk was defined but never called,
    # so unknown-size apps were reported as size=None. Run it here (bounded).
    _measure_app_sizes([a for a in out if a.get("size_source") != "disk"], stop=stop)
    out.sort(key=lambda a: (-(a.get("size") or 0), a["name"].lower()))
    return out


def mark_estimates(apps: list[dict[str, Any]], now: float | None = None) -> None:
    """Attach `last_used_label` clearly flagged as an estimate."""
    now = now or time.time()
    for a in apps:
        mtime = a.get("last_used") or 0
        if mtime:
            days = int((now - mtime) / 86400)
            a["last_used_label"] = f"~{days} j (est.)"
        else:
            a["last_used_label"] = "n/d"
