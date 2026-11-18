"""check_export measures labels per panel and names every raster by its kind."""

import base64
import io

from optodraw import check_export, figure_rasters

MM_PER_PT = 0.3528


def page(tmp_path, body, width=183, height=80):
    path = tmp_path / "fig.svg"
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                    f'width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">{body}</svg>',
                    encoding="utf-8")
    return path


def text(words, x, y, pt=7.0):
    return f'<text x="{x}" y="{y}" font-size="{pt * MM_PER_PT:.4f}" font-family="Helvetica">{words}</text>'


def inset(x, mm, body, kind="drawn"):
    return (f'<g data-inset="{kind}" data-panel="{mm:g}" transform="translate({x} 5)">'
            f'<svg width="{mm}" height="60" viewBox="0 0 {mm} 60">{body}</svg></g>')


def png(pixels):
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (pixels, pixels), "white").save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode()


def picture(pixels, mm):
    return f'<image x="0" y="0" width="{mm}" height="{mm}" xlink:href="data:image/png;base64,{png(pixels)}"/>'


def floors(findings):
    return [f for f in findings if "median label" in f]


def test_label_floor_is_per_panel(tmp_path):
    body = inset(1, 90, text("Laser", 5, 10, 5.5) + text("Lens", 40, 10, 5.5)) + \
        inset(92, 90, text("Mirror", 5, 10, 5.5) + text("Prism", 40, 10, 5.5))
    assert floors(check_export(page(tmp_path, body))) == []       # floor 0.0165 * 255 pt = 4.2 pt


def test_ceiling_wins_at_full_width(tmp_path):
    body = inset(0, 183, text("Laser", 5, 10, 8.0) + text("Lens", 60, 10, 8.0))
    assert floors(check_export(page(tmp_path, body))) == []


def test_label_below_the_floor_is_a_finding(tmp_path):
    body = inset(0, 120, text("Laser", 5, 10, 5.0) + text("Lens", 60, 10, 5.0))
    found = floors(check_export(page(tmp_path, body)))
    assert len(found) == 1 and "120 mm panel" in found[0] and "5.6 pt floor" in found[0]


def test_a_file_with_no_panels_counts_as_one(tmp_path):
    found = floors(check_export(page(tmp_path, text("Laser", 10, 20, 5.0) + text("Lens", 60, 20, 5.0), width=120)))
    assert len(found) == 1
    assert floors(check_export(page(tmp_path, text("Laser", 10, 20, 6.0) + text("Lens", 60, 20, 6.0), width=120))) == []


def test_page_text_outside_a_panel_is_not_counted(tmp_path):
    body = inset(0, 120, text("Laser", 5, 10, 6.0) + text("Lens", 60, 10, 6.0)) + \
        "".join(text(f"Note{n}", 130, 10 + 6 * n, 5.0) for n in range(5))
    assert floors(check_export(page(tmp_path, body))) == []


def test_a_low_resolution_picture_is_a_finding(tmp_path):
    body = inset(0, 30, picture(100, 30), kind="measured")
    found = [f for f in check_export(page(tmp_path, body)) if "ppi" in f]
    assert len(found) == 1 and "85 ppi" in found[0] and "measured" in found[0]


def test_a_drawn_raster_is_a_finding(tmp_path):
    body = inset(0, 25.4, picture(400, 25.4), kind="drawn")
    found = [f for f in check_export(page(tmp_path, body)) if "kind drawn" in f]
    assert len(found) == 1
    body = inset(0, 25.4, picture(400, 25.4), kind="measured")
    assert [f for f in check_export(page(tmp_path, body)) if "kind drawn" in f] == []


def test_rasters_are_listed_with_their_kind(tmp_path):
    body = inset(0, 25.4, picture(254, 25.4), kind="measured") + inset(40, 25.4, picture(508, 25.4), kind="render")
    found = figure_rasters(page(tmp_path, body))
    assert [kind for kind, _ in found] == ["measured", "render"]
    assert [round(ppi) for _, ppi in found] == [254, 508]


def test_a_thin_line_in_an_inset_is_a_finding(tmp_path):
    body = inset(0, 60, '<line x1="0" y1="5" x2="50" y2="5" stroke="black" stroke-width="0.03528"/>')
    found = [f for f in check_export(page(tmp_path, body)) if "thinner" in f]
    assert len(found) == 1 and "0.10 pt" in found[0]


