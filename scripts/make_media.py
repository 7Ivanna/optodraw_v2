"""Make the README images from the site's example cells: each image is a published figure, redrawn.

The cells live in ``docs/examples/<page>/`` and run in order, as on the site; the quick-start image comes
from the README's own code block. The images go to ``docs/public/media/``. A drawing becomes a PNG
through headless Chrome; a 3D image is a studio render (``render_3d_image``), about a minute each. The light
GIF is the 3D light player's video (``render_video``, needs ffmpeg). The editor images are the editor itself
in headless Chrome, on a throwaway workspace, so none of your saved scenes is opened or changed.

    python scripts/make_media.py                  # every image
    python scripts/make_media.py --no-3d          # no studio render and no light video
    python scripts/make_media.py rings-light      # only the images named
    python scripts/make_media.py --list           # what it would write
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CELLS = ROOT / "docs" / "examples"
OUT = ROOT / "docs" / "public" / "media"
WIDTH = 1400                         # PNG width in pixels
EDITOR = (1200, 800)                 # the editor's window, in pixels
TILE = (1200, 800)                   # every gallery image: the same size, so the README's columns are equal
GIF = (720, 480, 12, 3.0)            # the light GIF: width, height, frames per second, seconds

# image name -> (page/cell, view); the page's cells run in order up to that cell, and its scene is drawn
# (the Layout view takes a cell of the gdsfactory generic PDK instead)
GALLERY = {
    "ligo-2d": ("get-started/01-ligo", "2d"),
    "homodyne-1d": ("electronics/01-homodyne", "1d"),
    "rings-3d": ("3d/01-rings", "3d"),
    "rings-light": ("3d/01-rings", "light"),
    "xsection": ("cross-sections/01-schematic", "xs"),
    "xsection-sem": ("cross-sections/02-sem", "sem"),
    "editor-2d": ("chips/02-soh-mzm", "editor"),
    "editor-layout": ("gdsfactory/ring_single_heater", "layout"),
    "expander-rays": ("ray-tracing/01-expander", "2d"),
}
SLOW = {"3d", "light"}


def page_namespace(cell: str) -> dict:
    """Run the cells of a site page in one namespace, up to and including ``cell`` (page/name), and return
    the namespace. A page name alone runs every cell of the page."""

    namespace: dict = {"__name__": "__main__"}
    here = os.getcwd()
    os.chdir(ROOT)
    try:
        with contextlib.redirect_stdout(io.StringIO()):          # a cell may print a number: not wanted here
            page, _, last = cell.partition("/")
            for path in sorted((CELLS / page).glob("*.py")):
                exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
                if path.stem == last:
                    break
    finally:
        os.chdir(here)
    return namespace


def page_scene(cell: str):
    """The scene of a site page, after its cells up to ``cell``."""

    return page_namespace(cell)["scene"]


def readme_scene():
    """Run the README's quick start and return its scene: the image always shows that code."""

    block = re.search(r"## Quick start\s+```python\n(.*?)```", (ROOT / "README.md").read_text(), re.S).group(1)
    namespace: dict = {"__name__": "__main__"}
    with tempfile.TemporaryDirectory() as folder:
        here = os.getcwd()
        os.chdir(folder)
        try:
            exec(compile(block, "README.md", "exec"), namespace)
        finally:
            os.chdir(here)
    return namespace["scene"]


def svg_to_png(svg: str, target: Path) -> None:
    """Draw the SVG in headless Chrome at WIDTH pixels, on white, cropped to the drawing."""

    from optodraw.renderers.capture3d import find_chrome

    width, height = (float(v) for v in re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', svg).groups())
    tall = round(WIDTH * height / width)
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "page.html"
        (Path(folder) / "figure.svg").write_text(svg, encoding="utf-8")
        page.write_text(f'<body style="margin:0;background:#fff"><img src="figure.svg" style="width:{WIDTH}px;'
                        f'height:{tall}px;display:block">', encoding="utf-8")
        target.unlink(missing_ok=True)
        chrome = subprocess.Popen([find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                   "--allow-file-access-from-files", f"--user-data-dir={folder}/profile",
                                   f"--window-size={WIDTH},{tall}", f"--screenshot={target}", page.as_uri()],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(240):                 # Chrome can stay open after it writes the file: wait, then stop it
            if target.exists() and target.stat().st_size > 0:
                time.sleep(0.5)
                break
            time.sleep(0.5)
        chrome.kill()
        chrome.wait()
        if not target.exists():
            raise RuntimeError(f"Chrome wrote no image for {target.name}")


def light_frames(scene, folder: Path, look: str, times: list[float]) -> list[Path]:
    """PNG frames of the 3D light player at ``times`` (seconds of its wide view), on the video page of
    ``render_video`` (seeded, no bar). The caption block is left out: at gallery size it cannot be read, so the
    README's alt text says what it says."""

    from optodraw.animation3d.tour import Tour
    from optodraw.animation3d.video import _wait_ready
    from optodraw.renderers.capture3d import _Pipe, find_chrome
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    width, height = GIF[:2]
    html = ThreeJsRenderer(scene, look=look, tour_drives=True, tour=Tour([]),
                           video={"width": width, "height": height, "fps": GIF[2]}).render()
    html = html.replace("</style>", "#od-captions { display: none !important; }\n</style>", 1)
    page = folder / "light.html"
    page.write_text(html, encoding="utf-8")
    pipe = _Pipe(find_chrome(), folder / "profile", width, height)
    frames = []
    try:
        target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        pipe.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                         "mobile": False}, session)
        pipe.call("Page.navigate", {"url": page.as_uri()}, session)
        _wait_ready(pipe, session)
        for i, t in enumerate(times):
            pipe.call("Runtime.evaluate", {"expression": f"(odLight.frameAt({t!r}), new Promise((r) => "
                                           "requestAnimationFrame(() => r(1))))", "awaitPromise": True}, session,
                      timeout=120)
            frames.append(folder / f"frame_{i:05d}.png")
            frames[-1].write_bytes(base64.b64decode(pipe.call("Page.captureScreenshot", {"format": "png"},
                                                              session, timeout=120)["data"]))
    finally:
        pipe.close()
    return frames


