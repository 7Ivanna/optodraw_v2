"""The studio renderer's core (studio_core.js): pure functions, checked in a headless browser."""

import json
import math
from pathlib import Path

import pytest

from optodraw.renderers.capture3d import find_chrome, run_page

pytestmark = pytest.mark.skipif(find_chrome(required=False) is None, reason="needs Chrome, Chromium or Edge")

CORE = (Path(__file__).parents[1] / "optodraw" / "renderers" / "js" / "studio_core.js").read_text(encoding="utf-8")

RANDOM = """
function random(seed) {                                   // mulberry32: the same numbers in every browser
  return function () {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
"""


def _run(checks: str) -> dict:
    """Run ``checks`` (a function body that gets the core as ``S`` and returns a JSON value) in the page."""

    html = ("<!DOCTYPE html><textarea id='od-capture'></textarea><script>" + CORE + "</script><script>" + RANDOM
            + "const out = document.getElementById('od-capture');"
            + "try { out.value = JSON.stringify((function (S) {" + checks + "})(odStudioCore)); }"
            + "catch (e) { out.value = JSON.stringify({error: String(e && e.stack || e)}); }</script>")
    data = json.loads(run_page(html, timeout=120))
    assert not (isinstance(data, dict) and "error" in data), data
    return data


def test_the_bvh_finds_the_same_closest_hit_as_testing_every_triangle():
    data = _run("""
      const rand = random(7), n = 600, pos = new Float64Array(n * 9);
      for (let i = 0; i < n; i++) {                        // small triangles scattered in a 10 x 10 x 10 box
        const cx = rand() * 10, cy = rand() * 10, cz = rand() * 10;
        for (let k = 0; k < 9; k++) pos[i * 9 + k] = [cx, cy, cz][k % 3] + (rand() - 0.5) * 1.5;
      }
      function brute(o, d) {                               // Moller-Trumbore over every triangle
        let best = Infinity, tri = -1;
        for (let i = 0; i < n; i++) {
          const p = i * 9, e1 = [0, 1, 2].map(a => pos[p + 3 + a] - pos[p + a]), e2 = [0, 1, 2].map(a => pos[p + 6 + a] - pos[p + a]);
          const h = [d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0]];
          const det = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2];
          if (Math.abs(det) < 1e-14) continue;
          const s = [0, 1, 2].map(a => o[a] - pos[p + a]);
          const u = (s[0] * h[0] + s[1] * h[1] + s[2] * h[2]) / det;
          if (u < 0 || u > 1) continue;
          const q = [s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0]];
          const v = (d[0] * q[0] + d[1] * q[1] + d[2] * q[2]) / det;
          if (v < 0 || u + v > 1) continue;
          const t = (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2]) / det;
          if (t > 1e-9 && t < best) { best = t; tri = i; }
        }
        return [best, tri];
      }
      const bvh = S.buildBVH(pos), hit = S.newHit();
      let rays = 0, hits = 0, wrong = 0, wrongAny = 0;
      for (let r = 0; r < 3000; r++) {
        const o = [rand() * 14 - 2, rand() * 14 - 2, rand() * 14 - 2];
        let d = [rand() - 0.5, rand() - 0.5, rand() - 0.5];
        const l = Math.hypot(...d); d = d.map(v => v / l);
        if (r % 7 === 0) d = [0, 0, 1];                     // rays along an axis: the slab test's parallel case
        const [t, tri] = brute(o, d);
        const found = S.closestHit(bvh, o[0], o[1], o[2], d[0], d[1], d[2], Infinity, hit);
        rays++; if (tri >= 0) hits++;
        if (found !== (tri >= 0) || (found && (hit.tri !== tri || Math.abs(hit.t - t) > 1e-9))) wrong++;
        if (S.occluded(bvh, o[0], o[1], o[2], d[0], d[1], d[2], Infinity) !== (tri >= 0)) wrongAny++;
      }
      return {rays, hits, wrong, wrongAny, nodes: bvh.count};
    """)
    assert data["hits"] > 300 and data["rays"] == 3000                # the case is not empty
    assert data["wrong"] == 0 and data["wrongAny"] == 0, data


