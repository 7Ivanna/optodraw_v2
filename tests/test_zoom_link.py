"""Panel(zoom=(panel, region)) says one panel is a closer view of a place on another, and draws the link."""

import math
import xml.etree.ElementTree as ET

import pytest

from optodraw import Laser, Lens, Panel, Scene, check_export, export_panels

SVG = "{http://www.w3.org/2000/svg}"


def bench():
    scene = Scene(title="Bench", width=120, height=40, platform="free_space")
    scene.add(Laser(center=(-40, 0), label="Laser", label_side="top"))
    lens = scene.add(Lens(center=(0, 0), focal_length=40, label="Lens", label_side="top"))
    scene.add(Lens(center=(40, 0), focal_length=40, label="Lens 2", label_side="top"))
    return scene, lens


def detail():
    scene = Scene(title="Detail", width=60, height=40, platform="free_space")
    scene.add(Lens(center=(0, 0), focal_length=10, label="Close", label_side="top"))
    return scene


def write(tmp_path, rows, **kwargs):
    path = export_panels(tmp_path / "fig", rows, width_mm=183, formats=("svg",), **kwargs)["svg"]
    return ET.parse(path).getroot()


def zoom_of(root):
    marks = [g for g in root.iter(f"{SVG}g") if g.get("data-part") == "zoom"]
    assert len(marks) == 1
    return marks[0]


def _walk(element, matrix=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)):
    """Each element of the page with the matrix of the transforms above it. It does not go into an inset's drawing."""

    from optodraw.check import _matrix, _times

    matrix = _times(matrix, _matrix(element.get("transform")))
    yield element, matrix
    if element.get("data-inset") is None:
        for child in element:
            yield from _walk(child, matrix)


def panels(root):
    """Each panel as the page places it: its inset's nested ``<svg>``, with ``x``, ``y``, ``width`` and ``height`` in
    the page's units (y down) and its own ``viewBox``."""

    out = []
    for element, (a, b, c, d, e, f) in _walk(root):
        if element.get("data-inset") is not None:
            inner = next(child for child in element if child.tag == f"{SVG}svg")
            scale = math.sqrt(abs(a * d - b * c))
            out.append(ET.Element("svg", {"x": repr(e), "y": repr(f), "viewBox": inner.get("viewBox"),
                                          "width": repr(float(inner.get("width")) * scale),
                                          "height": repr(float(inner.get("height")) * scale)}))
    return out


def frames(root):
    """The box on the page of each stroked rect outside the insets' drawings."""

    out = []
    for element, (a, _, _, d, e, f) in _walk(root):
        if element.tag == f"{SVG}rect" and element.get("stroke", "none") != "none":
            x, y, w, h = box(element)
            out.append((a * x + e, d * y + f, a * w, d * h))
    return out


def box(element):
    return tuple(float(element.get(key)) for key in ("x", "y", "width", "height"))


def _points(path):
    d = path.get("d").replace("M", " ").replace("L", " ").replace("Z", " ")
    return [tuple(float(v) for v in p.split(",")) for p in d.split()]


def _polygon(mark):
    return _points(next(mark.iter(f"{SVG}path")))


def zoom_box(mark):
    """The zoom's box on the small panel, as x, y, width and height on the page."""

    xs, ys = zip(*_polygon(mark))
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def page_of(panel, x, y):
    """A point of a panel's own drawing, on the page."""

    px, py, wide, _ = box(panel)
    vx, vy, vw, _ = (float(v) for v in panel.get("viewBox").split())
    scale = wide / vw
    return px + (x - vx) * scale, py + (y - vy) * scale


def test_a_zoom_panel_before_its_source_joins_it_on_the_other_side(tmp_path):
    scene, _ = bench()
    second = Panel(scene)
    root = write(tmp_path, [[Panel(detail(), zoom=(second, (-5, -6, 5, 8))), second]])
    mark = zoom_of(root)
    x, y, _, h = zoom_box(mark)
    tx, _, tw, _ = box(panels(root)[0])
    ends = sorted(float(l.get("x1")) for l in mark.iter(f"{SVG}line"))
    assert ends == pytest.approx([x, x], abs=2e-3)
    assert {round(float(l.get("x2")), 3) for l in mark.iter(f"{SVG}line")} == {round(tx + tw, 3)}


def test_a_source_not_in_the_figure_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not in the figure"):
        write(tmp_path, [[Panel(bench()[0]), Panel(detail(), zoom=(Panel(detail()), (0, 0, 1, 1)))]])


def test_a_part_cannot_name_a_place_on_a_file(tmp_path):
    path = tmp_path / "plot.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"></svg>', encoding="utf-8")
    first = Panel(str(path))
    with pytest.raises(ValueError, match="part"):
        write(tmp_path, [[first, Panel(detail(), zoom=(first, bench()[1]))]])


