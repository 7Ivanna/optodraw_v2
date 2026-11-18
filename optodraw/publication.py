"""Publication figure templates and multi-format export bundles.

This module exposes two layers:

1. **Single-figure presets** (`paper_figure_preset`, `export_figure_bundle`,
   `export_paper_figures`) — the original, lightweight helpers for emitting an
   SVG + HTML + JSON triple sized for a journal column or slide.

2. **Multi-format publication bundles** (`PublicationBundle`,
   `build_publication_bundle`, named layout templates, caption builder,
   provenance manifest) — coordinated SVG / TikZ / PNG / JSON drops, with an
   optional cross-section bundle, a markdown caption stub assembled from
   ``physical_spec`` / ``physics_metadata``, and a provenance manifest that
   records the scene hash, the optodraw version, the component list, and the
   render timestamp.

The legacy single-figure API remains available; exported scene JSON retains
the original scene dimensions rather than the temporary paper frame.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
import shutil
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from optodraw.core.scene import Scene

# Scene width/height are treated as millimetres for paper presets.
_FIGURE_PRESETS: dict[str, dict[str, Any]] = {
    "default": {
        "width": 89.0,
        "height": 70.0,
        "font_size_pt": 8.0,
        "camera_distance": 120.0,
        "show_grid": False,
        "show_labels": True,
        "background": "#ffffff",
        "show_export_controls": False,
        "lighting_preset": "publication",
        "render_quality": "publication",
    },
    "single_column": {
        "width": 89.0,
        "height": 70.0,
        "font_size_pt": 8.0,
        "camera_distance": 120.0,
        "show_grid": False,
        "show_labels": True,
        "background": "#ffffff",
        "show_export_controls": False,
        "lighting_preset": "publication",
        "render_quality": "publication",
    },
    "double_column": {
        "width": 183.0,
        "height": 120.0,
        "font_size_pt": 8.0,
        "camera_distance": 180.0,
        "show_grid": False,
        "show_labels": True,
        "background": "#ffffff",
        "show_export_controls": False,
        "lighting_preset": "publication",
        "render_quality": "publication",
    },
    "full_width": {
        "width": 183.0,
        "height": 140.0,
        "font_size_pt": 9.0,
        "camera_distance": 200.0,
        "show_grid": False,
        "show_labels": True,
        "background": "#ffffff",
        "show_export_controls": False,
        "lighting_preset": "publication",
        "render_quality": "publication",
    },
    "nature_single": {
        "width": 89.0,
        "height": 60.0,
        "font_size_pt": 7.0,
        "camera_distance": 115.0,
        "show_grid": False,
        "show_labels": True,
        "background": "#ffffff",
        "show_export_controls": False,
        "lighting_preset": "publication",
        "render_quality": "publication",
    },
    "ieee_double": {
        "width": 178.0,
        "height": 110.0,
        "font_size_pt": 8.0,
        "camera_distance": 175.0,
        "show_grid": False,
        "show_labels": True,
        "background": "#ffffff",
        "show_export_controls": False,
        "lighting_preset": "publication",
        "render_quality": "publication",
    },
    "presentation": {
        "width": 240.0,
        "height": 135.0,
        "font_size_pt": 12.0,
        "camera_distance": 220.0,
        "show_grid": True,
        "show_labels": True,
        "background": "#f4f6f8",
        "show_export_controls": True,
        "lighting_preset": "studio",
        "render_quality": "interactive",
    },
}

_PRESET_ALIASES = {
    "paper": "single_column",
    "column": "single_column",
    "two_column": "double_column",
    "slide": "presentation",
}


def list_paper_figure_presets() -> list[str]:
    """Return built-in publication figure preset names."""

    return sorted(_FIGURE_PRESETS.keys())


def paper_figure_preset(name: str) -> dict[str, Any]:
    """Return render kwargs for a named publication figure template."""

    key = name.strip().lower().replace("-", "_")
    key = _PRESET_ALIASES.get(key, key)
    if key not in _FIGURE_PRESETS:
        available = ", ".join(list_paper_figure_presets())
        raise KeyError(f"Unknown paper figure preset '{name}'. Available: {available}")
    return dict(_FIGURE_PRESETS[key])


def _dpi_to_scale(dpi: float) -> float:
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    return float(dpi) / 76.2


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.strip().lower())
    slug = slug.strip("_")
    return slug or "figure"


def _svg_kwargs(preset: dict[str, Any], *, dpi: float, include_polarization: bool, view: str = "2d") -> dict[str, Any]:
    kwargs = {"scale": _dpi_to_scale(dpi)}
    if include_polarization:
        kwargs["show_polarization_overlay"] = True
    if view == "1d":
        kwargs["onchip_view"] = "1d"
    kwargs["font_size_pt"] = preset.get("font_size_pt", 8.0)
    return kwargs


def _format_views(paths: dict[str, Path], view: str) -> dict[str, str]:
    """Record the actual representation in each exported file."""

    if view == "xsection":
        return {fmt: "xsection" for fmt in paths}
    return {
        fmt: "3d" if fmt == "html" else "scene" if fmt == "json" else view
        for fmt in paths
    }


def _threejs_kwargs(preset: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "camera_distance",
        "show_grid",
        "show_labels",
        "background",
        "show_export_controls",
        "lighting_preset",
        "render_quality",
        "postprocessing",
    )
    return {key: preset[key] for key in keys if key in preset}


def _labelled(scene: Scene) -> list[Any]:
    """The parts whose label prints beside them, so the frame holds it: not beams, routes, scenery or insets."""

    from optodraw.check import _BACKGROUND

    return [n for n in scene.walk() if getattr(n, "label", "") and callable(getattr(n, "ports", None))
            and getattr(n, "component_type", "") not in _BACKGROUND | {"Beam", "FocusingBeam", "Route",
                                                                       "WaveguideRoute", "FiberRoute",
                                                                       "MetalRoute", "Inset"}]   # its label is a name


def _fitted_svg(scene: Scene, options: dict[str, Any], *, width_mm: float) -> str:
    """The 2D view framed on its content (labels included) and sized ``width_mm`` wide on the page, with the labels
    at ``options["font_size_pt"]`` points on the page whatever the scene's units."""

    import re

    from optodraw.check import _label_box

    page_pt = float(options.get("font_size_pt", 8.0))
    insets = [n for n in scene.walk() if getattr(n, "component_type", "") == "Inset"]
    for node in insets:                                  # one print state to start from: two exports of one scene
        node.set_print(1.0, page_pt)                     # give the same file; each pass asks a live source again
    x0, y0, x1, y1 = (float(v) for v in scene.content_bounds())
    labelled = _labelled(scene)
    box, mm_per_unit, render_pt = (x0, y0, x1, y1), width_mm / max(x1 - x0, 1e-9), page_pt
    for _ in range(4):                                   # the label size depends on the scale, and the frame on both
        for node in insets:                              # each inset draws at its mm width and the page's text size
            node.set_print(mm_per_unit, page_pt)
        x0, y0, x1, y1 = (float(v) for v in scene.content_bounds())     # with the insets at this scale
        render_pt = page_pt * 0.3528 * 8.0 / (3.0 * mm_per_unit)
        boxes = [(x0, y0, x1, y1)] + [_label_box(node, render_pt) for node in labelled]
        pad = 3.0 * render_pt / 8.0
        box = (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
               max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)
        mm_per_unit = width_mm / (box[2] - box[0])
    for node in insets:
        node.set_print(mm_per_unit, page_pt)
    width, height = box[2] - box[0], box[3] - box[1]
    original = scene.width, scene.height
    scene.width, scene.height = 2.0 * max(abs(box[0]), abs(box[2])), 2.0 * max(abs(box[1]), abs(box[3]))
    try:
        svg = scene.render_svg(**{**options, "font_size_pt": render_pt}).as_svg()
    finally:
        scene.width, scene.height = original
    root = re.search(r"<svg\b[^>]*>", svg).group(0)
    fitted = re.sub(r'\s(width|height|viewBox|font-family)="[^"]*"', "", root)
    fitted = fitted[:-1] + (f' width="{width_mm:g}mm" height="{height * mm_per_unit:.2f}mm" '
                            f'viewBox="{box[0]:.4f} {-box[3]:.4f} {width:.4f} {height:.4f}" '
                            'font-family="Helvetica, Arial, sans-serif">')
    return svg.replace(root, fitted, 1)


