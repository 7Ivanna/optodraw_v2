"""CoupledRingFilter: ports and drop side, geometry, animation numbers, and the scene round trip."""

import cmath
import math
from pathlib import Path

import numpy as np
import pytest

import optodraw
from optodraw import CoupledRingFilter, MicroringResonator, Scene
from optodraw.animation_engine import compile_signal_state
from optodraw.animation_engine.behaviours.geometry import N_SILICON
from optodraw.components.onchip.rings import butterworth_power_couplings, gap_for_power_coupling, gap_power_coupling
from optodraw.schema import scene_from_spec

# the test scenes leave the bus ends open on purpose: light leaving them is expected here
pytestmark = pytest.mark.filterwarnings("ignore:.*light leaves unconnected port")


def _drop(n):
    return "o3" if n % 2 else "o4"


# ---- ports and the drop side ---------------------------------------------------------------------
@pytest.mark.parametrize("n", [1, 2, 3, 4, 8])
def test_ports_sit_at_the_bus_ends_and_the_drop_side_alternates(n):
    part = CoupledRingFilter(order=n)
    ports = part.ports()
    assert set(ports) == {"o1", "o2", "o3", "o4"}
    assert ports["o1"].center.x < 0 < ports["o2"].center.x
    assert ports["o3"].center.x < 0 < ports["o4"].center.x
    assert ports["o1"].center.y == ports["o2"].center.y < 0 < ports["o3"].center.y == ports["o4"].center.y
    assert part.drop_port == _drop(n)
    assert part.add_port == ("o4" if n % 2 else "o3")
    assert {part.drop_port, part.add_port} == {"o3", "o4"}


def test_order_one_drops_where_the_single_add_drop_ring_drops():
    single = MicroringResonator(add_drop=True)
    assert "o3" in {path["port"] for path in single.optical_paths("o1")}
    assert CoupledRingFilter(order=1).drop_port == "o3"


def test_the_order_and_the_shape_are_checked():
    for bad in (0, 9):
        with pytest.raises(ValueError, match="order"):
            CoupledRingFilter(order=bad)
    with pytest.raises(ValueError, match="ring_shape"):
        CoupledRingFilter(ring_shape="square")
    with pytest.raises(ValueError, match="gaps"):
        CoupledRingFilter(order=3, gaps=[0.2, 0.3])
    with pytest.raises(ValueError, match="power_couplings"):
        CoupledRingFilter(order=2, power_couplings=[0.1, 0.1])


def test_gaps_take_one_number_or_one_value_per_coupler():
    assert CoupledRingFilter(order=3, gaps=0.25).gaps == (0.25,) * 4
    assert CoupledRingFilter(order=2, gaps=[0.2, 0.4, 0.3]).gaps == (0.2, 0.4, 0.3)


# ---- geometry ------------------------------------------------------------------------------------
def _flat(node):
    yield node
    for child in node.get("children", []):
        yield from _flat(child)


def _y_extent(node):
    ys = [p[1] for p in node["points"]]
    return min(ys), max(ys)


@pytest.mark.parametrize("shape", ["circle", "racetrack"])
@pytest.mark.parametrize("n", [1, 2, 5])
def test_rings_stand_in_a_column_with_the_requested_gaps(n, shape):
    gaps = [0.2 + 0.05 * i for i in range(n + 1)]
    part = CoupledRingFilter(order=n, ring_shape=shape, gaps=gaps, radius=8.0, coupling_length=6.0, render_physical=True)
    shapes = list(_flat(part.geometry_2d()))
    bands = sorted((s for s in shapes if s["type"] == "polygon" and s["stroke"] == "none"), key=lambda s: _y_extent(s)[0])
    buses = sorted((s for s in shapes if s["type"] == "polygon" and s["stroke"] != "none"), key=lambda s: _y_extent(s)[0])
    assert len(bands) == n and len(buses) == 2
    w = part.waveguide_width
    measured = [_y_extent(bands[0])[0] - _y_extent(buses[0])[1]]
    measured += [_y_extent(bands[k + 1])[0] - _y_extent(bands[k])[1] for k in range(n - 1)]
    measured += [_y_extent(buses[1])[0] - _y_extent(bands[-1])[1]]
    assert measured == pytest.approx(gaps, abs=1e-9)
    assert _y_extent(bands[0])[1] - _y_extent(bands[0])[0] == pytest.approx(2 * 8.0 + w)
    port_y = part.ports()["o1"].center.y
    assert port_y == pytest.approx(sum(_y_extent(buses[0])) / 2)
    xs = [p[0] for p in bands[0]["points"]]
    expected_width = 2 * 8.0 + w + (6.0 if shape == "racetrack" else 0.0)
    assert max(xs) - min(xs) == pytest.approx(expected_width)


def test_the_3d_geometry_has_one_solid_per_ring_and_bus():
    part = CoupledRingFilter(order=3, with_heaters=True)
    solids = [s for s in _flat_3d(part.geometry_3d()) if s.get("shape") != "group"]
    assert sum(1 for s in solids if s["shape"] == "extruded_polygon" and s["material"].get("preset") == "silicon_schematic") == 3


