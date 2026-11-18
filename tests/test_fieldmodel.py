"""The MMI self-imaging model that the Field look uses."""

import math

import numpy as np
import pytest

import optodraw
from optodraw.animation3d import fieldmodel
from optodraw.animation3d.inputs import default_inputs
from optodraw.animation3d.payload import build_light_payload
from optodraw.animation_engine.tables import compile_table


# ---- the steady state ---------------------------------------------------------------------------------------------


def _mzi_scene():
    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzi = scene.add(optodraw.MZI(center=(0, 0)))
    d3 = scene.add(optodraw.OnChipPhotodetector(center=(160, 40)))
    d4 = scene.add(optodraw.OnChipPhotodetector(center=(160, -40)))
    scene.route((laser, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o3"), (d3, "o1"), kind="waveguide")
    scene.route((mzi, "o4"), (d4, "o1"), kind="waveguide")
    return scene


def _k(edge, record):
    return 2 * math.pi * edge["group_index"] / (record["wavelength_nm"] * 1e-3)


def test_the_field_along_an_edge_runs_at_the_engines_wave_number():
    scene = _mzi_scene()
    table = compile_table(scene, mode="cw", params={"phase:mzi1:arm1": 0.7}, inputs=[])
    seen = set()
    for edge in table["edges"].values():
        for record in edge["cw"]:
            jones = np.array([complex(record["jones"][0], record["jones"][1]), complex(record["jones"][2], record["jones"][3])])
            k, length = _k(edge, record), edge["length_um"]
            for s in (0.0, 0.37 * length, 0.81 * length):
                # a path record holds the exit field; a link record the entry field
                want = jones * np.exp(1j * k * (s - length)) if record["jones_reference"] == "exit" else jones * np.exp(1j * k * s)
                assert fieldmodel.field_at(edge, record, s) == pytest.approx(want, abs=1e-9)
            seen.add(record["jones_reference"])
    assert seen == {"entry", "exit"}


def test_an_edges_front_is_its_length_over_the_group_velocity_summed_along_the_path():
    scene = _mzi_scene()
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", inputs=inputs)
    first = table["edges"]["path:onchiplaser1:_active->o1#emission"]
    route = table["edges"]["route:route1"]
    c_um_per_ps = 299.792458
    hand_t0 = first["length_um"] * first["group_index"] / c_um_per_ps          # from the source, along its path
    assert fieldmodel.arrival_front_ps(table, "route:route1")[0] == pytest.approx(hand_t0, abs=1e-9)
    hand_t1 = hand_t0 + route["length_um"] * route["group_index"] / c_um_per_ps
    assert fieldmodel.arrival_front_ps(table, "route:route1")[1] == pytest.approx(hand_t1, abs=1e-9)


# ---- what the Field look draws ------------------------------------------------------------------------------------


# ---- heat and RF -----------------------------------------------------------------------------------------------------


def _ring_with_heater(center=(0, 0), angle=0):
    from optodraw.components.onchip.rings import MicroringResonator

    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    ring = scene.add(MicroringResonator(center=center, angle=angle, with_heater=True))
    det = scene.add(optodraw.OnChipPhotodetector(center=(150, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (det, "o1"), kind="waveguide")
    return scene, ring


def _mzm_scene(style="gs"):
    from optodraw.registry import build_component

    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0), drive_style=style))
    det = scene.add(optodraw.OnChipPhotodetector(center=(160, 0)))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (det, "o1"), kind="waveguide")
    return scene, mzm


def test_the_heater_rise_is_the_phase_over_the_index_change_along_the_heater():
    assert fieldmodel.heater_delta_t_k(math.pi, 1550, 100) == pytest.approx(1.55 / (2 * 100 * 1.8e-4), abs=1e-9)
    assert fieldmodel.heater_delta_t_k(math.pi / 2, 1550, 50, dn_dt=2e-4) == pytest.approx(1.55 / (4 * 50 * 2e-4), abs=1e-9)


def test_the_rf_field_is_the_voltage_over_the_gap():
    assert fieldmodel.rf_field_v_per_um(2.0, 4.0) == 0.5


def test_a_gsg_modulator_has_an_rf_entry_for_each_gap():
    scene, _ = _mzm_scene("gsg")
    payload = build_light_payload(scene, params={"drive:mzm1": 1.0}, look="field")
    assert len(payload["rf"]) == 2 and all(r["gap_um"] > 0 for r in payload["rf"])


def test_a_driven_part_whose_heat_is_not_drawn_gives_a_notice():
    from optodraw.animation3d.effects import heat_notices
    from optodraw.registry import build_component

    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0), mechanism="thermo_optic"))
    det = scene.add(optodraw.OnChipPhotodetector(center=(160, 0)))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (det, "o1"), kind="waveguide")
    quiet = build_light_payload(scene, look="field")["notices"]
    driven = build_light_payload(scene, params={"drive:mzm1": 1.0}, look="field")
    assert "MZM 1 is driven; its heat is not drawn yet" in driven["notices"] and "MZM 1 is driven; its heat is not drawn yet" not in quiet
    assert driven["heat"] == []
    parts = {"ramzi1": type("P", (), {"component_type": "RingAssistedMZI"})(), "pad1": type("P", (), {"component_type": "HeaterPad"})(),
             "mzi1": type("P", (), {"component_type": "MZI"})()}
    assert heat_notices(parts, {"heater:ramzi1:ring1": 5.0, "heater:pad1": 3.0, "heater:mzi1": 9.0}) == [
        "Ring assisted MZI 1 is driven; its heat is not drawn yet", "Heater pad 1 is driven; its heat is not drawn yet"]
    assert heat_notices(parts, {"heater:ramzi1": 0.0}) == []


def test_every_caption_starts_with_a_capital_letter():
    scene, _ = _ring_with_heater()
    captions = build_light_payload(scene, params={"heater:microringresonator1": 10.0}, look="field")["captions"]
    scene, _ = _mzm_scene()
    captions += build_light_payload(scene, params={"drive:mzm1": 1.0}, look="field")["captions"]
    assert any(c.startswith("Heater on") for c in captions) and any(c.startswith("Drive on MZM 1: 1 V,") for c in captions)
    assert all(c[0].isupper() or c[0].isdigit() for c in captions), captions
