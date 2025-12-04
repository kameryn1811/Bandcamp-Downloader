# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Bandcamp Downloader Launcher
This creates a self-contained launcher.exe that bundles Python and can download/update the main script.
"""

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[
        ('ffmpeg.exe', '.'),  # Bundle ffmpeg.exe (will be extracted to launcher directory on first run)
    ],
    datas=[
        ('bandcamp_dl_gui.py', '.'),  # Bundle the script as a fallback (will be updated from GitHub)
        ('icon.ico', '.'),  # Bundle icon.ico (will be extracted to launcher directory on first run)
    ],
    hiddenimports=[
        'requests',  # Required for GitHub API calls
        'json',
        'pathlib',
        'subprocess',
        'threading',
        # Standard library modules used by bandcamp_dl_gui.py
        'webbrowser',
        'tempfile',
        'hashlib',
        'ctypes',
        'ctypes.wintypes',
        'urllib.request',  # URL redirect resolution
        'urllib.parse',  # URL parsing
        'urllib.error',  # URL error handling
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'tkinter.scrolledtext',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL._tkinter_finder',
        'yt_dlp',
        'tkinterdnd2',  # Drag-and-drop support for URL field
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
    name='BandcampDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compress executable (reduces size)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Hide console window - launch silently
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico'  # Use the same icon as the main app
)

