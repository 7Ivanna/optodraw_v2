"""FastAPI routes for the optodraw editor.

Every handler is a thin adapter over existing optodraw APIs:
``catalog`` for the palette, ``registry``/``schema`` for create + round-trip, and
``Scene.render_*`` for previews/export. No optical or geometry logic lives here.

FastAPI is imported at module top: this module is only loaded inside the GUI
process (via :mod:`optodraw.app.server`), never by the core library.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import time
import secrets
import threading
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from optodraw.animation3d.controls import light_changes, light_controls
from optodraw.animation3d.payload import animation_settings, build_light_payload, disabled_payload
from optodraw.animation_engine.errors import AnimationError, NotModelledYet
from optodraw.app.fragments import Fragments
from optodraw.app.session import SessionStore
from optodraw.components.optics.optomech import BEAM_HEIGHT
from optodraw.app.workspaces import safe_name as _safe_workspace_name

_MAX_UPLOAD_BYTES = 50_000_000  # 50 MB — large GDS still fits, 1 GB does not

_store = SessionStore()
_fragments = Fragments(_store.workspaces.root / ".fragments")    # the large inset drawings the payloads name by key
WORKSPACE_HEADER = "X-Optodraw-Workspace"   # the workspace the tab shows, sent with each change


def _same_workspace(request: Request) -> None:
    """Refuse a change from a tab that shows another workspace than the server has open (the server restarted, or
    another tab opened one): it would land in the wrong file. A request with no header passes: a script, a test or
    an MCP tool."""

    shown = request.headers.get(WORKSPACE_HEADER)
    if shown is not None and request.method not in {"GET", "HEAD"} and shown != _store.current:
        raise HTTPException(status_code=409, detail=f"this tab shows workspace '{shown}'; the editor now has "
                                                    f"'{_store.current}' open; reload the page")


router = APIRouter(prefix="/api", dependencies=[Depends(_same_workspace)])
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "optodraw_uploads"


def _session(session_id: str = "default"):
    return _store.get(session_id)


# -- request bodies --------------------------------------------------------- #


class NewSceneBody(BaseModel):
    title: str | None = None
    width: float | None = None
    height: float | None = None
    platform: str | None = None


class SceneMetaBody(BaseModel):
    title: str | None = None
    width: float | None = None
    height: float | None = None
    platform: str | None = None
    background: str | None = None  # artboard fill
    grid: float | None = None  # canvas dot spacing (px)
    show_labels: bool | None = None  # show component labels in the 2D view
    show_labels_3d: bool | None = None  # show component labels in the 3D view (off by default)
    show_grid_3d: bool | None = None  # show the ground grid/table in the 3D view
    beam_height: float | None = None  # optical/beam height free-space optics rise to (3D)
    beam_style: dict[str, float] | None = None  # the look of all the light: opacity, scale, by_wavelength
    foundry_stack: str | None = None  # scene-wide z-stack: components + GDS share one z-truth
    trace_mode: str | None = None  # ray tracing: "schematic" (snap to centers) | "physical" (real hits)
    chip_base: bool | None = None  # 3D auto die+carrier under chip scenes (false = off)


class PresetBody(BaseModel):
    name: str


# Deprecated alias kept for back-compat with older clients.
ExampleBody = PresetBody


class SimulateBody(BaseModel):
    kind: str
    params: dict[str, Any] = {}


class PolarizationBody(BaseModel):
    params: dict[str, Any] = {}


class GenerateBody(BaseModel):
    name: str
    params: dict[str, Any] = {}


class AnimateBody(BaseModel):
    recipe: str
    params: dict[str, Any] = {}


class FigureBody(BaseModel):
    template: str = "single_figure"
    formats: list[str] = ["svg", "json"]
    preset: str | None = None
    caption: str | None = None
    include_polarization: bool = False


class CreateComponentBody(BaseModel):
    name: str
    params: dict[str, Any] = {}


class UpdateComponentBody(BaseModel):
    params: dict[str, Any] = {}


class MoveComponentBody(BaseModel):
    center: list[float] = Field(min_length=2, max_length=2)
    angle: float | None = None


class BeamBody(BaseModel):
    path: list[Any]
    wavelength: float = 633.0
    width: float = 0.8


class RouteBody(BaseModel):
    # port-anchored route: src+dst; free polyline route: points (no ports)
    src: list[Any] | None = None
    dst: list[Any] | None = None
    points: list[Any] | None = None
    kind: str = "waveguide"
    path_type: str = "manhattan"
    smooth: bool = False
    # width None → derive from the connected ports (so manual routes match generators);
    # backend "local" → honor path_type (gdsfactory ignores it) and match the mesh.
    width: float | None = None
    width2: float | None = None  # taper end width
    backend: str = "local"
    waypoints: list[Any] = Field(default_factory=list)


class ArrangeBody(BaseModel):
    ids: list[str] | None = None  # None / empty = every component
    strategy: str = "grid"  # "grid" | "line"
    columns: int = 3
    spacing: float = 35.0
    axis: str = "x"  # line only: "x" | "y"


class TraceBody(BaseModel):
    source_id: str
    wavelength: float | None = None  # None = the source's own wavelength
    mode: str | None = None  # "schematic" | "physical"; None = scene trace_mode


class TextRouteBody(BaseModel):
    text: str = ""
    wavelength: float = 633.0


class CrossSectionBody(BaseModel):
    x: float | None = None  # absolute cut position in GDS units (vertical cut)
    pct: float | None = None  # cut position as 0..1 across the GDS width (scan slider)
    line: list[float] | None = None  # [x0,y0,x1,y1] ruler in GDS coords (arbitrary-angle cut)
    frame: str = "local"  # the frame of ``line``: "local" (the part's own) or "file" (the GDS file's, the layout view's ruler)
    window: float | None = None  # cut height window (defaults to full height)
    label: str = "A-A'"
    exaggeration: float = 28.0  # (legacy; cross-section now shows real microns)
    look: str = "schematic"  # schematic | slab | sem | top
    width_px: int | None = None  # sem and top: the image width (none: 2000, the full size)
    z_scale: float | None = None  # schematic: none stretches z only when a layer is too thin; 1 is true aspect
    mark: bool = True  # sem and top: the visible render marks (the PNG metadata stays)
    seed: int = 0  # sem and top: the noise
    depth: float | None = None  # slab: um behind the face (none: as deep as the window is wide)
    cutaway: bool = True  # slab: the cladding cut away in steps
    stage: str = "chip"  # top: device, chip or a step id
    tilt: float = 40.0  # top: degrees from straight down
    rotation: float = 0.0  # top: degrees the view turns


class PdkBody(BaseModel):
    name: str = "generic"


class StackBody(BaseModel):
    name: str  # bundled stack file stem (e.g. "siepic_ebeam")


class TechnologyFile(BaseModel):
    path: str  # the file's path in the picked folder, e.g. "klayout/d25/generic.lyd25"
    text: str


class TechnologyFolderBody(BaseModel):
    files: list[TechnologyFile]


class SceneBody(BaseModel):
    spec: dict[str, Any]
    edit: bool = False                  # an edit of the scene the session holds: the canvas sends it, an open does not
    whole: bool = False                 # the spec is a whole page (File > Open): leave every open inset first
    depth: int | None = None            # the open insets the editor shows: a mismatch is refused (409)


class InsetOpenBody(BaseModel):
    id: str


class InsetCloseBody(BaseModel):
    depth: int | None = None            # how many insets stay open: 0 is the page; one level up with none


class InsetBody(BaseModel):
    kind: str                           # a key of session.INSET_DEFAULTS: Text, Equation, Image, GdsView...
    source: dict[str, Any] = {}         # the record's values over the kind's defaults; a file is a path from /files
    of: str | None = None               # the inset it is made from: a section of a GDS view, a 3D view of one or a scene
    center: list[float] | None = Field(default=None, min_length=2, max_length=2)
    width: float = Field(default=50.0, gt=0)
    height: float | None = Field(default=None, gt=0)    # a free-shape source only (an empty box)
    label: str = ""
    frame: bool = False


class InsetSourceBody(BaseModel):
    source: dict[str, Any] = {}         # the record values that change; none builds it again as it is (Rebuild)


class InsetSizeBody(BaseModel):
    width: float = Field(gt=0)
    height: float | None = Field(default=None, gt=0)    # a free-shape source only


# -- rendering helpers ------------------------------------------------------ #


def _fragment_href(svg: str) -> str | None:
    """The URL of an inset drawing large enough to leave the payload, or None to draw it inline."""

    key = _fragments.key(svg)
    return None if key is None else f"/api/fragment/{key}"


def _editable_svg(session) -> str:
    """Render the session scene to an SVG string with selectable component ids. A large inset drawing goes by its
    URL (``GET /api/fragment/<key>``)."""

    scene = session.scene()
    ids = session.component_id_map(scene)
    drawing = scene.render_svg(editable=True, component_ids=ids, show_labels=session.spec.get("show_labels", True),
                               fragment_href=_fragment_href)
    return drawing.as_svg()


def _svg_payload(session, svg: str | None = None) -> dict[str, Any]:
    # Every mutating endpoint funnels through here, so this is the single autosave hook.
    session.autosave()
    svg = _editable_svg(session) if svg is None else svg
    return {"svg": svg, "spec": _fragments.keyed(session.spec), "workspace": _store.current, "path": session.path}


def _unkeyed(value: Any) -> Any:
    """A spec or a record the editor sent back, each ``svg_key`` of a large drawing back to its SVG. A key the store
    no longer holds (a sweep removed it) is refused (409)."""

    try:
        return _fragments.unkeyed(value)
    except KeyError as error:
        raise HTTPException(status_code=409, detail="this page names an inset drawing the server no longer holds: "
                                                    "reload the page") from error


def _same_level(session, depth: int | None) -> None:
    """Refuse a whole-scene edit sent for another level of open insets than the session holds: it would replace the
    wrong scene. The server restarted, or another tab opened or left an inset."""

    if depth is not None and depth != session.depth:
        raise HTTPException(status_code=409, detail="this page shows another level of open insets than the server "
                                                    "holds (the server restarted, or another tab moved): reload the page")


# -- catalog ---------------------------------------------------------------- #


@router.get("/health")
def health() -> dict[str, Any]:
    from optodraw import __version__

    return {"status": "ok", "version": __version__}


# -- workspaces ------------------------------------------------------------- #


class WorkspaceBody(BaseModel):
    name: str
    preset: str | None = None  # seed a new workspace from a built-in preset
    example: str | None = None  # deprecated alias for ``preset``


@router.get("/workspaces")
def list_workspaces() -> dict[str, Any]:
    from optodraw.presets import list_presets

    presets = list_presets()
    # ``presets`` is canonical; ``examples`` is a deprecated alias kept for old clients.
    return {"workspaces": _store.list(), "current": _store.current, "presets": presets, "examples": presets}


@router.post("/workspaces")
def create_workspace(body: WorkspaceBody) -> dict[str, Any]:
    spec = None
    seed = body.preset or body.example
    if seed:
        from optodraw.presets import build_preset

        try:
            spec = build_preset(seed).to_spec()
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"unknown preset '{seed}'") from error
    try:
        _store.create(body.name, spec)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


@router.post("/workspaces/{name}/open")
def open_workspace(name: str) -> dict[str, Any]:
    try:
        _store.open(name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"no workspace '{name}'") from error
    return _svg_payload(_session())


@router.put("/workspaces/{name}")
def rename_workspace(name: str, body: WorkspaceBody) -> dict[str, Any]:
    try:
        _store.rename(name, body.name)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"no workspace '{name}'") from error
    return {"workspaces": _store.list(), "current": _store.current}


@router.delete("/workspaces/{name}")
def delete_workspace(name: str) -> dict[str, Any]:
    if _safe_workspace_name(name) not in _store.list():
        raise HTTPException(status_code=404, detail=f"no workspace '{name}'")
    _store.delete(name)
    return _svg_payload(_session())


@router.get("/catalog")
def catalog(platform: str | None = None, category: str | None = None) -> dict[str, Any]:
    from optodraw.catalog import component_catalog, list_component_categories
    from .parts_api import store
    from .parts import describe_part

    components = component_catalog(platform=platform, category=category)
    for name, definition in store().definitions().items():
        if (platform is None or definition.platform == platform) and category in {None, "my_parts"}:
            components[name] = describe_part(definition)

    return {
        "components": components,
        "categories": list_component_categories() + ["my_parts"],
    }


@router.get("/catalog/{name:path}")
def describe(name: str, definition_hash: str | None = None) -> dict[str, Any]:
    from optodraw.catalog import describe_component

    try:
        if name.startswith("user:"):
            from .parts_api import definition_for
            from .parts import describe_part
            return describe_part(definition_for(name, definition_hash))
        return describe_component(name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@lru_cache(maxsize=512)
def _preview_svg(name: str, view: str = "2d") -> str:
    """Render one default component instance to a small standalone SVG."""

    from optodraw.core.scene import Scene
    from optodraw.registry import build_component

    component = build_component(name)
    if view == "1d":
        from optodraw.symbols import lookup

        return lookup(component).svg
    scene = Scene(width=90, height=90)
    scene.add(component)
    return scene.render_svg().as_svg()


@router.get("/preview/{name:path}")
def preview(name: str, view: str = "2d", definition_hash: str | None = None) -> dict[str, Any]:
    if view not in {"1d", "2d"}:
        raise HTTPException(status_code=400, detail="Preview view must be '1d' or '2d'")
    if name.startswith("user:"):
        from .parts_api import definition_for
        from optodraw.parts import UserPart
        try:
            component = UserPart(definition_for(name, definition_hash))
            if view == "1d":
                return {"svg": component.schematic_symbol().svg}
            from .parts_api import preview_svg
            return {"svg": preview_svg(component.definition)}
        except (KeyError, ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        return {"svg": _preview_svg(name, view)}
    except Exception:
        # Components that need a source file (GDSModel, CustomModel)
        # can't be built bare — serve a generic placeholder instead of a 404.
        placeholder = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
            '<rect x="6" y="10" width="36" height="28" rx="3" fill="#eef1f5" stroke="#9aa3ad"/>'
            '<path d="M12 32 22 20 28 27 33 22 38 32z" fill="#c3cbd6"/>'
            '<circle cx="17" cy="17" r="3" fill="#c3cbd6"/></svg>'
        )
        if view == "1d":
            placeholder = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
                '<rect x="6" y="10" width="36" height="28" fill="white" stroke="#111"/>'
                '<path d="M12 16 36 32 M12 32 36 16" fill="none" stroke="#111"/></svg>'
            )
        return {"svg": placeholder}


@lru_cache(maxsize=64)
def _preset_preview_svg(name: str) -> str:
    """Render a built-in preset scene to SVG for the preset gallery cards."""

    from optodraw.presets import build_preset

    return build_preset(name).render_svg().as_svg()


@router.get("/presets/{name}/preview")
def preset_preview(name: str) -> dict[str, Any]:
    try:
        return {"svg": _preset_preview_svg(name)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"unknown preset '{name}'") from error


@router.get("/materials")
def materials() -> dict[str, Any]:
    from optodraw.materials import list_material_presets

    return {"presets": list_material_presets()}


# -- scene ------------------------------------------------------------------ #


@router.get("/scene")
def get_scene(whole: bool = False) -> dict[str, Any]:
    """The scene the session holds; with ``whole``, the page, each open inset drawn again (Save)."""

    return _session().whole_spec() if whole else _session().spec


@router.post("/scene")
def set_scene(body: SceneBody) -> dict[str, Any]:
    from optodraw.schema import scene_from_spec

    session = _session()
    if not body.whole:
        _same_level(session, body.depth)
    spec = _unkeyed(body.spec)
    try:
        if body.whole:
            scene_from_spec(copy.deepcopy(spec))        # a page that does not load leaves the open insets as they are
            session.close_insets()
        session.load(spec, edit=body.edit)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(session)


@router.post("/scene/inset/open")
def open_inset(body: InsetOpenBody) -> dict[str, Any]:
    """Open a scene inset: the session edits its scene until the way back."""

    try:
        _session().open_inset(body.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"no part '{body.id}'") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


@router.post("/scene/inset/close")
def close_inset(body: InsetCloseBody) -> dict[str, Any]:
    """Go back out of open insets; each changed one draws again."""

    try:
        _session().close_inset(body.depth)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


# What a build of an inset source can raise: a bad value, a missing or unreadable file, a missing tool or extra.
_BUILD_ERRORS = (ValueError, TypeError, OSError, RuntimeError, ImportError)


@router.post("/inset")
def make_inset(body: InsetBody) -> dict[str, Any]:
    """Make an inset of a palette kind from plain values; its source builds once. Answers its id and the payload."""

    placement = body.model_dump(include={"center", "width", "height", "label", "frame"}, exclude_none=True)
    source = _unkeyed(body.source)                  # a copy of the open scene comes with its large drawings by key
    try:
        inset_id = _session().add_inset(body.kind, source, of=body.of, **placement)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"no inset '{body.of}'") from error
    except _BUILD_ERRORS as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": inset_id, **_svg_payload(_session())}


def _edit_inset(inset_id: str, **changes: Any) -> dict[str, Any]:
    try:
        _session().edit_inset(inset_id, **changes)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"no inset '{inset_id}'") from error
    except _BUILD_ERRORS as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


@router.post("/inset/{inset_id}/source")
def set_inset_source(inset_id: str, body: InsetSourceBody) -> dict[str, Any]:
    """Change an inset's source (text, file, page, stack, region, direction) and build it once; an empty change
    builds it again as it is (Rebuild)."""

    return _edit_inset(inset_id, source=_unkeyed(body.source))


@router.post("/inset/{inset_id}/size")
def resize_inset(inset_id: str, body: InsetSizeBody) -> dict[str, Any]:
    """Give an inset a new width (and a height, for a free-shape source); its source builds again at that size. A
    source the editor may not build is refused: ``PATCH /component`` with a width scales its saved drawing instead."""

    return _edit_inset(inset_id, width=body.width, height=body.height)


@router.post("/files")
async def keep_file(request: Request, filename: str = "file") -> dict[str, Any]:
    """Keep a picked file (raw bytes) in the files folder of the open workspace. The answer's ``path`` is what an
    inset record names: relative to the workspace."""

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large ({len(data)} bytes > {_MAX_UPLOAD_BYTES})")
    return {"path": _store.workspaces.keep_file(_store.current, filename, data)}


@router.get("/fragment/{key}")
def get_fragment(key: str) -> Response:
    """An inset drawing by the key the scene payload names it by, sanitized. A key names one drawing for ever, so the
    browser keeps it; the page it would open as runs nothing."""

    from optodraw.figure.fragment import sanitized

    try:
        svg = _fragments.get(key)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="no drawing with this key: reload the page") from error
    return Response(content=sanitized(svg), media_type="image/svg+xml", headers={
        "Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'"})


class SceneTextBody(BaseModel):
    text: str
    depth: int | None = None            # the open insets the text was read at: a mismatch is refused (409)


@router.get("/scene/text")
def get_scene_text() -> dict[str, Any]:
    """The scene as the Code tab's YAML text, and the lines of each entry."""

    from optodraw.app.spec_text import spec_text

    return spec_text(_session().spec)


