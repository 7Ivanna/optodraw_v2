"""A free-space balanced detector: two inputs side by side on one face, one difference output."""

from __future__ import annotations

import pytest

from optodraw import BalancedDetector, Beam, BeamSplitter, Laser, Mirror, Scene, check_figure, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.app.validation import run_checks
from optodraw.layout import aim
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d


def test_its_two_inputs_share_the_front_face_and_the_output_leaves_the_back():
    ports = BalancedDetector(box_size=20.0).ports()
    assert set(ports) == {"in1", "in2", "out"}
    assert ports["in1"].center.x == ports["in2"].center.x < 0 < ports["out"].center.x
    assert ports["in1"].orientation_deg == ports["in2"].orientation_deg == 180.0
    assert ports["in1"].center.y - ports["in2"].center.y == pytest.approx(BalancedDetector.PITCH * 20.0)
    assert ports["out"].kind == "electrical"


def _bench():
    scene = Scene(title="", platform="free_space")
    laser = scene.add(Laser(center=(-40, 4), wavelength=1064, label="Laser"))
    bs = scene.add(BeamSplitter(center=(-20, 4), transmission=50, label="BS", label_side="top"))
    fold = scene.add(Mirror(center=(-20, -4), label="M", label_side="bottom"))
    bd = scene.add(BalancedDetector(center=(4, 0), label="Balanced PD", label_side="bottom"))
    aim(bs, laser, fold)
    port = bd.world_port("in2").center
    aim(fold, bs, (port.x, port.y))
    scene.add(Beam.through(laser, bs, (bd, "in1"), wavelength=1064))
    scene.add(Beam.through((bs, "refl"), fold, (bd, "in2"), wavelength=1064))
    return scene


def test_it_absorbs_the_light_at_both_inputs():
    absorbed = Animation(_bench(), mode="cw", strict=True).auto().click().to_json()["signal_state"]["absorbed"]
    by_port = sorted((r["port"], round(r["power"], 4)) for r in absorbed)
    assert by_port == [("in1", 0.5), ("in2", round(0.5 * 0.99, 4))]


def test_it_counts_as_a_detector_that_needs_light():
    scene = _bench()
    assert not [issue for issue in run_checks(scene) if "Balanced PD" in issue["message"]]
    scene.add(BalancedDetector(center=(0, 40), label="Dark PD"))                # no beam reaches this one
    assert [issue for issue in run_checks(scene) if "Dark PD" in issue["message"]]


def test_it_keeps_its_size_through_a_save_and_stands_on_its_post():
    scene = Scene(title="", platform="free_space")
    scene.add(BalancedDetector(box_size=16.0))
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "BalancedDetector"]
    assert again.box_size == 16.0
    assert check_part_3d(BalancedDetector()) == []


def test_its_symbol_and_art_follow_the_plan():
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    part = BalancedDetector()
    assert lookup(part).exact and lookup(part).name == "balanced" and art_2d(part)["residual"] < 0.02


def test_a_balanced_bench_passes_the_figure_checks():
    scene = _bench()
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
