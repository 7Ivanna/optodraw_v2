"""System-level on-chip photonic primitives."""

from __future__ import annotations

from dataclasses import dataclass
import math
import warnings
from typing import Any

from optodraw.components.onchip.base import ChipComponent, _generic_pdk_defaults, SILICON_EDGE
from optodraw.components.onchip.geometry import (
    _chip_box,
    _chip_circle,
    _chip_extruded_polygon,
    _chip_fiber_3d_children,
    _chip_line,
    _chip_path_slab,
    _chip_polygon,
    _chip_polyline,
    _chip_segment_polygon,
    _chip_segment_slab,
    _chip_slab,
    _cut_footprints,
    _polyline_outline,
)
from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import PhysicalSpec
from optodraw.core.transform import Vec3


def _centered_offsets(count: int, pitch: float) -> list[float]:
    if count <= 0:
        return []
    origin = -0.5 * (count - 1) * pitch
    return [origin + index * pitch for index in range(count)]


def _side_orientation(side: str) -> float:
    return {"left": 180.0, "right": 0.0, "top": 90.0, "bottom": -90.0}[side]


@dataclass
class OpticalIOBank(ChipComponent):
    """Repeated optical I/O edge or grating coupler bank.

    Parameters
    ----------
    center : tuple[float, float]
        Bank center in physical microns.
    angle : float
        Rotation in degrees.
    count : int
        Number of optical channels.
    pitch : float
        Physical channel pitch in microns.
    coupler_kind : str
        ``"grating"``, ``"edge"``, or ``"fiber"`` visual style hint.
    side : str
        Local side where optical ports face: ``"left"``, ``"right"``, ``"top"``, or ``"bottom"``.
    stub_length : float
        Physical routing stub length for each channel.
    port_width : float
        Optical port width in microns.
    with_fibers : bool
        Add companion fiber ports and fiber markers to the bank.
    label : str
        Optional display label.
    """

    component_type = "OpticalIOBank"
    schematic_family = "optical_io_bank"
    count: int = 8
    pitch: float = 127.0
    coupler_kind: str = "grating"
    side: str = "left"
    stub_length: float = 18.0
    port_width: float = 0.5
    fiber_port_width: float = 10.0
    with_fibers: bool = False

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        count: int = 8,
        pitch: float = 127.0,
        coupler_kind: str = "grating",
        side: str = "left",
        stub_length: float = 18.0,
        port_width: float | None = None,
        fiber_port_width: float = 10.0,
        with_fibers: bool = False,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.count = int(count)
        if self.count < 1:
            raise ValueError("OpticalIOBank count must be at least 1")
        self.pitch = float(pitch)
        self.coupler_kind = str(coupler_kind).lower().replace("-", "_")
        if self.coupler_kind not in {"grating", "edge", "fiber"}:
            raise ValueError("coupler_kind must be one of: grating, edge, fiber")
        self.side = str(side).lower()
        if self.side not in {"left", "right", "top", "bottom"}:
            raise ValueError("side must be one of: left, right, top, bottom")
        self.stub_length = float(stub_length)
        self.port_width = float(strip["width"] if port_width is None else port_width)
        self.fiber_port_width = float(fiber_port_width)
        self.with_fibers = bool(with_fibers)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "count": self.count,
                "pitch": self.pitch,
                "stub_length": self.stub_length,
                "port_width": self.port_width,
                "fiber_port_width": self.fiber_port_width,
                "thickness": self.chip_thickness,
            },
        )

    @property
    def array_span(self) -> float:
        return (self.count - 1) * self.pitch

    def ports(self) -> dict[str, Port]:
        # Track the drawn bank: schematic pitch/stub (physical fiber pitch is far larger,
        # which would float the ports off the compacted drawing).
        ports: dict[str, Port] = {}
        orientation = _side_orientation(self.side)
        horizontal = self.side in {"left", "right"}
        sign = -1.0 if self.side in {"left", "bottom"} else 1.0
        pitch = self._draw("pitch", self.pitch)
        stub_length = self._draw("stub_length", self.stub_length)
        port_width = self._draw("port_width", self.port_width)
        coupler_w = self._draw("coupler_width", max(self.fiber_port_width, 12.0))
        coupler_l = self._draw("coupler_length", 24.0)
        fiber_distance = self._fiber_distance(stub_length, coupler_w, coupler_l)
        offsets = _centered_offsets(self.count, pitch)
        for index, offset in enumerate(offsets, start=1):
            if horizontal:
                center = Vec3(sign * stub_length / 2.0, offset, 0.0)
                fiber_center = Vec3(sign * fiber_distance, offset, 0.0)
            else:
                center = Vec3(offset, sign * stub_length / 2.0, 0.0)
                fiber_center = Vec3(offset, sign * fiber_distance, 0.0)
            ports[f"o{index}"] = Port(f"o{index}", center, orientation_deg=orientation, width=port_width)
            if self.with_fibers or self.coupler_kind == "fiber":
                ports[f"f{index}"] = Port(
                    f"f{index}",
                    fiber_center,
                    orientation_deg=orientation,
                    width=self.fiber_port_width,
                    kind="fiber",
                )
        return ports

    def _draw_axis(self) -> tuple[bool, float, float, list[float]]:
        horizontal = self.side in {"left", "right"}
        pitch = self._draw("pitch", self.pitch)
        stub_length = self._draw("stub_length", self.stub_length)
        offsets = _centered_offsets(self.count, pitch)
        sign = -1.0 if self.side in {"left", "bottom"} else 1.0
        return horizontal, sign, stub_length, offsets

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "iobank", {"count": int(self.count)}

    _OXIDE = "#d8eef7"

    def _coupler_shapes(self, offset: float, sign: float, horizontal: bool, stub_length: float, width: float,
                        coupler_w: float, coupler_l: float) -> list[tuple[str, list[tuple[float, float]]]]:
        """One coupler inside its coupler box: a grating coupler, or an edge coupler's inverse taper under oxide."""

        def at(u: float, v: float) -> tuple[float, float]:              # u outward from the bank, v across
            return (sign * u, offset + v) if horizontal else (offset + v, sign * u)

        def rect(u0: float, u1: float, half: float) -> list[tuple[float, float]]:
            return [at(u0, -half), at(u1, -half), at(u1, half), at(u0, half)]

        start, end, half_w = stub_length / 2.0, stub_length / 2.0 + coupler_l, coupler_w / 2.0
        if self.coupler_kind == "edge":
            tip = max(width * 0.25, 0.12)
            return [("silicon", [at(start, -width / 2.0), at(end, -tip / 2.0), at(end, tip / 2.0), at(start, width / 2.0)]),
                    ("oxide", rect(start + coupler_l * 0.25, end, half_w * 0.6))]
        grating = start + coupler_l * 0.4
        shapes = [("silicon", [at(start, -width / 2.0), at(grating, -half_w), at(grating, half_w), at(start, width / 2.0)]),
                  ("slab", rect(grating, end, half_w))]
        pitch = (end - grating) / 8
        shapes += [("tooth", rect(grating + pitch * (i + 0.3), grating + pitch * (i + 0.75), half_w)) for i in range(8)]
        return shapes

    def _fiber_distance(self, stub_length: float, coupler_w: float, coupler_l: float) -> float:
        """How far out from the bank a fibre sits: over the grating teeth (they run from 0.4 to 1.0 of the
        coupler), or at the facet beyond an edge coupler's tip, where a fibre butts against the chip."""

        if self.coupler_kind == "edge":
            return stub_length / 2.0 + coupler_l + coupler_w * 0.45
        return stub_length / 2.0 + coupler_l * 0.7

    def _fiber_center(self, offset: float, sign: float, horizontal: bool, stub_length: float, coupler_w: float,
                      coupler_l: float) -> tuple[float, float]:
        distance = sign * self._fiber_distance(stub_length, coupler_w, coupler_l)
        return (distance, offset) if horizontal else (offset, distance)

    def geometry_2d(self) -> dict[str, Any]:
        horizontal, sign, stub_length, offsets = self._draw_axis()
        width = self._draw("port_width", self.port_width)
        coupler_w = self._draw("coupler_width", max(self.fiber_port_width, 12.0))
        coupler_l = self._draw("coupler_length", 24.0)
        op = self.opacity
        style = {"silicon": dict(fill=self.color, opacity=op, stroke=SILICON_EDGE, stroke_width=0.08),
                 "slab": dict(fill=self.color, opacity=op * 0.42, stroke=SILICON_EDGE, stroke_width=0.08),
                 "tooth": dict(fill=self.color, opacity=op, stroke="none", stroke_width=0.0),
                 "oxide": dict(fill=self._OXIDE, opacity=op * 0.55, stroke="#8fb3c4", stroke_width=0.08)}
        children: list[dict[str, Any]] = []
        for offset in offsets:
            end = sign * stub_length / 2.0
            line = (0.0, offset, end, offset) if horizontal else (offset, 0.0, offset, end)
            children.append(_chip_line(*line, stroke=self.color, stroke_width=width, opacity=op))
            for role, points in self._coupler_shapes(offset, sign, horizontal, stub_length, width, coupler_w, coupler_l):
                children.append(_chip_polygon(points, **style[role]))
            if self.with_fibers or self.coupler_kind == "fiber":
                fx, fy = self._fiber_center(offset, sign, horizontal, stub_length, coupler_w, coupler_l)
                children.append(_chip_circle(fx, fy, coupler_w * 0.34, stroke="#5d8fb2", stroke_width=0.08, fill="#dff3ff", opacity=0.72))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        horizontal, sign, stub_length, offsets = self._draw_axis()
        width = self._draw("port_width", self.port_width)
        coupler_w = self._draw("coupler_width", max(self.fiber_port_width, 12.0))
        coupler_l = self._draw("coupler_length", 24.0)
        thickness, core = self._draw_thickness(), self._core()
        layer = {"silicon": (thickness, core),
                 "slab": (thickness * 0.5, core),     # shallow etch
                 "tooth": (thickness, core),
                 "oxide": (thickness * 1.8, {"color": self._OXIDE, "preset": "sio2"})}
        children: list[dict[str, Any]] = []
        for offset in offsets:
            if horizontal:
                children.append(_chip_slab(stub_length / 2.0, width, thickness, x=sign * stub_length / 4.0, y=offset, **core))
            else:
                children.append(_chip_slab(width, stub_length / 2.0, thickness, x=offset, y=sign * stub_length / 4.0, **core))
            for role, points in self._coupler_shapes(offset, sign, horizontal, stub_length, width, coupler_w, coupler_l):
                height, look = layer[role]
                children.append(_chip_extruded_polygon(points, height, **look))
            if self.with_fibers or self.coupler_kind == "fiber":
                fiber_x, fiber_y = self._fiber_center(offset, sign, horizontal, stub_length, coupler_w, coupler_l)
                cladding = coupler_w * 0.68                                  # the 2D disc
                if self.coupler_kind == "edge":                            # it lies on the chip, out from the facet
                    along_x = {"rotation": [0.0, 0.0, math.pi / 2.0]} if horizontal else {"rotation": [math.pi / 2.0, 0.0, 0.0]}
                    children.append({"shape": "cylinder", "radius": cladding / 2.0, "height": coupler_w,
                                     "position": [fiber_x, cladding / 2.0, -fiber_y], **along_x,
                                     "material": {"color": "#c9dceb", "opacity": 0.82, "transparent": True, "preset": "glass"}})
                else:                                                      # it stands over the teeth, as on a grating coupler
                    children.extend(_chip_fiber_3d_children(fiber_x, fiber_y, cladding, cladding * 0.42, 18.0,
                                                            base_height=core["z_offset"] + thickness))
        return self._on_the_stack(children)


