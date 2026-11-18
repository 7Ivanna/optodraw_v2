"""Offline 3D asset bundling: repeatable exports with no CDN at view time.

``render_threejs("scene.html", offline=True)`` writes ``scene.html`` plus a
sibling ``scene_assets/`` directory and rewrites the page to load everything
by relative path. The bundle pins the exact versions the renderer uses
(imported from ``threejs_renderer`` so the two cannot drift):

- ``three.module.js`` — three.js core (MIT)
- ``examples/jsm/`` — the addon tree from the pinned three.js tag tarball
- ``LICENSES/`` — upstream license texts plus a NOTICE with versions and URLs
- ``versions.json`` — the pinned versions, for repeatability checks

Google Fonts links are dropped in offline mode; the page CSS already falls
back to system sans stacks, so text renders without the webfont.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

from optodraw.renderers.threejs_renderer import (
    THREEJS_CDN,
    THREEJS_TAG,
    THREEJS_VERSION,
)

#: (local name, download URL, license note) for single-file assets.
SINGLE_FILES: tuple[tuple[str, str, str], ...] = (
    ("three.module.js", f"{THREEJS_CDN}/build/three.module.js", "three.js MIT"),
)

LICENSE_FILES: tuple[tuple[str, str], ...] = ()     # three.js's licence comes from its tarball

_THREE_TARBALL_URL = (
    f"https://github.com/mrdoob/three.js/archive/refs/tags/{THREEJS_TAG}.tar.gz"
)

NOTICE_TEMPLATE = """optodraw offline 3D assets
=============================
three.js {three_version} (MIT) — {three_cdn}
Addon tree examples/jsm/ extracted from the three.js {three_tag} release tarball.
License text: LICENSES/three-LICENSE.
Google Fonts links are omitted offline; the page falls back to system sans stacks.
"""


def _download(url: str, opener: Callable[[str], object] | None = None) -> bytes:
    if opener is not None:
        response = opener(url)
        data = response.read() if hasattr(response, "read") else bytes(response)
        return bytes(data)
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _asset_target(dest: Path, relative: Path) -> Path:
    """Reject archive paths or existing symlinks that leave the asset directory."""

    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe offline asset path: {relative}")
    target = dest / relative
    if not target.resolve().is_relative_to(dest.resolve()):
        raise ValueError(f"offline asset path leaves destination: {relative}")
    return target


def _extract_jsm_tree(tarball: bytes, dest: Path) -> int:
    """Extract ``examples/jsm/`` plus the root LICENSE from a release tarball."""

    count = 0
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 2:
                continue
            inner = Path(*parts[1:])
            if inner.parts[:2] == ("examples", "jsm") and member.isfile():
                target = _asset_target(dest, inner)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is not None:
                    target.write_bytes(source.read())
                    count += 1
            elif inner == Path("LICENSE") and member.isfile():
                source = archive.extractfile(member)
                if source is not None:
                    _asset_target(dest, Path("LICENSES/three-LICENSE")).write_bytes(source.read())
    return count


def bundle_offline_assets(
    dest: str | Path, *, opener: Callable[[str], object] | None = None
) -> dict[str, str]:
    """Download pinned 3D assets into ``dest``. Returns ``{name: version}``."""

    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True)
    (root / "LICENSES").mkdir(exist_ok=True)

    for name, url, _license in SINGLE_FILES:
        data = _download(url, opener)
        if not data:
            raise RuntimeError(f"empty download for offline asset {url}")
        _asset_target(root, Path(name)).write_bytes(data)

    tarball = _download(_THREE_TARBALL_URL, opener)
    found = _extract_jsm_tree(tarball, root)
    if found == 0:
        raise RuntimeError("three.js tag tarball contained no examples/jsm files")

    for name, url in LICENSE_FILES:
        data = _download(url, opener)
        if not data:
            raise RuntimeError(f"empty download for offline asset license {url}")
        _asset_target(root, Path("LICENSES") / name).write_bytes(data)

    _asset_target(root, Path("LICENSES/NOTICE.txt")).write_text(
        NOTICE_TEMPLATE.format(
            three_version=THREEJS_VERSION,
            three_cdn=THREEJS_CDN,
            three_tag=THREEJS_TAG,
        ),
        encoding="utf-8",
    )
    versions = {
        "three": THREEJS_VERSION,
        "three_tag": THREEJS_TAG,
    }
    _asset_target(root, Path("versions.json")).write_text(json.dumps(versions, indent=1), encoding="utf-8")
    return versions


def rewrite_html_offline(html: str, assets_rel: str) -> str:
    """Point a rendered page at a sibling assets dir; drop webfont links."""

    base = assets_rel.rstrip("/")
    html = html.replace(f"{THREEJS_CDN}/build/three.module.js", f"{base}/three.module.js")
    html = html.replace(f"{THREEJS_CDN}/examples/jsm/", f"{base}/examples/jsm/")
    return re.sub(
        r"<link\b[^>]*(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>",
        "",
        html,
        flags=re.IGNORECASE,
    )
