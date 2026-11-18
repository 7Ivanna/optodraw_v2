"""Look B: the cross-section as an SEM-like image, in PNG.

A grey per material, a bright rim along every edge (the secondary-electron edge effect), a beam blur, seeded
detector noise and an info bar with a scale bar. The image is a render: it says so in its info bar and across
the image (``mark=False`` removes both), and its PNG metadata says "rendered, not measured" always. It never
carries instrument values.
"""

from __future__ import annotations

from dataclasses import dataclass

from optodraw.gds.palette import canonical

# material -> (mean atomic number by mass, grey). The greys follow secondary-electron contrast in cross
# sections: vacuum black, oxide dark, silicon a darker grey, nitride mid, germanium and metals bright.
# Mean Z alone would put nitride under silicon; the column stays for reference.
SEM_MATERIALS: dict[str, tuple[float, int]] = {
    "vacuum": (0.0, 0),
    "sio2": (10.8, 72),
    "silicon": (14.0, 118),
    "polysilicon": (14.0, 124),
    "silicon_nitride": (11.2, 150),
    "aluminum": (13.0, 196),
    "aluminium": (13.0, 196),
    "titanium_nitride": (18.6, 200),
    "germanium": (32.0, 205),
    "copper": (29.0, 214),
    "tungsten": (74.0, 232),
    "gold": (79.0, 240),
}
_UNKNOWN = 160
_VACUUM_SHARE = 0.10                 # of the image height, above the top surface
_SUBSTRATE_SHARE = 0.08              # of the stack height, of substrate under the BOX
_MAX_ASPECT = 1.25                   # height over width; a taller cut loses substrate from the bottom


def sem_grey(material: str) -> int:
    """The grey (0 to 255) a material shows in look B."""

    return SEM_MATERIALS.get(canonical(material), (0.0, _UNKNOWN))[1]


@dataclass(frozen=True)
class SEMCanvas:
    """True-aspect pixels of the image area (the info bar sits under it)."""

    s0: float
    z_top: float
    px_per_um: float
    width: int
    height: int

    def x(self, s: float) -> float:
        return (s - self.s0) * self.px_per_um

    def y(self, z: float) -> float:
        return (self.z_top - z) * self.px_per_um


def sem_canvas(xs, width_px: int) -> SEMCanvas:
    """The window of ``xs`` at ``width_px`` across: vacuum over the top surface, the whole BOX, a little
    substrate."""

    s0, s1 = xs.window
    px_per_um = width_px / max(s1 - s0, 1e-9)
    solids = [g for g in xs.regions.values() if not g.is_empty]
    top = max(g.bounds[3] for g in solids)
    floor = min(g.bounds[1] for g in solids)
    box = xs.regions.get("box")
    box_bottom = box.bounds[1] if box is not None and not box.is_empty else floor
    bottom = max(floor, box_bottom - _SUBSTRATE_SHARE * (top - box_bottom))
    z_top = top + _VACUUM_SHARE / (1.0 - _VACUUM_SHARE) * (top - bottom)
    height = min(round((z_top - bottom) * px_per_um), int(_MAX_ASPECT * width_px))
    return SEMCanvas(s0=s0, z_top=z_top, px_per_um=px_per_um, width=int(width_px), height=int(height))


_SUPERSAMPLE = 2
_RIM_SURFACE = (95.0, 0.035)         # grey added at a surface to vacuum, and its fall-off length in um
_RIM_INTERFACE = (30.0, 0.015)       # the same at an interface between two materials
_BEAM = 0.006                        # um, the blur of the beam spot
_NOISE = (6.0, 0.05)                 # detector noise: a floor, and a share of the signal


