"""A GDS and a layer stack that disagree are found and said, never rendered silently."""

from __future__ import annotations

from pathlib import Path

import pytest

gdstk = pytest.importorskip("gdstk")

from optodraw.gds import check_stack  # noqa: E402


def _gds(path: Path, specs, cells=("DEVICE",)) -> Path:
    lib = gdstk.Library()
    for name in cells:
        cell = lib.new_cell(name)
        for i, (layer, datatype) in enumerate(specs):
            cell.add(gdstk.rectangle((i * 20, 0), (i * 20 + 10, 5), layer=layer, datatype=datatype))
    lib.write_gds(str(path))
    return path


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


