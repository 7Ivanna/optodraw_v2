"""Inset sources: an object with ``fragment(width_mm, *, font_pt) -> Fragment``. ``to_source`` picks one by type or
suffix."""

from __future__ import annotations

import base64
import copy
import dataclasses
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from optodraw.core.markup import plain, svg_text, text_width
from optodraw.figure.fragment import (PT_MM, Fragment, _numbers, _root, _without_text, affine, place_from, scaled,
                                      stored_fragment)
from optodraw.figure.timing import Timing
from optodraw.figure.view3d import View3D, scene_data

EMPTY_SHARE = 0.6           # the height of the empty box over its width: 50 by 30
DASH_MM = "1.2 1"
LINE_MM = 0.15
MM_IN = 25.4                # mm per inch
PRINT_PPI = 600             # the resolution of an optodraw render on paper
PICTURE_LIMIT = 16 * 1024 * 1024    # bytes of picture data above which an inset warns
# The polygons a GdsView region may hold. Measured 2026-11-06: a grid of separate 0.2 um squares (4 points each, the
# fewest bytes a polygon costs) writes 60.3 bytes per square at 183 mm wide and 56.2 at 89 mm, so its SVG passes 1 MB
# at 17395 and 18664 squares. The lnoi400 ring crop (ring_single on xs_rwg1000 with a TL strip) holds 22 polygons
# (132 kB). 17000 passes the ring and refuses every square grid past 1 MB. A curved polygon costs more bytes.
POLYGON_LIMIT = 17000
_ORIENTATION = 0x0112         # the EXIF tag that says how a picture is held
_PICTURE_KINDS = ("drawn", "measured", "render")
TOOL_TIMEOUT_S = 60         # seconds an outside tool (pdftocairo, latex, dvisvgm) may run
LINE_SPACING = 1.2          # the line pitch of a text, over its size
TEX_PT = 10                 # the size a TeX equation is set at, then scaled to the page's ``font_pt``


@runtime_checkable
class InsetSource(Protocol):
    """Anything that draws a fragment at a width. A source with ``free_shape = True`` also takes a ``height``."""

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment: ...


class SvgFile:
    """An SVG file, laid out at the width it is given. It keeps its own shape and its own text sizes.

    ``drop_text`` names texts to take out of the file. ``place(x, y)`` takes the file's own units, y down."""

    free_shape = False

    def __init__(self, path: str | Path, drop_text: str | tuple[str, ...] = ()):
        self.path = Path(path)
        self.drop_text = (drop_text,) if isinstance(drop_text, str) else tuple(drop_text)

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        name, svg = self.path.name, self.path.read_text(encoding="utf-8")
        if self.drop_text:
            svg = _without_text(svg, self.drop_text, name)
        return _laid_out(svg, name, width_mm)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "SvgFile", "path": str(self.path), "drop_text": list(self.drop_text)}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "SvgFile":
        return cls(base / _text(record, "path"), drop_text=_texts(record, "drop_text"))


def _laid_out(svg: str, name: str, width_mm: float) -> Fragment:
    """``svg`` scaled to ``width_mm``, its height following its shape. ``place`` takes the file's own units, y down."""

    root = _root(svg, name)
    (wide, tall), (x0, y0) = root.size, root.origin
    height_mm = width_mm * tall / wide
    sx, sy = width_mm / wide, height_mm / tall
    shape = affine(sx, 0.0, -x0 * sx, 0.0, sy, -y0 * sy)
    return Fragment(svg=root.close(f"{width_mm:.6g}mm", f"{height_mm:.6g}mm"), size_mm=(width_mm, height_mm),
                    place=place_from(shape), map=shape)


_SAME = affine(1.0, 0.0, 0.0, 0.0, 1.0, 0.0)          # place takes mm from the top left of the fragment


class EmptyBox:
    """The source of an inset with none: a dashed box, 50 by 30 by default. It takes the height it is given."""

    free_shape = True

    def __init__(self, height: float | None = None):
        self.height = height

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        tall = EMPTY_SHARE * width_mm if self.height is None else float(self.height)
        half = LINE_MM / 2.0
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.6g}mm" height="{tall:.6g}mm" '
               f'viewBox="0 0 {width_mm:.6g} {tall:.6g}"><rect x="{half}" y="{half}" width="{width_mm - LINE_MM:.6g}" '
               f'height="{tall - LINE_MM:.6g}" fill="none" stroke="#777777" stroke-width="{LINE_MM}" '
               f'stroke-dasharray="{DASH_MM}"/></svg>')
        return Fragment(svg=svg, size_mm=(width_mm, tall), place=place_from(_SAME), map=_SAME)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "EmptyBox", "height": self.height}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "EmptyBox":
        return cls(height=_value(record, "height", empty=True))


class SceneView:
    """A :class:`~optodraw.Scene` drawn at the inset's width, its labels at the page's ``font_pt``. ``view="2d"`` is
    the framed 2D drawing and ``place(x, y)`` takes scene units, y up. ``view="1d"`` is the symbol schematic, which has
    no scene units: ``place(x, y)`` then takes its own drawing units, y down. Its labels print at ``font_pt``.
    ``polarization=True`` draws the polarization states along the beams in the 2D view."""

    free_shape = False

    def __init__(self, scene: Any, view: str = "2d", polarization: bool = False):
        if view not in ("1d", "2d"):
            raise ValueError(f"view must be '1d' or '2d', got {view!r}")
        self.scene, self.view, self.polarization = scene, view, bool(polarization)

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        if self.view == "1d":
            from optodraw.notebook_1d import render_notebook_1d

            svg, flip = render_notebook_1d(self.scene, width_mm=width_mm, font_pt=font_pt), 1.0
        else:
            from optodraw.publication import _fitted_svg

            options = {"font_size_pt": float(font_pt),
                       **({"show_polarization_overlay": True} if self.polarization else {})}
            svg, flip = _fitted_svg(self.scene, options, width_mm=width_mm), -1.0
        root = _root(svg, "the scene")
        (wide, tall), (x0, y0) = root.size, root.origin
        if not wide > 0:                                    # a scene with no parts draws nothing
            return self._blank(width_mm)
        scale = width_mm / wide
        shape = affine(scale, 0.0, -x0 * scale, 0.0, flip * scale, -y0 * scale)
        return Fragment(svg=root.close(f"{width_mm:.6g}mm", f"{tall * scale:.6g}mm"), size_mm=(width_mm, tall * scale),
                        place=place_from(shape), map=shape)

    def _blank(self, width_mm: float) -> Fragment:
        """A blank of the scene frame's shape, its places in scene units, y up, about the frame's middle."""

        wide, tall = float(self.scene.width or 1.0), float(self.scene.height or 1.0)
        scale = width_mm / wide
        shape = affine(scale, 0.0, wide / 2.0 * scale, 0.0, -scale, tall / 2.0 * scale)
        size = (width_mm, tall * scale)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size[0]:.6g}mm" height="{size[1]:.6g}mm" '
               f'viewBox="0 0 {size[0]:.6g} {size[1]:.6g}"/>')
        return Fragment(svg=svg, size_mm=size, place=place_from(shape), map=shape)

    def to_record(self) -> dict[str, Any]:
        """The scene's own spec. Its paths are absolute (the page file makes them relative)."""

        from optodraw.schema import scene_to_spec

        record = {"kind": "SceneView", "view": self.view, "scene": scene_to_spec(self.scene)}
        return {**record, "polarization": True} if self.polarization else record

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "SceneView":
        from optodraw.schema import scene_from_spec

        if not isinstance(record.get("scene"), dict):
            raise ValueError("a SceneView record holds the scene's spec")
        return cls(scene_from_spec(record["scene"], base=base), view=_text(record, "view"),
                   polarization=bool(record.get("polarization", False)))


