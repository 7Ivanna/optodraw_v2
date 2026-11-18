"""Cache keys must not recursively capture scene membership or other caches."""

from optodraw import Scene, Waveguide
from optodraw.layout._cache import _component_state


def _routed_scene():
    scene = Scene()
    a = scene.add(Waveguide(center=(0, 0), width=0.5, bend_radius=2))
    b = scene.add(Waveguide(center=(80, 0), width=0.5, bend_radius=2))
    route = scene.route((a, "o2"), (b, "o1"), backend="local")
    return scene, a, route


def test_route_key_does_not_capture_unrelated_scene_members():
    scene, _, route = _routed_scene()
    original = _component_state(route)
    assert original is not None
    scene.add(Waveguide(center=(400, 400), width=0.5, bend_radius=2))
    assert _component_state(route) == original


def test_endpoint_caches_do_not_enter_route_key():
    _, endpoint, route = _routed_scene()
    original = _component_state(route)
    endpoint._layout_bounds_cache = (b"x" * 100_000, (-1, -1, 1, 1))
    endpoint._routing_obstacle_cache = (b"y" * 100_000, ())
    assert _component_state(route) == original
    assert len(original) < 10_000
    endpoint.length += 1
    assert _component_state(route) != original
