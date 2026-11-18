"""GDS Lens, the engine of the layout view: one self-contained ES module (GDSII and OASIS parsed by gdstk in
WebAssembly, drawn with WebGL2), vendored at a pinned version with its licences (see vendor/gds-lens/NOTICE).

This is the one place that names the version, so the editor, the notebook view and the one-file page load
the same file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

GDS_LENS_VERSION = "1.7.0"
GDS_LENS_SHA256 = "56ce13fb77926de4374a1a1dfa617ccfe7d820d946f47f346b5e55fd2c94050c"


def gds_lens_path() -> Path:
    """The vendored `gds-lens.js` (the package's single-file esm build)."""

    return Path(__file__).parent / "js" / "vendor" / "gds-lens" / "gds-lens.js"


@lru_cache(maxsize=1)
def gds_lens_source() -> str:
    """The text of `gds-lens.js`, read once."""

    return gds_lens_path().read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def gds_lens_host_source() -> str:
    """optodraw's GDS Lens host (``js/gds_lens_host.js``): a classic script to run before ``gds-lens.js``."""

    return (Path(__file__).parent / "js" / "gds_lens_host.js").read_text(encoding="utf-8")
