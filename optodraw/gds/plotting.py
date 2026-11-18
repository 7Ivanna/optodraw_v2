"""GDS plotting and layer report helpers."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any
import csv

from optodraw.gds.layout import GDSLayout, GDSLayerRecord, GDSSection
from optodraw.gds.mesh import (
    _coerce_section,
    _require_geometry_packages,
)

def plot_gds_top_view(
    layout: GDSLayout,
    sections: list[GDSSection | dict[str, Any]] | None = None,
    ax=None,
    *,
    label_layers: bool = False,
    label_fontsize: float = 8.5,
):
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon, Rectangle
    except ImportError as exc:
        raise ImportError("matplotlib is required for GDS plotting utilities") from exc

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))

    min_x, min_y, max_x, max_y = layout.bounds
    for record in layout.layer_records:
        if not record.visible:
            continue
        for polygon in record.polygons:
            ax.add_patch(
                MplPolygon(
                    polygon,
                    closed=True,
                    facecolor=record.color,
                    edgecolor="#1f2937",
                    linewidth=0.35,
                    alpha=record.opacity,
                )
            )

    if label_layers:
        for record in layout.layer_records:
            if not record.visible:
                continue
            anchor = record.label_anchor
            if anchor is None:
                continue
            ax.text(
                anchor[0],
                anchor[1],
                f"{record.name}\n{record.spec[0]}/{record.spec[1]}",
                ha="center",
                va="center",
                color="#102a43",
                fontsize=label_fontsize,
                fontweight="bold",
                bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "none", "alpha": 0.72},
                zorder=30,
            )

    for section_value in sections or []:
        section = _coerce_section(section_value)
        rect = Rectangle(
            (section.x - section.window / 2.0, min_y),
            section.window,
            max_y - min_y,
            linewidth=1.0,
            edgecolor="#102a43",
            facecolor="#102a43",
            alpha=0.08,
            linestyle="--",
        )
        ax.add_patch(rect)
        ax.text(
            section.x,
            max_y + (max_y - min_y) * 0.03,
            section.label,
            ha="center",
            va="bottom",
            color="#102a43",
            fontweight="bold",
        )

    ax.set_aspect("equal")
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    ax.set_title("Top View With Section Windows")
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return ax


def plot_gds_cross_section(
    layout: GDSLayout,
    section: GDSSection | dict[str, Any],
    *,
    ax=None,
    z_exaggeration: float = 28.0,
):
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError as exc:
        raise ImportError("matplotlib is required for GDS plotting utilities") from exc

    _, Polygon, box = _require_geometry_packages()
    from shapely.geometry import LineString

    if ax is None:
        _, ax = plt.subplots(figsize=(7, 3))

    selected = _coerce_section(section)
    _, min_y, _, max_y = layout.bounds
    if selected.mode == "section":
        slice_region = LineString([(selected.x, min_y - 1.0), (selected.x, max_y + 1.0)])
    else:
        slice_region = box(
            selected.x - selected.window / 2.0,
            min_y - 1.0,
            selected.x + selected.window / 2.0,
            max_y + 1.0,
        )

    def simple_parts(geometry):
        if geometry.is_empty:
            return
        parts = getattr(geometry, "geoms", None)
        if parts is None:
            yield geometry
        else:
            for part in parts:
                yield from simple_parts(part)

    profiles = []
    for record in layout.layer_records:
        if not record.visible:
            continue
        for polygon in record.polygons:
            shape = Polygon(polygon)
            if not shape.is_valid:
                shape = shape.buffer(0)
            if shape.is_empty:
                continue
            clipped = shape.intersection(slice_region)
            for geometry in simple_parts(clipped):
                bounds = geometry.bounds
                if len(bounds) != 4:
                    continue
                _, y0, _, y1 = bounds
                if y1 - y0 > 1e-6:
                    profiles.append(
                        {
                            "y0": float(y0),
                            "y1": float(y1),
                            "zmin": record.zmin,
                            "thickness": record.thickness,
                            "color": record.color,
                            "alpha": record.opacity,
                        }
                    )

    for profile in sorted(profiles, key=lambda item: (item["zmin"], item["y0"])):
        rect = Rectangle(
            (profile["y0"], profile["zmin"] * z_exaggeration),
            profile["y1"] - profile["y0"],
            profile["thickness"] * z_exaggeration,
            facecolor=profile["color"],
            edgecolor="#1f2937",
            linewidth=0.35,
            alpha=profile["alpha"],
        )
        ax.add_patch(rect)

    ax.axhline(0.0, color="#1f2937", linewidth=0.7, linestyle="--")
    ax.set_xlim(min_y, max_y)
    zmax = max((profile["zmin"] + profile["thickness"]) for profile in profiles) if profiles else 1.0
    ax.set_ylim(min(-0.2 * z_exaggeration, -0.05), (zmax + 0.15) * z_exaggeration)
    ax.set_title(f"Section {selected.label} at x={selected.x:.2f} um")
    ax.set_xlabel("y (um)")
    ax.set_ylabel(f"z x {z_exaggeration:.0f}")
    return ax



def _layer_report_rows(
    layer_records: list[GDSLayerRecord],
    *,
    float_precision: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in layer_records:
        anchor = record.label_anchor
        rows.append(
            {
                "layer": str(record.spec[0]),
                "datatype": str(record.spec[1]),
                "name": record.name,
                "style_source": record.style_source,
                "physical_stack_known": "yes" if record.physical_stack_known else "no",
                "matched_pdk": "yes" if record.matched_pdk else "no",
                "visible": "yes" if record.visible else "no",
                "material_preset": record.material_preset,
                "material_name": record.material_name or "",
                "zmin_um": _format_report_float(record.zmin, float_precision),
                "thickness_um": _format_report_float(record.thickness, float_precision),
                "polygon_count": str(record.polygon_count),
                "total_area_um2": _format_report_float(record.total_area_um2, float_precision),
                "label_anchor_x_um": "" if anchor is None else _format_report_float(anchor[0], float_precision),
                "label_anchor_y_um": "" if anchor is None else _format_report_float(anchor[1], float_precision),
                "description": record.description,
            }
        )
    return rows


def _format_report_float(value: float, float_precision: int) -> str:
    return f"{value:.{float_precision}f}"


def _layer_report_csv(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _layer_report_markdown(
    layout: GDSLayout,
    rows: list[dict[str, str]],
    *,
    include_summary: bool,
) -> str:
    summary = layout.summary()
    header = [f"# Layer Assignment Sheet: {layout.source_path.name}", ""]
    if include_summary:
        header.extend(
            [
                f"- Cell: {layout.cell_name}",
                f"- Source: {layout.source_path.as_posix()}",
                f"- Footprint: {summary['footprint_um'][0]:.3f} um x {summary['footprint_um'][1]:.3f} um",
                f"- Polygons: {summary['polygon_count']}",
                f"- PDK matched layers: {summary['matched_pdk_layers']}",
                f"- Fallback layers: {summary['fallback_layers']}",
                f"- Layers with physical stack: {summary['layers_with_physical_stack']}",
                f"- Layers with inferred stack: {summary['layers_with_inferred_stack']}",
                "",
            ]
        )

    if not rows:
        return "\n".join([*header, "No layers found.", ""])

    columns = list(rows[0].keys())
    label_map = {
        "layer": "Layer",
        "datatype": "Datatype",
        "name": "Name",
        "style_source": "Style Source",
        "physical_stack_known": "Physical Stack Known",
        "matched_pdk": "PDK Match",
        "visible": "Visible",
        "material_preset": "Material Preset",
        "material_name": "Material Name",
        "zmin_um": "zmin (um)",
        "thickness_um": "Thickness (um)",
        "polygon_count": "Polygons",
        "total_area_um2": "Area (um^2)",
        "label_anchor_x_um": "Label X (um)",
        "label_anchor_y_um": "Label Y (um)",
        "description": "Description",
    }
    table_lines = [
        "| " + " | ".join(label_map.get(column, column) for column in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        table_lines.append("| " + " | ".join(_escape_markdown_table(row[column]) for column in columns) + " |")

    return "\n".join([*header, *table_lines, ""])


def _escape_markdown_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _infer_layer_report_format(path: Path, explicit_format: str | None) -> str:
    if explicit_format is not None:
        normalized = explicit_format.strip().lower()
        if normalized in {"md", "markdown"}:
            return "markdown"
        if normalized == "csv":
            return "csv"
        raise ValueError("Unsupported layer report format. Use 'csv' or 'markdown'.")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    raise ValueError("Could not infer layer report format from output path. Use a .csv or .md suffix, or pass format= explicitly.")
