"""Tests for files.py: parsers, filter DSL, categorization, old views,
duplicate finder. Includes regressions for the menu-6 crashes."""
from __future__ import annotations

import os
import time

import files as files_mod

GB = 1024 ** 3
MB = 1024 ** 2
KB = 1024


# --------------------------------------------------------------------------- #
#  Size / age parsers
# --------------------------------------------------------------------------- #
def test_size_to_bytes_fr_and_en():
    assert files_mod.size_to_bytes("1.5 GB") == int(1.5 * GB)
    assert files_mod.size_to_bytes("1,5 Go") == int(1.5 * GB)
    assert files_mod.size_to_bytes("500MO") == 500 * MB
    assert files_mod.size_to_bytes("2TO") == 2 * 1024 ** 4
    assert files_mod.size_to_bytes("garbage") is None


def test_age_to_seconds():
    assert files_mod.age_to_seconds("90d") == 90 * 86400
    assert files_mod.age_to_seconds("2 years") == 2 * 365 * 86400
    assert files_mod.age_to_seconds("3 mois") == 3 * 30 * 86400
    assert files_mod.age_to_seconds("1 an") == 365 * 86400
    assert files_mod.age_to_seconds("xyz") is None


# --------------------------------------------------------------------------- #
#  Filter DSL
# --------------------------------------------------------------------------- #
def test_parse_filter_expr_basic():
    spec = files_mod.parse_filter_expr("size>10GB ext=.zip drive=d:")
    assert spec["min_size"] == 10 * GB
    assert spec["ext"] == "zip"
    assert spec["drive"] == "D:"


def test_parse_filter_expr_inclusive_flags():
    spec = files_mod.parse_filter_expr("size>=1GB age>=1year size<=5GB")
    assert spec["min_size_incl"] is True
    assert spec["min_age_incl"] is True
    assert spec["max_size_incl"] is True


def test_spec_matches_exclusive_vs_inclusive():
    now = time.time()
    item = {"path": "C:\\a.zip", "size": GB, "mtime": now - 365 * 86400,
            "ext": ".zip"}
    # strictly greater -> exactly 1 GB is excluded
    assert not files_mod.spec_matches(item, {"min_size": GB})
    # greater-or-equal -> exactly 1 GB passes
    assert files_mod.spec_matches(
        item, {"min_size": GB, "min_size_incl": True})
    # strictly smaller upper bound -> exactly 1 GB excluded
    assert not files_mod.spec_matches(item, {"max_size": GB})
    assert files_mod.spec_matches(
        item, {"max_size": GB, "max_size_incl": True})


def test_spec_matches_ext_and_drive():
    item = {"path": "D:\\x\\y.iso", "size": MB, "mtime": time.time(),
            "ext": ".iso"}
    assert files_mod.spec_matches(item, {"ext": "iso"})
    assert not files_mod.spec_matches(item, {"ext": "zip"})
    assert files_mod.spec_matches(item, {"drive": "D:"})
    assert not files_mod.spec_matches(item, {"drive": "C:"})


def test_describe_spec_includes_operators():
    d = files_mod.describe_spec({"min_size": GB, "min_size_incl": True})
    assert ">=" in d


# --------------------------------------------------------------------------- #
#  Categories
# --------------------------------------------------------------------------- #
def test_classify_file():
    assert files_mod.classify_file({"ext": ".zip", "path": "C:\\a.zip"}) == "archives"
    assert files_mod.classify_file({"ext": ".iso", "path": "D:\\x.iso"}) == "iso"
    assert files_mod.classify_file({"ext": ".exe", "path": "C:\\toto.exe"}) == "installers"
    assert files_mod.classify_file(
        {"ext": "", "path": "C:\\Users\\x\\Downloads\\stuff.dat"}) == "downloads"
    assert files_mod.classify_file(
        {"ext": "", "path": "C:\\proj\\build\\out.dat"}) == "builds"
    assert files_mod.classify_file({"ext": "", "path": "C:\\weird"}) == "other"


# --------------------------------------------------------------------------- #
#  Old files
# --------------------------------------------------------------------------- #
def _mk(size, age_days, path="C:\\f"):
    return {"path": path, "size": size,
            "mtime": time.time() - age_days * 86400, "ext": ".zip"}


def test_build_old_view_min_size_and_limit():
    old = [_mk(500 * MB, 100), _mk(2 * MB, 200), _mk(500 * KB, 400)]
    sel = files_mod.build_old_view(old, 90, limit=10, min_size=MB)
    # the 500 KB file is filtered out by min_size
    assert [f["size"] for f in sel] == [500 * MB, 2 * MB]
    sel2 = files_mod.build_old_view(old, 90, limit=1)
    assert len(sel2) == 1


def test_old_summary_by_category_shape():
    # regression: main.py unpacked (cat, (total, n)) instead of (cat, n, sz)
    old = [_mk(5 * MB, 100, "C:\\a.zip"), _mk(7 * MB, 120, "C:\\b.zip")]
    cats = files_mod.old_summary_by_category(old, 90)
    assert cats and cats[0][0] == "archives"
    cat, n, sz = cats[0]
    assert n == 2 and sz == 12 * MB


# --------------------------------------------------------------------------- #
#  Search + duplicates
# --------------------------------------------------------------------------- #
def test_parse_command():
    assert files_mod.parse_command("/large 10GB") == ("large", "10GB")
    assert files_mod.parse_command("plain term") == ("", "plain term")


def test_search_all_terms():
    cache = {
        "games": {"launchers": {"Steam": [{"name": "Hollow Knight", "size": 10}]}},
        "apps": [{"name": "VLC media player", "size": 50}],
        "bigfiles": [{"path": "C:\\x\\hollow.knight.iso", "size": 99,
                      "mtime": 0, "ext": ".iso"}],
        "trees": {},
    }
    res = files_mod.search_all("hollow", cache)
    assert res["games"] and res["files"]


def _touch(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_find_duplicates_groups_identical_files(tmp_path):
    a = _touch(tmp_path, "a.bin", b"ABCDEF" * 10)
    b = _touch(tmp_path, "b.bin", b"ABCDEF" * 10)
    c = _touch(tmp_path, "c.bin", b"XYZXYZZ" * 10)
    big = [{"path": p, "size": os.path.getsize(p), "mtime": 0}
           for p in (a, b, c)]
    res = files_mod.find_duplicates(big, min_size=10)
    assert res["groups"], "identical files must form a group"
    grp = res["groups"][0]
    assert sorted(grp["paths"]) == sorted([a, b])
    assert grp["wasted"] == grp["size"]


def test_find_duplicates_no_false_positive(tmp_path):
    a = _touch(tmp_path, "a.bin", b"AAAAAA" * 10)
    b = _touch(tmp_path, "b.bin", b"BBBBBB" * 10)  # same size, other content
    big = [{"path": p, "size": os.path.getsize(p), "mtime": 0} for p in (a, b)]
    res = files_mod.find_duplicates(big, min_size=10)
    assert not res["groups"]
