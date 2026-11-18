"""The MMI self-imaging model that the Field look uses."""

import cmath
import json
import math

import numpy as np
import pytest

import optodraw
from optodraw.animation3d import fieldmodel
from optodraw.animation3d.fieldmodel import mmi_self_imaging_length_um
from optodraw.animation3d.inputs import default_inputs
from optodraw.animation3d.payload import build_light_payload
from optodraw.animation_engine.tables import compile_table
from optodraw.presets import PRESETS, build_preset


def test_the_symmetric_one_by_two_length_follows_the_formula():
    l_pi = 4 * 2.85 * 36 / (3 * 1.55)
    assert mmi_self_imaging_length_um(6.0, 2.85, 1550.0, 2, True) == pytest.approx(3 * l_pi / 8, abs=1e-9)


def test_the_general_interference_length_is_three_beat_lengths_over_the_images():
    l_pi = 4 * 3.0 * 25 / (3 * 1.31)
    assert mmi_self_imaging_length_um(5.0, 3.0, 1310.0, 2, False) == pytest.approx(3 * l_pi / 2, abs=1e-9)
    assert mmi_self_imaging_length_um(5.0, 3.0, 1310.0, 4, False) == pytest.approx(3 * l_pi / 4, abs=1e-9)


# ---- the steady state ---------------------------------------------------------------------------------------------



def _nm(table):
    return next(r['wavelength_nm'] for e in table['edges'].values() for r in e['cw'])


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


@pytest.mark.parametrize("phi", [0.0, math.pi / 2, math.pi])
def test_the_field_model_gives_an_mzi_output_of_cos_squared(phi):
    scene = _mzi_scene()
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", params={"phase:mzi1:arm1": phi}, inputs=inputs)
    nm = _nm(table)
    assert fieldmodel.port_intensity(table, "port:mzi1:o4", nm) == pytest.approx(math.cos(phi / 2) ** 2, abs=1e-6)
    assert fieldmodel.port_intensity(table, "port:mzi1:o3", nm) == pytest.approx(math.sin(phi / 2) ** 2, abs=1e-6)


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


@pytest.mark.parametrize("phi", [0.0, math.pi / 2, math.pi])
def test_the_mzi_arms_interfere_to_cos_squared_at_matching_points_along_the_arms(phi):
    table = compile_table(_mzi_scene(), mode="cw", params={"phase:mzi1:arm1": phi}, inputs=[])
    arms = [(e, r) for i, e in table["edges"].items() for r in e["cw"] if r["to"] == "port:mzi1:o4"]
    assert len(arms) == 2 and arms[0][0]["length_um"] == pytest.approx(arms[1][0]["length_um"])
    for fraction in (0.0, 0.4, 1.0):
        total = sum(fieldmodel.field_at(e, r, fraction * e["length_um"]) for e, r in arms)
        assert fieldmodel.intensity(total) == pytest.approx(math.cos(phi / 2) ** 2, abs=1e-6)


def _phases_agree(a, b):
    return abs(cmath.exp(1j * fieldmodel.phase_of(a)) - cmath.exp(1j * fieldmodel.phase_of(b))) < 1e-6


def _joints(table, scale):
    """Per edge record: its start and end drawn field, the drawn fields at the end of the edges that feed it."""

    out = []
    for edge_id, edge in table["edges"].items():
        for record in edge["cw"]:
            start = fieldmodel.display_field(table, edge_id, record, 0.0, scale)
            feeders = [fieldmodel.display_field(table, other_id, found, other["length_um"], scale)
                       for other_id, other in table["edges"].items() for found in other["cw"]
                       if found["to"] == record["from"] and found["wavelength_nm"] == record["wavelength_nm"]]
            out.append((edge_id, record, start, feeders))
    return out


@pytest.mark.parametrize("name", ["mzi", "ring_resonator_chip"])
def test_at_scale_forty_the_field_is_continuous_at_every_joint_and_has_the_engines_phase_at_every_end(name):
    if name == "mzi":
        scene, params = _mzi_scene(), {"phase:mzi1:arm1": 1.0}
    else:
        scene, params = build_preset(name), None
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", params=params, inputs=inputs)
    checked = 0
    for edge_id, record, start, feeders in _joints(table, 40.0):
        edge = table["edges"][edge_id]
        engine_end = fieldmodel.end_field(edge, record)
        assert _phases_agree(fieldmodel.display_field(table, edge_id, record, edge["length_um"], 40.0), engine_end)
        drawn = fieldmodel.display_phase(table, edge_id, record, edge["length_um"], 40.0)
        assert abs(cmath.exp(1j * drawn) - cmath.exp(1j * fieldmodel.phase_of(engine_end))) < 1e-6
        if not feeders:
            continue
        checked += 1
        if edge_id.startswith("path:"):
            assert _phases_agree(start, sum(feeders))                           # the amplitude splits at a path
        else:
            assert fieldmodel.intensity(start - sum(feeders)) < 1e-12           # a link carries the sum, in full
    assert checked > 0


