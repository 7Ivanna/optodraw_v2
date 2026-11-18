"""Glyph draws the state of the signal beside a beam: a pulse, a pulse train, a spectrum, a wave, a spot."""

import pytest

from optodraw import Beam, Glyph, Laser, Mirror, Photodiode, Scene, check_figure
from optodraw.core.component import ANNOTATION_TYPES
from optodraw.notebook_1d import render_notebook_1d
from optodraw.registry import build_component


def bench():
    scene = Scene(title="Bench", width=120, height=80, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), wavelength=635, label="Laser", label_side="bottom"))
    mirror = scene.add(Mirror(center=(20, 0), angle=135, label="Mirror", label_side="right"))
    pd = scene.add(Photodiode(center=(20, -30), angle=90, label="PD", label_side="right"))
    beam = scene.add(Beam((laser, "out"), (mirror, "io"), (pd, "in"), wavelength=635, width=1.0))
    return scene, beam, mirror


def box_of(glyph):
    points = glyph.drawn_points()
    return (min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points))


def test_a_name_that_is_no_kind_is_refused():
    with pytest.raises(ValueError, match="pulse"):
        Glyph("square")


def test_over_a_flat_leg_the_glyph_stands_clear_above_the_beam():
    _, beam, _ = bench()
    glyph = Glyph.on(beam, "pulse", leg=0, at=0.5, side="left", gap=1.0)
    x0, y0, x1, y1 = box_of(glyph)
    (ax, ay), (bx, by) = beam.legs()[0]
    assert y0 == pytest.approx((ay + by) / 2.0 + beam.display_width / 2.0 + 1.0, abs=0.05)
    assert (x0 + x1) / 2.0 == pytest.approx((ax + bx) / 2.0, abs=0.05)


def test_a_spectrum_has_a_line_for_each_peak():
    outline = [c for c in Glyph("spectrum").annotation_2d()["children"] if c["type"] == "line"]
    assert len(outline) == 5


def test_a_wave_crosses_its_axis():
    outline = next(c for c in Glyph("wave").annotation_2d()["children"] if c["type"] == "polyline")["points"]
    middle = (max(y for _, y in outline) + min(y for _, y in outline)) / 2.0
    assert sum((a[1] - middle) * (b[1] - middle) < 0 for a, b in zip(outline, outline[1:])) >= 4


def test_a_spot_is_round():
    rings = [c for c in Glyph("spot").annotation_2d()["children"] if c["type"] == "circle"]
    assert len(rings) >= 3 and rings[0]["r"] > rings[-1]["r"]


def test_a_glyph_is_a_mark_and_is_no_part():
    assert "Glyph" in ANNOTATION_TYPES
    assert build_component("Glyph").ports() == {}
    scene, beam, _ = bench()
    scene.add(Glyph.on(beam, "pulse"))
    assert not any(isinstance(n, Glyph) for n in scene._parts())
    assert "Glyph" not in render_notebook_1d(scene)


def test_a_clear_glyph_passes_the_gate():
    scene, beam, _ = bench()
    scene.add(Glyph.on(beam, "pulse", leg=0))
    assert not [f for f in check_figure(scene, view="2d") if "glyph" in f]


