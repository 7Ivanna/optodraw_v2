"""One call writes a figure as SVG, PDF and PNG at its size on the page."""

from __future__ import annotations

import re

import pytest

from optodraw import Beam, Laser, Note, Objective, Photodiode, Sample, Scene, check_figure


def _bench():
    scene = Scene(title="bench", width=100, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-30, 0), label="Laser"))
    pd = scene.add(Photodiode(center=(30, 0), label="PD"))
    scene.add(Beam.through(laser, pd))
    return scene


def test_one_call_writes_three_files_at_the_page_size(tmp_path):
    pytest.importorskip("cairosvg")
    image = pytest.importorskip("PIL.Image")
    paths = _bench().export_figure(tmp_path / "fig", width_mm=89.0, dpi=800)
    assert sorted(paths) == ["pdf", "png", "svg"]
    assert all(path.stat().st_size > 0 for path in paths.values())
    assert 'width="89mm"' in paths["svg"].read_text()
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
