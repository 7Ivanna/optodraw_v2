"""The 3D page plays the engine's light: the page carries the light payload, and the player places every edge
in its guide and draws each packet where and when the engine says."""

from __future__ import annotations

import json
import math
import re

import pytest

from optodraw import Beam, Laser, Periscope, Photodiode, Scene
from optodraw.animation3d.payload import build_light_payload
from optodraw.animation_engine.errors import AnimationError
from optodraw.animation_engine.ids import scene_ids
from optodraw.animation_engine.inputs import InputSignal
from optodraw.presets import build_preset, list_presets
from optodraw.renderers.capture3d import find_chrome, run_page
from optodraw.renderers.threejs_renderer import ThreeJsRenderer

needs_chrome = pytest.mark.skipif(not find_chrome(required=False), reason="needs Chrome, Chromium or Edge")
REFUSED = "no light: periscope1: no behaviour yet for Periscope"


_PAGES: dict[tuple[str, str], str] = {}


def page_with_probe(preset: str | Scene, probe: str, **options) -> str:
    """The 3D page of ``preset`` (a preset name or a scene), with a script that writes
    ``JSON.stringify(eval(probe))`` into a hidden ``#od-capture`` textarea once odLight is built."""

    if isinstance(preset, str):                       # a preset's page is built once per options: the weight bank's
        key = (preset, json.dumps(options, sort_keys=True, default=repr))      # takes about 20 s
        if key not in _PAGES:
            _PAGES[key] = build_preset(preset).render_threejs(**options)
        html = _PAGES[key]
    else:
        html = preset.render_threejs(**options)
    script = ('<textarea id="od-capture" style="display:none"></textarea><script>(function(){'
              "var out=document.getElementById('od-capture');"
              "function fail(m){if(!out.value)out.value='error: '+m;}"
              "window.addEventListener('error',function(e){fail(e.message||'page error');});"
              "window.addEventListener('unhandledrejection',function(e){var r=e.reason;"
              "fail(r&&r.message?r.message:String(r));});"
              "(function wait(){if(window.odLight&&window.odLight.state.built){"
              f"try{{out.value=JSON.stringify(eval({json.dumps(probe)}));}}catch(e){{fail(e.message);}}"
              "}else{setTimeout(wait,50);}})();"
              "})();</script>\n")
    head, tag, tail = html.rpartition("</body>")
    return head + script + tag + tail


def _probe(preset: str | Scene, probe: str, **options):
    report = run_page(page_with_probe(preset, probe, **options), timeout=120)        # room for a loaded machine
    assert report and not report.startswith("error"), report
    return json.loads(report)


def _embedded_payload(html: str) -> dict:
    found = re.search(r"window\.__odLightData = (\{.*?\});\n", html, re.S)
    assert found, "the page carries no light payload"
    return json.loads(found.group(1))


def test_the_page_uses_the_new_player_and_not_the_old_one():
    html = build_preset("ring_resonator_chip").render_threejs()
    assert "window.odLight" in html and "window.__odLightData" in html
    assert "window.odAnim" not in html and "timeline3d" not in html


def test_the_page_carries_the_engines_payload_unchanged():
    """The page payload is the engine's with its tour; with tour_drives the drive tables of the tour's driven stops."""

    scene = build_preset("ring_resonator_chip")
    assert _embedded_payload(ThreeJsRenderer(scene).render()) == build_light_payload(scene)
    assert _embedded_payload(ThreeJsRenderer(scene, tour_drives=True).render()) == build_light_payload(scene, drives="tour")


def test_params_inputs_and_look_reach_the_engine():
    scene = build_preset("ring_resonator_chip")
    params = {"phase:coupledringfilter1": 2.0}
    html = ThreeJsRenderer(scene, params=params, look="field").render()
    assert _embedded_payload(html) == build_light_payload(scene, params=params, look="field")
    with pytest.raises(ValueError, match="look"):
        ThreeJsRenderer(scene, look="sparkle")


def test_every_item_carries_its_engine_id_and_every_light_host_is_drawn():
    scene = build_preset("ring_resonator_chip")
    items = ThreeJsRenderer(scene)._collect_scene_data()
    ids = set(scene_ids(scene).values())
    assert items and all(item["sid"] in ids for item in items)
    drawn = {item["sid"] for item in items}
    assert {host["sid"] for host in build_light_payload(scene)["hosts"].values()} <= drawn


def _periscope_bench() -> Scene:
    """A bench with a part the engine cannot model: this periscope brings no behaviour of its own (a periscope has
    one, so it stands in for a part that has none yet)."""

    scene = Scene(platform="free_space")
    laser = scene.add(Laser(center=(-60, 0)))
    up = scene.add(Periscope(center=(-20, 0), rise=20.0))
    up.animation_behaviour = lambda: None
    pd = scene.add(Photodiode(center=(60, 0)))
    scene.add(Beam((laser, "out"), (up, "in"), (up, "out"), (pd, "in")))
    return scene


def test_a_part_the_engine_cannot_model_turns_the_light_off_with_a_warning():
    with pytest.warns(RuntimeWarning, match=REFUSED):
        html = _periscope_bench().render_threejs()
    payload = _embedded_payload(html)
    assert payload["enabled"] is False and payload["notices"] == [REFUSED]


def test_an_engine_refusal_that_is_not_a_missing_model_raises(monkeypatch):
    def fails(*args, **kwargs):
        raise AnimationError("splitter1: a passive part gives out more power than it takes in (1.200)")

    monkeypatch.setattr("optodraw.renderers.threejs_renderer.build_light_payload", fails)
    with pytest.raises(AnimationError, match="more power"):
        build_preset("ring_resonator_chip").render_threejs()


def test_a_bad_explicit_input_or_params_raise():
    scene = build_preset("ring_resonator_chip")
    with pytest.raises(AnimationError, match="nosuchpart"):
        scene.render_threejs(inputs=[InputSignal("port:nosuchpart:o1")])
    with pytest.raises(AnimationError, match="no behaviour yet for Periscope"):
        _periscope_bench().render_threejs(params={})


def test_a_capture_never_builds_the_player():
    html = ThreeJsRenderer(build_preset("ring_resonator_chip"), capture={"width": 400, "height": 300}).render()
    assert "window.odLight = " not in html and "window.__odLightData = " not in html


@needs_chrome
def test_light_is_drawn_inside_the_guides_at_mid_height():
    """Every edge and every rail: coupled light is drawn on its rails, never across the gap, and a transfer that the
    rails draw is not drawn as well."""

    rows = _probe("ring_resonator_chip", "odLight.debugPlacement()")      # [{edge, inside: bool, worst_um: float}]
    hidden = set(build_light_payload(build_preset("ring_resonator_chip"))["hidden"])
    assert rows and any(row["edge"].startswith("rail:coupledringfilter1:") for row in rows) and hidden
    assert not hidden & {row["edge"] for row in rows}
    assert all(row["inside"] for row in rows), [row for row in rows if not row["inside"]]


