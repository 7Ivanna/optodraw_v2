"""Offline 3D asset bundling — all downloads mocked, no network in tests."""

from __future__ import annotations

import io
import json
import tarfile

from optodraw.renderers import offline_assets
from optodraw.renderers.offline_assets import (
    bundle_offline_assets,
    rewrite_html_offline,
)
from optodraw.renderers.threejs_renderer import (
    THREEJS_CDN,
    THREEJS_TAG,
    THREEJS_VERSION,
)


def _fake_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in {
            f"three.js-{THREEJS_TAG}/examples/jsm/controls/OrbitControls.js": b"export {};",
            f"three.js-{THREEJS_TAG}/LICENSE": b"MIT license text",
        }.items():
            payload = io.BytesIO(data)
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, payload)
    return buffer.getvalue()


def _opener(url: str):
    class _Fake:
        def __init__(self, data: bytes):
            self._data = data

        def read(self) -> bytes:
            return self._data

    if url.endswith(".tar.gz"):
        return _Fake(_fake_tarball())
    return _Fake(f"/* pinned bytes for {url} */".encode())


class TestBundle:
    def test_writes_files_licenses_and_versions(self, tmp_path):
        dest = tmp_path / "scene_assets"
        versions = bundle_offline_assets(dest, opener=_opener)
        assert versions["three"] == THREEJS_VERSION
        assert (dest / "three.module.js").is_file()
        assert not (dest / "three-mesh-bvh.js").exists()                      # the studio renderer needs no
        assert not (dest / "three-gpu-pathtracer.js").exists()                # GPU path tracer
        assert (dest / "examples" / "jsm" / "controls" / "OrbitControls.js").is_file()
        assert (dest / "LICENSES" / "NOTICE.txt").is_file()
        assert (dest / "LICENSES" / "three-LICENSE").is_file()
        assert json.loads((dest / "versions.json").read_text())["three_tag"] == THREEJS_TAG

    def test_empty_tarball_fails_loudly(self, tmp_path):
        import pytest

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz"):
            pass

        def _empty(url: str):
            class _Fake:
                def read(self) -> bytes:
                    return buffer.getvalue()

            return _Fake()

        with pytest.raises(RuntimeError, match="no examples/jsm files"):
            bundle_offline_assets(tmp_path / "bad", opener=_empty)


class TestRewrite:
    def test_urls_become_relative_and_fonts_drop(self):
        html = (
            '<link rel="preconnect" href="https://fonts.googleapis.com"/>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter"/>\n'
            '<script type="importmap">{"imports": {'
            f'"three": "{THREEJS_CDN}/build/three.module.js",'
            f'"three/addons/": "{THREEJS_CDN}/examples/jsm/"'
            "}}</script>"
        )
        out = rewrite_html_offline(html, "scene_assets")
        assert "https://" not in out
        assert "fonts.googleapis" not in out
        assert '"three": "scene_assets/three.module.js"' in out
        assert '"three/addons/": "scene_assets/examples/jsm/"' in out

    def test_constants_match_renderer(self):
        assert [name for name, _, _ in offline_assets.SINGLE_FILES] == ["three.module.js"]
        assert offline_assets.SINGLE_FILES[0][1] == f"{THREEJS_CDN}/build/three.module.js"
