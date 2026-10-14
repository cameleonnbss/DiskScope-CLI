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

import i18n
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
    report["insights"] = build_insights(report)
    return report


# --------------------------------------------------------------------------- #
#  Offline recommendations (heuristic rules over the REAL scan data).
#  No model, no API, no network - stdlib only, deterministic & testable.
# --------------------------------------------------------------------------- #
def build_insights(r: dict[str, Any]) -> list[tuple[str, str]]:
    """Return a list of (level, text) actionable insights.

    level is one of: "danger" (critical), "warn", "good", "info".
    """
    out: list[tuple[str, str]] = []
    for d in r.get("drives") or []:
        pct = d.get("pct") or 0.0
        mount = d.get("mount", "?")
        free = d.get("free", 0)
        if pct >= 0.90:
            out.append(("danger", i18n.t("ins_full", mount=mount,
                                         pct=f"{pct * 100:.0f}", free=ui.human(free))))
        elif pct >= 0.75:
            out.append(("warn", i18n.t("ins_high", mount=mount,
                                       pct=f"{pct * 100:.0f}", free=ui.human(free))))
    cl = r.get("cleanup") or {}
    if cl.get("safe_total"):
        out.append(("good", i18n.t("ins_cache", size=ui.human(cl["safe_total"]),
                                   n=cl.get("safe_items", 0))))
    if cl.get("review_total"):
        out.append(("info", i18n.t("ins_review", size=ui.human(cl["review_total"]))))
    for adv in (r.get("advisories") or [])[:3]:
        out.append(("info", i18n.t("ins_adv", name=adv.get('name', ''),
                                   size=ui.human(adv.get('size', 0) or 0),
                                   advice=adv.get('advice', ''))))
    lf = r.get("largest_file")
    if lf and (lf.get("size") or 0) >= 2 * 1024 ** 3:
        out.append(("info", i18n.t("ins_largest", size=ui.human(lf['size']), path=lf['path'])))
    ol = r.get("oldest_large_file")
    if ol:
        age = ui.human_age(max(0, time.time() - ol.get("mtime", 0)))
        out.append(("info", i18n.t("ins_oldest", age=age, path=ol['path'])))
    gs = r.get("game_storage") or {}
    if gs:
        top = max(gs.items(), key=lambda kv: kv[1])
        if top[1] > 0:
            out.append(("info", i18n.t("ins_games", size=ui.human(r.get('game_total', 0)),
                                       top=top[0])))
    tu = r.get("top_space_users") or []
    if tu and (tu[0].get("size") or 0) > 0:
        out.append(("info", i18n.t("ins_topuser", name=tu[0]['name'],
                                   size=ui.human(tu[0]['size']))))
    if not out:
        out.append(("good", i18n.t("ins_clean")))
    return out



_INS_MARK = {"danger": "[!]", "warn": "[~]", "good": "[+]", "info": "[-]"}


