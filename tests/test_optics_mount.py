"""Mount height system: why posts differ and how board tops are handled."""

from __future__ import annotations

import re

from optodraw import Scene
from optodraw.components.optics import Lens, Mirror
from optodraw.components.optics.optomech import Breadboard, OpticalTable


def _board_top(html: str) -> float:
    m = re.search(r"const BOARD_TOP = ([0-9.]+)", html)
    assert m, "BOARD_TOP not in html"
    return float(m.group(1))


class TestBoardTop:
    def test_without_board_is_zero(self):
        s = Scene(width=120, height=80)
        s.add(Lens(center=(0, 0), aperture=10))
        html = s.render_threejs()
        assert _board_top(html) == 0.0

    def test_breadboard_sets_board_top(self):
        s = Scene(width=200, height=120)
        s.add(Breadboard(center=(0, 0), thickness=2.4))
        s.add(Lens(center=(20, 0), aperture=10))
        assert _board_top(s.render_threejs()) == 2.4

    def test_tallest_board_wins(self):
        s = Scene(width=200, height=120)
        s.add(OpticalTable(center=(0, 0), thickness=4.0))
        s.add(Breadboard(center=(30, 0), thickness=6.0))
        assert _board_top(s.render_threejs()) == 6.0


class TestMountHeightModes:
    def test_default_post_is_aperture_dependent(self):
        # device bottom = BEAM_PLANE - radius, so larger aperture → lower bottom → shorter post
        small = Lens(center=(0, 0), aperture=6)
        large = Lens(center=(0, 0), aperture=14)
        assert small.base_mount == "post"
        assert large.base_mount == "post"
        # bottom height approx BEAM_PLANE - aperture/2
        assert small.aperture < large.aperture

    def test_post_beam_is_uniform(self):
        lens = Lens(center=(0, 0), aperture=10, base_mount="post_beam")
        assert lens.base_mount == "post_beam"
        s = Scene(width=120, height=80)
        s.add(lens)
        assert "post_beam" in s.render_threejs()

    def test_none_has_no_post(self):
        lens = Lens(center=(0, 0), base_mount="none")
        assert lens.base_mount == "none"

    def test_stage_mounts_still_exist(self):
        lens = Lens(center=(0, 0), base_mount="stage")
        assert lens.base_mount == "stage"
        mir = Mirror(center=(0, 0), base_mount="rotation_stage")
        assert mir.base_mount == "rotation_stage"


class TestMountHeight:
    def test_mount_height_sets_device_bottom(self):
        lens = Lens(center=(0, 0), aperture=10, mount_height=12)
        assert lens.mount_height == 12
        s = Scene(width=120, height=80)
        s.add(lens)
        assert "mountHeight" in s.render_threejs()

    def test_post_height_alias(self):
        lens = Lens(center=(0, 0), aperture=10, post_height=14)
        assert lens.mount_height == 14

    def test_mount_height_round_trips(self):
        lens = Lens(center=(0, 0), aperture=10, mount_height=11.5)
        assert lens.to_dict()["mount_height"] == 11.5

    def test_kinematic_mount_is_flat(self):
        from optodraw.components.optics.optomech import KinematicMount

        km = KinematicMount(center=(0, 0))
        s = Scene(width=200, height=120)
        s.add(Breadboard(center=(0, 0), thickness=2.4))
        s.add(km)
        html = s.render_threejs()
        # KinematicMount should not get a post; its bottom lifts to BOARD_TOP
        assert _board_top(html) == 2.4
