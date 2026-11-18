"""The vertical stack every on-chip part is built on.

All parts follow one open process, the GDSFactory generic stack (``gds/stacks/gdsfactory_generic.yaml``),
unless their scene sets a foundry stack. The numbers are kept here so a basic install (and the browser)
needs no YAML reader; a test checks them against the file. Heights are in um for a 220 nm core; a part
scales them to the core it draws.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PDK = "gdsfactory_generic.yaml"
DEFAULT_HEIGHTS = {
    "chip_thickness": 0.22,
    "core_z": 0.0, "core_height": 0.22,              # WG: the silicon core
    "rib_z": 0.0, "rib_height": 0.09,                # SLAB90: the residual slab, on the same base as the core
    "implant_z": 0.0, "implant_height": 0.09,        # the doping fills the slab
    "contact_z": 0.09, "contact_height": 1.01,       # VIAC: from the slab top to M1
    "metal_z": 1.1, "metal_height": 0.7,             # M1: electrodes and routing
    "heater_z": 1.1, "heater_height": 0.75,          # HEATER: titanium nitride, beside M1
    "pad_z": 3.2, "pad_height": 2.0,                 # M3: the pads
}


SCHEMATIC_RISE = 1.5   # a schematic part draws M1 this many core thicknesses above the buried oxide


@dataclass(frozen=True)
class StackCore:
    """What a foundry stack makes a part's core of (``LayerStackSpec.component_core``): the material of the core
    and of the slab it may stand on (keys of the material table), the fill of each from that table, and, in a film
    stack, the films over the core that the core etch patterns with it, as (bottom, thickness, material) in um.
    ``width`` is the stack's waveguide width in um: a part draws its guide that wide, so it sets the part's draw
    scale (None: the default scale). ``cladding`` is what covers the parts, as (bottom, top, material) in um: from
    the top of the lower cladding to the top of the fill.
    The levels of the core and the slab are in the component heights."""

    core: str = "silicon"
    slab: str = "silicon"
    over: tuple[tuple[float, float, str], ...] = ()
    fills: dict[str, str] = field(default_factory=dict)
    width: float | None = None
    cladding: tuple[float, float, str] | None = None


def component_stack(core: float, *, schematic: bool = False,
                    overrides: dict[str, float] | None = None) -> dict[str, float]:
    """Bottom and height of each layer for a part whose core is ``core`` thick: the default process, scaled to
    that core. A foundry stack (``overrides``, already scaled) replaces any of them.

    A schematic part is drawn narrow in plan, so the true oxide would lift its metal far above the waveguide.
    It keeps the same layers in the same order, with silicon at its true proportions, and compresses all
    above the slab so M1 sits ``SCHEMATIC_RISE`` core thicknesses up. The pads stay on top, above the rest, as
    plates as thick as M1."""

    factor = core / DEFAULT_HEIGHTS["chip_thickness"]
    stack = {key: value * factor for key, value in DEFAULT_HEIGHTS.items() if key != "chip_thickness"}
    supplied = overrides or {}
    if schematic and not supplied:
        top = stack["rib_z"] + stack["rib_height"]
        squeeze = (SCHEMATIC_RISE * core - top) / (stack["metal_z"] - top)
        for name in ("contact", "metal", "heater", "pad"):
            stack[name + "_z"] = top + (stack[name + "_z"] - top) * squeeze
            stack[name + "_height"] *= squeeze
        stack["pad_height"] = stack["metal_height"]        # a pad stays on top, as a plate: a thick one was a brick
    stack.update(supplied)
    if "contact_z" not in supplied:
        stack["contact_z"] = stack["rib_z"] + stack["rib_height"]
    if "metal_z" in supplied and not {"contact_height", "via_z"} & set(supplied):
        # a stack with a metal and no contact or via layer: the contact reaches the metal, as VIAC reaches M1
        stack["contact_height"] = stack["metal_z"] - stack["contact_z"]
    if "via_z" in supplied and "contact_height" not in supplied:
        stack["contact_height"] = stack["via_z"] - stack["contact_z"]
    if "metal_z" in supplied and "heater_z" not in supplied:      # a foundry metal with no heater: the heater on it
        stack["heater_z"], stack["heater_height"] = stack["metal_z"], stack["metal_height"]
    stack.setdefault("via_z", stack["contact_z"] + stack["contact_height"])
    stack.setdefault("via_height", max(stack["metal_z"] - stack["via_z"], 0.0))
    stack["slab_z"], stack["slab_height"] = stack["rib_z"], stack["rib_height"]
    for key, value in stack.items():
        if key.endswith("_height") and value < 0:
            raise ValueError(f"Invalid chip stack: {key} is negative; check contact, via and metal endpoints")
    return stack
