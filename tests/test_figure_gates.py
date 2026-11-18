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


def test_over_allows_the_overlap(tmp_path):
    page = _page(tmp_path)
    a = page.add(Inset(_file(tmp_path), center=(40, 30), width=40, label="a"))
    page.add(Inset(_file(tmp_path), center=(55, 30), width=20, label="b", over=a))
    assert not any("overlap" in f for f in check_figure(page, view="2d"))


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


