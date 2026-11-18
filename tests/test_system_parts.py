"""Parts that system figures show: an IQ modulator, a frequency comb, a superconducting detector."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.layout import estimate_component_bounds
from optodraw.registry import component_registry
from optodraw.symbols import lookup
from optodraw.symbols.art import art_2d


def test_the_iq_modulator_is_two_mzms_in_an_outer_interferometer():
    iq = optodraw.IQModulator(arm_gap=48.0)
    ports = iq.ports()
    assert component_registry()["IQModulator"].category == "on_chip"
    assert set(ports) == {"o1", "o2", "i_sig", "i_gnd", "q_sig", "q_gnd", "h1", "h2"}
    assert ports["o1"].center.x < -100 and ports["o2"].center.x > 100 and abs(ports["o1"].center.y) < 1e-9
    assert all(ports[name].center.y > 0 for name in ("i_sig", "i_gnd"))        # the I modulator is the upper arm
    assert all(ports[name].center.y < 0 for name in ("q_sig", "q_gnd", "h1", "h2"))
    assert {ports[name].kind for name in ("i_sig", "i_gnd", "q_sig", "q_gnd", "h1", "h2")} == {"electrical"}
    x0, y0, x1, y1 = estimate_component_bounds(iq)
    assert y1 - y0 > 48.0                                                        # both MZMs are drawn, apart


def test_the_q_electrodes_face_outward_so_no_route_crosses_a_waveguide():
    """Q is the I modulator mirrored: its electrodes and the bias heater pads sit below the lower arm."""

    iq = optodraw.IQModulator(arm_gap=48.0)
    ports, d = iq.ports(), 24.0
    assert all(ports[name].center.y > d for name in ("i_sig", "i_gnd"))
    assert all(ports[name].center.y < -d for name in ("q_sig", "q_gnd", "h1", "h2"))
    assert ports["i_sig"].center.y == pytest.approx(-ports["q_sig"].center.y)


def test_the_iq_modulator_keeps_its_layout_and_has_its_own_symbol():
    iq = optodraw.IQModulator()
    assert art_2d(iq) is None                                                    # on-chip: true geometry in 2D
    assert lookup(iq).exact and lookup(iq).name == "iqmod"
    assert iq.geometry_3d()["children"]


def test_the_frequency_comb_is_an_on_chip_source_with_the_comb_symbol():
    comb = optodraw.FrequencyComb(line_spacing_ghz=100.0, line_count=40)
    assert component_registry()["FrequencyComb"].category == "on_chip"
    assert set(comb.ports()) == set(optodraw.OnChipLaser().ports())
    symbol = lookup(comb)
    assert symbol.exact and symbol.name == "comb"
    assert comb.physics_metadata()["line_spacing_ghz"] == pytest.approx(100.0)