def test_the_cw_rails_are_drawn_from_the_feeding_links_phase_to_the_engines_phase():
    scene = _coupler_scene()
    cw = build_light_payload(scene)["cw"]
    assert cw["lambda_scale"] > 1
    rails = [r for r in cw["rails"] if r["window"] is not None]
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", inputs=inputs)
    paths = [fieldmodel.end_field(e, r) for i, e in table["edges"].items() for r in e["cw"]
             if i.startswith("path:directionalcoupler1:")]
    feeds = [fieldmodel.end_field(e, r) for i, e in table["edges"].items() for r in e["cw"]
             if r["to"].startswith("port:directionalcoupler1:") and not i.startswith("path:")]
    assert paths and len(feeds) == 1
    joined = 0
    for rail in rails:
        field = np.array(rail["fields"][0]["field"])
        z = field[:, 0] + 1j * field[:, 1]
        ref = int(np.argmin(np.abs(np.array(rail["arcs"]) - rail["ref_arc"])))
        unit = lambda v: cmath.exp(1j * cmath.phase(v))                                  # noqa: E731
        # the window end carries the phase of one of the engine's outputs of the coupler
        assert any(abs(unit(z[ref]) - cmath.exp(1j * fieldmodel.phase_of(end))) < 1e-5 for end in paths)
        if abs(z[0]) > 1e-6:                                                              # the lit rail starts at the link's end phase
            assert abs(unit(z[0]) - cmath.exp(1j * fieldmodel.phase_of(feeds[0]))) < 1e-5
            joined += 1
    assert joined == 1


def test_the_displayed_wavelength_keeps_the_phase_where_paths_meet():
    scene = _mzi_scene()
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", params={"phase:mzi1:arm1": 1.0}, inputs=inputs)
    nm = _nm(table)
    assert fieldmodel.port_intensity(table, "port:mzi1:o4", nm, scale=25.0) == pytest.approx(
        fieldmodel.port_intensity(table, "port:mzi1:o4", nm), abs=1e-9)


def test_the_arrival_front_of_each_edge_is_the_engines_t0():
    scene = _mzi_scene()
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", inputs=inputs)
    payload = build_light_payload(scene)
    assert payload["cw"]["edges"]
    for edge_id, edge in table["edges"].items():
        if edge["cw"]:
            assert fieldmodel.arrival_front_ps(payload["cw"], edge_id) == (
                min(r["t0"] for r in edge["cw"]), min(r["t1"] for r in edge["cw"]))
            assert fieldmodel.arrival_front_ps(payload["cw"], edge_id)[0] >= 0.0


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


def test_the_crest_spacing_is_the_guide_wavelength_times_the_scale():
    assert fieldmodel.crest_spacing_um(1550.0, 2.0, 1.0) == pytest.approx(0.775)
    assert fieldmodel.crest_spacing_um(1550.0, 2.0, 300.0) == pytest.approx(232.5)


def test_the_lambda_scale_puts_about_forty_crests_on_the_longest_guide():
    scale = fieldmodel.lambda_scale(1000.0, 1550.0, 2.0)
    assert 1000.0 / fieldmodel.crest_spacing_um(1550.0, 2.0, scale) == pytest.approx(40.0, rel=0.05)
    assert scale == round(scale) and fieldmodel.lambda_caption(scale) == f"Wavelength shown x{scale:.0f}"


def test_the_payload_says_the_wavelength_scale_and_gives_each_record_its_crest_spacing():
    payload = build_light_payload(_mzi_scene())
    cw = payload["cw"]
    assert f"Wavelength shown x{cw['lambda_scale']:.0f}" in payload["captions"]
    for edge in cw["edges"].values():
        for record in edge["cw"]:
            assert record["crest_um"] == pytest.approx(
                fieldmodel.crest_spacing_um(record["wavelength_nm"], edge["group_index"], cw["lambda_scale"]))
    # about 40 crests span the lit drawing (its largest side); lambda_scale rounds the exact scale to a whole number,
    # so the crest count is off 40 by at most 0.5 / scale
    points = np.array([p for e in cw["edges"].values() if e["cw"] for p in e["points"]])
    extent = float(max(points.max(axis=0) - points.min(axis=0)))
    edge = max(cw["edges"].values(), key=lambda e: e["length_um"])
    assert extent / edge["cw"][0]["crest_um"] == pytest.approx(40.0, rel=0.5 / cw["lambda_scale"] + 1e-9)
    assert "Crest spacing from the group index" in payload["captions"]


