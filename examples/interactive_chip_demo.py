"""Interactive chip viewer demo — sidebar, highlight, and scene JSON export.

Builds a routed ring-filter chip with ``build_ring_filter()`` and writes an
authoring-oriented Three.js HTML page under ``examples/output/interactive/``.

Usage::

    python examples/interactive_chip_demo.py
    python examples/interactive_chip_demo.py --output /tmp/ring_interactive.html
"""

from __future__ import annotations

import argparse
from pathlib import Path

from optodraw.layout.chip_builder import build_ring_filter


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "examples" / "output" / "interactive" / "ring_filter_interactive.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output HTML path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--show-dimensions",
        action="store_true",
        help="Start with physical dimension overlays visible",
    )
    args = parser.parse_args()

    built = build_ring_filter(title="Interactive Ring Filter", spacing_um=32.0)
    scene = built["scene"]
    scene.width = 300
    scene.height = 140

    built["grating_coupler"]._id = "gc"
    built["ring"]._id = "ring"
    built["photodetector"]._id = "pd"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    scene.render_interactive_html(
        args.output.as_posix(),
        show_grid=False,
        camera_distance=175,
        camera_preset="isometric",
        dimension_markers_default=args.show_dimensions,
    )
    print(f"Wrote interactive viewer to {args.output.resolve()}")


if __name__ == "__main__":
    main()
