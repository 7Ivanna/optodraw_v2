"""Regression cases from the portable user-part review."""

import math
import xml.etree.ElementTree as ET

import pytest

from optodraw import Scene, Waveguide
from optodraw.parts.definition import SvgAsset


def _asset(body, box=(-10, -5, 20, 10)):
    frame = " ".join(str(value) for value in box)
    return SvgAsset(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{frame}">{body}</svg>'.encode(),
        box,
    )


@pytest.mark.parametrize("path_type,smooth", [("manual", False), ("manhattan", False), ("manhattan", True)])
def test_connected_waypoints_round_trip(path_type, smooth):
    scene = Scene()
    a = scene.add(Waveguide(center=(0, 0), length=20, width=0.5, bend_radius=2, render_physical=True))
    b = scene.add(Waveguide(center=(80, 0), length=20, width=0.5, bend_radius=2, render_physical=True))
    steps = [{"x": 30}, {"y": 30}, {"x": 50}, {"y": 0}]
    route = scene.route(
        (a, "o2"), (b, "o1"), backend="local", path_type=path_type,
        smooth=smooth, bend_radius=2, steps=steps,
        start_straight_length=7, end_straight_length=9, snap_tolerance=0.001,
    )
    original_points = [point.as_tuple() for point in route.points]
    original_length = route.physical_length_um
    steps[0]["x"] = 999
    spec = scene.to_spec()
    saved = spec["routes"][0]
    assert saved["steps"][0] == {"x": 30}
    assert saved["start_straight_length"] == 7
    assert saved["end_straight_length"] == 9
    assert saved["snap_tolerance"] == 0.001
    restored = Scene.from_spec(spec)
    loaded = next(node for node in restored.walk() if node.component_type == "WaveguideRoute")
    assert [point.as_tuple() for point in loaded.points] == original_points
    assert loaded.physical_length_um == pytest.approx(original_length)
    assert loaded.start_component is not a
    assert loaded.start_component.world_port(loaded.start_port).center == loaded.points[0]
    assert loaded.end_component.world_port(loaded.end_port).center == loaded.points[-1]
    assert restored.to_spec()["routes"] == spec["routes"]


def test_svg_ids_and_references_are_per_embedding():
    asset = _asset('<defs><clipPath id="clip"><rect width="10" height="5"/></clipPath></defs>'
                   '<g id="body" clip-path="url(#clip)"><path d="M0 0H20V10Z"/></g>')
    original = asset.data
    digest = asset.digest
    first = asset.inner(namespace="first")
    second = asset.inner(namespace="second")
    document = ET.fromstring(f"<svg>{first}{second}</svg>")
    ids = [node.attrib["id"] for node in document.iter() if "id" in node.attrib]
    assert len(ids) == len(set(ids)) == 4
    assert document.find(".//g[@id='first-body']").attrib["clip-path"] == "url(#first-clip)"
    assert document.find(".//g[@id='second-body']").attrib["clip-path"] == "url(#second-clip)"
    assert asset.inner(namespace="first") == first
    assert asset.data == original and asset.digest == digest


def test_instance_namespace_survives_scene_round_trip():
    from optodraw.parts._svg_frame import svg_namespace

    scene = Scene()
    parts = [scene.add(Waveguide(center=(x, 0), width=0.5, bend_radius=2)) for x in (0, 80)]
    names = [svg_namespace(part, "a" * 64, "2d") for part in parts]
    assert names[0] != names[1]
    assert svg_namespace(parts[0], "a" * 64, "1d") != names[0]
    scene.route((parts[0], "o2"), (parts[1], "o1"), backend="local")
    assert [svg_namespace(part, "a" * 64, "2d") for part in parts] == names
    restored = Scene.from_spec(scene.to_spec())
    restored_parts = [part for part in restored.root.children if part.component_type == "Waveguide"]
    assert [svg_namespace(part, "a" * 64, "2d") for part in restored_parts] == names


def test_percentages_use_asset_frame_without_changing_asset():
    asset = _asset('<rect x="-10" y="-5" width="100%" height="100%"/>'
                   '<circle cx="50%" cy="50%" r="10%" stroke-width="2%"/>')
    original, digest = asset.data, asset.digest
    root = ET.fromstring(asset.inner())
    rect, circle = root.find("rect"), root.find("circle")
    assert float(rect.attrib["width"]) == 20
    assert float(rect.attrib["height"]) == 10
    assert float(circle.attrib["cx"]) == 10
    assert float(circle.attrib["cy"]) == 5
    diagonal = math.hypot(20, 10) / math.sqrt(2)
    assert float(circle.attrib["r"]) == pytest.approx(diagonal * 0.1)
    assert float(circle.attrib["stroke-width"]) == pytest.approx(diagonal * 0.02)
    three_d = ET.fromstring(asset.document())
    assert three_d.attrib["viewBox"] == "-10 -5 20 10"
    assert float(three_d.find("{http://www.w3.org/2000/svg}rect").attrib["width"]) == 20
    assert asset.data == original and asset.digest == digest


def test_nested_svg_percentages_use_its_own_view_box():
    asset = _asset('<svg width="50%" height="50%" viewBox="0 0 8 4">'
                   '<rect width="100%" height="50%"/></svg>')
    nested = ET.fromstring(asset.inner()).find("svg")
    assert float(nested.attrib["width"]) == 10
    assert float(nested.attrib["height"]) == 5
    assert float(nested.find("rect").attrib["width"]) == 8
    assert float(nested.find("rect").attrib["height"]) == 2


def test_unsupported_relative_dimension_has_named_error():
    asset = _asset('<rect width="3em" height="10"/>')
    with pytest.raises(ValueError, match=r"SVG rect.width.*relative"):
        asset.inner()
