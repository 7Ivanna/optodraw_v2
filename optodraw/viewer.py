"""A small, fixed size, zoomable notebook viewer with 2D and 3D tabs.

Why this exists
---------------
Rendering a scene straight into a notebook cell gives you an SVG that grows to
whatever the drawing needs, so a 1800 unit wide chip floorplan fills the screen
and you scroll the page to see it. What you usually want in a notebook is the
opposite: a small pane of a FIXED size that you can zoom and pan inside, the
way the tidy3d and gdsfactory viewers behave.

This module provides that, plus a tab to flip between the 2D drawing and the
interactive 3D scene, which optodraw can produce but previously only as a
separate file you had to open by hand.

Usage
-----
    scene.preview()                       # in a notebook cell
    scene.preview(width=1000, height=560)
    scene.preview().save("viewer.html")   # standalone file

The 3D pane needs a network connection: optodraw's three.js page pulls the
library from a CDN rather than inlining it, so an offline notebook shows the 2D
tab normally and an empty 3D pane. Pass ``show_3d=False`` for a notebook that
must work offline, or when several scenes make the output file large: the 3D
geometry, not the library, is what takes the space.

Implementation note
-------------------
Everything lives inside one iframe. JupyterLab does not execute <script> tags
that arrive through _repr_html_, so a viewer built as plain inline HTML would
show the panes but neither the tabs nor the zoom would work. Inside an iframe
the document is its own browsing context and its scripts run normally, which
also means several viewers in one notebook cannot collide.
"""

from __future__ import annotations

import html
import json
from typing import Any

_VIEWER_CSS = """
* { box-sizing: border-box; }
body { margin: 0; font: 13px/1.4 -apple-system, BlinkMacSystemFont, 'Segoe UI',
       Helvetica, Arial, sans-serif; color: #1a1a1a; background: #fff; }
.bar { display: flex; align-items: center; gap: .35rem; padding: .35rem .5rem;
       border-bottom: 1px solid #e2e6ea; background: #f7f8fa; }
.bar button { font: inherit; padding: .2rem .7rem; border: 1px solid #cbd2d9;
              background: #fff; border-radius: 4px; cursor: pointer; color: #1a1a1a; }
.bar button.on { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
.bar .sp { flex: 1; }
.bar .hint { color: #7a828a; font-size: 11.5px; }
.bar .zoom { color: #7a828a; font-size: 11.5px; min-width: 3.2rem; text-align: right; }
.pane { position: absolute; inset: 34px 0 0 0; overflow: hidden; }
.pane[hidden] { display: none; }
#stage { position: absolute; transform-origin: 0 0; }
#stage svg { display: block; }
#d2 { cursor: grab; background: #fff; }
#d2.drag { cursor: grabbing; }
#d3 { border: 0; }
#d3 iframe { width: 100%; height: 100%; border: 0; display: block; }
"""

_VIEWER_JS = """
const stage = document.getElementById('stage');
const pane = document.getElementById('d2');
let z = 1, ox = 0, oy = 0, fit = 1;

function apply() {
  stage.style.transform = `translate(${ox}px, ${oy}px) scale(${z})`;
  document.getElementById('zoom').textContent = Math.round(z / fit * 100) + '%';
}
function reset() {
  const svg = stage.querySelector('svg');
  if (!svg) return;
  const w = svg.getAttribute('width'), h = svg.getAttribute('height');
  const bw = parseFloat(w) || svg.getBoundingClientRect().width || 1;
  const bh = parseFloat(h) || svg.getBoundingClientRect().height || 1;
  const pad = 16;
  fit = Math.min((pane.clientWidth - pad) / bw, (pane.clientHeight - pad) / bh);
  z = fit;
  ox = (pane.clientWidth - bw * z) / 2;
  oy = (pane.clientHeight - bh * z) / 2;
  apply();
}
pane.addEventListener('wheel', (e) => {
  e.preventDefault();
  const r = pane.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const k = Math.exp(-e.deltaY * 0.0015);
  const nz = Math.min(fit * 60, Math.max(fit * 0.2, z * k));
  ox = mx - (mx - ox) * (nz / z);
  oy = my - (my - oy) * (nz / z);
  z = nz; apply();
}, { passive: false });
let dragging = false, px = 0, py = 0;
pane.addEventListener('pointerdown', (e) => {
  dragging = true; px = e.clientX; py = e.clientY;
  pane.classList.add('drag'); pane.setPointerCapture(e.pointerId);
});
pane.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  ox += e.clientX - px; oy += e.clientY - py;
  px = e.clientX; py = e.clientY; apply();
});
pane.addEventListener('pointerup', (e) => {
  dragging = false; pane.classList.remove('drag');
});
pane.addEventListener('dblclick', reset);

// the 3D document is only built when the tab is first opened, so a notebook
// with several viewers does not start a WebGL context for every one of them
let built = false;
const threeButton = document.getElementById('b3');
function show(which) {
  document.getElementById('d2').hidden = which !== '2d';
  document.getElementById('d3').hidden = which !== '3d';
  document.getElementById('b2').classList.toggle('on', which === '2d');
  if (threeButton) threeButton.classList.toggle('on', which === '3d');
  document.getElementById('hint').textContent = which === '2d'
    ? 'scroll to zoom, drag to pan, double click to fit'
    : 'drag to orbit, scroll to zoom';
  document.getElementById('zoom').style.visibility = which === '2d' ? 'visible' : 'hidden';
  if (which === '3d' && !built) {
    built = true;
    const f = document.createElement('iframe');
    f.setAttribute('allow', 'fullscreen');
    document.getElementById('d3').appendChild(f);
    f.src = URL.createObjectURL(new Blob([HTML3D], { type: 'text/html' }));
  }
}
document.getElementById('b2').onclick = () => show('2d');
if (threeButton) threeButton.onclick = () => show('3d');
window.addEventListener('resize', () => { if (!document.getElementById('d2').hidden) reset(); });
reset();
"""


