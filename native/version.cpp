/* version.cpp - dtk version / build banner. */
#include "dtk.h"

namespace dtk {
/* Keep this in sync with ui.APP_VERSION; it is the native core's own stamp. */
static const char *DTK_VERSION = "2.4.0";
}

int dtk::cmd_version() {
    std::printf("{");
    std::printf("\"name\":\"DiskTop Core\",");
    std::printf("\"version\":"); json_str(DTK_VERSION); std::printf(",");
#if defined(_WIN32)
    std::printf("\"platform\":\"windows\",");
#elif defined(__APPLE__)
    std::printf("\"platform\":\"macos\",");
#elif defined(__linux__)
    std::printf("\"platform\":\"linux\",");
#else
    std::printf("\"platform\":\"other\",");
#endif
    std::printf("\"compiler\":\"");
#if defined(__GNUC__)
    std::printf("gcc %d.%d", __GNUC__, __GNUC_MINOR__);
#elif defined(_MSC_VER)
    std::printf("msvc");
#else
    std::printf("unknown");
#endif
    std::printf("\",");
    std::printf("\"arch\":\"%lu-bit\",", (unsigned long)(sizeof(void *) * 8));
    std::printf("\"cxx\":%ld", (long)__cplusplus);
    std::printf("}\n");
    return 0;
}
