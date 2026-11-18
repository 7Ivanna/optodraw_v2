"""Flagship end-to-end Optodraw demo: ring filter chip pipeline.

Builds a routed on-chip scene (grating coupler → microring → photodetector) with
**schematic-default** component art and **physical-µm** ports/routes via
``build_ring_filter()``. Runs lightweight physics stubs and exports a full
publication/teaching bundle:

    Python scene → physics trace → SVG/TikZ → Three.js → scene JSON
    → optional GLB → optional Blender render script → optional resonance GIF
    → optional cross-section SVG (``--xsection``)

Outputs are written to ``examples/output/flagship/`` by default (gitignored).

Usage::

    python examples/flagship_ring_filter_demo.py
    python examples/flagship_ring_filter_demo.py --output-dir /tmp/flagship --gif
    python examples/flagship_ring_filter_demo.py --xsection
    python examples/flagship_ring_filter_demo.py --run-blender   # needs Blender + GLB deps

Requires only the core package for SVG/TikZ/Three.js/JSON. GLB export needs
``pip install optodraw[gds]``. Cross-section export uses the bundled
``generic_siph_minimal.yaml`` fixture (or ``OPTODRAW_OPEN_PDK_STACK`` when set).
GIF export needs ``pip install optodraw[gif]``. Headless Blender rendering is optional.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from optodraw import (
    animate_resonance_scan,
    build_ring_filter,
    export_blender_script,
)
from optodraw.core.routing import Route

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "examples" / "output" / "flagship"
XSECTION_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


@dataclass(frozen=True)
class PhysicsSummary:
    """Collected physics stub results for the flagship scene."""

    guided: dict[str, float]
    resonance: dict[str, Any]
    validation_warnings: list[str]


def build_scene() -> tuple[Any, Any, Any, Any, list[Route]]:
    """Construct the GC → ring → PD routed on-chip flagship scene."""

    built = build_ring_filter(title="Flagship Ring Filter Demo", spacing_um=32.0)
    scene = built["scene"]
    scene.width = 300
    scene.height = 140
    return (
        scene,
        built["grating_coupler"],
        built["ring"],
        built["photodetector"],
        built["routes"],
    )


def run_physics(
    scene: Any,
    *,
    gc: Any,
    ring: Any,
    pd: Any,
    routes: list[Route],
    wavelength_nm: float = 1550.0,
) -> PhysicsSummary:
    """Run guided-path, resonator, and validation physics stubs."""

    route_in, route_drop = routes[0], routes[1]
    guided = scene.trace_guided_path(
        [gc, route_in, ring, route_drop, pd],
        wavelength_nm=wavelength_nm,
    )
    resonance = scene.trace_resonator(ring, wavelength_nm=wavelength_nm)
    validation_warnings = scene.validate_physics(mode="coupling", wavelength_nm=wavelength_nm)
    validation_warnings.extend(scene.validate_physics(mode="mixed"))
    return PhysicsSummary(
        guided=guided.to_dict(),
        resonance=resonance,
        validation_warnings=validation_warnings,
    )


def _geo_node_to_meshes(node: dict[str, Any], trimesh: Any) -> list[Any]:
    """Convert one Optodraw geometry_3d node into local trimesh meshes."""

    shape = node.get("shape")
    if shape == "group":
        meshes: list[Any] = []
        for child in node.get("children", []):
            if isinstance(child, dict):
                meshes.extend(_geo_node_to_meshes(child, trimesh))
        return meshes

    transform = trimesh.transformations.identity_matrix()
    position = node.get("position", [0.0, 0.0, 0.0])
    if len(position) >= 3:
        transform = trimesh.transformations.translation_matrix(
            [float(position[0]), float(position[1]), float(position[2])]
        )

    rotation = node.get("rotation")
    if rotation and len(rotation) >= 3:
        rx, ry, rz = (math.radians(float(rotation[0])), math.radians(float(rotation[1])), math.radians(float(rotation[2])))
        rot = trimesh.transformations.euler_matrix(rx, ry, rz, axes="sxyz")
        transform = transform @ rot

    mesh = None
    if shape == "box":
        extents = [
            max(float(node.get("width", 1.0)), 1e-3),
            max(float(node.get("height", 1.0)), 1e-3),
            max(float(node.get("depth", node.get("width", 1.0))), 1e-3),
        ]
        mesh = trimesh.creation.box(extents=extents)
    elif shape == "cylinder":
        radius = max(float(node.get("radius", 1.0)), 1e-3)
        height = max(float(node.get("height", 1.0)), 1e-3)
        mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=32)
    elif shape == "sphere":
        radius = max(float(node.get("radius", 1.0)), 1e-3)
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=radius)
    elif shape == "torus":
        radius = max(float(node.get("radius", 1.0)), 1e-3)
        tube = max(float(node.get("tube", 0.2)), 1e-3)
        mesh = trimesh.creation.torus(major_radius=radius, minor_radius=tube)
    elif shape == "extruded_polygon":
        from shapely.geometry import Polygon

        points = node.get("points") or []
        if len(points) >= 3:
            xy = [(float(p[0]), float(p[1])) for p in points]
            polygon = Polygon(xy)
            if polygon.is_valid and not polygon.is_empty:
                height = max(float(node.get("height", 0.22)), 1e-3)
                mesh = trimesh.creation.extrude_polygon(polygon, height=height)

    if mesh is None:
        return []

    mesh.apply_transform(transform)
    return [mesh]


def _world_transform_matrix(component, trimesh: Any) -> Any:
    """Build a trimesh transform matching Three.js world placement."""

    wt = component.world_transform
    translation = trimesh.transformations.translation_matrix(
        [wt.position.x, wt.position.z, -wt.position.y]
    )
    rx = math.radians(wt.rotation_deg.x)
    ry = math.radians(wt.rotation_deg.z)
    rz = math.radians(-wt.rotation_deg.y)
    rotation = trimesh.transformations.euler_matrix(rx, ry, rz, axes="sxyz")
    return translation @ rotation


def try_export_glb(scene: Any, output_path: Path) -> bool:
    """Export scene 3D geometry to GLB when trimesh/shapely are installed."""

    try:
        import trimesh
    except ImportError:
        return False

    skip_types = {
        "Beam",
        "Route",
        "WaveguideRoute",
        "FiberRoute",
        "Grid",
        "Group",
        "FocusingBeam",
    }
    meshes: list[Any] = []
    for node in scene.walk():
        component_type = getattr(node, "component_type", node.__class__.__name__)
        if component_type in skip_types:
            continue
        geometry = node.geometry_3d()
        if not geometry:
            continue
        local_meshes = _geo_node_to_meshes(geometry, trimesh)
        world = _world_transform_matrix(node, trimesh)
        for mesh in local_meshes:
            mesh.apply_transform(world)
            meshes.append(mesh)

    if not meshes:
        return False

    combined = trimesh.util.concatenate(meshes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(output_path.as_posix(), file_type="glb")
    return True


def export_core_outputs(scene: Any, output_dir: Path) -> dict[str, Path]:
    """Write SVG, TikZ, Three.js HTML, and scene JSON."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "svg": output_dir / "ring_filter.svg",
        "tikz": output_dir / "ring_filter.tex",
        "html": output_dir / "ring_filter.html",
        "json": output_dir / "ring_filter.scene.json",
    }
    scene.render_svg(paths["svg"].as_posix())
    scene.render_tikz(paths["tikz"].as_posix(), standalone=False)
    scene.render_threejs(paths["html"].as_posix(), show_grid=False, camera_distance=175)
    scene.save(paths["json"])
    return paths


