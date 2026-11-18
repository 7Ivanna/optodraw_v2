"""The checks an agent runs on its own parts and scenes before it calls them done."""

from __future__ import annotations

import math

from optodraw import Component, Port, Transform, check_part_3d
from optodraw.core import Vec3


class _Part(Component):
    """A test part whose 3D solids are given directly."""

    def __init__(self, solids, post_at=None, base_mount="post"):
        super().__init__(label="part", base_mount=base_mount)
        self.transform = Transform.from_2d(0.0, 0.0, 0.0)
        self._geo = {"shape": "group", "children": solids}
        if post_at is not None:
            self._geo["post_at"] = post_at

    def ports(self):
        return {"in": Port("in", Vec3(-1, 0, 0), orientation_deg=180, kind="free_space")}

    def geometry_3d(self):
        return self._geo


_RING = {"shape": "cylinder", "radius": 5.0, "height": 2.0, "rotation": [0.0, 0.0, math.pi / 2], "position": [0, 0, 0]}
_BOSS = {"shape": "box", "width": 2.0, "height": 1.2, "depth": 4.0, "position": [0, -5.0, 0]}


def test_a_well_built_part_has_no_findings():
    assert check_part_3d(_Part([_RING, _BOSS], post_at=[0.0, -5.6, 0.0])) == []


def test_a_solid_that_touches_nothing_is_found():
    knob = {"shape": "sphere", "radius": 0.5, "position": [0, 12.0, 0], "role": "knob"}
    findings = check_part_3d(_Part([_RING, _BOSS, knob], post_at=[0.0, -5.6, 0.0]))
    assert any("touches nothing" in f and "knob" in f for f in findings)


def test_a_post_under_a_round_rim_is_found():
    findings = check_part_3d(_Part([_RING], post_at=[0.0, -5.0, 0.0]))
    assert any("flat face" in f for f in findings)


def test_a_post_inside_its_boss_is_found():
    findings = check_part_3d(_Part([_RING, _BOSS], post_at=[0.0, -5.5, 0.0]))
    assert any("flat face" in f for f in findings)


def test_a_part_that_stands_on_the_table_needs_no_post():
    assert check_part_3d(_Part([_RING], base_mount="none")) == []


def test_every_part_keeps_the_label_side_it_is_given():
    """A constructor that dropped label_side left the label on the beam, whatever the caller asked."""

    import warnings

    from optodraw.registry import component_registry, get_component_class

    dropped = []
    for name, spec in sorted(component_registry().items()):
        if not spec.creatable:
            continue
        cls = get_component_class(name)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                part = cls(label="x", label_side="right")
        except Exception:
            continue
        if getattr(part, "label_side", "top") != "right":
            dropped.append(name)
    assert not dropped, f"{len(dropped)} parts drop label_side: {dropped[:12]}"


def test_both_renderers_take_both_view_keywords(tmp_path):
    """render_svg took onchip_view= and render_tikz took view=; each ignored the other and drew 2D."""

    import pytest

    from optodraw import Laser, Lens, Scene

    scene = Scene(title="v", width=80, height=30, platform="free_space")
    scene.add(Laser(center=(-20, 0), label="L"))
    scene.add(Lens(center=(10, 0), label="f"))
    one_d = scene.render_svg(onchip_view="1d").as_svg()
    assert scene.render_svg(view="1d").as_svg() == one_d
    assert scene.render_tikz(onchip_view="1d") == scene.render_tikz(view="1d")
    with pytest.raises(ValueError):
        scene.render_svg(view="1d", onchip_view="2d")


def test_register_refuses_a_name_the_catalog_already_has(monkeypatch):
    """register("AOM", MyClass) silently replaced the built-in AOM for the whole process."""

    import pytest

    from optodraw import registry

    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))

    class MyAOM(registry.get_component_class("AOM")):
        pass

    with pytest.raises(ValueError, match="AOM"):
        registry.register("AOM", MyAOM, category="optics", platform="free_space", description="mine", parameters=[])
    registry.register("AOM", MyAOM, category="optics", platform="free_space", description="mine", parameters=[],
                      replace=True)
    assert registry.get_component_class("AOM") is MyAOM


def test_a_chip_part_is_not_checked_like_a_part_on_a_post():
    """A chip part's films sit in its layer stack with cladding between them, on a die the scene draws: it has
    no post, and a heater above the oxide does not hang in the air."""

    import pytest

    from optodraw import MZM, DirectionalCoupler, MicroringResonator, MicroringWeightBank, OnChipPhotodetector

    for part in (MicroringResonator(with_heater=True), MZM(), DirectionalCoupler(), OnChipPhotodetector(),
                 MicroringWeightBank(ring_count=2, with_heaters=True)):
        assert check_part_3d(part) == [], type(part).__name__
    with pytest.raises(AssertionError):
        assert check_part_3d(_floating_mirror()) == []


def _floating_mirror():
    from optodraw import Mirror

    class Floating(Mirror):
        def geometry_3d(self):
            geo = super().geometry_3d()
            return {"shape": "group", "children": [geo, {"shape": "box", "width": 1, "height": 1, "depth": 1,
                                                          "position": [50, 50, 50]}]}

    return Floating()