def render_sem(xs, *, seed: int = 0, mark: bool = True, width_px: int = 2000) -> bytes:
    """The cross-section ``xs`` as an SEM-like PNG ``width_px`` across, with an info bar under it. The same
    ``seed`` gives the same bytes. Implants do not show: an SEM does not see them without special contrast."""

    import numpy as np

    canvas = sem_canvas(xs, int(width_px))
    grey = _micrograph(xs, canvas, seed)
    if mark:
        grey = _diagonal_mark(grey, _feature_rows(xs, canvas))
    bar = _info_bar(xs.window[1] - xs.window[0], canvas.px_per_um, canvas.width, mark)
    return _png_bytes(np.vstack([grey, bar]))


def _png_bytes(pixels) -> bytes:
    """Grey pixels as PNG bytes, with the metadata of a render."""

    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
    except ImportError as exc:                       # pragma: no cover - Pillow ships with the gif extra
        raise ImportError("look B needs Pillow: pip install 'optodraw[gif]'") from exc
    import io

    import numpy as np

    image = Image.fromarray(np.clip(np.rint(pixels), 0, 255).astype(np.uint8), mode="L")
    info = PngInfo()                                  # always, marks or not: a render must not pass as a micrograph
    info.add_text("Software", "optodraw")
    info.add_text("Description", "rendered, not measured: an optodraw render of a process model, not a micrograph")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


_MARK = "optodraw render"
_MARK_ALPHA = 0.12                   # how strongly the diagonal mark lightens the image
_MARK_ANGLE = 25.0                   # degrees


def _feature_rows(xs, canvas: SEMCanvas) -> tuple[float, float, float] | None:
    """The row of the top surface, and the rows the device and its metals take (everything but the
    substrate and the oxide), or None."""

    features = [g for name, g in xs.regions.items() if not g.is_empty and name not in ("handle", "box")
                and canonical(xs.materials.get(name, name)) != "sio2"]
    if not features:
        return None
    surface = max(g.bounds[3] for g in xs.regions.values() if not g.is_empty)
    return (canvas.y(surface), canvas.y(max(g.bounds[3] for g in features)),
            canvas.y(min(g.bounds[1] for g in features)))


def _diagonal_mark(grey, rows: tuple[float, float, float] | None):
    """A faint "optodraw render" at an angle, in the taller of the solid bands over and under the device
    (``rows``: the top surface, the device top, the device bottom), so it never lies across the device."""

    import math

    import numpy as np
    from PIL import Image, ImageDraw

    height, width = grey.shape
    top, bottom = (0.0, float(height)) if rows is None else max(
        ((rows[0], rows[1]), (rows[2], float(height))), key=lambda band: band[1] - band[0])
    if bottom - top < 0.15 * height:                  # no room beside the device: the middle of the image
        top, bottom = 0.0, float(height)
    angle = math.radians(_MARK_ANGLE)
    size = round(0.075 * width)
    font, _ = _font(size)
    x0, y0, x1, y1 = font.getbbox(_MARK)
    tall = (x1 - x0) * math.sin(angle) + (y1 - y0) * math.cos(angle)
    wide = (x1 - x0) * math.cos(angle) + (y1 - y0) * math.sin(angle)
    shrink = min(1.0, 0.85 * (bottom - top) / tall, 0.8 * width / wide)
    font, _ = _font(max(12, round(size * shrink)))
    centre = (width / 2, (top + bottom) / 2)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).text(centre, _MARK, font=font, fill=255, anchor="mm")
    mask = mask.rotate(_MARK_ANGLE, resample=Image.Resampling.BICUBIC, center=centre)
    share = _MARK_ALPHA * np.asarray(mask, dtype=float) / 255.0
    return grey * (1.0 - share) + 255.0 * share


