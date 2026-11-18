"""SVG to PNG and to PDF on every system.

PNG goes through resvg, which installs as a wheel on Windows, macOS and Linux and needs no system library. PDF keeps
its text as text: cairosvg makes it where the cairo library loads, else headless Chrome or Edge prints it at the
drawing's own size. Edge comes with Windows, so a PDF works there with nothing to install."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


_SVG_TAG = re.compile(r"<(?:\w+:)?svg\b[^>]*>")          # ElementTree writes the root as <ns0:svg ...>
_SVG_NAME = re.compile(r"^<(?:\w+:)?svg")


def svg_to_png(svg: str, *, width: int | None = None, height: int | None = None, zoom: float | None = None,
               dpi: float | None = None, background: str | None = None) -> bytes:
    """The PNG bytes of ``svg``, ``width`` (and ``height``) pixels wide, ``zoom`` times its own size, or at its own
    size. ``dpi`` sets how many pixels a physical unit (mm, pt) of the drawing takes, as in cairosvg. ``background``
    fills what the drawing leaves clear; ``None`` keeps it transparent."""

    import resvg_py

    if width and height:                         # resvg fits both and keeps the aspect: set the exact size instead
        svg, width, height = _sized(svg, width, height), None, None
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height, zoom=zoom, dpi=float(dpi or 96.0),
                                       background=background))


def _sized(svg: str, width: int, height: int) -> str:
    """``svg`` drawn exactly ``width`` by ``height`` pixels, stretched as cairosvg stretches it."""

    head = _SVG_TAG.search(svg)
    if not head:
        raise ValueError("not an SVG: no <svg> element")
    tag = head.group(0)
    if "viewBox" not in tag:                     # keep the drawing's own units as the frame that stretches
        old = [re.search(rf'\s{name}="([\d.]+)(?:px)?"', tag) for name in ("width", "height")]
        if all(old):
            tag = _SVG_NAME.sub(rf'\g<0> viewBox="0 0 {old[0].group(1)} {old[1].group(1)}"', tag, count=1)
    tag = re.sub(r'\s(?:width|height|preserveAspectRatio)="[^"]*"', "", tag)
    tag = _SVG_NAME.sub(rf'\g<0> width="{width}" height="{height}" preserveAspectRatio="none"', tag, count=1)
    return svg[:head.start()] + tag + svg[head.end():]


def svg_to_pdf(svg: str, path: str | Path) -> Path:
    """Write ``svg`` as a one-page PDF at its own size, with the text kept as text, and return the path."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import cairosvg

        cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=str(path))
        return path
    except (ImportError, OSError):              # OSError: cairosvg is installed, but the cairo library is not
        pass
    from optodraw.renderers.capture3d import find_chrome

    browser = find_chrome(required=False)
    if browser is None:
        raise RuntimeError("A PDF needs Chrome or Edge, or the cairo library (macOS: brew install cairo; "
                           "Debian or Ubuntu: apt install libcairo2). SVG and PNG need neither.")
    _print_with_browser(browser, svg, path)
    return path


def _page_size(svg: str) -> tuple[str, str]:
    """The drawing's width and height as CSS lengths: a bare number is in px."""

    head = _SVG_TAG.search(svg)
    sizes = []
    for name in ("width", "height"):
        found = re.search(rf'\s{name}="([\d.]+)([a-z%]*)"', head.group(0)) if head else None
        if not found:
            raise ValueError(f"the SVG has no {name}, so its PDF page has no size")
        sizes.append(found.group(1) + (found.group(2) or "px"))
    return sizes[0], sizes[1]


def _print_with_browser(browser: str, svg: str, path: Path) -> None:
    width, height = _page_size(svg)
    path.unlink(missing_ok=True)                 # an older file there must not pass for this one
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "page.html"
        page.write_text(f'<!doctype html><meta charset="utf-8"><style>@page{{size:{width} {height};margin:0}}'
                        f"html,body{{margin:0}}svg{{display:block}}</style>{svg}", encoding="utf-8")
        run = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                              f"--user-data-dir={Path(folder) / 'profile'}", f"--print-to-pdf={path}", page.as_uri()],
                             capture_output=True, timeout=120)
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"{Path(browser).name} did not print the PDF: {run.stderr.decode(errors='replace')[-300:]}")