class _Unset:
    """Sentinel: "the caller said nothing", which is not the same as a default."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unset>"


_UNSET = _Unset()


def _arch_ladder(entries, *, total_spread: float, aperture_width: float) -> list[list[tuple[float, float]]]:
    """Arrayed waveguides: straight out of the aperture, over the fan, and back.

    This is the Luceda SWaveguideArray shape, and the important part is where
    the delay lives. Each arm leaves its aperture along the aperture NORMAL as a
    straight section, climbs, caps over both aperture fans, and enters the
    mirrored aperture along its normal. **The straight climb carries the
    delay**, which is what makes the ladder adjustable without deforming the
    bends: Luceda's array passes ``delay_lengths=[delay_length * i for i in
    range(n_arms)]`` and implements them in the straights.

    Three earlier shapes were wrong, and each failed for its own reason.
    Pushing Bezier control points along the tangents cannot reach a constant
    ladder at all, because a control point may not cross the mirror plane and
    that cap binds hardest on the short inner arms. Letting every arm follow its
    own aperture normal into a long straight makes the outer normals sweep
    across the inner arms. Capping over at each arm's own height lets the short
    inner arms arch through the arc where their outer neighbours start, which
    crossed 14 arms of a 24 arm router at every tilt angle from 50 to 60
    degrees. Only a cap above the WHOLE fan is safe.

    The family cannot tangle when two things hold, and ``_fan_radius`` and the
    tilt floor exist to hold them: aperture ``|x|`` rises along the arc, so no
    two climbs meet, and aperture ``y`` rises along the arc, so no arm has to
    reach back over its own neighbours.

    ``total_spread`` is the whole ladder, so the step is
    ``total_spread / (arms - 1)``. Nesting outranks it: arms already differ in
    length at the lowest arch that clears the fan, and a step below that
    difference can only be met by pulling outer arms under their neighbours, so
    a request under the floor is clamped with a warning.
    """

    lead = max(aperture_width * 2.0, 4.0)      # dead straight off the aperture
    clearance = max(aperture_width * 2.0, 3.0)

    def bezier(q0, c1, c2, q3, steps=14):
        out = []
        for step in range(steps + 1):
            u = step / steps
            v = 1.0 - u
            out.append((v**3 * q0[0] + 3*v*v*u * c1[0] + 3*v*u*u * c2[0] + u**3 * q3[0],
                        v**3 * q0[1] + 3*v*v*u * c1[1] + 3*v*u*u * c2[1] + u**3 * q3[1]))
        return out

    def arm_path(p0, t0, p3, t3, top):
        """Straight off the aperture, turn, climb, cap over the fan, and mirror.

        Three rules make this family impossible to tangle, and all three are
        load bearing. Each arm climbs at its OWN aperture's x plus one lead, an
        order the arc fixes, so no two climbs can meet. Every cap crosses ABOVE
        the whole aperture fan, so no arm can arch through the place where
        another one starts: drop that and the short inner arms cap over at the
        height where their outer neighbours leave the arc, which by itself
        crossed 14 arms of a 24 arm router at every tilt from 50 to 60 degrees.
        And every control point stays inside the corridor the arm is crossing,
        so x never doubles back. An arm that leaves along +x cannot climb at the
        x it left from without turning back through itself first.

        ``top`` is the height of the cap, which is the only free length, so the
        delay lives in a straight section as Luceda's array implements it.
        """

        a0 = (p0[0] + lead * t0[0], p0[1] + lead * t0[1])
        a3 = (p3[0] + lead * t3[0], p3[1] + lead * t3[1])
        bx = a0[0] + lead                        # the climb, one lead further in
        b0, b3 = (bx, top), (-bx, top)

        # Clamped into [a0x, bx]. A reach that leaves the corridor swings the
        # turn sideways over the neighbouring arms before it points upward.
        cx_in = min(max(a0[0] + lead * t0[0], a0[0]), bx)
        cx_out = max(min(a3[0] + lead * t3[0], a3[0]), -bx)
        turn_in = bezier(a0, (cx_in, a0[1] + lead * abs(t0[1])),
                         (bx, top - lead), b0)
        turn_out = bezier(b3, (-bx, top - lead),
                          (cx_out, a3[1] + lead * abs(t3[1])), a3)
        cap_reach = abs(b3[0] - b0[0]) * 0.42
        cap = bezier(b0, (b0[0], b0[1] + cap_reach), (b3[0], b3[1] + cap_reach), b3)
        return [p0, a0] + turn_in + cap + turn_out + [a3, p3]

    def arc_length(pts):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))

    # Arc order, not distance to the mirror plane. On a coupler tilted far
    # enough |x| folds back, so sorting by it interleaves neighbouring
    # apertures and their arms cross. Arms nest when each arches over its
    # NEIGHBOUR ON THE ARC.
    ordered = list(entries)
    if len(ordered) > 1 and abs(ordered[0][0][0]) > abs(ordered[-1][0][0]):
        ordered.reverse()                        # shortest arm first
    count = max(len(ordered), 1)

    geometry = []
    for tip, tangent in ordered:
        norm = math.hypot(*tangent) or 1.0
        t0 = (tangent[0] / norm, tangent[1] / norm)
        geometry.append((tip, t0, (-tip[0], tip[1]), (-t0[0], t0[1])))

    # The floor every cap has to clear: the top of the aperture fan, both horns.
    fan_top = max(tip[1] + lead * t0[1] for tip, t0, _, _ in geometry) + clearance

    floors = [arc_length(arm_path(*g, fan_top)) for g in geometry]
    natural = max((b - a for a, b in zip(floors, floors[1:])), default=0.0)
    asked = total_spread / max(count - 1, 1) if count > 1 else 0.0
    delta = max(asked, natural * 1.02)
    if count > 1 and delta > asked + 1e-9:
        warnings.warn(
            f"arrayed-waveguide spread {total_spread:.1f} asks for a {asked:.2f} step "
            f"across {count} arms, but they already differ by {natural:.2f} at the "
            f"shortest arch that clears the aperture fan. Holding the step at "
            f"{delta:.2f}: below it the arms have to cross each other.",
            stacklevel=3)

    def solve(step: float):
        start = max(floor - index * step for index, floor in enumerate(floors))
        paths = []
        for index, (p0, t0, p3, t3) in enumerate(geometry):
            target = start + index * step
            lo, hi = fan_top, fan_top + 16.0
            for _ in range(60):                  # length grows with the climb
                if arc_length(arm_path(p0, t0, p3, t3, hi)) >= target:
                    break
                hi = fan_top + (hi - fan_top) * 1.7
            for _ in range(56):
                mid = (lo + hi) / 2.0
                if arc_length(arm_path(p0, t0, p3, t3, mid)) < target:
                    lo = mid
                else:
                    hi = mid
            paths.append(arm_path(p0, t0, p3, t3, (lo + hi) / 2.0))
        return paths

    # Nesting is checked, not assumed, and the apex is what to check: each arm
    # starts at its own aperture height, so equal straights give unequal peaks.
    for _ in range(14):
        arms = solve(delta)
        apexes = [max(point[1] for point in arm) for arm in arms]
        if all(b >= a - 1e-9 for a, b in zip(apexes, apexes[1:])):
            break
        delta *= 1.15
    return arms


def _arm_apex(arm) -> float:
    return max(point[1] for point in arm)


# A star coupler is a horn, and a horn has a mouth angle. Every array aperture
# has to point into the quadrant between the mirror plane and straight up, or
# the array stops coming off the arc in a fixed order and any ladder drawn
# between two such horns crosses itself. The fan is centred on the tilt, so the
# room it has is whichever side of the quadrant is nearer, and this is the
# fraction of that room it may use. Measured on the router, a 32 arm array left
# to fan freely opened to 124 degrees and crossed 27 arm pairs at every tilt.
FAN_HALF_ANGLE_FRACTION = 0.7

# Centre to centre of two array apertures on the arc, in drawing units. An
# aperture is about 1.8 wide and needs a gap beside it, so this is close to the
# tightest a star coupler can be drawn.
ARRAY_APERTURE_PITCH = 3.2

# Below this the two horns face each other head on, the array arc is no longer
# monotone in either axis, and no ladder of nested arms exists between them.
# Above the ceiling the flank apertures point back over the horn.
MIN_LADDER_TILT_DEG = 30.0
MAX_LADDER_TILT_DEG = 68.0


def _ladder_tilt(requested: float) -> float:
    """The tilt actually drawn, which is held inside the workable range.

    Every array aperture has to point into the quadrant between the mirror
    plane and straight up. Below the floor the two horns face each other and no
    nested ladder exists; above the ceiling the flank apertures point back over
    the horn, and an arm that leaves pointing away from the mirror plane can
    only reach it by doubling back through its own neighbours.
    """

    if requested > MAX_LADDER_TILT_DEG + 1e-9:
        warnings.warn(
            f"a tilt of {requested:.0f} degrees turns the star coupler flank apertures "
            f"back over the horn, and their arrayed waveguides then have to double back "
            f"to reach the other coupler. Holding the tilt at "
            f"{MAX_LADDER_TILT_DEG:.0f} degrees.",
            stacklevel=3)
        return MAX_LADDER_TILT_DEG
    if requested >= MIN_LADDER_TILT_DEG - 1e-9:
        return requested
    warnings.warn(
        f"a tilt of {requested:.0f} degrees turns the two star couplers to face each "
        f"other, and their arrayed waveguides then have to cross to reach a constant "
        f"delay ladder. Holding the tilt at {MIN_LADDER_TILT_DEG:.0f} degrees.",
        stacklevel=3)
    return MIN_LADDER_TILT_DEG


def _fan_half_angle(tilt_deg: float) -> float:
    """How wide a horn tilted this far may open, in radians."""

    return math.radians(FAN_HALF_ANGLE_FRACTION * min(tilt_deg, 90.0 - tilt_deg))


def _fan_radius(count: int, pitch: float, requested: float, tilt_deg: float,
                *, what: str = "array") -> float:
    """The focal radius an aperture fan needs, which is never smaller than asked.

    More apertures at a fixed pitch need a longer free propagation region, not a
    wider mouth. Returning ``requested`` unchanged whenever it already fits keeps
    every layout that was in range exactly where it was, which matters: growing a
    horn moves every port on it, and a floorplan built around those ports.
    """

    if count <= 1 or pitch <= 0.0:
        return requested
    half_span = _fan_half_angle(tilt_deg)
    needed = pitch * (count - 1) / 2.0 / half_span
    if needed <= requested + 1e-9:
        return requested
    warnings.warn(
        f"{count} {what} apertures at a {pitch:.2f} pitch open the star coupler to "
        f"{math.degrees(pitch * (count - 1) / 2.0 / requested):.0f} degrees, past the "
        f"{math.degrees(half_span):.0f} degree half angle a horn tilted "
        f"{tilt_deg:.0f} degrees can hold. Growing its focal radius from "
        f"{requested:.1f} to {needed:.1f}. Ask for a longer free propagation "
        f"region, or fewer apertures, to keep the size you set.",
        stacklevel=3)
    return needed


def _star_coupler_horn(
    *,
    radius: float,
    slab_length: float,
    array_count: int,
    dummy_count: int,
    array_pitch_angle: float,
    channel_count: int,
    channel_pitch_angle: float,
    aperture_width: float,
    waveguide_width: float,
    array_taper: float = 14.0,
    channel_taper: float = 16.0,
    place=None,
    rotate=None,
) -> dict[str, Any]:
    """One flared star coupler: the slab, its array apertures and its channels.

    A free propagation region is the same object wherever it appears, so it is
    built in one place. The AWG and the AWGR used to draw their own, which is
    why they looked like two different tools had made them: the router had
    flared horns with tapered apertures and the grating had a plain lens with
    waveguides butting onto the arc.

    Geometry, all in a local frame with the array arc on the left:
    - the array arc is centred at ``-slab_length/2`` and carries
      ``array_count`` apertures plus ``dummy_count`` dummies on each flank
    - the channel arc is centred at ``+slab_length/2`` and carries
      ``channel_count`` apertures
    - both arcs have the same ``radius``, which is what makes the slab a horn
      rather than a lens

    ``place`` maps a local point into the component frame and ``rotate`` maps a
    local direction, so a caller can tilt or mirror the whole coupler. Each
    aperture reports its ``tip`` and its outward ``tan``, because a port on an
    arc launches along its own normal, not along +x.
    """

    place = place or (lambda x, y: (x, y))
    rotate = rotate or (lambda ux, uy: (ux, uy))

    centre_array = -slab_length / 2.0
    centre_channel = slab_length / 2.0
    total_array = array_count + 2 * dummy_count

    array_half_span = ((total_array - 1) / 2.0) * array_pitch_angle
    channel_half_span = ((channel_count - 1) / 2.0) * channel_pitch_angle
    alpha_max = array_half_span + array_pitch_angle * 0.6
    # A 1xN multiplexer has one channel aperture, and a mouth of zero angle
    # collapses the slab to a triangle with a point where its input should be.
    # A free propagation region still has a face there, so give it one: a third
    # of the array mouth reads as the same device seen from its narrow end.
    beta_max = max(channel_half_span + channel_pitch_angle * 0.6, alpha_max / 3.0)

    # The slab: the channel arc, then the array arc, so the polygon closes.
    channel_arc = []
    for i in range(17):
        th = -beta_max + 2.0 * beta_max * (i / 16)
        channel_arc.append(place(centre_channel - radius * math.cos(th), radius * math.sin(th)))
    array_arc = []
    for i in range(25):
        th = alpha_max - 2.0 * alpha_max * (i / 24)
        array_arc.append(place(centre_array + radius * math.cos(th), radius * math.sin(th)))

    def aperture(base_x, base_y, ux, uy, taper, mouth, throat):
        tip_x, tip_y = base_x + taper * ux, base_y + taper * uy
        perp_x, perp_y = -uy, ux
        half_mouth, half_throat = mouth / 2.0, throat / 2.0
        return {
            "poly": [
                place(base_x + half_mouth * perp_x, base_y + half_mouth * perp_y),
                place(tip_x + half_throat * perp_x, tip_y + half_throat * perp_y),
                place(tip_x - half_throat * perp_x, tip_y - half_throat * perp_y),
                place(base_x - half_mouth * perp_x, base_y - half_mouth * perp_y),
            ],
            "tip": place(tip_x, tip_y),
            "tan": rotate(ux, uy),
        }

    array, dummies = [], []
    for idx in range(total_array):
        th = array_half_span - idx * array_pitch_angle
        base_x, base_y = centre_array + radius * math.cos(th), radius * math.sin(th)
        is_dummy = idx < dummy_count or idx >= array_count + dummy_count
        entry = aperture(
            base_x, base_y, math.cos(th), math.sin(th),
            array_taper * (0.45 if is_dummy else 1.0),
            aperture_width,
            aperture_width * 0.6 if is_dummy else waveguide_width,
        )
        entry["is_dummy"] = is_dummy
        (dummies if is_dummy else array).append(entry)

    channels = []
    for k in range(channel_count):
        th = channel_half_span - k * channel_pitch_angle
        base_x, base_y = centre_channel - radius * math.cos(th), radius * math.sin(th)
        channels.append(aperture(
            base_x, base_y, -math.cos(th), math.sin(th),
            channel_taper, aperture_width * 0.85, waveguide_width,
        ))

    return {"slab": channel_arc + array_arc, "array": array, "dummies": dummies, "channels": channels}


@dataclass
class StarCoupler(ChipComponent):
    """Multi-input/multi-output Rowland-style Star Coupler / Free Propagation Region (FPR).

    Based on the foundry-enabled Rowland & Confocal star coupler architectures
    (e.g., Luceda IPKISS).

    Features:
    - Flared sector horn slab (Rowland circle free propagation region)
    - Input channel apertures on the focal circle arc
    - Array apertures on the grating circle arc with adiabatic widening tapers
    - Dummy aperture stubs on both flanks of the grating arc (matching physical layouts)
    - Ports: i1..iN on the channel side, o1..oM on the array side
    """

    component_type = "StarCoupler"
    schematic_family = "star_coupler"
    input_count: int = 1
    output_count: int = 8
    dummy_count: int = 2
    slab_length: float = 60.0
    slab_width: float = 80.0
    port_spacing: float = 12.0
    port_spacing_in: float = 8.0
    port_spacing_out: float = 4.5
    aperture_width: float = 1.8
    waveguide_width: float = 0.5
    taper_length: float = 14.0
    mounting: str = "rowland"

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        input_count: int = 1,
        output_count: int = 8,
        dummy_count: int = 2,
        slab_length: float = 60.0,
        slab_width: float = 80.0,
        port_spacing: float | None = None,
        port_spacing_in: float | None = None,
        port_spacing_out: float | None = None,
        aperture_width: float = 1.8,
        waveguide_width: float | None = None,
        taper_length: float = 14.0,
        mounting: str = "rowland",
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.input_count = int(input_count)
        self.output_count = int(output_count)
        self.dummy_count = int(dummy_count)
        if self.input_count < 1 or self.output_count < 1:
            raise ValueError("StarCoupler input_count and output_count must be at least 1")
        self.slab_length = float(slab_length)
        self.slab_width = float(slab_width)
        default_pitch = float(port_spacing if port_spacing is not None else 8.0)
        self.port_spacing = default_pitch
        self.port_spacing_in = float(port_spacing_in if port_spacing_in is not None else default_pitch)
        self.port_spacing_out = float(port_spacing_out if port_spacing_out is not None else max(default_pitch * 0.5, 3.2))
        self.aperture_width = float(aperture_width)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.taper_length = float(taper_length)
        self.mounting = mounting
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "input_count": self.input_count,
                "output_count": self.output_count,
                "dummy_count": self.dummy_count,
                "slab_length": self.slab_length,
                "slab_width": self.slab_width,
                "port_spacing": self.port_spacing,
                "port_spacing_in": self.port_spacing_in,
                "port_spacing_out": self.port_spacing_out,
                "waveguide_width": self.waveguide_width,
                "thickness": self.chip_thickness,
            },
        )

    def _star_layout(self) -> tuple[list[tuple[float, float]], list, list, list]:
        if self.render_physical:
            R = self.slab_length
            slab_width = self.slab_width
        else:
            R = self._draw("slab_length", self.slab_length) * self.slab_length / type(self).slab_length
            slab_width = self._draw("slab_width", self.slab_width) * self.slab_width / type(self).slab_width
        d_focal = R * 0.82
        c_left = d_focal / 2.0
        c_right = -d_focal / 2.0

        total_arr = self.output_count + 2 * self.dummy_count
        step_in = self.port_spacing_in / R if self.input_count > 1 else 0.0
        step_arr = self.port_spacing_out / R if total_arr > 1 else 0.0

        inputs = []
        for k in range(self.input_count):
            beta = ((self.input_count - 1) / 2.0 - k) * step_in
            bx = c_left - R * math.cos(beta)
            by = R * math.sin(beta)
            ux, uy = -math.cos(beta), math.sin(beta)
            tx = bx + self.taper_length * ux
            ty = by + self.taper_length * uy
            inputs.append(((bx, by), (tx, ty), math.degrees(math.atan2(uy, ux))))

        outputs = []
        dummies = []
        for idx in range(total_arr):
            alpha = ((total_arr - 1) / 2.0 - idx) * step_arr
            bx = c_right + R * math.cos(alpha)
            by = R * math.sin(alpha)
            ux, uy = math.cos(alpha), math.sin(alpha)
            is_dummy = (idx < self.dummy_count) or (idx >= self.output_count + self.dummy_count)
            stub = self.taper_length * 0.45 if is_dummy else self.taper_length
            tx = bx + stub * ux
            ty = by + stub * uy
            entry = ((bx, by), (tx, ty), math.degrees(math.atan2(uy, ux)))
            if is_dummy:
                dummies.append(entry)
            else:
                outputs.append(entry)

        half_width_angle = math.asin(min(max(slab_width / max(2.0 * R, 1e-9), 0.0), 0.95))
        beta_max = max(((self.input_count - 1) / 2.0 + 0.65) * step_in, half_width_angle)
        alpha_max = max(((total_arr - 1) / 2.0 + 0.65) * step_arr, half_width_angle)
        seg = 18
        horn_poly = []
        for i in range(seg + 1):
            t = -beta_max + 2.0 * beta_max * (i / seg)
            horn_poly.append((c_left - R * math.cos(t), R * math.sin(t)))
        for i in range(seg + 1):
            t = alpha_max - 2.0 * alpha_max * (i / seg)
            horn_poly.append((c_right + R * math.cos(t), R * math.sin(t)))

        return horn_poly, inputs, outputs, dummies

    def ports(self) -> dict[str, Port]:
        _poly, inputs, outputs, _dummies = self._star_layout()
        w = self._draw("waveguide_width", self.waveguide_width)
        ports = {}
        for idx, (_b, tip, orient) in enumerate(inputs, start=1):
            ports[f"i{idx}"] = Port(f"i{idx}", Vec3(tip[0], tip[1], 0.0), orientation_deg=orient, width=w)
        for idx, (_b, tip, orient) in enumerate(outputs, start=1):
            ports[f"o{idx}"] = Port(f"o{idx}", Vec3(tip[0], tip[1], 0.0), orientation_deg=orient, width=w)
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "star", {"inputs": int(self.input_count), "outputs": int(self.output_count), "pitch": 0.3}

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Follow the input taper, fan across the slab, then follow the output taper.

        The slab outline is the multimode region: the light crosses it from aperture to aperture."""
        poly, inputs, outputs, _dummies = self._star_layout()
        ins = {f"i{i+1}": entry for i, entry in enumerate(inputs)}
        outs = {f"o{i+1}": entry for i, entry in enumerate(outputs)}
        source, destinations = (ins, outs) if in_port in ins else (outs, ins)
        if in_port not in source:
            return []
        aperture, tip, _angle = source[in_port]
        region = {"kind": "slab", "outline": [list(point) for point in poly]}
        return [{"port": name, "pts": [tip, aperture, end[0], end[1]], "region": region}
                for name, end in destinations.items()]

    def geometry_2d(self) -> dict[str, Any]:
        poly, inputs, outputs, dummies = self._star_layout()
        w = self._draw("waveguide_width", self.waveguide_width)
        ap_w = self._draw("aperture_width", self.aperture_width)
        color = self.color
        stroke = "#263238"
        children = [
            _chip_polygon(poly, fill=color, opacity=self.opacity * 0.92, stroke=stroke, stroke_width=0.12)
        ]
        for bnd, tip, _o in inputs:
            children.append(_chip_segment_polygon(bnd, tip, ap_w, w, fill=color, opacity=self.opacity * 0.92, stroke="none"))
        for bnd, tip, _o in outputs:
            children.append(_chip_segment_polygon(bnd, tip, ap_w, w, fill=color, opacity=self.opacity * 0.92, stroke="none"))
        for bnd, tip, _o in dummies:
            children.append(_chip_segment_polygon(bnd, tip, ap_w, w, fill=color, opacity=self.opacity * 0.92, stroke="none"))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        poly, inputs, outputs, dummies = self._star_layout()
        thickness = self._draw_thickness()
        w = self._draw("waveguide_width", self.waveguide_width)
        ap_w = self._draw("aperture_width", self.aperture_width)
        children = [
            _chip_extruded_polygon(poly, thickness * 0.75, **self._core(), opacity=self.opacity * 0.75)
        ]
        for bnd, tip, _o in inputs + outputs + dummies:
            children.append(_chip_segment_slab(
                bnd, tip, ap_w, w, thickness,
                **self._core(),
            ))
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "star_coupler",
            "input_count": self.input_count,
            "output_count": self.output_count,
            "dummy_count": self.dummy_count,
            "mounting": self.mounting,
        }