def light_gif(scene, target: Path, look: str = "light") -> None:
    """The first seconds of the light player's wide view as a looping GIF, one palette for all frames."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("the light GIF needs ffmpeg")
    fps, seconds = GIF[2], GIF[3]
    with tempfile.TemporaryDirectory() as folder:
        light_frames(scene, Path(folder), look, [i / fps for i in range(round(fps * seconds))])
        subprocess.run([ffmpeg, "-v", "error", "-y", "-framerate", str(fps), "-i", f"{folder}/frame_%05d.png",
                        "-vf", "split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a",
                        "-loop", "0", str(target)], check=True)


class Editor:
    """The editor on a throwaway workspace, in headless Chrome: load a scene, click, and take a screenshot."""

    def __init__(self, base: str, pipe):
        self.base, self.pipe = base, pipe
        target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        pipe.call("Emulation.setDeviceMetricsOverride", {"width": EDITOR[0], "height": EDITOR[1],
                                                         "deviceScaleFactor": 1, "mobile": False}, self.session)

    def api(self, method: str, path: str, body: dict | None = None, raw: bytes | None = None):
        import json

        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        kind = "application/octet-stream" if raw is not None else "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": kind})
        with urllib.request.urlopen(request, timeout=120) as reply:
            return json.loads(reply.read())

    def js(self, expression: str):
        result = self.pipe.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                     "awaitPromise": True}, self.session)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait(self, expression: str, seconds: float = 60.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if value := self.js(expression):
                return value
            time.sleep(0.3)
        raise RuntimeError(f"the editor never showed {expression}")

    def open(self) -> None:
        self.pipe.call("Page.navigate", {"url": self.base + "/"}, self.session)
        self.wait("!!document.querySelector('#canvas svg')")
        self.js("document.querySelectorAll('.welcome, #welcome').forEach(e => e.hidden = true)")

    def click(self, selector: str) -> None:
        """A real mouse click, as a person makes it, on a drawn shape of the element (its middle can be a gap)."""

        box = self.wait(f"(() => {{ const e = document.querySelector({selector!r}); if (!e) return null;"
                        " for (const s of [e, ...e.querySelectorAll('*')]) { const r = s.getBoundingClientRect();"
                        " const x = r.x + r.width / 2, y = r.y + r.height / 2;"
                        " if (r.width && e.contains(document.elementFromPoint(x, y))) return [x, y]; }"
                        " return null; })()")
        for kind in ("mousePressed", "mouseReleased"):
            self.pipe.call("Input.dispatchMouseEvent", {"type": kind, "x": box[0], "y": box[1], "button": "left",
                                                        "clickCount": 1}, self.session)

    def shoot(self, target: Path) -> None:
        time.sleep(1.0)                                   # the last frame of a transition
        data = self.pipe.call("Page.captureScreenshot", {"format": "png"}, self.session)["data"]
        target.write_bytes(base64.b64decode(data))


@contextlib.contextmanager
def editor():
    import uvicorn

    from optodraw.app.server import create_app
    from optodraw.renderers.capture3d import _Pipe, find_chrome

    with tempfile.TemporaryDirectory(prefix="optodraw-media-") as folder:
        os.environ["OPTODRAW_WORKSPACE_DIR"] = str(Path(folder) / "workspaces")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        end = time.monotonic() + 30
        while not server.started and time.monotonic() < end:
            time.sleep(0.1)
        pipe = _Pipe(find_chrome(), Path(folder) / "profile", *EDITOR)
        try:
            yield Editor(f"http://127.0.0.1:{port}", pipe)
        finally:
            pipe.close()
            server.should_exit = True
            thread.join(timeout=10)


def editor_2d(app: Editor, scene, target: Path) -> None:
    """The editor in 2D with the modulator selected, so the inspector shows its parameters."""

    app.api("POST", "/api/scene", {"spec": scene.to_spec()})
    app.open()
    app.js("document.getElementById('btn-fit').click()")
    part = next(c["id"] for c in app.api("GET", "/api/scene")["components"] if c["type"] == "MZM")
    app.click(f'[data-component-id="{part}"]')
    app.wait("!document.getElementById('props-form').hidden")
    app.shoot(target)


def editor_layout(app: Editor, component: str, target: Path) -> None:
    """A device of the gdsfactory generic PDK (``component`` names its cell function), written to a GDS file,
    imported, and shown in the Layout view, with the inspector at the part's GDS layers."""

    import gdsfactory as gf

    gf.gpdk.PDK.activate()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"{component}.gds"
        getattr(gf.components, component)().write_gds(str(path))
        app.api("POST", "/api/scene/new", {})
        app.api("POST", f"/api/gds/import?filename={path.name}", raw=path.read_bytes())
    app.open()
    app.wait("!document.getElementById('btn-view-layout').disabled")
    app.js("document.getElementById('btn-view-layout').click()")
    app.wait("(async () => { const v = window.gdsLens; return !!v && (await v.getLayers()).length > 0; })()")
    app.js("[...document.querySelectorAll('.insp-sec-name')].find(e => e.textContent === 'GDS layers')"
           ".scrollIntoView({block: 'start'})")
    # the part's source is a path on this machine: it must not be in the image
    shown = app.js("(() => { const panel = document.getElementById('props-form').closest('aside')"
                   ".getBoundingClientRect(); return [...document.querySelectorAll('#props-form input')].some(i => {"
                   " const r = i.getBoundingClientRect(); return i.value.startsWith('/')"
                   " && r.bottom > Math.max(panel.top, 0) && r.top < Math.min(panel.bottom, innerHeight); }); })()")
    if shown:
        raise RuntimeError("the inspector shows a file path: the Layout view image would carry it")
    app.shoot(target)


