"""CoupledRingFilter: ports and drop side, geometry, animation numbers, and the scene round trip."""


import pytest

import optodraw
from optodraw import CoupledRingFilter, Scene
from optodraw.animation_engine import compile_signal_state
from optodraw.animation_engine.behaviours.geometry import N_SILICON
from optodraw.components.onchip.rings import butterworth_power_couplings

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


def test_drawn_and_physical_ports_agree_on_the_scale_of_the_drawing():
    part = CoupledRingFilter(order=2)
    drawn, physical = part.world_ports(), part.physical_world_ports()
    assert drawn["o1"].center.x != physical["o1"].center.x          # the schematic draws larger
    assert set(drawn) == set(physical)


# ---- the default couplings -----------------------------------------------------------------------


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


def test_light_from_the_top_bus_takes_the_reverse_path():
    # Reciprocity: for an odd order o1 -> o3, so o3 -> o1.
    scene = Scene(width=300, height=400, platform="on_chip")
    part = scene.add(CoupledRingFilter(order=3, center=(0, 0)))
    laser = scene.add(optodraw.OnChipLaser(center=(-120, part.ports()["o3"].center.y)))
    scene.route((laser, "o1"), (part, "o3"), kind="waveguide")
    centre, _ = _resonance(part)
    assert _exits(scene, centre)["o1"] > 0.5


# ---- the scene schema ----------------------------------------------------------------------------


