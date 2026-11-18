# PyInstaller spec for the optodraw desktop app.
#
# Build (run from this directory):
#     pip install "optodraw[desktop]" pyinstaller
#     pyinstaller optodraw.spec
#
# Produces dist/optodraw/ (onedir). On macOS it also yields dist/optodraw.app.
# See packaging/README.md for wrapping into .dmg / .appimage / .exe installers.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# uvicorn imports its loop/protocol implementations dynamically, and the editor's
# app package is imported lazily — collect both so the frozen app can find them.
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("optodraw.app")
    + ["optodraw", "fastapi", "anyio", "click", "webview"]
)

# Everything the package reads off disk at runtime, not just the front end:
# the editor's HTML/CSS/JS and the foundry layer stacks under gds/stacks.
# Collecting only app/static froze an app whose stack picker was empty.
datas = collect_data_files("optodraw")

a = Analysis(
    ["desktop_main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="optodraw",
    console=False,  # windowed app (no terminal)
    disable_windowed_traceback=False,
    icon=None,  # set a path to a .ico/.icns to brand the app
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="optodraw",
)

# macOS .app bundle (ignored on Windows/Linux).
app = BUNDLE(
    coll,
    name="optodraw.app",
    icon=None,
    bundle_identifier="com.optodraw.editor",
)
