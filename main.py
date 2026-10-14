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
        mode = "DRY RUN" if self.settings["dry_run"] else "DELETE ACTIF"
        return f"Mode: {mode}  |  Cache: {'on' if self.use_cache else 'off'}  |  [F5] Rescan"

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
                    ui.warn("Scan interrompu - résultats partiels conservés")
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
            ui.ok(f"Scan terminé : {total_files:,} fichiers en {ui._fmt_dur(duration)}")
        else:
            cache_mod.update_meta(self.cache, duration=time.monotonic() - t0,
                                  quick=True)
            if self.use_cache:
                cache_mod.save(self.cache)

    def ensure_scan(self, force: bool = False) -> None:
        if force or not self.have_full_scan():
            self.run_scan(quick=False, force=True)


def c_scan_head(mount: str) -> str:
    return ui.c(f"  ▶ Analyse de {mount}", "cyan", True)


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
        ui.err("Aucun disque détecté.")
        return
    ui.show_cache_info(app.cache.get("meta"))
    deltas = _drive_deltas(app)
    for d in ds:
        tops = [(t["name"], t["size"]) for t in (app.cache.get("top_folders") or {}).get(d["mount"], [])]
        ui.drive_panel(d, tops or None)
        delta = deltas.get(d["mount"])
        if delta:
            sign = "+" if delta > 0 else ""
            ui.console.print(ui.c(
                f"  depuis le scan précédent : {sign}{ui.human(abs(delta))} "
                f"{'utilisés en plus' if delta > 0 else 'libérés'}", "dim"))
    ui.console.print()


def view_full_analysis(app: App) -> None:
    ui.show_banner()
    ui.info("Analyse complète - tous les disques fixes vont être scannés.")
    if not ui.confirm("Lancer le scan complet ?", True):
        return
    app.run_scan(quick=False)
    view_drives(app)
    # navigation into a top folder
    ds = app.ensure_drives()
    for d in ds:
        tops = (app.cache.get("top_folders") or {}).get(d["mount"], [])
        if not tops:
            continue
        ui.console.print(ui.c(f"  Dossiers principaux de {d['mount']} :", "yellow", True))
        for i, t in enumerate(tops, 1):
            ui.console.print(f"   {i:>2}. {t['name']:<30.30} {ui.colorize(t['size'])}")
        idx = ui.choose_index(f"Explorer un dossier de {d['mount']} (0=passer)", len(tops), allow_zero=True)
        if idx:
            explore_folder(app, tops[idx - 1]["path"])


def explore_folder(app: App, path: str) -> None:
    """Deep-dive into one folder with a fresh bounded scan."""
    ui.console.print()
    ui.info(f"Analyse détaillée : {path}")
    with ui.ScanProgress(label="Analyse") as prog:
        cb = lambda f, b, e, p: prog.tick(f, e, p)  # noqa: E731
        try:
            tree, stats = scanner.scan_tree(path, path[:2], max_depth=scanner.DETAIL_DEPTH,
                                            progress=cb)
        except KeyboardInterrupt:
            ui.warn("Interrompu")
            return
    lines = ui.tree_lines(tree, max_depth=3, max_children=8)
    for ln in lines:
        ui.console.print("  " + ln)
    ui.console.print(ui.c(f"  Total: {ui.human(tree['size'])}  ·  {tree['files']:,} fichiers  ·  "
                          f"{tree['dirs']:,} sous-dossiers  ·  erreurs: {stats['errors']}", "dim"))
    # biggest files inside this folder
    big = sorted(app.cache.get("bigfiles", []), key=lambda x: x["size"], reverse=True)
    inner = [b for b in big if b["path"].lower().startswith(path.lower())][:10]
    if inner:
        ui.console.print(ui.c("  Plus gros fichiers ici :", "yellow", True))
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
                      title=f"Top dossiers {mount}  (cache)")
        return
    ui.info(f"Analyse rapide : tailles des dossiers de premier niveau ({mount})...")
    stop = threading.Event()

    def _prog(done: int, total: int, name: str, files: int) -> None:
        if _prog.prog is not None:
            _prog.prog.set_total(total)
            _prog.prog.tick(done, 0, name)
    _prog.prog = None  # type: ignore[attr-defined]

    with ui.ScanProgress(label=f"Top dossiers {mount}") as prog:
        _prog.prog = prog  # type: ignore[attr-defined]
        rows = scanner.top_level_sizes(mount, stop=stop, on_progress=_prog)
    ui.size_table([(name, size, f"{files:,} fichiers") for name, _p, size, files in rows[:15]],
                  title=f"Top dossiers {mount}")