def _coupler_scene():
    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 7)))
    dc = scene.add(optodraw.DirectionalCoupler(center=(0, 0)))
    d3 = scene.add(optodraw.OnChipPhotodetector(center=(160, 40)))
    d4 = scene.add(optodraw.OnChipPhotodetector(center=(160, -40)))
    scene.route((laser, "o1"), (dc, "o1"), kind="waveguide")
    scene.route((dc, "o3"), (d3, "o1"), kind="waveguide")
    scene.route((dc, "o4"), (d4, "o1"), kind="waveguide")
    return scene


def test_a_couplers_cw_rail_fields_sum_to_the_input_power_at_every_point():
    payload = build_light_payload(_coupler_scene())
    rails = [r for r in payload["cw"]["rails"] if r["window"] is not None]
    assert len(rails) == 2
    count = len(rails[0]["fields"][0]["field"])
    assert count > 3 and len(rails[1]["fields"][0]["field"]) == count == len(rails[0]["arcs"])
    total = np.zeros(count)
    for rail in rails:
        (record,) = rail["fields"]
        total += np.array([sum(v * v for v in f) for f in record["field"]])
    assert total == pytest.approx(np.full(count, total[0]), abs=1e-6)
    assert total[0] > 0
    powers = [np.array([sum(v * v for v in f) for f in r["fields"][0]["field"]]) for r in rails]
    assert powers[0].min() < powers[0].max() - 0.1            # the power moves from one rail to the other


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_cw_is_in_the_payload_of_every_preset_with_light(name):
    payload = build_light_payload(build_preset(name))
    assert "cw" in payload
    if payload["enabled"]:
        assert payload["cw"]["mode"] == "cw" and payload["cw"]["edges"]
        json.dumps(payload["cw"])


@pytest.mark.parametrize("name", ["mzi", "ring_resonator_chip"])
def test_a_cw_rail_that_the_engine_feeds_starts_at_the_phase_of_the_arriving_light(name):
    """A rail at the part's input starts at the phase of the light that arrives there. A rail inside the part (the
    second coupler of an MZI) is fed by a field the engine's table does not hold: it starts at its own phase."""

    scene = _mzi_scene() if name == "mzi" else build_preset(name)
    inputs, _ = default_inputs(scene)
    table = compile_table(scene, mode="cw", inputs=inputs)
    arriving = {}
    for edge in table["edges"].values():
        for record in edge["cw"]:
            arriving[record["to"]] = arriving.get(record["to"], 0) + fieldmodel.end_field(edge, record)
    rails = build_light_payload(scene)["cw"]["rails"]
    joined = 0
    for rail in rails:
        field = np.array(rail["fields"][0]["field"])
        z0 = field[0, 0] + 1j * field[0, 1]
        phases = [cmath.exp(1j * fieldmodel.phase_of(v)) for port, v in arriving.items()
                  if port.startswith(f"port:{rail['host']}:") and np.any(v)]
        if abs(z0) > 1e-6 and any(abs(cmath.exp(1j * cmath.phase(z0)) - p) < 1e-5 for p in phases):
            joined += 1
    assert joined >= 1


# ---- what the Field look draws ------------------------------------------------------------------------------------


def _mmi_scene(kind="MMI1x2"):
    """A laser that feeds an MMI; a detector on each output."""

    from optodraw.registry import build_component

    scene = optodraw.Scene(width=360, height=200, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-120, 0)))
    mmi = scene.add(build_component(kind, center=(0, 0)))
    scene.route((laser, "o1"), (mmi, "o1"), kind="waveguide")
    outs = [n for n in mmi.ports() if n != "o1"]
    for k, name in enumerate(outs):
        det = scene.add(optodraw.OnChipPhotodetector(center=(120, 30 * (k - (len(outs) - 1) / 2))))
        scene.route((mmi, name), (det, "o1"), kind="waveguide")
    return scene


def _grid(region):
    """A region's sampled field as complex values, ``[v][u]``, and the mask of the samples inside the region."""

    import base64

    nu, nv = region["size"]
    raw = np.frombuffer(base64.b64decode(region["data"]), np.uint8).reshape(nv, nu, 4).astype(float)
    z = ((raw[..., 0] - 128) + 1j * (raw[..., 1] - 128)) / 127 * region["scale"]
    return z, raw[..., 3] > 127


