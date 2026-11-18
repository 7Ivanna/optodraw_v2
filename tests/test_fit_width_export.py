"""A chip drawn in micrometres goes to a journal column at the column's width, with labels at the preset's size."""

from __future__ import annotations

import re
import warnings

import pytest

from optodraw import OnChipPhotodetector, Scene, VerticalGratingCoupler
from optodraw.publication import export_paper_figures


def _chip():
    chip = Scene(title="Detector chip", width=400, height=150, platform="on_chip")
    gc = chip.add(VerticalGratingCoupler(center=(-120, 0), angle=180, label="In"))
    pd = chip.add(OnChipPhotodetector(center=(120, 0), label="PD"))
    chip.route((gc, "o1"), (pd, "o1"), kind="waveguide", path_type="smooth")
    return chip


def _root(svg: str) -> dict[str, str]:
    tag = re.search(r"<svg\b[^>]*>", svg).group(0)
    return dict(re.findall(r'(\w+)="([^"]*)"', tag))


def test_a_chip_fits_the_column_width_with_labels_at_the_preset_size(tmp_path):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        paths = export_paper_figures(_chip(), tmp_path, preset="single_column", formats=("svg",), fit="width")
    assert not [w for w in caught if "clips content" in str(w.message)]
    svg = paths["svg"].read_text()
    root = _root(svg)
    assert root["width"] == "89mm"
    x, y, w, h = (float(v) for v in root["viewBox"].split())
    assert w > 200                                                     # the whole chip, not an 89 um window
    assert root["height"] == f"{h * 89.0 / w:.2f}mm"
    sizes = {float(s) for s in re.findall(r'font-size="([\d.]+)"', svg)}
    label_mm = max(sizes) * 89.0 / w
    assert label_mm == pytest.approx(8.0 * 0.3528, rel=0.05)          # 8 pt on the page


def test_fit_width_keeps_a_free_space_bench_at_its_page_size(tmp_path):
    from optodraw import Beam, Laser, Photodiode

    bench = Scene(title="Bench", width=89, height=40, platform="free_space")
    laser = bench.add(Laser(center=(-30, 0), label="Laser"))
    pd = bench.add(Photodiode(center=(30, 0), label="PD"))
    bench.add(Beam.through(laser, pd))
    root = _root(export_paper_figures(bench, tmp_path, preset="single_column", formats=("svg",), fit="width")["svg"].read_text())
    assert root["width"] == "89mm"
