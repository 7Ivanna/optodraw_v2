"""1D symbols: one TikZ library, prebuilt to SVG, looked up for a component.

``lookup(component)`` returns the symbol that the editor, the notebook and the
exports all draw. The TikZ source is in ``tikz/``; ``python -m
optodraw.symbols.build`` turns the variant table into ``svg/`` and
``symbols.json``. See ``docs/content/guides/your-own-parts.md``.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
PT_PER_CM = 72.0 / 2.54          # SVG points in one TikZ unit (1 cm)

_LIBRARIES: list[Path] = [HERE]


@dataclass(frozen=True)
class SymbolPort:
    name: str
    x: float                     # SVG points from the symbol's top left corner, y down
    y: float
    kind: str
    side: str                    # left | right | top | bottom: the edge the port leaves through


@dataclass(frozen=True)
class Symbol:
    name: str                    # the pic, or "block" for the fallback
    params: dict[str, Any]
    svg: str                     # a complete SVG document, with no ids and no text
    width: float                 # SVG points
    height: float
    origin: tuple[float, float]  # where the pic's (0,0) sits in the SVG frame
    ports: dict[str, SymbolPort]
    exact: bool                  # False: a near variant or the block stands in
    source: str                  # prebuilt | compiled | nearest | block
    flipped: bool = False        # drawn left to right reversed: see mirrored()
    rotation: float = 0.0        # degrees, counterclockwise on paper: see rotated()
    hub: tuple[float, float] | None = None   # where the beams of a splitter meet; a view draws the used paths to it
    svg2d: str | None = None     # the same drawing painted (materials, depth), for the 2D view

    def mirrored(self) -> "Symbol":
        """The same symbol reflected left to right, for a part that light enters from the right."""

        turn = {"left": "right", "right": "left"}
        ports = {
            name: SymbolPort(name, round(self.width - port.x, 3), port.y, port.kind, turn.get(port.side, port.side))
            for name, port in self.ports.items()
        }
        mirror = f'transform="translate({self.width} 0) scale(-1 1)"'
        if self.source == "block":               # the box and its text are symmetric: reflect the stubs only
            svg = self.svg.replace("<path d=", f"<path {mirror} d=", 1)
        else:
            svg = re.sub(r"(<svg[^>]*>)(.*)(</svg>)", rf"\1<g {mirror}>\2</g>\3", self.svg, flags=re.S)
        svg2d = None if self.svg2d is None else re.sub(r"(<svg[^>]*>)(.*)(</svg>)", rf"\1<g {mirror}>\2</g>\3",
                                                       self.svg2d, flags=re.S)
        hub = None if self.hub is None else (round(self.width - self.hub[0], 3), self.hub[1])
        return replace(self, svg=svg, ports=ports, origin=(self.width - self.origin[0], self.origin[1]),
                       flipped=not self.flipped, hub=hub, svg2d=svg2d)

    def rotated(self, degrees: float) -> "Symbol":
        """The same symbol turned counterclockwise on paper, for a part on a free-space bench.

        The frame grows to hold the turned art, and each port moves with it.
        """

        if not degrees % 360:
            return self
        turn = math.radians(degrees)
        c, s = math.cos(turn), math.sin(turn)
        w, h = self.width, self.height

        def spin(x: float, y: float) -> tuple[float, float]:     # about the middle; y grows downward
            return c * (x - w / 2.0) + s * (y - h / 2.0), -s * (x - w / 2.0) + c * (y - h / 2.0)

        corners = [spin(x, y) for x, y in ((0.0, 0.0), (w, 0.0), (0.0, h), (w, h))]
        left, top = min(x for x, _ in corners), min(y for _, y in corners)
        width = round(max(x for x, _ in corners) - left, 6)
        height = round(max(y for _, y in corners) - top, 6)

        def place(x: float, y: float) -> tuple[float, float]:
            x, y = spin(x, y)
            return round(x - left, 3), round(y - top, 3)

        sides = ["right", "top", "left", "bottom"]
        ports = {}
        for name, port in self.ports.items():
            facing = (sides.index(port.side) * 90.0 + degrees) % 360.0
            ports[name] = SymbolPort(name, *place(port.x, port.y), port.kind, sides[round(facing / 90.0) % 4])
        frame = f'viewBox="0 0 {width:g} {height:g}" width="{width:g}pt" height="{height:g}pt"'
        group = f'<g transform="translate({width / 2:g} {height / 2:g}) rotate({-degrees:g}) translate({-w / 2:g} {-h / 2:g})">'
        def wrap(text: str) -> str:
            return re.sub(r"<svg[^>]*>(.*)</svg>",
                          lambda m: f'<svg xmlns="http://www.w3.org/2000/svg" {frame}>{group}{m.group(1)}</g></svg>',
                          text, flags=re.S)

        svg, svg2d = wrap(self.svg), (None if self.svg2d is None else wrap(self.svg2d))
        return replace(self, svg=svg, width=width, height=height, ports=ports, origin=place(*self.origin),
                       rotation=(self.rotation + degrees) % 360.0, hub=None if self.hub is None else place(*self.hub),
                       svg2d=svg2d)

    def scaled(self, factor: float) -> "Symbol":
        """Scale symbol art and its ports together, without changing its aspect ratio."""
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("Symbol scale must be finite and positive")
        width, height = self.width * factor, self.height * factor

        def wrap(text):
            return re.sub(r"<svg[^>]*>(.*)</svg>", lambda m:
                          f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
                          f'<g transform="scale({factor})">{m.group(1)}</g></svg>', text, flags=re.S)

        return replace(self, svg=wrap(self.svg), width=width, height=height,
                       origin=tuple(value * factor for value in self.origin),
                       ports={name: replace(port, x=port.x * factor, y=port.y * factor)
                              for name, port in self.ports.items()},
                       hub=None if self.hub is None else tuple(value * factor for value in self.hub),
                       svg2d=None if self.svg2d is None else wrap(self.svg2d))

    def inner(self) -> str:
        """The drawing without its <svg> wrapper, to place inside another SVG."""

        return re.search(r"<svg[^>]*>(.*)</svg>", self.svg, re.S).group(1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "params": self.params, "svg": self.svg,
            "width": self.width, "height": self.height,
            "exact": self.exact, "source": self.source, "flipped": self.flipped, "rotation": self.rotation,
            "hub": None if self.hub is None else list(self.hub),
            "ports": [
                {"name": port.name, "x": port.x, "y": port.y, "kind": port.kind, "side": port.side}
                for port in self.ports.values()
            ],
        }


def add_library(path: str | Path) -> None:
    """Register a folder made by ``python -m optodraw.symbols.build --out``. It wins over built-in rows."""

    folder = Path(path)
    if not (folder / "symbols.json").is_file():
        raise FileNotFoundError(f"{folder} has no symbols.json; build it with python -m optodraw.symbols.build")
    if folder not in _LIBRARIES:
        _LIBRARIES.insert(0, folder)
    _index.cache_clear()


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, tuple[dict[str, Any], Path]], dict[str, str]]:
    """Every prebuilt variant by slug, and the default variant of each component class."""

    by_slug: dict[str, tuple[dict[str, Any], Path]] = {}
    by_class: dict[str, str] = {}
    for folder in _LIBRARIES:
        symbols = json.loads((folder / "symbols.json").read_text(encoding="utf-8"))["symbols"]
        for key, entry in symbols.items():
            by_slug.setdefault(key, (entry, folder))
            if entry.get("component") and not entry.get("args"):
                by_class.setdefault(entry["component"].rpartition(":")[2], key)
            for other in entry.get("also", []):
                by_class.setdefault(other.rpartition(":")[2], key)
    return by_slug, by_class


def _side(x: float, y: float, width: float, height: float) -> str:
    """The edge a port leaves through: the direction it lies in from the middle of the symbol."""

    dx = (x - width / 2.0) / max(width / 2.0, 1e-9)
    dy = (y - height / 2.0) / max(height / 2.0, 1e-9)
    if abs(dx) >= abs(dy):
        return "left" if dx < 0 else "right"
    return "top" if dy < 0 else "bottom"


def _symbol(entry: dict[str, Any], folder: Path, *, exact: bool, source: str) -> Symbol:
    width, height = float(entry["width"]), float(entry["height"])
    return Symbol(
        name=entry["symbol"],
        params=dict(entry["params"]),
        svg=(folder / "svg" / entry["svg"]).read_text(encoding="utf-8"),
        width=width,
        height=height,
        origin=(float(entry["origin"][0]), float(entry["origin"][1])),
        ports={
            name: SymbolPort(name, float(port["x"]), float(port["y"]), port["kind"],
                             port.get("side") or _side(float(port["x"]), float(port["y"]), width, height))
            for name, port in entry["ports"].items()
        },
        exact=exact,
        source=source,
        hub=None if entry.get("hub") is None else (float(entry["hub"][0]), float(entry["hub"][1])),
        svg2d=_read_2d(entry, folder),
    )


def _read_2d(entry: dict[str, Any], folder: Path) -> str | None:
    path = folder / "svg" / str(entry.get("svg2d", ""))
    return path.read_text(encoding="utf-8") if entry.get("svg2d") and path.is_file() else None


def _kinds(entry: dict[str, Any]) -> dict[str, str]:
    return {name: port["kind"] for name, port in entry["ports"].items()}


def _component_ports(component: Any) -> dict[str, Any]:
    ports = getattr(component, "ports", None)
    result = ports() if callable(ports) else {}
    return result if isinstance(result, dict) else {}


def _request(component: Any) -> tuple[str, dict[str, Any]] | None:
    """The symbol a component asks for: its own ``symbol_1d()``, else its class's default row."""

    method = getattr(component, "symbol_1d", None)
    request = method() if callable(method) else None
    if request is not None:
        return str(request[0]), dict(request[1])
    by_slug, by_class = _index()
    names = [str(getattr(component, "component_type", "")), *(cls.__name__ for cls in type(component).__mro__)]
    for name in names:                             # the catalog name first, then the class and its parents
        key = by_class.get(name)
        if key is not None:
            entry = by_slug[key][0]
            return entry["symbol"], dict(entry["params"])
    return None