def _peaks(values, floor=0.3):
    """Indices of the local maxima of ``values`` above ``floor`` of the largest."""

    top = max(values)
    return [i for i in range(len(values)) if values[i] >= floor * top
            and (i == 0 or values[i] > values[i - 1]) and (i == len(values) - 1 or values[i] >= values[i + 1])]


@pytest.mark.parametrize("kind, outputs", [("MMI1x2", ("o2", "o3")), ("MMI1x4", ("o2", "o3", "o4", "o5"))])
def test_an_mmi_region_grid_forms_one_image_on_each_drawn_output_port_with_the_engines_split(kind, outputs):
    from optodraw.animation_engine.graph import build_graph

    scene = _mmi_scene(kind)
    payload = build_light_payload(scene)
    sid = f"{kind.lower()}1"
    (region,) = [r for r in payload["cw"]["regions"] if r["host"] == sid]
    z, inside = _grid(region)
    assert inside.all()                                         # the grid fills the body rectangle
    nu, nv = region["size"]
    o, u, v = (np.array(c, float) for c in region["corners"])
    across = (v - o) / np.linalg.norm(v - o)
    part = build_graph(scene).parts[sid]

    def place(i, j):                                            # sample (i, j): the first and last column are the faces
        return o + (u - o) * i / (nu - 1) + (v - o) * j / (nv - 1)

    for column, ports in ((nu - 1, outputs), (0, ("o1",))):     # the output plane and the input plane
        intensity = list(np.abs(z[:, column]) ** 2)
        peaks = _peaks(intensity)
        assert len(peaks) == len(ports), (column, peaks)
        drawn = sorted(float(np.dot(np.array([part.world_port(n).center.x, part.world_port(n).center.y]) - o, across))
                       for n in ports)
        found = sorted(float(np.dot(place(column, j) - o, across)) for j in peaks)
        assert found == pytest.approx(drawn, abs=0.6), (found, drawn)   # the taper mouth is 2.6 wide
    # the engine's split: the field at each drawn output port (the last column, read between samples) is the field
    # of the edge that leaves there, half (MMI1x2) or a quarter (MMI1x4) of the power
    rows = np.array([float(np.dot(place(nu - 1, j) - o, across)) for j in range(nv)])
    leaving = {r["to"].rsplit(":", 1)[1]: r["amp"] for e, edge in payload["cw"]["edges"].items() if e.startswith(f"path:{sid}:")
               for r in edge["cw"]}
    for name in outputs:
        at = float(np.dot(np.array([part.world_port(name).center.x, part.world_port(name).center.y]) - o, across))
        here = complex(np.interp(at, rows, z[:, nu - 1].real), np.interp(at, rows, z[:, nu - 1].imag))
        assert abs(here) ** 2 == pytest.approx(leaving[name] ** 2, rel=0.1), name
        assert leaving[name] ** 2 == pytest.approx(1.0 / len(outputs), rel=1e-3)


def test_every_cw_record_carries_the_amplitude_and_the_display_phase_the_field_look_draws():
    payload = build_light_payload(_mzi_scene(), params={"phase:mzi1:arm1": 1.0})
    cw, checked = payload["cw"], 0
    for edge_id, edge in cw["edges"].items():
        for record in edge["cw"]:
            assert record["amp"] == pytest.approx(float(np.linalg.norm(fieldmodel.end_field(edge, record))), abs=1e-6)
            for s, drawn in zip((0.0, edge["length_um"]), record["phase"]):
                assert drawn == pytest.approx(fieldmodel.display_phase(cw, edge_id, record, s, cw["lambda_scale"]), abs=1e-4)
            # the front fades in over the time it takes to run one crest
            assert record["fade_ps"] == pytest.approx(record["crest_um"] * (record["t1"] - record["t0"]) / edge["length_um"], abs=1e-5)
            checked += 1
    assert checked > 5
    for rail in cw["rails"]:                                         # each rail's field: its crest spacing and fade
        span = rail["arcs"][-1] - rail["arcs"][0]
        for entry in rail["fields"]:
            assert entry["crest_um"] == pytest.approx(fieldmodel.crest_spacing_um(entry["wavelength_nm"], entry["n_eff"], cw["lambda_scale"]), abs=1e-5)
            assert entry["fade_ps"] == pytest.approx(entry["crest_um"] * (rail["t"][1] - rail["t"][0]) / span, abs=1e-5)
    assert cw["cycle_s"] > 0 and fieldmodel.cycle_caption(cw["cycle_s"]) in payload["captions"]


