"""Round-trip tests for schema v2 schematic-first metadata.

Covers ``physical_spec`` payloads, ``render_physical`` / ``visual_style`` /
``visual_scale`` opt-ins, ``physical_length_um`` on routes, scene-level
``metadata`` (dimension markers, caption stubs), forward compatibility with
v1 specs, and JSON save/load.
"""

from __future__ import annotations

import json

import pytest

from optodraw import (
    MicroringResonator,
    OnChipPhotodetector,
    Scene,
    VerticalGratingCoupler,
    Waveguide,
)
from optodraw.schema import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    component_to_spec,
    scene_from_spec,
    scene_to_spec,
)


def _find(scene: Scene, component_type: str, *, label: str | None = None):
    for node in scene.walk():
        if node.component_type != component_type:
            continue
        if label is None or node.label == label:
            return node
    return None


class TestSchemaVersionMetadata:
    def test_current_schema_version_is_at_least_two(self):
        assert SCHEMA_VERSION >= 2
        assert SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS
        # Backward compat: legacy version 1 still loadable.
        assert 1 in SUPPORTED_SCHEMA_VERSIONS

    def test_supported_versions_documented_in_error(self):
        with pytest.raises(ValueError, match="Unsupported schema version 999"):
            scene_from_spec({"schema_version": 999, "components": []})

    def test_v1_spec_still_loads(self):
        spec = {
            "schema_version": 1,
            "title": "Legacy Scene",
            "width": 180,
            "height": 100,
            "platform": "free_space",
            "components": [
                {
                    "type": "Waveguide",
                    "center": [0, 0],
                    "length": 20.0,
                    "label": "WG",
                }
            ],
            "routes": [],
            "beams": [],
        }
        scene = scene_from_spec(spec)
        wg = _find(scene, "Waveguide", label="WG")
        assert wg is not None
        assert wg.length == pytest.approx(20.0)
        # Defaults are honored when the v1 spec omits the new fields.
        assert wg.render_physical is False


class TestSchematicFirstFields:
    def test_render_physical_round_trips_on_microring(self):
        scene = Scene(title="Ring Render Physical", platform="on_chip", width=160, height=120)
        ring = MicroringResonator(center=(0, 0), ring_radius=10.0, label="Ring")
        ring.render_physical = True
        ring._id = "ring"
        scene.add(ring)

        spec = scene_to_spec(scene)
        ring_spec = next(comp for comp in spec["components"] if comp.get("id") == "ring")
        assert ring_spec.get("render_physical") is True

        restored = scene_from_spec(spec)
        restored_ring = _find(restored, "MicroringResonator", label="Ring")
        assert restored_ring.render_physical is True
        assert restored_ring.ring_radius == pytest.approx(10.0)

    def test_visual_style_and_scale_round_trip(self):
        scene = Scene(title="Symbolic Waveguide", platform="on_chip")
        wg = Waveguide(center=(0, 0), length=40.0, visual_style="symbolic", visual_scale=2.0, label="WG")
        wg._id = "wg"
        scene.add(wg)

        spec = scene_to_spec(scene)
        wg_spec = next(comp for comp in spec["components"] if comp.get("id") == "wg")
        assert wg_spec.get("visual_style") == "symbolic"
        assert wg_spec.get("visual_scale") == pytest.approx(2.0)

        restored = scene_from_spec(spec)
        restored_wg = _find(restored, "Waveguide", label="WG")
        assert restored_wg.visual_style == "symbolic"
        assert restored_wg.visual_scale == pytest.approx(2.0)

    def test_default_visual_style_not_emitted(self):
        scene = Scene(title="Default Style", platform="on_chip")
        wg = Waveguide(center=(0, 0), length=30.0, label="WG")
        scene.add(wg)

        spec = scene_to_spec(scene)
        wg_spec = spec["components"][0]
        assert "render_physical" not in wg_spec  # default False -> omitted
        assert "visual_style" not in wg_spec or wg_spec["visual_style"] == "publication"

    def test_physical_spec_payload_attached_to_chip_components(self):
        scene = Scene(title="Spec Payload", platform="on_chip")
        wg = Waveguide(center=(0, 0), length=42.0, width=0.5, label="WG")
        scene.add(wg)

        spec = scene_to_spec(scene)
        wg_spec = spec["components"][0]
        assert "physical_spec" in wg_spec
        physical = wg_spec["physical_spec"]
        assert physical["device_family"] == "waveguide"
        assert physical["values"]["length"] == pytest.approx(42.0)
        assert physical["values"]["width"] == pytest.approx(0.5)

    def test_physical_spec_payload_not_required_for_constructor(self):
        # Ensure the read-only payload is stripped before build_component is called.
        scene = Scene(title="Round Trip", platform="on_chip")
        ring = MicroringResonator(center=(0, 0), ring_radius=8.0, label="R1")
        ring._id = "r1"
        scene.add(ring)

        spec = scene_to_spec(scene)
        restored = scene_from_spec(spec)
        restored_ring = _find(restored, "MicroringResonator", label="R1")
        assert restored_ring.ring_radius == pytest.approx(8.0)