def _write_fitted_svg(scene: Scene, path: Path, options: dict[str, Any], *, width_mm: float) -> None:
    path.write_text(_fitted_svg(scene, options, width_mm=width_mm), encoding="utf-8")


def _figure_formats(formats: Iterable[str]) -> tuple[str, ...]:
    wanted = tuple(str(fmt).strip().lower() for fmt in formats)
    unknown = sorted(set(wanted) - {"svg", "pdf", "png"})
    if unknown:
        raise ValueError(f"Unsupported formats: {', '.join(unknown)}")
    return wanted


def _write_figure(svg: str, path: str | Path, wanted: tuple[str, ...], *, width_mm: float, dpi: float) -> dict[str, Path]:
    """Write the figure's SVG text in each wanted format, next to ``path``, and return their paths."""

    stem = Path(path)
    stem.parent.mkdir(parents=True, exist_ok=True)
    svg_path = stem.parent / f"{stem.name}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    written = {"svg": svg_path} if "svg" in wanted else {}
    if "pdf" in wanted or "png" in wanted:
        from optodraw.raster import svg_to_pdf, svg_to_png

        if "pdf" in wanted:
            written["pdf"] = svg_to_pdf(svg, stem.parent / f"{stem.name}.pdf")
        if "png" in wanted:
            written["png"] = stem.parent / f"{stem.name}.png"
            written["png"].write_bytes(svg_to_png(svg, width=round(float(width_mm) / 25.4 * float(dpi)),
                                                  background="white"))
    if "svg" not in wanted:
        svg_path.unlink()
    return written


def export_figure(scene: Scene, path: str | Path, *, width_mm: float, font_size_pt: float = 7.0, dpi: float = 800,
                  formats: Iterable[str] = ("svg", "pdf", "png")) -> dict[str, Path]:
    """Write the 2D figure ``width_mm`` wide on the page, framed on its content and labels, with the labels at
    ``font_size_pt``. ``path`` is the file name without its suffix; each format adds its own. PDF and PNG need
    ``pip install optodraw[gif]``. Returns the path of each format."""

    wanted = _figure_formats(formats)
    svg = _fitted_svg(scene, {"font_size_pt": float(font_size_pt)}, width_mm=float(width_mm))
    return _write_figure(svg, path, wanted, width_mm=float(width_mm), dpi=dpi)


@dataclass(frozen=True)
class Panel:
    """One panel of :func:`export_panels`: anything an :class:`~optodraw.Inset` holds, such as a :class:`Scene`, a
    cross-section, a matplotlib figure, an array, or the path of an SVG, PDF, PNG, JPEG or TIFF file.

    ``letter`` replaces the panel's next letter; ``""`` leaves it out and takes no letter, so the next panel gets it.
    ``drop_text`` names text to take out of an imported SVG, such as its old panel letter. ``share`` sets the part of
    the row's width the panel takes. ``view`` is ``"2d"`` or ``"1d"`` (the symbol schematic) for a scene. ``zoom`` says
    this panel is a closer view of a place on another: ``(panel, region)``, where ``panel`` is a :class:`Panel` of the
    figure or its source. ``region`` is a part of a 2D scene, or ``(x0, y0, x1, y1)`` in the units of ``Inset.at`` on
    that panel:

    - a 2D scene: scene units, y up;
    - a 1D scene: its drawing units, y down;
    - an SVG or PDF file: the file's own units, y down;
    - a picture: pixels from the top left, y down, or um with ``scale_um_per_px``;
    - a plot: the data of its first axes;
    - a section, and an SEM render of a section: um along the cut and z, up;
    - an SEM render of a top view: the layout file's um.

    A dashed grey box marks the place, a matching frame marks this panel, and two lines join them."""

    source: Any
    letter: str | None = None
    drop_text: tuple[str, ...] = ()
    share: float | None = None
    zoom: tuple[Any, Any] | None = None
    view: str = "2d"


