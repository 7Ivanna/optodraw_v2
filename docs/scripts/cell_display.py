"""Run one notebook cell and describe what it shows.

The site runs this same file in the reader's browser (Pyodide) and in CPython (the saved outputs), so a cell
shows the same thing in both. The last line of a cell, if it is an expression, is what the cell shows: a scene
or a part shows its 2D drawing, an SVG string or PNG bytes show as a picture, an HTML page (a 3D view) shows in a frame,
anything else shows as text. Printed text shows under it.
"""

from __future__ import annotations

import ast
import contextlib
import io
from typing import Any


def run_cell(code: str, namespace: dict[str, Any]) -> dict[str, str]:
    tree = ast.parse(code, mode="exec")
    last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(tree, "<cell>", "exec"), namespace)
        value = eval(compile(ast.Expression(last.value), "<cell>", "eval"), namespace) if last is not None else None
    shown = show(value)
    shown["stdout"] = printed.getvalue()
    return shown


def show(value: Any) -> dict[str, str]:
    if value is None:
        return {"kind": "none", "data": ""}
    from optodraw.figure.page import Page

    if isinstance(value, Page):          # a page at its own size, letters and all; its render_svg is the editor canvas
        return {"kind": "svg", "data": value.svg()}
    if hasattr(value, "render_svg"):                       # a scene or a part: its 2D drawing
        return {"kind": "svg", "data": value.render_svg().as_svg()}
    if hasattr(value, "as_svg"):                           # a drawsvg drawing
        return {"kind": "svg", "data": value.as_svg()}
    if isinstance(value, bytes) and value.startswith(b"\x89PNG\r\n\x1a\n"):   # a PNG image: shows as a picture
        return {"kind": "png", "data": value}
    if isinstance(value, str):
        head = value.lstrip()[:400].lower()
        if head.startswith("<svg") or (head.startswith("<?xml") and "<svg" in head):
            return {"kind": "svg", "data": value}
        if head.startswith("<!doctype html") or head.startswith("<html"):
            return {"kind": "html", "data": value}
        return {"kind": "text", "data": value}
    return {"kind": "text", "data": repr(value)}


def views(scene: Any, shown: dict[str, str]) -> dict[str, str]:
    """The 1D, 2D and 3D views of the cell's ``scene``, when the cell shows a picture of it. A cell that
    renders its own 3D page keeps that page, with its camera."""

    if shown["kind"] not in ("svg", "html") or not (hasattr(scene, "render_threejs") and hasattr(scene, "render_svg")):
        return {}
    from optodraw.notebook_1d import render_notebook_1d

    three = shown["data"] if shown["kind"] == "html" else scene.render_threejs(show_labels=False)
    return {"1d": render_notebook_1d(scene), "2d": scene.render_svg().as_svg(), "3d": three}
