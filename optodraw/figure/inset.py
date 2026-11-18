"""``Inset``: a 2D part that draws any fragment, and moves, turns and saves like any other part."""

from __future__ import annotations

import math
from typing import Any

from optodraw.core.component import Component
from optodraw.core.transform import Transform, Vec3
from optodraw.figure.fragment import PT_MM, Fragment, _root, fragment_record
from optodraw.figure.sources import SceneView, _Stored, from_record, rebased, record_of, to_source

FRAME_MM = 0.12             # the line of a frame, on the page
BAR_SHARE = (0.04, 0.012)   # of the inset width: the margin of the scale bar, and its thickness
BAR_FLOOR_MM = (1.0, 0.3)   # the least margin and the least thickness in mm
PLATE_ALPHA = 0.55          # the dark plate under the bar and its text
CLEAR_GAP = 0.2             # a cut letter moved off a panel letter stands this many letter heights past it


def _shift(node: Component, step: tuple[float, float]) -> None:
    """Move ``node`` by a step given in the world, worked out in the frame of its parent."""

    dx, dy = step
    if node._parent is not None:
        import numpy as np

        linear = np.array(node._parent.world_transform.to_matrix_4x4())[:3, :3]
        dx, dy = np.linalg.solve(linear, [dx, dy, 0.0])[:2]
    at = node.transform.position
    node.transform.position = Vec3(float(at.x) + float(dx), float(at.y) + float(dy), at.z)


class Anchor:
    """A place inside an inset, named in the source's own units. It acts as a pair ``(x, y)`` in scene units, y up,
    worked out when read, so it follows the inset when the inset moves, turns or changes width. A mark that holds one
    keeps that end on the place; ``Inset.move_to`` also moves the mark's text with the inset.

    ``inset.at(x, y, **options)`` makes one. ``options`` go to the fragment's ``place``."""

    def __init__(self, inset: "Inset", *point: float, **options: Any):
        self.inset, self.point, self.options = inset, point, options

    def xy(self) -> tuple[float, float]:
        inset = self.inset
        px, py = inset.fragment().place(*self.point, **self.options)
        wide, tall = inset.fragment().size_mm
        scale = inset._mm_per_unit
        dx, dy = (px - wide / 2.0) / scale, (tall / 2.0 - py) / scale
        turn = math.radians(float(inset.world_transform.rotation_deg.z))
        c, s = math.cos(turn), math.sin(turn)
        return (float(inset.world_position.x) + c * dx - s * dy, float(inset.world_position.y) + s * dx + c * dy)

    def __iter__(self):
        return iter(self.xy())

    def __getitem__(self, index):
        return self.xy()[index]

    def __len__(self) -> int:
        return 2

    def __repr__(self) -> str:
        return f"Anchor({self.point}, {self.options})" if self.options else f"Anchor({self.point})"


