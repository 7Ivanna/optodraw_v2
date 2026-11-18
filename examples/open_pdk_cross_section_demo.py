"""Open PDK cross-section demo (user-local stack paths only).

This script never embeds proprietary PDK names or paths in the repository.
Point it at **your** installed open-process stack YAML using either:

- environment variable ``OPTODRAW_OPEN_PDK_STACK`` (process YAML path), or
- CLI flag ``--process /path/to/process.yaml``

Optional GDS cut:

- ``OPTODRAW_OPEN_PDK_GDS`` or ``--gds /path/to/layout.gds``

Supported open stacks (install locally, paths vary by machine):

- IHP open SG13-style stacks (user-provided YAML)
- SiEPIC EBeam / UBC PDK exports (user-provided YAML)

The bundled ``generic_siph_minimal.yaml`` fixture is used when no stack path is set.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERIC_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "xsection" / "generic_siph_minimal.yaml"
DEFAULT_OUT = REPO_ROOT / "examples" / "output" / "open_pdk_xsection"


def resolve_process_path(cli_path: Path | None) -> Path:
    env_path = os.environ.get("OPTODRAW_OPEN_PDK_STACK", "").strip()
    if cli_path is not None:
        return cli_path.expanduser().resolve()
    if env_path:
        return Path(env_path).expanduser().resolve()
    if GENERIC_FIXTURE.exists():
        print(f"No user stack set — using generic fixture: {GENERIC_FIXTURE}")
        return GENERIC_FIXTURE
    raise FileNotFoundError(
        "Set OPTODRAW_OPEN_PDK_STACK or pass --process to a local open PDK process YAML"
    )


def resolve_gds_path(cli_path: Path | None) -> Path | None:
    env_path = os.environ.get("OPTODRAW_OPEN_PDK_GDS", "").strip()
    if cli_path is not None:
        return cli_path.expanduser().resolve()
    if env_path:
        return Path(env_path).expanduser().resolve()
    return None


def export_cross_section(
    *,
    process_path: Path,
    output_dir: Path,
    gds_path: Path | None = None,
    x_um: float = 0.0,
    window_um: float = 4.0,
    label: str = "A-A'",
    rasterize: bool = False,
) -> Path:
    from optodraw.gds.xsection import CrossSectionStripLayout, XSectionEngine, export_xsection_bundle
    from optodraw.gds.xsection.masks import LayoutCut

    engine = XSectionEngine.from_yaml(process_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    if gds_path is not None:
        from optodraw.gds.layout import load_gds_layout

        layout = load_gds_layout(gds_path)
        cut = LayoutCut.from_gds(
            layout,
            {"x": x_um, "window": window_um, "label": label},
            process=engine.process,
        )
        bundle = export_xsection_bundle(
            engine,
            cut,
            output_dir,
            rasterize=rasterize,
            layout=layout,
            section={"x": x_um, "window": window_um, "label": label},
        )
    else:
        cut = (
            CrossSectionStripLayout()
            .strip("RIB", width_um=0.5, center_y_um=0.0)
            .strip("SLAB", width_um=2.0, center_y_um=0.0)
            .section(x=x_um, window=window_um, label=label)
            .to_layout_cut()
        )
        bundle = export_xsection_bundle(engine, cut, output_dir, rasterize=rasterize)

    return bundle.composite_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process", type=Path, help="Local open PDK process YAML (or set OPTODRAW_OPEN_PDK_STACK)")
    parser.add_argument("--gds", type=Path, help="Optional local GDS layout (or set OPTODRAW_OPEN_PDK_GDS)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    parser.add_argument("--x", type=float, default=0.0, help="Section x coordinate (µm)")
    parser.add_argument("--window", type=float, default=4.0, help="Section window (µm)")
    parser.add_argument("--label", default="A-A'", help="Section label")
    parser.add_argument("--rasterize", action="store_true", help="Also emit PNG via cairosvg")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    process_path = resolve_process_path(args.process)
    gds_path = resolve_gds_path(args.gds)
    composite = export_cross_section(
        process_path=process_path,
        output_dir=args.out.expanduser().resolve(),
        gds_path=gds_path,
        x_um=args.x,
        window_um=args.window,
        label=args.label,
        rasterize=args.rasterize,
    )
    print(composite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
