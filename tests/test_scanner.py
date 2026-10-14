"""Tests for scanner.py: parallel walk correctness, batched collectors,
dir_size, top_level_sizes, compact_tree."""
from __future__ import annotations

import threading

import pytest

import scanner


@pytest.fixture()
def tree(tmp_path):
    """a/1.txt 4B, a/b/2.txt 6B, a/b/3.txt 10B, c/4.bin 1MB."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "1.txt").write_bytes(b"aaaa")
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "2.txt").write_bytes(b"b" * 6)
    (tmp_path / "a" / "b" / "3.txt").write_bytes(b"c" * 10)
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "4.bin").write_bytes(b"d" * (1024 * 1024))
    return str(tmp_path)


def test_scan_tree_totals(tree):
    node, stats = scanner.scan_tree(tree, "T:", max_depth=scanner.DEFAULT_DEPTH)
    assert stats["files"] == 4
    assert stats["bytes"] == 4 + 6 + 10 + 1024 * 1024
    assert node["size"] == stats["bytes"]
    assert node["dirs"] == 3


def test_scan_tree_collectors_batched(tree):
    col = scanner.Collectors(big_keep=2, old_min_size=1024)
    node, _stats = scanner.scan_tree(tree, "T:", collectors=col)
    big, old = col.results()
    assert len(big) <= 2
    # only the 1 MB file passes the 1 KB old-min-size
    assert len(old) == 1 and old[0]["size"] == 1024 * 1024


def test_scan_tree_stop_event(tree):
    stop = threading.Event()
    stop.set()
    node, stats = scanner.scan_tree(tree, "T:", stop=stop)
    # cancelled immediately: must not hang, counts stay bounded
    assert isinstance(node["size"], int)


def test_dir_size_matches_scan(tree):
    total, count = scanner.dir_size(tree)
    assert count == 4
    assert total == 4 + 6 + 10 + 1024 * 1024


def test_dir_size_max_files(tree):
    total, count = scanner.dir_size(tree, max_files=2)
    assert count == 2


def test_top_level_sizes(tree):
    rows = scanner.top_level_sizes(tree)
    names = [r[0] for r in rows]
    assert set(names) == {"a", "c"}
    assert rows[0][2] >= rows[1][2]  # sorted by size desc


def test_compact_tree_bounds(tree):
    node, _ = scanner.scan_tree(tree, "T:")
    compact = scanner.compact_tree(node, max_depth=1, max_children=1)
    assert len(compact.get("children", [])) <= 1


def test_collectors_add_files_trims():
    col = scanner.Collectors(big_keep=3, old_max=4, old_min_size=1)
    batch = [(f"C:\\f{i}", 100 - i, float(i), ".bin") for i in range(20)]
    col.add_files(batch, "C:")
    big, old = col.results()
    assert len(big) <= 3
    assert all(b["size"] >= 97 for b in big)  # kept the biggest
    assert len(old) <= 4
    col.add_files([], "C:")  # empty batch is a no-op


def test_collectors_add_file_single_compat():
    col = scanner.Collectors(big_keep=5, old_min_size=10)
    col.add_file("C:\\x.zip", 20, 1.0, ".zip", "C:")
    big, old = col.results()
    assert big[0]["path"] == "C:\\x.zip"
    assert old and old[0]["size"] == 20