@router.post("/scene/text")
def set_scene_text(body: SceneTextBody) -> dict[str, Any]:
    """Apply the Code tab's text as an edit of the scene. A fault answers 400 with its message and its line."""

    from optodraw.app.spec_text import SpecTextError, error_line, spec_from_text, spec_text

    session = _session()
    _same_level(session, body.depth)
    held = session.spec
    try:
        spec = spec_from_text(body.text, held)
    except SpecTextError as error:
        raise HTTPException(status_code=400, detail={"message": str(error), "line": error.line}) from error
    try:
        session.load(spec, edit=True)
    except Exception as error:                      # typed text can fail in any way: say how, and where
        words = error.args[0] if isinstance(error, KeyError) and error.args else str(error)   # no quotes of a KeyError
        detail = {"message": str(words) or type(error).__name__, "line": error_line(spec, body.text)}
        raise HTTPException(status_code=400, detail=detail) from error
    try:
        svg = _editable_svg(session)                # a value can build and still not draw: an angle with no number
    except Exception as error:
        session.load(held)
        raise HTTPException(status_code=400, detail={"message": f"the scene does not draw: {error}",
                                                     "line": None}) from error
    return {**_svg_payload(session, svg), **spec_text(session.spec)}


@router.post("/scene/new")
def new_scene(body: NewSceneBody) -> dict[str, Any]:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        _session().reset(**fields)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


