"""DiskTop - memory.py

RAM & background-process insight for the "what is eating my memory" view.

Two interchangeable back-ends provide the *same* normalized dictionaries:

  1. The optional native C++ core (`native/dtk.*`, see nativehelper.py) - fast,
     used whenever it was compiled and returns valid JSON.
  2. A pure-Python ctypes implementation that talks to the very same Win32 APIs
     (GlobalMemoryStatusEx / Toolhelp32 / PSAPI). It needs no compiler and no
     third-party package, so this menu works on every Windows machine out of the
     box. On non-Windows systems it degrades to /proc reads.

Nothing here kills a process or frees another program's memory. The only
"action" is `trim_working_set()`, which trims *this* process's own working set -
the safe, reversible "clean RAM" operation.
"""
from __future__ import annotations

import ctypes
import os
import sys
from typing import Any, Optional

import nativehelper

IS_WINDOWS = (os.name == "nt")


# --------------------------------------------------------------------------- #
#  Native (C++ core) path
# --------------------------------------------------------------------------- #
def _native_mem() -> Optional[dict[str, Any]]:
    d = nativehelper.dtk_run("mem")
    if not d or "total" not in d:
        return None
    return {
        "total": int(d.get("total", 0)),
        "available": int(d.get("available", 0)),
        "used": int(d.get("used", 0)),
        "load": float(d.get("load", 0.0)),
        "top": [{"pid": int(p.get("pid", 0)), "name": str(p.get("name", "")),
                 "rss": int(p.get("rss", 0))} for p in d.get("top", [])],
        "source": "native",
    }


def _native_procs() -> Optional[list[dict[str, Any]]]:
    d = nativehelper.dtk_run("proc")
    if not d or "processes" not in d:
        return None
    return [{"pid": int(p.get("pid", 0)), "name": str(p.get("name", "")),
             "rss": int(p.get("rss", 0)), "private": int(p.get("private", 0)),
             "threads": int(p.get("threads", 0))} for p in d.get("processes", [])]


def _native_startup() -> Optional[list[dict[str, Any]]]:
    d = nativehelper.dtk_run("startup")
    if not d or "items" not in d:
        return None
    return [{"source": str(i.get("source", "")), "name": str(i.get("name", "")),
             "command": str(i.get("command", ""))} for i in d.get("items", [])]


def _native_services() -> Optional[list[dict[str, Any]]]:
    d = nativehelper.dtk_run("svc")
    if not d or "services" not in d:
        return None
    return [{"name": str(s.get("name", "")), "display": str(s.get("display", "")),
             "state": str(s.get("state", ""))} for s in d.get("services", [])]


# --------------------------------------------------------------------------- #
#  Pure-Python ctypes fallback (Windows) - no compiler, no pip package needed.
# --------------------------------------------------------------------------- #
if IS_WINDOWS:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_uint32),
                    ("cntUsage", ctypes.c_uint32),
                    ("th32ProcessID", ctypes.c_uint32),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", ctypes.c_uint32),
                    ("cntThreads", ctypes.c_uint32),
                    ("th32ParentProcessID", ctypes.c_uint32),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_uint32),
                    ("szExeFile", ctypes.c_wchar * 260)]

    class PMCW(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32),
                    ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    _k32 = ctypes.windll.kernel32
    # K32GetProcessMemoryInfo lives in kernel32 on Vista+; fall back to psapi.
    try:
        _get_mem = _k32.K32GetProcessMemoryInfo
    except AttributeError:  # pragma: no cover - very old toolchains
        _get_mem = ctypes.windll.psapi.GetProcessMemoryInfo

    TH32CS_SNAPPROCESS = 0x2
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def _py_system_mem() -> dict[str, Any]:
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        total = avail = 0
        if _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
            total, avail = m.ullTotalPhys, m.ullAvailPhys
        used = max(0, total - avail)
        load = (used / total) if total else 0.0
        return {"total": total, "available": avail, "used": used, "load": load}

    def _py_procs() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE or snap == 0:
            return out
        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not _k32.Process32FirstW(snap, ctypes.byref(pe)):
                return out
            while True:
                pid = pe.th32ProcessID
                rss = priv = 0
                h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if h:
                    pmc = PMCW()
                    pmc.cb = ctypes.sizeof(PMCW)
                    if _get_mem(h, ctypes.byref(pmc), ctypes.sizeof(pmc)):
                        rss = int(pmc.WorkingSetSize)
                        priv = int(pmc.PagefileUsage)
                    _k32.CloseHandle(h)
                out.append({"pid": int(pid), "name": pe.szExeFile,
                            "rss": rss, "private": priv,
                            "threads": int(pe.cntThreads)})
                if not _k32.Process32NextW(snap, ctypes.byref(pe)):
                    break
        finally:
            _k32.CloseHandle(snap)
        return out
else:  # ------------------------------------------------------------- POSIX
    def _py_system_mem() -> dict[str, Any]:
        total = avail = 0
        try:
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1]) * 1024
        except OSError:
            pass
        used = max(0, total - avail)
        return {"total": total, "available": avail, "used": used,
                "load": (used / total) if total else 0.0}

    def _py_procs() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            entries = os.listdir("/proc")
        except OSError:
            return out
        for name in entries:
            if not name.isdigit():
                continue
            base = f"/proc/{name}"
            try:
                with open(f"{base}/status", encoding="utf-8", errors="ignore") as fh:
                    rss = comm = threads = 0
                    label = ""
                    for line in fh:
                        if line.startswith("Name:"):
                            label = line.split(":", 1)[1].strip()
                        elif line.startswith("VmRSS:"):
                            rss = int(line.split()[1]) * 1024
                        elif line.startswith("Threads:"):
                            threads = int(line.split()[1])
                out.append({"pid": int(name), "name": label, "rss": rss,
                            "private": rss, "threads": threads})
            except (OSError, ValueError):
                continue
        return out


# --------------------------------------------------------------------------- #
#  Public API - native first, Python fallback. Never raises.
# --------------------------------------------------------------------------- #
def system_mem() -> dict[str, Any]:
    return _native_mem() or {**_py_system_mem(), "source": "python"}


def top_processes(limit: int = 25) -> list[dict[str, Any]]:
    procs = _native_procs()
    if procs is None:
        procs = _py_procs()
    procs.sort(key=lambda p: p.get("rss", 0), reverse=True)
    return procs[:limit]


def autostart() -> Optional[list[dict[str, Any]]]:
    """Autostart entries; only the native core can read them. None otherwise."""
    return _native_startup()


def running_services() -> Optional[list[dict[str, Any]]]:
    svcs = _native_services()
    if svcs is None:
        return None
    return [s for s in svcs if s.get("state") == "Running"]


def native_active() -> bool:
    return nativehelper.dtk_available()


def trim_working_set() -> bool:
    """Return pages of *this process's* working set to the OS (safe, self-only)."""
    d = nativehelper.dtk_run("trim")
    if d is not None:
        return bool(d.get("trimmed"))
    if IS_WINDOWS:
        h = ctypes.c_void_p(-1)  # GetCurrentProcess pseudo-handle
        try:
            return bool(_k32.SetProcessWorkingSetSize(h, ctypes.c_size_t(-1),
                                                       ctypes.c_size_t(-1)))
        except Exception:  # noqa: BLE001 - best effort only
            return False
    return False