def test_the_export_gate_finds_a_zoom_line_through_a_label(tmp_path):
    path = tmp_path / "fig.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm" viewBox="0 0 120 80">'
                    '<text x="20" y="40" font-size="2.47" font-family="Helvetica">Objective</text>'
                    '<g data-part="zoom" fill="none" stroke="#777" stroke-width="0.12">'
                    '<line x1="0" y1="39" x2="100" y2="39"/></g></svg>', encoding="utf-8")
    assert any('"Objective"' in f and "zoom" in f for f in check_export(path))


# ---- ZoomLink on a Page: drawn from the live places of two insets ----

from optodraw import Inset  # noqa: E402
from optodraw.figure.page import Page  # noqa: E402

FILE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><rect width="40" height="20" fill="#cccccc"/>'
        '</svg>')


def _pair(tmp_path, page):
    path = tmp_path / "a.svg"
    path.write_text(FILE)
    small = page.add(Inset(str(path), center=(30, 30), width=40.0))
    big = page.add(Inset(str(path), center=(90, 30), width=40.0))
    return small, big


def _zoom_group(page):
    root = ET.fromstring(page.svg())
    marks = [g for g in root.iter(f"{SVG}g") if g.get("data-part") == "zoom"]
    assert len(marks) == 1
    return marks[0]


def test_zoom_region_outside_the_inset_is_an_error(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    with pytest.raises(ValueError, match="leaves the panel it looks at"):
        page.zoom(small, (30, 5, 60, 15), big)
    with pytest.raises(ValueError, match="empty"):
        page.zoom(small, (10, 5, 10, 15), big)


def test_a_part_names_its_region_on_a_scene_inset():
    scene, lens = bench()
    page = Page(width_mm=120, height_mm=60)
    small = page.add(Inset(scene, center=(30, 30), width=50.0))
    big = page.add(Inset(detail(), center=(90, 30), width=40.0))
    page.zoom(small, lens, big)
    x0, y0, x1, y1 = lens.drawn_box()
    corners = [(x, -y) for x, y in _polygon(_zoom_group(page))]
    assert corners[0] == pytest.approx(small.at(x0, y0).xy(), abs=2e-3)


def test_a_part_names_a_place_on_a_2d_scene_inset_only(tmp_path):
    from optodraw import SceneView

    scene, lens = bench()
    far = scene.add(Lens(center=(30, 12), focal_length=40, label="Far"))
    page = Page(width_mm=120, height_mm=60)
    flat = page.add(Inset(SceneView(scene, view="1d"), center=(30, 30), width=50.0))
    big = page.add(Inset(detail(), center=(90, 30), width=40.0))
    for part in (lens, far):              # one left the 1D panel, the other drew its box at a wrong place
        with pytest.raises(ValueError, match="a part names a place on a 2D scene"):
            page.zoom(flat, part, big)
    small, other = _pair(tmp_path, page)
    with pytest.raises(ValueError, match="a part names a place on a 2D scene"):
        page.zoom(small, lens, other)


def test_zoom_link_with_no_arguments_builds_and_draws_nothing():
    from optodraw.registry import build_component

    link = build_component("ZoomLink")
    assert link.component_type == "ZoomLink" and link.ports() == {}
    assert link.annotation_2d() == {"type": "group", "children": []} and link.drawn_points() == []


def test_the_svg_renderer_has_no_raw_type():
    import inspect

    from optodraw.renderers import svg_renderer

    assert '"raw"' not in inspect.getsource(svg_renderer)


def test_a_zoom_in_a_plain_scene_prints_its_lines_at_the_page_width(tmp_path):
    from optodraw.figure.inset import ZoomLink
    from optodraw.publication import ZOOM_DASH_MM, ZOOM_LINE_MM, export_figure

    scene = Scene(width=200, height=60)
    small, big = _pair(tmp_path, scene)
    big.move_to(150, 30)                                              # 200 units: 89 mm prints them small
    scene.add(Lens(center=(-40, 0)))
    scene.add(ZoomLink(small, (10, 5, 20, 15), big))
    path = export_figure(scene, tmp_path / "fig", width_mm=89, formats=("svg",))["svg"]
    root = ET.parse(path).getroot()
    mm_per_unit = 89.0 / float(root.get("viewBox").split()[2])
    lines = [e for e in zoom_of(root).iter() if e.tag in (f"{SVG}line", f"{SVG}path")]
    assert len(lines) == 4                                            # the box, the frame and two lines
    for line in lines:
        assert float(line.get("stroke-width")) * mm_per_unit == pytest.approx(ZOOM_LINE_MM, rel=1e-3)
        dash = [float(v) * mm_per_unit for v in line.get("stroke-dasharray").replace(",", " ").split()]
        assert dash == pytest.approx([float(v) for v in ZOOM_DASH_MM.split()], rel=1e-3)
