"""Tests for Tier 4 animation recipe helpers."""

from __future__ import annotations

from optodraw import (
    Beam,
    Lens,
    Laser,
    Scene,
    animate_focus,
    animate_interference,
    animate_resonance_scan,
)
from optodraw.core.beam import Beam as BeamType
from optodraw.layout import build_ring_filter
from optodraw.presets import ftir_setup


def _step_kinds(tl) -> list[str]:
    return [step.kind for step in tl._steps]


class TestAnimateInterference:

    def test_opening_caption_adds_pause(self):
        scene = ftir_setup()
        beams = [c for c in scene.walk() if isinstance(c, BeamType)]
        combiner = next(c for c in scene.walk() if c.label == "G1")       # the splitter that recombines the arms

        tl = animate_interference(
            scene,
            beams[0],
            beams[1],
            combiner,
            phase_steps=4,
            caption="Michelson interference lesson",
        )
        kinds = _step_kinds(tl)

        assert kinds[0] == "pause"
        assert tl._steps[0].caption == "Michelson interference lesson"
        assert kinds.count("pause") == 5


class TestAnimateResonanceScan:

    def test_wavelength_steps_controls_cavity_power_count(self):
        built = build_ring_filter()
        scene, ring = built["scene"], built["ring"]

        for steps in (1, 5, 12):
            tl = animate_resonance_scan(scene, ring, wavelength_steps=steps)
            assert _step_kinds(tl).count("cavity_power") == steps


class TestAnimateFocus:

    def test_focus_captions_reference_waist_metadata(self):
        scene = Scene(platform="free_space")
        laser = scene.add(Laser(center=(-40, 0), wavelength=633, label="HeNe"))
        lens = scene.add(Lens(center=(0, 0), focal_length=50.0, label="L1"))
        scene.add(Beam(laser, lens, wavelength=633))

        tl = animate_focus(scene, lens, caption="Gaussian focusing")
        waist_captions = [step.caption for step in tl._steps if step.kind == "cavity_power"]

        assert tl._steps[0].kind == "pause"
        assert waist_captions
        assert all("waist" in caption.lower() for caption in waist_captions)


    def test_focus_frame_states_non_empty(self):
        scene = Scene(platform="free_space")
        lens = scene.add(Lens(center=(0, 0), focal_length=40.0, label="L1"))
        tl = animate_focus(scene, lens)
        assert len(tl._to_frame_states()) > 1
