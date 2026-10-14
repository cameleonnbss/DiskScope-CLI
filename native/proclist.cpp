/* proclist.cpp - running-process snapshot + `dtk proc`.
 *
 * Enumerates every live process with its RAM footprint and thread count,
 * sorted largest first. This is the shared back-end used by both `proc` and
 * the top-consumers part of `mem`. Nothing here opens a handle with write
 * access: processes are only *queried*, never touched.
 */
#include "dtk.h"

#include <algorithm>
#include <string>
#include <vector>

#ifdef _WIN32
#ifndef WINVER
#define WINVER 0x0601
#endif
#include <windows.h>
#include <tlhelp32.h>
#include <psapi.h>

/* Query one process for its memory counters; false if access is denied. */
static bool query_proc_mem(HANDLE h, uint64_t &ws, uint64_t &priv) {
    PROCESS_MEMORY_COUNTERS_EX pmc{};
    pmc.cb = sizeof(pmc);
    if (!GetProcessMemoryInfo(h, reinterpret_cast<PROCESS_MEMORY_COUNTERS *>(&pmc),
                              sizeof(pmc)))
        return false;
    ws   = pmc.WorkingSetSize;
    priv = pmc.PrivateUsage;   /* pagefile-backed private bytes */
    return true;
}

namespace dtk {
std::vector<ProcInfo> snapshot_processes() {
    std::vector<ProcInfo> out;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return out;

    PROCESSENTRY32W pe{};
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            ProcInfo p;
            p.pid = static_cast<long>(pe.th32ProcessID);
            p.threads = static_cast<int>(pe.cntThreads);
            /* Convert the wide exe name to UTF-8 for a stable JSON string. */
            char buf[512];
            int n = WideCharToMultiByte(CP_UTF8, 0, pe.szExeFile, -1,
                                        buf, sizeof(buf), nullptr, nullptr);
            p.name = (n > 0) ? std::string(buf) : std::string("process");
            /* Query limited info; system processes may deny - that is fine. */
            HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                                   pe.th32ProcessID);
            if (h) {
                query_proc_mem(h, p.rss_bytes, p.private_bytes);
                CloseHandle(h);
            }
            out.push_back(std::move(p));
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return out;
}
}  /* namespace dtk */

#else  /* ------------------------------ POSIX ------------------------------ */
#include <dirent.h>
#include <cstdio>
#include <cstring>
#include <unistd.h>

namespace dtk {

/* Read one line of a /proc/<pid>/... pseudo-file. */
static std::string read_first_line(const std::string &path) {
    FILE *f = std::fopen(path.c_str(), "rb");
    if (!f) return {};
    char line[1024];
    std::string s;
    if (std::fgets(line, sizeof(line), f)) s = line;
    std::fclose(f);
    while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
    return s;
}

std::vector<ProcInfo> snapshot_processes() {
    std::vector<ProcInfo> out;
    DIR *d = opendir("/proc");
    if (!d) return out;
    const long page = sysconf(_SC_PAGESIZE);
    struct dirent *ent;
    while ((ent = readdir(d)) != nullptr) {
        /* Only numeric entries are processes. */
        bool numeric = true;
        for (const char *c = ent->d_name; *c; ++c)
            if (*c < '0' || *c > '9') { numeric = false; break; }
        if (!numeric) continue;

        ProcInfo p;
        p.pid = std::atol(ent->d_name);
        std::string base = std::string("/proc/") + ent->d_name;

        /* /proc/<pid>/stat: field 2 is comm, field 20 is num_threads. */
        std::string stat = read_first_line(base + "/stat");
        size_t lp = stat.find('(');
        size_t rp = stat.rfind(')');
        if (lp != std::string::npos && rp != std::string::npos && rp > lp)
            p.name = stat.substr(lp + 1, rp - lp - 1);
        if (rp != std::string::npos) {
            /* tokens after the ') ' close: state(3) ... num_threads is the 18th
               field counting from comm, i.e. index 17 of the tail split. */
            std::string tail = stat.substr(rp + 2);
            std::vector<std::string> tok;
            size_t i = 0;
            while (i < tail.size()) {
                size_t sp = tail.find(' ', i);
                if (sp == std::string::npos) sp = tail.size();
                tok.push_back(tail.substr(i, sp - i));
                i = sp + 1;
            }
            if (tok.size() > 17) p.threads = std::atoi(tok[17].c_str());
        }

        /* /proc/<pid>/status: VmRSS and VmSize are in kB. */
        FILE *st = std::fopen((base + "/status").c_str(), "rb");
        if (st) {
            char line[256];
            while (std::fgets(line, sizeof(line), st)) {
                if (!std::strncmp(line, "VmRSS:", 6))
                    p.rss_bytes = std::strtoull(line + 6, nullptr, 10) * 1024ULL;
                else if (!std::strncmp(line, "VmPriv:", 7))
                    p.private_bytes = std::strtoull(line + 7, nullptr, 10) * 1024ULL;
            }
            std::fclose(st);
        }
        if (p.private_bytes == 0) p.private_bytes = p.rss_bytes;
        (void)page;
        out.push_back(std::move(p));
    }
    closedir(d);
    return out;
}
}  /* namespace dtk */

#endif  /* _WIN32 */

namespace dtk {

/* Sort helper: biggest resident memory first. */
static void sort_by_ram(std::vector<ProcInfo> &v) {
    std::sort(v.begin(), v.end(), [](const ProcInfo &a, const ProcInfo &b) {
        return a.rss_bytes > b.rss_bytes;
    });
}

int cmd_proc() {
    auto procs = snapshot_processes();
    sort_by_ram(procs);

    if (g_json) {
        std::printf("{\"count\":%zu,\"processes\":[", procs.size());
        for (size_t i = 0; i < procs.size(); ++i) {
            const ProcInfo &p = procs[i];
            if (i) std::putchar(',');
            std::printf("{\"pid\":%ld,\"name\":", p.pid); json_str(p.name.c_str());
            std::printf(",\"rss\":%llu,\"private\":%llu,\"threads\":%d}",
                        (unsigned long long)p.rss_bytes,
                        (unsigned long long)p.private_bytes, p.threads);
        }
        std::printf("]}\n");
        return 0;
    }

    std::printf("%-8s %-30s %12s %8s\n", "PID", "NAME", "RSS", "THREADS");
    for (const ProcInfo &p : procs) {
        std::printf("%-8ld %-30.30s %12s %8d\n", p.pid, p.name.c_str(),
                    human_bytes(p.rss_bytes).c_str(), p.threads);
    }
    std::printf("\n%zu process(es)\n", procs.size());
    return 0;
}

}  /* namespace dtk */