@router.patch("/scene/meta")
def set_meta(body: SceneMetaBody) -> dict[str, Any]:
    try:
        _session().set_meta(**body.model_dump())
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


def _seed_preset(name: str) -> dict[str, Any]:
    """Seed the current scene from a built-in preset (no forced workspace)."""

    from optodraw.presets import build_preset

    try:
        spec = build_preset(name).to_spec()
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=404, detail=f"unknown preset '{name}'") from error
    if _session().depth:                            # a preset replaces the page: the editor goes back first
        raise HTTPException(status_code=409, detail="go back to the page first: a preset replaces the whole page")
    _session().load(spec)
    return _svg_payload(_session())


@router.post("/scene/arrange")
def arrange_scene(body: ArrangeBody) -> dict[str, Any]:
    """Tidy components onto a grid or a line (selection, or the whole scene)."""

    try:
        _session().arrange(
            body.ids, strategy=body.strategy, columns=body.columns,
            spacing=body.spacing, axis=body.axis,
        )
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


@router.post("/scene/preset")
def load_preset(body: PresetBody) -> dict[str, Any]:
    """Seed the current scene from a built-in preset."""

    return _seed_preset(body.name)


@router.post("/scene/example")
def load_example(body: PresetBody) -> dict[str, Any]:
    """Deprecated alias for ``/scene/preset``."""

    return _seed_preset(body.name)


# -- components ------------------------------------------------------------- #


@router.post("/component")
def create_component(body: CreateComponentBody) -> dict[str, Any]:
    try:
        component_id = _session().add_component(body.name, body.params)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": component_id, **_svg_payload(_session())}


def _engine_part(scene: Any, component_id: str) -> tuple[Any, str]:
    """``(scene, the engine's id of the part)`` for an editor component id; 404 for none, 400 for a route or beam."""

    from optodraw.animation_engine.ids import scene_ids

    ids = scene_ids(scene)
    for node in scene.walk():
        if getattr(node, "_id", "") == component_id:
            sid = ids.get(id(node), "")
            if not sid or sid.startswith("route") or not hasattr(node, "ports"):
                raise HTTPException(status_code=400, detail=f"'{component_id}' has no light settings")
            return scene, sid
    raise HTTPException(status_code=404, detail=f"Unknown item '{component_id}'")


@router.get("/component/{component_id}/light")
def component_light(component_id: str) -> dict[str, Any]:
    """The part's light settings (``animation3d.controls``): per control its key, unit, range and current value."""

    session = _session()
    scene, sid = _engine_part(session.scene(), component_id)
    _, params, inputs = animation_settings(session.spec.get("metadata"))
    try:
        return {"controls": light_controls(scene, sid, params=params, inputs=inputs)}
    except (AnimationError, NotModelledYet) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch("/component/{component_id}")
def update_component(component_id: str, body: UpdateComponentBody) -> dict[str, Any]:
    """Merge ``params`` into the component. ``params.light`` is not a component field: its values are the part's light
    settings (``GET /component/<id>/light``, keyed by control), stored under the engine's keys in
    ``metadata.animation.params``; a value at its default removes the key."""

    params = dict(body.params)
    light = params.pop("light", None)
    changes: dict[str, float | None] = {}
    if light is not None:
        if not isinstance(light, dict):
            raise HTTPException(status_code=400, detail="light must be an object")
        session = _session()
        scene, sid = _engine_part(session.scene(), component_id)
        _, current, inputs = animation_settings(session.spec.get("metadata"))
        try:
            changes = light_changes(scene, sid, light, params=current, inputs=inputs)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except (AnimationError, NotModelledYet) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        if params or not light:
            _session().update(component_id, params)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Unknown item '{component_id}'") from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if changes:
        _session().set_light_params(changes)
    return _svg_payload(_session())


@router.get("/ports")
def ports() -> dict[str, Any]:
    return {"ports": _session().ports_map()}


@router.post("/beam")
def create_beam(body: BeamBody) -> dict[str, Any]:
    try:
        beam_id = _session().add_beam(body.path, wavelength=body.wavelength, width=body.width)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": beam_id, **_svg_payload(_session())}


@router.post("/trace")
def trace(body: TraceBody) -> dict[str, Any]:
    try:
        beam_id = _session().trace_from(body.source_id, wavelength=body.wavelength, mode=body.mode)
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": beam_id, **_svg_payload(_session())}


@router.post("/route")
def create_route(body: RouteBody) -> dict[str, Any]:
    if body.points is not None:
        try:
            route_id = _session().add_free_route(
                body.points,
                kind=body.kind,
                path_type=body.path_type,
                smooth=body.smooth,
                width=body.width,
            )
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"id": route_id, **_svg_payload(_session())}
    if body.src is None or body.dst is None:
        raise HTTPException(status_code=400, detail="route needs src+dst ports, or points for a free route")
    try:
        route_id = _session().add_route(
            body.src,
            body.dst,
            kind=body.kind,
            path_type=body.path_type,
            smooth=body.smooth,
            width=body.width,
            width2=body.width2,
            backend=body.backend,
            waypoints=body.waypoints,
        )
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": route_id, **_svg_payload(_session())}


class RouteEditBody(BaseModel):
    waypoints: list[Any] | None = None
    points: list[Any] | None = None


@router.patch("/route/{route_id}")
def edit_route(route_id: str, body: RouteEditBody) -> dict[str, Any]:
    """Reshape a route — drag-to-reroute sends the new interior waypoints (or, for a
    free polyline route, its new vertices)."""
    try:
        _session().update_route(route_id, waypoints=body.waypoints, points=body.points)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"route {route_id} not found") from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": route_id, **_svg_payload(_session())}


@router.post("/route/text")
def route_text(body: TextRouteBody) -> dict[str, Any]:
    """Create beams/routes from a port DSL (one connection per line)."""
    try:
        result = _session().apply_text_routing(body.text, default_wavelength=body.wavelength)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {**result, **_svg_payload(_session())}


