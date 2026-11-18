"""Command-line launcher for the optodraw editor (``optodraw-gui``).

Starts a local server and opens the system browser. ``--desktop`` opens a
native window via PyWebView instead. Public hosting is not available yet.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from typing import Sequence

DEFAULT_PORT = 8000
PORT_SEARCH_SPAN = 20

INSTALL_HINT = (
    "The optodraw editor needs the GUI extra. Install it with "
    "`pip install optodraw[gui]` (add `optodraw[desktop]` for the native window)."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="optodraw-gui", description="Launch the optodraw editor.")
    parser.add_argument("--host", default="127.0.0.1", help="Server bind host (default 127.0.0.1).")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Server port. Default: {DEFAULT_PORT}, or the next free port if it is taken.",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    parser.add_argument("--desktop", action="store_true", help="Open a native PyWebView window.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Dev mode: auto-restart the server when Python files change.",
    )
    return parser


def _port_is_free(host: str, port: int) -> bool:
    """True if a server can bind ``host:port`` right now.

    The probe socket sets SO_REUSEADDR because uvicorn does, so a port left in
    TIME_WAIT by a previous run reads as free — which it is, for our purposes.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _resolve_port(host: str, requested: int | None) -> int:
    """Return the port to bind, searching upward only when none was asked for.

    Port 8000 is the busiest port on a developer's machine. Refusing to start
    because something else holds it is the wrong first impression for an app
    somebody just downloaded, so the default walks up to the next free one. An
    explicit ``--port`` is a decision, not a suggestion: it is returned as-is so
    the bind failure is reported instead of silently landing elsewhere.
    """

    if requested is not None:
        return requested
    for candidate in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SEARCH_SPAN):
        if _port_is_free(host, candidate):
            return candidate
    return DEFAULT_PORT  # nothing free nearby: let uvicorn report the real error


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.host not in {"127.0.0.1", "localhost"}:
        print("The editor can only bind to localhost in local-only mode.", file=sys.stderr)
        return 2
    if args.port is not None and not 1 <= args.port <= 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)
        return 2

    try:
        import uvicorn

        from optodraw.app.server import create_app
    except ImportError as error:
        print(f"{INSTALL_HINT}\n  ({error})", file=sys.stderr)
        return 1

    port = _resolve_port(args.host, args.port)
    if args.port is None and port != DEFAULT_PORT:
        print(f"Port {DEFAULT_PORT} is in use; starting on {port} instead.")
    args.port = port
    url = f"http://{args.host}:{port}/"

    if args.reload:
        # Dev mode: uvicorn's reloader needs an import string + factory, not an
        # app instance, so it can re-import on change. Edits to static frontend
        # files (HTML/CSS/JS) need only a browser refresh, not a restart.
        if not args.no_browser:
            threading.Timer(1.0, webbrowser.open, args=(url,)).start()
        print(f"optodraw editor (dev, auto-reload) at {url}  (Ctrl+C to stop)")
        uvicorn.run(
            "optodraw.app.server:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
            log_level="info",
        )
        return 0

    app = create_app()

    if args.desktop:
        return _run_desktop(app, args, url)

    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"optodraw editor running at {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _run_desktop(app, args, url: str) -> int:
    """Run uvicorn in a background thread and show a native PyWebView window."""

    try:
        import webview
    except ImportError as error:
        print(
            "The native window needs PyWebView. Install it with "
            f"`pip install optodraw[desktop]`.\n  ({error})",
            file=sys.stderr,
        )
        return 1

    import uvicorn

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started or not thread.is_alive():
            break
        time.sleep(0.1)
    if not server.started:
        server.should_exit = True
        print("Could not start the local editor server.", file=sys.stderr)
        return 1

    webview.create_window("optodraw editor", url, width=1280, height=820)
    webview.start()
    server.should_exit = True
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