class Inset(Component):
    """A drawing set into a figure: a file, a plot, a section. It has no ports and draws in 2D only.

    Parameters
    ----------
    source : str, path or source, optional
        What the inset holds. A path ending in ``.svg`` is a file; none gives an empty dashed box.
    center : tuple
        The middle of the inset, y up.
    width : float
        Its width in scene units (mm on a page). The height follows the source, unless a free-shape source is given
        ``height``.
    height : float, optional
        For a source with no shape of its own, such as the empty box. A fixed-shape source refuses it.
    frame : bool
        Draw a white backing and a thin frame.
    opacity : float
        0 to 1: the backing, the drawing and the frame fade together, as one layer.
    over : optional
        What the inset stands over: it gets a white backing.
    letter : optional
        The panel letter, kept for the page.
    bar : tuple, optional
        ``(length, text)``: a white scale bar ``length`` long in the source's own units, with ``text`` over it, at the
        bottom left. It reads the source's ``place``, so it needs a map that is linear in x with no turn; a log axis
        raises ValueError.
    **source_options
        Go to the source, for example ``drop_text`` for a file.

    A saved page keeps the source's record and its last fragment, so it loads and exports with no source file. A
    loaded inset never rebuilds by itself: at a new width it scales the stored drawing, with a note. Only
    :meth:`rebuild` draws it again from the record.
    """

    component_type = "Inset"
    color: str = "#333333"
    anchor: str = "middle"
    bold: bool = False

    def __init__(self, source=None, center=(0, 0), width=50.0, *, height=None, angle=0.0, frame=False, over=None,
                 letter=None, bar=None, label="", opacity=1.0, **source_options):
        self._item, self._options = source, source_options
        self.width, self.height = float(width), None if height is None else float(height)
        self.opacity = float(opacity)
        self.frame, self.over, self.letter, self.bar = bool(frame), over, letter, bar
        self.label = str(label)
        self._mm_per_unit, self._font_pt = 1.0, 8.0
        self._cache: tuple[Any, Fragment] | None = None
        self._built: float | None | str = "never"
        self.links: list[Component] = []        # parts that go on a page with it: the marks of a cut
        self._build()
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def _build(self) -> None:
        """The source, made once for the print scale: a free-shape source takes the height in mm, so it is made again
        when that height changes. Until then the fragment cache holds."""

        tall = None if self.height is None else self.height * self._mm_per_unit
        if self._built == tall:
            return
        self._built = tall
        self.source = to_source(self._item, height=tall, **self._options)

    def set_print(self, mm_per_unit: float, font_pt: float) -> None:
        """Tell the inset the print scale: ``mm_per_unit`` mm on the page per scene unit, and the text size in
        points."""

        self._mm_per_unit, self._font_pt = float(mm_per_unit), float(font_pt)
        self._build()

    def _forget(self) -> None:
        """Forget the fragment of a live source, so the next draw asks the source again: a scene or a plot may have
        changed. ``Page.svg`` calls it at the start of each export; a framed scene export asks again at each new
        scale anyway. A saved drawing stays."""

        if not isinstance(self.source, _Stored):
            self._cache = None

    def fragment(self) -> Fragment:
        """The source's fragment at this width and print scale, worked out once per export (see :meth:`_forget`)."""

        key = (id(self.source), self.width, self.height, self._mm_per_unit, self._font_pt)
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, self._drawn(self.source))
        return self._cache[1]

    def _name(self) -> str:
        return f"the inset {self.label!r}" if self.label else "an inset"

    def _kind(self) -> str:
        """The class name of what the inset holds, also for a saved one: "SceneView", "Text"..."""

        return self.source.record.get("kind") if isinstance(self.source, _Stored) else type(self.source).__name__

    def _panel(self) -> bool:
        """False for words set in the figure (a Text or an Equation): their text is page text, not a panel's."""

        return self._kind() not in ("Text", "Equation")

    def _drawn(self, source: Any) -> Fragment:
        """The fragment ``source`` draws at this width and print scale. A scale bar needs the fragment's map: a saved
        page keeps the map, not ``place``, so a bar on a fragment with none is refused here."""

        fragment = source.fragment(self.width * self._mm_per_unit, font_pt=self._font_pt)
        if self.bar is not None and fragment.map is None:
            raise ValueError(f"{self._name()} has a scale bar, but its source keeps no map: a bar reads the map, so "
                             "give the fragment a map (see place_from) or leave the bar out")
        return fragment

    def rebuild(self) -> None:
        """Build the source again and draw it fresh, so a changed file or object shows. An inset loaded from a page
        file builds from its record; a frozen record (a matplotlib figure, an array, a section or an SEM render:
        inputs that are not data) raises ValueError. A file that is gone raises FileNotFoundError, and the inset keeps
        what it had."""

        item, options = self._item, self._options
        if isinstance(item, _Stored):
            if item.frozen:
                name = f" {self.label!r}" if self.label else ""
                raise ValueError(f"the inset{name} holds a frozen {item.record['kind']} record: its inputs are not "
                                 "data, so it cannot rebuild")
            item = from_record(item.record, item.base)
        tall = None if self.height is None else self.height * self._mm_per_unit
        source = to_source(item, height=tall, **options)
        fragment = self._drawn(source)
        self._item, self._built, self.source = item, tall, source
        self._cache = ((id(source), self.width, self.height, self._mm_per_unit, self._font_pt), fragment)

    def _saved(self, base: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """The source record and the fragment for a page file: paths relative to the folder ``base``, or absolute with
        none. The fragment is the source's, without the scale bar, which is laid over it again after a load. A record
        that was never built keeps no fragment, so it stays unbuilt."""

        if not getattr(self.source, "built", True):
            return rebased(self.source.to_record(), base), None
        fragment = self.fragment()
        record, frozen = record_of(self.source, fragment, self.width * self._mm_per_unit, self._font_pt, self._name())
        return rebased(record, base), self._kept(fragment, frozen)

    def _kept(self, fragment: Fragment, frozen: bool = False) -> dict[str, Any]:
        """``fragment`` as a page file keeps it, with the width and height asked in mm and the font it drew at."""

        tall = None if self.height is None else self.height * self._mm_per_unit
        return {**fragment_record(fragment), "frozen": frozen, "width_mm": self.width * self._mm_per_unit,
                "height_mm": tall, "font_pt": self._font_pt}

    def at(self, *point: float, **options: Any) -> Anchor:
        """An :class:`Anchor` on a place in the source: ``inset.at(10, 5)`` in the source's own units."""

        return Anchor(self, *point, **options)

    def cut(self, a: Any, b: Any, *, name: str = "A", z: Any = None, z_scale: Any = "auto",
            **placement: Any) -> "Inset":
        """A new inset with the cross-section along ``a`` to ``b`` (file points in um, inside the region) of this
        inset's GDS file and stack. Its window is the whole cut, so its ends are ``a`` and ``b``. ``z=(z0, z1)``
        crops the height. ``z_scale`` is the section's: ``"auto"`` stretches z only when the thinnest film needs it,
        a number stretches z by that much (1 is true aspect). ``placement`` takes the Inset arguments (``center``,
        ``width``, ``frame``, ``letter``, ``over``).

        The new inset carries a :class:`CutLink` in ``links``: ``name`` and ``name′`` at the ends of the cut line and
        over the two top corners of the section. ``page.add`` adds it too; in a plain scene, add ``links[0]`` by
        hand."""

        from optodraw.figure.sources import GdsView, cut_section

        view = self.source
        if not isinstance(view, GdsView):
            raise TypeError(f"cut works on an inset of a live GdsView (a loaded one after rebuild()), not of a "
                            f"{self._kind()}")
        x0, y0, x1, y1 = view.region
        ends = []
        for point in (a, b):
            x, y = (float(v) for v in point)
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                raise ValueError(f"the cut end ({x:g}, {y:g}) leaves the region ({x0:g}, {y0:g}, {x1:g}, {y1:g})")
            ends.append((x, y))
        section = Inset(cut_section(view.path, view.stack, (ends[0], ends[1]), z, view.cell_name, z_scale=z_scale),
                        **placement)
        section.links = [CutLink(self, ends[0], ends[1], section, name)]
        return section

    def show_cut(self, section: "Inset", height: float | None = None, *, name: str = "A") -> "CutLink":
        """The cut of ``section`` (an inset of a section made by :meth:`cut` or ``cut_section``) drawn on this inset
        of a :meth:`View3D.chip`: a dashed line between the two cut ends at ``height`` (true um; by default the top of
        the chip as drawn), with ``name`` and ``name′`` past its ends. The section's top corners get the letters too,
        unless a cut on a GDS inset marks them already. Add the returned link to the page."""

        from optodraw.figure.sources import SectionView
        from optodraw.figure.view3d import View3D

        view, source = self.source, section.source
        if not (isinstance(view, View3D) and view._chip is not None):
            raise TypeError(f"show_cut works on an inset of a live View3D.chip, not of a {self._kind()}")
        cut = source.xs.source.get("cut") if isinstance(source, SectionView) else None
        if cut is None:
            raise TypeError("show_cut takes an inset of a live section made along a cut (Inset.cut or cut_section)")
        z = view._top() if height is None else float(height)
        (ax, ay), (bx, by) = cut
        marked = any(isinstance(link, CutLink) and link.section is section for link in section.links)
        return CutLink(self, (ax, ay, z), (bx, by, z), None if marked else section, name)

    def move_to(self, x: float, y: float) -> None:
        """Move the inset to ``(x, y)`` in scene coordinates. Every mark that holds an anchor of this inset moves by
        the same step, so its text keeps its place beside the inset. Marks of another inset stay."""

        old = self.world_position
        step = (float(x) - float(old.x), float(y) - float(old.y))
        _shift(self, step)
        root = self
        while root._parent is not None:
            root = root._parent
        walk = getattr(root, "walk", None)
        for node in (walk() if walk else ()):
            if any(a.inset is self for a in getattr(node, "_anchors", lambda: ())()):
                _shift(node, step)
                after = getattr(node, "_moved", None)
                if after:
                    after(step)

    @property
    def w_mm(self) -> float:
        return self.fragment().size_mm[0]

    @property
    def h_mm(self) -> float:
        return self.fragment().size_mm[1]

    def _size(self) -> tuple[float, float]:
        """The drawn width and height, in scene units."""

        wide, tall = self.fragment().size_mm
        return wide / self._mm_per_unit, tall / self._mm_per_unit

    def ports(self) -> dict[str, Any]:
        return {}

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        wide, tall = self._size()
        fragment = self.fragment()
        children: list[dict[str, Any]] = []
        if self.frame or self.over is not None:
            children.append({"type": "rect", "w": wide, "h": tall, "cx": 0.0, "cy": 0.0, "fill": "#ffffff",
                             "stroke": "none", "stroke_width": 0})
        children.append({"type": "fragment", "svg": self._with_bar(fragment), "w": wide, "h": tall,
                         "kind": fragment.kind, "mm": fragment.size_mm[0], "panel": self._panel()})
        if self.frame:                                  # over the drawing, so an opaque one hides no half of the line
            children.append({"type": "rect", "w": wide, "h": tall, "cx": 0.0, "cy": 0.0, "fill": "none",
                             "stroke": self.color, "stroke_width": FRAME_MM / self._mm_per_unit})
        return {"type": "group", "children": children}

    def _with_bar(self, fragment: Fragment) -> str:
        """The fragment's SVG with the scale bar laid over it: a white rect as long as ``length`` is on the page, its
        text over it, both on a thin dark plate, at the bottom left above the source's own strip. The overlay is a
        nested root in mm, so its text prints at the page font whatever the print scale."""

        if self.bar is None or not getattr(self.source, "built", True):        # an unbuilt record: an empty box
            return fragment.svg
        import html

        from optodraw.core.markup import text_width
        from optodraw.figure.page import FONT_FAMILY

        length, text = self.bar
        if not float(length) > 0.0:
            raise ValueError(f"{self._name()}: a scale bar has a length above 0, got {length!r}")
        try:
            a, b, c = (fragment.place(1.0 + k * float(length), 1.0) for k in range(3))
        except (ValueError, ArithmeticError) as exc:
            raise ValueError(f"{self._name()}: a scale bar needs a source with a linear x scale: {exc}") from exc
        steps = [(b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])]
        long = abs(steps[0][0])
        if not all(math.isfinite(v) for step in steps for v in step) or long == 0.0 or any(
                abs(step[0] - steps[0][0]) > 1e-6 * long or abs(step[1]) > 1e-6 * long for step in steps):
            raise ValueError(f"{self._name()}: a scale bar needs a source with a linear x scale and no turn (a log "
                             "axis has neither)")
        wide, tall = fragment.size_mm
        margin, thick = (max(BAR_FLOOR_MM[i], BAR_SHARE[i] * wide) for i in (0, 1))
        size = self._font_pt * PT_MM
        pad = 0.4 * size
        left, bottom = margin, tall - fragment.floor_mm - margin          # mm from the top left, y down
        base = bottom - thick - 0.3 * size                                # the text's baseline
        plate_w = max(long, text_width(str(text), size)) + 2.0 * pad
        plate = (left - pad, base - size - pad, plate_w, bottom + pad - (base - size - pad))
        root = _root(fragment.svg, "the fragment")
        overlay = (f'<svg x="{root.origin[0]:g}" y="{root.origin[1]:g}" width="{root.size[0]:g}" '
                   f'height="{root.size[1]:g}" viewBox="0 0 {wide:.6g} {tall:.6g}" preserveAspectRatio="none">'
                   f'<rect x="{plate[0]:.4f}" y="{plate[1]:.4f}" width="{plate[2]:.4f}" height="{plate[3]:.4f}" '
                   f'fill="#000000" fill-opacity="{PLATE_ALPHA}" stroke="none"/>'
                   f'<rect x="{left:.4f}" y="{bottom - thick:.4f}" width="{long:.4f}" height="{thick:.4f}" '
                   f'fill="#ffffff" stroke="none"/>'
                   f'<text x="{left:.4f}" y="{base:.4f}" font-family="{FONT_FAMILY}" font-size="{size:.4f}" '
                   f'fill="#ffffff">{html.escape(str(text))}</text></svg>')
        return root.close(f"{wide:.6g}mm", f"{tall:.6g}mm")[:-len("</svg>")] + overlay + "</svg>"

    def geometry_2d(self) -> dict[str, Any]:
        return self.annotation_2d()

    def drawn_points(self) -> list[tuple[float, float]]:
        """The four corners in the world, turned with the part."""

        wide, tall = self._size()
        turn = math.radians(float(self.world_transform.rotation_deg.z))
        c, s = math.cos(turn), math.sin(turn)
        x0, y0 = float(self.world_position.x), float(self.world_position.y)
        return [(x0 + c * dx - s * dy, y0 + s * dx + c * dy) for dx, dy in
                ((-wide / 2, -tall / 2), (wide / 2, -tall / 2), (wide / 2, tall / 2), (-wide / 2, tall / 2))]

    def box(self) -> tuple[float, float, float, float]:
        """``(x0, y0, x1, y1)`` around the inset in the world, y up."""

        points = self.drawn_points()
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)


