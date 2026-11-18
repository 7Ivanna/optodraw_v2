"""Tests for the physics→animation compiler."""

from __future__ import annotations

from optodraw import MZI, MZM, Scene, Waveguide
from optodraw.animation import AnimationTimeline
from optodraw.components.onchip.rings import MicroringResonator, PNMicroringModulator
from optodraw.components.onchip.io import OnChipPhotodetector
from optodraw.core.physics_compiler import compile_physics_animation


def _step_kinds(tl: AnimationTimeline) -> list[str]:
    return [step.kind for step in tl._steps]


class TestCompilePhysicsAnimation:
    def test_returns_animation_timeline_with_render_metadata(self):
        scene = Scene(platform="on_chip")
        mzi = scene.add(MZI(center=(0, 0)))
        mzi._id = "mzi"

        tl = compile_physics_animation(scene, fps=24, duration_s=3.5)

        assert isinstance(tl, AnimationTimeline)
        assert tl.fps == 24
        assert tl.duration_s == 3.5
        assert len(tl._steps) > 0

    def test_mzi_scene_dispatches_interference_recipe(self):
        scene = Scene(platform="on_chip")
        mzi = scene.add(MZI(center=(0, 0)))
        mzi._id = "mzi"

        tl = compile_physics_animation(scene)
        kinds = _step_kinds(tl)

        assert kinds.count("show") >= 1
        assert kinds.count("pause") >= 1

    def test_ring_scene_dispatches_resonance_scan(self):
        scene = Scene(platform="on_chip")
        ring = scene.add(MicroringResonator(center=(0, 0), ring_radius=8.0))
        ring._id = "ring"

        tl = compile_physics_animation(scene)
        kinds = _step_kinds(tl)

        assert kinds.count("show") >= 1
        assert "cavity_power" in kinds

    def test_mzm_scene_dispatches_mzm_mechanism(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(drive_style="gsg"))
        mzm._id = "mzm"

        tl = compile_physics_animation(scene)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 1
        assert kinds.count("cavity_power") >= 1

    def test_pn_ring_dispatches_pn_modulation(self):
        scene = Scene(platform="on_chip")
        ring = scene.add(PNMicroringModulator(ring_radius=8.0))
        ring._id = "pn_ring"

        tl = compile_physics_animation(scene)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 1
        assert kinds.count("cavity_power") >= 1

    def test_photodetector_dispatches_absorption(self):
        scene = Scene(platform="on_chip")
        pd = scene.add(OnChipPhotodetector(center=(0, 0)))
        pd._id = "pd"

        tl = compile_physics_animation(scene, include_guided_paths=False)
        kinds = _step_kinds(tl)

        assert kinds.count("show") == 1
        assert "wave_travel" in kinds or "cavity_power" in kinds

    def test_multi_component_scene_merges_sequences(self):
        scene = Scene(platform="on_chip")
        mzi = scene.add(MZI(center=(-20, 0)))
        ring = scene.add(MicroringResonator(center=(20, 0), ring_radius=8.0))
        mzi._id = "mzi"
        ring._id = "ring"

        tl = compile_physics_animation(scene)
        kinds = _step_kinds(tl)

        assert len(tl._steps) > 5
        assert kinds.count("show") >= 2
        assert "cavity_power" in kinds
        assert kinds.count("pause") >= 1

    def test_route_only_scene_uses_wave_travel_fallback(self):
        scene = Scene(platform="on_chip")
        wg_in = scene.add(Waveguide(center=(-15, 0), length=20.0))
        wg_out = scene.add(Waveguide(center=(15, 0), length=20.0))
        scene.route((wg_in, "o2"), (wg_out, "o1"))

        tl = compile_physics_animation(scene)
        kinds = _step_kinds(tl)

        assert kinds == ["wave_travel"]
        assert tl._steps[0].caption.startswith("Guided-mode propagation")

    def test_scene_wrapper_delegates_to_compiler(self):
        scene = Scene(platform="on_chip")
        ring = scene.add(MicroringResonator(ring_radius=8.0))
        ring._id = "ring"

        tl = scene.compile_physics_animation(fps=12, duration_s=2.0)

        assert isinstance(tl, AnimationTimeline)
        assert tl.fps == 12
        assert tl.duration_s == 2.0
        assert len(tl._steps) > 0

    def test_frame_states_non_empty_for_compiled_timeline(self):
        scene = Scene(platform="on_chip")
        mzm = scene.add(MZM(label="MZM"))
        mzm._id = "mzm"

        tl = compile_physics_animation(scene)
        frames = tl._to_frame_states()

        assert len(frames) > 1