def test_a_softbox_lights_a_surface_facing_it_by_the_exact_integral():
    """(1/pi) * integral of exp(s (cos - 1)) cos over the hemisphere = 2 ((s - 1) + exp(-s)) / s^2."""

    data = _run("""
      return [18, 30, 50].map(s => {
        const env = {ambient: [0, 0, 0], lobes: [{dir: [0, 1, 0], sharpness: s, color: [1, 1, 1]}]};
        const tables = S.buildTables(env), out = [0, 0, 0];
        S.diffuseLight(tables, env, 0, 1, 0, out);
        return [s, out[0]];
      });
    """)
    for s, got in data:
        assert got == pytest.approx(2 * ((s - 1) + math.exp(-s)) / s**2, rel=0.01), s


def test_no_material_returns_more_light_than_a_uniform_studio_gives():
    data = _run("""
      const env = {ambient: [1, 1, 1], lobes: []}, tables = S.buildTables(env), out = [0, 0, 0], rows = [];
      for (const metal of [0, 1]) for (const rough of [0.04, 0.3, 0.7, 1]) for (const nv of [1, 0.5, 0.1]) {
        S.shadeOpen(tables, env, [0, 1, 0], [Math.sqrt(1 - nv * nv), nv, 0], {base: [1, 1, 1], metal, rough}, out);
        rows.push([metal, rough, nv, out[0]]);
      }
      return rows;
    """)
    for metal, rough, nv, got in data:
        assert got <= 1.0 + 1e-6, (metal, rough, nv, got)              # energy is conserved
        assert got >= 0.75, (metal, rough, nv, got)                    # and little is lost


def test_a_smooth_metal_seen_head_on_reflects_its_own_colour():
    data = _run("""
      const env = {ambient: [1, 1, 1], lobes: []}, tables = S.buildTables(env), out = [0, 0, 0];
      S.shadeOpen(tables, env, [0, 1, 0], [0, 1, 0], {base: [1.0, 0.78, 0.34], metal: 1, rough: 0.04}, out);
      return out;
    """)
    assert data == pytest.approx([1.0, 0.78, 0.34], rel=0.03)         # gold's F0 in a white room


SCENE = """
function quad(pos, a, b, c, d) { pos.push(...a, ...b, ...c, ...a, ...c, ...d); }
function boxScene(world) {                        // a 20 x 20 floor (y = 0) and a 2 x 2 x 2 box at the origin
  const pos = [];
  quad(pos, [-10, 0, -10], [-10, 0, 10], [10, 0, 10], [10, 0, -10]);
  const s = 1, h = 2;
  quad(pos, [-s, h, -s], [-s, h, s], [s, h, s], [s, h, -s]);
  quad(pos, [-s, 0, s], [s, 0, s], [s, h, s], [-s, h, s]);
  quad(pos, [s, 0, -s], [-s, 0, -s], [-s, h, -s], [s, h, -s]);
  quad(pos, [s, 0, s], [s, 0, -s], [s, h, -s], [s, h, s]);
  quad(pos, [-s, 0, -s], [-s, 0, s], [-s, h, s], [-s, h, -s]);
  const n = pos.length / 9;
  return {
    positions: Float64Array.from(pos), normals: null, uvs: null, material: new Uint16Array(n),
    materials: [{base: [0.8, 0.8, 0.8], metal: 0, rough: 0.6, emissive: [0, 0, 0], opacity: 1, transmission: 0,
                 ior: 1.5, unlit: false, texture: -1}],
    textures: [],
    camera: {position: [0, 30, 0.001], right: [1, 0, 0], up: [0, 0, -1], back: [0, 1, 0], tanHalfY: 0.25, aspect: 1},
    env: world, width: 64, height: 64, samples: 1, exposure: 1,
  };
}
"""


def test_a_box_on_the_floor_casts_its_shadow_away_from_the_softbox():
    data = _run(SCENE + """
      const world = {ambient: [0.05, 0.05, 0.05], lobes: [{dir: [0.8, 0.6, 0], sharpness: 30, color: [5, 5, 5]}]};
      const ctx = S.prepareScene(boxScene(world)), buf = new Float32Array(64 * 64 * 4);
      S.renderTile(ctx, 0, 0, 64, 64, buf);
      const at = (x, z) => {                       // the pixel that looks down at floor point (x, 0, z)
        const px = Math.round(32 + (x / (30 * 0.25)) * 32 - 0.5), py = Math.round(32 + (z / (30 * 0.25)) * 32 - 0.5);
        return buf[(py * 64 + px) * 4];
      };
      return {lit: at(2.2, 0), shadow: at(-2.2, 0), alpha: buf[3]};
    """)
    assert data["alpha"] == pytest.approx(1.0)                         # the floor fills the view
    assert data["shadow"] < 0.5 * data["lit"], data