def _bend_to(start, leave, goal, radius: float, steps: int = 10) -> list[tuple[float, float]]:
    """Points after ``start`` of a circular bend of ``radius`` that turns the unit direction ``leave`` into ``goal``."""

    turn = math.atan2(leave[0] * goal[1] - leave[1] * goal[0], leave[0] * goal[0] + leave[1] * goal[1])
    if abs(turn) < 1e-9:
        return []
    side = math.copysign(1.0, turn)
    cx, cy = start[0] - side * radius * leave[1], start[1] + side * radius * leave[0]
    rx, ry = start[0] - cx, start[1] - cy
    return [(cx + rx * math.cos(turn * k / steps) - ry * math.sin(turn * k / steps),
             cy + rx * math.sin(turn * k / steps) + ry * math.cos(turn * k / steps)) for k in range(1, steps + 1)]


@dataclass
class AWG(ChipComponent):
    """Arrayed-waveguide grating demultiplexer schematic.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in physical microns.
    angle : float
        Rotation in degrees.
    channel_count : int
        Number of output wavelength channels.
    array_count : int
        Number of arrayed waveguides drawn between the two slab regions.
    channel_spacing : float
        Physical output channel pitch in microns.
    slab_length : float
        Physical length of each free-propagation slab in microns.
    slab_width : float
        Physical width of each free-propagation slab in microns.
    array_length : float
        Physical distance between slab regions in microns.
    free_spectral_range_nm : float
        Free spectral range metadata in nanometers.
    channel_spacing_nm : float
        Nominal wavelength spacing between output channels in nanometers.
    center_wavelength_nm : float
        Center wavelength metadata for the AWG passband.
    waveguide_width : float
        Optical waveguide and port width in microns. Defaults to the generic strip width.
    label : str
        Optional display label.
    """

    component_type = "AWG"
    schematic_family = "awg"
    channel_count: int = 8
    array_count: int = 16
    channel_spacing: float = 12.0
    slab_length: float = 90.0
    slab_width: float = 120.0
    array_length: float = 180.0
    free_spectral_range_nm: float = 20.0
    channel_spacing_nm: float = 0.8
    center_wavelength_nm: float = 1550.0
    waveguide_width: float = 0.5

    def __init__(self, center=(0, 0), angle=0, channel_count: int = 8, array_count: int = 16, channel_spacing=_UNSET, slab_length=_UNSET, slab_width=_UNSET, array_length=_UNSET, free_spectral_range_nm: float = 20.0, channel_spacing_nm: float = 0.8, center_wavelength_nm: float = 1550.0, waveguide_width: float | None = None, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.channel_count = int(channel_count)
        self.array_count = int(array_count)
        if self.channel_count < 1 or self.array_count < 2:
            raise ValueError("AWG channel_count must be >= 1 and array_count must be >= 2")
        # A dimension the caller passes must reach the drawing. The schematic
        # table is a family default, not an override: it used to replace all
        # four of these, so a mux asking for an 18 um slab and a demux asking
        # for 16 both drew the table's 42 and came out identical.
        asked = {
            "channel_spacing": channel_spacing,
            "slab_length": slab_length,
            "slab_width": slab_width,
            "array_length": array_length,
        }
        self._dim_overrides = {key: float(value) for key, value in asked.items() if value is not _UNSET}
        self.channel_spacing = float(12.0 if channel_spacing is _UNSET else channel_spacing)
        self.slab_length = float(90.0 if slab_length is _UNSET else slab_length)
        self.slab_width = float(120.0 if slab_width is _UNSET else slab_width)
        self.array_length = float(180.0 if array_length is _UNSET else array_length)
        # The couplers lean toward each other so the arms leave along their
        # aperture normals instead of turning through 90 degrees at the face.
        self.tilt_deg = float(kwargs.pop("tilt_deg", 45.0))
        self.free_spectral_range_nm = float(free_spectral_range_nm)
        self.channel_spacing_nm = float(channel_spacing_nm)
        self.center_wavelength_nm = float(center_wavelength_nm)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return 2.0 * self.slab_length + self.array_length

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "channel_count": self.channel_count,
                "array_count": self.array_count,
                "channel_spacing": self.channel_spacing,
                "slab_length": self.slab_length,
                "slab_width": self.slab_width,
                "array_length": self.array_length,
                "center_wavelength_nm": self.center_wavelength_nm,
                "channel_spacing_nm": self.channel_spacing_nm,
                "free_spectral_range_nm": self.free_spectral_range_nm,
                "waveguide_width": self.waveguide_width,
                "thickness": self.chip_thickness,
            },
        )

    def _awg_layout(self) -> tuple:
        """A 1xN arrayed-waveguide grating, built the way the router is.

        Two tilted flared star couplers face each other across the arrayed
        waveguides: one channel on the input coupler, ``channel_count`` on the
        output. Rotating the whole component 180 degrees turns the 1xN demux
        into an Nx1 mux, which is how the mux is drawn.

        The couplers come from ``_star_coupler_horn`` and the arms from
        ``_arch_ladder``, both shared with the AWGR, so a mux, a demux and a
        router drawn on one chip look like one device family. The AWG used to
        draw a plain lens with waveguides butted onto the arc and an arm bundle
        whose lengths were monotonic but arbitrary.

        Returns ``(in_slab, out_slab, input_wg, output_wgs, arms, apertures)``.
        """

        slab_l = self._draw("slab_length", self.slab_length)
        slab_w = self._draw("slab_width", self.slab_width)
        array_l = self._draw("array_length", self.array_length)
        pitch = self._draw("channel_spacing", self.channel_spacing)
        aperture_w = self._draw("aperture_width", getattr(self, "aperture_width", 1.8))
        wg_w = self._draw("waveguide_width", self.waveguide_width)

        # Radius from the slab the caller asked for: the arc spans the slab
        # width over the slab length, the same confocal relation the router uses.
        arms_drawn = max(min(self.array_count, 24), 2)
        tilt_deg = _ladder_tilt(self.tilt_deg)
        radius = _fan_radius(arms_drawn + 2, ARRAY_APERTURE_PITCH / 1.35,
                             max(slab_l, 1.0), tilt_deg) * 1.35
        tilt = math.radians(tilt_deg)

        # Aperture pitches as ANGLES on the arc. channel_spacing is a pitch on
        # the focal arc, not a routing pitch, so it is clamped: past about 60
        # degrees of focal arc a star coupler stops reading as a horn.
        def arc_step(spacing: float, count: int) -> float:
            if count <= 1:
                return 0.0
            step = spacing / radius
            span = (count - 1) * step
            return step * min(1.0, math.radians(60.0) / span) if span > 0 else step

        channel_step = arc_step(pitch, self.channel_count)
        array_step = ARRAY_APERTURE_PITCH / radius

        cos_t, sin_t = math.cos(tilt), math.sin(tilt)

        # How wide the horn really is, once tilted. Guessing this from
        # slab_length put the two couplers 50 units apart when each was 50 wide,
        # so they nearly touched and the arms had to climb a tall narrow spike
        # to make up the delay ladder. Build one at the origin and measure it.
        probe = _star_coupler_horn(
            radius=radius, slab_length=slab_l,
            array_count=arms_drawn, dummy_count=1, array_pitch_angle=array_step,
            channel_count=max(self.channel_count, 1), channel_pitch_angle=channel_step,
            aperture_width=aperture_w, waveguide_width=wg_w,
            array_taper=max(radius * 0.16, 3.0), channel_taper=max(radius * 0.20, 4.0),
            place=lambda x, y: (x * math.cos(tilt) - y * math.sin(tilt),
                                x * math.sin(tilt) + y * math.cos(tilt)),
        )
        probe_xs = [pt[0] for pt in probe["slab"]] + [a["tip"][0] for a in probe["array"]]
        horn_width = max(probe_xs) - min(probe_xs)
        separation = horn_width + max(array_l, slab_l)

        centre_x, centre_y = -separation / 2.0, 0.0

        def place_in(x, y):
            return (centre_x + x * cos_t - y * sin_t, centre_y + x * sin_t + y * cos_t)

        def rotate_in(ux, uy):
            return (ux * cos_t - uy * sin_t, ux * sin_t + uy * cos_t)

        in_horn = _star_coupler_horn(
            radius=radius, slab_length=slab_l,
            array_count=arms_drawn, dummy_count=1, array_pitch_angle=array_step,
            channel_count=1, channel_pitch_angle=0.0,
            aperture_width=aperture_w, waveguide_width=wg_w,
            array_taper=max(radius * 0.16, 3.0), channel_taper=max(radius * 0.20, 4.0),
            place=place_in, rotate=rotate_in,
        )
        out_horn = _star_coupler_horn(
            radius=radius, slab_length=slab_l,
            array_count=arms_drawn, dummy_count=1, array_pitch_angle=array_step,
            channel_count=self.channel_count, channel_pitch_angle=channel_step,
            aperture_width=aperture_w, waveguide_width=wg_w,
            array_taper=max(radius * 0.16, 3.0), channel_taper=max(radius * 0.20, 4.0),
            place=lambda x, y: (-place_in(x, y)[0], place_in(x, y)[1]),
            rotate=lambda ux, uy: (-rotate_in(ux, uy)[0], rotate_in(ux, uy)[1]),
        )

        channel = in_horn["channels"][0]
        mouth = channel["poly"]
        # The input bends from its aperture's tilt into the bus direction (-x), where its port faces: a guide that
        # stopped at the tilt met every bus at a corner. 10 um is the router's own bend radius.
        input_wg = [((mouth[0][0] + mouth[3][0]) / 2.0, (mouth[0][1] + mouth[3][1]) / 2.0), channel["tip"],
                    *_bend_to(channel["tip"], channel["tan"], (-1.0, 0.0), radius=10.0)]

        output_wgs = []
        for channel in out_horn["channels"]:
            tan = channel["tan"]
            mouth_out = channel["poly"]
            arc_pt = ((mouth_out[0][0] + mouth_out[3][0]) / 2.0, (mouth_out[0][1] + mouth_out[3][1]) / 2.0)
            output_wgs.append((arc_pt, channel["tip"], math.degrees(math.atan2(tan[1], tan[0]))))
        # Channel 1 at the bottom, channel N at the top. The builder walks the
        # arc downwards, and the router shares it, so the fan is ordered here.
        output_wgs.sort(key=lambda entry: entry[1][1])

        # The arms end on the mirror image of their own aperture, which is what
        # the shared ladder assumes, so the two couplers must be mirror images.
        entries = [(a["tip"], a["tan"]) for a in in_horn["array"]]
        arms = _arch_ladder(entries, total_spread=max(slab_w, radius), aperture_width=aperture_w)

        apertures = (in_horn["array"] + in_horn["dummies"] + in_horn["channels"]
                     + out_horn["array"] + out_horn["dummies"] + out_horn["channels"])

        # Centre the drawn body on the component origin. The couplers are built
        # about their own centres and then tilted, which walks the whole device
        # off the origin: placing one at center=(x, y) would not put it there,
        # and a floorplan computed by arithmetic would be wrong everywhere.
        drawn = list(in_horn["slab"]) + list(out_horn["slab"]) + [pt for arm in arms for pt in arm]
        xs = [point[0] for point in drawn]
        # x from the drawn body, y from the PORTS. This is a device you route
        # into, so placing it at center=(x, y) has to put its waveguides at that
        # y; the array arches to one side, which would otherwise drag the whole
        # thing down and leave the ports along the bottom edge.
        # The optical axis: the single input aperture, which the centre output
        # channel already shares. Putting that on y=0 is what makes
        # center=(x, y) mean what a floorplan expects. The fan itself is not
        # mirror symmetric about the axis, and cannot be: the channels are
        # evenly spaced along a TILTED arc, so their projection onto y is not
        # even. The router has the same property.
        # y=0 is the input aperture, NOT the middle of the drawing. A 1xN part
        # is placed at the height of the bus that feeds it, so anchoring the
        # single input port is what a caller can actually use. The arm bundle
        # then sits above the placement point, which is fine: Scene reads a
        # component's real box rather than assuming one centred on its origin.
        shift_x = -(min(xs) + max(xs)) / 2.0
        shift_y = -input_wg[-1][1]

        def move(point):
            return (point[0] + shift_x, point[1] + shift_y)

        in_slab = [move(pt) for pt in in_horn["slab"]]
        out_slab = [move(pt) for pt in out_horn["slab"]]
        arms = [[move(pt) for pt in arm] for arm in arms]
        input_wg = [move(point) for point in input_wg]
        output_wgs = [(move(arc), move(tip), orient) for arc, tip, orient in output_wgs]
        apertures = [
            {**a, "poly": [move(pt) for pt in a["poly"]], "tip": move(a["tip"])}
            for a in apertures
        ]
        return in_slab, out_slab, input_wg, output_wgs, arms, apertures

    def ports(self) -> dict[str, Port]:
        _il, _ol, input_wg, output_wgs, _arms, _apertures = self._awg_layout()
        w = self._draw("waveguide_width", self.waveguide_width)
        tip = input_wg[-1]
        ports = {"i1": Port("i1", Vec3(tip[0], tip[1], 0.0), orientation_deg=180, width=w)}
        for index, (_arc, otip, orient) in enumerate(output_wgs, start=1):
            # Outputs sit on a Rowland arc, so each one launches along its own
            # normal. Forcing 0 here sends every router waveguide out of the
            # free-propagation region at the wrong angle.
            ports[f"o{index}"] = Port(f"o{index}", Vec3(otip[0], otip[1], 0.0), orientation_deg=orient, width=w)
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "awg", {"inputs": 1, "outputs": int(self.channel_count), "arms": 7, "pitch": 0.3}

    def optical_paths(self, in_port: str) -> list[dict[str, Any]]:
        """Input guide, across the input slab, along the middle arrayed waveguide, across the output slab,
        out along the channel guide (reversed when light enters a channel).

        The middle arm stands for the whole array. Both slab outlines are the path's regions."""

        in_slab, out_slab, input_wg, output_wgs, arms, apertures = self._awg_layout()
        if in_port != "i1" and not (in_port.startswith("o") and in_port[1:].isdigit()
                                    and 1 <= int(in_port[1:]) <= len(output_wgs)):
            return []
        arm = [list(point) for point in arms[len(arms) // 2]]

        def mouth(aperture):
            return [(aperture["poly"][0][0] + aperture["poly"][3][0]) / 2.0,
                    (aperture["poly"][0][1] + aperture["poly"][3][1]) / 2.0]

        def aperture_at(point):
            return min((a for a in apertures if not a.get("is_dummy")), key=lambda a: math.dist(a["tip"], point))

        first, last = aperture_at(arm[0]), aperture_at(arm[-1])
        regions = [{"kind": "slab", "outline": [list(point) for point in slab]} for slab in (in_slab, out_slab)]

        def through(channel):
            arc, tip, _orient = output_wgs[channel]
            return ([list(point) for point in reversed(input_wg)] + [mouth(first)] + arm
                    + [mouth(last), list(arc), list(tip)])

        if in_port == "i1":
            return [{"port": f"o{k + 1}", "pts": through(k), "region": regions} for k in range(len(output_wgs))]
        return [{"port": "i1", "pts": through(int(in_port[1:]) - 1)[::-1], "region": regions}]

    def geometry_2d(self) -> dict[str, Any]:
        in_lens, out_lens, input_wg, output_wgs, arms, apertures = self._awg_layout()
        w = self._draw("waveguide_width", self.waveguide_width)
        # FPR slabs first (under); the waveguides terminate ON their arcs and are drawn on
        # top so they visibly meet the slab edge (no extension into it).
        children: list[dict[str, Any]] = [
            _chip_polygon(in_lens, fill="#7fb3d5", opacity=self.opacity * 0.5, stroke="#2f6f94", stroke_width=0.1),
            _chip_polygon(out_lens, fill="#7fb3d5", opacity=self.opacity * 0.5, stroke="#2f6f94", stroke_width=0.1),
        ]
        for arm in arms:
            children.append(_chip_polyline(arm, self.color, w * 0.85, self.opacity * 0.9))
        children.append(_chip_polyline(input_wg, self.color, w, self.opacity))
        for aperture in apertures:
            children.append(_chip_polygon(aperture["poly"], fill=self.color,
                                          opacity=self.opacity * (0.55 if aperture.get("is_dummy") else 0.95),
                                          stroke=SILICON_EDGE, stroke_width=0.07))
        for arc, tip, _o in output_wgs:
            children.append(_chip_segment_polygon(arc, tip, w * 1.5, w, fill=self.color, opacity=self.opacity, stroke=SILICON_EDGE, stroke_width=0.07, segments=8))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        in_lens, out_lens, input_wg, output_wgs, arms, apertures = self._awg_layout()
        thickness = self._draw_thickness()
        w = self._draw("waveguide_width", self.waveguide_width)
        guides: list[dict[str, Any]] = []
        for arm in arms:
            guides.append(_chip_path_slab(arm, w, thickness, **self._core()))
        guides.append(_chip_path_slab(input_wg, w, thickness, **self._core()))
        for arc, tip, _o in output_wgs:
            guides.append(_chip_path_slab([arc, tip], w, thickness, **self._core()))
        horns = [_chip_extruded_polygon(aperture["poly"], thickness, **self._core(),
                                        opacity=self.opacity * (0.55 if aperture.get("is_dummy") else 0.95))
                 for aperture in apertures]
        children = [
            *_cut_footprints(guides, horns),             # an arm ends where its aperture starts: one piece on each patch
            _chip_extruded_polygon(in_lens, thickness * 0.72, **self._core("#7fb3d5", "silicon_nitride"), opacity=self.opacity * 0.72),
            _chip_extruded_polygon(out_lens, thickness * 0.72, **self._core("#7fb3d5", "silicon_nitride"), opacity=self.opacity * 0.72),
            *horns,
        ]
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "arrayed_waveguide_grating",
            "channel_count": self.channel_count,
            "array_count": self.array_count,
            "center_wavelength_nm": self.center_wavelength_nm,
            "channel_spacing_nm": self.channel_spacing_nm,
            "free_spectral_range_nm": self.free_spectral_range_nm,
        }


@dataclass
class AWGR(ChipComponent):
    """N x N Arrayed-Waveguide Grating Router (AWGR).

    Drawn after the Rowland and Luceda cyclic router architectures:
    - Confocal/Rowland flared sector horn star couplers with dummy apertures
    - A phased array whose arms grow by a CONSTANT length increment
    - Tilted optical mountings matching physical GDS implementations
    - Cyclic all-to-all wavelength routing

    ``array_height`` is the total length spread across the array, so the
    per-arm increment is ``array_height / (array_count - 1)``. The arms are
    solved to hit that ladder: each one clears its aperture along the aperture
    normal, arches over, and descends into its mirror image, with the arch
    height solved so the length lands on the ladder.

    What this does NOT give you: the ladder is geometrically constant, and that
    is all. The free spectral range depends on the increment AND the group
    index AND the star coupler geometry, and optodraw models none of the
    optics. Take the optical design from a licensed AWG toolbox and use this to
    draw it.

    ``fpr_width`` is carried for the physical spec and is not used by the
    drawing. ``AWGR.fit_fpr`` sizes a width against a channel spacing, so it
    does not apply here either; the drawing scale comes from ``fpr_length`` and
    ``fpr_separation``, which must clear ``AWGR.min_fpr_separation``.
    """

    component_type = "AWGR"
    schematic_family = "awgr"
    channel_count: int = 4
    array_count: int = 16
    dummy_count: int = 3
    channel_spacing: float = 14.0
    fpr_length: float = 34.0
    fpr_width: float = 50.0
    fpr_separation: float = 120.0
    array_height: float = 70.0
    tilt_deg: float = 45.0
    free_spectral_range_nm: float = 12.8
    channel_spacing_nm: float = 1.6
    center_wavelength_nm: float = 1550.0
    waveguide_width: float = 0.5
    aperture_width: float = 1.8

    def __init__(
        self,
        center=(0, 0),
        angle=0,
        channel_count: int = 4,
        array_count: int = 16,
        dummy_count: int = 3,
        channel_spacing: float = 14.0,
        fpr_length: float = 34.0,
        fpr_width: float = 50.0,
        fpr_separation: float = 120.0,
        array_height: float = 70.0,
        tilt_deg: float = 45.0,
        free_spectral_range_nm: float = 12.8,
        channel_spacing_nm: float = 1.6,
        center_wavelength_nm: float = 1550.0,
        waveguide_width: float | None = None,
        aperture_width: float = 1.8,
        **kwargs,
    ):
        strip = _generic_pdk_defaults()["strip"]
        self.channel_count = int(channel_count)
        self.array_count = int(array_count)
        self.dummy_count = int(dummy_count)
        if self.channel_count < 1 or self.array_count < 2:
            raise ValueError("AWGR channel_count must be >= 1 and array_count must be >= 2")
        self.channel_spacing = float(channel_spacing)
        self.fpr_length = float(fpr_length)
        self.fpr_width = float(fpr_width)
        self.fpr_separation = float(fpr_separation)
        _min_sep = AWGR.min_fpr_separation(self.fpr_length)
        if self.fpr_separation < _min_sep:
            warnings.warn(
                f"AWGR fpr_separation={self.fpr_separation:.1f} is below the "
                f"minimum {_min_sep:.1f} for fpr_length={self.fpr_length:.1f}: "
                "the two FPR array faces would overlap and the arrayed "
                "waveguides would be drawn inside out. Clamping. Use "
                "AWGR.min_fpr_separation(fpr_length) to size it.",
                stacklevel=2)
            self.fpr_separation = _min_sep
        self.array_height = float(array_height)
        # A star coupler is a flared horn. channel_spacing is an APERTURE pitch
        # on the focal arc, not a post-fanout waveguide pitch: a foundry AWG
        # uses a few um here and fans out wider afterwards. Too
        # large a value opens the focal arc past 180 degrees and the coupler
        # renders as a blob instead of a horn.
        _R = self.fpr_length * 1.35
        _span = 2.0 * (((self.channel_count - 1) / 2.0 + 0.6)
                       * (self.channel_spacing * 0.75) / _R)
        _max = math.radians(60.0)
        if self.channel_count > 1 and _span > _max:
            _ok = _max / (2.0 * ((self.channel_count - 1) / 2.0 + 0.6)) * _R / 0.75
            warnings.warn(
                f"AWGR channel_spacing={self.channel_spacing:.1f} opens the focal "
                f"arc to {math.degrees(_span):.0f} deg for fpr_length="
                f"{self.fpr_length:.1f}; a star coupler needs under 60. Clamping "
                f"to {_ok:.1f}. This is an aperture pitch, not a routing pitch: "
                "fan the waveguides out after the coupler.",
                stacklevel=2)
            self.channel_spacing = _ok
        self.tilt_deg = float(tilt_deg)
        self.free_spectral_range_nm = float(free_spectral_range_nm)
        self.channel_spacing_nm = float(channel_spacing_nm)
        self.center_wavelength_nm = float(center_wavelength_nm)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.aperture_width = float(aperture_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.fpr_separation + 2.0 * self.fpr_length

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "channel_count": self.channel_count,
                "array_count": self.array_count,
                "dummy_count": self.dummy_count,
                "channel_spacing": self.channel_spacing,
                "fpr_length": self.fpr_length,
                "fpr_width": self.fpr_width,
                "fpr_separation": self.fpr_separation,
                "array_height": self.array_height,
                "tilt_deg": self.tilt_deg,
                "center_wavelength_nm": self.center_wavelength_nm,
                "channel_spacing_nm": self.channel_spacing_nm,
                "free_spectral_range_nm": self.free_spectral_range_nm,
                "waveguide_width": self.waveguide_width,
                "thickness": self.chip_thickness,
            },
        )

    @staticmethod
    def min_fpr_separation(fpr_length: float, fpr_width: float | None = None,
                           array_count: int = 16, dummy_count: int = 3,
                           margin: float = 20.0) -> float:
        """Smallest FPR separation that keeps the two array faces apart.

        The array apertures sit at local x = c_arr + R + taper, which works out
        at 0.875*fpr_length + 14. ``rot_in`` then shifts them by
        -fpr_separation/2. If that leaves the INPUT face at positive x the two
        free propagation regions interpenetrate, the arms are asked to run from
        right to left, and the phased array comes out inside out.
        """
        face = 0.875 * float(fpr_length) + 14.0
        return 2.0 * face + float(margin)

    @staticmethod
    def fit_fpr(
        channel_count: int,
        channel_spacing: float,
        fpr_length: float = 34.0,
        margin: float = 0.82,
    ) -> dict[str, float]:
        """Size a free-propagation-region width so a channel spacing fits its arc.

        NOT used by the AWGR drawing, and it cannot be without inventing a scale
        relationship that does not exist: the drawing takes its size from
        ``fpr_length`` and ``fpr_separation``, while ``fpr_width`` only reaches
        the physical spec. Deriving the drawing radius from ``fpr_width`` was
        tried and collapsed both couplers into one blob, because the default
        width of 50 um is unrelated to the drawing scale. The returned
        ``port_y`` is an untilted local value and does not match the drawn
        ports, which carry ``tilt_deg`` as well.

        Use it to reason about a real device. Do not expect it to move the
        picture.
        """

        need = (channel_count - 1) / 2.0 * float(channel_spacing)
        width = max(2.0 * need, 1.0)
        for _ in range(200):
            phi = math.atan2(fpr_length / 2.0, width / 2.0)
            radius = (width / 2.0) / max(math.sin(phi), 1e-9)
            if need <= margin * phi * radius:
                break
            width *= 1.05
        phi = math.atan2(fpr_length / 2.0, width / 2.0)
        radius = (width / 2.0) / max(math.sin(phi), 1e-9)
        step = float(channel_spacing) / radius
        ys = [
            radius * math.sin(((channel_count - 1) / 2.0 - k) * step)
            for k in range(channel_count)
        ]
        return {
            "fpr_length": float(fpr_length),
            "fpr_width": round(width, 2),
            "channel_spacing": float(channel_spacing),
            "port_y": [round(y, 2) for y in ys],
        }

    def _awgr_layout(self) -> tuple:
        total_arr = self.array_count + 2 * self.dummy_count
        tilt_deg = _ladder_tilt(self.tilt_deg)
        # Both fans, not just the array one. An unbounded channel mouth was a
        # documented trap: a 30 um channel spacing opened the focal arc to 167
        # degrees and the star coupler drew as a blob instead of a horn.
        fpr = self._draw("fpr_length", self.fpr_length)
        fpr = _fan_radius(total_arr, ARRAY_APERTURE_PITCH / 1.35, fpr, tilt_deg)
        fpr = _fan_radius(self.channel_count, self.channel_spacing * 0.75 / 1.35,
                          fpr, tilt_deg, what="channel")
        R = fpr * 1.35
        L_slab = fpr * 0.95
        tilt = math.radians(tilt_deg)
        h_apex = self._draw("array_height", self.array_height)

        cy_in = -10.0
        c_arr = -L_slab / 2.0
        c_focal = L_slab / 2.0

        ang_step_arr = ARRAY_APERTURE_PITCH / R
        ang_step_in = (self.channel_spacing * 0.75) / R if self.channel_count > 1 else 0.0

        arr_half_span = ((total_arr - 1) / 2.0) * ang_step_arr
        in_half_span = ((self.channel_count - 1) / 2.0) * ang_step_in

        cos_w = math.cos(tilt)
        sin_w = math.sin(tilt)

        alpha_max = arr_half_span + ang_step_arr * 0.6
        beta_max = in_half_span + ang_step_in * 0.6

        # How far the horn reaches toward the mirror plane. This is not a fixed
        # multiple of fpr_length: the tilt turns the whole coupler, and growing
        # the horn to fit its fan moves the face again. Assuming it put the two
        # couplers through each other as soon as the fan sizing widened them,
        # and an aperture arc that straddles the mirror plane is no longer
        # ordered in |x|, which is what the arm ladder nests on.
        taper_len_arr, taper_len_in = 14.0, 16.0

        def reach_x(x, y):
            return x * cos_w - y * sin_w

        faces = []
        for index in range(49):
            th = -alpha_max + 2.0 * alpha_max * index / 48.0
            for r in (R, R + taper_len_arr):
                faces.append(reach_x(c_arr + r * math.cos(th), r * math.sin(th)))
            th_in = -beta_max + 2.0 * beta_max * index / 48.0
            for r in (R, R + taper_len_in):
                faces.append(reach_x(c_focal - r * math.cos(th_in), r * math.sin(th_in)))
        sep = max(self._draw("fpr_separation", self.fpr_separation),
                  2.0 * max(faces) + 20.0)

        # The output side is drawn by mirroring the input placement, so only the
        # input centre is needed here.
        cx_in = -sep / 2.0
        self._drawn_separation = sep

        def rot_in(x, y):
            return (cx_in + x * cos_w - y * sin_w, cy_in + x * sin_w + y * cos_w)

        def mirror_pt(p):
            return (-p[0], p[1])

        # 1. Input Star Coupler Horn Slab
        seg_arr = 24
        arc_arr = []
        for i in range(seg_arr + 1):
            th = alpha_max - 2.0 * alpha_max * (i / seg_arr)
            arc_arr.append(rot_in(c_arr + R * math.cos(th), R * math.sin(th)))

        seg_in = 16
        arc_in = []
        for i in range(seg_in + 1):
            th = -beta_max + 2.0 * beta_max * (i / seg_in)
            arc_in.append(rot_in(c_focal - R * math.cos(th), R * math.sin(th)))

        poly_in = arc_in + arc_arr
        poly_out = [mirror_pt(p) for p in poly_in]

        # 2. Array Apertures
        arr_in, dum_in = [], []
        w_ap = self._draw("aperture_width", self.aperture_width)
        w_wg = self._draw("waveguide_width", self.waveguide_width)

        for idx in range(total_arr):
            th = arr_half_span - idx * ang_step_arr
            bx, by = c_arr + R * math.cos(th), R * math.sin(th)
            ux, uy = math.cos(th), math.sin(th)
            is_dum = (idx < self.dummy_count) or (idx >= self.array_count + self.dummy_count)
            t_len = taper_len_arr * 0.45 if is_dum else taper_len_arr
            tx, ty = bx + t_len * ux, by + t_len * uy

            perp_x, perp_y = -uy, ux
            w1 = w_ap / 2.0
            w2 = (w_wg if not is_dum else w_ap * 0.6) / 2.0
            p1 = rot_in(bx + w1 * perp_x, by + w1 * perp_y)
            p2 = rot_in(tx + w2 * perp_x, ty + w2 * perp_y)
            p3 = rot_in(tx - w2 * perp_x, ty - w2 * perp_y)
            p4 = rot_in(bx - w1 * perp_x, by - w1 * perp_y)

            t_w = rot_in(tx, ty)
            tan_w = (ux * cos_w - uy * sin_w, ux * sin_w + uy * cos_w)
            entry = {"poly": [p1, p2, p3, p4], "tip": t_w, "tan": tan_w, "is_dummy": is_dum}
            if is_dum:
                dum_in.append(entry)
            else:
                arr_in.append(entry)

        arr_out = []
        for a in arr_in:
            p_mir = [mirror_pt(pt) for pt in a["poly"]]
            tip_mir = mirror_pt(a["tip"])
            tan_mir = (-a["tan"][0], a["tan"][1])
            arr_out.append({"poly": p_mir, "tip": tip_mir, "tan": tan_mir, "is_dummy": False})

        dum_out = []
        for d in dum_in:
            p_mir = [mirror_pt(pt) for pt in d["poly"]]
            tip_mir = mirror_pt(d["tip"])
            tan_mir = (-d["tan"][0], d["tan"][1])
            dum_out.append({"poly": p_mir, "tip": tip_mir, "tan": tan_mir, "is_dummy": True})

        # 3. Channel Waveguides & Tapers
        chan_in = []
        for k in range(self.channel_count):
            th = in_half_span - k * ang_step_in
            bx, by = c_focal - R * math.cos(th), R * math.sin(th)
            ux, uy = -math.cos(th), math.sin(th)
            tx, ty = bx + taper_len_in * ux, by + taper_len_in * uy

            perp_x, perp_y = -uy, ux
            w1 = (w_ap * 0.85) / 2.0
            w2 = w_wg / 2.0
            p1 = rot_in(bx + w1 * perp_x, by + w1 * perp_y)
            p2 = rot_in(tx + w2 * perp_x, ty + w2 * perp_y)
            p3 = rot_in(tx - w2 * perp_x, ty - w2 * perp_y)
            p4 = rot_in(bx - w1 * perp_x, by - w1 * perp_y)

            ext_len = 26.0
            ex, ey = tx + ext_len * ux, ty + ext_len * uy
            tip_w = rot_in(tx, ty)
            ext_w = rot_in(ex, ey)
            tan_w = (ux * cos_w - uy * sin_w, ux * sin_w + uy * cos_w)
            chan_in.append({"poly": [p1, p2, p3, p4], "tip": tip_w, "ext": ext_w, "tan": tan_w})

        chan_out = []
        for c in chan_in:
            p_mir = [mirror_pt(pt) for pt in c["poly"]]
            tip_mir = mirror_pt(c["tip"])
            ext_mir = mirror_pt(c["ext"])
            tan_mir = (-c["tan"][0], c["tan"][1])
            chan_out.append({"poly": p_mir, "tip": tip_mir, "ext": ext_mir, "tan": tan_mir})

        # 4. Arrayed waveguides. Each arm launches along its aperture normal,
        # climbs, caps over both aperture fans and descends into the mirrored
        # aperture; the climb is the delay ladder. See ``_arch_ladder``, which
        # the AWG shares, for why the shape is what it is.
        #
        # This is why the couplers are TILTED: their array faces aim up and
        # inward, so the arms leave tangentially instead of turning through 90
        # degrees at the aperture.
        entries = []
        for a_ in arr_in:
            p0, t0 = a_["tip"], a_["tan"]
            if abs(p0[0]) < 1e-6:
                continue
            n = math.hypot(t0[0], t0[1]) or 1.0
            entries.append((p0, (t0[0] / n, t0[1] / n)))
        # innermost aperture (smallest |x|) gets the shortest arm
        arms = _arch_ladder(entries, total_spread=h_apex, aperture_width=w_ap)
        self._delta_length = h_apex / max(len(entries) - 1, 1) if len(entries) > 1 else 0.0

        # No recentring here either: the couplers stay on the placement point
        # and the array climbs above it, which is what a caller routing to the
        # channel ports is positioning. Scene reads the real box.
        return poly_in, poly_out, chan_in, chan_out, arr_in, arr_out, dum_in, dum_out, arms

    def ports(self) -> dict[str, Port]:
        _pi, _po, chan_in, chan_out, _ai, _ao, _di, _do, _arms = self._awgr_layout()
        w = self._draw("waveguide_width", self.waveguide_width)
        ports = {}
        # Each channel sits on a tilted arc, so it launches along its own
        # normal. Forcing 180 and 0 sent every route out of the coupler at the
        # wrong angle, which is the same bug the AWG had on its outputs.
        for idx, c in enumerate(chan_in, start=1):
            tan = c["tan"]
            ports[f"i{idx}"] = Port(f"i{idx}", Vec3(c["ext"][0], c["ext"][1], 0.0),
                                    orientation_deg=math.degrees(math.atan2(tan[1], tan[0])), width=w)
        for idx, c in enumerate(chan_out, start=1):
            tan = c["tan"]
            ports[f"o{idx}"] = Port(f"o{idx}", Vec3(c["ext"][0], c["ext"][1], 0.0),
                                    orientation_deg=math.degrees(math.atan2(tan[1], tan[0])), width=w)
        return ports

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        count = int(self.channel_count)
        return "awg", {"inputs": count, "outputs": count, "arms": 7, "pitch": 0.3}

    def geometry_2d(self) -> dict[str, Any]:
        poly_in, poly_out, chan_in, chan_out, arr_in, arr_out, dum_in, dum_out, arms = self._awgr_layout()
        w = self._draw("waveguide_width", self.waveguide_width)
        color = "#2b6cb0"
        stroke = "#1a4373"
        children = [
            _chip_polygon(poly_in, fill=color, opacity=0.92, stroke=stroke, stroke_width=0.12),
            _chip_polygon(poly_out, fill=color, opacity=0.92, stroke=stroke, stroke_width=0.12),
        ]
        for a in arr_in + arr_out + dum_in + dum_out:
            children.append(_chip_polygon(a["poly"], fill=color, opacity=0.92, stroke="none"))
        for c in chan_in + chan_out:
            children.append(_chip_polygon(c["poly"], fill=color, opacity=0.92, stroke="none"))
            children.append(_chip_line(c["tip"][0], c["tip"][1], c["ext"][0], c["ext"][1], stroke=color, stroke_width=w * 1.6, opacity=1.0))
        for arm in arms:
            children.append(_chip_polyline(arm, color, w * 1.6, 0.95))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        poly_in, poly_out, chan_in, chan_out, arr_in, arr_out, dum_in, dum_out, arms = self._awgr_layout()
        thickness = self._draw_thickness()
        w = self._draw("waveguide_width", self.waveguide_width)
        children = [
            _chip_extruded_polygon(poly_in, thickness * 0.85, **self._core("#2b6cb0", "silicon_nitride"), opacity=0.9),
            _chip_extruded_polygon(poly_out, thickness * 0.85, **self._core("#2b6cb0", "silicon_nitride"), opacity=0.9),
        ]
        for aperture in arr_in + arr_out + dum_in + dum_out:
            children.append(_chip_extruded_polygon(
                aperture["poly"], thickness, **self._core("#2b6cb0"),
                opacity=0.55 if aperture["is_dummy"] else 0.9,
            ))
        for c in chan_in + chan_out:
            children.append(_chip_extruded_polygon(
                c["poly"], thickness, **self._core("#2b6cb0"), opacity=0.9,
            ))
            children.append(_chip_path_slab([c["tip"], c["ext"]], w, thickness, **self._core("#2b6cb0")))
        for arm in arms:
            children.append(_chip_path_slab(arm, w, thickness, **self._core("#2b6cb0")))
        return self._on_the_stack(children)

    def physics_metadata(self) -> dict[str, Any]:
        return {
            "domain": "on_chip",
            "component": "arrayed_waveguide_grating_router",
            "channel_count": self.channel_count,
            "array_count": self.array_count,
            "dummy_count": self.dummy_count,
            "center_wavelength_nm": self.center_wavelength_nm,
            "channel_spacing_nm": self.channel_spacing_nm,
            "free_spectral_range_nm": self.free_spectral_range_nm,
        }