class SectionView:
    """A cross-section, drawn by its own ``svg()`` at the inset's width and the page's ``font_pt``: the films, the
    look and the labels come from the stack and the GDS, never from here. ``svg_options`` go to ``xs.svg()``.
    ``place(s, z)`` takes the cut position and the height in um.

    A section made from an object has a frozen record: it keeps the loaded layout and stack, not the file and the
    stack name. A section from :meth:`Inset.cut` carries ``data`` (the GDS file, the stack, the cut, ``z`` and
    ``z_scale``), so its record rebuilds while every svg option is one the data holds."""

    free_shape = False

    def __init__(self, xs: Any, data: dict[str, Any] | None = None, **svg_options: Any):
        self.xs, self.data, self.options = xs, data, svg_options

    @property
    def frozen(self) -> bool:
        return self.data is None or any(self.data.get(key) != value for key, value in self.options.items())

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        from dataclasses import asdict

        from optodraw.gds.xsection.schematic import section_frame

        if {"width_mm", "font_pt"} & set(self.options):
            raise ValueError("a section takes its width_mm and font_pt from the inset: leave them out of the options")
        root = _root(self.xs.svg(width_mm=width_mm, font_pt=font_pt, **self.options), "the section")
        wide, tall = root.size
        height_mm = tall * width_mm / wide
        frame, room = section_frame(self.xs, width_mm=width_mm, font_pt=font_pt, **self.options)
        shape = {"form": "section", **{key: None if value is None else float(value)
                                       for key, value in asdict(frame).items()}, "room": float(room)}
        return Fragment(svg=root.close(f"{width_mm:.6g}mm", f"{height_mm:.6g}mm"), size_mm=(width_mm, height_mm),
                        place=place_from(shape), map=shape)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "SectionView"} if self.frozen else {"kind": "SectionView", **self.data}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "SectionView":
        if "gds" not in record:
            raise ValueError("this SectionView record is frozen: it held a section object, so it cannot rebuild")
        cut = record.get("cut")
        if not isinstance(cut, list) or len(cut) != 2:
            raise ValueError(f"a SectionView record's cut is two points, got {cut!r}")
        ends = [tuple(_numbers(end, 2, "a SectionView record's cut end")) for end in cut]
        z = None if record.get("z") is None else tuple(_numbers(record["z"], 2, "a SectionView record's z"))
        z_scale = "auto" if record.get("z_scale", "auto") == "auto" else _value(record, "z_scale")
        return cut_section(base / _text(record, "gds"), _stack_at(_text(record, "stack"), base), (ends[0], ends[1]),
                           z, _maybe_text(record, "cell"), z_scale=z_scale)


def cut_section(gds: str | Path, stack: str | Path, cut: tuple[tuple[float, float], tuple[float, float]],
                z: tuple[float, float] | None = None, cell_name: str | None = None, *,
                z_scale: Any = "auto") -> SectionView:
    """The section of ``gds`` and ``stack`` along ``cut`` (two file points in um), as a source whose record is data.
    The window is the whole cut, so the ends of the section are the two points. ``z_scale`` is ``"auto"`` or a z
    stretch above 0."""

    from optodraw.gds.xsection.model import cross_section

    if z_scale != "auto":
        z_scale = float(z_scale)
        if not (math.isfinite(z_scale) and z_scale > 0.0):
            raise ValueError(f'z_scale is "auto" or a z stretch above 0, got {z_scale!r}')
    (ax, ay), (bx, by) = ((float(x), float(y)) for x, y in cut)
    window = (0.0, math.hypot(bx - ax, by - ay))
    # shortcut: z goes only when given, as cross_section takes z= only with the z window; pass it always then
    extra = {} if z is None else {"z": tuple(z)}
    xs = cross_section(gds, stack, ((ax, ay), (bx, by)), window=window, cell_name=cell_name, **extra)
    data = {"gds": str(gds), "stack": str(stack), "cut": [[ax, ay], [bx, by]],
            "z": None if z is None else [float(v) for v in z], "cell": cell_name, "z_scale": z_scale}
    return SectionView(xs, data=data, z_scale=z_scale)


