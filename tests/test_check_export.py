"""check_export reads the finished SVG and measures it at the size it prints."""

import base64
import io
import sys

import pytest

import optodraw
from optodraw import Beam, Laser, Lens, Note, Panel, Photodiode, Scene, check_export, export_panels
from optodraw.publication import export_figure

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


def test_a_clean_figure_has_no_findings(tmp_path):
    assert check_export(page(tmp_path, text("Laser", 10, 20) + text("Lens", 60, 20))) == []


def test_a_file_with_no_size_on_paper_is_refused(tmp_path):
    path = page(tmp_path, text("Laser", 10, 20), unit="")
    with pytest.raises(ValueError, match="no size on paper"):
        check_export(path)


def test_text_below_5_pt_names_the_text_and_its_size(tmp_path):
    found = one_fault(check_export(page(tmp_path, text("Laser", 10, 20, pt=4.0) + text("Lens", 60, 20))), "Laser")
    assert "4.0 pt" in found


def test_the_size_follows_the_view_box(tmp_path):
    body = '<text x="10" y="20" font-size="3" font-family="Helvetica">Laser</text>'
    found = one_fault(check_export(page(tmp_path, body, view="0 0 240 160")), "Laser")     # 3 units = 1.5 mm
    assert "4.3 pt" in found


def test_the_size_follows_a_scale_in_a_group(tmp_path):
    body = f'<g transform="translate(10 10) scale(0.5)">{text("Laser", 0, 0)}</g>'
    assert "3.5 pt" in one_fault(check_export(page(tmp_path, body)), "Laser")


def test_the_size_follows_a_nested_panel(tmp_path):
    inner = '<text x="10" y="20" font-size="4" font-family="Helvetica">Laser</text>'
    body = f'<svg x="0" y="0" width="60" height="40" viewBox="0 0 120 80">{inner}</svg>'    # 4 units = 2 mm
    assert "5.7 pt" not in " ".join(check_export(page(tmp_path, body)))
    small = '<text x="10" y="20" font-size="3" font-family="Helvetica">Laser</text>'
    body = f'<svg x="0" y="0" width="60" height="40" viewBox="0 0 120 80">{small}</svg>'
    assert "4.3 pt" in one_fault(check_export(page(tmp_path, body)), "Laser")


def test_a_rotated_group_keeps_the_size(tmp_path):
    body = f'<g transform="translate(30 30) rotate(90)">{text("Laser", 0, 0, pt=4.0)}</g>'
    assert "4.0 pt" in one_fault(check_export(page(tmp_path, body)), "Laser")


def test_a_size_in_a_style_attribute_is_read(tmp_path):
    body = f'<text x="10" y="20" style="font-size:{4 * MM_PER_PT:.4f}px;font-family:Helvetica">Laser</text>'
    assert "4.0 pt" in one_fault(check_export(page(tmp_path, body)), "Laser")


def test_a_font_size_on_a_group_reaches_its_text(tmp_path):
    body = f'<g font-size="{4 * MM_PER_PT:.4f}" font-family="Helvetica"><text x="10" y="20">Laser</text></g>'
    assert "4.0 pt" in one_fault(check_export(page(tmp_path, body)), "Laser")


def test_a_small_subscript_is_named_with_its_own_size(tmp_path):
    body = (f'<text x="10" y="20" font-size="{5 * MM_PER_PT:.4f}" font-family="Helvetica">f'
            f'<tspan font-size="{3 * MM_PER_PT:.4f}">p</tspan></text>') + text("Lens", 60, 20) + text("Laser", 60, 40)
    assert "3.0 pt" in one_fault(check_export(page(tmp_path, body)), "subscript")


def test_a_subscript_at_0_72_of_the_text_passes(tmp_path):
    body = (f'<text x="10" y="20" font-size="{7 * MM_PER_PT:.4f}" font-family="Helvetica">f'
            f'<tspan font-size="{5 * MM_PER_PT:.4f}">p</tspan></text>')
    assert check_export(page(tmp_path, body)) == []


def test_text_above_8_pt_is_named(tmp_path):
    assert "Laser" in one_fault(check_export(page(tmp_path, text("Laser", 10, 20, pt=10.0) + text("Lens", 60, 40))),
                                "above 8 pt")


