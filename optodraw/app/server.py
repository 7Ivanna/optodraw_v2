"""FastAPI application factory for the optodraw editor.

Loaded only inside the GUI process. The core library never imports this module,
so FastAPI stays an optional ``optodraw[gui]`` dependency.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from optodraw.app.api import _fragments, router, sweep_video_folders

STATIC_DIR = Path(__file__).parent / "static"

AUTH_COOKIE = "optodraw_token"


def _token_check(token: str) -> Callable[..., Any]:
    """Build the /api dependency that enforces a shared editor token.

    The token arrives as an ``Authorization: Bearer`` header (API clients), an
    ``X-Optodraw-Token`` header, or the cookie ``/auth/login`` sets for
    browsers. Comparison is constant-time.
    """

    async def _check(request: Request) -> None:
        supplied = request.headers.get("x-optodraw-token", "")
        if not supplied:
            authorization = request.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                supplied = authorization[7:].strip()
        if not supplied:
            supplied = request.cookies.get(AUTH_COOKIE, "")
        if not secrets.compare_digest(str(supplied), token):
            raise HTTPException(status_code=401, detail="missing or invalid editor token")

    return _check


def create_app(
    *,
    hosted: bool = False,
    auth_dependency: Callable[..., Any] | None = None,
    auth_token: str | None = None,
    allow_anonymous_hosted: bool = False,
) -> FastAPI:
    """Build the editor FastAPI app.

    The public package serves a single local editor. Hosted mode is reserved
    for a future deployment design and is rejected for now.

    Parameters
    ----------
    hosted:
        Reserved. ``True`` raises ``ValueError`` in the local-only editor.
    auth_dependency:
        Optional FastAPI dependency applied to every ``/api`` route. A hosted
        deployment passes its own auth check here to gate the API.
    auth_token:
        Shared secret for hosted mode. When set, every ``/api`` route requires
        it and browsers authenticate once via ``/auth/login?token=...``.
        Mutually exclusive with ``auth_dependency``.
    allow_anonymous_hosted:
        Explicitly allow hosted mode without an authentication dependency.
    """

    from optodraw import __version__

    if hosted:
        raise ValueError("hosted mode is not available while optodraw is local-only")

    if auth_token and auth_dependency is not None:
        raise ValueError("pass either auth_token or auth_dependency, not both")
    if hosted and not auth_token and auth_dependency is None and not allow_anonymous_hosted:
        raise ValueError("hosted mode requires auth_token or auth_dependency")

    app = FastAPI(title="optodraw editor", version=__version__)

    @app.middleware("http")
    async def _local_only(request: Request, call_next):
        from ipaddress import ip_address

        hostname = request.url.hostname
        if hostname not in {"localhost", "127.0.0.1", "::1", "testserver", "testclient"}:
            return PlainTextResponse("The optodraw editor is local-only.", status_code=403)
        client = request.client.host if request.client else None
        if client is not None:
            try:
                local_client = ip_address(client).is_loopback
            except ValueError:
                local_client = client in {"testclient", "testserver"}
            if not local_client:
                return PlainTextResponse("The optodraw editor is local-only.", status_code=403)
        return await call_next(request)

    if hosted:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    if auth_token:
        from fastapi import HTTPException
        from fastapi.responses import RedirectResponse

        auth_dependency = _token_check(auth_token)

        @app.get("/auth/login")
        def _login(request: Request, token: str = "") -> Any:
            """One-time browser login: sets the session cookie, then redirects."""

            if not secrets.compare_digest(token, auth_token):
                raise HTTPException(status_code=401, detail="missing or invalid editor token")
            response = RedirectResponse("/")
            response.set_cookie(
                AUTH_COOKIE,
                auth_token,
                httponly=True,
                samesite="lax",
                secure=request.url.scheme == "https",
            )
            return response

    dependencies = None
    if auth_dependency is not None:
        from fastapi import Depends

        dependencies = [Depends(auth_dependency)]

    # API routes are registered before the catch-all static mount so /api/* wins.
    app.include_router(router, dependencies=dependencies)
    sweep_video_folders()          # the video job folders a stopped server left behind
    _fragments.sweep()             # the inset drawings no payload named for two weeks, and the oldest past the cap

    if not hosted:
        # The editor's HTML/CSS/JS are served fresh every load. Browsers — and VS
        # Code's webview in particular — otherwise cache them aggressively, so edits
        # appear not to take effect ("I can't see the changes"). A hosted deploy
        # keeps normal caching (with hashed asset URLs) by leaving this off.
        @app.middleware("http")
        async def _no_cache_assets(request: Request, call_next):
            response = await call_next(request)
            if request.url.path == "/vendor/gds-lens.js":
                return response              # pinned and versioned (?v=): it may be cached for good
            response.headers["Cache-Control"] = "no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            for stale in ("etag", "ETag", "last-modified", "Last-Modified"):
                if stale in response.headers:
                    del response.headers[stale]
            return response

    if STATIC_DIR.is_dir() and not hosted:
        # Cache-busting: stamp every local asset URL with a token derived from the
        # files' mtimes, and version the ES-module imports inside each .js too. This
        # guarantees the browser fetches the current build even when it stubbornly
        # holds a stale copy (the recurring "I can't see the changes" problem).
        import re as _re

        from fastapi import HTTPException
        from fastapi.responses import HTMLResponse, Response

        def _asset_token() -> str:
            files = list(STATIC_DIR.rglob("*.js")) + list(STATIC_DIR.rglob("*.css"))
            return str(max((f.stat().st_mtime_ns for f in files), default=0))

        def _version_imports(src: str, token: str) -> str:
            return _re.sub(
                r"""((?:from|import)\s+["']\./[\w./-]+\.js)(["'])""",
                rf"\1?v={token}\2",
                src,
            )

        @app.get("/", response_class=HTMLResponse)
        def _index() -> HTMLResponse:
            token = _asset_token()
            html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace('href="css/app.css"', f'href="css/app.css?v={token}"')
            html = html.replace('src="js/app.js"', f'src="js/app.js?v={token}"')
            return HTMLResponse(html)

        @app.get("/js/{fname}")
        def _serve_js(fname: str) -> Response:
            import re as _re2

            if not _re2.fullmatch(r"[A-Za-z0-9_.-]+\.js", fname):
                raise HTTPException(status_code=404)
            path = STATIC_DIR / "js" / fname
            try:
                if not path.resolve().is_relative_to(STATIC_DIR.resolve()):
                    raise HTTPException(status_code=404)
            except ValueError:
                raise HTTPException(status_code=404)
            if not path.is_file():
                raise HTTPException(status_code=404)
            src = _version_imports(path.read_text(encoding="utf-8"), _asset_token())
            return Response(content=src, media_type="application/javascript")

    @app.get("/vendor/gds-lens.js")
    def _serve_gds_lens() -> Response:
        # the layout view's engine, vendored and pinned: the editor imports it with ?v=<version>
        from optodraw.renderers.gds_lens import gds_lens_source

        return Response(content=gds_lens_source(), media_type="text/javascript; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/vendor/gds-lens-host.js")
    def _serve_gds_lens_host() -> Response:
        from optodraw.renderers.gds_lens import gds_lens_host_source

        return Response(content=gds_lens_host_source(), media_type="text/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app
