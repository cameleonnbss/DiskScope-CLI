/* dtk.cpp - DiskTop Core: command dispatcher + shared helpers.
 *
 * `dtk` is the single native binary that exposes the low-level toolkit used by
 * DiskTop. It is intentionally tiny, allocation-light and side-effect-free:
 *
 *   dtk version            print native core version + build info
 *   dtk mem    [-j]        system memory pressure (JSON with -j)
 *   dtk proc   [-j]        running processes sorted by RAM
 *   dtk disk   [-j]        volumes and free space
 *   dtk svc                Windows services (Running/Stopped)
 *   dtk startup            autostart entries (Run keys, startup folders)
 *   dtk tmp <dir>          fast recursive size of a directory
 *   dtk trim               trim THIS process working set (safe, self-only)
 *
 * The Python layer always calls these with -j and parses JSON; on any parse
 * failure it falls back to its own ctypes implementation.
 */
#include "dtk.h"

#include <cstring>
#include <chrono>
#include <algorithm>

namespace dtk {

bool g_json = false;

void json_str(const char *s) {
    std::putchar('"');
    for (const unsigned char *p = reinterpret_cast<const unsigned char *>(s); *p; ++p) {
        unsigned char c = *p;
        switch (c) {
            case '"':  std::fputs("\\\"", stdout); break;
            case '\\': std::fputs("\\\\", stdout); break;
            case '\b': std::fputs("\\b", stdout);  break;
            case '\f': std::fputs("\\f", stdout);  break;
            case '\n': std::fputs("\\n", stdout);  break;
            case '\r': std::fputs("\\r", stdout);  break;
            case '\t': std::fputs("\\t", stdout);  break;
            default:
                if (c < 0x20) {
                    std::printf("\\u%04x", c);
                } else {
                    std::putchar(c);
                }
        }
    }
    std::putchar('"');
}

std::string human_bytes(uint64_t b) {
    static const char *units[] = {"B", "KB", "MB", "GB", "TB", "PB"};
    double v = static_cast<double>(b);
    int u = 0;
    while (v >= 1024.0 && u < 5) { v /= 1024.0; ++u; }
    char buf[48];
    if (u == 0) std::snprintf(buf, sizeof(buf), "%llu B", (unsigned long long)b);
    else        std::snprintf(buf, sizeof(buf), "%.2f %s", v, units[u]);
    return std::string(buf);
}

uint64_t now_ms() {
    using namespace std::chrono;
    return static_cast<uint64_t>(
        duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count());
}

}  /* namespace dtk */

/* Simple argument model: subcommand is argv[1]; -j/--json toggles output. */
int main(int argc, char **argv) {
    using namespace dtk;
    if (argc < 2) {
        std::fprintf(stderr,
            "DiskTop Core (dtk)\n"
            "usage: dtk <version|mem|proc|disk|svc|startup|tmp|trim> [-j] [path]\n");
        return 2;
    }
    /* Scan trailing args for the JSON flag so it works before or after the verb. */
    std::string verb = argv[1];
    std::string path;
    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "-j" || a == "--json") g_json = true;
        else if (!path.empty() || verb != "tmp") { /* ignore extras */ }
        if (verb == "tmp" && a[0] != '-') path = a;
    }

    if (verb == "version") return cmd_version();
    if (verb == "mem")     return cmd_mem(argv[0]);
    if (verb == "proc")    return cmd_proc();
    if (verb == "disk")    return cmd_disk();
    if (verb == "svc")     return cmd_svc();
    if (verb == "startup") return cmd_startup();
    if (verb == "trim")    return cmd_trim();
    if (verb == "tmp")     return cmd_tmp(path);

    std::fprintf(stderr, "dtk: unknown command '%s'\n", verb.c_str());
    return 2;
}
