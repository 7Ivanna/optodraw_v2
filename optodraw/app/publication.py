"""Publication figure-bundle export for the GUI → zip download.

Thin wrapper over ``optodraw.build_publication_bundle`` (writes SVG/TikZ/PNG/JSON +
caption + manifest to a directory); we zip that directory and hand back the bytes.
"""

from __future__ import annotations

import io
import pathlib
import tempfile
import zipfile
from typing import Any


def templates() -> dict[str, Any]:
    """Available figure templates + paper figure presets for the dialog."""

    from optodraw import list_paper_figure_presets, list_publication_templates

    return {"templates": list_publication_templates(), "presets": list_paper_figure_presets()}


def build_zip(
    scene: Any,
    *,
    template: str = "single_figure",
    formats: list[str] | tuple[str, ...] = ("svg", "json"),
    preset: str | None = None,
    caption: str | None = None,
    include_polarization: bool = False,
    view: str = "2d",
) -> bytes:
    """Build a publication bundle and return it as a zip archive (bytes)."""

    from optodraw import build_publication_bundle

    with tempfile.TemporaryDirectory() as tmp:
        build_publication_bundle(
            scene,
            tmp,
            template=template,
            formats=tuple(formats) or ("svg", "json"),
            preset=preset or None,
            caption=caption or None,
            include_polarization=bool(include_polarization),
            view=view,
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(pathlib.Path(tmp).rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp).as_posix())
        return buf.getvalue()
