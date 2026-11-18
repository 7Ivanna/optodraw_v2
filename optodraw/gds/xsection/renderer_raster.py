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
    dpi = _checked_dpi(dpi)
    try:
        import cairosvg
    except ImportError as exc:
        raise ImportError("cairosvg is required for PNG rasterization") from exc

    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), dpi=dpi)
    return png_path


def rasterize_svg_text_to_png(svg_text: str, png_path: Path, *, dpi: int = 300) -> Path:
    dpi = _checked_dpi(dpi)
    try:
        import cairosvg
    except ImportError as exc:
        raise ImportError("cairosvg is required for PNG rasterization") from exc

    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), write_to=str(png_path), dpi=dpi)
    return png_path
