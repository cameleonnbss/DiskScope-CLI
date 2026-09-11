"""DiskScope CLI - steam.py

Steam detection from local data only:
  * Steam.exe via registry (HKCU\\Software\\Valve\\Steam, SteamPath)
  * libraryfolders.vdf -> every library folder + mounted secondary drives
  * appmanifest_*.acf  -> installed apps with real names and install dirs

Every game's size is measured on disk (stateflags/SizeOnDisk in the .acf is
only a hint; the real number comes from scanning the game folder).
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any

import scanner

IS_WINDOWS = sys.platform == "win32" or os.name == "nt"
if IS_WINDOWS:
    import winreg
else:
    winreg = None  # type: ignore[assignment]

_STEAM_EXE_NAMES = ("steam.exe",)
_COMMON_LIB_ROOTS = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"D:\SteamLibrary",
    r"D:\Steam",
    r"E:\SteamLibrary",
    r"E:\Steam",
]


# --------------------------------------------------------------------------- #
#  VDF parsing (minimal, tolerant)
# --------------------------------------------------------------------------- #
_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|([^\s{}"]+)')


def parse_vdf(text: str) -> dict[str, Any]:
    """Parse a KeyValues/VDF document into nested dicts."""
    stack: list[dict[str, Any]] = [{}]
    key: str | None = None
    for m in _VDF_TOKEN.finditer(text):
        quoted, brace, bare = m.groups()
        if brace == "{":
            new: dict[str, Any] = {}
            top = stack[-1]
            if key is not None:
                top[key] = new
                key = None
            elif isinstance(top.get(""), list):
                pass
            stack.append(new)
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        elif quoted is not None:
            val = quoted.encode().decode("unicode_escape")
            top = stack[-1]
            if key is None:
                key = val
            else:
                top[key] = val
                key = None
        elif bare:
            top = stack[-1]
            if key is None:
                key = bare
            else:
                top[key] = bare
                key = None
    return stack[0]


def _find_steam_root() -> str | None:
    if IS_WINDOWS and winreg:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                v, _ = winreg.QueryValueEx(k, "SteamPath")
                if v and os.path.isdir(v):
                    return os.path.normpath(v)
        except OSError:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam") as k:
                v, _ = winreg.QueryValueEx(k, "InstallPath")
                if v and os.path.isdir(v):
                    return os.path.normpath(v)
        except OSError:
            pass
    for root in _COMMON_LIB_ROOTS:
        if os.path.isfile(os.path.join(root, "steam.exe")):
            return root
    return None


def steam_libraries() -> list[str]:
    """Every Steam library folder known to this machine (deduplicated)."""
    root = _find_steam_root()
    libs: list[str] = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        key = os.path.normcase(os.path.normpath(p))
        if key not in seen:
            seen.add(key)
            libs.append(os.path.normpath(p))

    candidates = []
    if root:
        candidates.append(root)
    for r in _COMMON_LIB_ROOTS:
        if os.path.isdir(r):
            candidates.append(r)
    for cand in candidates:
        vdf = os.path.join(cand, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                with open(vdf, "r", encoding="utf-8", errors="replace") as f:
                    data = parse_vdf(f.read())
                lf = data.get("libraryfolders", data)
                for entry in lf.values():
                    if isinstance(entry, dict):
                        p = entry.get("path", "")
                        if p and os.path.isdir(p):
                            _add(p)
            except (OSError, ValueError):
                pass
    for cand in candidates:
        if os.path.isdir(os.path.join(cand, "steamapps")):
            _add(cand)
    return libs


def _acf_manifests(lib: str) -> list[dict[str, Any]]:
    """Installed apps from appmanifest_*.acf (name + appid + installdir)."""
    apps: list[dict[str, Any]] = []
    sm = os.path.join(lib, "steamapps")
    try:
        names = [n for n in os.listdir(sm) if n.startswith("appmanifest_") and n.endswith(".acf")]
    except OSError:
        return apps
    for n in names:
        try:
            with open(os.path.join(sm, n), "r", encoding="utf-8", errors="replace") as f:
                data = parse_vdf(f.read())
            av = data.get("AppState", data)
            appid = str(av.get("appid", "") or re.sub(r"\D", "", n))
            name = av.get("name", "")
            installdir = av.get("installdir", "")
            flags = int(av.get("stateflags", "0") or 0)
            if name and installdir:
                apps.append({"appid": appid, "name": name,
                             "installdir": installdir,
                             "partially": bool(flags & 4)})  # 4 = needs update
        except (OSError, ValueError):
            continue
    return apps


def detect_steam(stop=None, measure_limit: int = 60) -> dict[str, Any]:
    """Full Steam inventory.

    Returns {"installed": bool, "root": str|None,
             "libraries": [ {path, total, games: [...] } ]}
    Game sizes are MEASURED on disk (bounded by measure_limit per library,
    largest manifests first).
    """
    libs_paths = steam_libraries()
    root = _find_steam_root()
    result: dict[str, Any] = {"installed": bool(libs_paths), "root": root,
                              "exe": os.path.join(root, "steam.exe") if root else None,
                              "libraries": []}
    seen_games: set[str] = set()
    import games as games_mod
    for lib in libs_paths:
        manifests = _acf_manifests(lib)
        games: list[dict[str, Any]] = []
        for m in manifests:
            if games_mod.is_noise_game(m["name"]):
                continue  # redistributables & tooling, not real games
            gdir = os.path.join(lib, "steamapps", "common", m["installdir"])
            key = os.path.normcase(os.path.normpath(gdir))
            if key in seen_games:      # same game surfaced via two libraries
                continue
            seen_games.add(key)
            games.append({
                "appid": m["appid"],
                "name": m["name"],
                "path": gdir,
                "library": lib,
                "launcher": "Steam",
                "size": None,          # filled below by real measurement
                "mtime": 0.0,
                "partially": m["partially"],
            })
        # measure the most promising first (manifests are already real apps)
        for g in games[:measure_limit]:
            if stop is not None and stop.is_set():
                break
            if g["path"] and os.path.isdir(g["path"]):
                size, files = scanner.dir_size(g["path"], stop=stop)
                g["size"] = size
                g["files"] = files
                g["mtime"] = scanner.newest_mtime(g["path"])
            else:
                g["size"] = 0
        total = sum(g["size"] or 0 for g in games)
        result["libraries"].append({"path": lib, "total": total, "games": games})
    return result


def open_game_folder(game: dict[str, Any]) -> bool:
    """Open the game folder in Explorer (never deletes anything)."""
    path = game.get("path") or ""
    if path and os.path.isdir(path):
        try:
            if IS_WINDOWS:
                os.startfile(path)  # type: ignore[attr-defined]
                return True
        except OSError:
            pass
    return False


def open_steam_store_page(appid: str) -> bool:
    """Open the Steam store page (optional helper, harmless)."""
    if appid:
        try:
            if IS_WINDOWS:
                os.startfile(f"https://store.steampowered.com/app/{appid}")  # type: ignore[attr-defined]
                return True
        except OSError:
            pass
    return False