# ---------------------------------------------------------------- check_figure on a page of insets

from optodraw import Callout, Inset, check_figure  # noqa: E402
from optodraw.figure.fragment import Fragment  # noqa: E402
from optodraw.figure.page import Page  # noqa: E402

FILE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
        '<rect width="40" height="20" fill="#cccccc"/></svg>')


def _file(tmp_path):
    path = tmp_path / "a.svg"
    path.write_text(FILE)
    return str(path)


def _page(tmp_path, **kw):
    return Page(width_mm=120, height_mm=60, letters=False, **kw)


def test_overlapping_insets_are_a_finding(tmp_path):
    page = _page(tmp_path)
    page.add(Inset(_file(tmp_path), center=(40, 30), width=40, label="a"))
    page.add(Inset(_file(tmp_path), center=(55, 30), width=40, label="b"))
    assert 'insets "a" and "b" overlap' in check_figure(page, view="2d")


def test_apart_insets_are_clean(tmp_path):
    page = _page(tmp_path)
    page.add(Inset(_file(tmp_path), center=(25, 30), width=40, label="a"))
    page.add(Inset(_file(tmp_path), center=(80, 30), width=40, label="b"))
    assert check_figure(page, view="2d") == []


def test_over_allows_the_overlap(tmp_path):
    page = _page(tmp_path)
    a = page.add(Inset(_file(tmp_path), center=(40, 30), width=40, label="a"))
    page.add(Inset(_file(tmp_path), center=(55, 30), width=20, label="b", over=a))
    assert not any("overlap" in f for f in check_figure(page, view="2d"))


def test_a_label_on_an_inset_passes(tmp_path):
    page = _page(tmp_path)
    inset = page.add(Inset(_file(tmp_path), center=(60, 30), width=40))
    page.add(Callout("power", center=(55, 30), target=inset.at(10, 5)))
    assert not any("sits on" in f for f in check_figure(page, view="2d"))


def test_a_covered_target_is_a_finding(tmp_path):
    class Fake:
        def fragment(self, width_mm, font_pt=7.0):
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm" viewBox="0 0 40 20">'
                   '</svg>')
            return Fragment(svg=svg, size_mm=(40.0, 20.0), place=lambda x, y: (x, y), covered=lambda x, y: x > 30)

    page = _page(tmp_path)
    inset = page.add(Inset(Fake(), center=(60, 30), width=40, label="s"))
    page.add(Callout("Ring", center=(60, 50), target=inset.at(35, 10)))
    page.add(Callout("Disk", center=(30, 50), target=inset.at(5, 10)))
    found = check_figure(page, view="2d")
    assert any('the target of "Ring" is hidden' in f for f in found)
    assert not any('"Disk"' in f and "hidden" in f for f in found)


def test_a_mark_outside_its_inset_is_a_finding(tmp_path):
    page = _page(tmp_path)
    inset = page.add(Inset(_file(tmp_path), center=(60, 30), width=40, label="sec"))
    page.add(Callout("probe", center=(60, 50), target=inset.at(60, 5)))
    found = check_figure(page, view="2d")
    assert any('"probe"' in f and '"sec"' in f for f in found)


def test_a_mark_of_a_removed_inset_is_a_finding(tmp_path):
    page = _page(tmp_path)
    inset = page.add(Inset(_file(tmp_path), center=(60, 30), width=40, label="sec"))
    page.add(Callout("probe", center=(60, 50), target=inset.at(10, 5)))
    page.root.children.remove(inset)
    found = check_figure(page, view="2d")
    assert any('"probe"' in f and "left the page" in f for f in found)
    assert page.export(tmp_path / "fig", formats=("svg",))["svg"].exists()


def test_a_zoom_of_a_removed_inset_is_a_finding(tmp_path):
    page = _page(tmp_path)
    small = page.add(Inset(_file(tmp_path), center=(30, 30), width=40, label="small"))
    big = page.add(Inset(_file(tmp_path), center=(90, 30), width=40, label="big"))
    page.zoom(small, (5, 5, 15, 10), big)
    page.root.children.remove(big)
    found = check_figure(page, view="2d")
    assert any('zoom' in f and '"big"' in f and "left the page" in f for f in found)
    assert page.export(tmp_path / "fig", formats=("svg",))["svg"].exists()


