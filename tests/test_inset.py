"""Inset is a 2D part that draws any fragment: a file, a plot, a section. It has no ports and the 1D and 3D views
skip it."""

import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from optodraw import Inset, Laser, Scene
from optodraw.catalog import list_components
from optodraw.figure.fragment import Fragment, _scoped, _svg_size
from optodraw.figure.sources import SvgFile, to_source
from optodraw.notebook_1d import render_notebook_1d
from optodraw.registry import build_component

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
       '<rect id="a" width="40" height="20" fill="url(#a)"/></svg>')


def write(tmp_path, text=SVG, name="a.svg"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_inset_is_a_registered_part():
    empty = build_component("Inset")
    assert empty.component_type == "Inset" and empty.ports() == {}
    assert "Inset" in list_components()


def test_inset_draws_a_file_at_its_width(tmp_path):
    scene = Scene(width=100, height=60)
    inset = scene.add(Inset(write(tmp_path), center=(0, 0), width=40.0))
    assert (inset.w_mm, inset.h_mm) == (40.0, 20.0)
    assert 'data-inset="drawn"' in scene.render_svg().as_svg()


def test_two_insets_of_one_file_keep_their_ids_apart(tmp_path):
    path = write(tmp_path)
    scene = Scene(width=200, height=60)
    scene.add(Inset(path, center=(-40, 0), width=40.0))
    scene.add(Inset(path, center=(40, 0), width=40.0))
    svg = scene.render_svg().as_svg()
    ids = re.findall(r'\bid="([^"]+)"', svg)
    assert len(ids) == len(set(ids)) and len([i for i in ids if i.endswith("-a")]) == 2
    ET.fromstring(svg)


def test_inset_has_its_own_draw_type_and_no_data_art(tmp_path):
    scene = Scene(width=100, height=60)
    scene.add(Inset(write(tmp_path), width=40.0))
    assert "data-art" not in scene.render_svg().as_svg()


def test_the_frame_line_is_drawn_over_the_inset(tmp_path):
    scene = Scene(width=100, height=60)
    scene.add(Inset(write(tmp_path), width=40.0, frame=True))
    root = ET.fromstring(scene.render_svg().as_svg())
    holder = next(p for p in root.iter() if any(c.get("data-inset") is not None for c in p))
    kinds = ["drawing" if c.get("data-inset") is not None else (c.get("fill"), c.get("stroke", "none"))
             for c in holder if c.get("data-inset") is not None or c.tag.endswith("}rect")]
    assert kinds == [("#ffffff", "none"), "drawing", ("none", "#333333")]     # an opaque drawing hides no line


def test_svg_with_no_viewbox_uses_its_size(tmp_path):
    path = write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="5mm">'
                           '<rect width="10" height="5"/></svg>')
    inset = Inset(path, width=30.0)
    assert inset.w_mm / inset.h_mm == pytest.approx(2.0)
    scene = Scene(width=100, height=60)
    scene.add(inset)
    ET.fromstring(scene.render_svg().as_svg())


def test_svg_with_no_shape_gives_the_clear_error(tmp_path):
    path = write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="5"/></svg>')
    with pytest.raises(ValueError, match="no shape to lay out"):
        Inset(path, width=30.0).fragment()


def test_the_1d_and_3d_views_skip_an_inset(tmp_path):
    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(-30, 0), label="Laser"))
    scene.add(Inset(write(tmp_path), center=(20, 0), width=30.0))
    assert "data-inset" not in render_notebook_1d(scene) and "Inset" not in render_notebook_1d(scene)
    assert not any(isinstance(n, Inset) for n in scene._parts())
    from optodraw.core.view_layout import display_scene
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    items = ThreeJsRenderer(display_scene(scene, "3d"))._collect_scene_data()
    assert any(item.get("label") == "Laser" for item in items)
    assert "Inset" not in str(items)


def test_content_bounds_hold_the_inset(tmp_path):
    scene = Scene(width=100, height=60)
    scene.add(Inset(write(tmp_path), center=(10, 5), width=40.0))
    x0, y0, x1, y1 = scene.content_bounds()
    assert (x0, y0, x1, y1) == pytest.approx((-10.0, -5.0, 30.0, 15.0))


def test_a_turned_inset_holds_its_corners(tmp_path):
    inset = Inset(write(tmp_path), center=(0, 0), width=40.0, angle=90.0)
    x0, y0, x1, y1 = inset.box()
    assert (x0, y0, x1, y1) == pytest.approx((-10.0, -20.0, 10.0, 20.0))


def test_height_goes_to_a_free_shape_source_only(tmp_path):
    box = Inset(width=50.0, height=10.0)
    assert (box.w_mm, box.h_mm) == (50.0, 10.0)
    assert Inset(width=50.0).h_mm == pytest.approx(30.0)          # the empty box is 50 by 30
    with pytest.raises(ValueError, match="keeps its own shape"):
        Inset(write(tmp_path), width=40.0, height=10.0)
    with pytest.raises(ValueError, match="keeps its own shape"):
        to_source(SvgFile(write(tmp_path)), height=10.0)


