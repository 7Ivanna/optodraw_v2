"""The recorded camera tour of a 3D scene, frame by frame, as a video.

The 3D page is built as a recording stage: the bar and every control are hidden (the caption block stays with all its
lines, so each screenshot carries them), the random numbers of the page are seeded, and the page draws the tour at the times Python asks
for (``odLight.frameAt``). With ffmpeg, Python takes a PNG screenshot of each frame at ``i / fps`` and streams it to
ffmpeg (MP4, H.264). Without ffmpeg, the page plays the tour in real time and a ``MediaRecorder`` saves it (WebM).
"""

from __future__ import annotations

import base64
import logging
import math
import shutil
import subprocess
import tempfile
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

from optodraw.renderers.capture3d import _Pipe, find_chrome

from .tour import Tour

log = logging.getLogger("optodraw.video")

SEED = 0x0D0D0D0D
LOAD_TIMEOUT_S = 180.0
FRAME_TIMEOUT_S = 120.0

# The page's random numbers (the ambient occlusion noise draws on Math.random at every load) come from one seeded
# generator that starts before any script of the page. A page error is written to #od-video at once. window.__odVideo
# tells the player the page is a video.
_HEAD = """<script>
window.__odVideo = true;            // the player shows every caption line: nobody can open Scales in a video
(function () {
  var a = %(seed)d >>> 0;
  Math.random = function () {
    a = (a + 0x6D2B79F5) >>> 0;
    var t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  function fail(m) { var o = document.getElementById('od-video'); if (o && !o.value) o.value = 'error: ' + m; }
  window.addEventListener('error', function (e) { fail(e.message || 'page error'); });
  window.addEventListener('unhandledrejection', function (e) { var r = e.reason; fail(r && r.message ? r.message : String(r)); });
})();
</script>
"""

_CSS = """      #od-bar, #info, #layer-legend, #render-overlay, #od-captions .od-scales { display: none !important; }
"""

# The page tells Python when the tour is ready (and how long it lasts); __odRecord plays the tour in real time and
# returns a WebM as base64 (``odLight.recordTour``, the same code as the page's Record video button).
_BODY = """<textarea id="od-video" style="display:none"></textarea>
<script>
(function () {
  var out = document.getElementById('od-video');
  (function wait() {
    if (!(window.odLight && window.odLight.state.built)) { setTimeout(wait, 50); return; }
    try {
      var warp = (window.__odLightData && window.__odLightData.tour_warp) || [];
      if (!window.__odLightData || !window.__odLightData.enabled || warp.length < 2) { out.value = 'error: the scene has no light to tour'; return; }
      odLight.control('tour', true);
      odLight.frameAt(0);
      out.value = 'ready:' + warp[warp.length - 1][0];
    } catch (e) { out.value = 'error: ' + e.message; }
  })();
  window.__odRecord = function (fps, duration) {
    return odLight.recordTour(fps, duration).then(function (blob) {
      return new Promise(function (resolve) {
        var reader = new FileReader();
        reader.onload = function () { resolve(String(reader.result).split(',')[1]); };
        reader.readAsDataURL(blob);
      });
    });
  };
})();
</script>
"""


def video_page_parts(video: dict[str, Any]) -> tuple[str, str, str]:
    """``(head, css, body)`` additions that turn the 3D page into a recording stage (``ThreeJsRenderer(video=...)``)."""

    return _HEAD % {"seed": int(video.get("seed", SEED))}, _CSS, _BODY


def _evaluate(pipe: _Pipe, session: str, expression: str, *, timeout: float, wait: bool = False) -> Any:
    reply = pipe.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": wait},
                      session, timeout=timeout)
    if "exceptionDetails" in reply:
        details = reply["exceptionDetails"]
        raise RuntimeError("The video page failed: " + str((details.get("exception") or {}).get("description")
                                                           or details.get("text")))
    return reply.get("result", {}).get("value")


def _wait_ready(pipe: _Pipe, session: str) -> float:
    """The tour's length in seconds, once the page has built its scene and started the tour."""

    deadline = time.monotonic() + LOAD_TIMEOUT_S
    while time.monotonic() < deadline:
        value = _evaluate(pipe, session, "(document.getElementById('od-video')||{}).value||''", timeout=30.0)
        if value.startswith("error"):
            raise RuntimeError(f"The 3D page did not start the tour: {value[7:]}")
        if value.startswith("ready:"):
            return float(value[6:])
        time.sleep(0.25)
    raise RuntimeError("The 3D page did not get ready in time.")


class _Progress:
    """Reports ``done`` of ``total`` frames each time another 10 % is done, to ``callback`` and the ``optodraw.video`` log."""

    def __init__(self, total: int, callback: Callable[[int, int], None] | None):
        self.total, self.callback, self.tenth = total, callback, 0

    def __call__(self, done: int) -> None:
        tenth = done * 10 // self.total
        if tenth > self.tenth:
            self.tenth = tenth
            log.info("video: %d of %d frames", done, self.total)
            if self.callback:
                self.callback(done, self.total)


