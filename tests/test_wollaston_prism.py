"""A Wollaston prism sends the two polarizations apart: H above the axis at o, V below it at e."""

from __future__ import annotations

import numpy as np

from optodraw import Beam, HalfWavePlate, Laser, Photodiode, Scene, WollastonPrism, check_figure
from optodraw.animation_engine.behaviours.polarisation import Wollaston
from optodraw.layout import face


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


def test_h_leaves_at_o_and_v_at_e():
    routes = {t.out_port: t.matrix for t in Wollaston().transfers(WollastonPrism(), "w", "in", 633.0, {})}
    assert set(routes) == {"o", "e"}
    assert np.allclose(routes["o"] @ [1, 0], [1, 0]) and np.allclose(routes["o"] @ [0, 1], [0, 0])
    assert np.allclose(routes["e"] @ [0, 1], [0, 1]) and np.allclose(routes["e"] @ [1, 0], [0, 0])


def test_a_balanced_bench_passes_the_figure_checks():
    scene = _balanced(22.5)
    scene.fit_frame(margin=4)
    assert check_figure(scene, preset="single_column") == []
