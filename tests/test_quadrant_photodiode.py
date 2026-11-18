"""A quadrant photodiode ends a beam and sends x, y and sum from three connectors on top."""

from __future__ import annotations

import pytest

from optodraw import Beam, Laser, Lens, QuadrantPhotodiode, Scene, check_figure, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.app.validation import run_checks
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import symbol_for_2d


def _at_focus(lit=True):
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), wavelength=1064, label="Laser"))
    lens = scene.add(Lens(center=(0, 0), focal_length=20, label="Lens"))
    qpd = scene.add(QuadrantPhotodiode(center=(0, 0 if lit else 30), label="QPD"))
    qpd.transform.position.x = 20 - qpd.ports()["in"].center.x           # its window at the focus
    scene.add(Beam.through(laser, lens, *([qpd] if lit else []), wavelength=1064, width=0.8))
    return scene


def test_the_light_enters_its_window_and_the_outputs_leave_on_top():
    ports = QuadrantPhotodiode(box_size=10).ports()
    assert ports["in"].kind == "free_space" and ports["in"].orientation_deg == pytest.approx(180)
    assert ports["in"].center.x < 0
    outputs = {name: ports[name] for name in ("x", "y", "sum")}
    assert all(p.kind == "electrical" and p.orientation_deg == pytest.approx(90) for p in outputs.values())
    assert all(p.center.y == pytest.approx(6.0) for p in outputs.values())   # the tops of the connectors


def test_it_absorbs_the_beam_it_ends():
    absorbed = Animation(_at_focus(), mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    assert {record["part"]: round(record["power"], 3) for record in absorbed} == {"quadrantphotodiode1": 1.0}


def test_a_qpd_that_no_beam_reaches_is_reported_dark():
    dark = [i["message"] for i in run_checks(_at_focus(lit=False)) if i["kind"] == "illumination"]
    assert any(message.startswith("QPD receives no light") for message in dark)
    assert not [i for i in run_checks(_at_focus()) if i["kind"] == "illumination"]


def test_its_3d_has_four_quadrants_and_stands_on_its_post():
    part = QuadrantPhotodiode()
    quadrants = [c for c in part.geometry_3d()["children"] if c.get("role") == "quadrant"]
    assert len(quadrants) == 4 and check_part_3d(part) == []


def test_it_keeps_its_values_through_a_save():
    scene = _at_focus()
    (qpd,) = [n for n in scene.walk() if n.component_type == "QuadrantPhotodiode"]
    qpd.active_diameter_mm = 3.0
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "QuadrantPhotodiode"]
    assert again.active_diameter_mm == pytest.approx(3.0)


def test_it_has_a_face_on_symbol_in_1d_and_the_housing_in_2d():
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    part = QuadrantPhotodiode()
    assert lookup(part).exact and lookup(part).name == "qpd" and not lookup(part).params
    assert symbol_for_2d(part).exact and symbol_for_2d(part).params == {"view": "top"}


def test_a_qpd_at_the_focus_passes_the_figure_checks():
    scene = _at_focus()
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
