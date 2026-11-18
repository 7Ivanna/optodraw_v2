"""export_panels lays out scenes and SVG files as one figure, with panel letters, and keeps each panel to itself."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

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


def _nested(svg):
    """Each panel as the page places it, as an ``<svg>`` tag: the id of its inset, and its ``x``, ``y``, ``width`` and
    ``height`` in the page's units (mm, y down), with its own ``viewBox``. The transforms above it place it."""

    from optodraw.check import _matrix, _times

    found = []

    def walk(element, matrix):
        matrix = _times(matrix, _matrix(element.get("transform")))
        if element.get("data-inset") is None:
            for child in element:
                walk(child, matrix)
            return
        inner = next(child for child in element if child.tag == "{http://www.w3.org/2000/svg}svg")
        a, b, c, d, e, f = matrix
        scale = math.sqrt(abs(a * d - b * c))
        wide, tall = (float(inner.get(key)) * scale for key in ("width", "height"))
        found.append(f'<svg id="{element.get("id")}" x="{e:.6f}" y="{f:.6f}" width="{wide:.6f}" height="{tall:.6f}" '
                     f'viewBox="{inner.get("viewBox")}">')

    walk(ET.fromstring(svg), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    return found


def _attr(tag, name):
    return float(re.search(rf'\s{name}="([-\d.]+)', tag).group(1))


def test_it_writes_the_three_formats(tmp_path, plot):
    paths = export_panels(tmp_path / "out" / "fig", [[_scene(), plot]], width_mm=120)
    assert sorted(paths) == ["pdf", "png", "svg"]
    assert all(path.is_file() and path.stat().st_size > 0 for path in paths.values())
    assert paths["pdf"].read_bytes().startswith(b"%PDF")


def test_the_png_has_the_page_width_at_the_dpi(tmp_path, plot):
    from PIL import Image

    paths = export_panels(tmp_path / "fig", [[_scene(), plot]], width_mm=127, dpi=400, formats=("png",))
    assert Image.open(paths["png"]).size[0] == 2000


def test_the_svg_is_as_wide_as_the_page_in_mm(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[_scene(), plot]], width_mm=120, formats=("svg",))["svg"].read_text()
    assert re.search(r'<svg\b[^>]*\swidth="120(\.0+)?mm"', svg)


def test_a_row_fills_the_width_and_its_panels_share_one_height(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[_scene(), plot]], width_mm=120, gap_mm=3,
                        formats=("svg",))["svg"].read_text()
    first, second = _nested(svg)
    assert _attr(first, "height") == pytest.approx(_attr(second, "height"), abs=0.01)    # each draws at its own size
    assert _attr(first, "width") + 3 + _attr(second, "width") == pytest.approx(120.0, abs=0.01)
    assert _attr(second, "x") == pytest.approx(_attr(first, "width") + 3, abs=0.01)


def test_rows_stack_down_the_page(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[_scene()], [plot]], width_mm=120, formats=("svg",))["svg"].read_text()
    first, second = _nested(svg)
    assert _attr(second, "y") > _attr(first, "y") + _attr(first, "height")


def test_a_share_sets_a_panels_width_and_the_rest_take_what_is_left(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[Panel(_scene(), share=0.7), plot]], width_mm=122, gap_mm=2,
                        formats=("svg",))["svg"].read_text()
    first, second = _nested(svg)
    assert _attr(first, "width") == pytest.approx(84.0, abs=0.01)
    assert _attr(second, "width") == pytest.approx(36.0, abs=0.01)


def test_panels_of_set_width_line_up_at_the_top_of_the_row(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[Panel(plot, share=0.2), Panel(plot, share=0.8)]], width_mm=102, gap_mm=2,
                        formats=("svg",))["svg"].read_text()
    short, tall = _nested(svg)
    assert _attr(tall, "height") == pytest.approx(4.0 * _attr(short, "height"), abs=0.01)
    assert _attr(short, "y") == pytest.approx(_attr(tall, "y"), abs=1e-3)
    letters = re.findall(r'<text\b[^>]*font-weight="bold"[^>]*>([^<]*)</text>', svg)
    assert letters == ["a", "b"]                        # the short panel on the left reads first


