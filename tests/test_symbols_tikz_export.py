"""The 1D TikZ export: the library, one pic per part, links between named ports."""

from __future__ import annotations

import re

import subprocess

import pytest

import optodraw
from optodraw.symbols import build
from optodraw.symbols.tikz_export import library_source, render_tikz_1d


def _scene() -> optodraw.Scene:
    scene = optodraw.Scene(width=300, height=120, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0), label="Laser 50% & more_1"))
    lasers = [laser, scene.add(optodraw.OnChipLaser(center=(-120, 40), label="L2"))]
    mux = scene.add(optodraw.AWG(center=(-40, 0), channel_count=4, angle=180, label="mux"))
    mzm = scene.add(optodraw.MZM(center=(60, 0), label="MZM"))
    dac = scene.add(optodraw.DAC(center=(60, 60), label="DAC"))
    for k, source in enumerate(lasers):
        scene.route((source, "o1"), (mux, f"o{k + 1}"), kind="waveguide")
    scene.route((mux, "i1"), (mzm, "o1"), kind="waveguide")
    scene.route((dac, "out"), (mzm, "sig"), kind="electrical")
    return scene


def test_the_export_is_pic_code_with_links_between_named_ports():
    tikz = render_tikz_1d(_scene())
    assert tikz.count("\\begin{tikzpicture}") == 1 and tikz.rstrip().endswith("\\end{tikzpicture}")
    assert "pics/od mzi/.style" in tikz                        # the library travels with the figure
    assert "{od mzi={drive=gs, length=2}}" in tikz
    assert "\\pic [xscale=-1] (n2)" in tikz                     # the demux used as a mux is mirrored
    assert "(n2-i1) -- " in tikz and " -- (n3-o1);" in tikz       # a chip's links are square routes
    assert "rounded corners" in tikz
    assert "\\draw[od cable" in tikz and "dashed" not in tikz   # the electrical link: a solid cable
    assert "show ports" not in tikz.split("\\begin{tikzpicture}")[1]    # port marks are off in exports
    assert "Laser 50\\% \\& more\\_1" in tikz                   # labels are escaped
    assert "{od laser={contacts=top}}" in tikz


def test_a_cable_turns_sharp_and_a_waveguide_bends():
    lines = render_tikz_1d(_scene()).splitlines()
    cables = [line for line in lines if line.startswith("\\draw[od cable")]
    guides = [line for line in lines if line.startswith("\\draw[od wg") and " -- " in line]
    assert cables and not any("rounded corners" in line for line in cables)
    assert any("rounded corners" in line for line in guides)


def test_a_part_with_no_pic_is_a_labeled_box_with_named_ports():
    from optodraw.core.component import Component
    from optodraw.core.ports import Port
    from optodraw.core.transform import Vec3

    class Unknown(Component):
        def ports(self):
            return {"o1": Port("o1", Vec3(5, 0, 0), orientation_deg=0)}

        def geometry_2d(self):
            return {"type": "group", "children": []}

    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    part = scene.add(Unknown(label="new part"))
    guide = scene.add(optodraw.Waveguide(center=(60, 0), label="wg"))
    scene.add(optodraw.Beam((part, "o1"), (guide, "o1")))
    tikz = render_tikz_1d(scene)
    assert "{Unknown}" in tikz and "coordinate (n0-o1)" in tikz
    assert "(n0-o1) .. controls" in tikz


def test_the_library_can_be_left_out_for_a_second_figure():
    tikz = render_tikz_1d(_scene(), include_library=False)
    assert "pics/od mzi/.style" not in tikz and "\\pic" in tikz
    assert library_source().startswith("% od-core.tex")


def test_scene_render_tikz_takes_the_1d_view(tmp_path):
    scene = _scene()
    assert scene.render_tikz(view="1d") == render_tikz_1d(scene)
    target = tmp_path / "figure.tex"
    scene.render_tikz(str(target), view="1d", include_library=False)
    assert target.read_text(encoding="utf-8") == render_tikz_1d(scene, include_library=False)
    assert "optodrawColor" in scene.render_tikz()               # the 2D export is as before


@pytest.mark.skipif(not build.latex_available(), reason="needs latex")
def test_the_export_compiles_without_optodraw(tmp_path):
    scene = _scene()
    (tmp_path / "doc.tex").write_text(
        "\\documentclass{article}\n\\usepackage{tikz}\n\\begin{document}\n"
        + render_tikz_1d(scene) + "\n\n" + render_tikz_1d(scene, include_library=False)
        + "\\end{document}\n", encoding="utf-8")
    result = subprocess.run(["latex", "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-1500:]


def test_a_label_is_written_where_the_layout_puts_it():
    from optodraw.symbols.schematic import build_schematic
    from optodraw.symbols.tikz_export import _cm

    scene = optodraw.Scene(width=300, height=200, platform="on_chip")
    mzm = scene.add(optodraw.MZM(center=(0, 0), label="MZM"))
    scope = scene.add(optodraw.Oscilloscope(center=(0, 80), label="Scope"))
    scene.route((scope, "ch1"), (mzm, "sig"), kind="electrical")
    text = render_tikz_1d(scene, include_library=False)
    for item in build_schematic(scene).items:
        x, baseline, anchor = item.label_at
        corner = {"middle": "base", "start": "base west", "end": "base east"}[anchor]
        assert f"anchor={corner}] at {_cm(x, baseline)} {{{item.label}}}" in text
        if item.label == "Scope":
            assert baseline < item.y                           # over the instrument, clear of its cables


def test_a_turned_part_is_turned_in_the_export(tmp_path):
    """On a bench a mirror turns to face its beam: the export writes the same turn, and the figure compiles."""

    from bench_scenes import ftir_setup

    text = render_tikz_1d(ftir_setup())
    assert "\\pic [rotate=270] " in text and "\\pic [rotate=90] " in text
    if not build.latex_available():
        return
    (tmp_path / "doc.tex").write_text("\\documentclass{article}\n\\usepackage{tikz}\n\\begin{document}\n"
                                      + text + "\n\\end{document}\n", encoding="utf-8")
    result = subprocess.run(["latex", "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-1500:]


@pytest.mark.skipif(not build.latex_available(), reason="needs latex and dvisvgm")
def test_the_library_adds_no_space_where_it_sits(tmp_path):
    """A figure exported with its library is as wide as the picture: the library typesets nothing."""

    def width(body: str) -> float:
        (tmp_path / "w.tex").write_text("\\documentclass[dvisvgm]{standalone}\n\\usepackage{tikz}\n\\begin{document}\n"
                                        + body + "\\begin{tikzpicture}\\draw (0,0) -- (1,0);\\end{tikzpicture}\n"
                                        "\\end{document}\n", encoding="utf-8")
        subprocess.run(["latex", "-interaction=nonstopmode", "-halt-on-error", "w.tex"], cwd=tmp_path,
                       capture_output=True, timeout=120, check=True)
        subprocess.run(["dvisvgm", "--no-fonts", "--bbox=papersize", "w.dvi", "-o", "w.svg"], cwd=tmp_path,
                       capture_output=True, timeout=120, check=True)
        return float(re.search(r"width=.([0-9.]+)pt", (tmp_path / "w.svg").read_text()).group(1))

    assert abs(width(library_source()) - width("")) < 1.0