def test_data_panel_holds_mm_in_a_scene_with_a_print_scale(tmp_path):
    scene = Scene(width=100, height=60)
    inset = scene.add(Inset(write(tmp_path), width=40.0))
    inset.set_print(0.5, 7.0)                                      # 40 units are 20 mm
    svg = scene.render_svg().as_svg()
    assert 'data-panel="20"' in svg and inset.w_mm == 20.0
    assert re.search(r'<svg[^>]*width="40"[^>]*height="20"', svg)     # w and h stay in drawn units


def test_a_fragment_that_reaches_outside_itself_is_kept_in(tmp_path):
    style = '<style>*{stroke-linejoin: round; stroke-linecap: butt} rect{fill: red}</style>'
    scoped = _scoped(f'<svg>{style}<rect id="r"/></svg>', "inset1")
    assert "#inset1 *{" in scoped and "#inset1 rect{" in scoped
    assert not re.search(r"(?<![\w#-])\*\{", scoped.replace("#inset1 *{", ""))
    scene = Scene(width=100, height=60)
    scene.add(Inset(write(tmp_path, SVG.replace("<rect", style + "<rect")), width=40.0))
    assert "#inset1 *{" in scene.render_svg().as_svg()


def test_scoping_keeps_at_rules_and_maps_the_root(tmp_path):
    css = ("<style>:root{--k: 1} html, body{margin: 0} @media print{a, b{color: red}} "
           "@keyframes spin{from{opacity: 0} 50%{opacity: .5} to{opacity: 1}} @font-face{font-family: X}</style>")
    out = _scoped(css, "inset3")
    assert "#inset3 > svg{--k: 1}" in out and "#inset3 > svg,#inset3 > svg{margin: 0}" in out
    assert "@media print{#inset3 a,#inset3 b{color: red}}" in out
    assert "from{opacity: 0}" in out and "50%{opacity: .5}" in out and "to{opacity: 1}" in out
    assert "@font-face{font-family: X}" in out


def test_svg_size_reads_a_viewbox_first():
    assert _svg_size('<svg viewBox="0 0 40 20" width="5mm">', "x") == (40.0, 20.0)


def test_a_fragment_is_a_plain_record():
    fragment = Fragment(svg="<svg/>", size_mm=(1.0, 2.0), place=lambda x, y: (x, y))
    assert (fragment.kind, fragment.notes, fragment.covered) == ("drawn", (), None)


def test_a_file_places_its_points_in_mm(tmp_path):
    fragment = SvgFile(write(tmp_path)).fragment(20.0, font_pt=7.0)
    assert fragment.size_mm == (20.0, 10.0) and fragment.place(40.0, 20.0) == (20.0, 10.0)


@pytest.mark.parametrize("first", ["optodraw.publication", "optodraw.figure", "optodraw.figure.fragment"])
def test_the_package_imports_in_any_order(first):
    code = f"import {first}; import optodraw.publication, optodraw.figure; print('ok')"
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr


# -- fix round 1 ------------------------------------------------------------------------------------------------

def reds(svg_text, size=200):
    """The number of red pixels in a render of ``svg_text``."""

    import io

    from PIL import Image

    from optodraw.raster import svg_to_png

    png = svg_to_png(svg_text, width=size)
    data = Image.open(io.BytesIO(png)).convert("RGB").tobytes()
    pixels = zip(data[0::3], data[1::3], data[2::3])
    return sum(1 for r, g, b in pixels if r > 200 and g < 60 and b < 60)


def test_the_source_protocol_is_exported_and_returned():
    import typing

    from optodraw.figure import EmptyBox, InsetSource

    assert typing.get_type_hints(to_source)["return"] is InsetSource
    assert isinstance(EmptyBox(), InsetSource)


@pytest.mark.parametrize("css", [
    'a::after{content:"}"} *{fill:red}',
    '[data-x="{"]{fill:red} *{fill:blue}',
    "/* } */ *{fill:red}",
    "@scope (.a){*{fill:red}}",
    "@starting-style{*{fill:red}}",
    "@layer base{*{fill:red}}",
])
def test_no_rule_stays_global(css):
    out = _scoped(f"<style>{css}</style>", "inset1")
    assert not re.search(r"(?<!#inset1 )\*\s*\{", out), out


def test_an_import_is_dropped_and_the_name_of_a_keyframe_stays_global():
    out = _scoped('<style>@import url(http://x/y.css); @keyframes spin{from{opacity:0}} *{fill:red}</style>', "inset1")
    assert "@import" not in out and "#inset1 *{fill:red}" in out
    assert "@keyframes spin{from{opacity:0}}" in out          # stated limit: animation names stay global


