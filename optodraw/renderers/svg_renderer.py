"""SVG renderer — 2D publication-quality figures using drawsvg."""

from __future__ import annotations

import math
from typing import Any

import drawsvg as draw

from optodraw.core.component import ANNOTATION_TYPES, Component, Group
from optodraw.core.beam import Beam, FocusingBeam, band_quads, drawn_widths
from optodraw.core.markup import has_markup, svg_text
from optodraw.core.routing import Route, bench_cable
from optodraw.components.optics import Lens, Mirror, BeamSplitter, Filter, Objective
from optodraw.components.devices import Laser, Lamp, Camera, Photodiode, Spectrometer
from optodraw.components.samples import Sample
from optodraw.components.misc import Grid, Block
from optodraw.renderers.capabilities import RenderReport
from optodraw.renderers.dimension_overlay import DimensionMarker, append_dimension_overlay
from optodraw.symbols.art import art_2d


#: carrier components that draw beneath everything, the lowest first: a table, a board on it, a die on the board
_CARRIERS = ("OpticalTable", "Breadboard", "Baseplate", "PCB", "ChipSubstrate")
_BACKGROUND_TYPES = frozenset(_CARRIERS)
_HOUSING_TYPES = frozenset({"Cryostat", "VacuumChamber"})      # drawn as cutaways: the light shows inside them
_STAGE_MOUNTS = frozenset({"stage", "xyz_stage", "rotation_stage"})   # 3D mounts drawn in 2D as a motion mark


def stage_mark_box(node) -> tuple[float, float, float, float] | None:
    """The box, in the part's own frame (y up), of the motion mark a part on a stage shows in 2D; None off a stage.

    The mark sits straight above or below the part in the world, on the side away from the label."""

    if getattr(node, "base_mount", "post") not in _STAGE_MOUNTS:
        return None
    from optodraw.layout import estimate_component_bounds
    from optodraw.renderers.labels import label_side

    x0, y0, x1, y1 = (float(v) for v in estimate_component_bounds(node))
    size = max(4.0, min(10.0, 0.6 * max(x1 - x0, y1 - y0)))
    turn = math.radians(float(node.transform.rotation_deg.z))
    cos, sin = abs(math.cos(turn)), abs(math.sin(turn))
    half_up = cos * (y1 - y0) / 2.0 + sin * (x1 - x0) / 2.0          # the part's half height in the world
    side = 1.0 if label_side(node).startswith("bottom") else -1.0    # world up, or world down
    dy = side * (half_up + 1.5 + size / 2.0)
    lx = (x0 + x1) / 2.0 + math.sin(turn) * dy                       # the world offset in the part's frame
    ly = (y0 + y1) / 2.0 + math.cos(turn) * dy
    h = size / 2.0
    return lx - h, ly - h, lx + h, ly + h


