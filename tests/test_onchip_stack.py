"""Every on-chip part follows one open process stack (GDSFactory generic) unless its scene sets a foundry stack.

The 3D solids of a part may start only on a level of that stack: the buried oxide (silicon), the top of the
slab (a contact), the top of a contact, a metal, the heater or the pad; germanium and the oxide over a core also
on the core top. A solid that starts anywhere else floats or sinks: metal laid straight on the core, a rib hung in
the air.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from optodraw.components.onchip.layer_stack import DEFAULT_HEIGHTS, component_stack
from optodraw.registry import build_component, component_registry

# Parts that are not a process layer on the die: flip-chip dies on top, the die itself, imported layouts, and a
# preset group (its parts are tested one by one).
_NOT_ON_THE_STACK = {"TIA", "ADC", "DACDriver", "ChipSubstrate", "GDSModel", "CustomModel", "Route", "PresetWDMInput"}
# A laser's III-V gain stack is bonded above the silicon process: it stacks on its own mesa.
_BONDED = {"indium_phosphide", "gallium_arsenide"}
# GE starts on the core top (the stack's zmin 0.220 on a 0.220 core), and so do the oxide and a GST film over a core.
_ON_THE_CORE = {"germanium", "sio2", "gst"}
_VARIANTS = {
    "MicroringResonator": [{"with_heater": True}, {"with_heater": True, "add_drop": True}],
    "MZM": [{"mechanism": "thermo_optic"}, {"drive_style": "gsg"}],
    "PhaseShifter": [{"mechanism": "thermo_optic"}, {"mechanism": "pn"}],
    "RacetrackResonator": [{"with_heater": True}],
}


def test_the_default_heights_are_the_bundled_gdsfactory_generic_stack():
    pytest.importorskip("yaml")
    from optodraw.gds.parsers import load_layer_stack

    stack = load_layer_stack(str(files("optodraw.gds") / "stacks" / "gdsfactory_generic.yaml"))
    assert stack.component_heights() == pytest.approx(DEFAULT_HEIGHTS)


def test_a_part_scales_the_stack_to_its_drawn_core():
    stack = component_stack(0.55)
    factor = 0.55 / DEFAULT_HEIGHTS["chip_thickness"]
    assert stack["core_height"] == 0.55
    assert stack["rib_height"] == pytest.approx(DEFAULT_HEIGHTS["rib_height"] * factor)
    assert stack["metal_z"] == pytest.approx(DEFAULT_HEIGHTS["metal_z"] * factor)
    assert stack["heater_z"] == pytest.approx(DEFAULT_HEIGHTS["heater_z"] * factor)


def _solids(node, z=0.0):
    """(shape, bottom, top, preset) of every solid, with the offsets of the groups above it."""

    position = node.get("position") or [0.0, 0.0, 0.0]
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _solids(child, z + float(position[1]))
        return
    height = float(node.get("height", 0.0) or 0.0)
    if node.get("shape") == "extruded_polygon":
        bottom = z + float(position[1])
    else:                                            # a box or a cylinder is placed by its centre
        bottom = z + float(position[1]) - height / 2.0
    yield node.get("shape"), bottom, bottom + height, (node.get("material") or {}).get("preset", "")


def _parts():
    out = []
    for name, spec in sorted(component_registry().items()):
        if spec.category != "on_chip" or name in _NOT_ON_THE_STACK:
            continue
        for kwargs in [{}] + _VARIANTS.get(name, []):
            out.append(pytest.param(name, kwargs, id=f"{name}-{'-'.join(kwargs) or 'default'}"))
    return out


@pytest.mark.parametrize("name, kwargs", _parts())
def test_every_solid_of_an_onchip_part_starts_on_a_level_of_the_stack(name, kwargs):
    part = build_component(name, **kwargs)
    stack = part._draw_layer_stack()
    levels = {0.0, stack["contact_z"], stack["contact_z"] + stack["contact_height"], stack["via_z"],
              stack["metal_z"], stack["metal_z"] + stack["metal_height"], stack["heater_z"],
              stack["heater_z"] + stack["heater_height"], stack["pad_z"], stack["pad_z"] + stack["pad_height"]}
    top = max(stack["pad_z"] + stack["pad_height"], stack["metal_z"] + stack["metal_height"],
              stack["heater_z"] + stack["heater_height"])
    tolerance = 1e-6 + 1e-3 * top
    wrong = []
    for shape, bottom, end, preset in _solids(part.geometry_3d()):
        if end - bottom <= tolerance or preset in _BONDED:
            continue                                   # an empty solid draws nothing
        allowed = levels | {stack["core_z"] + stack["core_height"]} if preset in _ON_THE_CORE else levels
        if not any(abs(bottom - level) <= tolerance for level in allowed):
            wrong.append(f"{shape} {preset or '?'} starts at {bottom:.3f}")
        elif end > top + 0.25 * stack["pad_height"] + tolerance:     # a thin finish may sit on a pad
            wrong.append(f"{shape} {preset or '?'} reaches {end:.3f} above the pad top {top:.3f}")
    assert not wrong, f"{name} {kwargs}: " + "; ".join(sorted(set(wrong))[:6])


def _boxes(node, z=0.0):
    """(centre x, centre y, half x, half y, bottom, top, preset) of every box, with group offsets."""

    position = node.get("position") or [0.0, 0.0, 0.0]
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _boxes(child, z + float(position[1]))
    elif node.get("shape") == "box":
        height = float(node.get("height", 0.0))
        bottom = z + float(position[1]) - height / 2.0
        yield (float(position[0]), -float(position[2]), float(node["width"]) / 2.0, float(node["depth"]) / 2.0,
               bottom, bottom + height, (node.get("material") or {}).get("preset", ""))


@pytest.mark.parametrize("name, kwargs", _parts())
def test_every_raised_pad_is_reached_by_a_small_via_on_metal(name, kwargs):
    """A pad stood on a via that ended in the oxide (the M1 stub stopped at the pad's edge, the via sat under
    its centre); then a plate the pad's size and a via block nearly as big filled the space under it, a heavy
    block. The route is a small via where the trace reaches the pad, standing on the trace's layer."""

    part = build_component(name, **kwargs)
    stack = part._draw_layer_stack()
    tolerance = 1e-6 + 1e-3 * (stack["pad_z"] + stack["pad_height"])
    if stack["pad_z"] <= stack["metal_z"] + stack["metal_height"] + tolerance:
        pytest.skip("the pads sit on the metal")
    boxes = list(_boxes(part.geometry_3d()))
    pads = [b for b in boxes if abs(b[4] - stack["pad_z"]) <= tolerance and b[6] == "gold"]
    vias = [b for b in boxes if b[6] == "copper" and abs(b[5] - stack["pad_z"]) <= 0.05 * stack["pad_height"] + tolerance]
    metal = [b for b in boxes if b[6] in {"gold", "titanium_nitride"} and b[4] < stack["pad_z"] - tolerance]   # a heater pad lands on TiN
    for x, y, hx, hy, *_ in pads:
        under = [v for v in vias if abs(v[0] - x) <= hx and abs(v[1] - y) <= hy]
        assert under, f"{name} {kwargs}: the pad at ({x:.2f}, {y:.2f}) has no via"
        assert all(v[2] <= 0.3 * hx + 1e-6 and v[3] <= 0.3 * hy + 1e-6 for v in under), f"{name}: a via block under the pad"
        for vx, vy, vhx, vhy, bottom, *_ in under:
            assert any(abs(m[0] - vx) <= m[2] and abs(m[1] - vy) <= m[3] and abs(m[5] - bottom) <= tolerance
                       for m in metal), f"{name} {kwargs}: the via under ({x:.2f}, {y:.2f}) stands on no metal"
        plates = [m for m in metal if abs(m[0] - x) < 0.2 * hx and abs(m[1] - y) < 0.2 * hy
                  and m[2] >= 0.8 * hx and m[3] >= 0.8 * hy]
        assert not plates, f"{name} {kwargs}: a plate the pad's size under the pad at ({x:.2f}, {y:.2f})"


