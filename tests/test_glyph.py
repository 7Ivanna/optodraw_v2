"""Glyph draws the state of the signal beside a beam: a pulse, a pulse train, a spectrum, a wave, a spot."""

import pytest

from optodraw import Beam, Glyph, Laser, Mirror, Note, Photodiode, Scene, check_figure
from optodraw.components.misc import GLYPH_KINDS
from optodraw.core.component import ANNOTATION_TYPES
from optodraw.notebook_1d import render_notebook_1d
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec


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


@pytest.mark.parametrize("kind", GLYPH_KINDS)
def test_each_kind_draws_in_svg_and_tikz(kind):
    scene, beam, _ = bench()
    tikz, svg = scene.render_tikz(), scene.render_svg().as_svg()
    scene.add(Glyph.on(beam, kind, leg=0))
    assert len(scene.render_tikz()) > len(tikz) and len(scene.render_svg().as_svg()) > len(svg)


def test_a_name_that_is_no_kind_is_refused():
    with pytest.raises(ValueError, match="pulse"):
        Glyph("square")


def test_a_glyph_takes_the_colour_of_its_beam():
    _, beam, _ = bench()
    assert Glyph.on(beam, "pulse").color == beam.color
    assert Glyph.on(beam, "pulse", color="#123456").color == "#123456"


def test_over_a_flat_leg_the_glyph_stands_clear_above_the_beam():
    _, beam, _ = bench()
    glyph = Glyph.on(beam, "pulse", leg=0, at=0.5, side="left", gap=1.0)
    x0, y0, x1, y1 = box_of(glyph)
    (ax, ay), (bx, by) = beam.legs()[0]
    assert y0 == pytest.approx((ay + by) / 2.0 + beam.display_width / 2.0 + 1.0, abs=0.05)
    assert (x0 + x1) / 2.0 == pytest.approx((ax + bx) / 2.0, abs=0.05)


def test_the_right_side_of_a_flat_leg_is_below_it():
    _, beam, _ = bench()
    assert box_of(Glyph.on(beam, "pulse", leg=0, side="right"))[3] < -beam.display_width / 2.0


def test_beside_a_steep_leg_the_glyph_stands_clear_of_the_beam():
    _, beam, _ = bench()
    glyph = Glyph.on(beam, "spectrum", leg=1, side="left", gap=1.0)     # the leg runs down, so left is +x
    (ax, _), (bx, _) = beam.legs()[1]
    assert box_of(glyph)[0] == pytest.approx((ax + bx) / 2.0 + beam.display_width / 2.0 + 1.0, abs=0.05)


def test_size_sets_the_width():
    wide = box_of(Glyph("pulse", size=12.0))
    assert wide[2] - wide[0] == pytest.approx(12.0)


def test_a_pulse_peaks_in_its_middle():
    outline = next(c for c in Glyph("pulse").annotation_2d()["children"] if c["type"] == "polyline")["points"]
    top = max(outline, key=lambda p: p[1])
    assert top[0] == pytest.approx(0.0, abs=0.2)
    assert outline[0][1] == pytest.approx(outline[-1][1])


def test_a_train_has_several_pulses():
    outline = next(c for c in Glyph("train").annotation_2d()["children"] if c["type"] == "polyline")["points"]
    ys = [y for _, y in outline]
    crests = sum(ys[i - 1] < ys[i] >= ys[i + 1] for i in range(1, len(ys) - 1))
    assert crests == 4


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


def test_a_line_keeps_its_share_of_the_text():
    glyph = Glyph("pulse")
    width = next(c for c in glyph.annotation_2d()["children"] if c["type"] == "polyline")["stroke_width"]
    twice = next(c for c in glyph.annotation_2d(2.0)["children"] if c["type"] == "polyline")["stroke_width"]
    assert twice == 2.0 * width


def test_a_saved_glyph_comes_back():
    scene, beam, _ = bench()
    scene.add(Glyph.on(beam, "train", size=9.0))
    back = next(n for n in scene_from_spec(scene_to_spec(scene)).walk() if isinstance(n, Glyph))
    assert (back.kind, back.size, back.color) == ("train", 9.0, beam.color)


def test_a_glyph_is_a_mark_and_is_no_part():
    assert "Glyph" in ANNOTATION_TYPES
    assert build_component("Glyph").ports() == {}
    scene, beam, _ = bench()
    scene.add(Glyph.on(beam, "pulse"))
    assert not any(isinstance(n, Glyph) for n in scene._parts())
    assert "Glyph" not in render_notebook_1d(scene)


def test_the_frame_holds_a_glyph():
    scene = Scene(title="x", width=80, height=20, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), wavelength=635))
    pd = scene.add(Photodiode(center=(30, 0), angle=180))
    beam = scene.add(Beam((laser, "out"), (pd, "in"), wavelength=635))
    _, _, _, top = scene.content_bounds()
    glyph = scene.add(Glyph.on(beam, "pulse", size=30.0, gap=8.0))
    assert scene.content_bounds()[3] >= box_of(glyph)[3] > top


def test_the_gate_finds_a_glyph_on_a_label():
    scene, beam, _ = bench()
    scene.add(Note("Key", center=(-10, 3.0)))
    scene.add(Glyph.on(beam, "pulse", leg=0))
    found = [f for f in check_figure(scene, view="2d") if "glyph" in f]
    assert len(found) == 1 and '"Key"' in found[0]


def test_the_gate_finds_a_glyph_on_a_part():
    scene, beam, mirror = bench()
    scene.add(Glyph.on(beam, "pulse", leg=0, at=0.98))
    assert any("glyph" in f and "Mirror" in f for f in check_figure(scene, view="2d"))


def test_a_clear_glyph_passes_the_gate():
    scene, beam, _ = bench()
    scene.add(Glyph.on(beam, "pulse", leg=0))
    assert not [f for f in check_figure(scene, view="2d") if "glyph" in f]


def test_the_frame_holds_the_whole_of_a_spot():
    x0, y0, x1, y1 = box_of(Glyph("spot", size=10.0))
    assert (x1 - x0, y1 - y0) == pytest.approx((6.0, 6.0))
