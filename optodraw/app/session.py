"""Editor session state — the scene *spec* is the single source of truth.

The front-end and back-end exchange plain JSON scene specs (the same schema as
``optodraw.schema``). Every edit mutates the spec dict; rendering rebuilds a live
:class:`~optodraw.core.scene.Scene` via :func:`scene_from_spec`. This keeps the
editor light (no bespoke component-mutation API) and trivially serializable.

No FastAPI dependency lives here, so this module is import-safe on its own.
"""

from __future__ import annotations

import logging
import math
import string

from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from optodraw.app.workspaces import FILES
from optodraw.core.scene import Scene
from optodraw.figure.inset import LINK_ENDS
from optodraw.figure.sources import POLYGON_LIMIT
from optodraw.schema import (
    SCHEMA_VERSION,
    UNITS,
    component_from_spec,
    scene_from_spec,
)


DEFAULT_TRACE_MODE = "physical"  # real ray optics (hits, misses, bundles) unless a scene says otherwise


def _validate_scene_settings(spec: dict[str, Any]) -> None:
    for key in ("width", "height"):
        try:
            value = float(spec[key])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"scene {key} must be a positive finite number") from error
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"scene {key} must be a positive finite number")
    for key in ("grid", "beam_height"):
        if spec.get(key) is not None and not math.isfinite(float(spec[key])):
            raise ValueError(f"scene {key} must be finite")
    if spec.get("trace_mode", DEFAULT_TRACE_MODE) not in {"physical", "schematic"}:
        raise ValueError("trace_mode must be 'physical' or 'schematic'")


def empty_scene_spec(
    *,
    title: str = "Untitled Setup",
    width: float = 220.0,
    height: float = 140.0,
    platform: str = "free_space",
) -> dict[str, Any]:
    """Return a minimal, valid empty scene spec."""

    return {
        "schema_version": SCHEMA_VERSION,
        "units": dict(UNITS),
        "title": title,
        "width": width,
        "height": height,
        "platform": platform,
        "trace_mode": DEFAULT_TRACE_MODE,
        "components": [],
        "routes": [],
        "beams": [],
    }


def _is_point(value: Any) -> bool:
    """A plain ``[x, y]`` position, not an anchor form."""

    return isinstance(value, (list, tuple)) and len(value) == 2


def _entries(components: Any) -> list[dict[str, Any]]:
    """Every component entry, the children of groups included."""

    found = []
    for entry in components if isinstance(components, list) else []:
        if isinstance(entry, dict):
            found += [entry, *_entries(entry.get("children"))]
    return found


def _inset_scene(entry: dict[str, Any]) -> dict[str, Any]:
    """The scene spec an inset entry keeps, to open in the editor. ValueError names what the entry holds instead."""

    from optodraw.figure.inset import KIND_WORDS

    if entry.get("type") != "Inset":
        raise ValueError(f"only an inset opens: {entry.get('id')!r} is a {entry.get('type')}")
    name = f"the inset {entry['label']!r}" if entry.get("label") else "this inset"
    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    if source.get("kind") != "SceneView":
        word = KIND_WORDS.get(source.get("kind"), "drawing")
        article = "an" if word[0] in "aeiou" or word[:3] in ("SEM", "SVG") else "a"
        raise ValueError(f"{name} holds {article} {word}: only a scene inset opens in the editor")
    if not isinstance(source.get("scene"), dict):
        raise ValueError(f"{name} keeps its drawing only (its scene names a file the page does not carry), so it "
                         "cannot open")
    _plain(source["scene"], f"{name} does not open")
    return deepcopy(source["scene"])


def _plain(scene: dict[str, Any], refused: str) -> None:
    """Refuse a scene that names a file on this computer (a GDS part): a page file never makes the editor read one,
    and a page does not carry it. ``refused`` says what does not happen."""

    from optodraw.figure.sources import _loose

    if _loose(scene):
        raise ValueError(f"{refused}: its scene names a file on this computer (a GDS part), which the page does not "
                         "carry")


#: The inset kinds the editor makes, each with the record values a new one starts from (the keys of its ``to_record``).
#: A plot and an SEM render are made in Python only: their inputs are not data.
INSET_DEFAULTS: dict[str, dict[str, Any]] = {
    "Text": {"text": "Text", "width": None, "size_pt": None, "align": "left"},
    "Equation": {"latex": "E = mc^2", "tex": False},
    "EmptyBox": {"height": None},
    "Image": {"path": None, "scale_um_per_px": None, "image_kind": "measured"},
    "SvgFile": {"path": None, "drop_text": []},
    "PdfFile": {"path": None, "page": 1},
    "SceneView": {"view": "2d", "scene": empty_scene_spec()},
    "Timing": {"rows": [{"row": "Clock", "name": "CLK", "period": 1.0, "duty": 0.5, "phase": 0.0}], "span": [0.0, 4.0],
               "unit": "", "marks": [], "row_mm": None, "illustrative": False},
    "GdsView": {"path": None, "stack": None, "region": None, "layers": None, "cell": None, "limit": POLYGON_LIMIT},
    "SectionView": {"gds": None, "stack": None, "cut": None, "z": None, "cell": None, "z_scale": "auto"},
    "View3D": {"direction": "isometric", "projection": "perspective", "style": None},
}


