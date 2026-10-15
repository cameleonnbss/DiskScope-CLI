# DiskTop

*(formerly “DiskScope CLI” — same engine, new logo; the repo, modules and cache
path keep the old name so nothing breaks.)*

[![CI](https://github.com/cameleonnbss/DiskScope-CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/cameleonnbss/DiskScope-CLI/actions/workflows/ci.yml)
[![Français](https://img.shields.io/badge/🇫🇷_Lire_en_Français-blue)](README_FR.md)
[![Release](https://img.shields.io/badge/Download-DiskTop.exe-brightgreen)](https://github.com/cameleonnbss/DiskScope-CLI/releases/latest)
[![GitHub](https://img.shields.io/badge/GitHub-cameleonnbss-181717?logo=github)](https://github.com/cameleonnbss)

**Windows Storage Analyzer — 100 % command line, real data only.**
Scan your drives, find what eats your space **and what eats your RAM**, locate old files, detect Steam / Epic / Battle.net / EA / Ubisoft / Riot / GOG games and review a safety-gated cleanup list.

Everything you see is computed from your actual disk **and live system memory**: sizes, dates, games, applications, processes. No fake data, no simulated progress.

---

## Features

| Menu | What it does |
|---|---|
| **1 — Full analysis** | Parallel scan of every fixed drive: sizes, file counts, big/old file collectors, per-drive top folders, interactive folder exploration |
| **2 — Quick analysis** | Drive overview + first-level folder sizes of C:, **parallel** across folders (thread pool) |
| **3 — Applications** | Registry uninstall keys + AppData programs + Store apps, real measured sizes, honestly-flagged estimates |
| **4 — Games** | Steam (`.acf` manifests), Epic (`.item`), Battle.net, Ubisoft Connect, EA App, Riot, GOG, Xbox — real local evidence only |
| **5 — Big files** | Top files with adjustable threshold (>1 GB…>9 GB, or >100 MB), plus a **[T] break-down by file type** (what kind of data is eating your disk) |
| **6 — Old files** | 30 d / 90 d / 180 d / 1 y / 2 y buckets + category breakdown (archives, ISO, installers, videos, logs, temp, builds) |
| **D — Duplicates** | Duplicate finder over the biggest files: size + partial + full SHA-256, I/O-bounded; reports wasted space per group |
| **C — Express cleanup** | One-stop cleanup: caches/temp, Recycle Bin (official Windows API), big files in Downloads with multi-select (`1,3-5`) — all confirmed before deletion |
| **7 — Advanced cleanup** | SAFE / REVIEW / DANGER recommendations + system advisories (hiberfil.sys, Windows.old, WinSxS, Delivery Optimization) with the official cleanup command |
| **8 — Report** | Full storage report, exportable to `report.txt`, `report.json`, `report.html`, `report.csv` (Excel-friendly) |
| **9 — Search** | `/large 10GB`, `/old 1year`, `/files .iso`, `/drive D:`, plain text search |
| **M — RAM & Tasks** | Live memory pressure, biggest RAM consumers, logon startup items and running services (native C++ core, ctypes fallback) + a safe "trim this app's working set" action |
| **S — Settings** | Dry-run toggle, cache clear, rescan, Store apps on/off, **language**, and **[G] open the project's GitHub page** |

The dashboard uses a **colour-coded menu** (analysis, cleanup, inventory and RAM
grouped by colour) and shows a **GitHub redirect** in the footer of every main
screen, so the source is always one key away ([S] → G, or `--github`).

## Run — one file, everything bootstraps itself

**Windows:** double-click (or run) `run.bat` — on first launch it finds Python
(even when it is not in PATH, via the `py` launcher), creates `.venv`, installs
`rich` + `send2trash`, then starts the app. Arguments pass straight through:

```bat
run.bat --quick
run.bat --selftest
```

**Git Bash / WSL / Linux / macOS dev:** the same thing with one file:

```sh
./run.sh --selftest
```

`install.bat` still works and is just a friendly front-end that runs
`run.bat --selftest`. Nothing else to wire up — every entry point uses the
same bootstrap, and the app always runs from its own folder no matter where
you launch it from.

### One-shot commands

```text
run.bat --quick             drive overview
run.bat --scan              full scan + summary
run.bat --report html       build & export report.html
run.bat --search iso        one-shot search
run.bat --no-cache          ignore saved cache
run.bat --selftest          verify installation
run.bat --empty-bin         empty the Recycle Bin (Windows API)
run.bat --github            open this project's GitHub page in your browser
run.bat --lang fr           start in French (en · fr · es · de · it)
```

## Language — English by default, switch anytime

The whole interface is **English by default** and every menu, prompt, table and
report flows through a small self-contained i18n layer (`i18n.py`). Change the
language live with **`S` — Settings → `[L] Language`** (arrow keys or the letter);
the choice is persisted to `%LOCALAPPDATA%\DiskScope\config.json` so it survives
restarts. Five languages ship today: **English, French, Spanish, German,
Italian** — adding another is just a new catalog dict with the same keys.

You can also set it without touching the UI:

```bat
run.bat --lang de            one-shot flag
set DISKTOP_LANG=es          environment override (wins over config)
```

Missing keys fall back to English, and unknown keys fall back to the key itself,
so a partial translation can never crash the app.

## Single `.exe` — no Python required

`DiskTop.spec` + `build_exe.bat` / `build_exe.sh` package the app into **one
self-contained `DiskTop.exe`** with [PyInstaller](https://pyinstaller.org) — the
end user does not need Python installed:

```bat
pip install pyinstaller
build_exe.bat                REM produces dist\DiskTop.exe
```

Each tagged release (e.g. `v2.5.0`) is built and uploaded automatically by
`.github/workflows/release.yml`, so the executable is attached to the GitHub
**Releases** page as a downloadable asset. The optional native C++ core is
bundled when a compiler was available; otherwise the pure-Python path runs.

## Native core — a real C++ engine (`native/`)

Behind the "RAM & Tasks" view lives **`dtk`** — the *DiskTop Core*, a small
cross-platform C++ toolkit (`native/*.cpp`, single binary, JSON output):

```text
dtk mem       live memory + top consumers
dtk proc      every process with its real working-set RAM
dtk startup   logon (autostart) registry entries
dtk svc       Windows service inventory
dtk disk      volumes + free space
dtk tmp DIR   fast Unicode-safe recursive folder size (never follows a junction)
dtk trim      release THIS process's own working set back to the OS
```

It is built on the Win32 API (`GlobalMemoryStatusEx`, Toolhelp32 snapshots,
`GetProcessMemoryInfo`, the Service Control Manager, the `Run` registry keys) and
on POSIX `/proc` elsewhere. **It is 100 % optional:** `run.bat` / `run.sh` /
`build_exe.bat` compile it only if `g++` exists, `nativehelper.py` runs it behind
a fail-safe wrapper, and `memory.py` reads the same numbers directly through
`ctypes` when the binary is absent — so the shipped `.exe` and every machine work
identically with or without a compiler. `DISKSCOPE_NO_NATIVE=1` disables it. The
core is **read-only** except for `trim`, which only touches DiskTop's own memory.

> **About the GitHub language bar:** DiskTop's runtime is Python and it ships a
> compiled C++ core. `.gitattributes` marks the Python glue, the C++ sources and
> the docs/scripts as `linguist-detectable=false`, so the small hand-written **C**
> helper (`native/dufast.c`) is the repository's featured language. This is purely
> the owner's display preference — it deletes nothing and changes neither what runs
> nor how it is tested; the full C++ core and every Python module stay in the repo.

## Safety model

- **No automatic deletion. Ever.** Every removal requires an explicit per-item confirmation.
- **Dry run is the default**: nothing is touched until you disable it in `S` > `D`.
- Deletions go to the **Recycle Bin** via `trash_win` (a ctypes + Windows Shell call that works even on accented profile paths like `C:\Users\caméléon`) with `send2trash` as fallback. Permanent delete only happens when the caller explicitly opts in.
- Hard-blocked by `safety.py`: drive roots, `C:\Windows` + subfolders, `Program Files`, `ProgramData`, `..` traversal, relative paths, the app's own folder, **and NTFS junctions/reparse points** (`Local Settings`, `Application Data`, …).
- Unreadable directories are skipped cleanly; **junctions and symlinks are never followed during scans** — this fixes a bug where every file under a junction was counted twice (double-sized folders, phantom duplicates).
- "Dernière utilisation" is only ever shown as an **estimate derived from file mtimes** and labelled as such — Windows does not expose true usage dates.

## Performance notes

- `os.scandir()` + a thread-pool per-directory walker; the GIL is released by OS calls so parallelism helps on NVMe.
- Bounded-memory collectors keep only the top 500 biggest files and 30 000 old-file candidates.
- Trees are compacted before caching; the JSON cache lives in `%LOCALAPPDATA%\DiskScope\cache.json` and makes menu switching instant.
- **Optional native accelerator:** if a C compiler is present, `run.bat` / `run.sh`
  build `native/dufast` (from `native/dufast.c`) to size cache/temp folders faster.
  It is used only when it exists and returns a positive size; otherwise the
  pure-Python walker runs — so it can never change a reported number or break.
  Disable it anytime with `DISKSCOPE_NO_NATIVE=1`.

## Project layout

```
main.py          entry point, menus, views, selftest
scanner.py       parallel recursive scanner + collectors
drives.py        volume enumeration (ctypes, stdlib only)
files.py         big/old analysis, filter mini-language, search
applications.py  registry + AppData + Store app detection
steam.py         VDF/ACF parsing, library discovery
epic.py          Epic .item manifests + .egstore fallback
games.py         Battle.net / Ubisoft / EA / Riot / GOG / Xbox
cleanup.py       SAFE / REVIEW / DANGER engine
reports.py       report builder + txt/json/html/csv export + offline insights
ui.py            rich-based rendering (logo banner, panels, bars, tables)
i18n.py          self-contained localization layer (en · fr · es · de · it, persisted)
safety.py        guards, trash deletion, dry-run mode
trash_win.py      Windows Recycle Bin (ctypes + Shell) — Unicode/accents safe
cache.py         persistent scan cache (atomic writes)
memory.py        live RAM / process / startup view (native core + ctypes fallback)
nativehelper.py  fail-safe bridge to the optional native core
native/dtk.*     the C++ DiskTop Core (mem/proc/disk/startup/svc/tmp/trim CLI)
native/dufast.c  optional C sizing helper (compiled by the launchers if gcc present)
run.bat          one-file Windows launcher (bootstraps venv + deps + optional native)
run.sh           one-file bash launcher (Git Bash / WSL / Linux / macOS)
DiskTop.spec     PyInstaller recipe for the single-file executable
build_exe.bat     builds dist\DiskTop.exe on Windows (pip install pyinstaller)
build_exe.sh     same build for bash/CI
tests/           pytest suite (safety, scanner, cache, filters, reports, native, launchers, locale)
```

## Requirements

- Windows 10 or 11 (works degraded elsewhere for development)
- Python 3.10+ (3.14/3.15 tested)
- `rich`, `send2trash` — auto-installed by `run.bat` / `run.sh` on first launch
- Optional: a C/C++ compiler (`gcc` for `dufast`, `g++` for the `dtk` core) — not required
- Optional: `pyinstaller` to build the single-file `DiskTop.exe` (`build_exe.bat`)

## Tests & CI

A pytest suite covers the safety guards, the scanner, the cache, the
filter mini-language, the duplicate finder and the report exporters:

```bat
pip install pytest
python -m pytest tests -q
```

Every push runs the suite plus `--selftest` on **Windows and Linux** across
Python 3.10 / 3.12 / 3.13 (`.github/workflows/ci.yml`).

## Changelog

### 2.5.0
- **GitHub redirect, everywhere**: the main menu now carries a colour-coded key set
  (analysis · cleanup · inventory · RAM grouped by colour) and a **GitHub footer**,
  Settings gains **[G] Open GitHub page**, and there is a one-shot `--github` flag.
  Uses stdlib `webbrowser`, is fully best-effort (never crashes on a headless box —
  it just prints the URL) and points at `github.com/cameleonnbss/DiskScope-CLI`.
- **"Space by file type"**: Big files ([5]) gained a **[T]** action that aggregates
  the cached big + old files by content category (videos, archives, ISOs, installers,
  downloads, builds, logs, other) so you can see *what kind of data* fills the disk,
  not just which files are largest (`files.space_by_type`, de-duplicated, size-sorted).
- **Menu polish**: the header panel now shows `DISKTOP · vX` with the tagline as a
  subtitle. New selftest checks (github redirect, space-by-type) and 4 new tests
  (79 total); all user-facing strings added across `en · fr · es · de · it`.

### 2.4.0
- **Native C++ core (`dtk`)**: a real cross-platform C++ engine under `native/`
  (`dtk.h`/`dtk.cpp` + `meminfo/proclist/diskstat/svc/tmpscan/trim/version`) that
  reads live memory, per-process working-set RAM, logon startup items, Windows
  services, volume free space and folder sizes, and can trim its own working set.
  Emits JSON, built on the Win32 API (with POSIX `/proc` fallbacks), compiled
  best-effort by `run.bat`/`run.sh`/`build_exe.bat`/CI when `g++` is present, and
  bundled into the `.exe` by `DiskTop.spec` when built. Strictly optional:
  `nativehelper.py` is fail-safe and `memory.py` mirrors every reading in pure
  `ctypes`, so nothing breaks without a compiler. Read-only except `trim`
  (self-process only).
- **New "M — RAM & Tasks" view**: memory-pressure bar, top RAM consumers, logon
  startup items and running-service count — answering "what runs in the
  background and eats my RAM" — with a safe working-set release.
- **Italian (5th UI language)**: `en · fr · es · de · it`, with the RAM/tasks
  strings translated across all locales.
- **Featured language**: `.gitattributes` now presents the hand-written **C** helper
  as the repository's featured language (Python glue, the C++ sources and the
  docs/scripts marked `linguist-detectable=false`); a display preference only — the
  C++ core and every Python module stay in the repo, with no runtime or test impact.
- **Selftest**: added a memory-backend check; README gains a French button, a
  download badge, and a native-core architecture section (`README_FR.md` mirror).

### 2.3.0
- **English by default + full i18n**: the interface now opens in **English** and
  every menu, prompt, banner, table, report and safety/cleanup message is routed
  through a self-contained localization layer (`i18n.py`). Four languages ship:
  **English, French, Spanish, German** (314 catalog keys, placeholder-checked and
  parity-verified across all locales). Switch live from **`S` → `[L] Language`**;
  the choice persists to `%LOCALAPPDATA%\DiskScope\config.json`. Also settable via
  `--lang <code>` or the `DISKTOP_LANG` env var. Unknown/partial keys fall back to
  English, then to the key, so a translation can never crash the app.
- **Single-file executable**: `DiskTop.spec` + `build_exe.bat` / `build_exe.sh`
  build one self-contained `DiskTop.exe` with PyInstaller (no Python needed on the
  target machine). `.github/workflows/release.yml` builds and attaches the `.exe`
  to each tagged release automatically.
- **Deep-view translation**: search, big/old files, duplicates, apps, games, drive
  and cleanup views — plus the module data strings in `files.py` (category labels,
  filter tokens), `safety.py` (refusal reasons + summary), `cleanup.py` (SAFE reasons,
  advisories, Recycle Bin) and `drives.py` (drive kinds) — are all localized while the
  functional identifiers (status tokens, category keys, drive types, hotkeys) stay stable.
- **Fix**: the junction self-test matched the French literal `"jonction"` inside a
  refusal message; it now asserts the guard simply *refuses* the reparse point, so it
  stays correct in every language.
- **Tests**: French-asserting tests made locale-deterministic (autouse English pin) and
  a new `tests/test_locale.py` guards catalog parity → 73 passing.

### 2.2.0
- **New logo + DiskTop identity**: the block-art startup banner and the visible
  product name are now **DiskTop**. Internal identifiers (GitHub repo, module
  files, `%LOCALAPPDATA%\DiskScope` cache path) are unchanged on purpose so
  nothing breaks.
- **Offline report insights**: `reports.py` now derives a prioritised
  **RECOMMANDATIONS** section (txt + html) straight from the real scan — full
  drives, cleanable caches, system advisories, oldest big unused file, dominant
  game launcher. No model, no API, no network: deterministic stdlib rules.
- **Bug fix — app sizes**: `_measure_app_sizes()` was defined but never called,
  so registry apps without `EstimatedSize` were always reported as *unknown*.
  They are now measured on disk (bounded by a budget), giving real sizes in
  the Applications menu.
- **Optional native accelerator (C)**: `native/dufast.c` + `nativehelper.py`
  speed up cache/temp folder sizing when a compiler is available. Strictly
  opt-in: the launchers build it only if `gcc`/`clang` exists, it is used only
  when it returns a positive size, and `DISKSCOPE_NO_NATIVE=1` or its absence
  falls back to the Python walker — so it can never change a number or break.
- **Tests**: +8 (insights, native fallback, launcher build guard) → 67 passing.

### 2.1.0
- **One-file launchers**: `run.bat` now bootstraps everything itself (Python
  detection via the `py` launcher even when PATH is empty, venv creation,
  dependency install on first run only) and runs from its own folder no
  matter where it is launched from; `run.sh` is the bash twin; `install.bat`
  delegates to the same bootstrap.
- **Security fix**: `is_protected()` compared an upper-cased path against a
  lower-cased blocklist, so `Program Files`, `ProgramData`, `$Recycle.Bin`,
  `System Volume Information`… were **never actually blocked** (only
  `C:\Windows` was, via a string fallback). Now all protected names match.
- **Fix**: menu 6 (Fichiers anciens) crashed with `TypeError`
  (`build_old_view` was called with an unsupported `min_size` argument).
- **Fix**: menu 6 `[C]` category view crashed with `ValueError`
  (wrong tuple unpacking of `old_summary_by_category`).
- **Fix**: Recycle Bin emptying failed on Python 3.10/3.11
  (`ctypes.HRESULT` only exists on 3.12+).
- **Fix**: CSV export always wrote an empty filesystem column
  (`fs` key instead of `fstype`).
- **Fix**: `/…` filters now honor `>=` and `<=` as inclusive bounds
  (they silently behaved like `>` and `<`).
- **Perf**: the scanner now aggregates per-directory stats with a single
  lock acquisition instead of one per file (less contention on large trees).
- **Tests + CI**: 54 new unit tests and a GitHub Actions matrix
  (Windows + Linux × Python 3.10/3.12/3.13).
