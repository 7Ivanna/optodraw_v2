"""The notebook viewer builds its page: 2D always, 3D when asked, and the 1D tab."""

from __future__ import annotations


import optodraw


def _scene() -> optodraw.Scene:
    scene = optodraw.Scene(width=200, height=80, platform="on_chip")
    a = scene.add(optodraw.Waveguide(center=(-40, 0), label="in"))
    b = scene.add(optodraw.MicroringResonator(center=(40, 0), label="ring"))
    scene.route((a, "o2"), (b, "o1"), kind="waveguide")
    return scene


def test_the_viewer_shows_in_a_notebook():
    html = _scene().preview(show_3d=False)._repr_html_()
    assert html.startswith("<iframe") and "srcdoc=" in html


