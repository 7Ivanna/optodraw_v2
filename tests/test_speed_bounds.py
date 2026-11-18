"""Bounds and obstacle caches preserve results across mutable scene state."""

import pytest

from optodraw import Laser, Scene
from optodraw.core.component import Component
from optodraw.core.routing import _obstacle_boxes
from optodraw.core.transform import Vec3
from optodraw.layout import estimate_component_bounds
from optodraw.schema import scene_to_spec


class CountingOutline(Component):
    calls = {}

    def __init__(self, center=(0, 0)):
        super().__init__()
        self.transform.position = Vec3(*center, 0)
        self.outline = {"type": "polygon", "points": [[-5, -3], [5, -3], [5, 3], [-5, 3]]}

    def geometry_2d(self):
        self.calls[id(self)] = self.calls.get(id(self), 0) + 1
        return self.outline


@pytest.fixture(autouse=True)
def reset_counts():
    CountingOutline.calls.clear()


def test_unchanged_bounds_do_not_rebuild_geometry():
    part = CountingOutline()
    assert estimate_component_bounds(part) == (-5, -3, 5, 3)
    assert estimate_component_bounds(part) == (-5, -3, 5, 3)
    assert part.calls[id(part)] == 1


def test_bounds_invalidate_after_nested_outline_mutation():
    part = CountingOutline()
    assert estimate_component_bounds(part) == (-5, -3, 5, 3)
    part.outline["points"][1][0] = 15
    assert estimate_component_bounds(part) == (-5, -3, 15, 3)
    assert estimate_component_bounds(part) == (-5, -3, 15, 3)
    assert part.calls[id(part)] == 2


def test_uncacheable_instance_state_keeps_bounds_working():
    part = CountingOutline()
    part.external_callback = lambda: None
    assert estimate_component_bounds(part) == (-5, -3, 5, 3)
    part.outline["points"][0][0] = -12
    assert estimate_component_bounds(part) == (-12, -3, 5, 3)


def make_scene():
    scene = Scene()
    start = scene.add(CountingOutline(center=(-30, 0)))
    end = scene.add(CountingOutline(center=(60, 0)))
    obstacle = scene.add(CountingOutline(center=(30, 7)))
    return scene, start, end, obstacle


def test_obstacles_reuse_geometry_and_return_an_independent_list():
    _, start, end, obstacle = make_scene()
    first = _obstacle_boxes(start, end)
    assert first == [(22, 0, 38, 14)]
    first.clear()
    assert _obstacle_boxes(start, end) == [(22, 0, 38, 14)]
    assert obstacle.calls[id(obstacle)] == 1


def test_endpoint_exclusion_and_margin_are_not_cached_per_route():
    _, start, end, obstacle = make_scene()
    assert _obstacle_boxes(start, end) == [(22, 0, 38, 14)]
    assert _obstacle_boxes(start, obstacle, margin=1) == [(54, -5, 66, 5)]


def test_obstacle_cache_tracks_geometry_position_and_scene_membership():
    scene, start, end, obstacle = make_scene()
    assert _obstacle_boxes(start, end) == [(22, 0, 38, 14)]
    obstacle.transform.position.x = 40
    obstacle.outline["points"][1][0] = 15
    assert _obstacle_boxes(start, end) == [(27, 0, 53, 14)]
    extra = scene.add(CountingOutline(center=(0, 20)))
    assert _obstacle_boxes(start, end) == [(27, 0, 53, 14), (-8, 13, 8, 27)]
    scene.root.children.remove(extra)
    assert _obstacle_boxes(start, end) == [(27, 0, 53, 14)]


def test_obstacle_cache_tracks_ancestor_transforms():
    scene, start, end, obstacle = make_scene()
    assert _obstacle_boxes(start, end) == [(22, 0, 38, 14)]
    scene.root.children.remove(obstacle)
    group = scene.group()
    group.add(obstacle)
    group.transform.position = Vec3(10, -2, 0)
    assert _obstacle_boxes(start, end) == [(32, -2, 48, 12)]
    group.transform.position.x = 20
    assert _obstacle_boxes(start, end) == [(42, -2, 58, 12)]


def test_caches_do_not_change_component_exports_scene_specs_or_svg():
    scene = Scene()
    part = scene.add(Laser(label="source"))
    spec = scene_to_spec(scene)
    component = part.to_dict()
    svg = scene.render_svg().as_svg()
    estimate_component_bounds(part)
    _obstacle_boxes(part, None)
    assert part.to_dict() == component
    assert scene_to_spec(scene) == spec
    assert scene.render_svg().as_svg() == svg


def test_uncacheable_obstacle_state_still_tracks_nested_changes():
    _, start, end, obstacle = make_scene()
    assert _obstacle_boxes(start, end) == [(22, 0, 38, 14)]
    obstacle.external_callback = lambda: None
    obstacle.outline["points"][1][0] = 15
    assert _obstacle_boxes(start, end) == [(17, 0, 43, 14)]