@router.post("/component/{component_id}/move")
def move_component(component_id: str, body: MoveComponentBody) -> dict[str, Any]:
    try:
        _session().move_component(component_id, center=body.center, angle=body.angle)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Unknown component '{component_id}'") from error
    except (ValueError, IndexError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _svg_payload(_session())


@router.delete("/component/{component_id}")
def delete_component(component_id: str) -> dict[str, Any]:
    try:
        _session().delete(component_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Unknown item '{component_id}'") from error
    return _svg_payload(_session())


# -- render / export -------------------------------------------------------- #


@router.get("/render/1d.svg")
def render_1d_svg() -> Response:
    from optodraw.notebook_1d import render_notebook_1d

    return Response(content=render_notebook_1d(_session().scene()), media_type="image/svg+xml")


@router.get("/scene/1d/model")
def one_d_model() -> dict[str, Any]:
    """The 1D schematic: each part's symbol and ports, the links, the marks, and every part's position."""

    from optodraw.figure.inset import views_note
    from optodraw.symbols.schematic import build_schematic, junctions

    scene = _session().scene()
    schematic = build_schematic(scene)
    components = [
        {"id": item.key, "type": item.component.component_type, "label": item.label,
         "label_above": item.label_above, "symbol": item.symbol.to_dict(),
         "label_at": [round(item.label_at[0] - item.x, 2), round(item.label_at[1] - item.y, 2), item.label_at[2]]}
        for item in schematic.items
    ]
    links = [
        {
            "start_id": schematic.items[link.start].key, "start_port": link.start_port,
            "end_id": schematic.items[link.end].key, "end_port": link.end_port, "kind": link.kind,
            **({"route": [[round(x, 2), round(y, 2)] for x, y in schematic.routes[index]]}
               if index in schematic.routes else {}),
        }
        for index, link in enumerate(schematic.links)
    ]
    positions = {item.key: [item.x, item.y] for item in schematic.items}
    dots = [[round(x, 2), round(y, 2)] for x, y in junctions(schematic)]

    def points(lines):
        return [[[round(x, 2), round(y, 2)] for x, y in line] for line in lines]

    marks = [{"kind": mark.kind, "lines": points(mark.lines), "heads": points(mark.heads), "dashed": mark.dashed,
              "color": mark.color, "label": mark.label,
              "label_at": [round(mark.label_at[0], 2), round(mark.label_at[1], 2), mark.label_at[2]]}
             for mark in schematic.marks]            # a region's box, a bracket, a stage's motion mark
    return {"components": components, "links": links, "positions": positions, "junctions": dots, "marks": marks,
            "note": views_note(scene, "1D")}


@router.put("/scene/1d/layout")
def save_one_d_layout(positions: dict[str, list[float]]) -> dict[str, Any]:
    import math

    session = _session()
    spec = session.spec
    ids = {entry.get("id") for entry in spec.get("components", [])}
    cleaned = {}
    for component_id, point in positions.items():
        if component_id not in ids:
            continue
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise HTTPException(status_code=400, detail=f"invalid 1D position for '{component_id}'")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=f"invalid 1D position for '{component_id}'") from error
        if not (math.isfinite(x) and math.isfinite(y) and x >= 0 and y >= 0):
            raise HTTPException(status_code=400, detail=f"invalid 1D position for '{component_id}'")
        cleaned[component_id] = [x, y]
    spec.setdefault("metadata", {})["one_d_layout"] = cleaned
    session.load(spec)
    session.autosave()
    return {"positions": cleaned}


@router.get("/render/svg")
def render_svg() -> dict[str, Any]:
    return {"svg": _editable_svg(_session()), "path": _session().path, "workspace": _store.current}


_LIGHT_CACHE: dict[str, dict[str, Any]] = {}      # light payloads by scene: an unchanged scene does not rebuild
_LIGHT_CACHE_SIZE = 4
_LIGHT_LOCK = threading.Lock()


def _light_for(scene: Any, spec: dict[str, Any], tour: bool = False) -> dict[str, Any]:
    """The engine's light payload for the editor, from ``metadata.animation`` (look, params, inputs, tour). With
    ``tour`` it carries the drive tables of the tour's driven stops (slow: one engine solve per sample)."""

    key = json.dumps([spec, (spec.get("metadata") or {}).get("animation"), tour], sort_keys=True, default=str)
    with _LIGHT_LOCK:
        cached = _LIGHT_CACHE.get(key)
    if cached is not None:
        return cached
    look, params, inputs = animation_settings(spec.get("metadata"))
    try:
        payload = build_light_payload(scene, params=params, inputs=inputs, look=look, drives="tour" if tour else None)
    except NotModelledYet as error:
        if params is not None or inputs is not None:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return disabled_payload([f"no light: {error}"], look=look)     # not cached: cheap, and it says why
    except AnimationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:                                         # an unknown look
        raise HTTPException(status_code=422, detail=str(error)) from error
    with _LIGHT_LOCK:
        while len(_LIGHT_CACHE) >= _LIGHT_CACHE_SIZE:
            _LIGHT_CACHE.pop(next(iter(_LIGHT_CACHE)), None)
        _LIGHT_CACHE[key] = payload
    return payload


@router.get("/scene3d")
def scene3d(light: bool = False, tour: bool = False) -> dict[str, Any]:
    """Return the 3D scene-data items for in-place rebuilds of the editor's 3D view.

    ``light`` is null unless asked for with ``light=1``: the payload is slow to build on a large chip, so the
    editor asks for it only while the light is on. ``tour=1`` asks for it with the tour's drive tables (Play tour)."""

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    session = _session()
    scene = session.scene()
    meta = session.spec
    renderer = ThreeJsRenderer(
        scene, editable=True, component_ids=session.component_id_map(scene),
        show_labels=meta.get("show_labels_3d", False), show_grid=meta.get("show_grid_3d", True),
        beam_height=meta.get("beam_height", BEAM_HEIGHT),
    )
    return {"items": renderer._collect_scene_data(), "light": _light_for(scene, meta, tour) if light or tour else None}


@router.get("/render/threejs", response_class=HTMLResponse)
def render_threejs(editable: bool = False) -> str:
    session = _session()
    scene = session.scene()
    meta = session.spec
    opts = {
        "show_labels": meta.get("show_labels_3d", False),
        "show_grid": meta.get("show_grid_3d", True),
        "beam_height": meta.get("beam_height", BEAM_HEIGHT),
        "show_chip_base": meta.get("chip_base", True) is not False,
    }
    if not editable:
        opts["look"], opts["params"], opts["inputs"] = animation_settings(meta.get("metadata"))
    if editable:
        return scene.render_threejs(editable=True, component_ids=session.component_id_map(scene), **opts)
    return scene.render_threejs(**opts)


@router.get("/render/tikz", response_class=PlainTextResponse)
def render_tikz(view: str = "2d") -> str:
    if view not in {"1d", "2d"}:
        raise HTTPException(status_code=400, detail="TikZ view must be '1d' or '2d'")
    return _session().scene().render_tikz(view=view)


@router.post("/gds/import")
async def import_gds(request: Request, filename: str = "import.gds") -> dict[str, Any]:
    """Import a GDS layout (raw bytes) as a GDSModel component in the scene."""

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty GDS upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"upload too large ({len(data)} bytes > {_MAX_UPLOAD_BYTES})")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "import.gds"
    path = _UPLOAD_DIR / f"{secrets.token_hex(8)}_{safe}"
    path.write_bytes(data)
    session = _session()
    try:
        cid = session.add_component("GDSModel", {"source": str(path), "label": Path(safe).stem})
    except Exception as error:  # invalid GDS / unreadable cell
        raise HTTPException(status_code=400, detail=f"could not load GDS: {error}") from error
    # GDSModel loads geometry lazily-tolerantly — a corrupt file yields an empty
    # placeholder. Reject it here so the user sees an error, not a blank chip.
    if not getattr(_find_gds_node(cid), "_polygons_by_spec", None):
        session.delete(cid)
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"'{safe}' is not a readable GDS file (no layout geometry found)")
    # A die is nearly always bigger than a fresh artboard, and the export frame
    # is what an SVG or PNG gets cropped to — so the first thing a user did was
    # export half a chip. Growing the frame is only safe when the import IS the
    # scene; once there is other work, the frame is a decision somebody made.
    if len(session.spec["components"]) == 1:
        scene = session.scene()
        scene.fit_frame(margin=max(scene.width, scene.height) * 0.04)
        session.set_meta(width=scene.width, height=scene.height, frame_center=list(scene.frame_center))
    return {"id": cid, **_svg_payload(session)}


@router.post("/model/import")
async def import_model(request: Request, filename: str = "model.glb") -> dict[str, Any]:
    """Import a 3D model (GLB/GLTF/OBJ/STL) as a CustomModel component."""

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty model upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"upload too large ({len(data)} bytes > {_MAX_UPLOAD_BYTES})")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "model.glb"
    path = _UPLOAD_DIR / f"{secrets.token_hex(8)}_{safe}"
    path.write_bytes(data)
    session = _session()
    try:
        cid = session.add_component("CustomModel", {"source": str(path), "label": Path(safe).stem})
    except Exception as error:  # unreadable / unsupported model
        raise HTTPException(status_code=400, detail=f"could not load model: {error}") from error
    return {"id": cid, **_svg_payload(session)}


def _find_gds_node(component_id: str) -> Any:
    """Return the live GDSModel node for ``component_id`` (404 if absent)."""

    scene = _session().scene()
    for node in scene.walk():
        if getattr(node, "_id", "") == component_id and node.component_type == "GDSModel":
            return node
    raise HTTPException(status_code=404, detail=f"no GDSModel '{component_id}'")


def _apply_gds_layer_styles(component_id: str, styles: dict[Any, dict[str, Any]]) -> dict[str, Any]:
    """Merge per-layer styles into a GDSModel's ``layer_stack`` and return a payload.

    Shared by the techfile and PDK endpoints — keys are stringified ``"layer/dtype"``
    so they round-trip through the JSON spec; existing overrides are preserved."""

    if not styles:
        raise HTTPException(status_code=400, detail="no layers to apply")
    _find_gds_node(component_id)  # 404 if the target isn't a GDSModel
    session = _session()
    entry = next((c for c in session.spec["components"] if c.get("id") == component_id), None)
    if entry is None:  # pragma: no cover - guarded by _find_gds_node above
        raise HTTPException(status_code=404, detail=f"no GDSModel '{component_id}'")
    merged = dict(entry.get("layer_stack") or {})
    for layer_spec, style in styles.items():
        key = f"{layer_spec[0]}/{layer_spec[1]}" if isinstance(layer_spec, tuple) else str(layer_spec)
        merged[key] = {**merged.get(key, {}), **{k: v for k, v in style.items() if v is not None}}
    session.update(component_id, {"layer_stack": merged})
    return {"applied": len(styles), "layers": _find_gds_node(component_id).layer_records(), **_svg_payload(session)}


