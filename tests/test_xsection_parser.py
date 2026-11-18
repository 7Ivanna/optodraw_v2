"""Best-effort KLayout XSection (.xs) thickness extraction."""

from __future__ import annotations

from optodraw.gds.parsers import parse_xsection_thickness

_XS = """
# KLayout XSection process
l_wg    = layer("1/0")
l_slab  = layer("2/0")
l_metal = layer("11/0")

substrate = bulk
wg   = mask(l_wg).grow(0.22, 0.0, :mode => :round)
slab = mask(l_slab).grow(0.15)
m1   = mask(l_metal).grow(0.70, 0.1)
"""


def test_xsection_extracts_layer_thickness(tmp_path):
    path = tmp_path / "process.xs"
    path.write_text(_XS, encoding="utf-8")
    styles = parse_xsection_thickness(str(path))
    assert styles[(1, 0)]["thickness"] == 0.22
    assert styles[(2, 0)]["thickness"] == 0.15
    assert styles[(11, 0)]["thickness"] == 0.70


def test_xsection_ignores_comments_and_unmapped(tmp_path):
    path = tmp_path / "process.xs"
    path.write_text("# wg = mask(l).grow(9.9)\nl = layer(\"3/0\")\n", encoding="utf-8")
    # commented grow is ignored; layer with no grow yields nothing
    assert parse_xsection_thickness(str(path)) == {}