def _ybranch_mzi():
    """An interferometer built from parts: a Y-branch splits, a phase shifter in each arm, a Y-branch combines."""

    from optodraw.registry import build_component

    scene = optodraw.Scene(width=400, height=200, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-160, 0)))
    y1 = scene.add(build_component("YBranch", center=(-90, 0)))
    ps1 = scene.add(build_component("PhaseShifter", center=(0, 30)))
    ps2 = scene.add(build_component("PhaseShifter", center=(0, -30)))
    y2 = scene.add(build_component("YBranch", center=(90, 0), angle=180))
    det = scene.add(optodraw.OnChipPhotodetector(center=(170, 0)))
    scene.route((laser, "o1"), (y1, "o1"), kind="waveguide")
    scene.route((y1, "o3"), (ps1, "o1"), kind="waveguide")
    scene.route((y1, "o2"), (ps2, "o1"), kind="waveguide")
    scene.route((ps1, "o2"), (y2, "o2"), kind="waveguide")
    scene.route((ps2, "o2"), (y2, "o3"), kind="waveguide")
    scene.route((y2, "o1"), (det, "o1"), kind="waveguide")
    return scene


@pytest.mark.parametrize("dark", [False, True])
def test_where_two_arms_meet_on_one_guide_the_drawn_field_is_their_complex_sum(dark):
    """The combiner's two paths share their last stretch: one of them draws the complex sum of both there (the other
    draws nothing), so at the combiner's output the drawn field is the engine's: dark when the arms cancel."""

    scene = _ybranch_mzi()
    params = None
    if dark:                                        # the phase that makes the arms cancel at the combiner
        table = compile_table(scene, mode="cw", inputs=default_inputs(scene)[0])
        arms = {r["from"]: fieldmodel.end_field(e, r)[0] for i, e in table["edges"].items() for r in e["cw"]
                if i.startswith("path:ybranch2:")}
        params = {"phase:phaseshifter1": math.pi + cmath.phase(arms["port:ybranch2:o3"]) - cmath.phase(arms["port:ybranch2:o2"])}
    payload = build_light_payload(scene, params=params)
    profiles = payload["cw"]["profiles"]
    pair = sorted(i for i in profiles if i.startswith("path:ybranch2:"))
    assert len(pair) == 2
    (first,), (second,) = (profiles[i] for i in pair)
    assert first["amp"][-1] * second["amp"][-1] == 0.0                # one of them draws the shared stretch
    drawn = max(first["amp"][-1], second["amp"][-1])
    leaving = payload["cw"]["edges"].get("route:route6", {"cw": [{"amp": 0.0}]})["cw"]
    out = leaving[0]["amp"] if leaving else 0.0
    assert drawn == pytest.approx(out, abs=1e-6)
    assert (out < 1e-3) if dark else (out > 0.9)
    # before the junction each arm draws its own field
    assert first["amp"][0] == pytest.approx(second["amp"][0], abs=1e-6) and first["amp"][0] > 0.4


def _drawn_pieces(payload):
    """Every drawn piece of the Field look, per wavelength: ``(id, nm, start point, end point, start field, end
    field)``, in the direction the light runs: edges (their profile where they share a guide) and rails."""

    cw = payload["cw"]
    hidden = set(payload["hidden"])
    rail_points = {(r["host"], r["section"], r["rail"]): r["points"] for r in payload["rails"]}
    out = []
    for edge_id, edge in cw["edges"].items():
        if edge_id in hidden:
            continue
        for r in edge["cw"]:
            profile = next((p for p in cw["profiles"].get(edge_id, []) if p["wavelength_nm"] == r["wavelength_nm"]), None)
            if profile:
                a0, a1, p0, p1 = profile["amp"][0], profile["amp"][-1], profile["phase"][0], profile["phase"][-1]
            else:
                (a0, a1), (p0, p1) = (r["amp0"], r["amp"]), r["phase"]
            start, end = (edge["points"][0], edge["points"][-1]) if not r["reverse"] else (edge["points"][-1], edge["points"][0])
            out.append((edge_id, r["wavelength_nm"], start, end, a0 * cmath.exp(1j * p0), a1 * cmath.exp(1j * p1)))
    for rail in cw["rails"]:
        points = rail["points"] or rail_points[(rail["host"], rail["section"], rail["rail"])]
        for f in rail["fields"]:
            (z0, z1) = (complex(v[0], v[1]) for v in (f["field"][0], f["field"][-1]))
            out.append((f"rail:{rail['host']}:{rail['section']}:{rail['rail']}", f["wavelength_nm"], points[0], points[-1], z0, z1))
    return out


