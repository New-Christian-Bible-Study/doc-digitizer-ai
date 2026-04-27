# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


ROOT = Path(SPECPATH).resolve()
ENTRYPOINT = ROOT / 'review-chunk.py'

datas = [
    (str(ROOT / 'icons' / 'review-chunk-lines.png'), 'icons'),
]

# Keep optional transcribe/review schema files available in case future
# reviewer flows read them directly.
for schema_name in (
    'raw-transcription.schema.json',
    'final-transcription.schema.json',
):
    schema_path = ROOT / schema_name
    if schema_path.is_file():
        datas.append((str(schema_path), '.'))

datas += collect_data_files('PySide6')
binaries = collect_dynamic_libs('pypdfium2')
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
]


a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(ROOT)],
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
    a.binaries,
    a.datas,
    [],
    name='review-chunk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

