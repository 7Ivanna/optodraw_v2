"""A chip inset for a bench figure: the films come from the stack, the look from the cross-section, and a beam enters."""

from __future__ import annotations

import re

import pytest

from optodraw import Lens, Scene, export_panels
from optodraw.core.beam import wavelength_to_hex
from optodraw.gds import cross_section, stack_section
from optodraw.gds.parsers import load_layer_stack

STACK = "gdsfactory_generic"
CORE = (1, 0)


def _film(xs, name):
    x0, z0, x1, z1 = xs.regions[name].bounds
    return z1 - z0, x1 - x0


def test_a_section_needs_only_the_stack_and_a_waveguide_width():
    xs = stack_section(STACK, CORE, width=0.5)
    assert xs.check() == []
    assert 0.5 <= _film(xs, "device")[1] < 0.6                    # the stack's sidewall widens its foot


def test_every_film_keeps_the_stack_thickness():
    xs = stack_section(STACK, CORE, width=0.5)
    oxide = load_layer_stack(STACK).oxide
    assert _film(xs, "box")[0] == pytest.approx(oxide["box_depth"], abs=1e-3)
    assert _film(xs, "device")[0] == pytest.approx(0.22, abs=1e-3)


def test_the_section_stays_near_the_waveguide():
    s0, s1 = stack_section(STACK, CORE, width=0.5).window
    assert s1 - s0 == pytest.approx(6.0)


def test_a_layer_the_stack_does_not_have_is_named_in_a_finding():
    xs = stack_section(STACK, (999, 0), width=0.5)
    assert any("(999, 0)" in finding for finding in xs.check())


def test_a_section_with_no_beam_draws_none():
    assert "data-beam" not in stack_section(STACK, CORE).svg()


def test_a_beam_is_drawn_in_its_own_colour():
    xs = stack_section(STACK, CORE)
    xs.beam(wavelength=450)
    assert re.search(rf'data-beam[^>]*fill="{wavelength_to_hex(450)}"', xs.svg())


def test_the_beam_ends_in_the_device_layer_by_default():
    xs = stack_section(STACK, CORE)
    beam = xs.beam(wavelength=450)
    (x0, x1), z = xs.window, beam.z
    assert x0 < beam.s < x1
    assert 0.0 < z < 0.22


def test_a_beam_can_end_at_a_named_place():
    xs = stack_section(STACK, CORE)
    beam = xs.beam(s=0.7, z=-1.0, wavelength=633)
    assert (beam.s, beam.z) == (0.7, -1.0)


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


def test_a_section_is_a_panel_of_a_figure(tmp_path):
    bench = Scene(title="bench", width=80, height=40, platform="free_space")
    bench.add(Lens(center=(0, 0), focal_length=50, label="f 50"))
    xs = stack_section(STACK, CORE)
    xs.beam(wavelength=450, label="450 nm")
    svg = export_panels(tmp_path / "fig", [[bench, xs]], width_mm=150, formats=("svg",))["svg"].read_text()
    assert len(re.findall(r"<svg\b", svg)) == 3
    assert "data-beam" in svg
    assert 'data-region="box"' in svg


def test_a_section_panel_prints_its_labels_at_the_asked_size(tmp_path):
    xs = stack_section(STACK, CORE)
    svg = export_panels(tmp_path / "fig", [[xs]], width_mm=90, font_size_pt=7, letters=False,
                        formats=("svg",))["svg"].read_text()
    tag = re.findall(r"<svg\b[^>]*>", svg)[1]
    width = float(re.search(r'\swidth="([\d.]+)', tag).group(1))
    view = float(re.search(r'viewBox="\S+ \S+ (\S+)', tag).group(1))
    size = float(re.search(r'<text\b[^>]*font-size="([\d.]+)', svg).group(1))
    assert size * width / view / 0.3528 == pytest.approx(7.0, rel=0.05)
