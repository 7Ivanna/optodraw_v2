"""Optional PNG rasterization from cross-section SVG output."""

from __future__ import annotations

from math import isfinite
from pathlib import Path


def _checked_dpi(dpi: int) -> float:
    value = float(dpi)
    if not isfinite(value) or value <= 0:
        raise ValueError("PNG dpi must be a positive finite number")
    return value


def rasterize_svg_to_png(svg_path: Path, png_path: Path, *, dpi: int = 300) -> Path:
    return rasterize_svg_text_to_png(Path(svg_path).read_text(encoding="utf-8"), png_path, dpi=dpi)


def rasterize_svg_text_to_png(svg_text: str, png_path: Path, *, dpi: int = 300) -> Path:
    from optodraw.raster import svg_to_png

    dpi = _checked_dpi(dpi)
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(svg_to_png(svg_text, dpi=dpi))
    return png_path
