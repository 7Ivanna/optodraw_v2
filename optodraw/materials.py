"""Material presets for 3D rendering.

The presets are intentionally lightweight PBR descriptions that can be used by
the Three.js renderer without shipping large texture assets.
"""

from __future__ import annotations

from copy import deepcopy


MATERIAL_PRESETS: dict[str, dict[str, object]] = {
    "gold": {
        "label": "Gold",
        "description": "Warm reflective metal for pads, mirrors, and contacts.",
        "color": "#d4af37",
        "metalness": 1.0,
        "roughness": 0.22,
        "physical": "#ffe29b",
    },
    "silicon": {
        "label": "Silicon",
        "description": "Dark neutral semiconductor finish for photonic devices.",
        "color": "#6f747a",
        "metalness": 0.15,
        "roughness": 0.48,
    },
    "silicon_schematic": {
        "label": "Silicon (schematic)",
        "description": "Higher-contrast silicon finish for legible schematic slab thicknesses.",
        "color": "#5a6168",
        "metalness": 0.12,
        "roughness": 0.38,
    },
    "germanium": {
        "label": "Germanium",
        "description": "Dense semiconductor finish for photodetectors and mid-IR layers.",
        "color": "#5f6770",
        "metalness": 0.18,
        "roughness": 0.42,
    },
    "germanium_schematic": {
        "label": "Germanium (schematic)",
        "description": "Readable germanium preset at schematic extrusion heights.",
        "color": "#525a63",
        "metalness": 0.16,
        "roughness": 0.36,
    },
    "indium_phosphide": {
        "label": "Indium Phosphide",
        "description": "III-V semiconductor preset for active photonic and laser structures.",
        "color": "#8a756a",
        "metalness": 0.12,
        "roughness": 0.44,
    },
    "gallium_arsenide": {
        "label": "Gallium Arsenide",
        "description": "III-V semiconductor preset for modulators, emitters, and RF optoelectronics.",
        "color": "#7c655e",
        "metalness": 0.14,
        "roughness": 0.46,
    },
    "silicon_nitride": {
        "label": "Silicon Nitride",
        "description": "Bright nitride material for low-loss waveguides.",
        "color": "#9fb9c9",
        "metalness": 0.05,
        "roughness": 0.32,
    },
    "sio2": {
        "label": "SiO2 / Glass",
        "description": "Transparent dielectric for oxide and glass optics.",
        "color": "#d8eef7",
        "metalness": 0.0,
        "roughness": 0.04,
        "transparent": True,
        "opacity": 0.42,
        "transmission": 0.9,
        "ior": 1.46,
        "thickness": 0.6,
    },
    "titanium": {
        "label": "Titanium",
        "description": "Cool engineering metal for mounts and housings.",
        "color": "#8d99a6",
        "metalness": 0.78,
        "roughness": 0.38,
        "physical": "#c2bab1",
    },
    "titanium_nitride": {
        "label": "Titanium Nitride",
        "description": "Conductive ceramic-metal heater material used in photonic process stacks.",
        "color": "#8b7a58",
        "metalness": 0.72,
        "roughness": 0.34,
    },
    "aluminum": {
        "label": "Aluminum",
        "description": "Bright machined metal for stages and instrument bodies.",
        "color": "#bcc4cc",
        "metalness": 0.88,
        "roughness": 0.28,
        "physical": "#f5f6f6",
    },
    "gst": {
        "label": "GST (Ge2Sb2Te5)",
        "description": "Phase-change chalcogenide film on a waveguide; dark when crystalline.",
        "color": "#4a4458",
        "metalness": 0.35,
        "roughness": 0.4,
    },
    "indium_tin_oxide": {
        "label": "Indium Tin Oxide",
        "description": "Transparent conductive oxide for electro-optic and display-adjacent process layers.",
        "color": "#b7d8df",
        "metalness": 0.08,
        "roughness": 0.14,
        "transparent": True,
        "opacity": 0.58,
        "transmission": 0.72,
        "ior": 1.9,
        "thickness": 0.25,
    },
    "copper": {
        "label": "Copper",
        "description": "Warm conductive metal for interconnects and heat spreaders.",
        "color": "#b46843",
        "metalness": 0.95,
        "roughness": 0.3,
        "physical": "#fad0c0",
    },
    "steel": {
        "label": "Steel",
        "description": "Utility structural metal for blocks and hardware.",
        "color": "#7d8790",
        "metalness": 0.7,
        "roughness": 0.46,
        "physical": "#c0bdba",
    },
    "ceramic": {
        "label": "Ceramic",
        "description": "Neutral ceramic packaging for sources and detectors.",
        "color": "#ddd7c9",
        "metalness": 0.02,
        "roughness": 0.82,
    },
    "polymer": {
        "label": "Polymer",
        "description": "Soft matte polymer finish for housings and flexible parts.",
        "color": "#9fb4a8",
        "metalness": 0.0,
        "roughness": 0.78,
    },
    "glass": {
        "label": "Optical Glass",
        "description": "Clear optical glass preset for lenses and windows.",
        "color": "#c9f1ff",
        "metalness": 0.0,
        "roughness": 0.02,
        "transparent": True,
        "opacity": 0.32,
        "transmission": 0.96,
        "ior": 1.52,
        "thickness": 0.8,
    },
    "air": {
        "label": "Air",
        "description": "Near-invisible surrounding medium for voids, trenches, and cladding gaps.",
        "color": "#eef7fb",
        "metalness": 0.0,
        "roughness": 0.0,
        "transparent": True,
        "opacity": 0.08,
        "transmission": 0.98,
        "ior": 1.0,
        "thickness": 0.1,
    },
}


def material_catalog() -> dict[str, dict[str, object]]:
    """Return a copy of all material presets."""

    return deepcopy(MATERIAL_PRESETS)


def list_material_presets() -> list[str]:
    """Return available material preset keys in definition order."""

    return list(MATERIAL_PRESETS.keys())


def get_material_preset(name: str) -> dict[str, object]:
    """Return one material preset by name or raise ``KeyError``."""

    if name not in MATERIAL_PRESETS:
        raise KeyError(f"Unknown material preset '{name}'. Available: {', '.join(list_material_presets())}")
    return deepcopy(MATERIAL_PRESETS[name])