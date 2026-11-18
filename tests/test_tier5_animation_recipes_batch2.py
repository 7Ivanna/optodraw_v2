"""Tests for Tier 5 animation recipe helpers (batch 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw import (
    Grating,
    Group,
    MZM,
    Prism,
    Scene,
    animate_dispersion,
    animate_layer_stack,
    animate_modulation,
    build_modulator_drive_chain,
)
from optodraw.core.interferometer import trace_mzm_transfer


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_GDS = REPO_ROOT / "examples" / "assets" / "demo_mask.gds"


def _step_kinds(tl) -> list[str]:
    return [step.kind for step in tl._steps]


class TestAnimateModulation:
    def test_modulator_drive_chain_builds_voltage_sweep(self):
        recipe = build_modulator_drive_chain(drive_style="gsg")
        scene = recipe["scene"]
        mzm = recipe["mzm"]

        tl = animate_modulation(scene, mzm, voltage_steps=8)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 1
        assert kinds.count("trace") >= 1
        assert kinds.count("cavity_power") == 8

    def test_voltage_captions_reference_transfer_stub(self):
        mzm = MZM(center=(0, 0), label="MZM")
        scene = Scene(platform="on_chip")
        scene.add(mzm)

        tl = animate_modulation(scene, mzm, voltage_steps=4, Vpi=4.0)
        power_captions = [step.caption for step in tl._steps if step.kind == "cavity_power"]

        assert len(power_captions) == 4
        assert all("V =" in caption and "T ≈" in caption for caption in power_captions)
        at_zero = trace_mzm_transfer(mzm, drive_voltage=0.0, Vpi=4.0)
        assert f"T ≈ {at_zero['through_power']:.2f}" in power_captions[0]

    def test_opening_caption_adds_pause(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(label="MZM"))

        tl = animate_modulation(
            scene,
            mzm,
            voltage_steps=3,
            caption="Electro-optic modulation",
        )
        assert _step_kinds(tl)[0] == "pause"
        assert tl._steps[0].caption == "Electro-optic modulation"

    def test_modulation_frame_states_non_empty(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(label="MZM"))
        tl = animate_modulation(scene, mzm, voltage_steps=3)
        assert len(tl._to_frame_states()) > 1


class TestAnimateLayerStack:
    def test_scene_stub_groups_reveal_bottom_to_top(self):
        scene = Scene(platform="on_chip", title="Stack stub")
        tl = animate_layer_stack(scene, caption="Layer stack lesson")
        kinds = _step_kinds(tl)

        assert kinds[0] == "pause"
        assert kinds.count("show") == 5
        assert kinds[-1] == "pause"
        assert "5 layers" in tl._steps[-1].caption

    def test_existing_scene_groups_are_used(self):
        scene = Scene(platform="on_chip")
        substrate = scene.add(Group(label="Substrate"))
        waveguide = scene.add(Group(label="Waveguide"))
        metal = scene.add(Group(label="Metal"))

        tl = animate_layer_stack(scene)
        show_captions = [step.caption for step in tl._steps if step.kind == "show"]

        assert len(show_captions) == 3
        assert show_captions == ["Substrate", "Waveguide", "Metal"]
        assert substrate in [step.component for step in tl._steps if step.kind == "show"]

    @pytest.mark.skipif(not DEMO_GDS.exists(), reason="demo GDS asset missing")
    def test_gds_layout_reveals_sorted_layers(self):
        pytest.importorskip("gdstk")
        from optodraw import load_gds_layout

        layout = load_gds_layout(DEMO_GDS)
        tl = animate_layer_stack(layout)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == len(layout.layer_records)
        show_captions = [step.caption for step in tl._steps if step.kind == "show"]
        assert all("z =" in caption for caption in show_captions)

    @pytest.mark.skipif(not DEMO_GDS.exists(), reason="demo GDS asset missing")
    def test_gds_path_loads_when_extra_available(self):
        pytest.importorskip("gdstk")
        tl = animate_layer_stack(DEMO_GDS)
        assert _step_kinds(tl).count("show") >= 1


class TestAnimateDispersion:
    def test_grating_fan_step_counts(self):
        scene = Scene(platform="free_space")
        grating = scene.add(Grating(center=(0, 0), pitch=1.0, label="Grating"))

        tl = animate_dispersion(scene, grating, wavelength_steps=6)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 1
        assert kinds.count("cavity_power") == 6
        assert kinds[-1] == "pause"
        assert "Angular spread" in tl._steps[-1].caption

    def test_prism_captions_include_wavelength_and_angle(self):
        scene = Scene(platform="free_space")
        prism = scene.add(Prism(center=(0, 0), refractive_index=1.515, label="Prism"))

        tl = animate_dispersion(scene, prism, wavelength_steps=4)
        fan_captions = [step.caption for step in tl._steps if step.kind == "cavity_power"]

        assert len(fan_captions) == 4
        assert all("λ =" in caption and "θ ≈" in caption for caption in fan_captions)

    def test_wavelength_steps_controls_fan_count(self):
        scene = Scene(platform="free_space")
        grating = scene.add(Grating(center=(0, 0), pitch=0.8))

        for steps in (1, 5, 10):
            tl = animate_dispersion(scene, grating, wavelength_steps=steps)
            assert _step_kinds(tl).count("cavity_power") == steps

    def test_dispersion_frame_states_non_empty(self):
        scene = Scene(platform="free_space")
        grating = scene.add(Grating(center=(0, 0), pitch=1.0))
        tl = animate_dispersion(scene, grating, wavelength_steps=3)
        assert len(tl._to_frame_states()) > 1
