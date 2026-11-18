"""Make the landing page's two rows: each a published figure from the site's cells, in 3D, 2D and 1D.

Free space: Advanced LIGO (Abbott et al. 2016, Fig. 3). On chip: the balanced homodyne receiver of
Yang et al. (2025), Fig. 3. The scenes come from ``docs/examples``, so the hero shows what the pages show.
Run it explicitly (the two studio renders take about a minute each), not on every site build:

    python docs/scripts/render_hero.py                   # everything
    python docs/scripts/render_hero.py --diagrams-only   # the 1D and 2D drawings and the 3D pages
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from make_media import page_scene  # noqa: E402  (the same cell runner as the README images)

from optodraw.notebook_1d import render_notebook_1d  # noqa: E402

OUT = ROOT / "docs" / "public" / "hero"
ROWS = {"ligo": "get-started/01-ligo", "homodyne": "electronics/01-homodyne"}


def main() -> None:
    warnings.simplefilter("ignore")
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, cell in ROWS.items():
        scene = page_scene(cell)
        scene.render_svg(str(OUT / f"{stem}.svg"))
        (OUT / f"{stem}-1d.svg").write_text(render_notebook_1d(scene), encoding="utf-8")
        scene.render_threejs(str(OUT / f"{stem}.html"), show_labels=False)
        if "--diagrams-only" not in sys.argv:
            scene.render_3d_image(str(OUT / f"{stem}.png"), background="light", width=1600, height=840, scale=1,   # the tile's shape
                                  samples=4, quality="final", labels=False)
        print(stem, "done")


if __name__ == "__main__":
    main()
