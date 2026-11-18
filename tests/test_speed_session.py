
import pytest

from optodraw.app.session import EditorSession
from optodraw.schema import scene_from_spec, scene_to_spec


def make_session(path_type="straight"):
    return EditorSession({
        "components": [
            {"id": name, "type": "Laser", "center": center}
            for name, center in zip("abcd", ([0, 0], [60, 0], [0, 40], [60, 40]))
        ],
        "routes": [
            {"id": "r1", "from": ["a", "out"], "to": ["b", "out"],
             "path_type": path_type, "backend": "local"},
            {"id": "r2", "from": ["c", "out"], "to": ["d", "out"],
             "path_type": path_type, "backend": "local"},
        ],
        "beams": [{"id": "beam", "type": "Beam", "path": [["c", "out"], ["d", "out"]]}],
        "part_definitions": {}, "assets": {},
    })


def nodes(scene):
    return {node._id: node for node in scene.root.children}


def assert_fresh_output(session):
    retained = session.scene()
    fresh = scene_from_spec(session.spec)
    session._tag_links(fresh)
    assert scene_to_spec(retained) == scene_to_spec(fresh)
    options = {"editable": True, "show_labels": True}
    assert retained.render_svg(component_ids=session.component_id_map(retained), **options).as_svg() == (
        fresh.render_svg(component_ids=session.component_id_map(fresh), **options).as_svg()
    )


def test_unchanged_scene_is_retained():
    session = make_session()
    scene = session.scene()
    assert session.scene() is scene
    session.ports_map()
    assert session.scene() is scene


def test_route_edit_preserves_components_and_other_links():
    session = make_session()
    before = nodes(session.scene())
    session.update_route("r1", waypoints=[[20, 15], [40, 15]])
    after = nodes(session.scene())
    assert after["r1"] is not before["r1"]
    for name in ("a", "b", "c", "d", "r2", "beam"):
        assert after[name] is before[name]
    assert_fresh_output(session)


def test_invalid_edit_keeps_retained_scene_and_spec():
    session = make_session()
    scene = session.scene()
    spec = session.spec
    with pytest.raises(ValueError):
        session.move_component("a", center=[float("nan"), 0])
    assert session.spec == spec
    assert session.scene() is scene


def test_deleted_unconnected_obstacle_rebuilds_routes():
    session = make_session("manhattan")
    spec = session.spec
    spec["components"].append({"id": "obstacle", "type": "Laser", "center": [30, 20]})
    session.load(spec)
    before = nodes(session.scene())
    session.delete("obstacle")
    after = nodes(session.scene())
    assert after["r1"] is not before["r1"]
    assert after["r2"] is not before["r2"]
    assert_fresh_output(session)