def cache_dir() -> Path:
    return Path(os.environ.get("OPTODRAW_SYMBOL_CACHE") or Path.home() / ".cache" / "optodraw" / "symbols")


@lru_cache(maxsize=1)
def _cache_key() -> str:
    from . import build

    return build.source_hash(build.library_files())[:12]        # a library edit starts a new cache


def _compiled(name: str, params: dict[str, Any]) -> tuple[dict[str, Any], Path] | None:
    """Compile a variant that is not prebuilt, once, into the user cache. None without LaTeX."""

    if os.environ.get("OPTODRAW_SYMBOL_COMPILE", "1") == "0":
        return None
    from . import build

    folder = cache_dir() / _cache_key()
    record = folder / f"{build.slug(name, params)}.json"
    try:
        entry: dict[str, Any] = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):                 # no record yet, or a damaged one
        if not build.latex_available():
            return None
        try:
            entry = build.compile_symbol(name, params, folder)
        except Exception as error:                # an unknown key or pic: remember it, do not retry each call
            entry = {"failed": str(error)[-400:]}
        try:
            folder.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps(entry), encoding="utf-8")
        except OSError:                           # a cache that cannot be written: go on without it
            pass
    if "failed" in entry or not (folder / "svg" / str(entry.get("svg"))).is_file():
        return None
    return entry, folder