ZOOM_COLOR = "#777777"
ZOOM_LINE_MM = 0.12                  # a third of a point: it reads as a guide and still prints
ZOOM_DASH_MM = "1 0.8"
CUT_COLOR = "#D55E00"                # Okabe-Ito vermillion: the cut line and its letters, apart from every film fill
CUT_LINE_MM = 0.25                   # 0.71 pt: it reads over the layer outlines (0.25 pt)


def _row_sizes(sizes: list[tuple[float, float]], shares: list[float | None], room: float) -> list[tuple[float, float]]:
    """The width and the height of each panel of a row. With no ``shares`` the panels share one height and fill
    ``room``. With shares, each panel with no share takes an even part of what is left."""

    if all(share is None for share in shares):
        height = room / sum(w / h for w, h in sizes)
        return [(height * w / h, height) for w, h in sizes]
    given = sum(share for share in shares if share is not None)
    empty = sum(share is None for share in shares)
    if given > 1.0 + 1e-9 or (empty and given >= 1.0):
        raise ValueError(f"the panel shares of a row add up to {given:g}: they leave no width")
    rest = (1.0 - given) / max(empty, 1)
    parts = [room * (rest if share is None else share) for share in shares]
    return [(part, part * h / w) for part, (w, h) in zip(parts, sizes)]


def _panel_inset(panel: Panel) -> Any:
    """The :class:`~optodraw.Inset` that draws ``panel``."""

    from optodraw.figure.inset import Inset

    options: dict[str, Any] = {"drop_text": panel.drop_text} if panel.drop_text else {}
    if isinstance(panel.source, Scene):
        if panel.drop_text:
            raise ValueError(f"drop_text takes text out of an SVG file, and the panel {panel.source.title!r} is a "
                             "scene: leave its labels out of the scene instead")
        options["view"] = panel.view
    elif panel.view != "2d":
        raise ValueError(f"view {panel.view!r} is for a scene panel, not for a {type(panel.source).__name__}")
    return Inset(panel.source, letter=panel.letter, **options)


def export_panels(path: str | Path, rows: Sequence[Any], *, width_mm: float, font_size_pt: float = 7.0,
                  dpi: float = 800, gap_mm: float = 2.0, letters: bool = True, letter_pt: float = 8.0,
                  formats: Iterable[str] = ("svg", "pdf", "png")) -> dict[str, Path]:
    """Write one figure of several panels, ``width_mm`` wide on the page, in the formats of :func:`export_figure`.

    ``rows`` is a list of rows, each a list of panels; a flat list is one row. A panel is anything a :class:`Panel`
    holds, or a :class:`Panel`. The panels of a row share one height and fill the width, unless a :class:`Panel` sets
    its ``share``; their top edges line up. Each panel gets the next letter (a, b, c) above its top left corner, in a
    band of its own, so a letter cannot touch a panel. Scene, section and plot text prints at ``font_size_pt``; an SVG
    or PDF file keeps its own sizes. A :class:`Panel` with ``zoom`` is linked to the place it shows. The figure is a
    :class:`~optodraw.Page` with one ``row`` per row of panels. Returns the path of each format.
    """

    from optodraw.figure.page import Page

    wanted = _figure_formats(formats)
    rows = list(rows)
    if not any(isinstance(row, (list, tuple)) for row in rows):
        rows = [rows]
    rows = [[item if isinstance(item, Panel) else Panel(item) for item in row] for row in rows]
    if not all(rows):
        raise ValueError("export_panels needs at least one panel in each row")

    page = Page(width_mm=width_mm, font_pt=font_size_pt, letters=letters, letter_pt=letter_pt)
    pairs = []
    for row in rows:
        insets = page.row([_panel_inset(panel) for panel in row], shares=[panel.share for panel in row], gap_mm=gap_mm)
        pairs += zip(row, insets)
    placed = {id(key): inset for panel, inset in pairs for key in (panel, panel.source)}
    for panel, big in pairs:
        if panel.zoom is None:
            continue
        name, region = panel.zoom
        if id(name) not in placed:
            raise ValueError("the panel a zoom looks at is not in the figure")
        page.zoom(placed[id(name)], region, big)
    return page.export(path, formats=wanted, dpi=dpi)


