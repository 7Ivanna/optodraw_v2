"""Datasheet numbers on the parts: saved with the scene, plain or sourced; a laser's power sets its field."""

from __future__ import annotations

import json

import pytest

import optodraw
from optodraw import Scene, Source, Sourced
from optodraw.animation_engine import build_graph
from optodraw.animation_engine.solver import steady_state
from optodraw.provenance import source_of

DETECTOR = ("responsivity_a_per_w", "dark_current_a", "bandwidth_hz")
LASER = ("power_mw", "threshold_a", "slope_w_per_a")
FIELDS = {
    "Photodiode": DETECTOR, "OnChipPhotodetector": DETECTOR, "AmplifiedPhotodetector": DETECTOR + ("gain_ohm",),
    "TIABlock": ("gain_ohm", "bandwidth_hz"), "Amplifier": ("gain", "bandwidth_hz"),
    "ADCBlock": ("sample_rate_hz", "full_scale_v"), "DAC": ("sample_rate_hz", "full_scale_v"),
    "LaserDriver": ("bias_a", "gain_a_per_v"), "Laser": LASER, "OnChipLaser": LASER,
    "MicroringResonator": ("heater_resistance_ohm",),
}
CASES = [(kind, name) for kind, names in FIELDS.items() for name in names]


def _spec(part) -> dict:
    scene = Scene()
    scene.add(part)
    return json.loads(json.dumps(scene.to_spec()))


def _saved(part):
    back = Scene.from_spec(_spec(part))
    return next(p for p in back.walk() if p.component_type == part.component_type)


@pytest.mark.parametrize("kind,name", CASES)
def test_a_plain_number_survives_save_and_load(kind, name):
    back = getattr(_saved(getattr(optodraw, kind)(**{name: 2.5})), name)
    assert back == 2.5 and source_of(back) is None


@pytest.mark.parametrize("kind,name", CASES)
def test_a_sourced_number_keeps_its_source(kind, name):
    source = Source("measured", "datasheet, table 2")
    back = getattr(_saved(getattr(optodraw, kind)(**{name: Sourced(2.5, source)})), name)
    assert back == 2.5 and source_of(back) == source


@pytest.mark.parametrize("kind", sorted(FIELDS))
def test_a_part_with_no_new_number_saves_no_new_key(kind):
    part = getattr(optodraw, kind)()
    assert all(getattr(part, name) is None for name in FIELDS[kind])
    saved = _spec(part)["components"][0]
    assert not set(FIELDS[kind]) & set(saved) and "sources" not in saved


def _detected(params=None, **laser):
    scene = Scene(width=120, height=40, platform="free_space")
    source = scene.add(optodraw.Laser(center=(-40, 0), wavelength=633, **laser))
    detector = scene.add(optodraw.Photodiode(center=(40, 0)))
    scene.add(optodraw.Beam.through(source, detector, wavelength=633))
    result = steady_state(build_graph(scene), params, floor=0.0)
    return sum(record["power"] for record in result.absorbed if record["part"] == "photodiode1")


def test_power_mw_sets_the_field_at_a_detector():
    assert _detected() == pytest.approx(1.0, rel=1e-12)                        # no number: 1 mW, as before
    assert _detected(power_mw=4.0) == pytest.approx(4.0 * _detected(), rel=1e-12)   # twice the amplitude
    assert _detected({"power:laser1": 9.0}, power_mw=4.0) == pytest.approx(9.0, rel=1e-12)