def test_shares_over_the_whole_width_are_refused(tmp_path, plot):
    with pytest.raises(ValueError, match="share"):
        export_panels(tmp_path / "fig", [[Panel(plot, share=0.8), Panel(plot, share=0.3)]], width_mm=100)


def test_a_flat_list_is_one_row(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [_scene(), plot], width_mm=120, formats=("svg",))["svg"].read_text()
    first, second = _nested(svg)
    assert _attr(first, "y") == pytest.approx(_attr(second, "y"), abs=1e-3)


def test_the_panels_are_lettered_in_order(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[_scene(), plot], [plot]], width_mm=120, formats=("svg",))["svg"].read_text()
    letters = re.findall(r'<text\b[^>]*font-weight="bold"[^>]*>([^<]*)</text>', svg)
    assert letters == ["a", "b", "c"]


def test_a_letter_sits_above_its_panel_so_it_cannot_touch_it(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[plot]], width_mm=120, formats=("svg",))["svg"].read_text()
    letter = re.search(r'<text\b[^>]*font-weight="bold"[^>]*>', svg).group(0)
    assert _attr(letter, "y") <= _attr(_nested(svg)[0], "y")


def test_letters_can_be_left_out_or_named(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[plot, plot]], width_mm=120, letters=False,
                        formats=("svg",))["svg"].read_text()
    assert 'font-weight="bold"' not in svg
    svg = export_panels(tmp_path / "fig", [[Panel(plot, letter="(c)"), Panel(plot, letter="")]], width_mm=120,
                        formats=("svg",))["svg"].read_text()
    assert re.findall(r'<text\b[^>]*font-weight="bold"[^>]*>([^<]*)</text>', svg) == ["(c)"]


def test_two_panels_keep_their_own_ids(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[plot, plot]], width_mm=120, formats=("svg",))["svg"].read_text()
    ids = re.findall(r'\bid="([^"]+)"', svg)
    assert len(ids) == len(set(ids))
    for reference in re.findall(r'url\(#([^)]+)\)', svg) + re.findall(r'href="#([^"]+)"', svg):
        assert reference in ids


def test_a_style_block_stays_inside_its_panel(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[_scene(), plot]], width_mm=120, formats=("svg",))["svg"].read_text()
    panel_id = re.search(r'\bid="([^"]+)"', _nested(svg)[1]).group(1)
    assert f"#{panel_id} *" in svg
    assert re.search(r"(?<![#\w-] )\*\s*\{", svg.replace(f"#{panel_id} *", "")) is None


def test_old_text_comes_out_by_name_and_the_rest_stays(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[Panel(plot, drop_text=("(a)",))]], width_mm=120,
                        formats=("svg",))["svg"].read_text()
    assert ">(a)<" not in svg
    assert "Power" in svg


def test_one_string_of_text_to_drop_is_one_text(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[Panel(plot, drop_text="(a)")]], width_mm=120,
                        formats=("svg",))["svg"].read_text()
    assert ">(a)<" not in svg


def test_text_to_drop_that_is_not_there_is_reported(tmp_path, plot):
    with pytest.warns(UserWarning, match="plot.svg"):
        export_panels(tmp_path / "fig", [[Panel(plot, drop_text=("(z)",))]], width_mm=120, formats=("svg",))


def test_a_scene_panel_prints_its_labels_at_the_asked_size(tmp_path):
    svg = export_panels(tmp_path / "fig", [[_scene(), _scene()]], width_mm=120, font_size_pt=7,
                        formats=("svg",))["svg"].read_text()
    tag = _nested(svg)[0]
    width, view = _attr(tag, "width"), float(re.search(r'viewBox="\S+ \S+ (\S+)', tag).group(1))
    label = re.search(r'<text\b[^>]*font-size="([\d.]+)"[^>]*>[^<]*f 50', svg)
    assert float(label.group(1)) * width / view / 0.3528 == pytest.approx(7.0, rel=0.03)


