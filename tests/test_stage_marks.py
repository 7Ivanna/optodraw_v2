"""A part on a stage shows a small motion mark in 2D, not a stage drawing; the stage itself is a 3D mount."""

from __future__ import annotations



from optodraw import Scene


def _svg(part):
    scene = Scene(title="stage", width=80, height=60, platform="free_space")
    scene.add(part)
    return scene.render_svg().as_svg()


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


