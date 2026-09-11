"""DiskScope CLI - epic.py

Epic Games detection from local manifest files:
  * %PROGRAMDATA%\\Epic\\EpicGamesLauncher\\Data\\Manifests\\*.item
  * %LOCALAPPDATA%\\EpicGamesLauncher\\... (variant layouts)
  * fallback: scan every fixed drive for .egstore folders (bounded)

Each .item JSON gives AppName, DisplayName, InstallLocation, CatalogItemId
and (when present) AppCategories. Sizes are measured on disk.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import scanner

IS_WINDOWS = sys.platform == "win32" or os.name == "nt"

_MANIFEST_GLOBS = [
    os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                 "Epic", "EpicGamesLauncher", "Data", "Manifests"),
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
                 "EpicGamesLauncher", "Data", "Manifests"),
]

# Well-known launcher roots used when no manifests are found
_COMMON_ROOTS = [
    r"D:\Epic Games",
    r"D:\EpicGames",
    r"E:\Epic Games",
    r"E:\EpicGames",
    r"C:\Program Files\Epic Games",
    r"D:\Games\Epic Games",
]


def _manifest_dirs() -> list[str]:
    return [d for d in _MANIFEST_GLOBS if os.path.isdir(d)]


def _parse_item(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("DisplayName") or data.get("AppName")
    loc = data.get("InstallLocation") or ""
    if not name:
        return None
    return {
        "name": name,
        "appname": data.get("AppName", ""),
        "catalog": data.get("CatalogItemId", ""),
        "path": loc,
        "launcher": "Epic Games",
        "version": data.get("AppVersionString") or data.get("BuildVersion") or "",
        "categories": data.get("AppCategories") or [],
    }


def _egstore_roots(stop=None, max_drives: int = 6) -> list[str]:
    """Fallback detection: look for .egstore folders at shallow depth."""
    roots: list[str] = []
    drives = [f"{c}:\\" for c in "CDEFGH"
              if os.path.isdir(f"{c}:\\")]
    for drv in drives[:max_drives]:
        if stop is not None and stop.is_set():
            break
        try:
            with os.scandir(drv) as it:
                for e in it:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    # drive-level game folders that may contain .egstore
                    for sub in (e,):
                        eg = os.path.join(sub.path, ".egstore")
                        if os.path.isdir(eg):
                            if sub.path not in roots:
                                roots.append(sub.path)
                    # one level deeper: D:\Games\Fortnite\.egstore
                    try:
                        with os.scandir(e.path) as it2:
                            for e2 in it2:
                                if e2.is_dir(follow_symlinks=False):
                                    eg = os.path.join(e2.path, ".egstore")
                                    if os.path.isdir(eg) and e2.path not in roots:
                                        roots.append(e2.path)
                    except OSError:
                        continue
        except OSError:
            continue
    return roots


def detect_epic(stop=None, measure_limit: int = 60) -> dict[str, Any]:
    """Full Epic inventory with real on-disk sizes."""
    games: list[dict[str, Any]] = []

    seen_paths: set[str] = set()
    for mdir in _manifest_dirs():
        try:
            items = [os.path.join(mdir, n) for n in os.listdir(mdir) if n.endswith(".item")]
        except OSError:
            continue
        for p in items[:200]:
            if stop is not None and stop.is_set():
                break
            parsed = _parse_item(p)
            if parsed and parsed["path"] and parsed["path"] not in seen_paths:
                seen_paths.add(parsed["path"])
                games.append(parsed)

    if not games:
        # fallback: launcher-installed folders found by .egstore markers
        for root in _egstore_roots(stop=stop) + [r for r in _COMMON_ROOTS if os.path.isdir(r)]:
            if stop is not None and stop.is_set():
                break
            if root in seen_paths:
                continue
            seen_paths.add(root)
            games.append({"name": os.path.basename(root), "appname": "",
                          "catalog": "", "path": root, "launcher": "Epic Games",
                          "version": "", "categories": []})

    for g in games[:measure_limit]:
        if stop is not None and stop.is_set():
            break
        p = g.get("path") or ""
        if p and os.path.isdir(p):
            size, files = scanner.dir_size(p, stop=stop)
            g["size"] = size
            g["files"] = files
            g["mtime"] = scanner.newest_mtime(p)
        else:
            g["size"] = 0

    games.sort(key=lambda g: g.get("size") or 0, reverse=True)
    return {"installed": bool(games), "games": games,
            "total": sum(g.get("size") or 0 for g in games)}
