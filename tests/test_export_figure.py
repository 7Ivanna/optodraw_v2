"""One call writes a figure as SVG, PDF and PNG at its size on the page."""

from __future__ import annotations

import re

import pytest

from optodraw import Beam, Laser, Note, Objective, Photodiode, Sample, Scene


def _bench():
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    scene.add(Beam.through(laser, pd))
    return scene


def test_one_call_writes_three_files_at_the_page_size(tmp_path):
    image = pytest.importorskip("PIL.Image")
    paths = _bench().export_figure(tmp_path / "fig", width_mm=89.0, dpi=800)
    assert sorted(paths) == ["pdf", "png", "svg"]
    assert all(path.stat().st_size > 0 for path in paths.values())
    assert 'width="89mm"' in paths["svg"].read_text()
    assert 'font-family="Helvetica' in _bench().render_svg().as_svg().split(">", 2)[1]   # as the 1D view
    assert image.open(paths["png"]).width == round(89.0 / 25.4 * 800)
    assert paths["pdf"].read_bytes().startswith(b"%PDF")


def test_formats_choose_the_files(tmp_path):
    paths = _bench().export_figure(tmp_path / "fig", width_mm=89.0, formats=("svg",))
    assert sorted(paths) == ["svg"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fig.svg"]


def test_an_unknown_format_is_refused(tmp_path):
    with pytest.raises(ValueError, match="tiff"):
        _bench().export_figure(tmp_path / "fig", width_mm=89.0, formats=("tiff",))


def test_a_long_note_at_the_edge_stays_on_the_page(tmp_path):
    scene = _bench()
    scene.add(Note("a long note at the edge of the figure", center=(35, 12), anchor="start"))
    svg = scene.export_figure(tmp_path / "fig", width_mm=89.0, formats=("svg",))["svg"].read_text()
    x0, _, width, _ = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split())
    assert x0 + width > 35.0 + 0.6 * len("a long note at the edge of the figure")


def test_an_objective_names_its_focus():
    scene = Scene(title="focus", width=100, height=100, platform="free_space")
    objective = scene.add(Objective(center=(10, 20), angle=-90, working_distance=14, label="Obj"))
    nose = objective.world_port("out").center
    assert objective.focus_point() == pytest.approx((float(nose.x), float(nose.y) - 14.0))


def test_a_sample_at_the_focus_stands_on_it():
    scene = Scene(title="focus", width=100, height=100, platform="free_space")
    objective = scene.add(Objective(center=(10, 20), angle=-90, working_distance=14, label="Obj"))
    sample = scene.add(Sample(center=objective.focus_point(), angle=-90, label="Chip"))
    assert (float(sample.world_position.x), float(sample.world_position.y)) == pytest.approx(objective.focus_point())


def test_without_the_cairo_library_a_browser_prints_the_pdf_at_its_page_size(tmp_path, monkeypatch):
    from optodraw.raster import svg_to_pdf
    from optodraw.renderers.capture3d import find_chrome

    if find_chrome(required=False) is None:
        pytest.skip("no Chrome or Edge here")
    monkeypatch.setitem(__import__("sys").modules, "cairosvg", None)          # as on Windows: no cairo
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="89mm" height="30mm" viewBox="0 0 89 30">' \
          '<text x="5" y="15" font-size="6">Laser</text></svg>'
    pdf = svg_to_pdf(svg, tmp_path / "fig.pdf").read_bytes()
    box = [float(v) for v in re.search(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)", pdf).groups()]
    assert box == pytest.approx([89 / 25.4 * 72, 30 / 25.4 * 72], abs=1.0)


def test_with_neither_cairo_nor_a_browser_the_pdf_error_names_both(tmp_path, monkeypatch):
    from optodraw.raster import svg_to_pdf

    monkeypatch.setitem(__import__("sys").modules, "cairosvg", None)
    monkeypatch.setenv("OPTODRAW_CHROME", str(tmp_path / "no-browser"))
    with pytest.raises(RuntimeError, match="Chrome or Edge, or the cairo library"):
        svg_to_pdf('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>', tmp_path / "x.pdf")
