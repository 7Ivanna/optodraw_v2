"""Mount height system: why posts differ and how board tops are handled."""

from __future__ import annotations

import re

from optodraw import Scene
from optodraw.components.optics import Lens
from optodraw.components.optics.optomech import Breadboard


def _board_top(html: str) -> float:
    m = re.search(r"const BOARD_TOP = ([0-9.]+)", html)
    assert m, "BOARD_TOP not in html"
    return float(m.group(1))


class TestMountHeight:
    def test_mount_height_sets_device_bottom(self):
        lens = Lens(center=(0, 0), aperture=10, mount_height=12)
        assert lens.mount_height == 12
        s = Scene(width=120, height=80)
        s.add(lens)
        assert "mountHeight" in s.render_threejs()


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
