"""Round-trip tests for schema v2 schematic-first metadata.

Covers ``physical_spec`` payloads, ``render_physical`` / ``visual_style`` /
``visual_scale`` opt-ins, ``physical_length_um`` on routes, scene-level
``metadata`` (dimension markers, caption stubs), forward compatibility with
v1 specs, and JSON save/load.
"""

from __future__ import annotations


import pytest

from optodraw import (
    Scene,
)
from optodraw.schema import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
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


class TestRoutePhysicalLength:

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


