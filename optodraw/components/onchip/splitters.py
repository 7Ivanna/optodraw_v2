"""Y-branch and directional coupler splitters."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec
from optodraw.core.transform import Vec3

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults, SILICON_EDGE
from optodraw.components.onchip.geometry import (
    _chip_box,
    _chip_extruded_polygon,
    _chip_polygon,
    _chip_segment_polygon,
    _chip_segment_slab,
    _cut_footprints,
    _polyline_outline,
    _segment_outline,
)

@dataclass
class YBranch(ChipComponent):
    component_type = "YBranch"
    schematic_family = "y_branch"
    branch_length: float = 9.0
    stem_length: float = 1.0
    waveguide_width: float = 0.5
    branch_gap: float | None = None
    branch_width: float = 0.8

    _REFERENCE_SEGMENT_WIDTHS = (0.5, 0.5, 0.6, 0.7, 0.9, 1.26, 1.4, 1.4, 1.4, 1.4, 1.31, 1.2, 1.2)

    def __init__(self, center=(0, 0), angle=0, branch_length=9.0, stem_length=1.0, waveguide_width: float | None = None, branch_gap: float | None = None, branch_width=0.8, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.branch_length = float(branch_length)
        self.stem_length = float(stem_length)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.branch_gap = branch_gap
        self.branch_width = float(branch_width)
        width_scale = self.waveguide_width / 0.5
        branch_scale = self.branch_length / 9.0 if self.branch_length > 0 else 1.0
        self.segment_widths = tuple(width * width_scale for width in self._REFERENCE_SEGMENT_WIDTHS)
        self.l_junction = 2.0 * branch_scale
        self.l_bend = 6.0 * branch_scale
        self.l_out = 1.0 * branch_scale
        self._junction_offset = (self.waveguide_width + 0.2 * width_scale) / 2.0
        default_gap = 2.0 * (self._junction_offset + 2.0 * branch_scale)
        self.output_offset = default_gap / 2.0 if branch_gap is None else float(branch_gap) / 2.0
        self.h_bend = max(self.output_offset - self._junction_offset, 0.0)
        self.branch_gap = self.output_offset * 2.0
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "branch_length": self.branch_length,
                "stem_length": self.stem_length,
                "waveguide_width": self.waveguide_width,
                "branch_gap": self.branch_gap,
                "branch_width": self.branch_width,
                "thickness": self.chip_thickness,
            },
        )

    def _draw_variant(self) -> YBranch:
        if self.render_physical:
            return self
        return YBranch(
            branch_length=self._draw("branch_length", self.branch_length),
            stem_length=self._draw("stem_length", self.stem_length),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            branch_gap=self._draw("branch_gap", self.branch_gap),
            branch_width=self._draw("branch_width", self.branch_width),
            **self._draw_variant_kwargs(),
        )

    @property
    def input_x(self) -> float:
        return -(self.stem_length / 2.0 + self.branch_length / 2.0)

    @property
    def split_x(self) -> float:
        return self.input_x + self.stem_length

    @property
    def junction_start_x(self) -> float:
        return self.split_x

    @property
    def junction_end_x(self) -> float:
        return self.junction_start_x + self.l_junction

    @property
    def bend_end_x(self) -> float:
        return self.junction_end_x + self.l_bend

    @property
    def output_x(self) -> float:
        return self.bend_end_x + self.l_out

    def _junction_polygon(self) -> list[tuple[float, float]]:
        if len(self.segment_widths) == 1:
            xs = [self.junction_start_x]
        else:
            step = self.l_junction / (len(self.segment_widths) - 1)
            xs = [self.junction_start_x + index * step for index in range(len(self.segment_widths))]
        top = [(x, width / 2.0) for x, width in zip(xs, self.segment_widths)]
        bottom = [(x, -width / 2.0) for x, width in reversed(list(zip(xs, self.segment_widths)))]
        return top + bottom

    def _output_centerline(self, sign: float) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        steps = 24
        start_y = sign * self._junction_offset
        end_y = sign * self.output_offset
        if self.l_bend <= 1e-9:
            points.append((self.junction_end_x, end_y))
        else:
            for index in range(steps + 1):
                t = index / steps
                x = self.junction_end_x + self.l_bend * t
                blend = 0.5 - 0.5 * math.cos(math.pi * t)
                y = start_y + (end_y - start_y) * blend
                points.append((x, y))
        points.append((self.output_x, end_y))
        return points

    def _branch_polygon(self, sign: float) -> list[tuple[float, float]]:
        return _polyline_outline(self._output_centerline(sign), self.waveguide_width)

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Animation paths on the DRAWN geometry: input stem through the junction,
        then each raised-cosine branch centerline at half power (or the reverse,
        combining, when light enters a branch)."""

        draw = self._draw_variant()
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        ports = self.ports()
        if in_port not in ports:
            return []
        stem = [[self.input_x, 0.0], [self.junction_start_x, 0.0], [self.junction_end_x, 0.0]]
        if in_port == "o1":
            paths = []
            for sign, port in ((1.0, "o2"), (-1.0, "o3")):
                branch = [list(p) for p in self._output_centerline(sign)]
                paths.append({
                    "port": port, "power": 0.5,
                    "pts": stem + branch,
                    "powers": [1.0] * len(stem) + [0.5] * len(branch),
                })
            return paths
        sign = 1.0 if in_port == "o2" else -1.0
        branch = [list(p) for p in self._output_centerline(sign)]
        return [{"port": "o1", "power": 0.97, "pts": branch[::-1] + stem[::-1]}]


    def ports(self) -> dict[str, Port]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        return {
            "o1": Port("o1", Vec3(self.input_x, 0, 0), orientation_deg=180, width=self.waveguide_width),
            "o2": Port("o2", Vec3(self.output_x, self.output_offset, 0), orientation_deg=0, width=self.waveguide_width),
            "o3": Port("o3", Vec3(self.output_x, -self.output_offset, 0), orientation_deg=0, width=self.waveguide_width),
        }

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()

        children = [
            _chip_segment_polygon(
                (self.input_x, 0.0),
                (self.junction_start_x, 0.0),
                self.waveguide_width,
                self.segment_widths[0],
                fill=self.color,
                opacity=self.opacity,
                stroke=SILICON_EDGE,
                stroke_width=0.08,
            ),
            _chip_polygon(
                self._junction_polygon(),
                fill=self.color,
                opacity=self.opacity,
                stroke=SILICON_EDGE,
                stroke_width=0.08,
            ),
            _chip_polygon(
                self._branch_polygon(1.0),
                fill=self.color,
                opacity=self.opacity,
                stroke=SILICON_EDGE,
                stroke_width=0.08,
            ),
            _chip_polygon(
                self._branch_polygon(-1.0),
                fill=self.color,
                opacity=self.opacity,
                stroke=SILICON_EDGE,
                stroke_width=0.08,
            ),
        ]
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()

        children = [
            _chip_segment_slab(
                (self.input_x, 0.0),
                (self.junction_start_x, 0.0),
                self.waveguide_width,
                self.segment_widths[0],
                self._draw_thickness(),
                **self._core(),
            ),
            _chip_extruded_polygon(
                self._junction_polygon(),
                self._draw_thickness(),
                **self._core(),
            ),
            _chip_extruded_polygon(
                self._branch_polygon(1.0),
                self._draw_thickness(),
                **self._core(),
            ),
            _chip_extruded_polygon(
                self._branch_polygon(-1.0),
                self._draw_thickness(),
                **self._core(),
            ),
        ]
        return self._on_the_stack(children)


