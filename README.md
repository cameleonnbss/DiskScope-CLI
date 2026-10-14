# DiskTop

*(formerly “DiskScope CLI” — same engine, new logo; the repo, modules and cache
path keep the old name so nothing breaks.)*

[![CI](https://github.com/cameleonnbss/DiskScope-CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/cameleonnbss/DiskScope-CLI/actions/workflows/ci.yml)

**Windows Storage Analyzer — 100 % command line, real data only.**
Scan your drives, find what eats your space, locate old files, detect Steam / Epic / Battle.net / EA / Ubisoft / Riot / GOG games and review a safety-gated cleanup list.

Everything you see is computed from your actual disk: sizes, dates, games, applications. No fake data, no simulated progress.

---

## Features

| Menu | What it does |
|---|---|
| **1 — Analyse complète** | Parallel scan of every fixed drive: sizes, file counts, big/old file collectors, per-drive top folders, interactive folder exploration |
| **2 — Analyse rapide** | Drive overview + first-level folder sizes of C:, **parallel** across folders (thread pool) |
| **3 — Applications** | Registry uninstall keys + AppData programs + Store apps, real measured sizes, honestly-flagged estimates |
| **4 — Jeux** | Steam (`.acf` manifests), Epic (`.item`), Battle.net, Ubisoft Connect, EA App, Riot, GOG, Xbox — real local evidence only |
| **5 — Gros fichiers** | Top files with adjustable threshold (>1 GB…>9 GB, or >100 MB) |
| **6 — Fichiers anciens** | 30 d / 90 d / 180 d / 1 an / 2 ans buckets + category breakdown (archives, ISO, installers, videos, logs, temp, builds) |
| **D — Doublons** | Duplicate finder over the biggest files: size + partial + full SHA-256, I/O-bounded; reports wasted space per group |
| **C — Nettoyage express** | One-stop cleanup: caches/temp, Recycle Bin (official Windows API), big files in Downloads with multi-select (`1,3-5`) — all confirmed before deletion |
| **7 — Nettoyage avancé** | SAFE / REVIEW / DANGER recommendations + system advisories (hiberfil.sys, Windows.old, WinSxS, Delivery Optimization) with the official cleanup command |
| **8 — Rapport** | Full storage report, exportable to `report.txt`, `report.json`, `report.html`, `report.csv` (Excel-friendly) |
| **9 — Recherche** | `/large 10GB`, `/old 1year`, `/files .iso`, `/drive D:`, plain text search |
| **S — Paramètres** | Dry-run toggle, cache clear, rescan, Store apps on/off |

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
```

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
safety.py        guards, trash deletion, dry-run mode
trash_win.py      Windows Recycle Bin (ctypes + Shell) — Unicode/accents safe
cache.py         persistent scan cache (atomic writes)
nativehelper.py  fail-safe bridge to the optional native accelerator
native/dufast.c  optional C sizing helper (compiled by the launchers if gcc present)
run.bat          one-file Windows launcher (bootstraps venv + deps + optional native)
run.sh           one-file bash launcher (Git Bash / WSL / Linux / macOS)
tests/           pytest suite (safety, scanner, cache, filters, reports, native, launchers)
```

## Requirements

- Windows 10 or 11 (works degraded elsewhere for development)
- Python 3.10+ (3.14/3.15 tested)
- `rich`, `send2trash` — auto-installed by `run.bat` / `run.sh` on first launch
- Optional: a C compiler (`gcc`/`clang`) to build the native accelerator — not required

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
