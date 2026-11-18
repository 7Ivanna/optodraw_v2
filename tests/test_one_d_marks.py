"""The 1D view draws the marks a 2D figure makes about its parts: a Region box, a Bracket and the motion mark of a
part on a stage. It also follows set_view_layout on a bench joined only by fibres."""

from __future__ import annotations

import pytest

from optodraw import Beam, Bracket, Laser, Lens, Photodiode, Region, Scene
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


