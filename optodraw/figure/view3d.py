"""``View3D``: a vector 3D view of a scene or a chip as an inset source, with marks on true 3D points.

The renderer (``optodraw.renderers.vector3d*``) needs numpy and shapely, so this module imports it inside functions:
a page file loads and exports with neither.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from optodraw.components.models import GDSModel
from optodraw.core.scene import Scene
from optodraw.figure.fragment import Fragment, place_from
from optodraw.gds.palette import canonical, material_fill
from optodraw.gds.parsers import LayerStackSpec, load_layer_stack, stack_wafer
from optodraw.gds.styles import normalize_layer_stack

# (x, y, z, 1) of a scene, z the height above the table, to the viewer's world, y up: (x, z, -y)
SCENE_AXES = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0)
COVER_SHARE = 1e-4          # a face hides a point when it is nearer by more than this share of the scene diagonal
BOXES = ("opaque", "clear")
PROJECTIONS = ("perspective", "parallel")
CAMERAS = (None, "home")


def scene_data(scene: Any) -> str:
    """What the vector view reads of ``scene``, as JSON text: the viewer's scene data, its page constants and its
    materials. Two scenes with the same text draw the same view, so this compares two scenes with no render."""

    from optodraw.core.view_layout import display_scene
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    renderer = ThreeJsRenderer(display_scene(scene, "3d"), capture={"background": "none"}, world="light")
    items = renderer._collect_scene_data()
    return json.dumps([items, asdict(renderer.page_constants(items)), renderer._resolved_material_catalog()],
                      sort_keys=True, default=str)


class _WaferChip(GDSModel):
    """The chip of :meth:`View3D.chip`: a GDSModel whose process context is the stack's own wafer. Under the top of
    the wafer the substrate and each film take their own material from the one table, opaque, so an InP chip shows
    no silicon handle and no oxide box. The rest of the viewer's process context stays: the footprint, the etch
    voids, the cover over the top metal and the clear fill over the wafer. ``box="clear"`` keeps an oxide film
    clear, as the viewer draws it. A drawn layer is opaque unless the stack gives it an opacity: the viewer's 0.8
    for a chip of many layers would make every layer clear in a figure, and a clear layer hides nothing.
    An etch that ends inside the wafer holds the stack's fill, as in the section: opaque in the wafer, clear over it."""

    component_type = "GDSModel"             # the viewer's chip rules (the die, the chip colours) key on this type

    def __init__(self, gds: Any, spec: LayerStackSpec, box: str, **options: Any):
        self._wafer, self._materials, self._box = stack_wafer(spec), spec.materials, box
        styles = {key: {"opacity": 1.0, **style} for key, style in normalize_layer_stack(spec.styles).items()}
        super().__init__(gds, layer_stack=styles, process_context=True, **{**spec.oxide, **options})

    def process_context_regions(self, exaggeration: float = 1.0):
        wafer = self._wafer
        top = wafer.substrate.zmin + wafer.substrate.thickness
        bands = [(-math.inf, top * exaggeration, wafer.substrate.material)]
        bands += [(film.zmin * exaggeration, (film.zmin + film.thickness) * exaggeration, film.material)
                  for film in wafer.films]
        top = bands[-1][1]
        bands.append((top, math.inf, None))                     # over the wafer: the viewer's own region
        left = -math.inf                                        # the top of the wafer that the etches leave
        oxide: dict[str, Any] = {}                              # the viewer's clear fill over a wafer
        for shape, za, zb, material in super().process_context_regions(exaggeration):
            drawn = "silicon" if material.get("preset") == "silicon" else "sio2"     # its handle, else its oxide
            if drawn == "sio2" and not oxide:
                oxide = material
            pieces: list[list[Any]] = []
            for z0, z1, name in bands:
                low, high = max(za, z0), min(zb, z1)
                if high - low <= 1e-9:
                    continue
                if name is not None:
                    left = max(left, high)
                look = self._look(name, drawn, material)
                if pieces and pieces[-1][2] == look:              # two films of one look: one solid, no seam
                    pieces[-1][1] = high
                else:
                    pieces.append([low, high, look])
            for low, high, look in pieces:
                yield shape, low, high, look
        if left == -math.inf:                                   # no wafer drawn: nothing to fill
            return
        yield from self._fill(exaggeration, top, left, oxide)

    def _fill(self, exaggeration: float, top: float, left: float, oxide: dict[str, Any]):
        """The stack's fill in each etch that ends at or under the wafer ``top``, from the etch floor up to the
        fill's top, as the section fills it: opaque under ``left``, the top of the wafer that the etches leave, and
        clear over it, as the viewer draws its fill over a wafer, in the fill's colour. A plan that one look fills
        over several bands of z is one solid."""

        from shapely.ops import unary_union

        fill = self._wafer.fill
        voids = [(plan, z0, min(z1, fill.top * exaggeration)) for plan, z0, z1 in self._etch_voids(exaggeration)
                 if z1 <= top + 1e-9]                  # an etch through the whole stack stays open, as in the section
        under = self._look(fill.material, "sio2", oxide)
        over = {**oxide, "color": material_fill(fill.material, self._materials), "preset": canonical(fill.material)}
        edges = sorted({z for _, z0, z1 in voids for z in (z0, z1)} | {left})
        pieces: list[list[Any]] = []                    # [plan, z_bottom, z_top, look]
        for za, zb in zip(edges, edges[1:]):
            active = [plan for plan, z0, z1 in voids if z0 < (za + zb) / 2 < z1]
            if not active:
                continue
            look = under if zb <= left + 1e-9 else over
            union = unary_union(active)
            for plan in getattr(union, "geoms", [union]):
                below = next((p for p in pieces if abs(p[2] - za) < 1e-9 and p[3] == look and p[0].equals(plan)),
                             None)
                if below is not None:
                    below[2] = zb
                else:
                    pieces.append([plan, za, zb, look])
        for plan, za, zb, look in pieces:
            yield plan, za, zb, look

    def _look(self, name: str | None, drawn: str, material: dict[str, Any]) -> dict[str, Any]:
        """The material of a wafer band: the viewer's own where it draws that material (its handle; its oxide only
        with ``box="clear"``) and over the wafer, else the band's own, opaque. The table's glass preset is clear, so
        the record sets no transmission."""

        if name is None or (canonical(name) == drawn and (drawn == "silicon" or self._box == "clear")):
            return material
        return {"color": material_fill(name, self._materials), "opacity": 1.0, "transmission": 0.0,
                "preset": canonical(name)}


