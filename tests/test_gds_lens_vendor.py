"""The layout view's engine: GDS Lens 1.7.0 (MIT), its single-file esm build, vendored with its licences."""

from __future__ import annotations

import hashlib


def test_the_vendored_viewer_is_the_pinned_build():
    from optodraw.renderers.gds_lens import GDS_LENS_SHA256, GDS_LENS_VERSION, gds_lens_path

    path = gds_lens_path()
    assert GDS_LENS_VERSION == "1.7.0"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == GDS_LENS_SHA256
    assert 'customElements.define("gds-lens"' in path.read_text(encoding="utf-8")


def test_the_licences_travel_with_the_viewer():
    from optodraw.renderers.gds_lens import GDS_LENS_SHA256, gds_lens_path

    folder = gds_lens_path().parent
    assert (folder / "LICENCE.md").read_text(encoding="utf-8").startswith("MIT License")
    assert "gdstk" in (folder / "THIRD-PARTY-LICENSES.md").read_text(encoding="utf-8")
    notice = (folder / "NOTICE").read_text(encoding="utf-8")
    assert "1.7.0" in notice and GDS_LENS_SHA256 in notice and "registry.npmjs.org" in notice


def test_the_viewer_fetches_nothing():
    from optodraw.renderers.gds_lens import gds_lens_source

    src = gds_lens_source()
    assert "gds-lens-engine.wasm" not in src            # the esm build inlines its binary
    assert gds_lens_source() is src                     # read once
