"""A chip inset for a bench figure: the films come from the stack, the look from the cross-section, and a beam enters."""

from __future__ import annotations

import re


from optodraw.gds import cross_section, stack_section

STACK = "gdsfactory_generic"
CORE = (1, 0)


def _film(xs, name):
    x0, z0, x1, z1 = xs.regions[name].bounds
    return z1 - z0, x1 - x0


def test_a_layer_the_stack_does_not_have_is_named_in_a_finding():
    xs = stack_section(STACK, (999, 0), width=0.5)
    assert any("(999, 0)" in finding for finding in xs.check())


def test_the_figure_grows_a_band_for_the_beam_to_enter_through():
    xs = stack_section(STACK, CORE)
    plain = float(re.search(r'height="([\d.]+)mm"', xs.svg()).group(1))
    xs.beam(wavelength=450, label="450 nm")
    drawn = xs.svg()
    assert float(re.search(r'height="([\d.]+)mm"', drawn).group(1)) > plain
    assert "450 nm" in drawn


def test_a_real_cut_takes_a_beam_the_same_way(tmp_path):
    import gdstk

    library = gdstk.Library()
    library.new_cell("rib").add(gdstk.rectangle((-10, -0.25), (10, 0.25), layer=1, datatype=0))
    library.write_gds(tmp_path / "rib.gds")
    xs = cross_section(tmp_path / "rib.gds", STACK, ((0, -6), (0, 6)))
    xs.beam(wavelength=450)
    assert "data-beam" in xs.svg()


