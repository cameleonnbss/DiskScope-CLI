/* diskstat.cpp - `dtk disk`: enumerate mounted volumes with free space.
 *
 * Mirrors drives.py (which uses ctypes) so the native path and the Python
 * fallback agree on the shape of the data. Everything here is read-only.
 */
#include "dtk.h"

#include <vector>

#ifdef _WIN32
#include <windows.h>

namespace dtk {
int cmd_disk() {
    std::vector<VolumeInfo> vols;
    wchar_t buf[512];
    DWORD n = GetLogicalDriveStringsW(sizeof(buf), buf);
    if (n > 0 && n < sizeof(buf) / sizeof(wchar_t)) {
        wchar_t *p = buf;
        while (*p) {
            VolumeInfo v;
            char mnt[16];
            WideCharToMultiByte(CP_UTF8, 0, p, -1, mnt, sizeof(mnt), nullptr, nullptr);
            v.mount = mnt;

            UINT type = GetDriveTypeW(p);
            v.removable = (type == DRIVE_REMOVABLE);
            v.network   = (type == DRIVE_REMOTE);

            ULARGE_INTEGER freeAvail, total, totalFree;
            if (GetDiskFreeSpaceExW(p, &freeAvail, &total, &totalFree)) {
                v.total = total.QuadPart;
                v.free_bytes = freeAvail.QuadPart;
                v.used = (v.total > v.free_bytes) ? (v.total - v.free_bytes) : 0;
            }
            wchar_t fs[128] = {0};
            if (GetVolumeInformationW(p, nullptr, 0, nullptr, nullptr, nullptr,
                                      fs, sizeof(fs) / sizeof(wchar_t))) {
                char fsu[128];
                WideCharToMultiByte(CP_UTF8, 0, fs, -1, fsu, sizeof(fsu), nullptr, nullptr);
                v.fstype = fsu;
            }
            vols.push_back(std::move(v));
            p += wcslen(p) + 1;
        }
    }

    if (g_json) {
        std::printf("{\"volumes\":[");
        for (size_t i = 0; i < vols.size(); ++i) {
            const VolumeInfo &v = vols[i];
            if (i) std::putchar(',');
            std::printf("{\"mount\":"); json_str(v.mount.c_str());
            std::printf(",\"fstype\":"); json_str(v.fstype.c_str());
            std::printf(",\"total\":%llu,\"free\":%llu,\"used\":%llu,"
                        "\"removable\":%s,\"network\":%s}",
                        (unsigned long long)v.total, (unsigned long long)v.free_bytes,
                        (unsigned long long)v.used,
                        v.removable ? "true" : "false", v.network ? "true" : "false");
        }
        std::printf("]}\n");
        return 0;
    }
    for (const VolumeInfo &v : vols)
        std::printf("%-6s %-10s total %12s free %12s\n", v.mount.c_str(),
                    v.fstype.c_str(), human_bytes(v.total).c_str(),
                    human_bytes(v.free_bytes).c_str());
    return 0;
}
}  /* namespace dtk */

#else  /* ------------------------------ POSIX ------------------------------ */
#include <sys/statvfs.h>
#include <cstdio>
#include <cstring>

namespace dtk {
int cmd_disk() {
    FILE *f = std::fopen("/proc/mounts", "rb");
    std::vector<VolumeInfo> vols;
    if (f) {
        char dev[512], mnt[512], fs[64];
        while (std::fscanf(f, "%511s %511s %63s", dev, mnt, fs) == 3) {
            /* Drain the rest of the line. */
            int c; while ((c = std::fgetc(f)) != '\n' && c != EOF) {}
            if (mnt[0] != '/') continue;
            struct statvfs sv;
            if (statvfs(mnt, &sv) != 0) continue;
            uint64_t total = (uint64_t)sv.f_blocks * sv.f_frsize;
            if (total == 0) continue;               /* skip pseudo filesystems */
            VolumeInfo v;
            v.mount = mnt; v.fstype = fs;
            v.total = total;
            v.free_bytes = (uint64_t)sv.f_bavail * sv.f_frsize;
            v.used = total - (uint64_t)sv.f_bfree * sv.f_frsize;
            vols.push_back(std::move(v));
        }
        std::fclose(f);
    }
    if (g_json) {
        std::printf("{\"volumes\":[");
        for (size_t i = 0; i < vols.size(); ++i) {
            const VolumeInfo &v = vols[i];
            if (i) std::putchar(',');
            std::printf("{\"mount\":"); json_str(v.mount.c_str());
            std::printf(",\"fstype\":"); json_str(v.fstype.c_str());
            std::printf(",\"total\":%llu,\"free\":%llu,\"used\":%llu}",
                        (unsigned long long)v.total, (unsigned long long)v.free_bytes,
                        (unsigned long long)v.used);
        }
        std::printf("]}\n");
        return 0;
    }
    for (const VolumeInfo &v : vols)
        std::printf("%-20s %-10s total %12s free %12s\n", v.mount.c_str(),
                    v.fstype.c_str(), human_bytes(v.total).c_str(),
                    human_bytes(v.free_bytes).c_str());
    return 0;
}
}  /* namespace dtk */

#endif  /* _WIN32 */
