# DiskScope CLI

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

## Install (Windows 10 / 11, PowerShell or CMD)

```bat
install.bat
```

Creates `.venv`, installs `rich` + `send2trash`, then runs a self-test.

## Run

```bat
run.bat
```

or from PowerShell:

```powershell
python main.py
```

### One-shot commands

```text
python main.py --quick            drive overview
python main.py --scan             full scan + summary
python main.py --report html      build & export report.html
python main.py --search iso       one-shot search
python main.py --no-cache         ignore saved cache
python main.py --selftest         verify installation
```

## Safety model

- **No automatic deletion. Ever.** Every removal requires an explicit per-item confirmation.
- **Dry run is the default**: nothing is touched until you disable it in `S` > `D`.
- Deletions go to the **Recycle Bin** via `send2trash` (permanent delete only if it is unavailable, after a second confirmation).
- Hard-blocked by `safety.py`: drive roots, `C:\Windows` + subfolders, `Program Files`, `ProgramData`, `..` traversal, relative paths, DiskScope's own folder.
- Unreadable directories are skipped cleanly; junctions/symlinks are never followed during scans.
- "Dernière utilisation" is only ever shown as an **estimate derived from file mtimes** and labelled as such — Windows does not expose true usage dates.

## Performance notes

- `os.scandir()` + a thread-pool per-directory walker; the GIL is released by OS calls so parallelism helps on NVMe.
- Bounded-memory collectors keep only the top 500 biggest files and 30 000 old-file candidates.
- Trees are compacted before caching; the JSON cache lives in `%LOCALAPPDATA%\DiskScope\cache.json` and makes menu switching instant.

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
reports.py       report builder + txt/json/html export
ui.py            rich-based rendering (banner, panels, bars, tables)
safety.py        guards, trash deletion, dry-run mode
cache.py         persistent scan cache (atomic writes)
```

## Requirements

- Windows 10 or 11 (works degraded elsewhere for development)
- Python 3.10+ (3.14 tested)
- `rich`, `send2trash` (installed by `install.bat`)
