import pytest

from optodraw.animation_engine import primitives as p


@pytest.mark.parametrize("action, kind", [
    (lambda: p.Create("part:laser1"), "Create"),
    (lambda: p.FadeIn("part:laser1"), "FadeIn"),
    (lambda: p.FadeOut("part:laser1"), "FadeOut"),
    (lambda: p.Indicate("part:laser1"), "Indicate"),
    (lambda: p.Dim("part:laser1"), "Dim"),
    (lambda: p.Label("part:laser1", "source"), "Label"),
    (lambda: p.Arrow((0, 0), (1, 1)), "Arrow"),
    (lambda: p.Write(r"T(\lambda)", near="part:ring1"), "Write"),
    (lambda: p.Transform("text:1", "text:2"), "Transform"),
    (lambda: p.MoveAlong("text:1", "route:route1"), "MoveAlong"),
    (lambda: p.Flow(paths=["route:route1"], style="photons"), "Flow"),
    (lambda: p.Zoom("part:ring1"), "Zoom"),
    (lambda: p.Pan((10, -5)), "Pan"),
    (lambda: p.Fit(), "Fit"),
    (lambda: p.Morph(to="1d"), "Morph"),
    (lambda: p.Set("wavelength", 1550.0), "Set"),
    (lambda: p.Sweep("wavelength", 1549, 1551, seconds=4), "Sweep"),
    (lambda: p.Plot(p.Quantity("route:route1"), against="wavelength"), "Plot"),
    (lambda: p.Wait(1), "Wait"),
    (lambda: p.Click(), "Click"),
])
def test_each_spec_primitive_has_a_data_descriptor(action, kind):
    assert action().type == kind


def test_invalid_sweeps_views_and_easing_are_rejected():
    with pytest.raises(ValueError, match="samples"):
        p.Sweep("wavelength", 1549, 1551, seconds=4, samples=1)
    with pytest.raises(ValueError, match="seconds"):
        p.Sweep("wavelength", 1549, 1551, seconds=0)
    with pytest.raises(ValueError, match="view"):
        p.Morph(to="3d")
    with pytest.raises(ValueError, match="easing"):
        p.Indicate("part:laser1", easing="unknown")


@pytest.mark.parametrize("name", p.EASINGS)
def test_easing_endpoints_are_explicit(name):
    assert p.ease(name, 0.0) == 0.0
    assert p.ease(name, 1.0) == (0.0 if name == "there_and_back" else 1.0)
    assert 0.0 <= p.ease(name, 0.3) <= 1.0
