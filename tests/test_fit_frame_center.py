"""fit_frame frames the content where it is: a drawing far from the origin gets a frame its own size."""

from __future__ import annotations


from optodraw import Lens, Scene


def test_fit_frame_holds_a_long_label_at_the_edge():
    """A long label on the outer side of the last part must not run past the frame."""

    from optodraw import check_figure

    scene = Scene(title="", width=50, height=50, platform="free_space")
    scene.add(Lens(center=(0, 0), label="L1"))
    scene.add(Lens(center=(20, 0), label="A very long objective label", label_side="right"))
    scene.fit_frame(margin=4)
    assert not [f for f in check_figure(scene, view="2d") if "cut off by the frame" in f]
