"""Drawing configuration for the animation engine."""

from __future__ import annotations

import math
import re
from dataclasses import KW_ONLY, asdict, dataclass, fields

from optodraw.core.beam import wavelength_to_hex

STYLE_NAMES = ("photons", "packets", "beam", "wave", "bits")
INFRARED_PALETTE = ((850.0, "#0072b2"), (1310.0, "#009e73"), (1550.0, "#e69f00"))


@dataclass(frozen=True)
class Style:
    name: str = "photons"
    _: KW_ONLY
    photons_per_power: float = 12.0
    dot_radius: float = 2.0
    beam_width: float = 2.0
    brightness: float = 1.0
    wave_scale: float = 1000.0
    polarisation: bool = False
    power_labels: bool = False
    infrared_palette: tuple = INFRARED_PALETTE

    def __post_init__(self):
        if self.name not in STYLE_NAMES:
            raise ValueError(f"unknown style: {self.name}")
        for name in ("photons_per_power", "dot_radius", "beam_width", "brightness", "wave_scale"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not isinstance(self.polarisation, bool) or not isinstance(self.power_labels, bool):
            raise ValueError("overlay options must be booleans")
        palette = tuple(tuple(item) for item in self.infrared_palette)
        if not palette:
            raise ValueError("infrared_palette must not be empty")
        anchors = set()
        for item in palette:
            if len(item) != 2:
                raise ValueError("invalid infrared_palette entry")
            wavelength, colour = item
            if (isinstance(wavelength, bool) or not isinstance(wavelength, (int, float))
                    or not math.isfinite(wavelength) or wavelength <= 780 or wavelength in anchors):
                raise ValueError("invalid infrared_palette wavelength")
            if not isinstance(colour, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", colour) is None:
                raise ValueError("invalid infrared_palette colour")
            anchors.add(wavelength)
        object.__setattr__(self, "infrared_palette", palette)

    def colour(self, wavelength_nm: float) -> str:
        if (isinstance(wavelength_nm, bool) or not isinstance(wavelength_nm, (int, float))
                or not math.isfinite(wavelength_nm) or wavelength_nm <= 0):
            raise ValueError("wavelength_nm must be positive and finite")
        if wavelength_nm <= 780:
            return wavelength_to_hex(wavelength_nm)
        return min(self.infrared_palette, key=lambda item: (abs(item[0] - wavelength_nm), item[0]))[1]

    def to_json(self) -> dict:
        data = asdict(self)
        data["infrared_palette"] = [list(item) for item in self.infrared_palette]
        return data

    @classmethod
    def from_json(cls, data: dict) -> Style:
        if not isinstance(data, dict) or set(data) - {field.name for field in fields(cls)}:
            raise ValueError("unknown style field")
        return cls(**data)


def resolve_style(value: str | Style) -> Style:
    return value if isinstance(value, Style) else Style(value)
