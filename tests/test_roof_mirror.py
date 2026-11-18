"""A hollow roof mirror: the beam comes back parallel and beside itself; on its stage it is a delay line."""

from __future__ import annotations

import pytest

from optodraw import Beam, Laser, Mirror, Photodiode, RoofMirror, Scene, check_figure, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.layout import aim, face
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d


def test_in_and_out_face_the_light_side_by_side():
    ports = RoofMirror(aperture=12.0).ports()
    assert set(ports) == {"in", "out"}
    assert ports["in"].orientation_deg == ports["out"].orientation_deg == 180.0
    assert ports["in"].center.x == ports["out"].center.x
    assert ports["in"].center.y - ports["out"].center.y == pytest.approx(2 * RoofMirror.OFFSET * 12.0)


def test_the_light_meets_each_face_at_45_degrees_and_turns_back():
    part = RoofMirror(aperture=12.0)
    start, first, second, end = part.light_path("in", "out")
    front = RoofMirror.FRONT * 12.0
    for x, y in (first, second):
        assert abs(y) == pytest.approx(front - x)                       # on a face: |y| = FRONT - x
    assert first[0] == second[0] and start[1] == first[1] and end[1] == second[1]
    assert part.light_path("out", "in") == [end, second, first, start]


def test_it_rides_a_stage_by_default_and_keeps_its_mount_through_a_save():
    assert RoofMirror().base_mount == "stage"
    scene = Scene(title="", platform="free_space")
    scene.add(RoofMirror(label="Delay"))
    scene.add(RoofMirror(center=(30, 0), base_mount="post", label="Fixed"))
    kept = {n.label: n.base_mount for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "RoofMirror"}
    assert kept == {"Delay": "stage", "Fixed": "post"}


def test_a_part_on_a_stage_stays_on_it_after_a_load():
    scene = Scene(title="", platform="free_space")
    scene.add(Mirror(base_mount="stage", label="M"))
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "Mirror"]
    assert again.base_mount == "stage"


def test_it_stands_on_its_post_or_stage():
    assert check_part_3d(RoofMirror()) == [] and check_part_3d(RoofMirror(base_mount="post")) == []


def _delay_line():
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-34, 3), wavelength=800, label="Laser"))
    roof = scene.add(RoofMirror(center=(6, 0), label="Delay", label_side="bottom"))
    fold = scene.add(Mirror(center=(-14, -3), label="M", label_side="left"))
    pd = scene.add(Photodiode(center=(-14, -18), label="PD", label_side="right"))
    out = roof.world_port("out").center
    aim(fold, (out.x, out.y), pd)
    face(pd, (-14, -3))
    scene.add(Beam.through(laser, (roof, "in"), (roof, "out"), fold, pd, wavelength=800))
    return scene


def test_the_light_comes_back_off_both_faces():
    absorbed = Animation(_delay_line(), mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    assert [r["power"] for r in absorbed] == pytest.approx([0.99 ** 3])      # two faces of 99 %, then the fold


def test_its_symbol_and_art_follow_the_plan():
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    part = RoofMirror()
    assert lookup(part).exact and lookup(part).name == "roof" and art_2d(part)["residual"] < 0.02


def test_a_delay_line_passes_the_figure_checks():
    scene = _delay_line()
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