@dataclass
class BraggGrating(ChipComponent):
    """Straight Bragg grating with schematic corrugation teeth.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in physical microns.
    angle : float
        Rotation in degrees.
    length : float
        Physical grating length in microns.
    period : float
        Physical corrugation period in microns.
    corrugation_width : float
        Physical corrugation tooth width in microns.
    waveguide_width : float
        Optical waveguide and port width in microns. Defaults to the generic strip width.
    center_wavelength_nm : float
        Center reflection wavelength metadata in nanometers.
    reflectivity : float
        Nominal reflectivity metadata as a unitless fraction.
    label : str
        Optional display label.
    """

    component_type = "BraggGrating"
    schematic_family = "bragg_grating"
    length: float = 240.0
    period: float = 0.32
    corrugation_width: float = 0.08
    waveguide_width: float = 0.5
    center_wavelength_nm: float = 1550.0
    reflectivity: float = 0.9

    def __init__(self, center=(0, 0), angle=0, length: float = 240.0, period: float = 0.32, corrugation_width: float = 0.08, waveguide_width: float | None = None, center_wavelength_nm: float = 1550.0, reflectivity: float = 0.9, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.length = float(length)
        self.period = float(period)
        self.corrugation_width = float(corrugation_width)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.center_wavelength_nm = float(center_wavelength_nm)
        self.reflectivity = float(reflectivity)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def grating_count(self) -> int:
        return max(int(round(self.length / max(self.period, 1e-9))), 1)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "length": self.length,
                "period": self.period,
                "corrugation_width": self.corrugation_width,
                "waveguide_width": self.waveguide_width,
                "center_wavelength_nm": self.center_wavelength_nm,
                "reflectivity": self.reflectivity,
                "thickness": self.chip_thickness,
            },
        )

    def physics_metadata(self) -> dict[str, Any]:
        # Restored from HEAD: this went missing while three neighbouring classes
        # were deleted and put back, and it is what the physics bridge reads.
        return {
            "domain": "on_chip",
            "component": "bragg_grating",
            "center_wavelength_nm": self.center_wavelength_nm,
            "period": self.period,
            "reflectivity": self.reflectivity,
        }

    def ports(self) -> dict[str, Port]:
        # Ports on the drawn grating ends (geometry is compacted to representative teeth).
        half = self._draw("length", self.length) / 2.0
        w = self._draw("waveguide_width", self.waveguide_width)
        return {
            "o1": Port("o1", Vec3(-half, 0.0, 0.0), orientation_deg=180, width=w),
            "o2": Port("o2", Vec3(half, 0.0, 0.0), orientation_deg=0, width=w),
        }

    def geometry_2d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("waveguide_width", self.waveguide_width)
        corrugation = self._draw("corrugation_width", self.corrugation_width)
        children: list[dict[str, Any]] = [_chip_box(0.0, 0.0, length, width, self.color, self.opacity, stroke=SILICON_EDGE, stroke_width=0.08)]
        # Draw a representative tooth train instead of thousands of physical-period teeth.
        tooth_count = min(self.grating_count, 32)
        for x in _centered_offsets(tooth_count, length / max(tooth_count, 1)):
            children.append(_chip_box(x, width / 2.0 + corrugation / 2.0, length / max(tooth_count, 1) * 0.45, corrugation, self.color, self.opacity))
            children.append(_chip_box(x, -width / 2.0 - corrugation / 2.0, length / max(tooth_count, 1) * 0.45, corrugation, self.color, self.opacity))
        return {"type": "group", "children": children}

    def geometry_3d(self) -> dict[str, Any]:
        length = self._draw("length", self.length)
        width = self._draw("waveguide_width", self.waveguide_width)
        corrugation = self._draw("corrugation_width", self.corrugation_width)
        thickness = self._draw_thickness()
        children: list[dict[str, Any]] = [_chip_slab(length, width, thickness, **self._core())]
        tooth_count = min(self.grating_count, 32)
        for x in _centered_offsets(tooth_count, length / max(tooth_count, 1)):
            children.append(_chip_slab(length / max(tooth_count, 1) * 0.45, corrugation, thickness, x=x, y=width / 2.0 + corrugation / 2.0, **self._core()))
            children.append(_chip_slab(length / max(tooth_count, 1) * 0.45, corrugation, thickness, x=x, y=-width / 2.0 - corrugation / 2.0, **self._core()))
        return self._on_the_stack(children)


