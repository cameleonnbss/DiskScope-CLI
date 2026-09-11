"""DiskScope CLI - cache.py

Persistent scan cache so re-entering menus doesn't rescan the whole disk.

Contents:
  * DriveStatsSnapshot : per-drive totals + top folders
  * DirNode trees      : sizes/files/children per scanned folder
  * BigFiles           : top N biggest files
  * OldFiles           : candidate old files (bounded)
  * Apps / Games       : registries & manifests
  * meta               : timing + counters, displayed as "Last scan"

Storage: a single JSON file in %LOCALAPPDATA%\\DiskScope\\cache.json,
written atomically (tmp + os.replace). Corrupted caches are discarded.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from typing import Any

CACHE_VERSION = 3
MAX_AGE_SECONDS = 30 * 60          # considered stale after 30 min
MAX_ITEMS = 60_000                  # hard cap of cached entries per list


def cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "DiskScope")
    os.makedirs(d, exist_ok=True)
    return d


def cache_file() -> str:
    return os.path.join(cache_dir(), "cache.json")


_lock = threading.RLock()


def load() -> dict[str, Any]:
    """Load the cache, or an empty structure. Never raises."""
    with _lock:
        try:
            with open(cache_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != CACHE_VERSION:
                return _empty()
            return data
        except (OSError, ValueError, KeyError):
            return _empty()


def _empty() -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "created": time.time(),
        "meta": {},
        "drives": {},          # "C:" -> totals dict
        "top_folders": {},     # "C:" -> [ {name,size,path} ]
        "trees": {},           # "C:" -> DirNode dict
        "bigfiles": [],        # [ {path,size,mtime,ext,drive} ]
        "oldfiles": [],        # same shape, filtered
        "apps": [],
        "games": [],
        "cleanup": {},         # {"safe": n, "review": n, "danger_note": ...}
        "history": [],         # [ {ts, drives: {"C:": used_bytes}} ] max 30
    }


def push_history(data: dict[str, Any], drives: dict[str, int]) -> None:
    """Record one {timestamp -> per-drive used bytes} point, keeping 30."""
    import time as _t
    pts = data.setdefault("history", [])
    pts.append({"ts": _t.time(), "drives": dict(drives)})
    if len(pts) > 30:
        del pts[:len(pts) - 30]


def save(data: dict[str, Any]) -> None:
    """Atomically persist the cache. Best-effort; failures are silent."""
    with _lock:
        data["version"] = CACHE_VERSION
        data["created"] = time.time()
        # bounded lists to keep the file small
        for key in ("bigfiles", "oldfiles"):
            if len(data.get(key, [])) > MAX_ITEMS:
                data[key] = data[key][:MAX_ITEMS]
        tmp = cache_file() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, cache_file())
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def clear() -> None:
    with _lock:
        try:
            os.unlink(cache_file())
        except OSError:
            pass


def is_fresh(data: dict[str, Any], max_age: int = MAX_AGE_SECONDS) -> bool:
    meta = data.get("meta") or {}
    fin = meta.get("finished", 0)
    return bool(fin) and (time.time() - fin) < max_age


def clone(data: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(data)


def update_meta(data: dict[str, Any], **kw: Any) -> None:
    meta = data.setdefault("meta", {})
    meta.update(kw)
    meta["finished"] = time.time()