# --------------------------------------------------------------------------- #
#  Renderers (plain text for files - no ANSI in exports)
# --------------------------------------------------------------------------- #
def render_text(r: dict[str, Any]) -> str:
    L: list[str] = []
    bar = "═" * 56
    L.append("╔" + bar + "╗")
    L.append("║" + i18n.t("rep_title").center(56) + "║")
    L.append("║" + i18n.t("rep_generated", ts=r['generated']).center(56) + "║")
    L.append("╚" + bar + "╝")
    L.append("")
    L.append(i18n.t("rep_disks"))
    for d in r["drives"]:
        L.append(f"  {d['mount']}  [{d.get('label') or '-'}]  ({d.get('fstype')}, {d.get('kind')})")
        L.append(f"    {i18n.t('rep_total')} {ui.human(d['total']):>10}   "
                 f"{i18n.t('rep_used')} {ui.human(d['used']):>10} ({d['pct'] * 100:.0f}%)   "
                 f"{i18n.t('rep_free')} {ui.human(d['free']):>10}")
    L.append("")
    L.append(i18n.t("rep_top_users") + "   " + i18n.t("rep_last_scan", ts=r['last_scan']))
    for i, t_ in enumerate(r["top_space_users"], 1):
        L.append(f"  {i:>2}. {t_['name']:<28.28} {ui.human(t_['size']):>10}")
        L.append(f"      {t_['path']}")
    L.append("")
    cl = r.get("cleanup")
    if cl:
        L.append(i18n.t("rep_potential"))
        L.append(f"  Safe    {ui.human(cl['safe_total']):>10}   ({cl['safe_items']} {i18n.t('rep_items')})")
        L.append(f"  Review  {ui.human(cl['review_total']):>10}   ({cl['review_items']} {i18n.t('rep_items')})")
        L.append("")
    lf = r.get("largest_file")
    if lf:
        L.append(i18n.t("rep_largest"))
        L.append(f"  {ui.human(lf['size'])}")
        L.append(f"  {lf['path']}")
        L.append("")
    ol = r.get("oldest_large_file")
    if ol:
        age = ui.human_age(max(0, time.time() - ol.get("mtime", 0)))
        L.append(i18n.t("rep_oldest"))
        L.append(f"  {ui.human(ol['size'])}   {i18n.t('rep_modified', age=age)}")
        L.append(f"  {ol['path']}")
        L.append("")
    L.append(i18n.t("rep_game"))
    if r["game_storage"]:
        for k, v in sorted(r["game_storage"].items(), key=lambda kv: kv[1], reverse=True):
            if v > 0:
                L.append(f"  {k:<22.22} {ui.human(v):>10}")
        L.append(f"  {i18n.t('rep_total'):<22.22} {ui.human(r['game_total']):>10}")
    else:
        L.append("  " + i18n.t("rep_no_game"))
    L.append("")
    L.append(i18n.t("rep_apps", n=r['apps_count']))
    ins = r.get("insights") or build_insights(r)
    if ins:
        L.append("")
        L.append(i18n.t("rep_recommendations"))
        for lvl, txt in ins:
            L.append(f"  {_INS_MARK.get(lvl, '-')} {txt}")
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
    T = i18n.t

    def drive_rows() -> str:
        rows = []
        for d in r["drives"]:
            pct = d["pct"] * 100
            rows.append(
                f"<tr><td>{e(d['mount'])}</td><td>{ui.human(d['total'])}</td>"
                f"<td>{ui.human(d['used'])}</td><td>{ui.human(d['free'])}</td>"
                f"<td><span class='bar'><span style='width:{pct:.0f}%'></span></span> "
                f"{pct:.0f}%</td><td>{e(d.get('fstype') or '')}</td><td>{e(d.get('kind') or '')}</td></tr>")
        return "".join(rows)

    def top_rows() -> str:
        return "".join(
            f"<tr><td>{i}</td><td>{e(it['name'])}</td><td>{ui.human(it['size'])}</td>"
            f"<td style='color:#6b7699'>{e(it['path'])}</td></tr>"
            for i, it in enumerate(r["top_space_users"], 1))

    def game_rows() -> str:
        return "".join(
            f"<tr><td>{e(k)}</td><td>{ui.human(v)}</td></tr>"
            for k, v in sorted(r["game_storage"].items(), key=lambda kv: kv[1], reverse=True) if v > 0)

    cl = r.get("cleanup")
    cleanup_html = ""
    if cl:
        cleanup_html = f"""
<h2>{T('rep_potential').title()}</h2>
<table><tr><th>Safe</th><td>{ui.human(cl['safe_total'])} ({cl['safe_items']} {T('rep_items')})</td></tr>
<tr><th>Review</th><td>{ui.human(cl['review_total'])} ({cl['review_items']} {T('rep_items')})</td></tr></table>"""

    def file_block(title: str, f: dict[str, Any] | None, extra: str = "") -> str:
        if not f:
            return ""
        return (f"<h2>{title}</h2><table><tr><th>{T('col_size')}</th><td>{ui.human(f['size'])}</td></tr>"
                f"<tr><th>{T('th_path')}</th><td style='color:#6b7699'>{e(f['path'])}</td></tr>{extra}</table>")

    ol = r.get("oldest_large_file")
    ol_extra = ""
    if ol:
        age = ui.human_age(max(0, time.time() - ol.get("mtime", 0)))
        ol_extra = f"<tr><th>{T('th_age')}</th><td>{T('rep_modified', age=age)}</td></tr>"

    _ins_color = {"danger": "#ff7b7f", "warn": "#ffd479",
                  "good": "#7bffb0", "info": "#9aa7ff"}
    ins = r.get("insights") or build_insights(r)
    insights_html = (f"<h2>{T('rep_recommendations').title()}</h2><ul>" + "".join(
        f"<li style='color:{_ins_color.get(lvl, '#d8e0f0')}'>{e(txt)}</li>"
        for lvl, txt in ins) + "</ul>") if ins else ""

    gen_line = T("html_generated", ts=e(r["generated"]), scan=e(r["last_scan"]),
                 dur=ui._fmt_dur(r["scan_duration"]))

    return f"""<!DOCTYPE html>
<html lang="{i18n.get_lang()}"><head><meta charset="utf-8">
<title>DiskTop - {T('rep_title').title()}</title><style>{_CSS}</style></head>
<body>
<h1>DiskTop — {T('rep_title').title()}</h1>
<p>{gen_line}</p>


<h2>{T('rep_disks').title()}</h2>
<table><tr><th>{T('th_volume')}</th><th>{T('rep_total')}</th><th>{T('rep_used')}</th><th>{T('rep_free')}</th><th>{T('th_usage')}</th>
<th>FS</th><th>Type</th></tr>{drive_rows()}</table>

<h2>{T('rep_top_users').title()}</h2>
<table><tr><th>#</th><th>{T('th_category')}</th><th>{T('col_size')}</th><th>{T('th_path')}</th></tr>{top_rows()}</table>
{insights_html}
{cleanup_html}
{file_block(T('rep_largest').title(), r.get("largest_file"))}
{file_block(T('rep_oldest').title(), ol, ol_extra)}
<h2>{T('rep_game').title()}</h2>
<table><tr><th>{T('th_launcher')}</th><th>{T('col_size')}</th></tr>{game_rows()}
<tr><th>{T('rep_total')}</th><th>{ui.human(r['game_total'])}</th></tr></table>
<p>{T('rep_apps', n=r['apps_count'])}</p>
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
        w.writerow([d.get("mount"), d.get("label"), d.get("fstype"), d.get("kind"),
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
