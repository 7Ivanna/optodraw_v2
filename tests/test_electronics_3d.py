"""Electronics in 3D: every block reads as a packaged chip, with its mark on the lid and metal at its ports."""

from __future__ import annotations

import pytest

from optodraw.registry import build_component


def _shapes(node):
    yield node
    for child in node.get("children", []):
        yield from _shapes(child)


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


GOLDS = {"#d4af37", "#d6a43a"}


@pytest.mark.parametrize("name, label", [("TIA", "TIA"), ("ADC", "ADC"), ("DACDriver", "DAC")])
def test_an_on_chip_electronic_block_is_a_dark_die_with_its_mark_and_pads(name, label):
    """They were light grey slabs at chip height with hairline marks: ghosts on the die."""

    part = build_component(name, label="")
    shapes = list(_shapes(part.geometry_3d()))
    assert any(s.get("shape") == "text_decal" and s.get("text") == label for s in shapes)
    bodies = [s for s in shapes if s.get("shape") == "box" and s["width"] >= part.length * 0.9]
    assert bodies and min(_luminance(s["material"]["color"]) for s in bodies) < 0.3
    assert max(s["height"] for s in bodies) > 1.0                           # a die stands above the waveguides
    golds = [s for s in shapes if (s.get("material") or {}).get("color", "").lower() in GOLDS]
    for port in part.ports().values():
        assert any(abs(g["position"][0] - port.center.x) <= part.pad_size and
                   abs(g["position"][2] + port.center.y) <= part.pad_size for g in golds), (name, port.name)


@pytest.mark.parametrize("name, labels", [("CoherentReceiver", {"90°", "I", "Q"}),
                                          ("ReceiverMacro", {"TIA", "ADC"}),
                                          ("TransmitterMacro", {"DAC", "DRV", "MOD"})])
def test_a_macro_is_a_module_with_its_labelled_dies_standing_on_it(name, labels):
    """The macros were flat navy plates with pale shapes a few tenths high: nothing read as a part."""

    part = build_component(name, label="")
    shapes = list(_shapes(part.geometry_3d()))
    assert labels <= {s.get("text") for s in shapes if s.get("shape") == "text_decal"}
    tops = [s["position"][1] + s["height"] / 2.0 for s in shapes if s.get("shape") == "box"]
    assert max(tops) > 1.8                                                   # the dies stand on the carrier
    golds = [s for s in shapes if (s.get("material") or {}).get("color", "").lower() in GOLDS]
    for port in part.ports().values():
        if port.kind == "electrical":
            assert any(abs(g["position"][0] - port.center.x) <= part.pad_size * 1.5 and
                       abs(g["position"][2] + port.center.y) <= part.pad_size * 1.5 for g in golds), (name, port.name)
