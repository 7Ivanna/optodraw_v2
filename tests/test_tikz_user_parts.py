"""A part made from SVG art goes into the 1D TikZ export as TikZ paths, with its ports named for the links."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from optodraw import Beam, Laser, PartLibrary, Photodiode, Scene, import_svg_part

ART = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 24">
  <rect x="4" y="0" width="4" height="24" rx="1" fill="#3b4148"/>
  <circle cx="6" cy="12" r="1.5" fill="none" stroke="#000"/>
  <path d="M5 4 l2 0 l0 3 z" fill="#888"/>
  <line id="port:in" x1="4" y1="12" x2="0" y2="12" data-kind="free_space"/>
  <line id="port:out" x1="8" y1="12" x2="12" y2="12" data-kind="free_space"/>
</svg>"""


def _scene():
    slit = import_svg_part("user:lab/Slit", ART, platform="free_space", origin=(6, 12), library=PartLibrary())
    scene = Scene(title="slit", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser"))
    part = scene.add(slit(center=(0, 0), label="Slit"))
    pd = scene.add(Photodiode(center=(40, 0), label="PD"))
    scene.add(Beam.through(laser, part, pd))
    return scene


def test_an_svg_part_is_drawn_as_paths_with_named_ports():
    tex = _scene().render_tikz(view="1d")
    assert "od user:" not in tex                                    # no pic that the library does not define
    assert "coordinate (n1-in)" in tex and "coordinate (n1-out)" in tex
    assert tex.count("\\path[draw=") >= 3                          # the rounded body, the circle and the mark, as lines


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="needs pdflatex")
@pytest.mark.parametrize("view", ["1d", "2d"])
def test_the_export_compiles(tmp_path, view):
    (tmp_path / "fig.tex").write_text(_scene().render_tikz(view=view, standalone=False))
    (tmp_path / "doc.tex").write_text("\\documentclass{standalone}\\usepackage{tikz}\\begin{document}"
                                      "\\input{fig.tex}\\end{document}\n")
    run = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "doc.tex"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=180)
    assert run.returncode == 0, run.stdout[-2000:]
