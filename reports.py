"""DiskScope CLI - reports.py

Global storage report: build from cached scan data, render as text /
JSON / HTML and export to report.txt / report.json / report.html.
"""
from __future__ import annotations

import html
import json
import os
import time
from typing import Any

import ui


def _label_for(name: str) -> str:
    n = name.lower()
    if "steam" in n:
        return "Steam"
    if "epic" in n:
        return "Epic"
    if "program files" in n:
        return "Applications"
    if n.startswith("users"):
        return "Users"
    if "download" in n:
        return "Downloads"
    if "windows" in n:
        return "Windows"
    return name


def build_report(cache: dict[str, Any], drives: list[dict[str, Any]],
                 cleanup: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aggregate everything worth reporting. Only cached REAL data."""
    top_users: list[dict[str, Any]] = []
    for mount, tree in (cache.get("trees") or {}).items():
        for ch in (tree.get("children") or [])[:12]:
            top_users.append({"name": _label_for(ch.get("name", ch.get("path", ""))),
                              "path": ch.get("path", ""), "size": ch.get("size", 0)})
    # merge same labels keeping max size path
    merged: dict[str, dict[str, Any]] = {}
    for t in top_users:
        cur = merged.get(t["name"])
        if cur is None or t["size"] > cur["size"]:
            merged[t["name"]] = t
    top_users = sorted(merged.values(), key=lambda x: x["size"], reverse=True)[:10]

    big = cache.get("bigfiles") or []
    largest = big[0] if big else None
    oldest_large = None
    if big:
        candidates = [b for b in big if b.get("size", 0) >= 100 * 1024 * 1024]
        if candidates:
            oldest_large = min(candidates, key=lambda x: x.get("mtime", 0))

    game_storage: dict[str, int] = {}
    games = cache.get("games") or {}
    if isinstance(games, dict):
        for launcher, lst in games.get("launchers", {}).items():
            game_storage[launcher] = sum(g.get("size") or 0 for g in lst)

    meta = cache.get("meta") or {}
    report: dict[str, Any] = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_scan": time.strftime("%Y-%m-%d %H:%M", time.localtime(meta.get("finished", 0))) if meta.get("finished") else "n/d",
        "scan_duration": meta.get("duration", 0),
        "drives": [{k: d.get(k) for k in ("mount", "total", "used", "free", "pct",
                                          "fstype", "kind", "label")} for d in drives],
        "top_space_users": top_users,
        "largest_file": largest,
        "oldest_large_file": oldest_large,
        "game_storage": game_storage,
        "game_total": sum(game_storage.values()),
        "apps_count": len(cache.get("apps") or []),
    }
    if cleanup:
        report["cleanup"] = {
            "safe_total": cleanup.get("safe_total", 0),
            "review_total": cleanup.get("review_total", 0),
            "safe_items": len(cleanup.get("safe", [])),
            "review_items": len(cleanup.get("review", [])),
            "safe": (cleanup.get("safe") or [])[:500],
            "review": (cleanup.get("review") or [])[:500],
        }
    report["bigfiles"] = big[:5000]
    report["advisories"] = (cleanup or {}).get("advisories") or []
    return report


# --------------------------------------------------------------------------- #
#  Renderers (plain text for files - no ANSI in exports)
# --------------------------------------------------------------------------- #
def render_text(r: dict[str, Any]) -> str:
    L: list[str] = []
    bar = "═" * 56
    L.append("╔" + bar + "╗")
    L.append("║" + "STORAGE REPORT".center(56) + "║")
    L.append("║" + f"généré {r['generated']}".center(56) + "║")
    L.append("╚" + bar + "╝")
    L.append("")
    L.append("DISQUES")
    for d in r["drives"]:
        L.append(f"  {d['mount']}  [{d.get('label') or '-'}]  ({d.get('fstype')}, {d.get('kind')})")
        L.append(f"    Total {ui.human(d['total']):>10}   "
                 f"Utilisé {ui.human(d['used']):>10} ({d['pct'] * 100:.0f}%)   "
                 f"Libre {ui.human(d['free']):>10}")
    L.append("")
    L.append(f"TOP SPACE USERS   (dernier scan : {r['last_scan']})")
    for i, t in enumerate(r["top_space_users"], 1):
        L.append(f"  {i:>2}. {t['name']:<28.28} {ui.human(t['size']):>10}")
        L.append(f"      {t['path']}")
    L.append("")
    cl = r.get("cleanup")
    if cl:
        L.append("POTENTIAL CLEANUP")
        L.append(f"  Safe    {ui.human(cl['safe_total']):>10}   ({cl['safe_items']} éléments)")
        L.append(f"  Review  {ui.human(cl['review_total']):>10}   ({cl['review_items']} éléments)")
        L.append("")
    lf = r.get("largest_file")
    if lf:
        L.append("LARGEST FILE")
        L.append(f"  {ui.human(lf['size'])}")
        L.append(f"  {lf['path']}")
        L.append("")
    ol = r.get("oldest_large_file")
    if ol:
        age = ui.human_age(max(0, time.time() - ol.get("mtime", 0)))
        L.append("OLDEST LARGE FILE (>100 MB)")
        L.append(f"  {ui.human(ol['size'])}   modifié il y a {age}")
        L.append(f"  {ol['path']}")
        L.append("")
    L.append("GAME STORAGE")
    if r["game_storage"]:
        for k, v in sorted(r["game_storage"].items(), key=lambda kv: kv[1], reverse=True):
            if v > 0:
                L.append(f"  {k:<22.22} {ui.human(v):>10}")
        L.append(f"  {'TOTAL':<22.22} {ui.human(r['game_total']):>10}")
    else:
        L.append("  aucun jeu détecté")
    L.append("")
    L.append(f"Applications détectées : {r['apps_count']}")
    return "\n".join(L)


def render_json(r: dict[str, Any]) -> str:
    return json.dumps(r, indent=2, ensure_ascii=False, default=str)


_CSS = """
body{font-family:Consolas,'Segoe UI',monospace;background:#0f1420;color:#d8e0f0;
     margin:2rem;line-height:1.5}
h1{color:#4fd6ff;border-bottom:2px solid #4fd6ff33;padding-bottom:.4rem}
h2{color:#9aa7ff;margin-top:1.6rem}
table{border-collapse:collapse;margin:.6rem 0}
td,th{border:1px solid #2a3350;padding:.25rem .8rem}
th{background:#1a2338;color:#7fe0ff}
.bar{background:#123;position:relative;display:inline-block;width:220px;height:14px;
     vertical-align:middle;border:1px solid #2a3350}
.bar>span{position:absolute;inset:0;background:linear-gradient(90deg,#2ad4ff,#7f6bff)}
.big{color:#ff7b7f}.warn{color:#ffd479}
"""


def render_html(r: dict[str, Any]) -> str:
    e = html.escape

    def drive_rows() -> str:
        rows = []
        for d in r["drives"]:
            pct = d["pct"] * 100
            cls = "big" if pct >= 90 else ("warn" if pct >= 75 else "")
            rows.append(
                f"<tr><td>{e(d['mount'])}</td><td>{ui.human(d['total'])}</td>"
                f"<td>{ui.human(d['used'])}</td><td>{ui.human(d['free'])}</td>"
                f"<td><span class='bar'><span style='width:{pct:.0f}%'></span></span> "
                f"{pct:.0f}%</td><td>{e(d.get('fstype') or '')}</td><td>{e(d.get('kind') or '')}</td></tr>")
        return "".join(rows)

    def top_rows() -> str:
        return "".join(
            f"<tr><td>{i}</td><td>{e(t['name'])}</td><td>{ui.human(t['size'])}</td>"
            f"<td style='color:#6b7699'>{e(t['path'])}</td></tr>"
            for i, t in enumerate(r["top_space_users"], 1))

    def game_rows() -> str:
        return "".join(
            f"<tr><td>{e(k)}</td><td>{ui.human(v)}</td></tr>"
            for k, v in sorted(r["game_storage"].items(), key=lambda kv: kv[1], reverse=True) if v > 0)

    cl = r.get("cleanup")
    cleanup_html = ""
    if cl:
        cleanup_html = f"""
<h2>Potential cleanup</h2>
<table><tr><th>Safe</th><td>{ui.human(cl['safe_total'])} ({cl['safe_items']} éléments)</td></tr>
<tr><th>Review</th><td>{ui.human(cl['review_total'])} ({cl['review_items']} éléments)</td></tr></table>"""

    def file_block(title: str, f: dict[str, Any] | None, extra: str = "") -> str:
        if not f:
            return ""
        return (f"<h2>{title}</h2><table><tr><th>Taille</th><td>{ui.human(f['size'])}</td></tr>"
                f"<tr><th>Chemin</th><td style='color:#6b7699'>{e(f['path'])}</td></tr>{extra}</table>")

    ol = r.get("oldest_large_file")
    ol_extra = ""
    if ol:
        age = ui.human_age(max(0, time.time() - ol.get("mtime", 0)))
        ol_extra = f"<tr><th>Âge</th><td>modifié il y a {age}</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>DiskScope - Storage Report</title><style>{_CSS}</style></head>
<body>
<h1>DiskScope CLI — Storage Report</h1>
<p>Généré le {e(r['generated'])} · dernier scan : {e(r['last_scan'])} ·
durée du scan : {ui._fmt_dur(r['scan_duration'])}</p>

<h2>Disques</h2>
<table><tr><th>Volume</th><th>Total</th><th>Utilisé</th><th>Libre</th><th>Usage</th>
<th>FS</th><th>Type</th></tr>{drive_rows()}</table>

<h2>Top space users</h2>
<table><tr><th>#</th><th>Catégorie</th><th>Taille</th><th>Chemin</th></tr>{top_rows()}</table>
{cleanup_html}
{file_block("Largest file", r.get("largest_file"))}
{file_block("Oldest large file", ol, ol_extra)}
<h2>Game storage</h2>
<table><tr><th>Launcher</th><th>Taille</th></tr>{game_rows()}
<tr><th>TOTAL</th><th>{ui.human(r['game_total'])}</th></tr></table>
<p>Applications détectées : {r['apps_count']}</p>
</body></html>"""


# --------------------------------------------------------------------------- #
#  Export
# --------------------------------------------------------------------------- #
def render_csv(r: dict[str, Any]) -> str:
    """CSV export: drives + big files + cleanup candidates, ';' separators
    (Excel-friendly for FR locales)."""
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, delimiter=";")

    w.writerow(["# Disques"])
    w.writerow(["mount", "label", "fs", "kind", "total", "used", "free"])
    for d in r.get("drives") or []:
        w.writerow([d.get("mount"), d.get("label"), d.get("fs"), d.get("kind"),
                    d.get("total", 0), d.get("total", 0) - d.get("free", 0),
                    d.get("free", 0)])

    w.writerow([])
    w.writerow(["# Gros fichiers"])
    w.writerow(["path", "size", "mtime"])
    for f in (r.get("bigfiles") or [])[:200]:
        w.writerow([f.get("path"), f.get("size", 0), f.get("mtime", 0)])

    cl = r.get("cleanup") or {}
    w.writerow([])
    w.writerow(["# Nettoyage SAFE"])
    w.writerow(["path", "size", "reason"])
    for it in cl.get("safe") or []:
        w.writerow([it.get("path"), it.get("size", 0), it.get("reason", "")])
    w.writerow(["# Nettoyage REVIEW"])
    w.writerow(["path", "size", "reason"])
    for it in cl.get("review") or []:
        w.writerow([it.get("path"), it.get("size", 0), it.get("reason", "")])
    return buf.getvalue()


def export(r: dict[str, Any], fmt: str, outdir: str | None = None) -> str:
    fmt = fmt.lower().lstrip(".")
    outdir = outdir or os.getcwd()
    name = {"txt": "report.txt", "json": "report.json", "html": "report.html",
            "htm": "report.html", "csv": "report.csv"}.get(fmt, "report.txt")
    path = os.path.join(outdir, name)
    if fmt == "json":
        content = render_json(r)
    elif fmt in ("html", "htm"):
        content = render_html(r)
    elif fmt == "csv":
        content = render_csv(r)
    else:
        content = render_text(r)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path
