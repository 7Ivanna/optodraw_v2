"""A physics number says where it comes from: measured, literature, simulated, or a model value."""

from __future__ import annotations

import copy
import pickle

import pytest
from conftest_models import _ring_scene

from optodraw import Scene, Source, Sourced
from optodraw.provenance import model_numbers, source_of


def test_a_sourced_number_is_its_value_and_keeps_its_source():
    s = Source("literature", "Bogaerts et al., Laser Photonics Rev. 6, 47 (2012)")
    k = Sourced(0.1, s)
    assert k == 0.1 and float(k) == 0.1 and source_of(k) is s and source_of(0.1) is None
    assert type(k * 2) is float and type(k + 1) is float


def test_a_source_kind_is_one_of_four():
    with pytest.raises(ValueError, match="measured, literature, simulated, model"):
        Source("guess")


def test_a_sourced_number_survives_copies():
    k = Sourced(4.2, Source("literature", "ref"))
    assert source_of(copy.deepcopy(k)) == k.source and source_of(pickle.loads(pickle.dumps(k))) == k.source
    assert copy.deepcopy(k) == 4.2


def test_a_ring_with_no_sources_names_its_three_model_numbers():
    scene, ring, _ = _ring_scene()                      # the ring's label is "ring"
    notes = model_numbers(scene)
    assert sum(n.startswith("ring:") for n in notes) == 3 and all("model" in n for n in notes)


def test_a_ring_with_all_three_sourced_names_none():
    scene, ring, _ = _ring_scene()
    for name, value in (("power_coupling", 0.1), ("round_trip_amplitude", 0.99), ("group_index", 4.2)):
        setattr(ring, name, Sourced(value, Source("literature", "ref")))
    assert not [n for n in model_numbers(scene) if n.startswith("ring:")]


def test_sources_survive_save_and_load():
    scene, ring, _ = _ring_scene()
    ring.power_coupling = Sourced(0.12, Source("simulated", "sha256:abc", "fieldrt 2D"))
    back = Scene.from_spec(scene.to_spec())
    k = next(p for p in back.walk() if p.component_type == "MicroringResonator").power_coupling
    assert k == 0.12 and source_of(k) == Source("simulated", "sha256:abc", "fieldrt 2D")


def test_an_add_drop_ring_also_names_its_drop_coupling():
    """An add-drop ring reads drop_power_coupling too: unnamed, a spectrum could rest on its default unseen."""

    from optodraw import MicroringResonator

    scene = Scene(platform="on_chip")
    scene.add(MicroringResonator(center=(0, 0), add_drop=True, label="ring"))
    notes = [n for n in model_numbers(scene) if n.startswith("ring:")]
    assert len(notes) == 4 and any("drop_power_coupling" in n for n in notes)
