"""Windows Recycle Bin deletion that works on accented / Unicode paths.

The stock ``send2trash`` library fails on profile paths containing non-ASCII
characters (e.g. ``C:\\Users\\caméléon``): it converts the path to a short
8.3 name (``CAMLON~1``), drops the accent, and raises ``FileNotFoundError``.
We call the Windows Shell directly through ctypes (``SHFileOperationW``), which
accepts the real Unicode path, so deletion works everywhere.

Pure stdlib + ctypes — no third-party dependency required on Windows.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

try:
    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    _HAS_SHELL = True
except Exception:  # noqa: BLE001
    shell32 = None
    _HAS_SHELL = False

# SHFILEOPSTRUCTW flags
FOF_ALLOWUNDO = 0x40        # send to Recycle Bin instead of deleting
FOF_NOCONFIRMATION = 0x10   # no "are you sure?" prompt
FOF_NOERRORUI = 0x0400      # no error dialog
FOF_SILENT = 0x0004         # no progress UI
FO_DELETE = 0x0003


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.UINT),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def send_to_trash(path: str) -> tuple[bool, str]:
    """Move a single file or directory to the Recycle Bin.

    Returns ``(ok, message)``.

    ``SHFileOperationW``'s numeric return code is unreliable when the path
    shim is involved, so we ignore it and instead verify the path is actually
    gone afterwards — that is the only signal that matters.
    """
    if not _HAS_SHELL:
        return False, "Windows shell unavailable"
    if not path:
        return False, "empty path"
    if not os.path.lexists(path):
        return False, "path does not exist"

    # Double-null terminated wide string as required by pFrom.
    buf = ctypes.create_unicode_buffer(str(path) + "\0")
    struc = SHFILEOPSTRUCTW()
    struc.hwnd = 0
    struc.wFunc = FO_DELETE
    struc.pFrom = buf
    struc.pTo = None
    struc.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    struc.fAnyOperationsAborted = 0
    struc.hNameMappings = None
    struc.lpszProgressTitle = None
    try:
        shell32.SHFileOperationW(ctypes.byref(struc))
    except Exception as e:  # noqa: BLE001
        return False, f"shell error: {e}"

    if not os.path.lexists(path):
        return True, "recycled"
    return False, "failed (file still present)"


def empty_recycle_bin(drive: str = "") -> tuple[bool, str]:
    """Empty the Recycle Bin through the official Windows API.

    Returns ``(ok, message)``. The caller must confirm with the user first.
    """
    if not _HAS_SHELL:
        return False, "Windows shell unavailable"
    shell32.SHEmptyRecycleBinW.restype = ctypes.HRESULT
    shell32.SHEmptyRecycleBinW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
    flags = 0x1 | 0x2 | 0x4  # NOCONFIRMATION | NOPROGRESSUI | NOSOUND
    root = (drive.rstrip("\\") if drive else None)
    try:
        hr = shell32.SHEmptyRecycleBinW(0, root, flags)
    except Exception as e:  # noqa: BLE001
        return False, f"error: {e}"
    if hr == 0:
        return True, "Recycle Bin emptied"
    if hr in (-2147418113, 0x8000FFFF, 1):  # E_UNEXPECTED / already empty
        return True, "Recycle Bin already empty"
    return False, f"Windows error 0x{hr & 0xFFFFFFFF:08X}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--empty":
        print(empty_recycle_bin()[1])
    elif len(sys.argv) > 1:
        print(send_to_trash(sys.argv[1]))