# Open photonics/electronics PDKs distributed as gdsfactory packages. They appear
# in the PDK picker automatically once their package is installed (pip install …),
# so users get SiEPIC / IHP / SkyWater etc. without us hand-coding their stacks.
# (id, label, module path or None for the built-in generic PDK)
_KNOWN_PDKS: list[tuple[str, str, str | None]] = [
    ("generic", "gdsfactory generic", None),
    ("cornerstone_si500", "CornerStone Si 500 nm", "cspdk.si500"),
    ("cornerstone_sin300", "CornerStone SiN 300 nm", "cspdk.sin300"),
    ("siepic_ebeam", "SiEPIC EBeam (UBC)", "ubcpdk"),
    ("sky130", "SkyWater sky130", "sky130"),
    ("gf180", "GlobalFoundries GF180MCU", "gf180"),
    ("ihp_sg13g2", "IHP SG13G2", "ihpsg13g2"),
]


def _resolve_pdk_object(module: str | None) -> Any:
    if module is None:
        try:
            from gdsfactory.gpdk import get_generic_pdk

            return get_generic_pdk()
        except Exception:
            pass
        try:
            from gdsfactory.gpdk import PDK as pdk

            return pdk
        except Exception:  # gdsfactory 8.x
            from gdsfactory.generic_tech import get_generic_pdk

            return get_generic_pdk()
    import importlib

    mod = importlib.import_module(module)
    pdk = getattr(mod, "PDK", None)
    if pdk is None:
        raise ValueError(f"module '{module}' has no PDK")
    return pdk


def _discover_pdks() -> list[dict[str, str]]:
    """List installed gdsfactory PDKs (generic + any open foundry packages)."""

    found: list[dict[str, str]] = []
    for pid, label, module in _KNOWN_PDKS:
        try:
            _resolve_pdk_object(module)
        except Exception:
            continue  # package not installed
        found.append({"id": pid, "label": label})
    return found


def _gdsfactory_pdk(name: str) -> Any:
    """Activate and return a known gdsfactory PDK by id."""

    module: str | None = None
    matched = False
    for pid, _label, mod in _KNOWN_PDKS:
        if pid == name or (name in ("", "generic_tech") and pid == "generic"):
            module, matched = mod, True
            break
    if not matched:
        raise HTTPException(status_code=400, detail=f"unknown PDK '{name}'")
    try:
        pdk = _resolve_pdk_object(module)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"PDK '{name}' is not installed: {error}") from error
    pdk.activate()
    return pdk


@router.get("/gds/{component_id}/layers")
def gds_layers(component_id: str) -> dict[str, Any]:
    """Return the GDS layer records for a GDSModel (for the editor layer panel)."""

    return {"layers": _find_gds_node(component_id).layer_records()}


_XS_LOOKS = ("schematic", "slab", "sem", "top")
_TOP_VIEWS: dict[tuple, Any] = {}  # the last top views, so a tilt change reuses their cuts


def _gds_layout_and_stack(node: Any) -> tuple[Any, Any]:
    """The part's polygons as a ``GDSLayout`` and the stack it carries (its layer styles and oxide), so the
    cut and the part's 3D view read one stack."""

    from optodraw.gds.layout import GDSLayerRecord, GDSLayout
    from optodraw.gds.parsers import LayerStackSpec

    polys_by_spec = node._polygons_by_spec
    styles: dict[Any, dict[str, Any]] = {}
    for spec in set(node._inferred_layer_stack) | set(node.layer_stack):
        combined = {**node._inferred_layer_stack.get(spec, {}), **node.layer_stack.get(spec, {})}
        zmin = combined.get("z_offset", combined.get("zmin"))
        style = {key: combined[key] for key in ("name", "role", "visible", "sidewall_deg", "polarity", "color")
                 if combined.get(key) is not None}
        if zmin is not None and combined.get("thickness") is not None:
            style.update(zmin=float(zmin), thickness=float(combined["thickness"]))
        style["material_preset"] = str(combined.get("material_preset", combined.get("preset", "silicon")))
        styles[spec] = style
    tops = [s["zmin"] + s["thickness"] for s in styles.values() if "zmin" in s and s.get("visible", True) is not False]
    oxide = {"box_depth": float(node.box_depth), "handle_thickness": float(node.handle_thickness),
             "cladding_top": float(node.cladding_top) or max(tops, default=0.0)}
    if float(getattr(node, "passivation", 0.0)) > 0:
        oxide["passivation"] = float(node.passivation)
    records = [GDSLayerRecord(spec=spec, name=str(styles.get(spec, {}).get("name", "")), description="",
                              color="#000000", opacity=1.0, thickness=0.0, zmin=0.0, material_preset="",
                              polygons=list(polygons), matched_pdk=False)
               for spec, polygons in polys_by_spec.items()]
    xs = [x for polygons in polys_by_spec.values() for polygon in polygons for x, _ in polygon]
    ys = [y for polygons in polys_by_spec.values() for polygon in polygons for _, y in polygon]
    layout = GDSLayout(source_path=Path(str(node.source) or "part.gds"), cell_name=node.cell_name or "",
                       bounds=(min(xs), min(ys), max(xs), max(ys)), layer_records=records)
    return layout, LayerStackSpec(name=node.label or "part stack", styles=styles, oxide=oxide,
                                  passivation_material=str(getattr(node, "passivation_material", "") or ""))


@router.get("/gds/{component_id}/file")
def gds_file(component_id: str) -> Response:
    """The part's GDS file, for the layout view (404 when the part has no file source or the file is gone)."""

    from optodraw.gds.layout import _source_path

    node = _find_gds_node(component_id)
    path = _source_path(node.source)
    if path is None or not Path(path).is_file():
        raise HTTPException(status_code=404, detail=f"no file for '{component_id}': {path or 'not a file source'}")
    from urllib.parse import quote

    return Response(content=Path(path).read_bytes(), media_type="application/octet-stream",
                    headers={"X-GDS-Cell": quote(node.layout_cell() or "")})  # the cell the part shows


@router.get("/gds/{component_id}/lyp")
def gds_lyp(component_id: str) -> Response:
    """The part's layer colours and names as a .lyp (its merged stack, as the 3D view draws it)."""

    return Response(content=_find_gds_node(component_id).layout_lyp(), media_type="application/xml")


@router.post("/gds/{component_id}/cross_section")
def gds_cross_section(component_id: str, body: CrossSectionBody) -> dict[str, Any]:
    """Cut a GDSModel along a line and run the process its stack implies (``cross_section``); return the
    look asked for (``schematic`` SVG, ``slab`` 3D page, ``sem`` PNG, ``top`` PNG of a square round the cut)
    and the layout marking the cut."""

    import base64
    import math
    import time

    from optodraw.gds.svg_section import topview_svg
    from optodraw.gds.xsection.model import CrossSection, cross_section

    node = _find_gds_node(component_id)
    polys_by_spec = getattr(node, "_polygons_by_spec", None)
    if not polys_by_spec:
        raise HTTPException(status_code=400, detail="GDS has no geometry to cut")
    looks = [look for look in _XS_LOOKS if look != "sem" or hasattr(CrossSection, "png")]
    look = (body.look or "schematic").lower()
    if look not in looks:
        detail = ("the SEM look is not in this version of optodraw" if look == "sem"
                  else f"look must be one of: {', '.join(looks)}")
        raise HTTPException(status_code=400, detail=detail)

    # bounds from the actual polygons (GDS coords); a FloorPlan layer sets the die boundary instead
    xs_all = [px for polygons in polys_by_spec.values() for poly in polygons for px, _ in poly]
    ys_all = [py for polygons in polys_by_spec.values() for poly in polygons for _, py in poly]
    xmin, xmax, ymin, ymax = min(xs_all), max(xs_all), min(ys_all), max(ys_all)
    fp = node._floorplan_bounds()
    if fp is not None:
        xmin, xmax, ymin, ymax = fp[0], fp[2], fp[1], fp[3]

    # The cut is a line A->B. A ruler ([x0,y0,x1,y1]) gives an arbitrary-angle cut
    # bounded to its own length; otherwise it's a full-height vertical cut at x.
    if body.frame not in ("local", "file"):
        raise HTTPException(status_code=400, detail=f"unknown frame {body.frame!r}: use 'local' or 'file'")
    if body.line and len(body.line) == 4:
        ax, ay, bx, by = (float(v) for v in body.line)
        if body.frame == "file":                    # the layout view's ruler: the GDS file's microns
            (ax, ay), (bx, by) = node.file_to_local(ax, ay), node.file_to_local(bx, by)
        cut_x = (ax + bx) / 2
    else:
        if body.x is not None:
            cut_x = body.x
        elif body.pct is not None:
            cut_x = xmin + max(0.0, min(1.0, body.pct)) * (xmax - xmin)
        else:
            cut_x = (xmin + xmax) / 2
        ax, ay, bx, by = cut_x, ymin, cut_x, ymax
    if math.hypot(bx - ax, by - ay) <= 0.0:
        raise HTTPException(status_code=400, detail="a cut needs two different points")

    top_polys = []                       # the top view: every visible drawn layer, openings left out
    # painted bottom up; a layer with no height assigned goes under the rest
    for record in sorted(node.layer_records(), key=lambda r: r["z"] if r["z"] is not None else -math.inf):
        if record["visible"] and record["material"] != "air":
            polygons = polys_by_spec.get((record["layer"], record["datatype"]), [])
            top_polys += [(poly, record["color"], min(float(record["opacity"]), 0.85)) for poly in polygons]
    label = (body.label or "A-A'").replace("\u2013", "-").replace("\u2014", "-")
    width_px = max(200, min(int(body.width_px or 2000), 4000))
    started = time.perf_counter()
    region, frame = None, None
    try:
        layout, stack = _gds_layout_and_stack(node)
        if look == "top":
            view, region = _top_view(component_id, layout, stack, (ax, ay, bx, by), body.stage)
            png = view.png(tilt=max(0.0, min(float(body.tilt), 85.0)), rotation=float(body.rotation), seed=body.seed,
                           mark=body.mark, width_px=width_px)
            content, kind, findings = "data:image/png;base64," + base64.b64encode(png).decode("ascii"), "png", view.check()
            frame = _turned_square(region, float(body.rotation))
        else:
            section = cross_section(layout, stack, ((ax, ay), (bx, by)), label=label)
            findings = section.check()
            if look == "schematic":
                content, kind = section.svg(z_scale=body.z_scale if body.z_scale else "auto"), "svg"
            elif look == "slab":
                from optodraw.gds.xsection.slab import VIEW

                content = section.slab(depth=body.depth, cutaway=body.cutaway).render_threejs(
                    show_labels=False, show_export_controls=False, camera_direction=VIEW)
                content = content.replace("</head>", "<style>#info{display:none}</style></head>", 1)  # small panel
                kind = "html"
            else:
                png = section.png(seed=body.seed, mark=body.mark, width_px=width_px)
                content, kind = "data:image/png;base64," + base64.b64encode(png).decode("ascii"), "png"
        top = topview_svg(top_polys, (ax, ay, bx, by), bounds=(xmin, ymin, xmax, ymax), title="Layout and cut",
                          frame=frame)
    except ValueError as error:  # a stage the process does not have, a region with no area
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # a stack the process cannot read, or a rendering failure
        raise HTTPException(status_code=400, detail=f"cross-section failed: {error}") from error

    return {
        "look": look,
        "looks": looks,
        "cross_section": content,
        "top_view": top,
        "format": kind,
        "bounds": [xmin, ymin, xmax, ymax],
        "cut": {"x": float(cut_x), "label": label, "length": math.hypot(bx - ax, by - ay),
                "angle": math.degrees(math.atan2(by - ay, bx - ax)) % 180.0},
        "line_file": [*node.local_to_file(ax, ay), *node.local_to_file(bx, by)],  # for the layout view's ruler
        "region": list(region) if region is not None else None,
        "findings": findings,
        "elapsed": round(time.perf_counter() - started, 2),
    }