def test_moving_a_3d_layout_moves_each_solid_once():
    """An extruded solid with a position (metal at its height) moved twice, by its points and by its position;
    a tube path's height moved instead of its z."""

    from optodraw.components.onchip.geometry import _mirror_layout_geometry_y, _translate_layout_geometry

    rail = {"shape": "extruded_polygon", "points": [(0, 0), (2, 0), (2, 1)], "holes": [[(0.5, 0.2), (1, 0.2), (1, 0.5)]],
            "height": 0.4, "position": [0.0, 1.1, 0.0]}
    box = {"shape": "box", "width": 1, "height": 1, "depth": 1, "position": [1.0, 2.0, 3.0]}
    wire = {"shape": "tube_path", "points": [(0.0, 1.0, 0.0), (4.0, 2.0, -1.0)], "radius": 0.1}
    group = {"shape": "group", "children": [rail, box, wire]}
    moved = _translate_layout_geometry(group, 10.0, 5.0)["children"]
    assert moved[0]["points"] == [(10.0, 5.0), (12.0, 5.0), (12.0, 6.0)] and moved[0]["position"] == [0.0, 1.1, 0.0]
    assert moved[0]["holes"][0][0] == (10.5, 5.2)
    assert moved[1]["position"] == [11.0, 2.0, -2.0]
    assert moved[2]["points"] == [(10.0, 1.0, -5.0), (14.0, 2.0, -6.0)]
    flipped = _mirror_layout_geometry_y(group)["children"]
    assert flipped[2]["points"] == [(0.0, 1.0, 0.0), (4.0, 2.0, 1.0)]                 # z flips, the height stays
    assert flipped[1]["position"] == [1.0, 2.0, -3.0]


