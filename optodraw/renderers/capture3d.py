"""A 3D image from Python: the three.js view rendered in a headless browser and saved as PNG.

The page renders once, in a capture mode (no panels, no animation loop), at the
size and background asked for, and writes the PNG into its own DOM. Python drives
a headless Chrome over its debugging pipe, waits for that PNG and reads it, so the
file is exactly the view and has an alpha channel when the background is ``"none"``.
"""

from __future__ import annotations

import base64
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

BACKGROUNDS = ("none", "light", "dark")
CHROME_FLAGS: list[str] = []          # extra browser flags (tests use them to turn WebGL off)

_CANDIDATES = {
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ],
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"],
}


def find_chrome(required: bool = True) -> str | None:
    """The browser that renders 3D images: ``OPTODRAW_CHROME``, else a Chrome, Chromium or Edge found here."""

    chosen = os.environ.get("OPTODRAW_CHROME")
    if chosen:
        if Path(chosen).exists():
            return chosen
        if required:
            raise RuntimeError(f"OPTODRAW_CHROME is set to {chosen}, which does not exist.")
        return None
    for name in _CANDIDATES.get(sys.platform, _CANDIDATES["linux"]):
        path = name if Path(name).is_absolute() else shutil.which(name)
        if path and Path(path).exists():
            return path
    if required:
        raise RuntimeError("A 3D image needs Chrome, Chromium or Edge. Install one, or set OPTODRAW_CHROME "
                           "to the browser executable.")
    return None