def test_a_panel_letter_may_be_larger_than_the_labels(tmp_path):
    body = text("a", 1, 4, pt=10.0, extra='font-weight="bold"') + text("Laser", 10, 20)
    assert check_export(page(tmp_path, body)) == []


def test_labels_under_the_ceiling_at_full_width_name_narrower_columns(tmp_path):
    found = one_fault(check_export(page(tmp_path, text("Laser", 10, 20) + text("Lens", 60, 20), width=183)),
                      "of the width")
    assert "1.35%" in found and "8.0 pt floor" in found and "120 or 136 mm" in found     # the 8 pt ceiling wins


def test_the_same_labels_pass_at_136_mm(tmp_path):
    assert check_export(page(tmp_path, text("Laser", 10, 20) + text("Lens", 60, 20), width=136)) == []


def test_a_width_that_is_no_column_is_named(tmp_path):
    found = one_fault(check_export(page(tmp_path, text("Laser", 10, 20), width=100)), "column")
    assert "100 mm" in found and "89, 120, 136, 183" in found


def test_a_figure_taller_than_the_page_is_named(tmp_path):
    assert "260 mm" in one_fault(check_export(page(tmp_path, text("Laser", 10, 20), height=260)), "247 mm")


def test_two_font_families_are_named(tmp_path):
    other = '<text x="60" y="20" font-size="2.47" font-family="Courier">Lens</text>'
    found = one_fault(check_export(page(tmp_path, text("Laser", 10, 20) + other)), "font famil")
    assert "Helvetica" in found and "Courier" in found


def test_a_family_list_counts_as_its_first_name(tmp_path):
    other = '<text x="60" y="20" font-size="2.47" font-family="Helvetica, Arial, sans-serif">Lens</text>'
    assert check_export(page(tmp_path, text("Laser", 10, 20) + other)) == []


def test_overlapping_text_names_both(tmp_path):
    found = one_fault(check_export(page(tmp_path, text("Laser source", 10, 20) + text("Lens array", 14, 20))), "overlap")
    assert "Laser source" in found and "Lens array" in found


def test_text_side_by_side_does_not_overlap(tmp_path):
    assert check_export(page(tmp_path, text("Laser", 10, 20) + text("Lens", 30, 20))) == []


def test_a_box_is_as_wide_as_its_letters(tmp_path):
    narrow = text("illillillillill", 10, 20)                # 15 narrow letters: about 8 mm at 7 pt
    assert check_export(page(tmp_path, narrow + text("Lens", 20, 20))) == []
    wide = text("WWWWWWWWWWWWWWW", 10, 20)                  # 15 wide ones: about 35 mm
    assert "overlap" in " ".join(check_export(page(tmp_path, wide + text("Lens", 20, 20))))


def test_an_end_anchor_moves_the_box_to_the_left(tmp_path):
    left = text("Laser source", 30, 20, extra='text-anchor="end"')
    right = text("Lens", 40, 20)
    assert check_export(page(tmp_path, left + right)) == []
    assert "overlap" in " ".join(check_export(page(tmp_path, left + text("Lens", 25, 20))))


def test_text_off_the_page_is_named(tmp_path):
    assert "Laser" in one_fault(check_export(page(tmp_path, text("Laser", 118, 20))), "off the page")


def test_rotated_text_is_left_out_of_the_overlap_check(tmp_path):
    turned = f'<g transform="translate(12 20) rotate(90)">{text("Laser source", 0, 0)}</g>'
    assert check_export(page(tmp_path, text("Laser source", 10, 20) + turned)) == []