def export_figure_bundle(
    scene: Scene,
    output_dir: str | Path,
    *,
    formats: tuple[str, ...] = ("svg", "html", "json"),
    dpi: float = 300,
    include_polarization: bool = False,
    preset: str = "single_column",
    stem: str | None = None,
    view: str = "2d",
    fit: str | None = None,
) -> dict[str, Path]:
    """Write the figure in ``formats``. ``fit="width"`` scales the 2D drawing to the preset's page width, with
    labels at the preset's point size: the way to put a chip drawn in micrometres into a journal column."""

    if view not in {"1d", "2d"}:
        raise ValueError("Publication view must be '1d' or '2d'")
    if fit not in (None, "width"):
        raise ValueError("fit must be None or 'width'")
    if fit == "width" and view != "2d":
        raise ValueError("fit='width' scales the 2D view")
    normalized_formats = {fmt.strip().lower() for fmt in formats}
    unknown = normalized_formats - {"svg", "html", "json"}
    if unknown:
        raise ValueError(f"Unsupported formats: {', '.join(sorted(unknown))}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = stem or _slugify(scene.title)
    preset_values = paper_figure_preset(preset)

    frame_w = float(preset_values["width"])
    frame_h = float(preset_values["height"])
    over: list[str] = []
    try:
        min_x, min_y, max_x, max_y = scene.content_bounds()
        if min_x < -frame_w / 2.0 or max_x > frame_w / 2.0:
            over.append(f"x [{min_x:.1f}, {max_x:.1f}] vs frame ±{frame_w / 2.0:.1f}")
        if min_y < -frame_h / 2.0 or max_y > frame_h / 2.0:
            over.append(f"y [{min_y:.1f}, {max_y:.1f}] vs frame ±{frame_h / 2.0:.1f}")
    except Exception:                                    # a scene whose bounds cannot be measured: no warning
        over = []
    if over and fit is None:
        warnings.warn(
            f"preset '{preset}' frame ({frame_w:g} x {frame_h:g}) clips content "
            f"({'; '.join(over)}). Call scene.fit_frame() first, pick a wider preset, or pass fit='width'.",
            stacklevel=2,
        )

    original_width = scene.width
    original_height = scene.height
    scene.width = frame_w
    scene.height = frame_h

    written: dict[str, Path] = {}
    try:
        if "svg" in normalized_formats:
            svg_path = out_dir / f"{base}.svg"
            options = _svg_kwargs(preset_values, dpi=dpi, include_polarization=include_polarization, view=view)
            if fit == "width":
                _write_fitted_svg(scene, svg_path, options, width_mm=frame_w)
            else:
                scene.render_svg(svg_path.as_posix(), **options)
            written["svg"] = svg_path

        if "html" in normalized_formats:
            html_path = out_dir / f"{base}.html"
            scene.render_threejs(html_path.as_posix(), **_threejs_kwargs(preset_values))
            written["html"] = html_path

    finally:
        scene.width = original_width
        scene.height = original_height

    if "json" in normalized_formats:
        json_path = out_dir / f"{base}.json"
        scene.save(json_path)
        written["json"] = json_path

    manifest = _provenance_manifest(
        scene,
        template=_TEMPLATES["single_figure"],
        panels_written=[
            {
                "name": "main",
                "preset": preset,
                "dpi": dpi,
                "include_polarization": include_polarization,
                "view": view,
                "format_views": _format_views(written, view),
                "paths": {fmt: path.relative_to(out_dir).as_posix() for fmt, path in written.items()},
            }
        ],
        extras={"preset": preset, "dpi": dpi, "include_polarization": include_polarization, "view": view},
    )
    manifest_path = out_dir / f"{base}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    written["manifest"] = manifest_path

    return written


def _default_preset_for_scene(scene: Scene) -> str:
    if scene.platform == "on_chip":
        return "double_column"
    return "single_column"


def export_paper_figures(
    scene: Scene,
    output_dir: str | Path,
    *,
    preset: str | None = None,
    **kwargs: Any,
) -> dict[str, Path]:
    chosen = preset or _default_preset_for_scene(scene)
    return export_figure_bundle(scene, output_dir, preset=chosen, **kwargs)


# =============================================================================
# Multi-format publication bundles
# =============================================================================

#: Supported per-panel output formats for :class:`PublicationBundle`.
SUPPORTED_BUNDLE_FORMATS: tuple[str, ...] = ("svg", "tikz", "png", "html", "json")


@dataclass(frozen=True)
class PanelSpec:
    """Layout slot inside a publication template."""

    name: str
    label: str = ""
    width_fraction: float = 1.0
    height_fraction: float = 1.0
    row: int = 0
    column: int = 0
    role: str = "device"


@dataclass(frozen=True)
class TemplateSpec:
    """A named publication layout (panels, grid shape, suggested preset)."""

    name: str
    description: str
    panels: tuple[PanelSpec, ...]
    rows: int = 1
    columns: int = 1
    suggested_preset: str = "single_column"
    suggested_width_mm: float | None = None
    suggested_height_mm: float | None = None

    @property
    def panel_count(self) -> int:
        return len(self.panels)


_TEMPLATES: dict[str, TemplateSpec] = {
    "single_figure": TemplateSpec(
        name="single_figure",
        description="One scene, one panel. Default for single-column figures.",
        panels=(PanelSpec(name="main", label="(a)", role="device"),),
        rows=1,
        columns=1,
        suggested_preset="single_column",
    ),
    "two_panel_horizontal": TemplateSpec(
        name="two_panel_horizontal",
        description="Two side-by-side panels (e.g. device | physics summary).",
        panels=(
            PanelSpec(name="left", label="(a)", width_fraction=0.5, column=0, role="device"),
            PanelSpec(name="right", label="(b)", width_fraction=0.5, column=1, role="detail"),
        ),
        rows=1,
        columns=2,
        suggested_preset="double_column",
    ),
    "two_panel_vertical": TemplateSpec(
        name="two_panel_vertical",
        description="Stacked panels (e.g. top view above context view).",
        panels=(
            PanelSpec(name="top", label="(a)", height_fraction=0.5, row=0, role="device"),
            PanelSpec(name="bottom", label="(b)", height_fraction=0.5, row=1, role="detail"),
        ),
        rows=2,
        columns=1,
        suggested_preset="single_column",
    ),
    "four_panel_grid": TemplateSpec(
        name="four_panel_grid",
        description="2x2 grid for multi-condition or process-step figures.",
        panels=(
            PanelSpec(name="top_left", label="(a)", width_fraction=0.5, height_fraction=0.5, row=0, column=0, role="device"),
            PanelSpec(name="top_right", label="(b)", width_fraction=0.5, height_fraction=0.5, row=0, column=1, role="detail"),
            PanelSpec(name="bottom_left", label="(c)", width_fraction=0.5, height_fraction=0.5, row=1, column=0, role="detail"),
            PanelSpec(name="bottom_right", label="(d)", width_fraction=0.5, height_fraction=0.5, row=1, column=1, role="detail"),
        ),
        rows=2,
        columns=2,
        suggested_preset="double_column",
    ),
    "device_plus_xsection": TemplateSpec(
        name="device_plus_xsection",
        description="Top-down device above its cross-section bundle.",
        panels=(
            PanelSpec(name="device", label="(a)", height_fraction=0.6, row=0, role="device"),
            PanelSpec(name="xsection", label="(b)", height_fraction=0.4, row=1, role="xsection"),
        ),
        rows=2,
        columns=1,
        suggested_preset="single_column",
    ),
}


def list_publication_templates() -> list[str]:
    """Return the names of built-in publication layout templates."""

    return sorted(_TEMPLATES.keys())


def get_publication_template(name: str) -> TemplateSpec:
    """Resolve a layout template by name (raises ``KeyError`` if unknown)."""

    key = name.strip().lower().replace("-", "_")
    if key not in _TEMPLATES:
        available = ", ".join(list_publication_templates())
        raise KeyError(f"Unknown publication template '{name}'. Available: {available}")
    return _TEMPLATES[key]


def _hash_scene_spec(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _component_list(scene: Scene) -> list[dict[str, Any]]:
    """Flat list of (type, label, id, position) for each non-Group component."""

    components: list[dict[str, Any]] = []
    for node in scene.walk():
        if node.component_type == "Group":
            continue
        position = node.world_transform.position
        components.append(
            {
                "type": node.component_type,
                "label": getattr(node, "label", "") or "",
                "id": getattr(node, "_id", "") or "",
                "position_um": [position.x, position.y, position.z],
            }
        )
    return components


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int,)):
        return f"{value}"
    if isinstance(value, float):
        if abs(value) >= 1000 or (value != 0 and abs(value) < 0.01):
            return f"{value:.3g}"
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        formatted = ", ".join(_format_value(item) for item in value)
        return f"({formatted})"
    return str(value)


