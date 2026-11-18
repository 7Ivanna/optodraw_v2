"""check_export reads the finished SVG and measures it at the size it prints."""

import base64
import io

import pytest

import optodraw
from optodraw import Beam, Laser, Lens, Photodiode, Scene, check_export

MM_PER_PT = 0.3528


def page(tmp_path, body, width=120, height=80, view=None, unit="mm"):
    """An SVG file ``width`` by ``height`` in ``unit``, one user unit to the millimetre unless ``view`` says."""

    box = view or f"0 0 {width} {height}"
    path = tmp_path / "fig.svg"
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                    f'width="{width}{unit}" height="{height}{unit}" viewBox="{box}">{body}</svg>', encoding="utf-8")
    return path


def text(words, x, y, pt=7.0, extra=""):
    return f'<text x="{x}" y="{y}" font-size="{pt * MM_PER_PT:.4f}" font-family="Helvetica" {extra}>{words}</text>'


def one_fault(findings, word):
    hits = [f for f in findings if word in f]
    assert len(hits) == 1, findings
    return hits[0]


def test_a_file_with_no_size_on_paper_is_refused(tmp_path):
    path = page(tmp_path, text("Laser", 10, 20), unit="")
    with pytest.raises(ValueError, match="no size on paper"):
        check_export(path)


def test_a_rotated_group_keeps_the_size(tmp_path):
    body = f'<g transform="translate(30 30) rotate(90)">{text("Laser", 0, 0, pt=4.0)}</g>'
    assert "4.0 pt" in one_fault(check_export(page(tmp_path, body)), "Laser")


def test_a_small_subscript_is_named_with_its_own_size(tmp_path):
    body = (f'<text x="10" y="20" font-size="{5 * MM_PER_PT:.4f}" font-family="Helvetica">f'
            f'<tspan font-size="{3 * MM_PER_PT:.4f}">p</tspan></text>') + text("Lens", 60, 20) + text("Laser", 60, 40)
    assert "3.0 pt" in one_fault(check_export(page(tmp_path, body)), "subscript")


def test_text_above_8_pt_is_named(tmp_path):
    assert "Laser" in one_fault(check_export(page(tmp_path, text("Laser", 10, 20, pt=10.0) + text("Lens", 60, 40))),
                                "above 8 pt")


def test_a_width_that_is_no_column_is_named(tmp_path):
    found = one_fault(check_export(page(tmp_path, text("Laser", 10, 20), width=100)), "column")
    assert "100 mm" in found and "89, 120, 136, 183" in found


def test_a_figure_taller_than_the_page_is_named(tmp_path):
    assert "260 mm" in one_fault(check_export(page(tmp_path, text("Laser", 10, 20), height=260)), "247 mm")


def test_two_font_families_are_named(tmp_path):
    other = '<text x="60" y="20" font-size="2.47" font-family="Courier">Lens</text>'
    found = one_fault(check_export(page(tmp_path, text("Laser", 10, 20) + other)), "font famil")
    assert "Helvetica" in found and "Courier" in found


def test_overlapping_text_names_both(tmp_path):
    found = one_fault(check_export(page(tmp_path, text("Laser source", 10, 20) + text("Lens array", 14, 20))), "overlap")
    assert "Laser source" in found and "Lens array" in found


def test_text_off_the_page_is_named(tmp_path):
    assert "Laser" in one_fault(check_export(page(tmp_path, text("Laser", 118, 20))), "off the page")


def test_too_many_words_name_the_density(tmp_path):
    lines = "".join(text("two words", 5 + 30 * (i % 3), 5 + 5 * (i // 3)) for i in range(30))
    found = one_fault(check_export(page(tmp_path, lines, width=89, height=60)), "words")
    assert "60 words" in found and "1.12" in found


def test_panel_letters_out_of_order_are_named(tmp_path):
    bold = 'font-weight="bold"'
    body = text("a", 1, 4, extra=bold) + text("c", 60, 4, extra=bold) + text("Laser", 10, 20)
    assert "a, c" in one_fault(check_export(page(tmp_path, body)), "panel letters")


def test_text_on_a_panel_letter_is_named(tmp_path):
    # the ln_ring page before the fix: the section's cut letter A over the panel letter b
    letter = '<text x="37.649" y="2.822" font-size="2.822" font-weight="bold">b</text>'
    cut = text("A", 39.648, 2.917, extra='text-anchor="middle" dominant-baseline="central"')
    found = one_fault(check_export(page(tmp_path, letter + cut)), "on a panel letter")    # mutant: the gate removed
    assert '"A" on "b"' in found
    assert check_export(page(tmp_path, letter + text("A", 45, 2.917, extra='dominant-baseline="central"'))) == []


def png(pixels):
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (pixels, pixels), "white").save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode()


def test_a_coarse_image_names_its_resolution(tmp_path):
    pytest.importorskip("PIL")
    body = text("Laser", 10, 20) + (f'<image x="0" y="30" width="25.4" height="25.4" '
                                    f'xlink:href="data:image/png;base64,{png(150)}"/>')
    assert "150 ppi" in one_fault(check_export(page(tmp_path, body)), "ppi")


def band(fill="#2f6fd0", y=16, height=6):
    return f'<rect x="0" y="{y}" width="120" height="{height}" fill="{fill}"/>'


def bench():
    scene = Scene(title="Bench", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser", label_side="top"))
    lens = scene.add(Lens(center=(0, 0), focal_length=40, label="Lens", label_side="top"))
    pd = scene.add(Photodiode(center=(40, 0), angle=180, label="PD", label_side="top"))
    beam = scene.add(Beam((laser, "out"), (lens, "in"), (lens, "out"), (pd, "in"), wavelength=635))
    return scene, beam


def test_the_export_gate_is_public():
    assert "check_export" in optodraw.__all__
