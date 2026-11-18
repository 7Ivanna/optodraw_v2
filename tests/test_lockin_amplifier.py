"""The lock-in amplifier: signal in, output X and reference in on the front panel, one plan for the ports, the 2D,
the TikZ pic and the 3D case (an SR830-kind dual-phase lock-in)."""

from __future__ import annotations

import pytest

from optodraw import (LockInAmplifier, Photodiode, Scene, WaveformGenerator, check_figure, check_part_3d)
from optodraw.catalog import describe_component, list_components
from optodraw.symbols import lookup
from optodraw.symbols.art import PORT_TOLERANCE, port_gaps


def test_it_is_an_instrument_with_three_electrical_jacks_under_the_panel():
    # mutant: "out": Port(..., kind="fiber") in LockInAmplifier.ports: no cable can reach the output
    assert "LockInAmplifier" in list_components(category="instruments")
    assert describe_component("LockInAmplifier")["platform"] == "free_space"
    ports = LockInAmplifier().ports()
    assert set(ports) == {"in", "out", "ref"}
    assert {(port.kind, port.orientation_deg) for port in ports.values()} == {("electrical", 270)}
    assert ports["in"].center.x < ports["out"].center.x < ports["ref"].center.x     # SR830 order, left to right


def test_the_1d_symbol_is_exact_and_each_jack_meets_its_port_in_2d():
    # mutant: \odport[electrical]{ref}{0.5,-0.5} in pics/od lockin, rebuild: the 2D art draws ref off its port
    part = LockInAmplifier()
    symbol = lookup(part)
    assert symbol.exact and symbol.source == "prebuilt"
    assert {name: mark.kind for name, mark in symbol.ports.items()} == dict.fromkeys(("in", "out", "ref"), "electrical")
    assert all(gap < PORT_TOLERANCE for gap in port_gaps(part).values()), port_gaps(part)


def test_the_3d_case_has_a_bnc_at_each_port_and_nothing_loose():
    # mutant: _bnc(x * u + 2.0, ...) in LockInAmplifier.geometry_3d: the jacks leave their ports
    part = LockInAmplifier()
    barrels = [solid for solid in part.geometry_3d()["children"] if solid.get("role") == "bnc"]
    assert sorted(solid["position"][0] for solid in barrels) == pytest.approx(
        sorted(port.center.x for port in part.ports().values()))
    assert check_part_3d(part) == []


def test_a_detector_and_a_reference_wire_to_it_clean_in_2d_and_1d():
    # mutant: JACKS "ref": 0.95 in LockInAmplifier: the reference jack sits on the corner of the case
    scene = Scene(width=120, height=60, platform="free_space")
    lockin = scene.add(LockInAmplifier(center=(20, 0), label="Lock-in"))
    pd = scene.add(Photodiode(center=(-30, -20), label="PD"))
    source = scene.add(WaveformGenerator(center=(40, 30), label="Reference"))
    scene.route((pd, "e2"), (lockin, "in"), kind="electrical", width=0.3)
    scene.route((source, "out2"), (lockin, "ref"), kind="electrical", width=0.3)
    scene.fit_frame(margin=6)
    assert check_figure(scene, preset="single_column") == []


def test_it_saves_and_loads_in_place():
    scene = Scene(width=60, height=30)
    part = scene.add(LockInAmplifier(center=(5, 2), angle=90, label="LIA"))
    again = next(item for item in Scene.from_spec(scene.to_spec()).walk() if isinstance(item, LockInAmplifier))
    assert again.label == "LIA"
    for name, port in part.world_ports().items():
        assert (again.world_ports()[name].center.x, again.world_ports()[name].center.y) == pytest.approx(
            (port.center.x, port.center.y))
