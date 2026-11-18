"""The 1D view draws the marks a 2D figure makes about its parts: a Region box, a Bracket and the motion mark of a
part on a stage. It also follows set_view_layout on a bench joined only by fibres."""

from __future__ import annotations

import pytest

from optodraw import Beam, Bracket, FiberCoupler, Laser, Lens, Photodiode, Region, Scene
from optodraw.symbols.schematic import build_schematic
from optodraw.symbols.tikz_export import render_tikz_1d


def _telescope(spacing=None):
    scene = Scene(width=100, height=40)
    if spacing is not None:
        scene.set_view_layout({"1d": {"spacing": spacing}})
    laser = scene.add(Laser(center=(-35, 0), label="Laser", label_side="top"))
    l1 = scene.add(Lens(center=(-10, 0), focal_length=10, label="L1", label_side="bottom"))
    l2 = scene.add(Lens(center=(10, 0), focal_length=10, label="L2", label_side="bottom"))
    det = scene.add(Photodiode(center=(35, 0), label="PD", label_side="top"))
    det.base_mount = "stage"
    scene.add(Beam.through(laser, l1, l2, det))
    scene.add(Region([l1, l2], label="Telescope"))
    scene.add(Bracket("4f", l1, l2, side="right"))
    return scene


def _box(item):
    return item.x, item.y, item.x + item.symbol.width, item.y + item.symbol.height


def _mark(schematic, kind):
    found = [mark for mark in schematic.marks if mark.kind == kind]
    assert len(found) == 1, [mark.kind for mark in schematic.marks]
    return found[0]


@pytest.mark.parametrize("spacing", [None, 1])
def test_a_region_box_holds_its_parts_in_1d(spacing):
    schematic = build_schematic(_telescope(spacing))
    region = _mark(schematic, "Region")
    xs = [x for line in region.lines for x, _ in line]
    ys = [y for line in region.lines for _, y in line]
    held = {item.label: _box(item) for item in schematic.items}
    for name in ("L1", "L2"):
        x0, y0, x1, y1 = held[name]
        assert min(xs) < x0 and x1 < max(xs) and min(ys) < y0 and y1 < max(ys), name
    for name in ("Laser", "PD"):
        x0, _, x1, _ = held[name]
        assert x1 < min(xs) or x0 > max(xs), name
    assert region.dashed and region.label == "Telescope"


@pytest.mark.parametrize("spacing", [None, 1])
def test_a_bracket_spans_its_parts_in_1d_clear_of_them(spacing):
    schematic = build_schematic(_telescope(spacing))
    bracket = _mark(schematic, "Bracket")
    points = [point for line in bracket.lines for point in line]
    held = {item.label: _box(item) for item in schematic.items}
    below = max(held["L1"][3], held["L2"][3])               # side="right" of a beam to the right is below it
    assert all(y > below for _, y in points)
    assert min(x for x, _ in points) <= held["L1"][2] and max(x for x, _ in points) >= held["L2"][0]
    assert bracket.label == "4f"


def test_a_part_on_a_stage_shows_its_motion_mark_in_1d():
    schematic = build_schematic(_telescope())
    stage = _mark(schematic, "stage")
    detector = next(item for item in schematic.items if item.label == "PD")
    x0, y0, x1, y1 = _box(detector)
    points = [point for line in stage.lines for point in line]
    assert len(stage.heads) == 2                                # a double arrow
    assert x0 <= min(x for x, _ in points) and max(x for x, _ in points) <= x1        # beside the part,
    assert max(y for _, y in points) < y0 or min(y for _, y in points) > y1           # not on it


def test_the_svg_and_the_tikz_draw_the_marks():
    scene = _telescope()
    svg = scene.render_svg(None, view="1d").as_svg()
    tikz = render_tikz_1d(scene, include_library=False)
    for text in ("Telescope", "4f"):
        assert f">{text}<" in svg and f"{{{text}}}" in tikz, text
    assert "od1-mark" in svg and "dashed" in tikz


def test_the_page_holds_the_marks():
    schematic = build_schematic(_telescope())
    points = [point for mark in schematic.marks for line in mark.lines for point in line]
    assert all(0.0 <= x <= schematic.width and 0.0 <= y <= schematic.height for x, y in points)


def test_set_view_layout_spaces_an_all_fibre_bench():
    def gap(spacing):
        scene = Scene(width=100, height=40)
        a = scene.add(FiberCoupler(center=(-30, 0), length=14, port_gap=8, label="FC1"))
        b = scene.add(FiberCoupler(center=(30, 0), length=14, port_gap=8, label="FC2"))
        scene.route((a, "out1"), (b, "in1"), kind="fiber")
        scene.route((a, "out2"), (b, "in2"), kind="fiber")
        scene.set_view_layout({"1d": {"spacing": spacing}})
        items = {item.label: item for item in build_schematic(scene).items}
        return items["FC2"].x - items["FC1"].x

    assert gap(3) > 2.0 * gap(1) > 0.0


def test_the_editor_1d_model_carries_the_marks():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    client = TestClient(create_app())
    client.post("/api/scene/new", json={})
    assert client.post("/api/scene", json={"spec": _telescope().to_spec(), "whole": True}).status_code == 200
    marks = client.get("/api/scene/1d/model").json()["marks"]
    assert sorted(mark["kind"] for mark in marks) == ["Bracket", "Region", "stage"]
    region = next(mark for mark in marks if mark["kind"] == "Region")
    assert region["dashed"] and region["label"] == "Telescope" and len(region["lines"][0]) > 4


@pytest.mark.parametrize("mount", ["stage", "xyz_stage", "rotation_stage", "none"])
def test_a_saved_scene_keeps_the_mount_of_a_part(mount):
    from optodraw.schema import scene_from_spec

    scene = _telescope()
    det = next(node for node in scene.walk() if getattr(node, "label", "") == "PD")
    det.base_mount = mount
    back = next(node for node in scene_from_spec(scene.to_spec()).walk() if getattr(node, "label", "") == "PD")
    assert back.base_mount == mount


def test_a_part_with_its_own_default_mount_saves_no_mount():
    from optodraw import Spectrometer

    scene = Scene(width=60, height=40)
    scene.add(Spectrometer(center=(0, 0), label="Spec"))
    assert "base_mount" not in next(c for c in scene.to_spec()["components"] if c["type"] == "Spectrometer")