@dataclass
class DirectionalCoupler(ChipComponent):
    component_type = "DirectionalCoupler"
    schematic_family = "directional_coupler"
    coupling_length: float = 7.0
    transition_length: float = 5.0
    straight_length: float = 0.0
    port_spacing: float = 4.0
    waveguide_gap: float = 0.2
    waveguide_width: float = 0.5
    coupling_ratio: float = 0.5

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        coupling_length: float = 7.0,
        transition_length: float = 5.0,
        straight_length: float = 0.0,
        port_spacing: float = 4.0,
        waveguide_gap: float | None = None,
        waveguide_width: float | None = None,
        coupling_ratio: float = 0.5,
        **kwargs,
    ):
        if not 0.0 <= float(coupling_ratio) <= 1.0:
            raise ValueError("coupling_ratio must be between 0 and 1")
        self.coupling_ratio = float(coupling_ratio)
        defaults = _generic_pdk_defaults()
        strip = defaults["strip"]
        ring = defaults["ring"]
        self.coupling_length = float(coupling_length)
        self.transition_length = float(transition_length)
        self.straight_length = float(straight_length)
        self.port_spacing = float(port_spacing)
        self.waveguide_gap = float(ring["gap"] if waveguide_gap is None else waveguide_gap)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "coupling_length": self.coupling_length,
                "transition_length": self.transition_length,
                "straight_length": self.straight_length,
                "total_length": self.total_length,
                "port_spacing": self.port_spacing,
                "waveguide_gap": self.waveguide_gap,
                "waveguide_width": self.waveguide_width,
                "thickness": self.chip_thickness,
            },
        )

    def anim_behaviors(self) -> list[dict]:
        return [
            {"key": "split", "label": "Split ratio (cross)", "options": [
                ["auto", "Design value"], ["0.5", "50 / 50"], ["0.25", "75 / 25"],
                ["0.1", "90 / 10"], ["0.01", "99 / 1"]]},
            {"key": "coupling", "label": "Transfer", "options": [
                ["auto", "Evanescent beat"], ["adiabatic", "Adiabatic (monotonic)"]]},
        ]

    def _draw_variant(self) -> DirectionalCoupler:
        if self.render_physical:
            return self
        return DirectionalCoupler(
            coupling_length=self._draw("coupling_length", self.coupling_length),
            transition_length=self._draw("transition_length", self.transition_length),
            straight_length=self._draw("straight_length", self.straight_length),
            port_spacing=self._draw("port_spacing", self.port_spacing),
            waveguide_gap=self._draw("waveguide_gap", self.waveguide_gap),
            waveguide_width=self._draw("waveguide_width", self.waveguide_width),
            coupling_ratio=self.coupling_ratio,
            **self._draw_variant_kwargs(),
        )

    @property
    def total_length(self) -> float:
        return self.coupling_length + 2.0 * self.transition_length + 2.0 * self.straight_length

    @property
    def coupling_spacing(self) -> float:
        return self.waveguide_gap + self.waveguide_width

    @property
    def body_height(self) -> float:
        return max(self.port_spacing, self.coupling_spacing + 1.8 * self.waveguide_width)

    def _centerline(self, sign: float) -> list[tuple[float, float]]:
        half_total = self.total_length / 2.0
        half_coupling = self.coupling_length / 2.0
        outer_y = sign * self.port_spacing / 2.0
        inner_y = sign * self.coupling_spacing / 2.0
        straight = max(self.straight_length, 0.0)
        # The raised-cosine bends start/end one transition away from the coupling
        # region; the straight access stubs run flat from the ports up to there.
        bend_start_x = -half_coupling - self.transition_length
        points = [(-half_total, outer_y)]

        if straight > 1e-9:
            points.append((bend_start_x, outer_y))  # straight input stub

        if self.transition_length > 1e-9:
            steps = 24
            for index in range(1, steps + 1):
                t = index / steps
                x = bend_start_x + self.transition_length * t
                blend = 0.5 - 0.5 * math.cos(math.pi * t)
                y = outer_y + (inner_y - outer_y) * blend
                points.append((x, y))
        else:
            points.append((-half_coupling, inner_y))

        if points[-1][0] < half_coupling - 1e-9:
            points.append((half_coupling, inner_y))

        if self.transition_length > 1e-9:
            steps = 24
            for index in range(1, steps + 1):
                t = index / steps
                x = half_coupling + self.transition_length * t
                blend = 0.5 - 0.5 * math.cos(math.pi * t)
                y = inner_y + (outer_y - inner_y) * blend
                points.append((x, y))
        else:
            points.append((half_coupling, outer_y))

        if abs(points[-1][0] - half_total) > 1e-9 or abs(points[-1][1] - outer_y) > 1e-9:
            points.append((half_total, outer_y))  # straight output stub
        return points

    def _polygon(self, sign: float) -> list[tuple[float, float]]:
        return _polyline_outline(self._centerline(sign), self.waveguide_width)

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Animation paths on the DRAWN centerlines: the bar arm keeps its rail, the
        cross arm hops rails at the coupling-region centre, and the power profile
        follows cos^2/sin^2 of the accumulated coupling phase — evanescent transfer
        exactly where the guides run closest."""

        draw = self._draw_variant()
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        ports = self.ports()
        if in_port not in ports:
            return []
        entry = ports[in_port]
        sign = 1.0 if float(entry.center.y) >= 0 else -1.0
        from_left = float(entry.center.x) < 0
        same = _densify(self._centerline(sign))
        other = _densify(self._centerline(-sign))
        if not from_left:
            same = same[::-1]
            other = other[::-1]
        params = getattr(self, "anim_params", None) or {}
        try:
            ratio = float(params.get("split", (self.physics_metadata() or {}).get("coupling_ratio", 0.5)))
        except Exception:
            ratio = 0.5
        ratio = min(max(ratio, 1e-4), 0.999)
        kappa_l = math.asin(math.sqrt(ratio))
        half_c = max(self.coupling_length / 2.0, 1e-6)

        def coupled_fraction(x: float) -> float:
            progress = (x + half_c) / (2 * half_c) if from_left else (half_c - x) / (2 * half_c)
            return min(max(progress, 0.0), 1.0)

        def region_start_index(centerline: list) -> int:
            for index, (x, _) in enumerate(centerline):
                if coupled_fraction(x) > 1e-6:
                    return max(index - 1, 0)
            return 0

        cross_pts = other[region_start_index(other):]
        lead = 0.0
        for i in range(len(same) - 1):
            if coupled_fraction(same[i + 1][0]) > 1e-6:
                break
            lead += math.dist(same[i], same[i + 1])
        exit_right = from_left

        def port_named(right: bool, s: float) -> str | None:
            for name, port in ports.items():
                if ((float(port.center.x) > 0) == right) and ((float(port.center.y) >= 0) == (s >= 0)):
                    return name
            return None

        paths = []
        bar_port = port_named(exit_right, sign)
        cross_port = port_named(exit_right, -sign)
        if bar_port:
            paths.append({
                "port": bar_port, "power": 1.0 - ratio,
                "pts": [list(p) for p in same],
                "powers": [math.cos(kappa_l * coupled_fraction(x)) ** 2 for x, _ in same],
            })
        if cross_port:
            paths.append({
                "port": cross_port, "power": ratio,
                "pts": [list(p) for p in cross_pts],
                "powers": [math.sin(kappa_l * coupled_fraction(x)) ** 2 for x, _ in cross_pts],
                "delay_len": round(lead, 4),
            })
        return paths

    def ports(self) -> dict[str, Port]:
        # Follow the drawn variant so ports sit on the drawn S-bend tips, not the
        # physical (compacted) coupling region.
        draw = self._draw_variant()
        if draw is not self:
            return draw.ports()
        half = self.total_length / 2.0
        dy = self.port_spacing / 2.0
        return {
            "o1": Port("o1", Vec3(-half, dy, 0), orientation_deg=180, width=self.waveguide_width),
            "o2": Port("o2", Vec3(-half, -dy, 0), orientation_deg=180, width=self.waveguide_width),
            "o3": Port("o3", Vec3(half, dy, 0), orientation_deg=0, width=self.waveguide_width),
            "o4": Port("o4", Vec3(half, -dy, 0), orientation_deg=0, width=self.waveguide_width),
        }

    def geometry_2d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_2d()

        return {
            "type": "group",
            "children": [
                _chip_box(0.0, 0.0, self.coupling_length, self.body_height, self.color, self.opacity * 0.16, stroke=SILICON_EDGE, stroke_width=0.05),
                _chip_polygon(self._polygon(1.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
                _chip_polygon(self._polygon(-1.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        draw = self._draw_variant()
        if draw is not self:
            return draw.geometry_3d()

        return self._on_the_stack([
                _chip_extruded_polygon(self._polygon(1.0), self._draw_thickness(), **self._core()),
                _chip_extruded_polygon(self._polygon(-1.0), self._draw_thickness(), **self._core()),
            ])

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "directional_coupler",
            "coupling_length": self.coupling_length,
            "coupling_ratio": self.coupling_ratio,
        }


def _coupler_arm(
    total_length: float,
    coupling_length: float,
    transition_length: float,
    outer_y: float,
    inner_y: float,
    *,
    straight: float = 0.0,
) -> list[tuple[float, float]]:
    """Raised-cosine S-bend access arm: ports at ``outer_y`` ease in to a parallel
    coupling region at ``inner_y`` and back out."""
    half_total = total_length / 2.0
    half_coupling = coupling_length / 2.0
    bend_start_x = -half_coupling - transition_length
    pts: list[tuple[float, float]] = [(-half_total, outer_y)]
    if straight > 1e-9:
        pts.append((bend_start_x, outer_y))
    steps = 24
    for i in range(1, steps + 1):
        t = i / steps
        blend = 0.5 - 0.5 * math.cos(math.pi * t)
        pts.append((bend_start_x + transition_length * t, outer_y + (inner_y - outer_y) * blend))
    pts.append((half_coupling, inner_y))
    for i in range(1, steps + 1):
        t = i / steps
        blend = 0.5 - 0.5 * math.cos(math.pi * t)
        pts.append((half_coupling + transition_length * t, inner_y + (outer_y - inner_y) * blend))
    if half_total - pts[-1][0] > 1e-9:                  # a repeated end point draws a flag at the end
        pts.append((half_total, outer_y))
    return pts


@dataclass
class TapCoupler(ChipComponent):
    """Asymmetric directional-coupler power tap (e.g. 1%/99%) — a straight bus with a
    short weakly-coupled drop waveguide for monitoring."""

    component_type = "TapCoupler"
    schematic_family = "tap_coupler"
    coupling_length: float = 8.0
    transition_length: float = 16.0
    port_spacing: float = 8.0
    waveguide_gap: float = 0.5
    waveguide_width: float = 0.5
    tap_ratio: float = 0.01

    # The tap arm rises (port_spacing - gap - width) over transition_length: about 7 over 16, a gentle bend.
    def __init__(self, center=(0, 0), angle=0, coupling_length=8.0, transition_length=16.0, port_spacing=8.0, waveguide_gap=0.5, waveguide_width: float | None = None, tap_ratio=0.01, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.coupling_length = float(coupling_length)
        self.transition_length = float(transition_length)
        self.port_spacing = float(port_spacing)
        self.waveguide_gap = float(waveguide_gap)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.tap_ratio = float(tap_ratio)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.coupling_length + 2.0 * self.transition_length

    def anim_behaviors(self) -> list[dict]:
        return [
            {"key": "split", "label": "Split ratio (cross)", "options": [
                ["auto", "Design value"], ["0.5", "50 / 50"], ["0.25", "75 / 25"],
                ["0.1", "90 / 10"], ["0.01", "99 / 1"]]},
            {"key": "coupling", "label": "Transfer", "options": [
                ["auto", "Evanescent beat"], ["adiabatic", "Adiabatic (monotonic)"]]},
        ]

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"coupling_length": self.coupling_length, "transition_length": self.transition_length, "total_length": self.total_length, "port_spacing": self.port_spacing, "tap_ratio": self.tap_ratio, "waveguide_width": self.waveguide_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        half = self.total_length / 2.0
        dy = self.port_spacing / 2.0
        w = self._draw("waveguide_width", self.waveguide_width)
        return {
            "o1": Port("o1", Vec3(-half, dy, 0), orientation_deg=180, width=w),   # bus in
            "o2": Port("o2", Vec3(half, dy, 0), orientation_deg=0, width=w),       # bus through
            "o3": Port("o3", Vec3(half, -dy, 0), orientation_deg=0, width=w),      # tap out
            "o4": Port("o4", Vec3(-half, -dy, 0), orientation_deg=180, width=w),   # tap add
        }

    def _bus(self) -> list[tuple[float, float]]:
        half = self.total_length / 2.0
        return [(-half, self.port_spacing / 2.0), (half, self.port_spacing / 2.0)]

    def _tap(self) -> list[tuple[float, float]]:
        inner = self.port_spacing / 2.0 - (self.waveguide_gap + self._draw("waveguide_width", self.waveguide_width))
        return _coupler_arm(self.total_length, self.coupling_length, self.transition_length, -self.port_spacing / 2.0, inner)

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Bus + tap arm animation on the DRAWN rails: the tap_ratio fraction hops
        to the tap arm across the coupling region (a 1% tap barely glows)."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        ratio = min(max(float(getattr(self, "tap_ratio", 0.01)), 1e-4), 0.999)
        return _two_rail_optical_paths(
            self, in_port, _sample_rail(self._bus()), self._tap(),
            ratio, self.coupling_length / 2.0,
        )


    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                _chip_polygon(_polyline_outline(self._bus(), self._draw("waveguide_width", self.waveguide_width)), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
                _chip_polygon(_polyline_outline(self._tap(), self._draw("waveguide_width", self.waveguide_width)), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        t = self._draw_thickness()
        core = self._core()
        return self._on_the_stack([
                _chip_extruded_polygon(_polyline_outline(self._bus(), self._draw("waveguide_width", self.waveguide_width)), t, **core),
                _chip_extruded_polygon(_polyline_outline(self._tap(), self._draw("waveguide_width", self.waveguide_width)), t, **core),
            ])

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "tap_coupler", "tap_ratio": self.tap_ratio, "coupling_ratio": self.tap_ratio}


@dataclass
class AdiabaticCoupler(ChipComponent):
    """Broadband adiabatic 3 dB coupler — two slightly mismatched waveguides brought
    parallel over a long interaction length for wavelength-insensitive 50:50 splitting."""

    component_type = "AdiabaticCoupler"
    schematic_family = "adiabatic_coupler"
    coupling_length: float = 30.0
    transition_length: float = 8.0
    port_spacing: float = 12.0
    waveguide_gap: float = 0.3
    waveguide_width: float = 0.5
    width_mismatch: float = 0.1

    def __init__(self, center=(0, 0), angle=0, coupling_length=30.0, transition_length=8.0, port_spacing=12.0, waveguide_gap=0.3, waveguide_width: float | None = None, width_mismatch=0.1, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.coupling_length = float(coupling_length)
        self.transition_length = float(transition_length)
        self.port_spacing = float(port_spacing)
        self.waveguide_gap = float(waveguide_gap)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.width_mismatch = float(width_mismatch)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.coupling_length + 2.0 * self.transition_length

    def anim_behaviors(self) -> list[dict]:
        return [
            {"key": "split", "label": "Split ratio (cross)", "options": [
                ["auto", "Design value"], ["0.5", "50 / 50"], ["0.25", "75 / 25"],
                ["0.1", "90 / 10"], ["0.01", "99 / 1"]]},
            {"key": "coupling", "label": "Transfer", "options": [
                ["auto", "Evanescent beat"], ["adiabatic", "Adiabatic (monotonic)"]]},
        ]

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"coupling_length": self.coupling_length, "transition_length": self.transition_length, "total_length": self.total_length, "port_spacing": self.port_spacing, "width_mismatch": self.width_mismatch, "waveguide_width": self.waveguide_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        half = self.total_length / 2.0
        dy = self.port_spacing / 2.0
        w = self._draw("waveguide_width", self.waveguide_width)
        return {
            "o1": Port("o1", Vec3(-half, dy, 0), orientation_deg=180, width=w),
            "o2": Port("o2", Vec3(-half, -dy, 0), orientation_deg=180, width=w),
            "o3": Port("o3", Vec3(half, dy, 0), orientation_deg=0, width=w),
            "o4": Port("o4", Vec3(half, -dy, 0), orientation_deg=0, width=w),
        }

    def _arm(self, sign: float) -> list[tuple[float, float]]:
        inner = sign * (self.waveguide_gap + self._draw("waveguide_width", self.waveguide_width)) / 2.0
        return _coupler_arm(self.total_length, self.coupling_length, self.transition_length, sign * self.port_spacing / 2.0, inner)

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Both drawn S-bend arms with the monotonic adiabatic transfer profile."""

        draw = self._draw_variant() if hasattr(self, "_draw_variant") else self
        if draw is not self:
            draw.anim_params = self.anim_params  # behaviours ride along
            return draw.optical_paths(in_port)
        return _two_rail_optical_paths(
            self, in_port, self._arm(1.0), self._arm(-1.0),
            0.5, self.coupling_length / 2.0, adiabatic=True,
        )


    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                _chip_box(0.0, 0.0, self.coupling_length, self.port_spacing, self.color, self.opacity * 0.14, stroke=SILICON_EDGE, stroke_width=0.05),
                _chip_polygon(_polyline_outline(self._arm(1.0), self._draw("waveguide_width", self.waveguide_width) + self.width_mismatch / 2.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
                _chip_polygon(_polyline_outline(self._arm(-1.0), self._draw("waveguide_width", self.waveguide_width) - self.width_mismatch / 2.0), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        t = self._draw_thickness()
        core = self._core()
        return self._on_the_stack([
                _chip_extruded_polygon(_polyline_outline(self._arm(1.0), self._draw("waveguide_width", self.waveguide_width) + self.width_mismatch / 2.0), t, **core),
                _chip_extruded_polygon(_polyline_outline(self._arm(-1.0), self._draw("waveguide_width", self.waveguide_width) - self.width_mismatch / 2.0), t, **core),
            ])

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "adiabatic_coupler", "coupling_ratio": 0.5}


@dataclass
class PolarizationRotator(ChipComponent):
    """Mode-evolution polarization rotator — an asymmetric (bi-level) waveguide that
    rotates TE↔TM. Drawn as a strip with an offset partial-etch rib that tapers across."""

    component_type = "PolarizationRotator"
    schematic_family = "polarization_rotator"
    length: float = 30.0
    width: float = 0.5
    rib_width: float = 0.25

    _RIB = "#7aa7dc"                                # the partially etched slab: a light tint of silicon

    def __init__(self, center=(0, 0), angle=0, length=30.0, width: float | None = None, rib_width=0.25, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.width = float(strip["width"] if width is None else width)
        self.rib_width = float(rib_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"length": self.length, "width": self.width, "rib_width": self.rib_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=self._draw("width", self.width)),
            "o2": Port("o2", Vec3(half, 0, 0), orientation_deg=0, width=self._draw("width", self.width)),
        }

    def _rib(self) -> list[tuple[float, float]]:
        """The partially etched slab on one side of the strip: it grows and shrinks again (bi-level taper)."""

        w, a = self._draw("width", self.width), self.length / 2.0 * 0.8
        lower = [(a - 2.0 * a * i / 40, -w / 2.0 - 3.4 * w * math.sin(math.pi * (1.0 - i / 40))) for i in range(41)]
        return [(-a, w / 2.0), (a, w / 2.0), *lower]

    def _strip(self) -> list[tuple[float, float]]:
        """The strip narrows and moves away from the slab where the slab is widest: the mode turns TE to TM."""

        w, half = self._draw("width", self.width), self.length / 2.0
        top, bottom = [], []
        for i in range(41):
            x, grow = -half + self.length * i / 40, math.sin(math.pi * i / 40)
            width, shift = w * (1.0 - 0.5 * grow), 0.45 * w * grow
            top.append((x, shift + width / 2.0))
            bottom.append((x, shift - width / 2.0))
        return top + bottom[::-1]

    def _centerline(self) -> list[list[float]]:
        """The middle of the drawn strip: it shifts sideways as the strip narrows (see ``_strip``)."""

        w, half = self._draw("width", self.width), self.length / 2.0
        return [[-half + self.length * i / 40, 0.45 * w * math.sin(math.pi * i / 40)] for i in range(41)]

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Along the drawn strip from one port to the other."""

        line = self._centerline()
        if in_port == "o1":
            return [{"port": "o2", "pts": line}]
        if in_port == "o2":
            return [{"port": "o1", "pts": line[::-1]}]
        return []

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [
                _chip_polygon(self._rib(), fill=self._RIB, opacity=self.opacity * 0.85, stroke=SILICON_EDGE, stroke_width=0.05),
                _chip_polygon(self._strip(), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        t = self._draw_thickness()
        preset = self._draw_material_preset()
        stack = self._draw_layer_stack()
        strip = _chip_extruded_polygon(self._strip(), t, **self._core())
        rib = _chip_extruded_polygon(self._rib(), stack["rib_height"], **self._slab(self._RIB, preset))
        return self._on_the_stack([*_cut_footprints([rib], [strip]), strip])     # the core owns its base

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "polarization_rotator", "mode": "polarization"}


@dataclass
class PolarizationSplitterRotator(ChipComponent):
    """Polarization splitter-rotator (PSR): one input is separated into a TE output and
    a rotated TM output — the workhorse of polarization-diversity receivers."""

    component_type = "PolarizationSplitterRotator"
    schematic_family = "polarization_splitter_rotator"
    length: float = 40.0
    port_spacing: float = 12.0
    waveguide_width: float = 0.5
    rotator_length: float = 12.0

    _RIB = "#7aa7dc"                                # the partially etched slab: a light tint of silicon

    def __init__(self, center=(0, 0), angle=0, length=40.0, port_spacing=12.0, waveguide_width: float | None = None, rotator_length=12.0, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.port_spacing = float(port_spacing)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.rotator_length = float(rotator_length)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"length": self.length, "port_spacing": self.port_spacing, "rotator_length": self.rotator_length, "waveguide_width": self.waveguide_width, "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        half = self.length / 2.0
        dy = self.port_spacing / 2.0
        w = self._draw("waveguide_width", self.waveguide_width)
        return {
            "o1": Port("o1", Vec3(-half, 0, 0), orientation_deg=180, width=w),    # input (TE+TM)
            "o2": Port("o2", Vec3(half, dy, 0), orientation_deg=0, width=w),       # TE out
            "o3": Port("o3", Vec3(half, -dy, 0), orientation_deg=0, width=w),      # TM out (rotated)
        }

    def _split_x(self) -> float:
        return -self.length / 2.0 + self.rotator_length

    def _output_arm(self, sign: float) -> list[tuple[float, float]]:
        x0 = self._split_x()
        half = self.length / 2.0
        end_y = sign * self.port_spacing / 2.0
        steps = 24
        pts = [(x0, 0.0)]
        span = half - x0
        for i in range(1, steps + 1):
            t = i / steps
            blend = 0.5 - 0.5 * math.cos(math.pi * t)
            pts.append((x0 + span * t, end_y * blend))
        return pts

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """The input stem to the split point, then the drawn arm: o2 above (TE), o3 below (TM, rotated)."""

        stem = [[-self.length / 2.0, 0.0], [self._split_x(), 0.0]]
        arms = {"o2": [list(p) for p in self._output_arm(1.0)], "o3": [list(p) for p in self._output_arm(-1.0)]}
        if in_port == "o1":
            return [{"port": port, "power": 0.5, "pts": stem + arm[1:]} for port, arm in arms.items()]
        if in_port in arms:
            return [{"port": "o1", "pts": arms[in_port][::-1] + stem[::-1][1:]}]
        return []

    def geometry_2d(self) -> dict[str, Any]:
        half = self.length / 2.0
        x0 = self._split_x()
        rib_off = self._draw("waveguide_width", self.waveguide_width) / 2.0
        return {
            "type": "group",
            "children": [
                _chip_segment_polygon((-half, 0.0), (x0, 0.0), self._draw("waveguide_width", self.waveguide_width), self._draw("waveguide_width", self.waveguide_width) * 1.4, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
                _chip_polygon(_segment_outline((-half, rib_off), (x0, -rib_off), self._draw("waveguide_width", self.waveguide_width) * 0.5, self._draw("waveguide_width", self.waveguide_width) * 0.5), fill=self._RIB, opacity=self.opacity, stroke="none", stroke_width=0.0),
                _chip_polygon(_polyline_outline(self._output_arm(1.0), self._draw("waveguide_width", self.waveguide_width)), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
                _chip_polygon(_polyline_outline(self._output_arm(-1.0), self._draw("waveguide_width", self.waveguide_width)), fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        t = self._draw_thickness()
        preset = self._draw_material_preset()
        stack = self._draw_layer_stack()
        half = self.length / 2.0
        x0 = self._split_x()
        rib_off = self._draw("waveguide_width", self.waveguide_width) / 2.0
        core = [
            _chip_segment_slab((-half, 0.0), (x0, 0.0), self._draw("waveguide_width", self.waveguide_width), self._draw("waveguide_width", self.waveguide_width) * 1.4, t, **self._core()),
            _chip_extruded_polygon(_polyline_outline(self._output_arm(1.0), self._draw("waveguide_width", self.waveguide_width)), t, **self._core()),
            _chip_extruded_polygon(_polyline_outline(self._output_arm(-1.0), self._draw("waveguide_width", self.waveguide_width)), t, **self._core()),
        ]
        # the partly etched section of the bi-level taper: the slab layer of the stack, on the same base; the core
        # owns the base where both are drawn
        rib = _chip_extruded_polygon(_segment_outline((-half, rib_off), (x0, -rib_off), self._draw("waveguide_width", self.waveguide_width) * 0.5, self._draw("waveguide_width", self.waveguide_width) * 0.5),
                                     stack["rib_height"], **self._slab(self._RIB, preset))
        return self._on_the_stack([core[0], *_cut_footprints([rib], core), *core[1:]])

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "polarization_splitter_rotator", "mode": "polarization"}


def _densify(points: list, max_step: float = 0.8) -> list:
    """Insert points on long straight legs so power profiles can localize
    (the coupling straight is drawn as ONE segment — a cos^2/sin^2 profile
    needs samples inside it)."""

    out = [list(points[0])]
    for a, b in zip(points, points[1:]):
        dist = math.dist(a, b)
        steps = max(int(dist / max_step), 1)
        for i in range(1, steps + 1):
            t = i / steps
            out.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
    return out


def _two_rail_optical_paths(
    node: Any,
    in_port: str,
    top_rail: list[tuple[float, float]],
    bottom_rail: list[tuple[float, float]],
    ratio: float,
    half_coupling: float,
    *,
    adiabatic: bool = False,
) -> list[dict[str, Any]]:
    """Shared two-rail coupler animation paths on the DRAWN centerlines.

    Bar keeps the entry rail; cross hops rails at the coupling centre. Power
    profiles follow cos^2/sin^2 of the accumulated coupling phase (or the
    monotonic adiabatic transfer)."""

    ports = node.ports()
    if in_port not in ports:
        return []
    entry = ports[in_port]
    sign = 1.0 if float(entry.center.y) >= 0 else -1.0
    from_left = float(entry.center.x) < 0
    same = _densify(top_rail if sign > 0 else bottom_rail)
    other = _densify(bottom_rail if sign > 0 else top_rail)
    if not from_left:
        same = same[::-1]
        other = other[::-1]
    node_params = getattr(node, "anim_params", None) or {}
    if "split" in node_params:
        try:
            ratio = float(node_params["split"])
        except (TypeError, ValueError):
            pass
    ratio = min(max(ratio, 1e-4), 0.999)
    kappa_l = math.asin(math.sqrt(ratio))
    half_c = max(half_coupling, 1e-6)

    def coupled_fraction(x: float) -> float:
        progress = (x + half_c) / (2 * half_c) if from_left else (half_c - x) / (2 * half_c)
        return min(max(progress, 0.0), 1.0)

    def cross_power(x: float) -> float:
        if adiabatic:
            return ratio * math.sin(0.5 * math.pi * coupled_fraction(x)) ** 2
        return math.sin(kappa_l * coupled_fraction(x)) ** 2

    # cross light GROWS on the neighbouring guide's own rail across the coupling
    # region (no geometric rail-hop — that's what evanescent coupling looks like);
    # delay_len offsets its start by the lead-in the light travelled on the bar.
    def region_start_index(centerline: list) -> int:
        for index, (x, _) in enumerate(centerline):
            if coupled_fraction(x) > 1e-6:
                return max(index - 1, 0)
        return 0

    cross_start = region_start_index(other)
    cross_pts = other[cross_start:]
    lead = 0.0
    for i in range(len(same) - 1):
        if coupled_fraction(same[i + 1][0]) > 1e-6:
            break
        lead += math.dist(same[i], same[i + 1])
    exit_right = from_left

    def port_named(right: bool, s: float) -> str | None:
        for name, port in ports.items():
            if ((float(port.center.x) > 0) == right) and ((float(port.center.y) >= 0) == (s >= 0)):
                return name
        return None

    paths = []
    bar_port = port_named(exit_right, sign)
    cross_port = port_named(exit_right, -sign)
    if bar_port:
        paths.append({
            "port": bar_port, "power": 1.0 - ratio,
            "pts": [list(p) for p in same],
            "powers": [1.0 - cross_power(x) for x, _ in same],
        })
    if cross_port:
        paths.append({
            "port": cross_port, "power": ratio,
            "pts": [list(p) for p in cross_pts],
            "powers": [cross_power(x) for x, _ in cross_pts],
            "delay_len": round(lead, 4),
        })
    return paths


def _sample_rail(rail: list[tuple[float, float]], steps: int = 24) -> list[tuple[float, float]]:
    """Resample a 2-point straight rail so power profiles can localize on it."""

    if len(rail) != 2:
        return list(rail)
    (x0, y0), (x1, y1) = rail
    return [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps) for i in range(steps + 1)]