_PHYSICS_FIELD_UNITS: dict[str, str] = {
    "length": " µm",
    "width": " µm",
    "bend_radius": " µm",
    "ring_radius": " µm",
    "coupling_length": " µm",
    "arm_length": " µm",
    "arm_gap": " µm",
    "amplifier_length": " µm",
    "wavelength": " nm",
    "design_wavelength_nm": " nm",
    "cutoff_wavelength": " nm",
    "pitch": " µm",
    "thickness": " µm",
    "aperture": " mm",
    "focal_length": " mm",
}

_PHYSICS_FIELD_PRIORITY: tuple[str, ...] = (
    "component",
    "wavelength",
    "design_wavelength_nm",
    "length",
    "width",
    "ring_radius",
    "bend_radius",
    "coupling_length",
    "arm_length",
    "arm_gap",
    "focal_length",
    "aperture",
    "pitch",
    "split_ratio",
    "extinction_ratio",
    "axis_angle",
    "fast_axis_angle",
    "retardance",
    "modulation_mechanism",
    "drive_style",
    "effective_index",
)


def _build_component_caption_fragment(node: Any) -> str | None:
    """Format physical_spec + physics_metadata into a single readable line."""

    label = (getattr(node, "label", "") or "").strip()
    component_type = getattr(node, "component_type", node.__class__.__name__)
    fields: list[tuple[str, Any]] = []

    physical = None
    if hasattr(node, "physical_spec"):
        try:
            physical = node.physical_spec()
        except Exception:
            physical = None
    if physical is not None and getattr(physical, "values", None):
        for key, value in physical.values.items():
            if value is None:
                continue
            fields.append((key, value))

    physics = None
    if hasattr(node, "physics_metadata"):
        try:
            physics = node.physics_metadata()
        except Exception:
            physics = None
    if isinstance(physics, dict):
        for key, value in physics.items():
            if key in {"domain", "component"} or value is None:
                continue
            if key in {key_b for key_b, _ in fields}:
                continue
            fields.append((key, value))

    if not fields and not label:
        return None

    seen: set[str] = set()
    priority_first: list[tuple[str, Any]] = []
    rest: list[tuple[str, Any]] = []
    field_map = dict(fields)
    for key in _PHYSICS_FIELD_PRIORITY:
        if key in field_map and key not in seen:
            priority_first.append((key, field_map[key]))
            seen.add(key)
    for key, value in fields:
        if key in seen:
            continue
        rest.append((key, value))
        seen.add(key)
    ordered = priority_first + rest

    pieces: list[str] = []
    for key, value in ordered[:6]:
        unit = _PHYSICS_FIELD_UNITS.get(key, "")
        pieces.append(f"{key.replace('_', ' ')} = {_format_value(value)}{unit}")

    head_label = label or component_type
    if pieces:
        return f"**{head_label}** ({component_type}): " + "; ".join(pieces) + "."
    return f"**{head_label}** ({component_type})."


def build_caption(
    scene: Scene,
    *,
    title: str | None = None,
    extra_notes: str | None = None,
    include_routes: bool = True,
    max_components: int = 12,
) -> str:
    """Assemble a markdown caption draft from physical_spec / physics_metadata.

    The caption opens with a sentence summarizing the scene title and platform,
    then lists up to ``max_components`` device fragments built from each
    component's ``physical_spec()`` and ``physics_metadata()``. If
    ``include_routes`` is set, routed interconnect lengths are appended.
    """

    heading = (title or scene.title or "Figure").strip()
    parts: list[str] = [f"**{heading}.**"]
    platform = getattr(scene, "platform", "free_space")
    platform_phrase = {
        "free_space": "free-space optical setup",
        "on_chip": "integrated photonic layout",
    }.get(platform, f"{platform.replace('_', ' ')} setup")
    parts.append(f"{platform_phrase.capitalize()}.")

    fragments: list[str] = []
    routes_summary: list[str] = []
    for node in scene.walk():
        component_type = getattr(node, "component_type", "")
        if component_type in {"Group", "Beam", "FocusingBeam", "Grid"}:
            continue
        if component_type in {"Route", "WaveguideRoute", "FiberRoute"}:
            if include_routes and len(routes_summary) < max_components:
                kind = getattr(node, "kind", "route")
                length_um = getattr(node, "physical_length_um", None)
                label = (getattr(node, "label", "") or "").strip()
                head = label or component_type
                try:
                    measured_length = float(length_um)
                except (TypeError, ValueError, OverflowError):
                    measured_length = 0.0
                if math.isfinite(measured_length) and measured_length > 0:
                    routes_summary.append(
                        f"{head} ({kind}, {measured_length:.2f} µm physical length)"
                    )
                else:
                    routes_summary.append(f"{head} ({kind})")
            continue
        if len(fragments) < max_components:
            fragment = _build_component_caption_fragment(node)
            if fragment is not None:
                fragments.append(fragment)

    if fragments:
        parts.append("Components: " + " ".join(fragments))
    if routes_summary:
        parts.append("Routes: " + "; ".join(routes_summary) + ".")
    if extra_notes:
        parts.append(extra_notes.strip())

    return "\n\n".join(parts).strip() + "\n"


