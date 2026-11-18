"""GDS files for the layout view tests: the docs device (straight_pn with its via stack to M3 and PADOPEN), and a
file with two top cells."""

from __future__ import annotations

from pathlib import Path


def docs_device_gds(folder: Path) -> Path:
    import gdstk

    lib = gdstk.Library()
    cell = lib.new_cell("straight_pn")
    pads = [((0, 1), (20, 11)), ((0, -11), (20, -1))]
    contacts = [((x - 0.35, y - 0.35), (x + 0.35, y + 0.35)) for x in range(2, 20, 2) for y in (-9, -7, -5, -3, 3, 5, 7, 9)]
    shapes = {(1, 0): [((0, -0.25), (20, 0.25))], (3, 0): [((0, -3.5), (20, 3.5))] + pads,
              (20, 0): [((0, -8), (20, 0))], (21, 0): [((0, 0), (20, 8))], (24, 0): [((0, -8), (20, -1))],
              (25, 0): [((0, 1), (20, 8))], (40, 0): contacts, (41, 0): pads, (44, 0): contacts, (45, 0): pads,
              (43, 0): contacts, (49, 0): pads, (46, 0): [((1.5, 2.5), (18.5, 9.5)), ((1.5, -9.5), (18.5, -2.5))]}
    for (layer, datatype), rects in shapes.items():
        for a, b in rects:
            cell.add(gdstk.rectangle(a, b, layer=layer, datatype=datatype))
    path = Path(folder) / "straight_pn.gds"
    lib.write_gds(str(path))
    return path


def two_tops_gds(folder: Path) -> Path:
    import gdstk

    lib = gdstk.Library()
    lib.new_cell("A").add(gdstk.rectangle((0, 0), (10, 2), layer=1))
    lib.new_cell("B").add(gdstk.rectangle((0, 0), (4, 4), layer=2), gdstk.rectangle((5, 0), (9, 4), layer=2))
    path = Path(folder) / "two_tops.gds"
    lib.write_gds(str(path))
    return path


def capture_over_http(html: str, folder: Path, timeout: float = 90.0) -> str:
    """Serve ``html`` from ``folder`` on 127.0.0.1 and return what the page writes into ``#od-capture``: a page
    opened from file:// cannot start GDS Lens's worker in Chrome, a page from any web origin can."""

    import functools
    import http.server
    import threading
    import time

    from optodraw.renderers.capture3d import _Pipe, find_chrome

    folder = Path(folder)
    (folder / "page.html").write_text(html, encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    pipe = _Pipe(find_chrome(), folder / "profile", 900, 600)
    try:
        target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        pipe.call("Page.navigate", {"url": f"http://127.0.0.1:{server.server_address[1]}/page.html"}, session)
        deadline, value = time.monotonic() + timeout, ""
        while time.monotonic() < deadline and not value:
            time.sleep(0.25)
            value = pipe.call("Runtime.evaluate", {"expression": "document.getElementById('od-capture').value",
                                                   "returnByValue": True}, session).get("result", {}).get("value") or ""
        return value
    finally:
        pipe.close()
        server.shutdown()
        server.server_close()
