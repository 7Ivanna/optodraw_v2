"""Export to SAX: SAX runs the exported netlist and gives the spectrum that optodraw computes, to 1e-9."""

from pathlib import Path

import numpy as np
import pytest

import optodraw
from optodraw.animation_engine import spectrum
from optodraw.animation_engine.ids import scene_ids
from optodraw.sax_export import to_sax
from optodraw.sparameters import SParameters

sax = pytest.importorskip("sax")
jax = pytest.importorskip("jax")
jax.config.update("jax_enable_x64", True)            # JAX computes in float32 by default; optodraw in float64

COUPLER = Path(__file__).resolve().parents[1] / "docs" / "examples" / "models" / "data" / "coupler_fieldrt.npz"


def _sax_power(scene, wavelengths_nm):
    """The exported circuit, and |S(in, out)|^2 from SAX for a (source part, port) and a (detector part, port)."""

    exported = to_sax(scene, wavelengths_nm=wavelengths_nm)
    circuit, _ = sax.circuit(exported.netlist, exported.models)
    s = circuit(wl=np.asarray(wavelengths_nm) / 1000.0)
    ids = scene_ids(scene)

    def power(source, detector):
        into, out = (next(name for name, end in exported.ports.items() if end == f"{ids[id(part)]}:{port}")
                     for part, port in (source, detector))
        return np.abs(np.asarray(s[(into, out)])) ** 2

    return exported, power


def test_the_imported_mzi_in_sax_equals_its_spectrum():
    # the MZI of docs/examples/models/03-imported-mzi.py: two fieldrt couplers with every table entry, reflections too
    table = SParameters.load(COUPLER)
    mzi = optodraw.Scene(platform="on_chip")
    laser = mzi.add(optodraw.OnChipLaser(center=(-120, 7)))
    split = mzi.add(optodraw.DirectionalCoupler(center=(0, 0)))
    join = mzi.add(optodraw.DirectionalCoupler(center=(150, 0)))
    split.model = join.model = table
    bar = mzi.add(optodraw.OnChipPhotodetector(center=(270, 30)))
    cross = mzi.add(optodraw.OnChipPhotodetector(center=(270, -30)))
    mzi.route((laser, "o1"), (split, "o1"), kind="waveguide")
    mzi.route((split, "o3"), (join, "o1"), kind="waveguide")
    mzi.route((split, "o4"), (join, "o2"), kind="waveguide", path_type="manhattan", steps=[{"y": -17.0}])
    mzi.route((join, "o3"), (bar, "o1"), kind="waveguide", path_type="smooth")
    mzi.route((join, "o4"), (cross, "o1"), kind="waveguide", path_type="smooth")
    grid = np.linspace(1500.0, 1600.0, 201)
    exported, power = _sax_power(mzi, grid)
    ids = scene_ids(mzi)
    components = [instance["component"] for instance in exported.netlist["instances"].values()]
    assert components.count("straight") == 5
    assert sorted(c for c in components if c != "straight") == sorted([ids[id(split)], ids[id(join)]])
    assert sorted(exported.ports.values()) == sorted(f"{ids[id(part)]}:o1" for part in (laser, bar, cross))
    m = spectrum(mzi, start_nm=1500, stop_nm=1600, points=201)
    for detector in (bar, cross):
        assert np.max(np.abs(power((laser, "o1"), (detector, "o1")) - m.of(detector, "o1"))) < 1e-9
    assert np.ptp(m.of(bar, "o1")) > 0.5                                       # the arms differ: fringes


def test_a_link_has_the_solver_phase():
    from optodraw.animation_engine.solver import phase_factor
    from optodraw.sax_export import straight

    s = straight(wl=1.55, length=37.5, group_index=4.2)                       # um, as SAX
    assert abs(s[("o1", "o2")] - phase_factor(37.5, 4.2, 1550.0)) < 1e-12
    assert abs(s[("o2", "o1")] - phase_factor(37.5, 4.2, 1550.0)) < 1e-12


def test_one_way_and_absorbing_parts_stop_the_light_in_sax():
    # SAX keys run (in, out) and optodraw tables (out, in): an isolator mounted backwards must stay dark in SAX.
    # A cryostat with its sample absorbs at every window, although its behaviour also has a transfer through it.
    scene = optodraw.Scene(width=300, height=240, platform="free_space")
    laser_a = scene.add(optodraw.Laser(center=(-60, 80)))
    forward = scene.add(optodraw.OpticalIsolator(center=(0, 80)))
    pd_a = scene.add(optodraw.Photodiode(center=(60, 80)))
    laser_b = scene.add(optodraw.Laser(center=(-60, 0)))
    backward = scene.add(optodraw.OpticalIsolator(center=(0, 0), angle=180))
    pd_b = scene.add(optodraw.Photodiode(center=(60, 0)))
    laser_c = scene.add(optodraw.Laser(center=(-60, -80)))
    cryostat = scene.add(optodraw.Cryostat(center=(0, -80)))
    pd_c = scene.add(optodraw.Photodiode(center=(60, -80)))
    scene.add(optodraw.Beam((laser_a, "out"), (forward, "in")))
    scene.add(optodraw.Beam((forward, "out"), (pd_a, "in")))
    scene.add(optodraw.Beam((laser_b, "out"), (backward, "out")))
    scene.add(optodraw.Beam((backward, "in"), (pd_b, "in")))
    scene.add(optodraw.Beam((laser_c, "out"), (cryostat, "in")))
    scene.add(optodraw.Beam((cryostat, "out"), (pd_c, "in")))
    grid = np.linspace(600.0, 700.0, 11)
    _, power = _sax_power(scene, grid)
    s = spectrum(scene, start_nm=600, stop_nm=700, points=11)
    assert np.max(np.abs(power((laser_a, "out"), (pd_a, "in")) - s.of(pd_a, "in"))) < 1e-9
    assert np.min(s.of(pd_a, "in")) > 0.5
    ids = scene_ids(scene)
    for laser, pd in ((laser_b, pd_b), (laser_c, pd_c)):
        assert f"{ids[id(pd)]}:in" not in s.power                              # optodraw: no light reaches it
        assert np.max(power((laser, "out"), (pd, "in"))) < 1e-20
