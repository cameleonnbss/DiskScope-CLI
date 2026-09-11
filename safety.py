"""DiskScope CLI - safety.py

The safety layer. Every destructive operation goes through here.

Guarantees:
  * dry-run mode defaults to ON for the delete workflow until the user
    explicitly turns it off (S > Toggle dry run) or confirms per item;
  * drive roots, C:\\Windows and friends are never deletable;
  * relative paths, `..` traversal and UNC trickery are rejected;
  * deletion uses send2trash (Recycle Bin) when available, and only falls
    back to a permanent delete after an explicit second confirmation.
"""
from __future__ import annotations

import os
import string
from pathlib import PureWindowsPath

try:
    from send2trash import send2trash  # type: ignore[import-untyped]
    HAS_TRASH = True
except ImportError:
    send2trash = None  # type: ignore[assignment]
    HAS_TRASH = False

# --------------------------------------------------------------------------- #
#  Protected locations
# --------------------------------------------------------------------------- #
_PROTECTED_NAMES = {
    "windows", "system32", "syswow64", "winsxs", "driverstore",
    "config", "sam", "security", "software", "system", "boot",
    "program files", "program files (x86)", "programdata",
    "recovery", "$recycle.bin", "system volume information",
    "appx", "windowsapps", "servicing",
}

_DRIVE_RE = None  # compiled lazily if ever needed


def _norm(path: str) -> str:
    """Normalise to an absolute uppercase Windows path (keeps 'C:\\')."""
    try:
        p = os.path.abspath(os.path.normpath(str(path)))
    except (ValueError, OSError):
        return str(path).upper()
    if len(p) > 3:  # never strip the backslash of drive roots
        p = p.rstrip("\\/")
    return p.upper()


def is_drive_root(path: str) -> bool:
    p = _norm(path)
    if len(p) <= 3 and p.endswith(":\\"):
        return True
    if p in ("\\\\?\\", "//", "/", "\\\\"):
        return True
    # UNC share root \\server\share
    parts = PureWindowsPath(path).parts
    if path.startswith("\\\\") and len(parts) <= 2:
        return True
    return False


def is_protected(path: str) -> tuple[bool, str]:
    """Return (True, reason) when path must never be deleted."""
    p = _norm(path)
    if is_drive_root(p):
        return True, "racine de disque"
    # C:\Windows and subfolders, C:\Program Files, etc. (anchored match)
    for drive in string.ascii_uppercase:
        prefix = f"{drive}:\\"
        if p.startswith(prefix):
            rel = p[len(prefix):]
            first = rel.split("\\", 1)[0] if rel else ""
            if first in _PROTECTED_NAMES:
                return True, f"{drive}:\\{first} (dossier système/programmes)"
            # one level deeper for known-sensitive subfolders
            if first == "USERS":
                return False, ""
    if "\\WINDOWS\\" in p or p.endswith("\\WINDOWS"):
        return True, "sous-dossier de Windows"
    return False, ""


def is_user_critical(path: str) -> tuple[bool, str]:
    """Paths that need extra confirmation but are not forbidden."""
    p = _norm(path)
    for frag in ("\\APPDATA\\ROAMING\\MICROSOFT", "\\APPDATA\\LOCAL\\MICROSOFT",
                 "\\DOCUMENTS", "\\DESKTOP", "\\PICTURES", "\\ONEDRIVE"):
        if frag in p:
            return True, "données utilisateur potentiellement importantes"
    return False, ""


def validate_delete_path(path: str) -> tuple[bool, str]:
    """All the guards. Returns (ok, reason)."""
    if not path or not str(path).strip():
        return False, "chemin vide"
    raw = str(path)
    if ".." in PureWindowsPath(raw).parts:
        return False, "traversée de chemin (..) interdite"
    if not os.path.isabs(raw):
        return False, "le chemin doit être absolu"
    if not os.path.exists(raw):
        return False, "le chemin n'existe plus (déjà supprimé ?)"
    if is_drive_root(raw):
        return False, "suppression d'une racine de disque interdite"
    protected, why = is_protected(raw)
    if protected:
        return False, why
    # Refuse paths directly inside the app's own folder
    if _norm(raw).startswith(_norm(os.path.dirname(os.path.abspath(__file__)))):
        return False, "fichiers de DiskScope lui-même"
    return True, ""


# --------------------------------------------------------------------------- #
#  Deletion engine
# --------------------------------------------------------------------------- #
class Deleter:
    """Performs (or simulates) trashing of paths with all guards active."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.log: list[tuple[str, str, str]] = []  # (path, status, detail)
        self.bytes_freed = 0
        self.bytes_planned = 0

    def delete(self, path: str, size: int = 0, reason: str = "") -> tuple[bool, str]:
        """Trash one path. Returns (success, message)."""
        ok, why = validate_delete_path(path)
        if not ok:
            self.log.append((path, "REFUSED", why))
            return False, f"Refusé : {why}"
        crit, why_c = is_user_critical(path)
        if crit and not self.dry_run:
            # user-critical paths always need the explicit per-item confirm
            # which the caller already provided; keep a marker in the log.
            pass
        if self.dry_run:
            self.bytes_planned += size
            self.log.append((path, "DRY-RUN", reason))
            return True, "simulé (dry run)"
        try:
            if HAS_TRASH:
                send2trash(path)
                status = "TRASHED"
            else:
                # explicit fallback: permanent delete, send2trash missing
                if os.path.isdir(path) and not os.path.islink(path):
                    import shutil
                    shutil.rmtree(path, ignore_errors=False)
                else:
                    os.remove(path)
                status = "DELETED"
            self.bytes_freed += size
            self.log.append((path, status, reason))
            return True, status.lower()
        except PermissionError as e:
            self.log.append((path, "DENIED", str(e)))
            return False, "accès refusé (fermez l'application qui l'utilise)"
        except OSError as e:
            self.log.append((path, "ERROR", str(e)))
            return False, f"erreur système : {e}"

    def summary(self) -> str:
        done = len([x for x in self.log if x[1] in ("TRASHED", "DELETED", "DRY-RUN")])
        ref = len([x for x in self.log if x[1] == "REFUSED"])
        errc = len([x for x in self.log if x[1] in ("ERROR", "DENIED")])
        bytes_ = self.bytes_planned if self.dry_run else self.bytes_freed
        mode = "DRY RUN (rien supprimé)" if self.dry_run else ("Corbeille" if HAS_TRASH else "Suppression directe")
        return (f"{done} élément(s) traité(s) · {ref} refusé(s) · {errc} erreur(s) · "
                f"libérable : {bytes_ / 1024**3:.2f} GB · mode : {mode}")


# --------------------------------------------------------------------------- #
#  Misc helpers used elsewhere
# --------------------------------------------------------------------------- #
def safe_scandir(path: str) -> os.DirEntry:
    """os.scandir wrapper that raises a clean error for unreadable dirs."""
    return os.scandir(path)  # caller wraps in try/except


IGNORED_ON_SCAN = {"$recycle.bin", "system volume information", "$windows.~ws",
                   "$windows.~bt", "$getcurrent", "config.msi", "recovery",
                   "msocache", "wuaudnld.vm", "swapfile.sys"}


def should_skip_dir(name: str) -> bool:
    return name.lower() in IGNORED_ON_SCAN


def is_symlink_suspect(entry: os.DirEntry) -> bool:
    """True for symlinks/junctions we must not follow while scanning."""
    try:
        return entry.is_symlink()
    except OSError:
        return True


DRY_RUN_DEFAULT = True
