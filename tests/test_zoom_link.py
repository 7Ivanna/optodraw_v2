"""Panel(zoom=(panel, region)) says one panel is a closer view of a place on another, and draws the link."""

import math
import xml.etree.ElementTree as ET

import pytest

from optodraw import Laser, Lens, Panel, Scene, check_export, export_panels
from optodraw.gds import stack_section

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


def test_a_figure_with_no_zoom_draws_no_link(tmp_path):
    root = write(tmp_path, [[Panel(bench()[0]), Panel(detail())]])
    assert not [g for g in root.iter(f"{SVG}g") if g.get("data-part") == "zoom"]


def test_the_box_stands_on_the_place_it_names(tmp_path):
    scene, _ = bench()
    first = Panel(scene)
    root = write(tmp_path, [[first, Panel(detail(), zoom=(first, (-5, -6, 5, 8)))]])
    x, y, w, h = zoom_box(zoom_of(root))
    assert (x, y) == pytest.approx(page_of(panels(root)[0], -5, -8), abs=2e-3)        # y runs up in a scene
    assert (x + w, y + h) == pytest.approx(page_of(panels(root)[0], 5, 6), abs=2e-3)


def test_side_by_side_the_lines_join_the_facing_corners(tmp_path):
    scene, _ = bench()
    first = Panel(scene)
    root = write(tmp_path, [[first, Panel(detail(), zoom=(first, (-5, -6, 5, 8)))]])
    mark = zoom_of(root)
    x, y, w, h = zoom_box(mark)
    tx, ty, tw, th = box(panels(root)[1])
    ends = sorted((float(l.get("x1")), float(l.get("y1")), float(l.get("x2")), float(l.get("y2")))
                  for l in mark.iter(f"{SVG}line"))
    assert len(ends) == 2
    assert ends[0] == pytest.approx((x + w, y, tx, ty), abs=2e-3)
    assert ends[1] == pytest.approx((x + w, y + h, tx, ty + th), abs=2e-3)


def test_on_rows_the_lines_leave_the_bottom_of_the_box(tmp_path):
    scene, _ = bench()
    first = Panel(scene)
    root = write(tmp_path, [[first], [Panel(detail(), zoom=(first, (-5, -6, 5, 8)))]])
    mark = zoom_of(root)
    x, y, w, h = zoom_box(mark)
    tx, ty, tw, _ = box(panels(root)[1])
    ends = sorted((float(l.get("x1")), float(l.get("y1")), float(l.get("x2")), float(l.get("y2")))
                  for l in mark.iter(f"{SVG}line"))
    assert ends[0] == pytest.approx((x, y + h, tx, ty), abs=2e-3)
    assert ends[1] == pytest.approx((x + w, y + h, tx + tw, ty), abs=2e-3)


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


def test_the_zoom_panel_gets_a_frame(tmp_path):
    scene, _ = bench()
    first = Panel(scene)
    root = write(tmp_path, [[first, Panel(detail(), zoom=(first, (-5, -6, 5, 8)))]])
    paths = list(zoom_of(root).iter(f"{SVG}path"))
    assert len(paths) == 2                              # the box on the source and the frame on the zoom panel
    xs, ys = zip(*_points(paths[1]))
    frame = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    assert frame == pytest.approx(box(panels(root)[1]), abs=2e-3)
    assert frames(root) == []                           # no solid frame of the inset's own


def test_a_part_names_its_own_box(tmp_path):
    scene, lens = bench()
    first = Panel(scene)
    root = write(tmp_path, [[first, Panel(detail(), zoom=(first, lens))]])
    x, y, w, h = zoom_box(zoom_of(root))
    left, top = page_of(panels(root)[0], -1.0, 0.0)
    assert x < page_of(panels(root)[0], 0.0, 0.0)[0] < x + w
    assert y < page_of(panels(root)[0], 0.0, 0.0)[1] < y + h


def test_a_scene_itself_names_the_source(tmp_path):
    scene, _ = bench()
    root = write(tmp_path, [[scene, Panel(detail(), zoom=(scene, (-5, -6, 5, 8)))]])
    assert zoom_of(root) is not None


def test_an_svg_file_uses_the_units_of_its_view_box_with_y_down(tmp_path):
    path = tmp_path / "plot.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><rect width="100" height="50" '
                    'fill="#eee"/></svg>', encoding="utf-8")
    first = Panel(str(path))
    root = write(tmp_path, [[first, Panel(detail(), zoom=(first, (10, 5, 20, 15)))]])
    x, y, _, _ = zoom_box(zoom_of(root))
    assert (x, y) == pytest.approx(page_of(panels(root)[0], 10, 5), abs=2e-3)


