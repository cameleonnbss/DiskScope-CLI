/* meminfo.cpp - system memory pressure + `dtk mem`.
 *
 * Produces the numbers behind DiskTop's "RAM & background" view: total,
 * available, used, a standby/cache figure and the top RAM consumers. The
 * "clean RAM" action DiskTop offers lives in trim.cpp and only ever trims the
 * calling process or asks the OS to drop its standby list (privilege-gated).
 */
#include "dtk.h"

#include <algorithm>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>

namespace dtk {
MemStat snapshot_mem() {
    MemStat m;
    MEMORYSTATUSEX ms{};
    ms.dwLength = sizeof(ms);
    if (GlobalMemoryStatusEx(&ms)) {
        m.total = ms.ullTotalPhys;
        m.available = ms.ullAvailPhys;
        m.used = (m.total > m.available) ? (m.total - m.available) : 0;
        m.load = m.total ? (double)m.used / (double)m.total : 0.0;
    }
    /* PERF_LIBRARY's performance counters are not exported by every SDK header
       set on MinGW, so commit-charge is approximated from GlobalMemoryStatus. */
    m.commit_total = ms.ullTotalPageFile;
    return m;
}
}  /* namespace dtk */

#else  /* ------------------------------ POSIX ------------------------------ */
#include <cstdio>
#include <cstring>

namespace dtk {
MemStat snapshot_mem() {
    MemStat m;
    FILE *f = std::fopen("/proc/meminfo", "rb");
    if (!f) return m;
    char line[256];
    unsigned long long total = 0, avail = 0, buffcache = 0, free_ = 0;
    while (std::fgets(line, sizeof(line), f)) {
        unsigned long long kb = 0;
        if (!std::strncmp(line, "MemTotal:", 9))       { std::sscanf(line + 9, "%llu", &kb); total = kb * 1024ULL; }
        else if (!std::strncmp(line, "MemAvailable:", 13)) { std::sscanf(line + 13, "%llu", &kb); avail = kb * 1024ULL; }
        else if (!std::strncmp(line, "MemFree:", 8))    { std::sscanf(line + 8, "%llu", &kb); free_ = kb * 1024ULL; }
        else if (!std::strncmp(line, "Buffers:", 8))    { std::sscanf(line + 8, "%llu", &kb); buffcache += kb * 1024ULL; }
        else if (!std::strncmp(line, "Cached:", 7))     { std::sscanf(line + 7, "%llu", &kb); buffcache += kb * 1024ULL; }
    }
    std::fclose(f);
    m.total = total;
    m.available = avail ? avail : free_;
    m.cached = buffcache;
    m.used = (total > m.available) ? (total - m.available) : 0;
    m.load = total ? (double)m.used / (double)total : 0.0;
    return m;
}
}  /* namespace dtk */

#endif  /* _WIN32 */

namespace dtk {

int cmd_mem(const std::string & /*argv0*/) {
    MemStat m = snapshot_mem();
    auto procs = snapshot_processes();
    std::sort(procs.begin(), procs.end(),
              [](const ProcInfo &a, const ProcInfo &b) {
                  return a.rss_bytes > b.rss_bytes;
              });
    const size_t TOP = 12;

    if (g_json) {
        std::printf("{\"total\":%llu,\"available\":%llu,\"used\":%llu,"
                    "\"cached\":%llu,\"load\":%.4f,\"top\":[",
                    (unsigned long long)m.total, (unsigned long long)m.available,
                    (unsigned long long)m.used, (unsigned long long)m.cached, m.load);
        for (size_t i = 0; i < procs.size() && i < TOP; ++i) {
            if (i) std::putchar(',');
            std::printf("{\"pid\":%ld,\"name\":", procs[i].pid);
            json_str(procs[i].name.c_str());
            std::printf(",\"rss\":%llu}", (unsigned long long)procs[i].rss_bytes);
        }
        std::printf("]}\n");
        return 0;
    }

    std::printf("Memory  total %s | used %s (%.0f%%) | available %s\n",
                human_bytes(m.total).c_str(), human_bytes(m.used).c_str(),
                m.load * 100.0, human_bytes(m.available).c_str());
    std::printf("\nTop RAM consumers:\n");
    for (size_t i = 0; i < procs.size() && i < TOP; ++i) {
        std::printf("  %-30.30s %10s  (pid %ld)\n", procs[i].name.c_str(),
                    human_bytes(procs[i].rss_bytes).c_str(), procs[i].pid);
    }
    return 0;
}

}  /* namespace dtk */
