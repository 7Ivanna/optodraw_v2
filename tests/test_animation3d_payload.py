"""The 3D light payload: the engine's packets, a host per edge, colours and a default input."""

import copy
import dataclasses
import functools
import json
import math
import time
import warnings

import pytest

from optodraw import Scene
from optodraw.animation3d.colours import CHANNEL_PALETTE, channel_colors
from optodraw.animation3d.inputs import default_inputs
from optodraw.animation3d.payload import _empty_cw, build_light_payload, default_params
from optodraw.animation_engine import compile_signal_state
from optodraw.core.beam import wavelength_to_hex
from optodraw.presets import build_preset
from optodraw.registry import build_component


def test_one_infrared_wavelength_is_white_and_several_get_the_palette_in_order():
    assert channel_colors([1550.0]) == {1550.0: "#ffffff"}
    assert channel_colors([1551.0, 1549.0, 1550.0]) == {1549.0: CHANNEL_PALETTE[0], 1550.0: CHANNEL_PALETTE[1],
                                                       1551.0: CHANNEL_PALETTE[2]}
    assert channel_colors([532.0])[532.0] == wavelength_to_hex(532.0)


def test_a_visible_wavelength_keeps_its_true_colour_among_several():
    assert channel_colors([532.0, 1550.0]) == {532.0: wavelength_to_hex(532.0), 1550.0: "#ffffff"}
    assert channel_colors([633.0, 1549.0, 1551.0]) == {633.0: wavelength_to_hex(633.0),
                                                      1549.0: CHANNEL_PALETTE[0], 1551.0: CHANNEL_PALETTE[1]}


def test_a_scene_without_a_source_takes_its_light_at_the_first_free_optical_input():
    scene = build_preset("ring_resonator_chip")
    found, notices = default_inputs(scene)
    assert len(found) == 1 and found[0].target.startswith("port:") and notices[0].startswith("no light source")


def test_the_default_input_on_a_bench_takes_the_wavelength_of_the_beam_at_its_port():
    """The bench preset's beam is 1090 nm: the light enters at that wavelength. One infrared line is white (Ruling 8),
    so its one colour is the colour the spec gives 1090 nm, not that of 1550 nm by chance."""

    scene = build_preset("free_space_breadboard")
    beams = [node for node in scene.walk() if type(node).__name__ == "Beam"]
    (found,), _ = default_inputs(scene)
    assert found.target == "port:iris1:in" and found.wavelength_nm == beams[0].wavelength == 1090.0
    assert build_light_payload(scene)["colors"] == {"1090.0": channel_colors([1090.0])[1090.0]}


def test_one_infrared_wavelength_says_it_is_shown_white_in_the_light_look():
    """Ruling 52: the white pulses on the bench's drawn red 1090 nm beam are explained. The caption shows in the Light
    look only (the Field look draws one infrared line red, white and blue); a visible laser has none."""

    payload = build_light_payload(build_preset("free_space_breadboard"))
    at = payload["captions"].index("1090 nm (infrared) shown white")
    assert at < payload["caption_split"] and payload["caption_light_only"] == [at]
    assert at not in payload["caption_folded"]
    visible = build_light_payload(build_preset("ftir"))
    assert not any("shown white" in c for c in visible["captions"]) and visible["caption_light_only"] == []


def test_a_visible_beam_gives_the_default_input_its_true_colour():
    """A 633 nm beam that starts in the air and meets a lens: the light that enters at the lens is red, the beam's
    own colour."""

    from optodraw import Beam, Lens, Photodiode

    scene = Scene(platform="free_space")
    lens = scene.add(Lens(center=(0, 0)))
    detector = scene.add(Photodiode(center=(60, 0)))
    scene.add(Beam.through((-60, 0), lens, detector, wavelength=633.0))
    (found,), _ = default_inputs(scene)
    assert found.wavelength_nm == 633.0
    assert build_light_payload(scene)["colors"] == {"633.0": wavelength_to_hex(633.0)}


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_payload_carries_the_engines_packets_unchanged():
    scene = build_preset("ring_resonator_chip")
    payload = build_light_payload(scene)
    inputs, _ = default_inputs(scene)                    # the engine ran with the display pulse at the default input
    rings = default_params(scene, inputs)                # and with the rings on resonance
    inputs = [dataclasses.replace(i, width_ps=payload["pulse_ps"]) for i in inputs]
    assert payload["pulse"] == compile_signal_state(scene, mode="pulse", params=rings, inputs=inputs).to_json()
    assert payload["enabled"] is True and payload["version"] == 1 and payload["train_period_ps"] > 0
    assert payload["colors"] == {"1550.0": "#ffffff"}
    assert any("3 s" in caption for caption in payload["captions"])


def test_every_edge_has_a_host_item():
    payload = build_light_payload(build_preset("ring_resonator_chip"))
    for edge_id in payload["pulse"]["edges"]:
        host = payload["hosts"][edge_id]
        assert host["kind"] in ("route", "beam", "part") and host["sid"]
    assert payload["hosts"]["route:route1"] == {"kind": "route", "sid": "route1", "segment": None}


def test_a_beam_edge_names_its_segment():
    from optodraw import Beam, Laser, Lens
    scene = Scene()
    laser = scene.add(Laser(center=(0, 0)))
    lens = scene.add(Lens(center=(60, 0)))
    scene.add(Beam(laser, lens))
    payload = build_light_payload(scene)
    beams = {k: v for k, v in payload["hosts"].items() if k.startswith("beam:")}
    assert beams and all(v["kind"] == "beam" and isinstance(v["segment"], int) for v in beams.values())


def test_the_payload_builds_the_signal_graph_once(monkeypatch):
    """The default input, the emitters and the payload share one graph (the engine's own solves build theirs)."""

    from optodraw.animation3d import inputs, payload
    from optodraw.animation_engine.graph import build_graph

    calls = []
    counted = lambda scene: calls.append(1) or build_graph(scene)          # noqa: E731
    monkeypatch.setattr(payload, "build_graph", counted)
    monkeypatch.setattr(inputs, "build_graph", counted)
    payload.build_light_payload(build_preset("free_space_breadboard"))
    assert len(calls) == 1


def test_a_scene_with_a_source_needs_no_default_input():
    scene = Scene()
    scene.add(build_component("Laser"))
    found, notices = default_inputs(scene)
    assert found == [] and notices == []


def test_a_scene_with_no_optical_port_gives_a_disabled_payload():
    scene = Scene()
    scene.add(build_component("SMU"))
    payload = build_light_payload(scene)
    assert payload["enabled"] is False and payload["notices"]
    assert payload["pulse"]["edges"] == {}


def test_the_payload_is_deterministic():
    scene = build_preset("ring_resonator_chip")
    assert json.dumps(build_light_payload(scene)) == json.dumps(build_light_payload(scene))


def _page_bytes(payload) -> int:
    """The bytes the page carries for the payload: the renderer embeds it as compact JSON."""

    from optodraw.renderers.threejs_renderer import _json_script_safe

    return len(_json_script_safe(payload).encode())


def test_a_large_chip_payload_stays_small_and_quick():
    start = time.perf_counter()
    payload = build_light_payload(build_preset("mzm_mesh_chip"))
    assert time.perf_counter() - start < 20 and _page_bytes(payload) < 5_000_000


def test_a_page_whose_light_passes_5_mb_gets_a_notice_with_its_size(monkeypatch):
    """Minor 17 of the final review: the notice names the size of the page's light (compact JSON, as embedded)."""

    from optodraw.animation3d import payload as module

    scene = build_preset("ring_resonator_chip")
    quiet = build_light_payload(scene)
    assert not any("MB" in notice for notice in quiet["notices"])
    monkeypatch.setattr(module, "BASE_LIMIT_BYTES", 100_000)
    loud = build_light_payload(scene)
    said = [notice for notice in loud["notices"] if "MB" in notice]
    size = module.page_bytes({**loud, "notices": quiet["notices"]})
    assert said == [f"the light payload is {size / 1e6:.1f} MB (more than 0.1 MB): the page loads slowly"]


class _FakeState:
    def __init__(self, packets):
        self.packets = packets

    def to_json(self):
        edges = {"route:route1": {"points": [], "length_um": 1.0, "group_index": 1.5, "packets": self.packets,
                                  "cw": []}}
        return {"version": 1, "mode": "pulse", "duration_ps": 1.0, "edges": edges, "exits": [], "absorbed": [],
                "warnings": []}


def _packet(nm):
    return {"from": "a", "to": "b", "t0": 0.0, "t1": 1.0, "jones": [1, 0, 0, 0], "wavelength_nm": nm,
            "width": 0.2, "source": "a"}


def test_explicit_empty_inputs_on_a_scene_without_a_source_give_a_disabled_payload():
    scene = Scene()
    scene.add(build_component("Lens"))
    payload = build_light_payload(scene, inputs=[])
    assert payload["enabled"] is False and payload["notices"] and payload["pulse"]["edges"] == {}


def test_params_reach_the_engine_and_change_the_packets():
    scene = build_preset("ring_resonator_chip")
    base = build_light_payload(scene)
    shifted = build_light_payload(scene, params={"phase:coupledringfilter1": 2.0})
    assert shifted["pulse"] != base["pulse"]


@pytest.fixture
def no_fronts(monkeypatch):
    """These tests fake the engine with an input the arrival fronts cannot read: no crossing, no display pulse, no
    steady state."""

    monkeypatch.setattr("optodraw.animation3d.payload._crossing_ps", lambda *args: 0.0)
    monkeypatch.setattr("optodraw.animation3d.payload._cw",
                        lambda scene, params, inputs, pulse, graph, rails, hidden, *rest: (_empty_cw(), [], list(hidden)))


def test_params_are_passed_to_the_engine_unchanged(monkeypatch, no_fronts):
    seen = {}

    def spy(scene, **kwargs):
        seen.update(kwargs)
        return _FakeState([_packet(1550.0)])

    monkeypatch.setattr("optodraw.animation3d.payload.compile_signal_state", spy)
    build_light_payload(Scene(), params={"phase:x": 1.0}, inputs=[object()])
    assert seen["params"] == {"phase:x": 1.0} and seen["mode"] == "pulse"


def test_light_without_packets_says_why(monkeypatch, no_fronts):
    monkeypatch.setattr("optodraw.animation3d.payload.compile_signal_state", lambda *a, **k: _FakeState([]))
    payload = build_light_payload(Scene(), inputs=[object()])
    assert payload["enabled"] is False and "no light reaches any path" in payload["notices"]


def test_more_channels_than_palette_colours_gives_a_notice(monkeypatch, no_fronts):
    packets = [_packet(1500.0 + k) for k in range(len(CHANNEL_PALETTE) + 2)]
    monkeypatch.setattr("optodraw.animation3d.payload.compile_signal_state", lambda *a, **k: _FakeState(packets))
    payload = build_light_payload(Scene(), inputs=[object()])
    assert f"{len(packets)} channels share colours: the palette has {len(CHANNEL_PALETTE)}" in payload["notices"]


def test_other_runtime_warnings_still_reach_the_caller(monkeypatch, no_fronts):
    import warnings

    def noisy(*args, **kwargs):
        warnings.warn("overflow in something", RuntimeWarning)
        return _FakeState([_packet(1550.0)])

    monkeypatch.setattr("optodraw.animation3d.payload.compile_signal_state", noisy)
    with pytest.warns(RuntimeWarning, match="overflow"):
        build_light_payload(Scene(), inputs=[object()])


def test_the_unconnected_port_warning_stays_inside_the_payload_builder():
    scene = build_preset("ring_resonator_chip")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_light_payload(scene)


def test_the_time_scale_is_in_the_payload_and_the_caption_comes_from_it():
    payload = build_light_payload(build_preset("ring_resonator_chip"))
    first = {}
    for end in payload["pulse"]["exits"] + payload["pulse"]["absorbed"]:
        key = (end["part"], end["port"])
        first[key] = min(first.get(key, end["t_ps"]), end["t_ps"])
    crossing = max(first.values())                      # the first light reaches its last end (it starts at 0)
    assert payload["seconds_per_ps"] * crossing == pytest.approx(3.0)
    assert payload["captions"][0] == "Time slowed so light crosses the circuit in about 3 s"
    assert build_light_payload(Scene(), inputs=[])["seconds_per_ps"] == 0.0


