/* trim.cpp - `dtk trim`: the only mutating native action, and it is scoped to
 * the calling process.
 *
 * On Windows it empties THIS process's working set with
 * SetProcessWorkingSetSize(-1, -1) - the classic "free RAM" trick used by
 * Task-Manager-style tools. Pages are simply returned to the standby list and
 * faulted back in transparently if needed, so it never loses data and touches
 * no other process. On POSIX there is no equivalent self-trim, so we report
 * that the operation is Windows-only and exit cleanly.
 */
#include "dtk.h"

#ifdef _WIN32
#include <windows.h>

namespace dtk {
int cmd_trim() {
    HANDLE h = GetCurrentProcess();
    /* (-1, -1) => reset to defaults, prompting the manager to trim the set. */
    BOOL ok = SetProcessWorkingSetSize(h, (SIZE_T)-1, (SIZE_T)-1);
    if (g_json) {
        std::printf("{\"trimmed\":%s}\n", ok ? "true" : "false");
    } else if (ok) {
        std::printf("working set trimmed for pid %lu\n",
                    (unsigned long)GetCurrentProcessId());
    } else {
        std::fprintf(stderr, "SetProcessWorkingSetSize failed (%lu)\n",
                     (unsigned long)GetLastError());
    }
    return ok ? 0 : 1;
}
}  /* namespace dtk */

#else
namespace dtk {
int cmd_trim() {
    if (g_json) std::printf("{\"trimmed\":false,\"reason\":\"windows-only\"}\n");
    else        std::printf("trim is Windows-only\n");
    return 0;
}
}  /* namespace dtk */
#endif
