"""Optodraw editor app (optional ``optodraw[gui]`` extra).

A web front-end + FastAPI back-end so non-coders can place, move, and edit
components visually. The same app is packaged three ways from one codebase:
pip/conda (``optodraw-gui``), a native desktop window (PyWebView), and a hosted
website. FastAPI is imported lazily so ``import optodraw.app`` stays cheap and
the core library never depends on it.
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_app", "main"]


def __getattr__(name: str) -> Any:  # PEP 562 lazy attribute access
    if name == "create_app":
        from optodraw.app.server import create_app

        return create_app
    if name == "main":
        from optodraw.app.launcher import main

        return main
    raise AttributeError(f"module 'optodraw.app' has no attribute {name!r}")