def _with_one_d_tab(document_method):
    """Add an offline 1D pane to the existing notebook document."""
    def wrapped(self):
        from .notebook_1d import render_notebook_1d

        document = document_method(self)
        button = '<button id="b1" type="button">1D</button>'
        pane = (
            '<div id="d1" hidden style="position:absolute;inset:34px 0 0 0;'
            'overflow:auto;background:#fff">'
            + render_notebook_1d(self.scene)
            + '</div>'
        )
        button_at = document.find('<button id="b2"')
        pane_at = document.find('<div class="pane" id="d2"')
        if button_at < 0 or pane_at < 0:
            raise ValueError("Notebook viewer tab anchors are missing")
        document = document[:button_at] + button + document[button_at:]
        pane_at = document.find('<div class="pane" id="d2"')
        document = document[:pane_at] + pane + document[pane_at:]
        script = '''<script>
(() => {
  const b1 = document.getElementById('b1');
  const b2 = document.getElementById('b2');
  const b3 = document.getElementById('b3');
  const d1 = document.getElementById('d1');
  const d2 = document.getElementById('d2');
  const d3 = document.getElementById('d3');
  const svg1 = d1.querySelector('svg');
  const baseWidth = (svg1 && svg1.viewBox && svg1.viewBox.baseVal.width)
    || parseFloat(svg1 && svg1.getAttribute('width')) || 600;
  const baseHeight = (svg1 && svg1.viewBox && svg1.viewBox.baseVal.height)
    || parseFloat(svg1 && svg1.getAttribute('height')) || 240;
  let scale1 = 1;
  let fit1 = 1;
  let fitted1 = false;
  let drag1 = null;
  function fitOneD() {
    if (!svg1) return;
    fit1 = Math.min(1, Math.max(1, d1.clientWidth - 16) / baseWidth,
      Math.max(1, d1.clientHeight - 16) / baseHeight);
    scale1 = fit1;
    svg1.style.width = `${baseWidth * scale1}px`;
    svg1.style.height = `${baseHeight * scale1}px`;
    d1.scrollLeft = 0;
    d1.scrollTop = 0;
  }
  d1.addEventListener('wheel', event => {
    if (!svg1) return;
    event.preventDefault();
    const box = d1.getBoundingClientRect();
    const localX = event.clientX - box.left;
    const localY = event.clientY - box.top;
    const contentX = d1.scrollLeft + localX;
    const contentY = d1.scrollTop + localY;
    const next = Math.max(fit1 * 0.2, Math.min(fit1 * 60, scale1 * (event.deltaY < 0 ? 1.12 : 1 / 1.12)));
    const ratio = next / scale1;
    scale1 = next;
    svg1.style.width = `${baseWidth * scale1}px`;
    svg1.style.height = `${baseHeight * scale1}px`;
    d1.scrollLeft = contentX * ratio - localX;
    d1.scrollTop = contentY * ratio - localY;
  }, {passive: false});
  d1.addEventListener('pointerdown', event => {
    drag1 = {x: event.clientX, y: event.clientY, left: d1.scrollLeft, top: d1.scrollTop};
    d1.setPointerCapture(event.pointerId);
  });
  d1.addEventListener('pointermove', event => {
    if (!drag1) return;
    d1.scrollLeft = drag1.left - (event.clientX - drag1.x);
    d1.scrollTop = drag1.top - (event.clientY - drag1.y);
  });
  d1.addEventListener('pointerup', () => { drag1 = null; });
  d1.addEventListener('pointercancel', () => { drag1 = null; });
  d1.addEventListener('dblclick', () => {
    fitOneD();
  });
  b1.addEventListener('click', () => {
    d1.hidden = false;
    if (!fitted1) { fitOneD(); fitted1 = true; }
    d2.hidden = true;
    if (d3) d3.hidden = true;
    b1.classList.add('on');
    b2.classList.remove('on');
    if (b3) b3.classList.remove('on');
    document.getElementById('hint').textContent = 'drag to pan, scroll to zoom';
    document.getElementById('zoom').style.visibility = 'hidden';
  });
  for (const button of [b2, b3].filter(Boolean)) {
    button.addEventListener('click', () => {
      d1.hidden = true;
      b1.classList.remove('on');
    });
  }
  window.addEventListener('resize', () => { if (!d1.hidden) fitOneD(); });
})();
</script>'''
        return document.replace('</body>', script + '</body>', 1)

    return wrapped