def test_a_cross_section_can_be_the_zoom(tmp_path):
    scene, lens = bench()
    first = Panel(scene)
    root = write(tmp_path, [[first, Panel(stack_section("gdsfactory_generic", (1, 0), width=0.5), zoom=(first, lens))]])
    assert len(panels(root)) == 2 and zoom_of(root) is not None


def test_a_source_not_in_the_figure_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not in the figure"):
        write(tmp_path, [[Panel(bench()[0]), Panel(detail(), zoom=(Panel(detail()), (0, 0, 1, 1)))]])


def test_an_empty_region_is_refused(tmp_path):
    first = Panel(bench()[0])
    with pytest.raises(ValueError, match="region"):
        write(tmp_path, [[first, Panel(detail(), zoom=(first, (5, 5, 5, 9)))]])


def test_a_region_past_the_panel_is_refused(tmp_path):
    first = Panel(bench()[0])
    with pytest.raises(ValueError, match="region"):
        write(tmp_path, [[first, Panel(detail(), zoom=(first, (500, 0, 510, 9)))]])


def test_a_part_cannot_name_a_place_on_a_file(tmp_path):
    path = tmp_path / "plot.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"></svg>', encoding="utf-8")
    first = Panel(str(path))
    with pytest.raises(ValueError, match="part"):
        write(tmp_path, [[first, Panel(detail(), zoom=(first, bench()[1]))]])


def test_a_part_cannot_name_a_place_on_a_1d_panel(tmp_path):
    scene, lens = bench()
    first = Panel(scene, view="1d")
    with pytest.raises(ValueError, match="a part names a place on a 2D scene"):
        write(tmp_path, [[first, Panel(detail(), zoom=(first, lens))]])


def test_a_zoom_panel_is_its_panel_too(tmp_path):
    scene, _ = bench()
    first = Panel(scene)
    root = write(tmp_path, [[first, Panel(detail(), zoom=(first, (-5, -6, 5, 8)))]])
    assert [t.text for t in root if t.tag == f"{SVG}text"] == ["a", "b"]


def test_the_link_is_not_a_hairline_on_paper(tmp_path):
    scene, _ = bench()
    first = Panel(scene)
    path = export_panels(tmp_path / "fig", [[first, Panel(detail(), zoom=(first, (-5, -6, 5, 8)))]], width_mm=183,
                         formats=("svg",))["svg"]
    assert not [f for f in check_export(path) if "thinner" in f]


def test_the_export_gate_finds_a_zoom_line_through_a_label(tmp_path):
    path = tmp_path / "fig.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm" viewBox="0 0 120 80">'
                    '<text x="20" y="40" font-size="2.47" font-family="Helvetica">Objective</text>'
                    '<g data-part="zoom" fill="none" stroke="#777" stroke-width="0.12">'
                    '<line x1="0" y1="39" x2="100" y2="39"/></g></svg>', encoding="utf-8")
    assert any('"Objective"' in f and "zoom" in f for f in check_export(path))


def test_the_export_gate_passes_a_zoom_line_clear_of_the_labels(tmp_path):
    path = tmp_path / "fig.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm" viewBox="0 0 120 80">'
                    '<text x="20" y="40" font-size="2.47" font-family="Helvetica">Objective</text>'
                    '<g data-part="zoom" fill="none" stroke="#777" stroke-width="0.12">'
                    '<line x1="0" y1="60" x2="100" y2="60"/></g></svg>', encoding="utf-8")
    assert not [f for f in check_export(path) if "zoom" in f]


# ---- ZoomLink on a Page: drawn from the live places of two insets ----

from optodraw import Inset  # noqa: E402
from optodraw.check import _read_page  # noqa: E402
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


def _lines(mark):
    return sorted((float(e.get("x1")), float(e.get("y1")), float(e.get("x2")), float(e.get("y2")))
                  for e in mark.iter(f"{SVG}line"))


