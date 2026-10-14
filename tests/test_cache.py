"""Tests for cache.py: atomic roundtrip, versioning, freshness, history."""
from __future__ import annotations

import json
import os
import time

import pytest

import cache as cache_mod


@pytest.fixture()
def isolated_cache(tmp_path, monkeypatch):
    path = str(tmp_path / "cache.json")
    monkeypatch.setattr(cache_mod, "cache_file", lambda: path)
    return path


def test_roundtrip(isolated_cache):
    data = cache_mod.load()
    data["meta"]["x"] = 1
    data["bigfiles"] = [{"path": "C:\\a", "size": 5}]
    cache_mod.save(data)
    loaded = cache_mod.load()
    assert loaded["meta"]["x"] == 1
    assert loaded["bigfiles"][0]["size"] == 5
    assert loaded["version"] == cache_mod.CACHE_VERSION


def test_corrupt_cache_discarded(isolated_cache):
    with open(isolated_cache, "w") as f:
        f.write("{not json!!")
    data = cache_mod.load()
    assert data["version"] == cache_mod.CACHE_VERSION
    assert data["bigfiles"] == []


def test_version_mismatch_returns_empty(isolated_cache):
    with open(isolated_cache, "w") as f:
        json.dump({"version": 999, "meta": {"junk": True},
                   "bigfiles": [{"path": "C:\\stale"}]}, f)
    data = cache_mod.load()
    empty = cache_mod._empty()
    assert data["version"] == empty["version"]
    assert data["bigfiles"] == []
    assert data["meta"] == {}


def test_no_leftover_tmp_on_success(isolated_cache):
    cache_mod.save(cache_mod.load())
    assert os.path.exists(isolated_cache)
    assert not os.path.exists(isolated_cache + ".tmp")


def test_save_bounds_biglists(isolated_cache):
    data = cache_mod.load()
    data["bigfiles"] = [{"path": f"C:\\f{i}", "size": i}
                        for i in range(cache_mod.MAX_ITEMS + 10)]
    cache_mod.save(data)
    loaded = cache_mod.load()
    assert len(loaded["bigfiles"]) == cache_mod.MAX_ITEMS


def test_is_fresh(isolated_cache):
    data = cache_mod.load()
    assert not cache_mod.is_fresh(data)
    cache_mod.update_meta(data, files=10, duration=1.0)
    assert cache_mod.is_fresh(data)
    data["meta"]["finished"] = time.time() - 3600
    assert not cache_mod.is_fresh(data)


def test_push_history_caps_at_30(isolated_cache):
    data = cache_mod.load()
    for i in range(40):
        cache_mod.push_history(data, {"C:": 1000 + i})
    assert len(data["history"]) == 30
    assert data["history"][-1]["drives"]["C:"] == 1039
