"""Compact on-chip blocks used by the preset chips.

These are the parts the preset layouts are drawn from: a wavelength-division
input, a delay spiral, a star coupler, a microring weight bank, and a balanced
photodetector, each drawn small enough that a whole processor fits in one
figure. The library has fuller versions of most of them; these stay because the
presets are laid out around their proportions.

They live here, and are registered, because a component that only exists inside
``presets.py`` cannot be rebuilt from a saved scene: picking such a preset in
the editor answered 500, and a saved copy would not reopen.
"""

from __future__ import annotations

from typing import Any

from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3
from optodraw.components.onchip import (
    _chip_line,
    _chip_polygon,
)
from optodraw.components.onchip.base import SILICON, SILICON_EDGE
from optodraw.components.onchip.geometry import _chip_extruded_polygon, _cut_footprints, _segment_outline
from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES

_WAVELENGTHS = ("#0072b2", "#009e73", "#e69f00")      # the 1D symbol's odw1, odw2, odw3
_SILICON_LIGHT = "#aac4df"                             # SILICON at 40% on white: the 2D combiner fill


class PresetChipComponent(Component):
    """Base class for compact on-chip components used only by presets."""

    chip_thickness: float = 0.22
    pdk: str = "generic"
    cross_section: str = "strip"

    def _init_chip(self, center=(0, 0), angle=0, **kwargs):
        """Initialize shared chip styling, transform, and metadata fields."""

        self.color = kwargs.get("color", "#7eb6e6")
        self.material_preset = kwargs.get("material_preset", "silicon")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "")
        self.chip_thickness = kwargs.get("chip_thickness", 0.22)
        self.pdk = kwargs.get("pdk", "generic")
        self.cross_section = kwargs.get("cross_section", "strip")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""


class WDMInput(PresetChipComponent):
    """Stylized wavelength-division input block for the WDM preset."""

    component_type = "PresetWDMInput"

    def __init__(self, center=(0, 0), angle=0, width=18.0, body_length=18.0, taper_length=10.0,
                 waveguide_width=SCHEMATIC_TABLES["_shared"]["waveguide_width"],    # as the on-chip parts draw it
                 wavelengths_nm=(1549.0, 1550.0, 1551.0), channel_powers=(1.0, 1.0, 1.0), **kwargs):
        self.width = width
        self.body_length = body_length
        self.taper_length = taper_length
        self.waveguide_width = waveguide_width
        self.wavelengths_nm = tuple(wavelengths_nm)
        self.channel_powers = tuple(channel_powers)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        """Return body plus taper length for placement and ports."""

        return self.body_length + self.taper_length

    def ports(self) -> dict[str, Port]:
        """Expose the single outgoing waveguide port."""

        return {
            "o1": Port("o1", Vec3(self.body_length / 2.0 + self.taper_length, 0, 0), orientation_deg=0, width=self.waveguide_width),
        }

    def _input_ys(self) -> tuple[float, float, float]:
        return (self.width * 0.3, 0.0, -self.width * 0.3)

    _DRAW_THICKNESS = 0.55                   # the 3D height of the on-chip parts' silicon beside it

    def _shapes(self) -> dict[str, Any]:
        """The 2D outlines: the funnel combiner, its output taper, and per wavelength a guide, its taper and an arrow."""

        half_body, w = self.body_length / 2.0, self.waveguide_width
        start = -half_body - self.body_length * 0.55
        flare = -half_body - self.body_length * 0.12
        funnel = [(-half_body, -self.width * 0.42), (half_body * 0.3, -self.width * 0.42), (half_body, -w * 1.2),
                  (half_body, w * 1.2), (half_body * 0.3, self.width * 0.42), (-half_body, self.width * 0.42)]
        inputs = []
        for y, colour in zip(self._input_ys(), _WAVELENGTHS):
            arrow_y = y + w * 1.6
            inputs.append({
                "colour": colour,
                "guide": _segment_outline((start, y), (flare, y), w, w),
                "taper": _segment_outline((flare, y), (-half_body, y), w, w * 2.4),
                "arrow": (start + 1.0, arrow_y, -half_body - 2.2, arrow_y),
                "head": [(-half_body - 2.6, arrow_y + 0.9), (-half_body - 1.2, arrow_y), (-half_body - 2.6, arrow_y - 0.9)],
            })
        output = _segment_outline((half_body, 0.0), (half_body + self.taper_length, 0.0), w * 2.4, w)
        return {"funnel": funnel, "output": output, "inputs": inputs}

    def geometry_2d(self) -> dict[str, Any]:
        """Three wavelengths, each on its own guide, into a silicon combiner that funnels to one output guide."""

        op, shapes = self.opacity, self._shapes()
        children = [
            _chip_polygon(shapes["funnel"], fill=SILICON, opacity=op * 0.3, stroke=SILICON_EDGE, stroke_width=0.1),
            _chip_polygon(shapes["output"], fill=SILICON, opacity=op, stroke=SILICON_EDGE, stroke_width=0.08),
        ]
        for item in shapes["inputs"]:
            children += [
                _chip_polygon(item["guide"], fill=SILICON, opacity=op, stroke=SILICON_EDGE, stroke_width=0.08),
                _chip_polygon(item["taper"], fill=SILICON, opacity=op, stroke=SILICON_EDGE, stroke_width=0.08),
                _chip_line(*item["arrow"], stroke=item["colour"], stroke_width=0.5, opacity=1.0),
                _chip_polygon(item["head"], fill=item["colour"], opacity=1.0, stroke="none", stroke_width=0.0),
            ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        """The 2D funnel as a shallow silicon slab, the three guides at full height, a coloured strip per wavelength."""

        t, shapes = self._DRAW_THICKNESS, self._shapes()
        children = [
            # opaque, in the light tint of the 2D fill: a translucent slab showed the room light and z-fought the die
            _chip_extruded_polygon(shapes["funnel"], t * 0.45, color=_SILICON_LIGHT, preset="silicon"),
            _chip_extruded_polygon(shapes["output"], t, color=SILICON, preset="silicon"),
        ]
        guides = [_chip_extruded_polygon(item[key], t, color=SILICON, preset="silicon")
                  for item in shapes["inputs"] for key in ("guide", "taper")]
        strips = []
        for item in shapes["inputs"]:
            x0, y, x1, _ = item["arrow"]
            strips += [_chip_extruded_polygon(_segment_outline((x0, y), (x1, y), 0.5, 0.5), t * 0.7, color=item["colour"]),
                       _chip_extruded_polygon(item["head"], t * 0.7, color=item["colour"])]
        # a strip is a legend, not a layer: it gives way where it crosses a guide
        return {"shape": "group", "children": [*children, *guides, *_cut_footprints(strips, guides)]}