def make(name: str, cell: str, view: str, app: Editor | None) -> str:
    target = OUT / f"{name}.png" if view != "light" else OUT / f"{name}.gif"
    if view == "editor":
        editor_2d(app, page_scene(cell), target)
    elif view == "layout":
        editor_layout(app, cell.partition("/")[2], target)
    elif view == "light":
        light_gif(page_scene(cell), target)
    elif view == "3d":
        page_scene(cell).render_3d_image(str(target), background="light", width=TILE[0], height=TILE[1],
                                         quality="final", labels=False)
    elif view == "xs":
        svg_to_png(page_namespace(cell)["xs"].svg(), target)
    elif view == "sem":
        page_namespace(cell)["xs"].png(target, width_px=WIDTH)
    elif view == "1d":
        from optodraw.notebook_1d import render_notebook_1d

        svg_to_png(render_notebook_1d(page_scene(cell)), target)
    else:
        scene = readme_scene() if cell == "README" else page_scene(cell)
        svg_to_png(scene.render_svg().as_svg(), target)
    if name in GALLERY and view != "light":
        tile(target)
    return f"{target.relative_to(ROOT)}"


def tile(path: Path) -> None:
    """Fit the image into TILE, centred on its own background (the colour of its top-left pixel)."""

    from PIL import Image

    image = Image.open(path).convert("RGB")
    scale = min(TILE[0] / image.width, TILE[1] / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", TILE, image.getpixel((0, 0)))
    canvas.paste(image, ((TILE[0] - image.width) // 2, (TILE[1] - image.height) // 2))
    canvas.save(path, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="only these images (by name); default: all")
    parser.add_argument("--no-3d", action="store_true", help="skip the studio renders and the light video")
    parser.add_argument("--list", action="store_true", help="print the image list and exit")
    args = parser.parse_args()
    images = {"quickstart": ("README", "2d"), **GALLERY}
    images = {name: job for name, job in images.items()
              if (not args.names or name in args.names) and not (args.no_3d and job[1] in SLOW)}
    if args.list:
        for name, (cell, view) in images.items():
            print(f"docs/public/media/{name}.{'gif' if view == 'light' else 'png'}  <- {cell}, {view}")
        return 0
    warnings.simplefilter("ignore")
    sys.path.insert(0, str(ROOT))
    OUT.mkdir(parents=True, exist_ok=True)
    browser_views = {name: job for name, job in images.items() if job[1] in ("editor", "layout")}
    for name, (cell, view) in images.items():
        if name not in browser_views:
            print(make(name, cell, view, None))
    if browser_views:
        with editor() as app:
            for name, (cell, view) in browser_views.items():
                print(make(name, cell, view, app))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