def _joint_jumps(payload, near=0.05):
    """At every place where drawn pieces end and start: the phase jump (one piece in, one out: also the amplitude
    jump). Several out (a split): each starts at the phase of the one in. Several in (a combiner): the one out starts
    at the phase of their sum (their amplitudes do not add: a Y-junction sends the rest away)."""

    pieces = _drawn_pieces(payload)
    jumps = []
    for _, nm, place, _, _, _ in pieces:
        ins = [p[5] for p in pieces if p[1] == nm and math.dist(p[3], place) < near and abs(p[5]) > 1e-3]
        outs = [p[4] for p in pieces if p[1] == nm and math.dist(p[2], place) < near and abs(p[4]) > 1e-3]
        arriving = sum(ins)
        if not ins or not outs or abs(arriving) < 1e-3:
            continue
        amplitude = abs(abs(outs[0]) - abs(arriving)) if len(ins) == len(outs) == 1 else 0.0
        jumps.append((max(abs(cmath.phase(z / arriving)) for z in outs), amplitude, place))
    return jumps


def _face_jumps(payload):
    """Where a lit edge enters or leaves a multimode region: the edge's drawn field at the face against the region's
    grid read there (between samples): ``(phase jump, relative amplitude jump, edge)``."""

    from optodraw.animation_engine.behaviours.geometry import arc_lengths, cut

    cw, out = payload["cw"], []
    for region in cw["regions"]:
        z, _ = _grid(region)
        nu, nv = region["size"]
        o, u, v = (np.array(c, float) for c in region["corners"])
        frame = np.array([u - o, v - o]).T
        for edge_id, stretches in cw["cuts"].items():
            edge = cw["edges"][edge_id]
            record = next((r for r in edge["cw"] if r["wavelength_nm"] == region["wavelength_nm"]), None)
            profile = next((p for p in cw["profiles"].get(edge_id, []) if p["wavelength_nm"] == region["wavelength_nm"]), None)
            total = arc_lengths(edge["points"])[-1]
            for start, end in stretches if record and edge_id.startswith(f"path:{region['host']}:") else ():
                mid = np.linalg.solve(frame, np.asarray(cut(edge["points"], 0.5 * (start + end) * total, 0.5 * (start + end) * total)[0]) - o)
                if not (0 <= mid[0] <= 1 and 0 <= mid[1] <= 1):
                    continue                                        # a stretch in the AWG's other slab
                for f in (start, end):
                    if profile:
                        arcs = np.array(arc_lengths(profile["points"])) / arc_lengths(profile["points"])[-1]
                        drawn = np.interp(f, arcs, profile["amp"]) * cmath.exp(1j * np.interp(f, arcs, profile["phase"]))
                    else:
                        drawn = fieldmodel.drawn_field(record, f)
                    if abs(drawn) < 1e-3:
                        continue                                    # this edge does not draw the stem: its partner does
                    a, b = np.linalg.solve(frame, np.asarray(cut(edge["points"], f * total, f * total)[0]) - o)
                    i, j = min(max(a * (nu - 1), 0.0), nu - 1 - 1e-9), min(max(b * (nv - 1), 0.0), nv - 1 - 1e-9)
                    i0, j0, fi, fj = int(i), int(j), i - int(i), j - int(j)
                    grid = (z[j0, i0] * (1 - fi) * (1 - fj) + z[j0, i0 + 1] * fi * (1 - fj) + z[j0 + 1, i0] * (1 - fi) * fj
                            + z[j0 + 1, i0 + 1] * fi * fj)
                    out.append((abs(cmath.phase(grid / drawn)), abs(abs(grid) - abs(drawn)) / abs(drawn), edge_id))
    return out


@pytest.mark.parametrize("name", ["mzi", "ybranch", "mmi", "ring_resonator_chip", "coherent_receiver_chip",
                                  "wdm_delay_weight_bank_chip"])