class View3D:
    """A vector 3D view: the viewer's solids with their hidden parts cut away, as SVG paths, at the inset's width.

    ``View3D(scene)`` draws a scene as the 3D viewer does; ``place(x, y, z=0.0)`` takes scene x and y, and z the
    height above the table in scene units (a beam runs at ``beam_height``). :meth:`chip` draws a GDS file on its
    stack; there ``place`` takes the file's x and y and the true z, in um. ``covered`` (same arguments) is True when
    a solid hides the point, so ``check_figure`` finds a mark whose target cannot be seen.

    ``direction`` is a viewer camera preset (``"isometric"``) or ``(x, y, z)`` toward the camera, z up.
    ``projection`` is ``"perspective"`` or ``"parallel"``. ``style`` goes to the renderer; None takes its default.
    ``camera="home"`` takes the viewer's framed pose. ``shadows=False`` leaves the studio's shadows out. A view of
    more than ``face_limit`` front faces (None: the renderer's ``FACE_LIMIT``) raises Vector3DError, which names
    the ways out. The view draws once per width and keeps the drawing until the scene changes."""

    free_shape = False

    def __init__(self, scene: Any, direction: Any = "isometric", projection: str = "perspective",
                 style: str | None = None, *, camera: str | None = None, shadows: bool = True,
                 face_limit: int | None = None):
        from optodraw.renderers.vector3d_hidden import _direction

        if projection not in PROJECTIONS:
            raise ValueError(f"projection is one of {', '.join(PROJECTIONS)}, got {projection!r}")
        if camera not in CAMERAS:
            raise ValueError(f"camera is None or 'home', got {camera!r}")
        if not isinstance(shadows, bool):
            raise ValueError(f"shadows is True or False, got {shadows!r}")
        if face_limit is not None and (not isinstance(face_limit, int) or isinstance(face_limit, bool)
                                       or face_limit < 1):
            raise ValueError(f"face_limit is a whole number over 0, or None, got {face_limit!r}")
        _direction(direction)
        self.scene, self.projection, self.style = scene, projection, style
        self.camera, self.shadows, self.face_limit = camera, shadows, face_limit
        self.direction = direction if isinstance(direction, str) else tuple(float(v) for v in direction)
        self._chip: dict[str, Any] | None = None          # View3D.chip: its inputs, for the record
        self._model: Any = None                            # View3D.chip: its GDSModel
        self._drawn: tuple[Any, Fragment] | None = None

    @classmethod
    def chip(cls, gds: Any, stack: Any, *, region: Any = None, z_scale: float = 4.0, cell: str | None = None,
             box: str = "opaque", direction: Any = "isometric", projection: str = "perspective",
             style: str | None = None, camera: str | None = None, shadows: bool = True,
             face_limit: int | None = None) -> "View3D":
        """A GDS file on its stack: ``stack`` is a bundled stack name, a stack file or a ``LayerStackSpec``.
        ``region=(x0, y0, x1, y1)`` in file um crops it; heights are drawn ``z_scale`` times true, and the fragment's
        note says so. The wafer under the layers comes from the stack, with the oxide under the device plane opaque
        so it hides the handle; ``box="clear"`` draws it clear, as the viewer does. A crop is a piece of a chip, so
        the viewer's die plate is left out. The shadows fall on the top of the lower cladding."""

        if box not in BOXES:
            raise ValueError(f"box is one of {', '.join(BOXES)}, got {box!r}")
        if isinstance(gds, (str, Path)) and not Path(gds).is_file():
            raise FileNotFoundError(f"no GDS file {str(gds)!r}")
        spec = stack if isinstance(stack, LayerStackSpec) else load_layer_stack(stack)
        region = None if region is None else tuple(float(v) for v in region)
        model = _WaferChip(gds, spec, box, z_exaggeration=float(z_scale), crop_region=region, cell_name=cell)
        scene = Scene(title="chip", platform="on_chip")
        scene.add(model)
        view = cls(scene, direction, projection, style, camera=camera, shadows=shadows, face_limit=face_limit)
        view._chip = {"gds": gds, "stack": stack, "region": region, "z_scale": float(z_scale), "cell": cell,
                      "box": box}
        view._model = model
        return view

    @property
    def frozen(self) -> bool:
        """A chip from an object (a layout or a stack object, not a file or a bundled name) cannot rebuild."""

        return self._chip is not None and not all(isinstance(self._chip[key], (str, Path)) for key in ("gds", "stack"))

    def fragment(self, width_mm: float, *, font_pt: float) -> Fragment:
        key = (float(width_mm), scene_data(self.scene))
        if self._drawn is None or self._drawn[0] != key:
            self._drawn = (key, self._draw(float(width_mm)))
        return self._drawn[1]

    def _draw(self, width_mm: float) -> Fragment:
        import numpy as np

        from optodraw.renderers.vector3d import FACE_LIMIT, _svg, drawn, frame
        from optodraw.renderers.vector3d_hidden import covered
        from optodraw.renderers.vector3d_scene import scene_solids

        options = {"show_chip_base": False} if self._chip is not None else None
        solids = scene_solids(self.scene, renderer_options=options)
        style = {} if self.style is None else {"style": self.style}
        camera, height = frame(solids, self.direction, self.projection, width_mm, camera=self.camera, **style,
                               shadows=self.shadows)
        group, shown = drawn(solids, camera, **style, shadows=self.shadows, face_limit=self.face_limit or FACE_LIMIT)
        svg = _svg(group, width_mm, height)
        world = self._world()
        right, up, back = camera.basis
        shape = {"form": "camera", "world": list(world), "eye": [float(v) for v in camera.eye],
                 "right": [float(v) for v in right], "up": [float(v) for v in up], "back": [float(v) for v in back],
                 "k": float(camera.k), "origin": [float(v) for v in camera.origin],
                 "perspective": bool(camera.perspective)}
        place = place_from(shape)
        points = np.vstack([face.ring for face in solids.faces])
        tol = COVER_SHARE * float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))

        def hidden(x: float, y: float, z: float = 0.0) -> bool:
            place(x, y, z)                                  # a point behind the eye raises ValueError
            at = [sum(world[4 * row + i] * v for i, v in enumerate((x, y, z, 1.0))) for row in range(3)]
            return covered(shown, camera, np.array(at, float), tol=tol)

        notes = (f"heights {self._chip['z_scale']:g} times true",) if self._chip is not None else solids.notes
        return Fragment(svg=svg, size_mm=(width_mm, height), place=place, covered=hidden, notes=tuple(notes),
                        map=shape)

    def _world(self) -> tuple[float, ...]:
        """The map from the source's (x, y, z, 1) to the viewer's world, row-major 3 by 4. On a chip: the file's um
        through ``GDSModel.file_to_local``, the true z times the height scale. The chip stands alone at the origin
        on its page, so the viewer adds no move and no lift."""

        if self._chip is None:
            return SCENE_AXES
        model = self._model
        (cx, cy), (x1, y1), (x2, y2) = (model.file_to_local(x, y) for x, y in ((0, 0), (1, 0), (0, 1)))
        return (x1 - cx, x2 - cx, 0.0, cx, 0.0, 0.0, float(model.z_exaggeration), 0.0, cy - y1, cy - y2, 0.0, -cy)

    def _top(self) -> float:
        """The top of the chip as drawn, in true um: where :meth:`Inset.show_cut` draws a cut by default."""

        model = self._model
        tops = [float((child.get("position") or (0.0, 0.0, 0.0))[1]) + float(child["height"])
                for child in model.geometry_3d().get("children", []) if "height" in child]
        return max(tops) / float(model.z_exaggeration)

    def to_record(self) -> dict[str, Any]:
        look = {"direction": self.direction if isinstance(self.direction, str) else list(self.direction),
                "projection": self.projection, "style": self.style, "camera": self.camera, "shadows": self.shadows,
                "face_limit": self.face_limit}
        if self._chip is None:
            from optodraw.schema import scene_to_spec

            return {"kind": "View3D", "scene": scene_to_spec(self.scene), **look}
        if self.frozen:
            return {"kind": "View3D"}
        chip = self._chip
        return {"kind": "View3D", "path": str(chip["gds"]), "stack": str(chip["stack"]),
                "region": None if chip["region"] is None else list(chip["region"]), "z_scale": chip["z_scale"],
                "cell": chip["cell"], "box": chip["box"], **look}

    @classmethod
    def _from_record(cls, record: dict[str, Any], base: Path) -> "View3D":
        from optodraw.figure.fragment import _numbers
        from optodraw.figure.sources import _maybe_text, _stack_at, _text, _value

        given = record.get("direction")
        limit = _value(record, "face_limit", empty=True)
        look = {"direction": given if isinstance(given, str) else
                tuple(_numbers(given, 3, "a View3D record's direction")),
                "projection": _text(record, "projection"), "style": _maybe_text(record, "style"),
                "camera": _maybe_text(record, "camera"), "shadows": record.get("shadows", True),
                "face_limit": None if limit is None else int(limit)}
        if "scene" in record:
            from optodraw.schema import scene_from_spec

            if not isinstance(record["scene"], dict):
                raise ValueError("a View3D record of a scene holds the scene's spec")
            return cls(scene_from_spec(record["scene"], base=base), **look)
        if "path" not in record:
            raise ValueError("this View3D record is frozen: it held a layout or a stack object, so it cannot rebuild")
        region = None if record.get("region") is None else _numbers(record["region"], 4, "a View3D record's region")
        return cls.chip(base / _text(record, "path"), _stack_at(_text(record, "stack"), base), region=region,
                        z_scale=_value(record, "z_scale"), cell=_maybe_text(record, "cell"), box=_text(record, "box"),
                        **look)
