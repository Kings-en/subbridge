# -*- mode: python ; coding: utf-8 -*-
"""SubBridge PyInstaller 打包配置（one-folder 模式）。

用法（Windows）：
    build\\windows\\build.bat
或：
    python -m PyInstaller build\\windows\\SubBridge.spec --noconfirm

注意：
- 不打包图标（仓库不含二进制文件）；如需图标，后续放一个 .ico 并取消
  下面 icon 的注释。
- ffmpeg 不打进包里：体积太大且各平台授权不同；CI 会把 gyan.dev 的
  ffmpeg 精简版放在 dist\\SubBridge\\ffmpeg\\bin 下，随包分发。
- faster-whisper / argos-translate 首次使用时才下载模型，模型也不进包。
"""

import os
from pathlib import Path

SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR.parent.parent
SRC_DIR = PROJECT_ROOT / "src"

block_cipher = None

a = Analysis(
    [str(SRC_DIR / "subbridge" / "__main__.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "faster_whisper",
        "ctranslate2",
        "argostranslate",
        "argostranslate.package",
        "argostranslate.translate",
        "sentencepiece",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=None,  # 仓库不含二进制图标文件；如需图标，在此指定 .ico 路径
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SubBridge",
)
