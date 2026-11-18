"""Record the short demo loop: drag an optic, watch the rays re-fold, go 3D.

A still cannot show the one thing that makes the editor worth opening — the
trace follows the hardware while you drag it. So the demo is recorded, and
recorded by a script, so it can be re-shot after any change instead of aging
into a lie.

    python scripts/make_demo.py            # webm -> mp4 + gif
    python scripts/make_demo.py --list     # what it would write

Needs Playwright with Chromium (``playwright install chromium``). ffmpeg is
optional: without it the raw .webm is still written.

Like the screenshot scripts, this drives a server on a throwaway workspace
directory, so none of the author's saved scenes are touched.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "public" / "media"
SIZE = (1280, 800)
GIF_WIDTH = 760
GIF_FPS = 8
GIF_SECONDS = 20  # a README gif has to stay small enough to actually load


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def _editor_server(port: int):
    """Run the editor in a background thread against a throwaway workspace dir."""

    import uvicorn

    from optodraw.app.server import create_app

    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:  # uvicorn flips this once the socket is listening
        if not thread.is_alive():
            raise RuntimeError("the editor server died during startup")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _scene():
    """A traced bundle through a lens: dragging the lens re-folds the rays."""

    from optodraw import Laser, Lens, Photodiode, Scene
    from optodraw.app.session import EditorSession

    scene = Scene(width=220, height=120, title="Drag an optic, the rays follow")
    scene.add(Laser(center=(-80, 0), rays=11, beam_width=7.0, label="laser"))
    scene.add(Lens(center=(-20, 0), focal_length=30.0, aperture=18.0, label="lens"))
    scene.add(Photodiode(center=(70, 0), angle=180, label="detector"))
    session = EditorSession(scene.to_spec())
    source = next(c["id"] for c in session.spec["components"] if c["type"] == "Laser")
    session.trace_from(source)
    return session.spec


def _grip(page, component_id: str) -> tuple[float, float]:
    """A point on the drawn optic that neither the label nor the beam covers.

    Two things sit in the way of a naive click. The group's box includes the
    label drawn above the part, so a fraction of that box lands on text; and the
    traced rays are drawn over the optic they pass through, so its centre
    hit-tests as a beam. Measuring the body shape itself and gripping near its
    top edge avoids both."""

    point = page.evaluate(
        """(id) => {
            const group = document.querySelector(`[data-component-id="${id}"]`);
            if (!group) return null;
            const shape = [...group.children].find((el) => el.tagName !== 'text');
            if (!shape) return null;
            const r = shape.getBoundingClientRect();
            return [r.x + r.width / 2, r.y + r.height * 0.09];
        }""",
        component_id,
    )
    if not point:
        raise RuntimeError(f"no drawn body for component {component_id}")
    return point[0], point[1]


def _drag(page, component_id: str, dx: float, dy: float = 0.0, steps: int = 24) -> None:
    """Drag a component by (dx, dy), slowly enough to see the trace keep up."""

    x, y = _grip(page, component_id)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=steps)
    page.wait_for_timeout(250)
    page.mouse.up()
    page.wait_for_timeout(600)


def _record(base: str, spec: dict, video_dir: Path) -> Path:
    from playwright.sync_api import sync_playwright

    lens_id = next(c["id"] for c in spec["components"] if c["type"] == "Lens")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": SIZE[0], "height": SIZE[1]},
            record_video_dir=str(video_dir),
            record_video_size={"width": SIZE[0], "height": SIZE[1]},
        )
        context.add_init_script("localStorage.setItem('od-welcome-hide', '1')")
        page = context.new_page()
        page.goto(base, wait_until="networkidle")
        page.wait_for_selector("#canvas svg", timeout=30_000)
        page.click("#btn-fit")
        page.wait_for_timeout(1200)

        page.mouse.click(*_grip(page, lens_id))  # select: the Inspector fills in
        page.wait_for_timeout(600)
        selected = page.text_content("#sel-info") or ""
        if "lens" not in selected.lower():
            # A miss records a video of nothing happening, which is worse than
            # no video: fail here instead of shipping a dud.
            raise RuntimeError(f"the click selected {selected!r}, not the lens")
        _drag(page, lens_id, 90)   # push the lens downstream: the focus walks out
        _drag(page, lens_id, -150)  # and back upstream
        page.wait_for_timeout(400)

        page.click("#btn-view-3d")  # same scene, orbited
        # The 3D view is an iframe that pulls three.js from a CDN. Waiting a
        # fixed guess either cuts it off or records ten seconds of blank page;
        # __odHome appears once its scene is built and framed.
        page.wait_for_function(
            """() => {
                const frame = document.getElementById('view3d');
                return frame && frame.contentWindow && frame.contentWindow.__odHome !== undefined;
            }""",
            timeout=45_000,
        )
        page.wait_for_timeout(900)
        # One click to a known pose, then let it sit. Scripted orbiting reads as
        # a camera flailing; the point here is only that it is the same scene.
        page.frame_locator("#view3d").locator('[data-camera-preset="isometric"]').click()
        page.wait_for_timeout(700)
        page.mouse.move(SIZE[0] * 0.45, SIZE[1] * 0.5)
        for _ in range(3):  # the auto-fit frames the whole table, not the optics
            page.mouse.wheel(0, -240)
            page.wait_for_timeout(220)
        page.wait_for_timeout(2200)

        video = page.video
        context.close()  # the file is only finalised on close
        browser.close()
        return Path(video.path())


def _encode(webm: Path, out: Path) -> list[Path]:
    """webm -> mp4 (docs site) + gif (README, where mp4 does not render)."""

    written = []
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found: keeping the raw .webm only")
        return written
    mp4 = out / "demo.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm),
         "-vf", "scale=1280:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "23", "-movflags", "+faststart", str(mp4)],
        check=True,
    )
    written.append(mp4)

    palette = out / "_palette.png"
    filters = f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-t", str(GIF_SECONDS), "-i", str(webm),
         "-vf", f"{filters},palettegen=stats_mode=diff:max_colors=128", str(palette)],
        check=True,
    )
    gif = out / "demo.gif"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-t", str(GIF_SECONDS), "-i", str(webm),
         "-i", str(palette),
         "-lavfi", f"{filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3", str(gif)],
        check=True,
    )
    palette.unlink(missing_ok=True)
    written.append(gif)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="Print what would be written and exit.")
    parser.add_argument("--out", type=Path, default=OUT, help="Output directory.")
    args = parser.parse_args(argv)

    if args.list:
        for name in ("demo.mp4", "demo.gif"):
            print(args.out / name)
        return 0

    os.environ["OPTODRAW_WORKSPACE_DIR"] = tempfile.mkdtemp(prefix="optodraw-demo-")

    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        print("Playwright is missing. Install it with:\n"
              "  pip install playwright && playwright install chromium")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    video_dir = Path(tempfile.mkdtemp(prefix="optodraw-video-"))
    spec = _scene()
    with _editor_server(_free_port()) as base:
        from optodraw.app.api import _store

        _store.get("default").load(spec)
        webm = _record(base, spec, video_dir)
    print(f"recorded {webm.name} ({webm.stat().st_size // 1024} KB)")
    for path in _encode(webm, args.out):
        print(f"wrote {path}  ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
