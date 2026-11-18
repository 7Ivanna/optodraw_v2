"""A cube beam splitter has four faces: light that enters by the fourth (tap) can recombine two beams."""

from __future__ import annotations

import pytest

from optodraw import (PBS, Beam, Laser, Mirror, NonPolarizingBeamSplitter, Photodiode, Scene)
from optodraw.layout import aim, face


@pytest.mark.parametrize("cls", [NonPolarizingBeamSplitter, PBS])
def test_a_cube_has_a_tap_port_on_its_fourth_face(cls):
    ports = cls().ports()
    assert set(ports) == {"in", "trans", "refl", "tap"}
    tap, refl = ports["tap"], ports["refl"]
    assert (tap.center.x, tap.center.y) == pytest.approx((refl.center.x, -refl.center.y))
    assert tap.orientation_deg % 360 == pytest.approx(270.0)


def _cube_mzi():
    s = Scene(title="cube MZI", width=120, height=90, platform="free_space")
    laser = s.add(Laser(center=(-45, -20), wavelength=633, label="Laser"))
    bs1 = s.add(NonPolarizingBeamSplitter(center=(-20, -20), label="BS1"))
    m2 = s.add(Mirror(center=(20, -20), label="M2"))
    m1 = s.add(Mirror(center=(-20, 20), label="M1"))
    bs2 = s.add(NonPolarizingBeamSplitter(center=(20, 20), label="BS2"))
    pd1 = s.add(Photodiode(center=(45, 20), label="PD1"))
    pd2 = s.add(Photodiode(center=(20, 45), label="PD2"))
    aim(m1, bs1, bs2)
    aim(m2, bs1, bs2)
    face(pd1, bs2)
    face(pd2, bs2)
    s.add(Beam.through(laser, (bs1, "in"), (bs1, "trans"), m2, (bs2, "tap"), (bs2, "refl"), pd2))
    s.add(Beam.through((bs1, "refl"), m1, (bs2, "in"), (bs2, "trans"), pd1))
    return s, pd1, pd2


def test_a_cube_mach_zehnder_recombines_and_keeps_the_power():
    from optodraw.animation_engine import Animation

    scene, pd1, pd2 = _cube_mzi()
    data = Animation(scene, mode="cw", strict=True).auto().click().to_json()
    power = {record["part"]: record["power"] for record in data["signal_state"]["absorbed"]}
    assert set(power) == {"photodiode1", "photodiode2"}
    assert sum(power.values()) == pytest.approx(0.99, abs=1e-9)       # lossless cubes; each arm's mirror reflects 99 %


def test_a_polarizing_cube_routes_light_from_its_tap_face():
    from optodraw.animation_engine.behaviours import find_behaviour

    behaviour = find_behaviour(PBS())
    routes = {(t.in_port, t.out_port) for port in ("tap", "trans", "refl")
              for t in behaviour.transfers(PBS(), "pbs1", port, 1550.0, {})}
    assert {("tap", "refl"), ("tap", "trans"), ("trans", "tap"), ("refl", "tap")} <= routes


@pytest.mark.parametrize("cls", [NonPolarizingBeamSplitter, PBS])
def test_the_cube_keeps_an_exact_1d_symbol(cls):
    from optodraw.symbols import lookup

    symbol = lookup(cls())
    assert symbol.exact and symbol.source == "prebuilt"
    assert set(symbol.ports) >= {"in", "trans", "refl", "tap"}