class GdsView:
    """A crop of a GDS file drawn as vector: each layer clipped to ``region`` (``x0, y0, x1, y1`` in file um) and
    merged into one path, filled from the one material table. A higher layer of the same material is a shade darker,
    so a ridge stands apart from its slab; an etch is white. Each layer has a thin outline in the ink colour.

    ``stack`` is a bundled stack name or a stack file. ``layers`` picks ``(layer, datatype)`` pairs; by default the
    stack's visible layers. ``place(x, y)`` takes file um, y up. More than ``limit`` polygons in the region raise
    ValueError. :meth:`Inset.cut` makes a section from the same file and stack."""

    free_shape = False

    def __init__(self, gds: str | Path, stack: str | Path, region: Any, layers: Any = None, *,
                 cell_name: str | None = None, limit: int = POLYGON_LIMIT):
        from optodraw.gds.parsers import load_layer_stack

        x0, y0, x1, y1 = (float(v) for v in region)
        if not (x1 > x0 and y1 > y0):
            raise ValueError(f"region is (x0, y0, x1, y1) with x1 > x0 and y1 > y0, got {tuple(region)!r}")
        self.path, self.stack, self.region = Path(gds), str(stack), (x0, y0, x1, y1)
        self.layers = None if layers is None else tuple((int(layer), int(kind)) for layer, kind in layers)
        self.cell_name, self.limit = cell_name, int(limit)
        self.spec = load_layer_stack(self.stack)
        missing = [f"{layer}/{kind}" for layer, kind in self.layers or () if (layer, kind) not in self.spec.styles]
        if missing:
            raise ValueError(f"GdsView: the stack {self.stack!r} has no layer {', '.join(missing)}: name layers it "
                             "holds")

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        from optodraw.gds.view import layer_shapes, view_svg

        shapes = layer_shapes(self.path, self.spec, self.region, self.layers, cell_name=self.cell_name,
                              limit=self.limit)
        x0, y0, x1, y1 = self.region
        k = width_mm / (x1 - x0)
        shape = affine(k, 0.0, -x0 * k, 0.0, -k, y1 * k)
        return Fragment(svg=view_svg(shapes, self.spec, self.region, width_mm), size_mm=(width_mm, (y1 - y0) * k),
                        place=place_from(shape), map=shape)

    def check(self) -> list[str]:
        """The faults between the file and the stack: a drawn layer the stack lacks is not in the picture."""

        from optodraw.gds.check import check_stack

        return check_stack(self.path, self.stack, cell_name=self.cell_name)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "GdsView", "path": str(self.path), "stack": self.stack, "region": list(self.region),
                "layers": None if self.layers is None else [list(key) for key in self.layers],
                "cell": self.cell_name, "limit": self.limit}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "GdsView":
        layers = record.get("layers")
        if layers is not None and not (isinstance(layers, list) and all(
                isinstance(key, list) and len(key) == 2 and all(type(v) is int for v in key) for key in layers)):
            raise ValueError(f"a GdsView record's layers are [layer, datatype] pairs or null, got {layers!r}")
        return cls(base / _text(record, "path"), _stack_at(_text(record, "stack"), base),
                   _numbers(record.get("region"), 4, "a GdsView record's region"), layers,
                   cell_name=_maybe_text(record, "cell"), limit=int(_value(record, "limit")))


class Plot:
    """A matplotlib figure, saved as SVG at the inset's width (and ``height``, else the figure's own shape). The text
    stays text and keeps the sizes the figure gives it. ``place(x, y, axes=0)`` takes data coordinates of the
    ``axes``-th axes of the figure (cartesian axes with linear or log scales; polar and 3D axes and other scales export
    but refuse ``place``), y up as in the plot. ``kind="measured"`` marks a plot of real data; the default ``"drawn"``
    is a model or a sketch. Heat maps stay rasters at 600 dpi.

    The figure is resized for the save and put back after it. Its record is frozen: a figure is not data."""

    free_shape = True
    frozen = True

    def __init__(self, figure: Any, height: float | None = None, kind: str = "drawn"):
        self.figure, self.height, self.kind = figure, height, kind

    def to_record(self) -> dict[str, Any]:
        return {"kind": "Plot"}

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        import io

        import matplotlib as mpl
        from matplotlib.transforms import Affine2D

        from optodraw.figure.page import FONT_FAMILY

        fig = self.figure
        old = tuple(fig.get_size_inches())
        tall = old[1] * width_mm / old[0] if self.height is None else float(self.height)
        faces = [name.strip() for name in FONT_FAMILY.split(",")]
        rc = {"svg.fonttype": "none", "svg.hashsalt": "optodraw", "font.family": ["sans-serif"],
              "font.sans-serif": faces,
              "savefig.bbox": "standard", "savefig.pad_inches": 0.0}
        out = io.BytesIO()
        fig.set_size_inches(width_mm / MM_IN, tall / MM_IN, forward=False)
        try:
            with mpl.rc_context(rc):
                fig.savefig(out, format="svg", dpi=600, metadata={"Date": None})
            # the layout has run in the save: freeze each axes' map to the page, in mm from the top left
            flip = Affine2D().scale(MM_IN / fig.dpi).scale(1.0, -1.0).translate(0.0, tall)
            shape = {"form": "plot", "axes": [_axes_map(ax, flip) for ax in fig.axes]}
        finally:
            fig.set_size_inches(*old, forward=False)
        svg = re.sub(r"<\?xml.*?\?>|<!DOCTYPE.*?>", "", out.getvalue().decode("utf-8"), flags=re.S).strip()
        root = _root(svg, "the plot")
        return Fragment(svg=root.close(f"{width_mm:.6g}mm", f"{tall:.6g}mm"), size_mm=(width_mm, tall),
                        place=place_from(shape), kind=self.kind, map=shape)


def _axes_map(ax: Any, flip: Any) -> dict[str, Any] | None:
    """The map of one axes from data to mm as a record: the scale of x and of y, then six affine terms. None for an
    axes that is not cartesian, or has a scale other than linear and log."""

    from matplotlib.scale import LogTransform
    from matplotlib.transforms import IdentityTransform

    def scale(axis: Any) -> list[Any] | None:
        transform = axis.get_transform()
        if isinstance(transform, IdentityTransform):
            return ["linear"]
        return ["log", float(transform.base)] if isinstance(transform, LogTransform) else None

    if ax.name != "rectilinear":
        return None
    x, y = scale(ax.xaxis), scale(ax.yaxis)
    if x is None or y is None:
        return None
    m = (ax.transLimits + ax.transAxes + flip).get_matrix()
    return {"x": x, "y": y, "m": [float(m[0][0]), float(m[0][1]), float(m[0][2]),
                                  float(m[1][0]), float(m[1][1]), float(m[1][2])]}


def _pillow():
    try:
        from PIL import Image as pil
    except ImportError as exc:                       # pragma: no cover - Pillow ships with the figure extra
        raise ImportError("a picture needs Pillow: pip install 'optodraw[figure]'") from exc
    return pil


