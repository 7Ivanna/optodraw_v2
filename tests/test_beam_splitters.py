"""One coated plate for beam splitters, partial reflectors and dichroics, told apart from a full mirror.

A partial reflector (a recycling or input mirror of an interferometer, a laser output coupler) is a plate beam
splitter used at normal incidence with its own split; a dichroic is the same plate with a colour coating.
"""

from __future__ import annotations


import optodraw


def _solids(node):
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _solids(child)
    else:
        yield node


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
