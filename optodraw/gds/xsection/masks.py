"""Boolean mask DSL and layout-cut → y-interval masks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from optodraw.gds.layout import GDSLayout, GDSSection
from optodraw.gds.mesh import _coerce_section, _iter_simple_geometries, _require_shapely_geometry
from optodraw.gds.xsection.schema import ProcessDefinition


@dataclass(frozen=True)
class Interval:
    y0: float
    y1: float

    def __post_init__(self) -> None:
        if self.y1 < self.y0:
            y0, y1 = self.y0, self.y1
            object.__setattr__(self, "y0", y1)
            object.__setattr__(self, "y1", y0)

    @property
    def width(self) -> float:
        return self.y1 - self.y0

    def overlaps(self, other: Interval, *, eps: float = 1e-9) -> bool:
        return self.y1 > other.y0 + eps and other.y1 > self.y0 + eps


@dataclass
class IntervalSet:
    intervals: list[Interval] = field(default_factory=list)

    @classmethod
    def from_intervals(cls, values: Iterable[tuple[float, float]]) -> IntervalSet:
        items = [Interval(float(y0), float(y1)) for y0, y1 in values if abs(float(y1) - float(y0)) > 1e-9]
        return cls(intervals=_normalize(items))

    @classmethod
    def full(cls, y_min: float, y_max: float) -> IntervalSet:
        return cls.from_intervals([(y_min, y_max)])

    def union(self, other: IntervalSet) -> IntervalSet:
        return IntervalSet(intervals=_normalize([*self.intervals, *other.intervals]))

    def intersection(self, other: IntervalSet) -> IntervalSet:
        result: list[Interval] = []
        for left in self.intervals:
            for right in other.intervals:
                y0 = max(left.y0, right.y0)
                y1 = min(left.y1, right.y1)
                if y1 - y0 > 1e-9:
                    result.append(Interval(y0, y1))
        return IntervalSet(intervals=_normalize(result))

    def difference(self, other: IntervalSet) -> IntervalSet:
        current = self.intervals
        for subtrahend in other.intervals:
            next_current: list[Interval] = []
            for interval in current:
                next_current.extend(_subtract_interval(interval, subtrahend))
            current = _normalize(next_current)
        return IntervalSet(intervals=current)

    def complement(self, y_min: float, y_max: float) -> IntervalSet:
        full = IntervalSet.full(y_min, y_max)
        return full.difference(self)

    def is_empty(self) -> bool:
        return not self.intervals

    def total_width(self) -> float:
        return sum(item.width for item in self.intervals)


def _normalize(intervals: list[Interval]) -> list[Interval]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: item.y0)
    merged: list[Interval] = [ordered[0]]
    for item in ordered[1:]:
        last = merged[-1]
        if item.y0 <= last.y1 + 1e-9:
            merged[-1] = Interval(last.y0, max(last.y1, item.y1))
        else:
            merged.append(item)
    return merged


def _subtract_interval(base: Interval, cut: Interval) -> list[Interval]:
    if not base.overlaps(cut):
        return [base]
    pieces: list[Interval] = []
    if cut.y0 > base.y0 + 1e-9:
        pieces.append(Interval(base.y0, cut.y0))
    if cut.y1 < base.y1 - 1e-9:
        pieces.append(Interval(cut.y1, base.y1))
    return pieces


class MaskExpression:
    """Parse mask strings like ``SLAB & ~RIB`` against named layer interval sets."""

    def __init__(self, expression: str):
        self.expression = expression.strip()
        self._tokens = _tokenize(self.expression)

    def evaluate(self, layers: dict[str, IntervalSet], *, y_min: float, y_max: float) -> IntervalSet:
        index = 0

        def parse_expr() -> IntervalSet:
            nonlocal index
            node = parse_term()
            while index < len(self._tokens) and self._tokens[index] == "|":
                index += 1
                node = node.union(parse_term())
            return node

        def parse_term() -> IntervalSet:
            nonlocal index
            node = parse_factor()
            while index < len(self._tokens) and self._tokens[index] == "&":
                index += 1
                node = node.intersection(parse_factor())
            return node

        def parse_factor() -> IntervalSet:
            return parse_unary()

        def parse_unary() -> IntervalSet:
            nonlocal index
            if index < len(self._tokens) and self._tokens[index] == "~":
                index += 1
                return parse_unary().complement(y_min, y_max)
            if index < len(self._tokens) and self._tokens[index] == "(":
                index += 1
                node = parse_expr()
                if index >= len(self._tokens) or self._tokens[index] != ")":
                    raise ValueError(f"Unmatched parenthesis in mask expression: {self.expression!r}")
                index += 1
                return node
            if index >= len(self._tokens):
                raise ValueError(f"Unexpected end of mask expression: {self.expression!r}")
            token = self._tokens[index]
            index += 1
            if token not in layers:
                return IntervalSet()
            return layers[token]

        result = parse_expr()
        if index != len(self._tokens):
            raise ValueError(f"Unexpected token {self._tokens[index]!r} in mask expression")
        return result


def _tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(expression):
        char = expression[index]
        if char.isspace():
            index += 1
            continue
        if char in "&|~()":
            tokens.append(char)
            index += 1
            continue
        start = index
        while index < len(expression) and (expression[index].isalnum() or expression[index] in "_-"):
            index += 1
        if start == index:
            raise ValueError(f"Invalid character {char!r} in mask expression")
        tokens.append(expression[start:index])
    return tokens


@dataclass
class LayoutCut:
    """Layout exposure along a vertical section line at fixed x."""

    y_min: float
    y_max: float
    x: float
    window: float
    label: str
    layer_intervals: dict[str, IntervalSet] = field(default_factory=dict)

    @classmethod
    def from_strips(
        cls,
        strips: dict[str, IntervalSet],
        *,
        y_min: float,
        y_max: float,
        x: float = 0.0,
        window: float = 4.0,
        label: str = "strip",
    ) -> LayoutCut:
        return cls(
            y_min=y_min,
            y_max=y_max,
            x=x,
            window=window,
            label=label,
            layer_intervals=dict(strips),
        )

    @classmethod
    def from_gds(
        cls,
        layout: GDSLayout,
        section: GDSSection | dict[str, Any],
        process: ProcessDefinition | None = None,
    ) -> LayoutCut:
        Polygon, box = _require_shapely_geometry()
        try:
            from shapely.geometry import LineString as _CutLine
        except ImportError as exc:
            raise ImportError("shapely is required for GDS section utilities") from exc
        selected = _coerce_section(section)
        _, min_y, _, max_y = layout.bounds
        slice_box = box(
            selected.x - selected.window / 2.0,
            min_y - 1.0,
            selected.x + selected.window / 2.0,
            max_y + 1.0,
        )

        gds_to_name: dict[tuple[int, int], str] = {}
        if process is not None:
            gds_to_name = process.gds_to_layout_name()

        merged: dict[str, list[Interval]] = {}
        exact = selected.mode == "section"
        cut_line = None
        if exact:
            cut_line = _CutLine([(selected.x, min_y - 1.0), (selected.x, max_y + 1.0)])
        for record in layout.layer_records:
            layer_name = gds_to_name.get(record.spec, record.name)
            for polygon in record.polygons:
                shape = Polygon(polygon)
                if not shape.is_valid:
                    shape = shape.buffer(0)
                if shape.is_empty:
                    continue
                if exact and cut_line is not None:
                    hit = shape.intersection(cut_line)
                    for piece in _iter_simple_geometries(hit):
                        piece_bounds = piece.bounds
                        if len(piece_bounds) != 4:
                            continue
                        _, y0, _, y1 = piece_bounds
                        if y1 - y0 > 1e-6:
                            merged.setdefault(layer_name, []).append(Interval(float(y0), float(y1)))
                    continue
                clipped = shape.intersection(slice_box)
                for geometry in _iter_simple_geometries(clipped):
                    bounds = geometry.bounds
                    if len(bounds) != 4:
                        continue
                    _, y0, _, y1 = bounds
                    if y1 - y0 > 1e-6:
                        merged.setdefault(layer_name, []).append(Interval(float(y0), float(y1)))

        layer_intervals = {
            name: IntervalSet(intervals=_normalize(intervals))
            for name, intervals in merged.items()
        }
        return cls(
            y_min=min_y,
            y_max=max_y,
            x=selected.x,
            window=selected.window,
            label=selected.label,
            layer_intervals=layer_intervals,
        )

    def evaluate_mask(self, expression: str) -> IntervalSet:
        return MaskExpression(expression).evaluate(
            self.layer_intervals,
            y_min=self.y_min,
            y_max=self.y_max,
        )

    def y_extent(self, margin: float = 0.0) -> tuple[float, float]:
        return (self.y_min - margin, self.y_max + margin)