def test_too_many_words_name_the_density(tmp_path):
    lines = "".join(text("two words", 5 + 30 * (i % 3), 5 + 5 * (i // 3)) for i in range(30))
    found = one_fault(check_export(page(tmp_path, lines, width=89, height=60)), "words")
    assert "60 words" in found and "1.12" in found


def test_a_hairline_is_named_with_its_width(tmp_path):
    body = text("Laser", 10, 20) + '<path d="M0,40 L100,40" stroke="#000" stroke-width="0.05" fill="none"/>'
    assert "0.14 pt" in one_fault(check_export(page(tmp_path, body)), "thinner than 0.25 pt")


def test_a_hairline_inside_a_symbol_is_the_symbols_detail(tmp_path):
    art = '<g data-art="lens"><g stroke="#000" stroke-width="0.05"><path d="M0,40 L100,40" fill="none"/></g></g>'
    assert check_export(page(tmp_path, text("Laser", 10, 20) + art)) == []


def test_a_shape_with_no_stroke_has_no_stroke_width(tmp_path):
    body = text("Laser", 10, 20) + '<rect x="0" y="40" width="9" height="9" fill="#000" stroke-width="0.05"/>'
    assert check_export(page(tmp_path, body)) == []


def test_a_stroke_on_a_group_reaches_its_paths(tmp_path):
    body = text("Laser", 10, 20) + '<g stroke="#000" stroke-width="0.05"><path d="M0,40 L100,40" fill="none"/></g>'
    one_fault(check_export(page(tmp_path, body)), "thinner than 0.25 pt")


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


def test_a_fine_image_passes(tmp_path):
    pytest.importorskip("PIL")
    body = text("Laser", 10, 20) + (f'<image x="0" y="30" width="25.4" height="25.4" '
                                    f'href="data:image/png;base64,{png(300)}"/>')
    assert check_export(page(tmp_path, body)) == []


def band(fill="#2f6fd0", y=16, height=6):
    return f'<rect x="0" y="{y}" width="120" height="{height}" fill="{fill}"/>'


def test_text_across_the_edge_of_a_band_is_named(tmp_path):
    pytest.importorskip("cairosvg")
    assert "Laser" in one_fault(check_export(page(tmp_path, band(y=19.2) + text("Laser", 10, 20))), "over the drawing")


def test_text_inside_a_flat_band_can_be_read(tmp_path):
    pytest.importorskip("cairosvg")
    assert check_export(page(tmp_path, band(y=10, height=20) + text("Laser", 10, 20))) == []


def test_the_check_says_when_it_cannot_look_at_the_drawing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    found = check_export(page(tmp_path, band(y=19.2) + text("Laser", 10, 20)))
    assert "optodraw[gif]" in one_fault(found, "not checked")


def bench():
    scene = Scene(title="Bench", width=120, height=40, platform="free_space")
    laser = scene.add(Laser(center=(-40, 0), label="Laser", label_side="top"))
    lens = scene.add(Lens(center=(0, 0), focal_length=40, label="Lens", label_side="top"))
    pd = scene.add(Photodiode(center=(40, 0), angle=180, label="PD", label_side="top"))
    beam = scene.add(Beam((laser, "out"), (lens, "in"), (lens, "out"), (pd, "in"), wavelength=635))
    return scene, beam


def test_a_real_export_reads_at_the_size_it_was_asked_for(tmp_path):
    scene, _ = bench()
    path = export_figure(scene, tmp_path / "fig", width_mm=120, font_size_pt=7.0, formats=("svg",))["svg"]
    assert [f for f in check_export(path) if "pt" in f and "thinner" not in f] == []
    small = export_figure(scene, tmp_path / "small", width_mm=120, font_size_pt=4.0, formats=("svg",))["svg"]
    assert "4.0 pt" in " ".join(check_export(small))


def test_a_real_note_on_the_edge_of_a_beam_is_found(tmp_path):
    pytest.importorskip("cairosvg")
    scene, beam = bench()
    clear = export_figure(scene, tmp_path / "clear", width_mm=120, formats=("svg",))["svg"]
    assert not [f for f in check_export(clear) if "over the drawing" in f]
    scene.add(Note("500 nm", center=(-20, beam.display_width / 2.0)))
    placed = export_figure(scene, tmp_path / "on", width_mm=120, formats=("svg",))["svg"]
    assert "500 nm" in one_fault(check_export(placed), "over the drawing")


def test_a_real_panel_figure_is_read_through_its_panels(tmp_path):
    scene, _ = bench()
    path = export_panels(tmp_path / "fig", [[Panel(scene), Panel(bench()[0])]], width_mm=183, font_size_pt=4.0,
                         formats=("svg",))["svg"]
    assert "4.0 pt" in " ".join(check_export(path))
    assert not [f for f in check_export(path) if "panel letters" in f]


def test_the_export_gate_is_public():
    assert "check_export" in optodraw.__all__