def _array_png(data: Any) -> bytes:
    """A 2D (grey) or 3D (grey, RGB or RGBA channels last) array as PNG bytes. ``uint8`` is kept, ``uint16`` goes to 8
    bit by 1/257, floats are 0 to 1, other integers are clipped to 0 to 255."""

    import numpy as np

    pixels = np.asarray(data)
    if pixels.ndim == 3 and pixels.shape[2] == 1:
        pixels = pixels[:, :, 0]
    if pixels.ndim not in (2, 3) or (pixels.ndim == 3 and pixels.shape[2] not in (2, 3, 4)):
        raise ValueError(f"a picture is a 2D or 3D array (rows, columns, 1 to 4 channels), got shape {pixels.shape}")
    if pixels.dtype == np.uint16:
        pixels = np.rint(pixels / 257.0)
    elif pixels.dtype.kind == "f":
        pixels = np.rint(np.clip(pixels, 0.0, 1.0) * 255.0)
    elif pixels.dtype.kind == "b":
        pixels = pixels * 255
    pixels = np.clip(pixels, 0, 255).astype(np.uint8)
    out = io.BytesIO()
    _pillow().fromarray(pixels).save(out, format="PNG")
    return out.getvalue()


def _picture_svg(mime: str, data: bytes, size_px: tuple[int, int], width_mm: float) -> tuple[str, float]:
    """One SVG root that holds the picture as an ``<image>`` of ``size_px`` pixels at ``width_mm``, and its height in
    mm. The viewBox is in pixels, so ``place`` takes pixels and scales them."""

    wide, tall = size_px
    height_mm = width_mm * tall / wide
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.6g}mm" height="{height_mm:.6g}mm" '
            f'viewBox="0 0 {wide} {tall}"><image width="{wide}" height="{tall}" preserveAspectRatio="none" '
            f'href="data:{mime};base64,{base64.b64encode(data).decode("ascii")}"/></svg>'), height_mm


class Image:
    """A picture, kept as pixels: a PNG, JPEG or TIFF file, or a 2D or 3D array (grey, RGB or RGBA; see
    ``_array_png`` for the scales). It is never traced to vector. A TIFF goes in as a PNG. ``place(x, y)`` takes pixels
    from the top left, y down, or um when ``scale_um_per_px`` is given. ``kind`` is ``"measured"`` for a real photo; a
    picture of data that is not measured says ``"drawn"`` or ``"render"``. A picture over 16 MB warns."""

    free_shape = False
    _SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

    def __init__(self, data: Any, scale_um_per_px: float | None = None, kind: str = "measured"):
        if kind not in _PICTURE_KINDS:
            raise ValueError(f"kind is one of {', '.join(_PICTURE_KINDS)}, not {kind!r}")
        if scale_um_per_px is not None and not float(scale_um_per_px) > 0.0:
            raise ValueError(f"scale_um_per_px is um per pixel above 0, not {scale_um_per_px!r}")
        self.scale_um_per_px = None if scale_um_per_px is None else float(scale_um_per_px)
        self.kind = kind
        self.data = Path(data) if isinstance(data, (str, Path)) else data
        size = self.data.stat().st_size if isinstance(self.data, Path) else getattr(self.data, "nbytes", 0)
        if size > PICTURE_LIMIT:
            warnings.warn(f"this picture holds {size / 2 ** 20:.0f} MB, which goes into the figure file as it is "
                          f"(limit {PICTURE_LIMIT / 2 ** 20:.0f} MB): shrink it first for a smaller file",
                          UserWarning, stacklevel=2)

    def _file(self) -> tuple[str, bytes]:
        """The mime type and the bytes to embed."""

        path = self.data
        if not isinstance(path, Path):
            return "image/png", _array_png(path)
        suffix = path.suffix.lower()
        if suffix not in self._SUFFIXES and suffix not in (".tif", ".tiff"):
            raise ValueError(f"no picture reader for {path.name!r}: known suffixes are .png .jpg .jpeg .tif .tiff")
        pil = _pillow()
        with pil.open(path) as image:
            turned = image.getexif().get(_ORIENTATION, 1) not in (0, 1)
            if suffix in self._SUFFIXES and not turned:
                return self._SUFFIXES[suffix], path.read_bytes()
            image.load()
            if turned:                                      # the file says how to hold it: turn the pixels so
                from PIL import ImageOps                    # that place and the picture agree with what viewers show

                image = ImageOps.exif_transpose(image)
            if image.mode in ("1", "L", "LA", "P", "RGB", "RGBA"):
                out = io.BytesIO()
                image.save(out, format="PNG")
                return "image/png", out.getvalue()
            if not image.mode.startswith("I;16"):           # 16-bit grey goes to 8 bit by 1/257; any other mode
                raise ValueError(f"{path.name!r} is in mode {image.mode!r}, which has no fixed scale to 8-bit grey "
                                 "or RGB (float pixels, CMYK ink): save it as 8- or 16-bit grey or as RGB first")
            return "image/png", _array_png(image)

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        mime, data = self._file()
        with _pillow().open(io.BytesIO(data)) as image:
            size = image.size
        svg, height_mm = _picture_svg(mime, data, size, width_mm)
        per_px = width_mm / size[0]
        step = per_px / (self.scale_um_per_px or 1.0)           # mm per unit of x and y
        shape = affine(step, 0.0, 0.0, 0.0, step, 0.0)
        return Fragment(svg=svg, size_mm=(width_mm, height_mm), place=place_from(shape), kind=self.kind, map=shape)

    @property
    def frozen(self) -> bool:
        """An array is not data a page file keeps: only a picture file rebuilds."""

        return not isinstance(self.data, Path)

    def to_record(self) -> dict[str, Any]:
        if self.frozen:
            return {"kind": "Image"}
        return {"kind": "Image", "path": str(self.data), "scale_um_per_px": self.scale_um_per_px,
                "image_kind": self.kind}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "Image":
        if "path" not in record:
            raise ValueError("this Image record is frozen: it held an array, so it cannot rebuild")
        return cls(base / _text(record, "path"), scale_um_per_px=_value(record, "scale_um_per_px", empty=True),
                   kind=_text(record, "image_kind"))


