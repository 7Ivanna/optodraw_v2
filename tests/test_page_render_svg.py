"""A page shown in a notebook (ScenePreview) or by the docs (cell_display.show) draws at its own size, as it prints.

Both called render_svg, which is the page's editor canvas: framed at the scene's height, 0 for a page as tall as
its content. The docs page of insets showed an empty drawing 0 units tall."""

import sys
from pathlib import Path

from optodraw import Lens, Page, Scene
from optodraw.viewer import ScenePreview

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs" / "scripts"))


def _page():
    bench = Scene(title="bench", platform="free_space")
    bench.add(Lens(center=(0, 0), label="L"))
    bench.fit_frame(margin=4)
    page = Page(width_mm=89)
    page.row([bench])
    return page


def test_a_notebook_preview_shows_a_page_at_its_own_size():
    page = _page()
    assert ScenePreview(page)._svg_text() == page.svg()
