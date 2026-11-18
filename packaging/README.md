# Packaging the optodraw editor

The editor ships from one codebase to four targets. The Python entry point is the
same everywhere: `optodraw.app.launcher:main` (CLI `optodraw-gui`), and the
desktop bundles use [`desktop_main.py`](desktop_main.py) which calls it with
`--desktop` (a native PyWebView window).

> Builds run on **your** machine / CI per OS — you can't cross-build native
> installers. The configs here are the recipes; CI just runs them.

## 1. pip

```bash
pip install "optodraw[gui]"      # editor (FastAPI + uvicorn)
optodraw-gui                     # browser
optodraw-gui --desktop           # native window (needs optodraw[desktop])
```

## 2. conda

A starter recipe is in [`../conda/meta.yaml`](../conda/meta.yaml). The package
is pure Python, so the conda build is `noarch` and does not need a Rust
toolchain:

```bash
conda install -n base conda-build
conda build conda/ -c conda-forge
```

For distribution, submitting to conda-forge is the durable path.

## 3. Native desktop bundles

Install the app + bundler, then build with the shared PyInstaller spec:

```bash
pip install "optodraw[desktop]" pyinstaller
cd packaging
pyinstaller optodraw.spec        # -> dist/optodraw/  (+ dist/optodraw.app on macOS)
```

The release workflow uploads `.tar.gz` archives of the built app directories.
It does not produce signed installers. To make installers, wrap the result per OS:

- **Windows `.exe` installer:** point [Inno Setup](https://jrsoftware.org/isinfo.php)
  or NSIS at `dist/optodraw/`. (The raw `dist/optodraw/optodraw.exe` already runs.)
- **macOS `.dmg`:** `create-dmg dist/optodraw.app` (or `hdiutil create`). Code-sign
  + notarize for distribution.
- **Linux `.appimage`:** feed `dist/optodraw/` to
  [`appimage-builder`](https://appimage-builder.readthedocs.io/) or `linuxdeploy`.

### Alternative: Briefcase

[Briefcase](https://briefcase.readthedocs.io/) targets all three native formats
from one config and is friendly for researchers. Use `desktop_main.py:run` as the
app entry; declare `optodraw[desktop]` as the requirement.

## Notes

- The launcher binds `127.0.0.1:8000` by default. If that port is taken, it
  walks to the next free port and prints the URL. An explicit `--port` is never
  moved.
- The spec uses `collect_data_files("optodraw")` to include the editor assets
  and layer stacks.
- Hosted web deployment (not a native app) is covered in
  [`../docs/architecture.md`](../docs/architecture.md).