def test_a_composed_modulator_draws_its_3d_metal_where_its_2d_metal_is():
    """The IQ modulator's MZM electrodes stood far from the arms in 3D."""

    from optodraw.registry import build_component

    def centres_2d(node):
        if node.get("type") == "group":
            for child in node.get("children", []):
                yield from centres_2d(child)
        elif str(node.get("fill", "")).lower() == "#d4af37":            # gold: the metal of the drawing
            if node.get("points"):
                xs, ys = [p[0] for p in node["points"]], [p[1] for p in node["points"]]
                yield ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
            elif "cx" in node:
                yield (float(node["cx"]), float(node["cy"]))

    def centres_3d(node):
        if node.get("shape") == "group":
            for child in node.get("children", []):
                yield from centres_3d(child)
        elif node.get("shape") == "extruded_polygon" and (node.get("material") or {}).get("preset") in ("gold", "titanium_nitride"):
            xs, ys = [p[0] for p in node["points"]], [p[1] for p in node["points"]]
            px, _, pz = node.get("position") or [0.0, 0.0, 0.0]               # the viewer adds the position
            yield ((min(xs) + max(xs)) / 2.0 + px, (min(ys) + max(ys)) / 2.0 - pz)

    part = build_component("IQModulator")
    flat = list(centres_2d(part.geometry_2d()))
    solid = list(centres_3d(part.geometry_3d()))
    assert flat and solid
    for x, y in solid:
        assert min(abs(x - a) + abs(y - b) for a, b in flat) < 2.0, f"3D metal at ({x:.1f}, {y:.1f}) has no 2D metal there"


@pytest.mark.parametrize("name, kwargs", _parts())
def test_every_pad_stack_reaches_a_trace_or_an_electrode(name, kwargs):
    """Leads stopped short of the pad plates (laser, comb, SOA): each pad stack stood alone on the oxide."""

    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_free_space_parts_3d import _world_boxes

    part = build_component(name, **kwargs)
    stack = part._draw_layer_stack()
    metal = [b for s, b in _world_boxes(part.geometry_3d())
             if (s.get("material") or {}).get("preset") in ("gold", "copper", "titanium_nitride", "tungsten", "aluminum")]

    def touching(p, q, tol=1e-3):
        return all(p[k][0] <= q[k][1] + tol and q[k][0] <= p[k][1] + tol for k in range(3))

    for pad in [b for b in metal if abs(b[1][0] - stack["pad_z"]) < 1e-3]:
        group, grew = [pad], True
        while grew:
            grew = False
            for b in metal:
                if b not in group and any(touching(b, g) for g in group):
                    group.append(b)
                    grew = True
        outside = [b for b in group if b[0][0] < pad[0][0] - 1e-3 or b[0][1] > pad[0][1] + 1e-3
                   or b[2][0] < pad[2][0] - 1e-3 or b[2][1] > pad[2][1] + 1e-3]
        assert outside, f"{name} {kwargs}: a pad stack at x {pad[0][0]:.1f}..{pad[0][1]:.1f} reaches no trace"