def test_the_display_pulse_is_an_eighth_of_the_crossing_and_the_caption_says_it():
    payload = build_light_payload(build_preset("ring_resonator_chip"))
    crossing = 3.0 / payload["seconds_per_ps"]
    assert payload["pulse_ps"] == pytest.approx(crossing / 8)
    widths = {p["width"] for edge in payload["pulse"]["edges"].values() for p in edge["packets"]}
    assert widths == {payload["pulse_ps"]}                                  # the engine's own pulse, not a JS stretch
    assert payload["captions"][1] == "Pulse 0.75 ps long, shown at 0.5 s per ps"


def _laser_bench():
    from optodraw import Beam, Laser, Photodiode

    scene = Scene()
    laser = scene.add(Laser(center=(0, 0)))
    pd = scene.add(Photodiode(center=(60, 0)))
    scene.add(Beam(laser, pd))
    return scene


def test_a_source_gets_the_display_pulse_unless_the_caller_set_its_width():
    payload = build_light_payload(_laser_bench())
    widths = {p["width"] for edge in payload["pulse"]["edges"].values() for p in edge["packets"]}
    assert widths == {payload["pulse_ps"]} and payload["pulse_ps"] != 0.2
    chosen = build_light_payload(_laser_bench(), params={"width:laser1": 0.5})
    assert {p["width"] for edge in chosen["pulse"]["edges"].values() for p in edge["packets"]} == {0.5}
    assert chosen["captions"][1].startswith("Pulse 0.5 ps long")


def test_an_explicit_input_keeps_its_own_pulse_width():
    scene = build_preset("ring_resonator_chip")
    (found,), _ = default_inputs(scene)
    payload = build_light_payload(scene, inputs=[dataclasses.replace(found, width_ps=0.3)])
    assert {p["width"] for edge in payload["pulse"]["edges"].values() for p in edge["packets"]} == {0.3}


def test_several_pulse_widths_are_each_named_in_the_caption():
    from optodraw import Beam, Laser, Photodiode

    scene = Scene()
    for k, y in enumerate((0, 40)):
        laser = scene.add(Laser(center=(0, y)))
        pd = scene.add(Photodiode(center=(60, y)))
        scene.add(Beam(laser, pd))
    payload = build_light_payload(scene, params={"width:laser1": 0.3, "width:laser2": 0.5})
    assert payload["captions"][1].startswith("Pulses 0.3 and 0.5 ps long, shown at ")
    assert payload["pulse_ps"] == 0.5


_MMI_NOTICE = "{sid}: MMI length is not its self-imaging length; the split shown is the engine's"


@pytest.mark.parametrize("ctype,kwargs,sid,notice", [
    ("MMI1x2", {}, "mmi1x21", False),
    ("MMI1x4", {}, "mmi1x41", False),                       # default MMIs are schematic: no notice
    ("MMI2x2", {}, "mmi2x21", False),
    ("MMI1x2", {"body_length": 12.0}, "mmi1x21", True),     # the user set an off length
    ("MMI1x2", {"body_length": 5.7}, "mmi1x21", False),     # the user set a length within 5 percent (5.75)
    ("MMI1x4", {"body_width": 5.0}, "mmi1x41", True)])      # the user set a width: 9.6 against 11.5
def test_an_mmi_off_its_self_imaging_length_gives_the_notice(ctype, kwargs, sid, notice):
    scene = Scene()
    scene.add(build_component(ctype, **kwargs))
    notices = build_light_payload(scene)["notices"]
    assert (_MMI_NOTICE.format(sid=sid) in notices) is notice


def _power(packet) -> float:
    return sum(v * v for v in packet["jones"])


def _rails_of(payload, sid):
    """``{(section, rail): drawing}`` of the rails of ``sid`` in the payload."""

    return {(d["section"], d["rail"]): d for d in payload["rails"] if d["host"] == sid}


def _near_rails(points, rails, half) -> bool:
    from shapely.geometry import Point

    return all(min(rail.distance(Point(p)) for rail in rails) <= half for p in points)


def test_coupled_light_grows_along_the_coupler_on_both_rails_and_never_crosses_the_gap():
    """A 0.3 coupler lit at o1: its o1 rail starts at the input's power and ends at the engine's 0.7, its o2 rail grows
    from nothing to the engine's 0.3, every drawn point lies on a rail (within half the guide width), never in the gap,
    and the engine's two transfers are not drawn as well."""

    from shapely.geometry import LineString

    from optodraw.animation_engine.behaviours.geometry import optical_path_points

    scene = Scene()
    coupler = scene.add(build_component("DirectionalCoupler"))
    coupler.coupling_ratio = 0.3
    payload = build_light_payload(scene)
    edges = payload["pulse"]["edges"]
    bar, cross = "path:directionalcoupler1:o1->o3", "path:directionalcoupler1:o1->o4"
    assert _power(edges[cross]["packets"][0]) == pytest.approx(0.3, abs=1e-6)
    assert {bar, cross} <= set(payload["hidden"]) and bar not in payload["profiles"]
    lit = {key: d for key, d in _rails_of(payload, "directionalcoupler1").items() if d["packets"]}
    (section,) = {key[0] for key in lit}
    (on_input,), (on_other,) = lit[section, 0]["packets"], lit[section, 1]["packets"]
    assert on_input["power"][0] == pytest.approx(1.0, abs=1e-6) and on_input["power"][-1] == pytest.approx(0.7, abs=1e-6)
    assert on_other["power"][0] == pytest.approx(0.0, abs=1e-9) and on_other["power"][-1] == pytest.approx(0.3, abs=1e-6)
    assert all(b >= a - 1e-7 for a, b in zip(on_other["power"], on_other["power"][1:]))     # it only grows
    rails = [LineString(path) for port in ("o1", "o2") for path in optical_path_points(coupler, port)[
        "o3" if port == "o1" else "o4"]]
    for key in lit:
        points = lit[key]["points"]
        assert len(points) == len(lit[key]["packets"][0]["power"]) > 10
        assert _near_rails(points, rails, coupler.waveguide_width / 2.0 + 1e-6), key


