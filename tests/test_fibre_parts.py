"""Fibre parts that papers show: an amplifier, a circulator, a 2x2 coupler, a spool, a variable attenuator."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.registry import build_component, component_registry
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d

FIBRE_PARTS = {
    "FiberAmplifier": {"in", "out"},
    "FiberCirculator": {"p1", "p2", "p3"},
    "FiberCoupler": {"in1", "in2", "out1", "out2"},
    "FiberSpool": {"in", "out"},
    "VariableAttenuator": {"in", "out"},
}


@pytest.mark.parametrize("name", FIBRE_PARTS)
def test_a_fibre_part_is_in_the_catalog_with_fibre_ports(name):
    spec = component_registry()[name]
    part = build_component(name)
    assert spec.category == "optics" and spec.platform == "free_space"
    assert set(part.ports()) == FIBRE_PARTS[name]
    assert {port.kind for port in part.ports().values()} == {"fiber"}


@pytest.mark.parametrize("name", FIBRE_PARTS)
def test_a_fibre_part_has_its_own_symbol_and_a_painted_2d_look(name):
    part = build_component(name)
    symbol = lookup(part)
    assert symbol.exact and symbol.source == "prebuilt", name
    art = art_2d(part)
    assert art is not None and art["residual"] < 0.15, name
    assert "Gradient" in art["svg"], name


def test_the_coupler_and_the_spool_keep_their_numbers():
    coupler = optodraw.FiberCoupler(ratio=0.9)
    spool = optodraw.FiberSpool(fiber_length_km=25.0)
    assert coupler.physics_metadata()["ratio"] == pytest.approx(0.9)
    assert spool.physics_metadata()["fiber_length_km"] == pytest.approx(25.0)
    with pytest.raises(ValueError):
        optodraw.FiberCoupler(ratio=1.5)


def test_light_goes_round_the_circulator_from_port_1_to_2_to_3():
    """Port 1 left, port 2 right, port 3 below: the order a reader expects from a fibre diagram."""

    ports = optodraw.FiberCirculator().ports()
    assert ports["p1"].center.x < 0 < ports["p2"].center.x
    assert ports["p3"].center.y < 0 and abs(ports["p3"].center.x) < 1e-9


def test_a_fibre_route_is_amber_like_the_fibre_leads_of_the_parts():
    """The parts draw their fibre leads amber (the jacket of a patch fibre); a green route did not match."""

    scene = optodraw.Scene(width=120, height=60, platform="free_space")
    amp = scene.add(optodraw.FiberAmplifier(center=(-30, 0), label=""))
    spool = scene.add(optodraw.FiberSpool(center=(30, 0), label=""))
    scene.route((amp, "out"), (spool, "in"), kind="fiber")
    svg = scene.render_svg().as_svg().lower()
    assert "#2a9d6f" not in svg and "#f59e0b" in svg


# ---------------------------------------------------------------- 3D: fibre parts lie on the table
FIBRE_3D = ["FiberAmplifier", "FiberCirculator", "FiberCoupler", "FiberSpool", "VariableAttenuator",
            "PolarizationController", "SNSPD"]


def _shapes(node):
    yield node
    for child in node.get("children", []):
        yield from _shapes(child)


def _lead_ends(geometry) -> list[tuple[float, float, float]]:
    """The end centres of every cylinder that lies along x or z, and the ends of every tube path."""

    import math

    ends = []
    for shape in _shapes(geometry):
        if shape.get("shape") == "tube_path":
            ends += [tuple(shape["points"][0]), tuple(shape["points"][-1])]
        elif shape.get("shape") == "cylinder" and shape.get("rotation"):
            x, y, z = shape.get("position", [0.0, 0.0, 0.0])
            h = shape["height"] / 2.0
            rx, _, rz = shape["rotation"]
            if abs(rz - math.pi / 2.0) < 1e-6:                               # along x
                ends += [(x - h, y, z), (x + h, y, z)]
            elif abs(rx - math.pi / 2.0) < 1e-6:                             # along z
                ends += [(x, y, z - h), (x, y, z + h)]
    return ends


def _lowest(geometry) -> float:
    import math

    lows = []
    for shape in _shapes(geometry):
        x, y, z = shape.get("position", [0.0, 0.0, 0.0])
        kind = shape.get("shape")
        if kind == "box":
            lows.append(y - shape["height"] / 2.0)
        elif kind == "cylinder":
            rotation = shape.get("rotation") or [0.0, 0.0, 0.0]
            lying = abs(rotation[0] - math.pi / 2.0) < 1e-6 or abs(rotation[2] - math.pi / 2.0) < 1e-6
            lows.append(y - (shape["radius"] if lying else shape["height"] / 2.0))
        elif kind == "extruded_polygon":
            lows.append(y)
        elif kind == "tube_path":
            lows.append(min(p[1] for p in shape["points"]) - shape.get("radius", 0.2))
    return min(lows)


@pytest.mark.parametrize("name", FIBRE_3D)
def test_a_fibre_part_lies_on_the_table_not_on_a_post(name):
    """A post lifted the parts to the beam height, while their fibre cables ran on the table."""

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(width=120, height=60, platform="free_space")
    part = scene.add(build_component(name, label=""))
    assert not ThreeJsRenderer(scene)._is_beam_plane_optic(part)
    assert _lowest(part.geometry_3d()) == pytest.approx(0.0, abs=1e-6)      # its base is the table


@pytest.mark.parametrize("name", FIBRE_3D)
def test_each_lead_of_a_fibre_part_meets_its_cable_at_the_port(name):
    from optodraw.components.optics.fibers import LEAD_HEIGHT

    part = build_component(name, label="")
    ends = _lead_ends(part.geometry_3d())
    for port in part.ports().values():
        target = (port.center.x, LEAD_HEIGHT, -port.center.y)
        assert any(sum((a - b) ** 2 for a, b in zip(end, target)) ** 0.5 < 0.8 for end in ends), (name, port.name)


def test_the_leads_are_at_the_height_the_viewer_runs_its_cables():
    from optodraw.components.optics.fibers import LEAD_HEIGHT
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(width=120, height=60, platform="free_space")
    amp = scene.add(optodraw.FiberAmplifier(center=(-30, 0), label=""))
    spool = scene.add(optodraw.FiberSpool(center=(30, 0), label=""))
    scene.route((amp, "out"), (spool, "in"), kind="fiber")
    assert f"const CABLE_Y = {LEAD_HEIGHT};" in ThreeJsRenderer(scene).render()


# ---------------------------------------------------------------- 3D: a cable rises to a connector on a post
def test_a_cable_end_on_a_post_mounted_part_is_marked_to_rise():
    """A cable to a part at the beam height ended at the foot of its post, on the table."""

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(width=160, height=60, platform="free_space")
    collimator = scene.add(optodraw.FiberCollimator(center=(-50, 0), angle=180, label=""))
    spool = scene.add(optodraw.FiberSpool(center=(30, 0), label=""))
    scene.route((collimator, "in"), (spool, "in"), kind="fiber")
    (route,) = [item for item in ThreeJsRenderer(scene)._collect_scene_data() if item.get("type") == "route"]
    assert route["cableRise"] == [True, False]                               # the collimator end rises, the spool end lies


def _cable_rise(points, at_start, beam_y, bench_y):
    import json
    import re
    import shutil
    import subprocess

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    html = ThreeJsRenderer(optodraw.Scene(width=60, height=40, platform="free_space")).render()
    source = re.search(r"function odCableRise\(pts, atStart, beamY, benchY\) \{.*?\n\}", html, re.S).group(0)
    script = f"{source}\nconsole.log(JSON.stringify(odCableRise({json.dumps(points)}, {str(at_start).lower()}, {beam_y}, {bench_y})));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


@pytest.mark.parametrize("at_start", [True, False])
def test_a_rising_cable_leaves_its_connector_level_and_comes_down_to_the_table(at_start):
    run = [[0.0, 2.2, 0.0], [30.0, 2.2, 0.0], [60.0, 2.2, 10.0]]
    path = _cable_rise(run if at_start else run[::-1], at_start, 16.0, 2.2)
    path = path if at_start else path[::-1]                                  # read from the raised end
    assert path[0] == pytest.approx([0.0, 16.0, 0.0])                        # at the connector, at the beam height
    assert path[1][1] == pytest.approx(16.0) and path[1][0] > 0.0            # straight out of it, along the route
    assert path[-1] == pytest.approx([60.0, 2.2, 10.0])                      # the far end untouched
    heights = [p[1] for p in path]
    assert all(a >= b - 1e-9 for a, b in zip(heights, heights[1:]))          # it only comes down
    assert min(heights) == pytest.approx(2.2)                                # and lies on the table