def _micrograph(xs, canvas: SEMCanvas, seed: int):
    """The image area as floats: greys, rims, beam blur and noise."""

    import numpy as np
    from scipy import ndimage

    labels, greys = _labels(xs, canvas)
    ss = _SUPERSAMPLE
    base = greys[labels].reshape(canvas.height, ss, canvas.width, ss).mean(axis=(1, 3))
    coarse = labels[::ss, ::ss]
    shade = greys[coarse]                            # one oxide against another shows no interface
    across = shade[:, 1:] != shade[:, :-1]
    down = shade[1:, :] != shade[:-1, :]
    vacuum = coarse == 0
    edges = np.zeros_like(vacuum)
    surface = np.zeros_like(vacuum)
    for step, near, far in ((across, np.s_[:, 1:], np.s_[:, :-1]), (down, np.s_[1:, :], np.s_[:-1, :])):
        touches = step & (vacuum[near] | vacuum[far])
        for side in (near, far):
            edges[side] |= step & ~touches
            surface[side] |= touches
    rim = np.zeros_like(base)
    for found, (gain, length) in ((surface, _RIM_SURFACE), (edges, _RIM_INTERFACE)):
        if found.any():
            distance = ndimage.distance_transform_edt(~found)
            rim += gain * np.exp(-distance / max(length * canvas.px_per_um, 1.5))
    image = base + np.where(vacuum, 0.0, rim)
    image = ndimage.gaussian_filter(image, max(_BEAM * canvas.px_per_um, 0.7))
    rng = np.random.default_rng(seed)
    image = image + rng.normal(0.0, 1.0, image.shape) * (_NOISE[0] + _NOISE[1] * image)
    return ndimage.gaussian_filter(image, 0.5)


def _labels(xs, canvas: SEMCanvas):
    """A label per pixel of the supersampled image area (0 is vacuum), and the grey of each label."""

    import numpy as np
    from PIL import Image, ImageDraw

    from optodraw.gds.xsection.schematic import _polygons

    ss = _SUPERSAMPLE
    size = (canvas.width * ss, canvas.height * ss)
    labels = np.zeros((size[1], size[0]), dtype=np.uint8)
    greys = [float(sem_grey("vacuum"))]
    for name, geometry in xs.regions.items():
        if geometry.is_empty:
            continue
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        for polygon in _polygons(geometry):
            draw.polygon([(canvas.x(s) * ss, canvas.y(z) * ss) for s, z in polygon.exterior.coords], fill=255)
            for ring in polygon.interiors:
                draw.polygon([(canvas.x(s) * ss, canvas.y(z) * ss) for s, z in ring.coords], fill=0)
        labels[np.asarray(mask) > 0] = len(greys)
        greys.append(float(sem_grey(xs.materials.get(name, name))))
    return labels, np.asarray(greys)


def _info_bar(span: float, px_per_um: float, width: int, mark: bool, note: str = ""):
    """A black bar ``width`` pixels across under an image ``span`` um wide, with a scale bar and its length
    (and ``note`` after it), and "optodraw render" at the right when ``mark``. No instrument values: this is a
    render."""

    import numpy as np
    from PIL import Image, ImageDraw

    from optodraw.gds.xsection.schematic import _nice, _size

    tall = max(30, round(0.06 * width))
    bar = Image.new("L", (width, tall), 0)
    draw = ImageDraw.Draw(bar)
    length = _nice(span / 5.0)
    x0, thick = round(0.03 * width), max(3, round(0.006 * width))
    x1 = x0 + round(length * px_per_um)
    draw.rectangle([x0, tall // 2 - thick // 2, x1, tall // 2 - thick // 2 + thick - 1], fill=255)
    font, micro = _font(max(10, round(0.42 * tall)))
    text = _size(length) + (f", {note}" if note else "")
    text = text if micro else text.replace("µ", "u").replace("°", " deg")
    draw.text((x1 + round(0.012 * width), tall // 2), text, font=font, fill=255, anchor="lm")
    if mark:
        draw.text((width - x0, tall // 2), _MARK, font=font, fill=210, anchor="rm")
    return np.asarray(bar, dtype=float)


def _font(size: int):
    """A font with a micro sign (DejaVu Sans, which matplotlib carries), else Pillow's own; and whether it
    has the micro sign."""

    import os

    from PIL import ImageFont

    try:
        import matplotlib

        return ImageFont.truetype(os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans.ttf"), size), True
    except (ImportError, OSError):
        return ImageFont.load_default(size=size), False
