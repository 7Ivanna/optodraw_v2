"""A triangular ring mode cleaner: its ring obeys the law of reflection, and its beams leave where the ring sends them."""

from __future__ import annotations

import math

import pytest

from optodraw import Beam, Laser, ModeCleaner, Photodiode, Scene, check_figure, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.layout import face
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d


def _reflect(d, n):
    dot = d[0] * n[0] + d[1] * n[1]
    return d[0] - 2.0 * dot * n[0], d[1] - 2.0 * dot * n[1]


def _unit(a, b):
    length = math.dist(a, b)
    return (b[0] - a[0]) / length, (b[1] - a[1]) / length


def test_each_mirror_sends_the_ring_on_to_the_next():
    mc, normals = ModeCleaner(), ModeCleaner.normals()
    ring = {"M1": (mc.M3, mc.M2), "M2": (mc.M1, mc.M3), "M3": (mc.M2, mc.M1)}
    here = {"M1": mc.M1, "M2": mc.M2, "M3": mc.M3}
    for name, (before, after) in ring.items():
        arriving = _unit(before, here[name])
        assert _reflect(arriving, normals[name]) == pytest.approx(_unit(here[name], after))


def test_the_input_reflected_at_m1_leaves_by_refl_along_the_leg_from_m3():
    mc = ModeCleaner(size=20.0)
    out = _reflect((1.0, 0.0), ModeCleaner.normals()["M1"])             # the input runs along +x
    assert out == pytest.approx(ModeCleaner.refl_direction())
    port = mc.ports()["refl"]
    angle = math.radians(port.orientation_deg)
    assert (math.cos(angle), math.sin(angle)) == pytest.approx(out)
    m1 = (mc.M1[0] * 20.0, mc.M1[1] * 20.0)                               # refl lies on that line, past M1
    assert _unit(m1, (port.center.x, port.center.y)) == pytest.approx(out)


def test_in_and_out_lie_on_one_line_and_the_piezo_adds_its_drive():
    ports = ModeCleaner(size=20.0).ports()
    assert set(ports) == {"in", "out", "refl"}
    assert (ports["in"].center.y, ports["out"].center.y) == (0.0, 0.0)
    assert (ports["in"].orientation_deg, ports["out"].orientation_deg) == (180.0, 0.0)
    pzt = ModeCleaner(piezo=True).ports()["pzt"]
    assert pzt.kind == "electrical" and pzt.orientation_deg == 90.0


def _bench(**options):
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-34, 0), wavelength=1064, label="Laser"))
    mc = scene.add(ModeCleaner(center=(0, 0), label="MC", label_side="top", **options))
    trans = scene.add(Photodiode(center=(24, 0), label="Trans"))
    dx, dy = mc.refl_direction()
    lock = scene.add(Photodiode(center=(-7.5 + 12 * dx, -3 + 12 * dy), label="Lock", label_side="left"))
    face(trans, mc)
    face(lock, mc)
    scene.add(Beam.through(laser, (mc, "in"), wavelength=1064))
    scene.add(Beam.through((mc, "out"), trans, wavelength=1064))
    scene.add(Beam.through((mc, "refl"), lock, wavelength=1064))
    return scene


def test_locked_it_passes_its_transmission_and_reflects_the_rest():
    absorbed = Animation(_bench(transmission=80.0), mode="cw", strict=True).auto().click().to_json()
    power = {r["part"]: r["power"] for r in absorbed["signal_state"]["absorbed"]}
    assert power == pytest.approx({"photodiode1": 0.8, "photodiode2": 0.2})


def test_it_keeps_its_values_through_a_save_and_stands_on_its_post():
    scene = _bench(piezo=True, size=24.0, transmission=85.0)
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "ModeCleaner"]
    assert (again.piezo, again.size, again.transmission) == (True, 24.0, 85.0)
    assert check_part_3d(ModeCleaner()) == [] and check_part_3d(ModeCleaner(piezo=True)) == []


def test_its_symbol_and_art_follow_the_plan():
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    for part in (ModeCleaner(), ModeCleaner(piezo=True)):
        assert lookup(part).exact and lookup(part).name == "modecleaner"
        assert art_2d(part)["residual"] < 0.02


def test_a_bench_with_it_passes_the_figure_checks():
    scene = _bench(piezo=True)
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
