"""The 3D page plays the engine's light: the page carries the light payload, and the player places every edge
in its guide and draws each packet where and when the engine says."""

from __future__ import annotations

import json
import re

import pytest

from optodraw import Beam, Laser, Periscope, Photodiode, Scene
from optodraw.animation3d.payload import build_light_payload
from optodraw.animation_engine.errors import AnimationError
from optodraw.animation_engine.inputs import InputSignal
from optodraw.presets import build_preset
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
    # 13 to 25 s with a GPU; 40 to 66 s in software WebGL (SwiftShader, as on a CI runner), more on a loaded one
    report = run_page(page_with_probe(preset, probe, **options), timeout=300)
    assert report and not report.startswith("error"), report
    return json.loads(report)


def _embedded_payload(html: str) -> dict:
    found = re.search(r"window\.__odLightData = (\{.*?\});\n", html, re.S)
    assert found, "the page carries no light payload"
    return json.loads(found.group(1))


def test_params_inputs_and_look_reach_the_engine():
    scene = build_preset("ring_resonator_chip")
    params = {"phase:coupledringfilter1": 2.0}
    html = ThreeJsRenderer(scene, params=params, look="field").render()
    assert _embedded_payload(html) == build_light_payload(scene, params=params, look="field")
    with pytest.raises(ValueError, match="look"):
        ThreeJsRenderer(scene, look="sparkle")


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


def test_a_bad_explicit_input_or_params_raise():
    scene = build_preset("ring_resonator_chip")
    with pytest.raises(AnimationError, match="nosuchpart"):
        scene.render_threejs(inputs=[InputSignal("port:nosuchpart:o1")])
    with pytest.raises(AnimationError, match="no behaviour yet for Periscope"):
        _periscope_bench().render_threejs(params={})


def _mzm_between_two_routes() -> Scene:
    from optodraw.registry import build_component

    scene = Scene()
    left = scene.add(build_component("VerticalGratingCoupler", center=(-150, 0)))
    mzm = scene.add(build_component("MZM", center=(0, 0)))
    right = scene.add(build_component("VerticalGratingCoupler", center=(150, 0), angle=180))
    scene.route((left, "o1"), (mzm, "o1"))
    scene.route((mzm, "o3"), (right, "o1"))
    return scene


SLOW_PRESETS = {"wdm_delay_weight_bank_chip"}        # a 16 s payload; its own test checks it in the Field look


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


# Edges that lie outside only because a part has no drawn internal path or the engine jumps a coupling gap, with
# the task that fixes them (Tasks 5 to 9). None in this scene.
MIXED_IDS_OUTSIDE: dict[str, str] = {}


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


COVER_PROBE = """(function () {
  const shot = () => document.querySelector('canvas').toDataURL('image/png');
  const out = []; odLight.setEnabled(true);
  for (const T of %s) {
    __odPT.active = false; odLight.frameAt(T); const on = shot();
    __odPT.active = true; odLight.frameAt(T); out.push([on, shot()]);       // the same frame, the glow hidden
  }
  __odPT.active = false; return out; })()"""


def _linear(srgb):
    """sRGB values (0 to 1) to linear light."""

    import numpy as np

    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


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
    report = run_page(page, width=1600, height=1000, timeout=300)
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


HEAT_PARAMS = {"heater:microringresonator1": 15.0}


CAPTIONS = "(odLight.setEnabled(%s), odLight.frameAt(1.0), (function(){ const e = document.getElementById('od-captions'); return e ? [e.style.display !== 'none', e.innerText.split('\\n')] : null; })())"


# the Field look's block with its Scales toggle closed, then open
FIELD_CAPTIONS = ("(odLight.setEnabled(true), odLight.frameAt(1.0), (function(){ const e = document.getElementById('od-captions');"
                  " const closed = e.innerText.split('\\n'); e.querySelector('.od-scales').click();"
                  " return [e.style.display !== 'none', closed, e.innerText.split('\\n')]; })())")


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
def test_the_play_tour_button_starts_and_stops_the_tour():
    probe = """(function () { const b = document.getElementById('light-tour'); const out = [b.disabled];
      b.click(); out.push(odLight.debugTour().active, b.textContent);
      b.click(); out.push(odLight.debugTour().active, b.textContent, document.getElementById('light-record').disabled);
      return out; })()"""
    assert _probe(_mzm_to_detector(), probe) == [False, True, "Stop tour", False, "Play tour", False]


@pytest.mark.filterwarnings("ignore:.*unconnected port:RuntimeWarning")
def test_the_weight_bank_page_carries_its_tour_without_drive_tables_and_stays_under_5_mb():
    html = build_preset("wdm_delay_weight_bank_chip").render_threejs()
    marker = "window.__odLightData = "
    start = html.index(marker) + len(marker)
    text = html[start:html.index(";\n", start)]
    assert len(text.encode()) < 5_000_000, len(text.encode())
    payload = json.loads(text)
    assert [s["sid"] for s in payload["tour"]["stops"] if s["drive"]] and payload["drives"] == []


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