def _top_view(component_id: str, layout: Any, stack: Any, cut: tuple[float, float, float, float], stage: str):
    """The top view of the square round the cut (its side the cut's length), and that square. The last few
    views stay, so a change of tilt, marks or noise reuses their cuts."""

    import json
    import math

    from optodraw.gds.xsection.top import top_view

    ax, ay, bx, by = cut
    half, mx, my = math.hypot(bx - ax, by - ay) / 2.0, (ax + bx) / 2.0, (ay + by) / 2.0
    region = (mx - half, my - half, mx + half, my + half)
    key = (component_id, tuple(round(v, 6) for v in region), str(stage),
           json.dumps({str(k): v for k, v in stack.styles.items()}, sort_keys=True, default=str),
           json.dumps(stack.oxide, sort_keys=True), stack.passivation_material,
           tuple((r.spec, len(r.polygons)) for r in layout.layer_records), tuple(layout.bounds))
    if key not in _TOP_VIEWS:
        while len(_TOP_VIEWS) >= 4:
            _TOP_VIEWS.pop(next(iter(_TOP_VIEWS)))
        _TOP_VIEWS[key] = top_view(layout, stack, region, stage=str(stage))
    return _TOP_VIEWS[key], region


def _turned_square(region: tuple[float, float, float, float], rotation: float) -> list[tuple[float, float]]:
    """The corners of ``region`` turned by ``rotation`` degrees about its centre: the part a top view shows."""

    import math

    x0, y0, x1, y1 = region
    cx, cy, h = (x0 + x1) / 2.0, (y0 + y1) / 2.0, (x1 - x0) / 2.0
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    return [(cx + c * u - s * v, cy + s * u + c * v) for u, v in ((-h, -h), (h, -h), (h, h), (-h, h))]


@router.post("/gds/{component_id}/technology")
async def attach_technology(component_id: str, request: Request, filename: str = "tech.lyp") -> dict[str, Any]:
    """Attach a KLayout ``.lyp`` / ``.lyt``, GDS3D techfile, or XSection ``.xs``.

    Parses per-layer styles (color/opacity/thickness/z/material) and merges them
    into the model's ``layer_stack`` so the 2D colors **and** the 3D layer stack
    (z + thickness) become physically correct. ``.lyp``/``.lyt`` carry colours;
    GDS3D ``.txt`` and ``.xs`` carry thickness. Reuses the library parsers."""

    from optodraw.gds.parsers import (
        load_layer_stack,
        parse_gds3d_techfile,
        parse_klayout_lyp,
        parse_xsection_thickness,
    )

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty technology upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"upload too large ({len(data)} bytes > {_MAX_UPLOAD_BYTES})")
    _find_gds_node(component_id)  # 404 if the target isn't a GDSModel
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "tech.lyp"
    path = _UPLOAD_DIR / f"{secrets.token_hex(8)}_{safe}"
    path.write_bytes(data)

    suffix = path.suffix.lower()
    stack_meta: dict[str, Any] = {}
    try:
        if suffix in (".yml", ".yaml", ".json"):
            # the SAME unified loader as bundled stacks: an attached private stack
            # (NDA foundry files) grows the identical process context — explicit
            # `oxide:` block, else derived from its own etch depths, else defaults
            stack = load_layer_stack(str(path))
            styles = stack.styles
            if styles:
                _session().update(component_id, {"process_context": True, **stack.oxide,
                                     "passivation_material": stack.passivation_material})
                stack_meta = {
                    "oxide": stack.oxide,
                    "oxide_source": stack.oxide_source,
                    "stack_warnings": stack.warnings,
                }
        elif suffix == ".lyp":
            styles = parse_klayout_lyp(str(path))
            # .lyp has NO z — the parser fills 0/0.22 defaults. Drop them so a .lyp
            # only sets appearance and never clobbers a real stack's z/thickness.
            for style in styles.values():
                for fake in ("zmin", "z_offset", "thickness"):
                    style.pop(fake, None)
        elif suffix in (".lyt", ".lyd25", ".zip"):
            # a .lyt names its .lyp and finds its heights in d25/*.lyd25, so it needs its folder: a .zip of it
            if suffix == ".zip":
                styles, stack_meta = _load_klayout(_technology_in(_unzip_technology(path)))
            else:
                styles, stack_meta = _load_klayout(path, shown_name=safe)
        elif suffix == ".xs":
            styles = parse_xsection_thickness(str(path))
        else:  # GDS3D process techfile (.txt / .tech)
            styles = parse_gds3d_techfile(str(path))
    except HTTPException:
        raise
    except Exception as error:  # malformed techfile
        raise HTTPException(status_code=400, detail=f"could not parse technology: {error}") from error
    if not styles:
        detail = "no layers found in this file"
        if suffix == ".xs":
            detail += " — .xs scripts vary; enter thickness per layer in the inspector if this didn't map"
        raise HTTPException(status_code=400, detail=detail)
    payload = _apply_gds_layer_styles(component_id, styles)
    payload.update(stack_meta)
    return payload


@router.post("/gds/{component_id}/technology_folder")
def attach_technology_folder(component_id: str, body: TechnologyFolderBody) -> dict[str, Any]:
    """Attach a KLayout technology folder picked in the browser. The editor sends its .lyt, .lyp and d25/*.lyd25
    files as text, each with its path in the folder; the rest of the folder (GDS libraries) stays on disk."""

    _find_gds_node(component_id)  # 404 if the target isn't a GDSModel
    if sum(len(item.text) for item in body.files) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"the folder's files are more than {_MAX_UPLOAD_BYTES} bytes")
    folder = _UPLOAD_DIR / f"{secrets.token_hex(8)}_tech"
    for item in body.files:
        _check_member(item.path, "in the folder")
        target = folder / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.text, encoding="utf-8")
    styles, stack_meta = _load_klayout(_technology_in(folder))
    if not styles:
        raise HTTPException(status_code=400, detail="no layers found in this technology")
    payload = _apply_gds_layer_styles(component_id, styles)
    payload.update(stack_meta)
    return payload


def _load_klayout(path: Path, *, shown_name: str | None = None) -> tuple[dict[Any, dict[str, Any]], dict[str, Any]]:
    """The styles and warnings of a KLayout .lyt or .lyd25; a .lyt without the .lyp it names says what to do."""

    from optodraw.gds.parsers import load_layer_stack

    try:
        stack = load_layer_stack(str(path))
    except FileNotFoundError as error:
        message = str(error).replace(path.name, shown_name or path.name)
        raise HTTPException(status_code=400, detail=f"{message}. Pick the technology folder (Attach technology "
                                                    "folder), or upload it as a .zip.") from error
    except Exception as error:  # malformed technology file
        raise HTTPException(status_code=400, detail=f"could not parse technology: {error}") from error
    return stack.styles, {"stack_warnings": stack.warnings}


