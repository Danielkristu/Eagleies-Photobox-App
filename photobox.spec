# PyInstaller spec for Photobox Flask+PyWebview app
# Run: pyinstaller photobox.spec

block_cipher = None

import sys
import os
from PyInstaller.utils.hooks import collect_submodules
import datetime

# Path to your main app
main_script = 'app.py'

# Data files: include templates and static folders
static_dir = os.path.join('static')
templates_dir = os.path.join('templates')

datas = [
    (static_dir, 'static'),
    (templates_dir, 'templates'),
    ('serviceAccountKey.json', '.'),
    ('firebase_key.json', '.'),
    ('firebase.json', '.'),
]

# Hidden imports for PyWebview and Flask
hiddenimports = collect_submodules('webview') + collect_submodules('flask')

# --- Versioning ---
def get_next_version(version_file='version.txt'):
    if os.path.exists(version_file):
        with open(version_file, 'r') as vf:
            version = vf.read().strip()
        parts = version.split('.')
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            major, minor, patch = map(int, parts)
            patch += 1
            return f"{major}.{minor}.{patch}"
    # If no version file or invalid, start at 1.0.0
    return "1.0.0"

version_file = 'version.txt'
version = get_next_version(version_file)
with open(version_file, 'w') as vf:
    vf.write(version)

# Build the exe
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

a = Analysis([
    main_script
],
    pathex=[os.getcwd()],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
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
    name=f'Photobox_{version}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=f'Photobox_{version}'
)
