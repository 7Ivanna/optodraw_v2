"""A ring heater sits on its ring and leaves between or away from the buses: no heater metal, pad or via
runs along or across a bus waveguide. Review: the heater ran round the outside of the ring, along both buses
of an add-drop ring, and its leads crossed the through bus to pads under it."""

import pytest
from shapely.geometry import Polygon, box

from optodraw import (CoupledRingFilter, MicroringResonator, MicroringWeightBank, PNMicroringModulator,
                      RacetrackResonator)
from optodraw.components.onchip.geometry import GOLD, TIN, VIA

METAL = {GOLD, TIN, VIA, "#e7c069"}                       # heater, pad, via and pad finish


def _leaves(node):
    if node.get("type") == "group":
        for child in node["children"]:
            yield from _leaves(child)
    else:
        yield node


def _shape(node):
    if node["type"] == "rect":
        return box(node["cx"] - node["w"] / 2, node["cy"] - node["h"] / 2, node["cx"] + node["w"] / 2, node["cy"] + node["h"] / 2)
    return Polygon([point[:2] for point in node["points"]]).buffer(0)


def _buses_and_metal(part):
    """The straight bus waveguides (long, one guide tall, in the part's colour) and every metal shape."""

    buses, metal = [], []
    for node in _leaves(part.geometry_2d()):
        if node["type"] not in ("rect", "polygon"):
            continue
        shape = _shape(node)
        x0, y0, x1, y1 = shape.bounds
        if node["fill"] == part.color and y1 - y0 < 2.0 and x1 - x0 > 10.0:
            buses.append(shape)
        elif node["fill"] in METAL:
            metal.append(shape)
    return buses, metal


@pytest.mark.parametrize("part, bus_count", [
    (MicroringResonator(add_drop=True, with_heater=True), 2),
    (MicroringResonator(with_heater=True), 1),
    (MicroringResonator(add_drop=True, with_heater=True, ring_radius=6.0, heater_pad_size=3.0), 2),
    (RacetrackResonator(add_drop=True, with_heater=True), 2),
    (RacetrackResonator(with_heater=True), 1),
    (PNMicroringModulator(add_drop=True), 2),
    (PNMicroringModulator(), 1),
    (MicroringWeightBank(ring_count=3, with_heaters=True), 3),        # through, drop and output buses
    (CoupledRingFilter(order=3, with_heaters=True), 2),
    (CoupledRingFilter(order=2, ring_shape="racetrack", with_heaters=True), 2),
], ids=lambda value: type(value).__name__ + ("-drop" if getattr(value, "add_drop", False) else "")
    if not isinstance(value, int) else str(value))
def test_no_heater_metal_runs_along_or_across_a_bus(part, bus_count):
    buses, metal = _buses_and_metal(part)
    assert len(buses) == bus_count and metal
    hits = [shape.bounds for shape in metal if any(shape.intersects(bus) for bus in buses)]
    assert hits == [], hits