QUOTED = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 20'>"
          "<defs><linearGradient id='g'/></defs><rect width='40' height='20' fill='url(#g)'/></svg>")


def test_single_quoted_files_load_and_keep_their_ids_apart(tmp_path):
    path = write(tmp_path, QUOTED)
    assert _svg_size("<svg viewBox='0 0 40 20'>", "x") == (40.0, 20.0)
    scene = Scene(width=200, height=60)
    scene.add(Inset(path, center=(-40, 0), width=40.0))
    scene.add(Inset(path, center=(40, 0), width=40.0))
    svg = scene.render_svg().as_svg()
    ids = re.findall(r"""\bid=["']([^"']+)["']""", svg)
    assert len(ids) == len(set(ids)) and "url(#inset1-g)" in svg and "url(#inset2-g)" in svg


def test_the_root_of_a_file_is_rewritten_like_its_children(tmp_path):
    text = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" filter="url(#b)">'
            '<filter id="b"><feGaussianBlur stdDeviation="1"/></filter><rect width="40" height="20"/></svg>')
    scene = Scene(width=100, height=60)
    scene.add(Inset(write(tmp_path, text), width=40.0))
    assert 'filter="url(#inset1-b)"' in scene.render_svg().as_svg()


RED_ID = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><style>#a{fill:#ff0000}</style>'
          '<rect id="a" width="40" height="20" fill="#0000ff"/></svg>')
RED_CLASS = RED_ID.replace("#a{", ".c{").replace('id="a"', 'class="c"')


def test_an_id_selector_still_paints_inside_an_inset(tmp_path):
    raw = reds(RED_ID)
    scene = Scene(width=60, height=40)
    scene.add(Inset(write(tmp_path, RED_ID), width=40.0))
    assert raw > 1000 and reds(scene.render_svg().as_svg()) > 1000


@pytest.mark.parametrize("text", [RED_ID, RED_CLASS], ids=["id-rule", "class-rule"])
def test_an_id_selector_paints_in_a_panel(tmp_path, text):
    from optodraw.publication import export_panels

    scene = Scene(width=60, height=40)
    scene.add(Inset(write(tmp_path, text), width=40.0))
    direct = reds(scene.render_svg().as_svg())
    out = export_panels(tmp_path / "fig", [scene, scene], width_mm=100.0, formats=("svg",))
    assert direct > 1000 and reds(out["svg"].read_text()) > 1000


def test_two_renders_of_one_renderer_give_one_text(tmp_path):
    from optodraw.renderers.svg_renderer import SvgRenderer

    scene = Scene(width=100, height=60)
    scene.add(Inset(write(tmp_path), width=40.0))
    renderer = SvgRenderer(scene)
    assert renderer.render().as_svg() == renderer.render().as_svg()


def test_the_viewbox_of_a_file_is_kept_to_the_digit(tmp_path):
    text = SVG.replace('viewBox="0 0 40 20"', 'viewBox="123456.789 0 40 20"')
    fragment = SvgFile(write(tmp_path, text)).fragment(20.0, font_pt=7.0)
    assert 'viewBox="123456.789 0 40 20"' in fragment.svg
    assert fragment.place(123456.789 + 40.0, 20.0) == pytest.approx((20.0, 10.0))


def test_a_self_closed_root_gives_a_well_formed_scene(tmp_path):
    path = write(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"/>')
    scene = Scene(width=100, height=60)
    scene.add(Inset(path, width=40.0))
    ET.fromstring(scene.render_svg().as_svg())


def test_the_text_helper_lives_with_the_other_two():
    from optodraw.figure.fragment import _without_text

    assert _without_text('<svg><text>a</text><text>b</text></svg>', ("a",), "x") == "<svg><text>b</text></svg>"


def test_the_label_of_an_inset_is_a_name_and_prints_nothing(tmp_path):
    scene = Scene(width=100, height=60)
    scene.add(Inset(write(tmp_path), width=40.0, label="plot"))
    assert ">plot<" not in scene.render_svg().as_svg()



def test_a_root_rule_paints_the_root_of_the_fragment(tmp_path):
    text = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><style>:root > rect{fill:#ff0000}</style>'
            '<rect width="40" height="20" fill="#0000ff"/></svg>')
    scene = Scene(width=60, height=40)
    scene.add(Inset(write(tmp_path, text), width=40.0))
    assert reds(text) > 1000 and reds(scene.render_svg().as_svg()) > 1000


def test_the_tikz_view_prints_no_inset_label(tmp_path):
    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(-30, 0), label="Laser"))
    scene.add(Inset(write(tmp_path), center=(20, 0), width=30.0, label="plot name"))
    tikz = scene.render_tikz()
    assert "Laser" in tikz and "plot name" not in tikz