def _check_member(name: str, where: str) -> None:
    """Refuse a path that leaves the technology folder: absolute, with a drive, or with a .. part."""

    parts = Path(name).parts
    if not parts or name.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
        raise HTTPException(status_code=400, detail=f"unsafe path {where}: {name}")


def _unzip_technology(archive: Path) -> Path:
    """Unpack an uploaded KLayout technology folder (.zip) beside the upload. A member that leaves the folder, or
    more unpacked bytes than an upload may have, is refused."""

    import zipfile

    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            for member in members:
                _check_member(member.filename, "in the .zip")
            if sum(member.file_size for member in members) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"the .zip unpacks to more than {_MAX_UPLOAD_BYTES} bytes")
            folder = archive.with_name(archive.stem + "_tech")
            bundle.extractall(folder)
    except zipfile.BadZipFile as error:
        raise HTTPException(status_code=400, detail=f"not a .zip file: {error}") from error
    return folder


def _technology_in(folder: Path) -> Path:
    """The one .lyt of a technology folder, else its one .lyd25 (heights only)."""

    for pattern in ("*.lyt", "*.lyd25"):
        found = sorted(p for p in folder.rglob(pattern) if not any(part.startswith("__MACOSX") for part in p.parts))
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise HTTPException(status_code=400, detail=f"the folder holds {len(found)} {pattern[1:]} files; "
                                                        "pick the folder of one technology")
    raise HTTPException(status_code=400, detail="the folder holds no .lyt or .lyd25 file")


@router.post("/gds/{component_id}/reset_layers")
def reset_gds_layers(component_id: str) -> dict[str, Any]:
    """Clear all per-layer overrides so the next stack/PDK applies from scratch."""

    _find_gds_node(component_id)  # 404 if not a GDSModel
    session = _session()
    session.update(component_id, {"layer_stack": {}})
    return {"layers": _find_gds_node(component_id).layer_records(), **_svg_payload(session)}


@router.get("/pdks")
def list_pdks() -> dict[str, Any]:
    """Return the installed gdsfactory PDKs that can be applied to a GDSModel."""

    return {"pdks": _discover_pdks()}


@router.post("/gds/{component_id}/pdk")
def apply_pdk(component_id: str, body: PdkBody) -> dict[str, Any]:
    """Apply a built-in gdsfactory PDK's layer styles + stack to a GDSModel."""

    from optodraw.gds.technology import get_gdsfactory_layer_styles

    pdk = _gdsfactory_pdk(body.name)
    try:
        styles = get_gdsfactory_layer_styles(pdk=pdk)
    except Exception as error:  # PDK without layer views
        raise HTTPException(status_code=400, detail=f"could not read PDK styles: {error}") from error
    return _apply_gds_layer_styles(component_id, styles)


_STACKS_DIR = Path(__file__).resolve().parent.parent / "gds" / "stacks"


@router.get("/stacks")
def list_stacks() -> dict[str, Any]:
    """List bundled foundry layer-stacks (z + thickness) applicable to a GDSModel."""

    from optodraw.gds.parsers import _load_yaml_file

    out: list[dict[str, str]] = []
    if _STACKS_DIR.is_dir():
        for path in sorted(_STACKS_DIR.glob("*.yaml")):
            if path.name.startswith("_"):
                continue  # _template.yaml etc. are downloadable, not applyable
            try:
                data = _load_yaml_file(path)
                label = data.get("name", path.stem) if isinstance(data, dict) else path.stem
            except Exception:
                label = path.stem
            out.append({"id": path.stem, "label": str(label)})
    return {"stacks": out}


@router.get("/stacks/template", response_class=PlainTextResponse)
def stack_template() -> Response:
    """Return the blank layer-stack template for users to fill in (NDA-safe)."""

    path = _STACKS_DIR / "_template.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="template not found")
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/yaml",
        headers={"Content-Disposition": 'attachment; filename="layer-stack-template.yaml"'},
    )


@router.post("/gds/{component_id}/stack")
def apply_stack(component_id: str, body: StackBody) -> dict[str, Any]:
    """Apply a bundled foundry layer-stack (z + thickness + material) to a GDSModel."""

    from optodraw.gds.parsers import load_layer_stack

    safe = re.sub(r"[^A-Za-z0-9_-]", "", body.name)
    path = _STACKS_DIR / f"{safe}.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"unknown stack '{body.name}'")
    stack = load_layer_stack(str(path))
    if not stack.styles:
        raise HTTPException(status_code=400, detail="stack defined no layers")
    # EVERY stack grows the full process context uniformly: the unified loader always
    # resolves the oxide envelope (explicit `oxide:` block, else derived from the
    # stack's own etch depths, else safe defaults) — a stack can never silently
    # produce a chip without its BOX/TOX. Etch layers (material: air) then carve
    # the real depths in 3D and in the cross-section.
    _session().update(component_id, {"process_context": True, **stack.oxide,
                                     "passivation_material": stack.passivation_material})
    payload = _apply_gds_layer_styles(component_id, stack.styles)
    payload["oxide"] = stack.oxide
    payload["oxide_source"] = stack.oxide_source
    payload["stack_warnings"] = stack.warnings
    return payload


@router.get("/export/glb")
def export_glb() -> Response:
    """Render the current scene to a deterministic, Blender-friendly GLB.

    Built server-side with trimesh (not the browser exporter), so GDS dies and
    setups always produce a clean binary glTF that Blender can import."""

    from optodraw.exporters import scene_to_glb

    try:
        data = scene_to_glb(_session().scene())
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"GLB export failed: {error}") from error
    title = str(_session().spec.get("title", "scene")).replace(" ", "_")
    return Response(
        content=data,
        media_type="model/gltf-binary",
        headers={"Content-Disposition": f'attachment; filename="{title}.glb"'},
    )


@router.get("/export/blender", response_class=PlainTextResponse)
def export_blender(glb: str = "scene.glb") -> str:
    """Return a headless Blender render script that imports the scene GLB.

    The script references the GLB by name, so save it next to the GLB downloaded
    from the 3D view and run: ``blender --background --python <script>``.
    """

    from optodraw.blender import export_blender_script

    out = Path(tempfile.gettempdir()) / "optodraw_scene.blender.py"
    export_blender_script(out, source_glb=glb, camera_preset="free_space_table")
    script = out.read_text(encoding="utf-8")
    # rewrite the resolved absolute GLB path back to the bare filename for portability
    abs_glb = Path(glb).expanduser().resolve(strict=False).as_posix()
    return script.replace(repr(abs_glb), repr(glb))


@router.get("/scene/download")
def download_scene() -> JSONResponse:
    spec = _session().whole_spec()
    title = str(spec.get("title", "scene")).replace(" ", "_")
    return JSONResponse(
        content=spec,
        headers={"Content-Disposition": f'attachment; filename="{title}.json"'},
    )


# -- simulate (analytical physics) ------------------------------------------ #

_POL_SKIP_TYPES = {"Beam", "Route", "FiberRoute", "WaveguideRoute", "MetalRoute", "Group"}


def _component_by_id(component_id: str) -> Any:
    """Return the live component instance for ``component_id`` (404 if absent)."""

    scene = _session().scene()
    for node in scene.walk():
        if getattr(node, "_id", "") == component_id:
            return node
    raise HTTPException(status_code=404, detail=f"no component '{component_id}'")


@router.get("/simulate/{component_id}/options")
def simulate_options(component_id: str) -> dict[str, Any]:
    """Which analytical simulations apply to the given component."""

    from optodraw.app import sim_plots

    component = _component_by_id(component_id)
    kinds = sim_plots.simulate_kinds(component)
    return {"kinds": kinds, "labels": {k: sim_plots.kind_label(k) for k in kinds}}


# NOTE: the literal /simulate/polarization route MUST precede the /simulate/{id}
# route below, or FastAPI matches "polarization" as a component_id.
@router.post("/simulate/polarization")
def simulate_polarization_chain(body: PolarizationBody) -> dict[str, Any]:
    """Trace polarization (Stokes) through the scene's ordered free-space optics."""

    from optodraw.app import sim_plots

    scene = _session().scene()
    chain = [n for n in scene.walk() if getattr(n, "component_type", "") and n.component_type not in _POL_SKIP_TYPES]
    if not chain:
        raise HTTPException(status_code=400, detail="scene has no optical components to trace")
    try:
        return sim_plots.simulate_polarization(chain, body.params)
    except ImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=f"polarization simulation failed: {error}") from error


@router.post("/simulate/{component_id}")
def simulate_component(component_id: str, body: SimulateBody) -> dict[str, Any]:
    """Run an analytical simulation for one component → plot SVG + data + controls."""

    from optodraw.app import sim_plots

    component = _component_by_id(component_id)
    try:
        return sim_plots.simulate(component, body.kind, body.params)
    except ImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"simulation failed: {error}") from error


# -- generators (parameterized scene builders) ------------------------------ #


@router.get("/generators")
def list_generators_endpoint() -> dict[str, Any]:
    """Available parameterized generators + their dialog field schemas."""

    from optodraw.app import generators

    return {"generators": generators.list_generators()}


@router.post("/generate")
def generate_scene(body: GenerateBody) -> dict[str, Any]:
    """Build a parameterized scene (mesh / array / chain) and load it (like a preset)."""

    from optodraw.app import generators

    try:
        scene = generators.build(body.name, body.params)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"unknown generator '{body.name}'") from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=f"generate failed: {error}") from error
    _session().load(scene.to_spec())
    return _svg_payload(_session())