def _flat_3d(node):
    yield node
    for child in node.get("children", []):
        yield from _flat_3d(child)


@pytest.mark.parametrize("n", [1, 2, 4])
def test_each_ring_gets_a_heater_on_alternating_sides(n):
    part = CoupledRingFilter(order=n, with_heaters=True)
    ports = part.ports()
    assert {name for name in ports if name.startswith("h")} == {f"h{k}{e}" for k in range(1, n + 1) for e in "ab"}
    for k in range(1, n + 1):
        west = ports[f"h{k}a"].center.x < 0
        assert west == (k % 2 == 1)
        assert ports[f"h{k}a"].center.y > ports[f"h{k}b"].center.y
        assert ports[f"h{k}a"].kind == "electrical"
        assert ports[f"h{k}a"].orientation_deg == (180 if west else 0)
    assert not any(name.startswith("h") for name in CoupledRingFilter(order=n).ports())


def test_drawn_and_physical_ports_agree_on_the_scale_of_the_drawing():
    part = CoupledRingFilter(order=2)
    drawn, physical = part.world_ports(), part.physical_world_ports()
    assert drawn["o1"].center.x != physical["o1"].center.x          # the schematic draws larger
    assert set(drawn) == set(physical)


# ---- the default couplings -----------------------------------------------------------------------
def test_the_gap_model_inverts():
    for gap in (0.2, 0.3, 0.6, 1.0):
        assert gap_for_power_coupling(gap_power_coupling(gap)) == pytest.approx(gap)


def test_default_gaps_give_the_butterworth_couplings():
    for n in range(1, 9):
        part = CoupledRingFilter(order=n)
        assert part.effective_power_couplings == pytest.approx(butterworth_power_couplings(n))
    two = butterworth_power_couplings(2)
    assert two[1] == pytest.approx(two[0] ** 2 / 4)                 # (g1 k)^2 / (4 g1 g2) with g1 = g2
    assert CoupledRingFilter(order=2, power_couplings=[0.2, 0.05, 0.2]).effective_power_couplings == (0.2, 0.05, 0.2)


# ---- the animation -------------------------------------------------------------------------------
def _scene(n, **kwargs):
    scene = Scene(width=300, height=400, platform="on_chip")
    part = scene.add(CoupledRingFilter(order=n, center=(0, 0), **kwargs))
    laser = scene.add(optodraw.OnChipLaser(center=(-120, part.ports()["o1"].center.y)))
    scene.route((laser, "o1"), (part, "o1"), kind="waveguide")
    return scene, part


def _resonance(part):
    length = part.round_trip_length
    m = round(N_SILICON * length / 1.55)
    return N_SILICON * length / m * 1000.0, N_SILICON * length / m / m * 1000.0      # wavelength, free spectral range in nm


def _exits(scene, wavelength, params=None):
    data = compile_signal_state(scene, mode="cw", params={"wavelength": wavelength, **(params or {})}).to_json()
    return {e["port"]: e["power"] for e in data["exits"]}


@pytest.mark.parametrize("n", [1, 2, 3])
def test_at_resonance_the_power_goes_to_the_drop_port_and_off_resonance_it_stays_in_the_bus(n):
    scene, part = _scene(n)
    centre, fsr = _resonance(part)
    on = _exits(scene, centre)
    assert on[part.drop_port] > 0.5 and on[part.drop_port] == max(on.values())
    assert on.get("o2", 0.0) < 0.05
    assert part.add_port not in on or on[part.add_port] < 1e-6
    off = _exits(scene, centre + fsr / 2)
    assert off["o2"] > 0.99 and off.get(part.drop_port, 0.0) < 0.01


def _reference(couplings, a, phi):
    """The same equations solved directly (Madsen and Zhao, ch. 5): (drop, through) power for a field in o1."""

    n = len(couplings) - 1
    t = [math.sqrt(1 - k) for k in couplings]
    c = [-1j * math.sqrt(k) for k in couplings]
    h = math.sqrt(a) * cmath.exp(0.5j * phi)
    upper, lower = list(range(n)), list(range(n, 2 * n))
    m = np.eye(2 * n, dtype=complex)
    b = np.zeros(2 * n, dtype=complex)
    m[upper[0], lower[0]] -= h * t[0]
    b[upper[0]] += h * c[0]
    m[lower[n - 1], upper[n - 1]] -= h * t[n]
    for k in range(n - 1):
        m[lower[k], upper[k]] -= h * t[k + 1]
        m[lower[k], lower[k + 1]] -= h * c[k + 1]
        m[upper[k + 1], upper[k]] -= h * c[k + 1]
        m[upper[k + 1], lower[k + 1]] -= h * t[k + 1]
    x = np.linalg.solve(m, b)
    return abs(c[n] * x[upper[n - 1]]) ** 2, abs(t[0] + c[0] * x[lower[0]]) ** 2


