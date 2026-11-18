"""Registry checklist: every registered part meets the contributor contract.

See docs/content/guides/your-own-parts.md. Parts that need constructor arguments (import wrappers,
routes) cannot default-construct and live in GRANDFATHERED instead of failing.
"""

from __future__ import annotations

import pytest

from optodraw.registry import component_registry

GRANDFATHERED = frozenset({"CustomModel", "GDSModel", "Route"})

#: Links need anchors to round-trip; an anchorless default instance is not a
#: meaningful spec. Real beams always carry a path (see test_scene_schema).
LINK_TYPES = frozenset({"Beam", "FocusingBeam", "WaveguideRoute", "FiberRoute"})


def _creatable():
    return {
        name: spec
        for name, spec in component_registry().items()
        if spec.creatable and name not in GRANDFATHERED
    }


def _names():
    return sorted(_creatable())


@pytest.mark.parametrize("name", _names())
def test_part_has_ports(name):
    spec = _creatable()[name]
    ports = spec.cls().ports()
    assert isinstance(ports, dict)


@pytest.mark.parametrize("name", _names())
def test_part_geometries_render(name):
    from optodraw.renderers.svg_renderer import SvgRenderer
    from optodraw.renderers.tikz_renderer import TikzRenderer

    from optodraw import Scene

    spec = _creatable()[name]
    scene = Scene(width=200, height=120)
    scene.add(spec.cls())
    assert isinstance(SvgRenderer(scene).render().as_svg(), str)
    assert "\\begin{tikzpicture}" in TikzRenderer(scene).render()


@pytest.mark.parametrize("name", _names())
def test_part_spec_round_trips(name):
    from optodraw import Scene
    from optodraw.schema import scene_from_spec

    if name in LINK_TYPES:
        pytest.skip("links need anchors; covered with paths in test_scene_schema")
    spec = _creatable()[name]
    scene = Scene(width=200, height=120)
    scene.add(spec.cls())
    rebuilt = scene_from_spec(scene.to_spec())
    assert rebuilt is not None


def test_grandfathered_list_stays_accurate():
    names = {name for name, spec in component_registry().items() if spec.creatable}
    assert GRANDFATHERED <= names, "grandfathered entry left the registry; drop it"
    for name in sorted(GRANDFATHERED):
        spec = component_registry()[name]
        try:
            spec.cls()
        except Exception:
            continue
        raise AssertionError(f"{name} now default-constructs; remove it from GRANDFATHERED")