def test_page_zoom_draws_box_and_two_lines(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    link = page.zoom(small, (10, 5, 20, 15), big)
    assert link.component_type == "ZoomLink"
    mark = _zoom_group(page)
    corners = [(x, -y) for x, y in _polygon(mark)]               # the page is y up, its SVG y down
    want = [small.at(10, 5).xy(), small.at(20, 5).xy(), small.at(20, 15).xy(), small.at(10, 15).xy()]
    assert corners == pytest.approx(want, abs=2e-3)
    bx0, by0, bx1, by1 = big.box()
    x0, y0, x1, y1 = min(c[0] for c in want), min(c[1] for c in want), max(c[0] for c in want), max(c[1] for c in want)
    lines = [(a, -b, c, -d) for a, b, c, d in _lines(mark)]
    assert len(lines) == 2
    assert sorted(lines) == pytest.approx(sorted([(x1, y1, bx0, by1), (x1, y0, bx0, by0)]), abs=2e-3)


def test_zoom_link_follows_both_insets_after_a_move(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    page.zoom(small, (10, 5, 20, 15), big)
    before = _lines(_zoom_group(page))
    small.move_to(30, 40)
    big.move_to(90, 20)
    mark = _zoom_group(page)
    assert _lines(mark) != before
    corners = [(x, -y) for x, y in _polygon(mark)]
    assert corners[0] == pytest.approx(small.at(10, 5).xy(), abs=2e-3)
    bx0, by0, bx1, by1 = big.box()
    ends = {(round(c, 3), round(-d, 3)) for _, _, c, d in _lines(mark)}
    assert ends == {(round(bx0, 3), round(by0, 3)), (round(bx0, 3), round(by1, 3))}


def test_a_turned_inset_gets_a_turned_box(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    small.transform.rotation_deg = type(small.transform.rotation_deg)(0.0, 0.0, 30.0)
    page.zoom(small, (10, 5, 20, 15), big)
    xs = {round(x, 3) for x, _ in _polygon(_zoom_group(page))}
    assert len(xs) == 4                                           # not an upright rectangle


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


def test_a_zoom_link_frames_the_big_inset_like_its_box(tmp_path):
    from optodraw.publication import ZOOM_COLOR, ZOOM_DASH_MM, ZOOM_LINE_MM

    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    page.zoom(small, (10, 5, 20, 15), big)
    elements = list(ET.fromstring(page.svg()).iter())
    mark = next(e for e in elements if e.get("data-part") == "zoom")
    assert elements.index(mark) > max(i for i, e in enumerate(elements) if e.get("data-inset") is not None)
    paths = list(mark.iter(f"{SVG}path"))
    assert len(paths) == 2
    for path in paths:                    # two matching dashed grey rectangles
        look = (path.get("fill"), path.get("stroke"), path.get("stroke-dasharray"), float(path.get("stroke-width")))
        assert look == ("none", ZOOM_COLOR, ZOOM_DASH_MM, ZOOM_LINE_MM)
    bx0, by0, bx1, by1 = big.box()
    corners = sorted((x, -y) for x, y in _points(paths[1]))
    assert corners == pytest.approx(sorted([(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]), abs=2e-3)


def test_zoom_link_with_no_arguments_builds_and_draws_nothing():
    from optodraw.registry import build_component

    link = build_component("ZoomLink")
    assert link.component_type == "ZoomLink" and link.ports() == {}
    assert link.annotation_2d() == {"type": "group", "children": []} and link.drawn_points() == []


def test_the_export_gate_finds_the_lines_of_a_zoom_link(tmp_path):
    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    page.zoom(small, (10, 5, 20, 15), big)
    root = ET.fromstring(page.svg())
    assert len(_read_page(root, "page.svg").zoom_lines) == 2
    path = tmp_path / "fig.svg"
    path.write_text(page.svg())
    assert not [f for f in check_export(path) if "thinner" in f]


def test_a_strict_render_of_a_page_with_a_zoom_link_passes(tmp_path):
    from optodraw.renderers.svg_renderer import SvgRenderer

    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    page.zoom(small, (10, 5, 20, 15), big)
    page._insets()
    svg = SvgRenderer(page, strict=True).render().as_svg()
    assert 'data-part="zoom"' in svg


def test_the_svg_renderer_has_no_raw_type():
    import inspect

    from optodraw.renderers import svg_renderer

    assert '"raw"' not in inspect.getsource(svg_renderer)


def test_a_zoom_link_saves_like_any_part(tmp_path):
    from optodraw.schema import component_to_spec

    page = Page(width_mm=120, height_mm=60)
    small, big = _pair(tmp_path, page)
    link = page.zoom(small, (10, 5, 20, 15), big)
    assert component_to_spec(link)["type"] == "ZoomLink"
    assert link.to_dict()["type"] == "ZoomLink"
    assert link.opacity == 1.0 and link.label_side == "top"


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
