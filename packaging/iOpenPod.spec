# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for iOpenPod macOS .app bundle
# Run from the repo root: pyinstaller packaging/iOpenPod.spec
#
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets" / "fonts"),       "assets/fonts"),
        (str(ROOT / "assets" / "ipod_images"), "assets/ipod_images"),
        (str(ROOT / "iTunesDB_Writer" / "wasm"), "iTunesDB_Writer/wasm"),
    ],
    hiddenimports=[
        # PyQt6
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        # crypto / hashing
        "Crypto",
        "Crypto.Cipher",
        "Crypto.Cipher.AES",
        # audio / fingerprinting
        "mutagen",
        "mutagen.mp3",
        "mutagen.flac",
        "mutagen.mp4",
        "mutagen.id3",
        # image processing
        "PIL",
        "PIL.Image",
        # Plex (optional — included so the import check works)
        "plexapi",
        "plexapi.myplex",
        "plexapi.server",
        # HTTP (Pinepods)
        "requests",
        "certifi",
        # wasmtime
        "wasmtime",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt6.QtLocation",
        "PyQt6.QtPositioning",
        "PyQt6.QtBluetooth",
        "PyQt6.QtNfc",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="iOpenPod",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="iOpenPod",
)

app = BUNDLE(
    coll,
    name="iOpenPod.app",
    icon=str(ROOT / "packaging" / "iOpenPod.icns"),
    bundle_identifier="com.xwbarton.iopenpod",
    info_plist={
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleShortVersionString": "1.1.0",
        "CFBundleName": "iOpenPod",
        "CFBundleDisplayName": "iOpenPod",
        "LSMinimumSystemVersion": "12.0",
    },
)