@pytest.mark.parametrize("n", [1, 2, 3])
def test_the_engine_matches_a_direct_solution_of_the_coupler_equations(n):
    scene, part = _scene(n, round_trip_amplitude=0.99)
    centre, fsr = _resonance(part)
    for shift in (-0.2, -0.05, 0.0, 0.03, 0.1, 0.4):
        wavelength = centre + shift * fsr
        phi = 2 * math.pi * N_SILICON * part.round_trip_length / (wavelength / 1000.0)
        drop, through = _reference(part.effective_power_couplings, 0.99, phi)
        got = _exits(scene, wavelength)
        assert got.get(part.drop_port, 0.0) == pytest.approx(drop, abs=1e-9)
        assert got.get("o2", 0.0) == pytest.approx(through, abs=1e-9)


def test_the_default_order_two_filter_has_a_flat_top():
    scene, part = _scene(2, round_trip_amplitude=1.0)
    centre, fsr = _resonance(part)
    shifts = np.linspace(-0.02, 0.02, 41)
    drop = np.array([_exits(scene, centre + s * fsr).get("o4", 0.0) for s in shifts])
    peak = drop.max()
    assert drop[20] == pytest.approx(peak, rel=1e-3)                # the maximum is at the centre: no double hump
    half = np.flatnonzero(drop > 0.5 * peak)
    width = shifts[half[-1]] - shifts[half[0]]
    assert width < 0.04                                             # the window holds the whole passband
    inner = drop[(abs(shifts) < 0.3 * width)]
    assert inner.min() > 0.85 * peak                                # flat, where one ring would be a Lorentzian
    assert np.all(np.diff(drop[20:]) <= 1e-9)                       # and it falls away monotonically


def test_the_rings_are_tuned_one_by_one_and_a_detuned_ring_blocks_the_drop():
    scene, part = _scene(2)
    centre, _ = _resonance(part)
    tuned = _exits(scene, centre)["o4"]
    detuned = _exits(scene, centre, {"phase:coupledringfilter1:ring2": math.pi})["o4"]
    assert tuned > 0.5 and detuned < 0.1 * tuned
    heated = _exits(scene, centre, {"heater:coupledringfilter1:ring1": 20.0})["o4"]     # 20 mW is pi
    assert heated < 0.1 * tuned


def test_the_power_never_exceeds_the_input():
    scene, part = _scene(3, round_trip_amplitude=0.95)
    centre, fsr = _resonance(part)
    for shift in np.linspace(0, 1, 9):
        assert sum(_exits(scene, centre + shift * fsr).values()) <= 1.0 + 1e-9


def test_light_from_the_top_bus_takes_the_reverse_path():
    # Reciprocity: for an odd order o1 -> o3, so o3 -> o1.
    scene = Scene(width=300, height=400, platform="on_chip")
    part = scene.add(CoupledRingFilter(order=3, center=(0, 0)))
    laser = scene.add(optodraw.OnChipLaser(center=(-120, part.ports()["o3"].center.y)))
    scene.route((laser, "o1"), (part, "o3"), kind="waveguide")
    centre, _ = _resonance(part)
    assert _exits(scene, centre)["o1"] > 0.5


# ---- the scene schema ----------------------------------------------------------------------------
@pytest.mark.parametrize("kwargs", [
    {"order": 2},
    {"order": 5, "ring_shape": "racetrack", "coupling_length": 8.0, "radius": 12.0},
    {"order": 3, "gaps": [0.2, 0.5, 0.6, 0.25], "with_heaters": True, "waveguide_width": 0.45},
    {"order": 4, "power_couplings": [0.1, 0.01, 0.005, 0.01, 0.1], "round_trip_amplitude": 0.97},
])
def test_the_part_survives_the_scene_round_trip(kwargs):
    scene = Scene(width=300, height=300, platform="on_chip")
    scene.add(CoupledRingFilter(center=(10, 20), label="F", **kwargs))
    rebuilt = scene_from_spec(scene.to_spec())
    (part,) = [n for n in rebuilt.walk() if isinstance(n, CoupledRingFilter)]
    original = next(n for n in scene.walk() if isinstance(n, CoupledRingFilter))
    for key in ("order", "ring_shape", "radius", "coupling_length", "gaps", "waveguide_width", "with_heaters",
                "round_trip_amplitude", "effective_power_couplings"):
        assert getattr(part, key) == pytest.approx(getattr(original, key))
    assert part.drop_port == original.drop_port
    assert set(part.ports()) == set(original.ports())


def test_the_part_is_in_the_catalog_and_has_one_symbol_row_per_order():
    from optodraw.catalog import describe_component, list_components

    assert "CoupledRingFilter" in list_components(platform="on_chip")
    assert describe_component("CoupledRingFilter")["description"]
    table = (Path(optodraw.__file__).parent / "symbols" / "variants.toml").read_text(encoding="utf-8")
    for n in range(1, 6):
        assert f'params = {{ order = {n} }}\ncomponent = "CoupledRingFilter"' in table
    assert CoupledRingFilter(order=3).symbol_1d() == ("coupledring", {"order": 3})
    assert CoupledRingFilter(order=2, with_heaters=True).symbol_1d() == ("coupledring", {"order": 2, "heater": True})