def test_a_page_with_no_height_uses_its_extent_as_the_frame(tmp_path):
    page = Page(width_mm=120, letters=False)
    page.add(Inset(_file(tmp_path), center=(60, 30), width=40))
    page.add(Callout("Si core", center=(60, 30), target=(70, 30)))
    assert not any("cut off by the frame" in f for f in check_figure(page, view="2d"))
    page.add(Callout("Gone", center=(400, 30), target=(390, 30)))
    assert any('"Gone"' in f and "cut off by the frame" in f for f in check_figure(page, view="2d"))


def test_insets_that_touch_at_an_edge_do_not_overlap(tmp_path):
    page = _page(tmp_path)
    page.add(Inset(_file(tmp_path), center=(30, 30), width=40, label="a"))
    page.add(Inset(_file(tmp_path), center=(70, 30), width=40, label="b"))      # a ends at 50, b starts at 50
    assert not any("overlap" in f for f in check_figure(page, view="2d"))


def test_a_fixed_height_page_flags_a_callout_off_the_page(tmp_path):
    page = _page(tmp_path)
    page.add(Callout("Inside", center=(60, 30), target=(70, 30)))
    page.add(Callout("Gone", center=(60, 200), target=(70, 190)))
    found = check_figure(page, view="2d")
    assert any('"Gone"' in f and "cut off by the frame" in f for f in found)
    assert not any('"Inside"' in f for f in found)


def test_a_covered_that_raises_does_not_crash(tmp_path):
    class Fake:
        def fragment(self, width_mm, font_pt=7.0):
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm" viewBox="0 0 40 20"></svg>'

            def covered(x, y):
                raise ValueError("edge")

            return Fragment(svg=svg, size_mm=(40.0, 20.0), place=lambda x, y: (x, y), covered=covered)

    page = _page(tmp_path)
    inset = page.add(Inset(Fake(), center=(60, 30), width=40, label="s"))
    page.add(Callout("Edge", center=(60, 50), target=inset.at(40, 10)))
    found = check_figure(page, view="2d")
    assert 'the source of "s" cannot tell if the target of "Edge" is hidden: point at another place' in found
    assert not any("outside" in f for f in found)


def _page_with(item, tmp_path):
    from optodraw import Inset
    from optodraw.figure.page import Page

    page = Page(width_mm=183, font_pt=7.0, letters=False)
    page.add(Inset(item, center=(91.5, 20), width=183))
    return page.export(tmp_path / "fig", formats=("svg",))["svg"]


def test_a_text_block_is_page_text_not_a_panel(tmp_path):
    from optodraw.figure.sources import Equation, Text

    for item in (Text("A full-width block of words at the page font, as a caption or a key reads."),
                 Equation("E = mc^2")):
        path = _page_with(item, tmp_path)
        svg = path.read_text(encoding="utf-8")
        assert "data-panel" not in svg and "data-inset" in svg
        assert floors(check_export(path)) == []


def test_nested_inset_text_goes_to_the_inner_panel(tmp_path):
    import xml.etree.ElementTree as ET

    from optodraw import Inset, Laser, Scene
    from optodraw.check import _read_page
    from optodraw.figure.page import Page
    from optodraw.figure.sources import SceneView

    inner = tmp_path / "t.svg"
    inner.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">'
                     '<text x="2" y="10" font-size="4">deep</text></svg>', encoding="utf-8")
    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(-30, 0), label="Laser"))
    scene.add(Inset(str(inner), center=(20, 0), width=40))
    page = Page(width_mm=183, height_mm=100, letters=False)
    page.add(Inset(SceneView(scene), center=(91.5, 50), width=150))
    path = page.export(tmp_path / "fig", formats=("svg",))["svg"]
    sheet = _read_page(ET.parse(path).getroot(), "fig.svg")
    deep, laser = (next(t for t in sheet.texts if t.words == words) for words in ("deep", "Laser"))
    assert deep.panel and laser.panel and deep.panel != laser.panel
    assert sheet.panels[deep.panel] < sheet.panels[laser.panel]          # the inner panel is the narrower one
