"""The Blender path renders the scene: the camera sees it, the background is the one asked for."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import optodraw
from optodraw.blender import export_blender_script


def _script(tmp_path, **kwargs) -> str:
    glb = tmp_path / "scene.glb"
    glb.write_bytes(b"")
    path = export_blender_script(tmp_path / "render.py", source_glb=glb, output_image=tmp_path / "out.png", **kwargs)
    return Path(path).read_text(encoding="utf-8")


def test_the_camera_sees_a_scene_of_any_size(tmp_path):
    """Scene units import as metres; Blender's default far clip (100 m) cut a 300-unit scene away."""

    assert "clip_end" in _script(tmp_path)


def test_the_background_colour_is_set_on_the_world_nodes(tmp_path):
    """world.color is ignored once the world uses nodes: the render came out grey."""

    script = _script(tmp_path, background_color="#ffffff")
    assert "'BACKGROUND'" in script and "use_nodes = True" in script


def test_background_none_renders_a_transparent_film(tmp_path):
    script = _script(tmp_path, background_color="none")
    assert "TRANSPARENT = True" in script and "film_transparent = TRANSPARENT" in script and "'RGBA'" in script


def _blender() -> str | None:
    found = shutil.which("blender")
    mac = Path("/Applications/Blender.app/Contents/MacOS/Blender")
    return found or (str(mac) if mac.exists() else None)


@pytest.mark.skipif(_blender() is None, reason="needs Blender")
def test_blender_renders_the_scene_not_an_empty_frame(tmp_path):
    from PIL import Image, ImageStat

    from optodraw.exporters.glb import scene_to_glb

    scene = optodraw.Scene(width=200, height=100, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-60, 0)))
    lens = scene.add(optodraw.Lens(center=(0, 0)))
    pd = scene.add(optodraw.Photodiode(center=(60, 0)))
    scene.add(optodraw.Beam(laser, lens, pd))
    glb = tmp_path / "scene.glb"
    glb.write_bytes(scene_to_glb(scene))
    out = tmp_path / "out.png"
    script = export_blender_script(tmp_path / "render.py", source_glb=glb, output_image=out, resolution=(320, 200),
                                   samples=8, background_color="none")
    subprocess.run([_blender(), "--background", "--python", str(script)], check=True, capture_output=True, timeout=600)
    image = Image.open(out).convert("RGBA")
    assert image.getpixel((1, 1))[3] == 0                                   # transparent where nothing is
    assert image.getchannel("A").getbbox() is not None                      # the parts are there
    assert max(ImageStat.Stat(image.convert("RGB")).stddev) > 5.0           # not one flat colour
    box = image.getchannel("A").getbbox()
    assert box[2] - box[0] > 0.4 * image.width                              # framed, not a speck in the middle


def test_a_script_can_take_the_camera_from_the_scene_file(tmp_path):
    """The viewer's camera travels in the GLB, so the photoreal image has the viewer's framing."""

    assert "CAMERA_FROM_SCENE = True" in _script(tmp_path, camera_from_scene=True)
    assert "CAMERA_FROM_SCENE = False" in _script(tmp_path)