def new_record(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    """The record of a new inset of ``kind``: ``values`` over the kind's defaults. ValueError for a kind the editor does
    not make."""

    if kind not in INSET_DEFAULTS:
        raise ValueError(f"the editor makes an inset of {', '.join(INSET_DEFAULTS)}, not {kind!r}: a plot or a render "
                         "is made in Python")
    return {"kind": kind, **deepcopy(INSET_DEFAULTS[kind]),
            **{key: deepcopy(value) for key, value in values.items() if key != "kind"}}


def _made_from(kind: str, source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """The record values a new ``kind`` inset takes from the record ``source`` of the inset it is made from: a section
    takes a GDS view's file, stack and cell, its cut inside the view's region; a 3D view takes a GDS view's crop, or a
    scene inset's scene."""

    made = source.get("kind")
    if kind == "SectionView" and made == "GdsView":
        x0, y0, x1, y1 = source["region"]
        cut = record.get("cut")
        if not (isinstance(cut, list) and len(cut) == 2 and all(
                isinstance(end, list) and len(end) == 2 and x0 <= end[0] <= x1 and y0 <= end[1] <= y1 for end in cut)):
            raise ValueError(f"a section's cut is two points [x, y] inside the GDS view's region ({x0:g}, {y0:g}, "
                             f"{x1:g}, {y1:g}), got {cut!r}")
        return {"gds": source["path"], "stack": source["stack"], "cell": source.get("cell")}
    if kind == "View3D" and made == "GdsView":
        return {"path": source["path"], "stack": source["stack"], "region": source.get("region"),
                "cell": source.get("cell"), "z_scale": record.get("z_scale", 4.0), "box": record.get("box", "opaque")}
    if kind == "View3D" and made == "SceneView" and isinstance(source.get("scene"), dict):
        return {"scene": deepcopy(source["scene"])}
    raise ValueError(f"a {kind} inset is not made from a {made} inset: a section is made from a GDS view, a 3D view "
                     "from a GDS view or a scene inset")


def print_scale(spec: dict[str, Any], entry: dict[str, Any]) -> tuple[float, float]:
    """``(mm per scene unit, font_pt)`` the inset ``entry`` of ``spec`` draws at: a page's own; else the scale of its
    last drawing; else the inset's default."""

    page, kept = spec.get("page"), entry.get("fragment")
    if isinstance(page, dict):
        return 1.0, float(page.get("font_pt", 7.0))
    if isinstance(kept, dict) and kept.get("width_mm") and kept.get("font_pt"):
        return float(kept["width_mm"]) / float(entry.get("width", 50.0)), float(kept["font_pt"])
    return 1.0, 8.0


def inset_fragment(entry: dict[str, Any], scale: tuple[float, float], root: Any = None) -> dict[str, Any]:
    """The fragment record the source of the inset ``entry`` draws now, built once from its record at ``scale`` (mm per
    scene unit, font_pt). ``root`` is the workspace folder its paths start from. A record that names a path outside the
    workspace's files folder, a TeX equation and a scene that names a file raise ValueError, before any file is read or
    any tool runs: the editor builds only what the user picked or typed."""

    from optodraw.figure.sources import SOURCE_KINDS, _paths

    record = entry["source"]
    if entry.get("height") is not None and not getattr(SOURCE_KINDS.get(record.get("kind")), "free_shape", False):
        raise ValueError(f"a {record.get('kind')} inset keeps its own shape, so it takes no height")
    files = None if root is None else (Path(root) / FILES).resolve()
    outside: list[str] = []

    def check(path: str) -> str:
        if files is None or not (Path(root) / path).resolve().is_relative_to(files):
            outside.append(path)
        return path

    _paths(record, check)
    if outside:
        raise ValueError(f"the inset's source names {outside[0]!r}, which is not in the workspace's files folder: pick "
                         "the file in the editor, which keeps it there")
    if record.get("kind") == "Equation" and record.get("tex"):
        raise ValueError("a TeX equation runs LaTeX: set it in Python, or set tex to false for mathtext")
    if isinstance(record.get("scene"), dict):
        _plain(record["scene"], "the inset does not build")
    inset = component_from_spec({key: value for key, value in deepcopy(entry).items() if key != "fragment"}, base=root)
    inset.set_print(*scale)
    inset.rebuild()
    return inset._kept(inset.fragment())


def _with_scene(spec: dict[str, Any], inset_id: str, scene: dict[str, Any] | None, *,
                redraw: bool) -> dict[str, Any]:
    """``spec`` with ``scene`` in the record of the inset ``inset_id`` (None keeps the record's scene). With
    ``redraw``, the inset draws again from its record, at the width and the font it was saved at."""

    from optodraw.schema import component_from_spec

    spec = deepcopy(spec)
    entry = next(e for e in _entries(spec.get("components")) if e.get("id") == inset_id)
    if scene is not None:
        entry["source"] = {**entry["source"], "scene": deepcopy(scene)}
    if redraw:
        inner = entry["source"]["scene"]
        _plain(inner, "the inset does not draw again")
        inset = component_from_spec(deepcopy(entry))
        inset.rebuild()
        entry["fragment"] = inset._kept(inset.fragment())
    return spec


class EditorSession:
    """One editable scene, addressed by component id.

    All public methods are thread-safe so a single session can back both the
    desktop window and (later) a hosted multi-request server.
    """

    def __init__(self, spec: dict[str, Any] | None = None) -> None:
        from optodraw.app._scene_cache import RetainedScene

        self._lock = RLock()
        self._scene_cache = RetainedScene()
        self._spec = deepcopy(spec) if spec is not None else empty_scene_spec()
        self._spec.setdefault("trace_mode", DEFAULT_TRACE_MODE)
        self._counter = 0
        self._sync_counter()
        self._ensure_ids()
        # the open insets, outermost first: (the spec around it, its id, its scene as it opened, the id counter)
        self._outer: list[tuple[dict[str, Any], str, dict[str, Any], int]] = []
        self._ws_store: Any = None  # WorkspaceStore, set by bind_workspace
        self._ws_name: str | None = None

    # -- workspace persistence --------------------------------------------- #

    def bind_workspace(self, store: Any, name: str) -> None:
        """Bind this session to a named workspace; future edits autosave to it."""

        self._ws_store = store
        self._ws_name = name

    @property
    def workspace(self) -> str | None:
        return self._ws_name

    def autosave(self) -> None:
        """Persist the current spec to the bound workspace (best-effort). With an inset open, that is the page with
        the scene in the inset's record; the inset draws again on the way back (:meth:`close_inset`)."""

        if self._ws_store is not None and self._ws_name:
            try:
                with self._lock:
                    page = self._page(redraw=False)
                self._ws_store.save(self._ws_name, page)
            except Exception as error:
                # Editing continues either way — but silence here means a full
                # disk or a read-only home eats the whole session without a
                # word, so it goes to the server log the user is looking at.
                logging.getLogger("optodraw").warning(
                    "could not autosave workspace %r: %s", self._ws_name, error
                )

    # -- spec access -------------------------------------------------------- #

    @property
    def spec(self) -> dict[str, Any]:
        """Return a deep copy of the current scene spec."""

        with self._lock:
            return deepcopy(self._spec)

    def set_light_params(self, changes: dict[str, float | None]) -> None:
        """Set engine parameters in ``metadata.animation.params``; ``None`` removes a key (it is back at its default)."""

        with self._lock:
            animation = self._spec.setdefault("metadata", {}).setdefault("animation", {})
            params = animation.setdefault("params", {})
            for key, value in changes.items():
                if value is None:
                    params.pop(key, None)
                else:
                    params[key] = value

    def load(self, spec: dict[str, Any], *, edit: bool = False) -> dict[str, Any]:
        """Replace the scene with ``spec`` after validating it round-trips.

        With ``edit``, ``spec`` is an edit of the scene this session holds: the 2D canvas sends a drag, a nudge, an
        align and a delete as a whole spec, so the inset rules of :meth:`move_component` and :meth:`delete` apply: an
        inset that moved brings its marks, and an inset that went leaves its marks on plain points. Without it (a file,
        a workspace, a preset, a generator, an undo) the spec loads as it is: ids come from labels and types, so two
        files often share them."""

        with self._lock:
            spec = deepcopy(spec)
            if edit:
                before = self._spec.get("components", [])
                old = {entry.get("id"): entry for entry in _entries(before) if entry.get("id")}
                for entry in spec.get("components") or []:
                    was = old.get(entry.get("id"))
                    if entry.get("type") == "Inset" and was and was.get("type") == "Inset" and _is_point(
                            entry.get("center")) and _is_point(was.get("center")):
                        step = (float(entry["center"][0]) - float(was["center"][0]),
                                float(entry["center"][1]) - float(was["center"][1]))
                        if step != (0.0, 0.0):
                            self._follow_inset(entry["id"], *step, components=spec["components"], before=old)
                if isinstance(spec.get("components"), list):
                    self._release_insets(spec, before)
        scene_from_spec(spec)  # raises on invalid spec / unknown component
        with self._lock:
            self._spec = deepcopy(spec)
            self._spec.setdefault("routes", [])
            self._spec.setdefault("beams", [])
            self._spec.setdefault("components", [])
            self._spec.setdefault("trace_mode", DEFAULT_TRACE_MODE)  # presets/old files omit it
            self._sync_counter()
            self._ensure_ids()  # presets/files may omit ids -> make links selectable
            self._refresh_traces()  # keep traced beams live across set-scene/undo/redo
            return deepcopy(self._spec)

    def reset(self, **kwargs: Any) -> dict[str, Any]:
        """Replace the scene with a fresh empty spec."""

        with self._lock:
            self.close_insets()                     # the whole page goes: the page it leaves is saved first
            candidate = empty_scene_spec(**kwargs)
            _validate_scene_settings(candidate)
            scene_from_spec(candidate)
            self._spec = candidate
            self._counter = 0
            return deepcopy(self._spec)

    # -- an inset opened in the editor --------------------------------------- #

    def open_inset(self, inset_id: str) -> None:
        """Edit the scene of the inset ``inset_id``: until :meth:`close_inset`, every edit, render and view of this
        session works on that scene, and autosave keeps the page with the scene in the inset's record. Only an inset
        whose record keeps its scene opens: another entry raises ValueError, an unknown id KeyError."""

        with self._lock:
            entry = next((e for e in _entries(self._spec.get("components")) if e.get("id") == inset_id), None)
            if entry is None:
                raise KeyError(inset_id)
            scene = _inset_scene(entry)
            around, counter = deepcopy(self._spec), self._counter
            try:
                self.load(scene)                    # it raises before anything changes
            except Exception as error:
                raise ValueError(f"the scene inside the inset does not load: {error}") from error
            self._outer.append((around, inset_id, deepcopy(self._spec), counter))

    @property
    def depth(self) -> int:
        """How many insets are open: 0 on the page."""

        return len(self._outer)

    def close_inset(self, depth: int | None = None) -> None:
        """Go back out to ``depth`` open insets (0 is the page; one level up with none). Each inset left draws again
        from its scene. A scene that cannot draw, and a page that does not build with the new drawing, raise
        ValueError, and the session stays where it was."""

        with self._lock:
            target = len(self._outer) - 1 if depth is None else int(depth)
            if not 0 <= target < len(self._outer):
                raise ValueError("no inset is open" if not self._outer else
                                 f"depth is 0 to {len(self._outer) - 1}, got {depth!r}")
            try:
                spec = self._fold(target, redraw=True)
                scene_from_spec(deepcopy(spec))     # the new drawing can move what it holds: a zoom on it, a mark
            except Exception as error:
                raise ValueError(f"the inset cannot draw the scene: {error}") from error
            self._spec, self._counter = spec, self._outer[target][3]
            del self._outer[target:]

    def close_insets(self) -> None:
        """Go back to the page from every open inset, and save it. An inset that cannot draw again keeps its scene and
        its old drawing (a warning in the server log), so nothing is lost."""

        with self._lock:
            if not self._outer:
                return
            try:
                self.close_inset(0)
            except Exception as error:
                logging.getLogger("optodraw").warning("an inset kept its old drawing: %s", error)
                self._spec, self._counter = self._page(redraw=False), self._outer[0][3]
                self._outer.clear()
        self.autosave()

    def _fold(self, target: int, *, redraw: bool) -> dict[str, Any]:
        """The spec at ``target`` open insets: the scene of each inset open below it put back in its record when it
        changed. With ``redraw``, each of those insets draws again from its record, also with no change: an autosave
        keeps a changed scene with its old drawing, so a session that stopped inside an inset leaves one."""

        spec = deepcopy(self._spec)
        for around, inset_id, opened, _ in reversed(self._outer[target:]):
            changed = spec != opened
            spec = (_with_scene(around, inset_id, spec if changed else None, redraw=redraw) if changed or redraw
                    else deepcopy(around))
        return spec

    def _page(self, *, redraw: bool) -> dict[str, Any]:
        return self._fold(0, redraw=redraw)

    def whole_spec(self) -> dict[str, Any]:
        """The page with every open inset drawn again from its scene, for a save; the session stays where it is. A
        page that does not draw or build that way is the page autosave keeps: each changed scene with its old
        drawing."""

        with self._lock:
            try:
                spec = self._page(redraw=True)
                scene_from_spec(deepcopy(spec))
                return spec
            except Exception as error:
                logging.getLogger("optodraw").warning("the saved page keeps an old inset drawing: %s", error)
                return self._page(redraw=False)

    @property
    def path(self) -> list[dict[str, str]]:
        """The page and each open inset, outermost first: ``{"name": "Page"}``, then ``{"id", "name"}`` with the
        inset's label, or the title of its scene."""

        with self._lock:
            levels = [{"name": "Page"}]
            for around, inset_id, opened, _ in self._outer:
                entry = next(e for e in _entries(around.get("components")) if e.get("id") == inset_id)
                levels.append({"id": inset_id, "name": str(entry.get("label") or opened.get("title") or inset_id)})
            return levels

    # -- an inset made in the editor ---------------------------------------- #

    @property
    def _root(self) -> Any:
        """The folder of the bound workspace store, where inset records name their files; None with no store."""

        return getattr(self._ws_store, "root", None)

    def add_inset(self, kind: str, source: dict[str, Any] | None = None, *, of: str | None = None,
                  **placement: Any) -> str:
        """Make an inset of ``kind`` (a key of :data:`INSET_DEFAULTS`) from plain values and build it once: ``source``
        holds its record's values over the kind's defaults, ``placement`` its ``center``, ``width``, ``height``,
        ``label``, ``frame``. ``of`` names the inset it is made from: a section of a GDS view, which a CutLink joins to
        it, or a 3D view of a GDS view or of a scene inset. Returns the new id; nothing changes when it does not
        build."""

        with self._lock:
            record = new_record(kind, source or {})
            others = _entries(self._spec.get("components"))
            if of is not None:
                parent = next((e for e in others if e.get("id") == of and e.get("type") == "Inset"), None)
                if parent is None or not isinstance(parent.get("source"), dict):
                    raise KeyError(of)
                record.update(_made_from(kind, parent["source"], record))
            page = isinstance(self._spec.get("page"), dict)
            middle = ([float(self._spec["width"]) / 2.0, float(self._spec["height"]) / 2.0] if page
                      else list(self._spec.get("frame_center") or [0.0, 0.0]))
            entry = {"type": "Inset", "id": self._new_id("inset"), "center": middle, "width": 50.0, **placement,
                     "source": record}
            entry["fragment"] = inset_fragment(entry, print_scale(self._spec, entry), self._root)
            candidate = deepcopy(self._spec)
            candidate["components"].append(entry)
            if kind == "SectionView" and of is not None:
                used = {e.get("name") for e in others if e.get("type") == "CutLink"}
                candidate["components"].append({
                    "type": "CutLink", "id": self._new_id("cutlink"), "source": of, "a": record["cut"][0],
                    "b": record["cut"][1], "section": entry["id"],
                    "name": next((c for c in string.ascii_uppercase if c not in used), "A")})
            scene_from_spec(deepcopy(candidate))
            self._spec = candidate
            return entry["id"]

    def edit_inset(self, inset_id: str, *, source: dict[str, Any] | None = None, width: float | None = None,
                   height: float | None = None) -> dict[str, Any]:
        """Change the inset ``inset_id`` and build its source once, in one edit: ``source`` holds the record values
        that change (text, file, page, stack, region, direction; none builds the record again as it is), ``width`` and
        ``height`` its size (a height for a free-shape source only). A source that does not build raises, and the
        scene stays as it was. Returns the new entry."""

        with self._lock:
            candidate = deepcopy(self._spec)
            entry = next((e for e in _entries(candidate.get("components")) if e.get("id") == inset_id), None)
            if entry is None:
                raise KeyError(inset_id)
            if entry.get("type") != "Inset" or not isinstance(entry.get("source"), dict):
                raise ValueError(f"{inset_id!r} is not an inset with a source")
            kind = entry["source"].get("kind")
            if (source or {}).get("kind", kind) != kind:
                raise ValueError(f"an inset keeps its kind ({kind}): make a new inset for another kind")
            scale = print_scale(candidate, entry)               # the scale it drew at, before a new width
            entry["source"] = {**entry["source"], **deepcopy(source or {})}
            for key, value in (("width", width), ("height", height)):
                if value is not None:
                    entry[key] = float(value)
            entry["fragment"] = inset_fragment(entry, scale, self._root)
            scene_from_spec(deepcopy(candidate))
            self._spec = candidate
            return deepcopy(entry)

    def scene(self) -> Scene:
        """Return the retained live scene. Edit it through this session."""

        with self._lock:
            scene = self._scene_cache.get(self._spec)
            self._tag_links(scene)
            return scene

    def _tag_links(self, scene: Scene) -> None:
        """Stamp editor ids onto beam/route nodes (components already carry _id).

        ``scene_from_spec`` adds beams/routes in spec order, so we can match by
        order to give them stable ids the renderer/front-end can select."""

        beam_ids = [b.get("id") for b in self._spec.get("beams", []) if b.get("id")]
        route_ids = [r.get("id") for r in self._spec.get("routes", []) if r.get("id")]
        bi = ri = 0
        for node in scene.root.children:
            ctype = getattr(node, "component_type", "")
            if ctype in {"Beam", "FocusingBeam"} and bi < len(beam_ids):
                node._id = beam_ids[bi]
                bi += 1
            elif ctype in {"Route", "WaveguideRoute", "FiberRoute", "MetalRoute"} and ri < len(route_ids):
                node._id = route_ids[ri]
                ri += 1

    def component_id_map(self, scene: Scene) -> dict[int, str]:
        """Return the renderer ``id(node) -> id`` map for selectable nodes.

        Covers components (``_id`` set by ``component_from_spec``) and beams/routes
        (``_id`` set by :meth:`_tag_links`)."""

        return {id(node): node._id for node in scene.walk() if getattr(node, "_id", "")}

    def ports_map(self) -> dict[str, list[dict[str, Any]]]:
        """Return ``{component_id: [world port dicts]}`` for connectable ports.

        Connections attach to these physical ports (not device centers); they
        carry world position + outward orientation + kind."""

        scene = self.scene()
        out: dict[str, list[dict[str, Any]]] = {}
        for node in scene.walk():
            node_id = getattr(node, "_id", "")
            if not node_id:
                continue
            try:
                world_ports = (
                    node.drawing_world_ports()
                    if hasattr(node, "drawing_world_ports")
                    else node.world_ports()
                )
            except Exception:
                continue
            if not world_ports:
                continue
            out[node_id] = [
                {
                    "name": name,
                    "x": port.center.x,
                    "y": port.center.y,
                    "orientation_deg": port.orientation_deg,
                    "kind": port.kind,
                }
                for name, port in world_ports.items()
            ]
        return out

    # -- mutations ---------------------------------------------------------- #

    def add_component(self, name: str, params: dict[str, Any] | None = None) -> str:
        """Append a component, returning its assigned id. Validates by building."""

        if name.startswith("user:"):
            from .parts import EditorParts
            from .workspaces import WorkspaceStore
            root = self._ws_store.root if self._ws_store is not None else WorkspaceStore().root
            return self.add_part(EditorParts(root).get(name), params)

        params = dict(params or {})
        params.pop("type", None)
        params.pop("id", None)
        with self._lock:
            component_id = self._new_id(name)
            entry = {"type": name, "id": component_id, **params}
            if "center" not in entry:
                # Default new parts onto the optical axis (y=0), stepped along x so
                # mirrors, lenses, etc. line up on the same plane instead of stacking.
                n = len(self._spec["components"])
                entry["center"] = [round(-90.0 + n * 26.0, 1), 0.0]
            component_from_spec(deepcopy(entry))  # validate (raises on bad params)
            self._spec["components"].append(entry)
            self._refresh_traces()  # a new optic may sit in a traced ray's path
            from optodraw.registry import SOURCE_COMPONENT_TYPES

            if name in SOURCE_COMPONENT_TYPES and any(
                b.get("traced_from") for b in self._spec.get("beams", [])
            ):
                # Trace mode is ON (other sources are emitting): a newly placed
                # source joins in. In a dark scene it stays dark until Trace.
                try:
                    self.trace_from(component_id)
                except Exception:
                    pass  # portless/degenerate placement must never block the add
            return component_id

    def add_part(self, definition, params=None):
        """Place a frozen definition and carry its tables through scene history."""
        from optodraw.parts import PartFactory
        from optodraw.schema import component_to_spec

        values = dict(params or {})
        values.pop("type", None)
        values.pop("id", None)
        with self._lock:
            values.setdefault("center", [-90 + len(self._spec["components"])*26, 0])
            component = PartFactory(definition)(**values)
            entry = component_to_spec(component)
            entry["id"] = self._new_id("userpart")
            candidate = deepcopy(self._spec)
            for key in ("part_definitions", "assets"):
                candidate.setdefault(key, {}).update(entry.pop(key, {}))
            candidate["components"].append(entry)
            scene_from_spec(candidate)
            self._spec = candidate
            self._refresh_traces()
            return entry["id"]

    def add_beam(
        self,
        path: list[Any],
        *,
        wavelength: float = 633.0,
        width: float = 0.8,
    ) -> str:
        """Add a free-space beam connecting a chain of component ids / points."""

        if not isinstance(path, list) or len(path) < 2:
            raise ValueError("a beam needs at least two endpoints (component ids or points)")
        if float(wavelength) <= 0:
            raise ValueError(f"wavelength must be > 0, got {wavelength!r}")
        with self._lock:
            beam_id = self._new_link_id("beam")
            entry = {
                "id": beam_id,
                "type": "Beam",
                "path": list(path),
                "wavelength": float(wavelength),
                "width": float(width),
            }
            candidate = deepcopy(self._spec)
            candidate.setdefault("beams", []).append(entry)
            scene_from_spec(candidate)  # validate refs resolve before committing
            self._spec.setdefault("beams", []).append(entry)
            return beam_id

    def add_route(
        self,
        src: list[Any],
        dst: list[Any],
        *,
        kind: str = "waveguide",
        path_type: str = "manhattan",
        smooth: bool = False,
        width: float | None = None,
        width2: float | None = None,
        backend: str = "local",
        waypoints: list[Any] | None = None,
    ) -> str:
        """Add a route between two ``[component_id, port]`` endpoints.

        ``path_type`` selects the routing geometry (``manhattan``, ``L``,
        ``straight``, ``smooth``). ``waypoints`` is an optional list of absolute
        ``(x, y)`` points the route must pass through (sent as ``steps`` so the
        endpoints still resolve from the live ports and follow device moves)."""

        if not (isinstance(src, (list, tuple)) and isinstance(dst, (list, tuple))):
            raise ValueError("route endpoints must be [component_id, port] pairs")
        with self._lock:
            route_id = self._new_link_id("route")
            entry: dict[str, Any] = {
                "id": route_id,
                "from": list(src),
                "to": list(dst),
                "kind": kind,
                "path_type": path_type,
                "backend": backend,
            }
            if width is not None:
                entry["width"] = float(width)  # else route_ports derives it from the ports
            if width2 is not None:
                entry["width2"] = float(width2)  # taper end width (auto from ports when omitted)
            if smooth:
                entry["smooth"] = True
            if waypoints:
                entry["steps"] = [{"x": float(p[0]), "y": float(p[1])} for p in waypoints]
            candidate = deepcopy(self._spec)
            candidate.setdefault("routes", []).append(entry)
            scene_from_spec(candidate)  # validate endpoints resolve
            self._spec.setdefault("routes", []).append(entry)
            return route_id

    def add_free_route(
        self,
        points: list[Any],
        *,
        kind: str = "waveguide",
        path_type: str = "manhattan",
        smooth: bool = False,
        width: float | None = None,
    ) -> str:
        """Add a free polyline route through explicit ``(x, y)`` points — no ports.

        This is how port-less components get wired: the route
        exists purely as drawn geometry, same as mesh/preset free polylines."""

        if len(points) < 2:
            raise ValueError("a free route needs at least 2 points")
        with self._lock:
            route_id = self._new_link_id("route")
            entry: dict[str, Any] = {
                "id": route_id,
                "points": [[float(p[0]), float(p[1])] for p in points],
                "kind": kind,
                "path_type": path_type,
            }
            if width is not None:
                entry["width"] = float(width)
            if smooth:
                entry["smooth"] = True
            candidate = deepcopy(self._spec)
            candidate.setdefault("routes", []).append(entry)
            scene_from_spec(candidate)  # validate the entry round-trips
            self._spec.setdefault("routes", []).append(entry)
            return route_id

    def update_route(self, route_id: str, *, waypoints: list[Any] | None = None, points: list[Any] | None = None) -> str:
        """Reshape an existing route. ``waypoints`` rewrites the interior points a
        port-anchored route must pass through (stored as ``steps`` so it still
        re-resolves + orthogonalizes from the live ports); ``points`` replaces a
        free polyline route's explicit vertices outright."""

        if waypoints is not None and points is not None:
            raise ValueError("update_route: provide either waypoints or points, not both")
        with self._lock:
            candidate = deepcopy(self._spec)
            found = next((e for e in candidate.get("routes", []) if e.get("id") == route_id), None)
            if found is None:
                raise KeyError(route_id)
            if waypoints is not None:
                if waypoints:
                    found["steps"] = [{"x": float(p[0]), "y": float(p[1])} for p in waypoints]
                else:
                    found.pop("steps", None)
                found.pop("points", None)
            if points is not None:
                found["points"] = [[float(p[0]), float(p[1])] for p in points]
                found.pop("steps", None)
            scene_from_spec(candidate)  # validate it still builds
            self._spec = candidate
            return route_id

    def _resolve_component_ref(self, ref: str) -> str | None:
        """Resolve a text reference to a component id (exact id, then label, ci)."""

        ref = str(ref).strip()
        ids = {c["id"] for c in self._spec.get("components", []) if c.get("id")}
        if ref in ids:
            return ref
        low = ref.lower()
        for c in self._spec.get("components", []):
            if str(c.get("id", "")).lower() == low or str(c.get("label", "")).lower() == low:
                return c["id"]
        return None

    def apply_text_routing(self, text: str, default_wavelength: float = 633.0) -> dict[str, Any]:
        """Create beams/routes from a port DSL, one connection per line.

        Syntax (chains allowed): ``laser.out -> dichroic.in -> obj.in``. The link
        kind is inferred from the port kinds (free-space -> beam, optical/waveguide
        -> waveguide route, fiber -> fiber route); override with a ``beam:`` /
        ``wg:`` / ``fiber:`` / ``electrical:`` prefix. A numeric prefix (``532:``)
        sets the beam wavelength/color; unprefixed beams use ``default_wavelength``.
        Re-applying replaces all text-defined links. Returns
        ``{"errors": [...], "created": n}``."""

        prefixes = {"beam": "beam", "wg": "waveguide", "waveguide": "waveguide",
                    "fiber": "fiber", "electrical": "electrical"}
        with self._lock:
            ports = self.ports_map()
            errors: list[str] = []
            new_beams: list[dict[str, Any]] = []
            new_routes: list[dict[str, Any]] = []

            def kind_for(cid: str, port: str) -> str:
                for p in ports.get(cid, []):
                    if p["name"] == port:
                        return p.get("kind", "free_space")
                return "free_space"

            for n, raw in enumerate(text.splitlines(), 1):
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                # Optional prefix before ':' — a kind keyword and/or a wavelength in
                # nm (which sets the beam color). e.g. "532:", "wg:", "wg 1550:".
                override = None
                override_wl = None
                if ":" in line:
                    head, tail = line.split(":", 1)
                    tokens = head.strip().lower().split()

                    def _is_nm(tok: str) -> bool:
                        return tok.replace(".", "", 1).isdigit()

                    if tokens and all(t in prefixes or _is_nm(t) for t in tokens):
                        for t in tokens:
                            if t in prefixes:
                                override = prefixes[t]
                            else:
                                override_wl = float(t)
                        line = tail.strip()
                toks = [t.strip() for t in line.split("->")]
                if len(toks) < 2:
                    errors.append(f"line {n}: expected 'a.port -> b.port'")
                    continue
                eps: list[tuple[str, str]] = []
                bad = False
                for tok in toks:
                    if "." not in tok:
                        errors.append(f"line {n}: '{tok}' must be component.port")
                        bad = True
                        break
                    cref, port = tok.rsplit(".", 1)
                    cid = self._resolve_component_ref(cref)
                    if cid is None:
                        errors.append(f"line {n}: unknown component '{cref.strip()}'")
                        bad = True
                        break
                    names = [p["name"] for p in ports.get(cid, [])]
                    if port.strip() not in names:
                        have = ", ".join(names) or "none"
                        errors.append(f"line {n}: '{cref.strip()}' has no port '{port.strip()}' (ports: {have})")
                        bad = True
                        break
                    eps.append((cid, port.strip()))
                if bad:
                    continue
                for (a_id, a_p), (b_id, b_p) in zip(eps, eps[1:]):
                    kind = override or kind_for(a_id, a_p)
                    if kind in {"beam", "free_space"}:
                        new_beams.append({"id": self._new_link_id("txbeam"), "type": "Beam",
                                          "path": [[a_id, a_p], [b_id, b_p]],
                                          "wavelength": override_wl if override_wl is not None else default_wavelength,
                                          "width": 0.8, "from_text": True})
                    else:
                        new_routes.append({"id": self._new_link_id("txroute"), "from": [a_id, a_p],
                                           "to": [b_id, b_p], "kind": kind, "path_type": "manhattan",
                                           "from_text": True})

            candidate = deepcopy(self._spec)
            candidate["beams"] = [b for b in candidate.get("beams", []) if not b.get("from_text")] + new_beams
            candidate["routes"] = [r for r in candidate.get("routes", []) if not r.get("from_text")] + new_routes
            scene_from_spec(candidate)  # validate before committing
            self._spec["beams"] = candidate["beams"]
            self._spec["routes"] = candidate["routes"]
            self.autosave()
            return {"errors": errors, "created": len(new_beams) + len(new_routes)}

    def _exit_length(self) -> float:
        """Exit tail after a ray's last interaction: ~1.5× the export frame, so
        rays visibly run past the scene without blowing up TikZ/GLB bounding
        boxes or the 3D camera fit (Fit in the canvas ignores tails anyway)."""

        width = float(self._spec.get("width") or 220.0)
        height = float(self._spec.get("height") or 140.0)
        return max(1.5 * max(width, height), 150.0)

    def trace_from(
        self, source_id: str, *, wavelength: float | None = None, exit_length: float | None = None,
        mode: str | None = None,
    ) -> str:
        """Physically trace rays from a source's output port through the scene's
        free-space optics — reflecting at mirrors, refracting at lenses, and
        **branching at beam splitters / dichroics**. In physical mode the source
        emits a parallel **bundle** (chief + marginal rays across its beam width),
        so lenses visibly converge the fan. Each ray branch becomes its own beam;
        re-tracing the same source replaces its trace.

        ``wavelength``: None uses the source's own wavelength (e.g. a 532 nm
        laser traces green). ``mode``: "schematic" | "physical", defaulting to
        the scene-level ``trace_mode`` meta field."""

        with self._lock:
            trace_mode = str(mode or self._spec.get("trace_mode") or DEFAULT_TRACE_MODE)
            scene = scene_from_spec(deepcopy(self._spec))
            traced = self._trace_source(
                scene, source_id, wavelength=wavelength,
                exit_length=self._exit_length() if exit_length is None else exit_length,
                mode=trace_mode,
            )
            if not traced:
                raise ValueError("trace produced no path")
            beams = self._spec.setdefault("beams", [])
            beams[:] = [b for b in beams if b.get("traced_from") != source_id]  # replace prior trace(s)
            first_id = ""
            for entry in traced:
                beam_id = self._new_link_id("trace")
                first_id = first_id or beam_id
                beams.append({"id": beam_id, "type": "Beam", "traced_from": source_id,
                              "trace_mode": trace_mode, **entry})
            self.autosave()
            return first_id


    def _trace_source(
        self, scene: Scene, source_id: str, *, wavelength: float | None, exit_length: float, mode: str,
    ) -> list[dict[str, Any]]:
        """Trace one source on a prebuilt scene → beam-entry dicts (chief first).

        Each dict carries path/wavelength/width/power/ray — ready to merge into a
        spec beam entry. ``wavelength=None`` resolves to the source's own."""

        from optodraw.core.raytrace import trace_bundle

        node = next((n for n in scene.walk() if getattr(n, "_id", "") == source_id), None)
        if node is None:
            raise KeyError(source_id)
        ports = node.ports()
        if not ports:
            raise ValueError(f"'{source_id}' has no port to trace from")
        port_name = "out" if "out" in ports else next(iter(ports))
        if wavelength is None:
            wavelength = float(getattr(node, "wavelength", 633.0) or 633.0)
        beam_width = float(getattr(node, "beam_width", 1.6) or 1.6)
        rays = max(1, min(int(getattr(node, "rays", 13) or 13), 61))
        ray_width = float(getattr(node, "ray_width", 0.45) or 0.45)
        beam_color = getattr(node, "beam_color", None)
        divergence = float(getattr(node, "divergence_deg", 0.0) or 0.0)
        results = trace_bundle(
            scene, (node, port_name), rays=rays, width=beam_width,
            divergence_deg=divergence,
            wavelength_nm=float(wavelength), exit_length=exit_length, mode=mode,
            plane=self._spec.get("beam_height"),
        )
        entries: list[dict[str, Any]] = []
        for result in results:
            # each vertex carries its out-of-plane height (z): the 3D bundle is a
            # true cone through foci (the renderer adds z to the beam-plane height)
            heights = [round(float(getattr(p, "z", 0.0)), 3) for p in result.points]
            if any(heights):
                path = [[round(float(p.x), 3), round(float(p.y), 3), z]
                        for p, z in zip(result.points, heights)]
            else:
                path = [[round(float(p.x), 3), round(float(p.y), 3)] for p in result.points]
            if len(path) < 2:
                continue
            ray = int(getattr(result, "ray", 0))
            entry: dict[str, Any] = {
                "path": path, "wavelength": float(wavelength),
                "width": ray_width, "ray": ray,  # uniform hairlines — a fan, not a hierarchy
                "power": round(float(getattr(result, "power", 1.0)), 4),
            }
            if beam_color:
                entry["color"] = str(beam_color)
            entries.append(entry)
        if getattr(node, "show_envelope", False):
            envelope = self._envelope_entry(results, entries)
            if envelope:
                entries.insert(0, envelope)  # behind the rays it wraps
        return entries

    @staticmethod
    def _envelope_entry(results: list[Any], entries: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The beam cone: out along one marginal ray and back along the other.

        Only for an unbranched bundle — once a splitter doubles the rays there is
        no single pair of marginals to wrap."""

        if len(results) != len(entries) or len(results) < 3:
            return None
        if len({int(getattr(r, "ray", 0)) for r in results}) != len(results):
            return None  # branched: ray indices repeat
        order = sorted(range(len(results)), key=lambda i: float(getattr(results[i], "offset", 0.0)))
        low, high = entries[order[0]], entries[order[-1]]
        if len(low["path"]) != len(high["path"]):
            return None  # the two edges took different routes (a clip or a miss)
        base = dict(high)
        base["path"] = [list(p) for p in high["path"]] + [list(p) for p in reversed(low["path"])]
        base["envelope"] = True
        base["ray"] = -1
        return base

    def _refresh_traces(self) -> None:
        """Recompute every traced beam (``traced_from``) against the current spec.

        Called (lock held) after spec mutations so traces stay live: move a
        mirror and its beam re-folds, delete the source and its trace goes too.
        Branch ids are reused in order so selection survives a refresh."""

        beams = self._spec.get("beams") or []
        by_source: dict[str, list[dict[str, Any]]] = {}
        for beam in beams:
            source = beam.get("traced_from")
            if source:
                by_source.setdefault(source, []).append(beam)
        if not by_source:
            return
        try:
            scene = scene_from_spec(deepcopy(self._spec))
        except Exception:
            return  # spec mid-edit or invalid: keep the existing beams
        component_ids: set[str] = set()

        def _collect_ids(entries: list) -> None:
            for candidate in entries:
                if isinstance(candidate, dict):
                    if candidate.get("id"):
                        component_ids.add(candidate["id"])
                    _collect_ids(candidate.get("children") or [])

        _collect_ids(self._spec.get("components", []))
        kept = [b for b in beams if not b.get("traced_from")]
        for source, olds in by_source.items():
            if source not in component_ids:
                continue  # source deleted → its traced beams go with it
            first = olds[0]
            # Scene-level trace_mode wins on refresh (the Scene-settings toggle
            # re-modes every live trace); the stored per-beam mode is the fallback.
            # Wavelength is NOT carried over — the source's own value wins, so
            # editing the laser re-tints and re-routes (dichroics) immediately.
            trace_mode = str(self._spec.get("trace_mode") or first.get("trace_mode") or DEFAULT_TRACE_MODE)
            try:
                traced = self._trace_source(
                    scene, source, wavelength=None, exit_length=self._exit_length(), mode=trace_mode
                )
            except (KeyError, ValueError):
                kept.extend(olds)  # keep the stale trace rather than lose the light
                continue
            old_ids = [b.get("id") for b in olds if b.get("id")]
            for index, entry in enumerate(traced):
                beam_id = old_ids[index] if index < len(old_ids) else self._new_link_id("trace")
                kept.append({"id": beam_id, "type": "Beam", "traced_from": source,
                             "trace_mode": trace_mode, **entry})
        self._spec["beams"] = kept

    def update(self, item_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Merge ``params`` into a component or beam/route, then revalidate. A new center of an inset brings its marks,
        as in :meth:`move_component`."""

        params = dict(params)
        params.pop("type", None)
        params.pop("id", None)
        with self._lock:
            for entry in self._spec["components"]:
                if entry.get("id") == item_id:
                    merged = {**entry, **params}
                    if "part_definition" in entry:
                        from optodraw.parts.serialization import read_definitions
                        if "parameters" in params:
                            merged["parameters"] = {**entry.get("parameters", {}), **params["parameters"]}
                        component_from_spec(deepcopy(merged), _definitions=read_definitions(self._spec))
                        candidate = deepcopy(self._spec)
                        for item in candidate["components"]:
                            if item.get("id") == item_id:
                                item.clear()
                                item.update(merged)
                        scene_from_spec(candidate)  # reject variants that remove connected ports
                    else:
                        component_from_spec(deepcopy(merged))  # validate
                    old, new = entry.get("center"), merged.get("center")
                    if entry.get("type") == "Inset" and _is_point(old) and _is_point(new):
                        self._follow_inset(item_id, float(new[0]) - float(old[0]), float(new[1]) - float(old[1]))
                    entry.clear()
                    entry.update(merged)
                    self._refresh_traces()  # param/angle edits re-fold traced rays
                    return deepcopy(entry)
            for key in ("beams", "routes"):
                for entry in self._spec.get(key, []):
                    if entry.get("id") == item_id:
                        if key == "beams" and entry.get("traced_from"):
                            return self._update_traced_beam(entry, params)
                        merged = {**entry, **params}
                        candidate = deepcopy(self._spec)
                        for e in candidate[key]:
                            if e.get("id") == item_id:
                                e.clear()
                                e.update(merged)
                        scene_from_spec(candidate)  # validate
                        entry.clear()
                        entry.update(merged)
                        return deepcopy(entry)
            raise KeyError(item_id)

    #: traced rays are DERIVED from their source — edits remap onto the laser
    _TRACED_BEAM_PARAM_MAP = {"wavelength": "wavelength", "width": "ray_width", "color": "beam_color"}

    def _update_traced_beam(self, entry: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Route edits of a traced ray to its source component and re-trace.

        Without this, the merge is applied and then immediately clobbered by the
        live refresh while the API response claims the edit succeeded."""

        source_id = entry.get("traced_from")
        beam_id = entry.get("id")
        source = None
        for candidate in self._spec.get("components", []):
            if candidate.get("id") == source_id:
                source = candidate
                break
        if source is None:
            raise KeyError(source_id)
        unsupported = set(params) - set(self._TRACED_BEAM_PARAM_MAP)
        if unsupported:
            raise ValueError(f"traced rays cannot edit: {', '.join(sorted(unsupported))}")
        source_changes = {
            self._TRACED_BEAM_PARAM_MAP[key]: value for key, value in params.items()
        }
        component_from_spec(deepcopy({**source, **source_changes}))
        source.update(source_changes)
        self._refresh_traces()
        refreshed = next((b for b in self._spec.get("beams", []) if b.get("id") == beam_id), None)
        return deepcopy(refreshed if refreshed is not None else entry)

    def move_component(
        self,
        component_id: str,
        *,
        center: list[float] | tuple[float, float],
        angle: float | None = None,
    ) -> dict[str, Any]:
        """Set a component's center (and optional angle) — the drag/rotate commit."""

        try:
            cx, cy = float(center[0]), float(center[1])
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError(f"center must be [x, y] with two numbers, got {center!r}") from error
        if not math.isfinite(cx) or not math.isfinite(cy):
            raise ValueError(f"center must be finite numbers, got {center!r}")
        if angle is not None:
            try:
                angle_f = float(angle)
            except (TypeError, ValueError) as error:
                raise ValueError(f"angle must be a finite number, got {angle!r}") from error
            if not math.isfinite(angle_f):
                raise ValueError(f"angle must be finite, got {angle!r}")
        with self._lock:
            entry = self._find(component_id)
            if entry.get("type") == "Inset" and _is_point(entry.get("center")):
                old = entry["center"]
                self._follow_inset(component_id, cx - float(old[0]), cy - float(old[1]))
            entry["center"] = [cx, cy]
            if angle is not None:
                entry["angle"] = float(angle)
            self._refresh_traces()  # live rays follow the moved/rotated optic
            return deepcopy(entry)

    def _follow_inset(self, component_id: str, dx: float, dy: float, *, components: list[Any] | None = None,
                      before: dict[str, Any] | None = None) -> None:
        """Shift the plain ``center`` of each mark that holds an anchor of this inset by the step of the inset.

        Anchor values are never rewritten, and a ``center`` that is itself an anchor is live. A plain end of a span is
        an offset from its center, so it takes the opposite step and stays where it was given. ``components`` is the
        list to change (the session's by default). With ``before`` (the old entries by id), a mark that is new, or
        that the same update moved too, stays as it is given."""

        def held(value: Any) -> bool:
            return isinstance(value, dict) and value.get("anchor") == component_id

        for entry in self._spec["components"] if components is None else components:
            ends = entry.get("ends") or []
            anchors = [entry.get("target"), *ends]
            if not any(held(a) for a in anchors) or not _is_point(entry.get("center")):
                continue
            if before is not None and (before.get(entry.get("id")) or {}).get("center") != entry["center"]:
                continue
            entry["center"] = [float(entry["center"][0]) + dx, float(entry["center"][1]) + dy]
            if ends:
                entry["ends"] = [end if isinstance(end, dict) else [end[0] - dx, end[1] - dy] for end in ends]

    def _release_insets(self, spec: dict[str, Any], before: list[Any], nodes: dict[str, Any] | None = None) -> None:
        """Release in ``spec`` every link to an inset of ``before`` (the old entries) that ``spec`` no longer holds, as
        a saved page releases an inset that left it: an anchor becomes the place it marks now, a zoom that joins the
        inset goes, and an ``over`` that names it is cleared. ``nodes`` are the parts of the old scene by id (built
        from the session's spec with none). Only an entry that held the link before changes."""

        from optodraw.app._scene_cache import _links

        now = {entry.get("id") for entry in _entries(spec["components"])}
        gone = {e["id"] for e in _entries(before) if e.get("type") == "Inset" and e.get("id") and e["id"] not in now}
        if not gone:
            return
        old = {entry.get("id"): entry for entry in _entries(before) if entry.get("id")}
        nodes = self._nodes() if nodes is None else nodes

        def place(value: dict[str, Any]) -> list[float]:
            inset = nodes[value["anchor"]]
            try:
                x, y = inset.at(*value["point"], **(value.get("options") or {})).xy()
            except (ValueError, ArithmeticError, TypeError):
                x, y = inset.world_position.x, inset.world_position.y
            return [float(x), float(y)]

        def release(entries: list[Any]) -> list[Any]:
            kept = []
            for entry in entries:
                if isinstance(entry.get("children"), list):
                    entry["children"] = release(entry["children"])
                named = _links(old[entry["id"]]) & gone if entry.get("id") in old else set()
                if {entry.get(key) for key in LINK_ENDS.get(entry.get("type"), ())} & named:
                    continue                                       # the zoom or cut of an inset that went goes too
                if entry.get("over") in named:
                    entry.pop("over")

                def held(value: Any) -> bool:
                    return isinstance(value, dict) and value.get("anchor") in named and "point" in value

                if held(entry.get("center")):                      # a note on the place: it stays there
                    (x, y), (dx, dy) = place(entry["center"]), entry.pop("center_offset", None) or (0.0, 0.0)
                    entry["center"] = [x + float(dx), y + float(dy)]
                mark = nodes.get(entry.get("id"))
                at = entry["center"] if _is_point(entry.get("center")) else (
                    (mark.world_position.x, mark.world_position.y) if mark is not None else (0.0, 0.0))
                for key, value in list(entry.items()):
                    if key == "ends" and isinstance(value, list):   # a span's end: an offset from the note
                        entry[key] = [[a - float(b) for a, b in zip(place(end), at)] if held(end) else end
                                      for end in value]
                    elif held(value):
                        entry[key] = place(value)
                kept.append(entry)
            return kept

        spec["components"] = release(spec["components"])

    def _nodes(self) -> dict[str, Any]:
        """The parts of the session's scene by id."""

        return {node._id: node for node in self._scene_cache.get(self._spec).walk() if getattr(node, "_id", "")}

    def arrange(
        self,
        ids: list[str] | None = None,
        *,
        strategy: str = "grid",
        columns: int = 3,
        spacing: float = 35.0,
        axis: str = "x",
    ) -> None:
        """Lay components out on a grid or line, in place.

        The placement math lives in :mod:`optodraw.layout`; this only feeds it the
        built components and writes the new centers back. ``ids`` empty = the whole
        scene. The block keeps its current top-left corner, so it tidies rather
        than teleports. A mark of an inset is never laid out: it goes with its
        inset, as in :meth:`move_component`, and a mark of two moved insets
        moves once, as in :meth:`load`."""

        from optodraw.app._scene_cache import _links
        from optodraw.layout import optimize_layout

        with self._lock:
            scene = scene_from_spec(deepcopy(self._spec))
            built = {getattr(node, "_id", ""): node for node in scene.walk()}
            components = self._spec.get("components", [])
            insets = {e.get("id") for e in _entries(components) if e.get("type") == "Inset"}
            wanted = [e["id"] for e in components
                      if e.get("id") in built and (not ids or e["id"] in ids)
                      and (e.get("type") == "Inset" or not _links(e) & insets)]
            if len(wanted) < 2:
                raise ValueError("arrange needs at least two components")
            targets = [built[cid] for cid in wanted]
            origin = (min(t.transform.position.x for t in targets),
                      max(t.transform.position.y for t in targets))
            options: dict[str, Any] = {"origin": origin}
            if strategy == "grid":
                options.update(columns=max(int(columns), 1), spacing=(float(spacing), float(spacing)))
            else:
                options.update(axis=axis, spacing=float(spacing))
            optimize_layout(targets, strategy=strategy, **options)
            before = {e.get("id"): {"center": e.get("center")} for e in components}
            for cid, node in zip(wanted, targets):
                entry, center = self._find(cid), [node.transform.position.x, node.transform.position.y]
                if entry.get("type") == "Inset" and _is_point(entry.get("center")):
                    old = entry["center"]
                    self._follow_inset(cid, center[0] - float(old[0]), center[1] - float(old[1]), before=before)
                entry["center"] = center
            self._refresh_traces()  # rays follow the tidied optics

    def delete(self, item_id: str) -> None:
        """Remove a component, beam, or route by id.

        Deleting ANY ray of a traced bundle switches that source's trace OFF
        (all its rays go) — otherwise the live refresh would just regrow the
        bundle from the source. Trace = light on, delete = light off.
        Deleting an inset leaves its marks on plain points (:meth:`_release_insets`)."""

        with self._lock:
            hit = next((e for e in _entries(self._spec.get("components")) if e.get("id") == item_id), None)
            inset = hit is not None and any(e.get("type") == "Inset" for e in _entries([hit]))
            before = list(self._spec.get("components", [])) if inset else []     # the entries, the deleted one too
            nodes = self._nodes() if inset else None
            for key in ("components", "beams", "routes"):
                items = self._spec.get(key, [])
                for index, entry in enumerate(items):
                    if entry.get("id") == item_id:
                        source = entry.get("traced_from") if key == "beams" else None
                        if source:
                            items[:] = [b for b in items if b.get("traced_from") != source]
                        else:
                            del items[index]
                        if key == "components":
                            removed_ids: set[str] = set()

                            def collect_ids(component: dict[str, Any]) -> None:
                                if component.get("id"):
                                    removed_ids.add(component["id"])
                                for child in component.get("children") or []:
                                    if isinstance(child, dict):
                                        collect_ids(child)

                            def references_removed(endpoint: Any) -> bool:
                                if isinstance(endpoint, str):
                                    return endpoint in removed_ids
                                if isinstance(endpoint, (list, tuple)):
                                    return bool(endpoint) and endpoint[0] in removed_ids
                                if isinstance(endpoint, dict):
                                    return any(endpoint.get(field) in removed_ids for field in ("id", "component", "component_id"))
                                return False

                            collect_ids(entry)
                            self._spec["beams"] = [
                                beam for beam in self._spec.get("beams", [])
                                if beam.get("traced_from") not in removed_ids
                                and not any(references_removed(point) for point in (beam.get("path") or []))
                            ]
                            self._spec["routes"] = [
                                route for route in self._spec.get("routes", [])
                                if not references_removed(route.get("from"))
                                and not references_removed(route.get("to"))
                            ]
                            metadata = self._spec.get("metadata")
                            layout = metadata.get("one_d_layout") if isinstance(metadata, dict) else None
                            if isinstance(layout, dict):
                                for removed_id in removed_ids:
                                    layout.pop(removed_id, None)
                            if nodes is not None:
                                self._release_insets(self._spec, before, nodes)
                        self._refresh_traces()  # drop orphaned traces / re-fold around the gap
                        return
            raise KeyError(item_id)

    def set_meta(self, **fields: Any) -> dict[str, Any]:
        """Update scene-level fields (title, width, height, platform)."""

        allowed = {"title", "width", "height", "frame_center", "platform", "background", "grid", "show_labels", "show_labels_3d", "show_grid_3d", "beam_height", "beam_style", "foundry_stack", "trace_mode", "chip_base"}
        with self._lock:
            candidate = deepcopy(self._spec)
            for key, value in fields.items():
                if key in allowed and value is not None:
                    candidate[key] = value
            _validate_scene_settings(candidate)
            scene_from_spec(candidate)
            self._spec = candidate
            if "trace_mode" in fields:
                self._refresh_traces()  # flipping schematic/physical re-traces the scene
            self.autosave()
            return deepcopy(self._spec)

    # -- internals ---------------------------------------------------------- #

    def _find(self, component_id: str) -> dict[str, Any]:
        for entry in self._spec["components"]:
            if entry.get("id") == component_id:
                return entry
        raise KeyError(component_id)

    def _existing_ids(self) -> set[str]:
        ids: set[str] = set()
        for key in ("components", "beams", "routes"):
            for entry in self._spec.get(key, []):
                if isinstance(entry, dict) and "id" in entry:
                    ids.add(entry["id"])
        return ids

    def _new_id(self, name: str) -> str:
        existing = self._existing_ids()
        base = str(name).lower()
        while True:
            self._counter += 1
            candidate = f"{base}_{self._counter}"
            if candidate not in existing:
                return candidate

    def _new_link_id(self, prefix: str) -> str:
        return self._new_id(prefix)

    def _ensure_ids(self) -> None:
        """Give every component/beam/route entry an id so it is selectable.

        Presets and imported scene files often omit beam/route ids; without one
        the renderer can't tag them and the front-end can't select/delete them."""

        for key, prefix in (("components", "c"), ("beams", "beam"), ("routes", "route")):
            for entry in self._spec.get(key, []):
                if isinstance(entry, dict) and not entry.get("id"):
                    entry["id"] = self._new_link_id(prefix)

    def _sync_counter(self) -> None:
        """Advance the counter past any numeric suffixes already in the spec."""

        for key in ("components", "beams", "routes"):
            for entry in self._spec.get(key, []):
                if not isinstance(entry, dict):
                    continue
                _, _, suffix = str(entry.get("id", "")).rpartition("_")
                if suffix.isdigit():
                    self._counter = max(self._counter, int(suffix))


class SessionStore:
    """A single active editor session bound to a persistent named workspace."""

    def __init__(self, workspace_store: Any = None, default_name: str = "Untitled") -> None:
        from optodraw.app.workspaces import WorkspaceStore, safe_name

        self._lock = RLock()
        self.workspaces = workspace_store or WorkspaceStore()
        self._safe = safe_name
        self._name = safe_name(self.workspaces.newest() or default_name)    # the page the user had open last
        spec = self.workspaces.load(self._name)
        self._session = EditorSession(spec) if spec is not None else EditorSession()
        self._session.bind_workspace(self.workspaces, self._name)
        if spec is None:
            self._session.autosave()  # materialize the default workspace on disk

    def get(self, session_id: str = "default") -> EditorSession:
        return self._session

    @property
    def current(self) -> str:
        return self._name

    def list(self) -> list[str]:
        return self.workspaces.list()

    def open(self, name: str) -> EditorSession:
        with self._lock:
            if not self.workspaces.exists(name):
                raise KeyError(name)
            self._session.close_insets()            # the page it leaves keeps the inset's new drawing: read after it
            spec = self.workspaces.load(name)
            if spec is None:
                raise KeyError(name)
            self._session.load(spec)
            self._name = self._safe(name)
            self._session.bind_workspace(self.workspaces, self._name)
            return self._session

    def create(self, name: str, spec: dict[str, Any] | None = None) -> EditorSession:
        with self._lock:
            # Names collapse to a filesystem stem, so "My Chip!" and "My Chip"
            # are one file: creating either used to empty the other without a
            # word. Save As is not allowed to destroy work under another name.
            if self.workspaces.exists(name):
                raise FileExistsError(f"a workspace named '{self._safe(name)}' already exists")
            stem = self.workspaces.save(name, spec or empty_scene_spec(title=self._safe(name)))
            return self.open(stem)

    def rename(self, old: str, new: str) -> str:
        with self._lock:
            if self._safe(new) != self._safe(old) and self.workspaces.exists(new):
                raise FileExistsError(f"a workspace named '{self._safe(new)}' already exists")
            stem = self.workspaces.rename(old, new)
            if self._name == self._safe(old):
                self._name = stem
                self._session.bind_workspace(self.workspaces, stem)
            return stem

    def delete(self, name: str) -> EditorSession:
        with self._lock:
            if self._name == self._safe(name):      # back to its page before the file goes, so nothing writes it again
                self._session.close_insets()
            self.workspaces.delete(name)
            if self._name == self._safe(name):
                remaining = self.workspaces.list()
                if remaining:
                    return self.open(remaining[0])
                return self.create("Untitled")
            return self._session

    def to_spec(self, session_id: str = "default") -> dict[str, Any]:
        return self._session.spec