def test_a_scene_pad_on_a_chip_is_reached_by_a_small_via_where_its_wire_lands():
    """A scene's ElectricalPad on a chip stands on the pad layer; a small via at each port, on a short landing
    from the port, takes the route up from the metal. A plate and a via block under the whole pad read as a
    heavy block."""

    import optodraw
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(platform="on_chip")
    scene.add(optodraw.OnChipPhotodetector())
    pad = scene.add(optodraw.ElectricalPad(center=(60, 0)))
    renderer = ThreeJsRenderer(scene)
    stack = renderer._chip_stack()
    boxes = list(_boxes(renderer._pad_on_the_stack(pad, pad.geometry_3d())))
    vias = [b for b in boxes if b[6] == "copper"]
    landings = [b for b in boxes if b[6] == "gold" and abs(b[4] - stack["metal_z"]) < 1e-6]
    assert len(vias) == len(pad.ports()) and all(max(b[2], b[3]) <= 0.3 * 16.0 for b in vias)
    assert landings and all(max(b[2], b[3]) < 0.5 * 32.0 for b in landings)
    for port in pad.ports().values():                    # each landing reaches its port
        px, py = port.center.x, port.center.y
        assert any(abs(px - b[0]) <= b[2] + 1e-6 and abs(py - b[1]) <= b[3] + 1e-6 for b in landings)


def test_a_heater_pad_on_a_chip_lays_its_heater_on_the_heater_layer_and_only_its_pads_up_top():
    """The whole HeaterPad was lifted to the pad layer: its heater meander hung at the top of the stack."""

    import optodraw
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    scene = optodraw.Scene(platform="on_chip")
    scene.add(optodraw.OnChipPhotodetector())
    heater = scene.add(optodraw.HeaterPad(center=(0, 60)))
    renderer = ThreeJsRenderer(scene)
    stack = renderer._chip_stack()
    boxes = list(_boxes(renderer._pad_on_the_stack(heater, heater.geometry_3d())))
    thin = [b for b in boxes if min(b[2], b[3]) < 1.0]                       # the meander's segments
    wide = [b for b in boxes if min(b[2], b[3]) > 3.0 and b[6] != "copper"]
    assert thin and all(abs(b[4] - stack["heater_z"]) < 1e-6 for b in thin)
    assert any(abs(b[4] - stack["pad_z"]) < 1e-6 for b in wide)


def _leaves(node):
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _leaves(child)
    elif node.get("shape") in {"box", "extruded_polygon"}:
        yield node


@pytest.mark.parametrize("name", ["OnChipPhotodetector", "OnChipBalancedPhotodetector", "AvalanchePhotodetector"])
def test_a_doped_strip_in_a_detector_fills_its_silicon_to_the_top(name):
    """The cut that stops the flicker left each doped strip at slab height in a hole of the full-height silicon, a
    trench in the 3D view. An implant changes the silicon in place, so it reaches the top of the silicon it lies in."""

    import shapely

    from optodraw.components.onchip.geometry import _plan

    silicon = [(node, *_plan(node)) for node in _leaves(build_component(name).geometry_3d())
               if str((node.get("material") or {}).get("preset", "")).startswith("silicon")]
    core = (silicon[0][0].get("material") or {}).get("color")             # the input guide: the plain silicon
    regions = [(shapely.Polygon(plan.exterior), top) for node, plan, _, top in silicon
               if node["material"].get("color") == core]
    strips = [(plan, top) for node, plan, _, top in silicon if node["material"].get("color") != core]
    assert strips, f"{name} draws no doped silicon"
    for plan, top in strips:
        around = [high for region, high in regions if region.buffer(1e-6).contains(plan)]
        assert around and top == pytest.approx(max(around)), (name, plan.bounds, top, around)   # mutant: no raise
