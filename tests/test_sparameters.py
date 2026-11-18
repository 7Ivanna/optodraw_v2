"""Imported S-parameter tables: the readers, their checks and the model slot.

The test code writes its own fixtures (a lossless delay line as SAX npz and as Touchstone .s2p) into tmp_path.
"""

import cmath
import math
from pathlib import Path

import numpy as np
import pytest

import optodraw
from optodraw.animation_engine import AnimationError
from optodraw.animation_engine.behaviours.tabulated import TabulatedBehaviour
from optodraw.animation_engine.ids import scene_ids
from optodraw.animation_engine.parameters import compile_sweep
from optodraw.provenance import Source
from optodraw.sparameters import SParameters, check

N_DELAY, L_DELAY = 2.5, 10.0                        # the fixtures' delay line: group index and length (um)
GRID_NM = np.linspace(1500.0, 1600.0, 101)          # 1 nm steps


# --- Fixtures, written by the test itself -------------------------------------------------------------------------

def _expected(wavelength_nm):
    """The delay line's S21 in optodraw's (and SAX's) exp(-i omega t) convention: exp(+i 2 pi n L / lambda)."""

    return np.exp(2j * np.pi * N_DELAY * L_DELAY / (np.asarray(wavelength_nm) / 1000.0))


def _delay_matrix():
    matrix = np.zeros((GRID_NM.size, 2, 2), dtype=complex)        # [wavelength, out, in]
    matrix[:, 1, 0] = matrix[:, 0, 1] = _expected(GRID_NM)
    return matrix


def _write_npz(path, matrix):
    """The layout optodraw reads: the fieldrt.sax.sdict keys (out, in) joined by a comma; wavelengths in um."""

    names = ("o1@0", "o2@0")
    np.savez(path, wavelengths_um=GRID_NM / 1000.0,
             **{f"{names[i]},{names[j]}": matrix[:, i, j] for i in range(2) for j in range(2)})


def _write_s2p(path, matrix, form="RI", unit="HZ"):
    """Touchstone 1 in the RF convention exp(+j omega t), so the conjugate; frequency ascending; S11 S21 S12 S22."""

    hz = 299792458.0 / (GRID_NM * 1e-9)
    lines = ["! written by tests/test_sparameters.py", f"# {unit} S {form} R 50"]
    for k in np.argsort(hz):
        row = [hz[k] / {"HZ": 1.0, "GHZ": 1e9}[unit]]
        for i, j in ((0, 0), (1, 0), (0, 1), (1, 1)):
            value = complex(np.conj(matrix[k, i, j]))
            if form == "RI":
                row += [value.real, value.imag]
            else:
                size = abs(value) if form == "MA" else 20.0 * math.log10(abs(value))
                row += [size, math.degrees(cmath.phase(value))]
        lines.append(" ".join(f"{x:.17g}" for x in row))
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def delay_line(tmp_path):
    npz, s2p = tmp_path / "delay.npz", tmp_path / "delay.s2p"
    _write_npz(npz, _delay_matrix())
    _write_s2p(s2p, _delay_matrix())
    return npz, s2p


