"""RingAssistedMZI: ports, ring placement, geometry, animation numbers, round trip."""

from __future__ import annotations

import cmath
import json
import math

import numpy as np
import pytest

import optodraw
from optodraw import RingAssistedMZI, Scene
from optodraw.animation_engine.graph import build_graph
from optodraw.animation_engine.solver import propagate_pulses, steady_state
from optodraw.animation_engine.state import compile_signal_state
from optodraw.symbols import build as symbol_build

N_G = 4.2                      # group index of the engine for an optical port


def _scene(part, source_x=-160.0):
    """A laser into o1, a detector on each right-hand port; detectors are numbered 1 (o3) and 2 (o4)."""

    scene = Scene(width=500, height=200, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(source_x, 0)))
    placed = scene.add(part)
    d3 = scene.add(optodraw.OnChipPhotodetector(center=(190, 40)))
    d4 = scene.add(optodraw.OnChipPhotodetector(center=(190, -40)))
    scene.route((laser, "o1"), (placed, "o1"), kind="waveguide")
    scene.route((placed, "o3"), (d3, "o1"), kind="waveguide")
    scene.route((placed, "o4"), (d4, "o1"), kind="waveguide")
    return scene


def _powers(scene, wavelength=1550.0, params=None):
    result = steady_state(build_graph(scene), {"wavelength": wavelength, **(params or {})})
    by = {hit["part"]: hit["power"] for hit in result.absorbed}
    return by.get("onchipphotodetector1", 0.0), by.get("onchipphotodetector2", 0.0)     # o3, o4


def _ring_response(part, k, wavelength_nm, extra_phase=0.0):
    """The all-pass response of ring k with the numbers the behaviour uses."""

    kappa = part.ring_power_coupling(k)
    t, a = math.sqrt(1.0 - kappa), part.round_trip_amplitude
    z = a * cmath.exp(1j * (2.0 * math.pi * N_G * 2.0 * math.pi * part.ring_radius / (wavelength_nm / 1000.0) + extra_phase))
    return (t - z) / (1.0 - t * z)


# ---------------------------------------------------------------- ports


def test_the_ports_follow_the_mzi():
    ramzi, mzi = RingAssistedMZI(rings_per_arm=(0, 0), arm_length=48.0, arm_gap=14.0), optodraw.MZI()
    for name in ("o1", "o2", "o3", "o4"):
        port, ref = ramzi.ports()[name], mzi.ports()[name]
        assert (port.center.x, port.center.y, port.orientation_deg) == pytest.approx((ref.center.x, ref.center.y, ref.orientation_deg))
        assert port.kind == "optical"
    assert {n for n, p in ramzi.ports().items() if p.kind == "electrical"} == {"h1", "h2"}


@pytest.mark.parametrize("bad", [dict(rings_per_arm=(1,)), dict(rings_per_arm=(-1, 0)), dict(coupler="y"),
                                 dict(rings_per_arm=(1, 1), ring_gap=[0.2])])
def test_bad_arguments_are_named_errors(bad):
    with pytest.raises(ValueError):
        RingAssistedMZI(**bad)


# ---------------------------------------------------------------- ring placement


# ---------------------------------------------------------------- geometry


def _polygons(node):
    if node.get("type") == "polygon":
        yield node["points"]
    for child in node.get("children", []):
        yield from _polygons(child)


@pytest.mark.parametrize("coupler", ["dc", "mmi"])
def test_the_physical_drawing_reaches_the_ports_and_holds_every_ring(coupler):
    part = RingAssistedMZI(rings_per_arm=(1, 1), coupler=coupler, render_physical=True)
    polygons = list(_polygons(part.geometry_2d()))
    xs = [x for poly in polygons for x, _, _ in poly]
    assert max(xs) == pytest.approx(part.ports()["o3"].center.x, abs=0.05)
    assert min(xs) == pytest.approx(part.ports()["o1"].center.x, abs=0.05)
    ring_tops = [max(y for _, y, _ in poly) for poly in polygons]
    ring = part.ring_layout()[0]
    assert any(top == pytest.approx(ring["y"] + part.ring_radius + part.waveguide_width / 2.0, abs=0.01) for top in ring_tops)
    assert min(y for poly in polygons for _, y, _ in poly) < -part.arm_gap / 2.0 - 2.0 * part.ring_radius      # the bottom ring


