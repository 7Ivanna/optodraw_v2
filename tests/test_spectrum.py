"""Spectra: the steady power at each output against wavelength, checked against the closed forms."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest_models import _ring_scene

import optodraw
from optodraw.animation_engine import spectrum
from optodraw.animation_engine.behaviours import behaviour_for, polyline_length
from optodraw.animation_engine.behaviours.geometry import index_of
from optodraw.animation_engine.ids import scene_ids


def _phase(ring, wavelengths_nm):
    """The round-trip phase of the loop the engine uses, at the group index the engine uses."""

    L = polyline_length(behaviour_for(ring, "r").geometry(ring, True)[1])
    return 2 * math.pi * index_of(ring, "o1") * L / (wavelengths_nm / 1000)


def test_an_all_pass_ring_matches_its_closed_form():
    scene, ring, pd = _ring_scene()
    pd_sid = scene_ids(scene)[id(pd)]
    s = spectrum(scene, start_nm=1540, stop_nm=1560, points=401)
    r, a = math.sqrt(1 - 0.1), 0.99
    phi = _phase(ring, s.wavelengths_nm)
    closed = (a**2 - 2*a*r*np.cos(phi) + r**2) / (1 - 2*a*r*np.cos(phi) + (a*r)**2)
    assert np.max(np.abs(s.power[f"{pd_sid}:o1"] - closed)) < 1e-9


def test_an_add_drop_ring_drop_port_matches_its_closed_form():
    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0), add_drop=True))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")           # the drop port o3 is open: light exits there
    s = spectrum(scene, start_nm=1540, stop_nm=1560, points=401)
    r1 = r2 = math.sqrt(1 - 0.1)
    a = 0.99
    phi = _phase(ring, s.wavelengths_nm)
    closed = (1 - r1**2) * (1 - r2**2) * a / (1 - 2*r1*r2*a*np.cos(phi) + (r1*r2*a)**2)
    assert np.max(np.abs(s.power[f"{scene_ids(scene)[id(ring)]}:o3"] - closed)) < 1e-9


def test_an_open_output_port_is_reported_too():
    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    ring = scene.add(optodraw.MicroringResonator(center=(0, 0), label="ring"))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    s = spectrum(scene, start_nm=1549, stop_nm=1551, points=3)
    assert s.power[f"{scene_ids(scene)[id(ring)]}:o2"].shape == (3,)


def test_the_notes_say_what_is_model():
    s = spectrum(_ring_scene()[0], start_nm=1549, stop_nm=1551, points=3)
    assert any("group index" in n and "resonance position" in n for n in s.notes)
    assert sum("(model)" in n or "(default, model)" in n for n in s.notes) == 3


def test_a_spectrum_answers_for_a_part():
    scene, ring, pd = _ring_scene()
    s = spectrum(scene, start_nm=1549, stop_nm=1551, points=5)
    key = next(k for k in s.power if k.endswith(":o1") and k.startswith("onchipphotodetector"))
    assert s.of(pd, "o1") is s.power[key]
    with pytest.raises(KeyError, match="no light ends at"):
        s.of(ring, "o4")