def view_apps(app: App) -> None:
    ui.show_banner()
    ui.info("Détection des applications (registre + AppData + Store)...")
    stop = threading.Event()
    with ui.ScanProgress(label="Applications"):
        apps = _detect_apps_blocking(stop, app.settings["include_store_apps"])
    apps.sort(key=lambda a: a.get("size") or 0, reverse=True)
    known = [a for a in apps if a.get("size")]
    unknown = [a for a in apps if not a.get("size")]
    ui.console.print(ui.c(f"  {len(apps)} applications détectées  ·  "
                          f"{len(known)} avec taille réelle  ·  "
                          f"{len(unknown)} sans taille fiable", "dim"))
    rows = []
    for a in known[:40]:
        note = f"{a.get('publisher', '')[:24]}  {a.get('last_used_label', '')}"
        rows.append((a["name"][:38], a["size"], note))
    ui.size_table(rows, title="APPLICATIONS (tailles mesurées sur disque)")
    if unknown:
        ui.console.print(ui.c(f"  ... + {len(unknown)} applications sans taille fiable (registre)", "dim"))
    ui.console.print(ui.c("  * Dernière utilisation estimée d'après les dates de fichiers - "
                          "Windows n'expose pas la vraie date d'usage.", "dim"))
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
    ui.info("Détection des jeux (Steam, Epic, Battle.net, Ubisoft, EA, Riot, GOG, Xbox)...")
    stop = threading.Event()
    with ui.ScanProgress(label="Jeux"):
        try:
            inv = games_mod.detect_games(stop=stop)
        except Exception as e:  # never crash the menu on one launcher
            ui.err(f"Erreur détection jeux : {e}")
            return
    app.cache["games"] = {"launchers": {k: [{kk: g.get(kk) for kk in ("name", "path", "size", "appid", "mtime")}
                                            for g in v] for k, v in inv["launchers"].items()}}
    if app.use_cache:
        cache_mod.save(app.cache)

    if inv["total"] == 0:
        ui.warn("Aucun jeu détecté sur cette machine (aucune donnée locale trouvée).")
        return
    # per-launcher summary
    rows = [(k, sum(g.get("size") or 0 for g in v), f"{len(v)} jeux")
            for k, v in inv["launchers"].items() if v]
    ui.size_table(rows, title="STORAGE PAR LAUNCHER")
    # game list (rich table, sized + dated, no wrap noise)
    all_games = [(k, g) for k, v in inv["launchers"].items() for g in v]
    all_games.sort(key=lambda kg: kg[1].get("size") or 0, reverse=True)
    shown = all_games[:40]
    rows = [(g.get("name", ""), g.get("size"), launcher,
             ui.human_age(max(0, time.time() - g.get("mtime", 0))) if g.get("mtime") else "-")
            for launcher, g in shown]
    ui.console.print()
    ui.games_table(rows, title="JEUX - tailles réelles mesurées sur disque")
    if len(all_games) > len(shown):
        ui.console.print(ui.c(f"  ... + {len(all_games) - len(shown)} autres jeux", "dim"))
    ui.console.print(ui.c("  Aucun jeu n'est jamais supprimé automatiquement.", "dim"))
    idx = ui.choose_index("N° de jeu : [O] dossier  ·  [B] page boutique  ·  0=retour",
                          len(shown), allow_zero=True)
    if not idx:
        return
    _launcher, g = shown[idx - 1]
    act = "O"
    try:
        act = input(ui.c("  [O]uvrir le dossier / [B]outique > ", "cyan")).strip().upper() or "O"
    except (EOFError, KeyboardInterrupt):
        pass
    if act == "B":
        appid = g.get("appid") or ""
        if _launcher == "Steam" and appid:
            import steam
            steam.open_steam_store_page(appid)
        else:
            ui.warn("Page boutique disponible pour les jeux Steam uniquement.")
    else:
        games_mod.open_game_folder(g)