@pytest.mark.parametrize("coupler", ["dc", "mmi"])
@pytest.mark.parametrize("rings", [(1, 0), (1, 1)])
def test_3d_has_the_silicon_the_rings_and_the_metal(rings, coupler):
    part = RingAssistedMZI(rings_per_arm=rings, coupler=coupler, render_physical=True)
    solids = part.geometry_3d()["children"]
    assert all(s["shape"] in ("extruded_polygon", "box") for s in solids)
    silicon = [s for s in solids if s["shape"] == "extruded_polygon" and s.get("position") is None]
    metal = [s for s in solids if s["shape"] == "extruded_polygon" and s.get("position") is not None]
    assert len(metal) == 1 + sum(rings)                                         # the arm heater and one per ring
    assert len(silicon) == len(part._silicon_polygons()) + sum(rings)
    vias = [s for s in solids if s["shape"] == "box"]
    want = 2 * (1 + sum(rings)) if part._draw_layer_stack()["via_height"] > 0 else 0   # no via layer, no via
    assert len(vias) == want
    # the metal stands on the silicon layer, not inside it
    assert all(s["position"][1] >= max(si["height"] for si in silicon) - 1e-9 for s in metal)


# ---------------------------------------------------------------- animation


@pytest.mark.parametrize("rings, coupler", [((1, 0), "dc"), ((1, 1), "mmi"), ((2, 1), "dc"), ((2, 1), "mmi")])
def test_continuous_light_passes_the_passivity_check_and_keeps_power(rings, coupler):
    state = compile_signal_state(_scene(RingAssistedMZI(center=(0, 0), rings_per_arm=rings, coupler=coupler)), mode="cw",
                                 params={"wavelength": 1552.32}).to_json()
    total = sum(hit["power"] for hit in state["absorbed"])
    assert 0.0 < total <= 1.0 + 1e-9


def test_a_pulse_rings_down_round_the_ring_and_nothing_is_created():
    scene = _scene(RingAssistedMZI(center=(0, 0), rings_per_arm=(1, 0)))
    result = propagate_pulses(build_graph(scene))
    loops = sorted((p for p in result.packets if "_r1f->_r1f" in p.edge), key=lambda p: p.t0_ps)
    powers = [float(np.sum(np.abs(p.jones) ** 2)) for p in loops]
    assert len(loops) > 3 and all(b < a for a, b in zip(powers, powers[1:]))
    assert sum(hit["power"] for hit in result.absorbed) <= 1.0 + 1e-9


def test_light_from_the_right_goes_through_the_same_rings():
    part = RingAssistedMZI(center=(0, 0), rings_per_arm=(2, 1), ring_gap=(0.15, 0.2, 0.3))
    scene = Scene(width=500, height=200, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(190, 0)))
    placed = scene.add(part)
    d1 = scene.add(optodraw.OnChipPhotodetector(center=(-160, 40)))
    d2 = scene.add(optodraw.OnChipPhotodetector(center=(-160, -40)))
    scene.route((laser, "o1"), (placed, "o4"), kind="waveguide")        # in at the lower right port
    scene.route((placed, "o1"), (d1, "o1"), kind="waveguide")
    scene.route((placed, "o2"), (d2, "o1"), kind="waveguide")
    for wavelength in (1550.0, 1552.3):
        h = [_ring_response(part, k, wavelength) for k in (1, 2, 3)]
        result = steady_state(build_graph(scene), {"wavelength": wavelength})
        by = {hit["part"]: hit["power"] for hit in result.absorbed}
        assert sum(by.values()) <= 1.0 + 1e-9
        assert by["onchipphotodetector2"] == pytest.approx(abs(h[0] * h[1] - h[2]) ** 2 / 4, abs=1e-9)
        assert by["onchipphotodetector1"] == pytest.approx(abs(h[0] * h[1] + h[2]) ** 2 / 4, abs=1e-9)


