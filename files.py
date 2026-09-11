"""DiskScope CLI - files.py

File-level analysis: big/old collectors' views, size/age filter DSL,
search across the cached tree, and a bounded duplicate-file finder.
"""
from __future__ import annotations

import collections
import hashlib
import os
import re
import threading
import time
from typing import Any

import safety

# --------------------------------------------------------------------------- #
#  Old-file categories
# --------------------------------------------------------------------------- #
CATEGORY_EXTS: dict[str, set[str]] = {
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "iso": {".iso", ".img", ".bin", ".mds", ".mdf", ".vhd", ".vhdx", ".nsp", ".xci"},
    "installers": {".exe", ".msi", ".msix", ".appx", ".msu"},
    "videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv"},
    "logs": {".log", ".etl", ".dmp", ".old"},
    "temp": {".tmp", ".temp", ".etl"},  # note: .etl in both, ok
}

CATEGORY_LABELS = {
    "archives": "archives anciennes",
    "iso": "images disque anciennes",
    "installers": "anciens installateurs",
    "videos": "anciennes vidéos",
    "logs": "anciens logs",
    "temp": "temporaires anciens",
    "downloads": "anciens téléchargements",
    "builds": "anciens builds",
    "other": "divers",
}

_INSTALLER_DIRS = ("downloads", "desktop", "documents")


def classify_file(item: dict[str, Any]) -> str:
    """Assign an old-file category from extension + location heuristics."""
    ext = (item.get("ext") or os.path.splitext(item.get("path", ""))[1]).lower()
    path = (item.get("path") or "").lower().replace("/", "\\")
    for cat, exts in CATEGORY_EXTS.items():
        if ext in exts:
            return cat
    if ext == ".exe":
        if any(f"\\{d}\\" in path for d in _INSTALLER_DIRS) or path.endswith(".exe"):
            return "installers"
    if "\\downloads\\" in path:
        return "downloads"
    if re.search(r"\\(build|dist|target|bin|obj|out)\\", path):
        return "builds"
    return "other"


# --------------------------------------------------------------------------- #
#  Size / age parsing  ("10GB", "500 Mo", "1.5 TB", "90d", "2 ans"...)
# --------------------------------------------------------------------------- #
_SIZE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(B|O|KO|KB|K|MO|MB|M|GO|GB|G|TO|TB|T)\s*$", re.I)
_AGE_RE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)\s*"
    r"(J|JOUR|JOURS|D|DAY|DAYS|SEM|SEMAINE|SEMAINES|W|WEEK|WEEKS|"
    r"MOIS|M|MONTH|MONTHS|AN|ANS|Y|YEAR|YEARS)\s*$", re.I)

_SIZE_MULT = {"B": 1, "O": 1, "K": 1024, "KO": 1024, "KB": 1024,
              "M": 1024**2, "MO": 1024**2, "MB": 1024**2,
              "G": 1024**3, "GO": 1024**3, "GB": 1024**3,
              "T": 1024**4, "TO": 1024**4, "TB": 1024**4}

_AGE_SECS = {"J": 86400, "JOUR": 86400, "JOURS": 86400, "D": 86400,
             "DAY": 86400, "DAYS": 86400,
             "SEM": 7 * 86400, "SEMAINE": 7 * 86400, "SEMAINES": 7 * 86400,
             "W": 7 * 86400, "WEEK": 7 * 86400, "WEEKS": 7 * 86400,
             "MOIS": 30 * 86400, "M": 30 * 86400,
             "MONTH": 30 * 86400, "MONTHS": 30 * 86400,
             "AN": 365 * 86400, "ANS": 365 * 86400,
             "Y": 365 * 86400, "YEAR": 365 * 86400, "YEARS": 365 * 86400}


def size_to_bytes(text: str) -> int | None:
    m = _SIZE_RE.match(text or "")
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", ".")) * _SIZE_MULT[m.group(2).upper()])
    except (ValueError, KeyError):
        return None


def age_to_seconds(text: str) -> float | None:
    m = _AGE_RE.match(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ".")) * _AGE_SECS[m.group(2).upper()]
    except (ValueError, KeyError):
        return None


