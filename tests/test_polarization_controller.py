"""The fibre polarization controller: a fibre wound on paddles, fibre in and fibre out."""

from __future__ import annotations


import pytest

import optodraw


def _shapes(geometry: dict, key: str, kind: str) -> list[dict]:
    found = [geometry] if geometry.get(key) == kind else []
    for child in geometry.get("children", []):
        found.extend(_shapes(child, key, kind))
    return found


def test_it_refuses_a_controller_with_no_paddle():
    with pytest.raises(ValueError, match="paddles"):
        optodraw.PolarizationController(paddles=0)


def test_it_draws_in_every_renderer_and_carries_a_fibre():
    scene = optodraw.Scene(width=260, height=120, platform="on_chip")
    controller = scene.add(optodraw.PolarizationController(center=(-60, 0), label="PC"))
    coupler = scene.add(optodraw.EdgeCoupler(center=(60, 0), label="EC"))
    scene.route((controller, "out"), (coupler, "f1"), kind="fiber")
    assert "<svg" in scene.render_svg().as_svg()
    assert "tikzpicture" in scene.render_tikz()
    assert "PolarizationController" in scene.render_threejs() or "torus" in scene.render_threejs()
    data = controller.to_dict()
    assert data["type"] == "PolarizationController" and data["paddles"] == 3


