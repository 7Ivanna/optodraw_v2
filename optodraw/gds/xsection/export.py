"""Export cross-section bundles (composite SVG, per-layer SVG, manifest)."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from optodraw.gds.layout import GDSLayout, load_gds_layout
from optodraw.gds.xsection.engine import OutputStack, XSectionEngine
from optodraw.gds.xsection.fast_path import plot_flat_cross_section_preview
from optodraw.gds.xsection.masks import LayoutCut
from optodraw.gds.xsection.renderer_raster import rasterize_svg_to_png
from optodraw.gds.xsection.renderer_svg import render_layer_svgs, render_output_stack_to_svg
from optodraw.gds.xsection.schema import ProcessDefinition, load_process_definition


@dataclass
class XSectionBundle:
    composite_path: Path
    layer_paths: dict[str, Path] = field(default_factory=dict)
    manifest_path: Path | None = None
    png_paths: dict[str, Path] = field(default_factory=dict)
    output_stack: OutputStack | None = None
    mode: str = "expert"


def export_xsection_bundle(
    process: ProcessDefinition | XSectionEngine | str | Path,
    cut: LayoutCut,
    output_dir: str | Path,
    *,
    mode: Literal["auto", "expert", "fast"] = "auto",
    rasterize: bool = False,
    layout: GDSLayout | None = None,
    section: dict[str, Any] | None = None,
) -> XSectionBundle:
    if mode not in {"auto", "expert", "fast"}:
        raise ValueError(f"Unknown cross-section export mode {mode!r}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = _coerce_engine(process)
    selected_mode = mode
    if mode == "auto":
        selected_mode = "expert"

    if selected_mode == "fast":
        if layout is None or section is None:
            raise ValueError("fast mode requires layout and section arguments")
        preview_path = output_dir / "flat_preview.png"
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ImportError("matplotlib is required for fast-path preview export") from exc
        preview = plot_flat_cross_section_preview(layout, section)
        figure = getattr(preview, "figure", None)
        if figure is None:
            figure = preview if hasattr(preview, "savefig") else plt.gcf()
        figure.savefig(preview_path, dpi=150, bbox_inches="tight")
        plt.close(figure)
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "process": engine.process.name,
                    "cut_label": cut.label,
                    "mode": "fast",
                    "composite": preview_path.name,
                    "layers": {},
                    "png": {"composite": preview_path.name},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return XSectionBundle(
            composite_path=preview_path,
            manifest_path=manifest_path,
            png_paths={"composite": preview_path},
            mode="fast",
        )

    stack = engine.run(cut)
    composite_path = render_output_stack_to_svg(
        stack,
        engine.process,
        output_dir / "composite.svg",
    )
    layer_paths = {}
    if engine.process.render.separate_layers:
        layer_paths = render_layer_svgs(stack, engine.process, output_dir)

    png_paths: dict[str, Path] = {}
    if rasterize:
        png_paths["composite"] = rasterize_svg_to_png(
            composite_path,
            output_dir / "composite.png",
            dpi=engine.process.render.dpi,
        )
        for name, svg_path in layer_paths.items():
            png_paths[name] = rasterize_svg_to_png(
                svg_path,
                svg_path.with_suffix(".png"),
                dpi=engine.process.render.dpi,
            )

    manifest = {
        "process": engine.process.name,
        "cut_label": cut.label,
        "mode": selected_mode,
        "composite": composite_path.name,
        "layers": {name: path.name for name, path in layer_paths.items()},
        "png": {name: path.name for name, path in png_paths.items()},
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return XSectionBundle(
        composite_path=composite_path,
        layer_paths=layer_paths,
        manifest_path=manifest_path,
        png_paths=png_paths,
        output_stack=stack,
        mode=selected_mode,
    )


def _coerce_engine(process: ProcessDefinition | XSectionEngine | str | Path) -> XSectionEngine:
    if isinstance(process, XSectionEngine):
        return process
    if isinstance(process, ProcessDefinition):
        return XSectionEngine(process)
    return XSectionEngine(load_process_definition(process))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export expert cross-section figures from process YAML.")
    parser.add_argument("--process", required=True, help="Path to process YAML/JSON")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--gds", help="Optional GDS layout path")
    parser.add_argument("--x", type=float, default=0.0, help="Section x coordinate (um)")
    parser.add_argument("--window", type=float, default=4.0, help="Section window (um)")
    parser.add_argument("--label", default="A-A'", help="Section label")
    parser.add_argument("--mode", choices=["auto", "expert", "fast"], default="auto")
    parser.add_argument("--rasterize", action="store_true", help="Also emit PNG via cairosvg")
    args = parser.parse_args(argv)

    process = load_process_definition(args.process)
    engine = XSectionEngine(process)

    if args.gds:
        layout = load_gds_layout(args.gds)
        cut = LayoutCut.from_gds(
            layout,
            {"x": args.x, "window": args.window, "label": args.label},
            process=process,
        )
        bundle = export_xsection_bundle(
            engine,
            cut,
            args.out,
            mode=args.mode,
            rasterize=args.rasterize,
            layout=layout,
            section={"x": args.x, "window": args.window, "label": args.label},
        )
    else:
        from optodraw.gds.xsection.strip_layout import CrossSectionStripLayout

        cut = (
            CrossSectionStripLayout()
            .strip("RIB", width_um=0.5, center_y_um=0.0)
            .section(x=args.x, window=args.window, label=args.label)
            .to_layout_cut()
        )
        bundle = export_xsection_bundle(engine, cut, args.out, mode=args.mode, rasterize=args.rasterize)

    print(bundle.composite_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
