# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building standalone LinkChat.exe on Windows."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ICON_PATH = ROOT / "windows" / "linkchat_win" / "assets" / "linkchat.ico"

datas = [(str(ICON_PATH), "linkchat_win/assets")]
binaries = []
hiddenimports = [
    "_cffi_backend",
    "linkchat_core",
    "linkchat_win",
    "linkchat_win.app",
    "linkchat_win.ble_transport",
    "linkchat_win.ui",
    "linkchat_win.ui.main_window",
    "linkchat_win.ui.theme",
    "linkchat_win.ui.verify_dialog",
]

datas += collect_data_files("customtkinter")

for pkg in ("bleak", "bless", "cryptography"):
    pkg_datas, pkg_bins, pkg_imports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_bins
    hiddenimports += pkg_imports

hiddenimports += collect_submodules("winrt")

a = Analysis(
    [str(ROOT / "windows" / "linkchat_win" / "__main__.py")],
    pathex=[str(ROOT / "core"), str(ROOT / "windows")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LinkChat",
    icon=str(ICON_PATH),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