def _mzm_between_two_routes() -> Scene:
    from optodraw.registry import build_component

    scene = Scene()
    left = scene.add(build_component("VerticalGratingCoupler", center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    right = scene.add(build_component("VerticalGratingCoupler", center=(150, 0), angle=180))
    scene.route((left, "o1"), (mzm, "o1"))
    scene.route((mzm, "o3"), (right, "o1"))
    return scene


@needs_chrome
def test_an_mzm_stem_is_as_bright_as_the_route_that_feeds_it_and_the_route_it_feeds():
    """Brightness inside a part comes from the payload: where the input route meets the MZM's input stem, and where
    the MZM's output stem meets the next route, the light is equally bright (the packet's middle is at the joint)."""

    params = {"drive:mzm1": 1.0}
    payload = build_light_payload(_mzm_between_two_routes(), params=params)
    (into,) = payload["pulse"]["edges"]["route:route1"]["packets"]
    (out,) = payload["pulse"]["edges"]["route:route2"]["packets"]
    stem_in, stem_out = "rail:mzm1:0:0", "rail:mzm1:1:0"                  # the input stage's stem; the output stem
    at = [t * payload["seconds_per_ps"] for t in (into["t1"], out["t0"])]
    probe = (f"(odLight.setEnabled(true), [odLight.frameAt({at[0]}), odLight.debugEnds(), "
             f"odLight.frameAt({at[1]}), odLight.debugEnds()].filter((v, i) => i % 2))")
    entry, exit_ = _probe(_mzm_between_two_routes(), probe, params=params)
    assert entry["route:route1"]["last"] > 0.3
    assert entry["route:route1"]["tip"] == pytest.approx(entry["route:route1"]["last"], rel=1e-6)   # no dip at the joint
    assert entry[stem_in]["first"] == pytest.approx(entry["route:route1"]["last"], rel=0.01)
    assert exit_["route:route2"]["first"] > 0.3
    assert exit_[stem_out]["last"] == pytest.approx(exit_["route:route2"]["first"], rel=0.01)


@needs_chrome
def test_brightness_is_relative_to_the_source_power():
    """A dim source (a quarter of unit power) still draws its full light at full brightness."""

    scene = build_preset("ring_resonator_chip")
    from optodraw.animation3d.inputs import default_inputs

    (found,), _ = default_inputs(scene)
    inputs = [InputSignal(found.target, jones=(0.5, 0.0, 0.0, 0.0))]
    payload = build_light_payload(scene, inputs=inputs)
    (packet,) = payload["pulse"]["edges"]["route:route1"]["packets"]
    power = sum(v * v for v in packet["jones"])
    assert payload["source_power"] == pytest.approx(0.25) and power < 0.25
    seconds = 0.5 * (packet["t0"] + packet["t1"]) * payload["seconds_per_ps"]
    glow = _probe(scene, f"(odLight.setEnabled(true), odLight.frameAt({seconds}), odLight.debugGlow())", inputs=inputs)
    assert glow["route:route1"]["peak"] == pytest.approx(math.sqrt(power / 0.25), rel=0.01)


@needs_chrome
def test_a_packet_glows_on_its_edge_at_its_time_with_root_power_brightness_and_repeats_each_train_period():
    payload = build_light_payload(build_preset("ring_resonator_chip"))
    (packet,) = payload["pulse"]["edges"]["route:route1"]["packets"]
    power = sum(v * v for v in packet["jones"])
    reference = payload["source_power"]                                  # the input's power: unit power here
    seconds = 0.5 * (packet["t0"] + packet["t1"]) * payload["seconds_per_ps"]     # the caption's time scale
    period = payload["train_period_ps"] * payload["seconds_per_ps"]
    probe = (f"(odLight.setEnabled(true), [odLight.frameAt({seconds}), odLight.debugGlow(), "
             f"odLight.frameAt({seconds + period}), odLight.debugGlow()].filter((v, i) => i % 2))")
    first, again = _probe("ring_resonator_chip", probe)
    for glow in (first, again):
        assert glow["route:route1"]["peak"] == pytest.approx(math.sqrt(power / reference), rel=0.01)
        assert glow["route:route1"]["color"] == "#ffffff"
    assert "route:route5" not in first                                  # the first pulse reaches it later


@needs_chrome
def test_free_space_light_rides_the_beams_in_its_own_colour():
    payload = build_light_payload(build_preset("ftir"))
    ((nm, colour),) = payload["colors"].items()
    first = min((p for e, edge in payload["pulse"]["edges"].items() if e.startswith("beam:") for p in edge["packets"]),
                key=lambda p: p["t0"])
    seconds = 0.5 * (first["t0"] + first["t1"]) * payload["seconds_per_ps"]
    rows, glow = _probe("ftir", f"(odLight.setEnabled(true), odLight.frameAt({seconds}), "
                                "[odLight.debugPlacement(), odLight.debugGlow()])")
    assert rows and all(row["inside"] for row in rows), [row for row in rows if not row["inside"]]
    beams = {edge: g for edge, g in glow.items() if edge.startswith("beam:")}
    assert beams and all(g["color"] == colour for g in beams.values()), (nm, beams)


SLOW_PRESETS = {"wdm_delay_weight_bank_chip"}        # a 16 s payload; its own test checks it in the Field look


@needs_chrome
@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
@pytest.mark.parametrize("preset", [pytest.param(name, marks=pytest.mark.slow) if name in SLOW_PRESETS else name
                                    for name in list_presets()])
def test_every_preset_draws_its_light_inside_its_hosts(preset):
    """Every lit edge and rail of every preset lies inside its host: a guide at mid-height, a beam's tube, or a
    free-space optic's body. A thin optic (an iris) is drawn thinner than the span between its ports: along the beam
    its aperture runs from port to port, as the spec's straight fallback for thin optics has it."""

    rows, enabled = _probe(preset, "[odLight.debugPlacement(), __odLightData.enabled]")
    assert enabled and rows
    assert all(row["inside"] for row in rows), [row for row in rows if not row["inside"]]


@needs_chrome
def test_a_thin_optic_aperture_reaches_only_half_a_unit_past_its_body():
    """Ruling 52: the iris's ports lie 0.22 past its drawn body along the beam (inside); an iris path whose end runs
    2 units farther along the beam reads outside."""

    html = page_with_probe("free_space_breadboard", "odLight.debugPlacement()")
    payload = _embedded_payload(html)
    edge = "path:iris1:in->out"
    assert next(row for row in _probe_html(html) if row["edge"] == edge)["inside"]
    points = payload["pulse"]["edges"][edge]["points"]
    (x0, y0), (x1, y1) = points[0], points[-1]
    length = math.hypot(x1 - x0, y1 - y0)
    points[-1] = [x1 + 2.0 * (x1 - x0) / length, y1 + 2.0 * (y1 - y0) / length]
    far = re.sub(r"window\.__odLightData = \{.*?\};\n", lambda _: "window.__odLightData = " + json.dumps(payload) + ";\n",
                 html, count=1, flags=re.S)
    row = next(row for row in _probe_html(far) if row["edge"] == edge)
    assert not row["inside"] and row["worst_um"] > 1.0, row


@needs_chrome
def test_the_light_button_says_why_there_is_no_light():
    with pytest.warns(RuntimeWarning, match=REFUSED):
        page = page_with_probe(_periscope_bench(), "[document.getElementById('anim-toggle').disabled, "
                                                   "document.getElementById('anim-toggle').title]")
    report = run_page(page)
    assert json.loads(report) == [True, REFUSED], report


WORLD_PROBE = """(function () {
  const px = (c) => { const d = c.getContext('2d').getImageData(0, 0, 2, 256).data; const h = (i) => '#' + [0, 1, 2].map((k) => d[i + k].toString(16).padStart(2, '0')).join('');
    return [h(0), h(255 * 8)]; };
  const bg = () => px(__odWorld.background().image);
  const out = { before: bg() };
  odLight.setEnabled(true); out.on = bg();
  odLight.setEnabled(false); out.off = bg();
  odLight.setEnabled(true); __odWorld.apply('light'); out.picked = bg();
  odLight.setEnabled(false); out.after_pick = bg();
  return out; })()"""


def _near(colour: str, want: str) -> bool:
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (colour, want))
    return all(abs(x - y) <= 3 for x, y in zip(a, b))


@needs_chrome
@pytest.mark.parametrize("look", ["light", "field"])
def test_the_world_turns_navy_while_the_light_plays_and_comes_back(look):
    out = _probe("ring_resonator_chip", WORLD_PROBE, look=look)
    assert _near(out["on"][0], "#0b1033") and _near(out["on"][1], "#151a4a"), out["on"]
    assert out["off"] == out["before"] and _near(out["before"][0], "#eef1f4"), out
    assert _near(out["picked"][0], "#eef1f4"), out["picked"]          # the View menu can still pick Light
    assert out["after_pick"] == out["picked"], out                    # and the light going off leaves that pick


# Edges that lie outside only because a part has no drawn internal path or the engine jumps a coupling gap, with
# the task that fixes them (Tasks 5 to 9). None in this scene.
MIXED_IDS_OUTSIDE: dict[str, str] = {}


def _chip_on_bench() -> Scene:
    """A laser and a lens on the bench, a grating coupler and a photodetector on a chip (Review Focus 3)."""

    from optodraw import Lens, OnChipPhotodetector, VerticalGratingCoupler

    scene = Scene(title="Chip on a bench")
    laser = scene.add(Laser(center=(-80, 0)))
    lens = scene.add(Lens(center=(-40, 0)))
    coupler = scene.add(VerticalGratingCoupler(center=(0, 0)))
    detector = scene.add(OnChipPhotodetector(center=(-60, 30)))
    scene.add(Beam((laser, "out"), (lens, "in")))
    scene.add(Beam((lens, "out"), (coupler, "f1")))
    scene.route((coupler, "o1"), (detector, "o1"))
    return scene


@needs_chrome
def test_a_chip_on_a_bench_draws_every_edge_inside_at_its_own_height():
    scene = _chip_on_bench()
    assert "const CHIP_LIFT = 8.2" in scene.render_threejs()
    rows, heights = _probe(scene, "[odLight.debugPlacement(), odLight.debugHeights()]")
    outside = {row["edge"] for row in rows if not row["inside"]}
    assert outside == set(MIXED_IDS_OUTSIDE), [row for row in rows if not row["inside"]]
    assert {row["edge"] for row in rows} == set(heights)
    lift = 8.2
    beam_heights = {h["min"] for e, h in heights.items() if h["kind"] in ("tube", "axis")}
    assert len(beam_heights) == 1 and all(h["min"] == h["max"] for e, h in heights.items() if h["kind"] in ("tube", "axis"))
    (beam_height,) = beam_heights
    assert beam_height > lift + 10                                   # the bench beams run at the beam height
    chip = {e: h for e, h in heights.items() if h["kind"] == "guide"}
    assert chip and all(h["min"] > lift for h in chip.values()), chip      # the chip sits on the lift
    assert all(h["max"] < beam_height for h in chip.values())


@needs_chrome
def test_enabling_again_while_the_light_plays_keeps_a_world_the_user_picked():
    probe = """(function () {
      const name = () => __odWorld.name();
      odLight.setEnabled(true); __odWorld.apply('dark'); odLight.setEnabled(true);
      const kept = name(); odLight.setEnabled(false);
      return { kept, after: name() }; })()"""
    out = _probe("ring_resonator_chip", probe)
    assert out == {"kept": "dark", "after": "dark"}, out


LOOK_PROBE = """(function () {
  const shot = () => document.querySelector('canvas').toDataURL('image/png');
  const T = %s;
  __odWorld.apply('none'); odLight.frameAt(T); const mask = shot();      // the chip alone, on a clear canvas
  __odWorld.apply('light'); odLight.frameAt(T); const off = shot();
  odLight.setEnabled(true); odLight.frameAt(T); const on = shot();
  __odPT.active = true; odLight.frameAt(T); const unlit = shot(); __odPT.active = false;   // on, the glow hidden
  return [mask, off, on, unlit]; })()"""


def _image(data_url: str):
    import base64
    import io

    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGBA"), float) / 255


def _luminance(image):
    return image[..., 0] * 0.2126 + image[..., 1] * 0.7152 + image[..., 2] * 0.0722


@needs_chrome
@pytest.mark.parametrize("preset", ["ring_resonator_chip", "coherent_receiver_chip"])
def test_the_light_reads_on_a_dark_chip(preset):
    """With the light on the chip reads dark, and the light reads on it: it lights at least 0.3 % of the frame, and its
    stronger half (by the glow it adds) is brighter than the chip round it by 0.1. The light's brightness follows the
    root of its power and does not clip to white (Ruling 24), so faint light lights fewer pixels than a clipped glow."""

    import numpy as np

    payload = build_light_payload(build_preset(preset))
    packets = [p for edge in payload["pulse"]["edges"].values() for p in edge["packets"]]
    span = max(p["t1"] for p in packets) - min(p["t0"] for p in packets)
    seconds = (span + 0.5 * payload["train_period_ps"]) * payload["seconds_per_ps"]          # mid-train
    report = run_page(page_with_probe(preset, LOOK_PROBE % seconds), width=1600, height=1000, timeout=120)
    assert report and not report.startswith("error"), report
    mask, off, on, unlit = (_image(url) for url in json.loads(report))
    chip = mask[..., 3] > 0.5
    amount = np.abs(_luminance(on) - _luminance(unlit))
    glow = amount > 8 / 255
    assert glow.sum() >= 0.003 * glow.size, glow.sum()                     # at least 0.3 % of the frame
    near = np.zeros_like(glow)                                              # the chip within 6 px of the glow
    for dy in range(-6, 7):
        for dx in range(-6, 7):
            near |= np.roll(np.roll(glow, dy, 0), dx, 1)
    around = near & ~glow & chip
    strong = glow & (amount >= np.median(amount[glow]))
    assert strong.sum() >= 0.0015 * glow.size, strong.sum()                # the stronger half: at least 0.15 % of the frame
    assert _luminance(on)[strong].mean() > _luminance(on)[around].mean() + 0.1
    assert _luminance(on)[chip].mean() < _luminance(off)[chip].mean()


COVER_PROBE = """(function () {
  const shot = () => document.querySelector('canvas').toDataURL('image/png');
  const out = []; odLight.setEnabled(true);
  for (const T of %s) {
    __odPT.active = false; odLight.frameAt(T); const on = shot();
    __odPT.active = true; odLight.frameAt(T); out.push([on, shot()]);       // the same frame, the glow hidden
  }
  __odPT.active = false; return out; })()"""


@needs_chrome
@pytest.mark.parametrize("far", [False, True], ids=["default", "far"])
def test_metal_above_a_guide_hides_the_light(far):
    """The ring preset's heaters and their leads lie above the rings and the bus or beside them: no light shows on
    them, at the default camera and at a far zoom (a part far away makes the camera stand back, and the rings sit
    off the middle of the view, where eye rays tilt)."""

    import numpy as np

    from optodraw.registry import build_component

    scene = build_preset("ring_resonator_chip")
    if far:
        scene.add(build_component("Waveguide", center=(1500, 0)))
    payload = build_light_payload(scene)
    packets = [p for edge in payload["pulse"]["edges"].values() for p in edge["packets"]]
    span = max(p["t1"] for p in packets) - min(p["t0"] for p in packets)
    times = [(span + f * payload["train_period_ps"]) * payload["seconds_per_ps"] for f in (0.1, 0.4, 0.7)]
    size = (2400, 1500) if far else (1600, 1000)
    report = run_page(page_with_probe(scene, COVER_PROBE % times, camera_preset="top"), width=size[0], height=size[1],
                      timeout=120)
    assert report and not report.startswith("error"), report
    for on_url, hidden_url in json.loads(report):
        on, hidden = _image(on_url), _image(hidden_url)
        r, g, b = hidden[..., 0], hidden[..., 1], hidden[..., 2]
        gold = (r > b + 0.06) & (g > b + 0.03) & (r >= g)                  # the heater metal, glow hidden
        inner = gold.copy()                                                 # one pixel in from its edge
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                inner &= np.roll(np.roll(gold, dy, 0), dx, 1)
        change = np.abs(_luminance(on) - _luminance(hidden))
        assert inner.sum() > 200 and (change > 8 / 255).sum() > 1000, (inner.sum(), (change > 8 / 255).sum())
        # no glow at all on the metal: the ribbon's width lies in the view plane, so its edges keep its centre's depth
        # (a ribbon across each vertex's eye ray once brought its edge over the heater beside a ring at the far zoom)
        assert int(((change > 8 / 255) & inner).sum()) == 0, int(((change > 8 / 255) & inner).sum())


@needs_chrome
def test_the_scene_lights_dim_while_the_light_plays_and_come_back():
    probe = """(function () {
      const out = { before: __odWorld.lights() };
      odLight.setEnabled(true); out.on = __odWorld.lights();
      odLight.setEnabled(false); out.after = __odWorld.lights();
      __odWorld.apply('dark'); out.dark = __odWorld.lights(); __odWorld.apply('light');
      odLight.setEnabled(true); __odWorld.apply('dark'); out.picked = __odWorld.lights();
      odLight.setEnabled(false); return out; })()"""
    out = _probe("ring_resonator_chip", probe)
    assert out["after"] == pytest.approx(out["before"])                     # every light back as it was
    assert all(on <= before + 1e-9 for on, before in zip(out["on"], out["before"]))
    assert sum(out["on"]) < 0.5 * sum(out["before"])                         # the chip reads dark
    assert out["picked"] == pytest.approx(out["dark"])                       # a world picked meanwhile keeps its lights


def _linear(srgb):
    """sRGB values (0 to 1) to linear light."""

    import numpy as np

    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _rail_samples(payload, part, sid, ports):
    """Per output port, the drawn points of the rail of ``sid`` that ends there, on the stretch where both rails already
    carry their end power (past the coupling) and away from the joint: ``{port: (rail id, [(x, y)])}``."""

    rails = {}
    for d in payload["rails"]:
        for name in ports:
            centre = part.world_port(name).center
            if d["host"] == sid and d["packets"] and math.dist(d["points"][-1], (float(centre.x), float(centre.y))) < 1e-3:
                rails[name] = d
    steady = [i for i in range(len(rails[ports[0]]["points"]) - 2)
              if all(abs(d["packets"][0]["power"][i] - d["packets"][0]["power"][-1]) <= 0.02 * d["packets"][0]["power"][-1]
                     for d in rails.values())]
    return {name: (f"rail:{sid}:{d['section']}:{d['rail']}", [d["points"][i] for i in steady[2:]]) for name, d in rails.items()}


@needs_chrome
def test_a_close_up_keeps_the_brightness_ratio_of_the_two_outputs_of_a_coupler():
    """Close over mzm_mesh_chip's directionalcoupler4, while both outputs carry light: the glow (in linear light, the
    frame with the light less the same frame with the glow hidden) on the o3 rail against the o4 rail is the root of
    their powers' ratio, sqrt(0.0953 / 0.6547), within 20 %. The glow stays below white."""

    import numpy as np

    from optodraw.animation_engine.graph import build_graph

    scene = build_preset("mzm_mesh_chip")
    payload = build_light_payload(scene)
    part = build_graph(scene).parts["directionalcoupler4"]
    samples = _rail_samples(payload, part, "directionalcoupler4", ("o3", "o4"))
    ends = {name: next(d for d in payload["rails"] if f"rail:{d['host']}:{d['section']}:{d['rail']}" == rail)["packets"][0]
            for name, (rail, _) in samples.items()}
    assert ends["o3"]["power"][-1] == pytest.approx(0.0953, abs=1e-3) and ends["o4"]["power"][-1] == pytest.approx(0.6547, abs=1e-3)
    seconds = 0.5 * (ends["o4"]["t0"] + ends["o4"]["t1"]) * payload["seconds_per_ps"]       # both rails lit
    xs = [float(part.world_port(n).center.x) for n in part.ports()]
    ys = [float(part.world_port(n).center.y) for n in part.ports()]
    cx, cy, span = 0.5 * (min(xs) + max(xs)), 0.5 * (min(ys) + max(ys)), max(max(xs) - min(xs), max(ys) - min(ys))
    points = [[rail, x, y] for rail, pts in samples.values() for x, y in pts]
    probe = ("(function(){ const { THREE, camera } = __odCamera(); odLight.setEnabled(true);"
             f" camera.position.set({cx}, {1.6 * span}, {-cy} + 1e-4); camera.lookAt({cx}, 0, {-cy}); camera.updateMatrixWorld();"
             " const shot = () => document.querySelector('canvas').toDataURL('image/png');"
             f" __odPT.active = false; odLight.frameAt({seconds}); const on = shot();"
             f" __odPT.active = true; odLight.frameAt({seconds}); const off = shot(); __odPT.active = false;"
             " const c = document.querySelector('canvas'), h = odLight.debugHeights();"
             f" const px = {json.dumps(points)}.map(([id, x, y]) => {{ const m = h[id];"
             " const v = new THREE.Vector3(x, 0.5 * (m.min + m.max), -y).project(camera);"
             " return [(v.x + 1) / 2 * c.width, (1 - v.y) / 2 * c.height]; });"
             " return [on, off, px]; })()")
    page = page_with_probe(scene, probe, camera_preset="top").replace(
        "function odRenderFrame() {", "window.__odCamera = () => ({ THREE, camera });\nfunction odRenderFrame() {", 1)
    report = run_page(page, width=1600, height=1000, timeout=180)
    assert report and not report.startswith("error"), report
    on_url, off_url, pixels = json.loads(report)
    on, off = _image(on_url)[..., :3], _image(off_url)[..., :3]
    glow = (_linear(on) - _linear(off)) @ np.array([0.2126, 0.7152, 0.0722])
    means, k = {}, 0
    for name, (_, pts) in samples.items():
        values = []
        for x, y in pixels[k:k + len(pts)]:
            col, row = int(round(x)), int(round(y))
            if 1 <= col < glow.shape[1] - 1 and 1 <= row < glow.shape[0] - 1:
                values.append(glow[row - 1:row + 2, col - 1:col + 2].mean())
        k += len(pts)
        assert len(values) >= 8, name
        means[name] = float(np.mean(values))
    assert means["o3"] / means["o4"] == pytest.approx(math.sqrt(0.0953 / 0.6547), rel=0.2), means
    assert on.max() < 250 / 255


@needs_chrome
@pytest.mark.parametrize("preset", ["mzm_mesh_chip", "ring_resonator_chip"])
def test_in_a_full_chip_view_the_brightest_guide_stays_below_white(preset):
    """At times through the train, the brightest pixel the glow lights (where it adds more than 8/255) is below white:
    overlapping glows (a coupler's rails, guides closer than the ribbon's least width) do not add up to white."""

    payload = build_light_payload(build_preset(preset))
    packets = [p for edge in payload["pulse"]["edges"].values() for p in edge["packets"]]
    start, span = min(p["t0"] for p in packets), max(p["t1"] for p in packets) - min(p["t0"] for p in packets)
    times = [(start + f * span) * payload["seconds_per_ps"] for f in (0.3, 0.6, 0.9)]
    probe = ("(function(){ const shot = () => document.querySelector('canvas').toDataURL('image/png'); const out = [];"
             " odLight.setEnabled(true); for (const T of %s) { __odPT.active = false; odLight.frameAt(T); const on = shot();"
             " __odPT.active = true; odLight.frameAt(T); out.push([on, shot()]); } __odPT.active = false; return out; })()"
             ) % json.dumps(times)
    report = run_page(page_with_probe(preset, probe, camera_preset="top"), width=1600, height=1000, timeout=180)
    assert report and not report.startswith("error"), report
    lit_any = False
    for on_url, off_url in json.loads(report):
        on, off = _image(on_url)[..., :3], _image(off_url)[..., :3]
        lit = (on - off).max(axis=2) > 8 / 255
        if lit.any():
            lit_any = True
            assert on[lit].max() < 250 / 255, float(on[lit].max())
    assert lit_any


# ---- the Field look ------------------------------------------------------------------------------------------------


def _mzi_scene() -> Scene:
    """A laser, an MZI with two couplers, a detector on each output."""

    import optodraw

    scene = Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzi = scene.add(optodraw.MZI(center=(0, 0)))
    d3 = scene.add(optodraw.OnChipPhotodetector(center=(160, 40)))
    d4 = scene.add(optodraw.OnChipPhotodetector(center=(160, -40)))
    scene.route((laser, "o1"), (mzi, "o1"), kind="waveguide")
    scene.route((mzi, "o3"), (d3, "o1"), kind="waveguide")
    scene.route((mzi, "o4"), (d4, "o1"), kind="waveguide")
    return scene


def _steady_seconds(payload) -> float:
    """A time after the last arrival front of the steady state, in the page's seconds."""

    last = max(r["t1"] for e in payload["cw"]["edges"].values() for r in e["cw"])
    return (last + 0.2) * payload["seconds_per_ps"]


def _glow_along(page_scene, probe_times, strips, camera=None, **options):
    """Per time, the light the Field look adds at the drawn points of each strip (world x, y): the frame less the same
    frame with the light hidden, in linear light. ``[{strip: (luminance per point, linear rgb per point)}]``; the
    luminance is the largest of the 3 x 3 pixels round the point, the colour their mean. ``camera`` is ``(x, y,
    height)``: a top view over that place; else the top preset."""

    import numpy as np

    points = [[name, x, y] for name, pts in strips.items() for x, y in pts]
    view = "" if camera is None else (f" camera.position.set({camera[0]}, {camera[2]}, {-camera[1]} + 1e-4);"
                                      f" camera.lookAt({camera[0]}, 0, {-camera[1]}); camera.updateMatrixWorld();")
    probe = ("(function(){ const { THREE, camera } = __odCamera(); odLight.setEnabled(true);" + view +
             " const shot = () => document.querySelector('canvas').toDataURL('image/png'); const out = [];"
             f" for (const T of {json.dumps(probe_times)}) {{ __odPT.active = false; odLight.frameAt(T); const on = shot();"
             " __odPT.active = true; odLight.frameAt(T); out.push([on, shot()]); } __odPT.active = false;"
             " const c = document.querySelector('canvas');"
             f" const px = {json.dumps(points)}.map(([id, x, y]) => {{"
             " const v = new THREE.Vector3(x, 0, -y).project(camera); return [(v.x + 1) / 2 * c.width, (1 - v.y) / 2 * c.height]; });"
             " return [out, px]; })()")
    page = page_with_probe(page_scene, probe, camera_preset="top", **options).replace(
        "function odRenderFrame() {", "window.__odCamera = () => ({ THREE, camera });\nfunction odRenderFrame() {", 1)
    report = run_page(page, width=1600, height=1000, timeout=180)
    assert report and not report.startswith("error"), report
    shots, pixels = json.loads(report)
    result = []
    for on_url, off_url in shots:
        on, off = _image(on_url)[..., :3], _image(off_url)[..., :3]
        added = _linear(on) - _linear(off)
        glow = np.abs(added) @ np.array([0.2126, 0.7152, 0.0722])
        found, k = {}, 0
        for name, pts in strips.items():
            values, colours = [], []
            for x, y in pixels[k:k + len(pts)]:
                col, row = int(round(x)), int(round(y))
                if 1 <= col < glow.shape[1] - 1 and 1 <= row < glow.shape[0] - 1:
                    values.append(float(glow[row - 1:row + 2, col - 1:col + 2].max()))
                    colours.append(added[row - 1:row + 2, col - 1:col + 2].reshape(-1, 3).mean(axis=0))
            k += len(pts)
            assert len(values) >= 8, name
            found[name] = (values, colours)
        result.append(found)
    return result


def _hue(rgb) -> float:
    """The hue of a colour, in degrees."""

    import colorsys

    r, g, b = (max(float(v), 0.0) for v in rgb)
    return 360.0 * colorsys.rgb_to_hsv(r, g, b)[0]


def _middle(points, keep=0.6):
    """The middle ``keep`` of a polyline's points (away from the parts at its ends)."""

    n = len(points)
    cut = int(n * (1 - keep) / 2)
    return points[cut:n - cut]


def _dense(points, step=2.0):
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        count = max(1, int(math.dist(a, b) / step))
        out += [[a[0] + (b[0] - a[0]) * k / count, a[1] + (b[1] - a[1]) * k / count] for k in range(1, count + 1)]
    return out


@needs_chrome
def test_the_field_look_shows_the_dark_output_of_an_mzi_at_phase_pi():
    """The frame responds to the arms' phase: at phase 0 the o4 output strip is lit and o3 dark, at phase pi o4 is dark
    (its light under 10 % of its light at phase 0) and o3 lit; the lit strip shows crests and troughs, red and blue.
    The sampled intensities (odLight.debugField) agree, and inside the MZI the second coupler's rail that ends at o4 is
    dark at its end at phase pi."""

    import numpy as np

    at_pi = build_light_payload(_mzi_scene(), params={"phase:mzi1:arm1": math.pi}, look="field")
    at_zero = build_light_payload(_mzi_scene(), params={"phase:mzi1:arm1": 0.0}, look="field")
    strips = {"o3": _dense(_middle(at_pi["cw"]["edges"]["route:route2"]["points"])),
              "o4": _dense(_middle(at_zero["cw"]["edges"]["route:route3"]["points"]))}
    assert "route:route3" not in at_pi["cw"]["edges"] and "route:route2" not in at_zero["cw"]["edges"]
    seconds = _steady_seconds(at_pi)
    light, colours = {}, None
    for phase in (0.0, math.pi):
        (frame,) = _glow_along(_mzi_scene(), [seconds], strips, params={"phase:mzi1:arm1": phase}, look="field")
        light[phase] = {name: float(np.mean(values)) for name, (values, _) in frame.items()}
        colours = frame["o3"][1] if phase else colours
    assert light[0.0]["o4"] > 0.02 and light[math.pi]["o3"] > 0.02, light
    assert light[math.pi]["o4"] < 0.1 * light[0.0]["o4"], light                # the o4 strip goes dark
    assert light[0.0]["o3"] < 0.1 * light[math.pi]["o3"], light                # and o3 lights
    assert any(r > b + 0.05 for r, g, b in colours) and any(b > r + 0.05 for r, g, b in colours)   # crests and troughs

    params = {"phase:mzi1:arm1": math.pi}
    field = _probe(_mzi_scene(), f"(odLight.setEnabled(true), odLight.frameAt({seconds}), odLight.debugField())",
                   params=params, look="field")
    edges = field["edges"]
    assert edges["route:route2"]["mean"] > 0.3
    assert edges.get("route:route3", {"mean": 0.0})["mean"] < 0.1 * edges["route:route2"]["mean"]
    ends = {}
    for rail in at_pi["rails"]:                                               # the second coupler's two rails
        if rail["host"] == "mzi1" and rail["section"] == 1:
            ends[tuple(round(v, 1) for v in rail["points"][-1])] = f"rail:mzi1:1:{rail['rail']}"
    from optodraw.animation_engine.graph import build_graph

    part = build_graph(_mzi_scene()).parts["mzi1"]
    at = {n: min(ends, key=lambda p: math.dist(p, (part.world_port(n).center.x, part.world_port(n).center.y))) for n in ("o3", "o4")}
    assert edges[ends[at["o4"]]]["tail"] < 0.1 * edges[ends[at["o3"]]]["tail"]


def _two_mmis() -> Scene:
    """Two lasers: one feeds an MMI1x2, the other an MMI1x4; a detector on each output."""

    import optodraw
    from optodraw.registry import build_component

    scene = Scene(width=400, height=300, platform="on_chip")
    for row, kind in ((80.0, "MMI1x2"), (-80.0, "MMI1x4")):
        laser = scene.add(optodraw.OnChipLaser(center=(-120, row)))
        mmi = scene.add(build_component(kind, center=(0, row)))
        scene.route((laser, "o1"), (mmi, "o1"), kind="waveguide")
        outs = [n for n in mmi.ports() if n != "o1"]
        for k, name in enumerate(outs):
            det = scene.add(optodraw.OnChipPhotodetector(center=(120, row + 25 * (k - (len(outs) - 1) / 2))))
            scene.route((mmi, name), (det, "o1"), kind="waveguide")
    return scene


@needs_chrome
def test_in_an_mmi_region_the_image_count_at_the_output_plane_equals_the_number_of_outputs():
    """The player draws each MMI body's field from the payload's grid: at the output plane it has one image per output
    port (two for the MMI1x2, four for the MMI1x4). Both looks share one placement: every edge, rail and region of the
    Field look lies inside its host."""

    import numpy as np

    payload = build_light_payload(_two_mmis(), look="field")
    seconds = _steady_seconds(payload)
    rows, field = _probe(_two_mmis(), f"(odLight.setEnabled(true), odLight.frameAt({seconds}), "
                                      "[odLight.debugPlacement(), odLight.debugField()])", look="field")
    assert rows and all(row["inside"] for row in rows), [row for row in rows if not row["inside"]]
    assert any(row["edge"].startswith("region:") for row in rows)
    counts = {}
    for region in field["regions"]:
        out = region["out"]
        top = max(out)
        counts[region["host"]] = len([i for i in range(len(out)) if out[i] >= 0.3 * top
                                      and (i == 0 or out[i] > out[i - 1]) and (i == len(out) - 1 or out[i] >= out[i + 1])])
    assert counts == {"mmi1x21": 2, "mmi1x41": 4}, counts
    # the same count in the frame: over each MMI, the light the field adds along its output face (just inside the body),
    # its strongest colour channel, the largest over eight frames an eighth of a cycle apart (a crest passes every place
    # once a cycle; the colour map draws crests and troughs strongest in red or blue)
    cycle = payload["cw"]["cycle_s"]
    times = [seconds + k * cycle / 8 for k in range(8)]
    seen = {}
    for region in payload["cw"]["regions"]:
        o, u, v = (np.array(c, float) for c in region["corners"])
        face = [list(o + 0.97 * (u - o) + t * (v - o)) for t in np.linspace(0.02, 0.98, 90)]
        centre = o + 0.5 * (u - o) + 0.5 * (v - o)
        frames = _glow_along(_two_mmis(), times, {"face": face}, camera=(centre[0], centre[1], 3.0 * float(np.linalg.norm(v - o))),
                             look="field")
        light = np.max([[max(c) for c in frame["face"][1]] for frame in frames], axis=0)
        top = light.max()
        seen[region["host"]] = len([i for i in range(len(light)) if light[i] >= 0.3 * top
                                    and (i == 0 or light[i] > light[i - 1]) and (i == len(light) - 1 or light[i] >= light[i + 1])])
    assert seen == {"mmi1x21": 2, "mmi1x41": 4}, seen


@needs_chrome
def test_before_the_front_arrives_an_edge_is_dark_and_the_front_fades_in_over_one_crest():
    """In the frame with the front half way along route1: route1 is lit more than a crest behind the front and dark
    ahead of it, and route3 (not reached yet) is dark. debugField gives the same: a ramp of about one crest."""

    import numpy as np

    payload = build_light_payload(_mzi_scene(), look="field")
    edge = payload["cw"]["edges"]["route:route1"]
    (record,) = edge["cw"]
    later = payload["cw"]["edges"]["route:route3"]["cw"][0]               # o4: lit at phase 0
    t = record["t0"] + 0.5 * (record["t1"] - record["t0"])                    # the front half way along route1
    assert later["t0"] > t
    route = _dense(edge["points"], step=0.5)
    arcs = np.concatenate([[0.0], np.cumsum([math.dist(a, b) for a, b in zip(route, route[1:])])])
    fraction = arcs / arcs[-1]
    (frame,) = _glow_along(_mzi_scene(), [t * payload["seconds_per_ps"]],
                           {"route1": route, "route3": _middle(payload["cw"]["edges"]["route:route3"]["points"])}, look="field")
    light = np.array(frame["route1"][0])
    assert len(light) == len(route)
    crest = record["crest_um"] / arcs[-1]                                      # one crest, as a fraction of the route
    behind, ahead = light[fraction < 0.5 - 1.2 * crest], light[fraction > 0.5 + 0.1 * crest]
    level = np.percentile(behind, 90)
    assert level > 0.02 and behind.min() > 0.1 * level, (level, behind.min())   # lit behind the front
    assert ahead.max() < 0.03 * level, (ahead.max(), level)                     # dark ahead of it
    assert max(frame["route3"][0]) < 0.03 * level                               # not reached yet: dark

    probe = f"(odLight.setEnabled(true), odLight.frameAt({t * payload['seconds_per_ps']}), odLight.debugField(['route:route1']))"
    field = _probe(_mzi_scene(), probe, look="field")
    assert field["edges"]["route:route3"]["max"] == 0.0
    samples = field["edges"]["route:route1"]["samples"]                         # [[arc fraction, intensity], ...]
    full = record["amp"] ** 2
    lit = [f for f, i in samples if i > 0.9 * full]
    dark = [f for f, i in samples if i < 1e-9]
    assert lit and dark and max(lit) < min(dark)
    ramp = (min(dark) - max(lit)) * edge["length_um"]
    assert 0.3 * record["crest_um"] <= ramp <= 1.5 * record["crest_um"], (ramp, record["crest_um"])


@needs_chrome
def test_in_the_light_world_the_glow_never_takes_light_away():
    """The glows combine as light on a screen does: a + b (1 - a), with the glow a at most 1. In the light world
    (picked from the View menu while the light plays) no pixel gets darker with the light on. The "high" quality
    draws into a float target, where a part can be brighter than 1 (white) before the tone curve: with the scene's
    lights raised 12 times, the chip under the glow is such a part. There a + b (1 - a) = 1 + (b - 1)(1 - a) stays
    above 1: a pixel may come down toward white, but never below the white of the tone curve."""

    payload = build_light_payload(build_preset("ring_resonator_chip"))
    packets = [p for edge in payload["pulse"]["edges"].values() for p in edge["packets"]]
    span = max(p["t1"] for p in packets) - min(p["t0"] for p in packets)
    seconds = (span + 0.2 * payload["train_period_ps"]) * payload["seconds_per_ps"]
    probe = ("(function(){ const shot = () => document.querySelector('canvas').toDataURL('image/png'); const out = [];"
             " odLight.setEnabled(true); __odWorld.apply('light');"
             " for (const boost of [1, 12]) { __odScene().traverse((o) => { if (o.isLight) o.intensity *= boost; });"
             f" __odPT.active = false; odLight.frameAt({seconds}); const on = shot();"
             f" __odPT.active = true; odLight.frameAt({seconds}); out.push([on, shot()]); }}"
             " __odPT.active = false; return out; })()")
    page = page_with_probe("ring_resonator_chip", probe, camera_preset="top").replace(
        "function odRenderFrame() {", "window.__odScene = () => scene;\nfunction odRenderFrame() {", 1)
    report = run_page(page, width=1600, height=1000, timeout=180)
    assert report and not report.startswith("error"), report
    (normal_on, normal_off), (bright_on, bright_off) = ((_image(a)[..., :3], _image(b)[..., :3]) for a, b in json.loads(report))
    assert ((normal_on - normal_off).max(axis=2) > 8 / 255).sum() > 1000          # the light shows
    assert int(((normal_off - normal_on).max(axis=2) > 8 / 255).sum()) == 0         # and takes nothing away
    darker = (bright_off - bright_on).max(axis=2) > 8 / 255
    # linear 1.0 after the renderer's Neutral tone curve (exposure 1) is about 240 of 255 in sRGB
    assert int((darker & (bright_on.max(axis=2) < 230 / 255)).sum()) == 0, int((darker & (bright_on.max(axis=2) < 230 / 255)).sum())


@needs_chrome
def test_a_world_picked_while_the_light_plays_keeps_the_brightness_ratio_of_a_couplers_outputs():
    """The directionalcoupler4 close-up as above, after the user picks the dark world and then the light world while
    the light plays: the o3 and o4 rails' glow keep the root of their powers' ratio within 20 % in both. (Quality
    "high" only: the "fast" quality blends after the tone curve, in sRGB values, and does not keep the ratio.)"""

    import numpy as np

    from optodraw.animation_engine.graph import build_graph

    scene = build_preset("mzm_mesh_chip")
    payload = build_light_payload(scene)
    part = build_graph(scene).parts["directionalcoupler4"]
    samples = _rail_samples(payload, part, "directionalcoupler4", ("o3", "o4"))
    o4 = next(d for d in payload["rails"] if f"rail:{d['host']}:{d['section']}:{d['rail']}" == samples["o4"][0])["packets"][0]
    seconds = 0.5 * (o4["t0"] + o4["t1"]) * payload["seconds_per_ps"]
    xs = [float(part.world_port(n).center.x) for n in part.ports()]
    ys = [float(part.world_port(n).center.y) for n in part.ports()]
    cx, cy, span = 0.5 * (min(xs) + max(xs)), 0.5 * (min(ys) + max(ys)), max(max(xs) - min(xs), max(ys) - min(ys))
    points = [[rail, x, y] for rail, pts in samples.values() for x, y in pts]
    probe = ("(function(){ const { THREE, camera } = __odCamera(); odLight.setEnabled(true);"
             f" camera.position.set({cx}, {1.6 * span}, {-cy} + 1e-4); camera.lookAt({cx}, 0, {-cy}); camera.updateMatrixWorld();"
             " const shot = () => document.querySelector('canvas').toDataURL('image/png'); const out = [];"
             " for (const world of ['dark', 'light']) { __odWorld.apply(world);"
             f" __odPT.active = false; odLight.frameAt({seconds}); const on = shot();"
             f" __odPT.active = true; odLight.frameAt({seconds}); out.push([on, shot()]); __odPT.active = false; }}"
             " const c = document.querySelector('canvas'), h = odLight.debugHeights();"
             f" const px = {json.dumps(points)}.map(([id, x, y]) => {{ const m = h[id];"
             " const v = new THREE.Vector3(x, 0.5 * (m.min + m.max), -y).project(camera);"
             " return [(v.x + 1) / 2 * c.width, (1 - v.y) / 2 * c.height]; });"
             " return [out, px]; })()")
    page = page_with_probe(scene, probe, camera_preset="top").replace(
        "function odRenderFrame() {", "window.__odCamera = () => ({ THREE, camera });\nfunction odRenderFrame() {", 1)
    report = run_page(page, width=1600, height=1000, timeout=180)
    assert report and not report.startswith("error"), report
    shots, pixels = json.loads(report)
    for world, (on_url, off_url) in zip(("dark", "light"), shots):
        on, off = _image(on_url)[..., :3], _image(off_url)[..., :3]
        glow = (_linear(on) - _linear(off)) @ np.array([0.2126, 0.7152, 0.0722])
        means, k = {}, 0
        for name, (_, pts) in samples.items():
            values = []
            for x, y in pixels[k:k + len(pts)]:
                col, row = int(round(x)), int(round(y))
                if 1 <= col < glow.shape[1] - 1 and 1 <= row < glow.shape[0] - 1:
                    values.append(glow[row - 1:row + 2, col - 1:col + 2].mean())
            k += len(pts)
            assert len(values) >= 8, name
            means[name] = float(np.mean(values))
        assert means["o3"] / means["o4"] == pytest.approx(math.sqrt(0.0953 / 0.6547), rel=0.2), (world, means)


@needs_chrome
def test_the_weight_bank_places_every_edge_rail_and_region_inside_its_host():
    """The AWG's slabs are drawn in another, translucent material than its guides: the light that crosses a slab, and
    the slab's field grid, lie inside the slab at its middle height. Every other edge, rail and region of the Field
    look lies inside its host too (one placement for both looks)."""

    rows = _probe("wdm_delay_weight_bank_chip", "odLight.debugPlacement()", look="field")
    assert {row["edge"] for row in rows if row["edge"].startswith("region:awg1:")}       # both slabs, every colour
    assert any(row["edge"].startswith("path:awg1:") for row in rows)
    assert all(row["inside"] for row in rows), [row for row in rows if not row["inside"]]


@needs_chrome
def test_a_slab_only_counts_as_inside_where_a_payload_region_outlines_it():
    """The player counts a sample on a part's translucent body as inside only where a payload region outlines it. With
    each awg1 outline shrunk to a third of its size, the paths that cross the rest of the slabs read outside; with the
    real outlines, inside."""

    html = page_with_probe("wdm_delay_weight_bank_chip", "odLight.debugPlacement()", look="field")
    payload = _embedded_payload(html)
    assert any(region["host"] == "awg1" for region in payload["cw"]["regions"])
    real = _probe_html(html)
    assert any(row["edge"].startswith("path:awg1:") for row in real)
    assert all(row["inside"] for row in real if row["edge"].startswith("path:awg1:"))

    for region in payload["cw"]["regions"]:
        if region["host"] == "awg1":
            cx = sum(x for x, _ in region["outline"]) / len(region["outline"])
            cy = sum(y for _, y in region["outline"]) / len(region["outline"])
            region["outline"] = [[cx + (x - cx) / 3, cy + (y - cy) / 3] for x, y in region["outline"]]
    cut = re.sub(r"window\.__odLightData = \{.*?\};\n", lambda _: "window.__odLightData = " + json.dumps(payload) + ";\n",
                 html, count=1, flags=re.S)
    rows = _probe_html(cut)
    outside = [row["edge"] for row in rows if not row["inside"]]
    assert outside and all(edge.startswith("path:awg1:") for edge in outside), outside


def _probe_html(html: str):
    report = run_page(html, timeout=120)
    assert report and not report.startswith("error"), report
    return json.loads(report)


@needs_chrome
def test_each_channel_of_the_weight_bank_draws_its_field_in_its_own_colour():
    """Several wavelengths each get their own colour in the Field look too: the light the field adds along each AWG
    channel guide (one wavelength each) has the hue of that channel's colour, and the four channels differ."""

    import numpy as np

    payload = build_light_payload(build_preset("wdm_delay_weight_bank_chip"), look="field")
    strips, want = {}, {}
    for edge_id, edge in payload["cw"]["edges"].items():
        for record in edge["cw"]:
            if edge_id.startswith("route:") and record["to"].startswith("port:awg1:o"):
                name = record["to"].rsplit(":", 1)[1]
                strips[name] = _dense(_middle(edge["points"]), step=1.0)
                want[name] = payload["colors"][str(record["wavelength_nm"])]
    assert len(strips) == 4 and len(set(want.values())) == 4
    (frame,) = _glow_along("wdm_delay_weight_bank_chip", [_steady_seconds(payload)], strips, look="field")
    hues = {}
    for name, (values, colours) in frame.items():
        lit = [c for v, c in zip(values, colours) if v > 0.2 * max(values)]
        assert len(lit) >= 8, name
        hues[name] = _hue(np.mean(lit, axis=0))
        target = _hue(_linear(np.array([int(want[name][i:i + 2], 16) for i in (1, 3, 5)], float) / 255))
        assert min(abs(hues[name] - target), 360 - abs(hues[name] - target)) < 25, (name, hues[name], target)


@needs_chrome
def test_a_visible_laser_draws_its_field_in_its_true_colour():
    """A 532 nm input draws a green field (its true colour), not red, white and blue."""

    import numpy as np

    from optodraw.animation3d.inputs import default_inputs

    scene = build_preset("ring_resonator_chip")
    (found,), _ = default_inputs(scene)
    inputs = [InputSignal(found.target, wavelength_nm=532.0)]
    payload = build_light_payload(scene, inputs=inputs, look="field")
    strip = {"route1": _dense(_middle(payload["cw"]["edges"]["route:route1"]["points"]), step=1.0)}
    (frame,) = _glow_along(scene, [_steady_seconds(payload)], strip, inputs=inputs, look="field")
    values, colours = frame["route1"]
    lit = np.mean([c for v, c in zip(values, colours) if v > 0.2 * max(values)], axis=0)
    assert lit[1] > 2 * lit[0] and lit[1] > 2 * lit[2], lit                    # green, from the true colour


@needs_chrome
def test_the_field_look_draws_a_zero_crossing_dimmer_than_a_crest():
    """The opacity follows |e| (fieldWeight): at one place the light the Field look adds a quarter cycle after a crest,
    at a zero crossing, is under 0.6 of what it added at the crest."""

    import numpy as np

    from optodraw.animation3d.inputs import default_inputs

    scene = build_preset("ring_resonator_chip")
    (found,), _ = default_inputs(scene)
    inputs = [InputSignal(found.target, wavelength_nm=532.0)]                 # a visible colour: its tint does not hide the weight
    payload = build_light_payload(scene, inputs=inputs, look="field")
    strip = {"route1": _dense(_middle(payload["cw"]["edges"]["route:route1"]["points"]), step=0.5)}
    seconds = _steady_seconds(payload)
    crest_frame, zero_frame = _glow_along(scene, [seconds, seconds + payload["cw"]["cycle_s"] / 4], strip, inputs=inputs,
                                          look="field")
    crest, zero = (np.array(frame["route1"][0]) for frame in (crest_frame, zero_frame))
    at_crest = crest >= 0.8 * crest.max()
    assert at_crest.sum() >= 5
    assert zero[at_crest].mean() < 0.6 * crest[at_crest].mean(), (zero[at_crest].mean(), crest[at_crest].mean())


# ---- heat and RF in the Field look ---------------------------------------------------------------------------------


def _heated_ring_scene():
    import optodraw
    from optodraw.components.onchip.rings import MicroringResonator

    scene = Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    ring = scene.add(MicroringResonator(center=(0, 0), with_heater=True))
    det = scene.add(optodraw.OnChipPhotodetector(center=(150, 0)))
    scene.route((laser, "o1"), (ring, "o1"), kind="waveguide")
    scene.route((ring, "o2"), (det, "o1"), kind="waveguide")
    return scene


def _driven_mzm_scene():
    import optodraw
    from optodraw.registry import build_component

    scene = Scene(width=360, height=160, platform="on_chip")
    laser = scene.add(optodraw.OnChipLaser(center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    det = scene.add(optodraw.OnChipPhotodetector(center=(160, 0)))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (det, "o1"), kind="waveguide")
    return scene


HEAT_PARAMS = {"heater:microringresonator1": 15.0}


@needs_chrome
def test_heat_and_rf_show_only_in_the_field_look():
    heat = {look: _probe(_heated_ring_scene(), "(odLight.setEnabled(true), odLight.frameAt(1.0), odLight.debugEffects())", params=HEAT_PARAMS,
                         look=look) for look in ("light", "field")}
    assert [e["kind"] for e in heat["field"]] == ["heat"] and [e["visible"] for e in heat["field"]] == [True]
    assert [e["visible"] for e in heat["light"]] == [False]
    rf = {look: _probe(_driven_mzm_scene(), "(odLight.setEnabled(true), odLight.frameAt(1.0), odLight.debugEffects())", params={"drive:mzm1": 1.0},
                       look=look) for look in ("light", "field")}
    assert [e["kind"] for e in rf["field"]] == ["rf"] and [e["visible"] for e in rf["field"]] == [True]
    assert [e["visible"] for e in rf["light"]] == [False]


@needs_chrome
def test_the_cladding_round_a_driven_heater_is_warmer_in_colour_than_far_from_it_and_warms_with_time():
    """Field look, a ring heater driven at 15 mW: the light the page adds on the cladding just outside the heater's metal is warm (red over blue)
    and bright; 45 um above it, it is under a tenth of that. At time 0 the spine is still cold."""

    import numpy as np

    payload = build_light_payload(_heated_ring_scene(), params=HEAT_PARAMS, look="field")
    (heat,) = payload["heat"]
    upper = [p for p in heat["path"] if p[1] > 3]
    beside = [[x * (1 + 1.6 / 13.15), y * (1 + 1.6 / 13.15)] for x, y in upper]   # on the cladding, just outside the metal
    strips = {"near": beside, "far": [[x, y + 45.0] for x, y in upper]}
    cold, warm = _glow_along(_heated_ring_scene(), [0.0, max(_steady_seconds(payload), 2.0)], strips, params=HEAT_PARAMS,
                             look="field")
    near = np.mean(np.array(warm["near"][1]), axis=0)
    assert near[0] > 0.03 and near[0] > 2 * near[2], near                         # warm: red over blue
    assert np.mean(warm["far"][0]) < 0.1 * np.mean(warm["near"][0]), (np.mean(warm["far"][0]), np.mean(warm["near"][0]))
    assert np.mean(cold["near"][0]) < 0.2 * np.mean(warm["near"][0])


@needs_chrome
def test_a_driven_mzm_shows_the_rf_in_its_electrode_gap_as_a_wave_of_both_signs():
    """Field look, drive 1 V: between the electrodes (clear of the arm) the page adds light with green crests and magenta
    troughs along the electrodes; with no drive the same places add under a tenth of that."""

    import numpy as np

    payload = build_light_payload(_driven_mzm_scene(), params={"drive:mzm1": 1.0}, look="field")
    (rf,) = payload["rf"]
    x0, x1 = rf["signal"][0][0], rf["signal"][1][0]
    y = rf["ground"][0][1] + 0.3 * (rf["signal"][0][1] - rf["ground"][0][1])      # the lower third of the gap
    strip = {"gap": [[x0 + (x1 - x0) * k / 60.0, y] for k in range(6, 55)]}
    (driven,) = _glow_along(_driven_mzm_scene(), [1.0], strip, params={"drive:mzm1": 1.0}, look="field")
    (idle,) = _glow_along(_driven_mzm_scene(), [1.0], strip, params={"drive:mzm1": 0.0}, look="field")
    values, colours = driven["gap"]
    assert np.mean(values) > 0.01 and np.mean(idle["gap"][0]) < 0.1 * np.mean(values), (np.mean(values), np.mean(idle["gap"][0]))
    lit = [c for v, c in zip(values, colours) if v > 0.3 * max(values)]
    assert any(c[1] > 2 * c[0] for c in lit) and any(c[0] > 2 * c[1] for c in lit), lit[:6]


def _luminance_at(scene, points, time, params, **options):
    """The luminance (linear light) at each point (world x, y) in four frames of one time: ``base`` (nothing of the light
    drawn), ``optical`` (the field's ribbons alone), ``both`` (ribbons and the heat or RF) and ``effects`` (heat or RF
    alone), and the frame ``effects`` with its alpha, for a mask."""

    import numpy as np

    probe = ("(function(){ const { THREE, camera } = __odCamera(); odLight.setEnabled(true);"
             " const shot = () => document.querySelector('canvas').toDataURL('image/png'); const out = {};"
             f" odLight.frameAt({time});"
             " for (const [name, a, b] of [['base', false, false], ['optical', false, true], ['both', true, true], ['effects', true, false]]) {"
             f" odLight.debugShow(a, b); odLight.frameAt({time}); out[name] = shot(); }}"
             " const c = document.querySelector('canvas');"
             f" const px = {json.dumps(points)}.map(([x, y]) => {{"
             " const v = new THREE.Vector3(x, 0, -y).project(camera); return [(v.x + 1) / 2 * c.width, (1 - v.y) / 2 * c.height]; });"
             " return [out, px]; })()")
    page = page_with_probe(scene, probe, camera_preset="top", params=params, look="field", **options).replace(
        "function odRenderFrame() {", "window.__odCamera = () => ({ THREE, camera });\nfunction odRenderFrame() {", 1)
    report = run_page(page, width=1600, height=1000, timeout=180)
    assert report and not report.startswith("error"), report
    shots, pixels = json.loads(report)
    out = {}
    for name, url in shots.items():
        image = _linear(_image(url)[..., :3])
        lum = image @ np.array([0.2126, 0.7152, 0.0722])
        out[name] = np.array([lum[int(round(y)) - 1:int(round(y)) + 2, int(round(x)) - 1:int(round(x)) + 2].mean()
                              for x, y in pixels if 1 <= x < lum.shape[1] - 1 and 1 <= y < lum.shape[0] - 1])
    return out


def _optical_points(payload, host, keep):
    pts = []
    for edge_id, edge in payload["cw"]["edges"].items():
        if payload["hosts"].get(edge_id, {}).get("sid") == host and payload["hosts"][edge_id]["kind"] == "part":
            pts += [p for p in _dense(edge["points"], step=0.5) if keep(p)]
    return pts


@needs_chrome
def test_the_heat_leaves_at_least_half_of_the_optical_fields_light_over_the_ring():

    payload = build_light_payload(_heated_ring_scene(), params=HEAT_PARAMS, look="field")
    (heat,) = payload["heat"]
    near = lambda p: min(math.dist(p, q) for q in heat["path"]) < 4.0                    # noqa: E731
    points = _optical_points(payload, "microringresonator1", near)
    assert len(points) >= 20
    seconds = max(_steady_seconds(payload), 2.0)
    frames = _luminance_at(_heated_ring_scene(), points, seconds, HEAT_PARAMS)
    without, with_heat = frames["optical"] - frames["base"], frames["both"] - frames["effects"]
    assert without.mean() > 0.01 and (frames["effects"] - frames["base"]).mean() > 0.003       # the heat is drawn
    assert with_heat.mean() >= 0.5 * without.mean(), (with_heat.mean(), without.mean())


@needs_chrome
def test_the_rf_leaves_at_least_half_of_the_optical_fields_light_on_the_arm_in_the_gap():
    payload = build_light_payload(_driven_mzm_scene(), params={"drive:mzm1": 1.0}, look="field")
    (rf,) = payload["rf"]
    low, high = sorted((rf["ground"][0][1], rf["signal"][0][1]))
    x0, x1 = rf["signal"][0][0], rf["signal"][1][0]
    points = _optical_points(payload, "mzm1", lambda p: low < p[1] < high and x0 < p[0] < x1)
    assert len(points) >= 20
    frames = _luminance_at(_driven_mzm_scene(), points, 2.0, {"drive:mzm1": 1.0})
    without, with_rf = frames["optical"] - frames["base"], frames["both"] - frames["effects"]
    assert without.mean() > 0.01 and (frames["effects"] - frames["base"]).mean() > 0.002
    assert with_rf.mean() >= 0.5 * without.mean(), (with_rf.mean(), without.mean())


@needs_chrome
def test_the_heat_is_drawn_only_inside_the_chip_outline():
    """The maps carry the chip's outline (the die footprint of the page): it holds the heater, and fragments outside it are
    discarded: with the outline cut through the ring's middle, nothing is drawn to its right."""

    import numpy as np

    probe = """(function () {
      const shot = () => document.querySelector('canvas').toDataURL('image/png');
      __odWorld.apply('none'); odLight.setEnabled(true); odLight.frameAt(2.0);
      const found = odLight.debugEffects();
      odLight.debugShow(false, false); odLight.frameAt(2.0); const base = shot();
      odLight.debugShow(true, false); odLight.frameAt(2.0); const whole = shot();
      odLight.debugClip(-1e9, -1e9, 0, 1e9); odLight.frameAt(2.0); const half = shot();
      return [found, base, whole, half]; })()"""
    page = page_with_probe(_heated_ring_scene(), probe, camera_preset="top", params={"heater:microringresonator1": 20.0}, look="field")
    report = run_page(page, width=1600, height=1000, timeout=180)
    assert report and not report.startswith("error"), report
    found, base, whole, half = json.loads(report)
    (heat,) = [e for e in found if e["kind"] == "heat"]
    x0, z0, x1, z1 = heat["clip"]
    assert -400 < x0 < -20 and 20 < x1 < 400 and -200 < z0 < -13 and 13 < z1 < 200, heat["clip"]   # a finite outline round the heater
    base = _image(base)[..., :3]
    whole, half = (np.abs(_image(url)[..., :3] - base).max(axis=2) > 2 / 255 for url in (whole, half))
    columns = np.nonzero(whole.any(axis=0))[0]
    middle = int((columns.min() + columns.max()) / 2)                  # the heat is round the ring: its middle is the ring's
    assert whole[:, middle + 40:].sum() > 1000
    assert half[:, middle + 40:].sum() == 0 and half[:, :middle - 40].sum() > 1000


@needs_chrome
def test_halving_a_heaters_power_halves_its_drawn_peak():
    params = {"heater:coupledringfilter1:ring1": 20.0, "heater:coupledringfilter1:ring3": 10.0}
    found = _probe("ring_resonator_chip", "(odLight.setEnabled(true), odLight.frameAt(1.0), odLight.debugEffects())",
                   params=params, look="field")
    peak = {e["sid"]: e["peak"] for e in found}
    assert peak["coupledringfilter1:ring1"] == pytest.approx(2 * peak["coupledringfilter1:ring3"], rel=1e-3), peak
    assert 0.2 < peak["coupledringfilter1:ring1"] <= 1.0


CAPTIONS = "(odLight.setEnabled(%s), odLight.frameAt(1.0), (function(){ const e = document.getElementById('od-captions'); return e ? [e.style.display !== 'none', e.innerText.split('\\n')] : null; })())"


# the Field look's block with its Scales toggle closed, then open
FIELD_CAPTIONS = ("(odLight.setEnabled(true), odLight.frameAt(1.0), (function(){ const e = document.getElementById('od-captions');"
                  " const closed = e.innerText.split('\\n'); e.querySelector('.od-scales').click();"
                  " return [e.style.display !== 'none', closed, e.innerText.split('\\n')]; })())")


@needs_chrome
def test_the_page_draws_the_payloads_captions_while_the_light_is_on():
    """The short lines (the time scale, the pulse, the wavelength factor) stay in view; the model lines fold behind the
    Scales toggle and show when it is clicked (Minor 3 of the final review: the block hid part of the circuit)."""

    heater = {"heater:microringresonator1": 15.0}
    light = _probe(_heated_ring_scene(), CAPTIONS % "true", params=heater, look="light")
    shown, closed, opened = _probe(_heated_ring_scene(), FIELD_CAPTIONS, params=heater, look="field")
    off = _probe(_heated_ring_scene(), CAPTIONS % "false", params=heater, look="field")
    shown_light, closed, opened = " ".join(light[1]), " ".join(closed), " ".join(opened)
    assert light[0] and "Time slowed so light crosses" in shown_light and "Pulse" in shown_light
    assert "Wavelength shown x" not in shown_light and "K above the chip" not in shown_light
    assert "1550 nm (infrared) shown white" in shown_light and "shown white" not in opened    # Light look only
    assert shown and "Time slowed so light crosses" in closed and "Wavelength shown x" in closed and "Scales" in closed
    assert "Crest spacing from the group index" not in closed and "K above the chip" not in closed
    assert "Crest spacing from the group index" in opened and "K above the chip" in opened and "us real" in opened
    assert "slower than real" not in opened.split("K above the chip")[0]
    assert off[0] is False                                                       # the light is off: the block is hidden
    assert "\u2014" not in opened and "\u2013" not in opened
    legend = _probe(_heated_ring_scene(), "(odLight.setEnabled(true), odLight.frameAt(1.0), "
                    "document.querySelectorAll('#od-captions .od-legend').length)", params=heater, look="field")
    assert legend == 1


@needs_chrome
def test_record_video_carries_the_folded_captions_while_it_records():
    """Ruling 52: the page's Record video draws the caption block into the WebM, so the folded lines show while it
    records and fold again when it ends."""

    heater = {"heater:microringresonator1": 15.0}
    html = _heated_ring_scene().render_threejs(params=heater, look="field")
    script = ("<textarea id='od-capture' style='display:none'></textarea><script>(function(){"
              "var out=document.getElementById('od-capture');"
              "function text(){return document.getElementById('od-captions').innerText;}"
              "(function wait(){if(!(window.odLight&&window.odLight.state.built)){setTimeout(wait,50);return;}"
              "try{odLight.setEnabled(true);odLight.frameAt(1.0);var before=text();var p=odLight.recordTour(10,0.4);"
              "var during=text();p.then(function(){out.value=JSON.stringify([before,during,text()]);},"
              "function(e){out.value='error: '+e.message;});}catch(e){out.value='error: '+e.message;}})();"
              "})();</script>\n")
    head, tag, tail = html.rpartition("</body>")
    report = run_page(head + script + tag + tail, timeout=120)
    assert report and not report.startswith("error"), report
    before, during, after = json.loads(report)
    line = "Heat time constant is shown as"
    assert line not in before and line in during and line not in after, (before, during, after)


@needs_chrome
def test_the_captions_do_not_cover_the_layer_legend_and_the_bar():
    """A page with a layer legend (bottom left) and the light on: the caption block, the legend and the bar do not overlap,
    and the captions stand above the legend."""

    probe = """(function () {
      odLight.setEnabled(true); odLight.frameAt(1.0);
      const box = (id) => { const e = document.getElementById(id); if (!e) return null; const r = e.getBoundingClientRect();
                            return [r.left, r.top, r.right, r.bottom]; };
      return [box('od-captions'), box('layer-legend'), box('od-bar'), document.getElementById('od-captions').style.display]; })()"""
    legend = {"Waveguide": "#1f77b4", "Metal1": {"color": "#bcc4cc", "label": "M1 routing"}, "VIA": {"color": "#777777"}}
    for width in (1600, 700):
        page = page_with_probe(_heated_ring_scene(), probe, params=HEAT_PARAMS, look="field", layer_legend=legend)
        report = run_page(page, width=width, height=900, timeout=180)
        assert report and not report.startswith("error"), report
        captions, layer, bar, shown = json.loads(report)
        assert shown == "block" and captions and layer and bar

        def overlap(a, b):
            return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

        assert not overlap(captions, layer), (width, captions, layer)
        assert not overlap(captions, bar), (width, captions, bar)
        assert captions[3] <= layer[1] + 1e-6, (width, captions, layer)


@needs_chrome
def test_with_ambient_occlusion_on_the_rf_gap_is_not_darkened_and_the_field_stays_clear():
    """The "high" page draws with ambient occlusion (GTAO). The flat RF map must not feed it: off the arm, in the gap, the
    page with the RF drawn is not darker than with it hidden, and the arm's field keeps at least half of its light."""

    assert _probe(_driven_mzm_scene(), "!!window.__odGTAO", params={"drive:mzm1": 1.0}, look="field", quality="high") is True
    payload = build_light_payload(_driven_mzm_scene(), params={"drive:mzm1": 1.0}, look="field")
    (rf,) = payload["rf"]
    x0, x1 = rf["signal"][0][0], rf["signal"][1][0]
    y = rf["ground"][0][1] + 0.25 * (rf["signal"][0][1] - rf["ground"][0][1])         # in the gap, clear of the arm
    gap = [[x0 + (x1 - x0) * k / 40.0, y] for k in range(4, 37)]
    frames = _luminance_at(_driven_mzm_scene(), gap, 2.0, {"drive:mzm1": 1.0}, quality="high")
    assert (frames["effects"] - frames["base"]).mean() > 0, (frames["effects"] - frames["base"]).mean()   # lighter, not darker
    low, high = sorted((rf["ground"][0][1], rf["signal"][0][1]))
    arm = _optical_points(payload, "mzm1", lambda p: low < p[1] < high and x0 < p[0] < x1)
    arm_frames = _luminance_at(_driven_mzm_scene(), arm, 2.0, {"drive:mzm1": 1.0}, quality="high")
    assert (arm_frames["both"] - arm_frames["effects"]).mean() >= 0.5 * (arm_frames["optical"] - arm_frames["base"]).mean()


# ---- the tour: the camera follows the light from device to device ---------------------------------------------------

TOUR_PROBE = """(function () {
  const caption = () => { const e = document.getElementById('od-captions'); return e && e.style.display !== 'none' ? e.innerText : ''; };
  const snap = () => { const d = odLight.debugTour(); return { t: d.t, focus: d.focus, target: d.target, camera: d.camera,
    labels: d.labels, glass: d.glass, drive: d.drive, light: d.light, ps: d.ps, captions: caption() }; };
  odLight.frameAt(0);
  const before = Object.assign(snap(), { world: __odWorld.name(), enabled: odLight.state.enabled });
  odLight.control('tour', true);
  const plan = odLight.debugTour();
  const during = { world: __odWorld.name(), enabled: odLight.state.enabled };
  const stops = plan.stops.map((s) => { odLight.frameAt(s.arrive + 0.02); const start = snap();
    odLight.frameAt(0.5 * (s.arrive + s.leave)); return { start, mid: snap() }; });
  odLight.frameAt(0.2); const first = snap();
  odLight.frameAt(plan.end - 0.2); const last = snap();
  odLight.control('tour', false);
  odLight.frameAt(0);
  const after = Object.assign(snap(), { world: __odWorld.name(), enabled: odLight.state.enabled });
  return { before, plan, during, stops, first, last, after }; })()"""


def _mzm_to_detector() -> Scene:
    """A laser, a driven MZM, a detector: a driven stop with metal over the guide, then a detector stop."""

    from optodraw.registry import build_component

    scene = Scene(width=400, height=160, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    det = scene.add(build_component("OnChipPhotodetector", center=(160, 0)))
    scene.route((laser, "o1"), (mzm, "o1"), kind="waveguide")
    scene.route((mzm, "o3"), (det, "o1"), kind="waveguide")
    return scene


def _inside(point, box, tol=1e-6) -> bool:
    return all(box[0][k] - tol <= point[k] <= box[1][k] + tol for k in range(3))


def _inside_plan(inner, outer, tol=1e-3) -> bool:
    """Whether a box lies inside another in plan (x and z, the chip's plane)."""

    return all(outer[0][k] - tol <= inner[0][k] and inner[1][k] <= outer[1][k] + tol for k in (0, 2))


@needs_chrome
def test_play_tour_frames_each_stop_in_the_order_the_light_arrives():
    from optodraw.animation3d.tour import scene_tour

    scene = build_preset("coherent_receiver_chip")
    payload = build_light_payload(scene)
    run = _probe(scene, TOUR_PROBE)
    stops = run["plan"]["stops"]
    assert [s["sid"] for s in stops] == [s.sid for s in scene_tour(scene, payload).stops]
    warp = payload["tour_warp"]
    assert [(s["arrive"], s["leave"]) for s in stops] == pytest.approx([(warp[1 + 2 * j][0], warp[2 + 2 * j][0])
                                                                        for j in range(len(stops))])
    assert run["plan"]["end"] == pytest.approx(warp[-1][0])
    for stop, frame in zip(stops, run["stops"]):
        assert frame["mid"]["focus"] == stop["sid"]
        assert _inside(frame["mid"]["target"], stop["box"]), (stop["sid"], frame["mid"]["target"], stop["box"])
        assert frame["mid"]["ps"] == pytest.approx(0.5 * (warp[1 + 2 * stops.index(stop)][1] + warp[2 + 2 * stops.index(stop)][1]),
                                                   rel=1e-6)
    wide = math.dist(run["first"]["camera"], run["first"]["target"])
    assert all(math.dist(f["mid"]["camera"], f["mid"]["target"]) < wide for f in run["stops"])     # closer at each stop
    assert run["first"]["focus"] is None and run["last"]["focus"] is None


@needs_chrome
@pytest.mark.parametrize("labels", [False, True])
def test_only_the_device_in_focus_shows_its_label(labels):
    scene = build_preset("coherent_receiver_chip")
    names = build_light_payload(scene)["tour_names"]
    run = _probe(scene, TOUR_PROBE, show_labels=labels)
    for stop, frame in zip(run["plan"]["stops"], run["stops"]):
        assert frame["mid"]["labels"] == [names[stop["sid"]]], stop["sid"]
    assert run["first"]["labels"] == [] and run["last"]["labels"] == []
    if labels:
        assert len(run["after"]["labels"]) == len(run["before"]["labels"]) > len(run["plan"]["stops"])   # all back
    else:
        assert run["before"]["labels"] == [] and run["after"]["labels"] == []


@needs_chrome
def test_metal_over_the_light_turns_see_through_only_during_its_devices_stop():
    run = _probe(_mzm_to_detector(), TOUR_PROBE)
    mzm, det = run["plan"]["stops"]
    glass = run["stops"][0]["mid"]["glass"]
    assert glass, "the modulator's electrodes turn see-through at its stop"
    for g in glass:
        assert g["transparent"] and g["opacity"] <= 0.3
        assert _inside_plan(g["box"], mzm["box"]) and g["box"][1][1] > mzm["guide_top"], (g, mzm)
    assert all(_inside_plan(g["box"], det["box"]) for g in run["stops"][1]["mid"]["glass"])
    assert run["first"]["glass"] == [] and run["last"]["glass"] == [] and run["after"]["glass"] == []
    assert run["before"]["glass"] == []


def _pass_times(payload, sid):
    """Per pass of the driven stop at part ``sid``: ``(pulse n, drive value, physics ps when it reaches the part, the
    tour's video time then)``. A driven stop runs at the normal rate, so video time follows physics time linearly."""

    stops = payload["tour"]["stops"]
    i = next(k for k, stop in enumerate(stops) if stop["sid"] == sid)
    (va, pa), (vb, pb) = payload["tour_warp"][1 + 2 * i], payload["tour_warp"][2 + 2 * i]
    table = next(t for t in payload["drives"] if t["sid"] == sid)
    out = []
    for n, level in zip(table["passes"], table["levels"]):
        ps = table["first_ps"] + n * payload["train_period_ps"]
        out.append((n, table["values"][level], ps, va + (ps - pa) * payload["seconds_per_ps"]))
    return out, (va, pa, vb, pb)


def _video_at(payload, sid, ps):
    """The tour's video time at physics time ``ps`` inside the hold of the driven stop at ``sid``."""

    (va, pa, vb, pb) = _pass_times(payload, sid)[1]
    assert pa <= ps <= pb, (sid, ps, pa, pb)
    return va + (ps - pa) * payload["seconds_per_ps"]


@needs_chrome
def test_at_each_driven_stop_of_the_mesh_the_output_switches_from_packet_to_packet():
    """Ruling 46: at each driven stop of the mesh chip at least 3 packets cross the modulator during the hold, and the
    drawn glow on its output route (where the packet's centre is) differs by more than 50 % between the packet that
    met the lowest drive level and the one that met the highest. The camera sees nothing outside the stop's frame."""

    scene = build_preset("mzm_mesh_chip")
    payload = build_light_payload(scene, drives="tour")
    period, checks = payload["train_period_ps"], []
    assert len(payload["drives"]) == len([s for s in payload["tour"]["stops"] if s["drive"]]) > 0
    for table in payload["drives"]:
        passes, _ = _pass_times(payload, table["sid"])
        assert len(passes) >= 3, table["sid"]
        out = next(e for e, edge in payload["pulse"]["edges"].items()
                   if e.startswith("route:") and any(p["from"].startswith(f"port:{table['sid']}:") for p in edge["packets"]))
        packet = payload["pulse"]["edges"][out]["packets"][0]
        middle = 0.5 * (packet["t0"] + packet["t1"])             # pulse 0's centre at the route's middle
        low = min(passes, key=lambda x: (x[1], x[0]))
        high = max(passes, key=lambda x: (x[1], -x[0]))
        checks.append([table["sid"], out, [_video_at(payload, table["sid"], middle + p[0] * period) for p in (low, high)]])
    probe = """(function () { odLight.control('tour', true);
      return %s.map(([sid, out, times]) => times.map((t) => { odLight.frameAt(t); const d = odLight.debugTour();
        return [odLight.debugGlowAt(out, 0.5), d.focus, d.unframed]; })); })()""" % json.dumps(checks)
    for (sid, out, _), ((low, focus_low, unseen_low), (high, focus_high, unseen_high)) in zip(checks, _probe(scene, probe, tour_drives=True)):
        assert focus_low == focus_high == sid
        assert abs(low - high) > 0.5 * max(low, high), (sid, out, low, high)
        assert unseen_low == [] and unseen_high == [], (sid, unseen_low, unseen_high)


@needs_chrome
def test_a_driven_stop_shows_its_drive_and_the_captions():
    run = _probe(_mzm_to_detector(), TOUR_PROBE, tour_drives=True)
    mid = run["stops"][0]["mid"]
    assert mid["drive"]["param"] == "drive:mzm1"
    assert "Time runs at normal speed while a drive changes" in mid["captions"]
    assert "Drive on MZM 1: 0 to 2 V" in mid["captions"] and "Drives stay as set" not in mid["captions"]
    assert "Time slows at each stop" in run["first"]["captions"] and "Drive on" not in run["first"]["captions"]
    assert "driven stops at 1x" in run["first"]["captions"]                # a drive swings: the rates name it
    assert run["first"]["drive"] is None and run["stops"][1]["mid"]["drive"] is None
    assert "\u2014" not in mid["captions"] and "\u2013" not in mid["captions"]


@needs_chrome
@pytest.mark.parametrize("tour_drives", [False, True])
def test_frame_at_the_same_tour_time_draws_the_same_camera_and_light(tour_drives):
    probe = """(function () { odLight.control('tour', true); const d = odLight.debugTour();
      const t = 0.5 * (d.stops[0].arrive + d.stops[0].leave) + 0.1;
      const shot = () => { odLight.frameAt(t); const s = odLight.debugTour(); return [s.camera, s.target, s.ps, odLight.debugGlow()]; };
      const a = shot(); odLight.frameAt(0.8 * d.end); odLight.frameAt(0.3); return [a, shot()]; })()"""
    first, again = _probe(_mzm_to_detector(), probe, tour_drives=tour_drives)
    assert first == again and first[3]
    assert _probe(_mzm_to_detector(), probe, tour_drives=tour_drives) == [first, again]   # a new page: the same frame


@needs_chrome
def test_the_tour_turns_the_world_navy_and_the_light_on_and_gives_both_back():
    run = _probe(_mzm_to_detector(), TOUR_PROBE)
    assert run["before"]["world"] == "light" and run["before"]["enabled"] is False
    assert run["during"] == {"world": "night", "enabled": True}
    assert run["after"]["world"] == "light" and run["after"]["enabled"] is False
    assert run["after"]["camera"] == run["before"]["camera"] and run["after"]["target"] == run["before"]["target"]


@needs_chrome
def test_the_play_tour_button_starts_and_stops_the_tour():
    probe = """(function () { const b = document.getElementById('light-tour'); const out = [b.disabled];
      b.click(); out.push(odLight.debugTour().active, b.textContent);
      b.click(); out.push(odLight.debugTour().active, b.textContent, document.getElementById('light-record').disabled);
      return out; })()"""
    assert _probe(_mzm_to_detector(), probe) == [False, True, "Stop tour", False, "Play tour", False]


@needs_chrome
def test_the_record_video_button_is_on_and_the_player_records_the_tour():
    probe = """(function () { const b = document.getElementById('light-record');
      const out = [b.disabled, b.title, typeof odLight.recordTour];
      b.click(); out.push(b.disabled, b.textContent);
      return out; })()"""
    run = _probe(_mzm_to_detector(), probe)
    assert run[0] is False and "WebM" in run[1] and "no part labels" in run[1] and run[2] == "function"
    assert run[3] is True and run[4].startswith("Recording")           # a click starts the recording


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_weight_bank_page_carries_its_tour_without_drive_tables_and_stays_under_5_mb():
    html = build_preset("wdm_delay_weight_bank_chip").render_threejs()
    marker = "window.__odLightData = "
    start = html.index(marker) + len(marker)
    text = html[start:html.index(";\n", start)]
    assert len(text.encode()) < 5_000_000, len(text.encode())
    payload = json.loads(text)
    assert [s["sid"] for s in payload["tour"]["stops"] if s["drive"]] and payload["drives"] == []


@needs_chrome
def test_without_drive_tables_the_tour_keeps_the_drives_as_set_and_says_so():
    run = _probe(_mzm_to_detector(), TOUR_PROBE)
    mid = run["stops"][0]["mid"]
    assert mid["drive"] is None and "Drives stay as set in this page" in mid["captions"]    # at its driven stop only
    assert "Drives stay as set" not in run["first"]["captions"] and "Drives stay as set" not in run["stops"][1]["mid"]["captions"]
    assert "Drive on" not in mid["captions"] and "Time runs at normal speed" not in mid["captions"]
    assert "driven stops at 1x" not in run["first"]["captions"]            # no drive swings: the rates say so


@needs_chrome
def test_in_the_field_look_a_driven_stop_swings_the_output_field_and_gives_it_back():
    """The Field look shows the level of the latest packet to reach the part: as set for the first (0 V), dark at
    v_pi. The first stop begins as the first packet arrives."""

    scene = _mzm_to_detector()
    payload = build_light_payload(scene, drives="tour")
    passes, (va, pa, vb, pb) = _pass_times(payload, "mzm1")
    top = max(passes, key=lambda x: x[1])
    times = [va + 0.02, top[3] + 0.01]                          # the first packet; just after the top one arrives
    probe = """(function () { const field = () => odLight.debugTour().field['route:route2'];
      odLight.frameAt(1.0); const before = field(); odLight.control('tour', true);
      const out = %s.map((t) => { odLight.frameAt(t); return [field(), odLight.debugTour().drive.value]; });
      odLight.control('tour', false); odLight.frameAt(1.0); return [before, out, field()]; })()""" % json.dumps(times)
    before, ((start, start_value), (mid, mid_value)), after = _probe(scene, probe, look="field", tour_drives=True)
    assert before > 0 and start == pytest.approx(before) and after == pytest.approx(before) and start_value == 0.0
    assert mid_value == pytest.approx(2.0) and mid < 0.5 * start, (start, mid)          # v_pi: the output goes dark


def _modulator_then_coupler() -> Scene:
    """A laser, a driven MZM, a directional coupler drawn by its rails (inside the modulator's frame), two detectors."""

    from optodraw.registry import build_component

    scene = Scene(width=700, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-250, 0)))
    mzm = scene.add(build_component("MZM", center=(-60, 0)))
    coupler = scene.add(build_component("DirectionalCoupler", center=(60, 0)))
    top = scene.add(build_component("OnChipPhotodetector", center=(190, 40)))
    bottom = scene.add(build_component("OnChipPhotodetector", center=(190, -40)))
    for a, b in (((laser, "o1"), (mzm, "o1")), ((mzm, "o3"), (coupler, "o1")), ((coupler, "o3"), (top, "o1")),
                 ((coupler, "o4"), (bottom, "o1"))):
        scene.route(a, b, kind="waveguide")
    return scene


@needs_chrome
@pytest.mark.parametrize("look", ["light", "field"])
def test_the_coupler_after_the_modulator_follows_each_packets_drive_level(look):
    """The swing reaches the parts after the driven one within the stop's frame: the coupler drawn by its rails is at
    about 0.7 of its brightness (half the power) for the packet that met half of v_pi, and dark for the one that met v_pi.
    The Light look draws each packet where it is; the Field look shows the latest packet's level."""

    scene = _modulator_then_coupler()
    payload = build_light_payload(scene, drives="tour")
    passes, (va, pa, vb, pb) = _pass_times(payload, "mzm1")
    half, top = (next(p for p in passes if p[1] == pytest.approx(v)) for v in (1.0, 2.0))
    rail = payload["rails"][[f"rail:{r['host']}:{r['section']}:{r['rail']}" for r in payload["rails"]].index("rail:directionalcoupler1:0:0")]
    centre = 0.5 * (rail["packets"][0]["t0"] + rail["packets"][0]["t1"])        # pulse 0's centre at the rail's middle
    period = payload["train_period_ps"]
    if look == "light":
        times = [_video_at(payload, "mzm1", centre + p[0] * period) for p in (half, top)]
        before = [_video_at(payload, "mzm1", centre + passes[0][0] * period)]    # the first packet met the drive as set
    else:
        times, before = [half[3] + 0.01, top[3] + 0.01], [va + 0.02]
    probe = """(function () { const now = () => { const d = odLight.debugTour();
        return ['rail:directionalcoupler1:0:0', 'rail:directionalcoupler1:0:1'].map((id) =>
          %r === 'light' ? odLight.debugGlowAt(id, 0.5) : (d.field[id] || 0)); };
      odLight.control('tour', true); return %s.map((t) => { odLight.frameAt(t); return now(); }); })()""" % (look, json.dumps(before + times))
    as_set, at_half, at_top = _probe(scene, probe, look=look, tour_drives=True)
    assert max(as_set) > 0.1, as_set
    assert 0.55 * max(as_set) < max(at_half) < 0.85 * max(as_set), (as_set, at_half)
    assert max(at_top) < 0.1 * max(as_set), (as_set, at_top)


@needs_chrome
def test_the_wide_views_frame_the_circuit():
    """Both wide views frame the circuit's parts (not the die) to about 0.9 of the view on its fuller axis."""

    probe = """(function () { odLight.control('tour', true); const d = odLight.debugTour();
      odLight.frameAt(0.2); const first = odLight.debugTour().frame; odLight.frameAt(d.end - 0.2);
      return [first, odLight.debugTour().frame]; })()"""
    for frame in _probe("coherent_receiver_chip", probe):
        x0, y0, x1, y1 = frame
        assert max(abs(v) for v in frame) <= 0.92, frame
        assert max(x1 - x0, y1 - y0) / 2 >= 0.85, frame


@needs_chrome
def test_the_live_tour_follows_the_speed_and_eases_back_to_the_view_from_before():
    probe = """(function () { odLight.frameAt(0); const before = odLight.debugTour().camera;
      odLight.control('tour', true); odLight.control('speed', 2); odLight.debugAdvance(0.5); const t = odLight.debugTour().t;
      const end = odLight.debugTour().end; odLight.debugAdvance((end - t + 0.4) / 2);     // 0.4 s into the way back
      const back = odLight.debugTour(); odLight.debugAdvance(0.6);
      const done = odLight.debugTour(); return [t, back.active, back.camera, done.active, done.camera, before]; })()"""
    t, returning, middle, active, after, before = _probe(_mzm_to_detector(), probe)
    assert t == pytest.approx(1.0)                                   # half a second at speed 2
    assert returning and math.dist(middle, before) > 1e-3            # easing back, not there yet
    assert not active and after == pytest.approx(before)


@needs_chrome
def test_a_glb_export_stops_the_tour_first():
    probe = """(function () { odLight.control('tour', true); const s = odLight.debugTour().stops[0];
      odLight.frameAt(0.5 * (s.arrive + s.leave)); const glass = odLight.debugTour().glass.length;
      document.getElementById('btn-export-glb').click(); const d = odLight.debugTour();
      return [glass, d.active, d.glass.length]; })()"""
    glass, active, after = _probe(_mzm_to_detector(), probe)
    assert glass > 0 and active is False and after == 0


@needs_chrome
def test_a_tour_without_a_time_for_its_stops_plays_the_wide_views_only():
    probe = """(function () { __odLightData.tour_warp = __odLightData.tour_warp.slice(0, 2);
      odLight.control('tour', true); odLight.frameAt(1.0); const d = odLight.debugTour();
      return [d.active, d.stops.length, d.focus]; })()"""
    assert _probe(_mzm_to_detector(), probe) == [True, 0, None]


@needs_chrome
def test_in_the_field_look_the_driven_parts_rf_map_swings_with_its_drive():
    payload = build_light_payload(_mzm_to_detector(), drives="tour")
    (table,) = payload["drives"]
    gap, scale = table["rf_maps"][0]["gap_um"], payload["rf_scale_v_per_um"]
    passes, (va, pa, vb, pb) = _pass_times(payload, "mzm1")
    top = max(passes, key=lambda x: x[1])
    probe = """(function () { const rf = () => odLight.debugEffects().filter((e) => e.swing && e.kind === 'rf').map((e) => [e.visible, e.peak]);
      odLight.control('tour', true); return %s.map((t) => { odLight.frameAt(t); return rf(); }); })()""" % json.dumps([va + 0.02, top[3] + 0.01, 0.2])
    start, mid, wide = _probe(_mzm_to_detector(), probe, look="field", tour_drives=True)
    assert mid and all(visible and peak == pytest.approx(2.0 / gap / scale, rel=1e-4) for visible, peak in mid)
    assert all(not visible for visible, _ in start + wide)


@needs_chrome
def test_in_the_field_look_a_heaters_map_swings_with_its_drive():
    scene = _heated_ring_scene()
    payload = build_light_payload(scene, drives="tour")
    (table,) = payload["drives"]
    assert table["param"] == "heater:microringresonator1"
    top_k = table["heat_maps"][0]["delta_t_k"] / payload["heat_scale_k"]
    passes, (va, pa, vb, pb) = _pass_times(payload, "microringresonator1")
    top = max(passes, key=lambda x: x[1])
    probe = """(function () { const heat = () => odLight.debugEffects().filter((e) => e.swing && e.kind === 'heat').map((e) => [e.visible, e.peak]);
      odLight.control('tour', true); return %s.map((t) => { odLight.frameAt(t); return heat(); }); })()""" % json.dumps([0.2, top[3] + 0.01])
    wide, mid = _probe(scene, probe, look="field", tour_drives=True)
    assert mid and all(visible and peak == pytest.approx(top_k, rel=1e-4) for visible, peak in mid)
    assert 0.2 < top_k <= 1.0 and all(not visible for visible, _ in wide)


MMI_X = 60.0          # the MMIs this far from the phase shifter: a combiner stem lies in its stop's frame


def _mmi_interferometer() -> Scene:
    """Two 1x2 MMIs, a heated phase shifter on one arm: the combiner's stems are drawn by profiles."""

    from optodraw.registry import build_component

    scene = Scene(width=400, height=200, platform="on_chip")
    laser = scene.add(build_component("OnChipLaser", center=(-170, 0)))
    split = scene.add(build_component("MMI1x2", center=(-MMI_X, 0)))
    top = scene.add(build_component("PhaseShifter", center=(0, 30)))
    bottom = scene.add(build_component("Waveguide", center=(0, -30)))
    combine = scene.add(build_component("MMI1x2", center=(MMI_X, 0), angle=180))
    det = scene.add(build_component("OnChipPhotodetector", center=(170, 0)))
    for a, b in (((laser, "o1"), (split, "o1")), ((split, "o2"), (top, "o1")), ((split, "o3"), (bottom, "o1")),
                 ((top, "o2"), (combine, "o2")), ((bottom, "o2"), (combine, "o3")), ((combine, "o1"), (det, "o1"))):
        scene.route(a, b, kind="waveguide")
    return scene


@needs_chrome
def test_in_the_field_look_a_combiners_stems_draw_each_samples_profile():
    scene = _mmi_interferometer()
    payload = build_light_payload(scene, drives="tour")
    (table,) = payload["drives"]
    stems = sorted(eid for eid in payload["cw"]["profiles"] if eid.startswith("path:mmi1x22:"))
    k = len(table["values"]) - 1                                         # the top of the swing
    want = {eid: max(max(p["amp"]) for p in table["profiles"][k].get(eid, payload["cw"]["profiles"][eid])) for eid in stems}
    passes, _ = _pass_times(payload, "phaseshifter1")
    top = max(passes, key=lambda x: x[1])
    probe = """(function () { odLight.control('tour', true); odLight.frameAt(%r); const d = odLight.debugTour();
      return [d.drive.level, %s.map((id) => d.field[id] || 0)]; })()""" % (top[3] + 0.01, json.dumps(stems))
    level, drawn = _probe(scene, probe, look="field", tour_drives=True)
    assert level == k and stems
    for eid, value in zip(stems, drawn):
        assert value <= want[eid] + 1e-6, (eid, value, want[eid])            # never above the level's own numbers
    base = [max(max(p["amp"]) for p in payload["cw"]["profiles"][eid]) for eid in stems]
    assert any(abs(b - d) > 0.1 * b for b, d in zip(base, drawn)), (base, drawn)


def _level_changes(scene, payload):
    """Per drive table, per level: the edges, rails and profiles a full solve at that level changes (no frame)."""

    from optodraw.animation3d.inputs import input_wavelength
    from optodraw.animation3d.payload import _drive_sample
    from optodraw.animation_engine.graph import build_graph

    params, inputs = payload["cw"]["params"], [InputSignal.from_json(i) for i in payload["cw"]["inputs"]]
    graph = build_graph(scene)
    base = {"pulse": payload["pulse"], "cw": payload["cw"], "rails": payload["rails"], "hidden": payload["hidden"],
            "graph": graph, "wavelength_nm": input_wavelength(graph, inputs, params)}
    keys = ("pulse", "cw", "rails", "cw_rails", "profiles")
    return {table["sid"]: [set().union(*(sample[k].keys() for k in keys))
                           for sample in (_drive_sample(scene, params, inputs, table["param"], v, base, 1.0) for v in table["values"])]
            for table in payload["drives"]}


@needs_chrome
@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
@pytest.mark.parametrize("preset", ["mzm_mesh_chip", pytest.param("wdm_delay_weight_bank_chip", marks=pytest.mark.slow)])
def test_at_each_driven_stop_the_view_stays_inside_the_tables_frame(preset):
    """Ruling 47, tied to the camera: at 1600 x 900 (the video's shape), 800 x 600 and 2400 x 800 (wider than the
    frame's own margin: the player brings the camera closer), at every driven stop the light the camera sees lies inside
    the table's frame (reach at most 1), and every edge, rail or profile in view that a full solve of a level changes
    is carried in that level's deltas."""

    scene = build_preset(preset)
    html = scene.render_threejs(tour_drives=True)
    payload = _embedded_payload(html)
    assert len(payload["drives"]) == len([s for s in payload["tour"]["stops"] if s["drive"]]) > 0
    full = _level_changes(scene, payload)
    carried = {t["sid"]: [set().union(*(t[k][level].keys() for k in ("pulse", "cw", "rails", "cw_rails", "profiles")))
                          for level in range(len(t["values"]))] for t in payload["drives"]}
    probe = """(function () { odLight.control('tour', true); return odLight.debugTour().stops.filter((s) => s.drive).map((s) => {
      odLight.frameAt(0.5 * (s.arrive + s.leave)); const d = odLight.debugTour(); return [s.sid, d.reach, d.unframed, d.seen]; }); })()"""
    page = page_with_probe(scene, probe, tour_drives=True)
    for width, height in ((1600, 900), (800, 600), (2400, 800)):
        report = run_page(page, width=width, height=height, timeout=300)
        assert report and not report.startswith("error"), report
        for sid, reach, unseen, seen in json.loads(report):
            assert reach <= 1.0 and unseen == [], (width, sid, reach, unseen)
            for level, changed in enumerate(full[sid]):
                assert not (changed & set(seen)) - carried[sid][level], (width, sid, level, sorted((changed & set(seen)) - carried[sid][level])[:5])


@needs_chrome
def test_a_driven_stop_with_one_pulse_says_so_and_keeps_its_caption():
    """The ring chip's heated filter: the 12 s cap leaves one pulse in its hold."""

    scene = build_preset("ring_resonator_chip")
    payload = build_light_payload(scene, drives="tour")
    assert "5th-order filter ring 1: the drive is shown on 1 pulse; the Field look shows it in steady state" in payload["notices"]
    run = _probe(scene, TOUR_PROBE, tour_drives=True)
    (stop, frames) = next((s, f) for s, f in zip(run["plan"]["stops"], run["stops"]) if s["drive"])
    assert "Time runs at normal speed while a drive changes" in frames["mid"]["captions"]