def test_an_svg_with_only_a_size_still_gives_its_shape(tmp_path):
    path = tmp_path / "sized.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="30mm" height="10mm"><rect width="3" height="1"/></svg>')
    svg = export_panels(tmp_path / "fig", [[path]], width_mm=90, letters=False, formats=("svg",))["svg"].read_text()
    assert _attr(_nested(svg)[0], "height") == pytest.approx(30.0, abs=0.01)


def test_an_svg_with_no_size_is_refused_by_name(tmp_path):
    path = tmp_path / "shapeless.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="3" height="1"/></svg>')
    with pytest.raises(ValueError, match="shapeless.svg"):
        export_panels(tmp_path / "fig", [[path]], width_mm=90, formats=("svg",))


def test_no_panels_is_refused():
    with pytest.raises(ValueError, match="panel"):
        export_panels("fig", [], width_mm=90)


def test_an_unknown_format_is_refused(tmp_path, plot):
    with pytest.raises(ValueError, match="eps"):
        export_panels(tmp_path / "fig", [[plot]], width_mm=90, formats=("eps",))


# ---- export_panels on the Page: every source an inset takes, one page system ----

def test_export_panels_takes_a_png(tmp_path):
    from PIL import Image

    path = tmp_path / "photo.png"
    Image.new("RGB", (40, 20), "#c03030").save(path)
    svg = export_panels(tmp_path / "fig", [[path]], width_mm=89, formats=("svg",))["svg"].read_text()
    assert "data:image/png;base64," in svg
    assert _attr(_nested(svg)[0], "height") == pytest.approx(89.0 / 2.0, abs=0.01)


def test_export_panels_takes_a_matplotlib_figure(tmp_path):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(4, 2))
    ax = fig.add_subplot()
    ax.plot([0, 1], [0, 1])
    ax.set_xlabel("Detuning")
    svg = export_panels(tmp_path / "fig", [[_scene(), fig]], width_mm=120, formats=("svg",))["svg"].read_text()
    assert "Detuning" in svg
    assert len(_nested(svg)) == 2


def test_panel_takes_a_view(tmp_path):
    assert Panel(_scene()).view == "2d"
    svg = export_panels(tmp_path / "fig", [[Panel(_scene(), view="1d")]], width_mm=89,
                        formats=("svg",))["svg"].read_text()
    assert 'aria-label="1D schematic"' in svg


def test_a_view_is_for_a_scene_panel(tmp_path, plot):
    with pytest.raises(ValueError, match="view"):
        export_panels(tmp_path / "fig", [[Panel(plot, view="1d")]], width_mm=90, formats=("svg",))


def test_export_panels_builds_a_page(tmp_path, monkeypatch, plot):
    from optodraw.figure.page import Page

    calls, real = [], Page.export

    def spy(self, path, **kwargs):
        calls.append((self, kwargs))
        return real(self, path, **kwargs)

    monkeypatch.setattr(Page, "export", spy)
    paths = export_panels(tmp_path / "fig", [[_scene(), plot]], width_mm=120, font_size_pt=6.5, letter_pt=9.0,
                          dpi=300, formats=("svg",))
    assert len(calls) == 1
    page, kwargs = calls[0]
    assert (page.width_mm, page.font_pt, page.letter_pt) == (120.0, 6.5, 9.0)
    assert kwargs == {"formats": ("svg",), "dpi": 300}
    assert paths["svg"].is_file()


def test_an_unlettered_panel_takes_no_letter_slot(tmp_path, plot):
    svg = export_panels(tmp_path / "fig", [[plot, Panel(plot, letter=""), plot]], width_mm=120,
                        formats=("svg",))["svg"].read_text()
    assert re.findall(r'<text\b[^>]*font-weight="bold"[^>]*>([^<]*)</text>', svg) == ["a", "b"]


def test_text_to_drop_on_a_scene_panel_is_refused(tmp_path):
    with pytest.raises(ValueError, match=r"drop_text.*'bench'"):
        export_panels(tmp_path / "fig", [[Panel(_scene("bench"), drop_text=("x",))]], width_mm=120,
                      formats=("svg",))
