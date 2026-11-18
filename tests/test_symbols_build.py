"""The shipped 1D symbol library agrees with its TikZ source and with the components."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from optodraw.symbols import build

LIBRARY = Path(build.__file__).parent
needs_latex = pytest.mark.skipif(not build.latex_available(), reason="needs latex and dvisvgm")


def _library() -> dict:
    return json.loads((LIBRARY / "symbols.json").read_text(encoding="utf-8"))


def test_the_shipped_library_is_built_from_the_present_source():
    """An edit to a pic or to the table without a rebuild fails here. Needs no LaTeX."""

    table = (LIBRARY / "variants.toml").read_text(encoding="utf-8")
    assert _library()["source_hash"] == build.source_hash(build.library_files(), table), (
        "the TikZ source or the variant table changed: run python -m optodraw.symbols.build"
    )


def test_no_shipped_svg_has_an_id_or_text():
    """1D files carry no id; a 2D file keeps the ids its gradients need, each with the symbol's own prefix."""

    files = sorted((LIBRARY / "svg").glob("*.svg"))
    assert len(files) == 2 * len(_library()["symbols"])     # each symbol in the 1D look and the 2D look
    for path in files:
        text = path.read_text(encoding="utf-8")
        if path.name.endswith(".2d.svg"):
            prefix = "od-" + path.name[: -len(".2d.svg")] + "-"
            assert all(found.startswith(prefix) for found in re.findall(r"\sid='([^']+)'", text)), path.name
        else:
            assert not re.search(r"\sid=", text), path.name     # ids collide when symbols share a page
        assert "<text" not in text, path.name               # a symbol holds no text; labels sit outside
        assert "stroke" in text, path.name                  # strokes stay strokes, for CSS in the editor


def test_a_variant_that_serves_more_classes_fits_each_of_them():
    for entry in _library()["symbols"].values():
        for other in entry.get("also", []):
            assert build.port_mismatch(entry, other, {}) is None, other


def test_ports_lie_inside_the_symbol_frame():
    for name, entry in _library()["symbols"].items():
        assert 0 <= entry["origin"][0] <= entry["width"] and 0 <= entry["origin"][1] <= entry["height"]
        for port_name, port in entry["ports"].items():
            assert -0.01 <= port["x"] <= entry["width"] + 0.01, (name, port_name)
            assert -0.01 <= port["y"] <= entry["height"] + 0.01, (name, port_name)
            assert port["kind"] in {"optical", "electrical", "thermal", "fiber", "free_space"}


def test_slug_ignores_key_order_and_number_form():
    assert build.slug("mzi", {"length": 2, "drive": "gs"}) == build.slug("mzi", {"drive": "gs", "length": 2.0})
    assert build.slug("ring", {"drop": True, "heater": False}) == build.slug("ring", {"drop": True})
    assert build.slug("waveguide", {}) == "waveguide"


@needs_latex
def test_a_symbol_with_the_wrong_ports_fails_the_build(tmp_path):
    table = tmp_path / "table.toml"
    table.write_text('[[variant]]\nsymbol = "waveguide"\ncomponent = "MMI1x2"\n', encoding="utf-8")
    with pytest.raises(build.SymbolBuildError, match=r"missing \['o3'\]"):
        build.build(table, tmp_path / "out")
    assert not (tmp_path / "out" / "symbols.json").exists()


@needs_latex
def test_an_unknown_key_is_an_error_not_a_blank_symbol(tmp_path):
    with pytest.raises(build.SymbolBuildError):
        build.compile_symbol("waveguide", {"no such key": 1}, tmp_path)


def test_the_photodiode_beam_port_lies_on_the_diode_body():
    """The beam ends on the triangle's left edge (y = 0): no thin stub runs from the port to the diode."""

    entry = _library()["symbols"]["detector"]
    port, (ox, oy) = entry["ports"]["in"], entry["origin"]
    edge_x = -3.13                                          # the left edge of the triangle M-6.26-5.69H6.26L0 5.69Z at y = 0
    assert abs(port["y"] - oy) < 0.2
    assert abs((port["x"] - ox) - edge_x) < 0.5


