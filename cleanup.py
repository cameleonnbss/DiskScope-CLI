"""DiskScope CLI - cleanup.py

Potential-cleanup engine with three safety classes:

  SAFE    - temp files, identified caches, thumbnails, Recycle Bin...
            still never deleted without confirmation.
  REVIEW  - old archives/ISO/installers/builds that the user must judge.
  DANGER  - listed for transparency but never deletable (Windows, PF...).

Every recommendation carries: path, real size, age, reason, category.
Deletion itself always goes through safety.Deleter (guards + trash).
"""
from __future__ import annotations

import os
import time
from typing import Any

import files as files_mod
import scanner
import safety
import nativehelper
import i18n
import ui

HOME = os.path.expanduser("~")
LOCAL = os.environ.get("LOCALAPPDATA", os.path.join(HOME, r"AppData\Local"))
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, r"AppData\Roaming"))
WIN = os.environ.get("WINDIR", r"C:\Windows")

# --------------------------------------------------------------------------- #
#  Known SAFE targets (clearly identified caches / temp locations)
# --------------------------------------------------------------------------- #
SAFE_TARGETS: list[tuple[str, str]] = [
    # (path template, i18n reason key)
    (r"%LOCALAPPDATA%\Temp", "cl_r_usertemp"),
    (r"%WINDIR%\Temp", "cl_r_windtemp"),
    (r"%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db",
     "cl_r_thumb"),
    (r"%LOCALAPPDATA%\CrashDumps", "cl_r_crash"),
    (r"%LOCALAPPDATA%\D3DSCache", "cl_r_dx"),
    (r"%LOCALAPPDATA%\NVIDIA\DXCache", "cl_r_nvidia"),
    (r"%LOCALAPPDATA%\NVIDIA\GLCache", "cl_r_nvidia"),
    (r"%LOCALAPPDATA%\AMD\DxCache", "cl_r_amd"),
    (r"%LOCALAPPDATA%\AMD\DxcCache", "cl_r_amd"),
    (r"%LOCALAPPDATA%\IconCache.db", "cl_r_icon"),
    (r"%LOCALAPPDATA%\pip\cache", "cl_r_pip"),
    (r"%LOCALAPPDATA%\npm-cache", "cl_r_npm"),
    (r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache",
     "cl_r_chrome"),
    (r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache",
     "cl_r_edge"),
    (r"%APPDATA%\Mozilla\Firefox\Profiles\*\cache2", "cl_r_firefox"),
    (r"%WINDIR%\Prefetch", "cl_r_prefetch"),
    (r"%WINDIR%\SoftwareDistribution\Download", "cl_r_wu"),
    (r"%TEMP%", "cl_r_temp"),
]

REVIEW_MIN_AGE_DAYS = 90
REVIEW_MIN_SIZE = 10 * 1024 * 1024  # 10 MB minimum to be worth listing
EXPRESS_MIN_FILE_SIZE = 50 * 1024 * 1024  # 50 MB for the Downloads express list
IS_WINDOWS = os.name == "nt"


def _expand(p: str) -> str:
    return os.path.expandvars(p.replace("%WINDIR%", os.environ.get("WINDIR", r"C:\Windows")))


def _dir_stats(path: str, stop=None) -> tuple[int, int]:
    if os.path.isfile(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 0
    # Optional native accelerator (native/dufast.c) - faster sizing for the
    # cache/temp folders measured here. It is used only when a built binary is
    # present AND returns a positive size; otherwise we fall back to the Python
    # walker, so the reported number is never wrong because of the native path.
    nd = nativehelper.native_du(path)
    if nd:
        return nd
    return scanner.dir_size(path, stop=stop)


# --------------------------------------------------------------------------- #
#  SAFE items
# --------------------------------------------------------------------------- #
def find_safe_items(stop=None, max_items: int = 60) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for template, reason_key in SAFE_TARGETS:
        if stop is not None and stop.is_set():
            break
        reason = i18n.t(reason_key)
        base = _expand(template)
        if any(ch in base for ch in "*?["):
            import glob as _glob
            matches = _glob.glob(base)[:6]
        else:
            matches = [base] if os.path.exists(base) else []
        for m in matches:
            if not os.path.exists(m):
                continue
            mkey = os.path.normcase(os.path.normpath(os.path.realpath(m)))
            if mkey in seen:
                continue
            seen.add(mkey)
            if safety.path_crosses_reparse_point(m):
                continue
            ok, _why = safety.validate_delete_path(m)
            if not ok:
                continue  # protected -> never listed as SAFE
            size, nfiles = _dir_stats(m, stop=stop)
            if size <= 0:
                continue
            items.append({
                "path": m, "size": size, "files": nfiles,
                "reason": reason, "level": "SAFE", "age_days": 0,
                "category": "cache/temp",
            })
            if len(items) >= max_items:
                return items
    return items


# --------------------------------------------------------------------------- #
#  REVIEW items (from cached old-file candidates)
# --------------------------------------------------------------------------- #
def find_review_items(oldfiles: list[dict[str, Any]], stop=None,
                      limit: int = 80) -> list[dict[str, Any]]:
    now = time.time()
    out: list[dict[str, Any]] = []
    for f in oldfiles:
        if stop is not None and stop.is_set():
            break
        size = f.get("size", 0)
        mtime = f.get("mtime", 0)
        age_days = int((now - mtime) / 86400) if mtime else 0
        if size < REVIEW_MIN_SIZE or age_days < REVIEW_MIN_AGE_DAYS:
            continue
        path = f.get("path", "")
        # le cache peut dater d'avant le correctif jonctions : on re-teste
        # le chemin complet pour ne jamais proposer un doublon fantome
        if safety.path_crosses_reparse_point(path):
            continue
        ok, _why = safety.validate_delete_path(path)
        if not ok:
            continue
        cat = files_mod.classify_file(f)
        if cat == "other":
            continue
        out.append({
            "path": f["path"], "size": size, "files": 1,
            "reason": i18n.t("cl_old", cat=files_mod.category_label(cat),
                             d=age_days),
            "level": "REVIEW", "age_days": age_days, "category": cat,
        })
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x["size"], reverse=True)
    return out


