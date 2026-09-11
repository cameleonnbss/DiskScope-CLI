"""DiskScope CLI - games.py

Aggregates every game launcher:

  Steam            -> steam.py (registry + libraryfolders.vdf + .acf)
  Epic Games       -> epic.py (.item manifests / .egstore markers)
  Battle.net       -> product.db + %PROGRAMDATA%\\Blizzard Entertainment\\*
  Ubisoft Connect  -> registry + Ubisoft Game Launcher\\installed games
  EA App           -> %PROGRAMDATA%\\EA\\Actions + Steam/EPIC compat markers
  Riot Games       -> registry + Riot Games installs
  Xbox / GOG       -> GOG Galaxy per-game .json info files, Xbox apps

A game is only listed when there is REAL LOCAL PROOF (manifest file,
registry entry, marker folder). Names alone are never trusted.
Every size is measured on disk.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import epic
import scanner
import steam

IS_WINDOWS = sys.platform == "win32" or os.name == "nt"
if IS_WINDOWS:
    import winreg
else:
    winreg = None  # type: ignore[assignment]

PROGRAMDATA = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
PROGRAMFILES = os.environ.get("ProgramFiles", r"C:\Program Files")
PROGRAMFILES_X86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))


def _newest(path: str) -> float:
    return scanner.newest_mtime(path)


def _game(name: str, path: str, launcher: str) -> dict[str, Any]:
    return {"name": name, "path": path, "launcher": launcher,
            "size": None, "files": 0, "mtime": 0.0, "appid": ""}


# Names that come from launcher manifests but are not real games.
_NOISE_PATTERNS = (
    "steamworks common redistributables", "steamworks shared",
    "directx", "microsoft visual c++", "visual c++ redistributable",
    "unreal engine redist", "physx", "open al", "openal",
    "steam runtime", "proton "
    "steam linux runtime", "dotnet desktop runtime", ".net runtime",
    "microsoft edge webview", "webview2", "easetup", "eais",
    "easy anti-cheat", "easyanticheat", "punkbuster", "vcredist",
)


def is_noise_game(name: str) -> bool:
    n = (name or "").strip().lower()
    return any(p in n for p in _NOISE_PATTERNS)


def _measure(games: list[dict[str, Any]], stop=None, limit: int = 40) -> None:
    for g in games[:limit]:
        if stop is not None and stop.is_set():
            break
        if g.get("path") and os.path.isdir(g["path"]):
            size, files = scanner.dir_size(g["path"], stop=stop)
            g["size"], g["files"] = size, files
            g["mtime"] = _newest(g["path"])
        else:
            g["size"] = 0


# --------------------------------------------------------------------------- #
#  Battle.net
# --------------------------------------------------------------------------- #
def _battle_net(stop=None) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    # product.db is a binary sqlite-like blob; we extract readable strings
    db = os.path.join(PROGRAMDATA, "Battle.net", "Agent", "product.db")
    blob = b""
    try:
        with open(db, "rb") as f:
            blob = f.read(2_000_000)
    except OSError:
        blob = b""
    seen_uids: set[str] = set()
    if blob:
        import re
        # product.db contains strings like "product_uid" ... "game_folder"
        txt = blob.decode("latin-1", errors="replace")
        for m in re.finditer(r"([a-z0-9_]{3,30})\x00{0,2}([A-Za-z]:\\\\[^\x00]{3,120})", txt):
            uid, folder = m.group(1), m.group(2).replace("\\\\", "\\")
            if uid in seen_uids or not os.path.isdir(folder):
                continue
            seen_uids.add(uid)
            games.append(_game(os.path.basename(folder), folder, "Battle.net"))
    # Fallback: well-known install roots
    roots = [
        os.path.join(PROGRAMFILES_X86, "World of Warcraft"),
        os.path.join(PROGRAMFILES_X86, "Overwatch"),
        os.path.join(PROGRAMFILES_X86, "Call of Duty"),
        os.path.join(PROGRAMFILES_X86, "Diablo IV"),
        r"D:\World of Warcraft", r"D:\Overwatch", r"D:\Call of Duty",
    ]
    known = {os.path.normcase(g["path"]) for g in games}
    for r in roots:
        if os.path.isdir(r) and os.path.normcase(r) not in known:
            games.append(_game(os.path.basename(r), r, "Battle.net"))
    return games


# --------------------------------------------------------------------------- #
#  Ubisoft Connect
# --------------------------------------------------------------------------- #
def _ubisoft(stop=None) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    base = os.path.join(PROGRAMFILES_X86, "Ubisoft", "Ubisoft Game Launcher")
    data_dir = None
    # installed_response / installed games are stored locally
    for cand in (os.path.join(base, "data"), os.path.join(LOCALAPPDATA, "Ubisoft Game Launcher", "data")):
        if os.path.isdir(cand):
            data_dir = cand
            break
    settings = os.path.join(base, "settings.yaml") if os.path.isdir(base) else None
    installs: dict[str, str] = {}
    if data_dir:
        # data/games/* contain per-game registry of installs (yaml-ish)
        gdir = os.path.join(data_dir, "games")
        if os.path.isdir(gdir):
            try:
                for gid in os.listdir(gdir):
                    stats = os.path.join(gdir, gid, "installs.ini") or ""
                    for ini_name in ("installs.ini", "install.ini"):
                        ini = os.path.join(gdir, gid, ini_name)
                        if os.path.isfile(ini):
                            try:
                                with open(ini, "r", encoding="utf-8", errors="replace") as f:
                                    for line in f:
                                        if "=" in line:
                                            k, v = line.split("=", 1)
                                            if "installdir" in k.lower().replace("_", ""):
                                                installs[gid] = v.strip()
                            except OSError:
                                pass
            except OSError:
                pass
    # Registry fallback
    if IS_WINDOWS and winreg:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs") as hk:
                i = 0
                while True:
                    try:
                        gid = winreg.EnumKey(hk, i)
                        i += 1
                        with winreg.OpenKey(hk, gid) as gk:
                            try:
                                v, _ = winreg.QueryValueEx(gk, "InstallDir")
                                if v and os.path.isdir(v):
                                    installs.setdefault(gid, v)
                            except OSError:
                                pass
                    except OSError:
                        break
        except OSError:
            pass
    for gid, loc in installs.items():
        if os.path.isdir(loc):
            games.append(_game(os.path.basename(loc.rstrip("\\/")), loc, "Ubisoft Connect"))
    if settings is None and not installs:
        # last resort: common library roots with Ubisoft markers
        for root in (r"D:\Ubisoft", r"D:\Ubisoft Game Launcher", r"E:\Ubisoft"):
            if os.path.isdir(root):
                try:
                    with os.scandir(root) as it:
                        for e in it:
                            if e.is_dir(follow_symlinks=False) and os.path.isdir(os.path.join(e.path, " Ubisoft")):
                                games.append(_game(e.name, e.path, "Ubisoft Connect"))
                except OSError:
                    pass
    return games


# --------------------------------------------------------------------------- #
#  EA App
# --------------------------------------------------------------------------- #
def _ea_app(stop=None) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    ea_dir = os.path.join(PROGRAMDATA, "EA", "Actions")
    if os.path.isdir(ea_dir):
        try:
            with os.scandir(ea_dir) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False) and e.name.startswith("Origin"):
                        # folder name like "Origin.GAME_NAME" ; .maf files carry paths
                        mafs = []
                        try:
                            mafs = [n for n in os.listdir(e.path) if n.endswith(".maf")]
                        except OSError:
                            pass
                        for maf in mafs[:1]:
                            try:
                                with open(os.path.join(e.path, maf), "r", encoding="utf-8", errors="replace") as f:
                                    content = f.read()
                                import re
                                m = re.search(r'downloadname="([^"]+)"', content)
                                install = re.search(r'filepath="([^"]+)"', content)
                                if install and os.path.isdir(install.group(1)):
                                    games.append(_game(
                                        (m.group(1) if m else os.path.basename(install.group(1))),
                                        install.group(1), "EA App"))
                            except OSError:
                                continue
        except OSError:
            pass
    # Common install roots when the .maf parse yields nothing
    if not games:
        for root in (r"C:\Program Files\EA Games", r"D:\EA Games", r"E:\EA Games",
                     os.path.join(PROGRAMFILES_X86, "Origin Games")):
            if os.path.isdir(root):
                try:
                    with os.scandir(root) as it:
                        for e in it:
                            if e.is_dir(follow_symlinks=False):
                                games.append(_game(e.name, e.path, "EA App"))
                except OSError:
                    pass
    return games


# --------------------------------------------------------------------------- #
#  Riot Games
# --------------------------------------------------------------------------- #
def _riot(stop=None) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    candidates = {
        "League of Legends": [r"C:\Riot Games\League of Legends", r"D:\Riot Games\League of Legends"],
        "VALORANT": [r"C:\Riot Games\VALORANT", r"D:\Riot Games\VALORANT"],
        "Teamfight Tactics": [r"C:\Riot Games\Teamfight Tactics"],
        "League of Legends: Wild Rift": [],
    }
    for name, paths in candidates.items():
        for p in paths:
            if os.path.isdir(p):
                games.append(_game(name, p, "Riot Games"))
                break
    # riotclientservices registry points to installs
    if IS_WINDOWS and winreg and not games:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Riot Games") as rk:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(rk, i)
                        i += 1
                        try:
                            with winreg.OpenKey(rk, sub) as sk:
                                v, _ = winreg.QueryValueEx(sk, "InstallLocation") if True else ("", 0)
                                if v and os.path.isdir(v):
                                    games.append(_game(sub, v, "Riot Games"))
                        except OSError:
                            continue
                    except OSError:
                        break
        except OSError:
            pass
    return games


# --------------------------------------------------------------------------- #
#  GOG (Galaxy client stores per-game metadata json)
# --------------------------------------------------------------------------- #
def _gog(stop=None) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    base = os.path.join(PROGRAMDATA, "GOG.com", "Galaxy", "storage", "game_info")
    if os.path.isdir(base):
        try:
            entries = [os.path.join(base, n) for n in os.listdir(base) if n.endswith(".json")]
        except OSError:
            entries = []
        for p in entries[:200]:
            if stop is not None and stop.is_set():
                break
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            gp = data.get("gamePath") or data.get("installPath") or ""
            name = os.path.basename(gp.rstrip("\\/")) if gp else data.get("title") or os.path.basename(p)
            if gp and os.path.isdir(gp):
                games.append(_game(name, gp, "GOG"))
    return games


# --------------------------------------------------------------------------- #
#  Xbox / Microsoft Gaming
# --------------------------------------------------------------------------- #
def _xbox(stop=None) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    if not IS_WINDOWS or winreg is None:
        return games
    for view in (0,):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\GamingServices\PackageRepository\InstalledGames", 0, winreg.KEY_READ) as hk:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(hk, i)
                        i += 1
                        try:
                            with winreg.OpenKey(hk, sub) as sk:
                                v, _ = winreg.QueryValueEx(sk, "LocalPath") if True else ("", 0)
                                if v and os.path.isdir(v):
                                    games.append(_game(sub.split("\\")[-1], v, "Xbox / Microsoft"))
                        except OSError:
                            continue
                    except OSError:
                        break
        except OSError:
            pass
    return games


# --------------------------------------------------------------------------- #
#  Aggregation
# --------------------------------------------------------------------------- #
LAUNCHERS = ("Steam", "Epic Games", "Battle.net", "Ubisoft Connect",
             "EA App", "Riot Games", "GOG", "Xbox / Microsoft")


def _prune_noise(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in games if not is_noise_game(g.get("name", ""))]


def detect_games(stop=None, steam_limit: int = 60, other_limit: int = 40) -> dict[str, Any]:
    """Full inventory across launchers. Only REAL local evidence counts."""
    result: dict[str, Any] = {"launchers": {}, "total": 0}
    st = steam.detect_steam(stop=stop, measure_limit=steam_limit)
    steam_games = _prune_noise([g for lib in st["libraries"] for g in lib["games"]])
    _measure(steam_games, stop=stop, limit=steam_limit)  # already measured; idempotent
    result["launchers"]["Steam"] = steam_games

    ep = epic.detect_epic(stop=stop, measure_limit=other_limit)
    result["launchers"]["Epic Games"] = _prune_noise(ep["games"])

    for name, fn in (("Battle.net", _battle_net), ("Ubisoft Connect", _ubisoft),
                     ("EA App", _ea_app), ("Riot Games", _riot),
                     ("GOG", _gog), ("Xbox / Microsoft", _xbox)):
        try:
            games = _prune_noise(fn(stop=stop))
        except Exception:
            games = []
        _measure(games, stop=stop, limit=other_limit)
        result["launchers"][name] = games

    total = 0
    for lst in result["launchers"].values():
        total += sum(g.get("size") or 0 for g in lst)
    result["total"] = total
    result["steam_installed"] = st["installed"]
    result["steam_root"] = st.get("root")
    return result


def open_game_folder(game: dict[str, Any]) -> bool:
    path = game.get("path") or ""
    if path and os.path.isdir(path):
        try:
            if IS_WINDOWS:
                os.startfile(path)  # type: ignore[attr-defined]
                return True
        except OSError:
            pass
    return False
