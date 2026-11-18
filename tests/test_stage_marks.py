"""A part on a stage shows a small motion mark in 2D, not a stage drawing; the stage itself is a 3D mount."""

from __future__ import annotations

import re

import pytest

from optodraw import Mirror, Sample, Scene


def _svg(part):
    scene = Scene(title="stage", width=80, height=60, platform="free_space")
    scene.add(part)
    return scene.render_svg().as_svg()


@pytest.mark.parametrize("mount", ["stage", "xyz_stage", "rotation_stage"])
def test_a_part_on_a_stage_carries_its_motion_mark(mount):
    part = Mirror(center=(0, 0), label="M")
    part.base_mount = mount
    assert f'data-stage="{mount}"' in _svg(part)


def test_a_part_on_a_post_has_no_mark():
    assert "data-stage" not in _svg(Mirror(center=(0, 0), label="M"))


def test_the_mark_sits_on_the_side_away_from_the_label():
    part = Sample(center=(0, 0), label="Sample", label_side="bottom")
    part.base_mount = "xyz_stage"
    svg = _svg(part)
    mark = re.search(r'<g transform="translate\(([-\d.]+),([-\d.]+)\)" data-stage="xyz_stage"', svg)
    assert mark and float(mark.group(2)) < 0                    # svg y up: above the part, the label is below


def test_the_xyz_stage_is_a_3d_mount():
    import inspect
    import optodraw.renderers.threejs_renderer as module

    assert "odAddXYZStage" in inspect.getsource(module)


def test_a_cryostat_without_its_sample_draws_no_sample_and_no_beam_axis():
    """with_sample=False leaves the stage bare for a sample placed in it: the art must not draw a second one,
    nor a red axis through the windows that reads as a beam."""

    from optodraw import Cryostat
    from optodraw.symbols import lookup
    from optodraw.symbols.art import art_2d

    bare = Cryostat(with_sample=False)
    assert art_2d(bare)["params"] == {"view": "top", "sample": "no"}
    assert lookup(bare).params == {"sample": "no"} and lookup(bare).exact
    assert art_2d(Cryostat())["params"] == {"view": "top"}


@pytest.mark.parametrize("side", ["right", "bottom"])
def test_a_fitted_frame_keeps_the_motion_mark_in(side):
    """fit_frame framed the parts and their labels, not the mark: the ODMR sample's XYZ mark was cut at the frame."""

    import math

    scene = Scene(title="stage", platform="free_space")
    scene.add(Sample(center=(0, 0), angle=-90, label="Sample", label_side=side, base_mount="xyz_stage"))
    scene.fit_frame(margin=1, grid=1)
    svg = scene.render_svg().as_svg()
    mark = re.search(r'<g transform="translate\(([-\d.]+),([-\d.]+)\)" data-stage="xyz_stage"', svg)
    tx, ty = (float(v) for v in mark.groups())
    px, py, turn = (float(v) for v in re.findall(                # the part's group: the last turned one before it
        r'<g transform="translate\(([-\d.]+),([-\d.]+)\) rotate\(([-\d.]+)\)"', svg[:mark.start()])[-1])
    a = math.radians(turn)                                       # svg rotate(a) about the part's place
    mx, my = px + tx * math.cos(a) - ty * math.sin(a), py + tx * math.sin(a) + ty * math.cos(a)
    x0, y0, w, h = (float(v) for v in re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg).groups())
    half = 2.0                                                   # the smallest mark is 4 wide
    assert x0 <= mx - half and mx + half <= x0 + w and y0 <= my - half and my + half <= y0 + h
