"""optodraw MCP Server — AI-assisted optical setup design.

This exposes optodraw as an MCP tool server, allowing AI assistants
(VS Code Copilot, Cursor, Windsurf, etc.) to design optical setups
via natural language.

Run with: optodraw-mcp
Or configure in your MCP client as a stdio server.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _allowed_output_roots() -> list[Path]:
    """Directories the MCP server may write into.

    The server runs with user privileges, so an injected prompt that steers an
    output argument must not be able to plant files anywhere on disk. Writes
    stay inside the working directory, the user's home, and the system temp
    directory by default; ``OPTODRAW_MCP_ALLOWED_ROOTS`` adds more (os.pathsep
    separated).
    """

    roots = {Path.cwd().resolve(), Path.home().resolve(), Path(tempfile.gettempdir()).resolve()}
    extra = os.environ.get("OPTODRAW_MCP_ALLOWED_ROOTS", "")
    for item in extra.split(os.pathsep):
        if item.strip():
            roots.add(Path(item.strip()).expanduser().resolve())
    return sorted(roots)


def _safe_output_path(value: str | os.PathLike[str], what: str) -> Path:
    """Resolve an output argument and refuse paths outside the allowed roots."""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()
    for root in _allowed_output_roots():
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    allowed = ", ".join(str(root) for root in _allowed_output_roots())
    raise ValueError(
        f"{what} '{value}' is outside the directories this tool may write to "
        f"({allowed}). Add a root via OPTODRAW_MCP_ALLOWED_ROOTS if needed."
    )


def _build_scene_from_spec(spec: dict) -> Any:
    """Given a JSON spec, build an optodraw Scene."""
    from optodraw.schema import scene_from_spec

    return scene_from_spec(spec)


def _get_available_components() -> list[dict[str, Any]]:
    """Return creatable components from the shared catalog (registry is source of truth)."""
    from optodraw.catalog import component_catalog
    from optodraw.registry import component_registry

    registry = component_registry()
    components: list[dict[str, Any]] = []
    for name, info in sorted(component_catalog().items()):
        spec = registry.get(name)
        if spec is None or not spec.creatable:
            continue
        components.append(
            {
                "type": name,
                "category": info["category"],
                "platform": info["platform"],
                "params": list(info["parameters"]),
                "desc": info["description"],
                "schematic_default": info.get("schematic_default", False),
                "supports_render_physical": info.get("supports_render_physical", False),
                "supports_physical_spec": info.get("supports_physical_spec", False),
            }
        )
    return components


def _get_on_chip_components(*, schematic_default: bool | None = None) -> list[dict[str, Any]]:
    from optodraw.catalog import list_on_chip_components

    return list_on_chip_components(schematic_default=schematic_default)


def _get_workflow_catalog() -> dict[str, Any]:
    from optodraw.catalog import workflow_catalog

    return workflow_catalog()


def _resolve_layout_cut(cut_spec: dict[str, Any], *, process_yaml: str | None = None) -> Any:
    """Build a LayoutCut from MCP JSON (synthetic strips or GDS slice)."""
    from optodraw.gds.xsection import CrossSectionStripLayout
    from optodraw.gds.xsection.masks import LayoutCut

    cut_type = cut_spec.get("type", "strips")
    if cut_type == "strips":
        layout = CrossSectionStripLayout()
        for strip in cut_spec.get("strips", []):
            layout.strip(
                strip["layer"],
                width_um=float(strip["width_um"]),
                center_y_um=float(strip["center_y_um"]),
            )
        if "y_min" in cut_spec and "y_max" in cut_spec:
            layout.span(float(cut_spec["y_min"]), float(cut_spec["y_max"]))
        section = cut_spec.get("section", {})
        layout.section(
            x=float(section.get("x", 0.0)),
            window=float(section.get("window", 4.0)),
            label=str(section.get("label", "strip")),
        )
        return layout.to_layout_cut()

    if cut_type == "gds":
        from optodraw.gds import load_gds_layout, load_process_definition

        gds_path = cut_spec.get("gds_path")
        if not gds_path:
            raise ValueError("gds cut requires gds_path")
        process_path = process_yaml or cut_spec.get("process_yaml")
        process = load_process_definition(process_path) if process_path else None
        layout = load_gds_layout(gds_path)
        section = cut_spec.get("section", {})
        return LayoutCut.from_gds(layout, section, process=process)

    raise ValueError(f"Unknown cut type '{cut_type}'. Expected 'strips' or 'gds'.")


def _handle_export_xsection_bundle(arguments: dict[str, Any]) -> str:
    from optodraw.gds.xsection import export_xsection_bundle

    process_yaml = arguments.get("process_yaml")
    if not process_yaml:
        raise ValueError("process_yaml is required")
    output_dir = _safe_output_path(arguments.get("output_dir", "xsection_out"), "output_dir")
    cut = _resolve_layout_cut(arguments.get("cut", {}), process_yaml=process_yaml)
    mode = arguments.get("mode", "auto")
    rasterize = bool(arguments.get("rasterize", False))

    layout = None
    section = None
    if mode == "fast":
        gds_path = arguments.get("gds_path") or arguments.get("cut", {}).get("gds_path")
        if not gds_path:
            raise ValueError("fast mode requires gds_path")
        from optodraw.gds import load_gds_layout

        layout = load_gds_layout(gds_path)
        section = arguments.get("section") or arguments.get("cut", {}).get("section") or {
            "x": 0.0,
            "window": 4.0,
            "label": "A-A'",
        }

    bundle = export_xsection_bundle(
        process_yaml,
        cut,
        str(output_dir),
        mode=mode,
        rasterize=rasterize,
        layout=layout,
        section=section,
    )
    payload = {
        "composite": str(bundle.composite_path),
        "mode": bundle.mode,
        "layer_paths": {name: str(path) for name, path in bundle.layer_paths.items()},
        "manifest": str(bundle.manifest_path) if bundle.manifest_path else None,
        "png_paths": {name: str(path) for name, path in bundle.png_paths.items()},
    }
    return json.dumps(payload, indent=2)


def _handle_build_publication_bundle(arguments: dict[str, Any]) -> str:
    from optodraw.publication import build_publication_bundle

    spec = arguments.get("spec")
    if spec is None:
        raise ValueError("spec is required")
    output_dir = _safe_output_path(arguments.get("output_dir", "publication_out"), "output_dir")
    template = arguments.get("template", "single_figure")
    formats = arguments.get("formats", ["svg", "json"])
    scene = _build_scene_from_spec(spec)
    bundle = build_publication_bundle(
        scene,
        str(output_dir),
        template=template,
        formats=tuple(formats),
        preset=arguments.get("preset"),
        dpi=float(arguments.get("dpi", 300)),
        include_polarization=bool(arguments.get("include_polarization", False)),
        stem=arguments.get("stem"),
        caption=arguments.get("caption"),
    )
    return json.dumps(bundle.to_dict(), indent=2)


def _handle_physics_timeline_hints(arguments: dict[str, Any]) -> str:
    from optodraw.core.physics_bridge import physics_trace_to_timeline_hints

    spec = arguments.get("spec")
    if spec is None:
        raise ValueError("spec is required")
    scene = _build_scene_from_spec(spec)
    hints = physics_trace_to_timeline_hints(
        scene,
        wavelength_nm=float(arguments.get("wavelength_nm", 1550.0)),
        include_guided_paths=bool(arguments.get("include_guided_paths", True)),
    )
    return json.dumps(hints, indent=2)


def _timeline_summary(timeline: Any) -> dict[str, Any]:
    steps = list(getattr(timeline, "_steps", []))
    return {
        "timeline": True,
        "fps": getattr(timeline, "fps", None),
        "duration_s": getattr(timeline, "duration_s", None),
        "step_count": len(steps),
        "step_kinds": [getattr(step, "kind", "") for step in steps],
    }


def _handle_compile_physics_animation(arguments: dict[str, Any]) -> str:
    from optodraw.catalog import compile_physics_animation

    spec = arguments.get("spec")
    if spec is None:
        raise ValueError("spec is required")
    scene = _build_scene_from_spec(spec)
    compile_kwargs: dict[str, Any] = {}
    if arguments.get("fps") is not None:
        compile_kwargs["fps"] = int(arguments["fps"])
    if arguments.get("duration_s") is not None:
        compile_kwargs["duration_s"] = float(arguments["duration_s"])
    if arguments.get("wavelength_nm") is not None:
        compile_kwargs["wavelength_nm"] = float(arguments["wavelength_nm"])
    if arguments.get("include_guided_paths") is not None:
        compile_kwargs["include_guided_paths"] = bool(arguments["include_guided_paths"])
    result = compile_physics_animation(scene, **compile_kwargs)
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
    elif hasattr(result, "_steps"):
        payload = _timeline_summary(result)
    elif isinstance(result, dict):
        payload = result
    else:
        payload = {"result": result}
    return json.dumps(payload, indent=2, default=str)


def _handle_export_interactive_html(arguments: dict[str, Any]) -> str:
    from optodraw.renderers.interactive_scene import export_interactive_html

    spec = arguments.get("spec")
    if spec is None:
        raise ValueError("spec is required")
    output_path = arguments.get("output_path")
    if not output_path:
        raise ValueError("output_path is required")
    resolved_output = _safe_output_path(output_path, "output_path")
    scene = _build_scene_from_spec(spec)
    html = export_interactive_html(
        scene,
        str(resolved_output),
        show_component_sidebar=bool(arguments.get("show_component_sidebar", True)),
        show_dimension_markers=bool(arguments.get("show_dimension_markers", True)),
        dimension_markers_default=bool(arguments.get("dimension_markers_default", False)),
    )
    out = resolved_output
    payload = {
        "output_path": str(out),
        "bytes": out.stat().st_size if out.is_file() else len(html.encode("utf-8")),
        "interactive": 'data-optodraw-interactive-scene="true"' in html,
    }
    return json.dumps(payload, indent=2)


def _get_available_presets() -> list[dict]:
    from optodraw import PRESETS

    return [{"name": name, "builder": func.__name__} for name, func in PRESETS.items()]


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "optodraw_list_components",
            "description": "List creatable optical components and parameters from the shared catalog.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "optodraw_list_onchip_components",
            "description": (
                "List on-chip photonic components with schematic_default and physical-rendering metadata."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "schematic_default": {
                        "type": "boolean",
                        "description": "When set, filter to components that do or do not default to schematic art.",
                    },
                },
            },
        },
        {
            "name": "optodraw_list_workflows",
            "description": (
                "List workflow APIs: xsection export, layout builders, animation recipes, "
                "publication templates, and schematic rendering flags."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "optodraw_create_setup",
            "description": (
                "Create an optical setup from a JSON specification. "
                "Returns scene data and can save SVG (2D) and interactive 3D HTML files. "
                "The spec should have 'title', 'components' (list of {type, center, angle, ...}), "
                "and 'beams' (list of {path: [component_ids or coordinates], wavelength})."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {
                        "type": "object",
                        "description": "The optical setup specification",
                    },
                    "output_svg": {
                        "type": "string",
                        "description": "Filename for SVG output (optional)",
                    },
                    "output_3d": {
                        "type": "string",
                        "description": "Filename for 3D HTML output (optional)",
                    },
                },
                "required": ["spec"],
            },
        },
        {
            "name": "optodraw_render_3d",
            "description": "Re-render an existing setup specification to interactive 3D HTML.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {"type": "object"},
                    "output_path": {
                        "type": "string",
                        "description": "Destination .html path (created if its directory is missing).",
                        "default": "setup_3d.html",
                    },
                    "filename": {"type": "string", "description": "Deprecated alias for output_path."},
                },
                "required": ["spec"],
            },
        },
        {
            "name": "optodraw_list_presets",
            "description": "List built-in setup presets.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "optodraw_export_xsection_bundle",
            "description": (
                "Export a process-aware cross-section bundle (composite SVG, per-layer SVG, manifest) "
                "from a process YAML and layout cut definition."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "process_yaml": {
                        "type": "string",
                        "description": "Path to a process/stack YAML (ProcessDefinition).",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory for exported SVG/PNG/manifest files.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "expert", "fast"],
                        "default": "auto",
                    },
                    "rasterize": {
                        "type": "boolean",
                        "default": False,
                        "description": "Also emit PNG rasterizations when dependencies are available.",
                    },
                    "gds_path": {
                        "type": "string",
                        "description": "Optional GDS path (required for fast mode).",
                    },
                    "cut": {
                        "type": "object",
                        "description": (
                            "Layout cut spec. Use type='strips' with strips=[{layer,width_um,center_y_um}] "
                            "for synthetic cuts, or type='gds' with gds_path and section={x,window,label}."
                        ),
                    },
                },
                "required": ["process_yaml", "output_dir"],
            },
        },
        {
            "name": "optodraw_build_publication_bundle",
            "description": (
                "Build a multi-format publication bundle from a scene JSON spec and named template."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {"type": "object", "description": "Scene JSON specification."},
                    "output_dir": {"type": "string", "description": "Destination directory."},
                    "template": {
                        "type": "string",
                        "description": "Publication template name (see optodraw_list_workflows).",
                        "default": "single_figure",
                    },
                    "formats": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Output formats: svg, tikz, png, html, json.",
                    },
                    "preset": {"type": "string", "description": "Optional paper preset override."},
                    "dpi": {"type": "number", "default": 300},
                    "include_polarization": {"type": "boolean", "default": False},
                    "stem": {"type": "string"},
                    "caption": {"type": "string"},
                },
                "required": ["spec", "output_dir"],
            },
        },
        {
            "name": "optodraw_physics_timeline_hints",
            "description": (
                "Return physics→animation timeline hints for a scene JSON spec: suggested "
                "animation recipes and parameter hints per component id."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {"type": "object", "description": "Scene JSON specification."},
                    "wavelength_nm": {"type": "number", "default": 1550.0},
                    "include_guided_paths": {"type": "boolean", "default": True},
                },
                "required": ["spec"],
            },
        },
        {
            "name": "optodraw_compile_physics_animation",
            "description": (
                "Compile physics traces into an animation timeline via "
                "optodraw.core.physics_compiler."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {"type": "object", "description": "Scene JSON specification."},
                    "fps": {"type": "integer", "default": 30},
                    "duration_s": {"type": "number", "default": 4.0},
                    "wavelength_nm": {"type": "number", "default": 1550.0},
                    "include_guided_paths": {"type": "boolean", "default": True},
                },
                "required": ["spec"],
            },
        },
        {
            "name": "optodraw_export_interactive_html",
            "description": (
                "Export an enhanced interactive Three.js HTML viewer from a scene JSON spec."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spec": {"type": "object", "description": "Scene JSON specification."},
                    "output_path": {
                        "type": "string",
                        "description": "Destination .html path.",
                    },
                    "show_component_sidebar": {"type": "boolean", "default": True},
                    "show_dimension_markers": {"type": "boolean", "default": True},
                    "dimension_markers_default": {"type": "boolean", "default": False},
                },
                "required": ["spec", "output_path"],
            },
        },
    ]


def dispatch_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """Execute an MCP tool by name and return a text payload (for tests and stdio server)."""
    arguments = arguments or {}

    if name == "optodraw_list_components":
        return json.dumps(_get_available_components(), indent=2)

    if name == "optodraw_list_onchip_components":
        schematic_default = arguments.get("schematic_default")
        if schematic_default is not None:
            schematic_default = bool(schematic_default)
        return json.dumps(_get_on_chip_components(schematic_default=schematic_default), indent=2)

    if name == "optodraw_list_workflows":
        return json.dumps(_get_workflow_catalog(), indent=2)

    if name == "optodraw_list_presets":
        return json.dumps(_get_available_presets(), indent=2)

    if name == "optodraw_create_setup":
        spec = arguments["spec"]
        scene = _build_scene_from_spec(spec)
        results = [f"Created scene: {scene}"]
        svg_file = arguments.get("output_svg")
        if svg_file:
            resolved_svg = _safe_output_path(svg_file, "output_svg")
            resolved_svg.parent.mkdir(parents=True, exist_ok=True)
            scene.render_svg(str(resolved_svg))
            results.append(f"SVG saved to: {resolved_svg}")
        html_file = arguments.get("output_3d")
        if html_file:
            resolved_html = _safe_output_path(html_file, "output_3d")
            resolved_html.parent.mkdir(parents=True, exist_ok=True)
            scene.render_threejs(str(resolved_html))
            results.append(f"3D HTML saved to: {resolved_html}")
        results.append(f"\nScene data:\n{json.dumps(scene.to_dict(), indent=2)}")
        return "\n".join(results)

    if name == "optodraw_render_3d":
        spec = arguments["spec"]
        # "filename" is the original argument; "output_path" is what every other
        # tool here calls it, and what callers reach for. Accept both, and answer
        # with the resolved path: a bare relative name told the caller neither
        # where the page went nor that their argument had been ignored.
        target = _safe_output_path(
            arguments.get("output_path") or arguments.get("filename") or "setup_3d.html",
            "output_path",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        scene = _build_scene_from_spec(spec)
        scene.render_threejs(str(target))
        return json.dumps(
            {
                "output_path": str(target),
                "bytes": target.stat().st_size if target.is_file() else 0,
            },
            indent=2,
        )

    if name == "optodraw_export_xsection_bundle":
        return _handle_export_xsection_bundle(arguments)

    if name == "optodraw_build_publication_bundle":
        return _handle_build_publication_bundle(arguments)

    if name == "optodraw_physics_timeline_hints":
        return _handle_physics_timeline_hints(arguments)

    if name == "optodraw_compile_physics_animation":
        return _handle_compile_physics_animation(arguments)

    if name == "optodraw_export_interactive_html":
        return _handle_export_interactive_html(arguments)

    # An unknown tool must surface as a protocol error, not a successful text
    # reply the client would read as a valid result.
    known = ", ".join(sorted(tool["name"] for tool in _tool_definitions()))
    raise ValueError(f"Unknown tool '{name}'. Known tools: {known}")


def main():
    """Entry point for the MCP server (stdio transport)."""
    try:
        from mcp.server import Server  # pyright: ignore[reportMissingImports]
        from mcp.server.stdio import stdio_server  # pyright: ignore[reportMissingImports]
        from mcp.types import Tool, TextContent  # pyright: ignore[reportMissingImports]
    except ImportError:
        print(
            "MCP SDK is required. Install with: pip install optodraw[mcp]",
            file=sys.stderr,
        )
        sys.exit(1)

    server = Server("optodraw")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**tool) for tool in _tool_definitions()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        return [TextContent(type="text", text=dispatch_tool(name, arguments))]

    import asyncio

    asyncio.run(stdio_server(server))


if __name__ == "__main__":
    main()