def test_a_turned_part_has_the_same_response():
    flat, turned = RingAssistedMZI(rings_per_arm=(1, 1)), RingAssistedMZI(rings_per_arm=(1, 1), angle=90)
    behaviour = optodraw.animation_engine.behaviours.behaviour_for(flat, "r1")
    a = {(t.out_port, t.name): t.matrix for t in behaviour.transfers(flat, "r1", "o1", 1550.0, {})}
    b = {(t.out_port, t.name): t.matrix for t in behaviour.transfers(turned, "r1", "o1", 1550.0, {})}
    assert a.keys() == b.keys() and all(np.allclose(a[k], b[k]) for k in a)


# ---------------------------------------------------------------- catalog, round trip, symbol


@pytest.mark.parametrize("kwargs", [
    dict(),
    dict(rings_per_arm=(2, 1), ring_gap=(0.15, 0.2, 0.3), coupler="mmi", ring_radius=8.0, arm_length=70.0, arm_gap=16.0),
    dict(rings_per_arm=(0, 2), with_heaters=False),
    dict(rings_per_arm=(1, 1), render_physical=True),
])
def test_a_scene_round_trip_keeps_every_parameter(kwargs):
    scene = Scene(width=300, height=200, platform="on_chip")
    scene.add(RingAssistedMZI(center=(10, 5), **kwargs))
    spec = json.loads(json.dumps(scene.to_spec()))
    again = Scene.from_spec(spec)
    (part,) = [p for p in again.walk() if isinstance(p, RingAssistedMZI)]
    (first,) = [p for p in scene.walk() if isinstance(p, RingAssistedMZI)]
    for name in ("rings_per_arm", "ring_radius", "ring_gap", "arm_length", "arm_gap", "coupler", "with_heaters", "render_physical"):
        assert getattr(part, name) == getattr(first, name), name
    assert part.ports().keys() == first.ports().keys()
    assert again.to_spec() == scene.to_spec()


def test_the_symbol_request_names_a_row_of_the_variant_table():
    rows = symbol_build.load_table(symbol_build.HERE / "variants.toml")
    slugs = {symbol_build.slug(row["symbol"], row["params"]) for row in rows}
    for rings in ((1, 0), (1, 1), (2, 1)):
        name, params = RingAssistedMZI(rings_per_arm=rings).symbol_1d()
        assert symbol_build.slug(name, params) in slugs, rings
    assert RingAssistedMZI(with_heaters=False).symbol_1d()[1]["bare"] is True
    assert RingAssistedMZI(coupler="mmi").symbol_1d()[1]["splitter"] == "mmi2x2"


def test_every_variant_row_matches_the_ports_of_its_part():
    rows = [r for r in symbol_build.load_table(symbol_build.HERE / "variants.toml") if r.get("component") == "RingAssistedMZI"]
    assert len(rows) == 3
    for row in rows:
        assert {n for n in symbol_build.component_ports(row["component"], row["args"])} >= {"o1", "o2", "o3", "o4", "h1", "h2"}


def test_the_timeline_has_both_arm_guides_the_ring_loops_and_the_heat():
    from optodraw import Waveguide, route_ports
    from optodraw.core.timeline3d import anim_payload_map

    scene = Scene(platform="on_chip")
    wg = scene.add(Waveguide(center=(-90, 0)))
    part = scene.add(RingAssistedMZI(center=(0, 0), rings_per_arm=(1, 1)))
    scene.add(route_ports((wg, "o2"), (part, "o1")))
    payload = anim_payload_map(scene)[id(part)]
    assert len(payload["guides"]) == 4                                           # two arms and two ring loops
    assert len(payload["heat"]["paths"]) == 3                                    # the arm heater and each ring heater
    drawn = part._draw_variant()
    assert payload["heat"]["paths"][0]["pts"][0][1] == pytest.approx(drawn.arm_gap / 2.0)
    bare = RingAssistedMZI(rings_per_arm=(1, 0), with_heaters=False)
    scene2 = Scene(platform="on_chip")
    scene2.add(bare)
    assert "heat" not in (anim_payload_map(scene2).get(id(bare)) or {})
