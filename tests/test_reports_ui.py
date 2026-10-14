"""Tests for reports.py (txt/json/html/csv export) and ui.py helpers."""
from __future__ import annotations

import json
import time

import reports
import ui


def _sample_report():
    now = time.time()
    cache = {
        "meta": {"finished": now, "duration": 12.5, "files": 5000},
        "trees": {"C:": {"name": "C:", "path": "C:\\", "size": 999,
                         "children": [{"name": "Users", "path": "C:\\Users",
                                       "size": 700, "children": []}]}},
        "bigfiles": [{"path": "C:\\x\\big.iso", "size": 5 * 1024 ** 3,
                      "mtime": now - 400 * 86400, "ext": ".iso", "drive": "C:"}],
        "oldfiles": [],
        "apps": [{"name": "VLC"}],
        "games": {"launchers": {"Steam": [{"name": "Portal", "size": 1000}]}},
    }
    drives = [{"mount": "C:\\", "label": "SYS", "total": 500 * 1024 ** 3,
               "free": 100 * 1024 ** 3, "used": 400 * 1024 ** 3, "pct": 0.8,
               "fstype": "NTFS", "kind": "SSD/HDD (fixe)"}]
    cleanup = {"safe": [{"path": "C:\\temp", "size": 10, "reason": "temp"}],
               "review": [], "safe_total": 10, "review_total": 0,
               "danger_notes": [], "advisories": []}
    return reports.build_report(cache, drives, cleanup)


def test_build_report_shape():
    r = _sample_report()
    assert r["drives"][0]["mount"] == "C:\\"
    assert r["top_space_users"][0]["name"] == "Users"
    assert r["game_total"] == 1000
    assert r["largest_file"]["path"] == "C:\\x\\big.iso"
    assert r["cleanup"]["safe_items"] == 1


def test_render_text_contains_sections():
    txt = reports.render_text(_sample_report())
    for needle in ("DISQUES", "TOP SPACE USERS", "GAME STORAGE", "LARGEST FILE"):
        assert needle in txt


def test_render_json_valid():
    r = _sample_report()
    parsed = json.loads(reports.render_json(r))
    assert parsed["drives"][0]["fstype"] == "NTFS"


def test_render_html_escapes_paths():
    r = _sample_report()
    r["top_space_users"] = [{"name": "<b>x</b>", "path": "C:\\<script>",
                             "size": 1}]
    out = reports.render_html(r)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_render_csv_has_fstype():
    # regression: csv used d.get("fs") (missing key) -> column was empty
    out = reports.render_csv(_sample_report())
    assert "NTFS" in out


def test_export_all_formats(tmp_path):
    r = _sample_report()
    for fmt in ("txt", "json", "html", "csv"):
        path = reports.export(r, fmt, outdir=str(tmp_path))
        assert path.endswith("report." + fmt)
        with open(path, encoding="utf-8") as f:
            assert f.read(), f"{fmt} export is empty"


# --------------------------------------------------------------------------- #
#  ui helpers
# --------------------------------------------------------------------------- #
def test_human_sizes():
    assert ui.human(0) == "0 B"
    assert ui.human(1023) == "1023 B"
    assert ui.human(1024) == "1.0 KB"
    assert ui.human(5 * 1024 ** 3) == "5.0 GB"


def test_human_age():
    assert ui.human_age(45 * 86400) == "45 j"
    assert ui.human_age(800 * 86400) == "2 ans"
    assert ui.human_age(100) == "1 min"


def test_human_compact():
    assert ui.human_compact(1024) == "1K"
    assert ui.human_compact(500) == "500"


def test_short_and_severity():
    long = "C:\\very\\long\\path\\that\\goes\\on\\and\\on\\forever"
    assert ui._short(long, 20).startswith("...")
    assert ui.severity_color(0.95) == "red"
    assert ui.severity_color(0.20) == "green"


def test_choose_multi_parsing(monkeypatch):
    cases = [("1,3-5", [1, 3, 4, 5]), ("5-3", [3, 4, 5]), ("", []),
             ("abc", []), ("9", []), ("2, 4", [2, 4]), ("n", [])]
    for raw, want in cases:
        monkeypatch.setattr("builtins.input", lambda *a, **k: raw)
        assert ui.choose_multi("t", 6) == want, raw


def test_tree_lines_counts_hidden():
    root = {"path": "C:\\", "size": 100, "name": "C:", "children": [
        {"name": f"d{i}", "path": f"C:\\d{i}", "size": 10 - i,
         "files": i, "children": []} for i in range(10)]}
    lines = ui.tree_lines(root, max_depth=1, max_children=3)
    joined = "\n".join(lines)
    assert "+7 more" in joined