def test_refraction_follows_snells_law():
    data = _run("""
      const out = [];
      for (const deg of [0, 20, 40, 60]) {
        const a = deg * Math.PI / 180, d = [Math.sin(a), -Math.cos(a), 0], t = S.refract(d, [0, 1, 0], 1 / 1.5);
        out.push([Math.sin(a), Math.hypot(t[0], t[2]), t[1] < 0]);
      }
      const tir = S.refract([Math.sin(1.2), -Math.cos(1.2), 0], [0, 1, 0], 1.5);   // inside glass, steep
      return {rows: out, tir};
    """)
    for sin_i, sin_t, downward in data["rows"]:
        assert sin_t == pytest.approx(sin_i / 1.5, abs=1e-12) and downward
    assert data["tir"] is None                                         # total internal reflection


GLASS = """
function glassScene(transmission) {          // a white light panel at z = -5, a 1 thick glass slab at z = 0, camera at z = 10
  const pos = [];
  quad(pos, [-20, -20, -5], [20, -20, -5], [20, 20, -5], [-20, 20, -5]);
  quad(pos, [-3, -3, 0.5], [3, -3, 0.5], [3, 3, 0.5], [-3, 3, 0.5]);              // front face, normal +z
  quad(pos, [-3, -3, -0.5], [-3, 3, -0.5], [3, 3, -0.5], [3, -3, -0.5]);          // back face, normal -z
  const n = pos.length / 9, material = new Uint16Array(n).fill(1);
  material[0] = 0; material[1] = 0;
  return {
    positions: Float64Array.from(pos), normals: null, uvs: null, material,
    materials: [{base: [1, 1, 1], metal: 0, rough: 1, emissive: [0, 0, 0], opacity: 1, transmission: 0, ior: 1.5, unlit: true, texture: -1},
                {base: [1, 1, 1], metal: 0, rough: 0.02, emissive: [0, 0, 0], opacity: 0.4, transmission, ior: 1.5, unlit: false, texture: -1}],
    textures: [], env: {ambient: [0, 0, 0], lobes: []},
    camera: {position: [0, 0, 10], right: [1, 0, 0], up: [0, 1, 0], back: [0, 0, 1], tanHalfY: 0.05, aspect: 1},
    width: 8, height: 8, samples: 1, exposure: 1,
  };
}
"""


def test_a_clear_glass_slab_passes_the_light_fresnel_leaves():
    data = _run(SCENE + GLASS + """
      const ctx = S.prepareScene(glassScene(1)), buf = new Float32Array(8 * 8 * 4);
      S.renderTile(ctx, 0, 0, 8, 8, buf);
      return [buf[(4 * 8 + 4) * 4], buf[(4 * 8 + 4) * 4 + 3]];
    """)
    assert data[0] == pytest.approx((1 - 0.04) ** 2, rel=1e-3)          # two surfaces at normal incidence
    assert data[1] == pytest.approx(1.0)