class SagnacLoop(ChipComponent):
    """Sagnac loop mirror schematic with two input/output ports.

    Parameters
    ----------
    center : tuple[float, float]
        Component center in physical microns.
    angle : float
        Rotation in degrees.
    loop_radius : float
        Physical loop radius in microns.
    coupler_length : float
        Physical directional-coupler interaction length in microns.
    port_spacing : float
        Physical spacing between the two left-side waveguide ports.
    waveguide_width : float
        Optical waveguide and port width in microns. Defaults to the generic strip width.
    label : str
        Optional display label.
    """

    component_type = "SagnacLoop"
    schematic_family = "sagnac_loop"
    loop_radius: float = 30.0
    coupler_length: float = 18.0
    port_spacing: float = 8.0
    waveguide_width: float = 0.5

    def __init__(self, center=(0, 0), angle=0, loop_radius: float = 30.0, coupler_length: float = 18.0, port_spacing: float = 8.0, waveguide_width: float | None = None, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.loop_radius = float(loop_radius)
        self.coupler_length = float(coupler_length)
        self.port_spacing = float(port_spacing)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def total_length(self) -> float:
        return self.coupler_length + 2.0 * self.loop_radius

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={
                "loop_radius": self.loop_radius,
                "coupler_length": self.coupler_length,
                "port_spacing": self.port_spacing,
                "waveguide_width": self.waveguide_width,
                "thickness": self.chip_thickness,
            },
        )

    def ports(self) -> dict[str, Port]:
        # Ports at the drawn input-waveguide ends: left = -(coupler/2 + radius), y = ±spacing/2.
        half = self._draw("coupler_length", self.coupler_length) / 2.0 + self._draw("loop_radius", self.loop_radius)
        spacing = self._draw("port_spacing", self.port_spacing)
        w = self._draw("waveguide_width", self.waveguide_width)
        return {
            "o1": Port("o1", Vec3(-half, spacing / 2.0, 0.0), orientation_deg=180, width=w),
            "o2": Port("o2", Vec3(-half, -spacing / 2.0, 0.0), orientation_deg=180, width=w),
        }

    def _loop_path(self) -> list[tuple[float, float]]:
        """The one waveguide of the mirror: in at o1, through the coupler, round the loop, back out at o2."""

        r = self._draw("loop_radius", self.loop_radius)
        cl = self._draw("coupler_length", self.coupler_length)
        sp = self._draw("port_spacing", self.port_spacing)
        w = self._draw("waveguide_width", self.waveguide_width)
        c = 0.8 * w                                         # half the centre spacing in the coupler (gap 0.6 w)
        x0, xl, xr = -(cl / 2.0 + r), -cl / 2.0, cl / 2.0
        bend, rho = 0.6 * r, 0.4 * r                        # the loop: S-bends out, then a half circle
        xc = xr + bend

        def sbend(xa: float, ya: float, xb: float, yb: float) -> list[tuple[float, float]]:
            return [(xa + (xb - xa) * i / 24.0, ya + (yb - ya) * (0.5 - 0.5 * math.cos(math.pi * i / 24.0)))
                    for i in range(1, 25)]

        arc = [(xc + rho * math.cos(math.radians(a)), rho * math.sin(math.radians(a))) for a in range(90, -91, -6)]
        return [(x0, sp / 2.0), *sbend(x0, sp / 2.0, xl, c), (xr, c), *sbend(xr, c, xc, rho), *arc[1:],
                *sbend(xc, -rho, xr, -c), (xl, -c), *sbend(xl, -c, x0, -sp / 2.0)]

    def geometry_2d(self) -> dict[str, Any]:
        cl = self._draw("coupler_length", self.coupler_length)
        w = self._draw("waveguide_width", self.waveguide_width)
        return {
            "type": "group",
            "children": [
                _chip_box(0.0, 0.0, cl, 3.6 * w, self.color, self.opacity * 0.14, stroke=SILICON_EDGE, stroke_width=0.05),
                _chip_polygon(_polyline_outline(self._loop_path(), w), fill=self.color, opacity=self.opacity,
                              stroke=SILICON_EDGE, stroke_width=0.08),
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        w = self._draw("waveguide_width", self.waveguide_width)
        return self._on_the_stack([_chip_extruded_polygon(_polyline_outline(self._loop_path(), w), self._draw_thickness(),
                                                **self._core())])

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "sagnac_loop", "loop_radius": self.loop_radius, "port_spacing": self.port_spacing}

@dataclass


class EchelleGrating(ChipComponent):
    """Planar concave (echelle / Rowland) grating demultiplexer — a free-propagation
    slab whose curved edge carries reflective facets that disperse wavelengths back to
    the output waveguides. A compact alternative to an AWG."""

    component_type = "EchelleGrating"
    schematic_family = "echelle_grating"
    channel_count: int = 8
    slab_length: float = 60.0
    slab_width: float = 44.0
    grating_radius: float | None = None
    waveguide_width: float = 0.5
    facet_count: int = 26
    center_wavelength_nm: float = 1550.0
    channel_spacing_nm: float = 0.8

    def __init__(self, center=(0, 0), angle=0, channel_count=8, slab_length=60.0, slab_width=44.0, grating_radius: float | None = None, waveguide_width: float | None = None, facet_count=26, center_wavelength_nm=1550.0, channel_spacing_nm=0.8, **kwargs):
        strip = _generic_pdk_defaults()["strip"]
        self.channel_count = int(channel_count)
        self.slab_length = float(slab_length)
        self.slab_width = float(slab_width)
        self.grating_radius = float(slab_length if grating_radius is None else grating_radius)
        self.waveguide_width = float(strip["width"] if waveguide_width is None else waveguide_width)
        self.facet_count = int(facet_count)
        self.center_wavelength_nm = float(center_wavelength_nm)
        self.channel_spacing_nm = float(channel_spacing_nm)
        self._init_chip(center=center, angle=angle, **kwargs)

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"channel_count": self.channel_count, "slab_length": self.slab_length, "slab_width": self.slab_width, "grating_radius": self.grating_radius, "center_wavelength_nm": self.center_wavelength_nm, "channel_spacing_nm": self.channel_spacing_nm, "thickness": self.chip_thickness},
        )

    def _arc(self) -> list[tuple[float, float]]:
        r = self.grating_radius
        cx = -self.slab_length / 2.0
        theta = math.asin(min((self.slab_width / 2.0) / r, 0.96))
        steps = 48
        return [
            (cx + r * math.cos(theta - 2.0 * theta * i / steps), r * math.sin(theta - 2.0 * theta * i / steps))
            for i in range(steps + 1)
        ]

    def _slab_polygon(self) -> list[tuple[float, float]]:
        half_w = self.slab_width / 2.0
        left = -self.slab_length / 2.0
        return [(left, half_w), *self._arc(), (left, -half_w)]

    @property
    def _access_length(self) -> float:
        return self.slab_length * 0.2                       # the guides run this far out of the slab

    def _port_ys(self) -> list[float]:
        total = self.channel_count + 1
        span = self.slab_width * 0.78
        return [(-(total - 1) / 2.0 + i) * (span / max(total - 1, 1)) for i in range(total)]

    def ports(self) -> dict[str, Port]:
        x = -self.slab_length / 2.0 - self._access_length
        ys = self._port_ys()
        ports = {"in": Port("in", Vec3(x, ys[0], 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width))}
        for i, y in enumerate(ys[1:], start=1):
            ports[f"o{i}"] = Port(f"o{i}", Vec3(x, y, 0), orientation_deg=180, width=self._draw("waveguide_width", self.waveguide_width))
        return ports

    def _teeth(self) -> list[list[tuple[float, float]]]:
        """The echelle facets: one sawtooth step on the curved edge per facet, facing the guides."""

        cx, r = -self.slab_length / 2.0, self.grating_radius
        theta = math.asin(min((self.slab_width / 2.0) / r, 0.96))
        n, depth = max(self.facet_count, 2), self.slab_length * 0.045
        teeth = []
        for k in range(n):
            a0, a1 = theta - 2.0 * theta * k / n, theta - 2.0 * theta * (k + 1) / n
            p0 = (cx + r * math.cos(a0), r * math.sin(a0))
            p1 = (cx + r * math.cos(a1), r * math.sin(a1))
            out = (cx + (r + depth) * math.cos(a0), (r + depth) * math.sin(a0))
            teeth.append([p0, out, p1])
        return teeth

    def _reflector_band(self) -> list[tuple[float, float]]:
        cx, r = -self.slab_length / 2.0, self.grating_radius
        theta = math.asin(min((self.slab_width / 2.0) / r, 0.96))
        r0, r1 = r + self.slab_length * 0.045, r + self.slab_length * 0.075
        outer = [(cx + r1 * math.cos(theta - 2.0 * theta * i / 48), r1 * math.sin(theta - 2.0 * theta * i / 48)) for i in range(49)]
        inner = [(cx + r0 * math.cos(-theta + 2.0 * theta * i / 48), r0 * math.sin(-theta + 2.0 * theta * i / 48)) for i in range(49)]
        return outer + inner

    def _guides(self) -> list[list[tuple[float, float]]]:
        """Each guide widens into the slab, as the arms of an AWG do."""

        left, w = -self.slab_length / 2.0, self._draw("waveguide_width", self.waveguide_width)
        x0, wide = left - self._access_length, 3.0 * w
        return [[(x0, y + w / 2.0), (left - self._access_length * 0.45, y + w / 2.0), (left, y + wide / 2.0),
                 (left, y - wide / 2.0), (left - self._access_length * 0.45, y - w / 2.0), (x0, y - w / 2.0)]
                for y in self._port_ys()]

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "echelle", {"outputs": int(self.channel_count), "pitch": 0.2}

    def geometry_2d(self) -> dict[str, Any]:
        tooth = {"fill": self.color, "opacity": self.opacity * 0.92, "stroke": SILICON_EDGE, "stroke_width": 0.05}
        return {
            "type": "group",
            "children": [
                _chip_polygon(self._slab_polygon(), fill=self.color, opacity=self.opacity * 0.3, stroke=SILICON_EDGE, stroke_width=0.1),
                _chip_polygon(self._reflector_band(), **tooth),
                *[_chip_polygon(points, **tooth) for points in self._teeth()],
                *[_chip_polygon(points, **tooth) for points in self._guides()],
            ],
        }

    def geometry_3d(self) -> dict[str, Any]:
        thickness, core = self._draw_thickness(), self._core()
        solid = [_chip_extruded_polygon(points, thickness, **core)
                 for points in (self._reflector_band(), *self._teeth(), *self._guides())]
        slab = _chip_extruded_polygon(self._slab_polygon(), thickness, **core, opacity=0.6)
        return self._on_the_stack([*_cut_footprints([slab], solid), *solid])    # the facets own their patch

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "on_chip", "component": "echelle_grating", "mode": "wavelength", "channel_count": self.channel_count, "center_wavelength_nm": self.center_wavelength_nm}