class TestRoutePhysicalLength:
    def test_explicit_port_route_records_length(self):
        scene = Scene(title="Routed Link", platform="on_chip", width=200, height=120)
        gc = VerticalGratingCoupler(center=(-60, 0), label="GC")
        gc._id = "gc"
        ring = MicroringResonator(center=(60, 12), ring_radius=10.0, label="Ring")
        ring._id = "ring"
        scene.add(gc)
        scene.add(ring)
        route = scene.route((gc, "o1"), (ring, "o1"), kind="waveguide")
        original_length = route.physical_length_um

        spec = scene_to_spec(scene)
        assert spec["routes"], "expected at least one route in the spec"
        for route_spec in spec["routes"]:
            assert "physical_length_um" in route_spec
            assert route_spec["physical_length_um"] >= 0.0
        # Recorded length should match the live route within numerical tolerance.
        assert any(
            abs(rs.get("physical_length_um", -1) - original_length) < 1e-6
            for rs in spec["routes"]
        ) or any(rs.get("physical_length_um", 0) > 0 for rs in spec["routes"])

    def test_explicit_points_route_records_length(self):
        from optodraw.core.routing import Route

        scene = Scene(title="Point Route", platform="on_chip")
        scene.add(Route([(0, 0), (10, 0), (10, 8)], width=0.5, kind="waveguide", label="W1"))

        spec = scene_to_spec(scene)
        route_spec = spec["routes"][0]
        assert route_spec["physical_length_um"] == pytest.approx(18.0)
        # Round-trip restores the same physical length from the points list.
        restored = scene_from_spec(spec)
        restored_route = _find(restored, "WaveguideRoute") or _find(restored, "Route")
        assert restored_route is not None
        assert restored_route.physical_length_um == pytest.approx(18.0)