def parse_filter_expr(expr: str) -> dict[str, Any]:
    """'size>10GB ext=.zip age>1year drive=D:' -> spec dict."""
    spec: dict[str, Any] = {}
    for tok in (expr or "").split():
        m = re.match(r"^(size|age)([<>]=?)(.+)$", tok, re.I)
        if m:
            key = m.group(1).lower()
            op = m.group(2)
            val_txt = m.group(3)
            if key == "size":
                val = size_to_bytes(val_txt)
            else:
                val = age_to_seconds(val_txt)
            if val is None:
                continue
            if op == ">":
                spec["min_" + key] = val
            elif op == ">=":
                spec["min_" + key] = val
                spec.setdefault("_ge", set()).add(key)
            elif op == "<":
                spec["max_" + key] = val
            elif op == "<=":
                spec["max_" + key] = val
            continue
        m = re.match(r"^ext=(\S+)$", tok, re.I)
        if m:
            spec["ext"] = m.group(1).lower().lstrip(".")
            continue
        m = re.match(r"^drive=([A-Za-z]:?)$", tok)
        if m:
            spec["drive"] = m.group(1).upper().rstrip(":") + ":"
            continue
        m = re.match(r"^type=(\S+)$", tok, re.I)
        if m:
            spec["type"] = m.group(1).lower()
            continue
    return spec


def spec_matches(item: dict[str, Any], spec: dict[str, Any]) -> bool:
    size = item.get("size", 0)
    mtime = item.get("mtime", 0)
    age = (time.time() - mtime) if mtime else 0
    if "min_size" in spec and size <= spec["min_size"]:
        return False
    if "max_size" in spec and size >= spec["max_size"]:
        return False
    if "min_age" in spec and age < spec["min_age"]:
        return False
    if "max_age" in spec and age > spec["max_age"]:
        return False
    if "ext" in spec and (item.get("ext") or "").lower().lstrip(".") != spec["ext"]:
        return strict_ext_ok(item, spec["ext"])
    if "drive" in spec:
        p = (item.get("path") or "")
        if not p.upper().startswith(spec["drive"]):
            return False
    if "type" in spec and classify_file(item) != spec["type"]:
        return False
    return True


def strict_ext_ok(item: dict[str, Any], want: str) -> bool:
    # extension comparison is exact; helper kept for clarity
    return (item.get("ext") or "").lower().lstrip(".") == want