class SvgRenderer:
    """Renders a Scene to SVG via drawsvg."""

    def __init__(self, scene, **kwargs):
        self.scene = scene
        from optodraw.renderers.capabilities import view_keyword

        self.onchip_view = view_keyword(kwargs, "onchip_view")
        self.scale = kwargs.get("scale", 1.0)
        self.strict: bool = kwargs.get("strict", False)
        self.report = RenderReport()
        # Publication type size: text geometry sizes scale by font_size_pt
        # relative to the 8 pt reference body size used across presets.
        self.font_size_pt = float(kwargs.get("font_size_pt", 8.0))
        # Animation support: set of id(component) to skip entirely
        self.hidden_ids: set[int] = kwargs.get("hidden_ids", set())
        # Animation support: id(beam/route) -> draw fraction 0.0..1.0
        self.partial_beams: dict[int, float] = kwargs.get("partial_beams", {})
        # Animation support: id(beam/route) -> (start_fraction, end_fraction)
        self.traveling_waves: dict[int, tuple[float, float]] = kwargs.get("traveling_waves", {})
        self.beam_widths: dict[int, float] = {}             # id(beam) -> its drawn width, nested on a shared path
        # Animation support: id(component) -> highlight strength 0.0..1.0
        self.highlight_levels: dict[int, float] = kwargs.get("highlight_levels", {})
        # Polarization overlay support (opt-in; backward compatible when False)
        self.show_polarization_overlay: bool = kwargs.get("show_polarization_overlay", False)
        self.polarization_overlays: dict[Any, Any] = dict(kwargs.get("polarization_overlays", {}))
        self.polarization_caption: str = kwargs.get("polarization_caption", "")
        self._resolved_polarization_overlays = self._resolve_polarization_overlays()
        self.show_dimension_overlay: bool = kwargs.get("show_dimension_overlay", False)
        raw_markers = kwargs.get("dimension_markers", [])
        self.dimension_markers: list[DimensionMarker] = list(raw_markers)
        # Editor support (opt-in): tag each component group with a stable id so an
        # interactive front-end can hit-test and select via the SVG itself. When
        # ``editable`` is False (default) output is byte-identical to before.
        self.editable: bool = kwargs.get("editable", False)
        self.component_ids: dict[int, str] = dict(kwargs.get("component_ids", {}))
        self.show_labels: bool = kwargs.get("show_labels", True)
        # Editor support: takes an inset's SVG and gives a URL for it, or None to draw it inline. A large drawing then
        # goes by its URL, so the editor's payload does not carry it.
        self.fragment_href = kwargs.get("fragment_href")
        self._inset_count = 0                                  # numbers the insets of one render: inset1, inset2...

    def render(self, filename: str | None = None) -> draw.Drawing:
        if self.onchip_view == "1d":
            return self._render_schematic(filename)
        s = self.scene
        self._inset_count = 0                                  # the insets are numbered per render
        self.beam_widths = drawn_widths([n for n in s.walk() if isinstance(n, Beam)])
        cx, cy = getattr(s, "frame_center", (0.0, 0.0))       # SVG y runs down: the frame's top is at -cy - h/2
        # the 1D view's family: without one, a browser draws the labels serif and a PNG sans
        d = draw.Drawing(s.width, s.height, origin=(cx - s.width / 2.0, -cy - s.height / 2.0),
                         font_family="Helvetica,Arial,sans-serif")
        self._render_node(d, s.root)
        if self.show_dimension_overlay and self.dimension_markers:
            append_dimension_overlay(d, self.dimension_markers)
        if self.show_polarization_overlay:
            self._draw_scene_polarization_legend(d)
        d.set_render_size(int(s.width * 3 * self.scale))
        if filename:
            d.save_svg(filename)
        return d

    def _render_schematic(self, filename: str | None) -> draw.Drawing:
        """The 1D view is the schematic: each part as its looked-up symbol, on the 1D layout."""

        from optodraw.notebook_1d import schematic_body
        from optodraw.symbols.schematic import build_schematic

        schematic = build_schematic(self.scene)
        d = draw.Drawing(schematic.width, schematic.height)        # origin top left, as the symbols are
        d.append(draw.Raw(schematic_body(schematic)))
        d.set_render_size(int(schematic.width * 3 * self.scale))
        if filename:
            d.save_svg(filename)
        return d

    def _resolve_polarization_overlays(self) -> dict[int, Any]:
        overlays: dict[int, Any] = {}
        for key, stokes in self.polarization_overlays.items():
            if isinstance(key, int):
                overlays[key] = stokes
                continue
            for node in self.scene.walk():
                node_key = getattr(node, "_id", None) or id(node)
                if node_key == key or getattr(node, "label", "") == key:
                    overlays[id(node)] = stokes
                    break
        for node in self.scene.walk():
            stokes = getattr(node, "_polarization_stokes", None)
            if stokes is not None:
                overlays[id(node)] = stokes
        if not overlays and self.show_polarization_overlay:
            overlays = self._traced_polarization()
        return overlays

    def _traced_polarization(self) -> dict[int, Any]:
        """The state after each part that acts on polarization, traced along each beam. The light starts
        unpolarized: a source does not say how it is polarized, so the first polariser sets the state."""

        from optodraw.core.polarization import StokesVector, jones_matrix_from_component, trace_stokes_through

        found: dict[int, Any] = {}
        for beam in self.scene.walk():
            if not isinstance(beam, Beam):
                continue
            parts = []
            for anchor in beam.anchors:
                part = anchor[0] if isinstance(anchor, (tuple, list)) and anchor and isinstance(anchor[0], Component) \
                    else anchor
                if isinstance(part, Component) and (not parts or parts[-1] is not part):
                    parts.append(part)
            wavelength = float(getattr(beam, "wavelength", 633.0) or 633.0)
            chain = []
            for part in parts[1:]:
                if jones_matrix_from_component(part, wavelength_nm=wavelength) is None:
                    continue                                    # it does not act on polarization
                chain.append(part)
                found.setdefault(id(part), trace_stokes_through(chain, StokesVector.unpolarized(),
                                                                wavelength_nm=wavelength).stokes)
        return found

    def _polarization_stokes_for(self, node: Component) -> Any | None:
        return self._resolved_polarization_overlays.get(id(node))

    @staticmethod
    def _s3_stroke_color(s3: float) -> str:
        if s3 > 0.15:
            return "#c0392b"
        if s3 < -0.15:
            return "#2980b9"
        return "#333333"

    def _draw_polarization_overlay(self, parent, node: Component, stokes: Any) -> None:
        from optodraw.core.polarization_viz import stokes_to_ellipse, stokes_to_poincare_2d

        inset_y = getattr(node, "aperture", getattr(node, "box_size", 8.0)) * 0.55 + 5.0
        ellipse = stokes_to_ellipse(stokes, cx=0.0, cy=inset_y, scale=3.6)
        s1, s2 = stokes_to_poincare_2d(stokes)
        stroke = self._s3_stroke_color(float(ellipse.get("s3", 0.0)))

        overlay = draw.Group(opacity=0.92)
        overlay.append(
            draw.Ellipse(
                ellipse["cx"],
                -ellipse["cy"],
                ellipse["rx"] * 2.0,
                ellipse["ry"] * 2.0,
                fill="none",
                stroke=stroke,
                stroke_width=0.35,
                transform=f"rotate({-ellipse['angle']},{ellipse['cx']},{-ellipse['cy']})",
            )
        )
        overlay.append(
            draw.Text(
                str(ellipse.get("label", "")),
                1.8,
                ellipse["cx"],
                -ellipse["cy"] - ellipse["rx"] - 1.2,
                text_anchor="middle",
                fill="#444",
            )
        )
        overlay.append(
            draw.Text(
                f"S3={float(ellipse.get('s3', 0.0)):+.2f}",
                1.4,
                ellipse["cx"] + 3.2,
                -ellipse["cy"],
                text_anchor="start",
                fill=stroke,
            )
        )
        overlay.append(
            draw.Circle(
                5.8,
                -inset_y - 4.0,
                1.1,
                fill=stroke,
                opacity=min(0.85, 0.35 + 0.5 * abs(float(ellipse.get("s3", 0.0)))),
            )
        )
        overlay.append(
            draw.Text(
                f"({s1:+.2f},{s2:+.2f})",
                1.2,
                7.2,
                -inset_y - 4.0,
                text_anchor="start",
                fill="#666",
            )
        )
        parent.append(overlay)

    def _draw_scene_polarization_legend(self, parent) -> None:
        if self.polarization_caption:
            parent.append(
                draw.Text(
                    self.polarization_caption,
                    3.2,
                    getattr(self.scene, "frame_center", (0.0, 0.0))[0] - self.scene.width / 2.0 + 6.0,
                    -getattr(self.scene, "frame_center", (0.0, 0.0))[1] - self.scene.height / 2.0 + 8.0,
                    text_anchor="start",
                    fill="#222",
                )
            )

    def _node_transform(self, node: Component) -> str:
        t = node.transform
        # World frame is y-up / CCW (matching the ray engine and 3D). SVG is y-down,
        # so we flip BOTH the y position and the rotation sign; otherwise asymmetric
        # parts (mirrors, beam splitters, prisms…) would render mirror-flipped from
        # their actual reflection geometry.
        parts = [
            f"translate({t.position.x},{-t.position.y})",
            f"rotate({-t.rotation_deg.z})",
        ]
        sx = -1 if getattr(node, "flip_horizontal", False) else 1
        sy = -1 if getattr(node, "flip_vertical", False) else 1
        if sx != 1 or sy != 1:
            parts.append(f"scale({sx},{sy})")
        return " ".join(parts)

    @staticmethod
    def _in_parent_frame(node: Component, points):
        """Convert world-space link points before drawing inside a parent group."""
        parent = getattr(node, "_parent", None)
        if parent is None:
            return points
        transform = parent.world_transform
        angle = math.radians(float(transform.rotation_deg.z))
        cosine, sine = math.cos(angle), math.sin(angle)
        converted = []
        for point in points:
            dx = float(point[0]) - float(transform.position.x)
            dy = float(point[1]) - float(transform.position.y)
            converted.append((dx * cosine + dy * sine, -dx * sine + dy * cosine, point[2] if len(point) > 2 else 0.0))
        return converted

    def _render_node(self, parent_svg, node: Component):
        # Animation: skip hidden components
        if id(node) in self.hidden_ids:
            return

        if isinstance(node, Group):
            g = draw.Group(transform=self._node_transform(node))
            children = list(node.children)
            # Background carriers (substrates, tables, breadboards) always render
            # FIRST so devices placed on them stay visible and clickable — no
            # matter when the carrier was added to the scene.
            background = sorted((c for c in children if getattr(c, "component_type", "") in _BACKGROUND_TYPES),
                                key=lambda c: _CARRIERS.index(c.component_type))
            if background:
                children = background + [c for c in children if c not in background]
            beams = [c for c in children if isinstance(c, (Beam, FocusingBeam))]
            cables = [c for c in children if isinstance(c, Route) and bench_cable(c.kind, c.start_component, c.end_component)]
            if beams or cables:
                # The light under the parts, over the carriers and the housings
                # it runs into: a beam drawn over an optic hid it, and the figure
                # no longer showed which part takes the light. Widest first, so
                # overlapping beams of different wavelengths nest visibly. A bench
                # cable lies under the parts too: its end goes under its connector.
                under = background + [c for c in children if getattr(c, "component_type", "") in _HOUSING_TYPES
                                      or getattr(c, "in_cryostat", False)]
                beams.sort(key=self._beam_width, reverse=True)
                placed = {id(c) for c in under + beams + cables}
                children = under + beams + cables + [c for c in children if id(c) not in placed]
            for child in children:
                self._render_node(g, child)
            parent_svg.append(g)
            return

        is_link = isinstance(node, (Beam, Route, FocusingBeam)) or getattr(node, "component_type", "") in {"Beam", "Route", "WaveguideRoute", "FiberRoute", "FocusingBeam"}
        g_attrs: dict[str, Any] = {} if is_link else {"transform": self._node_transform(node)}
        if self.editable:
            component_id = self.component_ids.get(id(node))
            if component_id:
                g_attrs["data-component-id"] = component_id
        if getattr(node, "component_type", "") in ANNOTATION_TYPES and node.opacity < 1.0:
            g_attrs["opacity"] = node.opacity           # an inset fades as one layer: backing, drawing and frame
        g = draw.Group(**g_attrs)

        # Dispatch based on component type. Beams/routes use absolute world
        # coordinates; in editor mode they are wrapped in their (identity) group
        # so the id-tagged ``g`` makes them selectable like components.
        if isinstance(node, Beam) or getattr(node, "component_type", "") == "Beam":
            self._draw_beam(g if self.editable else parent_svg, node)
            if self.editable:
                parent_svg.append(g)
            return
        elif isinstance(node, Route) or getattr(node, "component_type", "") in {"Route", "WaveguideRoute", "FiberRoute"}:
            self._draw_route(g if self.editable else parent_svg, node)
            if self.editable:
                parent_svg.append(g)
            return
        elif isinstance(node, FocusingBeam) or getattr(node, "component_type", "") == "FocusingBeam":
            self._draw_focusing_beam(g if self.editable else parent_svg, node)
            if self.editable:
                parent_svg.append(g)
            return
        elif isinstance(node, Grid):
            self._draw_grid(parent_svg, node)
            return
        elif node.component_type in ANNOTATION_TYPES:         # its text is the label below
            self._draw_geometry(g, node.annotation_2d(self.font_size_pt / 8.0))
        elif self.onchip_view != "1d" and (art := art_2d(node)) is not None:
            self._draw_geometry(g, art)                       # painted with its symbol: see optodraw/symbols/art.py
        elif isinstance(node, Lens):
            self._draw_lens(g, node)
        elif isinstance(node, Mirror):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, BeamSplitter):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Filter):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Objective):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Laser):
            self._draw_geometry(g, node.geometry_2d())  # burst included in geometry
        elif isinstance(node, Lamp):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Camera):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Photodiode):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Spectrometer):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Sample):
            self._draw_geometry(g, node.geometry_2d())
        elif isinstance(node, Block):
            self._draw_geometry(g, node.geometry_2d())
        else:
            geometry = node.geometry_2d()
            if geometry:
                self._draw_geometry(g, geometry)
            else:
                # Generic box fallback
                self._draw_blackbox(g, node)

        highlight_level = self.highlight_levels.get(id(node), 0.0)
        if highlight_level > 0.0:
            self._draw_component_highlight(g, node, highlight_level)

        if self.show_polarization_overlay:
            stokes = self._polarization_stokes_for(node)
            if stokes is not None:
                self._draw_polarization_overlay(g, node, stokes)

        if getattr(node, "base_mount", "post") in _STAGE_MOUNTS:
            g.append(self._stage_mark(node))

        # Add label if present (suppressed when labels are turned off). The art
        # rotates with the component; the NAME must not — a part placed at 180
        # would otherwise read upside down.
        if node.label and self.show_labels and node.component_type != "Inset":     # an inset's label is a name
            g.append(self._label_text(node, draw))

        parent_svg.append(g)

    # -- individual draw methods -------------------------------------------

    def _stage_mark(self, node):
        """A part on a stage: a small motion mark beside it, not a stage drawing (the stage is a 3D mount).

        The arrows turn with the part (a translation stage moves it along its own axis); the mark sits on the
        world side away from the label (``stage_mark_box``)."""

        mount = node.base_mount
        x0, y0, x1, y1 = stage_mark_box(node)
        size = x1 - x0
        lx, ly = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        mark = draw.Group(transform=f"translate({lx:.3f},{-ly:.3f})", **{"data-stage": mount})
        ink = {"stroke": "#4a5260", "stroke_width": 0.35, "fill": "none", "stroke_linecap": "round"}
        h = size / 2.0
        head = 0.22 * size

        def arrow(ax, ay, bx, by):
            mark.append(draw.Line(ax, ay, bx, by, **ink))
            for (px, py), (qx, qy) in (((ax, ay), (bx, by)), ((bx, by), (ax, ay))):
                ux, uy = (px - qx), (py - qy)
                n = math.hypot(ux, uy) or 1.0
                ux, uy = ux / n, uy / n
                mark.append(draw.Lines(px, py, px - head * ux + 0.5 * head * uy, py - head * uy - 0.5 * head * ux,
                                       px - head * ux - 0.5 * head * uy, py - head * uy + 0.5 * head * ux,
                                       close=True, fill="#4a5260", stroke="none"))

        if mount == "stage":
            arrow(-h, 0.0, h, 0.0)
        elif mount == "xyz_stage":
            arrow(-h, 0.0, h, 0.0)
            arrow(0.0, -h, 0.0, h)
            mark.append(draw.Circle(0.62 * h, -0.62 * h, 0.2 * h, **ink))         # z: out of the page
            mark.append(draw.Circle(0.62 * h, -0.62 * h, 0.05 * h, fill="#4a5260"))
        else:                                                                 # a rotation stage
            r = 0.75 * h
            start, end = math.radians(40.0), math.radians(320.0)
            steps = [start + (end - start) * k / 24 for k in range(25)]
            points = [v for t in steps for v in (r * math.cos(t), -r * math.sin(t))]
            mark.append(draw.Lines(*points, close=False, **ink))
            tx, ty = r * math.cos(end), -r * math.sin(end)
            ux, uy = -math.sin(end), -math.cos(end)                           # the arc's direction at its end
            mark.append(draw.Lines(tx + head * ux, ty + head * uy, tx - 0.5 * head * uy, ty + 0.5 * head * ux,
                                   tx + 0.5 * head * uy, ty - 0.5 * head * ux, close=True, fill="#4a5260", stroke="none"))
        return mark

    @staticmethod
    def _text(draw, label, size, x, y, **kwargs):
        """``label`` as text. With markup it is written by hand: drawsvg escapes what it is given."""

        if not has_markup(label):
            return draw.Text(label, size, x, y, **kwargs)
        anchor = kwargs.pop("text_anchor", "start")
        look = " ".join(f'{key.replace("_", "-")}="{value}"' for key, value in kwargs.items())
        return draw.Raw(svg_text(label, size, x, y, anchor, look))

    def _label_text(self, node, draw):
        """The component's name: upright whatever its rotation, and clear of its
        art (a fixed offset drops the label inside anything tall, like a ring).

        The gap is measured from the top of the art, not from half its height:
        a part drawn mostly above its centre, like a weight bank over its bus,
        would otherwise carry its name inside the drawing."""

        from optodraw.renderers.labels import label_side, label_spot

        size = 3 * (self.font_size_pt / 8.0)
        if node.component_type in ANNOTATION_TYPES:
            return self._text(draw, node.label, size, 0, size * 0.35, text_anchor=node.anchor, fill=node.color,
                              font_weight="bold" if node.bold else "normal")
        side = label_side(node)
        if side == "top":
            try:
                from optodraw.layout import estimate_component_bounds

                top = float(estimate_component_bounds(node)[3])
            except Exception:  # pragma: no cover - unknown geometry: keep the old gap
                top = 0.0
            x, y, anchor = 0, -max(top + 3.0, 8.0), "middle"   # an int: the default output keeps its bytes
        else:                                      # beside or below: measured in the world, svg y runs down
            dx, dy = label_spot(node)
            below = side.startswith("bottom")
            x, y = dx, -dy + (size * 0.8 if below else 0.0 if side.startswith("top") else size * 0.35)
            anchor = "end" if side.endswith("left") else "start" if side.endswith("right") else "middle"
        text = self._text(draw, node.label, size, x, y, text_anchor=anchor, fill="#333")
        # the group already applies rotate(-angle) for the y-flip, so the label
        # needs +angle to come out level — negating here only looks right at 180
        spin = float(node.transform.rotation_deg.z) % 360.0
        holder = text
        if spin:
            holder = draw.Group(transform=f"rotate({spin})")
            holder.append(text)
        sx = -1 if getattr(node, "flip_horizontal", False) else 1
        sy = -1 if getattr(node, "flip_vertical", False) else 1
        if sx != 1 or sy != 1:                     # the part's flip reaches the label: flip it back
            unflip = draw.Group(transform=f"scale({sx},{sy})")
            unflip.append(holder)
            holder = unflip
        return holder

    def _draw_grid(self, parent, node: Grid):
        g = draw.Group(stroke="black", opacity=node.opacity, stroke_width=0.1)
        w, h, p = node.grid_width, node.grid_height, node.pitch
        if p <= 1e-9 or w <= 0 or h <= 0:
            parent.append(g)
            return
        x = float(p)
        while x < w / 2 - 1e-9:
            g.append(draw.Line(x, -h / 2, x, h / 2))
            g.append(draw.Line(-x, -h / 2, -x, h / 2))
            x += float(p)
        y = float(p)
        while y < h / 2 - 1e-9:
            g.append(draw.Line(-w / 2, y, w / 2, y))
            g.append(draw.Line(-w / 2, -y, w / 2, -y))
            y += float(p)
        parent.append(g)

    def _draw_lens(self, g, node: Lens):
        r, w = node.radius, node.aperture
        p = draw.Path(fill=node.color, opacity=node.opacity)
        p.M(0, w / 2)
        p.Q(r, 0, 0, -w / 2)
        p.Q(-r, 0, 0, w / 2)
        p.Z()
        g.append(p)

    def _draw_blackbox(self, g, node, emission=False):
        sz = getattr(node, "box_size", 5.0)
        g.append(draw.Rectangle(-sz, -sz / 2, sz, sz, fill="white", stroke="black", stroke_width=sz / 20))
        if emission and hasattr(node, "color"):
            import numpy as np
            scatter = draw.Line(-sz / 2, 0, -sz / 8, 0, stroke=node.color, stroke_width=sz / 10, stroke_linecap="round")
            g.append(scatter)
            for a in np.linspace(0, 360, 7, endpoint=False):
                g.append(draw.Use(scatter, 0, 0, transform=f"rotate({a},{-sz/2},0)"))

    @staticmethod
    def _partial_path_points(pts: list, fraction: float) -> list:
        """Truncate a list of waypoints to ``fraction`` of total path length."""
        if fraction >= 1.0:
            return pts
        if fraction <= 0.0:
            return [(pts[0][0], pts[0][1])]
        total = sum(
            math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            for i in range(len(pts) - 1)
        )
        target = fraction * total
        result = [(pts[0][0], pts[0][1])]
        cumulative = 0.0
        for i in range(len(pts) - 1):
            seg_len = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            if cumulative + seg_len >= target:
                t = (target - cumulative) / seg_len if seg_len > 0 else 0.0
                x = pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
                y = pts[i][1] + t * (pts[i + 1][1] - pts[i][1])
                result.append((x, y))
                break
            result.append((pts[i + 1][0], pts[i + 1][1]))
            cumulative += seg_len
        return result

    @staticmethod
    def _path_slice_points(pts: list, start_fraction: float, end_fraction: float) -> list:
        """Return the sub-path between ``start_fraction`` and ``end_fraction`` of total length."""

        if len(pts) < 2:
            return [(pt[0], pt[1]) for pt in pts]

        start_fraction = min(max(start_fraction, 0.0), 1.0)
        end_fraction = min(max(end_fraction, 0.0), 1.0)
        if end_fraction <= start_fraction:
            end_point = SvgRenderer._partial_path_points(pts, end_fraction)[-1]
            return [(end_point[0], end_point[1])]

        total = sum(
            math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            for i in range(len(pts) - 1)
        )
        if total <= 1e-12:
            return [pts[0], pts[-1]]

        start_target = total * start_fraction
        end_target = total * end_fraction
        result: list[tuple[float, float]] = []
        cumulative = 0.0

        for i in range(len(pts) - 1):
            x1, y1 = pts[i][0], pts[i][1]
            x2, y2 = pts[i + 1][0], pts[i + 1][1]
            seg_len = math.hypot(x2 - x1, y2 - y1)
            seg_start = cumulative
            seg_end = cumulative + seg_len
            cumulative = seg_end
            if seg_len <= 1e-12 or seg_end < start_target:
                continue
            if seg_start > end_target:
                break

            local_start = max(start_target, seg_start)
            local_end = min(end_target, seg_end)
            t1 = (local_start - seg_start) / seg_len
            t2 = (local_end - seg_start) / seg_len
            p1 = (x1 + t1 * (x2 - x1), y1 + t1 * (y2 - y1))
            p2 = (x1 + t2 * (x2 - x1), y1 + t2 * (y2 - y1))

            if not result or math.hypot(result[-1][0] - p1[0], result[-1][1] - p1[1]) > 1e-9:
                result.append(p1)
            if math.hypot(result[-1][0] - p2[0], result[-1][1] - p2[1]) > 1e-9:
                result.append(p2)

            if seg_end >= end_target:
                break

        return result

    @staticmethod
    def _brighten_color(color: str, amount: float = 0.4) -> str:
        if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
            return color
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw_wave_overlay(self, parent, pts: list, node_color: str, node_width: float, node_opacity: float):
        if len(pts) < 2:
            return
        p = draw.Path(
            stroke=self._brighten_color(node_color, 0.45),
            fill="none",
            stroke_width=max(node_width * 1.9, node_width + 0.8),
            opacity=min(1.0, node_opacity + 0.15),
            stroke_linecap="round",
            stroke_linejoin="round",
        )
        p.M(pts[0][0], -pts[0][1])
        for pt in pts[1:]:
            p.L(pt[0], -pt[1])
        parent.append(p)

    def _draw_component_highlight(self, parent, node: Component, strength: float):
        opacity = 0.12 + 0.42 * strength
        stroke = self._brighten_color(getattr(node, "color", "#2d6cdf"), 0.5)
        if hasattr(node, "ring_radius"):
            radius = getattr(node, "ring_radius") + max(getattr(node, "waveguide_width", 0.5) * 3.0, 1.2)
            parent.append(
                draw.Circle(
                    0,
                    0,
                    radius,
                    fill="none",
                    stroke=stroke,
                    stroke_width=max(getattr(node, "waveguide_width", 0.5) * 3.2, 0.9),
                    opacity=opacity,
                )
            )
            return
        if hasattr(node, "total_length") and hasattr(node, "width"):
            width = getattr(node, "total_length")
            height = max(getattr(node, "width"), 1.0) * 2.4
            parent.append(
                draw.Rectangle(
                    -width / 2.0,
                    -height / 2.0,
                    width,
                    height,
                    fill="none",
                    stroke=stroke,
                    stroke_width=0.8,
                    opacity=opacity,
                )
            )
            return
        parent.append(draw.Circle(0, 0, 8.0, fill="none", stroke=stroke, stroke_width=0.8, opacity=opacity))

    def _draw_beam(self, parent, node: Beam):
        pts = self._in_parent_frame(node, node.resolve_points())
        if len(pts) < 2:
            return
        fraction = self.partial_beams.get(id(node), 1.0)
        if fraction < 1.0:
            pts = self._partial_path_points(pts, fraction)
        if len(pts) < 2:
            return
        color = node.color
        if getattr(node, "envelope", False):
            # the beam cone: one closed outline through both marginal rays, so a
            # focus renders as the textbook hourglass (the outline crosses itself)
            # translucent: the cone is a wash the individual rays still read through
            env = draw.Path(stroke="none", fill=color, opacity=node.opacity * 0.3, fill_rule="evenodd")
            env.M(pts[0][0], -pts[0][1])
            for pt in pts[1:]:
                env.L(pt[0], -pt[1])
            env.Z()
            parent.append(env)
            return
        bw = self._beam_width(node)
        self._append_hit_area(parent, pts, bw)
        # Draw the light BETWEEN parts: a beam threaded through a chain names each
        # optic twice (arriving at "in", leaving at "out"), and that span lies
        # inside the component — stroking it lays a line across its own art.
        runs = [self._in_parent_frame(node, run) for run in node.segments()] if fraction >= 1.0 else [pts]
        layer = draw.Group(opacity=node.opacity)      # one translucent layer: light that passes twice is not drawn twice
        for run in runs or [pts]:
            if len(run) < 2:
                continue
            quads = band_quads(run, bw)
            if quads:
                p = draw.Path(fill=color)
                for quad in quads:
                    p.M(quad[0][0], -quad[0][1])
                    for pt in quad[1:]:
                        p.L(pt[0], -pt[1])
                    p.Z()
                layer.append(p)
                continue
            p = draw.Path(stroke=color, fill="none", stroke_width=bw)
            p.M(run[0][0], -run[0][1])
            for pt in run[1:]:
                p.L(pt[0], -pt[1])
            layer.append(p)
        parent.append(layer)
        wave_window = self.traveling_waves.get(id(node))
        if wave_window is not None:
            wave_pts = self._path_slice_points(self._in_parent_frame(node, node.resolve_points()), wave_window[0], wave_window[1])
            self._draw_wave_overlay(parent, wave_pts, color, bw, node.opacity)

    def _beam_width(self, node: Any) -> float:
        return self.beam_widths.get(id(node), getattr(node, "display_width", 0.0))

    def _append_hit_area(self, parent, pts, width: float) -> None:
        """In editor mode, lay a transparent wide stroke under a thin path so it
        is easy to click-select."""

        if not self.editable or len(pts) < 2:
            return
        hit = draw.Path(stroke="#000000", fill="none", stroke_width=max(width * 4.0, 3.0), opacity=0.0)
        hit.M(pts[0][0], -pts[0][1])
        for pt in pts[1:]:
            hit.L(pt[0], -pt[1])
        parent.append(hit)

    def _draw_route(self, parent, node: Route):
        pts = self._in_parent_frame(node, node.resolve_points())
        if len(pts) < 2:
            return
        fraction = self.partial_beams.get(id(node), 1.0)
        if fraction < 1.0:
            pts = self._partial_path_points(pts, fraction)
        if len(pts) < 2:
            return
        color = node.color
        width2 = getattr(node, "width2", None)
        self._append_hit_area(parent, pts, max(node.width, width2 or 0.0))
        if width2 is not None and abs(float(width2) - float(node.width)) > 1e-9:
            # tapered waveguide: a filled outline whose width lerps start -> end
            self._draw_tapered_polyline(parent, pts, float(node.width), float(width2), color, node.opacity)
        else:
            p = draw.Path(
                stroke=color,
                fill="none",
                stroke_width=node.width,
                opacity=node.opacity,
                stroke_linecap="round",
                stroke_linejoin="round",
            )
            p.M(pts[0][0], -pts[0][1])
            for pt in pts[1:]:
                p.L(pt[0], -pt[1])
            parent.append(p)
        wave_window = self.traveling_waves.get(id(node))
        if wave_window is not None:
            wave_pts = self._path_slice_points(self._in_parent_frame(node, node.resolve_points()), wave_window[0], wave_window[1])
            self._draw_wave_overlay(parent, wave_pts, color, node.width, node.opacity)

    def _draw_tapered_polyline(self, parent, pts, width1: float, width2: float, color: str, opacity: float) -> None:
        """Filled outline along a polyline with linearly varying width (a taper)."""

        import math as _math

        xy = [(p[0], -p[1]) for p in pts]  # world y-up -> svg y-down
        seg_len = [_math.dist(xy[i], xy[i + 1]) for i in range(len(xy) - 1)]
        total = sum(seg_len) or 1.0
        # per-vertex outward normal = normalized average of adjacent segment normals
        normals = []
        for i in range(len(xy)):
            vecs = []
            if i > 0:
                dx, dy = xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]
                vecs.append((dx, dy))
            if i < len(xy) - 1:
                dx, dy = xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1]
                vecs.append((dx, dy))
            ax = sum(v[0] for v in vecs) / len(vecs)
            ay = sum(v[1] for v in vecs) / len(vecs)
            norm = _math.hypot(ax, ay) or 1.0
            normals.append((-ay / norm, ax / norm))
        left, right = [], []
        run = 0.0
        for i, (x, y) in enumerate(xy):
            if i > 0:
                run += seg_len[i - 1]
            half = (width1 + (width2 - width1) * (run / total)) / 2.0
            nx, ny = normals[i]
            left.append((x + nx * half, y + ny * half))
            right.append((x - nx * half, y - ny * half))
        p = draw.Path(fill=color, stroke="none", opacity=opacity)
        p.M(*left[0])
        for pt in left[1:]:
            p.L(*pt)
        for pt in reversed(right):
            p.L(*pt)
        p.Z()
        parent.append(p)

    def _draw_focusing_beam(self, parent, node: FocusingBeam):
        corners = self._in_parent_frame(node, node.corners())
        if not corners:
            return
        color = node.color
        path = draw.Path(fill=color, opacity=node.opacity)
        first, rest = corners[0], corners[1:]
        path.M(first[0], -first[1])       # SVG y grows downward; a corner may carry z too
        for corner in rest:
            path.L(corner[0], -corner[1])
        path.Z()
        parent.append(path)

    def _draw_geometry(self, parent, geometry: dict[str, Any]):
        gtype = geometry.get("type")
        if gtype != "group":
            self.report.check("svg", gtype, strict=self.strict, detail=f"2D node type {gtype!r}")
        if gtype == "group":
            part = geometry.get("part")                        # a named group: data-part, for the export gate
            holder = draw.Group(**{"data-part": part}) if part else parent
            for child in geometry.get("children", []):
                self._draw_geometry(holder, child)
            if part:
                parent.append(holder)
            return

        if gtype == "art":                                     # a symbol drawing, fitted to the part's ports
            a, b, c, d, e, f = geometry["matrix"]
            parent.append(draw.Raw(
                f'<g data-art="{geometry["symbol"]}" transform="matrix({a:.6g} {b:.6g} {c:.6g} {d:.6g} {e:.6g} {f:.6g})">'
                f'{geometry["svg"]}</g>'))
            for extra in ("overlay", "outline"):               # computed data on its screen; a moving part's place
                if extra in geometry:
                    self._draw_geometry(parent, geometry[extra])
            return

        if gtype == "fragment":                                # an inset: its own nested SVG, ids and rules kept inside
            from optodraw.figure.fragment import nested_svg

            self._inset_count += 1
            name = f"inset{self._inset_count}"
            w, h = geometry["w"], geometry["h"]
            panel = f' data-panel="{geometry["mm"]:g}"' if geometry.get("panel", True) else ""    # words: page text
            if self.editable:                                  # the editor picks it anywhere in its box, not on ink only
                parent.append(draw.Raw(f'<rect class="od-pick" x="{-w / 2.0:.6g}" y="{-h / 2.0:.6g}" width="{w:.6g}" '
                                       f'height="{h:.6g}" fill="none" pointer-events="all"/>'))
            href = self.fragment_href(geometry["svg"]) if self.fragment_href else None
            body = (f'<image href="{href}" width="{w:.6g}" height="{h:.6g}" preserveAspectRatio="none"/>' if href
                    else nested_svg(geometry["svg"], w, h, name))
            parent.append(draw.Raw(
                f'<g id="{name}" data-inset="{geometry["kind"]}"{panel} '
                f'transform="translate({-w / 2.0:.6g} {-h / 2.0:.6g})">{body}</g>'))
            return

        if gtype == "text":
            text_scale = self.font_size_pt / 8.0
            parent.append(
                draw.Text(
                    str(geometry.get("text", "")),
                    float(geometry.get("size", 4.0)) * text_scale,
                    geometry.get("x", 0.0),
                    -geometry.get("y", 0.0),
                    fill=geometry.get("fill", "#1f2937"),
                    opacity=geometry.get("opacity", 1.0),
                    text_anchor=geometry.get("text_anchor", "middle"),
                    dominant_baseline="central",
                    font_weight=geometry.get("font_weight", "normal"),
                    font_family="sans-serif",
                )
            )
            return

        if gtype == "rect":
            w = geometry["w"]
            h = geometry["h"]
            cx = geometry.get("cx", 0.0)
            cy = geometry.get("cy", 0.0)
            parent.append(
                draw.Rectangle(
                    cx - w / 2.0,
                    -cy - h / 2.0,
                    w,
                    h,
                    fill=geometry.get("fill", "none"),
                    stroke=geometry.get("stroke", "none"),
                    stroke_width=geometry.get("stroke_width", 0),
                    opacity=geometry.get("opacity", 1.0),
                )
            )
            return

        if gtype == "line":
            line_kwargs: dict[str, Any] = {}
            if geometry.get("stroke_dasharray"):
                line_kwargs["stroke_dasharray"] = geometry["stroke_dasharray"]
            if geometry.get("part"):                           # drawsvg writes a path: the export gate reads <line>
                dash = f' stroke-dasharray="{geometry["stroke_dasharray"]}"' if geometry.get("stroke_dasharray") else ""
                parent.append(draw.Raw(
                    f'<line x1="{geometry["x1"]:.4f}" y1="{-geometry["y1"]:.4f}" x2="{geometry["x2"]:.4f}" '
                    f'y2="{-geometry["y2"]:.4f}" stroke="{geometry.get("stroke", "#000000")}" '
                    f'stroke-width="{geometry.get("stroke_width", 1.0)}"{dash} data-part="{geometry["part"]}"/>'))
                return
            parent.append(
                draw.Line(
                    geometry["x1"],
                    -geometry["y1"],
                    geometry["x2"],
                    -geometry["y2"],
                    stroke=geometry.get("stroke", "#000000"),
                    stroke_width=geometry.get("stroke_width", 1.0),
                    opacity=geometry.get("opacity", 1.0),
                    **line_kwargs,
                )
            )
            return

        if gtype == "circle":
            parent.append(
                draw.Circle(
                    geometry.get("cx", 0.0),
                    -geometry.get("cy", 0.0),
                    geometry["r"],
                    fill=geometry.get("fill", "none"),
                    stroke=geometry.get("stroke", "none"),
                    stroke_width=geometry.get("stroke_width", 0),
                    opacity=geometry.get("opacity", 1.0),
                )
            )
            return

        if gtype == "path":
            # Raw SVG path in the component's y-up local frame — flip via transform
            # (the d string can't be sign-flipped textually).
            parent.append(
                draw.Path(
                    d=geometry.get("d", ""),
                    fill=geometry.get("fill", "none"),
                    stroke=geometry.get("stroke", "none"),
                    stroke_width=geometry.get("stroke_width", 0),
                    opacity=geometry.get("opacity", 1.0),
                    transform="scale(1,-1)",
                )
            )
            return

        if gtype == "ellipse":
            parent.append(
                draw.Ellipse(
                    geometry.get("cx", 0.0),
                    -geometry.get("cy", 0.0),
                    geometry["rx"],
                    geometry["ry"],
                    fill=geometry.get("fill", "none"),
                    stroke=geometry.get("stroke", "none"),
                    stroke_width=geometry.get("stroke_width", 0),
                    opacity=geometry.get("opacity", 1.0),
                )
            )
            return

        if gtype == "polygon":
            points = geometry.get("points", [])
            if not points:
                return
            poly_kwargs = {key: geometry[value] for key, value in
                           (("stroke_dasharray", "stroke_dasharray"), ("data-part", "part")) if geometry.get(value)}
            path = draw.Path(
                fill=geometry.get("fill", "none"),
                stroke=geometry.get("stroke", "none"),
                stroke_width=geometry.get("stroke_width", 0),
                opacity=geometry.get("opacity", 1.0),
                **poly_kwargs,
            )
            first = points[0]
            path.M(first[0], -first[1])
            for point in points[1:]:
                path.L(point[0], -point[1])
            path.Z()
            parent.append(path)
            return

        if gtype == "polyline":
            points = geometry.get("points", [])
            if not points:
                return
            path_kwargs: dict[str, Any] = {}
            if geometry.get("stroke_dasharray"):
                path_kwargs["stroke_dasharray"] = geometry["stroke_dasharray"]
            path = draw.Path(
                fill=geometry.get("fill", "none"),
                stroke=geometry.get("stroke", "#000000"),
                stroke_width=geometry.get("stroke_width", 1.0),
                opacity=geometry.get("opacity", 1.0),
                stroke_linecap=geometry.get("linecap", "butt"),
                stroke_linejoin=geometry.get("linejoin", "miter"),
                **path_kwargs,
            )
            first = points[0]
            path.M(first[0], -first[1])
            for point in points[1:]:
                path.L(point[0], -point[1])
            if geometry.get("closed"):
                path.Z()
            parent.append(path)
            return