def _provenance_manifest(
    scene: Scene,
    *,
    template: TemplateSpec,
    panels_written: list[dict[str, Any]],
    extras: dict[str, Any] | None = None,
    timestamp: _dt.datetime | None = None,
) -> dict[str, Any]:
    from optodraw import __version__ as _optodraw_version

    spec = scene.to_spec()
    moment = (timestamp or _dt.datetime.now(_dt.timezone.utc)).isoformat()
    return {
        "schema": "optodraw.publication_bundle/1",
        "title": scene.title,
        "platform": scene.platform,
        "optodraw_version": _optodraw_version,
        "scene_hash_sha256": _hash_scene_spec(spec),
        "scene_schema_version": spec.get("schema_version"),
        "render_timestamp": moment,
        "template": {
            "name": template.name,
            "description": template.description,
            "rows": template.rows,
            "columns": template.columns,
            "panels": [
                {
                    "name": panel.name,
                    "label": panel.label,
                    "row": panel.row,
                    "column": panel.column,
                    "role": panel.role,
                }
                for panel in template.panels
            ],
        },
        "panels": panels_written,
        "components": _component_list(scene),
        "extras": dict(extras or {}),
    }


@dataclass
class PublicationBundle:
    """Coordinated multi-format export for a publication figure.

    ``primary_paths`` lists the formats emitted for the first / main panel
    (``svg``, ``tikz``, ``png``, ``html``, ``json``).  ``panels`` records one
    entry per template slot, including their per-format paths.  ``caption_path``
    points at the markdown caption stub and ``manifest_path`` at the provenance
    JSON manifest.  ``xsection_bundle`` is populated when a cross-section
    bundle was attached via the ``xsection`` keyword.
    """

    output_dir: Path
    template: TemplateSpec
    primary_paths: dict[str, Path] = field(default_factory=dict)
    panels: list[dict[str, Any]] = field(default_factory=list)
    caption_path: Path | None = None
    manifest_path: Path | None = None
    xsection_bundle: Any | None = None
    figure_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "template": self.template.name,
            "primary_paths": {key: str(path) for key, path in self.primary_paths.items()},
            "panels": [
                {**panel, "paths": {fmt: str(path) for fmt, path in panel.get("paths", {}).items()}}
                for panel in self.panels
            ],
            "caption_path": None if self.caption_path is None else str(self.caption_path),
            "manifest_path": None if self.manifest_path is None else str(self.manifest_path),
            "xsection_composite": (
                None
                if self.xsection_bundle is None or getattr(self.xsection_bundle, "composite_path", None) is None
                else str(self.xsection_bundle.composite_path)
            ),
        }


def _resolve_panel_scenes(
    scene: Scene,
    template: TemplateSpec,
    extra_scenes: Sequence[Scene] | None,
) -> list[Scene]:
    """Match the requested template's panels to an ordered list of scenes.

    The primary ``scene`` is always assigned to panel 0.  Subsequent panels use
    ``extra_scenes`` if provided; missing extras default to the primary scene
    (so a single source scene can fill every slot of a multi-panel template).
    """

    extras = list(extra_scenes or [])
    out: list[Scene] = []
    for index, _panel in enumerate(template.panels):
        if index == 0:
            out.append(scene)
        elif index - 1 < len(extras):
            out.append(extras[index - 1])
        else:
            out.append(scene)
    return out


def _normalize_bundle_formats(formats: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(fmt.strip().lower() for fmt in formats))
    unknown = [fmt for fmt in normalized if fmt not in SUPPORTED_BUNDLE_FORMATS]
    if unknown:
        raise ValueError(
            f"Unsupported publication bundle format(s): {', '.join(sorted(unknown))}. "
            f"Choose from: {', '.join(SUPPORTED_BUNDLE_FORMATS)}"
        )
    return normalized


def _maybe_rasterize_svg(svg_path: Path, png_path: Path, *, dpi: int) -> tuple[Path | None, str | None]:
    """Rasterize an SVG to PNG. Returns ``(path, None)`` on success or
    ``(None, reason)`` so callers can surface *why* PNG was skipped instead of
    silently dropping the requested format."""
    try:
        from optodraw.gds.xsection.renderer_raster import rasterize_svg_to_png
    except Exception as error:
        return None, f"PNG raster backend unavailable ({error})"
    try:
        return rasterize_svg_to_png(svg_path, png_path, dpi=dpi), None
    except ImportError:
        return None, "PNG export needs the 'cairosvg' package — install it with: pip install cairosvg"
    except Exception as error:
        return None, f"PNG render failed: {error}"


