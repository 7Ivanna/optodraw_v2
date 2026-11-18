"""``Page``: a scene in mm, origin lower left, y up, that prints at its exact size.

``optodraw.publication`` builds ``export_panels`` on this module, so the two import each other inside functions only.
"""

from __future__ import annotations

import html
import math
import re
from pathlib import Path
from typing import Any, Iterable

from optodraw.core.scene import Scene
from optodraw.figure.fragment import PT_MM
from optodraw.figure.inset import CutLink, Inset, ZoomLink

FONT_FAMILY = "Helvetica, Arial, sans-serif"
LETTER_BAND = 1.2                       # the band above an inset that holds its letter, in letter heights
ROW_PASSES = 5                          # a scene's shape changes a little with its width: a row sizes it this often


class Page(Scene):
    """A figure page: a :class:`Scene` in mm that prints at its exact size.

    Parameters
    ----------
    width_mm, height_mm : float
        The size on paper. Without ``height_mm`` the page is as tall as its content (letters included); a height of 0
        or less raises ValueError.
    font_pt : float
        The text size on paper, for every label and every source optodraw draws.
    letters : bool
        Put a bold panel letter above each inset, in reading order. An inset with its own ``letter`` keeps it whatever
        this says; ``letter=""`` leaves one out and takes no slot. Past 26 insets, set the letters by hand.
    letter_pt : float
        The size of the letters.
    """

    def __init__(self, width_mm: float = 183.0, height_mm: float | None = None, font_pt: float = 7.0,
                 title: str = "Figure", letters: bool = True, letter_pt: float = 8.0):
        if height_mm is not None and not float(height_mm) > 0.0:
            raise ValueError(f"height_mm is a size above 0 in mm, or None for a page as tall as its content; got "
                             f"{height_mm!r}")
        super().__init__(title=title, width=float(width_mm), height=float(height_mm or 0.0), platform="mixed")
        self.width_mm = float(width_mm)
        self.height_mm = None if height_mm is None else float(height_mm)
        self.font_pt, self.letters, self.letter_pt = float(font_pt), bool(letters), float(letter_pt)

    @classmethod
    def from_template(cls, template: Any, scenes: Iterable[Any], *, width_mm: float, font_pt: float = 7.0,
                      view: str = "2d", polarization: bool = False) -> "Page":
        """A page that lays out a :class:`~optodraw.TemplateSpec`: ``scenes[i]`` goes to ``template.panels[i]``. Panels
        with the same ``row`` make one :meth:`row`, in ``column`` order, and each takes its ``width_fraction`` of the
        row. The panel's ``label`` is the letter of its inset, as given (``""`` leaves it out). A scene is drawn in
        ``view`` (``"2d"`` or ``"1d"``), with the polarization states if ``polarization``; any other item is an
        :class:`Inset` source as it is. ``role`` and ``height_fraction`` have no counterpart: the panels of a row share
        one height, so each row is as tall as its drawings need."""

        panels, items = list(template.panels), list(scenes)
        if len(items) != len(panels):
            raise ValueError(f"{len(items)} scenes for {len(panels)} panels of template {template.name!r}")
        page = cls(width_mm=width_mm, font_pt=font_pt, title=template.name)

        def inset(index: int) -> Inset:
            item = items[index]
            if isinstance(item, Inset):
                return item
            options = {"view": view, "polarization": polarization} if isinstance(item, Scene) else {}
            return Inset(item, letter=panels[index].label, **options)

        for number in sorted({panel.row for panel in panels}):
            row = sorted((i for i, panel in enumerate(panels) if panel.row == number), key=lambda i: panels[i].column)
            page.row([inset(i) for i in row], shares=[panels[i].width_fraction for i in row])
        return page

    def add(self, component: Any) -> Any:
        """Add ``component``, then the parts it carries in ``links`` right after it: the marks of a cut from
        :meth:`Inset.cut`. The saved order (source, section, marks) lets a load find each inset a mark names."""

        added = super().add(component)
        for link in getattr(component, "links", ()):
            super().add(link)
        return added

    def _render_pt(self) -> float:
        """The renderer's text size that prints at ``font_pt`` on the page (it reads 8 as 3 units)."""

        return self.font_pt * PT_MM * 8.0 / 3.0

    def _insets(self) -> list[Inset]:
        found = [node for node in self.walk() if isinstance(node, Inset)]
        for inset in found:
            inset.set_print(1.0, self.font_pt)
        return found

    def _letters(self, insets: list[Inset]) -> list[tuple[str, float, float]]:
        """``(letter, x, y)`` for each lettered inset: the left edge and the baseline, y up, in reading order. An inset
        joins the row above it when it overlaps the row's span by more than half of the smaller of the two heights. A
        row reads left to right (the higher first at one left edge: the sort keeps the order of the tops); the rows run
        top to bottom."""

        size = self.letter_pt * PT_MM
        rows: list[list[Inset]] = []
        low = high = 0.0                              # the span of the row being filled
        for inset in sorted((i for i in insets if i.over is None), key=lambda i: -i.box()[3]):
            _, y0, _, y1 = inset.box()
            if rows and min(y1, high) - max(y0, low) > 0.5 * min(y1 - y0, high - low) + 1e-6:
                rows[-1].append(inset)
                low, high = min(low, y0), max(high, y1)
            else:
                rows.append([inset])
                low, high = y0, y1
        marks = []
        count = 0
        for inset in (i for row in rows for i in sorted(row, key=lambda i: round(i.box()[0], 3))):
            if inset.letter == "":                    # left out: it takes no slot
                continue
            if inset.letter is None and self.letters and count >= 26:
                raise ValueError("a page letters 26 insets a to z: set the letters of the others by hand with "
                                 "letter=, or leave them out with letter=\"\"")
            letter = inset.letter if inset.letter is not None else chr(97 + count) if self.letters else ""
            count += 1
            if letter:
                x0, _, _, y1 = inset.box()
                marks.append((str(letter), x0, y1 + (LETTER_BAND - 1.0) * size))
        return marks

    def _extent(self, insets: list[Inset]) -> tuple[float, float]:
        """The page's bottom and top edge, y up: ``0`` and ``height_mm`` when given, else from the lower of ``0`` and
        the content bottom to the content top (the text of labels and marks and the letters included)."""

        from optodraw.check import _label_box
        from optodraw.publication import _labelled

        if self.height_mm is not None:
            return 0.0, self.height_mm
        _, bottom, _, top = (float(v) for v in self.content_bounds())
        boxes = [_label_box(node, self._render_pt()) for node in _labelled(self)]
        top = max([top] + [box[3] for box in boxes])
        bottom = min([0.0, bottom] + [i.box()[1] for i in insets] + [box[1] for box in boxes])
        size = self.letter_pt * PT_MM
        for _, _, y in self._letters(insets):
            top = max(top, y + size)             # the baseline sits 0.2 letter heights over the inset
        return bottom, top

    def _clear_cuts(self, marks: list[tuple[str, float, float]]) -> None:
        """Give each cut link the box of each panel letter in ``marks``, y up, as check_export reads it, so the cut
        letters keep clear of them."""

        from optodraw.core.markup import text_width

        size = self.letter_pt * PT_MM
        boxes = [(x, y - 0.2 * size, x + text_width(letter, size), y + 0.75 * size) for letter, x, y in marks]
        for node in self.walk():
            if isinstance(node, CutLink):
                node.keep_clear = boxes

    def svg(self) -> str:
        """The page as SVG text: ``width_mm`` by its height on paper, one user unit per mm. Each live source (not one
        loaded from a page file) is asked once, so a scene or a plot changed since the last export shows."""

        insets = self._insets()
        for inset in insets:
            inset._forget()
        marks = self._letters(insets)
        self._clear_cuts(marks)
        bottom, top = self._extent(insets)
        wide, tall = self.width_mm, top - bottom
        render_pt = self._render_pt()
        saved = self.width, self.height, self.frame_center
        self.width, self.height, self.frame_center = wide, tall, (wide / 2.0, (top + bottom) / 2.0)
        try:
            svg = self.render_svg(font_size_pt=render_pt).as_svg()
        finally:
            self.width, self.height, self.frame_center = saved
        root = re.search(r"<svg\b[^>]*>", svg).group(0)
        fitted = re.sub(r'\s(width|height|viewBox|font-family)="[^"]*"', "", root)
        tall = math.ceil(tall * 100.0 - 1e-6) / 100.0    # the printed height, up: the view box takes it, scale 1
        fitted = fitted[:-1] + (f' width="{wide:g}mm" height="{tall:.2f}mm" '
                                f'viewBox="0 {-top:.4f} {wide:.4f} {tall:.4f}" font-family="{FONT_FAMILY}">')
        size = self.letter_pt * PT_MM
        letters = "".join(f'<text x="{x:.3f}" y="{-y:.3f}" font-family="{FONT_FAMILY}" font-size="{size:.3f}" '
                          f'font-weight="bold" fill="#000000">{html.escape(letter)}</text>'
                          for letter, x, y in marks)
        svg = svg.replace(root, fitted, 1)
        return svg[:svg.rindex("</svg>")] + letters + "</svg>\n" if letters else svg

    def export(self, path: str | Path, *, formats: Iterable[str] = ("svg", "pdf", "png"),
               dpi: float = 800.0) -> dict[str, Path]:
        """Write the page next to ``path`` (the name without its suffix), one file per format. PDF and PNG need
        ``pip install optodraw[figure]``. Returns the path of each format."""

        from optodraw.publication import _figure_formats, _write_figure

        wanted = _figure_formats(formats)
        return _write_figure(self.svg(), path, wanted, width_mm=self.width_mm, dpi=dpi)

    def row(self, items: Iterable[Any], *, top: float | None = None, shares: Iterable[float | None] | None = None,
            gap_mm: float = 2.0, x: float = 0.0) -> list[Inset]:
        """Lay ``items`` in a row from ``x``, their top edges at ``top`` (y up). With no ``shares`` they share one
        height and fill the page width; ``shares`` give a part of that width to a panel, and the others share what is
        left. When the row draws a letter, ``top`` is the top of the letter band (1.2 letter heights) and the insets sit
        under it. With no ``top`` the row goes ``gap_mm`` under the lowest inset already on the page (at 0 on a page
        with none); an inset with ``over=`` floats and does not count. An item that is not an :class:`Inset` becomes
        one. Returns the insets."""

        from optodraw.publication import _row_sizes

        insets = [item if isinstance(item, Inset) else Inset(item) for item in items]
        shares = list(shares) if shares is not None else [None] * len(insets)
        if len(shares) != len(insets):
            raise ValueError(f"{len(shares)} shares for {len(insets)} items")
        for inset in insets:
            inset.set_print(1.0, self.font_pt)
        if top is None:
            below = [n.box()[1] for n in self._insets() if n.over is None and n not in insets]
            top = min(below) - gap_mm if below else 0.0
        room = self.width_mm - x - gap_mm * (len(insets) - 1)
        for _ in range(ROW_PASSES):                # the heights agree to about 1 um after five passes
            slots = _row_sizes([(i.w_mm, i.h_mm) for i in insets], shares, room)
            for inset, (wide, _) in zip(insets, slots):
                inset.width = wide
        lettered = any(i.over is None and i.letter != "" and (self.letters or i.letter is not None) for i in insets)
        top -= LETTER_BAND * self.letter_pt * PT_MM if lettered else 0.0
        left = float(x)
        for inset, (wide, tall) in zip(insets, slots):
            inset.width = wide
            if inset not in list(self.walk()):
                self.add(inset)
            inset.set_print(1.0, self.font_pt)
            inset.move_to(left + wide / 2.0, top - inset.h_mm / 2.0)
            left += wide + gap_mm
        return insets

    def zoom(self, small: Inset, region: Any, big: Inset) -> ZoomLink:
        """Draw a box on ``small``, a matching frame on ``big``, which shows it closer, and two lines between them.
        ``region`` is ``(x0, y0, x1, y1)`` in the units of ``small.at``, or a part of the scene in a 2D scene inset.
        Both insets must be on the page. The link is worked out at each render, so it follows both insets when they
        move."""

        for inset in (small, big):
            if inset not in list(self.walk()):
                raise ValueError("the inset a zoom joins is not on the page")
            inset.set_print(1.0, self.font_pt)
        return self.add(ZoomLink(small, region, big))
