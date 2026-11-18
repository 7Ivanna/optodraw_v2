"""GDS parsing, layer-stack mapping, plotting, and mesh export helpers."""

from optodraw.gds.layout import (
    GDSLayout,
    GDSLayerRecord,
    GDSSection,
    load_bounds_from_path,
    load_bounds_from_source,
    load_gds_cell,
    load_gds_geometry_from_path,
    load_gds_geometry_from_source,
    load_gds_layout,
    polygon_points,
)
from optodraw.gds.mesh import build_gds_sections, build_gds_trimesh, weighted_x_positions
from optodraw.gds.check import check_stack
from optodraw.gds.parsers import (
    bundled_stack_names,
    load_layer_stack,
    parse_blendergds_layer_config,
    parse_gds3d_techfile,
    parse_klayout_lyp,
)
from optodraw.gds.plotting import plot_gds_cross_section, plot_gds_top_view
from optodraw.gds.styles import (
    GENERIC_AUX_LAYER_DEPTHS,
    GDS_LAYER_PALETTE,
    GDS_MATERIAL_ALIASES,
    LayerSpec,
    MeshBackend,
    coerce_scalar,
    color_to_rgba,
    get_gdsfactory_layer_styles,
    get_generic_pdk_layer_styles,
    get_layer_name_map,
    layer_tuple_from_value,
    material_preset_from_layer_name,
    material_preset_from_name,
    normalize_layer_stack,
)
from optodraw.gds.layout_view import layout_html
from optodraw.gds.technology import Technology, TechnologyLayer

_XSECTION_EXPORTS = {
    "CrossSection",
    "CrossSectionStripLayout",
    "cross_section",
    "LayoutCut",
    "OutputStack",
    "ProcessDefinition",
    "SectionBeam",
    "TopView",
    "XSectionBundle",
    "XSectionEngine",
    "bootstrap_process_skeleton",
    "export_xsection_bundle",
    "layer_stack_hints",
    "load_process_definition",
    "stack_section",
    "top_view",
}


def __getattr__(name: str):
    if name in _XSECTION_EXPORTS:
        from optodraw.gds import xsection

        value = getattr(xsection, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "bundled_stack_names",
    "check_stack",
    "load_layer_stack",
    "GENERIC_AUX_LAYER_DEPTHS",
    "GDSLayout",
    "GDSLayerRecord",
    "GDSSection",
    "GDS_LAYER_PALETTE",
    "GDS_MATERIAL_ALIASES",
    "LayerSpec",
    "MeshBackend",
    "Technology",
    "TechnologyLayer",
    "build_gds_sections",
    "build_gds_trimesh",
    "color_to_rgba",
    "coerce_scalar",
    "get_gdsfactory_layer_styles",
    "get_generic_pdk_layer_styles",
    "get_layer_name_map",
    "layer_tuple_from_value",
    "load_bounds_from_path",
    "load_bounds_from_source",
    "load_gds_cell",
    "load_gds_geometry_from_path",
    "load_gds_geometry_from_source",
    "load_gds_layout",
    "material_preset_from_layer_name",
    "material_preset_from_name",
    "normalize_layer_stack",
    "parse_blendergds_layer_config",
    "parse_gds3d_techfile",
    "parse_klayout_lyp",
    "plot_gds_cross_section",
    "plot_gds_top_view",
    "CrossSection",
    "CrossSectionStripLayout",
    "LayoutCut",
    "OutputStack",
    "ProcessDefinition",
    "XSectionBundle",
    "XSectionEngine",
    "bootstrap_process_skeleton",
    "cross_section",
    "export_xsection_bundle",
    "layer_stack_hints",
    "layout_html",
    "load_process_definition",
    "polygon_points",
    "weighted_x_positions",
]