# -- record video (the tour as an MP4) ----------------------------------------------------------------------------- #

_VIDEO_JOBS: dict[str, dict[str, Any]] = {}
_VIDEO_LOCK = threading.Lock()
_VIDEO_KEEP_S = 15 * 60          # a finished job and its file go after this time, if nobody downloads it


class VideoBody(BaseModel):
    width: int = Field(1920, ge=16, le=7680)
    height: int = Field(1080, ge=16, le=4320)
    fps: int = Field(30, ge=1, le=120)


def _drop_video_job(job_id: str) -> None:
    with _VIDEO_LOCK:
        job = _VIDEO_JOBS.pop(job_id, None)
    if job:
        shutil.rmtree(job["folder"], ignore_errors=True)


def _sweep_video_jobs() -> None:
    now = time.monotonic()
    with _VIDEO_LOCK:
        old = [i for i, j in _VIDEO_JOBS.items() if j["state"] != "running" and now - j["finished"] > _VIDEO_KEEP_S]
    for job_id in old:
        _drop_video_job(job_id)


_VIDEO_PREFIX = "optodraw-video-job-"


def sweep_video_folders() -> list[str]:
    """Remove the video job folders that a stopped server left in the system temp (the server start calls this). A
    folder goes when nothing in it changed for ``_VIDEO_KEEP_S``: a running job writes its video, and a finished one
    goes after that time anyway. Returns the folders removed."""

    now, gone = time.time(), []
    for folder in sorted(Path(tempfile.gettempdir()).glob(_VIDEO_PREFIX + "*")):
        if not folder.is_dir():
            continue
        try:
            newest = max([folder.stat().st_mtime] + [p.stat().st_mtime for p in folder.rglob("*")])
        except OSError:
            continue
        if now - newest > _VIDEO_KEEP_S:
            shutil.rmtree(folder, ignore_errors=True)
            gone.append(str(folder))
    return gone


def _run_video_job(job: dict[str, Any], spec: dict[str, Any], options: dict[str, Any]) -> None:
    """The worker thread: the scene's own tour and settings (``metadata.animation``) through ``render_tour_video``."""

    def progress(done: int, total: int) -> None:
        job["done"], job["total"] = done, total

    try:
        from optodraw.schema import scene_from_spec

        out = scene_from_spec(spec).render_tour_video(str(Path(job["folder"]) / "tour.mp4"), progress=progress, **options)
        job["path"] = str(out)
        job["done"] = job["total"] or job["done"]
        job["state"] = "done"
    except Exception as error:                                   # the editor shows the text; the job ends as failed
        job["error"] = str(error) or type(error).__name__
        job["state"] = "failed"
        shutil.rmtree(job["folder"], ignore_errors=True)          # a failed job keeps its error text, not its folder
    finally:
        job["finished"] = time.monotonic()
        timer = threading.Timer(_VIDEO_KEEP_S, _drop_video_job, args=(job["id"],))
        timer.daemon = True
        timer.start()


@router.post("/render/video")
def start_video(body: VideoBody) -> dict[str, Any]:
    """Start one render job of the tour video and return its id. One job runs at a time (409 while one does)."""

    _sweep_video_jobs()
    spec = copy.deepcopy(_session().spec)          # a copy: the editor goes on editing while the job runs
    with _VIDEO_LOCK:
        if any(j["state"] == "running" for j in _VIDEO_JOBS.values()):
            raise HTTPException(status_code=409, detail="A video is already being recorded. Wait until it is done.")
        job_id = secrets.token_hex(8)
        job = {"id": job_id, "state": "running", "done": 0, "total": 0, "error": None, "path": None,
               "folder": tempfile.mkdtemp(prefix=_VIDEO_PREFIX), "finished": 0.0}
        _VIDEO_JOBS[job_id] = job
    threading.Thread(target=_run_video_job, args=(job, spec, body.model_dump()), name=f"video-{job_id}",
                     daemon=True).start()
    return {"id": job_id}


def _video_job(job_id: str) -> dict[str, Any]:
    _sweep_video_jobs()
    with _VIDEO_LOCK:
        job = _VIDEO_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video job.")
    return job


def _video_state(job: dict[str, Any]) -> dict[str, Any]:
    out = {key: job[key] for key in ("id", "state", "done", "total", "error")}
    if job["state"] == "done":
        out["url"] = f"/api/render/video/{job['id']}/file"
        out["filename"] = Path(job["path"]).name
    return out


@router.get("/render/video")
def video_running() -> dict[str, Any]:
    """The running job, if any (the editor finds it again after a reload); else ``{"state": "idle"}``."""

    with _VIDEO_LOCK:
        running = next((j for j in _VIDEO_JOBS.values() if j["state"] == "running"), None)
    return _video_state(running) if running else {"id": None, "state": "idle"}


@router.get("/render/video/{job_id}")
def video_progress(job_id: str) -> dict[str, Any]:
    """The job's state (running, done or failed), the frames done of the total, the error text and, when done, the
    URL of the file."""

    return _video_state(_video_job(job_id))


@router.get("/render/video/{job_id}/file")
def video_file(job_id: str):
    """The finished video (``video/mp4``; ``video/webm`` where ffmpeg is missing). The job goes after the download."""

    from starlette.background import BackgroundTask

    job = _video_job(job_id)
    if job["state"] != "done":
        raise HTTPException(status_code=409, detail="The video is not done.")
    path = Path(job["path"])
    kind = "video/webm" if path.suffix == ".webm" else "video/mp4"
    return FileResponse(path, media_type=kind, filename=path.name, background=BackgroundTask(_drop_video_job, job_id))


# -- animation (GIF export) ------------------------------------------------- #


@router.post("/animation/flow")
def animation_flow(body: PolarizationBody) -> Response:
    """Scene-level light-flow animation (a pulse travels through every route/beam) → GIF."""

    from optodraw.app import animations

    try:
        data = animations.render_flow_gif(_session().scene(), body.params)
    except ImportError as error:
        raise HTTPException(status_code=400, detail="animated GIF export requires optodraw[gif] (pip install pillow)") from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return Response(content=data, media_type="image/gif", headers={"Content-Disposition": 'attachment; filename="light_flow.gif"'})


@router.get("/animation/{component_id}/recipes")
def animation_recipes(component_id: str) -> dict[str, Any]:
    """Animation recipes applicable to the given component."""

    from optodraw.app import animations

    component = _component_by_id(component_id)
    return {"recipes": animations.recipes_for(component)}


@router.post("/animation/{component_id}/gif")
def animation_gif(component_id: str, body: AnimateBody) -> Response:
    """Render an animation recipe for the component to an animated GIF download."""

    from optodraw.app import animations

    scene = _session().scene()
    component = next((n for n in scene.walk() if getattr(n, "_id", "") == component_id), None)
    if component is None:
        raise HTTPException(status_code=404, detail=f"no component '{component_id}'")
    try:
        data = animations.render_gif_bytes(scene, component, body.recipe, body.params)
    except ImportError as error:
        raise HTTPException(status_code=400, detail="animated GIF export requires optodraw[gif] (pip install pillow)") from error
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=f"animation failed: {error}") from error
    return Response(
        content=data,
        media_type="image/gif",
        headers={"Content-Disposition": f'attachment; filename="{body.recipe}.gif"'},
    )


@router.get("/animation/payloads")
def animation_payloads() -> dict[str, Any]:
    """Physics payloads for live 2D animation — same `t_ps` map the 3D engine uses.

    The `2D` `svg_anim.js` consumes this with no re-normalization, so `2D`
    is the reference and `3D` will be fixed to follow it.
    """

    from optodraw.core.timeline3d import anim_payload_map

    scene = _session().scene()
    raw = anim_payload_map(scene)
    # Map python id(node) -> component string id for the SVG `data-component-id`
    id_to_cid: dict[int, str] = {}
    for node in scene.walk():
        cid = getattr(node, "_id", "")
        if cid:
            id_to_cid[id(node)] = cid
    payloads: dict[str, Any] = {}
    for pid, payload in raw.items():
        cid = id_to_cid.get(pid)
        if cid:
            payloads[cid] = payload
    return payloads


# -- validation / design checks --------------------------------------------- #


@router.post("/validate")
def validate_scene() -> dict[str, Any]:
    """Run platform-appropriate design-rule checks over the current scene."""

    from optodraw.app import validation

    return {"checks": validation.run_checks(_session().scene())}


# -- publication figure export ---------------------------------------------- #


@router.get("/publication/templates")
def publication_templates() -> dict[str, Any]:
    """Figure templates + paper figure presets for the Export-figure dialog."""

    from optodraw.app import publication

    return publication.templates()


@router.post("/export/figure")
def export_figure(body: FigureBody, view: str = "2d") -> Response:
    """Build a publication figure bundle and return it as a zip download."""

    from optodraw.app import publication

    try:
        data = publication.build_zip(
            _session().scene(),
            template=body.template,
            formats=body.formats,
            preset=body.preset,
            caption=body.caption,
            include_polarization=body.include_polarization,
            view=view,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"figure export failed: {error}") from error
    title = str(_session().spec.get("title", "figure")).replace(" ", "_")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{title}_figures.zip"'},
    )

# The local parts dialog calls the same package import and serialization APIs.
from .parts_api import router as parts_router  # noqa: E402

router.include_router(parts_router)