def test_a_lens_casts_a_lighter_shadow_than_a_solid_part():
    """Light at 45 degrees from +x; the box hangs 3 above the floor; its shadow falls near x = -4."""

    data = _run(SCENE + """
      function shadowOf(material) {
        const world = {ambient: [0.05, 0.05, 0.05], lobes: [{dir: [Math.SQRT1_2, Math.SQRT1_2, 0], sharpness: 200, color: [5, 5, 5]}]};
        const scene = boxScene(world);
        scene.materials.push(material);
        for (let i = 2; i < scene.material.length; i++) scene.material[i] = 1;   // the box takes material 1
        for (let i = 9 * 2; i < scene.positions.length; i += 3) scene.positions[i + 1] += 3;
        scene.camera = {position: [-4, 30, 0.001], right: [1, 0, 0], up: [0, 0, -1], back: [0, 1, 0], tanHalfY: 0.01, aspect: 1};
        scene.width = 2; scene.height = 2;
        const ctx = S.prepareScene(scene), buf = new Float32Array(2 * 2 * 4);
        S.renderTile(ctx, 0, 0, 2, 2, buf);
        return buf[0];
      }
      const solid = {base: [0.8, 0.8, 0.8], metal: 0, rough: 0.6, emissive: [0, 0, 0], opacity: 1, transmission: 0, ior: 1.5, unlit: false, texture: -1};
      const glass = {base: [1, 1, 1], metal: 0, rough: 0.02, emissive: [0, 0, 0], opacity: 0.4, transmission: 1, ior: 1.5, unlit: false, texture: -1};
      const open = {base: [0, 0, 0], metal: 0, rough: 1, emissive: [0, 0, 0], opacity: 0, transmission: 0, ior: 1.5, unlit: true, texture: -1};
      return {solid: shadowOf(solid), glass: shadowOf(glass), open: shadowOf(open)};
    """)
    assert data["solid"] < data["glass"] < data["open"], data                # a light shadow, but a shadow
    kept = (data["glass"] - data["solid"]) / (data["open"] - data["solid"])  # the direct light the glass passes
    assert 0.6 < kept < 0.9, data


def test_the_denoiser_smooths_a_surface_and_keeps_its_edges():
    data = _run("""
      const W = 16, H = 8, n = W * H, buf = new Float32Array(n * 4), G = S.newGBuffer(W, H);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const i = y * W + x, left = x < W / 2, noise = (x + y) % 2 ? 0.1 : -0.1;
        const v = (left ? 0.2 : 0.8) + noise;
        buf.set([v, v, v, 1], i * 4);
        G.id[i] = left ? 1 : 2; G.depth[i] = 10; G.normal.set([0, 127, 0], i * 3);
        const alb = left ? 50 : 200; G.albedo.set([alb, alb, alb], i * 3);
      }
      S.denoise(buf, W, H, G);
      const row = Array.from({length: W}, (_, x) => buf[(4 * W + x) * 4]);
      return row;
    """)
    left, right = data[:8], data[8:]
    assert max(left[1:6]) - min(left[1:6]) < 0.06 and max(right[2:7]) - min(right[2:7]) < 0.06   # smoother
    assert max(left) < 0.36 and min(right) > 0.64                     # no mixing across the edge


def test_the_glow_spreads_a_beams_light_to_its_neighbours():
    data = _run("""
      const W = 32, H = 32, buf = new Float32Array(W * H * 4), emit = new Float32Array((W / 2) * (H / 2) * 3);
      for (let i = 0; i < W * H; i++) buf[i * 4 + 3] = 1;
      emit.set([4, 0, 0], ((H / 4) * (W / 2) + W / 4) * 3);           // one bright red source at the centre
      S.glow(buf, emit, W, H, 0.6, 2.0);
      const at = (x, y) => buf[(y * W + x) * 4];
      return {centre: at(16, 16), near: at(19, 16), far: at(31, 0), green: buf[(16 * W + 16) * 4 + 1]};
    """)
    assert data["centre"] > data["near"] > data["far"] >= 0.0 and data["near"] > 0.0
    assert data["green"] == 0.0


def test_a_reflection_of_a_bright_beam_cannot_flash_white():
    """A thin, very bright emissive part met by a few glossy rays gave white specks (fireflies)."""

    data = _run(SCENE + """
      const world = {ambient: [0.2, 0.2, 0.2], lobes: []};
      const scene = boxScene(world);                 // the box becomes a blinding emitter; the floor a glossy metal
      scene.materials = [{base: [0.7, 0.7, 0.7], metal: 1, rough: 0.3, emissive: [0, 0, 0], opacity: 1, transmission: 0, ior: 1.5, unlit: false, texture: -1},
                         {base: [0, 0, 0], metal: 0, rough: 1, emissive: [400, 0, 0], opacity: 1, transmission: 0, ior: 1.5, unlit: false, texture: -1}];
      for (let i = 2; i < scene.material.length; i++) scene.material[i] = 1;
      scene.camera = {position: [-6, 4, 0.001], right: [0, 0, -1], up: [0.5, 0.866, 0], back: [-0.866, 0.5, 0], tanHalfY: 0.3, aspect: 1};
      scene.width = 16; scene.height = 16;
      const ctx = S.prepareScene(scene), buf = new Float32Array(16 * 16 * 4), gb = S.newGBuffer(16, 16);
      S.renderTile(ctx, 0, 0, 16, 16, buf, gb);
      let maxFloor = 0, floor = 0;
      for (let i = 0; i < 16 * 16; i++) if (gb.id[i] === 1) { floor++; maxFloor = Math.max(maxFloor, buf[i * 4]); }
      return {maxFloor, floor};
    """)
    assert data["floor"] > 20, data                                      # the view shows the floor
    assert data["maxFloor"] <= 2.5, data                                 # reflected light is clamped


