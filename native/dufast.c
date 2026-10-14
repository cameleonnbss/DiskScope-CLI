/* dufast.c - optional native accelerator for DiskTop.
 *
 * Computes the total bytes + regular-file count of one directory (recursive),
 * never following symlinks/junctions. DiskTop uses it to size cache/temp
 * folders faster than the Python walker WHEN this binary is present; when it
 * is not, the Python scanner is used instead - so this is a pure optimization,
 * never a requirement.
 *
 * Output (stdout):  "<total_bytes> <file_count>\n"
 * Exit codes:       0 ok, 2 usage error.
 *
 * Build (MinGW / gcc / clang):   gcc -O2 -o dufast dufast.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/types.h>

#define MAX_NODES 5000000L   /* hard bound so a huge/cyclic tree never hangs us */

static long long g_bytes = 0;
static long long g_files = 0;
static long long g_nodes = 0;

#ifdef _WIN32
#include <io.h>
#include <direct.h>
/* findfirst/findnext attribute bits (FILE_ATTRIBUTE_*) */
#define ATTR_SUBDIR   0x10
#define ATTR_REPARSE  0x400

static void walk(const char *path) {
    char pattern[4096];
    char full[4096];
    struct _finddatai64_t fd;   /* .size is 64-bit -> handles files > 2 GB */
    intptr_t h;
    if (g_nodes++ > MAX_NODES) return;
    if ((size_t)snprintf(pattern, sizeof(pattern), "%s\\*", path) >= sizeof(pattern))
        return;
    h = _findfirsti64(pattern, &fd);
    if (h == -1) return;                         /* unreadable -> nothing counted */
    do {
        const char *name = fd.name;
        if (name[0] == '.' &&
            (name[1] == '\0' || (name[1] == '.' && name[2] == '\0'))) continue; /* . / .. */
        if (fd.attrib & ATTR_REPARSE) continue;  /* never follow junctions/symlinks */
        if ((size_t)snprintf(full, sizeof(full), "%s\\%s", path, name) >= sizeof(full))
            continue;
        if (fd.attrib & ATTR_SUBDIR) {
            walk(full);
        } else {
            g_bytes += (long long)fd.size;
            g_files += 1;
        }
        if (g_nodes > MAX_NODES) break;
    } while (_findnexti64(h, &fd) == 0);
    _findclose(h);
}

#else
#include <sys/stat.h>
#include <dirent.h>

static void walk(const char *path) {
    char full[4096];
    DIR *d;
    struct dirent *ent;
    struct stat st;
    if (g_nodes++ > MAX_NODES) return;
    d = opendir(path);
    if (!d) return;
    while ((ent = readdir(d)) != NULL) {
        const char *name = ent->d_name;
        if (name[0] == '.' &&
            (name[1] == '\0' || (name[1] == '.' && name[2] == '\0'))) continue;
        if (strlen(path) + strlen(name) + 2 > sizeof(full)) continue;
        snprintf(full, sizeof(full), "%s/%s", path, name);
        if (lstat(full, &st) != 0) continue;      /* lstat: do not follow symlinks */
        if (S_ISDIR(st.st_mode)) {
            walk(full);
        } else if (S_ISREG(st.st_mode)) {
            g_bytes += (long long)st.st_size;
            g_files += 1;
        }
        if (g_nodes > MAX_NODES) break;
    }
    closedir(d);
}
#endif

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: dufast <directory>\n");
        return 2;
    }
    walk(argv[1]);
    printf("%lld %lld\n", g_bytes, g_files);
    return 0;
}
