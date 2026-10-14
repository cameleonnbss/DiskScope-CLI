/* svc.cpp - `dtk svc` and `dtk startup`: service + autostart inventory.
 *
 * Read-only introspection that powers DiskTop's "what runs in the background"
 * picture. On Windows it uses the Service Control Manager and the classic Run
 * registry keys; on other platforms it reports an empty set so the same binary
 * still builds and the Python layer simply shows nothing extra.
 */
#include "dtk.h"

#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>

namespace dtk {

static const char *state_name(DWORD st) {
    switch (st) {
        case SERVICE_RUNNING: return "Running";
        case SERVICE_STOPPED: return "Stopped";
        case SERVICE_PAUSED:  return "Paused";
        case SERVICE_START_PENDING: return "StartPending";
        case SERVICE_STOP_PENDING:  return "StopPending";
        default: return "Other";
    }
}

/* Enumerate every service, handling the ERROR_MORE_DATA paging protocol. */
static std::vector<ServiceInfo> list_services() {
    std::vector<ServiceInfo> out;
    SC_HANDLE scm = OpenSCManagerW(nullptr, nullptr, SC_MANAGER_ENUMERATE_SERVICE);
    if (!scm) return out;

    DWORD bytesNeeded = 0, servicesReturned = 0, resume = 0;
    /* First call with no buffer to learn the size. */
    EnumServicesStatusExW(scm, SC_ENUM_PROCESS_INFO, SERVICE_WIN32,
                          SERVICE_STATE_ALL, nullptr, 0, &bytesNeeded,
                          &servicesReturned, &resume, nullptr);
    if (bytesNeeded == 0) { CloseServiceHandle(scm); return out; }

    std::vector<BYTE> buf(bytesNeeded);
    resume = 0;
    if (!EnumServicesStatusExW(scm, SC_ENUM_PROCESS_INFO, SERVICE_WIN32,
                               SERVICE_STATE_ALL, buf.data(), bytesNeeded,
                               &bytesNeeded, &servicesReturned, &resume, nullptr)
        && GetLastError() != ERROR_MORE_DATA) {
        CloseServiceHandle(scm);
        return out;
    }

    auto *items = reinterpret_cast<ENUM_SERVICE_STATUS_PROCESSW *>(buf.data());
    char tmp[512];
    for (DWORD i = 0; i < servicesReturned; ++i) {
        ServiceInfo s;
        int n = WideCharToMultiByte(CP_UTF8, 0, items[i].lpServiceName, -1,
                                    tmp, sizeof(tmp), nullptr, nullptr);
        if (n > 0) s.name = tmp;
        n = WideCharToMultiByte(CP_UTF8, 0, items[i].lpDisplayName, -1,
                                tmp, sizeof(tmp), nullptr, nullptr);
        if (n > 0) s.display = tmp;
        s.state = state_name(items[i].ServiceStatusProcess.dwCurrentState);
        out.push_back(std::move(s));
    }
    CloseServiceHandle(scm);
    return out;
}

/* Walk one Run/RunOnce key and collect name=value pairs. */
static void read_run_key(HKEY root, const wchar_t *path, const char *source,
                         std::vector<StartupItem> &out) {
    HKEY hk;
    if (RegOpenKeyExW(root, path, 0, KEY_READ, &hk) != ERROR_SUCCESS) return;
    wchar_t name[256];
    BYTE data[2048];
    DWORD i = 0;
    char utf8name[512], utf8cmd[2048];
    for (;;) {
        DWORD nlen = sizeof(name) / sizeof(wchar_t);
        DWORD dlen = sizeof(data);
        DWORD type = 0;
        if (RegEnumValueW(hk, i++, name, &nlen, nullptr, &type, data, &dlen)
            != ERROR_SUCCESS)
            break;
        if (type != REG_SZ && type != REG_EXPAND_SZ) continue;
        StartupItem item;
        item.source = source;
        if (WideCharToMultiByte(CP_UTF8, 0, name, -1, utf8name, sizeof(utf8name),
                                nullptr, nullptr) > 0)
            item.name = utf8name;
        auto *wval = reinterpret_cast<wchar_t *>(data);
        if (WideCharToMultiByte(CP_UTF8, 0, wval, -1, utf8cmd, sizeof(utf8cmd),
                                nullptr, nullptr) > 0)
            item.command = utf8cmd;
        out.push_back(std::move(item));
    }
    RegCloseKey(hk);
}

static std::vector<StartupItem> list_startup() {
    std::vector<StartupItem> out;
    const wchar_t *runHk  = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
    const wchar_t *run1Hk = L"Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce";
    read_run_key(HKEY_LOCAL_MACHINE, runHk,  "Machine\\Run", out);
    read_run_key(HKEY_CURRENT_USER,  runHk,  "User\\Run", out);
    read_run_key(HKEY_CURRENT_USER,  run1Hk, "User\\RunOnce", out);
    return out;
}

int cmd_svc() {
    auto svcs = list_services();
    if (g_json) {
        std::printf("{\"count\":%zu,\"services\":[", svcs.size());
        for (size_t i = 0; i < svcs.size(); ++i) {
            if (i) std::putchar(',');
            std::printf("{\"name\":"); json_str(svcs[i].name.c_str());
            std::printf(",\"display\":"); json_str(svcs[i].display.c_str());
            std::printf(",\"state\":"); json_str(svcs[i].state.c_str());
            std::printf("}");
        }
        std::printf("]}\n");
        return 0;
    }
    int running = 0;
    for (const ServiceInfo &s : svcs)
        if (s.state == "Running") { ++running;
            std::printf("  [Running] %-40.40s %s\n", s.name.c_str(), s.display.c_str()); }
    std::printf("\n%d running / %zu total\n", running, svcs.size());
    return 0;
}

int cmd_startup() {
    auto items = list_startup();
    if (g_json) {
        std::printf("{\"count\":%zu,\"items\":[", items.size());
        for (size_t i = 0; i < items.size(); ++i) {
            if (i) std::putchar(',');
            std::printf("{\"source\":"); json_str(items[i].source.c_str());
            std::printf(",\"name\":"); json_str(items[i].name.c_str());
            std::printf(",\"command\":"); json_str(items[i].command.c_str());
            std::printf("}");
        }
        std::printf("]}\n");
        return 0;
    }
    for (const StartupItem &it : items)
        std::printf("  %-16s %-28.28s %s\n", it.source.c_str(), it.name.c_str(),
                    it.command.c_str());
    std::printf("\n%zu autostart entry(ies)\n", items.size());
    return 0;
}

}  /* namespace dtk */

#else  /* ------------------------------ POSIX ------------------------------ */
namespace dtk {
int cmd_svc() {
    if (g_json) std::printf("{\"count\":0,\"services\":[]}\n");
    else        std::printf("services inventory is Windows-only\n");
    return 0;
}
int cmd_startup() {
    if (g_json) std::printf("{\"count\":0,\"items\":[]}\n");
    else        std::printf("autostart inventory is Windows-only\n");
    return 0;
}
}  /* namespace dtk */
#endif
