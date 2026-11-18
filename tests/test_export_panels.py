"""export_panels lays out scenes and SVG files as one figure, with panel letters, and keeps each panel to itself."""

from __future__ import annotations


import pytest

from optodraw import Lens, Panel, Scene, export_panels

MPL_STYLE = "<style type='text/css'>*{stroke-linecap: butt}</style>"
PLOT = f"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="200pt" height="100pt"
     viewBox="0 0 200 100">
 <defs>{MPL_STYLE}<clipPath id="clip1"><rect width="200" height="100"/></clipPath>
  <path id="mark" d="M0 0L1 1"/></defs>
 <g clip-path="url(#clip1)"><use xlink:href="#mark" x="3" y="4"/></g>
 <text x="5" y="20">(a)</text>
 <text x="5" y="40"><tspan>Power</tspan></text>
</svg>
"""


def _scene(title="bench"):
    scene = Scene(title=title, width=80, height=40, platform="free_space")
    scene.add(Lens(center=(0, 0), focal_length=50, label="f 50"))
    return scene


@pytest.fixture
def plot(tmp_path):
    path = tmp_path / "plot.svg"
    path.write_text(PLOT, encoding="utf-8")
    return path


def test_shares_over_the_whole_width_are_refused(tmp_path, plot):
    with pytest.raises(ValueError, match="share"):
        export_panels(tmp_path / "fig", [[Panel(plot, share=0.8), Panel(plot, share=0.3)]], width_mm=100)


def test_old_text_comes_out_by_name_and_the_rest_stays(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[Panel(plot, drop_text=("(a)",))]], width_mm=120,
                        formats=("svg",))["svg"].read_text()
    assert ">(a)<" not in svg
    assert "Power" in svg


def test_text_to_drop_that_is_not_there_is_reported(tmp_path, plot):
    with pytest.warns(UserWarning, match="plot.svg"):
        export_panels(tmp_path / "fig", [[Panel(plot, drop_text=("(z)",))]], width_mm=120, formats=("svg",))


def test_an_svg_with_no_size_is_refused_by_name(tmp_path):
    path = tmp_path / "shapeless.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="3" height="1"/></svg>')
    with pytest.raises(ValueError, match="shapeless.svg"):
        export_panels(tmp_path / "fig", [[path]], width_mm=90, formats=("svg",))


def test_no_panels_is_refused():
    with pytest.raises(ValueError, match="panel"):
        export_panels("fig", [], width_mm=90)


# ---- export_panels on the Page: every source an inset takes, one page system ----


def test_panel_takes_a_view(tmp_path):
    assert Panel(_scene()).view == "2d"
    svg = export_panels(tmp_path / "fig", [[Panel(_scene(), view="1d")]], width_mm=89,
                        formats=("svg",))["svg"].read_text()
    assert 'aria-label="1D schematic"' in svg


def test_a_view_is_for_a_scene_panel(tmp_path, plot):
    with pytest.raises(ValueError, match="view"):
        export_panels(tmp_path / "fig", [[Panel(plot, view="1d")]], width_mm=90, formats=("svg",))


def test_text_to_drop_on_a_scene_panel_is_refused(tmp_path):
    with pytest.raises(ValueError, match=r"drop_text.*'bench'"):
        export_panels(tmp_path / "fig", [[Panel(_scene("bench"), drop_text=("x",))]], width_mm=120,
                      formats=("svg",))
