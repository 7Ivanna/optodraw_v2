"""render_video: the tour of a 3D scene, frame by frame, in headless Chrome, saved as MP4 (WebM without ffmpeg)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from optodraw import Scene
from optodraw.animation3d.tour import Stop, Tour
from optodraw.animation3d.video import render_video
from optodraw.registry import build_component
from optodraw.renderers.capture3d import find_chrome

needs_chrome = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
SMALL = dict(width=320, height=180, fps=10)


def _chip() -> Scene:
    scene = Scene(width=600, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-200, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(200, 0)))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (det, "o1"), kind="waveguide")
    return scene


def _two_seconds() -> Tour:
    """A wide view of 0.5 s, one stop held for 1 s, a wide view of 0.5 s: 2 s."""

    return Tour([Stop("mzm1", hold_s=1.0)], wide_s=0.5)


def _hashes(folder: Path, numbers=(0, 10, 19)) -> list[str]:
    return [hashlib.sha256((folder / f"frame_{n:05d}.png").read_bytes()).hexdigest() for n in numbers]


def _frames(path: Path) -> tuple[int, str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames,width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)["streams"][0]
    return int(stream["nb_read_frames"]), f"{stream['width']}x{stream['height']}"


@needs_chrome
@needs_ffmpeg
@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_two_second_tour_is_twenty_frames_and_the_same_scene_gives_the_same_frames(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    calls: list[tuple[int, int]] = []
    out = render_video(_chip(), tmp_path / "tour.mp4", tour=_two_seconds(), keep_frames=first,
                       progress=lambda done, total: calls.append((done, total)), **SMALL)
    assert out == tmp_path / "tour.mp4" and out.exists() and out.stat().st_size > 0
    assert _frames(out) == (20, "320x180")
    render_video(_chip(), tmp_path / "again.mp4", tour=_two_seconds(), keep_frames=second, **SMALL)
    assert _hashes(first) == _hashes(second)                       # the same scene gives the same pixels
    assert len(set(_hashes(first))) == 3                           # and the frames differ from each other
    assert [d for d, _ in calls] == list(range(2, 21, 2)) and {t for _, t in calls} == {20}   # every 10 %


@needs_chrome
@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_without_ffmpeg_the_video_is_a_webm_and_says_so(tmp_path, monkeypatch):
    chrome = find_chrome()
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    with pytest.warns(UserWarning, match="WebM"):
        out = render_video(_chip(), tmp_path / "tour.mp4", tour=_two_seconds(), chrome=chrome, **SMALL)
    assert out == tmp_path / "tour.webm" and not (tmp_path / "tour.mp4").exists()
    assert out.read_bytes()[:4] == bytes.fromhex("1a45dfa3") and out.stat().st_size > 1000   # an EBML (WebM) file
    monkeypatch.undo()
    if shutil.which("ffmpeg"):                                     # the caption block is drawn into the recording
        from PIL import Image
        frame = tmp_path / "mid.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(out), "-frames:v", "1", str(frame)],
                       check=True)
        box = Image.open(frame).convert("L").crop((12, 100, 200, 170))
        assert box.getextrema()[1] > 180                            # the caption's pale text on the dark block


def test_a_tour_name_that_is_not_auto_and_odd_sizes_are_refused(tmp_path):
    with pytest.raises(ValueError, match="tour"):
        render_video(_chip(), tmp_path / "x.mp4", tour="fast", **SMALL)
    with pytest.raises(ValueError, match="fps"):
        render_video(_chip(), tmp_path / "x.mp4", width=320, height=180, fps=0)


@needs_chrome
@needs_ffmpeg
@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_scene_method_renders_the_tour_with_the_scenes_own_settings(tmp_path):
    out = _chip().render_tour_video(tmp_path / "scene.mp4", tour=_two_seconds(), **SMALL)
    assert _frames(out) == (20, "320x180")


@needs_chrome
@needs_ffmpeg
@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_failed_render_leaves_no_partial_file_and_keeps_an_earlier_video(tmp_path, monkeypatch):
    from optodraw.animation3d import video

    out = tmp_path / "tour.mp4"
    out.write_bytes(b"earlier video")
    real = video._evaluate

    def failing(pipe, session, expression, **kwargs):
        if "frameAt(0.5" in expression:
            raise RuntimeError("frame failed")
        return real(pipe, session, expression, **kwargs)

    monkeypatch.setattr(video, "_evaluate", failing)
    with pytest.raises(RuntimeError, match="frame failed"):
        render_video(_chip(), out, tour=_two_seconds(), **SMALL)
    assert out.read_bytes() == b"earlier video"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tour.mp4"]          # no .part file
    out.unlink()
    with pytest.raises(RuntimeError, match="frame failed"):
        render_video(_chip(), out, tour=_two_seconds(), **SMALL)
    assert list(tmp_path.iterdir()) == []
