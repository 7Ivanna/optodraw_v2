"""Inset is a 2D part that draws any fragment: a file, a plot, a section. It has no ports and the 1D and 3D views
skip it."""

import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from optodraw import Inset, Laser, Scene
from optodraw.figure.fragment import Fragment, _scoped
from optodraw.figure.sources import SvgFile, to_source
from optodraw.notebook_1d import render_notebook_1d

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
       '<rect id="a" width="40" height="20" fill="url(#a)"/></svg>')


def write(tmp_path, text=SVG, name="a.svg"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


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


def test_height_goes_to_a_free_shape_source_only(tmp_path):
    box = Inset(width=50.0, height=10.0)
    assert (box.w_mm, box.h_mm) == (50.0, 10.0)
    assert Inset(width=50.0).h_mm == pytest.approx(30.0)          # the empty box is 50 by 30
    with pytest.raises(ValueError, match="keeps its own shape"):
        Inset(write(tmp_path), width=40.0, height=10.0)
    with pytest.raises(ValueError, match="keeps its own shape"):
        to_source(SvgFile(write(tmp_path)), height=10.0)


def test_scoping_keeps_at_rules_and_maps_the_root(tmp_path):
    css = ("<style>:root{--k: 1} html, body{margin: 0} @media print{a, b{color: red}} "
           "@keyframes spin{from{opacity: 0} 50%{opacity: .5} to{opacity: 1}} @font-face{font-family: X}</style>")
    out = _scoped(css, "inset3")
    assert "#inset3 > svg{--k: 1}" in out and "#inset3 > svg,#inset3 > svg{margin: 0}" in out
    assert "@media print{#inset3 a,#inset3 b{color: red}}" in out
    assert "from{opacity: 0}" in out and "50%{opacity: .5}" in out and "to{opacity: 1}" in out
    assert "@font-face{font-family: X}" in out


def test_a_fragment_is_a_plain_record():
    fragment = Fragment(svg="<svg/>", size_mm=(1.0, 2.0), place=lambda x, y: (x, y))
    assert (fragment.kind, fragment.notes, fragment.covered) == ("drawn", (), None)


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


RED_ID = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20"><style>#a{fill:#ff0000}</style>'
          '<rect id="a" width="40" height="20" fill="#0000ff"/></svg>')
RED_CLASS = RED_ID.replace("#a{", ".c{").replace('id="a"', 'class="c"')


def test_the_tikz_view_prints_no_inset_label(tmp_path):
    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(-30, 0), label="Laser"))
    scene.add(Inset(write(tmp_path), center=(20, 0), width=30.0, label="plot name"))
    tikz = scene.render_tikz()
    assert "Laser" in tikz and "plot name" not in tikz
