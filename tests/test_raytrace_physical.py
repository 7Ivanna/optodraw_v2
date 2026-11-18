"""Physical-mode ray tracing: interface segments, hits/misses, focus, live re-trace.

Physical mode (``trace_branched(..., mode="physical")``) intersects rays with
each optic's real interface segments instead of snapping to component centers:
apertures clip, misses propagate straight, off-axis lens hits bend by hit
height, curved mirrors focus at f, splitters branch with their set ratios,
dichroics pass/reflect by wavelength, and detectors absorb. The editor session
re-traces every ``traced_from`` beam after each spec mutation, so traces stay
live while components move.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from optodraw import Scene  # noqa: E402
from optodraw.app.server import create_app  # noqa: E402
from optodraw.components.devices import Laser  # noqa: E402

RAYS = Laser.rays  # default bundle size — tests track the class default
from optodraw.components.optics import (  # noqa: E402
    PBS,
    BeamSplitter,
    ConcaveMirror,
    ConvexMirror,
    DichroicMirror,
    Lens,
    Mirror,
)
from optodraw.core.raytrace import (  # noqa: E402
    _default_interfaces,
    trace_branched,
    trace_bundle,
)


def _trace(scene, source, **kwargs):
    kwargs.setdefault("mode", "physical")
    return trace_branched(scene, (source, "out"), **kwargs)


class TestDefaultInterfaces:

    def test_concave_mirror_focal_from_explicit_setting(self):
        (iface,) = _default_interfaces(ConcaveMirror(center=(0, 0), angle=0, focal_length=25.0))
        assert iface.kind == "mirror" and iface.efl == pytest.approx(25.0)

    def test_convex_mirror_focal_is_negative(self):
        (iface,) = _default_interfaces(ConvexMirror(center=(0, 0), angle=0, focal_length=25.0))
        assert iface.efl == pytest.approx(-25.0)

    def test_curved_mirror_focal_derives_from_sagitta(self):
        # R = (a² + s²) / 2s with a = aperture/2 = 5, s = 0.5 → R = 25.25, f = 12.625
        (iface,) = _default_interfaces(ConcaveMirror(center=(0, 0), angle=0, aperture=10.0, curvature_depth=0.5))
        assert iface.efl == pytest.approx(12.625)


    def test_pbs_cube_coating_is_diagonal(self):
        (iface,) = _default_interfaces(PBS(center=(0, 0), angle=0))
        assert iface.kind == "beam_splitter" and iface.polarizing
        assert iface.p1[0] == pytest.approx(iface.p1[1])  # 45° diagonal in local frame
        assert iface.p2[0] == pytest.approx(iface.p2[1])


    def test_lens_without_focal_falls_back_to_schematic(self):
        (iface,) = _default_interfaces(Lens(center=(0, 0), angle=0, focal_length=None))
        assert iface.kind == "schematic"

    def test_laser_declares_no_surfaces(self):
        assert _default_interfaces(Laser(center=(0, 0), angle=0)) == []


class TestPhysicalHitsAndMisses:


    def test_schematic_mode_snaps_where_physical_misses(self):
        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        scene.add(Mirror(center=(0, 30), angle=135))
        (schematic,) = trace_branched(scene, (laser, "out"), mode="schematic")
        (physical,) = _trace(scene, laser)
        assert schematic.direction_deg == pytest.approx(90.0, abs=1e-6)  # snapped + folded
        assert physical.direction_deg == pytest.approx(0.0)  # physically missed


    def test_a_cryostat_absorbs_instead_of_leaking_out_the_far_wall(self):
        from optodraw.components.samples import Cryostat

        scene = Scene()
        laser = scene.add(Laser(center=(-60, 0), angle=0))
        cryo = scene.add(Cryostat(center=(20, 0), angle=180))
        (result,) = _trace(scene, laser)
        assert result.points[-1].x == pytest.approx(cryo.world_port("in").center.x, abs=1e-6)


    def test_an_objective_brings_a_collimated_beam_to_a_focus(self):
        # An objective is a strong lens. It used to be invisible to the tracer,
        # so a bundle crossed a 100x objective without converging at all.
        from optodraw.components.optics import Objective
        from optodraw.core.raytrace import trace_bundle

        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        objective = scene.add(Objective(center=(0, 0), angle=0, magnification=10))
        results = trace_bundle(scene, (laser, "out"), rays=5, width=6.0, mode="physical",
                               exit_length=objective.working_distance * 2.2)
        crossing = [r for r in results if abs(float(getattr(r, "offset", 0.0))) > 1e-9]
        assert crossing, "the bundle has no off-axis rays to converge"
        for ray in crossing:
            # every off-axis ray leaves bent toward the axis
            assert ray.direction_deg != pytest.approx(0.0, abs=1e-6)
        # and the marginal rays cross the axis at the working distance
        focus = objective.world_port("out").center.x + objective.working_distance
        edge = max(results, key=lambda r: abs(float(getattr(r, "offset", 0.0))))
        crossings = [
            a.x + (b.x - a.x) * (0.0 - a.y) / (b.y - a.y)
            for a, b in zip(edge.points, edge.points[1:]) if (a.y > 0) != (b.y > 0)
        ]
        assert crossings, "the marginal ray never crosses the axis"
        assert crossings[0] == pytest.approx(focus, rel=0.25)

    def test_a_retroreflector_sends_the_beam_back(self):
        from optodraw.components.optics import Retroreflector

        scene = Scene()
        laser = scene.add(Laser(center=(-40, 6), angle=0))
        scene.add(Retroreflector(center=(0, 0), angle=180))
        (result,) = _trace(scene, laser)
        assert result.direction_deg == pytest.approx(180.0, abs=1e-6)
        # a corner cube returns the ray on the far side of its apex, so the
        # return leg is visible beside the input instead of drawn on top of it
        assert result.points[-1].y == pytest.approx(-6.0, abs=1e-6)
        assert result.points[-1].x < 0.0  # heading back the way it came

    def test_a_pentaprism_turns_the_beam_and_says_where_it_leaves(self):
        # A pentaprism deviates by a constant 90 degrees — that constancy is the
        # whole reason to buy one instead of a mirror. Its ports said as much
        # all along; a traced ray went straight through it regardless.
        from optodraw.components.optics import Pentaprism

        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        prism = scene.add(Pentaprism(center=(0, 0), angle=0))
        (result,) = _trace(scene, laser)
        assert result.direction_deg % 360 == pytest.approx(270.0, abs=1e-6)
        assert prism.ports()["out"].orientation_deg % 360 == pytest.approx(270.0)
        assert result.points[-1].y < result.points[0].y  # it leaves downward


    def test_a_longpass_filter_blocks_what_it_is_there_to_block(self):
        # The reason a filter is in the drawing at all: it stops the pump and
        # passes the signal. Without an edge wavelength it is a piece of glass,
        # so both colours used to sail through it into the spectrometer.
        from optodraw.components.optics import Filter

        for wavelength, blocked in ((532.0, True), (650.0, False)):
            scene = Scene()
            laser = scene.add(Laser(center=(-40, 0), angle=0, wavelength=wavelength))
            scene.add(Filter(center=(0, 0), angle=0, cutoff_wavelength=600, pass_band="longpass"))
            (result,) = _trace(scene, laser, wavelength_nm=wavelength)
            if blocked:
                assert result.points[-1].x == pytest.approx(0.0, abs=1e-6)
            else:
                assert result.points[-1].x > 10.0


    def test_a_filter_with_no_edge_still_just_passes_light(self):
        # Most filters in a drawing are unspecified glass in the signal path;
        # they must not start eating beams the moment this feature lands.
        from optodraw.components.optics import Filter

        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        scene.add(Filter(center=(0, 0), angle=0))
        (result,) = _trace(scene, laser, exit_length=60.0)
        assert result.points[-1].x > 10.0  # straight past the glass

    def test_ring_cavity_respects_segment_budget(self):
        scene = Scene()
        laser = scene.add(Laser(center=(-10, 0), angle=0))
        scene.add(Mirror(center=(0, 0), angle=135))
        scene.add(Mirror(center=(0, 20), angle=45))
        scene.add(Mirror(center=(-20, 20), angle=135))
        scene.add(Mirror(center=(-20, 0), angle=45))
        results = _trace(scene, laser, max_segments=16)
        assert len(results) == 1
        assert len(results[0].points) <= 18  # 16 bounces + start + exit — no hang


class TestSplittersAndDichroics:
    def test_split_ratio_carries_into_branch_powers(self):
        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        scene.add(BeamSplitter(center=(0, 0), angle=135, transmission=70.0))
        results = _trace(scene, laser)
        by_dir = {round(r.direction_deg): r.power for r in results}
        assert by_dir[0] == pytest.approx(0.7)
        assert by_dir[90] == pytest.approx(0.3)

    def test_dichroic_plate_longpass_routes_by_wavelength(self):
        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        scene.add(BeamSplitter(center=(0, 0), angle=135, dichroic=True, cutoff_wavelength=600.0))
        (passed,) = _trace(scene, laser, wavelength_nm=633.0)
        (reflected,) = _trace(scene, laser, wavelength_nm=450.0)
        assert passed.direction_deg == pytest.approx(0.0)
        assert reflected.direction_deg == pytest.approx(90.0, abs=1e-6)


class TestDivergentSources:
    """Not every source is collimated: a lamp or a fiber tip fans out from its
    face, and a lens one focal length away turns that fan back into a beam."""

    def _fan(self, divergence, *, width=2.0, rays=9, lens_at_f=None):
        scene = Scene(width=260, height=160)
        laser = Laser(center=(-40, 0), divergence_deg=divergence, beam_width=width, rays=rays)
        scene.add(laser)
        if lens_at_f:  # place it a focal length from the EMISSION port, not the body
            emit_x = laser.transform.position.x + laser.ports()["out"].center.x
            scene.add(Lens(center=(emit_x + lens_at_f, 0), focal_length=lens_at_f, aperture=40.0))
        return trace_bundle(
            scene, (laser, "out"), rays=rays, width=width,
            divergence_deg=divergence, exit_length=80, mode="physical",
        )


class TestBeamEnvelope:
    """The beam cone: one closed outline through a bundle's marginal rays, filled
    in 2D figures. Off by default — it is a drawing choice, not physics."""

    def _scene(self, envelope):
        from optodraw.app.session import EditorSession, empty_scene_spec

        spec = empty_scene_spec()
        spec["components"] = [
            {"type": "Laser", "id": "src", "center": [-40, 0], "rays": 7,
             "beam_width": 4.0, "show_envelope": envelope},
            {"type": "Lens", "id": "lens", "center": [0, 0], "focal_length": 24.0, "aperture": 20.0},
        ]
        session = EditorSession(spec)
        session.trace_from("src")
        return session.spec["beams"]


    def test_envelope_is_skipped_by_the_3d_and_tikz_renderers(self):
        from optodraw.app.session import EditorSession

        session = EditorSession(empty_spec_with_envelope())
        session.trace_from("src")
        scene = session.scene()
        beams = [b for b in scene.walk() if getattr(b, "envelope", False)]
        assert len(beams) == 1  # the cone IS in the scene...

        items: list = []
        from optodraw.renderers.threejs_renderer import ThreeJsRenderer

        renderer = ThreeJsRenderer(scene)
        renderer._walk(scene.root, items)
        assert len([i for i in items if i.get("type") == "beam"]) == 7  # ... but not in 3D

        from optodraw.renderers.tikz_renderer import TikzRenderer

        assert TikzRenderer(scene)._render_node(beams[0]) == []


def empty_spec_with_envelope():
    from optodraw.app.session import empty_scene_spec

    spec = empty_scene_spec()
    spec["components"] = [
        {"type": "Laser", "id": "src", "center": [-40, 0], "rays": 7, "beam_width": 4.0, "show_envelope": True},
    ]
    return spec


class TestRefractingBodies:
    """Prisms and gratings as REAL surfaces: two-face refraction with dispersion,
    and the grating equation at any incidence (the old models were stubs — one
    face for a prism, normal incidence only for a grating)."""

    def _prism_scene(self, **kwargs):
        from optodraw.components.optics import Prism

        scene = Scene(width=240, height=140)
        laser = Laser(center=(-40, 0))
        scene.add(laser)
        # rotated off normal incidence — a beam entering a 60 deg prism square-on
        # hits the exit face past the critical angle and totally internally reflects
        kwargs.setdefault("angle", 50.0)
        scene.add(Prism(center=(10, 0), **kwargs))
        return scene, laser

    def _out_deg(self, scene, laser, nm):
        results = trace_branched(scene, (laser, "out"), mode="physical", wavelength_nm=nm, exit_length=60)
        return results[0].direction_deg

    def test_prism_deviates_the_beam(self):
        scene, laser = self._prism_scene()
        assert abs(self._out_deg(scene, laser, 589.0)) > 1.0  # two surfaces bend it


    def test_grating_follows_the_grating_equation_off_normal(self):
        # sin(theta_out) = sin(theta_in) + m*lambda/pitch, measured from the normal
        from optodraw.components.optics import Grating

        scene = Scene(width=240, height=140)
        laser = Laser(center=(-40, 0))
        scene.add(laser)
        scene.add(Grating(center=(10, 0), angle=20.0, pitch=2.0, aperture=40.0))
        (result,) = trace_branched(scene, (laser, "out"), mode="physical", wavelength_nm=600.0, exit_length=60)
        expected = math.degrees(math.asin(math.sin(math.radians(-20.0)) + 0.6 / 2.0)) + 20.0
        assert result.direction_deg == pytest.approx(expected, abs=0.5)

    def test_evanescent_order_passes_straight_through(self):
        from optodraw.components.optics import Grating

        scene = Scene(width=240, height=140)
        laser = Laser(center=(-40, 0))
        scene.add(laser)
        scene.add(Grating(center=(10, 0), pitch=0.3, aperture=40.0))  # lambda/pitch > 2
        (result,) = trace_branched(scene, (laser, "out"), mode="physical", wavelength_nm=633.0, exit_length=60)
        assert result.direction_deg == pytest.approx(0.0, abs=1e-6)


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    test_client = TestClient(app)
    test_client.post("/api/scene/new", json={})
    return test_client


class TestLiveRetrace:
    def _setup_fold(self, client: TestClient) -> tuple[str, str, str]:
        laser = client.post("/api/component", json={"name": "Laser", "params": {"center": [-40, 0]}}).json()["id"]
        mirror = client.post(
            "/api/component", json={"name": "Mirror", "params": {"center": [20, 0], "angle": 135}}
        ).json()["id"]
        beam = client.post("/api/trace", json={"source_id": laser}).json()["id"]
        return laser, mirror, beam

    def _traced_beams(self, client: TestClient) -> list[dict]:
        """Chief rays only — marginal bundle rays are visual detail."""
        spec = client.get("/api/scene").json()
        return [b for b in spec.get("beams", []) if b.get("traced_from") and not b.get("ray")]

    def _all_traced(self, client: TestClient) -> list[dict]:
        spec = client.get("/api/scene").json()
        return [b for b in spec.get("beams", []) if b.get("traced_from")]


    def test_preset_scenes_trace_as_bundles(self, client: TestClient):
        client.post("/api/scene/preset", json={"name": "confocal_pl"})
        spec = client.get("/api/scene").json()
        assert spec["trace_mode"] == "physical"
        source = next(c for c in spec["components"] if c["type"] == "Laser")
        client.post("/api/trace", json={"source_id": source["id"]})
        assert len(self._all_traced(client)) > 1  # branches × bundle rays


class TestBundles:


    def test_bundle_degenerates_in_schematic_mode(self):
        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        results = trace_bundle(scene, (laser, "out"), rays=7, width=3.0, mode="schematic")
        assert len(results) == 1 and results[0].ray == 0

    def test_trace_mode_semantics(self):
        """Trace = light on; delete any ray = light off; lit scenes recruit new sources."""

        from fastapi.testclient import TestClient as _TC

        tc = _TC(create_app())
        tc.post("/api/scene/new", json={})

        def traced():
            spec = tc.get("/api/scene").json()
            return [b for b in spec["beams"] if b.get("traced_from")]

        # dark scene: placing a source does NOT auto-emit (manual Trace is the switch)
        laser = tc.post("/api/component", json={"name": "Laser", "params": {"center": [-40, 0]}}).json()["id"]
        assert traced() == []

        # light on: bundle appears, chief carries the laser's own wavelength
        tc.post("/api/trace", json={"source_id": laser})
        bundle = traced()
        assert len(bundle) == RAYS
        chief = next(b for b in bundle if not b.get("ray"))
        assert chief["wavelength"] == pytest.approx(532.0)
        assert len({b["width"] for b in bundle}) == 1  # uniform fan, no fat chief

        # a source placed into a LIT scene joins in immediately
        tc.post("/api/component", json={"name": "Laser", "params": {"center": [-40, 30]}})
        assert len(traced()) == 2 * RAYS

        # deleting ANY marginal ray switches that source's whole bundle off...
        victim = next(b for b in traced() if b.get("traced_from") == laser and b.get("ray"))
        tc.delete(f"/api/component/{victim['id']}")
        remaining = traced()
        assert all(b.get("traced_from") != laser for b in remaining)
        assert len(remaining) == RAYS  # the second source still emits

        # ...and moving an optic afterwards must NOT resurrect the dead bundle
        mirror = tc.post("/api/component", json={"name": "Mirror", "params": {"center": [20, 0], "angle": 135}}).json()["id"]
        tc.post(f"/api/component/{mirror}/move", json={"center": [30, 0], "angle": 135})
        assert all(b.get("traced_from") != laser for b in traced())


class TestBundleKnobsAndOneSidedDichroic:
    def test_laser_bundle_knobs_flow_into_the_spec(self):
        from fastapi.testclient import TestClient as _TC

        tc = _TC(create_app())
        tc.post("/api/scene/new", json={})
        laser = tc.post("/api/component", json={
            "name": "Laser",
            "params": {"center": [-40, 0], "rays": 4, "ray_width": 0.8, "beam_color": "#ff00aa", "beam_width": 2.5},
        }).json()["id"]
        payload = tc.post("/api/trace", json={"source_id": laser}).json()
        traced = [b for b in payload["spec"]["beams"] if b.get("traced_from")]
        assert len(traced) == 4
        assert all(b["width"] == pytest.approx(0.8) for b in traced)
        assert all(b["color"] == "#ff00aa" for b in traced)
        assert 'stroke="#ff00aa"' in payload["svg"]  # the override reaches the drawing


    def test_dichroic_back_face_just_transmits(self):
        # Coating is on the local +x face. At angle=0 it faces AWAY from a beam
        # arriving from the left → back-face hit → substrate pass at ANY wavelength.
        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        scene.add(DichroicMirror(center=(0, 0), angle=0, cutoff_wavelength=600.0))
        for wavelength in (450.0, 633.0):
            (result,) = _trace(scene, laser, wavelength_nm=wavelength)
            assert result.direction_deg == pytest.approx(0.0)
        # Flipped 180° the coating faces the beam → normal dichroic routing
        scene2 = Scene()
        laser2 = scene2.add(Laser(center=(-40, 0), angle=0))
        scene2.add(DichroicMirror(center=(0, 0), angle=180, cutoff_wavelength=600.0))
        (reflected,) = _trace(scene2, laser2, wavelength_nm=450.0)
        assert abs(_normalized(reflected.direction_deg)) == pytest.approx(180.0, abs=1e-6)


def _normalized(angle):
    angle = angle % 360.0
    return angle - 360.0 if angle > 180.0 else angle


class TestPointFocusAndVerticalChannel:
    def _crossing(self, result, x):
        a, b = result.points[-2:]
        t = (x - a.x) / (b.x - a.x)
        return a.y + t * (b.y - a.y), a.z + t * (b.z - a.z)


    def test_cylindrical_lens_makes_a_line_focus(self):
        from optodraw.components.optics import CylindricalLens

        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        scene.add(CylindricalLens(center=(0, 0), angle=0, focal_length=20.0))  # axis y: in-plane only
        results = trace_bundle(scene, (laser, "out"), rays=13, width=1.6, mode="physical", exit_length=40.0)
        max_z = 0.0
        for r in results:
            y, z = self._crossing(r, 20.0)
            assert y == pytest.approx(0.0, abs=1e-3)  # focuses in the plane
            max_z = max(max_z, abs(z))
        assert max_z == pytest.approx(0.8, abs=1e-3)  # vertical spread untouched (line focus)


class TestApertures:
    def test_iris_passes_the_opening_and_blocks_the_blades(self):
        from optodraw.components.optics import Iris

        # opening radius 2.5: a ray at +2 clears it, a ray at +4 hits the blades
        for offset, passes in ((0.0, True), (2.0, True), (4.0, False)):
            scene = Scene()
            laser = scene.add(Laser(center=(-40, offset), angle=0))
            scene.add(Iris(center=(0, 0), angle=0, aperture_diameter=5.0, outer_diameter=12.0))
            (result,) = _trace(scene, laser)
            if passes:
                assert result.points[-1].x > 10.0  # straight through the hole
            else:
                assert result.points[-1].x == pytest.approx(0.0, abs=1e-6)  # ends on the plate


class TestReviewFixes:
    def test_zero_transmission_splitter_reflects_everything(self):
        scene = Scene()
        laser = scene.add(Laser(center=(-40, 0), angle=0))
        scene.add(BeamSplitter(center=(0, 0), angle=135, transmission=0.0))
        results = _trace(scene, laser)
        by_dir = {round(r.direction_deg): r.power for r in results}
        assert by_dir.get(90) == pytest.approx(1.0)  # all power reflects
        assert 0 not in by_dir or by_dir[0] == pytest.approx(0.0)  # nothing transmits


    def test_editing_a_traced_ray_remaps_to_the_source(self, client=None):
        from fastapi.testclient import TestClient as _TC

        tc = _TC(create_app())
        tc.post("/api/scene/new", json={})
        laser = tc.post("/api/component", json={"name": "Laser", "params": {"center": [-40, 0]}}).json()["id"]
        tc.post("/api/trace", json={"source_id": laser})
        chief = next(b for b in tc.get("/api/scene").json()["beams"] if b.get("traced_from") and not b.get("ray"))
        response = tc.patch(f"/api/component/{chief['id']}", json={"params": {"width": 2.0}}).json()
        entry = next(b for b in response["spec"]["beams"] if b["id"] == chief["id"])
        assert entry["width"] == pytest.approx(2.0)  # response reflects the STORED state
        source = next(c for c in tc.get("/api/scene").json()["components"] if c["id"] == laser)
        assert source["ray_width"] == pytest.approx(2.0)  # remapped onto the laser


    def test_grouped_source_survives_refresh(self):
        from optodraw.app.session import EditorSession, empty_scene_spec

        spec = empty_scene_spec()
        spec["trace_mode"] = "physical"
        spec["components"] = [{
            "type": "Group", "id": "g1",
            "children": [{"type": "Laser", "id": "laser_g", "center": [-40, 0]}],
        }]
        session = EditorSession(spec)
        session.trace_from("laser_g")
        assert any(b.get("traced_from") == "laser_g" for b in session.spec["beams"])
        session.set_meta(title="poke")  # any mutation triggers the refresh
        assert any(b.get("traced_from") == "laser_g" for b in session.spec["beams"])
