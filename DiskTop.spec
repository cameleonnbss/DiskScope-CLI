# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DiskTop - builds a single self-contained executable.

Usage (see build_exe.bat / build_exe.sh):
    pyinstaller DiskTop.spec --noconfirm

Produces dist/DiskTop(.exe). The optional native C accelerator (native/dufast)
is bundled next to a 'native' data folder when it has been compiled, so the
shipped binary can use the fast path too - and still falls back to pure Python.
"""
import os

block_cipher = None

_datas = []
_binaries = []
for _name in ("dufast.exe", "dufast"):
    _p = os.path.join("native", _name)
    if os.path.isfile(_p):
        _binaries.append((_p, "native"))
        break

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=["rich", "send2trash"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DiskTop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