def _nearest(name: str, params: dict[str, Any], wanted: dict[str, str]) -> tuple[dict[str, Any], Path] | None:
    """The prebuilt variant of the same pic, with the same ports, that shares the most parameters."""

    best, best_score = None, -1
    for key in sorted(_index()[0]):
        entry, folder = _index()[0][key]
        if entry["symbol"] != name or _kinds(entry) != wanted:
            continue
        names = set(params) | set(entry["params"])
        score = sum(1 for item in names if params.get(item) == entry["params"].get(item)) - len(names)
        if best is None or score > best_score:
            best, best_score = (entry, folder), score
    return best


_BLOCK_MARGIN = 9.0              # port stub length, SVG points
_BLOCK_PITCH = 11.0              # distance between ports on one side


def _block(component: Any) -> Symbol:
    """The fallback: a black-outline box with the part's type, and every port on the side it faces."""

    label = str(getattr(component, "component_type", type(component).__name__))
    sides: dict[str, list[tuple[float, str, str]]] = {"left": [], "right": [], "top": [], "bottom": []}
    for name, port in _component_ports(component).items():
        angle = float(getattr(port, "orientation_deg", 0.0)) % 360.0
        center = getattr(port, "center", None)
        px, py = float(getattr(center, "x", 0.0)), float(getattr(center, "y", 0.0))
        kind = str(getattr(port, "kind", "optical"))
        if 45.0 <= angle < 135.0:
            sides["top"].append((px, name, kind))
        elif 135.0 <= angle < 225.0:
            sides["left"].append((-py, name, kind))        # local y is up; the SVG frame is y down
        elif 225.0 <= angle < 315.0:
            sides["bottom"].append((px, name, kind))
        else:
            sides["right"].append((-py, name, kind))
    m = _BLOCK_MARGIN
    box_w = max(46.0, 4.2 * len(label) + 10.0, _BLOCK_PITCH * (max(len(sides["top"]), len(sides["bottom"])) + 1))
    box_h = max(24.0, _BLOCK_PITCH * (max(len(sides["left"]), len(sides["right"])) + 1))
    width, height = box_w + 2 * m, box_h + 2 * m
    ports: dict[str, SymbolPort] = {}
    stubs: list[str] = []
    for side, members in sides.items():
        members.sort()
        for index, (_, name, kind) in enumerate(members):
            along = (index + 1) / (len(members) + 1)
            if side in ("left", "right"):
                y = m + along * box_h
                x, inner_x = (0.0, m) if side == "left" else (width, width - m)
                stubs.append(f"M{x:.2f} {y:.2f}H{inner_x:.2f}")
            else:
                x = m + along * box_w
                y, inner_y = (0.0, m) if side == "top" else (height, height - m)
                stubs.append(f"M{x:.2f} {y:.2f}V{inner_y:.2f}")
            ports[name] = SymbolPort(name, round(x, 3), round(y, 3), kind, side)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}pt" height="{height}pt">'
        f'<path d="{" ".join(stubs)}" fill="none" stroke="#000" stroke-width="0.9" stroke-linecap="round"/>'
        f'<rect x="{m}" y="{m}" width="{box_w}" height="{box_h}" fill="#fff" stroke="#000" stroke-width="0.9"/>'
        f'<text x="{width / 2}" y="{height / 2}" font-size="7" font-family="Helvetica,Arial,sans-serif" '
        f'text-anchor="middle" dominant-baseline="central">{html.escape(label)}</text></svg>'
    )
    return Symbol("block", {"label": label}, svg, width, height, (width / 2, height / 2), ports, False, "block")