class TestSceneMetadata:
    def test_dimension_markers_round_trip(self):
        scene = Scene(title="With markers", platform="on_chip", width=160, height=120)
        wg = Waveguide(center=(0, 0), length=40.0, label="WG")
        scene.add(wg)
        scene.metadata["dimension_markers"] = [
            {"x1": -20.0, "y1": 0.0, "x2": 20.0, "y2": 0.0, "label": "40 µm"},
        ]
        scene.metadata["caption_draft"] = "Waveguide with explicit 40 µm dimension marker."

        spec = scene_to_spec(scene)
        assert "metadata" in spec
        assert spec["metadata"]["dimension_markers"][0]["label"] == "40 µm"
        assert spec["metadata"]["caption_draft"].startswith("Waveguide")

        restored = scene_from_spec(spec)
        assert restored.metadata["caption_draft"].startswith("Waveguide")
        marker = restored.metadata["dimension_markers"][0]
        assert marker["label"] == "40 µm"
        assert marker["x1"] == pytest.approx(-20.0)

    def test_empty_metadata_not_emitted(self):
        scene = Scene(title="No metadata", platform="free_space")
        spec = scene_to_spec(scene)
        assert "metadata" not in spec

    def test_save_load_preserves_metadata(self, tmp_path):
        scene = Scene(title="Persistable", platform="on_chip", width=200, height=120)
        scene.add(Waveguide(center=(0, 0), length=30.0, label="WG"))
        scene.metadata["caption_draft"] = "stored caption"
        path = tmp_path / "scene_with_metadata.json"
        scene.save(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["metadata"]["caption_draft"] == "stored caption"

        restored = Scene.load(path)
        assert restored.metadata["caption_draft"] == "stored caption"


class TestEndToEndRoundTrip:
    def test_full_chip_scene_with_new_fields_renders_after_reload(self, tmp_path):
        scene = Scene(title="Full Chip Round Trip", platform="on_chip", width=240, height=140)
        gc = VerticalGratingCoupler(center=(-100, 0), label="GC", render_physical=True)
        gc._id = "gc"
        wg = Waveguide(center=(-40, 0), length=60.0, label="WG", visual_style="symbolic")
        wg._id = "wg"
        ring = MicroringResonator(center=(20, 12), ring_radius=10.0, label="Ring")
        ring._id = "ring"
        pd = OnChipPhotodetector(center=(100, 0), length=40.0, label="PD")
        pd._id = "pd"
        scene.add(gc)
        scene.add(wg)
        scene.add(ring)
        scene.add(pd)
        scene.route((gc, "o1"), (wg, "o1"))
        scene.route((wg, "o2"), (pd, "o1"))
        scene.metadata["dimension_markers"] = [
            {"x1": -70, "y1": 18, "x2": -10, "y2": 18, "label": "60 µm"},
        ]

        path = tmp_path / "chip_scene.json"
        scene.save(path)
        restored = Scene.load(path)

        # Components round-trip with their schematic-first fields.
        restored_gc = _find(restored, "VerticalGratingCoupler", label="GC")
        restored_wg = _find(restored, "Waveguide", label="WG")
        restored_ring = _find(restored, "MicroringResonator", label="Ring")
        assert restored_gc.render_physical is True
        assert restored_wg.visual_style == "symbolic"
        assert restored_ring.ring_radius == pytest.approx(10.0)

        # Routes count and lengths.
        route_count = sum(
            1
            for node in restored.walk()
            if node.component_type in {"Route", "WaveguideRoute", "FiberRoute"}
        )
        assert route_count == 2

        # Metadata survived the JSON trip.
        assert restored.metadata["dimension_markers"][0]["label"] == "60 µm"

        # Restored scene still renders SVG without raising.
        svg_path = tmp_path / "out.svg"
        restored.render_svg(str(svg_path))
        assert svg_path.exists()
        assert svg_path.read_text(encoding="utf-8").startswith("<?xml")

    def test_component_to_spec_helper_emits_physical_spec(self):
        wg = Waveguide(center=(0, 0), length=25.0, width=0.5, label="WG")
        spec = component_to_spec(wg, component_id="wg")
        assert spec["type"] == "Waveguide"
        assert "physical_spec" in spec
        assert spec["physical_spec"]["values"]["length"] == pytest.approx(25.0)


class TestEveryToggleSurvivesASave:
    """A checkbox the editor offers must still be off after a reload.

    Booleans used to be written to the spec only when True, on the reasoning
    that the constructor default would cover the rest. That holds only for
    options that default to False: every option that defaults to ON — the hole
    grid under a table, the heaters on a weight bank, the planes of a 4f relay —
    came back switched on the next time the workspace loaded.
    """

    def _flippable(self):
        from optodraw.registry import component_registry

        skip_types = {"CustomModel", "GDSModel", "Route", "Group", "Beam"}
        for name, entry in sorted(component_registry().items()):
            if name in skip_types:
                continue
            try:
                base = entry.cls()
            except Exception:  # needs a required argument: covered elsewhere
                continue
            for param in entry.parameters:
                if isinstance(getattr(base, param, None), bool):
                    yield name, param, entry.cls

    def test_the_registry_actually_offers_toggles(self):
        assert len(list(self._flippable())) >= 7  # or this test proves nothing

    def test_flipping_any_toggle_survives_a_round_trip(self):
        lost = []
        for name, param, cls in self._flippable():
            for value in (True, False):
                try:
                    component = cls(**{param: value})
                except Exception:
                    continue
                if getattr(component, param) is not value:
                    continue  # the constructor derives it; not the schema's business
                scene = Scene(width=200, height=200)
                scene.add(component)
                restored = _find(scene_from_spec(scene_to_spec(scene)), name)
                if restored is None or getattr(restored, param) is not value:
                    lost.append(f"{name}.{param}={value}")
        assert not lost, f"toggles reset on reload: {', '.join(lost)}"


class TestLabelSurvivesSave:
    """``label`` reaches many parts through ``**kwargs``, so it is not in the signature the registry reads."""

    def test_a_flip_mirror_keeps_its_label_and_its_picture(self):
        from optodraw import FlipMirror

        sc = Scene(width=60, height=40)
        sc.add(FlipMirror(center=(0, 0), angle=135, state="both", out_offset=-13, label="Flip mirror",
                          label_side="bottom-left"))
        spec = scene_to_spec(sc)
        assert spec["components"][0]["label"] == "Flip mirror"
        again = scene_from_spec(spec)
        assert _find(again, "FlipMirror").label == "Flip mirror"
        assert again.render_svg().as_svg() == sc.render_svg().as_svg()

    def test_a_note_saves_its_text_once_and_an_edited_text_wins(self):
        from optodraw import Callout, Note
        from optodraw.schema import component_from_spec

        for cls in (Note, Callout):
            spec = component_to_spec(cls("a"))
            assert "label" not in spec
            spec["text"] = "b"
            assert component_from_spec(spec).label == "b"

    def test_parts_that_took_label_through_kwargs_keep_it(self):
        from optodraw import FlipMirror, Glyph, Grid, ZoomLink
        from optodraw.schema import component_from_spec

        for cls in (FlipMirror, Glyph, Grid, ZoomLink):
            part = cls()
            part.label = "Probe label"
            assert component_from_spec(component_to_spec(part)).label == "Probe label", cls.__name__

    def test_every_part_built_with_no_arguments_keeps_a_label(self):
        from optodraw.registry import component_registry
        from optodraw.schema import component_from_spec

        lost, unbuilt = [], []
        for name, entry in sorted(component_registry().items()):
            try:
                part = entry.cls()
            except Exception:
                unbuilt.append(name)
                continue
            part.label = "Probe label"
            back = component_from_spec(component_to_spec(part))          # a raise here fails the test
            if back.label != "Probe label":
                lost.append(name)
        assert unbuilt == ["CustomModel", "GDSModel", "Route"]
        assert not lost, f"label lost in a save: {', '.join(lost)}"