def _render_panel(
    scene: Scene,
    panel: PanelSpec,
    output_dir: Path,
    *,
    base_stem: str,
    preset_values: dict[str, Any],
    panel_width_mm: float,
    panel_height_mm: float,
    formats: tuple[str, ...],
    dpi: float,
    include_polarization: bool,
    view: str,
) -> dict[str, Path]:
    stem = f"{base_stem}_{panel.name}"
    out: dict[str, Path] = {}

    original_width = scene.width
    original_height = scene.height
    scene.width = float(panel_width_mm)
    scene.height = float(panel_height_mm)
    try:
        if "svg" in formats:
            svg_path = output_dir / f"{stem}.svg"
            scene.render_svg(
                svg_path.as_posix(),
                **_svg_kwargs(
                    preset_values,
                    dpi=dpi,
                    include_polarization=include_polarization,
                    view=view,
                ),
            )
            out["svg"] = svg_path
        if "tikz" in formats:
            tex_path = output_dir / f"{stem}.tex"
            scene.render_tikz(tex_path.as_posix(), view=view)
            out["tikz"] = tex_path
        if "png" in formats:
            png_path = output_dir / f"{stem}.png"
            svg_for_png = out.get("svg")
            if svg_for_png is None:
                tmp_svg = output_dir / f"{stem}._raster.svg"
                scene.render_svg(
                    tmp_svg.as_posix(),
                    **_svg_kwargs(
                        preset_values,
                        dpi=dpi,
                        include_polarization=include_polarization,
                        view=view,
                    ),
                )
                svg_for_png = tmp_svg
            rasterized, reason = _maybe_rasterize_svg(svg_for_png, png_path, dpi=int(dpi))
            if rasterized is not None:
                out["png"] = rasterized
            else:
                # PNG was requested but couldn't be produced — surface it instead of
                # silently dropping the format (the SVG/TikZ panels still ship).
                note = output_dir / f"{stem}.png.MISSING.txt"
                note.write_text(
                    f"PNG export skipped for panel '{panel.name}'.\nReason: {reason}\n"
                    "The SVG/TikZ versions of this panel were written normally.\n",
                    encoding="utf-8",
                )
                warnings.warn(f"PNG export skipped for '{panel.name}': {reason}", RuntimeWarning, stacklevel=2)
            if svg_for_png != out.get("svg") and svg_for_png.exists():
                try:
                    svg_for_png.unlink()
                except OSError:
                    pass
        if "html" in formats:
            html_path = output_dir / f"{stem}.html"
            scene.render_threejs(html_path.as_posix(), **_threejs_kwargs(preset_values))
            out["html"] = html_path
    finally:
        scene.width = original_width
        scene.height = original_height

    if "json" in formats:
        json_path = output_dir / f"{stem}.json"
        scene.save(json_path)
        out["json"] = json_path

    return out


