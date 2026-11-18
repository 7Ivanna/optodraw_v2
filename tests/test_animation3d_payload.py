"""The 3D light payload: the engine's packets, a host per edge, colours and a default input."""

import functools
import math

import pytest

from optodraw import Scene
from optodraw.animation3d.colours import CHANNEL_PALETTE, channel_colors
from optodraw.animation3d.inputs import default_inputs
from optodraw.animation3d.payload import _empty_cw, build_light_payload, default_params
from optodraw.animation_engine import compile_signal_state
from optodraw.presets import build_preset
from optodraw.registry import build_component


def test_the_default_input_on_a_bench_takes_the_wavelength_of_the_beam_at_its_port():
    """The bench preset's beam is 1090 nm: the light enters at that wavelength. One infrared line is white (Ruling 8),
    so its one colour is the colour the spec gives 1090 nm, not that of 1550 nm by chance."""

    scene = build_preset("free_space_breadboard")
    beams = [node for node in scene.walk() if type(node).__name__ == "Beam"]
    (found,), _ = default_inputs(scene)
    assert found.target == "port:iris1:in" and found.wavelength_nm == beams[0].wavelength == 1090.0
    assert build_light_payload(scene)["colors"] == {"1090.0": channel_colors([1090.0])[1090.0]}


def _page_bytes(payload) -> int:
    """The bytes the page carries for the payload: the renderer embeds it as compact JSON."""

    from optodraw.renderers.threejs_renderer import _json_script_safe

    return len(_json_script_safe(payload).encode())


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


@pytest.fixture
def no_fronts(monkeypatch):
    """These tests fake the engine with an input the arrival fronts cannot read: no crossing, no display pulse, no
    steady state."""

    monkeypatch.setattr("optodraw.animation3d.payload._crossing_ps", lambda *args: 0.0)
    monkeypatch.setattr("optodraw.animation3d.payload._cw",
                        lambda scene, params, inputs, pulse, graph, rails, hidden, *rest: (_empty_cw(), [], list(hidden)))


def test_more_channels_than_palette_colours_gives_a_notice(monkeypatch, no_fronts):
    packets = [_packet(1500.0 + k) for k in range(len(CHANNEL_PALETTE) + 2)]
    monkeypatch.setattr("optodraw.animation3d.payload.compile_signal_state", lambda *a, **k: _FakeState(packets))
    payload = build_light_payload(Scene(), inputs=[object()])
    assert f"{len(packets)} channels share colours: the palette has {len(CHANNEL_PALETTE)}" in payload["notices"]


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


def _mzm_between_two_routes():
    scene = Scene()
    left = scene.add(build_component("VerticalGratingCoupler", center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    right = scene.add(build_component("VerticalGratingCoupler", center=(150, 0), angle=180))
    scene.route((left, "o1"), (mzm, "o1"))
    scene.route((mzm, "o3"), (right, "o1"))
    return scene


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


def _lit_preset(name):
    return build_preset(name), _preset_payload(name)


INVARIANT_CASES = {name: (lambda name=name: _lit_preset(name)) for name in (
    "ring_resonator_chip", "coherent_receiver_chip", "mzm_mesh_chip", "wdm_delay_weight_bank_chip")}
INVARIANT_CASES |= {f"chain {k1} {k2}": (lambda k1=k1, k2=k2: (_chain(k1, k2), build_light_payload(_chain(k1, k2))))
                    for k1, k2 in ((0.3, 0.9), (0.5, 1.0))}


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


def _closed(rail):
    import math

    return math.dist(rail["points"][0], rail["points"][-1]) < 1e-3


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


def _port_xy(scene, sid, port):
    from optodraw.animation_engine.graph import build_graph

    centre = build_graph(scene).parts[sid].world_port(port).center
    return float(centre.x), float(centre.y)


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


# ---- rings at resonance, drive tables, the heater's slow-down -------------------------------------------------------


BUILD_UP = "Pulses are shorter than the rings' build-up, so they drop little light. The Field look shows the steady state."


def _add_drop_ring_scene():
    from optodraw.components.onchip.rings import MicroringResonator

    scene = Scene(width=360, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    ring = scene.add(MicroringResonator(center=(0, 0), add_drop=True, with_heater=True))
    through = scene.add(build_component("OnChipPhotodetector", center=(150, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (through, "o1"), kind="waveguide")
    return scene


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


def _heated_mzi_scene():
    scene = Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    mzi = scene.add(build_component("MZI", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(160, 40)))
    scene.route((laser, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o3"), (det, "o1"), kind="waveguide")
    return scene


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


def test_the_conservation_check_finds_a_ring_rail_that_goes_once_round_losing_light():
    payload = build_light_payload(_between_gratings("RingAssistedMZI"))
    (ring,) = [d for d in payload["rails"] if d["host"] == "ringassistedmzi1" and d["packets"] and _closed(d)]
    ring["packets"] = [dict(p, power=[0.5 * v for v in p["power"]]) for p in ring["packets"]]
    assert unconserved(payload)[0]


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


