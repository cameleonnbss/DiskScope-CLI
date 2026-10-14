/* dtk.h - DiskTop Core (native, C++).
 *
 * A small, dependency-free C++ engine that performs the low-level system
 * introspection DiskTop relies on: memory pressure, running processes,
 * volumes, services, autostart entries and fast directory sizing. Everything
 * here is deliberately *read-only* or *privilege-gated* and safe: it never
 * deletes a file and never force-kills a process on its own.
 *
 * The Python front-end (nativehelper.py / memory.py) treats this binary as a
 * pure accelerator: when `dtk` is missing or returns anything unexpected, the
 * app transparently falls back to its own stdlib (ctypes) implementation, so a
 * missing/failed native build can never break DiskTop.
 *
 * Cross-platform: Windows uses the Win32/PSAPI APIs; other platforms read from
 * /proc and statvfs so the same code compiles and runs under Linux/macOS too.
 */
#ifndef DISKTOP_CORE_H
#define DISKTOP_CORE_H

#include <cstdint>
#include <string>
#include <vector>
#include <cstdio>

namespace dtk {

/* One row of a process table, normalised across platforms. */
struct ProcInfo {
    long      pid = 0;
    std::string name;
    std::string user;
    uint64_t  rss_bytes = 0;   /* resident / working-set size */
    uint64_t  private_bytes = 0; /* private working set (Win) / anon (posix) */
    int       threads = 0;
    bool      is_background = false; /* no window / service-ish heuristic */
};

/* A memory snapshot of the whole machine. */
struct MemStat {
    uint64_t total = 0;
    uint64_t available = 0;
    uint64_t used = 0;
    uint64_t cached = 0;       /* standby (Win) / buff+cache (posix) */
    uint64_t commit_total = 0; /* page-charge style counter, 0 if N/A */
    double   load = 0.0;       /* 0..1 used fraction */
};

/* One mounted volume / drive. */
struct VolumeInfo {
    std::string mount;         /* "C:\\" or "/data" */
    std::string label;
    std::string fstype;
    uint64_t total = 0;
    uint64_t free_bytes = 0;
    uint64_t used = 0;
    bool     removable = false;
    bool     network = false;
};

/* A Windows service / POSIX unit stub. */
struct ServiceInfo {
    std::string name;
    std::string display;
    std::string state;         /* Running / Stopped / ... */
    std::string start_type;    /* Auto / Manual / Disabled */
};

/* An autostart entry (registry Run keys / Startup folder / XDG autostart). */
struct StartupItem {
    std::string source;        /* "Run", "RunOnce", "StartupFolder", ... */
    std::string name;
    std::string command;
    bool        enabled = true;
};

/* A directory-size result, matching the dufast wire format. */
struct DirSize {
    uint64_t bytes = 0;
    uint64_t files = 0;
    bool     ok = false;
};

/* ---- sub-command entry points. Each returns a process exit code. ---- */
int cmd_mem(const std::string &argv0);
int cmd_proc();
int cmd_disk();
int cmd_svc();
int cmd_startup();
int cmd_tmp(const std::string &path);
int cmd_trim();
int cmd_version();

/* ---- shared platform snapshots (implemented in proclist/meminfo) ---- */
std::vector<ProcInfo> snapshot_processes();
MemStat snapshot_mem();

/* ---- shared, tiny helpers implemented in dtk.cpp ---- */
/* Emit a string as a JSON string literal (with quotes) to stdout. */
void json_str(const char *s);
/* Human-readable byte count, e.g. 1.5 GB (used by the non-JSON tables). */
std::string human_bytes(uint64_t b);
/* Millisecond uptime-ish clock, monotonic, for the walk bound checks. */
uint64_t now_ms();
/* True if the caller asked for JSON output via -j/--json. */
extern bool g_json;

}  /* namespace dtk */

#endif /* DISKTOP_CORE_H */
