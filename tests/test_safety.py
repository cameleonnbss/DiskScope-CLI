"""Tests for safety.py guards and the Deleter (dry-run first)."""
from __future__ import annotations

import os

import pytest

import safety

IS_NT = os.name == "nt"
windows_only = pytest.mark.skipif(not IS_NT, reason="Windows path semantics")


# --------------------------------------------------------------------------- #
#  validate_delete_path
# --------------------------------------------------------------------------- #
def test_empty_and_blank_rejected():
    assert not safety.validate_delete_path("")[0]
    assert not safety.validate_delete_path("   ")[0]


def test_relative_path_rejected():
    ok, why = safety.validate_delete_path("folder\\sub")
    assert not ok and "absolu" in why


@windows_only
def test_traversal_rejected():
    ok, why = safety.validate_delete_path("C:\\Users\\..\\..\\Windows")
    assert not ok and "traversée" in why


@windows_only
def test_drive_root_rejected():
    assert safety.is_drive_root("C:\\")
    assert safety.is_drive_root("D:")
    ok, _why = safety.validate_delete_path("C:\\")
    assert not ok


@windows_only
def test_windows_folder_protected():
    ok, why = safety.validate_delete_path("C:\\Windows\\System32\\drivers")
    assert not ok
    assert "Windows" in why or "système" in why
    prot, _ = safety.is_protected("C:\\Program Files\\SomeApp")
    assert prot
    # regression: uppercase path vs lowercase set used to disable the
    # whole _PROTECTED_NAMES list (only \WINDOWS\ fallback worked)
    for p in ("C:\\ProgramData\\x", "D:\\Program Files (x86)\\y",
              "C:\\$Recycle.Bin\\S-1-5-18", "C:\\Windows"):
        assert safety.is_protected(p)[0], p


def test_missing_path_rejected(tmp_path):
    ghost = tmp_path / "does_not_exist"
    ok, why = safety.validate_delete_path(str(ghost))
    assert not ok and "n'existe plus" in why


def test_existing_tmp_file_passes_guards(tmp_path):
    f = tmp_path / "ok.txt"
    f.write_text("x")
    ok, why = safety.validate_delete_path(str(f))
    assert ok, why


# --------------------------------------------------------------------------- #
#  Reparse helpers (cheap cross-platform shape checks)
# --------------------------------------------------------------------------- #
def test_is_reparse_point_false_for_regular(tmp_path):
    d = tmp_path / "regular"
    d.mkdir()
    assert not safety.is_reparse_point(str(d))


@windows_only
def test_junction_refused(tmp_path):
    """A real junction must be refused by the delete guards."""
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    created = os.system(f'mklink /J "{link}" "{target}" >nul 2>&1') == 0
    if not created or not os.path.lexists(link):
        pytest.skip("could not create junction (permissions)")
    try:
        assert safety.is_reparse_point(str(link))
        ok, why = safety.validate_delete_path(str(link))
        assert not ok and "jonction" in why
    finally:
        os.rmdir(link)


# --------------------------------------------------------------------------- #
#  Deleter
# --------------------------------------------------------------------------- #
def test_deleter_dry_run_touches_nothing(tmp_path):
    f = tmp_path / "keepme.txt"
    f.write_text("data")
    d = safety.Deleter(dry_run=True)
    ok, msg = d.delete(str(f), size=4, reason="test")
    assert ok and "simulé" in msg
    assert f.exists()
    assert d.bytes_planned == 4 and d.bytes_freed == 0


def test_deleter_refused_path_not_trashed(tmp_path):
    d = safety.Deleter(dry_run=False)
    ok, msg = d.delete("relative\\path")
    assert not ok and msg.startswith("Refusé")
    assert d.log[-1][1] == "REFUSED"


@windows_only
def test_deleter_real_trash(tmp_path):
    f = tmp_path / "trashme.txt"
    f.write_text("bye")
    d = safety.Deleter(dry_run=False)
    ok, msg = d.delete(str(f), size=3, reason="test")
    # in CI the recycle bin may be unavailable; that must be a clean failure
    assert ok or "corbeille" in msg
    if ok:
        assert not f.exists()
        assert d.bytes_freed == 3
