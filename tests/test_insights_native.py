"""Regression tests for the offline insights engine and the optional
native helper (dufast). Both must degrade gracefully so the app never
depends on them."""
from __future__ import annotations

import os
import time

import pytest

import nativehelper
import reports
import scanner

GB = 1024 ** 3


def _report():
    now = time.time()
    cache = {
        "meta": {"finished": now, "duration": 9.0, "files": 1000},
        "trees": {"C:": {"name": "C:", "path": "C:\\", "size": 1, "children": [
            {"name": "Users", "path": "C:\\Users", "size": 400 * GB, "children": []}]}},
        "bigfiles": [{"path": "C:\\x\\big.vhdx", "size": 9 * GB,
                      "mtime": now - 500 * 86400, "ext": ".vhdx", "drive": "C:"}],
        "oldfiles": [], "apps": [], "games": {"launchers": {"Steam": [{"size": 100 * GB}]}},
    }
    drives = [{"mount": "C:\\", "label": "SYS", "total": 500 * GB, "free": 35 * GB,
               "used": 465 * GB, "pct": 0.93, "fstype": "NTFS", "kind": "SSD/HDD (fixe)"}]
    cleanup = {"safe": [{"path": "C:\\temp", "size": 5 * GB, "reason": "temp"}],
               "review": [], "safe_total": 5 * GB, "review_total": 0,
               "danger_notes": [], "advisories": []}
    return reports.build_report(cache, drives, cleanup)


def test_build_report_attaches_insights():
    r = _report()
    assert isinstance(r["insights"], list) and r["insights"]
    for lvl, txt in r["insights"]:
        assert lvl in ("danger", "warn", "good", "info")
        assert isinstance(txt, str) and txt


def test_insights_flags_full_drive_and_cleanable_cache():
    r = _report()
    ins = reports.build_insights(r)
    levels = {lvl for lvl, _ in ins}
    assert "danger" in levels          # 93% full
    assert "good" in levels            # 5 GB safely cleanable
    assert any("C:\\" in t for _, t in ins)


def test_render_text_and_html_include_recommendations():
    r = _report()
    assert "RECOMMANDATIONS" in reports.render_text(r)
    assert "Recommandations" in reports.render_html(r)


def test_insights_escape_paths_in_html():
    r = _report()
    r["insights"] = [("info", "C:\\<script>alert(1)</script>")]
    out = reports.render_html(r)
    assert "<script>alert" not in out
    assert "&lt;script&gt;" in out


# --------------------------------------------------------------------------- #
#  Native helper: must be fully optional.
# --------------------------------------------------------------------------- #
def test_native_du_returns_none_without_binary(monkeypatch):
    monkeypatch.setattr(nativehelper, "binary_path", lambda: None)
    assert nativehelper.native_du(".") is None


def test_kill_switch_disables_native(monkeypatch, tmp_path):
    # Even if a binary existed, the env kill switch must make us ignore it.
    monkeypatch.setenv("DISKSCOPE_NO_NATIVE", "1")
    assert nativehelper.binary_path() is None


def test_native_du_empty_dir_is_not_trusted(tmp_path):
    if not nativehelper.binary_path():
        pytest.skip("native dufast binary not built")
    empty = tmp_path / "empty"
    empty.mkdir()
    # empty dir -> size 0 -> we must NOT trust it (returns None -> Python fallback)
    assert nativehelper.native_du(str(empty)) is None


def test_native_du_matches_python_when_present(tmp_path):
    if not nativehelper.binary_path():
        pytest.skip("native dufast binary not built")
    d = tmp_path / "tree"
    (d / "sub").mkdir(parents=True)
    (d / "a.bin").write_bytes(b"x" * 1000)
    (d / "sub" / "b.bin").write_bytes(b"y" * 2500)
    n = nativehelper.native_du(str(d))
    py = scanner.dir_size(str(d))
    assert n is not None
    assert n[0] == py[0] == 3500
    assert n[1] == py[1] == 2
