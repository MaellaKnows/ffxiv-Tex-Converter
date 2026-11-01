# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules


# ============================================================
# Project paths
# ============================================================

project = Path.cwd().resolve()

script = project / "main.py"
texconv = project / "tools" / "texconv.exe"
icon = project / "icon.ico"


# ============================================================
# Check required files
# ============================================================

if not script.exists():
    raise SystemExit(
        "Missing main.py. Please run this build from the project folder."
    )

if not texconv.exists():
    raise SystemExit(
        "Missing tools\\texconv.exe. Run BUILD_EXE.bat first."
    )


# ============================================================
# 图标（同时作为窗口图标打进包里）
# ============================================================

icon_path = str(icon) if icon.exists() else None

if icon_path is None:
    print("[INFO] icon.ico not found. EXE will use the default icon.")
else:
    print("[INFO] Using icon:", icon)

datas = []
if icon_path:
    datas.append((icon_path, "."))


# ============================================================
# Analysis
# ============================================================

a = Analysis(
    [str(script)],

    pathex=[
        str(project)
    ],

    binaries=[
        (
            str(texconv),
            "tools"
        )
    ],

    datas=datas,

    hiddenimports=collect_submodules("tkinter"),

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],

    noarchive=False,
)


# ============================================================
# Python archive
# ============================================================

pyz = PYZ(
    a.pure
)


# ============================================================
# Final EXE
# ============================================================

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],

    name="FFXIVTextureBatchConverter",

    # Custom Windows icon
    icon=icon_path,

    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,

    # GUI application, no console window
    console=False,

    disable_windowed_traceback=False,
    argv_emulation=False,
)