class ScenePreview:
    """A fixed size, zoomable 2D and 3D view of a scene, for notebooks."""

    def __init__(
        self,
        scene: Any,
        width: int = 900,
        height: int = 520,
        *,
        title: str | None = None,
        show_3d: bool = True,
        svg_kwargs: dict | None = None,
        threejs_kwargs: dict | None = None,
    ) -> None:
        self.scene = scene
        self.width = int(width)
        self.height = int(height)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Preview width and height must be positive")
        self.title = title if title is not None else getattr(scene, "title", "") or ""
        self.show_3d = bool(show_3d)
        self._svg_kwargs = svg_kwargs or {}
        self._threejs_kwargs = threejs_kwargs or {}

    # -- pieces ------------------------------------------------------------
    def _svg_text(self) -> str:
        from optodraw.figure.page import Page

        if isinstance(self.scene, Page):     # a page at its own size with its letters, as it prints
            return self.scene.svg()
        drawing = self.scene.render_svg(**self._svg_kwargs)
        for attr in ("as_svg", "to_svg", "asSvg"):
            fn = getattr(drawing, attr, None)
            if callable(fn):
                return fn()
        return str(drawing)

    def _html_3d(self) -> str:
        if not self.show_3d:
            return ""
        try:
            return self.scene.render_threejs(**self._threejs_kwargs)
        except Exception as exc:                      # a missing 3D geometry must
            return (                                  # not take the 2D view down
                "<!doctype html><meta charset='utf-8'>"
                "<body style=\"font:13px sans-serif;padding:1rem;color:#b00\">"
                f"3D view unavailable: {html.escape(str(exc))}</body>"
            )

    def save_1d_svg(self, path):
        """Write the compact 1D schematic as a standalone SVG file."""
        from pathlib import Path

        from .notebook_1d import render_notebook_1d

        target = Path(path)
        target.write_text(render_notebook_1d(self.scene), encoding="utf-8")
        return target

    @_with_one_d_tab
    def document(self) -> str:
        """The complete viewer as a standalone HTML document."""
        svg = self._svg_text()
        # strip any XML prolog so the SVG can be inlined in an HTML body
        if svg.lstrip().startswith("<?xml"):
            svg = svg.split("?>", 1)[1]
        tabs = (
            '<button id="b2" class="on">2D</button>'
            + ('<button id="b3">3D</button>' if self.show_3d else '')
        )
        title = html.escape(self.title)
        # json quoting handles quotes and backslashes, but NOT the sequence
        # "</script>", which the 3D document contains and which would close this
        # script block early and silently break every line after it.
        html3d = json.dumps(self._html_3d()).replace("</", "<\\/")
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>{_VIEWER_CSS}</style></head>
<body>
  <div class="bar">{tabs}<span class="sp"></span>
    <span class="hint" id="hint">scroll to zoom, drag to pan, double click to fit</span>
    <span class="zoom" id="zoom"></span>
  </div>
  <div class="pane" id="d2"><div id="stage">{svg}</div></div>
  <div class="pane" id="d3" hidden></div>
  <script>
  const HTML3D = {html3d};
  {_VIEWER_JS}
  </script>
  <title>{title}</title>
</body></html>"""

    # -- outputs -----------------------------------------------------------
    def _repr_html_(self) -> str:
        doc = self.document()
        srcdoc = doc.replace("&", "&amp;").replace('"', "&quot;")
        return (
            f'<iframe srcdoc="{srcdoc}" width="{self.width}" height="{self.height}" '
            f'style="border:1px solid #e2e6ea;border-radius:6px;background:#fff" '
            f'loading="lazy"></iframe>'
        )

    def save(self, filename: str) -> str:
        """Write the viewer as a standalone HTML file."""
        with open(filename, "w", encoding="utf-8") as fh:
            fh.write(self.document())
        return filename

    def __repr__(self) -> str:
        return (f"ScenePreview({self.title!r}, {self.width}x{self.height}, "
                f"3d={'on' if self.show_3d else 'off'})")