def test_the_drawn_field_has_no_jump_at_any_joint_or_region_face(name):
    """Crests never jump: where one drawn piece ends and the next starts (an edge, a coupling section's rail, the
    next section's rail, a ring closing on itself), the drawn field is the same; where a lit edge meets a multimode
    region, the region's grid has the edge's field there."""

    scene, params = {"mzi": (_mzi_scene, {"phase:mzi1:arm1": 1.0}), "ybranch": (_ybranch_mzi, None),
                     "mmi": (_mmi_scene, None)}.get(name, (lambda: build_preset(name), None))
    payload = build_light_payload(scene(), params=params)
    jumps = _joint_jumps(payload)
    assert len(jumps) >= 4
    worst = max(jumps)
    assert worst[0] < 1e-3 and max(j[1] for j in jumps) < 1e-3, worst
    if payload["cw"]["regions"]:
        faces = _face_jumps(payload)
        assert faces and max(f[0] for f in faces) < 0.15 and max(f[1] for f in faces) < 0.08, max(faces)


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


def test_a_heated_ring_has_one_heat_entry_that_follows_its_heater_arc_with_the_engines_phase():
    scene, ring = _ring_with_heater(center=(20, 5))
    sid = next(s for s, p in __import__("optodraw.animation_engine.graph", fromlist=["x"]).build_graph(scene).parts.items() if p is ring)
    payload = build_light_payload(scene, params={f"heater:{sid}": 10.0}, look="field")
    (entry,) = payload["heat"]
    spine = ring.heater_centerline()
    assert entry["sid"] == sid and entry["width_um"] == ring.heater_width
    assert np.allclose(entry["path"], [[20 + x, 5 + y] for x, y in spine], atol=1e-3)
    length = sum(math.dist(a, b) for a, b in zip(spine, spine[1:]))
    assert entry["delta_t_k"] == pytest.approx(fieldmodel.heater_delta_t_k(math.pi * 10.0 / 20.0, 1550.0, length), rel=1e-9)
    assert entry["tau_s"] == 0.4 and entry["grow_um2_per_s"] > 0
    assert build_light_payload(scene, look="field")["heat"] == []               # no heater power: no heat


def test_a_driven_mzm_has_one_rf_entry_with_the_drawn_gap_and_the_engines_drive():
    scene, mzm = _mzm_scene()
    payload = build_light_payload(scene, params={"drive:mzm1": 1.5}, look="field")
    (entry,) = payload["rf"]
    drawn = mzm._draw_variant()                                                 # the page draws this variant
    polygons = drawn._electrode_polygons(drawn._active_metrics())
    edges = [[y for x, y in polygon if x == max(px for px, _ in polygon)] for polygon in polygons]   # each rail's right end
    signal_low, ground_high = min(edges[0]), max(edges[1])
    assert entry["gap_um"] == pytest.approx(signal_low - ground_high, abs=1e-3)
    assert entry["v"] == 1.5 and entry["sid"] == "mzm1"
    assert entry["signal"][0][1] == pytest.approx(signal_low, abs=1e-3) and entry["ground"][0][1] == pytest.approx(ground_high, abs=1e-3)
    assert entry["v_rf_um_per_ps"] == pytest.approx(fieldmodel.C_UM_PER_PS / 2.5)
    assert build_light_payload(scene, look="field")["rf"] == []                 # no drive: no field


def test_a_gsg_modulator_has_an_rf_entry_for_each_gap():
    scene, _ = _mzm_scene("gsg")
    payload = build_light_payload(scene, params={"drive:mzm1": 1.0}, look="field")
    assert len(payload["rf"]) == 2 and all(r["gap_um"] > 0 for r in payload["rf"])


def test_the_captions_name_the_peak_rise_and_the_drive_in_plain_sentences():
    scene, ring = _ring_with_heater()
    heat = " ".join(build_light_payload(scene, params={"heater:microringresonator1": 10.0}, look="field")["captions"])
    assert "K above the chip" in heat and "simple diffusion model" in heat and "us real" in heat and "3 time constants" in heat
    scene, _ = _mzm_scene()
    rf = " ".join(build_light_payload(scene, params={"drive:mzm1": 1.5}, look="field")["captions"])
    assert "1.5 V" in rf and "V per um" in rf and "s per ps" in rf and "slower than real" in rf
    assert "—" not in heat + rf and "–" not in heat + rf


def test_the_colour_scale_is_the_largest_value_rounded_up_to_1_2_or_5_times_a_power_of_ten():
    from optodraw.animation3d.effects import nice_ceiling

    assert [nice_ceiling(v) for v in (46.6, 50.0, 50.1, 0.0947, 1.0, 1.01, 2.0, 7.0, 0.0)] == [50.0, 50.0, 100.0, 0.1, 1.0, 2.0, 2.0, 10.0, 0.0]
    scene, _ = _ring_with_heater()
    payload = build_light_payload(scene, params={"heater:microringresonator1": 10.0}, look="field")   # 41 K
    assert payload["heat_scale_k"] == 50.0 and payload["heat"][0]["delta_t_k"] < 50.0
    scene, _ = _mzm_scene()
    payload = build_light_payload(scene, params={"drive:mzm1": 1.0}, look="field")
    assert payload["rf_scale_v_per_um"] == 0.1
    assert build_light_payload(scene, look="field")["heat_scale_k"] == 0.0


