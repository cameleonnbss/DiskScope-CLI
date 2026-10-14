"""The one-file-launcher promise: run.bat / run.sh / install.bat exist,
are self-contained, and the bash twin is syntactically valid."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def test_launchers_exist():
    for name in ("run.bat", "run.sh", "install.bat", "main.py", "requirements.txt"):
        assert os.path.isfile(os.path.join(ROOT, name)), name


def test_run_bat_is_self_containing():
    txt = _read("run.bat").lower()
    # must pin its own folder, find python without PATH, create the venv,
    # install deps conditionally, and pass arguments through
    assert "%~dp0" in txt
    assert "py -3" in txt
    assert "-m venv" in txt
    assert "requirements.txt" in txt
    assert "main.py %*" in txt
    # optional native accelerator build (best-effort, app works without it)
    assert "dufast" in txt


def test_install_bat_delegates_to_run_bat():
    txt = _read("install.bat").lower()
    assert "call run.bat --selftest" in txt


def test_run_sh_syntax():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    # Use a RELATIVE path + cwd=ROOT: a Windows-style absolute path breaks
    # under WSL's bash (backslashes are dropped), and this repo lives under a
    # folder with accents, so only the relative form is portable across the
    # Git Bash / WSL / MSYS bash variants.
    r = subprocess.run([bash, "-n", "run.sh"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_run_sh_mirrors_the_bootstrap():
    txt = _read("run.sh")
    assert 'cd "$(dirname "$0")"' in txt
    assert "-m venv" in txt
    assert "requirements.txt" in txt
    assert 'main.py "$@"' in txt
    assert "dufast" in txt
