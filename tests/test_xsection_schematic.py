"""Look A: the cross-section as a textbook process figure."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from optodraw.gds.layout import GDSLayerRecord, GDSLayout
from optodraw.gds.xsection.model import cross_section


def _record(spec, polygons):
    return GDSLayerRecord(spec=spec, name=f"L{spec[0]}", description="", color="#000000", opacity=1.0,
                          thickness=0.22, zmin=0.0, material_preset="silicon", polygons=polygons, matched_pdk=False)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _modulator():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)]),
        _record((20, 0), [_rect(-20, -3, 20, 0)]), _record((21, 0), [_rect(-20, 0, 20, 3)]),
        _record((40, 0), [_rect(-20, -2.8, 20, -2.2)]), _record((41, 0), [_rect(-20, -3.2, 20, -1.8)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -6), (0, 6)))


def _wide_modulator():
    """The modulator with a 10 um slab: at 89 mm its 90 nm slab is under 2 pt in true aspect."""

    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -5, 20, 5)]),
        _record((20, 0), [_rect(-20, -5, 20, 0)]), _record((21, 0), [_rect(-20, 0, 20, 5)]),
        _record((40, 0), [_rect(-20, -4.6, 20, -3.9)]), _record((41, 0), [_rect(-20, -5.5, 20, -3.0)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -7), (0, 7)))


def _nitride_strip():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((203, 0), [_rect(-20, -0.6, 20, 0.6)])])
    return cross_section(layout, "cornerstone_sin300", ((0, -3), (0, 3)))


def _root(svg):
    return dict(re.findall(r'(\w[\w-]*)="([^"]*)"', re.search(r"<svg\b[^>]*>", svg).group(0)))


def test_the_figure_is_the_preset_width_in_millimetres():
    svg = _modulator().svg(preset="single_column")
    assert _root(svg)["width"] == "89mm"


def test_true_aspect_prints_no_z_scale():
    svg = _modulator().svg(labels=False, dims=None, z_scale=1)
    assert "z ×" not in svg and 'class="z-scale-bar"' not in svg


def test_a_thin_slab_is_exaggerated_by_default_and_says_by_how_much():
    svg = _wide_modulator().svg(dims=None)
    [n] = re.findall(r"z × (\d+)", svg)
    assert int(n) in (2, 3, 5, 10, 20, 50)
    assert 'class="z-scale-bar"' in svg


def test_auto_keeps_true_aspect_when_every_layer_reads():
    svg = _nitride_strip().svg(labels=False, dims=None)
    assert "z ×" not in svg


def test_an_explicit_z_scale_is_printed_with_a_vertical_bar():
    xs = _modulator()
    plain = xs.svg(labels=False, dims=None, z_scale=1)
    tall = xs.svg(labels=False, dims=None, z_scale=3)
    assert "z × 3" in tall
    assert re.search(r'class="z-scale-bar".*?>\s*\d+(\.\d+)?\s*(µm|nm)\s*<', tall, re.S)
    assert float(_root(tall)["height"][:-2]) > float(_root(plain)["height"][:-2])


def test_every_region_is_drawn_with_its_material_colour():
    from optodraw.gds.palette import material_fill

    svg = _modulator().svg(labels=False, dims=None)
    for region, colour in (("device", material_fill("silicon")), ("oxide", material_fill("sio2")),
                           ("M1", material_fill("aluminum"))):
        assert re.search(rf'data-region="{re.escape(region)}"[^>]*fill="{colour}"', svg), region


def test_a_colour_option_overrides_the_palette():
    svg = _modulator().svg(labels=False, dims=None, colors={"device": "#123456"})
    assert re.search(r'data-region="device"[^>]*fill="#123456"', svg)


def test_a_thick_box_is_cut_short_with_a_break_and_a_substrate_stub():
    svg = _modulator().svg(labels=True, dims=None)
    assert 'class="break"' in svg and "Si substrate" in svg


def test_a_scale_bar_names_its_length():
    svg = _modulator().svg(labels=False, dims=None)
    assert re.search(r'class="scale-bar".*?>\s*\d+(\.\d+)?\s*(µm|nm)\s*<', svg, re.S)


def test_doping_is_drawn_over_the_silicon():
    svg = _modulator().svg(labels=False, dims=None)
    assert svg.count('class="doping"') >= 2


def _labels(svg):
    """(text, x, y, font size, anchor) of each label. A label with a script (SiO2) has no anchor: it starts at x."""

    out = []
    for head, inner in re.findall(r'<text ([^>]*class="label"[^>]*)>(.*?)</text>', svg):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', head))
        out.append((re.sub(r"<[^>]+>", "", inner), float(attrs["x"]), float(attrs["y"]), float(attrs["font-size"]),
                    attrs.get("text-anchor", "start")))
    return out


def _text_boxes(svg):
    boxes = []
    for text, x, y, size, anchor in _labels(svg):
        width = len(text) * size * 0.6
        left = x - width / 2 if anchor == "middle" else x
        boxes.append((text, left, y - size * 0.8, left + width, y + size * 0.2))
    return boxes


def test_every_region_gets_one_label():
    svg = _modulator().svg(dims=None)
    texts = [t for t, *_ in _text_boxes(svg)]
    for name in ("Si", "BOX", "SiO2", "M1", "VIAC", "Si substrate", "N", "P"):
        assert texts.count(name) == 1, name


def test_labels_never_overlap():
    boxes = _text_boxes(_modulator().svg(dims=None))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[3] <= b[1] or b[3] <= a[1] or a[4] <= b[2] or b[4] <= a[2], (a[0], b[0])


def test_labels_stay_inside_the_figure():
    svg = _modulator().svg(dims=None)
    width, height = float(_root(svg)["width"][:-2]), float(_root(svg)["height"][:-2])
    for text, x0, y0, x1, y1 in _text_boxes(svg):
        assert 0 <= x0 and x1 <= width and 0 <= y0 and y1 <= height, text


def test_a_label_that_does_not_fit_inside_gets_a_leader():
    svg = _modulator().svg(dims=None)
    assert 'class="leader"' in svg                                         # VIAC is far too narrow to hold its name


def test_auto_dimensions_give_the_rib_and_slab_sizes():
    svg = _modulator().svg(labels=False)
    texts = re.findall(r'<g class="dim">.*?<text[^>]*>([^<]+)</text>', svg, re.S)
    assert "500 nm" in texts and "220 nm" in texts and "90 nm" in texts


def test_a_dimension_list_keeps_only_the_named_ones():
    svg = _modulator().svg(labels=False, dims=["rib width"])
    assert svg.count('<g class="dim">') == 1


def test_dimension_texts_and_labels_never_overlap():
    svg = _modulator().svg()
    boxes = _text_boxes(svg)
    for x, y, size, anchor, text in re.findall(
            r'<g class="dim">.*?<text x="([\d.]+)" y="([\d.]+)" font-size="([\d.]+)"[^>]*text-anchor="(\w+)"[^>]*>([^<]+)<',
            svg, re.S):
        x, y, size = float(x), float(y), float(size)
        width = len(text) * size * 0.6
        left = {"middle": x - width / 2, "end": x - width}.get(anchor, x)
        boxes.append((text, left, y - size * 0.8, left + width, y + size * 0.2))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[3] <= b[1] or b[3] <= a[1] or a[4] <= b[2] or b[4] <= a[2], (a[0], b[0])


def test_the_process_strip_has_one_captioned_panel_per_step():
    xs = _modulator()
    svg = xs.steps_svg()
    assert svg.count('<svg class="step"') == len(xs.steps)
    captions = [" ".join(re.findall(r"<tspan[^>]*>([^<]*)</tspan>", body))
                for body in re.findall(r'<text class="caption"[^>]*>(.*?)</text>', svg)]
    assert captions[0] == "1. SOI wafer"
    assert captions == [f"{index}. {caption}" for index, (_, caption, _) in enumerate(xs.steps, start=1)]


def test_the_process_strip_shares_one_z_stretch():
    svg = _modulator().steps_svg()
    assert len(set(re.findall(r"z × (\d+)", svg))) <= 1


def _heavy_modulator():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -5, 20, 5)]),
        _record((24, 0), [_rect(-20, -5, 20, -3.5)]), _record((25, 0), [_rect(-20, 3.5, 20, 5)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -7), (0, 7)))


def test_the_strip_names_the_heavy_implants_as_the_figure_does():
    xs = _heavy_modulator()
    captions = [caption for _, caption, _ in xs.steps]
    assert "N++ implant" in captions and "P++ implant" in captions
    assert not any("NPP" in caption or "PPP" in caption for caption in captions)
    svg = xs.steps_svg()
    first = captions.index("N++ implant")
    panels = re.findall(r'<svg class="step".*?</svg>', svg, re.S)
    assert ['data-species="NPP"' in panel for panel in panels] == [index >= first for index in range(len(panels))]


def _bar_parts(svg):
    """(s bar: x0, x1, y; its text: x, y, anchor, text) and the same for the z bar (x, y0, y1)."""

    s_group = re.search(r'<g class="scale-bar">(.*?)</g>', svg, re.S).group(1)
    z_group = re.search(r'<g class="z-scale-bar">(.*?)</g>', svg, re.S).group(1)
    x0, y, length = map(float, re.search(r'd="M([\d.]+),([\d.]+) h([\d.]+)"', s_group).groups())
    zx, zy, tall = map(float, re.search(r'd="M([\d.]+),([\d.]+) v(-[\d.]+)"', z_group).groups())
    def text(group):
        tag, value = re.search(r'(<text [^>]*>)([^<]+)<', group).groups()
        x, y, size = re.search(r'x="([\d.]+)" y="([\d.]+)" font-size="([\d.]+)"', tag).groups()
        anchor = re.search(r'text-anchor="(\w+)"', tag)
        return x, y, size, anchor.group(1) if anchor else "start", value

    return (x0, x0 + length, y, text(s_group)), (zx, zy + tall, zy, text(z_group))


def test_the_scale_bar_values_sit_clear_of_both_bars():
    svg = _wide_modulator().svg(dims=None)
    (s0, s1, sy, (tx, ty, size, anchor, value)), (zx, ztop, zbottom, (zx_t, zy_t, zsize, zanchor, zvalue)) = \
        _bar_parts(svg)
    assert float(tx) >= s1 + 0.5                                       # the s value right of its bar
    assert zanchor == "end" and float(zx_t) <= zx - 0.5                # the z value left of its bar
    z_box_right, z_box_bottom = float(zx_t), float(zy_t) + 0.2 * float(zsize)
    assert z_box_right < s0 or z_box_bottom < sy - 0.3                 # never on the s bar's line
    stretch = re.search(r'<text class="z-stretch" x="([\d.]+)"', svg)
    assert float(stretch.group(1)) > float(tx) + len(value) * float(size) * 0.6


def _rib_only():
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, -0.25, 20, 0.25)]), _record((3, 0), [_rect(-20, -3, 20, 3)])])
    return cross_section(layout, "gdsfactory_generic", ((0, -5), (0, 5)))


def _region_paths(svg, region):
    out = []
    for d in re.findall(rf'data-region="{re.escape(region)}"[^>]*d="([^"]+)"', svg):
        out.append([tuple(map(float, point.split(","))) for point in re.findall(r"[\d.]+,[\d.]+", d)])
    return out


def test_a_thick_top_oxide_is_cut_short_and_keeps_its_surface():
    svg = _rib_only().svg(labels=False, dims=None, z_scale=1)
    assert svg.count('class="break"') == 2                                 # the BOX and the top oxide
    oxide = sorted(_region_paths(svg, "oxide"), key=lambda points: min(y for _, y in points))
    upper, lower = oxide[0], oxide[-1]
    assert len({round(y, 3) for _, y in upper}) > 2                        # the conformal bumps still show
    (bar_mm, value), = re.findall(r'<g class="scale-bar"><path d="M[\d.]+,[\d.]+ h([\d.]+)".*?>([\d.]+) µm<', svg)
    mm_per_um = float(bar_mm) / float(value)
    device_top = min(y for points in _region_paths(svg, "device") for _, y in points)
    kept = (device_top - min(y for _, y in lower)) / mm_per_um
    assert kept == pytest.approx(max(0.4, 4.5 / mm_per_um), abs=0.02)      # 0.4 um, or room for the rib width


def test_the_cut_top_oxide_keeps_room_for_the_rib_width():
    texts = re.findall(r'<g class="dim">.*?<text[^>]*>([^<]+)</text>', _rib_only().svg(), re.S)
    assert "500 nm" in texts and "220 nm" in texts and "90 nm" in texts


def test_a_thin_top_oxide_is_drawn_whole():
    svg = _nitride_strip().svg(labels=False, dims=None)
    assert svg.count('class="break"') == 1


def test_no_two_leader_lines_cross():
    """The PN phase shifter of the docs page: the VIAC leader and the N++ leader once crossed."""

    import re
    from pathlib import Path

    from shapely.geometry import LineString

    cell = Path(__file__).resolve().parents[1] / "docs" / "examples" / "cross-sections" / "01-schematic.py"
    namespace: dict = {"__name__": "__main__"}
    exec(compile(cell.read_text(encoding="utf-8"), str(cell), "exec"), namespace)
    svg = namespace["xs"].svg()
    lines = [LineString([(float(a), float(b)), (float(c), float(d))])
             for a, b, c, d in re.findall(r'class="leader" d="M([-\d.]+),([-\d.]+) L([-\d.]+),([-\d.]+)"', svg)]
    assert len(lines) >= 2
    assert not [(i, j) for i in range(len(lines)) for j in range(i + 1, len(lines)) if lines[i].intersects(lines[j])]


def _pn_m3():
    """The docs device: straight_pn with via_stack_slab_m3, contacts through M1 and M2 to the M3 pads, the
    passivation opened on PADOPEN."""

    pads = [_rect(0, 1, 20, 11), _rect(0, -11, 20, -1)]
    holes = [_rect(x - 0.35, y - 0.35, x + 0.35, y + 0.35) for x in range(2, 20, 2) for y in (-9, -7, -5, -3, 3, 5, 7, 9)]
    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(0, -11, 20, 11), layer_records=[
        _record((1, 0), [_rect(0, -0.25, 20, 0.25)]), _record((3, 0), [_rect(0, -3.5, 20, 3.5), *pads]),
        _record((20, 0), [_rect(0, -8, 20, 0)]), _record((21, 0), [_rect(0, 0, 20, 8)]),
        _record((24, 0), [_rect(0, -8, 20, -1)]), _record((25, 0), [_rect(0, 1, 20, 8)]),
        _record((40, 0), holes), _record((41, 0), pads), _record((44, 0), holes), _record((45, 0), pads),
        _record((43, 0), holes), _record((49, 0), pads),
        _record((46, 0), [_rect(1.5, 2.5, 18.5, 9.5), _rect(1.5, -9.5, 18.5, -2.5)])])
    return cross_section(layout, "gdsfactory_generic", ((2, 12), (2, -12)))


def test_no_label_is_dropped_when_the_oxide_has_no_room_for_it():
    """With the passivation's long name the label column grew, the plot narrowed, and the SiO2 label found no
    room between the contact stacks: it was left out. A label with no room inside goes to the column."""

    texts = [t for t, *_ in _text_boxes(_pn_m3().svg())]                  # with its dimension marks, as in the docs
    for name in ("SiO2", "BOX", "M3", "M2", "M1", "VIA2", "VIA1", "VIAC"):     # the passivation is oxide: no label
        assert texts.count(name) == 1, (name, texts)


def test_an_oxide_label_in_the_column_keeps_its_leader_off_the_metal():
    """The SiO2 label went to the column with a leader from the gap between the contact stacks, straight
    through M1. An oxide's leader starts where the oxide meets the column side of the figure."""

    from shapely.geometry import LineString, Polygon

    svg = _pn_m3().svg()
    metal = []
    for name, d in re.findall(r'<path class="region" data-region="([^"]+)"[^>]*\bd="([^"]+)"', svg):
        if name.startswith(("M", "VIA")):
            for ring in re.split(r"Z\s*", d):
                points = [(float(x), float(y)) for x, y in re.findall(r"([-\d.]+),([-\d.]+)", ring)]
                if len(points) >= 3:
                    metal.append(Polygon(points))
    x, y = next((x, y) for text, x, y, _, _ in _labels(svg) if text == "SiO2")
    leaders = [LineString([(float(a), float(b)), (float(c), float(d))]) for a, b, c, d in
               re.findall(r'class="leader" d="M([-\d.]+),([-\d.]+) L([-\d.]+),([-\d.]+)"', svg)]
    leader = min(leaders, key=lambda line: line.distance(LineString([(x, y), (x + 1, y)])))
    assert not [shape for shape in metal if leader.crosses(shape) or leader.within(shape)], leader.wkt