# --------------------------------------------------------------------------- #
#  DANGER awareness (informational only - never actionable)
# --------------------------------------------------------------------------- #
DANGER_NOTE_KEYS = [
    "cl_danger1", "cl_danger2", "cl_danger3", "cl_danger4",
]


def danger_notes() -> list[str]:
    """Localized 'never deletable' transparency notes."""
    return [i18n.t(k) for k in DANGER_NOTE_KEYS]


def danger_summary(drives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sizes of protected zones, shown for transparency."""
    out: list[dict[str, Any]] = []
    for d in drives[:1]:  # system drive only, bounded
        for name, why_key in ((r"C:\Windows", "cl_sysfiles"),
                              (r"C:\Program Files", "cl_progs"),
                              (r"C:\Program Files (x86)", "cl_progs32")):
            if os.path.isdir(name):
                out.append({"path": name, "size": None, "reason": i18n.t(why_key),
                            "level": "DANGER", "note": i18n.t("cl_nodel")})
    return out


# --------------------------------------------------------------------------- #
#  Aggregation
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#  Express cleanup: Recycle Bin + Downloads junk
# --------------------------------------------------------------------------- #
def recycle_bins(drives: list[dict[str, Any]], stop=None) -> list[dict[str, Any]]:
    """Size of $Recycle.Bin on each fixed drive (informational + actionable)."""
    out: list[dict[str, Any]] = []
    for d in drives:
        if stop is not None and stop.is_set():
            break
        root = (d.get("mount") or "").rstrip("\\")
        rb = os.path.join(root + os.sep, "$Recycle.Bin") if root else ""
        if not rb or not os.path.isdir(rb):
            continue
        size, nfiles = scanner.dir_size(rb, stop=stop)
        if size > 0:
            out.append({"path": rb, "size": size, "files": nfiles,
                        "reason": i18n.t("cl_rb_of", root=root), "level": "SAFE",
                        "age_days": 0, "category": "recycle"})
    return out


def empty_recycle_bin(drive_mount: str = "") -> tuple[bool, str]:
    """Empty the Recycle Bin through the official Windows API.

    Returns (ok, message). The caller must confirm with the user first.
    """
    if not IS_WINDOWS:
        return False, i18n.t("cl_winreq")
    try:
        import ctypes
        from ctypes import wintypes
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        # ctypes.HRESULT only exists on Python 3.12+; fall back to the
        # signed 32-bit int it wraps so 3.10/3.11 keep working.
        shell32.SHEmptyRecycleBinW.restype = getattr(ctypes, "HRESULT", ctypes.c_long)
        flags = 0x1 | 0x2 | 0x4  # SHERB_NOCONFIRMATION | NOPROGRESSUI | NOSOUND
        root = (drive_mount or "").rstrip("\\") or None
        hr = shell32.SHEmptyRecycleBinW(ctypes.c_wchar_p(root) if root else None,
                                        flags)
        if hr == 0:
            return True, i18n.t("cl_emptied")
        if hr == -2147418113 or hr == 0x8000FFFF:  # E_UNEXPECTED = already empty
            return True, i18n.t("cl_already")
        return False, i18n.t("cl_werr", code=f"{hr & 0xFFFFFFFF:08X}")
    except Exception as e:  # noqa: BLE001
        return False, i18n.t("cl_err", err=f"{e.__class__.__name__}: {e}")


def find_express_items(cache: dict[str, Any], drives: list[dict[str, Any]],
                       stop=None, downloads_limit: int = 25) -> dict[str, Any]:
    """Assemble the express-cleanup bundle.

    Returns {"caches": [...], "recycle": [...], "downloads": [...]}
    All items pass safety.validate_delete_path; nothing here is auto-deleted.
    """
    caches = find_safe_items(stop=stop)
    recycle = recycle_bins(drives, stop=stop)
    # Downloads: recent-ish files big enough to matter, newest first
    downloads: list[dict[str, Any]] = []
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    now = time.time()
    if os.path.isdir(dl):
        candidates: list[dict[str, Any]] = []
        stack = [dl]
        while stack:
            if stop is not None and stop.is_set():
                break
            p = stack.pop()
            try:
                with os.scandir(p) as it:
                    for e in it:
                        try:
                            if e.is_symlink() or safety.is_reparse_entry(e):
                                continue
                            if e.is_dir(follow_symlinks=False):
                                if not safety.should_skip_dir(e.name):
                                    stack.append(e.path)
                            elif e.is_file(follow_symlinks=False):
                                st = e.stat(follow_symlinks=False)
                                if st.st_size >= EXPRESS_MIN_FILE_SIZE:
                                    candidates.append({
                                        "path": e.path, "size": st.st_size,
                                        "mtime": st.st_mtime,
                                        "ext": os.path.splitext(e.name)[1].lower(),
                                        "age_days": int((now - st.st_mtime) / 86400),
                                    })
                        except OSError:
                            continue
            except OSError:
                continue
            if len(candidates) > 4000:
                break
        candidates.sort(key=lambda x: x["size"], reverse=True)
        for c in candidates[:downloads_limit]:
            if safety.path_crosses_reparse_point(c["path"]):
                continue
            ok, _why = safety.validate_delete_path(c["path"])
            if ok:
                c["reason"] = i18n.t("cl_download")
                c["level"] = "REVIEW"
                c["files"] = 1
                downloads.append(c)
    return {"caches": caches, "recycle": recycle, "downloads": downloads}


# --------------------------------------------------------------------------- #
#  System advisories (big known space hogs; handled via commands, not deletion)
# --------------------------------------------------------------------------- #
def system_advisories(drives: list[dict[str, Any]], stop=None) -> list[dict[str, Any]]:
    """Detect big, officially-cleanable system artifacts.

    These are NOT trashable files: each carries the Windows command or
    settings path that handles it properly.
    """
    out: list[dict[str, Any]] = []
    windir = os.environ.get("WINDIR", r"C:\Windows")

    def _sz(p: str) -> int:
        if stop is not None and stop.is_set():
            return 0
        try:
            return os.path.getsize(p)
        except OSError:
            return 0

    # hiberfil.sys - hibernation file (powercfg handles it)
    for d in drives:
        mount = (d.get("mount") or "C:").rstrip(os.sep)
        hf = os.path.join(mount + os.sep, "hiberfil.sys")
        s = _sz(hf)
        if s > 1024**3:
            out.append({
                "name": i18n.t("cl_hib_name"), "size": s, "path": hf,
                "advice": i18n.t("cl_hib_adv"),
                "how": "cmd",
            })
        break

    # Windows.old - previous Windows install
    for d in drives:
        mount = (d.get("mount") or "C:").rstrip(os.sep)
        wo = os.path.join(mount + os.sep, "Windows.old")
        if os.path.isdir(wo):
            size, _n = scanner.dir_size(wo, stop=stop)
            if size > 0:
                out.append({
                    "name": i18n.t("cl_wold_name"), "size": size,
                    "path": wo,
                    "advice": i18n.t("cl_wold_adv"),
                    "how": "settings",
                })
        break

    # Delivery Optimization cache
    do_cache = os.path.join(windir, "SoftwareDistribution", "DeliveryOptimization")
    if os.path.isdir(do_cache):
        size, _n = scanner.dir_size(do_cache, stop=stop)
        if size > 500 * 1024**2:
            out.append({
                "name": i18n.t("cl_do_name"),
                "size": size, "path": do_cache,
                "advice": i18n.t("cl_do_adv"),
                "how": "settings",
            })

    # WinSxS cleanup hint (size survey only; DISM handles it)
    sxs = os.path.join(windir, "WinSxS")
    if os.path.isdir(sxs):
        size, _n = scanner.dir_size(sxs, stop=stop, max_files=60000)
        if size > 8 * 1024**3:
            out.append({
                "name": i18n.t("cl_sxs_name"), "size": size, "path": sxs,
                "advice": i18n.t("cl_sxs_adv"),
                "how": "cmd",
            })

    # Memory dump
    dump = os.path.join(windir, "MEMORY.DMP")
    s = _sz(dump)
    if s > 256 * 1024**2:
        out.append({
            "name": i18n.t("cl_dump_name"), "size": s, "path": dump,
            "advice": i18n.t("cl_dump_adv"),
            "how": "settings",
        })
    return out


def build_cleanup_report(cache: dict[str, Any], stop=None,
                         drives: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    safe = find_safe_items(stop=stop)
    review = find_review_items(cache.get("oldfiles", []), stop=stop, limit=300)
    safe_total = sum(x["size"] for x in safe)
    review_total = sum(x["size"] for x in review)
    advisories = system_advisories(drives or [], stop=stop) if drives else []
    return {
        "safe": safe,
        "review": review,
        "safe_total": safe_total,
        "review_total": review_total,
        "danger_notes": danger_notes(),
        "advisories": advisories,
    }
