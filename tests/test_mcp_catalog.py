"""Tests for catalog workflow discovery and MCP tool dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from optodraw.catalog import (
    describe_workflow_api,
    list_animation_recipes,
    list_on_chip_components,
    workflow_catalog,
)
from optodraw.mcp_server import (
    _get_available_components,
    _get_on_chip_components,
    _tool_definitions,
    dispatch_tool,
)


pytest.importorskip("yaml")
pytest.importorskip("shapely")

FIXTURE = Path(__file__).parent / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


class TestWorkflowCatalog:
    def test_workflow_catalog_includes_new_apis(self):
        catalog = workflow_catalog()
        assert "export_xsection_bundle" in catalog["xsection"]
        assert "XSectionEngine" in catalog["xsection"]
        assert "build_ring_filter" in catalog["layout_builders"]
        assert "build_mzm_mesh" in catalog["layout_builders"]
        assert "build_microring_weight_mesh" in catalog["layout_builders"]
        assert "build_publication_bundle" in catalog["publication"]
        assert "single_figure" in catalog["publication"]["templates"]
        assert "physics_trace_to_timeline_hints" in catalog["physics_bridge"]
        assert "compile_physics_animation" in catalog["physics_bridge"]
        assert "export_interactive_html" in catalog["interactive"]
        assert len(catalog["animation_recipes"]) >= 10
        assert "render_physical" in catalog["schematic_rendering"]["component_flags"]

    def test_describe_workflow_api_physics_and_interactive(self):
        hints = describe_workflow_api("physics_trace_to_timeline_hints")
        assert hints["kind"] == "physics_bridge"
        assert hints["mcp_tool"] == "optodraw_physics_timeline_hints"
        interactive = describe_workflow_api("export_interactive_html")
        assert interactive["kind"] == "interactive"
        assert interactive["mcp_tool"] == "optodraw_export_interactive_html"

    def test_list_animation_recipes_matches_catalog(self):
        names = list_animation_recipes()
        catalog_names = [entry["name"] for entry in workflow_catalog()["animation_recipes"]]
        assert names == catalog_names
        assert "animate_mzm_mechanism" in names

    def test_describe_workflow_api_animation_and_template(self):
        focus = describe_workflow_api("animate_focus")
        assert focus["kind"] == "animation_recipe"
        template = describe_workflow_api("single_figure")
        assert template["kind"] == "publication_template"
        assert template["panel_count"] >= 1


class TestOnChipCatalog:
    def test_on_chip_components_include_schematic_default(self):
        entries = list_on_chip_components()
        assert entries
        waveguide = next(item for item in entries if item["name"] == "Waveguide")
        assert waveguide["schematic_default"] is True
        assert waveguide["supports_render_physical"] is True

    def test_on_chip_filter_schematic_default(self):
        schematic = list_on_chip_components(schematic_default=True)
        assert all(item["schematic_default"] for item in schematic)
        assert any(item["name"] == "MicroringResonator" for item in schematic)


class TestMcpComponentListing:
    def test_mcp_components_derived_from_catalog(self):
        mcp_components = _get_available_components()
        on_chip = _get_on_chip_components()
        mcp_types = {item["type"] for item in mcp_components}
        assert "Prism" in mcp_types
        assert "Waveguide" in mcp_types
        wg_mcp = next(item for item in mcp_components if item["type"] == "Waveguide")
        wg_catalog = next(item for item in on_chip if item["name"] == "Waveguide")
        assert wg_mcp["schematic_default"] == wg_catalog["schematic_default"]
        assert wg_mcp["supports_render_physical"] == wg_catalog["supports_render_physical"]

    def test_tool_definitions_include_new_tools(self):
        names = {tool["name"] for tool in _tool_definitions()}
        for required in (
            "optodraw_list_onchip_components",
            "optodraw_list_workflows",
            "optodraw_export_xsection_bundle",
            "optodraw_build_publication_bundle",
            "optodraw_physics_timeline_hints",
            "optodraw_compile_physics_animation",
            "optodraw_export_interactive_html",
        ):
            assert required in names


class TestMcpDispatch:
    def test_dispatch_list_workflows(self):
        payload = json.loads(dispatch_tool("optodraw_list_workflows"))
        assert "build_ring_filter" in payload["layout_builders"]
        assert "physics_trace_to_timeline_hints" in payload["physics_bridge"]
        assert "export_interactive_html" in payload["interactive"]

    def test_dispatch_physics_timeline_hints(self):
        spec = {
            "title": "MCP Physics Hints",
            "platform": "on_chip",
            "components": [
                {"type": "MZI", "center": [0, 0], "angle": 0, "id": "mzi"},
            ],
        }
        payload = json.loads(
            dispatch_tool(
                "optodraw_physics_timeline_hints",
                {"spec": spec, "wavelength_nm": 1550.0},
            )
        )
        assert "mzi" in payload
        assert payload["mzi"]["recipe"] == "animate_interference"
        assert "phase_bias_rad" in payload["mzi"]["hints"]

    def test_dispatch_export_interactive_html(self, tmp_path):
        spec = {
            "title": "MCP Interactive",
            "platform": "free_space",
            "components": [
                {"type": "Laser", "center": [0, 0], "angle": 0, "id": "las"},
                {"type": "Mirror", "center": [20, 0], "angle": 45, "id": "mir"},
            ],
        }
        out = tmp_path / "interactive.html"
        payload = json.loads(
            dispatch_tool(
                "optodraw_export_interactive_html",
                {"spec": spec, "output_path": str(out)},
            )
        )
        assert payload["interactive"] is True
        assert Path(payload["output_path"]).is_file()
        assert 'data-optodraw-interactive-scene="true"' in out.read_text(encoding="utf-8")

    def test_dispatch_compile_physics_animation_returns_timeline_summary(self):
        spec = {
            "title": "MCP Compiler",
            "platform": "on_chip",
            "components": [{"type": "MZI", "center": [0, 0], "angle": 0, "id": "mzi"}],
        }
        payload = json.loads(
            dispatch_tool(
                "optodraw_compile_physics_animation",
                {"spec": spec, "fps": 24, "duration_s": 3.5},
            )
        )
        assert payload["timeline"] is True
        assert payload["fps"] == 24
        assert payload["duration_s"] == 3.5
        assert payload["step_count"] > 0
        assert "show" in payload["step_kinds"]

    def test_dispatch_export_xsection_bundle(self, tmp_path):
        cut = {
            "type": "strips",
            "strips": [
                {"layer": "RIB", "width_um": 0.5, "center_y_um": 0.0},
                {"layer": "SLAB", "width_um": 2.0, "center_y_um": 0.0},
            ],
        }
        payload = json.loads(
            dispatch_tool(
                "optodraw_export_xsection_bundle",
                {
                    "process_yaml": str(FIXTURE),
                    "output_dir": str(tmp_path / "xsection"),
                    "cut": cut,
                },
            )
        )
        assert Path(payload["composite"]).exists()
        assert payload["mode"] == "expert"

    def test_dispatch_build_publication_bundle(self, tmp_path):
        spec = {
            "title": "MCP Publication Smoke",
            "platform": "free_space",
            "components": [
                {"type": "Laser", "center": [0, 0], "angle": 0, "id": "las"},
                {"type": "Mirror", "center": [20, 0], "angle": 45, "id": "mir"},
            ],
        }
        payload = json.loads(
            dispatch_tool(
                "optodraw_build_publication_bundle",
                {
                    "spec": spec,
                    "output_dir": str(tmp_path / "pub"),
                    "template": "single_figure",
                    "formats": ["svg", "json"],
                },
            )
        )
        assert payload["template"] == "single_figure"
        assert Path(payload["manifest_path"]).exists()
        assert "svg" in payload["primary_paths"]

    def test_dispatch_list_onchip_components_filter(self):
        payload = json.loads(
            dispatch_tool(
                "optodraw_list_onchip_components",
                {"schematic_default": True},
            )
        )
        assert payload
        assert all(item["schematic_default"] for item in payload)


class TestToolsSayWhereTheyPutThings:
    """An agent cannot open a file it cannot locate.

    ``optodraw_render_3d`` took a relative ``filename``, defaulted it, wrote the
    page into whatever directory the server happened to be running in, and
    reported the bare name back — so the caller learned neither where the file
    went nor that a mistyped argument had been ignored.
    """

    SPEC = {
        "schema_version": 2, "title": "MCP path probe", "width": 120, "height": 80,
        "components": [{"type": "Laser", "id": "l1", "center": [-30, 0]},
                       {"type": "Lens", "id": "n1", "center": [10, 0]}],
        "beams": [], "routes": [],
    }

    def test_render_3d_writes_where_it_is_told_and_says_so(self, tmp_path):
        import json

        from optodraw.mcp_server import dispatch_tool

        target = tmp_path / "nested" / "scene.html"
        payload = json.loads(dispatch_tool("optodraw_render_3d",
                                           {"spec": self.SPEC, "output_path": str(target)}))
        assert payload["output_path"] == str(target.resolve())
        assert target.is_file() and payload["bytes"] == target.stat().st_size

    def test_render_3d_still_answers_to_the_old_argument(self, tmp_path):
        import json

        from optodraw.mcp_server import dispatch_tool

        target = tmp_path / "legacy.html"
        payload = json.loads(dispatch_tool("optodraw_render_3d",
                                           {"spec": self.SPEC, "filename": str(target)}))
        assert payload["output_path"] == str(target.resolve())

    def test_create_setup_reports_resolved_paths(self, tmp_path):
        from optodraw.mcp_server import dispatch_tool

        svg = tmp_path / "setup.svg"
        result = dispatch_tool("optodraw_create_setup", {"spec": self.SPEC, "output_svg": str(svg)})
        assert str(svg.resolve()) in result
        assert svg.is_file()
