"""A fragment is a piece of figure drawn elsewhere: one SVG root at final size, plus where its source points land.

This module imports nothing from ``optodraw.publication``.
"""

from __future__ import annotations

import html
import math
import re
import warnings
from dataclasses import dataclass
from typing import Any, Callable

PT_MM = 0.3528              # one point in mm
KINDS = ("drawn", "measured", "render")
MAP_FORMS = ("affine", "plot", "section", "tilted", "scaled", "camera")
TILTED = ("place needs tilt=0: in a tilted render a point's row depends on its height, so no map from the layout to "
          "the picture is exact")

_SVG_UNITS = {"": 1.0, "px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0, "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0}

_ROOT = re.compile(r"(?::root|html|body)(?![\w-])")
_QUOTED = r"""(?:"[^"]*"|'[^']*')"""
# at-rules whose block holds declarations or keyframes, not selectors: they stay as they are
_PLAIN_AT_RULES = ("font-face", "page", "property", "counter-style", "font-feature-values", "font-palette-values",
                   "position-try", "viewport", "color-profile")

# The elements a fragment keeps, by local name in lower case: what optodraw's sources, matplotlib, pdftocairo and
# dvisvgm write, and the RDF metadata of a file. Any other element goes with all it holds: script, foreignObject, an
# HTML element, an animation that can set a link.
_ELEMENTS = frozenset(name.lower() for name in (
    "svg", "g", "defs", "style", "symbol", "use", "switch", "a", "title", "desc", "metadata", "path", "rect", "circle",
    "ellipse", "line", "polyline", "polygon", "text", "tspan", "textPath", "image", "clipPath", "mask", "pattern",
    "marker", "linearGradient", "radialGradient", "stop", "filter", "feBlend", "feColorMatrix", "feComponentTransfer",
    "feComposite", "feConvolveMatrix", "feDiffuseLighting", "feDisplacementMap", "feDistantLight", "feDropShadow",
    "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR", "feGaussianBlur", "feImage", "feMerge", "feMergeNode",
    "feMorphology", "feOffset", "fePointLight", "feSpecularLighting", "feSpotLight", "feTile", "feTurbulence",
    "RDF", "Work", "Agent", "format", "type", "date", "creator", "publisher", "rights", "source", "language",
    "description", "subject", "identifier", "contributor", "relation", "coverage", "License", "permits", "requires",
    "prohibits"))
_VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "keygen", "link", "meta", "param",
                   "source", "track", "wbr"))     # HTML elements with no end tag: one goes alone
# An HTML parser reads what an SVG desc or title holds as HTML, where style and title are raw text up to their end
# tag: they keep their text and no element.
_TEXT_ONLY = ("desc", "title")
_LINKS = ("href", "src", "srcset")         # attributes that load or open what they name
_SAFE_LINK = re.compile(r"#\S*|data:image/(?:png|jpeg)[;,].*", re.I | re.S)
_SPACE = "\t\n\f\r "                       # the white space of an HTML parser: it reads the editor's canvas
_TAG_NAME = re.compile(r"[^\t\n\f\r />]+")
_ATTRIBUTE_NAME = re.compile(r"=?[^\t\n\f\r />=]*")
_UNQUOTED = re.compile(r"[^\t\n\f\r >]*")
_SAFE_COMMENT = re.compile(r"<!--(?:(?!--)[^<>])*(?<!-)-->")


@dataclass
class Fragment:
    """What an inset source gives: ``svg`` is one SVG root at final size (its ids are scoped on placement), ``size_mm``
    its width and height, and ``place(x, y)`` takes source coordinates to mm in the fragment, y down. ``covered`` says
    if a source point is hidden (3D only). ``kind`` is ``"drawn"``, ``"measured"`` or ``"render"``, for the gates and
    the record. ``notes`` go in the caption: ``"heights 4 times true"``. ``floor_mm`` is the height of a strip along the
    bottom that the source fills itself (the info bar of an SEM render): a mark of the inset stays above it. ``map``
    is ``place`` as numbers (see :func:`place_from`), so a saved page keeps it; a fragment without one takes no
    marks after a load."""

    svg: str
    size_mm: tuple[float, float]
    place: Callable[..., tuple[float, float]]
    covered: Callable[..., bool] | None = None
    kind: str = "drawn"
    notes: tuple[str, ...] = ()
    floor_mm: float = 0.0
    map: dict[str, Any] | None = None