FLOATING_BOX = """
function floatingBox(floor) {                 // only the box (no floor triangles); the light at 45 degrees from +x
  const world = {ambient: [0.1, 0.1, 0.1], lobes: [{dir: [Math.SQRT1_2, Math.SQRT1_2, 0], sharpness: 60, color: [5, 5, 5]}]};
  const scene = boxScene(world);
  scene.positions = scene.positions.slice(18);                     // drop the two floor triangles
  scene.material = scene.material.slice(2);
  scene.floor = floor;
  scene.width = 64; scene.height = 64;
  return scene;
}
const at = (buf, x, z) => {                     // the pixel that looks down at floor point (x, 0, z), camera at y = 30
  const px = Math.round(32 + (x / (30 * 0.25)) * 32 - 0.5), py = Math.round(32 + (z / (30 * 0.25)) * 32 - 0.5);
  return Array.from(buf.subarray((py * 64 + px) * 4, (py * 64 + px) * 4 + 4));
};
"""


def test_the_shadow_catcher_keeps_a_transparent_image_and_its_shadows():
    data = _run(SCENE + FLOATING_BOX + """
      const ctx = S.prepareScene(floatingBox({y: 0, mode: 'shadow', center: [0, 0], fade: [20, 40]}));
      const buf = new Float32Array(64 * 64 * 4);
      S.renderTile(ctx, 0, 0, 64, 64, buf);
      return {shadow: at(buf, -2.2, 0), open: at(buf, 5, 5), beside: at(buf, 0, 2.6)};
    """)
    assert data["shadow"][3] > 0.3 and data["open"][3] < 0.01, data            # alpha is the shadow, the open floor clear
    assert data["beside"][3] < 0.01, data                                      # a contact shadow only close to the part
    assert max(data["shadow"][:3]) < 1e-6, data                               # and adds no colour


def test_the_studio_floor_is_solid_near_the_parts_and_fades_far_away():
    data = _run(SCENE + FLOATING_BOX + """
      const ctx = S.prepareScene(floatingBox({y: 0, mode: 'studio', center: [0, 0], fade: [3, 6], color: [0.6, 0.62, 0.66]}));
      const buf = new Float32Array(64 * 64 * 4);
      S.renderTile(ctx, 0, 0, 64, 64, buf);
      return {near: at(buf, 2.2, 0), far: at(buf, 7, 7)};
    """)
    assert data["near"][3] == pytest.approx(1.0, abs=1e-6) and data["near"][0] > 0.1, data   # solid and lit
    assert data["far"][3] < 0.05, data


def test_the_denoiser_smooths_the_shadow_catcher_too():
    """Catcher pixels are partly transparent; they are filtered, alpha included, among floor pixels only."""

    data = _run("""
      const W = 12, H = 4, buf = new Float32Array(W * H * 4), G = S.newGBuffer(W, H);
      G.floor = 9;
      for (let i = 0; i < W * H; i++) {
        const a = 0.4 + ((i % 2) ? 0.1 : -0.1);
        buf.set([0, 0, 0, a], i * 4);
        G.id[i] = 9; G.depth[i] = 10; G.normal.set([0, 127, 0], i * 3);
      }
      S.denoise(buf, W, H, G);
      const row = Array.from({length: W}, (_, x) => buf[(2 * W + x) * 4 + 3]);
      return row;
    """)
    assert max(data[2:10]) - min(data[2:10]) < 0.05, data
