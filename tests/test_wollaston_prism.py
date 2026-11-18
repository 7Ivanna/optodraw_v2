"""A Wollaston prism sends the two polarizations apart: H above the axis at o, V below it at e."""

from __future__ import annotations

import numpy as np
import pytest

from optodraw import Beam, HalfWavePlate, Laser, Photodiode, Scene, WollastonPrism, check_figure, check_part_3d
from optodraw.animation_engine import Animation
from optodraw.animation_engine.behaviours.polarisation import Wollaston
from optodraw.layout import face
from optodraw.schema import scene_from_spec, scene_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import symbol_for_2d


def _balanced(plate_angle):
    scene = Scene(title="", platform="free_space")
    scene.set_view_layout({"1d": {"spacing": 1}})
    laser = scene.add(Laser(center=(-34, 0), wavelength=633, label="Laser"))
    hwp = scene.add(HalfWavePlate(center=(-14, 0), fast_axis_angle=plate_angle, label="HWP"))
    wp = scene.add(WollastonPrism(center=(0, 0), label="WP", label_side="bottom"))
    up = scene.add(Photodiode(center=(26, 7), label="PD1", label_side="top"))
    down = scene.add(Photodiode(center=(26, -7), label="PD2", label_side="bottom"))
    face(up, wp)
    face(down, wp)
    scene.add(Beam.through(laser, hwp, wp, wavelength=633, width=0.6))
    scene.add(Beam.through((wp, "o"), up, wavelength=633, width=0.5))
    scene.add(Beam.through((wp, "e"), down, wavelength=633, width=0.5))
    return scene


def test_the_two_outputs_leave_the_back_face_apart_by_the_separation():
    ports = WollastonPrism(separation_deg=16.0).ports()
    assert set(ports) == {"in", "o", "e"}
    assert ports["o"].orientation_deg == pytest.approx(8.0) and ports["e"].orientation_deg == pytest.approx(-8.0)
    assert ports["o"].center.y > 0 > ports["e"].center.y
    assert ports["o"].center.x == pytest.approx(ports["e"].center.x) == pytest.approx(-ports["in"].center.x)


def test_h_leaves_at_o_and_v_at_e():
    routes = {t.out_port: t.matrix for t in Wollaston().transfers(WollastonPrism(), "w", "in", 633.0, {})}
    assert set(routes) == {"o", "e"}
    assert np.allclose(routes["o"] @ [1, 0], [1, 0]) and np.allclose(routes["o"] @ [0, 1], [0, 0])
    assert np.allclose(routes["e"] @ [0, 1], [0, 1]) and np.allclose(routes["e"] @ [1, 0], [0, 0])


def test_light_at_45_degrees_splits_evenly_and_h_goes_to_one_side():
    def powers(angle):
        state = Animation(_balanced(angle), mode="cw", strict=True).auto().click().to_json()["signal_state"]
        return {record["part"]: round(record["power"], 3) for record in state["absorbed"]}

    assert powers(22.5) == {"photodiode1": 0.5, "photodiode2": 0.5}
    assert powers(0.0).get("photodiode1") == 1.0 and powers(0.0).get("photodiode2", 0.0) == 0.0


def test_it_keeps_its_separation_through_a_save_and_has_clean_3d():
    scene = Scene(title="", platform="free_space")
    scene.add(WollastonPrism(separation_deg=5.0))
    (again,) = [n for n in scene_from_spec(scene_to_spec(scene)).walk() if n.component_type == "WollastonPrism"]
    assert again.separation_deg == pytest.approx(5.0)
    assert check_part_3d(WollastonPrism()) == []


def test_it_has_its_own_symbol():
    # needs the symbol library rebuilt with the rows of variants.toml (python -m optodraw.symbols.build)
    part = WollastonPrism()
    assert lookup(part).exact and symbol_for_2d(part).exact and lookup(part).name == "wollaston"


def test_a_balanced_bench_passes_the_figure_checks():
    scene = _balanced(22.5)
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
