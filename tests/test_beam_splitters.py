"""One coated plate for beam splitters, partial reflectors and dichroics, told apart from a full mirror.

A partial reflector (a recycling or input mirror of an interferometer, a laser output coupler) is a plate beam
splitter used at normal incidence with its own split; a dichroic is the same plate with a colour coating.
"""

from __future__ import annotations

import math

import optodraw
from optodraw.symbols import lookup


def _solids(node):
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _solids(child)
    else:
        yield node


def _coating(part):
    """The coating disc of a plate: the thinnest solid across the beam axis."""

    discs = [s for s in _solids(part.geometry_3d()) if s.get("shape") == "cylinder"]
    return min(discs, key=lambda s: float(s.get("height", 1e9)))["material"]


def test_a_plate_has_a_port_on_each_face_for_normal_incidence():
    plate = optodraw.BeamSplitter(thickness=0.7)
    ports = plate.ports()
    assert {"in", "trans", "refl", "tap", "front", "back"} <= set(ports)
    assert ports["front"].center.x < 0 < ports["back"].center.x
    assert math.isclose(ports["front"].orientation_deg % 360, 180) and math.isclose(ports["back"].orientation_deg % 360, 0)
    assert math.isclose(abs(ports["front"].center.x), 0.35) and ports["front"].center.y == 0


def test_a_beam_through_a_partial_reflector_at_normal_incidence_uses_its_faces():
    scene = optodraw.Scene(platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-30, 0)))
    mirror = scene.add(optodraw.BeamSplitter(center=(0, 0), angle=180, transmission=3, label="Power recycling"))
    detector = scene.add(optodraw.Photodiode(center=(30, 0)))
    beam = scene.add(optodraw.Beam.through(laser, mirror, detector))
    used = [anchor[1] for anchor in beam.anchors if isinstance(anchor, tuple) and anchor[0] is mirror]
    assert sorted(used) == ["back", "front"]
    ys = [point[1] for point in beam.resolve_points()]
    assert max(ys) - min(ys) < 1e-6                         # straight through: no kink at the plate


def test_the_coating_looks_more_like_a_mirror_as_the_reflectance_rises():
    opacity = [_coating(optodraw.BeamSplitter(transmission=t))["opacity"] for t in (90, 50, 3)]
    assert opacity[0] < opacity[1] < opacity[2]


def test_a_plate_is_clear_glass_not_a_dark_block():
    for part in (optodraw.BeamSplitter(), optodraw.BeamSplitter(dichroic=True)):
        substrate = max((s for s in _solids(part.geometry_3d()) if s.get("shape") == "cylinder"),
                        key=lambda s: float(s.get("radius", 0)) * float(s.get("height", 0)))
        assert substrate["material"].get("transparent") and substrate["material"].get("opacity", 1) < 0.6


def test_a_dichroic_coating_has_its_own_colour():
    assert _coating(optodraw.BeamSplitter(dichroic=True))["color"] != _coating(optodraw.BeamSplitter())["color"]


def test_a_dichroic_mirror_is_the_dichroic_plate():
    dichroic = optodraw.DichroicMirror(cutoff_wavelength=600)
    assert isinstance(dichroic, optodraw.BeamSplitter) and dichroic.dichroic
    assert set(dichroic.ports()) == set(optodraw.BeamSplitter().ports())
    symbol = lookup(dichroic)
    assert (symbol.name, symbol.params, symbol.source) == ("platesplitter", {"kind": "dichroic"}, "prebuilt")


def test_a_plate_symbol_carries_the_face_ports():
    symbol = lookup(optodraw.BeamSplitter())
    assert symbol.source == "prebuilt" and {"front", "back"} <= set(symbol.ports)


def test_a_partial_mirror_is_a_part_people_can_find():
    """People look for a partial mirror by that name: it is the coated plate at normal incidence."""

    from optodraw.registry import component_registry

    spec = component_registry()["PartialMirror"]
    assert "partial" in spec.description.lower() and "transmission" in spec.parameters
    mirror = optodraw.PartialMirror(transmission=3, label="Output coupler")
    assert isinstance(mirror, optodraw.BeamSplitter) and not mirror.dichroic and mirror.transmission == 3
    assert {"front", "back"} <= set(mirror.ports())
    symbol = lookup(mirror)
    assert (symbol.name, symbol.source) == ("partialmirror", "prebuilt")


def test_a_saved_partial_mirror_keeps_its_transmission():
    from optodraw.schema import component_from_spec, component_to_spec

    again = component_from_spec(component_to_spec(optodraw.PartialMirror(center=(4, 2), angle=90, transmission=1.4)))
    assert type(again).__name__ == "PartialMirror" and again.transmission == 1.4


def test_a_partial_mirror_stands_across_its_beam_in_1d_and_the_splitter_stays_diagonal():
    from optodraw.symbols.schematic import build_schematic

    scene = optodraw.Scene(platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-40, 0)))
    coupler = scene.add(optodraw.PartialMirror(center=(-20, 0), angle=180, transmission=3, label="PRM"))
    plate = scene.add(optodraw.BeamSplitter(center=(-5, 0), angle=180, transmission=20, label="plate"))
    splitter = scene.add(optodraw.BeamSplitter(center=(10, 0), angle=45, label="BS"))
    detector = scene.add(optodraw.Photodiode(center=(30, 0)))
    side = scene.add(optodraw.Photodiode(center=(10, 20), angle=-90))
    scene.add(optodraw.Beam.through(laser, coupler, plate, splitter, detector))
    scene.add(optodraw.Beam.through(splitter, side))
    names = {item.label: item.symbol.name for item in build_schematic(scene).items if item.label in ("PRM", "plate", "BS")}
    assert names == {"PRM": "partialmirror", "plate": "partialmirror", "BS": "platesplitter"}
