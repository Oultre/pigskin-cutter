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

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("cutup")            # web/static, data/**, glyphs.npz, ffmpeg if bundled
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("cutup")
    + ["cv2", "numpy", "openpyxl", "fastapi", "anyio", "email.mime.multipart"]
)

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
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
    console=True,               # a console window shows the "running at http://…" line
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,     # unsigned by design (PLAN §3.6)
    entitlements_file=None,
)
