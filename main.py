"""DiskScope CLI - main.py

Entry point and interactive menu. Run with no arguments for the full TUI,
or use flags for one-shot commands:

  python main.py --scan          full scan then summary
  python main.py --quick         drive overview only
  python main.py --report html   build + export report
  python main.py --search steam  quick search from the command line
  python main.py --selftest      verify the installation (used by install.bat)
  python main.py --empty-bin     empty the Recycle Bin (Windows API)
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from typing import Any

import cache as cache_mod
import cleanup
import drives as drives_mod
import files as files_mod
import games as games_mod
import i18n
import memory
import reports
import safety
import scanner
import ui


APP_VERSION = ui.APP_VERSION

# Combien de gros fichiers on conserve dans le cache et les rapports.
# L'ancien plafond de 500 (puis 200 dans reports.py) faisait disparaître
# des dossiers entiers (Downloads = 184 Go n'apparaissait qu'à 72 Go).
BIG_KEEP = 5000


class App:
    """Shared state for the whole session."""

    def __init__(self, use_cache: bool = True):
        self.settings = {
            "dry_run": safety.DRY_RUN_DEFAULT,
            "min_big_size": 1024 ** 3,          # 1 GB default filter
            "old_age_days": 90,
            "include_store_apps": True,
        }
        self.use_cache = use_cache
        self.cache = cache_mod.load() if use_cache else cache_mod._empty()
        self.drives: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    def settings_line(self) -> str:
        mode = i18n.t("mode_dry") if self.settings["dry_run"] else i18n.t("mode_del")
        cache = i18n.t("on") if self.use_cache else i18n.t("off")
        return i18n.t("settings_line", mode=mode, cache=cache)


    def deleter(self) -> safety.Deleter:
        return safety.Deleter(dry_run=self.settings["dry_run"])

    # ------------------------------------------------------------------ #
    def ensure_drives(self) -> list[dict[str, Any]]:
        if not self.drives:
            self.drives = drives_mod.list_drives()
        return self.drives

    def have_full_scan(self) -> bool:
        return bool(self.cache.get("trees")) and bool((self.cache.get("meta") or {}).get("finished"))

    def run_scan(self, quick: bool = False, force: bool = False) -> None:
        """Scan all fixed drives (full) or just build a drive overview (quick)."""
        self.ensure_drives()
        fixed = [d for d in self.drives if d["kind"].startswith("SSD") or "fixe" in d["kind"]]
        targets = fixed or self.drives[:1]
        if quick:
            targets = targets[:1]
        stop = threading.Event()
        all_big: list[dict[str, Any]] = []
        all_old: list[dict[str, Any]] = []
        trees: dict[str, Any] = {}
        tops: dict[str, Any] = {}
        t0 = time.monotonic()
        total_files = 0
        for d in targets:
            mount = d["mount"]
            if quick:
                continue
            ui.console.print(c_scan_head(mount))
            collectors = scanner.Collectors(big_keep=BIG_KEEP, old_min_size=1024 * 1024)
            tree = None
            stats: dict[str, Any] = {}
            with ui.ScanProgress(label=f"Scan {mount}") as prog:
                cb = lambda f, b, e, p: prog.tick(f, e, p)  # noqa: E731
                try:
                    tree, stats = scanner.scan_tree(
                        mount, mount, max_depth=scanner.DEFAULT_DEPTH,
                        progress=cb, collectors=collectors, stop=stop)
                except KeyboardInterrupt:
                    stop.set()
                    ui.warn(i18n.t("vw_scan_interrupted"))
            if tree is None:
                return
            compact = scanner.compact_tree(tree, max_depth=4, max_children=14)
            trees[mount] = compact
            tops[mount] = [{"name": ch["name"], "path": ch["path"], "size": ch["size"]}
                           for ch in (tree.get("children") or [])[:12]]
            big, old = collectors.results()
            all_big.extend(big)
            all_old.extend(old)
            total_files += stats["files"]
        duration = time.monotonic() - t0
        if not quick:
            try:
                hist_drives = {d["mount"]: max(0, d.get("total", 0) - d.get("free", 0))
                               for d in self.drives}
                cache_mod.push_history(self.cache, hist_drives)
            except Exception:
                pass
        if not quick:
            all_big.sort(key=lambda x: x["size"], reverse=True)
            seen: set[str] = set()
            dedup_old = []
            for f in sorted(all_old, key=lambda x: x["size"], reverse=True):
                if f["path"] not in seen:
                    seen.add(f["path"])
                    dedup_old.append(f)
            self.cache["trees"] = trees
            self.cache["top_folders"] = tops
            self.cache["bigfiles"] = all_big[:BIG_KEEP]
            self.cache["oldfiles"] = dedup_old[:30000]
            cache_mod.update_meta(self.cache, duration=duration, files=total_files,
                                  quick=quick)
            if self.use_cache:
                cache_mod.save(self.cache)
            ui.ok(i18n.t("vw_scan_done", n=f"{total_files:,}", dur=ui._fmt_dur(duration)))
        else:
            cache_mod.update_meta(self.cache, duration=time.monotonic() - t0,
                                  quick=True)
            if self.use_cache:
                cache_mod.save(self.cache)

    def ensure_scan(self, force: bool = False) -> None:
        if force or not self.have_full_scan():
            self.run_scan(quick=False, force=True)


def c_scan_head(mount: str) -> str:
    return ui.c(i18n.t("vw_scan_of", mount=mount), "cyan", True)


# --------------------------------------------------------------------------- #
#  Views
# --------------------------------------------------------------------------- #
def _drive_deltas(app: App) -> dict[str, int]:
    """Per-drive change vs the previous history point ("C:" -> delta used)."""
    hist = app.cache.get("history") or []
    if len(hist) < 2:
        return {}
    last, prev = hist[-1], hist[-2]
    out: dict[str, int] = {}
    for mount, used in (last.get("drives") or {}).items():
        p = (prev.get("drives") or {}).get(mount)
        if p is not None:
            out[mount] = int(used) - int(p)
    return out


def view_drives(app: App) -> None:
    ui.show_banner()
    ds = app.ensure_drives()
    if not ds:
        ui.err(i18n.t("vw_no_disk"))
        return
    ui.show_cache_info(app.cache.get("meta"))
    deltas = _drive_deltas(app)
    for d in ds:
        tops = [(t["name"], t["size"]) for t in (app.cache.get("top_folders") or {}).get(d["mount"], [])]
        ui.drive_panel(d, tops or None)
        delta = deltas.get(d["mount"])
        if delta:
            sign = "+" if delta > 0 else ""
            _dk = "vw_delta_more" if delta > 0 else "vw_delta_free"
            ui.console.print(ui.c(
                "  " + i18n.t(_dk, v=f"{sign}{ui.human(abs(delta))}"), "dim"))
    ui.console.print()


def view_full_analysis(app: App) -> None:
    ui.show_banner()
    ui.info(i18n.t("vw_full_intro"))
    if not ui.confirm(i18n.t("vw_full_confirm"), True):
        return
    app.run_scan(quick=False)
    view_drives(app)
    # navigation into a top folder
    ds = app.ensure_drives()
    for d in ds:
        tops = (app.cache.get("top_folders") or {}).get(d["mount"], [])
        if not tops:
            continue
        ui.console.print(ui.c("  " + i18n.t("vw_top_folders_of", mount=d["mount"]), "yellow", True))
        for i, t in enumerate(tops, 1):
            ui.console.print(f"   {i:>2}. {t['name']:<30.30} {ui.colorize(t['size'])}")
        idx = ui.choose_index(i18n.t("vw_explore_folder", mount=d["mount"]), len(tops), allow_zero=True)
        if idx:
            explore_folder(app, tops[idx - 1]["path"])


def explore_folder(app: App, path: str) -> None:
    """Deep-dive into one folder with a fresh bounded scan."""
    ui.console.print()
    ui.info(i18n.t("vw_detail_analysis", path=path))
    with ui.ScanProgress(label=i18n.t("vw_prog_analyse")) as prog:
        cb = lambda f, b, e, p: prog.tick(f, e, p)  # noqa: E731
        try:
            tree, stats = scanner.scan_tree(path, path[:2], max_depth=scanner.DETAIL_DEPTH,
                                            progress=cb)
        except KeyboardInterrupt:
            ui.warn(i18n.t("vw_interrupted"))
            return
    lines = ui.tree_lines(tree, max_depth=3, max_children=8)
    for ln in lines:
        ui.console.print("  " + ln)
    ui.console.print(ui.c(i18n.t("vw_explore_total", size=ui.human(tree['size']),
                                files=f"{tree['files']:,}", dirs=f"{tree['dirs']:,}",
                                errors=stats['errors']), "dim"))
    # biggest files inside this folder
    big = sorted(app.cache.get("bigfiles", []), key=lambda x: x["size"], reverse=True)
    inner = [b for b in big if b["path"].lower().startswith(path.lower())][:10]
    if inner:
        ui.console.print(ui.c(i18n.t("vw_biggest_here"), "yellow", True))
        for b in inner:
            age = ui.human_age(max(0, time.time() - b.get("mtime", 0)))
            ui.console.print(f"    {ui.colorize(b['size']):>12}  {os.path.basename(b['path'])[:40]:<40.40} {ui.c(age, 'dim')}")


def view_quick(app: App) -> None:
    ui.show_banner()
    app.run_scan(quick=True)
    view_drives(app)
    d = app.ensure_drives()[0]
    mount = d["mount"]
    # Reuse the full-scan cache when it covers this drive (instant display).
    tops = (app.cache.get("top_folders") or {}).get(mount)
    if tops and app.have_full_scan():
        ui.size_table([(t["name"], t["size"], "") for t in tops[:15]],
                      title=i18n.t("vw_top_folders_cache", mount=mount))
        return
    ui.info(i18n.t("vw_quick_intro", mount=mount))
    stop = threading.Event()

    def _prog(done: int, total: int, name: str, files: int) -> None:
        if _prog.prog is not None:
            _prog.prog.set_total(total)
            _prog.prog.tick(done, 0, name)
    _prog.prog = None  # type: ignore[attr-defined]

    with ui.ScanProgress(label=i18n.t("vw_top_folders", mount=mount)) as prog:
        _prog.prog = prog  # type: ignore[attr-defined]
        rows = scanner.top_level_sizes(mount, stop=stop, on_progress=_prog)
    ui.size_table([(name, size, i18n.t("cache_files", n=f"{files:,}")) for name, _p, size, files in rows[:15]],
                  title=i18n.t("vw_top_folders", mount=mount))


def view_apps(app: App) -> None:
    ui.show_banner()
    ui.info(i18n.t("vw_apps_detecting"))
    stop = threading.Event()
    with ui.ScanProgress(label=i18n.t("menu_apps")):
        apps = _detect_apps_blocking(stop, app.settings["include_store_apps"])
    apps.sort(key=lambda a: a.get("size") or 0, reverse=True)
    known = [a for a in apps if a.get("size")]
    unknown = [a for a in apps if not a.get("size")]
    ui.console.print(ui.c(i18n.t("vw_apps_summary", n=len(apps),
                                 known=len(known), unknown=len(unknown)), "dim"))
    rows = []
    for a in known[:40]:
        note = f"{a.get('publisher', '')[:24]}  {a.get('last_used_label', '')}"
        rows.append((a["name"][:38], a["size"], note))
    ui.size_table(rows, title=i18n.t("vw_apps_title"))
    if unknown:
        ui.console.print(ui.c(i18n.t("vw_apps_unknown_more", n=len(unknown)), "dim"))
    ui.console.print(ui.c(i18n.t("vw_apps_note"), "dim"))
    _apps_cache(app, apps)


def ensure_inventory(app: App, stop: threading.Event | None = None) -> None:
    """Populate cached apps/games when missing (used by the report views)."""
    if not app.cache.get("apps"):
        apps = _detect_apps_blocking(stop, app.settings["include_store_apps"])
        _apps_cache(app, apps)
    if not app.cache.get("games"):
        try:
            inv = games_mod.detect_games(stop=stop, steam_limit=30, other_limit=20)
        except Exception:
            inv = {"launchers": {}}
        app.cache["games"] = {"launchers": {k: [{kk: g.get(kk) for kk in
                              ("name", "path", "size", "appid", "mtime")} for g in v]
                              for k, v in inv["launchers"].items()}}
        if app.use_cache:
            cache_mod.save(app.cache)


def _detect_apps_blocking(stop, include_store: bool):
    import applications
    apps = applications.detect_apps(stop=stop, include_store=include_store)
    applications.mark_estimates(apps)
    return apps


def _apps_cache(app: App, apps: list[dict[str, Any]]) -> None:
    slim = [{k: a.get(k) for k in ("name", "publisher", "version", "size",
                                   "location", "last_used_label", "store")}
            for a in apps[:300]]
    app.cache["apps"] = slim
    if app.use_cache:
        cache_mod.save(app.cache)


def view_games(app: App) -> None:
    ui.show_banner()
    ui.info(i18n.t("vw_games_detecting"))
    stop = threading.Event()
    with ui.ScanProgress(label=i18n.t("menu_games")):
        try:
            inv = games_mod.detect_games(stop=stop)
        except Exception as e:  # never crash the menu on one launcher
            ui.err(i18n.t("vw_games_error", e=e))
            return
    app.cache["games"] = {"launchers": {k: [{kk: g.get(kk) for kk in ("name", "path", "size", "appid", "mtime")}
                                            for g in v] for k, v in inv["launchers"].items()}}
    if app.use_cache:
        cache_mod.save(app.cache)

    if inv["total"] == 0:
        ui.warn(i18n.t("vw_games_none"))
        return
    # per-launcher summary
    rows = [(k, sum(g.get("size") or 0 for g in v), i18n.t("vw_games_count", n=len(v)))
            for k, v in inv["launchers"].items() if v]
    ui.size_table(rows, title=i18n.t("vw_storage_by_launcher"))
    # game list (rich table, sized + dated, no wrap noise)
    all_games = [(k, g) for k, v in inv["launchers"].items() for g in v]
    all_games.sort(key=lambda kg: kg[1].get("size") or 0, reverse=True)
    shown = all_games[:40]
    rows = [(g.get("name", ""), g.get("size"), launcher,
             ui.human_age(max(0, time.time() - g.get("mtime", 0))) if g.get("mtime") else "-")
            for launcher, g in shown]
    ui.console.print()
    ui.games_table(rows, title=i18n.t("vw_games_title"))
    if len(all_games) > len(shown):
        ui.console.print(ui.c(i18n.t("vw_games_more", n=len(all_games) - len(shown)), "dim"))
    ui.console.print(ui.c(i18n.t("vw_games_nodel"), "dim"))
    idx = ui.choose_index(i18n.t("vw_games_pick"),
                          len(shown), allow_zero=True)
    if not idx:
        return
    _launcher, g = shown[idx - 1]
    act = "O"
    try:
        act = input(ui.c(i18n.t("vw_games_action"), "cyan")).strip().upper() or "O"
    except (EOFError, KeyboardInterrupt):
        pass
    if act == "B":
        appid = g.get("appid") or ""
        if _launcher == "Steam" and appid:
            import steam
            steam.open_steam_store_page(appid)
        else:
            ui.warn(i18n.t("vw_store_steam_only"))
    else:
        games_mod.open_game_folder(g)


def view_duplicates(app: App) -> None:
    """[D] Duplicate file finder (content-hash verified, report only)."""
    ui.show_banner()
    big = app.cache.get("bigfiles") or []
    if len(big) < 4:
        ui.warn(i18n.t("vw_dup_need_scan"))
        return
    ui.info(i18n.t("vw_dup_searching", n=len(big)))
    stop = threading.Event()
    t0 = time.monotonic()
    with ui.ScanProgress(label=i18n.t("vw_prog_dupes")):
        res = files_mod.find_duplicates(big, stop=stop)
    groups = res["groups"]
    if not groups:
        ui.ok(i18n.t("vw_dup_none", t=f"{time.monotonic() - t0:.1f}"))
        return
    ui.console.print()
    ui.console.print(ui.c(i18n.t("vw_dup_groups", n=len(groups),
                                 v=ui.colorize(res['wasted_total'])),
                          "yellow", True))
    for gi, g in enumerate(groups, 1):
        ui.console.print(f"\n  [{gi}]  {ui.colorize(g['size'])}  x{len(g['paths'])}  "
                         + i18n.t("vw_dup_recoverable", v=ui.human(g['wasted'])))
        for p in g["paths"]:
            ui.console.print(ui.c(f"        {p}", "dim"))
    ui.console.print(ui.c(i18n.t("vw_dup_note"), "dim"))


def view_big_files(app: App) -> None:
    ui.show_banner()
    while True:
        big = app.cache.get("bigfiles") or []
        if not big:
            ui.warn(i18n.t("vw_no_cache_scan"))
            return
        threshold = app.settings["min_big_size"]
        selected = [b for b in big if b["size"] >= threshold][:20]
        ui.console.print(ui.c(i18n.t("vw_big_top", n=len(selected), v=ui.human(threshold)), "cyan", True))
        ui.console.print()
        ui.size_table([(os.path.basename(b["path"])[:44], b["size"],
                        f"{b.get('ext', '')}  {ui._short(b['path'], 46)}")
                       for b in selected])
        total = sum(b["size"] for b in selected)
        ui.console.print(ui.c(i18n.t("vw_shown_total", v=ui.human(total)), "dim"))
        ui.console.print(ui.c(i18n.t("vw_big_help"), "dim"))
        try:
            ch = input(ui.c("  " + i18n.t("st_choice"), "cyan")).strip().upper()
        except (EOFError, KeyboardInterrupt):
            return
        if not ch:
            return
        if ch.isdigit():
            app.settings["min_big_size"] = int(ch) * 1024 ** 3
        elif ch == "A":
            app.settings["min_big_size"] = 100 * 1024 * 1024
        elif ch == "E":
            idx = ui.choose_index(i18n.t("vw_big_explore"), len(selected))
            if idx:
                path = selected[idx - 1]["path"]
                folder = os.path.dirname(path)
                if os.path.isdir(folder):
                    try:
                        os.startfile(folder)  # type: ignore[attr-defined]
                    except OSError:
                        pass


def view_old_files(app: App) -> None:
    ui.show_banner()
    old = app.cache.get("oldfiles") or []
    if not old:
        ui.warn(i18n.t("vw_no_cache_scan"))
        return
    buckets = [("bl_30", 30), ("bl_90", 90), ("bl_180", 180),
               ("bl_1y", 365), ("bl_2y", 730)]
    for i, (bk, days) in enumerate(buckets, 1):
        items = files_mod.build_old_view(old, days, min_size=1 * 1024 * 1024, limit=100000)
        ui.console.print(i18n.t("vw_old_bucket", i=i, label=i18n.t(bk),
                               n=f"{len(items):>5}",
                               v=ui.colorize(sum(x['size'] for x in items))))
    ui.console.print(ui.c(i18n.t("vw_old_help"), "dim"))
    try:
        ch = input(ui.c(i18n.t("vw_old_prompt"), "cyan")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if not ch:
        return
    if ch == "C":
        days = app.settings["old_age_days"]
        cats = files_mod.old_summary_by_category(old, days)
        ui.console.print(ui.c(i18n.t("vw_old_cats_title", days=days), "yellow", True))
        # old_summary_by_category yields (cat, count, total_size)
        ui.size_table([(files_mod.category_label(cat), sz, i18n.t("cache_files", n=n))
                       for cat, n, sz in cats], title=i18n.t("vw_by_category"))
        ui.press_enter()
        return
    if ch.isdigit() and 1 <= int(ch) <= len(buckets):
        bk, days = buckets[int(ch) - 1]
        app.settings["old_age_days"] = days
        items = files_mod.build_old_view(old, days, min_size=1 * 1024 * 1024)
        ui.console.print(ui.c(i18n.t("vw_old_files_title", label=i18n.t(bk)), "cyan", True))
        ui.size_table([(os.path.basename(f["path"])[:42], f["size"],
                        f"{ui.human_age(max(0, time.time() - f.get('mtime', 0)))}  {ui._short(f['path'], 44)}")
                       for f in items[:20]])
        ui.press_enter()


def view_cleanup(app: App) -> None:
    ui.show_banner()
    ui.info(i18n.t("vw_cleanup_searching"))
    stop = threading.Event()
    with ui.ScanProgress(label=i18n.t("vw_prog_cleanup")):
        rep = cleanup.build_cleanup_report(app.cache, stop=stop,
                                           drives=app.ensure_drives())
    colors = {"SAFE": "green", "REVIEW": "yellow", "DANGER": "red"}
    # one global numbering shared with the interactive prompt below
    pool = [(level, it) for level in ("SAFE", "REVIEW") for it in rep[level.lower()]]
    pool_map = {(level, it["path"]): n for n, (level, it) in enumerate(pool, 1)}
    for level in ("SAFE", "REVIEW"):
        items = rep[level.lower()]
        if not items:
            continue
        total = sum(x["size"] for x in items)
        ui.console.print()
        ui.console.print(ui.c(f"  [{level}]  {len(items)} {i18n.t('rep_items')}  ·  {ui.human(total)}",
                              colors[level], True))
        for it in items[:25]:
            n = pool_map.get((level, it["path"]), "?")
            day = i18n.age_units()[2]
            age = f" · {it['age_days']} {day}" if it.get("age_days") else ""
            ui.console.print(f"   {n:>2}. {ui.colorize(it['size']):>12}  {it['path']}")
            ui.console.print(ui.c("       " + i18n.t("ci_reason", r=it['reason']) + age, "dim"))
        if len(items) > 25:
            ui.console.print(ui.c(f"   ... + {len(items) - 25}", "dim"))
    ui.console.print()
    if rep.get("advisories"):
        ui.console.print(ui.c("  " + i18n.t("cv_sys"), "magenta", True))
        for adv in rep["advisories"]:
            ui.console.print(f"    • {adv['name']}  {ui.colorize(adv['size'])}")
            ui.console.print(ui.c(f"      → {adv['advice']}", "dim"))
        ui.console.print()
    ui.console.print(ui.c("  " + i18n.t("cv_danger"), "red", True))
    for note in rep["danger_notes"]:
        ui.console.print(ui.c(f"    • {note}", "dim"))
    total_potential = rep["safe_total"] + rep["review_total"]
    state = i18n.t("cv_actif") if app.settings["dry_run"] else i18n.t("cv_off")
    ui.console.print(ui.c("\n  " + i18n.t("cv_potential", v=ui.human(total_potential), state=state),
                          "cyan", True))
    _cleanup_interactive(app, rep)



def _cleanup_interactive(app: App, rep: dict[str, Any]) -> None:
    pool = [(level, it) for level in ("SAFE", "REVIEW") for it in rep[level.lower()]]
    if not pool:
        return
    try:
        raw = input(ui.c("  " + i18n.t("ci_prompt") + " ", "cyan")).strip()

    except (EOFError, KeyboardInterrupt):
        return
    if not raw or not raw.isdigit():
        return
    idx = int(raw)
    if not (1 <= idx <= len(pool)):
        return
    level, item = pool[idx - 1]
    path = item["path"]
    ui.console.print()
    ui.console.print(ui.c(f"  [{level}]", "yellow", True))
    ui.console.print("  " + i18n.t("ci_path", p=path))
    ui.console.print("  " + i18n.t("ci_size", s=ui.colorize(item['size'])))
    ui.console.print(ui.c("  " + i18n.t("ci_reason", r=item['reason']), "dim"))
    try:
        choice = input(ui.c("  " + i18n.t("ci_action") + " ", "yellow")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if choice == "O":
        if os.path.isdir(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                ui.err(i18n.t("ci_cannot_open"))
        else:
            ui.warn(i18n.t("ci_missing"))
        return
    if choice != "S":
        ui.info(i18n.t("ci_kept"))
        return
    ok, why = safety.validate_delete_path(path)
    if not ok:
        ui.err(i18n.t("ci_refused", why=why))
        return
    deleter = app.deleter()
    if not app.settings["dry_run"]:
        if not ui.confirm(i18n.t("ci_confirm", p=path), False):
            ui.info(i18n.t("ci_cancelled"))
            return

    done, msg = deleter.delete(path, size=item["size"], reason=item["reason"])
    if done:
        ui.ok(f"{msg} - {ui.human(item['size'])}")
    else:
        ui.err(msg)
    ui.info(deleter.summary())


def view_express_cleanup(app: App) -> None:
    """[C] Express cleanup: caches + Recycle Bin + Downloads junk."""
    ui.show_banner()
    ui.info(i18n.t("xc_start"))
    stop = threading.Event()
    with ui.ScanProgress(label=i18n.t("xc_prog")):

        bundle = cleanup.find_express_items(app.cache, app.ensure_drives(), stop=stop)

    caches = bundle["caches"]
    recycle = bundle["recycle"]
    downloads = bundle["downloads"]

    # ---- summary strip ------------------------------------------------- #
    tot_c = sum(i["size"] for i in caches)
    tot_r = sum(i["size"] for i in recycle)
    tot_d = sum(i["size"] for i in downloads)
    ui.console.print()
    ui.console.print(ui.c(f"  {i18n.t('xc_caches'):15}: {ui.colorize(tot_c)}", "green", True))
    ui.console.print(ui.c(f"  {i18n.t('xc_bin'):15}: {ui.colorize(tot_r)}", "green", True))
    ui.console.print(ui.c(f"  {i18n.t('xc_downloads'):15}: {ui.colorize(tot_d)}", "yellow", True))
    ui.console.print(ui.c("  " + i18n.t("xc_total", v=ui.human(tot_c + tot_r + tot_d)) + "\n", "bold cyan"))


    deleter = app.deleter()
    deleted_any = False

    # ---- 1) caches ------------------------------------------------------ #
    if caches:
        caches.sort(key=lambda x: x["size"], reverse=True)
        ui.console.print(ui.c("  " + i18n.t("xc_cache_hdr", n=len(caches)), "green", True))
        for it in caches[:12]:
            ui.console.print(f"      {ui.colorize(it['size']):>12}  {it['path']}")
        if len(caches) > 12:
            ui.console.print(ui.c("      " + i18n.t("xc_more", n=len(caches) - 12), "dim"))
        if ui.confirm(i18n.t("xc_q_caches")):

            for it in caches:
                done, msg = deleter.delete(it["path"], size=it["size"], reason=it["reason"])
                deleted_any = deleted_any or done
                if not done:
                    ui.warn(f"  {it['path']} : {msg}")
            ui.ok(deleter.summary())

    # ---- 2) Recycle Bin ------------------------------------------------- #
    if recycle:
        for rb in recycle:
            ui.console.print(ui.c("\n  " + i18n.t("xc_bin_hdr", path=rb['path']), "green", True))
            ui.console.print(f"      {ui.colorize(rb['size']):>12}  " + i18n.t("xc_items", n=f"{rb['files']:,}"))
        if ui.confirm(i18n.t("xc_q_bin")):
            for rb in recycle:
                done, msg = cleanup.empty_recycle_bin(rb["path"][:2])
                if done:
                    ui.ok(i18n.t("xc_bin_done", drive=rb['path'][:2], msg=msg))
                else:
                    ui.err(i18n.t("xc_bin_done", drive=rb['path'][:2], msg=msg))


    # ---- 3) Downloads junk ---------------------------------------------- #
    if downloads:
        ui.console.print(ui.c("\n  " + i18n.t("xc_dl_hdr", n=len(downloads),
                              size=ui.human(cleanup.EXPRESS_MIN_FILE_SIZE)), "yellow", True))
        day = i18n.age_units()[2]
        ui.size_table([(os.path.basename(d["path"])[:40], d["size"],
                        f"{d['age_days']} {day}") for d in downloads[:20]],
                      title="")
        mode = ""
        try:
            mode = input(ui.c("  " + i18n.t("xc_dlmode") + " ", "cyan")).strip().upper()
        except (EOFError, KeyboardInterrupt):
            pass
        if mode == "S":
            done, _bytes = _express_downloads_multi(app, downloads)
            deleted_any = deleted_any or done
        elif mode != "0":
            idx = ui.choose_index(i18n.t("xc_pickfile"),
                                  min(20, len(downloads)), allow_zero=True)
            while idx:
                d = downloads[idx - 1]
                if not os.path.exists(d["path"]):
                    ui.warn(i18n.t("xc_filemissing"))
                else:
                    done, msg = deleter.delete(d["path"], size=d["size"], reason=i18n.t("cl_download"))
                    deleted_any = deleted_any or done
                    ui.ok(f"{os.path.basename(d['path'])} : {msg}") if done else ui.warn(msg)
                idx = ui.choose_index(i18n.t("xc_pickfile"),
                                      min(20, len(downloads)), allow_zero=True)

    if not (caches or recycle or downloads):
        ui.warn(i18n.t("xc_none"))
        return
    if not deleted_any:
        state = i18n.t("cv_actif") if app.settings["dry_run"] else i18n.t("cv_off")
        ui.console.print(ui.c("\n  " + i18n.t("xc_dryonly", state=state), "dim"))



def _express_downloads_multi(app: App, downloads: list[dict[str, Any]]) -> tuple[bool, int]:
    """Batch-trash Downloads files with one final confirmation.
    Returns (anything_done, total_bytes_selected)."""
    idxs = ui.choose_multi(i18n.t("dm_multi"),
                           min(20, len(downloads)))
    if not idxs:
        return False, 0
    picked = [downloads[i - 1] for i in idxs if os.path.exists(downloads[i - 1]["path"])]
    if not picked:
        ui.warn(i18n.t("dm_none"))
        return False, 0
    total = sum(f["size"] for f in picked)
    ui.console.print("  " + i18n.t("dm_count", n=len(picked), size=ui.human(total)))
    for f in picked[:10]:
        ui.console.print(ui.c(f"    · {f['path']}", "dim"))
    if len(picked) > 10:
        ui.console.print(ui.c(f"    ... + {len(picked) - 10}", "dim"))
    if not ui.confirm(i18n.t("dm_confirm", n=len(picked)), False):
        ui.info(i18n.t("ci_cancelled"))
        return False, 0

    deleter = app.deleter()
    done_count = 0
    for f in picked:
        done, msg = deleter.delete(f["path"], size=f["size"], reason=i18n.t("cl_download_multi"))
        done_count += 1 if done else 0
    ui.ok(deleter.summary())
    return done_count > 0, total


def view_report(app: App) -> None:
    ui.show_banner()
    if not app.have_full_scan():
        ui.warn(i18n.t("rp_nocache"))
        app.run_scan(quick=True)
    with ui.ScanProgress(label=i18n.t("rp_prog")):
        ensure_inventory(app)
        cl = cleanup.build_cleanup_report(app.cache, drives=app.ensure_drives())
    rep = reports.build_report(app.cache, app.ensure_drives(), cl)
    ui.console.print(reports.render_text(rep))
    ui.console.print()
    fmt = ui.ask(i18n.t("rp_export"))
    if fmt:
        try:
            path = reports.export(rep, fmt)
            ui.ok(i18n.t("rp_done", path=path))
        except OSError as e:
            ui.err(i18n.t("rp_err", e=e))



def view_search(app: App, initial: str = "") -> None:
    ui.show_banner()
    ui.console.print(ui.c(i18n.t("vw_search_help"), "dim"))
    try:
        term = initial or input(ui.c(i18n.t("vw_search_prompt"), "cyan")).strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not term:
        return
    kind, payload = files_mod.parse_command(term)
    if kind == "games":
        view_games(app)
        return
    if kind == "drive":
        drive = payload.upper().rstrip(":\\")
        rows = [b for b in app.cache.get("bigfiles", [])
                if b["path"].upper().startswith(drive)][:25]
        ui.size_table([(os.path.basename(b["path"])[:40], b["size"], ui._short(b["path"], 50))
                       for b in rows], title=i18n.t("vw_files_of", drive=drive))
        return
    if kind in ("large", "old", "files", "filter"):
        if kind == "large":
            spec = files_mod.parse_filter_expr(f"size>{payload}")
        elif kind == "old":
            spec = files_mod.parse_filter_expr(f"age>{payload}")
        elif kind == "files":
            spec = files_mod.parse_filter_expr(payload)
        else:
            spec = files_mod.parse_filter_expr(payload)
        src = list(app.cache.get("bigfiles", [])) + list(app.cache.get("oldfiles", []))
        seen: set[str] = set()
        uniq = []
        for f in sorted(src, key=lambda x: x["size"], reverse=True):
            if f["path"] not in seen:
                seen.add(f["path"])
                uniq.append(f)
        res = files_mod.apply_filters(uniq, spec)[:25]
        ui.console.print(ui.c(i18n.t("vw_search_filter", spec=files_mod.describe_spec(spec)), "dim"))
        ui.size_table([(os.path.basename(f["path"])[:40], f["size"], ui._short(f["path"], 50))
                       for f in res], title=i18n.t("vw_results"))
        return
    # plain search across everything cached
    res = files_mod.search_all(term, app.cache)
    counts = {k: len(v) for k, v in res.items() if v}
    if not counts:
        ui.warn(i18n.t("vw_search_nores", term=term))
        return
    if res["games"]:
        ui.console.print(ui.c(i18n.t("vw_sect_games"), "magenta", True))
        for g in res["games"][:10]:
            ui.console.print(f"    {g['name'][:30]:<30.30}  {ui.colorize(g.get('size') or 0):>12}  "
                             f"{ui.c(g.get('launcher', ''), 'dim')}  {ui._short(g.get('path', ''), 40)}")
    if res["apps"]:
        ui.console.print(ui.c(i18n.t("vw_sect_apps"), "magenta", True))
        for a in res["apps"][:10]:
            ui.console.print(f"    {a['name'][:30]:<30.30}  "
                             f"{ui.colorize(a.get('size') or 0) if a.get('size') else ui.c(i18n.t('na'), 'dim'):>12}")
    if res["files"]:
        ui.console.print(ui.c(i18n.t("vw_sect_files"), "magenta", True))
        for f in res["files"][:15]:
            ui.console.print(f"    {ui.colorize(f['size']):>12}  {ui._short(f['path'], 56)}")
    if res["dirs"]:
        ui.console.print(ui.c(i18n.t("vw_sect_dirs"), "magenta", True))
        for d in res["dirs"][:15]:
            ui.console.print(f"    {ui.colorize(d['size']):>12}  {ui._short(d['path'], 56)}")


def change_language() -> None:
    """Small submenu to switch + persist the UI language."""
    ui.console.print()
    ui.console.print(ui.c("  " + i18n.t("lang_title"), "cyan", True))
    codes = ", ".join(f"{code}={name}" for code, name in i18n.LANGS)
    ui.console.print(ui.c("  " + i18n.t("lang_list", codes=codes), "dim"))
    try:
        raw = input(ui.c("  " + i18n.t("lang_prompt") + " ", "cyan")).strip().lower()

    except (EOFError, KeyboardInterrupt):
        return
    if not raw:
        return
    code = i18n.save_lang(raw)
    name = i18n.LANG_NAMES.get(code, code)
    if code == i18n._normalize(raw):
        ui.ok(i18n.t("lang_set", name=name))
    else:
        ui.warn(i18n.t("lang_invalid", name=name))


def view_memory(app: App) -> None:
    """[M] Live RAM & background view.

    Shows real memory usage, the biggest memory consumers, and - when the
    native C++ core is available - the autostart items and running services.
    Works with or without the compiled core (pure-Python ctypes fallback).
    Never kills a process; the only action trims DiskTop's own working set.
    """
    ui.show_banner()
    ui.info(i18n.t("vw_mem_intro"))
    try:
        mem = memory.system_mem()
    except Exception as e:  # noqa: BLE001 - the view must never crash the menu
        ui.err(i18n.t("vw_error", e=e))
        return
    total = mem.get("total", 0)
    used = mem.get("used", 0)
    avail = mem.get("available", 0)
    load = float(mem.get("load", 0.0))
    pct = f"{load * 100:.0f}%"
    ui.console.print()
    ui.console.print(ui.c("  " + i18n.t("vw_mem_title"), "cyan", True))
    # usage bar, coloured by pressure
    bar_w = 28
    filled = int(round(min(1.0, load) * bar_w))
    bar = ui.c("\u2588" * filled, ui.severity_color(load)) + \
        ui.c("\u2591" * (bar_w - filled), "grey")
    ui.console.print(f"  [{bar}] {pct}")
    ui.console.print("   " + i18n.t("vw_mem_load",
                                    used=ui.human(used), total=ui.human(total), pct=pct))
    ui.console.print("   " + i18n.t("vw_mem_avail", avail=ui.human(avail)))
    src = i18n.t("vw_mem_src_native") if mem.get("source") == "native" \
        else i18n.t("vw_mem_src_python")
    ui.console.print(ui.c("   " + i18n.t("vw_mem_backend", b=src), "dim"))
    # top consumers table
    procs = memory.top_processes(15)
    if procs:
        rows = []
        for p in procs:
            note = f"pid {p.get('pid', 0)}  \u00b7  {i18n.t('vw_mem_col_threads')} {p.get('threads', 0)}"
            rows.append((str(p.get("name", ""))[:38], p.get("rss", 0), note))
        ui.size_table(rows, title=i18n.t("vw_mem_top_hdr"))
    else:
        ui.warn(i18n.t("vw_mem_none"))
    # autostart + services (native core only)
    auto = memory.autostart()
    if auto:
        ui.console.print(ui.c("  " + i18n.t("vw_mem_autostart_hdr"), "yellow", True))
        for it in auto[:20]:
            ui.console.print(f"    {it.get('name', '')[:26]:<26.26} "
                             + ui.c(it.get("source", "")[:16], "dim") + "  "
                             + ui.c(ui._short(it.get("command", ""), 40), "grey"))
        if len(auto) > 20:
            ui.console.print(ui.c(f"    ... + {len(auto) - 20}", "dim"))
    svcs = memory.running_services()
    if svcs:
        ui.console.print(ui.c("  " + i18n.t("vw_mem_svc_hdr", n=len(svcs)), "magenta", True))
    # safe action: trim this process's own working set
    ui.console.print(ui.c("  " + i18n.t("vw_mem_help"), "dim"))
    try:
        ch = input(ui.c("  " + i18n.t("vw_mem_trim_q"), "cyan")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if ch == "T":
        if memory.trim_working_set():
            ui.ok(i18n.t("vw_mem_trim_done"))
        else:
            ui.info(i18n.t("vw_mem_trim_no"))


def view_settings(app: App) -> None:
    ui.show_banner()
    ui.console.print(ui.c("  " + i18n.t("st_title"), "cyan", True))
    dry = i18n.t("st_dry_on") if app.settings["dry_run"] else i18n.t("st_dry_off")
    ui.console.print("   " + i18n.t("st_dry", state=dry))
    ui.console.print("   " + i18n.t("st_cache", path=cache_mod.cache_file()))
    ui.console.print("   " + i18n.t("st_rescan"))
    store = i18n.t("on") if app.settings["include_store_apps"] else i18n.t("off")
    ui.console.print("   " + i18n.t("st_store", state=store))
    name = i18n.LANG_NAMES.get(i18n.get_lang(), i18n.get_lang())
    ui.console.print("   " + i18n.t("st_lang", name=name))
    ui.console.print(ui.c("   " + i18n.t("st_back"), "dim"))
    try:
        ch = input(ui.c("  " + i18n.t("st_choice") + " ", "cyan")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if ch == "D":
        app.settings["dry_run"] = not app.settings["dry_run"]
        state = i18n.t("st_dry_enabled") if app.settings["dry_run"] else i18n.t("st_dry_disabled")
        ui.ok(i18n.t("st_dry_toggled", state=state))
        if not app.settings["dry_run"]:
            ui.warn(i18n.t("st_bin_warn"))
    elif ch == "C":
        cache_mod.clear()
        app.cache = cache_mod._empty()
        ui.ok(i18n.t("st_cache_cleared"))
    elif ch == "F":
        app.run_scan(quick=False, force=True)
    elif ch == "S":
        app.settings["include_store_apps"] = not app.settings["include_store_apps"]
    elif ch == "L":
        change_language()


# --------------------------------------------------------------------------- #
#  Main loop
# --------------------------------------------------------------------------- #
def main_menu(app: App) -> None:
    while True:
        ui.show_banner()
        ui.show_cache_info(app.cache.get("meta"))
        choice = ui.show_menu(app.settings_line())
        try:
            if choice == "1":
                view_full_analysis(app)
                ui.press_enter()
            elif choice == "2":
                view_quick(app)
                ui.press_enter()
            elif choice == "3":
                view_apps(app)
                ui.press_enter()
            elif choice == "4":
                view_games(app)
                ui.press_enter()
            elif choice == "5":
                view_big_files(app)
            elif choice == "6":
                view_old_files(app)
            elif choice == "D":
                view_duplicates(app)
                ui.press_enter()
            elif choice == "C":
                view_express_cleanup(app)
                ui.press_enter()
            elif choice == "7":
                view_cleanup(app)
                ui.press_enter()
            elif choice == "8":
                view_report(app)
                ui.press_enter()
            elif choice == "9":
                view_search(app)
                ui.press_enter()
            elif choice == "M":
                view_memory(app)
            elif choice in ("S", "P"):
                view_settings(app)
            elif choice in ("Q", "X"):
                ui.info(i18n.t("bye"))
                return
            elif choice in ("F5", "R"):
                app.run_scan(quick=False, force=True)
                view_drives(app)
                ui.press_enter()
            else:
                ui.warn(i18n.t("invalid_choice"))
        except KeyboardInterrupt:
            ui.warn(i18n.t("interrupted_menu"))

        except Exception as e:  # last-resort guard: never die on one view
            ui.err(i18n.t("vw_error", e=f"{e.__class__.__name__}: {e}"))
            ui.press_enter()


def _junction_selftest(safety_mod) -> bool:
    """Vérifie que les points de jonction sont détectés puis refusés.

    Retourne True si la protection fonctionne, ou si la machine n'a
    aucune jonction à tester (rien à vérifier dans ce cas).
    """
    profile = os.path.expanduser("~")
    for name in ("Local Settings", "Application Data"):
        p = os.path.join(profile, name)
        if not os.path.lexists(p):
            continue
        if not safety_mod.is_reparse_point(p):
            return False
        ok, why = safety_mod.validate_delete_path(p)
        if ok:
            return False
    return True


def selftest() -> int:
    """Used by install.bat to verify the installation."""
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        ui.ok(name) if cond else failures.append(name) or ui.err(name)

    check("imports modules", all(m for m in (cache_mod, scanner, ui, files_mod, safety)))
    check("vdf parse", steam_parse_test())
    check("size parser", files_mod.size_to_bytes("1.5 GB") == int(1.5 * 1024 ** 3))
    check("age parser", files_mod.age_to_seconds("2 years") == 2 * 365 * 86400)
    check("filters", files_mod.parse_filter_expr("size>10GB ext=.zip")["min_size"] == 10 * 1024 ** 3)
    check("safety: drive root refused", not safety.validate_delete_path("C:\\")[0])
    check("safety: windows refused", not safety.validate_delete_path("C:\\Windows\\System32")[0])
    check("safety: traversal refused", not safety.validate_delete_path("C:\\Users\\..\\..")[0])
    check("safety: junction refused", _junction_selftest(safety))
    # cache roundtrip in an ISOLATED temp file - never touch the real cache
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "diskscope_selftest_cache.json")
    orig_cache_file = cache_mod.cache_file
    try:
        cache_mod.cache_file = lambda: tmp  # type: ignore[assignment]
        cache_mod.save({"meta": {"x": 1}})
        data = cache_mod.load()
        check("cache roundtrip", isinstance(data, dict) and
              (data.get("meta") or {}).get("x") == 1)
    finally:
        cache_mod.cache_file = orig_cache_file
        try:
            os.unlink(tmp)
        except OSError:
            pass
    import cleanup  # noqa: F401  import check
    import applications  # noqa: F401
    import epic  # noqa: F401
    import games  # noqa: F401
    import reports  # noqa: F401
    # --- new-feature checks -------------------------------------------------
    check("age format", ui.human_age(800 * 86400).split()[0] == "2"
          and ui.human_age(45 * 86400).split()[0] == "45")

    check("multi-select parse", _selftest_multi())
    _dup = files_mod.find_duplicates(
        [{"path": p, "size": 3, "mtime": 0} for p in []])
    check("duplicates module", isinstance(_dup, dict) and "groups" in _dup)
    check("history api", hasattr(cache_mod, "push_history"))
    import reports as _rep
    check("csv export", hasattr(_rep, "render_csv"))
    check("i18n ready", i18n.get_lang() in dict(i18n.LANGS) and bool(i18n.t("menu_scan")))
    import memory as _mem  # noqa: F401  import check
    check("memory backend", isinstance(_mem.native_active(), bool) and
          _mem.system_mem().get("total", 0) >= 0)
    check("all modules import", not failures)
    if failures:
        return 1
    ui.ok(i18n.t("selftest_ready"))
    return 0



def _selftest_multi() -> bool:
    import builtins
    import ui as _ui
    ok = True
    for raw, want in [("1,3-5", [1, 3, 4, 5]), ("", []), ("9", []), ("abc", [])]:
        saved = builtins.input
        try:
            builtins.input = lambda *a, **k: raw
            got = _ui.choose_multi("t", 6)
            ok = ok and got == want
        finally:
            builtins.input = saved
    return ok


def steam_parse_test() -> bool:
    import steam
    vdf = steam.parse_vdf('"libraryfolders"\n{\n"0"\n{\n"path"\t"C:\\\\Program Files (x86)\tSteam"\n}\n}')
    return bool(vdf)


def main() -> int:
    if os.name == "nt":
        os.system("")  # enable ANSI escape sequences on legacy conhost
    i18n.load_lang()  # persisted choice (defaults to English)
    parser = argparse.ArgumentParser(prog="DiskTop",
                                     description=i18n.t("ap_desc"))
    parser.add_argument("--scan", action="store_true", help=i18n.t("ap_scan"))
    parser.add_argument("--quick", action="store_true", help=i18n.t("ap_quick"))
    parser.add_argument("--report", nargs="?", const="txt", choices=["txt", "json", "html", "csv"],
                        help=i18n.t("ap_report"))
    parser.add_argument("--search", metavar="TERM", help=i18n.t("ap_search"))
    parser.add_argument("--no-cache", action="store_true", help=i18n.t("ap_nocache"))
    parser.add_argument("--selftest", action="store_true", help=i18n.t("ap_selftest"))
    parser.add_argument("--empty-bin", action="store_true", help=i18n.t("ap_emptybin"))
    parser.add_argument("--lang", metavar="CODE", choices=[c for c, _ in i18n.LANGS],
                        help=i18n.t("ap_lang"))
    parser.add_argument("--version", action="version", version=f"DiskTop {APP_VERSION}")
    args = parser.parse_args()
    if args.lang:
        i18n.set_lang(args.lang)  # this run only, not persisted

    app = App(use_cache=not args.no_cache)

    try:
        if args.selftest:
            return selftest()
        if args.quick:
            view_quick(app)
            return 0
        if args.scan:
            app.run_scan(quick=False)
            view_drives(app)
            return 0
        if args.report:
            if not app.have_full_scan():
                app.run_scan(quick=True)
            ensure_inventory(app)
            cl = cleanup.build_cleanup_report(app.cache, drives=app.ensure_drives())
            rep = reports.build_report(app.cache, app.ensure_drives(), cl)
            path = reports.export(rep, args.report)
            ui.ok(i18n.t("rp_saved", path=path))
            return 0

        if args.search:
            view_search(app, args.search)
            return 0
        if args.empty_bin:
            ok, msg = cleanup.empty_recycle_bin()
            if ok:
                ui.ok(msg)
            else:
                ui.warn(msg)
            return 0
        main_menu(app)
        return 0
    except KeyboardInterrupt:
        print()
        ui.info(i18n.t("vw_interrupted"))
        return 130


if __name__ == "__main__":
    sys.exit(main())
