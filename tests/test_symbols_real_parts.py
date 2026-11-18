"""A bench symbol shows its object: the art agrees with the part's own 3D model, and no two parts share one bar."""

import io
import itertools
import re

import pytest

from optodraw import Beam, Laser, Photodiode, Razor, Scene
from optodraw.animation_engine import Animation
from optodraw.symbols import lookup
from optodraw.symbols.art import symbol_for_2d
from optodraw.symbols.build import library_files


def art(part, look="2d"):
    """The drawing of a part as red, green, blue, alpha, at ten pixels to the point."""

    numpy = pytest.importorskip("numpy")
    from optodraw.raster import svg_to_png
    image = pytest.importorskip("PIL.Image")
    symbol = lookup(part)
    drawn = svg_to_png(symbol.svg2d if look == "2d" else symbol.svg, zoom=10)
    return numpy.asarray(image.open(io.BytesIO(drawn)).convert("RGBA")).astype(float), symbol


def pixel(rgba, symbol, x, y):
    """The row and the column of a point of the symbol, in SVG points."""

    scale = rgba.shape[1] / symbol.width
    return int(y * scale), int(x * scale)


def luma(rgba):
    return 0.2126 * rgba[..., 0] + 0.7152 * rgba[..., 1] + 0.0722 * rgba[..., 2]


def runs(row):
    return sum(1 for a, b in itertools.pairwise([False, *row]) if b and not a)


def silhouette(part, size=64):
    numpy = pytest.importorskip("numpy")
    image = pytest.importorskip("PIL.Image")
    rgba, _ = art(part)
    ink = rgba[..., 3] > 128
    rows, columns = numpy.where(ink.any(axis=1))[0], numpy.where(ink.any(axis=0))[0]
    crop = ink[rows.min():rows.max() + 1, columns.min():columns.max() + 1]
    return numpy.asarray(image.fromarray(crop).resize((size, size))) > 0


def solids(part):
    return part.geometry_3d()["children"]


def top_of(solid):
    return solid["position"][1] + solid["height"] / 2.0


def ray_of_the_dump():
    """The legs of the ray in the picture of the dump, as they are drawn: (x0, y0, x1, y1), in units of the aperture."""

    tex = "\n".join(path.read_text(encoding="utf-8") for path in library_files())
    picture = tex[tex.index("pics/od beamdump/.style"):]
    legs = re.search(r"\\odo in\s*\{([^}]*)\}", picture).group(1)
    return [tuple(float(v) for v in leg.strip().split("/")[:4]) for leg in legs.split(",")]


def absorbed(*parts):
    scene = Scene(title="Light", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=633))
    placed = [scene.add(part) for part in parts]
    scene.add(Beam.through(laser, *placed, wavelength=633))
    light = Animation(scene, mode="cw", strict=True).auto().click()
    return {record["part"]: round(record["power"], 3) for record in light.to_json()["signal_state"]["absorbed"]}


def test_a_knife_edge_on_the_axis_passes_half_of_the_power():
    assert list(absorbed(Razor(center=(0, 0)), Photodiode(center=(30, 0), angle=180)).values()) == [0.5]


def top_art(part):
    """The drawing a part shows in 2D, which may be another view than its 1D symbol."""

    numpy = pytest.importorskip("numpy")
    from optodraw.raster import svg_to_png
    image = pytest.importorskip("PIL.Image")
    symbol = symbol_for_2d(part)
    drawn = svg_to_png(symbol.svg2d, zoom=10)
    return numpy.asarray(image.open(io.BytesIO(drawn)).convert("RGBA")).astype(float), symbol