KIND_WORDS = {"SceneView": "scene", "SectionView": "section", "Plot": "plot", "Image": "picture",
              "SemView": "SEM render", "SvgFile": "SVG file", "PdfFile": "PDF file", "Text": "text",
              "Equation": "equation", "EmptyBox": "empty box", "Timing": "timing diagram", "GdsView": "GDS view"}

#: Each link part, and the keys that name the two insets it joins: a page file saves them as ids, and a link goes
#: when one of its insets leaves.
LINK_ENDS = {"ZoomLink": ("small", "big"), "CutLink": ("source", "section")}


def views_note(scene: Any, view: str) -> str:
    """The note a 1D or 3D ``view`` shows for the insets it leaves out, each by its label or the kind it holds. An
    inset draws in 2D only. Empty when the scene has none."""

    insets = [node for node in scene.walk() if isinstance(node, Inset)]
    if not insets:
        return ""
    names = ", ".join(node.label or KIND_WORDS.get(node._kind(), "inset") for node in insets)
    count = "1 inset" if len(insets) == 1 else f"{len(insets)} insets"
    return f"Not in {view}: {count} ({names}). An inset draws in the 2D view only."


def _facing_corners(box: tuple[float, ...], panel: tuple[float, ...]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The two lines from ``box`` to ``panel``, each x, y, width, height on the page: on the sides that face."""

    x, y, w, h = box
    px, py, pw, ph = panel
    if px >= x + w:
        return (x + w, y, px, py), (x + w, y + h, px, py + ph)
    if px + pw <= x:
        return (x, y, px + pw, py), (x, y + h, px + pw, py + ph)
    if py >= y + h:
        return (x, y + h, px, py), (x + w, y + h, px + pw, py)
    return (x, y, px, py + ph), (x + w, y, px + pw, py + ph)


class ZoomLink(Component):
    """A box on one inset, a matching frame on a second inset that shows it closer, and two grey lines that join them.
    It has no ports and draws in 2D only. The box, the frame and the lines are worked out from the live places of both
    insets at each render, so they follow a move, a turn or a new width.

    Parameters
    ----------
    small : Inset
        The inset the box stands on.
    region : tuple or Component
        ``(x0, y0, x1, y1)`` in the units of ``small.at``, or a part of the scene in a 2D scene inset (its world box).
        A part on any other inset raises ValueError: its world box is not in that inset's units.
    big : Inset
        The inset that shows the region closer.

    ``ZoomLink()`` with no arguments builds and draws nothing."""

    component_type = "ZoomLink"
    color: str = "#777777"
    anchor: str = "middle"
    bold: bool = False

    def __init__(self, small=None, region=None, big=None, *, center=(0, 0), angle=0.0, label=""):
        super().__init__()
        self.small, self.big, self.label = small, big, str(label)
        source = getattr(small, "source", None)
        if isinstance(region, Component) and not (isinstance(source, SceneView) and source.view == "2d"):
            raise ValueError("a part names a place on a 2D scene: give (x0, y0, x1, y1) in the panel's own units")
        self.region = None if region is None else self._region(region)
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        if self.small is not None and self.region is not None:
            self._corners()

    @staticmethod
    def _region(region: Any) -> tuple[float, float, float, float]:
        if isinstance(region, Component):
            region = region.drawn_box()
        x0, y0, x1, y1 = (float(value) for value in region)
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"the zoom region ({x0:g}, {y0:g}, {x1:g}, {y1:g}) is empty: give x0, y0, x1, y1")
        return x0, y0, x1, y1

    def _live(self) -> bool:
        return self.small is not None and self.big is not None and self.region is not None

    def _corners(self) -> list[tuple[float, float]]:
        """The region's four corners on the page, worked out now through ``small.at``. A corner that falls off the
        inset raises ValueError."""

        x0, y0, x1, y1 = self.region
        corners = [self.small.at(x, y).xy() for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        wide, tall = self.small._size()
        turn = math.radians(float(self.small.world_transform.rotation_deg.z))
        c, s = math.cos(turn), math.sin(turn)
        ox, oy = float(self.small.world_position.x), float(self.small.world_position.y)
        slack = 1e-6 * max(wide, tall, 1.0)
        for x, y in corners:
            dx, dy = x - ox, y - oy
            if abs(c * dx + s * dy) > wide / 2.0 + slack or abs(c * dy - s * dx) > tall / 2.0 + slack:
                raise ValueError(f"the zoom region ({x0:g}, {y0:g}, {x1:g}, {y1:g}) leaves the panel it looks at")
        return corners

    def _anchors(self) -> list[Any]:
        return []

    def ports(self) -> dict[str, Any]:
        return {}

    def _lines(self, corners: list[tuple[float, float]]) -> list[tuple[float, float, float, float]]:
        """The two lines, ``(x1, y1, x2, y2)`` in the world, y up, from the box's page bounds to ``big``."""

        xs, ys = [p[0] for p in corners], [p[1] for p in corners]
        bx0, by0, bx1, by1 = self.big.box()
        box = (min(xs), -max(ys), max(xs) - min(xs), max(ys) - min(ys))
        place = (bx0, -by1, bx1 - bx0, by1 - by0)
        return [(x1, -y1, x2, -y2) for x1, y1, x2, y2 in _facing_corners(box, place)]     # it reads y down

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        if not self._live():
            return {"type": "group", "children": []}
        from optodraw.publication import ZOOM_COLOR, ZOOM_DASH_MM, ZOOM_LINE_MM

        corners = self._corners()
        px, py = float(self.world_position.x), float(self.world_position.y)
        scale = self.small._mm_per_unit                     # mm on the page per scene unit, as the insets print
        look = {"stroke": ZOOM_COLOR, "stroke_width": ZOOM_LINE_MM / scale,
                "stroke_dasharray": " ".join(f"{float(v) / scale:.6g}" for v in ZOOM_DASH_MM.split())}
        children = [{"type": "polygon", "points": [(x - px, y - py) for x, y in points], **look}
                    for points in (corners, self.big.drawn_points())]          # the box, then the frame on big
        children += [{"type": "line", "x1": a - px, "y1": b - py, "x2": c - px, "y2": d - py, "part": "zoom", **look}
                     for a, b, c, d in self._lines(corners)]
        return {"type": "group", "part": "zoom", "children": children}

    def geometry_2d(self) -> dict[str, Any]:
        return self.annotation_2d()

    def drawn_points(self) -> list[tuple[float, float]]:
        """The box corners, the corners of the frame on ``big`` and the line ends in the world: the frame holds them."""

        if not self._live():
            return []
        corners = self._corners()
        return (corners + self.big.drawn_points()
                + [p for a, b, c, d in self._lines(corners) for p in ((a, b), (c, d))])


class CutLink(Component):
    """The marks of a cut: a line from ``a`` to ``b`` on a GDS inset, ``name`` and ``name′`` past its two ends, and the
    same letters over the two top corners of the section the cut made. It keeps no place of its own: each render reads
    the live places of both insets, so the marks stay on the cut ends when either inset moves or changes width, and
    after a load. A letter that would sit on a box in ``keep_clear`` (the panel letters, which a :class:`Page` sets
    before each draw; x0, y0, x1, y1 in the world, y up) moves right, past it. It has no ports and draws in 2D only.
    :meth:`Inset.cut` makes it.

    On a 3D chip inset (:meth:`Inset.show_cut`) each end is ``(x, y, height)`` and the line is dashed: it floats over
    the drawing. With no ``section`` it marks the line only.

    ``CutLink()`` with no arguments draws nothing."""

    component_type = "CutLink"
    color: str = "#777777"
    anchor: str = "middle"
    bold: bool = False

    def __init__(self, source=None, a=None, b=None, section=None, name="A", *, center=(0, 0), angle=0.0, label=""):
        super().__init__()
        self.source, self.section, self.name, self.label = source, section, str(name), str(label)
        self.a, self.b = (None if p is None else tuple(float(v) for v in p) for p in (a, b))
        self.keep_clear: list[tuple[float, float, float, float]] = []
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)

    def _live(self) -> bool:
        return None not in (self.source, self.a, self.b)

    def _anchors(self) -> list[Any]:
        return []

    def ports(self) -> dict[str, Any]:
        return {}

    def _size(self) -> float:
        """The letter height in scene units: the page's font_pt."""

        return self.source._font_pt * PT_MM / self.source._mm_per_unit

    def _places(self) -> list[tuple[float, float]]:
        """The two cut ends on the source inset and the two top corners of the section plot (with a section), in the
        world, y up, read now from the live places of both insets."""

        ends = [self.source.at(*self.a).xy(), self.source.at(*self.b).xy()]
        if self.section is None:
            return ends
        shape = self.section.fragment().map or {}
        while shape.get("form") == "scaled":                # a saved section drawn at a new width
            shape = shape.get("map") or {}
        top = float(shape.get("z1", 0.0))                   # a saved section never built has no frame
        return ends + [self.section.at(0.0, top).xy(), self.section.at(math.dist(self.a[:2], self.b[:2]), top).xy()]

    def _letters(self, places: list[tuple[float, float]]) -> list[tuple[str, float, float]]:
        """``(text, x, y)`` of the letters, centred: one height past each line end, and one height over each section
        corner, each moved right past a box in ``keep_clear`` it would sit on."""

        from optodraw.core.markup import text_width

        (ax, ay), (bx, by) = places[:2]
        size = self._size()
        run = math.hypot(bx - ax, by - ay) or 1.0
        ux, uy = (bx - ax) / run * size, (by - ay) / run * size
        first, second = self.name, f"{self.name}′"
        letters = [(first, ax - ux, ay - uy), (second, bx + ux, by + uy)]
        if len(places) == 4:                                # a section on the page: its two corners too
            (lx, ly), (rx, ry) = places[2:]
            letters += [(first, lx, ly + size), (second, rx, ry + size)]
        out = []
        for text, x, y in letters:
            half = text_width(text, size) / 2.0
            for x0, y0, x1, y1 in sorted(self.keep_clear):
                if x - half < x1 and x + half > x0 and y - size / 2.0 < y1 and y + size / 2.0 > y0:
                    x = x1 + CLEAR_GAP * size + half
            out.append((text, x, y))
        return out

    def annotation_2d(self, scale: float = 1.0) -> dict[str, Any]:
        if not self._live():
            return {"type": "group", "children": []}
        from optodraw.publication import CUT_COLOR, CUT_LINE_MM, ZOOM_DASH_MM

        places = self._places()
        px, py = float(self.world_position.x), float(self.world_position.y)
        (ax, ay), (bx, by) = places[:2]
        mm = self.source._mm_per_unit
        dash = ({"stroke_dasharray": " ".join(f"{float(v) / mm:.6g}" for v in ZOOM_DASH_MM.split())}
                if len(self.a) == 3 else {})                # a cut over a 3D view floats over the drawing
        children = [{"type": "line", "x1": ax - px, "y1": ay - py, "x2": bx - px, "y2": by - py, "part": "cut",
                     "stroke": CUT_COLOR, "stroke_width": CUT_LINE_MM / mm, **dash}]
        children += [{"type": "text", "text": text, "x": x - px, "y": y - py, "size": 3.0, "fill": CUT_COLOR,
                      "text_anchor": "middle"} for text, x, y in self._letters(places)]      # 3 prints at font_pt
        return {"type": "group", "part": "cut", "children": children}

    def geometry_2d(self) -> dict[str, Any]:
        return self.annotation_2d()

    def drawn_points(self) -> list[tuple[float, float]]:
        """The line ends and the box of each letter in the world: the frame holds them."""

        if not self._live():
            return []
        places, size = self._places(), self._size()
        points = places[:2]
        for text, x, y in self._letters(places):
            half = 0.31 * size * len(text)                  # 0.62 of the height per letter, as the label gate
            points += [(x - half, y - size / 2.0), (x + half, y + size / 2.0)]
        return points
