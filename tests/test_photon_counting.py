"""Photon counting parts: a fibre-coupled single-photon counting module and a coincidence counter."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.schema import component_from_spec, component_to_spec
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d


def _kinds(part) -> dict[str, str]:
    return {name: port.kind for name, port in part.ports().items()}


def test_a_photon_counter_takes_a_fibre_and_gives_a_pulse_per_channel():
    part = optodraw.PhotonCounter(channels=4)
    ports = part.ports()
    assert sorted(ports) == sorted([f"fiber{i}" for i in range(1, 5)] + [f"pulse{i}" for i in range(1, 5)])
    assert all(ports[f"fiber{i}"].kind == "fiber" and ports[f"fiber{i}"].center.x < 0 for i in range(1, 5))
    assert all(ports[f"pulse{i}"].kind == "electrical" and ports[f"pulse{i}"].center.x > 0 for i in range(1, 5))
    heights = [ports[f"fiber{i}"].center.y for i in range(1, 5)]
    assert heights == sorted(heights, reverse=True)                   # channel 1 is the top one


def test_a_coincidence_counter_takes_a_pulse_per_channel_and_gives_its_counts():
    part = optodraw.CoincidenceCounter(channels=4)
    ports = part.ports()
    assert sorted(ports) == ["data", "in1", "in2", "in3", "in4"]
    assert all(port.kind == "electrical" for port in ports.values())
    assert ports["data"].center.x > 0 > ports["in1"].center.x


@pytest.mark.parametrize("cls", [optodraw.PhotonCounter, optodraw.CoincidenceCounter])
def test_a_counter_has_one_to_eight_channels(cls):
    with pytest.raises(ValueError):
        cls(channels=0)
    with pytest.raises(ValueError):
        cls(channels=9)


@pytest.mark.parametrize("cls", [optodraw.PhotonCounter, optodraw.CoincidenceCounter])
@pytest.mark.parametrize("channels", [1, 2, 4])
def test_a_counter_gets_its_own_symbol_with_its_ports(cls, channels):
    part = cls(channels=channels)
    symbol = lookup(part)
    assert symbol.source == "prebuilt" and symbol.exact, (symbol.name, symbol.params)
    assert {name: port.kind for name, port in symbol.ports.items()} == _kinds(part)


@pytest.mark.parametrize("cls", [optodraw.PhotonCounter, optodraw.CoincidenceCounter])
def test_a_counter_is_painted_in_2d_from_its_symbol(cls):
    art = art_2d(cls(channels=4))
    assert art is not None and art["residual"] < 0.15


@pytest.mark.parametrize("cls", [optodraw.PhotonCounter, optodraw.CoincidenceCounter])
def test_a_saved_counter_keeps_its_channels(cls):
    part = cls(center=(5, -3), angle=180, channels=2, label="X")
    again = component_from_spec(component_to_spec(part))
    assert (type(again), again.channels, again.label) == (cls, 2, "X")
    assert sorted(again.ports()) == sorted(part.ports())


@pytest.mark.parametrize("cls", [optodraw.PhotonCounter, optodraw.CoincidenceCounter])
def test_a_counter_has_a_3d_body(cls):
    geometry = cls(channels=4).geometry_3d()
    assert geometry["shape"] == "group" and len(geometry["children"]) >= 3
