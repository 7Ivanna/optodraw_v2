"""Every example cell on the documentation site runs and shows something (site rule D7)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"site_{name}", DOCS / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_cell_shows_its_last_line():
    display = _script("cell_display")
    assert display.run_cell("x = 2\nprint('hello')\nx + 1", {}) == {"kind": "text", "data": "3", "stdout": "hello\n"}
    assert display.run_cell("y = 1", {})["kind"] == "none"
    assert display.show("<svg viewBox='0 0 1 1'></svg>")["kind"] == "svg"
    assert display.show("<!DOCTYPE html><html></html>")["kind"] == "html"


def test_every_site_example_runs_and_shows_something(tmp_path):
    pytest.importorskip("gdstk")                         # the GDS page's cell imports a mask
    cells = _script("run_examples").run(public=tmp_path / "public", table=tmp_path / "cells.json")
    assert len(cells) >= 10
    for key, cell in cells.items():
        assert cell["title"] and cell["code"].strip(), key
        assert cell["kind"] != "none" or cell["stdout"].strip(), f"{key} shows nothing"
        if cell["output"]:
            assert (tmp_path / "public" / cell["output"].removeprefix("/examples/")).stat().st_size > 500, key


def test_a_cell_marked_for_python_only_says_why(tmp_path):
    cell = tmp_path / "01-gds.py"
    cell.write_text("# browser: no (GDS import needs gdstk)\n# A mask\nx = 1\nx\n")
    read = _script("run_examples").read_cell(cell)
    assert read["browser"] is False and read["why"] == "GDS import needs gdstk" and read["title"] == "A mask"
    assert not read["code"].startswith("# browser")


def test_a_cell_that_ends_in_png_bytes_shows_a_picture(tmp_path):
    display = _script("cell_display")
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    assert display.show(png) == {"kind": "png", "data": png}
    page = tmp_path / "examples" / "demo"
    page.mkdir(parents=True)
    (page / "01-image.py").write_text("# An image\nb'\\x89PNG\\r\\n\\x1a\\n' + b'rest'\n")
    cells = _script("run_examples").run(tmp_path / "examples", tmp_path / "public", tmp_path / "cells.json")
    assert cells["demo/01-image"]["output"] == "/examples/demo/01-image.png"
    assert (tmp_path / "public" / "demo" / "01-image.png").read_bytes() == png
