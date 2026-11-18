"""Every on-chip part follows one open process stack (GDSFactory generic) unless its scene sets a foundry stack.

The 3D solids of a part may start only on a level of that stack: the buried oxide (silicon), the top of the
slab (a contact), the top of a contact, a metal, the heater or the pad; germanium and the oxide over a core also
on the core top. A solid that starts anywhere else floats or sinks: metal laid straight on the core, a rib hung in
the air.
"""

from __future__ import annotations


import pytest

from optodraw.registry import build_component, component_registry

from sweep import sweep

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


def _check_every_solid_of_an_onchip_part_starts_on_a_level_of_the_stack(name, kwargs):
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


def test_every_solid_of_an_onchip_part_starts_on_a_level_of_the_stack():
    sweep(_check_every_solid_of_an_onchip_part_starts_on_a_level_of_the_stack, _parts())


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


def _leaves(node):
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _leaves(child)
    elif node.get("shape") in {"box", "extruded_polygon"}:
        yield node


