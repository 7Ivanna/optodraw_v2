"""The arrayed waveguides must form a real ladder, not just a rising bundle.

A phased array is a grating because every arm is longer than the last by the
SAME amount. That constant increment sets the dispersion and the free spectral
range. The arms used to be drawn by pushing Bezier control points a fixed step
per arm, which is not the same thing: the step is not the arc length, and the
no-knot cap bound the short inner arms hardest, so the increments came out
between 1.6 and 26.3 um. Monotonic, and nothing more.

A monotonic-but-arbitrary ladder is the worst state to be in: it looks like a
designed grating and is not one, which is how somebody ends up reading a
dispersion off a picture.
"""

from __future__ import annotations

import math
import warnings

import pytest

from optodraw.components.onchip.system import AWGR


def _arm_lengths(awgr: AWGR) -> list[float]:
    *_, arms = awgr._awgr_layout()
    return [sum(math.dist(p, q) for p, q in zip(arm, arm[1:])) for arm in arms]


def _build(**kwargs) -> AWGR:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # geometry clamps warn by design
        return AWGR(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {},
    {"array_count": 8},
    {"array_count": 24},
    {"array_height": 100.0},
    {"fpr_length": 50.0, "fpr_separation": 200.0},
])
def test_the_delay_increment_is_constant(kwargs):
    lengths = _arm_lengths(_build(**kwargs))
    steps = [b - a for a, b in zip(lengths, lengths[1:])]
    assert steps, "an array needs more than one arm"
    assert max(steps) - min(steps) < 1e-6, (
        f"increments run {min(steps):.3f} to {max(steps):.3f}: that is a bundle, not a grating"
    )
    assert min(steps) > 0.0


def test_array_height_asks_for_the_total_delay_spread():
    """The parameter has to mean something, and it does: the total spread,
    honoured whenever the arms can nest at that step.

    Nesting outranks it. Arms already differ in length at the lowest arch that
    clears their apertures, and a step below that difference can only be met by
    pulling the outer arms down under their neighbours, which is a drawing of
    crossing arrayed waveguides. So a request under the floor is clamped, and
    says so."""

    for height in (200.0, 300.0):        # clear of the nesting floor
        lengths = _arm_lengths(_build(array_height=height))
        assert lengths[-1] - lengths[0] == pytest.approx(height, abs=1e-6)


def test_a_spread_too_small_to_nest_is_clamped_and_warns():
    with pytest.warns(UserWarning, match="arms have to cross"):
        awgr = AWGR(array_height=20.0)
        lengths = _arm_lengths(awgr)
    assert lengths[-1] - lengths[0] > 20.0
    steps = [b - a for a, b in zip(lengths, lengths[1:])]
    assert max(steps) - min(steps) < 1e-6      # still a constant ladder


def test_arms_reach_their_apertures_exactly():
    awgr = _build()
    *_, arr_in, arr_out, _dummy_in, _dummy_out, arms = awgr._awgr_layout()
    tips = [a["tip"] for a in arr_in] + [a["tip"] for a in arr_out]
    worst = max(min(math.dist(end, tip) for tip in tips)
                for arm in arms for end in (arm[0], arm[-1]))
    assert worst < 1e-9, f"arms float {worst:.4f} um off their aperture tips"


def test_no_arm_doubles_back_on_itself():
    """x monotonic per arm is the cheap proof that nothing knots or crosses."""

    for arm in _build()._awgr_layout()[-1]:
        xs = [p[0] for p in arm]
        rising = all(b >= a - 1e-9 for a, b in zip(xs, xs[1:]))
        falling = all(b <= a + 1e-9 for a, b in zip(xs, xs[1:]))
        assert rising or falling


class TestArmsNestAndDoNotCross:
    """The picture of an AWG is nested arms: evenly spaced, one peak, nothing
    touching. Solving each arm's arch height independently for a length target
    let an inner arm arch OVER an outer one, which crossed 14 arm pairs on the
    router at the parameters a real chip was using."""

    @staticmethod
    def _crossing_pairs(arms) -> int:
        def side(p, q, r):
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        def crosses(a, b, c, d):
            d1, d2, d3, d4 = side(c, d, a), side(c, d, b), side(a, b, c), side(a, b, d)
            return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))

        return sum(
            1
            for i in range(len(arms))
            for j in range(i + 1, len(arms))
            if any(crosses(*x, *y)
                   for x in zip(arms[i], arms[i][1:])
                   for y in zip(arms[j], arms[j][1:]))
        )

    @pytest.mark.parametrize("kwargs", [
        {},
        {"array_count": 24},
        {"array_height": 20.0},                       # below the nesting floor
        {"array_count": 16, "channel_count": 4, "channel_spacing": 7.5,
         "fpr_length": 36.0, "array_height": 65.0, "tilt_deg": 45.0},   # a real chip
    ])
    def test_no_two_arms_cross(self, kwargs):
        arms = _build(**kwargs)._awgr_layout()[-1]
        assert self._crossing_pairs(arms) == 0

    def test_the_arches_are_ordered_outward(self):
        arms = _build()._awgr_layout()[-1]
        apexes = [max(point[1] for point in arm) for arm in arms]
        assert apexes == sorted(apexes), "arm k must arch over arm k-1, or they cross"

    def test_the_awg_arms_nest_too(self):
        from optodraw import AWG

        arms = AWG(channel_count=4, array_count=10, channel_spacing=7.0,
                   slab_length=16.0, slab_width=26.0, array_length=30.0)._awg_layout()[4]
        assert self._crossing_pairs(arms) == 0
