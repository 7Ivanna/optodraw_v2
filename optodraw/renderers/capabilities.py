"""Per-renderer capability tables: what each output supports, approximates, or skips.

Every renderer used to drop unsupported content silently. Each table maps a
geometry ``type`` (2D) or ``shape`` (3D) to one verdict:

- ``full``: rendered as authored.
- ``approximate``: rendered in reduced form (documented per renderer).
- ``skip``: omitted from the output.

Renderers accept ``strict=False``. Default mode records a :class:`RenderReport`
(available as ``renderer.report`` after rendering) without changing output.
Strict mode raises :class:`UnsupportedGeometryError` on the first skipped or
approximated node instead of dropping it.
"""

from __future__ import annotations

from typing import Any

FULL = "full"
APPROXIMATE = "approximate"
SKIP = "skip"

VERDICTS = (FULL, APPROXIMATE, SKIP)


class UnsupportedGeometryError(ValueError):
    """A renderer met content it cannot represent faithfully in strict mode."""


SVG_2D: dict[str, str] = {
    "art": FULL,      # a symbol drawing fitted to the part's ports (optodraw/symbols/art.py)
    "group": FULL,
    "text": FULL,
    "rect": FULL,
    "line": FULL,
    "circle": FULL,
    "path": FULL,
    "ellipse": FULL,
    "polygon": FULL,
    "polyline": FULL,
    "fragment": FULL,  # an inset: a nested SVG root (optodraw/figure/)
}

TIKZ_2D: dict[str, str] = {
    "art": FULL,      # a \pic of the symbol library
    "group": FULL,
    "text": FULL,
    "rect": FULL,
    "line": FULL,
    "circle": FULL,
    "path": APPROXIMATE,  # M/L/Q/A/Z subset; other commands collapse to endpoints
    "ellipse": FULL,
    "polygon": FULL,
    "polyline": FULL,
}

GLB_3D: dict[str, str] = {
    "rect": FULL,  # extruded outline
    "polygon": FULL,  # extruded outline
    "circle": FULL,  # faceted, resolution=24
    "ellipse": FULL,  # faceted via affine scale
    "line": APPROXIMATE,  # stroked path extruded as a flat solid
    "polyline": APPROXIMATE,  # stroked path extruded as a flat solid
    "text": SKIP,
    "group": FULL,  # container, dispatched per child
    "path": SKIP,
    "ellipse_outline": SKIP,
}

THREEJS_3D: dict[str, str] = {
    "group": FULL,
    "box": FULL,
    "cylinder": FULL,
    "sphere": FULL,
    "torus": FULL,
    "extruded_polygon": FULL,
    "svg_extrusion": APPROXIMATE,  # shallow schematic extrusion, not physical device geometry
    "lathe_profile": FULL,
    "tube_path": FULL,
    "text_sprite": FULL,
    "text_decal": FULL,
}

TABLES: dict[str, dict[str, str]] = {
    "svg": SVG_2D,
    "tikz": TIKZ_2D,
    "glb": GLB_3D,
    "threejs": THREEJS_3D,
}


def verdict(renderer: str, kind: str | None) -> str:
    """Return the support verdict for a geometry type, defaulting to ``skip``."""

    return TABLES.get(renderer, {}).get(kind or "", SKIP)


class RenderReport:
    """What an export dropped or reduced, in one shared shape.

    Matches the GLB exporter report so every renderer speaks the same format:
    ``{"meshes"/"nodes": int, "skipped": [...], "approximated": [...], "failed": [...]}``.
    Entries are human-readable strings naming the node and the reason.
    """

    def __init__(self) -> None:
        self.nodes = 0
        self.skipped: list[str] = []
        self.approximated: list[str] = []
        self.failed: list[str] = []

    def record(self, verdict_name: str, detail: str) -> None:
        if verdict_name == SKIP:
            self.skipped.append(detail)
        elif verdict_name == APPROXIMATE:
            self.approximated.append(detail)

    def check(
        self,
        renderer: str,
        kind: str | None,
        *,
        strict: bool,
        detail: str,
        unknown_as: str = SKIP,
    ) -> str:
        """Record a verdict; raise in strict mode unless fully supported.

        ``unknown_as`` overrides the verdict for types missing from the table.
        Three.js passes ``APPROXIMATE`` because its fallback draws a magenta
        box instead of dropping the mesh.
        """

        result = verdict(renderer, kind)
        if kind not in TABLES.get(renderer, {}):
            result = unknown_as
        if result == FULL:
            return result
        if strict:
            raise UnsupportedGeometryError(f"{renderer}: {detail} (support: {result})")
        self.record(result, f"{renderer}: {detail} (support: {result})")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "skipped": list(self.skipped),
            "approximated": list(self.approximated),
            "failed": list(self.failed),
        }


def view_keyword(kwargs: dict, primary: str) -> str:
    """The 1D or 2D view from ``view=`` or ``onchip_view=``: both renderers take both names."""

    given = {key: kwargs[key] for key in ("view", "onchip_view") if key in kwargs}
    if len(set(given.values())) > 1:
        raise ValueError(f"view={given['view']!r} and onchip_view={given['onchip_view']!r} disagree")
    view = next(iter(given.values()), "2d")
    if view not in {"1d", "2d"}:
        raise ValueError(f"{primary} must be '1d' or '2d'")
    return view
