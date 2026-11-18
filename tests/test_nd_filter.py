"""A neutral density filter takes the same share of every wavelength, and it leaves the beam its colour."""

from __future__ import annotations

import pytest

from optodraw import Beam, Laser, NDFilter, Photodiode, Scene
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.registry import build_component
from optodraw.schema import scene_from_spec, scene_to_spec


def _bench(**kwargs):
    scene = Scene(title="nd", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), wavelength=450, label="Laser"))
    nd = scene.add(NDFilter(center=(0, 0), label="ND wheel", **kwargs))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    return scene, laser, nd, pd


def test_it_is_built_from_the_registry():
    assert build_component("NDFilter", optical_density=2.0).optical_density == 2.0


def test_it_keeps_its_density_through_a_save():
    scene, _, _, _ = _bench(optical_density=1.5)
    loaded = next(n for n in scene_from_spec(scene_to_spec(scene)).walk() if isinstance(n, NDFilter))
    assert loaded.optical_density == 1.5


def test_a_negative_density_is_refused():
    with pytest.raises(ValueError, match="optical_density"):
        NDFilter(optical_density=-1.0)


def test_it_passes_every_wavelength_to_the_ray_tracer():
    assert NDFilter(optical_density=3.0).optical_interfaces() == []


def test_light_keeps_ten_to_the_minus_od_of_its_power():
    part = NDFilter(optical_density=2.0)
    amplitude = behaviour_for(part, "s").amplitude(part, "s", 450.0, {})
    assert amplitude ** 2 == pytest.approx(0.01)


def test_it_leaves_the_beam_its_colour():
    scene, laser, nd, pd = _bench()
    scene.add(Beam.through(laser, nd, pd, wavelength=450))
    svg = scene.render_svg().as_svg()
    assert "#f0a800" not in svg and "#0046ff" in svg


def test_it_has_a_grey_symbol_of_its_own():
    from optodraw import Filter
    from optodraw.symbols import lookup

    grey, teal = lookup(NDFilter()), lookup(Filter())
    assert grey.source == "prebuilt" and grey.svg != teal.svg and grey.ports.keys() == teal.ports.keys()


def test_it_draws_in_every_view():
    from optodraw.symbols.schematic import build_schematic

    scene, laser, nd, pd = _bench()
    scene.add(Beam.through(laser, nd, pd, wavelength=450))
    assert nd.geometry_2d() and nd.geometry_3d()
    assert len(build_schematic(scene).items) == 3