class SemView:
    """optodraw's own SEM-style render of a :class:`~optodraw.gds.xsection.top.TopView` or of a cross-section, set in
    as a picture. It is a render, never a measurement: ``kind="render"``, the visible mark is on by default, and
    ``mark=False`` leaves the kind and adds a note.

    The picture is ``width_px`` across, by default the pixels that give 600 ppi at the inset's width. ``tilt`` and
    ``rotation`` (degrees) go to a top view. ``place(x, y)`` takes layout um for a top view and ``(s, z)`` um for a
    section, y down in the picture and the info strip under it. A tilted top view has no map from the layout to
    the picture (a point's row depends on its height), so ``place`` raises ValueError naming ``tilt``.

    Its record is frozen: a view keeps the loaded layout and process, not the file and the stack name."""

    free_shape = False
    frozen = True

    def __init__(self, item: Any, *, width_px: int | None = None, tilt: float = 0.0, rotation: float = 0.0,
                 seed: int = 0, mark: bool = True):
        from optodraw.gds.xsection.model import CrossSection
        from optodraw.gds.xsection.top import TopView

        if isinstance(item, CrossSection):
            for name, value in (("tilt", tilt), ("rotation", rotation)):
                if float(value) != 0.0:
                    raise ValueError(f"a cross-section render takes no {name}: it is a view of the cut face")
        elif not isinstance(item, TopView):
            raise TypeError(f"SemView takes a TopView or a CrossSection, not {type(item).__name__}")
        self.item, self.width_px, self.mark, self.seed = item, width_px, bool(mark), seed
        self.tilt, self.rotation = float(tilt), float(rotation)

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        from optodraw.gds.xsection.top import TopView

        px = int(self.width_px) if self.width_px else max(1, round(width_mm / MM_IN * PRINT_PPI))
        item, top = self.item, isinstance(self.item, TopView)
        extra = {"tilt": self.tilt, "rotation": self.rotation} if top else {}
        data = item.png(width_px=px, seed=self.seed, mark=self.mark, **extra)
        with _pillow().open(io.BytesIO(data)) as image:
            size = image.size
        svg, height_mm = _picture_svg("image/png", data, size, width_mm)
        per_px = width_mm / size[0]
        if top and self.tilt != 0.0:
            shape = {"form": "tilted", "tilt": self.tilt}
        elif top:                                           # locate is affine in x and y: read its terms off 3 points
            (c0, r0), (c1, r1), (c2, r2) = (item.locate(x, y, px, self.rotation) for x, y in ((0, 0), (1, 0), (0, 1)))
            shape = affine((c1 - c0) * per_px, (c2 - c0) * per_px, c0 * per_px,
                           (r1 - r0) * per_px, (r2 - r0) * per_px, r0 * per_px)
        else:
            from optodraw.gds.xsection.sem import sem_canvas

            canvas = sem_canvas(item, px)
            k = canvas.px_per_um * per_px
            shape = affine(k, 0.0, -canvas.s0 * k, 0.0, -k, canvas.z_top * k)
        notes = () if self.mark else ("an optodraw render, not a measurement",)
        strip = max(30, round(0.06 * size[0]))              # the height of the info bar ``_info_bar`` lays out
        return Fragment(svg=svg, size_mm=(width_mm, height_mm), place=place_from(shape), kind="render", notes=notes,
                        floor_mm=strip * per_px, map=shape)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "SemView"}


def _tool(name: str, needed_for: str) -> str:
    """The path of the outside tool ``name``, or a RuntimeError that names it."""

    found = shutil.which(name)
    if found is None:
        raise RuntimeError(f"{needed_for} needs the tool {name!r}, which is not on PATH: install it, or leave it out")
    return found


def _run(args: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None) -> None:
    """Run an outside tool (no shell, with a time limit). A failure raises RuntimeError with the tool's message."""

    try:
        done = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=TOOL_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{Path(args[0]).name} ran over {TOOL_TIMEOUT_S} s and was stopped") from exc
    if done.returncode:
        detail = (done.stderr.strip() or done.stdout.strip())[-600:]
        raise RuntimeError(f"{Path(args[0]).name} failed ({done.returncode}): {detail}")


class PdfFile:
    """A page of a PDF file, set in as vector. ``pdftocairo`` turns the page into SVG, so its text becomes glyph paths
    and it keeps its own sizes. The page is laid out at the inset's width, as an :class:`SvgFile`. ``page`` counts from
    1. ``place(x, y)`` takes the page's own units (points), y down. Needs ``pdftocairo`` (poppler) on ``PATH``."""

    free_shape = False

    def __init__(self, path: str | Path, page: int = 1):
        if int(page) < 1:
            raise ValueError(f"page counts from 1, got {page!r}")
        self.path, self.page = Path(path), int(page)

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        tool = _tool("pdftocairo", "a PDF inset")
        if not self.path.is_file():
            raise FileNotFoundError(f"no PDF file {str(self.path)!r}")
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "page.svg"
            _run([tool, "-svg", "-f", str(self.page), "-l", str(self.page), str(self.path), str(out)])
            svg = out.read_text(encoding="utf-8")
        return _laid_out(svg, self.path.name, width_mm)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "PdfFile", "path": str(self.path), "page": self.page}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "PdfFile":
        return cls(base / _text(record, "path"), page=int(_value(record, "page")))


def _wrap(text: str, size: float, limit: float) -> list[str]:
    """``text`` cut into lines no wider than ``limit`` (in the units of ``size``) at its spaces. A newline is a hard
    break and a word wider than the limit stays whole on its own line."""

    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}" if line else word
            if line and text_width(trial, size) > limit:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


