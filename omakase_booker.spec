# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Omakase Auto-Booker Windows .exe"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['omakase_booker/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.example.yaml', '.'),
    ],
    hiddenimports=[
        'ttkbootstrap',
        'tkcalendar',
        'babel.numbers',
        'pystray',
        'PIL',
        'google.auth',
        'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'googleapiclient.discovery',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OmakaseBooker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add .ico file for custom icon
)