def lookup(component: Any, request: tuple[str, dict[str, Any]] | None = None) -> Symbol:
    """The 1D symbol of a component, or the variant ``request`` names (the 2D art asks this way).

    Order: the prebuilt variant with the same parameters; with LaTeX installed,
    a fresh compile kept in the user cache; the nearest prebuilt variant
    (``exact=False``); the labeled block (``exact=False``). A symbol is used
    only when its port names and kinds equal the component's.
    """

    custom = getattr(component, "schematic_symbol", None)
    definition = getattr(component, "_part_definition", None)
    if request is None and not callable(custom) and definition is not None:
        from optodraw.parts import UserPart

        surrogate = UserPart(definition, parameters=dict(getattr(component, "_part_parameters", {})))
        def custom():
            return surrogate.schematic_symbol(_namespace_owner=component)
    if request is None and callable(custom):
        symbol = custom()
        wanted = {name: str(getattr(port, "kind", "optical")) for name, port in _component_ports(component).items()}
        if not isinstance(symbol, Symbol) or {name: port.kind for name, port in symbol.ports.items()} != wanted:
            raise ValueError("A custom 1D symbol must match its component's port names and kinds")
        return symbol
    wanted = {name: str(getattr(port, "kind", "optical")) for name, port in _component_ports(component).items()}
    request = request or _request(component)
    if request is not None:
        name, params = request
        from .build import slug

        hit = _index()[0].get(slug(name, params))
        if hit is not None and _kinds(hit[0]) == wanted:
            return _symbol(*hit, exact=True, source="prebuilt")
        compiled = _compiled(name, params)
        if compiled is not None and _kinds(compiled[0]) == wanted:
            return _symbol(*compiled, exact=True, source="compiled")
        near = _nearest(name, params, wanted)
        if near is not None:
            return _symbol(*near, exact=False, source="nearest")
    return _block(component)


__all__ = ["PT_PER_CM", "Symbol", "SymbolPort", "add_library", "cache_dir", "lookup"]
