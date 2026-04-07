# -*- mode: python ; coding: utf-8 -*-

import sys
import os
import re

# 从源代码中提取版本号
version = "1.2.1"
try:
    if os.path.exists('minimal_uploader.py'):
        with open('minimal_uploader.py', 'r', encoding='utf-8') as f:
            content = f.read()
            match = re.search(r'APP_VERSION\s*=\s*(["\'])(.*?)\1', content)
            if match:
                version = match.group(2)
except Exception as e:
    print(f"Error extracting version: {e}")

# 尝试获取 FFmpeg/FFprobe 二进制文件路径 (可选，代码中有 fallback)
binaries = []
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    if ffmpeg_exe and os.path.exists(ffmpeg_exe):
        binaries.append((ffmpeg_exe, '.'))
        ffmpeg_dir = os.path.dirname(ffmpeg_exe)
        ffprobe_exe = os.path.join(ffmpeg_dir, "ffprobe.exe")
        if os.path.exists(ffprobe_exe):
            binaries.append((ffprobe_exe, '.'))
except Exception as e:
    print(f"Warning: Could not bundle FFmpeg/FFprobe binaries: {e}")

a = Analysis(
    ['minimal_uploader.py'],
    pathex=['.'],
    binaries=binaries,
    datas=[('assets', 'assets')],
    hiddenimports=['config'],
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
    version='version_info.txt' if os.path.exists('version_info.txt') else None,
    icon=['assets\\icons\\app_icon.ico'] if os.path.exists('assets\\icons\\app_icon.ico') else None,
)
