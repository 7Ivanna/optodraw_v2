"""Synthetic strip layouts for cross-section cuts without GDS."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from optodraw.gds.xsection.masks import IntervalSet, LayoutCut


@dataclass
class CrossSectionStripLayout:
    """Declare rectangular layout strips along the cut line."""

    strips: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    y_min: float = -2.0
    y_max: float = 2.0
    x: float = 0.0
    window: float = 4.0
    label: str = "strip"

    def strip(self, layer: str, *, width_um: float, center_y_um: float) -> CrossSectionStripLayout:
        if not math.isfinite(width_um) or width_um <= 0:
            raise ValueError("strip width_um must be positive and finite")
        if not math.isfinite(center_y_um):
            raise ValueError("strip center_y_um must be finite")
        half = width_um / 2.0
        self.strips.setdefault(layer, []).append((center_y_um - half, center_y_um + half))
        return self

    def span(self, y_min: float, y_max: float) -> CrossSectionStripLayout:
        if not math.isfinite(y_min) or not math.isfinite(y_max) or y_min >= y_max:
            raise ValueError("span requires finite bounds with y_min < y_max")
        self.y_min = float(y_min)
        self.y_max = float(y_max)
        return self

    def section(self, *, x: float = 0.0, window: float = 4.0, label: str = "strip") -> CrossSectionStripLayout:
        if not math.isfinite(x) or not math.isfinite(window) or window <= 0:
            raise ValueError("section x must be finite and window must be positive and finite")
        self.x = float(x)
        self.window = float(window)
        self.label = label
        return self

    def to_layout_cut(self) -> LayoutCut:
        layer_intervals = {
            name: IntervalSet.from_intervals(
                (max(y0, self.y_min), min(y1, self.y_max))
                for y0, y1 in values
                if y1 > self.y_min and y0 < self.y_max
            )
            for name, values in self.strips.items()
        }
        return LayoutCut.from_strips(
            layer_intervals,
            y_min=self.y_min,
            y_max=self.y_max,
            x=self.x,
            window=self.window,
            label=self.label,
        )
