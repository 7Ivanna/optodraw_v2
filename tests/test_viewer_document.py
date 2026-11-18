"""The notebook viewer builds its page: 2D always, 3D when asked, and the 1D tab."""

from __future__ import annotations

import pytest

import optodraw
from optodraw.presets import PRESETS, build_preset


def _scene() -> optodraw.Scene:
    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    a = scene.add(optodraw.Waveguide(center=(-40, 0), label="in"))
    b = scene.add(optodraw.MicroringResonator(center=(40, 0), label="ring"))
    scene.route((a, "o2"), (b, "o1"), kind="waveguide")
    return scene


@pytest.mark.parametrize("show_3d", [True, False])
def test_the_viewer_document_builds(show_3d):
    """scene.preview() used to raise: the 1D tab looked for a tag the page writes differently."""

    document = _scene().preview(show_3d=show_3d).document()
    assert document.index('id="b1"') < document.index('id="b2"')       # the 1D tab comes first
    assert document.index('id="d1"') < document.index('id="d2"')       # and its pane sits before the 2D pane
    assert ('id="b3"' in document) is show_3d
    pane = document[document.index('id="d1"'):document.index('id="d2"')]
    assert "<svg" in pane and "</svg>" in pane                        # the 1D drawing is in its pane


def test_the_viewer_shows_in_a_notebook():
    html = _scene().preview(show_3d=False)._repr_html_()
    assert html.startswith("<iframe") and "srcdoc=" in html


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_every_preset_draws_and_opens_in_the_viewer(name):
    """The FTIR preset once anchored a beam on a port its sample had lost. Nothing drew it, so no test saw it."""

    scene = build_preset(name)
    assert "<svg" in scene.render_svg().as_svg()
    assert 'id="d2"' in scene.preview(show_3d=False).document()