class Text:
    """Words set in the figure, in the page's font at the page's ``font_pt`` (or ``size_pt``). Markup works as in a
    label: ``SiO_2``, ``cm^2``, ``*italic*``, ``**bold**``. A line breaks at a space when the next word would pass the
    width; ``"\\n"`` breaks it by hand. Markup that spans a break (``*two words*``) is cut with the line: keep a
    marked run inside one line.

    ``width`` (mm) narrows the column below the inset's width and never widens it: the inset's width is the
    limit, so one number sets the shape. The fragment is as wide as the inset and as tall as the lines. ``align`` is
    ``"left"``, ``"center"`` or ``"right"`` inside the column, which starts at the left edge of the inset.
    ``place(x, y)`` takes mm from the top left of the text."""

    free_shape = False

    def __init__(self, text: str, width: float | None = None, size_pt: float | None = None, align: str = "left"):
        if align not in ("left", "center", "right"):
            raise ValueError(f"align is left, center or right, got {align!r}")
        if width is not None and not float(width) > 0.0:
            raise ValueError(f"width is mm above 0, not {width!r}")
        if size_pt is not None and not float(size_pt) > 0.0:
            raise ValueError(f"size_pt is above 0, not {size_pt!r}")
        self.text, self.width, self.size_pt, self.align = str(text), width, size_pt, align

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        from optodraw.figure.page import FONT_FAMILY

        size = (font_pt if self.size_pt is None else float(self.size_pt)) * PT_MM
        limit = width_mm if self.width is None else min(width_mm, float(self.width))
        lines = _wrap(self.text, size, limit)
        pitch = LINE_SPACING * size
        height_mm = max(1, len(lines)) * pitch
        anchor, x = {"left": ("start", 0.0), "center": ("middle", limit / 2.0), "right": ("end", limit)}[self.align]
        look = f'font-family="{FONT_FAMILY}" fill="#000000"'
        body = "".join(svg_text(line, round(size, 4), x, round(0.5 * pitch + 0.35 * size + i * pitch, 4), anchor, look)
                       for i, line in enumerate(lines) if plain(line))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.6g}mm" height="{height_mm:.6g}mm" '
               f'viewBox="0 0 {width_mm:.6g} {height_mm:.6g}">{body}</svg>')
        return Fragment(svg=svg, size_mm=(width_mm, height_mm), place=place_from(_SAME), map=_SAME)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "Text", "text": self.text, "width": self.width, "size_pt": self.size_pt, "align": self.align}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "Text":
        return cls(_text(record, "text"), width=_value(record, "width", empty=True),
                   size_pt=_value(record, "size_pt", empty=True), align=_text(record, "align"))


class Equation:
    """A formula, set as vector paths (no text element, no raster). ``tex=False`` uses matplotlib's mathtext, which
    needs no outside tool; ``tex=True`` uses LaTeX and ``dvisvgm`` (both on ``PATH``) for the full TeX set.
    The formula is written without the ``$`` signs.

    It prints at the page's ``font_pt``, so its size is its own: the fragment is as wide and tall as the formula, and
    the inset's width is not used. ``place(x, y)`` takes mm from the top left of the formula."""

    free_shape = False

    def __init__(self, latex: str, tex: bool = False):
        self.latex, self.tex = str(latex).strip().strip("$").strip(), bool(tex)
        if not self.latex:
            raise ValueError("an equation needs a formula")
        self._set: tuple[Any, str] | None = None

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        key = (self.latex, self.tex, float(font_pt))         # the width is not used: a new width sets nothing again
        if getattr(self, "_set", None) is None or self._set[0] != key:
            self._set = (key, self._tex_svg() if self.tex else self._mathtext_svg(font_pt))
        svg, scale = self._set[1], font_pt / TEX_PT if self.tex else 1.0
        root = _root(svg, "the equation")
        wide, tall = (value * PT_MM * scale for value in root.size)          # the SVG's units are points
        return Fragment(svg=root.close(f"{wide:.6g}mm", f"{tall:.6g}mm"), size_mm=(wide, tall),
                        place=place_from(_SAME), map=_SAME)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "Equation", "latex": self.latex, "tex": self.tex}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "Equation":
        if not isinstance(record.get("tex"), bool):
            raise ValueError(f"an Equation record's tex is true or false, got {record.get('tex')!r}")
        return cls(_text(record, "latex"), tex=record["tex"])

    def _mathtext_svg(self, font_pt: float) -> str:
        import matplotlib as mpl
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.transforms import IdentityTransform

        fig = Figure(dpi=72)                                  # not pyplot: no global figure state, nothing to restore
        FigureCanvasAgg(fig)
        with mpl.rc_context({"svg.fonttype": "path", "svg.hashsalt": "optodraw"}):
            label = fig.text(0, 0, f"${self.latex}$", fontsize=font_pt, transform=IdentityTransform())
            box = label.get_window_extent(fig.canvas.get_renderer())        # at 72 dpi a pixel is a point
            label.set_position((-box.x0, -box.y0))
            fig.set_size_inches(box.width / 72.0, box.height / 72.0)
            out = io.BytesIO()
            fig.savefig(out, format="svg", dpi=72, metadata={"Date": None})
        return re.sub(r"<\?xml.*?\?>|<!DOCTYPE.*?>", "", out.getvalue().decode("utf-8"), flags=re.S).strip()

    def _tex_svg(self) -> str:
        """The formula set at ``TEX_PT``; :meth:`fragment` scales it to the page's font_pt."""

        dvisvgm, latex = _tool("dvisvgm", "a TeX equation"), _tool("latex", "a TeX equation")
        doc = (f"\\documentclass[{TEX_PT}pt]{{article}}\\pagestyle{{empty}}\\usepackage{{amsmath,amssymb}}"
               f"\\begin{{document}}${self.latex}$\\end{{document}}\n")
        # paranoid file access: TeX and dvisvgm open no file outside the temp folder (no absolute path, no "..")
        env = {key: value for key, value in os.environ.items() if key != "TEXMFOUTPUT"}
        env.update(openin_any="p", openout_any="p")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "eq.tex").write_text(doc, encoding="utf-8")
            _run([latex, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "eq.tex"], cwd=folder,
                 env=env)
            _run([dvisvgm, "--no-fonts", "--bbox=min", "-o", "eq.svg", "eq.dvi"], cwd=folder, env=env)
            return (Path(folder) / "eq.svg").read_text(encoding="utf-8")


def _is_figure(item: Any) -> bool:
    return callable(getattr(item, "savefig", None)) and hasattr(item, "axes")


_BY_SUFFIX: dict[str, Any] = {".svg": SvgFile, ".pdf": PdfFile, ".png": Image, ".jpg": Image, ".jpeg": Image,
                              ".tif": Image, ".tiff": Image}


