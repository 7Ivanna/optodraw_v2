"""Text markup on labels and notes: x_i, x_{ij}, x^2, *italic*, **bold**."""

import io

import pytest

from optodraw import Laser, Scene
from optodraw.core.markup import Run, latex, plain, runs, svg_spans


def test_a_backslash_keeps_the_character():
    assert runs(r"a\_b and \*c\*") == [Run("a_b and *c*")]
    assert plain(r"x\^2") == "x^2"


def test_svg_spans_style_italic_and_bold():
    assert 'font-style="oblique"' in svg_spans("*k*", 4.0)
    assert 'font-weight="bold"' in svg_spans("**k**", 4.0)


def test_latex_writes_the_runs():
    def same(text):
        return text.replace("%", r"\%")

    assert latex("5% f_p", same) == r"5\% f\textsubscript{p}"
    assert latex("cm^2", same) == r"cm\textsuperscript{2}"
    assert latex("*k* **b**", same) == r"\textit{k} \textbf{b}"


def scene_with(label):
    scene = Scene(title="x", width=80, height=40, platform="free_space")
    scene.add(Laser(center=(-20, 0), label=label, label_side="top"))
    return scene


def ink(body):
    """The grey pixels of an SVG body that is 100 units wide, one pixel to a tenth of a unit."""

    numpy = pytest.importorskip("numpy")
    from optodraw.raster import svg_to_png
    image = pytest.importorskip("PIL.Image")
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="20mm" viewBox="0 0 100 20">{body}</svg>'
    drawn = svg_to_png(svg, width=1000, background="white")
    return numpy.asarray(image.open(io.BytesIO(drawn)).convert("L"))


