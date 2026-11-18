"""Migrate legacy drawsvg cross-section sketch to the xsection engine.

Uses the bundled ``generic_siph_minimal.yaml`` process fixture and a synthetic
``CrossSectionStripLayout`` (no GDS required).  Outputs land in
``examples/output/xsection/`` by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "xsection" / "generic_siph_minimal.yaml"
DEFAULT_OUT = REPO_ROOT / "examples" / "output" / "xsection"


def export_strip_cross_section(output_dir: Path) -> Path:
    from optodraw.gds.xsection import CrossSectionStripLayout, XSectionEngine, export_xsection_bundle

    if not FIXTURE.exists():
        raise FileNotFoundError(f"Process fixture not found: {FIXTURE}")

    engine = XSectionEngine.from_yaml(FIXTURE)
    cut = (
        CrossSectionStripLayout()
        .strip("RIB", width_um=0.5, center_y_um=0.0)
        .strip("SLAB", width_um=2.0, center_y_um=0.0)
        .span(y_min=-2.0, y_max=2.0)
        .section(x=0.0, window=4.0, label="WG strip")
        .to_layout_cut()
    )
    bundle = export_xsection_bundle(engine, cut, output_dir)
    return bundle.composite_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Output directory for composite SVG and layer bundle",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    composite = export_strip_cross_section(args.out.expanduser().resolve())
    print(composite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
