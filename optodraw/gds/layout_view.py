"""The layout view of an imported GDS: GDS Lens (vendored, see optodraw/renderers/gds_lens.py) in one HTML file
with the layout's bytes.

The page needs no network and no web server. Opened from disk (file://), Chrome starts no worker from a blob
URL, which is how GDS Lens starts its parse worker; the page's host (gds_lens_host.js) then starts it from a
data: URL. Notebooks and the editor serve the page from their own origin.

The page writes a JSON summary into a hidden ``#od-capture`` input once the layout is drawn, for headless
checks: ``{"ok": true, "layers": n, "polygons": n, "top": cell or null, "colors": {"L/D": fill}}``, or
``{"ok": false, "error": message}``.
"""

from __future__ import annotations

import base64
import html as _html
import json
import os
from pathlib import Path
from typing import Any

from optodraw.gds.lyp import stack_to_lyp
from optodraw.renderers.gds_lens import gds_lens_host_source, gds_lens_source

_START = """
;(async () => {
  const data = JSON.parse(document.getElementById("od-layout-data").textContent);
  const viewer = document.getElementById("od-layout");
  const capture = (value) => { document.getElementById("od-capture").value = JSON.stringify(value); };
  try {
    const bytes = Uint8Array.from(atob(data.gds), (c) => c.charCodeAt(0));
    await viewer.load(bytes, { topCell: data.cell || null });
    if (data.lyp) await viewer.setLyp("stack.lyp", data.lyp);
    const layers = await viewer.getLayers();
    const colors = {};
    for (const row of layers) colors[`${row.layer}/${row.datatype}`] = row.fillColor;
    capture({ ok: true, layers: layers.length, polygons: layers.reduce((n, row) => n + (row.polygonCount || 0), 0),
              top: (await viewer.getTopCells()).current, colors });
  } catch (err) {
    capture({ ok: false, error: String((err && err.message) || err) });
  }
})();
"""


def _lyp_text(stack: Any, lyp: str | None) -> str | None:
    if lyp is not None:
        return lyp
    if stack is None:
        return None
    styles = getattr(stack, "styles", None)
    if styles is None:
        from optodraw.gds import load_layer_stack

        styles = load_layer_stack(stack).styles
    return stack_to_lyp(styles)


def layout_html(source: str | os.PathLike | bytes, *, cell: str | None = None, stack: Any = None,
                lyp: str | None = None, title: str = "Layout", filename: str | os.PathLike | None = None) -> str:
    """A one-file page that shows the GDS or OASIS layout ``source`` (a path or its bytes) in GDS Lens.

    ``cell`` draws that cell as the top. ``stack`` (a bundled name, a YAML path or a ``LayerStackSpec``) gives
    the layer colours and names through a written .lyp; ``lyp`` (the .lyp text) wins over ``stack``. The page
    is returned, and written to ``filename`` when one is given."""

    data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    payload = json.dumps({"gds": base64.b64encode(bytes(data)).decode("ascii"), "cell": cell,
                          "lyp": _lyp_text(stack, lyp)}).replace("</", "<\\/")
    script = gds_lens_source().replace("</script", "<\\/script") + _START
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_html.escape(title)}</title>"
        "<style>html, body { margin: 0; height: 100%; background: #0f1720; }"
        " gds-lens { display: block; width: 100vw; height: 100vh; }</style></head><body>\n"
        '<gds-lens id="od-layout"></gds-lens>\n<input type="hidden" id="od-capture" value="">\n'
        f'<script type="application/json" id="od-layout-data">{payload}</script>\n'
        f"<script>\n{gds_lens_host_source()}</script>\n"
        f'<script type="module">\n{script}</script>\n</body></html>\n'
    )
    if filename is not None:
        Path(filename).write_text(page, encoding="utf-8")
    return page


class LayoutPreview:
    """A layout page in a notebook cell: an iframe whose document is the page (a notebook runs no script in its
    output HTML, an iframe does), served from the notebook's own origin."""

    def __init__(self, html: str, width: int = 900, height: int = 600):
        self.html, self.width, self.height = html, int(width), int(height)

    def _repr_html_(self) -> str:
        srcdoc = self.html.replace("&", "&amp;").replace('"', "&quot;")
        return (f'<iframe srcdoc="{srcdoc}" width="{self.width}" height="{self.height}" '
                f'style="border:1px solid #e2e6ea;border-radius:6px;background:#fff" loading="lazy"></iframe>')

    def save(self, filename: str | os.PathLike) -> Path:
        """Write the page; it opens from disk (see the module docstring)."""

        path = Path(filename)
        path.write_text(self.html, encoding="utf-8")
        return path