def to_source(item: Any = None, *, height: float | None = None, **options: Any) -> InsetSource:
    """The source for ``item``, picked by type or suffix. ``None`` is the empty box; a path ending in ``.svg`` is a
    :class:`SvgFile`; a ``.pdf`` is a :class:`PdfFile`; a ``.png``, ``.jpg``, ``.tif`` file or an array is an
    :class:`Image`; a ``TopView`` is a :class:`SemView`; an object with ``fragment`` is its own source. ``options`` go
    to the source. ``height`` goes to a free-shape source (``free_shape = True``); a source that keeps its own shape
    refuses it. A string that is not an
    existing file raises ``FileNotFoundError``: words go through :class:`Text`."""

    if item is None:
        source = EmptyBox(height=height)
    elif callable(getattr(item, "fragment", None)):
        if options:
            raise TypeError(f"a ready source takes no options, got {sorted(options)}")
        source = item
        if height is not None:
            _free(source)
            source = copy.copy(source)
            source.height = height
    elif _is_figure(item):
        source = Plot(item, height=height, **options)
    elif _is_scene(item):                                    # a Page too: it is a Scene, and it has svg()
        if height is not None:
            _free(SceneView)
        source = SceneView(item, **options)
    elif callable(getattr(item, "svg", None)):
        if not _is_section(item):
            raise TypeError(f"no inset source for {type(item).__name__}: of the objects with svg(), an inset takes a "
                            "cross-section; give a drawing as an SVG file, or as a source with fragment()")
        if height is not None:
            _free(SectionView)
        source = SectionView(item, **options)
    elif _is_array(item):
        if height is not None:
            _free(Image)
        source = Image(item, **options)
    elif isinstance(item, (str, Path)):
        kind = _BY_SUFFIX.get(Path(item).suffix.lower())
        if kind is None and not Path(item).is_file():
            raise FileNotFoundError(f"no file {str(item)!r}: a string is a path here, so write words as "
                                    f"Text({str(item)!r})")
        if kind is None:
            raise ValueError(f"no inset source for {Path(item).name!r}: known suffixes are {', '.join(_BY_SUFFIX)}")
        if height is not None:
            _free(kind)
        source = kind(item, **options)
    elif _is_top_view(item):
        if height is not None:
            _free(SemView)
        source = SemView(item, **options)
    else:
        raise TypeError(f"no inset source for {type(item).__name__}")
    return source


def _is_array(item: Any) -> bool:
    import numpy as np

    return isinstance(item, np.ndarray)


def _is_top_view(item: Any) -> bool:
    from optodraw.gds.xsection.top import TopView

    return isinstance(item, TopView)


def _is_section(item: Any) -> bool:
    try:
        from optodraw.gds.xsection.model import CrossSection
    except ImportError:                                      # no gds extra: no section can exist
        return False
    return isinstance(item, CrossSection)


def _is_scene(item: Any) -> bool:
    from optodraw.core.scene import Scene

    return isinstance(item, Scene)


def _free(source: Any) -> None:
    if not getattr(source, "free_shape", False):
        name = getattr(source, "__name__", type(source).__name__)
        raise ValueError(f"{name} keeps its own shape, so it takes no height")


# ---- records: a page file keeps each source as data, and only these kinds load ----

#: The source kinds a page file may name. A record names one of these and holds data only, so loading runs no code.
#: ``Fragment`` is a source optodraw has no record for: only its fragment is kept.
SOURCE_KINDS: dict[str, type] = {"EmptyBox": EmptyBox, "SvgFile": SvgFile, "PdfFile": PdfFile, "SceneView": SceneView,
                                 "SectionView": SectionView, "GdsView": GdsView, "Plot": Plot, "Image": Image,
                                 "SemView": SemView, "Text": Text, "Equation": Equation, "Timing": Timing,
                                 "View3D": View3D, "Fragment": Fragment}
#: The keys of each record kind that hold a file path, moved with the page file. A ``stack`` is a path only when it
#: names a file (see :func:`_stack_file`); else it is a bundled stack's name.
_PATH_KEYS: dict[str, tuple[str, ...]] = {"SvgFile": ("path",), "PdfFile": ("path",), "Image": ("path",),
                                          "GdsView": ("path", "stack"), "SectionView": ("gds", "stack"),
                                          "View3D": ("path", "stack")}


def _stack_file(stack: str) -> bool:
    """True when ``stack`` names a stack file, not a bundled stack.

    shortcut: a file is told by its suffix (.yaml, .lyt), so a stack file with no suffix saves as a name; read the
    disk here if one appears."""

    return bool(Path(stack).suffix)


def _stack_at(stack: str, base: Path) -> str | Path:
    """A record's ``stack``: a file from the page file's folder ``base``, or a bundled name as it is."""

    return base / stack if _stack_file(stack) else stack


def _maybe_text(record: dict[str, Any], key: str) -> str | None:
    return None if record.get(key) is None else _text(record, key)


def _kind(record: Any) -> type:
    kind = record.get("kind") if isinstance(record, dict) else None
    if not isinstance(kind, str) or kind not in SOURCE_KINDS:
        raise ValueError(f"no inset source kind {kind!r}: a record names one of {', '.join(SOURCE_KINDS)}")
    return SOURCE_KINDS[kind]


def _text(record: dict[str, Any], key: str) -> str:
    if not isinstance(record.get(key), str):
        raise ValueError(f"a {record.get('kind')} record's {key} is text, got {record.get(key)!r}")
    return record[key]


def _texts(record: dict[str, Any], key: str) -> tuple[str, ...]:
    values = record.get(key, [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"a {record.get('kind')} record's {key} is a list of text, got {values!r}")
    return tuple(values)


def _value(record: dict[str, Any], key: str, empty: bool = False) -> float | None:
    value = record.get(key)
    if empty and value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"a {record.get('kind')} record's {key} is a number, got {value!r}")
    return float(value)


def from_record(record: dict[str, Any], base: Path) -> InsetSource:
    """The source a record describes, its paths taken from ``base`` (the page file's folder). Only the kinds in
    :data:`SOURCE_KINDS` load. A frozen record (a plot, an array, a section or a render: inputs that are not data)
    raises ValueError naming ``frozen``."""

    cls = _kind(record)
    build = getattr(cls, "_from_record", None)
    if build is None:
        raise ValueError(f"this {record['kind']} record is frozen: its inputs are not data, so it cannot rebuild")
    return build(record, Path(base))


def _paths(value: Any, change: Any) -> Any:
    """``value`` with each source path in it passed through ``change``: a record, or the scene spec of a SceneView,
    whose own insets hold records too."""

    if isinstance(value, list):
        return [_paths(item, change) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _paths(item, change) for key, item in value.items()}
    for key in _PATH_KEYS.get(out.get("kind"), ()):
        if isinstance(out.get(key), str) and (key != "stack" or _stack_file(out[key])):
            out[key] = change(out[key])
    return out


