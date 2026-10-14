/* tmpscan.cpp - `dtk tmp <dir>`: fast recursive directory size.
 *
 * A modern C++/Win32 port of dufast.c: it totals bytes and regular-file counts
 * without ever following a symlink/junction (reparse points), and hard-bounds
 * the node count so a pathological tree cannot hang the caller. DiskTop uses
 * it to size cache/temp folders; if it fails, cleanup.py sizes them in Python.
 */
#include "dtk.h"

#include <string>

static const long long MAX_NODES = 5000000LL;

#ifdef _WIN32
#include <windows.h>

namespace dtk {
static void walkW(const wchar_t *path, long long &bytes, long long &files,
                  long long &nodes) {
    if (nodes++ > MAX_NODES) return;
    wchar_t pattern[MAX_PATH * 2];
    if (wsprintfW(pattern, L"%s\\*", path) >= (int)sizeof(pattern) / 2 - 2)
        return;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.cFileName[0] == L'.' &&
            (fd.cFileName[1] == 0 || (fd.cFileName[1] == L'.' && fd.cFileName[2] == 0)))
            continue;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) continue;
        wchar_t full[MAX_PATH * 2];
        if (wsprintfW(full, L"%s\\%s", path, fd.cFileName) >= (int)sizeof(full) / 2 - 2)
            continue;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            walkW(full, bytes, files, nodes);
        } else {
            ULARGE_INTEGER sz;
            sz.LowPart = fd.nFileSizeLow;
            sz.HighPart = fd.nFileSizeHigh;
            bytes += (long long)sz.QuadPart;
            files += 1;
        }
        if (nodes > MAX_NODES) break;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

int cmd_tmp(const std::string &path) {
    if (path.empty()) { std::fprintf(stderr, "usage: dtk tmp <dir>\n"); return 2; }
    /* std::string here is UTF-8 (argv); widen for the Unicode Win32 walk. */
    int wlen = MultiByteToWideChar(CP_UTF8, 0, path.c_str(), -1, nullptr, 0);
    if (wlen <= 0) return 2;
    std::wstring w(wlen, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, path.c_str(), -1, &w[0], wlen);

    long long bytes = 0, files = 0, nodes = 0;
    walkW(w.c_str(), bytes, files, nodes);
    if (g_json) std::printf("{\"bytes\":%lld,\"files\":%lld,\"ok\":true}\n", bytes, files);
    else        std::printf("%lld %lld\n", bytes, files);
    return 0;
}
}  /* namespace dtk */

#else  /* ------------------------------ POSIX ------------------------------ */
#include <sys/stat.h>
#include <dirent.h>
#include <cstring>

namespace dtk {
static void walk(const char *path, long long &bytes, long long &files,
                 long long &nodes) {
    if (nodes++ > MAX_NODES) return;
    DIR *d = opendir(path);
    if (!d) return;
    struct dirent *ent;
    struct stat st;
    char full[4096];
    while ((ent = readdir(d)) != nullptr) {
        const char *name = ent->d_name;
        if (name[0] == '.' &&
            (name[1] == 0 || (name[1] == '.' && name[2] == 0))) continue;
        if (std::strlen(path) + std::strlen(name) + 2 > sizeof(full)) continue;
        std::snprintf(full, sizeof(full), "%s/%s", path, name);
        if (lstat(full, &st) != 0) continue;
        if (S_ISDIR(st.st_mode)) walk(full, bytes, files, nodes);
        else if (S_ISREG(st.st_mode)) { bytes += (long long)st.st_size; files += 1; }
        if (nodes > MAX_NODES) break;
    }
    closedir(d);
}

int cmd_tmp(const std::string &path) {
    if (path.empty()) { std::fprintf(stderr, "usage: dtk tmp <dir>\n"); return 2; }
    long long bytes = 0, files = 0, nodes = 0;
    walk(path.c_str(), bytes, files, nodes);
    if (g_json) std::printf("{\"bytes\":%lld,\"files\":%lld,\"ok\":true}\n", bytes, files);
    else        std::printf("%lld %lld\n", bytes, files);
    return 0;
}
}  /* namespace dtk */

#endif  /* _WIN32 */
