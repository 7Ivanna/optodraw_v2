"""Tests for MZM mechanism and ring coupling animation recipes."""

from __future__ import annotations

from optodraw import MZM, Scene, animate_mzm_mechanism, animate_ring_coupling
from optodraw.layout.chip_builder import build_ring_filter


def _step_kinds(tl) -> list[str]:
    return [step.kind for step in tl._steps]


class TestAnimateMzmMechanism:

    def test_opening_caption_adds_pause(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(label="MZM"))
        tl = animate_mzm_mechanism(scene, mzm, phase_steps=3, caption="MZM mechanism")
        assert _step_kinds(tl)[0] == "pause"
        assert tl._steps[0].caption == "MZM mechanism"


class TestAnimateRingCoupling:

    def test_ring_chip_coupling_captions(self):
        built = build_ring_filter()
        scene, ring = built["scene"], built["ring"]
        tl = animate_ring_coupling(scene, ring, coupling_steps=3)
        power_captions = [step.caption for step in tl._steps if step.kind == "cavity_power"]
        assert len(power_captions) == 3
        assert all("T =" in caption for caption in power_captions)