@dataclass


class ChipSubstrate(ChipComponent):
    """A die / substrate base rectangle that defines the chip extent (SOI by default).
    Drawn translucent and behind everything so devices placed on top stay visible; a
    chamfered corner marks die orientation. The on-chip analogue of an optical table."""

    component_type = "ChipSubstrate"
    schematic_family = "substrate"
    length: float = 200.0
    width: float = 120.0
    kind: str = "soi"
    chamfer: float = 12.0

    _FILL = {"soi": "#dde7ef", "silicon": "#cfd8e0", "sin": "#e7e0ee", "inp": "#e6ddd2"}
    _STROKE = "#8fa6b8"

    def __init__(self, center=(0, 0), angle=0, length=200.0, width=120.0, kind="soi", chamfer=12.0, **kwargs):
        self.length = float(length)
        self.width = float(width)
        self.kind = str(kind)
        self.chamfer = float(chamfer)
        kwargs.setdefault("opacity", 0.5)        # translucent so devices on top remain visible
        kwargs.setdefault("color", self._FILL.get(self.kind, self._FILL["soi"]))
        self._init_chip(center=center, angle=angle, **kwargs)

    @property
    def _fill(self) -> str:
        return self._FILL.get(self.kind, self._FILL["soi"])

    def physical_spec(self) -> PhysicalSpec:
        return PhysicalSpec(
            device_family=self.schematic_family,
            values={"length": self.length, "width": self.width, "kind_index": float(list(self._FILL).index(self.kind) if self.kind in self._FILL else 0), "thickness": self.chip_thickness},
        )

    def ports(self) -> dict[str, Port]:
        return {}

    def _outline(self) -> list[tuple[float, float]]:
        hl, hw = self.length / 2.0, self.width / 2.0
        c = max(min(self.chamfer, self.width * 0.4, self.length * 0.4), 0.0)
        # chamfered top-left corner = die orientation marker
        return [(-hl + c, hw), (hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw - c)]

    def geometry_2d(self) -> dict[str, Any]:
        return {
            "type": "group",
            "children": [_chip_polygon(self._outline(), fill=self._fill, opacity=self.opacity, stroke=self._STROKE, stroke_width=0.4)],
        }

    def geometry_3d(self) -> dict[str, Any]:
        ts = 6.0
        return {"shape": "group", "children": [_chip_extruded_polygon(self._outline(), ts, color=self._fill, preset="silicon", z_offset=-ts)]}
