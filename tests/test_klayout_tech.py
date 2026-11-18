"""KLayout technologies: a .lyt names its .lyp (colours and names) and has no heights; KLayout keeps the heights in
a .lyd25 script. load_layer_stack takes a .lyt (following its .lyp and finding its d25 script) or a .lyd25."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from optodraw.gds import load_layer_stack

GDSFACTORY_TECH = Path(__import__("gdsfactory").__file__).parent / "generic_tech" / "klayout"


def test_a_lyd25_gives_the_heights_of_its_plain_layers():
    from optodraw.gds.klayout_tech import parse_lyd25

    styles, warnings = parse_lyd25(GDSFACTORY_TECH / "d25" / "generic_tech.lyd25")
    nitride, metal3 = styles[(34, 0)], styles[(49, 0)]
    assert nitride["zmin"] == pytest.approx(0.3) and nitride["thickness"] == pytest.approx(0.4)
    assert nitride["name"] == "nitride" and nitride["material_preset"] == "silicon_nitride"
    assert metal3["zmin"] == pytest.approx(3.2) and metal3["thickness"] == pytest.approx(2.0)
    assert metal3["material_preset"] == "aluminum"
    assert (99999, 0) not in styles and any("99999/0" in w for w in warnings)     # substrate, box and clad share it
    assert any("slab_core_shallow_etch_0" in w for w in warnings)                  # a derived layer: skipped, said
    assert styles[(6, 0)]["zmin"] == pytest.approx(-8.0) and styles[(6, 0)]["thickness"] == pytest.approx(5.0)


def test_a_lyd25_takes_an_inline_input_and_a_height(tmp_path):
    from optodraw.gds.klayout_tech import parse_lyd25

    path = tmp_path / "s.lyd25"
    path.write_text("z(input(1, 0), zstart: 0.0, height: 0.22, name: 'WG: si 1/0')\n"
                    "zz(fill: 0xff0000) {\n  z(input(41), zstart: 1.0, zstop: 1.5)\n}\n", encoding="utf-8")
    styles, _ = parse_lyd25(path)
    assert styles[(1, 0)]["thickness"] == pytest.approx(0.22) and styles[(1, 0)]["material_preset"] == "silicon"
    assert styles[(41, 0)]["zmin"] == pytest.approx(1.0) and styles[(41, 0)]["thickness"] == pytest.approx(0.5)


def test_a_lyt_follows_its_lyp_and_finds_its_d25_script():
    stack = load_layer_stack(GDSFACTORY_TECH / "tech.lyt")
    assert stack.name == "generic_tech" and len(stack.styles) >= 30                # the colours and names of layers.lyp
    nitride = stack.styles[(34, 0)]
    assert nitride["color"].startswith("#") and nitride["zmin"] == pytest.approx(0.3)
    assert nitride["thickness"] == pytest.approx(0.4)


def test_a_lyt_without_its_lyp_names_the_missing_file(tmp_path):
    shutil.copy(GDSFACTORY_TECH / "tech.lyt", tmp_path / "tech.lyt")
    with pytest.raises(FileNotFoundError, match="layers.lyp"):
        load_layer_stack(tmp_path / "tech.lyt")


def test_a_lyt_without_a_d25_script_says_it_has_no_heights(tmp_path):
    shutil.copy(GDSFACTORY_TECH / "tech.lyt", tmp_path / "tech.lyt")
    shutil.copy(GDSFACTORY_TECH / "layers.lyp", tmp_path / "layers.lyp")
    stack = load_layer_stack(tmp_path / "tech.lyt")
    assert "zmin" not in stack.styles[(34, 0)] and any("no heights" in w for w in stack.warnings)


def test_a_lyd25_alone_is_a_stack_of_heights():
    stack = load_layer_stack(GDSFACTORY_TECH / "d25" / "generic_tech.lyd25")
    assert stack.styles[(41, 0)]["thickness"] == pytest.approx(0.7)