def build_publication_bundle(
    scene: Scene,
    output_dir: str | Path,
    *,
    template: str | TemplateSpec = "single_figure",
    formats: Iterable[str] = ("svg", "tikz", "json"),
    preset: str | None = None,
    dpi: float = 300,
    include_polarization: bool = False,
    stem: str | None = None,
    caption: str | None = None,
    caption_notes: str | None = None,
    extra_scenes: Sequence[Scene] | None = None,
    xsection: Any | None = None,
    extras: dict[str, Any] | None = None,
    view: str = "2d",
) -> PublicationBundle:
    """Render a coordinated multi-format publication bundle.

    Parameters
    ----------
    scene
        Primary scene; always assigned to the first panel of the chosen
        template.
    output_dir
        Destination directory.  Created if it does not exist.
    template
        Either a named template (see :func:`list_publication_templates`) or a
        custom :class:`TemplateSpec`.
    formats
        Subset of ``svg``, ``tikz``, ``png``, ``html``, ``json`` to emit for
        each panel.  ``png`` requires ``cairosvg``; if it is unavailable the
        PNG is silently skipped (the SVG and TikZ are still emitted).
    preset
        Override the template's suggested paper preset.
    dpi
        Used for both SVG scaling and optional PNG rasterization.
    include_polarization
        Enable the polarization overlay in the SVG renderer.
    stem
        Override the slugified filename stem.
    caption
        If provided, write this text verbatim.  Otherwise call
        :func:`build_caption` on the primary scene.
    caption_notes
        Optional trailing markdown paragraph appended to the auto-built caption.
    extra_scenes
        Optional scenes for additional template panels.  When fewer scenes are
        provided than the template requires, the primary scene fills the
        remaining slots.
    xsection
        Optional :class:`~optodraw.gds.XSectionBundle` to attach (for the
        ``device_plus_xsection`` template the bundle's composite SVG is also
        copied/recorded into the panel manifest).
    extras
        Free-form metadata merged into the provenance manifest's ``extras``.
    view
        Use ``1d`` for compact monochrome SVG and TikZ panels, or ``2d`` for
        the standard figure geometry.
    """

    if view not in {"1d", "2d"}:
        raise ValueError("Publication view must be '1d' or '2d'")

    if isinstance(template, TemplateSpec):
        template_spec = template
    else:
        template_spec = get_publication_template(template)

    chosen_preset = preset or template_spec.suggested_preset
    preset_values = paper_figure_preset(chosen_preset)
    bundle_formats = _normalize_bundle_formats(formats)

    if any(panel.role == "xsection" for panel in template_spec.panels):
        if xsection is None:
            raise ValueError("This publication template requires a cross-section bundle")
        composite = getattr(xsection, "composite_path", None)
        png_composite = (getattr(xsection, "png_paths", None) or {}).get("composite")
        if not any(path is not None and Path(path).is_file() for path in (composite, png_composite)):
            raise FileNotFoundError("The cross-section bundle has no existing composite SVG or PNG")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_stem = stem or _slugify(scene.title)

    scenes_for_panels = _resolve_panel_scenes(scene, template_spec, extra_scenes)
    figure_width_mm = float(template_spec.suggested_width_mm or preset_values["width"])
    figure_height_mm = float(template_spec.suggested_height_mm or preset_values["height"])

    panels_out: list[dict[str, Any]] = []
    primary_paths: dict[str, Path] = {}
    for index, (panel, panel_scene) in enumerate(zip(template_spec.panels, scenes_for_panels)):
        panel_width = figure_width_mm * panel.width_fraction
        panel_height = figure_height_mm * panel.height_fraction
        if panel.role == "xsection":
            paths = _attach_xsection_panel(out_dir, base_stem, panel, xsection)
        else:
            paths = _render_panel(
                panel_scene,
                panel,
                out_dir,
                base_stem=base_stem,
                preset_values=preset_values,
                panel_width_mm=panel_width,
                panel_height_mm=panel_height,
                formats=bundle_formats,
                dpi=dpi,
                include_polarization=include_polarization,
                view=view,
            )
        panels_out.append(
            {
                "name": panel.name,
                "label": panel.label,
                "role": panel.role,
                "row": panel.row,
                "column": panel.column,
                "width_mm": panel_width,
                "height_mm": panel_height,
                "scene_title": panel_scene.title,
                "scene_hash_sha256": _hash_scene_spec(panel_scene.to_spec()),
                "view": view if panel.role != "xsection" else "xsection",
                "format_views": _format_views(paths, view if panel.role != "xsection" else "xsection"),
                "paths": {fmt: path for fmt, path in paths.items()},
            }
        )
        if index == 0:
            primary_paths = dict(paths)

    figure_path = None
    if len(template_spec.panels) > 1:           # the panels also come together on one page
        from optodraw.figure.page import Page
        from optodraw.figure.sources import Image

        def item(paths: dict[str, Path]) -> Any:     # a drawn section: its SVG, else its PNG as a drawn picture
            return paths["svg"] if paths.get("svg") else Image(paths["png"], kind="drawn")

        sources = [item(panels_out[i]["paths"]) if panel.role == "xsection" else s
                   for i, (panel, s) in enumerate(zip(template_spec.panels, scenes_for_panels))]
        page = Page.from_template(
            template_spec, sources, width_mm=figure_width_mm, font_pt=float(preset_values.get("font_size_pt", 8.0)),
            view=view, polarization=include_polarization,
        )
        figure_path = page.export(out_dir / f"{base_stem}_figure", formats=("svg",))["svg"]

    xsection_paths: dict[str, Path] = {}
    if xsection is not None:
        xsection_panel = next((panel for panel in panels_out if panel["role"] == "xsection"), None)
        xsection_paths = (
            xsection_panel["paths"] if xsection_panel is not None
            else _attach_xsection_panel(out_dir, base_stem, PanelSpec(name="xsection"), xsection)
        )

    caption_text = caption if caption is not None else build_caption(
        scene,
        title=scene.title,
        extra_notes=caption_notes,
    )
    caption_path = out_dir / f"{base_stem}_caption.md"
    caption_path.write_text(caption_text, encoding="utf-8")

    manifest = _provenance_manifest(
        scene,
        template=template_spec,
        panels_written=[
            {
                **{key: value for key, value in panel.items() if key != "paths"},
                "paths": {
                    fmt: path.relative_to(out_dir).as_posix()
                    for fmt, path in panel.get("paths", {}).items()
                },
            }
            for panel in panels_out
        ],
        extras={**(extras or {}), "view": view},
    )
    if figure_path is not None:
        manifest["figure"] = figure_path.relative_to(out_dir).as_posix()
    if xsection is not None:
        layers: dict[str, str] = {}
        for index, (name, source) in enumerate((getattr(xsection, "layer_paths", {}) or {}).items(), 1):
            suffix = Path(source).suffix or ".svg"
            target = out_dir / f"{base_stem}_xsection_layer_{index}_{_slugify(str(name))}{suffix}"
            copied = _copy_bundle_asset(source, target)
            if copied is not None:
                layers[str(name)] = copied.relative_to(out_dir).as_posix()
        composite = xsection_paths.get("svg") or xsection_paths.get("png")
        manifest["xsection"] = {
            "composite": composite.relative_to(out_dir).as_posix() if composite else None,
            "mode": getattr(xsection, "mode", None),
            "layers": layers,
            "manifest": (
                xsection_paths["json"].relative_to(out_dir).as_posix()
                if "json" in xsection_paths else None
            ),
        }
    manifest_path = out_dir / f"{base_stem}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return PublicationBundle(
        output_dir=out_dir,
        template=template_spec,
        primary_paths=primary_paths,
        panels=panels_out,
        caption_path=caption_path,
        manifest_path=manifest_path,
        xsection_bundle=xsection,
        figure_path=figure_path,
    )


def _copy_bundle_asset(source: str | Path, target: Path) -> Path | None:
    path = Path(source)
    if not path.is_file():
        return None
    if path.resolve() != target.resolve():
        shutil.copyfile(path, target)
    return target


def _attach_xsection_panel(
    out_dir: Path,
    base_stem: str,
    panel: PanelSpec,
    xsection: Any | None,
) -> dict[str, Path]:
    """Copy cross-section outputs into the publication bundle."""

    if xsection is None:
        return {}

    paths: dict[str, Path] = {}
    composite = getattr(xsection, "composite_path", None)
    if composite is not None:
        copied = _copy_bundle_asset(composite, out_dir / f"{base_stem}_{panel.name}.svg")
        if copied is not None:
            paths["svg"] = copied
    png_paths = getattr(xsection, "png_paths", None) or {}
    if "composite" in png_paths:
        copied = _copy_bundle_asset(png_paths["composite"], out_dir / f"{base_stem}_{panel.name}.png")
        if copied is not None:
            paths["png"] = copied
    manifest_path = getattr(xsection, "manifest_path", None)
    if manifest_path is not None:
        copied = _copy_bundle_asset(manifest_path, out_dir / f"{base_stem}_{panel.name}.json")
        if copied is not None:
            paths["json"] = copied
    return paths


__all__ = [
    "Panel",
    "export_figure_bundle",
    "export_panels",
    "export_paper_figures",
    "list_paper_figure_presets",
    "paper_figure_preset",
    "PanelSpec",
    "TemplateSpec",
    "PublicationBundle",
    "SUPPORTED_BUNDLE_FORMATS",
    "build_caption",
    "build_publication_bundle",
    "get_publication_template",
    "list_publication_templates",
]