def _mzm_between_two_routes():
    scene = Scene()
    left = scene.add(build_component("VerticalGratingCoupler", center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    right = scene.add(build_component("VerticalGratingCoupler", center=(150, 0), angle=180))
    scene.route((left, "o1"), (mzm, "o1"))
    scene.route((mzm, "o3"), (right, "o1"))
    return scene


def test_an_mzm_draws_its_input_stem_at_the_input_power_and_its_output_stem_at_the_engines_output():
    """A Y-branch MZM is drawn by its stages: the input stem at the power that comes in, each arm at half of it, and
    the output stem at the coherent sum the engine sends on; its arm transfers are not drawn as well."""

    payload = build_light_payload(_mzm_between_two_routes(), params={"drive:mzm1": 1.0})
    edges = payload["pulse"]["edges"]
    (into,), (out,) = edges["route:route1"]["packets"], edges["route:route2"]["packets"]
    assert {"path:mzm1:o1->o3#arm1", "path:mzm1:o1->o3#arm2"} <= set(payload["hidden"])
    lit = {key: d["packets"] for key, d in _rails_of(payload, "mzm1").items() if d["packets"]}
    assert sorted(lit) == [(0, 0), (0, 1), (0, 2), (1, 0)]                   # stem and two arms; the output stem
    assert lit[0, 0][0]["power"][0] == pytest.approx(_power(into), rel=1e-6)
    for arm in (1, 2):
        assert lit[0, arm][0]["power"] == pytest.approx([0.5 * _power(into)] * len(lit[0, arm][0]["power"]), rel=1e-6)
    assert lit[1, 0][0]["power"][-1] == pytest.approx(_power(out), rel=1e-6)
    assert _power(out) == pytest.approx(0.5 * _power(into), rel=1e-6)          # cos^2 of a quarter turn


def test_the_payload_carries_the_total_source_power():
    from optodraw.animation_engine.inputs import InputSignal

    scene = build_preset("ring_resonator_chip")
    (found,), _ = default_inputs(scene)
    assert build_light_payload(scene)["source_power"] == pytest.approx(1.0)
    dim = build_light_payload(scene, inputs=[InputSignal(found.target, jones=(0.5, 0.0, 0.0, 0.0))])
    assert dim["source_power"] == pytest.approx(0.25)
    assert build_light_payload(_laser_bench())["source_power"] > 0


@pytest.mark.parametrize("ctype,setting", [("DirectionalCoupler", "coupling_ratio"), ("MicroringResonator", "power_coupling")])
def test_a_coupler_that_sends_all_its_light_across_still_shows_it_coming_in(ctype, setting):
    """Power coupling 1: the bar transfer carries nothing, yet the input rail starts at o1 with the input's power, and
    every drawn point lies on a rail."""

    from shapely.geometry import LineString

    from optodraw.animation_engine.behaviours.geometry import optical_path_points, port_xy

    scene = Scene()
    part = scene.add(build_component(ctype))
    setattr(part, setting, 1.0)
    payload = build_light_payload(scene)
    sid = next(iter(payload["pulse"]["edges"])).split(":")[1]
    assert payload["source_power"] == pytest.approx(1.0)
    at_input = [d for d in payload["rails"] if d["host"] == sid and d["packets"]
                and abs(d["points"][0][0] - port_xy(part, "o1")[0]) + abs(d["points"][0][1] - port_xy(part, "o1")[1]) < 1e-3]
    assert sum(p["power"][0] for d in at_input for p in d["packets"]) == pytest.approx(1.0, rel=1e-6)
    rails = [LineString(path) for port in part.ports() for paths in optical_path_points(part, port).values()
             for path in paths if len(path) >= 2]
    half = 0.5 * max(float(p.width) for p in part.ports().values()) + 1e-6
    for d in payload["rails"]:
        assert _near_rails(d["points"], rails, half), (d["section"], d["rail"])


def _chain(k1, k2):
    """Two couplers joined by equal routes (power couplings ``k1`` then ``k2``), with a grating at each end."""

    scene = Scene()
    source = scene.add(build_component("VerticalGratingCoupler", center=(-150, 7)))
    first = scene.add(build_component("DirectionalCoupler", center=(0, 0)))
    second = scene.add(build_component("DirectionalCoupler", center=(100, 0)))
    first.coupling_ratio, second.coupling_ratio = k1, k2
    up = scene.add(build_component("VerticalGratingCoupler", center=(250, 7), angle=180))
    down = scene.add(build_component("VerticalGratingCoupler", center=(250, -7), angle=180))
    scene.route((source, "o1"), (first, "o1"))
    scene.route((first, "o3"), (second, "o1"))
    scene.route((first, "o4"), (second, "o2"))
    scene.route((second, "o3"), (up, "o1"))
    scene.route((second, "o4"), (down, "o1"))
    return scene


def _between_gratings(ctype, **options):
    """``ctype`` lit from a grating at o1, with a grating on each output on the far side."""

    scene = Scene()
    left = scene.add(build_component("VerticalGratingCoupler", center=(-250, 0)))
    part = scene.add(build_component(ctype, center=(0, 0), **options))
    scene.route((left, "o1"), (part, "o1"))
    outs = sorted(n for n, p in part.ports().items() if p.kind != "electrical" and p.center.x > 1e-6)
    for k, name in enumerate(outs):
        grating = scene.add(build_component("VerticalGratingCoupler", center=(250, 30 * (k - 0.5) * (len(outs) > 1)),
                                            angle=180))
        scene.route((part, name), (grating, "o1"))
    return scene


def _route_powers(payload, sid):
    """The engine's light leaving the ports of ``sid`` on routes: ``[(port, wavelength, time, power)]``, one per
    packet (the time at the port)."""

    return [(p["from"].split(":")[2], p["wavelength_nm"], p["t0"], _power(p))
            for eid, edge in payload["pulse"]["edges"].items() if eid.startswith("route:")
            for p in edge["packets"] if p["from"].startswith(f"port:{sid}:")]


def _rail_ends(payload, scene, sid):
    """The light the rails of ``sid`` draw where they end at a port: ``[(port, wavelength, time, power)]``, one per
    rail packet. A rail's port is the port at its last point (none: the rail ends inside the part)."""

    import math

    from optodraw.animation_engine.graph import build_graph

    part = build_graph(scene).parts[sid]
    ports = {name: (float(part.world_port(name).center.x), float(part.world_port(name).center.y))
             for name, port in part.ports().items() if port.kind != "electrical"}
    found = []
    for d in payload["rails"]:
        if d["host"] != sid:
            continue
        at = [name for name, xy in ports.items() if math.dist(xy, d["points"][-1]) < 1e-3]
        found += [(at[0], p["wavelength_nm"], p["t1"], p["power"][-1]) for p in d["packets"]] if at else []
    return found


def _same_exit(a, b) -> bool:
    return a[0] == b[0] and a[1] == b[1] and abs(a[2] - b[2]) < 1e-6


def assert_rail_ends_match_the_routes(payload, scene, sid):
    """Each light that leaves ``sid`` on a route (port, wavelength, time) is the light its rails draw there, within
    1 %, and no rail draws light at a port where the engine sends none (above the engine's floor: it drops what
    leaves a port with less than 1e-3 of the source power)."""

    drawn, leaving = _rail_ends(payload, scene, sid), _route_powers(payload, sid)
    assert leaving, f"no light leaves {sid}"
    for exit_ in leaving:
        total = sum(end[3] for end in drawn if _same_exit(end, exit_))
        assert total == pytest.approx(exit_[3], rel=0.01, abs=1e-6), (sid, exit_)
    for end in drawn:
        if end[3] > 1e-3 * payload["source_power"]:
            assert any(_same_exit(end, exit_) for exit_ in leaving), (sid, end)


def test_a_coupler_lit_at_both_inputs_draws_the_coherent_field_on_each_rail():
    """mzm_mesh_chip's directionalcoupler4 takes light at both inputs; the engine adds them coherently. Each rail's end
    draws the power of the route that leaves it, not each input's split on its own."""

    scene = build_preset("mzm_mesh_chip")
    payload = build_light_payload(scene)
    edges = payload["pulse"]["edges"]
    assert {e.split("->")[0] for e in edges if e.startswith("path:directionalcoupler4:")} == {
        "path:directionalcoupler4:o1", "path:directionalcoupler4:o2"}
    leaving = {port: power for port, _, _, power in _route_powers(payload, "directionalcoupler4")}
    assert set(leaving) == {"o3", "o4"} and abs(leaving["o3"] - leaving["o4"]) > 0.3       # a real interference
    assert_rail_ends_match_the_routes(payload, scene, "directionalcoupler4")


def test_two_couplers_in_a_row_cancel_on_one_rail_and_add_on_the_other():
    """Two 50 : 50 couplers joined by equal routes: the second is lit at both inputs in phase; its o3 rail ends dark and
    its o4 rail carries all the light, as the engine says."""

    scene = _chain(0.5, 0.5)
    payload = build_light_payload(scene)
    drawn = {}
    for port, _, _, power in _rail_ends(payload, scene, "directionalcoupler2"):
        drawn[port] = drawn.get(port, 0.0) + power
    leaving = {port: power for port, _, _, power in _route_powers(payload, "directionalcoupler2")}
    assert drawn["o3"] == pytest.approx(0.0, abs=1e-6) and "o3" not in leaving
    assert drawn["o4"] == pytest.approx(leaving["o4"], rel=0.01) and leaving["o4"] == pytest.approx(0.5, rel=1e-6)


RAIL_END_CASES = {                     # label: (scene, params, coupling part)
    "mesh dc4": (lambda: build_preset("mzm_mesh_chip"), {}, "directionalcoupler4"),
    "chain 0.3 0.9 first": (lambda: _chain(0.3, 0.9), {}, "directionalcoupler1"),
    "chain 0.3 0.9 second": (lambda: _chain(0.3, 0.9), {}, "directionalcoupler2"),
    "chain 0.5 1.0 second": (lambda: _chain(0.5, 1.0), {}, "directionalcoupler2"),
    "MZI 0 mW": (lambda: _between_gratings("MZI"), {}, "mzi1"),
    "MZI 5 mW": (lambda: _between_gratings("MZI"), {"heater:mzi1": 5.0}, "mzi1"),
    "MZI 13 mW": (lambda: _between_gratings("MZI"), {"heater:mzi1": 13.0}, "mzi1"),
    "MZM coupler": (lambda: _between_gratings("MZM", splitter="coupler"), {"drive:mzm1": 0.6}, "mzm1"),
    "MZM branch_coupler": (lambda: _between_gratings("MZM", splitter="branch_coupler"), {"drive:mzm1": 0.6}, "mzm1"),
    "MZM": (lambda: _between_gratings("MZM"), {"drive:mzm1": 0.6}, "mzm1")}


@pytest.mark.parametrize("scene,params,sid", [pytest.param(*case, id=label) for label, case in RAIL_END_CASES.items()])
def test_every_rail_end_draws_the_light_that_leaves_there(scene, params, sid):
    scene = scene()
    assert_rail_ends_match_the_routes(build_light_payload(scene, params=params), scene, sid)


@functools.lru_cache(maxsize=None)
def _preset_payload(name):
    return build_light_payload(build_preset(name))


def _section_inputs(payload, scene, params):
    """``{(sid, section): [input power per bucket]}``: what comes into each coupling section of the payload's rails."""

    from optodraw.animation3d.rails import buckets
    from optodraw.animation_engine.behaviours import find_behaviour
    from optodraw.animation_engine.graph import build_graph
    from optodraw.animation_engine.signals import power

    graph, found = build_graph(scene), {}
    for sid in sorted({d["host"] for d in payload["rails"]}):
        part = graph.parts[sid]
        for index, section in enumerate(find_behaviour(part).sections(part, sid, params)):
            if section.kappa is not None:
                found[sid, index] = [sum(power(f) for f in b["fields"]) for b in buckets(section, payload["pulse"])]
    return found


def _lit_preset(name):
    return build_preset(name), _preset_payload(name)


INVARIANT_CASES = {name: (lambda name=name: _lit_preset(name)) for name in (
    "ring_resonator_chip", "coherent_receiver_chip", "mzm_mesh_chip", "wdm_delay_weight_bank_chip")}
INVARIANT_CASES |= {f"chain {k1} {k2}": (lambda k1=k1, k2=k2: (_chain(k1, k2), build_light_payload(_chain(k1, k2))))
                    for k1, k2 in ((0.3, 0.9), (0.5, 1.0))}


@pytest.mark.parametrize("label", sorted(INVARIANT_CASES))
def test_at_every_point_of_a_coupling_section_its_two_rails_carry_its_input_power(label):
    """Every coupling section that light reaches: at each sample of the two windows, per engine bucket, the rail
    powers add up to the power that comes into the section (within 1e-6). Losses act only after the window."""

    scene, payload = INVARIANT_CASES[label]()
    inputs = _section_inputs(payload, scene, payload["cw"]["params"])
    rails = {}
    for d in payload["rails"]:
        rails.setdefault((d["host"], d["section"]), {})[d["rail"]] = d
    checked = 0
    for key, into in inputs.items():
        if not into:
            continue
        a, b = rails[key][0], rails[key][1]
        assert len(a["packets"]) == len(b["packets"]) == len(into), key
        (a0, a1), (b0, b1) = a["window"], b["window"]
        for pa, pb, power_in in zip(a["packets"], b["packets"], into):
            for va, vb in zip(pa["power"][a0:a1 + 1], pb["power"][b0:b1 + 1], strict=True):
                assert va + vb == pytest.approx(power_in, abs=1e-6), key
        checked += 1
    assert checked, f"{label}: no coupling section is lit"


def test_the_weight_bank_payload_stays_under_5_mb():
    assert _page_bytes(_preset_payload("wdm_delay_weight_bank_chip")) < 5_000_000


def _around(ctype, lit="o1", setup=None, **options):
    """``ctype`` with a grating on every optical port, routed in at ``lit`` and out at the others (the default input
    lights the first grating, on the first port). ``setup`` takes the part and may change it."""

    scene = Scene()
    part = scene.add(build_component(ctype, center=(0, 0), **options))
    if setup is not None:
        setup(part)
    names = sorted(n for n, p in part.ports().items() if p.kind != "electrical")
    for k, name in enumerate(names):
        centre = part.ports()[name].center
        side = 1 if centre.x >= 0 else -1
        grating = scene.add(build_component("VerticalGratingCoupler", center=(centre.x + side * 120, centre.y * 3 + 40 * k),
                                            angle=0 if side < 0 else 180))
        if name == lit:
            scene.route((grating, "o1"), (part, name))
        else:
            scene.route((part, name), (grating, "o1"))
    return scene


def _coupler(ratio):
    return _around("DirectionalCoupler", setup=lambda part: setattr(part, "coupling_ratio", ratio))


# label: (scene, params, the part whose rails end at its ports): the corners where a coupling factor is 0
BOUNDARY_CASES = {
    "coupler kappa 0": (lambda: _coupler(0.0), {}, "directionalcoupler1"),
    "coupler kappa 1": (lambda: _coupler(1.0), {}, "directionalcoupler1"),
    "chain 0.5 0.0": (lambda: _chain(0.5, 0.0), {}, "directionalcoupler2"),
    "ring filter c0 1": (lambda: _around("CoupledRingFilter"), {"power_coupling:coupledringfilter1:c0": 1.0},
                         "coupledringfilter1"),
    "add-drop drop 0": (lambda: _around("MicroringResonator", add_drop=True),
                        {"drop_power_coupling:microringresonator1": 0.0}, "microringresonator1"),
    "add-drop kappa 1": (lambda: _around("MicroringResonator", add_drop=True),
                         {"power_coupling:microringresonator1": 1.0}, "microringresonator1"),
    "all-pass kappa 1": (lambda: _around("MicroringResonator"), {"power_coupling:microringresonator1": 1.0},
                         "microringresonator1"),
    "ring-assisted MZI": (lambda: _between_gratings("RingAssistedMZI"), {}, "ringassistedmzi1")}


@pytest.mark.parametrize("scene,params,sid", [pytest.param(*case, id=label) for label, case in BOUNDARY_CASES.items()])
def test_at_a_coupling_of_0_or_1_every_rail_end_still_draws_the_light_that_leaves_there(scene, params, sid):
    """An input read through a transfer that carries nothing is read through the one that carries it, so no input is
    lost where a coupler sends all its light across or none."""

    scene = scene()
    payload = build_light_payload(scene, params=params)
    assert_rail_ends_match_the_routes(payload, scene, sid)
    into = {port: power for port, _, _, power in _route_arrivals(payload, sid)}
    drawn = {port: power for port, _, _, power in _rail_starts(payload, scene, sid)}
    assert into and all(drawn.get(port, 0.0) == pytest.approx(power, rel=0.01) for port, power in into.items()), (into, drawn)


def _route_arrivals(payload, sid):
    return [(p["to"].split(":")[2], p["wavelength_nm"], p["t1"], _power(p))
            for eid, edge in payload["pulse"]["edges"].items() if eid.startswith("route:")
            for p in edge["packets"] if p["to"].startswith(f"port:{sid}:")]


def _rail_starts(payload, scene, sid):
    """The light the rails of ``sid`` draw where they start at a port, summed per port's first packet."""

    import math

    from optodraw.animation_engine.graph import build_graph

    part = build_graph(scene).parts[sid]
    ports = {name: (float(part.world_port(name).center.x), float(part.world_port(name).center.y))
             for name, port in part.ports().items() if port.kind != "electrical"}
    found = []
    for d in payload["rails"]:
        at = [name for name, xy in ports.items() if d["host"] == sid and math.dist(xy, d["points"][0]) < 1e-3]
        found += [(at[0], p["wavelength_nm"], p["t0"], p["power"][0]) for p in d["packets"][:1]] if at else []
    return found


def _end_ports(scene, params, hosts):
    """``{(sid, section, rail): engine port}`` for every rail whose drawn end is an engine port: a read of the section
    ends there, on that rail, at the rail's last drawn arc length."""

    from optodraw.animation_engine.behaviours import find_behaviour
    from optodraw.animation_engine.graph import build_graph

    graph, found = build_graph(scene), {}
    for sid in hosts:
        part = graph.parts[sid]
        for index, section in enumerate(find_behaviour(part).sections(part, sid, params)):
            for read in (read for reads in section.inputs for read in reads):
                rail, arc = read.end
                if abs(arc - section.rails[rail].draw[1]) < 1e-6:
                    found[sid, index, rail] = read.port
    return found


def _arrivals(payload):
    """The engine's light that arrives at each port, per wavelength: ``{(sid, port, nm): [(time, jones, bucket)]}``, one
    entry per packet (on a route or a transfer) that ends there, also where the engine then drops it. ``bucket`` is the
    engine's bucket the light joined as it left that port (the light the engine added and sent on together); None for
    light that arrives on a route."""

    from optodraw.animation_engine.signals import from_json

    found: dict = {}
    for edge in payload["pulse"]["edges"].values():
        for p in edge["packets"]:
            _, sid, port = p["to"].split(":")
            found.setdefault((sid, port, p["wavelength_nm"]), []).append((p["t1"], from_json(p["jones"]), p.get("bucket")))
    return found


def _engine_light(arrivals, port, nm, times, tol, whole=False):
    """The power of the engine's fields that arrive at ``port`` at these instants (each within ``tol``), added. With
    ``whole`` (the light a packet going on holds): the engine's whole buckets of the light that arrives at the first of
    these instants that has any, the coherent sum of every field that carries one of those bucket ids (later trips
    within the pulse included)."""

    import numpy as np

    from optodraw.animation_engine.signals import power

    found = arrivals.get((*port, nm), [])
    near = [entry for t in times for entry in found if abs(entry[0] - t) <= tol]
    if whole:                       # the buckets of the light at the first of these instants that has any
        first = next((t for t in sorted(times) if any(abs(entry[0] - t) <= tol for entry in found)), None)
        near = [entry for entry in found if first is not None and abs(entry[0] - first) <= tol]
        joined = {bucket for _, _, bucket in near if bucket is not None}
        near = [entry for entry in near if entry[2] is None] + [entry for entry in found if entry[2] in joined]
    return power(sum((jones for _, jones, _ in near), np.zeros(2, complex)))


def _meeting_places(payload, scene, params):
    """Where drawn light meets, on the parts that have coupling sections: ``[(place, [event])]``. An event is
    ``(time, power, wavelength, +1 coming in or -1 going on, width, on a rail, port)``: routes arriving and leaving,
    section rails ending and starting, plain part edges ending and starting, exits and absorbers. The port is the
    engine port ``(sid, name)`` the event is at, when it is known: a route's, an exit's or an absorber's port, or the
    port at a rail's drawn end (``_end_ports``); None elsewhere."""

    import math

    from optodraw.animation_engine.graph import build_graph

    graph = build_graph(scene)
    hosts, hidden, edges = {d["host"] for d in payload["rails"]}, set(payload["hidden"]), payload["pulse"]["edges"]
    ends = _end_ports(scene, params, hosts)
    places: list = []

    def add(at, *event):
        place = next((p for p in places if math.dist(p[0], at) < 1e-3), None)
        if place is None:
            place = (tuple(at), [])
            places.append(place)
        place[1].append(event)

    def port(sid, name):
        centre = graph.parts[sid].world_port(name).center
        return float(centre.x), float(centre.y)

    for eid, edge in edges.items():
        for p in edge["packets"]:
            if eid.startswith("route:"):
                (_, a, out), (_, b, into) = p["from"].split(":"), p["to"].split(":")
                if a in hosts:
                    add(port(a, out), p["t0"], _power(p), p["wavelength_nm"], -1, p["width"], False, (a, out))
                if b in hosts:
                    add(port(b, into), p["t1"], _power(p), p["wavelength_nm"], +1, p["width"], False, (b, into))
            elif eid.startswith("path:") and eid.split(":")[1] in hosts and eid not in hidden:
                add(edge["points"][0], p["t0"], _power(p), p["wavelength_nm"], -1, p["width"], False, None)
                add(edge["points"][-1], p["t1"], _power(p), p["wavelength_nm"], +1, p["width"], False, None)
    for d in payload["rails"]:
        end = ends.get((d["host"], d["section"], d["rail"]))
        for p in d["packets"]:
            add(d["points"][0], p["t0"], p["power"][0], p["wavelength_nm"], -1, p["width"], True, None)
            add(d["points"][-1], p["t1"], p["power"][-1], p["wavelength_nm"], +1, p["width"], True,
                (d["host"], end) if end else None)
    for record in payload["pulse"]["exits"]:
        if record["part"] in hosts:
            add(port(record["part"], record["port"]), record["t_ps"], record["power"], record["wavelength_nm"], -1,
                record["width"], False, (record["part"], record["port"]))
    for record in payload["pulse"]["absorbed"]:
        if record["part"] in hosts:
            into = next(e for e in edges if e.startswith(f"path:{record['part']}:")
                        and e.split("->")[1].split("#")[0] == record["port"])
            add(edges[into]["points"][-1], record["t_ps"], record["power"], record["wavelength_nm"], -1, 0.0, False,
                (record["part"], record["port"]))
    return places


def _coherent(powers) -> tuple[float, float]:
    """The least and the most power that fields of these powers give when they add."""

    import math

    roots = sorted(math.sqrt(p) for p in powers)
    return max(0.0, roots[-1] - sum(roots[:-1])) ** 2, sum(roots) ** 2


def _slack(payload, floor=1e-3):
    """Light below the engine's floor: 1e-3 of its source's power (the sources taken as equal)."""

    sources = {p["source"] for edge in payload["pulse"]["edges"].values() for p in edge["packets"]}
    return floor * (payload["source_power"] or 1.0) / max(len(sources), 1)


def unbalanced_meetings(payload, scene, floor=1e-3, params=None):
    """Where the drawn light does not add up: at each place where a section rail starts or ends, per wavelength. Events
    within a twentieth of a pulse width are one instant. An instant passes when one of these holds:

    1. The light that comes in goes on with the same power (1 % plus the slack).
    2. It joins another instant. Light at an instant with nothing on the other side joins the last earlier instant of
       the other side within a pulse width, when that instant has light on both sides, or only light going on. (The
       engine adds what leaves one port within a pulse width and sends it at the first departure, so a drawn packet
       may hold light of later instants: light is drawn leaving before it arrives, never later.) Where the engine's
       port is known, only instants above the slack join. Where no port is known, faint instants join too, because no
       engine bucket can be read there (a ring rail that closes on itself).
    3. Where the port is known and the two sides differ, the engine's packets at the port decide, each within 1 % plus
       the slack. The light that comes in has the power of the engine's fields at its instants, added, with the
       instants the engine dropped (engine light with nothing drawn, held by the last earlier packet that comes in).
       The light that goes on has the power of the engine's fields at the instants it took in (the old rule), or the
       power of the engine's whole buckets of the light at the first of those instants that has light (every field
       with the same bucket id, later trips within the pulse included: the whole-bucket credit). At strong joints of
       the weight bank these two values differ, so a second value can pass there; the rail's other end still checks
       the whole packet. A joined instant holds its own light, or that light and the light the engine dropped after it.
    4. Where the port is not known, the two sides agree within the coherent bounds, ``(max root - other roots)^2`` to
       ``(sum of roots)^2``; so do two arms that meet at a Y-branch.

    Light below the slack (the engine's floor, 1e-3 of its source's power; the sources are taken as equal) needs no
    partner. A ring rail that goes once round starts and ends at one place, so this check cannot see it lose light;
    ``unconserved`` does."""

    slack, bad = _slack(payload, floor), []
    arrivals = _arrivals(payload)
    for place, events in _meeting_places(payload, scene, params or {}):
        if not any(e[5] for e in events):
            continue
        fed = any(e[3] > 0 for e in events)
        for nm in sorted({e[2] for e in events}):
            port = next((e[6] for e in events if e[2] == nm and e[6]), None)
            instants: list = []                       # [time, width, ins, outs, joined instants, dropped instants]
            for t, p, _, sign, width, _, _ in sorted((e for e in events if e[2] == nm), key=lambda e: e[0]):
                if not instants or t - instants[-1][0] > 0.05 * max(width, instants[-1][1]):
                    instants.append([t, width, [], [], [], []])
                instants[-1][1] = max(instants[-1][1], width)
                instants[-1][2 if sign > 0 else 3].append(p)
            merged = set()
            for i, (t, width, ins, outs, *_) in enumerate(instants):
                if (ins and outs) or (port and sum(ins + outs) <= slack):     # where no port is known, faint trips join too
                    continue
                j = next((j for j in range(i - 1, -1, -1) if j not in merged and instants[j][3 if ins else 2]), None)
                if j is None or t - instants[j][0] >= max(width, instants[j][1]):
                    continue
                if (instants[j][2] and instants[j][3]) or (ins and not instants[j][2]):
                    instants[j][4].append(i)
                    merged.add(i)
            seen = [instant[0] for instant in instants]
            for te in sorted(t for t, *_ in arrivals.get((*port, nm), [])) if port else ():
                if any(abs(te - ts) <= 0.05 * max(e[4] for e in events) for ts in seen):
                    continue
                seen.append(te)
                j = next((j for j in range(len(instants) - 1, -1, -1) if instants[j][0] < te and instants[j][2]), None)
                if j is not None and te - instants[j][0] < instants[j][1]:
                    instants[j][5].append(te)
            for i, (t, width, ins, outs, joined, dropped) in enumerate(instants):
                if i in merged:
                    continue
                more_ins = [p for j in joined for p in instants[j][2]]
                more_outs = [p for j in joined for p in instants[j][3]]
                come, go = sum(ins + more_ins), sum(outs + more_outs)
                if max(come, go) <= slack:
                    continue
                if not (ins or more_ins) or not (outs or more_outs):
                    if ins or fed:
                        bad.append((place, nm, t, "unpaired", ins, outs))
                    continue
                ok = abs(go - come) <= 0.01 * max(go, come) + slack
                if not ok and not joined and len(ins) > 1 and len(outs) == 1:
                    low, high = _coherent(ins)
                    ok = 0.99 * low - slack <= go <= 1.01 * high + slack
                elif (joined or not ok) and port:
                    tol = 0.05 * width

                    def matches(drawn, *engine):
                        return any(abs(drawn - e) <= 0.01 * max(drawn, e) + slack for e in engine)

                    def light(times, whole=False):
                        return _engine_light(arrivals, port, nm, times, tol, whole)

                    held = ([t] + [instants[j][0] for j in joined if instants[j][3]] + dropped,   # by the host's ins
                            [t] + [instants[j][0] for j in joined if instants[j][2]])             # by the host's outs
                    # light going on holds the instants it took in, or the engine's whole buckets (later trips too);
                    # a joined instant holds its own light, or that and the light the engine dropped after it
                    ok = matches(sum(ins), light(held[0])) and matches(sum(outs), light(held[1]), light(held[1], whole=True))
                    for j in joined:
                        tj, j_dropped = instants[j][0], instants[j][5]
                        ok = ok and matches(sum(instants[j][2] + instants[j][3]), light([tj]), light([tj] + j_dropped))
                elif joined:
                    many, one = (ins + more_ins, go) if len(ins + more_ins) > 1 else (outs + more_outs, come)
                    low, high = _coherent(many)
                    ok = 0.99 * low - slack <= one <= 1.01 * high + slack
                if not ok:
                    bad.append((place, nm, t, ins + more_ins, outs + more_outs))
    return bad


CONTINUITY_CASES = {name: (lambda name=name: _lit_preset(name)) for name in (
    "ring_resonator_chip", "coherent_receiver_chip", "mzm_mesh_chip", "wdm_delay_weight_bank_chip")}
CONTINUITY_CASES |= {label: (lambda case=case: (case[0](), build_light_payload(case[0](), params=case[1])))
                     for label, case in BOUNDARY_CASES.items()}
CONTINUITY_CASES |= {f"chain {k1} {k2}": (lambda k1=k1, k2=k2: (_chain(k1, k2), build_light_payload(_chain(k1, k2))))
                     for k1, k2 in ((0.3, 0.9), (0.5, 1.0))}
CONTINUITY_CASES["weight bank kappa 1"] = lambda: (build_preset("wdm_delay_weight_bank_chip"), build_light_payload(
    build_preset("wdm_delay_weight_bank_chip"), params={"power_coupling:microringweightbank1": 1.0}))
CONTINUITY_CASES["Y-branch MZM"] = lambda: (_between_gratings("MZM"), build_light_payload(_between_gratings("MZM"),
                                                                                          params={"drive:mzm1": 0.6}))


@functools.lru_cache(maxsize=None)
def _continuity(label):
    """A case, built once: two tests read it, and the weight bank's payload takes about 20 s."""

    return CONTINUITY_CASES[label]()


@pytest.mark.parametrize("label", sorted(CONTINUITY_CASES))
def test_drawn_light_goes_on_where_it_comes_in(label):
    """Each section's entry carries the light of the route or rail that feeds it, and each rail's end the light of the
    next section's entry or the route that leaves (``unbalanced_meetings``). This checks what the invariant cannot:
    the invariant takes a section's input from the same reads the rails use, so a lost input would still pass it."""

    scene, payload = _continuity(label)
    assert payload["rails"], f"{label}: nothing is drawn on rails"
    assert unbalanced_meetings(payload, scene, params=payload["cw"]["params"]) == []      # the params the payload used


def test_the_continuity_check_finds_a_lost_input():
    """The check itself: drop the light of one rail and it no longer adds up where that rail meets the route."""

    scene = _chain(0.5, 0.5)
    payload = build_light_payload(scene)
    rail = next(d for d in payload["rails"] if d["host"] == "directionalcoupler2" and d["packets"])
    rail["packets"] = [dict(p, power=[0.0] * len(p["power"])) for p in rail["packets"]]
    assert unbalanced_meetings(payload, scene)


def _late(payload, sid, by):
    """A copy of the payload with the rails of ``sid`` drawn ``by`` pulse widths late."""

    payload = copy.deepcopy(payload)
    for d in payload["rails"]:
        for p in d["packets"] if d["host"] == sid else ():
            p["t0"], p["t1"] = p["t0"] + by * p["width"], p["t1"] + by * p["width"]
    return payload


def _dimmed(payload, sid, section, rail, nm, index, factor):
    """A copy of the payload with the ``index``-th packet (in time) of one rail at ``nm`` drawn at ``factor`` of its
    power."""

    payload = copy.deepcopy(payload)
    drawing = next(d for d in payload["rails"] if (d["host"], d["section"], d["rail"]) == (sid, section, rail))
    packet = sorted((p for p in drawing["packets"] if p["wavelength_nm"] == nm), key=lambda p: p["t0"])[index]
    packet["power"] = [v * factor for v in packet["power"]]
    return payload


def _closed(rail):
    import math

    return math.dist(rail["points"][0], rail["points"][-1]) < 1e-3


@pytest.mark.parametrize("make,host,pick", [            # pick(rail, the arm rails of sections whose ring goes once round)
    (lambda: _between_gratings("RingAssistedMZI"), "ringassistedmzi1", lambda d, arm: (d["section"], d["rail"]) in arm),
    (lambda: build_preset("wdm_delay_weight_bank_chip"), "microringweightbank1", lambda d, arm: d["rail"] == 1)],  # a half ring
    ids=["ring-assisted MZI arm", "weight bank ring"])
def test_the_continuity_check_finds_a_lost_ring_rail_with_the_rings_on_resonance(make, host, pick):
    """The check credits light going on with the engine's whole buckets, and lets faint trips join where no port is
    known; a rail of a ring section that loses half its light is still found. (A ring rail that goes once round starts
    and ends at one place, so this check cannot see it lose light; ``unconserved`` does.)"""

    scene = make()
    payload = build_light_payload(scene)
    assert unbalanced_meetings(payload, scene, params=payload["cw"]["params"]) == []
    lit = [d for d in payload["rails"] if d["host"] == host and d["packets"]]
    rails = [d for d in lit if pick(d, {(r["section"], 0) for r in lit if _closed(r)})]
    assert rails
    rail = max(rails, key=lambda d: max(max(p["power"]) for p in d["packets"]))
    rail["packets"] = [dict(p, power=[0.5 * v for v in p["power"]]) for p in rail["packets"]]
    assert unbalanced_meetings(payload, scene, params=payload["cw"]["params"])


@pytest.mark.parametrize("by", [0.3, 0.8])
def test_the_continuity_check_finds_rails_drawn_late(by):
    """The check itself: the second coupler's rails drawn late by a fraction of the pulse no longer meet the routes
    that feed them, although every power still matches."""

    scene = _chain(0.5, 0.5)
    assert unbalanced_meetings(_late(build_light_payload(scene), "directionalcoupler2", by), scene)


@pytest.mark.parametrize("index,factor", [(0, 0.8), (1, 0.3)])
def test_the_continuity_check_finds_a_wrong_power_where_the_engine_merged_trips(index, factor):
    """The check itself, at a joint the engine merges: in the first weight bank, ring 3's bottom coupler reads its
    inputs at o2, where the engine added two trips into one bucket, so its ring rail ends with one packet where the
    top coupler's ring rail starts with a packet per trip. The first trip drawn at 0.8 of its power, or the second
    at 0.3, no longer adds up to the packet that holds them both."""

    scene, payload = _lit_preset("wdm_delay_weight_bank_chip")
    rails = _rails_of(payload, "microringweightbank1")
    assert rails[13, 1]["points"][0] == rails[12, 1]["points"][-1]
    trips = [p["t0"] for p in rails[13, 1]["packets"] if p["wavelength_nm"] == 1548.8][:2]
    assert trips[1] - trips[0] < rails[13, 1]["packets"][0]["width"]
    assert not any(abs(p["t1"] - trips[1]) < 1e-6 for p in rails[12, 1]["packets"])      # the second trip is merged
    assert unbalanced_meetings(_dimmed(payload, "microringweightbank1", 13, 1, 1548.8, index, factor), scene)


@pytest.mark.parametrize("label", sorted(CONTINUITY_CASES))
def test_every_coupling_section_that_light_reaches_is_drawn(label):
    """A section whose transfers carry light (above the engine's floor) draws it on its rails: no input is lost
    because it was read through a transfer that carries nothing or takes no time."""

    from optodraw.animation_engine.behaviours import find_behaviour
    from optodraw.animation_engine.graph import build_graph

    scene, payload = _continuity(label)
    graph, edges = build_graph(scene), payload["pulse"]["edges"]
    params = payload["cw"]["params"]
    drawn = {(d["host"], d["section"]) for d in payload["rails"] if d["packets"]}
    slack = 1e-3 * payload["source_power"]
    for sid in {eid.split(":")[1] for eid in payload["hidden"]}:
        part = graph.parts[sid]
        for index, section in enumerate(find_behaviour(part).sections(part, sid, params)):
            read = {eid for found in section.inputs for r in found for eid, _, _ in r.edges}
            lit = any(_power(p) > slack for eid in read for p in edges.get(eid, {"packets": []})["packets"])
            assert not lit or (sid, index) in drawn, (label, sid, index)


def test_the_arm_of_a_ring_assisted_mzi_carries_its_first_pass_past_the_ring():
    """The ring section reads the arm where the ring's own port keeps its trips apart; on the first pass the arm rail
    runs from the input coupler's power to the engine's arm power past the ring (its two output transfers)."""

    scene = _between_gratings("RingAssistedMZI")
    payload = build_light_payload(scene)
    edges = payload["pulse"]["edges"]
    rails = _rails_of(payload, "ringassistedmzi1")
    past = sum(_power(edges[f"path:ringassistedmzi1:_a0f0->{port}#arm1"]["packets"][0]) for port in ("o3", "o4"))
    (first, *_), arm_in = rails[1, 0]["packets"], rails[0, 0]["packets"][0]["power"][-1]
    assert past == pytest.approx(0.225, rel=0.01)
    assert first["power"][0] == pytest.approx(arm_in, rel=1e-6) and first["power"][-1] == pytest.approx(past, rel=0.01)


def test_a_coupler_that_sends_all_its_light_across_moves_at_the_speed_of_its_drawn_rails():
    """Coupling 1, light at one input: the input rail starts when the route arrives and takes the engine's time for
    the crossing transfer over the drawn rail (not over the crossing path's own length)."""

    import math

    scene = _coupler(1.0)
    payload = build_light_payload(scene)
    edges = payload["pulse"]["edges"]
    (arriving,) = [p for eid, e in edges.items() if eid.startswith("route:") for p in e["packets"]
                   if p["to"].startswith("port:directionalcoupler1:")]
    port = arriving["to"].split(":")[2]
    (crossing,) = [p for eid, e in edges.items() if eid.startswith(f"path:directionalcoupler1:{port}->")
                   for p in e["packets"] if _power(p) > 0.25]
    (start, *_), = [d["packets"] for d in payload["rails"] if d["host"] == "directionalcoupler1"
                    and math.dist(d["points"][0], _port_xy(scene, "directionalcoupler1", port)) < 1e-3]
    assert start["t0"] == pytest.approx(arriving["t1"], abs=1e-6)
    assert start["t1"] - start["t0"] == pytest.approx(crossing["t1"] - crossing["t0"], rel=1e-6)


def test_a_ring_at_coupling_1_draws_each_returning_trip_at_its_own_time():
    """The weight bank at power coupling 1, ring 0's bus coupler: the bus light crosses into the ring, and the ring's
    light crosses back onto the bus a trip later, less than half a pulse width after. The engine keeps the two apart
    (they leave by different ports), and so does the drawing: the bus light's packet ends with nothing on the bus,
    each returning trip's packet starts from nothing and ends when and as strong as the engine's packet that crosses
    onto the bus, and every bus-rail packet that ends with light is the start of the next rail at that time."""

    import math

    scene = build_preset("wdm_delay_weight_bank_chip")
    payload = build_light_payload(scene, params={"power_coupling:microringweightbank1": 1.0})
    rails = _rails_of(payload, "microringweightbank1")
    bus = rails[0, 0]
    (following,) = [d for key, d in rails.items() if key != (0, 0) and math.dist(d["points"][0], bus["points"][-1]) < 1e-3]
    floor = 1e-3 * payload["source_power"]
    packets = [p for p in bus["packets"] if p["wavelength_nm"] == 1548.8]
    (entering,) = [p for p in packets if p["power"][0] > floor]
    assert entering["power"][-1] == pytest.approx(0.0, abs=1e-9)
    returning = sorted(((p["t1"], p["power"][-1]) for p in packets if p["power"][-1] > floor), key=lambda e: e[0])
    crossing = payload["pulse"]["edges"]["path:microringweightbank1:_ring_bottom_f0->_lower_f1"]["packets"]
    engine = sorted((p["t1"], _power(p)) for p in crossing if p["wavelength_nm"] == 1548.8 and _power(p) > floor)
    assert len(returning) == len(engine) >= 1
    for (t, drawn), (t_engine, sent) in zip(returning, engine):
        assert t == pytest.approx(t_engine, abs=1e-6) and drawn == pytest.approx(sent, rel=1e-6)
        assert any(p["t0"] == pytest.approx(t, abs=1e-6) and p["power"][0] == pytest.approx(drawn, rel=1e-6)
                   for p in following["packets"]), t
    assert all(p["power"][0] == pytest.approx(0.0, abs=1e-9) for p in packets if p is not entering)


def _port_xy(scene, sid, port):
    from optodraw.animation_engine.graph import build_graph

    centre = build_graph(scene).parts[sid].world_port(port).center
    return float(centre.x), float(centre.y)


def test_an_mzi_coupler_section_takes_its_coupling_from_the_engines_coupler(monkeypatch):
    """The MZI's couplers in the drawing are the engine's: an uneven ``coupling`` changes the sections with it."""

    import math

    from optodraw.animation_engine.behaviours import find_behaviour
    from optodraw.animation_engine.behaviours.interferometers import MachZehnder

    def uneven(end, local, port, arm):
        if len(end) == 1:
            return 1.0 / math.sqrt(2.0)
        upper = local[port][1] >= max(local[n][1] for n in end)
        return math.sqrt(0.7) if upper == (arm == 0) else 1j * math.sqrt(0.3)

    monkeypatch.setattr(MachZehnder, "coupling", staticmethod(uneven))
    part = build_component("MZI")
    kappas = [section.kappa for section in find_behaviour(part).sections(part, "mzi1", {})]
    assert kappas and kappas == pytest.approx([0.3] * len(kappas))


def test_a_polarisation_splitter_stem_draws_the_power_that_comes_in():
    """A splitter's shared stem is drawn at the input's power, split by the input's own polarisation: a TE input to a
    polarisation splitter-rotator all goes to one output, so the stem is not drawn at twice the input."""

    scene = Scene()
    left = scene.add(build_component("VerticalGratingCoupler", center=(-250, 0)))
    part = scene.add(build_component("PolarizationSplitterRotator", center=(0, 0)))
    scene.route((left, "o1"), (part, "o1"))
    for k, name in enumerate(sorted(n for n, p in part.ports().items() if p.kind != "electrical" and p.center.x > 1e-6)):
        grating = scene.add(build_component("VerticalGratingCoupler", center=(250, 40 * (k - 0.5)), angle=180))
        scene.route((part, name), (grating, "o1"))
    payload = build_light_payload(scene)
    edges, profiles = payload["pulse"]["edges"], payload["profiles"]
    (into,) = [p for eid, e in edges.items() if eid.startswith("route:") for p in e["packets"]
               if p["to"].startswith("port:polarizationsplitterrotator1:")]
    stems = {eid: profile for eid, profile in profiles.items() if eid.startswith("path:polarizationsplitterrotator1:")}
    assert stems
    drawn = sum(profile["share"][0] * _power(p) for eid, profile in stems.items() for p in edges[eid]["packets"])
    assert drawn == pytest.approx(_power(into), rel=1e-6)


@pytest.mark.parametrize("k2", [1.0, 0.9])
def test_a_coupler_lit_at_both_inputs_draws_their_coherent_field_inside_the_window(k2):
    """Chain 0.5 then ``k2``: inside the second coupler's window each rail draws the coupled-mode field of the two
    fields that arrive (from the engine's routes), also at coupling 1, where the engine sends each input out on its
    own port: at F = 0.5 the rails then carry 0 and all of it."""

    import math

    import numpy as np

    from optodraw.animation3d.rails import layout
    from optodraw.animation_engine.behaviours import find_behaviour
    from optodraw.animation_engine.graph import build_graph
    from optodraw.animation_engine.signals import from_json

    scene = _chain(0.5, k2)
    payload = build_light_payload(scene)
    part = build_graph(scene).parts["directionalcoupler2"]
    into = {p["to"].split(":")[2]: from_json(p["jones"]) for eid, e in payload["pulse"]["edges"].items()
            if eid.startswith("route:") for p in e["packets"] if p["to"].startswith("port:directionalcoupler2:")}
    first = _port_xy(scene, "directionalcoupler2", "o1")
    section = next(s for s in find_behaviour(part).sections(part, "directionalcoupler2", {})
                   if math.dist(s.rails[0].points[0], first) < 1e-3)
    done = np.asarray(layout(section)[0]["done"])
    theta = math.asin(math.sqrt(k2))
    a = np.cos(theta * done)[:, None] * into["o1"] + 1j * np.sin(theta * done)[:, None] * into["o2"]
    b = 1j * np.sin(theta * done)[:, None] * into["o1"] + np.cos(theta * done)[:, None] * into["o2"]
    rails = {r: d for (s, r), d in _rails_of(payload, "directionalcoupler2").items() if d["packets"]
             and math.dist(d["points"][0], _port_xy(scene, "directionalcoupler2", "o1" if r == 0 else "o2")) < 1e-3}
    for r, want in ((0, a), (1, b)):
        drawn = np.sum([p["power"] for p in rails[r]["packets"]], axis=0)
        assert np.max(np.abs(drawn - np.sum(np.abs(want) ** 2, axis=1))) < 1e-4, r
    if k2 == 1.0:
        middle = int(np.argmin(np.abs(done - 0.5)))
        assert np.sum(np.abs(a[middle]) ** 2) == pytest.approx(0.0, abs=1e-3)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_weight_bank_payload_with_a_heater_and_a_drive_stays_under_5_mb():
    params = {"heater:microringweightbank1:ring2": 10.0, "drive:mzm1": 1.0}
    payload = build_light_payload(build_preset("wdm_delay_weight_bank_chip"), params=params, look="field")
    assert [h["sid"] for h in payload["heat"]] == ["microringweightbank1:ring2"] and len(payload["rf"]) == 1
    size = _page_bytes(payload)
    assert size < 5_000_000, size


# ---- rings at resonance, drive tables, the heater's slow-down -------------------------------------------------------


def _cw_power(payload, port, key="from"):
    """The CW power on the routes that leave ``port`` (``key`` "from") or arrive there ("to")."""

    return sum(sum(v * v for v in r["jones"]) for eid, e in payload["cw"]["edges"].items() if eid.startswith("route:")
               for r in e["cw"] if r[key] == port)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_default_ring_filter_sits_on_resonance_and_the_caption_says_so():
    """The chip's light enters the fifth-order filter at o2: the through port is o1 and the drop port o4."""

    payload = build_light_payload(build_preset("ring_resonator_chip"))
    port = "port:coupledringfilter1:"
    given = _cw_power(payload, port + "o2", "to")
    assert given > 0
    assert _cw_power(payload, port + "o4") > 0.5 * given          # the drop port
    assert _cw_power(payload, port + "o1") < 0.5 * given          # the through port
    shown = payload["captions"][:payload["caption_split"]]
    assert "Rings tuned to resonance (illustrative)" in shown and BUILD_UP in shown
    tuned = build_light_payload(build_preset("ring_resonator_chip"), params={"phase:coupledringfilter1": 0.0})
    assert "Rings tuned to resonance (illustrative)" not in tuned["captions"] and BUILD_UP not in tuned["captions"]


BUILD_UP = "Pulses are shorter than the rings' build-up, so they drop little light. The Field look shows the steady state."


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_model_lines_fold_and_the_short_lines_stay_in_view():
    """The time scale, the pulse, the heater slow-down and the wavelength factor stay in view; the model lines (the
    rings, the crests, the field cycle, the heat model) fold behind the page's Scales toggle."""

    payload = build_light_payload(build_preset("ring_resonator_chip"), look="field", heater_delay_scale=2.0,
                                  params={"heater:coupledringfilter1:ring1": 10.0})
    captions, folded = payload["captions"], set(payload["caption_folded"])
    shown = [c for i, c in enumerate(captions) if i not in folded]
    assert len(shown) == 5 and shown[0].startswith("Time slowed") and shown[1].startswith("Pulse ")
    assert shown[2] == "1550 nm (infrared) shown white"
    assert shown[3] == "Heater slow-down shown x2" and shown[4].startswith("Wavelength shown x")
    hidden = [c for i, c in enumerate(captions) if i in folded]
    assert "Rings tuned to resonance (illustrative)" in hidden and "Crest spacing from the group index" in hidden
    assert any("K above the chip" in c for c in hidden) and any(c.startswith("Field cycle") for c in hidden)


def _add_drop_ring_scene():
    from optodraw.components.onchip.rings import MicroringResonator

    scene = Scene(width=360, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    ring = scene.add(MicroringResonator(center=(0, 0), add_drop=True, with_heater=True))
    through = scene.add(build_component("OnChipPhotodetector", center=(150, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (through, "o1"), kind="waveguide")
    return scene


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_default_add_drop_ring_drops_most_of_its_input():
    payload = build_light_payload(_add_drop_ring_scene())
    given = _cw_power(payload, "port:microringresonator1:o1", "to")
    drop = sum(e["power"] for e in payload["cw"]["exits"] if e["part"] == "microringresonator1" and e["port"] == "o3")
    assert given > 0 and drop > 0.5 * given and _cw_power(payload, "port:microringresonator1:o2") < 0.5 * given


def test_the_default_ring_phase_closes_each_round_trip_of_the_engines_own_transfers():
    import cmath

    from optodraw.animation_engine.behaviours import find_behaviour
    from optodraw.animation_engine.graph import build_graph
    from optodraw.animation_engine.solver import phase_factor

    scene = build_preset("ring_resonator_chip")
    inputs, _ = default_inputs(scene)
    found = default_params(scene, inputs)
    assert set(found) == {f"phase:coupledringfilter1:ring{k}" for k in range(1, 6)}
    part = build_graph(scene).parts["coupledringfilter1"]
    behaviour = find_behaviour(part)
    for k in range(1, 6):
        trip = 1.0 + 0j
        for a, b in ((f"_a{k}u", f"_a{k}l"), (f"_a{k}l", f"_a{k}u")):
            (t,) = [t for t in behaviour.transfers(part, "coupledringfilter1", a, inputs[0].wavelength_nm, found) if t.out_port == b]
            trip *= complex(t.matrix[0, 0]) * phase_factor(t.length, t.group_index, inputs[0].wavelength_nm)
        assert abs(cmath.phase(trip)) < 1e-9 and abs(found[f"phase:coupledringfilter1:ring{k}"]) <= math.pi
    assert default_params(scene, inputs, {"phase:coupledringfilter1": 0.3}) == {}
    assert "phase:coupledringfilter1:ring2" not in default_params(scene, inputs, {"phase:coupledringfilter1:ring2": 0.3})
    assert default_params(scene, inputs, {"heater:coupledringfilter1:ring2": 5.0}) == found     # a heater detunes from it


def test_without_drives_the_payload_has_no_drive_tables():
    assert build_light_payload(_mzm_between_two_routes())["drives"] == []
    with pytest.raises(ValueError, match="gratingcoupler|no heater or drive"):
        build_light_payload(_mzm_between_two_routes(), drives=["verticalgratingcoupler1"])


def _sample_packets(payload, entry, k, edge_id):
    """The packets of ``edge_id`` at sample ``k`` of a drive table: the sample's own, else the base state's."""

    own = entry["pulse"][k].get(edge_id)
    if own is not None:
        return list(zip(own["from"], own["wavelength_nm"], own["power"], own["t0"], own["t1"]))
    base = payload["pulse"]["edges"].get(edge_id, {"packets": []})["packets"]
    return [(p["from"], p["wavelength_nm"], _power(p), p["t0"], p["t1"]) for p in base]


def _sample_cw(payload, entry, k, edge_id):
    own = entry["cw"][k].get(edge_id)
    records = own if own is not None else payload["cw"]["edges"].get(edge_id, {"cw": []})["cw"]
    return [(r["from"], r["to"], r["wavelength_nm"], r["amp"], r["phase"]) for r in records]


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_an_mzm_drive_table_follows_the_engine_at_every_sample():
    from optodraw.animation3d.fieldmodel import display_numbers
    from optodraw.animation_engine.inputs import InputSignal
    from optodraw.animation_engine.tables import compile_table

    scene = _mzm_between_two_routes()
    payload = build_light_payload(scene, drives="all")
    (entry,) = payload["drives"]
    assert entry["param"] == "drive:mzm1" and entry["sid"] == "mzm1" and len(entry["values"]) == 24
    assert entry["values"][0] == 0.0 and entry["values"][-1] == pytest.approx(2.0)        # 0 to v_pi
    params, inputs = payload["cw"]["params"], [InputSignal.from_json(i) for i in payload["cw"]["inputs"]]
    assert entry["pulse"][0] == {} and entry["cw"][0] == {}                                # 0 V is the base state
    for k, value in enumerate(entry["values"]):
        sample = {**params, "drive:mzm1": value}
        engine = compile_signal_state(scene, mode="pulse", params=sample, inputs=inputs).to_json()
        want = [(p["from"], p["wavelength_nm"], _power(p), p["t0"], p["t1"])
                for p in engine["edges"].get("route:route2", {"packets": []})["packets"]]
        got = _sample_packets(payload, entry, k, "route:route2")
        assert len(got) == len(want), k
        for g, w in zip(got, want):
            assert g[:2] == w[:2] and g[2:] == pytest.approx(w[2:], abs=1e-6), k
        table = compile_table(scene, mode="cw", params=sample, inputs=inputs)
        display_numbers(table, payload["cw"]["lambda_scale"])
        want_cw = [(r["from"], r["to"], r["wavelength_nm"], r["amp"], r["phase"])
                   for r in table["edges"].get("route:route2", {"cw": []})["cw"]]
        assert _sample_cw(payload, entry, k, "route:route2") == pytest.approx(want_cw, abs=1e-6), k
    assert entry["pulse"][23]["route:route2"]["power"] == [] and entry["cw"][23]["route:route2"] == []   # v_pi: dark


def _heated_ring_scene():
    from optodraw.components.onchip.rings import MicroringResonator

    scene = Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    ring = scene.add(MicroringResonator(center=(0, 0), with_heater=True))
    det = scene.add(build_component("OnChipPhotodetector", center=(150, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (det, "o1"), kind="waveguide")
    return scene


def test_a_ring_heater_drive_starts_at_the_base_state_and_detunes_the_ring():
    payload = build_light_payload(_heated_ring_scene(), drives=["microringresonator1"])
    (entry,) = payload["drives"]
    assert entry["param"] == "heater:microringresonator1" and entry["values"][0] == 0.0 and entry["values"][-1] == 20.0
    assert entry["pulse"][0] == {} and entry["cw"][0] == {}                # 0 mW: the ring stays at its default
    assert "route:route2" in entry["cw"][-1] and "route:route2" in entry["pulse"][-1]     # 20 mW detunes it


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_drive_tables_for_twelve_mesh_modulators_stay_under_5_mb():
    """Twelve parts asked: the ten modulators the light reaches get tables; the two dark ones change no light."""

    lit = [1, 5, 6, 9, 10, 11, 13, 14, 15, 16]
    start = time.perf_counter()
    payload = build_light_payload(build_preset("mzm_mesh_chip"), drives=[f"mzm{k}" for k in lit + [2, 3]])
    elapsed, size = time.perf_counter() - start, _page_bytes(payload)
    print(f"mzm_mesh_chip with drive tables for 12 parts: {size / 1e6:.2f} MB in {elapsed:.1f} s")
    assert [d["sid"] for d in payload["drives"]] == [f"mzm{k}" for k in lit]
    assert all(len(d["pulse"]) == len(d["cw"]) == 24 and any(d["pulse"]) for d in payload["drives"])
    assert {"mzm2: drive:mzm2 changes no light", "mzm3: drive:mzm3 changes no light"} <= set(payload["notices"])
    assert size < 5_000_000, size


def _heated_mzi_scene():
    scene = Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    mzi = scene.add(build_component("MZI", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(160, 40)))
    scene.route((laser, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o3"), (det, "o1"), kind="waveguide")
    return scene


def _heated_shifter_scene():
    scene = Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    shifter = scene.add(build_component("PhaseShifter", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(150, 0)))
    scene.route((laser, "o1"), (shifter, "o1"), kind="waveguide")
    scene.route((shifter, "o2"), (det, "o1"), kind="waveguide")
    return scene


def _later(shown, plain, edge_id, key):
    pairs = list(zip(shown["pulse"]["edges"][edge_id]["packets"], plain["pulse"]["edges"][edge_id]["packets"], strict=True))
    assert pairs and all(a["jones"] == pytest.approx(b["jones"], abs=1e-12) for a, b in pairs)      # the phase is unchanged
    return [a[key] - b[key] for a, b in pairs]


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_heater_slow_down_shown_100_times_delays_the_heated_light_and_the_light_after_it():
    """Above 1 the payload solves the pulse with each heater's delay times the scale; no phase changes. Against the same
    phase from a phase key (no delay): a heated phase shifter's light and the route after it arrive 100 times the true
    delay later. In an MZI only the heated arm is late: the engine adds the two arms in one bucket at the output port,
    which opens with the first arrival (the unheated arm), so the route after the MZI does not move. The input
    coupler's rails follow the slower arm: they end later, by no more than the arm's delay."""

    true_delay = math.pi * 1.55 / (2 * math.pi * 299.792458)               # ps: pi at 1550 nm with the engine's c
    scene = _heated_shifter_scene()
    shown = build_light_payload(scene, params={"heater:phaseshifter1": 20.0}, heater_delay_scale=100.0)
    plain = build_light_payload(scene, params={"phase:phaseshifter1": math.pi})
    assert "Heater slow-down shown x100" in shown["captions"][:shown["caption_split"]]
    assert not any("slow-down" in c for c in plain["captions"])
    assert _later(shown, plain, "path:phaseshifter1:o1->o2", "t1") == pytest.approx([100 * true_delay], abs=1e-9)
    for key in ("t0", "t1"):
        assert _later(shown, plain, "route:route2", key) == pytest.approx([100 * true_delay], abs=1e-9)

    scene = _heated_mzi_scene()
    shown = build_light_payload(scene, params={"heater:mzi1": 20.0}, heater_delay_scale=100.0)
    plain = build_light_payload(scene, params={"phase:mzi1:arm1": math.pi})
    for edge_id in ("path:mzi1:o1->o3#arm1", "path:mzi1:o1->o4#arm1"):
        assert _later(shown, plain, edge_id, "t1") == pytest.approx([100 * true_delay], abs=1e-9)
    for edge_id in ("path:mzi1:o1->o3#arm2", "route:route2"):
        assert _later(shown, plain, edge_id, "t1") == pytest.approx([0.0], abs=1e-9)
    late = [a["t1"] - b["t1"] for ra, rb in zip(shown["rails"], plain["rails"], strict=True) if ra["host"] == "mzi1" and ra["section"] == 0
            for a, b in zip(ra["packets"], rb["packets"], strict=True)]
    assert late and all(0 < lag <= 100 * true_delay + 1e-9 for lag in late)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_coupler_lit_only_by_continuous_light_is_drawn_by_its_rails_alone():
    """On resonance the filter drops its light to tapcoupler2 in the steady state; each pulse trip there is below the
    engine's floor, so no pulse rail hides the coupler's transfers. Its CW rails draw it, and its transfers are hidden."""

    payload = build_light_payload(build_preset("ring_resonator_chip"))
    assert not any(eid.startswith("path:tapcoupler2:") for eid in payload["pulse"]["edges"])
    lit = {eid for eid, e in payload["cw"]["edges"].items() if eid.startswith("path:tapcoupler2:") and e["cw"]}
    assert lit and lit <= set(payload["hidden"])
    rails = [r for r in payload["cw"]["rails"] if r["host"] == "tapcoupler2"]
    assert rails and all(isinstance(r["points"], list) and isinstance(r["points"][0], list) for r in rails)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_field_look_shows_the_heater_slow_down_too():
    """The caption names the slow-down in both looks: the steady state's arrival fronts carry the scaled delay."""

    true_delay = math.pi * 1.55 / (2 * math.pi * 299.792458)
    scene = _heated_mzi_scene()
    shown = build_light_payload(scene, params={"heater:mzi1": 20.0}, heater_delay_scale=100.0, look="field")
    plain = build_light_payload(scene, params={"phase:mzi1:arm1": math.pi}, look="field")
    for edge_id, lag in (("path:mzi1:o1->o3#arm1", 100 * true_delay), ("path:mzi1:o1->o3#arm2", 0.0), ("route:route2", 0.0)):
        for a, b in zip(shown["cw"]["edges"][edge_id]["cw"], plain["cw"]["edges"][edge_id]["cw"], strict=True):
            assert a["t1"] - b["t1"] == pytest.approx(lag, abs=1e-9) and a["jones"] == pytest.approx(b["jones"], abs=1e-12)


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_drive_that_changes_nothing_has_no_table_and_a_notice_says_why():
    payload = build_light_payload(_heated_mzi_scene(), params={"phase:mzi1:arm1": 1.0}, drives=["mzi1"])
    assert payload["drives"] == []
    assert "mzi1: heater:mzi1 has no effect while a phase is set" in payload["notices"]


def test_a_ring_no_light_reaches_keeps_its_phase_and_its_drive_changes_no_light():
    from optodraw.components.onchip.rings import MicroringResonator

    scene = _heated_ring_scene()
    scene.add(MicroringResonator(center=(0, 60), with_heater=True))             # nothing routes light to it
    payload = build_light_payload(scene, drives=["microringresonator2"])
    assert "phase:microringresonator1" in payload["cw"]["params"]
    assert "phase:microringresonator2" not in payload["cw"]["params"]
    assert payload["drives"] == []
    assert "microringresonator2: heater:microringresonator2 changes no light" in payload["notices"]


def unconserved(payload, floor=1e-3):
    """``(coupler sections that lose or make light, buckets checked)``: in each section with two rails and a window, per
    bucket (the rails' packets in order, at one wavelength), the rails' powers at the window's start add up to those at
    its end (1 % plus the slack), as the drawing's coupled-mode model keeps the power there. Unlike the meetings check
    this sees a ring rail that goes once round, whose two ends sit at one place."""

    from collections import defaultdict

    slack, sections = _slack(payload, floor), defaultdict(list)
    for d in payload["rails"]:
        sections[d["host"], d["section"]].append(d)
    bad, checked = [], 0
    for (host, index), rails in sections.items():
        if len(rails) != 2 or any(d["window"] is None for d in rails) or len({len(d["packets"]) for d in rails}) != 1:
            continue
        for k in range(len(rails[0]["packets"])):
            packets = [d["packets"][k] for d in rails]
            if len({p["wavelength_nm"] for p in packets}) != 1:
                continue
            start = sum(p["power"][d["window"][0]] for d, p in zip(rails, packets))
            end = sum(p["power"][d["window"][1]] for d, p in zip(rails, packets))
            checked += 1
            if abs(start - end) > 0.01 * max(start, end) + slack:
                bad.append((host, index, k, start, end))
    return bad, checked


RESONANT_PAYLOADS = {
    "ring-assisted MZI": lambda: build_light_payload(_between_gratings("RingAssistedMZI")),
    "add-drop ring": lambda: build_light_payload(_add_drop_ring_scene()),
    "ring_resonator_chip": lambda: _preset_payload("ring_resonator_chip"),
    "wdm_delay_weight_bank_chip": lambda: _preset_payload("wdm_delay_weight_bank_chip")}


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
@pytest.mark.parametrize("label", sorted(RESONANT_PAYLOADS))
def test_every_coupler_section_keeps_its_light_with_the_rings_on_resonance(label):
    bad, checked = unconserved(RESONANT_PAYLOADS[label]())
    assert checked and bad == [], bad[:3]


def test_the_conservation_check_finds_a_ring_rail_that_goes_once_round_losing_light():
    payload = build_light_payload(_between_gratings("RingAssistedMZI"))
    (ring,) = [d for d in payload["rails"] if d["host"] == "ringassistedmzi1" and d["packets"] and _closed(d)]
    ring["packets"] = [dict(p, power=[0.5 * v for v in p["power"]]) for p in ring["packets"]]
    assert unconserved(payload)[0]


def test_render_threejs_reads_the_scenes_animation_settings_and_explicit_arguments_win():
    scene = _heated_ring_scene()
    scene.metadata["animation"] = {"look": "field", "params": {"heater:microringresonator1": 15.0}, "inputs": []}
    plain = _heated_ring_scene()

    def light_of(page: str) -> dict:
        marker = "window.__odLightData = "
        start = page.index(marker) + len(marker)
        return json.JSONDecoder().raw_decode(page[start:])[0]

    from_metadata = light_of(scene.render_threejs())
    assert from_metadata["look"] == "field"
    expected = build_light_payload(plain, params={"heater:microringresonator1": 15.0}, look="field")
    assert from_metadata["cw"] == expected["cw"]
    assert light_of(scene.render_threejs(look="light", params={}))["look"] == "light"
    assert light_of(scene.render_threejs(params={}))["cw"] == light_of(plain.render_threejs())["cw"] != from_metadata["cw"]


# ---- the tour in the payload ----------------------------------------------------------------------------------------


def _modulators_in_series(count: int):
    """A laser, ``count`` MZMs one after the other, a detector: one driven stop per modulator."""

    scene = Scene(width=300 * count + 300, height=160, platform="on_chip")
    parts = [scene.add(build_component("OnChipLaser", center=(-150 * count - 50, 0)))]
    parts += [scene.add(build_component("MZM", center=(300 * k - 150 * (count - 1), 0))) for k in range(count)]
    parts.append(scene.add(build_component("OnChipPhotodetector", center=(150 * count + 80, 0))))
    for a, b in zip(parts, parts[1:]):
        scene.route((a, "o1" if a is parts[0] else "o3"), (b, "o1"), kind="waveguide")
    return scene


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_payload_carries_its_tour_the_time_warp_and_the_names_of_the_stops():
    from optodraw.animation3d.tour import scene_tour, time_warp

    scene = _modulators_in_series(1)
    payload = build_light_payload(scene)
    tour = scene_tour(scene, payload)
    assert [s.sid for s in tour.stops] == ["mzm1", "onchipphotodetector1"]
    assert payload["tour"] == tour.to_json()
    assert payload["tour_warp"] == [list(knot) for knot in time_warp(tour, payload, driven=False)]   # no table: slow holds
    swung = build_light_payload(scene, drives="tour")
    assert swung["tour_warp"] == [list(knot) for knot in time_warp(tour, swung)] != payload["tour_warp"]
    assert payload["tour_names"] == {"mzm1": "MZM 1", "onchipphotodetector1": "On chip photodetector 1"}
    assert payload["drives"] == []                                        # tables only when asked


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_drives_tour_gives_each_driven_stop_a_level_per_pass_seen_in_its_frame():
    """Rulings 46 and 47: one table per driven stop with the levels its passes meet (0 up to the top and back), each
    level keeping only the edges and rails its stop's frame shows, the rest equal to a full drive table's."""

    from optodraw.animation3d.payload import _in_frame, pass_levels
    from optodraw.animation3d.tour import driven_passes, scene_tour, time_warp

    scene = _modulators_in_series(2)
    payload = build_light_payload(scene, drives="tour")
    driven = [(s["sid"], s["drive"]) for s in payload["tour"]["stops"] if s["drive"]]
    assert driven == [("mzm1", "drive:mzm1"), ("mzm2", "drive:mzm2")]
    assert [(d["sid"], d["param"]) for d in payload["drives"]] == driven
    tour = scene_tour(scene, payload)
    passes = driven_passes(tour, payload, time_warp(tour, payload))
    full = {d["sid"]: d for d in build_light_payload(scene, drives=["mzm1", "mzm2"])["drives"]}
    points = {**{e: v["points"] for e, v in payload["cw"]["edges"].items()}, **{e: v["points"] for e, v in payload["pulse"]["edges"].items()}}
    outside = []
    for i, table in zip([i for i, s in enumerate(tour.stops) if s.drive], payload["drives"]):
        fractions, sequence = pass_levels(len(passes[i]))
        assert table["passes"] == passes[i] and len(table["passes"]) >= 3 and table["levels"] == sequence
        assert table["values"] == [2.0 * f for f in fractions] and table["frame"][2] > 0
        top, whole = len(table["values"]) - 1, full[table["sid"]]
        assert whole["values"][-1] == table["values"][top]
        seen = {e: v for e, v in whole["pulse"][-1].items() if _in_frame(points.get(e), table["frame"])}
        assert table["pulse"][top] == seen and seen                          # what the frame shows, as a full table has it
        outside.append(set(whole["pulse"][-1]) - set(seen))
    assert outside[0]                                       # the first stop's frame leaves out the second modulator's light
    assert [d["caption"] for d in payload["drives"]] == ["Drive on MZM 1: 0 to 2 V", "Drive on MZM 2: 0 to 2 V"]
    assert payload["rf_scale_v_per_um"] > 0                               # the colour scale covers the tour's drive
    assert not [n for n in payload["notices"] if "MB" in n]


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_past_the_page_limit_the_latest_stops_tables_go(monkeypatch):
    from optodraw.animation3d import payload as module

    scene = _modulators_in_series(2)
    full = build_light_payload(scene, drives="tour")
    monkeypatch.setattr(module, "PAGE_LIMIT_BYTES", _page_bytes(full) - 1)
    first = build_light_payload(scene, drives="tour")
    assert [d["sid"] for d in first["drives"]] == ["mzm1"] and first["drives"][0] == full["drives"][0]
    assert "Tour drives left out to keep the page under 15 MB: mzm2" in first["notices"]
    assert _page_bytes(first) <= _page_bytes(full) - 1
    monkeypatch.setattr(module, "PAGE_LIMIT_BYTES", _page_bytes(build_light_payload(scene)) + 10)
    none = build_light_payload(scene, drives="tour")
    assert none["drives"] == [] and "Tour drives left out to keep the page under 15 MB: mzm1, mzm2" in none["notices"]


def _modulator_then_coupler():
    """A laser, a driven MZM, a directional coupler drawn by its rails, two detectors."""

    scene = Scene(width=700, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-250, 0)))
    mzm = scene.add(build_component("MZM", center=(-60, 0)))
    coupler = scene.add(build_component("DirectionalCoupler", center=(150, 0)))
    top = scene.add(build_component("OnChipPhotodetector", center=(280, 40)))
    bottom = scene.add(build_component("OnChipPhotodetector", center=(280, -40)))
    for a, b in (((laser, "o1"), (mzm, "o1")), ((mzm, "o3"), (coupler, "o1")), ((coupler, "o3"), (top, "o1")),
                 ((coupler, "o4"), (bottom, "o1"))):
        scene.route(a, b, kind="waveguide")
    return scene


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_drive_table_carries_the_rails_of_every_part_the_swing_reaches():
    """The coupler after the modulator is drawn by rails: at each sample its rails are the engine's rails of that
    state (a factor per packet where they are the base rails times a factor)."""

    from optodraw.animation3d.rails import build_rails
    from optodraw.animation_engine.graph import build_graph
    from optodraw.animation_engine.inputs import InputSignal

    scene = _modulator_then_coupler()
    payload = build_light_payload(scene, drives=["mzm1"])
    (entry,) = payload["drives"]
    params, inputs = payload["cw"]["params"], [InputSignal.from_json(i) for i in payload["cw"]["inputs"]]
    base = {f"rail:{r['host']}:{r['section']}:{r['rail']}": r for r in payload["rails"]}
    coupler = sorted(key for key in base if key.startswith("rail:directionalcoupler1:"))
    assert coupler
    for k in (1, 12, 23):
        sample = {**params, "drive:mzm1": entry["values"][k]}
        engine = compile_signal_state(scene, mode="pulse", params=sample, inputs=inputs).to_json()
        drawn = {f"rail:{r['host']}:{r['section']}:{r['rail']}": r for r in build_rails(scene, sample, engine, build_graph(scene))[0]}
        def ident(p):
            return (p["wavelength_nm"], round(p["t0"], 5), round(p["t1"], 5))

        for key in coupler:
            found = entry["rails"][k].get(key)
            assert found is not None, (k, key)                              # the swing reaches the coupler
            want = {ident(p): p["power"] for p in drawn[key]["packets"]} if key in drawn else {}
            got = ({**{ident(p): [s * v for v in p["power"]] for s, p in zip(found["scales"], base[key]["packets"]) if s},
                    **{ident(p): p["power"] for p in found.get("extra", [])}}
                   if "scales" in found else {ident(p): p["power"] for p in found["packets"]})
            got = {i: v for i, v in got.items() if i in want or max(v, default=0) > 2e-6}     # a packet at 0 is no packet
            assert got.keys() == want.keys() and all(got[i] == pytest.approx(want[i], abs=2e-6) for i in want), (k, key)
        assert set(entry["cw_rails"][k]) >= set(coupler) or k == 0


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_drive_table_carries_the_rf_and_heat_values_of_each_sample():
    from optodraw.animation3d.effects import build_heat, build_rf
    from optodraw.animation3d.inputs import input_wavelength
    from optodraw.animation_engine.graph import build_graph

    (rf,) = build_light_payload(_mzm_between_two_routes(), drives="all")["drives"]
    assert rf["rf_maps"] and all(r["v"] == pytest.approx(rf["values"][-1]) for r in rf["rf_maps"])
    assert all(sample == ([value] * len(rf["rf_maps"]) if value else []) for value, sample in zip(rf["values"], rf["rf"]))
    scene = _heated_ring_scene()
    payload = build_light_payload(scene, drives=["microringresonator1"])
    (heat,) = payload["drives"]
    graph = build_graph(scene)
    parts, nm = graph.parts, input_wavelength(graph, [], payload["cw"]["params"])
    for value, sample in zip(heat["values"], heat["heat"]):
        found = build_heat(parts, {**payload["cw"]["params"], heat["param"]: value}, nm)
        assert sample == [h["delta_t_k"] for h in found if h["sid"] == "microringresonator1"]
    assert heat["heat_maps"] and heat["heat_maps"][0]["delta_t_k"] == pytest.approx(max(max(s, default=0) for s in heat["heat"]))
    assert payload["heat_scale_k"] >= heat["heat_maps"][0]["delta_t_k"] and build_rf(parts, payload["cw"]["params"]) == []


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_drive_table_carries_each_samples_changed_profiles():
    from optodraw.animation3d.fieldmodel import display_numbers, overlap_profiles
    from optodraw.animation_engine.inputs import InputSignal
    from optodraw.animation_engine.tables import compile_table

    scene = Scene(width=600, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-250, 0)))
    split = scene.add(build_component("MMI1x2", center=(-150, 0)))
    top = scene.add(build_component("PhaseShifter", center=(0, 30)))
    bottom = scene.add(build_component("Waveguide", center=(0, -30)))
    combine = scene.add(build_component("MMI1x2", center=(150, 0), angle=180))
    det = scene.add(build_component("OnChipPhotodetector", center=(260, 0)))
    for a, b in (((laser, "o1"), (split, "o1")), ((split, "o2"), (top, "o1")), ((split, "o3"), (bottom, "o1")),
                 ((top, "o2"), (combine, "o2")), ((bottom, "o2"), (combine, "o3")), ((combine, "o1"), (det, "o1"))):
        scene.route(a, b, kind="waveguide")
    payload = build_light_payload(scene, drives=["phaseshifter1"])
    (entry,) = payload["drives"]
    params, inputs = payload["cw"]["params"], [InputSignal.from_json(i) for i in payload["cw"]["inputs"]]
    for k in (0, 12, 23):
        table = compile_table(scene, mode="cw", params={**params, entry["param"]: entry["values"][k]}, inputs=inputs)
        display_numbers(table, payload["cw"]["lambda_scale"])
        want = overlap_profiles(table, payload["hidden"])
        got = {eid: v for eid, v in {**payload["cw"]["profiles"], **entry["profiles"][k]}.items() if v}
        assert got.keys() == want.keys() and all(got[e] == pytest.approx(want[e], abs=1e-6) for e in want), k
    assert entry["profiles"][0] == {} and entry["profiles"][23]


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_a_stop_whose_table_is_dropped_holds_as_an_undriven_stop():
    """Task 16 carry: driven is decided per stop after the tables are known; a stop with no table has the slow hold."""

    from optodraw.animation3d.tour import scene_tour, time_warp

    scene = _heated_mzi_scene()
    payload = build_light_payload(scene, params={"phase:mzi1:arm1": 1.0}, drives="tour")
    assert payload["drives"] == [] and any(s["drive"] for s in payload["tour"]["stops"])
    tour = scene_tour(scene, payload)
    assert payload["tour_warp"] == [list(k) for k in time_warp(tour, payload, driven=False)]


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_warp_follows_the_kept_tables_when_one_stop_keeps_its_table_and_one_loses_it(monkeypatch):
    from optodraw.animation3d import payload as module
    from optodraw.animation3d.tour import scene_tour, time_warp

    scene = _modulators_in_series(2)
    full = build_light_payload(scene, drives="tour")
    monkeypatch.setattr(module, "PAGE_LIMIT_BYTES", _page_bytes(full) - 1)
    cut = build_light_payload(scene, drives="tour")
    assert [d["sid"] for d in cut["drives"]] == ["mzm1"]
    tour = scene_tour(scene, cut)
    index = [s.sid for s in tour.stops].index("mzm1")
    assert cut["tour_warp"] == [list(k) for k in time_warp(tour, cut, driven={index})]
    assert cut["tour_warp"] != full["tour_warp"]
    (table,) = cut["drives"]                       # the kept table was built for the warp the page carries
    from optodraw.animation3d.tour import driven_passes
    assert table["passes"] == driven_passes(tour, cut, [tuple(k) for k in cut["tour_warp"]])[index]


def test_the_few_pulses_notice_is_only_for_a_table_the_page_keeps(monkeypatch):
    from optodraw.animation3d import payload as module

    scene = build_preset("ring_resonator_chip")
    note = "5th-order filter ring 1: the drive is shown on 1 pulse; the Field look shows it in steady state"
    assert note in build_light_payload(scene, drives="tour")["notices"]
    monkeypatch.setattr(module, "PAGE_LIMIT_BYTES", _page_bytes(build_light_payload(scene)) + 10)
    cut = build_light_payload(scene, drives="tour")
    assert cut["drives"] == [] and note not in cut["notices"]