def _guide_scene():
    """A laser, a waveguide and a detector on a chip."""

    scene = optodraw.Scene(width=300, height=80, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    guide = scene.add(optodraw.Waveguide(center=(0, 0)))
    pd = scene.add(optodraw.OnChipPhotodetector(center=(120, 0)))
    scene.route((laser, "o1"), (guide, "o1"), kind="waveguide")
    scene.route((guide, "o2"), (pd, "o1"), kind="waveguide")
    return scene, guide, pd


# --- The tests ----------------------------------------------------------------------------------------------------

def test_a_lossless_delay_line_keeps_its_sign_from_both_formats(delay_line):
    # the generator writes S21 = exp(+i 2 pi n L / lambda) (SAX sign) to npz, and its conjugate to .s2p
    npz, s2p = delay_line
    for path, ports in ((npz, {"o1": "in", "o2": "out"}), (s2p, {"1": "in", "2": "out"})):
        sp = SParameters.load(path, ports=ports)
        assert np.allclose(np.angle(sp.at(1550.0)[("out", "in")]), np.angle(_expected(1550.0)), atol=1e-9)
        assert set(sp.s) == {("out", "in"), ("in", "out")}                  # the zero reflections are dropped


@pytest.mark.parametrize("form, unit", [("RI", "GHZ"), ("MA", "HZ"), ("DB", "GHZ")])
def test_touchstone_formats_units_and_port_order(tmp_path, form, unit):
    magnitudes = np.array([[0.1, 0.5], [0.9, 0.2]])                        # [out, in]: S21 is not S12
    path = tmp_path / "pair.s2p"
    _write_s2p(path, magnitudes * _expected(GRID_NM)[:, None, None], form, unit)
    s = SParameters.load(path).at(1550.0)
    for i, j in ((0, 0), (1, 0), (0, 1), (1, 1)):
        assert abs(s[(str(i + 1), str(j + 1))] - magnitudes[i, j] * _expected(1550.0)) < 1e-9


def test_tm_entries_are_dropped_and_a_port_map_typo_is_refused(tmp_path):
    path = tmp_path / "two_modes.npz"
    te = _expected(GRID_NM)
    np.savez(path, wavelengths_um=GRID_NM / 1000.0, **{"o2@0,o1@0": te, "o2@1,o1@1": 0.5 * te, "o2@1,o1@0": 0.1 * te})
    assert set(SParameters.load(path).s) == {("o2", "o1")}
    with pytest.raises(ValueError, match="o3"):
        SParameters.load(path, ports={"o3": "in"})


def test_unmapped_touchstone_ports_name_both_sides(delay_line):
    sp = SParameters.load(delay_line[1])                                    # ports "1" and "2", no map
    with pytest.raises(AnimationError, match=r"1, 2 .*in, out"):
        check(sp, optodraw.Lens())


def test_a_gain_table_is_refused():
    def table(gain):
        return SParameters(GRID_NM, {("o2", "o1"): gain * _expected(GRID_NM)}, Source("model"))

    guide = optodraw.Waveguide()
    with pytest.raises(AnimationError, match=r"more power .*1\.1 at"):
        check(table(1.1), guide)
    check(table(1.000001), guide)                                           # no error
    assert any("1.01" in warning for warning in check(table(1.01), guide))  # a warning
    assert check(table(1.0), guide) == []


def test_a_wavelength_outside_the_table_is_refused(delay_line):
    from optodraw.animation_engine import spectrum

    scene, guide, _ = _guide_scene()
    guide.model = SParameters.load(delay_line[0])
    sid = scene_ids(scene)[id(guide)]
    refused = rf"^{sid}: .*outside the imported table, 1500 to 1600 nm"
    with pytest.raises(AnimationError, match=refused):
        spectrum(scene, start_nm=1600, stop_nm=1650, points=6)
    with pytest.raises(AnimationError, match=refused):
        compile_sweep(scene, "wavelength", [1590.0, 1610.0])              # an animation's wavelength sweep


def test_a_coarse_table_warns_at_the_resonance():
    n, a, r = 4.2, 0.99, math.sqrt(1 - 0.1)
    loop = 170 * 1.55 / n                                                   # a resonance at 1550 nm exactly

    def ring(grid):
        e = np.exp(2j * np.pi * n * loop / (grid / 1000.0))
        through = (r - a * e) / (1 - r * a * e)
        return SParameters(grid, {("o2", "o1"): through, ("o1", "o2"): through}, Source("model"))

    coarse = check(ring(np.linspace(1545.0, 1555.0, 11)), optodraw.Waveguide())           # 1 nm steps
    assert any("1550" in w and " nm " in w and "coarse" in w for w in coarse)
    assert check(ring(np.linspace(1545.0, 1555.0, 1001)), optodraw.Waveguide()) == []     # 0.01 nm steps


def test_the_model_slot_replaces_the_part_behaviour():
    from optodraw.animation_engine import spectrum

    scene, guide, pd = _guide_scene()
    amplitude = np.sqrt(0.5 + 0.4 * np.sin(2 * np.pi * (GRID_NM - 1500.0) / 20.0))
    s21 = amplitude * _expected(GRID_NM)
    guide.model = SParameters(GRID_NM, {("o2", "o1"): s21, ("o1", "o2"): s21}, Source("model"))
    s = spectrum(scene, start_nm=1540, stop_nm=1560, points=21)              # the table's own wavelengths
    sid = scene_ids(scene)[id(pd)]
    seen = sum(power for key, power in s.power.items() if key.startswith(f"{sid}:"))
    assert np.max(np.abs(seen - amplitude[40:61] ** 2)) < 1e-9


def test_a_tabulated_transfer_is_te_only_with_the_table_phase_and_group_delay(delay_line):
    sp = SParameters.load(delay_line[0])
    (tr,) = TabulatedBehaviour(sp).transfers(optodraw.Waveguide(), "waveguide1", "o1", 1550.0, {})
    assert tr.out_port == "o2" and tr.phase_included
    assert abs(tr.matrix[0, 0] - _expected(1550.0)) < 1e-9 and not np.any(tr.matrix.ravel()[1:])
    assert tr.length * tr.group_index == pytest.approx(N_DELAY * L_DELAY, rel=1e-9)     # the delay n L / c


def test_a_tabulated_part_says_te_only(delay_line):
    from optodraw.animation_engine import spectrum

    scene, guide, _ = _guide_scene()
    guide.model = SParameters.load(delay_line[0])
    notes = spectrum(scene, start_nm=1549, stop_nm=1551, points=3).notes
    assert any("TE only" in note for note in notes)


@pytest.mark.parametrize("kind", ["heater", "phase"])
def test_a_tabulated_part_refuses_a_heater_sweep(delay_line, kind):
    scene, guide, _ = _guide_scene()
    guide.model = SParameters.load(delay_line[0])
    sid = scene_ids(scene)[id(guide)]
    with pytest.raises(AnimationError, match=rf"^{sid} has an imported model: its phase and heater cannot be swept$"):
        compile_sweep(scene, f"{kind}:{sid}", [0.0, 1.0])


FIELDRT_COUPLER = Path(__file__).resolve().parents[1] / "docs" / "examples" / "models" / "data" / "coupler_fieldrt.npz"
FORWARD = (("o3", "o1"), ("o4", "o1"), ("o3", "o2"), ("o4", "o2"))


def test_the_imported_mzi_equals_a_direct_cascade():
    # the docs example's MZI of two fieldrt couplers, with only the forward entries (no reflection, so one pass is
    # the whole answer): the engine's power must equal S_join . arms . S_split written out here with numpy
    from optodraw.animation_engine import spectrum
    from optodraw.animation_engine.graph import build_graph

    full = SParameters.load(FIELDRT_COUPLER)
    table = SParameters(full.wavelengths_nm, {key: full.s[key] for key in FORWARD}, full.source)
    scene = optodraw.Scene(platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 7)))
    split = scene.add(optodraw.DirectionalCoupler(center=(0, 0)))
    join = scene.add(optodraw.DirectionalCoupler(center=(150, 0)))
    split.model = join.model = table
    bar = scene.add(optodraw.OnChipPhotodetector(center=(270, 30)))
    cross = scene.add(optodraw.OnChipPhotodetector(center=(270, -30)))
    scene.route((laser, "o1"), (split, "o1"), kind="waveguide")
    scene.route((split, "o3"), (join, "o1"), kind="waveguide")
    scene.route((split, "o4"), (join, "o2"), kind="waveguide", path_type="manhattan", steps=[{"y": -17.0}])
    scene.route((join, "o3"), (bar, "o1"), kind="waveguide", path_type="smooth")
    scene.route((join, "o4"), (cross, "o1"), kind="waveguide", path_type="smooth")
    ids = scene_ids(scene)
    links = {frozenset((link.a, link.b)): link for link in build_graph(scene).links}

    def link(a, port_a, b, port_b, wl_um):
        found = links[frozenset(((ids[id(a)], port_a), (ids[id(b)], port_b)))]
        return np.exp(2j * np.pi * found.group_index * found.length / wl_um)

    def cascade(wl_nm, s):
        wl_um = wl_nm / 1000.0
        into = link(laser, "o1", split, "o1", wl_um)
        upper = s[("o3", "o1")] * into * link(split, "o3", join, "o1", wl_um)
        lower = s[("o4", "o1")] * into * link(split, "o4", join, "o2", wl_um)
        return {"bar": np.abs((s[("o3", "o1")] * upper + s[("o3", "o2")] * lower) * link(join, "o3", bar, "o1", wl_um)) ** 2,
                "cross": np.abs((s[("o4", "o1")] * upper + s[("o4", "o2")] * lower) * link(join, "o4", cross, "o1", wl_um)) ** 2}

    on_table = spectrum(scene, start_nm=1500, stop_nm=1600, points=201)            # every fifth table wavelength
    rows = np.searchsorted(full.wavelengths_nm, on_table.wavelengths_nm - 1e-6)
    assert np.allclose(full.wavelengths_nm[rows], on_table.wavelengths_nm, rtol=0, atol=1e-9)
    expected = cascade(on_table.wavelengths_nm, {key: full.s[key][rows] for key in FORWARD})
    between = spectrum(scene, start_nm=1500.05, stop_nm=1599.55, points=200)       # midway between table wavelengths
    at = [table.at(wl) for wl in between.wavelengths_nm]
    expected_between = cascade(between.wavelengths_nm, {key: np.array([row[key] for row in at]) for key in FORWARD})
    for name, part in (("bar", bar), ("cross", cross)):
        assert np.max(np.abs(on_table.of(part, "o1") - expected[name])) < 1e-9
        assert np.max(np.abs(between.of(part, "o1") - expected_between[name])) < 1e-9
    assert np.ptp(expected["bar"]) > 0.5                                             # the arms differ: fringes
