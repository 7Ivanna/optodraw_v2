"""Thin local-editor adapters over the portable part APIs."""
from pathlib import Path
import tempfile

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from optodraw.parts import PartLibrary, UserPart, import_svg_part, load_part, save_part
from optodraw.parts.serialization import read_definitions
from .parts import EditorParts, describe_part

router = APIRouter(prefix="/parts")


def store():
    from .api import _store
    return EditorParts(_store.workspaces.root)


def definition_for(name, digest=None):
    if digest is None:
        return store().get(name)
    from .api import _session
    definitions = read_definitions(_session().spec)
    definition = definitions.get(digest)
    if definition is None:
        candidate = store().get(name)
        if candidate.digest == digest:
            definition = candidate
    if definition is None or definition.name != name:
        raise ValueError(f"{name}: missing frozen definition {digest}")
    return definition


def preview_svg(definition):
    variant = definition.variant()
    asset = variant.symbol_2d or variant.symbol_1d
    view_box = " ".join(f"{v:g}" for v in asset.view_box)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">'
            + asset.inner(namespace=f"preview_{definition.digest}_2d") + '</svg>')


class PartBody(BaseModel):
    name: str = "user:my/Part"
    svg: str = Field(max_length=10*1024*1024)
    symbol_1d: str | None = Field(default=None, max_length=10*1024*1024)
    platform: str = "on_chip"
    ports: list[dict] | None = None
    parameters: dict = Field(default_factory=dict)
    description: str = ""


def draft(body):
    return import_svg_part(body.name, body.svg, platform=body.platform, ports=body.ports,
                           symbol_1d=body.symbol_1d, parameters=body.parameters,
                           description=body.description, library=PartLibrary()).definition


def _error(error):
    return HTTPException(status_code=400, detail=str(error))


@router.get("")
def list_parts():
    try:
        return {"parts": {name: describe_part(d) for name, d in store().definitions().items()}}
    except (ValueError, OSError) as error:
        raise _error(error) from error


@router.post("")
def create_part(body: PartBody):
    try:
        return describe_part(store().save(draft(body)))
    except (ValueError, TypeError, OSError) as error:
        raise _error(error) from error


@router.post("/inspect")
def inspect_part(body: PartBody, view: str = "2d"):
    try:
        definition = draft(body)
        variant = definition.variant()
        if view not in {"1d", "2d"}:
            raise ValueError("Part preview view must be 1d or 2d")
        svg = (UserPart(definition).schematic_symbol().svg if view == "1d" else
               preview_svg(definition))
        return {**describe_part(definition), "svg": svg,
                "ports": [p.to_dict() for p in variant.ports], "schematic_3d": True}
    except (ValueError, TypeError, OSError) as error:
        raise _error(error) from error


@router.post("/threejs", response_class=HTMLResponse)
def draft_threejs(body: PartBody):
    from optodraw import Scene
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer
    try:
        definition = draft(body)
        scene = Scene(platform=definition.platform)
        scene.add(UserPart(definition))
        return HTMLResponse(ThreeJsRenderer(scene, show_export_controls=False, show_chip_base=False).render())
    except (ValueError, TypeError, OSError) as error:
        raise _error(error) from error


@router.post("/import")
async def import_part(request: Request):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 100*1024*1024:
            raise HTTPException(status_code=413, detail="Part exceeds the 100 MiB limit")
        chunks.append(chunk)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "upload.odpart"
            path.write_bytes(b"".join(chunks))
            factory = load_part(path, library=PartLibrary())
            return describe_part(store().save(factory.definition))
    except (ValueError, TypeError, OSError) as error:
        raise _error(error) from error


@router.get("/export")
def export_part(name: str, definition_hash: str | None = None):
    try:
        definition = definition_for(name, definition_hash)
        with tempfile.TemporaryDirectory() as temporary:
            path = save_part(definition, Path(temporary) / "part.odpart")
            data = path.read_bytes()
        filename = definition.name.split("/", 1)[1] + ".odpart"
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except (KeyError, ValueError, OSError) as error:
        raise _error(error) from error