def rebased(record: dict[str, Any], base: Path | None) -> dict[str, Any]:
    """``record`` with its paths relative to ``base`` (the folder of the page file), or absolute with no base."""

    def change(path: str) -> str:
        whole = os.path.abspath(path)
        if base is None:
            return whole
        try:
            return Path(os.path.relpath(whole, os.path.abspath(base))).as_posix()
        except ValueError:                                  # another drive: no relative path exists
            return whole

    return _paths(record, change)


def _loose(value: Any) -> bool:
    """True when a scene spec names a file or folder on disk that :func:`_paths` does not move with the page file: a
    GDS part's own path, for one."""

    if isinstance(value, str):
        return "\n" not in value and len(value) < 4096 and os.path.exists(value)
    if isinstance(value, list):
        return any(_loose(item) for item in value)
    if isinstance(value, dict):
        moved = _PATH_KEYS.get(value.get("kind"), ())
        return any(_loose(item) for key, item in value.items() if key not in moved)
    return False


def record_of(source: Any, fragment: Fragment, width_mm: float, font_pt: float,
              name: str = "an inset") -> tuple[dict[str, Any], bool]:
    """The record of ``source``, its paths as the source holds them, and whether it is frozen: a frozen record keeps
    its kind only, and the page keeps the fragment. A source with no record of its own is kind ``Fragment``. A
    scene's record (a SceneView, or a View3D of a scene) is its spec. It is frozen when the spec names a file of its
    own (a GDS part), and when it does not draw ``fragment`` again exactly; the second warns, naming the inset
    (``name``). A 3D view is not drawn again for this: the same scene data draws the same view."""

    if isinstance(source, _Stored):
        return source.to_record(), source.frozen
    record = source.to_record() if callable(getattr(source, "to_record", None)) else None
    if not isinstance(record, dict) or SOURCE_KINDS.get(record.get("kind")) is not type(source):
        return {"kind": "Fragment"}, True                   # a user's source, or a subclass with the parent's record
    frozen = bool(getattr(source, "frozen", False))
    of_scene = "scene" in record
    if of_scene and not frozen:
        frozen = _loose(record["scene"])
        if frozen:
            warnings.warn(f"{name} saves its scene frozen: its spec names a file of its own (a GDS part) that the page "
                          "file does not carry, so the page keeps the drawing; it cannot rebuild after a load",
                          UserWarning, stacklevel=2)
            return {"kind": record["kind"]}, True
    if of_scene and not frozen:
        try:                                                # a probe: any failure means the spec does not draw it
            again = from_record(json.loads(json.dumps(record)), Path("."))
            if isinstance(source, View3D):                  # a 3D draw is slow, and its scene data is all it reads
                frozen = source._drawn is None or scene_data(again.scene) != source._drawn[0][1]
            else:
                drawn = again.fragment(width_mm, font_pt=font_pt)
                frozen = (drawn.svg, tuple(drawn.size_mm), drawn.map) != (fragment.svg, tuple(fragment.size_mm),
                                                                         fragment.map)
        except Exception:
            frozen = True
        if frozen:
            warnings.warn(f"{name} saves its scene frozen: the scene's saved spec does not draw the view the page "
                          "shows (the scene changed after the inset drew it, or its spec does not keep every detail); "
                          "call rebuild() on the inset before the save to keep it live", UserWarning, stacklevel=2)
    return ({"kind": record["kind"]} if frozen else record), frozen


class _Stored:
    """The source of an inset loaded from a page file: the record of the source it was, and the fragment it drew last
    at ``at`` (width and height asked in mm, and font_pt). It never rebuilds by itself, so a loaded page reads no
    source file and runs no tool: at another width it scales the stored fragment, and a note says its text no longer
    prints at the page's font_pt. Only :meth:`Inset.rebuild` builds the source again from the record. A record with
    no stored fragment (a spec written by hand) is not built either: it draws an empty box, every place in it lands
    in its middle, and ``check_figure`` names it until a rebuild."""

    def __init__(self, record: dict[str, Any], fragment: dict[str, Any] | None, base: Path):
        cls = _kind(record)
        self.record, self.base = dict(record), Path(base)
        self.stored = None if fragment is None else stored_fragment(fragment)
        self.frozen = (fragment is not None and bool(fragment.get("frozen", False))) or not hasattr(cls, "_from_record")
        self.at = None if fragment is None else (_value(fragment, "width_mm"),
                                                 _value(fragment, "height_mm", empty=True), _value(fragment, "font_pt"))
        self.free_shape = bool(getattr(cls, "free_shape", False) or (self.at is not None and self.at[1] is not None))
        self.height: float | None = None

    def to_record(self) -> dict[str, Any]:
        """The record, its paths taken from the page file's folder."""

        return _paths(self.record, lambda path: str(self.base / path))

    @property
    def built(self) -> bool:
        """False for a record with no stored drawing: it reads no file and runs no tool until a rebuild."""

        return self.stored is not None

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        if self.stored is None:                             # never built by itself: an empty box
            box = EmptyBox(height=self.height).fragment(width_mm, font_pt=font_pt)
            middle = affine(0.0, 0.0, box.size_mm[0] / 2.0, 0.0, 0.0, box.size_mm[1] / 2.0)
            return dataclasses.replace(box, place=place_from(middle), map=middle)
        ratio, pt = width_mm / self.at[0], self.at[2]
        if not math.isclose(ratio, 1.0, rel_tol=1e-9):
            return scaled(self.stored, ratio, f"scaled from the saved drawing: its text no longer prints at "
                                              f"{font_pt:g} pt")
        if math.isclose(font_pt, pt, rel_tol=1e-9):        # the same width: a new height alone keeps the drawing
            return self.stored
        return dataclasses.replace(self.stored, notes=self.stored.notes + (
            f"the saved drawing: its text prints at {pt:g} pt, not {font_pt:g} pt",))


def stored_source(record: dict[str, Any], fragment: dict[str, Any] | None, base: Path) -> _Stored:
    """The source of an inset from its page file: ``record``, the stored ``fragment`` and the page file's folder."""

    return _Stored(record, fragment, base)