def affine(a: float, b: float, c: float, d: float, e: float, f: float) -> dict[str, Any]:
    """The map ``(x, y) -> (a x + b y + c, d x + e y + f)`` as a record."""

    return {"form": "affine", "m": [float(v) for v in (a, b, c, d, e, f)]}


def _numbers(values: Any, count: int, what: str) -> list[float]:
    """``values`` as ``count`` floats. Anything but a list of plain finite numbers raises ValueError."""

    if not isinstance(values, (list, tuple)) or len(values) != count or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
        raise ValueError(f"{what} takes {count} finite numbers, got {values!r}")
    return [float(v) for v in values]


def _number(record: dict[str, Any], key: str, what: str, empty: bool = False) -> float | None:
    if empty and record.get(key) is None:
        return None
    return _numbers([record.get(key)], 1, f"{what} {key!r}")[0]


def _scale(spec: Any) -> Callable[[float], float]:
    """An axis scale from its record: ``["linear"]`` or ``["log", base]``, as matplotlib draws them."""

    if spec == ["linear"]:
        return float
    if isinstance(spec, list) and len(spec) == 2 and spec[0] == "log":
        base = _numbers(spec[1:], 1, "a log scale's base")[0]
        if not (base > 0.0 and base != 1.0):
            raise ValueError(f"a log scale's base is above 0 and not 1, got {base!r}")
        log = {10.0: math.log10, 2.0: math.log2, math.e: math.log}.get(base)

        def logarithm(value: float) -> float:
            if not value > 0.0:
                raise ValueError(f"a log axis takes values above 0, got {value!r}")
            return log(value) if log else math.log(value) / math.log(base)

        return logarithm
    raise ValueError(f"a plot map knows the axis scales linear and log, not {spec!r}")