class _Pipe:
    """The Chrome DevTools protocol over --remote-debugging-pipe (fd 3 in, fd 4 out): standard library only."""

    def __init__(self, browser: str, profile: Path, width: int, height: int):
        if os.name != "posix":
            raise RuntimeError("3D images need macOS or Linux for now.")
        import fcntl                               # Unix only: imported here so the editor still loads on Windows
        to_chrome_r, self._to_chrome = os.pipe()
        self._from_chrome, from_chrome_w = os.pipe()

        def wire() -> None:                        # in the child, before exec: the pipe ends become fds 3 and 4
            high_r = fcntl.fcntl(to_chrome_r, fcntl.F_DUPFD, 10)      # above 4 first, so neither end is overwritten
            high_w = fcntl.fcntl(from_chrome_w, fcntl.F_DUPFD, 10)
            os.dup2(high_r, 3)
            os.dup2(high_w, 4)

        gl = ["--use-angle=metal"] if sys.platform == "darwin" else ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        command = [browser, "--headless=new", "--remote-debugging-pipe", *gl, "--hide-scrollbars", "--mute-audio",
                   "--no-first-run", *CHROME_FLAGS,
                   f"--window-size={width},{height}", f"--user-data-dir={profile}", "about:blank"]
        self.process = subprocess.Popen(command, preexec_fn=wire, close_fds=False,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self._buffer, self._next = b"", 0
        self.stage = ""                            # the last 'od-stage: ...' console message (needs Runtime.enable)

    def call(self, method: str, params: dict[str, Any] | None = None, session: str | None = None,
             timeout: float = 60.0) -> dict[str, Any]:
        self._next += 1
        message: dict[str, Any] = {"id": self._next, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        os.write(self._to_chrome, json.dumps(message).encode() + b"\0")
        deadline = time.monotonic() + timeout
        while True:
            while b"\0" in self._buffer:
                raw, self._buffer = self._buffer.split(b"\0", 1)
                reply = json.loads(raw)
                if reply.get("method") == "Runtime.consoleAPICalled":
                    text = str((reply["params"].get("args") or [{}])[0].get("value", ""))
                    if text.startswith("od-stage: "):
                        self.stage = text[len("od-stage: "):]
                if reply.get("id") == self._next:
                    if "error" in reply:
                        raise RuntimeError(f"{method}: {reply['error'].get('message')}")
                    return reply.get("result", {})
            if time.monotonic() > deadline:
                raise TimeoutError(method)
            ready, _, _ = select.select([self._from_chrome], [], [], 0.5)
            if ready:
                chunk = os.read(self._from_chrome, 1 << 20)
                if not chunk:
                    raise RuntimeError("The browser closed.")
                self._buffer += chunk

    def close(self) -> None:
        try:
            self.call("Browser.close", timeout=5.0)
        except Exception:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        for fd in (self._to_chrome, self._from_chrome):
            try:
                os.close(fd)
            except OSError:
                pass


def run_page(html: str, *, width: int = 800, height: int = 600, timeout: float = 60.0,
             chrome: str | None = None, element: str = "od-capture", stage: str | None = None) -> str:
    """Load ``html`` in a headless browser and return what the page writes into ``#element`` ('' if nothing).

    With ``stage``, a page that runs out of time gives ``"error: timed out (last stage: <#stage text>)"``.
    """

    browser = chrome or find_chrome()
    probe = f"(function(){{var e=document.getElementById({json.dumps(element)});return e?e.value:'';}})()"
    with tempfile.TemporaryDirectory(prefix="optodraw-3d-") as folder:
        page = Path(folder) / "scene.html"
        page.write_text(html, encoding="utf-8")
        pipe = _Pipe(browser, Path(folder) / "profile", int(width), int(height))
        try:
            target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            if stage:
                pipe.call("Runtime.enable", {}, session)                   # the page's console messages carry its stage
            pipe.call("Page.navigate", {"url": page.as_uri()}, session)
            deadline, value = time.monotonic() + timeout, ""
            while time.monotonic() < deadline:                 # the page is busy while it builds and renders
                try:
                    value = pipe.call("Runtime.evaluate", {"expression": probe, "returnByValue": True}, session,
                                      timeout=max(deadline - time.monotonic(), 1.0)).get("result", {}).get("value") or ""
                except TimeoutError:
                    break
                if value:
                    break
                time.sleep(0.5)
            if not value and stage and pipe.stage:
                value = f"error: timed out (last stage: {pipe.stage})"
            elif not value and stage:
                probe = f"(function(){{var e=document.getElementById({json.dumps(stage)});return e?e.value:'';}})()"
                try:
                    last = pipe.call("Runtime.evaluate", {"expression": probe, "returnByValue": True}, session,
                                     timeout=10.0).get("result", {}).get("value") or "not started"
                except (TimeoutError, RuntimeError):
                    last = "the page did not answer"
                value = f"error: timed out (last stage: {last})"
        finally:
            pipe.close()
    return value


def _capture(scene: Any, capture: dict[str, Any], camera: Any, prefix: str, timeout: float) -> bytes:
    """Run the page in capture mode and return the PNG it writes."""

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    chrome = capture.pop("chrome", None)
    world = "light" if capture["background"] == "none" else capture["background"]
    view = {"camera_preset": camera} if isinstance(camera, str) else {"camera_direction": camera}
    html = ThreeJsRenderer(scene, capture=capture, world=world, **view).render()
    value = run_page(html, width=int(capture["width"]), height=int(capture["height"]), timeout=timeout, chrome=chrome,
                     stage="od-stage")
    if not value.startswith(prefix):
        raise RuntimeError("The 3D page did not produce its file" + (f": {value[7:]}" if value else " in time."))
    return base64.b64decode(value.split(",", 1)[1])


ENGINES = ("studio", "viewer")
QUALITIES = ("final", "draft")


def render_3d_image(scene: Any, filename: str | os.PathLike[str], *, background: str = "none",
                    camera: str | tuple[float, float, float] = "isometric", width: int = 1600, height: int = 1000,
                    scale: float = 2.0, labels: bool = False, engine: str = "studio", samples: int = 4,
                    quality: str = "final", chrome: str | None = None, timeout: float | None = None,
                    workers: int | None = None) -> Path:
    """Render ``scene`` in 3D and save a PNG of ``width`` x ``height`` times ``scale`` pixels.

    ``background`` is ``"none"`` (transparent, no floor), ``"light"`` or ``"dark"`` (the studio
    worlds of the viewer). ``camera`` is a viewer camera preset, such as ``"isometric"`` or ``"top"``,
    or a direction ``(x, y, z)`` from the scene toward the camera (z up).
    ``engine="studio"`` (the default) is optodraw's own renderer: studio light, soft shadows, ambient
    occlusion and reflections, on the CPU of any machine, ``samples`` per pixel. ``quality="draft"``
    is a quick look (scale 1, one sample, fewer rays). ``engine="viewer"`` saves the viewer's own
    real-time render.
    """

    if background not in BACKGROUNDS:
        raise ValueError(f"background must be one of: {', '.join(BACKGROUNDS)}")
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of: {', '.join(ENGINES)}")
    if quality not in QUALITIES:
        raise ValueError(f"quality must be one of: {', '.join(QUALITIES)}")
    if quality == "draft":
        scale, samples = 1.0, 1
    capture = {"width": int(width), "height": int(height), "scale": float(scale), "background": background,
               "labels": bool(labels), "chrome": chrome}
    out = Path(filename)
    out.parent.mkdir(parents=True, exist_ok=True)
    if engine == "studio":
        capture.update({"engine": "studio", "samples": max(1, int(samples)), "quality": quality, "workers": workers})
    limit = timeout if timeout is not None else (1800.0 if engine == "studio" else 180.0)
    out.write_bytes(_capture(scene, capture, camera, "data:image/png;base64,", limit))
    return out

