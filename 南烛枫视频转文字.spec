# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules


datas = [
    ('app\\assets', 'app/assets'),
    ('..\\CleanVideoDownloader\\app\\assets', 'app/assets'),
    ('..\\JHlib\\ffmpeg', 'tools/ffmpeg'),
]
binaries = []
hiddenimports = []

for package_name in (
    'faster_whisper',
    'ctranslate2',
    'huggingface_hub',
    'tokenizers',
    'docx',
):
    hiddenimports += collect_submodules(package_name)
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    ['start.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='南烛枫视频转文字',
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
    icon='app\\assets\\nanzhufeng-video-transcriber-icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='南烛枫视频转文字',
)
