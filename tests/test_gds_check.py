"""A GDS and a layer stack that disagree are found and said, never rendered silently."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

gdstk = pytest.importorskip("gdstk")

from optodraw import GDSModel  # noqa: E402
from optodraw.gds import check_stack, load_gds_layout  # noqa: E402
from optodraw.gds.parsers import load_layer_stack  # noqa: E402


def _gds(path: Path, specs, cells=("DEVICE",)) -> Path:
    lib = gdstk.Library()
    for name in cells:
        cell = lib.new_cell(name)
        for i, (layer, datatype) in enumerate(specs):
            cell.add(gdstk.rectangle((i * 20, 0), (i * 20 + 10, 5), layer=layer, datatype=datatype))
    lib.write_gds(str(path))
    return path


def test_a_bundled_stack_loads_by_name():
    assert load_layer_stack("gdsfactory_generic").oxide_source == "explicit"
    with pytest.raises(FileNotFoundError):
        load_layer_stack("no_such_stack")


def test_a_clean_file_and_stack_have_no_findings(tmp_path):
    gds = _gds(tmp_path / "ok.gds", [(1, 0), (41, 0)])
    assert check_stack(gds, "gdsfactory_generic", cell_name="DEVICE") == []


def test_the_silent_faults_are_each_named(tmp_path):
    gds = _gds(tmp_path / "bad.gds", [(1, 2), (77, 0), (99, 0)], cells=("A", "B"))
    findings = check_stack(gds, "gdsfactory_generic")
    text = "\n".join(findings)
    assert "several top cells" in text
    assert "(1, 2)" in text and "datatype" in text
    assert "(77, 0)" in text
    assert "die outline" in text


def test_a_stack_in_nanometres_and_an_unread_entry_are_found(tmp_path):
    gds = _gds(tmp_path / "ok.gds", [(1, 0)])
    stack = tmp_path / "nm.yaml"
    stack.write_text('name: nm\nlayers:\n  "1/0": {name: WG, zmin: 0, thickness: 220, material: silicon}\n'
                     '  "foo": {name: X, zmin: 0, thickness: 1}\n')
    text = "\n".join(check_stack(gds, stack, cell_name="DEVICE"))
    assert "units: nm" in text
    assert "2 layers in the file, 1 understood" in text
    assert "not explicit" in text


def test_loading_a_layout_warns_about_a_layer_with_a_made_up_height(tmp_path):
    gds = _gds(tmp_path / "bad.gds", [(1, 0), (77, 0)])
    styles = load_layer_stack("gdsfactory_generic").styles
    with pytest.warns(UserWarning, match=r"\(77, 0\).*not in the layer stack"):
        load_gds_layout(str(gds), cell_name="DEVICE", layer_styles=styles)


def test_loading_a_matching_layout_is_quiet(tmp_path):
    gds = _gds(tmp_path / "ok.gds", [(1, 0), (41, 0)])
    styles = load_layer_stack("gdsfactory_generic").styles
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        load_gds_layout(str(gds), cell_name="DEVICE", layer_styles=styles)


def test_a_gds_model_warns_about_a_layer_no_style_covers(tmp_path):
    gds = _gds(tmp_path / "bad.gds", [(1, 0), (777, 0)])
    with pytest.warns(UserWarning, match=r"\(777, 0\).*not in the layer stack"):
        GDSModel(str(gds), cell_name="DEVICE")


def test_a_layer_that_floats_above_the_oxide_is_found(tmp_path):
    gds = _gds(tmp_path / "ok.gds", [(1, 0), (41, 0)])
    stack = tmp_path / "gap.yaml"
    stack.write_text('name: gap\nunits: nm\noxide:\n  box: {thickness: 2000, material: sio2}\n'
                     '  tox: {thickness: 2000, material: sio2}\n  handle: {thickness: 2000, material: silicon}\n'
                     'layers:\n  "1/0": {name: WG, zmin: 0, thickness: 220, material: silicon}\n'
                     '  "41/0": {name: M1, zmin: 2200, thickness: 700, material: aluminum}\n')
    text = "\n".join(check_stack(gds, stack, cell_name="DEVICE"))
    assert "(41, 0)" in text and "above the oxide top" in text


def test_a_pad_on_the_oxide_top_does_not_float(tmp_path):
    gds = _gds(tmp_path / "ok.gds", [(1, 0), (41, 0)])
    stack = tmp_path / "pad.yaml"
    stack.write_text('name: pad\nunits: nm\noxide:\n  box: {thickness: 2000, material: sio2}\n'
                     '  tox: {thickness: 2000, material: sio2}\n  handle: {thickness: 2000, material: silicon}\n'
                     'layers:\n  "1/0": {name: WG, zmin: 0, thickness: 220, material: silicon}\n'
                     '  "41/0": {name: M1, zmin: 2000, thickness: 700, material: aluminum}\n')
    assert check_stack(gds, stack, cell_name="DEVICE") == []


def test_a_metal_on_a_drawn_via_above_the_oxide_does_not_float(tmp_path):
    gds = _gds(tmp_path / "via.gds", [(1, 0), (40, 0), (41, 0)])
    stack = tmp_path / "via.yaml"
    stack.write_text('name: via\nunits: nm\noxide:\n  box: {thickness: 2000, material: sio2}\n'
                     '  tox: {thickness: 2000, material: sio2}\n  handle: {thickness: 2000, material: silicon}\n'
                     'layers:\n  "1/0": {name: WG, zmin: 0, thickness: 220, material: silicon}\n'
                     '  "40/0": {name: Via, zmin: 2000, thickness: 200, material: tungsten}\n'
                     '  "41/0": {name: M1, zmin: 2200, thickness: 700, material: aluminum}\n')
    assert check_stack(gds, stack, cell_name="DEVICE") == []