def export_physics_report(summary: PhysicsSummary, output_dir: Path) -> Path:
    """Persist physics stub results alongside rendered artifacts."""

    report_path = output_dir / "physics_summary.json"
    payload = {
        "guided_path": summary.guided,
        "resonance": summary.resonance,
        "validation_warnings": summary.validation_warnings,
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return report_path


def try_export_resonance_gif(
    scene: Any,
    ring: Any,
    output_path: Path,
    *,
    wavelength_steps: int = 8,
) -> bool:
    """Render a resonance-scan GIF when pillow/cairosvg extras are available."""

    try:
        timeline = animate_resonance_scan(
            scene,
            ring,
            wavelength_steps=wavelength_steps,
            caption="Ring filter resonance scan",
        )
        timeline.render_gif(output_path.as_posix(), fps=4)
    except ImportError:
        return False
    return output_path.exists()


def try_export_xsection(output_dir: Path, *, process_path: Path | None = None) -> Path | None:
    """Export a strip cross-section SVG when gds/xsection extras are available."""

    try:
        import os

        from optodraw.gds.xsection import CrossSectionStripLayout, XSectionEngine, export_xsection_bundle
    except ImportError:
        return None

    env_path = os.environ.get("OPTODRAW_OPEN_PDK_STACK", "").strip()
    yaml_path = process_path
    if yaml_path is None and env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            yaml_path = candidate
    if yaml_path is None:
        yaml_path = XSECTION_FIXTURE
    if not yaml_path.exists():
        return None

    xsection_dir = output_dir / "xsection"
    engine = XSectionEngine.from_yaml(yaml_path)
    cut = (
        CrossSectionStripLayout()
        .strip("RIB", width_um=0.5, center_y_um=0.0)
        .strip("SLAB", width_um=2.0, center_y_um=0.0)
        .section(label="flagship")
        .to_layout_cut()
    )
    bundle = export_xsection_bundle(engine, cut, xsection_dir)
    return bundle.composite_path if bundle.composite_path.exists() else None


def try_export_blender_bundle(
    glb_path: Path,
    output_dir: Path,
    *,
    run_blender: bool = False,
    blender_executable: str = "blender",
) -> dict[str, Path | None]:
    """Write a headless Blender script (and optionally render PNG)."""

    if not glb_path.exists():
        return {"script": None, "render": None}

    render_path = output_dir / "ring_filter_render.png"
    script_path = export_blender_script(
        output_dir / "ring_filter_render.blender.py",
        source_glb=glb_path,
        output_image=render_path,
        camera_preset="isometric",
        resolution=(1280, 960),
        background_color="#f8fafc",
        samples=32,
    )

    rendered: Path | None = None
    if run_blender and shutil.which(blender_executable):
        try:
            subprocess.run(
                [
                    blender_executable,
                    "--background",
                    "--python",
                    script_path.as_posix(),
                ],
                check=True,
                text=True,
                capture_output=True,
                timeout=600,
            )
            if render_path.exists():
                rendered = render_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            rendered = None

    return {"script": script_path, "render": rendered}


def run_pipeline(
    *,
    output_dir: Path = DEFAULT_OUTPUT,
    wavelength_nm: float = 1550.0,
    write_gif: bool = False,
    write_xsection: bool = False,
    run_blender: bool = False,
    gif_steps: int = 8,
) -> dict[str, Any]:
    """Execute the full flagship export pipeline and return artifact metadata."""

    scene, gc, ring, pd, routes = build_scene()
    summary = run_physics(
        scene,
        gc=gc,
        ring=ring,
        pd=pd,
        routes=routes,
        wavelength_nm=wavelength_nm,
    )

    output_dir = output_dir.expanduser().resolve()
    artifacts = export_core_outputs(scene, output_dir)
    artifacts["physics"] = export_physics_report(summary, output_dir)

    glb_path = output_dir / "ring_filter.glb"
    artifacts["glb"] = glb_path if try_export_glb(scene, glb_path) else None

    blender_bundle = try_export_blender_bundle(
        glb_path if artifacts["glb"] else Path("__missing__.glb"),
        output_dir,
        run_blender=run_blender,
    )
    artifacts["blender_script"] = blender_bundle["script"]
    artifacts["blender_render"] = blender_bundle["render"]

    gif_path = output_dir / "ring_filter_resonance.gif"
    if write_gif and try_export_resonance_gif(scene, ring, gif_path, wavelength_steps=gif_steps):
        artifacts["gif"] = gif_path
    else:
        artifacts["gif"] = None

    artifacts["xsection"] = try_export_xsection(output_dir) if write_xsection else None

    return {
        "output_dir": output_dir,
        "artifacts": artifacts,
        "physics": summary,
    }


def _print_summary(result: dict[str, Any]) -> None:
    output_dir = result["output_dir"]
    artifacts: dict[str, Path | None] = result["artifacts"]
    physics: PhysicsSummary = result["physics"]

    print(f"Flagship demo complete → {output_dir}")
    for key in ("svg", "tikz", "html", "json", "physics", "glb", "xsection", "blender_script", "blender_render", "gif"):
        path = artifacts.get(key)
        status = path if path else "skipped"
        print(f"  {key:16} {status}")

    print("Physics highlights:")
    print(f"  guided path length (um): {physics.guided['path_length_um']:.2f}")
    print(f"  ring through power:      {physics.resonance['through_power']:.3f}")
    if physics.validation_warnings:
        print(f"  validation warnings:     {len(physics.validation_warnings)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for exported artifacts (default: examples/output/flagship)",
    )
    parser.add_argument("--wavelength-nm", type=float, default=1550.0, help="Probe wavelength in nm")
    parser.add_argument("--gif", action="store_true", help="Export resonance-scan GIF when gif extras installed")
    parser.add_argument("--xsection", action="store_true", help="Export strip cross-section SVG (needs optodraw[gds])")
    parser.add_argument("--gif-steps", type=int, default=8, help="Wavelength samples in the GIF timeline")
    parser.add_argument(
        "--run-blender",
        action="store_true",
        help="Run headless Blender render when Blender and GLB export are available",
    )
    parser.add_argument("--blender", default="blender", help="Blender executable name or path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_pipeline(
        output_dir=args.output_dir,
        wavelength_nm=args.wavelength_nm,
        write_gif=args.gif,
        write_xsection=args.xsection,
        run_blender=args.run_blender,
        gif_steps=args.gif_steps,
    )
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
