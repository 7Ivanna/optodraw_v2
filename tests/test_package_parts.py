"""The package set: wire bonds, a fibre array, an edge-launch SMA jack and a plain board.

A wire bond is a route kind: an arc from pad to pad in 2D, a gold loop from pad top to pad top in 3D, an electrical
link in 1D. The fibre array and the SMA jack are parts with ports on their 1D and 2D art, a clean 3D model and a
catalog entry that saves and loads. A plain board draws its outline in its own colour and its edge pads, no traces.
"""

from __future__ import annotations


import pytest

from optodraw import ChipSubstrate, ElectricalPad, PCB, Scene
from optodraw.check import solid_boxes
from optodraw.symbols.schematic import build_schematic

PARTS = {"FiberArray": ({f"o{i}" for i in range(1, 9)}, "fiber"), "SMAConnector": ({"e1"}, "electrical")}
SIZES = [("FiberArray", {}), ("FiberArray", {"count": 4, "pitch": 0.5}), ("SMAConnector", {})]


def _bonded(chip: bool = False):
    """Two pads and a bond from the first to the second; on a die when ``chip``, so the 3D page lifts the pads."""

    scene = Scene(width=80, height=50, platform="mixed")
    if chip:
        scene.add(ChipSubstrate(center=(-10, 4), length=40, width=20, label="PIC"))
    a = scene.add(ElectricalPad(center=(-8, 3), width=3.2, height=3.2, label="A"))
    b = scene.add(ElectricalPad(center=(-22, 5), width=3.2, height=3.2, label="B"))
    return scene, a, b, scene.route((a, "e1"), (b, "e1"), kind="wirebond")


def _top(geometry: dict) -> float:
    return max(box[1][1] for _, box in solid_boxes(geometry))


# ---------------------------------------------------------------- wire bond


def test_a_wire_bond_is_an_electrical_link_in_1d():
    # mutant: kwargs["kind"] = "wirebond" in WireBond.__init__: the 1D view draws the bond as light
    scene, *_ = _bonded()
    assert [(link.kind, link.electrical) for link in build_schematic(scene).links] == [("electrical", True)]


# ---------------------------------------------------------------- fibre array, SMA jack


# ---------------------------------------------------------------- plain board


def test_a_plain_board_saves_and_loads_with_its_style_and_colour():
    # mutant: drop "style" from the PCB row of _BUILTIN_METADATA: the board loads with its traces again
    scene = Scene(width=120, height=80, platform="mixed")
    scene.add(PCB(style="plain", color="#1e5a8a"))
    again = next(item for item in Scene.from_spec(scene.to_spec()).walk() if type(item).__name__ == "PCB")
    assert (again.style, again.color) == ("plain", "#1e5a8a")
    with pytest.raises(ValueError, match="plain"):
        PCB(style="fancy")
