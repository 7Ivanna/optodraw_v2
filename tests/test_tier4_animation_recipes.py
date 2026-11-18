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
    def test_ftir_preset_builds_expected_step_kinds(self):
        scene = ftir_setup()
        beams = [c for c in scene.walk() if isinstance(c, BeamType)]
        combiner = next(c for c in scene.walk() if c.label == "G1")       # the splitter that recombines the arms
        assert len(beams) >= 2

        tl = animate_interference(scene, beams[0], beams[1], combiner, phase_steps=8)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 1
        assert kinds.count("trace") == 2
        assert kinds.count("pause") == 8
        assert len(tl._steps) == 11

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

    def test_phase_sweep_captions_include_constructive_and_destructive(self):
        scene = ftir_setup()
        beams = [c for c in scene.walk() if isinstance(c, BeamType)]
        combiner = next(c for c in scene.walk() if c.label == "G1")       # the splitter that recombines the arms

        tl = animate_interference(scene, beams[0], beams[1], combiner, phase_steps=8)
        phase_captions = [step.caption for step in tl._steps if step.kind == "pause"]

        assert any("Constructive" in caption for caption in phase_captions)
        assert any("Destructive" in caption for caption in phase_captions)

    def test_frame_states_non_empty(self):
        scene = ftir_setup()
        beams = [c for c in scene.walk() if isinstance(c, BeamType)]
        combiner = next(c for c in scene.walk() if c.label == "G1")       # the splitter that recombines the arms
        tl = animate_interference(scene, beams[0], beams[1], combiner, phase_steps=4)
        states = tl._to_frame_states()
        assert len(states) > 1


class TestAnimateResonanceScan:
    def test_ring_chip_preset_step_counts(self):
        built = build_ring_filter()
        scene, ring = built["scene"], built["ring"]

        tl = animate_resonance_scan(scene, ring, wavelength_steps=10)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 1
        assert kinds.count("trace") >= 1
        assert kinds.count("cavity_power") == 10
        assert len(tl._steps) == 12

    def test_wavelength_steps_controls_cavity_power_count(self):
        built = build_ring_filter()
        scene, ring = built["scene"], built["ring"]

        for steps in (1, 5, 12):
            tl = animate_resonance_scan(scene, ring, wavelength_steps=steps)
            assert _step_kinds(tl).count("cavity_power") == steps

    def test_cavity_power_captions_include_transmission(self):
        built = build_ring_filter()
        scene, ring = built["scene"], built["ring"]
        tl = animate_resonance_scan(scene, ring, wavelength_steps=3)

        power_captions = [step.caption for step in tl._steps if step.kind == "cavity_power"]
        assert len(power_captions) == 3
        assert all("T =" in caption for caption in power_captions)

    def test_resonance_scan_frame_states_include_highlights(self):
        built = build_ring_filter()
        scene, ring = built["scene"], built["ring"]
        tl = animate_resonance_scan(scene, ring, wavelength_steps=2)
        states = tl._to_frame_states()

        highlight_states = [state for state in states if state["highlight_levels"]]
        assert highlight_states


class TestAnimateFocus:
    def test_focus_scene_step_kinds(self):
        scene = Scene(platform="free_space")
        laser = scene.add(Laser(center=(-40, 0), wavelength=633, label="HeNe"))
        lens = scene.add(Lens(center=(0, 0), focal_length=50.0, label="L1"))
        scene.add(Beam(laser, lens, wavelength=633))

        tl = animate_focus(scene, lens)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 2
        assert kinds.count("trace") == 1
        assert kinds.count("cavity_power") >= 1

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

    def test_focus_without_beam_still_builds_timeline(self):
        scene = Scene(platform="free_space")
        lens = scene.add(Lens(center=(0, 0), focal_length=30.0, label="L1"))

        tl = animate_focus(scene, lens)
        assert _step_kinds(tl).count("cavity_power") >= 1

    def test_focus_frame_states_non_empty(self):
        scene = Scene(platform="free_space")
        lens = scene.add(Lens(center=(0, 0), focal_length=40.0, label="L1"))
        tl = animate_focus(scene, lens)
        assert len(tl._to_frame_states()) > 1