def test_halving_a_heaters_power_halves_its_rise():
    scene = build_preset("ring_resonator_chip")
    payload = build_light_payload(scene, params={"heater:coupledringfilter1:ring1": 20.0,
                                                 "heater:coupledringfilter1:ring3": 10.0}, look="field")
    rise = {h["sid"]: h["delta_t_k"] for h in payload["heat"]}
    ring1, ring3 = rise["coupledringfilter1:ring1"], rise["coupledringfilter1:ring3"]
    spine = {h["sid"]: h["path"] for h in payload["heat"]}
    length = lambda path: sum(math.dist(a, b) for a, b in zip(path, path[1:]))        # noqa: E731
    assert ring1 * length(spine["coupledringfilter1:ring1"]) == pytest.approx(2 * ring3 * length(spine["coupledringfilter1:ring3"]), rel=1e-4)


def test_heat_comes_only_from_a_drawn_heater_with_power_not_from_an_abstract_phase():
    scene, _ = _ring_with_heater()
    assert build_light_payload(scene, params={"phase:microringresonator1": 1.0}, look="field")["heat"] == []
    assert build_light_payload(scene, params={"heater:microringresonator1": 0.0}, look="field")["heat"] == []
    mzi = _mzi_scene_for_heat()
    assert build_light_payload(mzi, params={"phase:mzi1:arm1": math.pi}, look="field")["heat"] == []
    (entry,) = build_light_payload(mzi, params={"heater:mzi1": 10.0}, look="field")["heat"]
    assert entry["sid"] == "mzi1" and entry["delta_t_k"] > 0


def test_the_heat_rise_is_the_one_at_the_input_wavelength():
    """The rise that gives a heater's phase grows with the wavelength (phase = 2 pi dn/dT dT L / wavelength): at
    1310 nm it is 1310 / 1550 of the rise at 1550 nm."""

    rises = {}
    for nm in (1550.0, 1310.0):
        scene = _mzi_scene_for_heat()
        next(p for p in scene.walk() if type(p).__name__ == "OnChipLaser").wavelength_nm = nm
        (entry,) = build_light_payload(scene, params={"heater:mzi1": 10.0}, look="field")["heat"]
        rises[nm] = entry["delta_t_k"]
    assert rises[1310.0] == pytest.approx(rises[1550.0] * 1310.0 / 1550.0, rel=1e-9)


def _mzi_scene_for_heat():
    scene = optodraw.Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzi = scene.add(optodraw.MZI(center=(0, 0)))
    det = scene.add(optodraw.OnChipPhotodetector(center=(160, 40)))
    scene.route((laser, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o3"), (det, "o1"), kind="waveguide")
    return scene


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


def test_a_caption_names_a_part_by_its_label_when_it_has_one():
    """A part has one name in the captions, the notices and the tour: its label, else its type in words and its
    number (``shown_name``)."""

    scene, ring = _ring_with_heater()
    ring.label = "Tuning ring"
    payload = build_light_payload(scene, params={"heater:microringresonator1": 10.0}, look="field")
    heat = [c for c in payload["captions"] if "K above" in c]
    assert heat == [f"Heater on Tuning ring: up to {payload['heat'][0]['delta_t_k']:.1f} K above the chip."]
    ring.label = ""
    payload = build_light_payload(scene, params={"heater:microringresonator1": 10.0}, look="field")
    assert any(c.startswith("Heater on Microring resonator 1: up to") for c in payload["captions"])
    assert payload["tour_names"]["microringresonator1"] == "Microring resonator 1"


def test_every_caption_starts_with_a_capital_letter():
    scene, _ = _ring_with_heater()
    captions = build_light_payload(scene, params={"heater:microringresonator1": 10.0}, look="field")["captions"]
    scene, _ = _mzm_scene()
    captions += build_light_payload(scene, params={"drive:mzm1": 1.0}, look="field")["captions"]
    assert any(c.startswith("Heater on") for c in captions) and any(c.startswith("Drive on MZM 1: 1 V,") for c in captions)
    assert all(c[0].isupper() or c[0].isdigit() for c in captions), captions
