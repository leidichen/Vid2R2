# -*- mode: python ; coding: utf-8 -*-

import sys
import os
import re
import imageio_ffmpeg

# 从源代码中提取版本号
version = "1.2.1"
try:
    with open('minimal_uploader.py', 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r'APP_VERSION\s*=\s*(["\'])(.*?)\1', content)
        if match:
            version = match.group(2)
except Exception:
    pass

# 获取 FFmpeg/FFprobe 二进制文件路径
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
ffmpeg_dir = os.path.dirname(ffmpeg_exe)
ffprobe_exe = os.path.join(ffmpeg_dir, "ffprobe.exe")

binaries = [
    (ffmpeg_exe, '.'),  # 打包到根目录
]
if os.path.exists(ffprobe_exe):
    binaries.append((ffprobe_exe, '.'))

a = Analysis(
    ['minimal_uploader.py'],
    pathex=[],
    binaries=binaries,
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'Vid2R2-v{version}',
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
    version='version_info.txt',
    icon=['assets\\icons\\app_icon.ico'],
)