def view_duplicates(app: App) -> None:
    """[D] Duplicate file finder (content-hash verified, report only)."""
    ui.show_banner()
    big = app.cache.get("bigfiles") or []
    if len(big) < 4:
        ui.warn("Analyse complète requise d'abord (menu 1) - le chercheur de "
                "doublons travaille sur les plus gros fichiers recensés.")
        return
    ui.info(f"Recherche de doublons parmi les {len(big)} plus gros fichiers "
            "(hash SHA-256 partiel puis complet)...")
    stop = threading.Event()
    t0 = time.monotonic()
    with ui.ScanProgress(label="Doublons"):
        res = files_mod.find_duplicates(big, stop=stop)
    groups = res["groups"]
    if not groups:
        ui.ok(f"Aucun doublon détecté parmi les gros fichiers "
              f"({time.monotonic() - t0:.1f}s).")
        return
    ui.console.print()
    ui.console.print(ui.c(f"  {len(groups)} groupes de doublons  ·  espace "
                          f"récupérable : {ui.colorize(res['wasted_total'])}",
                          "yellow", True))
    for gi, g in enumerate(groups, 1):
        ui.console.print(f"\n  [{gi}]  {ui.colorize(g['size'])}  x{len(g['paths'])}  "
                         f"(récupérable : {ui.human(g['wasted'])})")
        for p in g["paths"]:
            ui.console.print(ui.c(f"        {p}", "dim"))
    ui.console.print(ui.c("\n  Aucune suppression automatique : comparez avant "
                          "d'agir ( menu 5 ou 7 pour traiter un fichier).", "dim"))