def place_from(record: dict[str, Any] | None) -> Callable[..., tuple[float, float]]:
    """``place`` from its record, which holds numbers and the names of axis scales only, so loading one runs no code.

    ``affine``: ``m`` = a, b, c, d, e, f. ``plot``: one entry per axes (``None`` for an axes that is not cartesian or
    not linear or log), each the scale of x and y and six affine terms after them; ``place(x, y, axes=0)``.
    ``section``: the frame of a cross-section figure (a thick top oxide cut out between ``keep`` and ``resume``).
    ``tilted``: a tilted render, which refuses. ``scaled``: another map times ``by``. ``camera``: a 3D view;
    ``world`` (12 terms, row-major 3 by 4) takes ``(x, y, z, 1)`` to the viewer's world, then the camera's ``eye``,
    its axes ``right``, ``up`` and ``back``, ``k`` and ``origin`` take it to the page, as ``Camera.page`` does;
    ``place(x, y, z=0.0)``, and a point behind the eye raises. ``None``: no map."""

    if record is None:
        def none(*point: Any, **options: Any) -> tuple[float, float]:
            raise ValueError("this saved inset keeps no map of its source, so a mark cannot land in it")

        return none
    form = record.get("form") if isinstance(record, dict) else None
    if form == "affine":
        a, b, c, d, e, f = _numbers(record.get("m"), 6, "an affine map")
        return lambda x, y: (a * x + b * y + c, d * x + e * y + f)
    if form == "plot":
        entries = record.get("axes")
        if not isinstance(entries, list):
            raise ValueError(f"a plot map holds a list of axes, got {entries!r}")
        if not all(entry is None or isinstance(entry, dict) for entry in entries):
            raise ValueError(f"each axes of a plot map is a record or None, got {entries!r}")
        maps = [None if entry is None else (_scale(entry.get("x")), _scale(entry.get("y")),
                                            _numbers(entry.get("m"), 6, "an axes map")) for entry in entries]

        def place(x: float, y: float, axes: int = 0) -> tuple[float, float]:
            if isinstance(axes, bool) or not isinstance(axes, int) or not 0 <= axes < len(maps):
                raise ValueError(f"no axes {axes!r}: the plot has {len(maps)}, counted from 0")
            if maps[axes] is None:
                raise ValueError(f"place takes cartesian axes with a linear or log scale, and axes {axes} is not one")
            sx, sy, (a, b, c, d, e, f) = maps[axes]
            u, v = sx(x), sy(y)
            return a * u + b * v + c, d * u + e * v + f

        return place
    if form == "section":
        s0, z1, scale, zscale, left, top, gap, room = (_number(record, key, "a section map") for key in
                                                       ("s0", "z1", "scale", "zscale", "left", "top", "gap", "room"))
        keep, resume = (_number(record, key, "a section map", empty=True) for key in ("keep", "resume"))
        if (keep is None) != (resume is None):
            raise ValueError("a section map gives both keep and resume, or neither")

        def section(s: float, z: float) -> tuple[float, float]:
            y = top + (z1 - z) * zscale                     # the frame of ``schematic._Frame``, with no numpy
            if keep is not None and not z >= (keep + resume) / 2.0:
                y = top + (z1 - resume) * zscale + gap + (keep - z) * zscale
            return left + (s - s0) * scale, y + room

        return section
    if form == "tilted":
        _number(record, "tilt", "a tilted map")

        def tilted(*point: Any, **options: Any) -> tuple[float, float]:
            raise ValueError(TILTED)

        return tilted
    if form == "scaled":
        by, inner = _number(record, "by", "a scaled map"), place_from(record.get("map"))
        return lambda *point, **options: tuple(v * by for v in inner(*point, **options))
    if form == "camera":
        world = _numbers(record.get("world"), 12, "a camera map's world")
        eye, right, up, back = (_numbers(record.get(key), 3, f"a camera map's {key}")
                                for key in ("eye", "right", "up", "back"))
        k = _number(record, "k", "a camera map")
        ox, oy = _numbers(record.get("origin"), 2, "a camera map's origin")
        perspective = record.get("perspective")
        if not isinstance(perspective, bool):
            raise ValueError(f"a camera map's perspective is true or false, got {perspective!r}")

        def camera(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
            point = (float(x), float(y), float(z), 1.0)
            view = [sum(world[4 * row + i] * point[i] for i in range(4)) - eye[row] for row in range(3)]
            vx, vy, vz = (sum(a * b for a, b in zip(view, axis)) for axis in (right, up, back))
            if perspective and not -vz > 0.0:
                raise ValueError(f"the point ({float(x):g}, {float(y):g}, {float(z):g}) lies behind the eye of the "
                                 "3D view")
            scale = k / -vz if perspective else k
            return vx * scale + ox, -vy * scale + oy

        return camera
    raise ValueError(f"no map form {form!r}: a saved map is one of {', '.join(MAP_FORMS)}")


def fragment_record(fragment: Fragment) -> dict[str, Any]:
    """``fragment`` as data for the page file: everything but ``place`` (kept as ``map``) and ``covered``."""

    return {"svg": fragment.svg, "size_mm": [float(v) for v in fragment.size_mm], "kind": fragment.kind,
            "notes": list(fragment.notes), "map": fragment.map, "floor_mm": float(fragment.floor_mm)}


def stored_fragment(record: dict[str, Any]) -> Fragment:
    """The fragment a page file keeps, ``place`` rebuilt from its map, its SVG :func:`sanitized`. A record that is not
    one raises ValueError."""

    if not isinstance(record, dict) or not isinstance(record.get("svg"), str):
        raise ValueError("a saved fragment holds its SVG text")
    kind, notes = record.get("kind", "drawn"), record.get("notes", [])
    if kind not in KINDS:
        raise ValueError(f"a saved fragment's kind is one of {', '.join(KINDS)}, not {kind!r}")
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise ValueError(f"a saved fragment's notes are a list of text, got {notes!r}")
    return Fragment(svg=sanitized(record["svg"]), size_mm=tuple(_numbers(record.get("size_mm"), 2, "size_mm")),
                    place=place_from(record.get("map")), kind=kind, notes=tuple(notes),
                    floor_mm=_number(record, "floor_mm", "a saved fragment") if "floor_mm" in record else 0.0,
                    map=record.get("map"))


def scaled(fragment: Fragment, ratio: float, note: str) -> Fragment:
    """``fragment`` drawn ``ratio`` times as large: the viewBox scales the art, and the size, ``place`` and the floor
    scale with it. ``note`` goes with the notes."""

    wide, tall = (value * ratio for value in fragment.size_mm)
    shape = None if fragment.map is None else {"form": "scaled", "by": float(ratio), "map": fragment.map}
    return Fragment(svg=_root(fragment.svg).close(f"{wide:.6g}mm", f"{tall:.6g}mm"), size_mm=(wide, tall),
                    place=place_from(shape), kind=fragment.kind, notes=fragment.notes + (note,),
                    floor_mm=fragment.floor_mm * ratio, map=shape)


def _attr(tag: str, name: str) -> str | None:
    """The value of attribute ``name`` in ``tag``, in single or double quotes."""

    found = re.search(rf"""\s{name}\s*=\s*(["'])(.*?)\1""", tag, flags=re.S)
    return found.group(2) if found else None


def _svg_size(root: str, name: str) -> tuple[float, float]:
    """The width and the height of an SVG root tag in its own units: from its viewBox, else from its size."""

    box = _attr(root, "viewBox")
    if box:
        values = [float(value) for value in re.split(r"[\s,]+", box.strip())]
        return values[2], values[3]
    size = [re.search(rf"""\s{key}\s*=\s*["']([\d.]+)\s*([a-z]*)["']""", root) for key in ("width", "height")]
    if not all(size) or any(match.group(2) not in _SVG_UNITS for match in size):
        raise ValueError(f"{name} gives no viewBox and no width and height, so it has no shape to lay out")
    return tuple(float(match.group(1)) * _SVG_UNITS[match.group(2)] for match in size)


@dataclass
class _Root:
    """An SVG root split apart: ``tag`` is the root tag without its geometry and without its closing ``>``, ``view``
    the viewBox as the file writes it (or one worked out from its size), ``inner`` what lies inside."""

    tag: str
    view: str
    inner: str
    size: tuple[float, float]
    origin: tuple[float, float]

    def close(self, width: str, height: str) -> str:
        """The root as a tag of the given width and height, with the viewBox it had."""

        return f'{self.tag} width="{width}" height="{height}" viewBox="{self.view}">{self.inner}</svg>'


def _root(svg: str, name: str = "a fragment") -> _Root:
    """Split the SVG root of ``svg``. A root that closes itself (``<svg .../>``) has nothing inside."""

    found = re.search(rf"<svg\b(?:[^>\"']|{_QUOTED})*>", svg)
    if found is None:
        raise ValueError(f"{name} holds no <svg> root")
    root = found.group(0)
    size = _svg_size(root, name)
    view = _attr(root, "viewBox")
    values = [float(v) for v in re.split(r"[\s,]+", view.strip())] if view else [0.0, 0.0]
    tag = re.sub(rf"\s(?:id|x|y|width|height|viewBox)\s*=\s*{_QUOTED}", "", root)
    closed = tag.endswith("/>")
    tag = tag[:-2 if closed else -1].rstrip()
    inner = "" if closed else svg[found.end():svg.rfind("</svg>")]
    return _Root(tag, view.strip() if view else f"0 0 {size[0]!r} {size[1]!r}", inner, size, (values[0], values[1]))


def _without_text(svg: str, texts: tuple[str, ...], name: str) -> str:
    """``svg`` with each ``<text>`` that reads as one of ``texts`` taken out."""

    found = set()

    def keep(match: re.Match) -> str:
        words = html.unescape(re.sub(r"<[^>]+>", "", match.group(0))).strip()
        if words in texts:
            found.add(words)
            return ""
        return match.group(0)

    out = re.sub(r"<text\b.*?</text>", keep, svg, flags=re.S)
    missing = [text for text in texts if text not in found]
    if missing:
        warnings.warn(f"{name} has no text {missing}: its text may be outlined as paths", UserWarning, stacklevel=3)
    return out


def _strip_comments(css: str) -> str:
    """``css`` without its comments. Quoted text is left alone."""

    out, i = [], 0
    while i < len(css):
        char = css[i]
        if char in "\"'":
            end = _after_string(css, i)
            out.append(css[i:end])
            i = end
        elif css.startswith("/*", i):
            end = css.find("*/", i + 2)
            i = len(css) if end < 0 else end + 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _after_string(css: str, i: int) -> int:
    """The index after the quoted string that starts at ``css[i]``."""

    quote, i = css[i], i + 1
    while i < len(css) and css[i] != quote:
        i += 2 if css[i] == "\\" else 1
    return i + 1


def _find(css: str, i: int, stops: str) -> int:
    """The index of the first char of ``stops`` at or after ``i``, outside quoted text. -1 when there is none."""

    while i < len(css):
        if css[i] in stops:
            return i
        i = _after_string(css, i) if css[i] in "\"'" else i + 1
    return -1


def _split_selectors(text: str) -> list[str]:
    """``text`` cut at the commas that stand outside parentheses, brackets and quotes."""

    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        char = text[i]
        if char in "\"'":
            i = _after_string(text, i)
            continue
        depth += (char in "([") - (char in ")]")
        if char == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    return parts + [text[start:]]


def _scope_selector(selector: str, scope: str, panel_id: str, ids: set[str]) -> str:
    """One selector kept inside ``scope``. The root of a document (``:root``, ``html``, ``body``) becomes the
    fragment's own root, the ``svg`` that stands in ``scope``, and an ``#id`` that ``_scoped`` renames is renamed here
    too."""

    selector = re.sub(r"#([\w-]+)", lambda m: f"#{panel_id}-{m.group(1)}" if m.group(1) in ids else m.group(0),
                      selector.strip())
    root = _ROOT.match(selector)
    return f"{scope} > svg" + selector[root.end():] if root else f"{scope} {selector}"


def _scope_css(css: str, scope: str, panel_id: str, ids: set[str]) -> str:
    """``css`` with every rule kept to the elements inside ``scope``. The block of every at-rule that holds selectors
    (``@media``, ``@supports``, ``@layer``, ``@scope``, ``@starting-style`` and any other) is scoped. ``@font-face``,
    ``@page`` and the like stay as they are, and so do ``@keyframes``. ``@import`` is dropped."""

    out, i = [], 0
    while i < len(css):
        stop = _find(css, i, "{;}")
        if stop < 0:
            out.append(css[i:])
            break
        if css[stop] != "{":                                   # a statement such as @charset, or a stray }
            statement = css[i:stop + 1]
            if css[stop] == ";" and not statement.lstrip().lower().startswith("@import"):
                out.append(statement)
            i = stop + 1
            continue
        depth, end = 1, stop + 1
        while end < len(css) and depth:
            end = _find(css, end, "{}")
            if end < 0:
                end = len(css)
                break
            depth += 1 if css[end] == "{" else -1
            end += 1
        head, body = css[i:stop].strip(), css[stop + 1:end - 1 if depth == 0 else end]
        if head.startswith("@"):
            name = (re.match(r"@([\w-]+)", head) or [None, ""])[1].lower()
            if not (name.endswith("keyframes") or name in _PLAIN_AT_RULES):
                body = _scope_css(body, scope, panel_id, ids)
            out.append(f"{head}{{{body}}}")
        else:
            out.append(",".join(_scope_selector(part, scope, panel_id, ids) for part in _split_selectors(head)
                                if part.strip()) + f"{{{body}}}")
        i = end
    return "".join(out)


def _scoped(inner: str, panel_id: str) -> str:
    """``inner`` with its ids and its style rules kept to one panel: two panels often share ids such as ``clip1``, and a
    style rule such as ``*{...}`` or ``rect{...}`` reaches the whole file. A rule is cut down to the element with id
    ``panel_id`` and what lies inside it, and an ``#id`` in a selector follows the id it names.

    Stated limits: the names of ``@keyframes`` and the families of ``@font-face`` stay global, so two fragments that
    define the same name share it. An ``@import`` is dropped."""

    ids = set(re.findall(r"""(?<![\w:-])id\s*=\s*["']([^"']+)["']""", inner))

    def name(value: str) -> str:
        return f"{panel_id}-{value}" if value in ids else value

    inner = re.sub(r"""(?<![\w:-])id(\s*=\s*)(["'])([^"']+)\2""",
                   lambda m: f"id{m.group(1)}{m.group(2)}{name(m.group(3))}{m.group(2)}", inner)
    inner = re.sub(r"url\((\s*[\'\"]?)#([^)\'\"\s]+)", lambda m: f"url({m.group(1)}#{name(m.group(2))}", inner)
    inner = re.sub(r"""href(\s*=\s*)(["'])#([^"']+)\2""",
                   lambda m: f"href{m.group(1)}{m.group(2)}#{name(m.group(3))}{m.group(2)}", inner)

    def style(match: re.Match) -> str:
        bare = re.sub(r"<!\[CDATA\[|\]\]>", "", match.group(2))
        css = _scope_css(_strip_comments(bare), f"#{panel_id}", panel_id, ids)
        return match.group(1) + (css if bare == match.group(2) else f"<![CDATA[{css}]]>") + match.group(3)

    return re.sub(r"(<style\b[^>]*>)(.*?)(</style>)", style, inner, flags=re.S)


def _tag(svg: str, at: int) -> tuple[str, list[tuple[str, str | None, int, int]], int, bool] | None:
    """The tag whose name starts at ``svg[at]``, read as an HTML parser reads it (the editor's canvas is HTML): its
    name, each attribute as name, value, start and end, the index after the tag, and whether it closes itself. None
    when the tag never ends."""

    found = _TAG_NAME.match(svg, at)
    name, i, attributes = found.group(0), found.end(), []
    while i < len(svg):
        char = svg[i]
        if char in _SPACE:
            i += 1
        elif char == "/":
            if svg.startswith("/>", i):
                return name, attributes, i + 2, True
            i += 1
        elif char == ">":
            return name, attributes, i + 1, False
        else:
            start, i = i, _ATTRIBUTE_NAME.match(svg, i).end()
            key, j, value = svg[start:i], i, None
            while j < len(svg) and svg[j] in _SPACE:
                j += 1
            if j < len(svg) and svg[j] == "=":
                j += 1
                while j < len(svg) and svg[j] in _SPACE:
                    j += 1
                if j < len(svg) and svg[j] in "\"'":
                    close = svg.find(svg[j], j + 1)
                    if close < 0:
                        return None
                    value, i = svg[j + 1:close], close + 1
                else:
                    i = _UNQUOTED.match(svg, j).end()
                    value = svg[j:i]
            attributes.append((key, value, start, i))
    return None


def _ascii_letter(char: str) -> bool:
    return char.isascii() and char.isalpha()


def _unsafe(key: str, value: str | None) -> bool:
    """True for an attribute that runs code or loads a file: every ``on...`` handler, and a link that is not ``#id`` or
    an embedded PNG or JPEG as written. A link written with character references is not read: it goes. So does a value
    that holds ``<`` (XML forbids it): in raw text a browser reads a ``</style>`` in it as the end tag."""

    local = key.lower().rsplit(":", 1)[-1]
    return (local.startswith("on") or (local in _LINKS and not _SAFE_LINK.fullmatch(value or ""))
            or "<" in (value or ""))


def sanitized(svg: str) -> str:
    """``svg`` with nothing that runs code or loads a file: an element that is not in the allow-list goes with all it
    holds (``script``, ``foreignObject``, any HTML element), and so do each ``on...`` attribute, each ``href`` or
    ``src`` that is not ``#id`` or ``data:image/png`` or ``jpeg``, and each attribute whose value holds ``<``. A
    ``desc`` or ``title`` keeps its text only: each element in it goes with all it holds. Processing instructions,
    doctypes, comments that hold ``<``, ``>`` or ``--`` and CDATA that holds ``<`` go too, and a lone ``<`` becomes
    ``&lt;``. The text is read as an HTML parser reads it, so the editor's canvas sees what this sees. What is kept
    stays byte for byte."""

    out, i = [], 0
    dropping, depth = "", 0                  # the element that goes with all it holds, and how deep in it
    text_only = ""                           # the desc or title being read
    while i < len(svg):
        lt = svg.find("<", i)
        if lt < 0:
            out.append("" if dropping else svg[i:])
            break
        out.append("" if dropping else svg[i:lt])
        after = svg[lt + 1:lt + 2]
        if svg.startswith("<!--", lt):
            end = svg.find("-->", lt + 4)
            i = len(svg) if end < 0 else end + 3
            if not dropping and _SAFE_COMMENT.fullmatch(svg, lt, i):
                out.append(svg[lt:i])
        elif svg.startswith("<![CDATA[", lt):
            end = svg.find("]]>", lt + 9)
            i = len(svg) if end < 0 else end + 3
            if not dropping and end >= 0 and "<" not in svg[lt + 9:end]:
                out.append(svg[lt:i])
        elif after in ("!", "?") or (after == "/" and not _ascii_letter(svg[lt + 2:lt + 3])):
            end = svg.find(">", lt + 1)                   # a declaration, an instruction or a bogus comment: it goes
            i = len(svg) if end < 0 else end + 1
        elif _ascii_letter(after) or after == "/":
            closing = after == "/"
            tag = _tag(svg, lt + 1 + closing)
            if tag is None:                               # a tag that never ends: the rest goes
                break
            name, attributes, i, closed = tag
            local = name.lower().rsplit(":", 1)[-1]
            if dropping:
                if local == dropping and not closed:
                    depth += -1 if closing else 1
                    dropping = dropping if depth else ""
            elif local not in _ELEMENTS or (text_only and not (closing and local == text_only)):
                dropping, depth = ("", 0) if closing or closed or local in _VOID else (local, 1)
            elif closing:
                out.append(f"</{name}>" if attributes else svg[lt:i])
                text_only = ""
            else:
                tag_text, cut = svg[lt:i], 0
                for key, value, start, end in attributes:
                    if _unsafe(key, value):
                        tag_text = tag_text[:start - lt - cut] + " " + tag_text[end - lt - cut:]
                        cut += end - start - 1
                out.append(tag_text)
                text_only = local if local in _TEXT_ONLY and not closed else ""
        else:                                             # a lone '<' is text
            if not dropping:
                out.append("&lt;")
            i = lt + 1
    return "".join(out)


def nested_svg(svg: str, width: float, height: float, panel_id: str) -> str:
    """The SVG root ``svg`` as a nested ``<svg>`` ``width`` by ``height`` wide, its ids, references and rules kept to
    ``panel_id``. The root tag is scoped with its children. The SVG is :func:`sanitized` first and again last: the
    scoping strips CSS comments in each style span, and so can join ``o/**/nerror`` to ``onerror``."""

    return sanitized(_scoped(_root(sanitized(svg)).close(f"{width:.6g}", f"{height:.6g}"), panel_id))
