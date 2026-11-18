"""An EOM has its drive and an amplified detector its output: the cables of a lock or a link end on ports.

The EOM drew its drive lead and the amplified detector its BNC, but neither had a port, so a figure could not wire
the local oscillator to the Pockels cell or the detector to the lock-in. The EOM's 2D art also covered only the
first half of the crystal: sized to the aperture, it was anchored on ``in`` and drew ``out`` 6.8 units short."""

from __future__ import annotations

import pytest

from optodraw import (EOM, AmplifiedPhotodetector, Beam, Laser, LockInAmplifier, Scene, WaveformGenerator,
                      check_figure)
from optodraw.symbols import lookup
from optodraw.symbols.art import PORT_TOLERANCE, art_2d

PARTS = [(EOM, {}, "rf"), (EOM, {"crystal_length": 20.0}, "rf"), (AmplifiedPhotodetector, {}, "out")]


@pytest.mark.parametrize("cls, args, name", PARTS)
def test_the_part_has_an_electrical_port_for_its_cable(cls, args, name):
    # mutant: delete ports["rf"] from EOM.ports: the oscillator has nothing to plug into
    part = cls(**args)
    assert part.ports()[name].kind == "electrical"
    symbol = lookup(part)
    assert symbol.exact and {key: mark.kind for key, mark in symbol.ports.items()} == {
        key: port.kind for key, port in part.ports().items()}


@pytest.mark.parametrize("cls, args, name", PARTS)
def test_the_2d_art_draws_every_port_where_the_part_has_it(cls, args, name):
    # mutant: delete _art_scale_from_ports from EOM: the art is sized to the aperture and "out" lands mid-crystal
    part = cls(**args)
    art, symbol = art_2d(part), lookup(part)
    a, b, c, d, e, f = art["matrix"]
    for key, port in part.ports().items():
        mark = symbol.ports[key]
        drawn = (a * mark.x + c * mark.y + e, -(b * mark.x + d * mark.y + f))
        assert drawn == pytest.approx((port.center.x, port.center.y), abs=PORT_TOLERANCE), key


def test_an_oscillator_drives_the_pockels_cell_and_a_lock_in_reads_the_detector():
    # mutant: "out" at (self.box_size * 0.3, 0, 0) in AmplifiedPhotodetector.ports: the cable ends inside the art
    scene = Scene(width=120, height=70, platform="free_space")
    laser = scene.add(Laser(center=(-45, 15), wavelength=1064, label="Laser"))
    eom = scene.add(EOM(center=(-15, 15), label="Pockels cell", label_side="bottom"))   # the drive leaves the top
    pd = scene.add(AmplifiedPhotodetector(center=(15, 15), label="Detector"))
    lo = scene.add(WaveformGenerator(center=(-15, 40), angle=180, label="Oscillator", label_side="bottom"))  # jacks face up
    lockin = scene.add(LockInAmplifier(center=(30, -15), label="Lock-in"))
    scene.add(Beam.through(laser, eom, pd, wavelength=1064))
    scene.route((lo, "out1"), (eom, "rf"), kind="electrical", width=0.3)
    scene.route((pd, "out"), (lockin, "in"), kind="electrical", width=0.3)
    scene.fit_frame(margin=6)
    assert check_figure(scene, preset="single_column") == []