def view_big_files(app: App) -> None:
    ui.show_banner()
    while True:
        big = app.cache.get("bigfiles") or []
        if not big:
            ui.warn("Aucun scan en cache. Lancez l'analyse complète [1] d'abord.")
            return
        threshold = app.settings["min_big_size"]
        selected = [b for b in big if b["size"] >= threshold][:20]
        ui.console.print(ui.c(f"  TOP {len(selected)} GROS FICHIERS  (seuil : {ui.human(threshold)})", "cyan", True))
        ui.console.print()
        ui.size_table([(os.path.basename(b["path"])[:44], b["size"],
                        f"{b.get('ext', '')}  {ui._short(b['path'], 46)}")
                       for b in selected])
        total = sum(b["size"] for b in selected)
        ui.console.print(ui.c(f"  Total affiché : {ui.human(total)}", "dim"))
        ui.console.print(ui.c("  [1-9] seuil en Go  ·  [A] tous (>100 Mo)  ·  [E] explorer  ·  [Entrée] retour", "dim"))
        try:
            ch = input(ui.c("  Choix > ", "cyan")).strip().upper()
        except (EOFError, KeyboardInterrupt):
            return
        if not ch:
            return
        if ch.isdigit():
            app.settings["min_big_size"] = int(ch) * 1024 ** 3
        elif ch == "A":
            app.settings["min_big_size"] = 100 * 1024 * 1024
        elif ch == "E":
            idx = ui.choose_index("Numéro du fichier à explorer", len(selected))
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
        ui.warn("Aucun scan en cache. Lancez l'analyse complète [1] d'abord.")
        return
    buckets = [("30 jours", 30), ("90 jours", 90), ("180 jours", 180),
               ("1 an", 365), ("2 ans", 730)]
    for i, (label, days) in enumerate(buckets, 1):
        items = files_mod.build_old_view(old, days, min_size=1 * 1024 * 1024, limit=100000)
        ui.console.print(f"   [{i}] Non modifiés depuis {label:<9} : {len(items):>5} fichiers, "
                         f"{ui.colorize(sum(x['size'] for x in items))}")
    ui.console.print(ui.c("  [C] par catégorie  ·  [Entrée] retour", "dim"))
    try:
        ch = input(ui.c("  Bucket > ", "cyan")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if not ch:
        return
    if ch == "C":
        days = app.settings["old_age_days"]
        cats = files_mod.old_summary_by_category(old, days)
        ui.console.print(ui.c(f"  Catégories (>{days} jours) :", "yellow", True))
        ui.size_table([(files_mod.CATEGORY_LABELS.get(c, c), total, f"{n} fichiers")
                       for c, (total, n) in cats], title="PAR CATÉGORIE")
        ui.press_enter()
        return
    if ch.isdigit() and 1 <= int(ch) <= len(buckets):
        label, days = buckets[int(ch) - 1]
        app.settings["old_age_days"] = days
        items = files_mod.build_old_view(old, days, min_size=1 * 1024 * 1024)
        ui.console.print(ui.c(f"  FICHIERS ANCIENS (> {label}, > 1 Mo)", "cyan", True))
        ui.size_table([(os.path.basename(f["path"])[:42], f["size"],
                        f"{ui.human_age(max(0, time.time() - f.get('mtime', 0)))}  {ui._short(f['path'], 44)}")
                       for f in items[:20]])
        ui.press_enter()


def view_cleanup(app: App) -> None:
    ui.show_banner()
    ui.info("Recherche de nettoyage potentiel...")
    stop = threading.Event()
    with ui.ScanProgress(label="Nettoyage"):
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
        ui.console.print(ui.c(f"  [{level}]  {len(items)} éléments  ·  {ui.human(total)}",
                              colors[level], True))
        for it in items[:25]:
            n = pool_map.get((level, it["path"]), "?")
            age = f" · {it['age_days']} j" if it.get("age_days") else ""
            ui.console.print(f"   {n:>2}. {ui.colorize(it['size']):>12}  {it['path']}")
            ui.console.print(ui.c(f"       Raison : {it['reason']}{age}", "dim"))
        if len(items) > 25:
            ui.console.print(ui.c(f"   ... + {len(items) - 25}", "dim"))
    ui.console.print()
    if rep.get("advisories"):
        ui.console.print(ui.c("  [SYSTEME] Gros postes de nettoyage officiels :", "magenta", True))
        for adv in rep["advisories"]:
            ui.console.print(f"    • {adv['name']}  {ui.colorize(adv['size'])}")
            ui.console.print(ui.c(f"      → {adv['advice']}", "dim"))
        ui.console.print()
    ui.console.print(ui.c("  [DANGER] Jamais proposés :", "red", True))
    for note in rep["danger_notes"]:
        ui.console.print(ui.c(f"    • {note}", "dim"))
    total_potential = rep["safe_total"] + rep["review_total"]
    ui.console.print(ui.c(f"\n  Libérable potentiellement : {ui.human(total_potential)} "
                          f"(dry run {'ACTIF' if app.settings['dry_run'] else 'inactif'})",
                          "cyan", True))
    _cleanup_interactive(app, rep)


def _cleanup_interactive(app: App, rep: dict[str, Any]) -> None:
    pool = [(level, it) for level in ("SAFE", "REVIEW") for it in rep[level.lower()]]
    if not pool:
        return
    try:
        raw = input(ui.c("  N° d'élément à traiter (vide = retour) > ", "cyan")).strip()
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
    ui.console.print(f"  Chemin : {path}")
    ui.console.print(f"  Taille : {ui.colorize(item['size'])}")
    ui.console.print(ui.c(f"  Raison : {item['reason']}", "dim"))
    try:
        choice = input(ui.c("  [S]upprimer  [K]eep  [O]uvrir le dossier > ", "yellow")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if choice == "O":
        if os.path.isdir(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                ui.err("Impossible d'ouvrir le dossier.")
        else:
            ui.warn("Le chemin n'existe plus.")
        return
    if choice != "S":
        ui.info("Conservé.")
        return
    ok, why = safety.validate_delete_path(path)
    if not ok:
        ui.err(f"Suppression refusée : {why}")
        return
    deleter = app.deleter()
    if not app.settings["dry_run"]:
        if not ui.confirm(f"Confirmer l'envoi à la CORBEILLE de :\n  {path}", False):
            ui.info("Annulé.")
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
    ui.info("Nettoyage express : caches, corbeille, gros téléchargements...")
    stop = threading.Event()
    with ui.ScanProgress(label="Nettoyage express"):
        bundle = cleanup.find_express_items(app.cache, app.ensure_drives(), stop=stop)

    caches = bundle["caches"]
    recycle = bundle["recycle"]
    downloads = bundle["downloads"]

    # ---- summary strip ------------------------------------------------- #
    tot_c = sum(i["size"] for i in caches)
    tot_r = sum(i["size"] for i in recycle)
    tot_d = sum(i["size"] for i in downloads)
    ui.console.print()
    ui.console.print(ui.c(f"  Caches/Temp     : {ui.colorize(tot_c)}", "green", True))
    ui.console.print(ui.c(f"  Corbeille       : {ui.colorize(tot_r)}", "green", True))
    ui.console.print(ui.c(f"  Téléchargements : {ui.colorize(tot_d)}", "yellow", True))
    ui.console.print(ui.c(f"  TOTAL récupérable : {ui.human(tot_c + tot_r + tot_d)}\n", "bold cyan"))

    deleter = app.deleter()
    deleted_any = False

    # ---- 1) caches ------------------------------------------------------ #
    if caches:
        caches.sort(key=lambda x: x["size"], reverse=True)
        ui.console.print(ui.c(f"  [1] CACHES & TEMP  ({len(caches)} éléments)", "green", True))
        for it in caches[:12]:
            ui.console.print(f"      {ui.colorize(it['size']):>12}  {it['path']}")
        if len(caches) > 12:
            ui.console.print(ui.c(f"      ... + {len(caches) - 12} autres", "dim"))
        if ui.confirm("Vider tous ces caches/temp ?"):
            for it in caches:
                done, msg = deleter.delete(it["path"], size=it["size"], reason=it["reason"])
                deleted_any = deleted_any or done
                if not done:
                    ui.warn(f"  {it['path']} : {msg}")
            ui.ok(deleter.summary())

    # ---- 2) Recycle Bin ------------------------------------------------- #
    if recycle:
        for rb in recycle:
            ui.console.print(ui.c(f"\n  [2] CORBEILLE {rb['path']}", "green", True))
            ui.console.print(f"      {ui.colorize(rb['size']):>12}  {rb['files']:,} éléments")
        if ui.confirm("Vider la corbeille ? (définitif, via l'API Windows)"):
            for rb in recycle:
                done, msg = cleanup.empty_recycle_bin(rb["path"][:2])
                if done:
                    ui.ok(f"Corbeille {rb['path'][:2]} : {msg}")
                else:
                    ui.err(f"Corbeille {rb['path'][:2]} : {msg}")

    # ---- 3) Downloads junk ---------------------------------------------- #
    if downloads:
        ui.console.print(ui.c(f"\n  [3] TELECHARGEMENTS  ({len(downloads)} fichiers de "
                              f"> {ui.human(cleanup.EXPRESS_MIN_FILE_SIZE)})", "yellow", True))
        ui.size_table([(os.path.basename(d["path"])[:40], d["size"],
                        f"{d['age_days']} j") for d in downloads[:20]],
                      title="")
        mode = ""
        try:
            mode = input(ui.c("  [S]élection multiple  ·  [Entrée] un par un  ·  "
                              "[0] passer > ", "cyan")).strip().upper()
        except (EOFError, KeyboardInterrupt):
            pass
        if mode == "S":
            done, _bytes = _express_downloads_multi(app, downloads)
            deleted_any = deleted_any or done
        elif mode != "0":
            idx = ui.choose_index("N° du fichier (0=fin)",
                                  min(20, len(downloads)), allow_zero=True)
            while idx:
                d = downloads[idx - 1]
                if not os.path.exists(d["path"]):
                    ui.warn("Le fichier n'existe plus.")
                else:
                    done, msg = deleter.delete(d["path"], size=d["size"], reason="téléchargement")
                    deleted_any = deleted_any or done
                    ui.ok(f"{os.path.basename(d['path'])} : {msg}") if done else ui.warn(msg)
                idx = ui.choose_index("N° du fichier (0=fin)",
                                      min(20, len(downloads)), allow_zero=True)

    if not (caches or recycle or downloads):
        ui.warn("Rien à nettoyer - tout est déjà propre !")
        return
    if not deleted_any:
        ui.console.print(ui.c("\n  Rien n'a été supprimé (dry run "
                              f"{'ACTIF' if app.settings['dry_run'] else 'inactif'}).", "dim"))


def _express_downloads_multi(app: App, downloads: list[dict[str, Any]]) -> tuple[bool, int]:
    """Batch-trash Downloads files with one final confirmation.
    Returns (anything_done, total_bytes_selected)."""
    idxs = ui.choose_multi("N° à mettre à la corbeille (ex : 1,3-5 ; vide=annuler)",
                           min(20, len(downloads)))
    if not idxs:
        return False, 0
    picked = [downloads[i - 1] for i in idxs if os.path.exists(downloads[i - 1]["path"])]
    if not picked:
        ui.warn("Aucun fichier sélectionné n'existe plus.")
        return False, 0
    total = sum(f["size"] for f in picked)
    ui.console.print(f"  {len(picked)} fichier(s), {ui.human(total)} :")
    for f in picked[:10]:
        ui.console.print(ui.c(f"    · {f['path']}", "dim"))
    if len(picked) > 10:
        ui.console.print(ui.c(f"    ... + {len(picked) - 10}", "dim"))
    if not ui.confirm(f"Envoyer ces {len(picked)} fichier(s) à la corbeille ?", False):
        ui.info("Annulé.")
        return False, 0
    deleter = app.deleter()
    done_count = 0
    for f in picked:
        done, msg = deleter.delete(f["path"], size=f["size"], reason="téléchargement (multi)")
        done_count += 1 if done else 0
    ui.ok(deleter.summary())
    return done_count > 0, total


def view_report(app: App) -> None:
    ui.show_banner()
    if not app.have_full_scan():
        ui.warn("Aucune analyse complète en cache - lancement rapide d'un scan...")
        app.run_scan(quick=True)
    with ui.ScanProgress(label="Rapport"):
        ensure_inventory(app)
        cl = cleanup.build_cleanup_report(app.cache, drives=app.ensure_drives())
    rep = reports.build_report(app.cache, app.ensure_drives(), cl)
    ui.console.print(reports.render_text(rep))
    ui.console.print()
    fmt = ui.ask("Exporter ? [txt/json/html/csv] (vide = retour)")
    if fmt:
        try:
            path = reports.export(rep, fmt)
            ui.ok(f"Rapport exporté : {path}")
        except OSError as e:
            ui.err(f"Export impossible : {e}")


def view_search(app: App, initial: str = "") -> None:
    ui.show_banner()
    ui.console.print(ui.c("  Commandes : /large 10GB · /old 1year · /files .iso · /games · /drive D: · "
                          "texte = recherche", "dim"))
    try:
        term = initial or input(ui.c("  Rechercher > ", "cyan")).strip()
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
                       for b in rows], title=f"FICHIERS {drive}:")
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
        ui.console.print(ui.c(f"  Filtre : {files_mod.describe_spec(spec)}", "dim"))
        ui.size_table([(os.path.basename(f["path"])[:40], f["size"], ui._short(f["path"], 50))
                       for f in res], title="RÉSULTATS")
        return
    # plain search across everything cached
    res = files_mod.search_all(term, app.cache)
    counts = {k: len(v) for k, v in res.items() if v}
    if not counts:
        ui.warn(f"Aucun résultat pour '{term}' (le cache ne couvre que le dernier scan).")
        return
    if res["games"]:
        ui.console.print(ui.c("  JEUX", "magenta", True))
        for g in res["games"][:10]:
            ui.console.print(f"    {g['name'][:30]:<30.30}  {ui.colorize(g.get('size') or 0):>12}  "
                             f"{ui.c(g.get('launcher', ''), 'dim')}  {ui._short(g.get('path', ''), 40)}")
    if res["apps"]:
        ui.console.print(ui.c("  APPLICATIONS", "magenta", True))
        for a in res["apps"][:10]:
            ui.console.print(f"    {a['name'][:30]:<30.30}  "
                             f"{ui.colorize(a.get('size') or 0) if a.get('size') else ui.c('n/d', 'dim'):>12}")
    if res["files"]:
        ui.console.print(ui.c("  FICHIERS", "magenta", True))
        for f in res["files"][:15]:
            ui.console.print(f"    {ui.colorize(f['size']):>12}  {ui._short(f['path'], 56)}")
    if res["dirs"]:
        ui.console.print(ui.c("  DOSSIERS", "magenta", True))
        for d in res["dirs"][:15]:
            ui.console.print(f"    {ui.colorize(d['size']):>12}  {ui._short(d['path'], 56)}")


def view_settings(app: App) -> None:
    ui.show_banner()
    ui.console.print(ui.c("  PARAMÈTRES", "cyan", True))
    ui.console.print(f"   [D] Dry run : {'ACTIF (aucune suppression réelle)' if app.settings['dry_run'] else 'INACTIF (corbeille réelle)'}")
    ui.console.print(f"   [C] Vider le cache ({cache_mod.cache_file()})")
    ui.console.print("   [F] Rescan complet [F5]")
    ui.console.print("   [S] Store apps : " + ("on" if app.settings["include_store_apps"] else "off"))
    ui.console.print("   [Entrée] retour")
    try:
        ch = input(ui.c("  Choix > ", "cyan")).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if ch == "D":
        app.settings["dry_run"] = not app.settings["dry_run"]
        ui.ok(f"Dry run {'activé' if app.settings['dry_run'] else 'désactivé'}")
        if not app.settings["dry_run"]:
            ui.warn("Les suppressions enverront à la CORBEILLE (send2trash), jamais en dur.")
    elif ch == "C":
        cache_mod.clear()
        app.cache = cache_mod._empty()
        ui.ok("Cache vidé.")
    elif ch == "F":
        app.run_scan(quick=False, force=True)
    elif ch == "S":
        app.settings["include_store_apps"] = not app.settings["include_store_apps"]


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
            elif choice in ("S", "P"):
                view_settings(app)
            elif choice in ("Q", "X"):
                ui.info("À bientôt !")
                return
            elif choice in ("F5", "R"):
                app.run_scan(quick=False, force=True)
                view_drives(app)
                ui.press_enter()
            else:
                ui.warn("Choix invalide.")
        except KeyboardInterrupt:
            ui.warn("Interrompu - retour au menu.")
        except Exception as e:  # last-resort guard: never die on one view
            ui.err(f"Erreur : {e.__class__.__name__}: {e}")
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
        if ok or "jonction" not in why:
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
    check("french ages", ui.human_age(800 * 86400) == "2 ans"
          and ui.human_age(45 * 86400) == "45 j")
    check("multi-select parse", _selftest_multi())
    _dup = files_mod.find_duplicates(
        [{"path": p, "size": 3, "mtime": 0} for p in []])
    check("duplicates module", isinstance(_dup, dict) and "groups" in _dup)
    check("history api", hasattr(cache_mod, "push_history"))
    import reports as _rep
    check("csv export", hasattr(_rep, "render_csv"))
    check("all modules import", not failures)
    if failures:
        return 1
    ui.ok("DiskScope est prêt. Lancez run.bat !")
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
    parser = argparse.ArgumentParser(prog="DiskScope CLI",
                                     description="Windows Storage Analyzer")
    parser.add_argument("--scan", action="store_true", help="full scan then exit summary")
    parser.add_argument("--quick", action="store_true", help="quick drive overview")
    parser.add_argument("--report", nargs="?", const="txt", choices=["txt", "json", "html", "csv"],
                        help="build report and export")
    parser.add_argument("--search", metavar="TERM", help="one-shot search")
    parser.add_argument("--no-cache", action="store_true", help="ignore saved cache")
    parser.add_argument("--selftest", action="store_true", help="verify installation")
    parser.add_argument("--empty-bin", action="store_true",
                        help="vide la corbeille (Recycle Bin) via l'API Windows")
    parser.add_argument("--version", action="version", version=f"DiskScope CLI {APP_VERSION}")
    args = parser.parse_args()

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
            ui.ok(f"Rapport : {path}")
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
        ui.info("Interrompu.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
