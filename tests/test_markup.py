"""Text markup on labels and notes: x_i, x_{ij}, x^2, *italic*, **bold**."""

import io

import pytest

from optodraw import Laser, Lens, Note, Scene, check_figure
from optodraw.core.markup import Run, latex, plain, runs, svg_spans, svg_text
from optodraw.notebook_1d import render_notebook_1d
from optodraw.schema import scene_from_spec, scene_to_spec


def test_plain_text_is_one_run():
    assert runs("Laser source") == [Run("Laser source")]


@pytest.mark.parametrize("text", ["beam_splitter", "rf_to_pad", "thin_lens_singlet", "2 * 3 * 4", "a*b", "x^", "x_",
                                  "AB12-345", "5 mW/cm", "f = 50 mm", "_x", "^2"])
def test_text_that_is_not_markup_stays_as_written(text):
    assert runs(text) == [Run(text)]
    assert plain(text) == text


def test_a_one_letter_subscript():
    assert runs("f_p") == [Run("f"), Run("p", script="sub")]


def test_a_braced_subscript_takes_several_letters():
    assert runs("T_{ij} here") == [Run("T"), Run("ij", script="sub"), Run(" here")]


def test_a_superscript():
    assert runs("cm^2") == [Run("cm"), Run("2", script="sup")]
    assert runs("cm^{-1}") == [Run("cm"), Run("-1", script="sup")]


def test_a_script_ends_before_a_following_word():
    assert runs("f_p and g") == [Run("f"), Run("p", script="sub"), Run(" and g")]


def test_italic():
    assert runs("the *k* vector") == [Run("the "), Run("k", italic=True), Run(" vector")]


def test_bold():
    assert runs("a **fast** path") == [Run("a "), Run("fast", bold=True), Run(" path")]


def test_a_script_inside_italic_stays_italic():
    assert runs("*f_p*") == [Run("f", italic=True), Run("p", script="sub", italic=True)]


def test_a_backslash_keeps_the_character():
    assert runs(r"a\_b and \*c\*") == [Run("a_b and *c*")]
    assert plain(r"x\^2") == "x^2"


def test_plain_gives_the_words_alone():
    assert plain("the *k_x* vector, cm^{-1}") == "the k" "x vector, cm-1"


def test_svg_spans_of_plain_text_are_the_escaped_text():
    assert svg_spans("a < b", 3.0) == "a &lt; b"


def test_svg_spans_shift_a_script_and_bring_the_text_back():
    spans = svg_spans("f_p x", 4.0)
    assert spans.startswith("f<tspan")
    assert 'font-size="2.88"' in spans                                       # 0.72 of the text
    assert spans.count('dy="1"') == 1 and spans.count('dy="-1"') == 1        # down a quarter of the size, and back


def test_svg_spans_lift_a_superscript():
    spans = svg_spans("cm^2", 4.0)
    assert 'dy="-1.52"' in spans and spans.endswith("</tspan>")


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


def test_a_part_label_draws_its_script_in_2d():
    svg = scene_with("f_p").render_svg().as_svg()
    assert "<tspan" in svg and "f_p" not in svg


def test_a_plain_label_keeps_its_bytes():
    plain_svg = scene_with("Laser").render_svg().as_svg()
    assert "<tspan" not in plain_svg and ">Laser<" in plain_svg


def test_a_note_draws_its_script():
    scene = scene_with("Laser")
    scene.add(Note("P_{in} = 1 mW", center=(0, 10)))
    svg = scene.render_svg().as_svg()
    assert ">in</tspan>" in svg and "P_{in}" not in svg


def test_a_label_on_a_turned_part_keeps_its_script():
    scene = Scene(title="x", width=80, height=40, platform="free_space")
    scene.add(Lens(center=(0, 0), angle=90, label="f_1"))
    assert "<tspan" in scene.render_svg().as_svg()


def test_the_1d_view_draws_the_script():
    scene = scene_with("f_p")
    scene.add(Lens(center=(20, 0), label="L"))
    svg = render_notebook_1d(scene)
    assert "<tspan" in svg and "f_p" not in svg


def test_tikz_writes_the_script():
    tex = scene_with("f_p").render_tikz()
    assert r"f\textsubscript{p}" in tex


def test_a_saved_scene_keeps_the_markup_as_written():
    label = next(n for n in scene_from_spec(scene_to_spec(scene_with("f_p"))).walk() if isinstance(n, Laser)).label
    assert label == "f_p"


def test_the_gate_measures_the_letters_that_print():
    long = "x_{aaaaaaaaaaaaaaaa}"
    assert plain(long) == "x" + "a" * 16
    from optodraw.check import _label_box

    laser = scene_with(long).root.children[0]
    x0, _, x1, _ = _label_box(laser, 8.0)
    assert x1 - x0 == pytest.approx(len(plain(long)) * 3.0 * 0.62)


def test_the_gate_does_not_read_markup_as_a_long_label():
    assert not [f for f in check_figure(scene_with("f_{p}"), view="2d") if "words" in f]


def ink(body):
    """The grey pixels of an SVG body that is 100 units wide, one pixel to a tenth of a unit."""

    numpy = pytest.importorskip("numpy")
    cairosvg = pytest.importorskip("cairosvg")
    image = pytest.importorskip("PIL.Image")
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="20mm" viewBox="0 0 100 20">{body}</svg>'
    drawn = cairosvg.svg2png(bytestring=svg.encode(), output_width=1000, background_color="white")
    return numpy.asarray(image.open(io.BytesIO(drawn)).convert("L"))


@pytest.mark.parametrize("anchor", ["start", "middle", "end"])
def test_the_runs_of_a_label_follow_each_other_in_the_png(anchor):
    numpy = pytest.importorskip("numpy")

    def span(body):
        columns = numpy.where((ink(body) < 200).any(axis=0))[0]
        return columns.min(), columns.max()

    x = {"start": 5.0, "middle": 50.0, "end": 95.0}[anchor]
    marked = span(svg_text("Pumpkin_{inner} and more", 6.0, x, 10.0, anchor))
    as_plain = span(f'<text x="{x}" y="10" font-size="6" text-anchor="{anchor}">Pumpkin inner and more</text>')
    assert marked == pytest.approx(as_plain, abs=70)                    # the script is narrower: 0.7 units at most


def test_an_italic_run_leans_in_the_png():
    assert (ink(svg_text("*kfp*", 6.0, 5.0, 10.0)) != ink(svg_text("kfp", 6.0, 5.0, 10.0))).any()


def test_the_gate_sees_a_script_as_part_of_its_label():
    from optodraw.core.markup import text_width

    assert text_width("f_p", 10.0) == pytest.approx(10.0 * (0.278 + 0.72 * 0.556))