def test_a_room_folded_by_the_height_break_does_not_break_the_labels():
    # the docs device moved to its centre, as the editor holds it: the BOX and top-oxide breaks fold an oxide
    # room on the page, and the label search joined the rooms with GEOS, which refused the folded one
    import dataclasses
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "docs" / "examples" / "cross-sections" / "01-schematic.py"
    namespace: dict = {}
    exec(compile(example.read_text(encoding="utf-8"), str(example), "exec"), namespace)
    layout = namespace["layout"]
    centred = dataclasses.replace(layout, layer_records=[
        dataclasses.replace(r, polygons=[[(x - 10.0, y) for x, y in points] for points in r.polygons])
        for r in layout.layer_records])
    xs = cross_section(centred, "gdsfactory_generic", ((0.0, -11.0), (0.0, 11.0)))
    assert "<svg" in xs.svg()


def test_a_deep_substrate_under_a_thin_box_is_a_stub_under_a_break():
    """The InP section drew its 2 um model substrate in full under a thin 0.5 um buffer: stretched five times, the
    figure stood twice as tall as it was wide and its labels read at a third of their size on a page. A substrate
    under a BOX too thin to cut is the stub under the break, as on silicon."""

    layout = GDSLayout(source_path=Path("t.gds"), cell_name="T", bounds=(-50, -50, 50, 50), layer_records=[
        _record((1, 0), [_rect(-20, 0.75, 20, 3.75)]), _record((1, 0), [_rect(-20, -3.75, 20, -0.75)])])
    xs = cross_section(layout, "inp_generic", ((0, -5), (0, 5)), window=(1.0, 9.0))
    svg = xs.svg()
    assert not re.search(r'data-region="handle"', svg), "the substrate is drawn in full, not as a stub"
    assert svg.count("InP substrate") == 1                          # named once, in its stub
