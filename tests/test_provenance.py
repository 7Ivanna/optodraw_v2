"""A physics number says where it comes from: measured, literature, simulated, or a model value."""

from __future__ import annotations


import pytest
from conftest_models import _ring_scene

from optodraw import Scene, Source, Sourced
from optodraw.provenance import source_of


def test_a_source_kind_is_one_of_four():
    with pytest.raises(ValueError, match="measured, literature, simulated, model"):
        Source("guess")


def test_sources_survive_save_and_load():
    scene, ring, _ = _ring_scene()
    ring.power_coupling = Sourced(0.12, Source("simulated", "sha256:abc", "fieldrt 2D"))
    back = Scene.from_spec(scene.to_spec())
    k = next(p for p in back.walk() if p.component_type == "MicroringResonator").power_coupling
    assert k == 0.12 and source_of(k) == Source("simulated", "sha256:abc", "fieldrt 2D")


