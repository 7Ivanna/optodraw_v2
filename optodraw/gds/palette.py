"""The one material table: the fill colour, the label and the metal flag of each material a stack names.

Sections, GDS views and the 3D context read their colours here. A stack may add or override a fill and a label
under its ``materials:`` block; those overrides are the optional ``overrides`` argument below.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Material:
    fill: str              # the section and GDS view colour
    label: str             # markup: SiO_2 sets a subscript
    metal: bool = False    # the engine stages metals after the films


MATERIALS: dict[str, Material] = {
    "silicon": Material("#9aa9bd", "Si"),
    "polysilicon": Material("#b6a8c9", "Poly-Si"),
    "sio2": Material("#e6eff7", "SiO_2"),
    "silicon_nitride": Material("#93c9a0", "SiN"),
    "germanium": Material("#c9a0d6", "Ge"),
    "aluminum": Material("#c3c8cf", "Al", metal=True),
    "copper": Material("#d08b5b", "Cu", metal=True),
    "tungsten": Material("#7d8590", "W", metal=True),
    "titanium_nitride": Material("#b08d57", "TiN", metal=True),
    "gold": Material("#e0b84f", "Au", metal=True),
    "lithium_niobate": Material("#d9b3e6", "LiNbO_3"),
    "lithium_tantalate": Material("#e6c3a1", "LiTaO_3"),
    "indium_phosphide": Material("#9fbcb5", "InP"),
    "ingaasp": Material("#e3a76f", "InGaAsP"),
    "ingaas": Material("#c9825a", "InGaAs"),
    "gallium_arsenide": Material("#a5c08f", "GaAs"),
    "aluminum_nitride": Material("#d4e0c1", "AlN"),
    "barium_titanate": Material("#e7a1a8", "BaTiO_3"),
    "indium_tin_oxide": Material("#bde3df", "ITO"),
    "silicon_carbide": Material("#7e9c8c", "SiC"),
    "platinum": Material("#a7aab0", "Pt", metal=True),
    "titanium": Material("#9b8f84", "Ti", metal=True),
    "nichrome": Material("#8c8580", "NiCr", metal=True),
    "metal": Material("#b0b5bc", "Metal", metal=True),
    "bcb": Material("#f2e3bd", "BCB"),
    "polyimide": Material("#efc27f", "Polyimide"),
    "sapphire": Material("#d2deef", "Sapphire"),
    "air": Material("#ffffff", "Air"),
}

# Other names for a material. styles.GDS_MATERIAL_ALIASES is this dict: material_preset_from_name reads a name it
# holds as a known 3D preset, so the identity entries stay.
ALIASES: dict[str, str] = {
    "si": "silicon",
    "silicon": "silicon",
    "handle": "silicon",
    "sio2": "sio2",
    "silica": "sio2",
    "silicon_dioxide": "sio2",
    "oxide": "sio2",
    "glass": "glass",
    "sin": "silicon_nitride",
    "silicon_nitride": "silicon_nitride",
    "aluminum": "aluminum",
    "aluminium": "aluminum",
    "al": "aluminum",
    "copper": "copper",
    "cu": "copper",
    "titanium": "titanium",
    "ti": "titanium",
    "tin": "titanium_nitride",
    "titanium_nitride": "titanium_nitride",
    "ge": "germanium",
    "germanium": "germanium",
    "inp": "indium_phosphide",
    "indium_phosphide": "indium_phosphide",
    "gaas": "gallium_arsenide",
    "gallium_arsenide": "gallium_arsenide",
    "ito": "indium_tin_oxide",
    "indium_tin_oxide": "indium_tin_oxide",
    "air": "air",
    "linbo3": "lithium_niobate",
    "litao3": "lithium_tantalate",
    "ingaasp": "ingaasp",
    "ingaas": "ingaas",
    "aln": "aluminum_nitride",
    "batio3": "barium_titanate",
    "bto": "barium_titanate",
    "sic": "silicon_carbide",
    "pt": "platinum",
}
DOPING = {"N": "#d9534f", "P": "#3d7cc9", "NPP": "#a52a2a", "PPP": "#1f4e8c"}
DOPING_NAMES = {"NPP": "N++", "PPP": "P++"}     # the textbook names of the heavy implants
UNKNOWN_FILL = "#d9d9d9"


def normal_name(name: object) -> str:
    """``name`` stripped and in lower case, with dashes and spaces as underscores."""

    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


def canonical(name: object) -> str:
    """The table key of ``name``: ``"LiNbO3"`` is ``"lithium_niobate"``. A name the table lacks stays as it is."""

    key = normal_name(name)
    return ALIASES.get(key, key)


def material_fill(name: object, overrides: dict[str, dict[str, str]] | None = None) -> str:
    """The fill colour of ``name``: the stack's own (``overrides``, keyed by table key), else the table's, else grey."""

    key = canonical(name)
    own = (overrides or {}).get(key, {}).get("fill")
    return own or (MATERIALS[key].fill if key in MATERIALS else UNKNOWN_FILL)


def material_label(name: object, overrides: dict[str, dict[str, str]] | None = None) -> str | None:
    """The label of ``name`` in markup, or None for a material that neither the stack nor the table knows."""

    key = canonical(name)
    own = (overrides or {}).get(key, {}).get("label")
    return own or (MATERIALS[key].label if key in MATERIALS else None)


def is_known(name: object, overrides: dict[str, dict[str, str]] | None = None) -> bool:
    """True when the table or the stack's ``materials:`` block names ``name``."""

    key = canonical(name)
    return key in MATERIALS or key in (overrides or {})


def is_metal(name: object) -> bool:
    found = MATERIALS.get(canonical(name))
    return bool(found and found.metal)


def doping_label(species: str) -> str:
    """The name a figure gives an implant: ``N++`` for the stack's ``NPP``."""

    return DOPING_NAMES.get(str(species).upper(), str(species))
