"""The studio renderer from Python: Scene.render_3d_image(engine="studio")."""

from __future__ import annotations

import io

import pytest

import optodraw
from optodraw.renderers.capture3d import find_chrome

needs_chrome = pytest.mark.skipif(find_chrome(required=False) is None, reason="needs Chrome, Chromium or Edge")


def _bench():
    scene = optodraw.Scene(title="bench", width=120, height=80, platform="free_space")
    laser = scene.add(optodraw.Laser(center=(-30, 0), label="laser"))
    lens = scene.add(optodraw.Lens(center=(0, 0), label="lens"))
    detector = scene.add(optodraw.Photodiode(center=(30, 0), label="PD"))
    scene.add(optodraw.Beam(laser, lens, detector, label=""))
    return scene


def _image(path):
    from PIL import Image

    return Image.open(io.BytesIO(path.read_bytes())).convert("RGBA")


@pytest.mark.parametrize("engine", ["other", "blender"])
def test_an_unknown_engine_is_a_named_error(tmp_path, engine):
    """optodraw renders with its own engines only; Blender is not one."""

    with pytest.raises(ValueError, match="^engine must be one of: studio, viewer$"):
        _bench().render_3d_image(str(tmp_path / "x.png"), engine=engine)


@needs_chrome
def test_a_studio_image_has_its_size_and_is_clear_where_there_is_nothing(tmp_path):
    path = _bench().render_3d_image(str(tmp_path / "bench.png"), engine="studio", background="none", width=160,
                                    height=100, scale=1.0, samples=1, quality="draft")
    image = _image(path)
    assert image.size == (160, 100)
    alpha = image.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0                                 # nothing in the corner: transparent
    assert max(alpha.getdata()) == 255                                 # the parts are solid


@needs_chrome
def test_a_studio_render_that_runs_out_of_time_names_its_last_stage(tmp_path):
    from optodraw.renderers.capture3d import render_3d_image

    with pytest.raises(RuntimeError, match=r"last stage: (reading the scene|preparing|tile \d+ of \d+)"):
        render_3d_image(_bench(), tmp_path / "slow.png", engine="studio", width=1600, height=1000, scale=2.0,
                        samples=16, timeout=6.0)


def test_the_editor_loads_where_python_has_no_fcntl():
    """Windows has no fcntl: the module that drives Chrome for 3D images imports it only when it runs."""

    import subprocess
    import sys

    code = "import sys; sys.modules['fcntl'] = None; import optodraw.app.server, optodraw.renderers.capture3d"
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-600:]
