# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Pigskin Cutter (one-file, unsigned — PLAN §3.6).

Bundles the engine + FastAPI + the built React frontend (cutup/web/static) + the
bundled OCR package and starter data (cutup/data/**). ffmpeg, if present under
cutup/bin/<platform>/, is picked up by collect_data_files too; otherwise the app
falls back to ffmpeg on PATH.

Build (on each target OS — macOS builds on macOS, Windows on Windows):
    pip install -e ".[dev]" pyinstaller
    cd frontend && npm ci && npm run build && cd ..
    pyinstaller packaging/pigskin-cutter.spec
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = collect_data_files("cutup")            # web/static, data/**, glyphs.npz, ffmpeg if bundled
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("cutup")
    + ["cv2", "numpy", "openpyxl", "fastapi", "anyio", "email.mime.multipart"]
)
binaries = []

# pywebview + its Windows backend (pythonnet/clr + Edge WebView2 interop) power the
# native app window. Pull in everything they need so the one-file build opens a real
# window instead of a browser tab.
for pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        p_datas, p_bins, p_hidden = collect_all(pkg)
        datas += p_datas
        binaries += p_bins
        hiddenimports += p_hidden
    except Exception:
        pass  # missing on a platform whose backend differs; window falls back to browser
hiddenimports += ["clr", "webview.platforms.winforms", "webview.platforms.edgechromium"]

# App/window icon (the Pigskin Cutter logo), if it's been generated into the tree.
_icon = os.path.join("..", "src", "cutup", "data", "branding", "app.ico")
icon = _icon if os.path.exists(_icon) else None

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PigskinCutter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # windowed: double-click shows the app window, not a
                                # black console. CLI use from a terminal re-attaches to
                                # it at runtime (see cli._prepare_console).
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,     # unsigned by design (PLAN §3.6)
    entitlements_file=None,
    icon=icon,                  # the Pigskin Cutter logo, if generated into the tree
)