def render_video(scene: Any, path: str | Path, *, look: str = "light", tour: str | Tour = "auto", width: int = 1920,
                 height: int = 1080, fps: int = 30, params: dict | None = None, inputs: list | None = None,
                 chrome: str | None = None, keep_frames: str | Path | None = None,
                 progress: Callable[[int, int], None] | None = None) -> Path:
    """Render the camera tour of ``scene`` as a video of ``width`` x ``height`` at ``fps`` frames per second.

    ``tour`` is ``"auto"`` (the tour saved in the scene, else the automatic one) or a ``Tour``. The video lasts the
    tour's length. Frame ``i`` is the page at ``i / fps`` seconds, so the same scene gives the same frames. With
    ffmpeg on the path the file is an MP4 (H.264, each frame piped to ffmpeg as a PNG, never all in memory); without
    it the page records a real-time playback as WebM, the suffix of ``path`` becomes ``.webm`` and a warning says so.
    With ffmpeg a suffix other than ``.mp4`` becomes ``.mp4``; the returned path is the real one. A failed render leaves
    no file at the path and keeps any earlier file there.
    ``keep_frames`` (a folder) also keeps each frame as ``frame_00000.png`` (MP4 route only). ``progress(done, total)``
    is called at every 10 % of the frames. Returns the path written."""

    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    if not (isinstance(tour, Tour) or tour == "auto"):
        raise ValueError('tour must be "auto" or a Tour')
    width, height, fps = int(width), int(height), int(fps)
    if width < 16 or height < 16:
        raise ValueError("width and height must be at least 16 pixels")
    if fps < 1:
        raise ValueError("fps must be 1 or more")
    ffmpeg = shutil.which("ffmpeg")
    out = Path(path)
    if ffmpeg:
        if width % 2 or height % 2:
            raise ValueError("width and height must be even for an MP4")
        out = out.with_suffix(".mp4") if out.suffix.lower() != ".mp4" else out
    else:
        out = out.with_suffix(".webm")
        warnings.warn(f"ffmpeg is not installed: the video is a real-time WebM recording, saved as {out.name}. "
                      "The part labels (CSS2D) are not in the WebM, and keep_frames is ignored on this route",
                      UserWarning, stacklevel=2)
    browser = chrome or find_chrome()
    html = ThreeJsRenderer(scene, look=look, params=params, inputs=inputs, tour_drives=True,
                           tour=None if tour == "auto" else tour,
                           video={"width": width, "height": height, "fps": fps}).render()
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = Path(keep_frames) if keep_frames else None
    if kept:
        kept.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="optodraw-video-") as folder:
        page = Path(folder) / "scene.html"
        page.write_text(html, encoding="utf-8")
        pipe = _Pipe(browser, Path(folder) / "profile", width, height)
        try:
            target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            pipe.call("Emulation.setDeviceMetricsOverride",
                      {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, session)
            pipe.call("Page.navigate", {"url": page.as_uri()}, session)
            seconds = _wait_ready(pipe, session)
            if ffmpeg:
                _record_frames(pipe, session, ffmpeg, out, Path(folder), seconds, fps, kept, progress)
            else:
                data = _evaluate(pipe, session, f"window.__odRecord({fps}, {seconds!r})", timeout=seconds + FRAME_TIMEOUT_S,
                                 wait=True)
                out.write_bytes(base64.b64decode(data))
        finally:
            pipe.close()
    return out


def _record_frames(pipe: _Pipe, session: str, ffmpeg: str, out: Path, folder: Path, seconds: float, fps: int,
                   kept: Path | None, progress: Callable[[int, int], None] | None) -> None:
    """Draw frame ``i`` at ``i / fps``, screenshot it and stream it to ffmpeg."""

    total = max(1, math.ceil(seconds * fps - 1e-6))
    report = _Progress(total, progress)
    part = out.with_name(out.name + ".part")           # ffmpeg writes here; success renames it, failure deletes it
    command = [ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-f", "mp4", str(part)]
    errors = (folder / "ffmpeg.log").open("wb")
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
    except BaseException:
        errors.close()
        raise
    sent, done = 0, False
    try:
        try:
            for i in range(total):
                _evaluate(pipe, session,
                          f"(odLight.frameAt({i / fps!r}), new Promise((r) => requestAnimationFrame(() => r(1))))",
                          timeout=FRAME_TIMEOUT_S, wait=True)
                png = base64.b64decode(pipe.call("Page.captureScreenshot", {"format": "png"}, session,
                                                 timeout=FRAME_TIMEOUT_S)["data"])
                if kept:
                    (kept / f"frame_{i:05d}.png").write_bytes(png)
                assert process.stdin is not None
                process.stdin.write(png)
                sent += 1
                report(i + 1)
        except BrokenPipeError:
            pass                                       # ffmpeg stopped early: its exit code and the count tell why
        except BaseException:
            process.kill()
            raise
        finally:
            try:
                if process.stdin:
                    process.stdin.close()
            except BrokenPipeError:
                pass
            code = process.wait()
            errors.close()
        if code != 0:
            raise RuntimeError("ffmpeg failed: " + (folder / "ffmpeg.log").read_text(errors="replace").strip()[-500:])
        if sent < total:
            raise RuntimeError(f"ffmpeg stopped after {sent} of {total} frames")
        part.replace(out)
        done = True
    finally:
        if not done:
            part.unlink(missing_ok=True)