def apply_filters(items: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [x for x in items if spec_matches(x, spec)]


def describe_spec(spec: dict[str, Any]) -> str:
    parts = []
    if "min_size" in spec:
        parts.append(f"taille > {spec['min_size'] / 1024**3:.4g} GB".replace(".0000", ""))
    if "max_size" in spec:
        parts.append(f"taille < {spec['max_size'] / 1024**3:.4g} GB".replace(".0000", ""))
    if "min_age" in spec:
        parts.append(f"âge > {spec['min_age'] / 86400:.0f} j")
    if "max_age" in spec:
        parts.append(f"âge < {spec['max_age'] / 86400:.0f} j")
    if "ext" in spec:
        parts.append(f"ext .{spec['ext']}")
    if "drive" in spec:
        parts.append(f"disque {spec['drive']}")
    if "type" in spec:
        parts.append(f"type {spec['type']}")
    return " · ".join(parts) if parts else "aucun"


def build_old_view(oldfiles: list[dict[str, Any]], min_age_days: int,
                   limit: int = 25) -> list[dict[str, Any]]:
    cutoff = time.time() - min_age_days * 86400
    sel = [f for f in oldfiles if f.get("mtime", 0) and f["mtime"] <= cutoff]
    sel.sort(key=lambda x: x["size"], reverse=True)
    return sel[:limit]


def old_summary_by_category(oldfiles: list[dict[str, Any]], min_age_days: int) -> list[tuple[str, int, int]]:
    cutoff = time.time() - min_age_days * 86400
    buckets: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for f in oldfiles:
        if f.get("mtime", 0) and f["mtime"] <= cutoff:
            cat = classify_file(f)
            buckets[cat][0] += 1
            buckets[cat][1] += f["size"]
    order = {"archives": 0, "iso": 1, "installers": 2, "downloads": 3,
             "videos": 4, "logs": 5, "temp": 6, "builds": 7, "other": 8}
    return sorted(((cat, n, sz) for cat, (n, sz) in buckets.items()),
                  key=lambda x: (order.get(x[0], 9), -x[2]))


# --------------------------------------------------------------------------- #
#  Command parsing for search ("/large 10GB", "/old 1year", "/files .iso"...)
# --------------------------------------------------------------------------- #
_CMD_RE = re.compile(r"^/(\w+)\s*(.*)$")


def parse_command(text: str) -> tuple[str, str]:
    m = _CMD_RE.match((text or "").strip())
    if not m:
        return "", text.strip()
    return m.group(1).lower(), m.group(2).strip()


# --------------------------------------------------------------------------- #
#  Search across the cached tree
# --------------------------------------------------------------------------- #
def _tree_search(node: dict[str, Any], term: str, out: list[dict[str, Any]],
                 limit: int) -> None:
    if len(out) >= limit:
        return
    name = (node.get("name") or "").lower()
    path = (node.get("path") or "")
    if term in name and not node.get("is_file"):
        out.append({"path": path, "size": node.get("size", 0),
                    "kind": "dir", "name": name})
    for ch in node.get("children") or []:
        _tree_search(ch, term, out, limit)


def search_all(term: str, cache: dict[str, Any], limit: int = 40
               ) -> dict[str, list[dict[str, Any]]]:
    """Search games, apps, files and folders by substring."""
    term = (term or "").strip().lower()
    out: dict[str, list[dict[str, Any]]] = {"games": [], "apps": [],
                                            "files": [], "dirs": []}
    if not term:
        return out

    games = (cache.get("games") or {}).get("launchers") or {}
    for _launcher, lst in games.items():
        for g in lst or []:
            if term in (g.get("name") or "").lower():
                out["games"].append(g)
    out["games"].sort(key=lambda g: g.get("size") or 0, reverse=True)
    out["games"] = out["games"][:10]

    for a in (cache.get("apps") or []):
        if term in (a.get("name") or "").lower():
            out["apps"].append(a)
    out["apps"].sort(key=lambda a: a.get("size") or 0, reverse=True)
    out["apps"] = out["apps"][:10]

    big = cache.get("bigfiles") or []
    out["files"] = [f for f in big if term in (f.get("path") or "").lower()][:15]

    for _mount, tree in (cache.get("trees") or {}).items():
        _tree_search(tree, term, out["dirs"], 10)
    return out


# --------------------------------------------------------------------------- #
#  Duplicate finder (bounded, content-hash verified)
# --------------------------------------------------------------------------- #
def find_duplicates(bigfiles: list[dict[str, Any]], stop=None,
                    min_size: int = 32 * 1024 * 1024,
                    max_groups: int = 15, max_hash_bytes_total: int = 512 * 1024 * 1024) -> dict[str, Any]:
    """Find duplicate files among the biggest cached files.

    Two passes: full size equality -> partial 64 KB head hash -> full hash.
    All hashes are streamed (64 KB chunks); a global byte budget bounds I/O.
    Nothing is ever deleted here - the view just reports groups.
    """
    by_size: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for f in bigfiles or []:
        if (f.get("size") or 0) >= min_size:
            by_size[f["size"]].append(f)

    groups: list[dict[str, Any]] = []
    hashed = 0

    def stream_hash(path: str, full: bool) -> str:
        h = hashlib.sha256()
        budget = -1 if full else 65536
        try:
            with open(path, "rb") as f:
                while budget != 0:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
                    if budget > 0:
                        budget -= len(chunk)
            return h.hexdigest()
        except OSError:
            return ""

    for size in sorted(by_size, reverse=True):
        if stop is not None and stop.is_set() or len(groups) >= max_groups:
            break
        cands = [f for f in by_size[size] if os.path.exists(f["path"])]
        if len(cands) < 2:
            continue
        # partial hash buckets
        buckets: dict[str, list[str]] = collections.defaultdict(list)
        for f in cands:
            if stop is not None and stop.is_set():
                break
            if hashed >= max_hash_bytes_total:
                break
            sig = stream_hash(f["path"], full=False)
            hashed += 65536
            if sig:
                buckets[sig].append(f["path"])
        for sig, paths in buckets.items():
            if len(paths) < 2:
                continue
            final: dict[str, list[str]] = collections.defaultdict(list)
            for p in paths:
                if stop is not None and stop.is_set() or hashed >= max_hash_bytes_total:
                    break
                fsig = stream_hash(p, full=True)
                hashed += size
                if fsig:
                    final[fsig].append(p)
            for _fsig, fpaths in final.items():
                if len(fpaths) >= 2:
                    groups.append({"size": size, "paths": fpaths,
                                   "wasted": size * (len(fpaths) - 1)})
                    if len(groups) >= max_groups:
                        break
        if len(groups) >= max_groups:
            break

    groups.sort(key=lambda g: g["wasted"], reverse=True)
    return {"groups": groups, "wasted_total": sum(g["wasted"] for g in groups),
            "hashed_bytes": hashed}
