
// The light player. It draws the physics engine's light (the payload in window.__odLightData) on the drawn
// guides, beams and fibre cables. Every number comes from the payload: the edges, the packets' entry and exit
// times, their powers, widths and colours, the train period, the source power, each part edge's profile (the share
// of its power at each point where edges share a guide), and the rails of coupling sections (one light per rail, with
// its power at each point, per engine bucket), which replace the transfers they draw. The player only moves each
// packet along its edge (or rail) between its entry and exit time, so it moves at the guide's group velocity.
// The Field look draws the engine's steady state (the payload's cw): E = amp cos(phase - omega t) times a mode shape
// across each guide, from the amplitude and display phase the payload gives along each edge and rail, the multimode
// regions from their sampled fields, and a front that fades in over one crest where the light first arrives. Where
// fields meet the payload has already added them. omega is a display frequency: one cycle per cw.cycle_s seconds.
window.odLight = (function () {
  const S = { enabled: false, playing: false, speed: 1.0, t: 0, raw: 0, look: 'light', group: null, built: false };
  const STEP = 0.5;               // sample spacing along an edge, in scene units
  const MAX_SAMPLES = 1500;       // samples per edge at most (longer edges get a wider spacing)
  const HALO = 3.0;               // the glow is this many guide widths wide
  const VIEWPORT = { value: 1 };  // the drawing height in pixels, shared by every glow
  // The brightest glow, the sources' whole power at the middle of a guide, is PEAK in linear light after the renderer's
  // exposure (white is 1). The Neutral tone mapping is straight up to 0.76 and then bends softly toward white, so the
  // drawn brightness keeps its ratio, at every zoom, up to about 0.8 of the sources' root power, and brighter light
  // still rises, more slowly, and stays below white.
  const PEAK = 0.9;
  const GAIN = { value: PEAK };   // PEAK over the exposure, shared by every glow
  const FIELD_HALF = 0.8;         // the field ribbon is this many guide widths each way: the mode's tails
  const FIELD_TIME = { value: 0 }, FIELD_OMEGA = { value: 0 }, REF = { value: 1 };   // ps; omega t; the sources' amplitude
  const DOWN = new THREE.Vector3(0, -1, 0), UP = new THREE.Vector3(0, 1, 0);
  const SMOOTH = 2.0;             // the ribbon's direction is the path's over this length each way (scene units)
  const OPEN = 1e6;               // nothing above a sample, or no bend
  const HEAT_TIME = { value: 0 };   // the time as asked, in seconds: the heat grows on it
  const HEAT_CELLS = 40000;       // the most vertices of one heater's map
  const HEAT_ALPHA = 0.35, RF_ALPHA = 0.25;     // the most a map covers what is under it: the optical field stays clear
  const HEAT_STOPS = [[0, [0.15, 0.01, 0.25]], [0.35, [0.55, 0.04, 0.12]], [0.7, [0.85, 0.2, 0.04]], [1, [0.95, 0.38, 0.03]]];
  const RF_POSITIVE = [0.10, 0.95, 0.50], RF_NEGATIVE = [1.0, 0.12, 0.75];   // linear light; both below white
  const raycaster = new THREE.Raycaster();
  let data = null, placed = [], effects = [], psPerSecond = 1, spanS = 0, periodS = 0;
  let itemsBySid = new Map(), recById = new Map(), referencePower = 1;
  let swingEffects = [];          // the heat and RF maps of the tour's driven parts, drawn only while their drive swings
  let last = performance.now() / 1000, scrubbing = false, drawnAt = null;

  // --- the Light look: a short streak with an additive core and a soft halo ----------------------------------
  // A ribbon along the placed path faces the camera. Each vertex moves toward the eye as far as the eye ray from the
  // path runs inside the guide, plus a margin: that changes its depth and not its place on the screen, so the light
  // at mid-height shows through its own guide, and a part above or beside the guide still hides it.
  const VERT = '#include <common>\n#include <logdepthbuf_pars_vertex>\n' + `
    attribute vec3 aTangent;
    attribute float aSide;
    #ifdef FIELD
    attribute vec3 aField;                       // the field look: amplitude, phase, arrival time (ps)
    varying vec3 vField;
    #else
    attribute vec3 aGlow;
    varying vec3 vGlow;
    #endif
    attribute float aGap;                        // from the guide top up to the first part over or beside it
    attribute float aBend;                       // the widest the ribbon may be here without folding on a bend
    uniform float uHalf;
    uniform vec2 uGuide;                         // the guide's half width and half thickness
    uniform float uViewport;                     // the drawing height in pixels
    uniform float uMinPx;                        // the least half width on screen, in pixels
    varying float vSide;
    void main() {
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vec3 t = normalize(aTangent), eye = normalize(cameraPosition - wp.xyz);
      // the ribbon's width lies in the view plane (across the camera's axis, not across this vertex's own eye ray),
      // so every point of it has its centre's depth: away from the middle of a wide view an eye ray tilts, and a
      // ribbon across it would bring one edge nearer than its centre, over metal beside the guide
      vec3 forward = -vec3(viewMatrix[0][2], viewMatrix[1][2], viewMatrix[2][2]);
      vec3 across = cross(t, forward);
      float n = length(across);
      across = n > 1e-5 ? across / n : vec3(0.0, 1.0, 0.0);
      vec3 side = cross(vec3(0.0, 1.0, 0.0), t);
      side = length(side) > 1e-4 ? normalize(side) : vec3(1.0, 0.0, 0.0);
      float inside = min(uGuide.y / max(abs(eye.y), 1e-3), uGuide.x / max(abs(dot(eye, side)), 1e-3));
      float depth = max(-(viewMatrix * wp).z, 1e-6);
      // the margin: 0.3 % of the view distance (smaller did not clear the guide in a test), but never more than half
      // the gap to a part over or beside the guide, so that part still hides the light
      float margin = min(0.003 * depth, 0.5 * aGap);
      float lift = 1.05 * min(inside, 50.0 * max(uGuide.x, uGuide.y)) + margin;
      // display only: the light's ribbon is at least 10 px half wide on screen (the field's 4 px). With the profile in
      // FRAG, the halo is then at least 12 px wide at half height and the core at least 6.7 px. On a tight bend it
      // stays narrower than the bend.
      float pixel = 2.0 * depth / (projectionMatrix[1][1] * uViewport);
      vec3 p = wp.xyz + across * aSide * min(max(uHalf, uMinPx * pixel), aBend);
      // an edge that reaches below the guide's foot would hide behind the floor in front of it: it clears that floor
      vec3 toEye = normalize(cameraPosition - p);
      float foot = wp.y - uGuide.y;
      if (p.y < foot && toEye.y > 1e-3) lift = max(lift, 1.02 * (foot - p.y) / toEye.y + margin);
      wp.xyz = p + toEye * lift;
      #ifdef FIELD
      vField = aField;
      #else
      vGlow = aGlow;
      #endif
      vSide = aSide;
      gl_Position = projectionMatrix * viewMatrix * wp;
      #include <logdepthbuf_vertex>
    }`;
  const FRAG = '#include <common>\n#include <logdepthbuf_pars_fragment>\n' + `
    uniform float uGain;                       // PEAK over the exposure
    varying vec3 vGlow;
    varying float vSide;
    void main() {
      #include <logdepthbuf_fragment>
      float d = vSide * vSide;
      // the core: flat across the guide and falling at its sides (half height at about a third of the half width,
      // the guide's width), so a streak reads as a lit guide; the halo: a soft glow round it
      float core = exp(-d * d / 0.0256);
      float halo = 0.5 * exp(-d / 0.52);
      // the brightness is the root of the power over the sources' power: 1 for all of it. A soft knee keeps more
      // (packets of one train that overlap, a ring's build-up) below 1: straight up to 0.85, then bending toward 1.
      float m = max(max(vGlow.r, vGlow.g), vGlow.b);
      float k = m <= 0.85 ? m : 0.85 + 0.15 * (1.0 - 2.0 / (exp(2.0 * (m - 0.85) / 0.15) + 1.0));
      vec3 glow = m > 0.0 ? vGlow * (k / m) : vec3(0.0);
      // at most 1: the blend (see glowMesh) then has no negative factor
      gl_FragColor = vec4(min(uGain * glow * (core + halo) / 1.5, vec3(1.0)), 1.0);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`;

  // --- the Field look: the field's colour and its amplitude as opacity -------------------------------------------
  // e is the field over its amplitude. One wavelength that is not visible (white): blue at -1, white at 0, red at +1.
  // Any other wavelength, its own colour (a visible one its true colour): full at a crest, dim at a trough. The
  // opacity follows |e| as well, so crests and troughs read and the zeros between them do not (linear light).
  const FIELD_COLOUR = `
    uniform vec3 uTint;
    uniform float uPlain;
    vec3 fieldColour(float e) {
      if (uPlain > 0.5) return e >= 0.0 ? mix(vec3(1.0), vec3(0.791, 0.032, 0.021), e) : mix(vec3(1.0), vec3(0.021, 0.155, 0.791), -e);
      return uTint * (0.6 + 0.4 * e);
    }
    float fieldWeight(float e) { return 0.35 + 0.65 * abs(e); }`;
  const FIELD_FRAG = '#include <common>\n#include <logdepthbuf_pars_fragment>\n' + FIELD_COLOUR + `
    uniform float uGain, uTime, uOmegaT, uFade, uRef;
    varying vec3 vField;
    varying float vSide;
    void main() {
      #include <logdepthbuf_fragment>
      // the front: dark before the light arrives, full one crest behind it
      float front = clamp((uTime - vField.z) / uFade, 0.0, 1.0);
      // the mode across the guide: a Gaussian, 1/e at the guide's edge (0.625 of the ribbon's half width)
      float mode = exp(-vSide * vSide / 0.39);
      float e = cos(vField.y - uOmegaT);
      gl_FragColor = vec4(uGain * fieldColour(e), clamp(vField.x / uRef, 0.0, 1.0) * front * mode * fieldWeight(e));
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`;
  // --- heat and RF (the Field look only): closed forms of the payload's constants, drawn under the optical field -------
  // A flat mesh on the cladding, moved toward the eye by 0.3 % of the view distance. vA is set per mesh: the heat's
  // distance to the heater spine (um); the RF's distance along the electrodes (um). Nothing is drawn outside the chip.
  const EFFECT_VERT = '#include <common>\n#include <logdepthbuf_pars_vertex>\n' + `
    attribute float aA;
    varying float vA;
    varying vec2 vXZ;
    void main() {
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vXZ = wp.xz;
      vec3 eye = normalize(cameraPosition - wp.xyz);
      float depth = max(-(viewMatrix * wp).z, 1e-6);
      wp.xyz += eye * 0.003 * depth;
      vA = aA;
      gl_Position = projectionMatrix * viewMatrix * wp;
      #include <logdepthbuf_vertex>
    }`;
  // the colour map of the heat: piecewise linear between the stops, from dark purple to a deep orange (below white)
  const heatColourGlsl = () => 'vec3 heatColour(float k) { k = clamp(k, 0.0, 1.0); vec3 c = vec3(' + HEAT_STOPS[0][1].join(', ') + ');' +
    HEAT_STOPS.slice(1).map(([at, rgb], i) => ` c = mix(c, vec3(${rgb.join(', ')}), clamp((k - ${HEAT_STOPS[i][0].toFixed(3)}) / ${(at - HEAT_STOPS[i][0]).toFixed(3)}, 0.0, 1.0));`).join('') +
    ' return c; }';
  // the temperature rise at distance d from the spine, T = peak (1 - exp(-t / tau)) exp(-d^2 / (2 s^2)), s^2 = s0^2 + g t,
  // with peak the heater's rise over the scene's scale. It covers the cladding at most HEAT_ALPHA, and not at all where k is low.
  const HEAT_FRAG = '#include <common>\n#include <logdepthbuf_pars_fragment>\n' + `
    uniform float uGain, uTime, uTau, uHold, uPeak, uSigma0, uGrow;
    uniform vec4 uClip;
    varying float vA;
    varying vec2 vXZ;
    ${heatColourGlsl()}
    void main() {
      #include <logdepthbuf_fragment>
      if (vXZ.x < uClip.x || vXZ.y < uClip.y || vXZ.x > uClip.z || vXZ.y > uClip.w) discard;
      float t = min(uTime, uHold * uTau);
      float k = uPeak * (1.0 - exp(-t / uTau)) * exp(-vA * vA / (2.0 * (uSigma0 * uSigma0 + uGrow * t)));
      gl_FragColor = vec4(uGain * heatColour(k), ${HEAT_ALPHA} * smoothstep(0.03, 0.3, k));
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`;
  // the field between the electrodes, E = (V / gap) cos(2 pi (s - v t) / wave): green at a positive crest, magenta at a
  // negative one, over the scene's scale; it covers what is under it at most RF_ALPHA
  const RF_FRAG = '#include <common>\n#include <logdepthbuf_pars_fragment>\n' + `
    uniform float uGain, uTime, uSpeed, uWave, uField, uRef;
    uniform vec4 uClip;
    varying float vA;
    varying vec2 vXZ;
    void main() {
      #include <logdepthbuf_fragment>
      if (vXZ.x < uClip.x || vXZ.y < uClip.y || vXZ.x > uClip.z || vXZ.y > uClip.w) discard;
      float e = cos(6.2831853 * (vA - uSpeed * uTime) / uWave) * sign(uField);
      vec3 c = e >= 0.0 ? vec3(${RF_POSITIVE.join(', ')}) : vec3(${RF_NEGATIVE.join(', ')});
      gl_FragColor = vec4(uGain * c, ${RF_ALPHA} * clamp(abs(uField) / uRef, 0.0, 1.0) * abs(e));
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`;
  // a multimode region: a flat mesh on the top of the part's body over the region, moved toward the eye by 0.3 % of
  // the view distance (as the ribbon's margin), never more than half the gap to a part over it, which still hides it
  const REGION_VERT = '#include <common>\n#include <logdepthbuf_pars_vertex>\n' + `
    attribute float aGap;
    varying vec2 vUv;
    void main() {
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vec3 eye = normalize(cameraPosition - wp.xyz);
      float depth = max(-(viewMatrix * wp).z, 1e-6);
      wp.xyz += eye * min(0.003 * depth, 0.5 * aGap);
      vUv = uv;
      gl_Position = projectionMatrix * viewMatrix * wp;
      #include <logdepthbuf_vertex>
    }`;
  // its field from the payload's grid: real and imaginary part (128 is zero), arrival time, inside the region
  const REGION_FRAG = '#include <common>\n#include <logdepthbuf_pars_fragment>\n' + FIELD_COLOUR + `
    uniform sampler2D uField;
    uniform float uScale, uT0, uT1, uGain, uTime, uOmegaT, uFade, uRef;
    varying vec2 vUv;
    void main() {
      #include <logdepthbuf_fragment>
      vec4 s = texture2D(uField, vUv);
      vec2 z = (s.rg * 255.0 - 128.0) / 127.0 * uScale;
      float amp = length(z);
      float front = clamp((uTime - (uT0 + s.b * (uT1 - uT0))) / uFade, 0.0, 1.0);
      float e = amp > 1e-6 ? (z.x * cos(uOmegaT) + z.y * sin(uOmegaT)) / amp : 0.0;
      gl_FragColor = vec4(uGain * fieldColour(e), clamp(amp / uRef, 0.0, 1.0) * front * s.a * fieldWeight(e));
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`;

  function power(p) { return p.jones.reduce((sum, v) => sum + v * v, 0); }
  // the payload's colour keys are Python's str(float): "1550.0", never JavaScript's "1550"
  function pyKey(nm) { return Number.isInteger(nm) ? nm.toFixed(1) : String(nm); }
  function colourOf(nm) {
    const colours = data.colors || {};
    let hex = colours[pyKey(nm)];
    if (hex === undefined) hex = Object.entries(colours).find(([key]) => Number(key) === nm)?.[1];
    return new THREE.Color(hex || '#ffffff');
  }
  function plan(p) { return new THREE.Vector3(p[0], 0, -p[1]); }       // world (x, y) -> three (x, 0, -y)
  function planDistance(a, b) { return Math.hypot(a.x - b.x, a.z - b.z); }

  // points every STEP along a polyline; the corners stay. With lists of values (one value per point each),
  // out.shares holds each list interpolated at the new points. out.along holds, per new point, the segment it lies
  // on and its fraction there, so a later list of values can be read at the same points (valuesAt).
  function resample(pts, lists) {
    let total = 0;
    for (let i = 0; i < pts.length - 1; i++) total += pts[i].distanceTo(pts[i + 1]);
    const step = Math.max(STEP, total / MAX_SAMPLES), out = [pts[0].clone()], map = [0, 0];
    const vals = lists ? lists.map((v) => (v ? [v[0]] : null)) : null;
    for (let i = 0; i < pts.length - 1; i++) {
      const len = pts[i].distanceTo(pts[i + 1]);
      if (len < 1e-9) continue;
      const n = Math.max(1, Math.ceil(len / step));
      for (let k = 1; k <= n; k++) {
        out.push(pts[i].clone().lerp(pts[i + 1], k / n));
        map.push(i, k / n);
        if (vals) lists.forEach((v, j) => { if (v) vals[j].push(v[i] + (v[i + 1] - v[i]) * (k / n)); });
      }
    }
    if (vals) out.shares = vals.map((v) => (v ? Float32Array.from(v) : null));
    out.along = map;
    return out;
  }
  // a list of values (one per point of the polyline resample read) at the resampled points
  function valuesAt(map, values) {
    const out = new Float32Array(map.length / 2);
    for (let k = 0; k < out.length; k++) {
      const i = map[2 * k], f = map[2 * k + 1], a = values[i], b = i + 1 < values.length ? values[i + 1] : a;
      out[k] = a + (b - a) * f;
    }
    return out;
  }
  // a drawn path runs the way the engine's edge runs: from its first point
  function orient(pts, edgePoints) {
    const start = plan(edgePoints[0]);
    return planDistance(pts[0], start) <= planDistance(pts[pts.length - 1], start) ? pts : pts.slice().reverse();
  }
  // the meshes of a host, or only those in one of its guide materials
  function meshesOf(obj, presets) {
    const out = [];
    obj.traverse((o) => {
      if (!o.isMesh) return;
      const materials = Array.isArray(o.material) ? o.material : [o.material];
      if (!presets || materials.some((m) => m && m.userData && presets.includes(m.userData.odPreset))) out.push(o);
    });
    return out;
  }
  function topOf(meshes) {
    const box = new THREE.Box3();
    for (const m of meshes) box.expandByObject(m);
    return box.isEmpty() ? 0 : box.max.y + 1;
  }
  // the top and bottom of the first guide a vertical line at (x, z) meets, and its mesh, or null
  function column(x, z, meshes, top) {
    raycaster.set(new THREE.Vector3(x, top, z), DOWN);
    const hits = raycaster.intersectObjects(meshes, false);
    if (!hits.length) return null;
    const own = hits.filter((h) => h.object === hits[0].object);
    return { top: own[0].point.y, bottom: own[own.length - 1].point.y, object: hits[0].object };
  }

  // the tubes the static view drew for a beam or a cable: segments with their radius, in world space
  function drawnTubes(obj) {
    const out = [];
    if (!obj) return out;
    obj.traverse((o) => {
      if (!o.isMesh) return;
      const g = o.geometry, par = g.parameters || {};
      if (g.type === 'CylinderGeometry') {
        const a = o.localToWorld(new THREE.Vector3(0, -par.height / 2, 0)), b = o.localToWorld(new THREE.Vector3(0, par.height / 2, 0));
        out.push({ a, b, r: par.radiusTop });
      } else if (g.type === 'TubeGeometry') {
        const axis = par.path.getSpacedPoints(Math.max(64, 4 * par.tubularSegments)).map((q) => o.localToWorld(q.clone()));
        for (let i = 0; i < axis.length - 1; i++) out.push({ a: axis[i], b: axis[i + 1], r: par.radius });
      }
    });
    return out;
  }

  // --- placement: each engine edge on its drawn host ------------------------------------------------------------
  function placeRoute(edge, obj) {
    if (obj && obj.userData.odStrip) {
      const strip = obj.userData.odStrip, lift = obj.position.y;
      const pts = strip.points.map((p) => new THREE.Vector3(p.x, p.y + strip.mid + lift, p.z));
      const meshes = meshesOf(obj);
      return { kind: 'guide', pts: resample(orient(pts, edge.points)), width: strip.width, thick: strip.thick,
               meshes, top: topOf(meshes) };
    }
    if (obj && obj.userData.odCable) {
      const { curve, radius } = obj.userData.odCable;
      const n = Math.min(MAX_SAMPLES, Math.max(8, Math.ceil(curve.getLength() / STEP)));
      const pts = orient(curve.getSpacedPoints(n), edge.points);
      return { kind: 'tube', pts, width: 2 * radius, thick: 2 * radius, tubes: drawnTubes(obj) };
    }
    return null;
  }
  function placeBeam(edge, host, item, obj) {
    if (!item || !item.points || item.points.length < 2) return null;
    const pts = item.points.map((p) => new THREE.Vector3(p[0], p[1] + BEAM_PLANE, p[2]));
    // segment k joins anchors k and k + 1: their points are neighbours at index k or later (a periscope adds
    // points between two anchors on one part)
    const a = plan(edge.points[0]), b = plan(edge.points[edge.points.length - 1]);
    let best = -1, cost = Infinity;
    for (let i = Math.min(host.segment || 0, pts.length - 2); i < pts.length - 1; i++) {
      const c = planDistance(pts[i], a) + planDistance(pts[i + 1], b);
      if (c < cost - 1e-9) { cost = c; best = i; }
    }
    if (best < 0) return null;
    const radius = (item.width || 0.8) * 0.3;                       // the static beam tube's radius
    const axis = [pts[best], pts[best + 1]];
    // a focusing beam has no static mesh: its check is its widest envelope round the anchors' line
    const tubes = item.type === 'fbeam' ? [{ a: axis[0], b: axis[1], r: (item.width || 0.8) / 2 }] : drawnTubes(obj);
    return { kind: 'tube', pts: resample(axis), width: 2 * radius, thick: 2 * radius, tubes };
  }
  // a part edge on its own points, or on its profile's or a rail's points with values at each sample: the first list
  // is the share every packet takes, the others the values of single packets (null: the first list)
  function placePart(points, shares, item, obj, guideWidth, outlines) {
    if (!item || !points || points.length < 2) return null;
    const flat = resample(points.map(plan), shares);
    const weight = flat.shares ? flat.shares[0] : null, weights = flat.shares ? flat.shares.slice(1) : null;
    if (item.beamPlane) {                                           // a free-space optic: at its beam height
      const y = BEAM_PLANE + (item.lift || 0);
      for (const p of flat) p.y = y;
      return { kind: 'axis', pts: flat, width: 0.5, thick: 0.5, box: obj ? new THREE.Box3().setFromObject(obj) : null, weight, weights,
               map: flat.along };
    }
    if (!obj) return null;
    const meshes = meshesOf(obj, item.guide), top = topOf(meshes);
    // a sample off the guides inside one of the part's multimode regions (outlines from the payload) lies in the
    // translucent body drawn there (an AWG's slab, in another material than its guides), at that body's middle
    const regions = (outlines || []).map((o) => o.map(plan)), bodies = regions.length ? bodiesOf(obj, meshes) : [];
    const bodyTop = topOf(bodies);
    const found = flat.map((p) => (meshes.length ? column(p.x, p.z, meshes, top) : null)
                                  || (bodies.length && inRegion(p, regions) ? column(p.x, p.z, bodies, bodyTop) : null));
    const hit = found.map((c, i) => (c ? i : -1)).filter((i) => i >= 0);
    const box = hit.length ? null : new THREE.Box3().setFromObject(obj);     // no guide met: the body's middle
    let thick = 0;
    flat.forEach((p, i) => {
      // a sample off the guides takes the height of the nearest sample on one: the engine's path stays as given
      const near = found[i] || (hit.length ? found[hit.reduce((b, j) => (Math.abs(j - i) < Math.abs(b - i) ? j : b))] : null);
      p.y = near ? 0.5 * (near.top + near.bottom) : 0.5 * (box.min.y + box.max.y);
      if (near) thick = Math.max(thick, near.top - near.bottom);
    });
    return { kind: 'guide', pts: flat, width: guideWidth, thick, meshes, top, bodies, bodyTop, regions, weight, weights,
             map: flat.along };
  }
  // whether a point (in plan) lies inside one of the outlines (in plan; even-odd rule)
  function inRegion(p, outlines) {
    return outlines.some((poly) => {
      let inside = false;
      for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const a = poly[i], b = poly[j];
        if ((a.z > p.z) !== (b.z > p.z) && p.x < (b.x - a.x) * (p.z - a.z) / (b.z - a.z) + a.x) inside = !inside;
      }
      return inside;
    });
  }
  // the part's translucent meshes that are not its guides: multimode bodies drawn in another material (an AWG's slabs)
  function bodiesOf(obj, guides) {
    return meshesOf(obj).filter((m) => !guides.includes(m) && [].concat(m.material).every((x) => x && x.transparent));
  }
  // for each sample of a guide edge: the gap from the guide top up to the first opaque part over it or beside it,
  // out to the reach of a wide glow (a heater, a lead, a metal route); OPEN where there is none
  const REACH = [0, 2, -2, 6, -6, 12, -12];
  function coverGaps(rec, pool) {
    const box = new THREE.Box3().setFromPoints(rec.pts).expandByScalar(Math.max(...REACH) + rec.width);
    const near = pool.filter((c) => c.box.intersectsBox(box) && !rec.meshes.includes(c.mesh)).map((c) => c.mesh);
    if (!near.length) return null;
    const raw = rec.pts.map((p, i) => {
      const k = Math.min(i + 1, rec.pts.length - 1), j = Math.max(i - 1, 0);
      const across = new THREE.Vector3(rec.pts[k].z - rec.pts[j].z, 0, rec.pts[j].x - rec.pts[k].x).normalize();
      const top = p.y + rec.thick / 2;
      let gap = OPEN;
      for (const d of REACH) {
        const off = d === 0 ? 0 : Math.sign(d) * (0.5 * rec.width + Math.abs(d));
        raycaster.set(new THREE.Vector3(p.x + across.x * off, top + 1e-4, p.z + across.z * off), UP);
        const hits = raycaster.intersectObjects(near, false);
        if (hits.length) gap = Math.min(gap, hits[0].distance);
      }
      return gap;
    });
    // a sample takes the smallest gap within the same reach along the path: the glow is that long each way
    const reach = Math.max(...REACH);
    let a = 0;
    return raw.map((_, i) => {
      const s = rec.pts[i];
      while (s.distanceTo(rec.pts[a]) > reach && a < i) a++;
      let gap = OPEN;
      for (let k = a; k < raw.length && rec.pts[k].distanceTo(s) <= reach; k++) gap = Math.min(gap, raw[k]);
      return gap;
    });
  }

  function glowMesh(rec) {
    const pts = rec.pts, n = pts.length;
    rec.cum = new Float64Array(n);
    for (let i = 1; i < n; i++) rec.cum[i] = rec.cum[i - 1] + pts[i].distanceTo(pts[i - 1]);
    rec.length = rec.cum[n - 1];
    const position = new Float32Array(6 * n), tangent = new Float32Array(6 * n), side = new Float32Array(2 * n);
    const gap = new Float32Array(2 * n), bend = new Float32Array(2 * n);
    rec.glow = new Float32Array(6 * n);                 // the drawn colour, per ribbon vertex (two per sample)
    rec.power = new Float32Array(n);                    // the power drawn at each sample, and its colour mix
    rec.mix = new Float32Array(3 * n);
    // the path's direction over SMOOTH each way: a ribbon wider than the step folds where the direction jumps
    const at = (d) => {
      d = Math.max(0, Math.min(rec.length, d));
      let a = 0, b = n - 1;
      while (b - a > 1) { const m = (a + b) >> 1; if (rec.cum[m] <= d) a = m; else b = m; }
      const span = rec.cum[b] - rec.cum[a];
      return pts[a].clone().lerp(pts[b], span > 0 ? (d - rec.cum[a]) / span : 0);
    };
    const dirs = pts.map((p, i) => {
      const t = at(rec.cum[i] + SMOOTH).sub(at(rec.cum[i] - SMOOTH));
      return t.lengthSq() > 0 ? t.normalize() : pts[Math.min(i + 1, n - 1)].clone().sub(pts[Math.max(i - 1, 0)]).normalize();
    });
    for (let i = 0; i < n; i++) {
      const t = dirs[i], j = Math.max(i - 1, 0), k = Math.min(i + 1, n - 1);
      const turn = dirs[j].angleTo(dirs[k]), run = rec.cum[k] - rec.cum[j];
      for (let s = 0; s < 2; s++) {
        const v = 2 * i + s;
        position.set([pts[i].x, pts[i].y, pts[i].z], 3 * v);
        tangent.set([t.x, t.y, t.z], 3 * v);
        side[v] = s ? 1 : -1;
        gap[v] = rec.gaps ? rec.gaps[i] : OPEN;
        bend[v] = turn > 1e-6 ? 0.9 * run / turn : OPEN;          // 0.9 of the bend's radius
      }
    }
    const index = [];
    for (let i = 0; i < n - 1; i++) { const q = 2 * i; index.push(q, q + 1, q + 2, q + 1, q + 3, q + 2); }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
    rec.dirs = dirs;
    rec.tangent = tangent;
    rec.tangentAttr = new THREE.BufferAttribute(tangent, 3);
    geometry.setAttribute('aTangent', rec.tangentAttr);
    geometry.setAttribute('aSide', new THREE.BufferAttribute(side, 1));
    geometry.setAttribute('aGap', new THREE.BufferAttribute(gap, 1));
    geometry.setAttribute('aBend', new THREE.BufferAttribute(bend, 1));
    rec.attr = new THREE.BufferAttribute(rec.glow, 3).setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('aGlow', rec.attr);
    geometry.setIndex(index);
    // glows that overlap (two rails of a coupler, guides closer than the ribbon's least width on screen, the joint of
    // two ribbons) combine as light on a screen does, a + b - ab: on a dark chip each adds its own light, and
    // together they stay below white, near the brightness of their powers added. The factors are a + b (1 - a), with
    // the glow a at most 1 (FRAG clamps it), so no factor is negative. In the "high" quality the view is drawn into a
    // float target, where a part can be brighter than 1 (white before the tone curve): there the sum is
    // 1 + (b - 1)(1 - a), so the glow can bring such a part down toward white but never below it (holding b itself
    // would need a second pass). The "fast" quality blends after the tone curve, in sRGB values: there the drawn
    // brightness does not keep the ratio of the root powers.
    const material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor,
      blendDst: THREE.OneMinusSrcColorFactor, blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor,
      uniforms: { uHalf: { value: 0.5 * HALO * rec.width }, uGuide: { value: new THREE.Vector2(rec.width / 2, rec.thick / 2) },
                  uViewport: VIEWPORT, uGain: GAIN, uMinPx: { value: 10 } },
    });
    rec.geometry = geometry;
    rec.lightMesh = ribbon(rec, geometry, material);
  }
  function ribbon(rec, geometry, material) {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;            // the vertex shader widens the ribbon: its bounds are not the points'
    // in a chip guide, before the translucent cladding (seen through it); in a beam, after the beam's own tube
    mesh.renderOrder = rec.kind === 'tube' ? 10 : -1;
    S.group.add(mesh);
    return mesh;
  }

  // --- the Field look: each record's field on the ribbon of its edge or rail --------------------------------------
  // the arc fraction of each point of a polyline (in plan)
  function fractions(pts) {
    const out = new Float64Array(pts.length);
    for (let i = 1; i < pts.length; i++) out[i] = out[i - 1] + planDistance(pts[i], pts[i - 1]);
    const total = out[pts.length - 1];
    if (total > 0) for (let i = 0; i < out.length; i++) out[i] /= total;
    return out;
  }
  // a value given at increasing fractions ``at``, read at fraction f (linear between them)
  function readAt(at, values, f) {
    let a = 0, b = at.length - 1;
    if (f <= at[0]) return values[0];
    if (f >= at[b]) return values[b];
    while (b - a > 1) { const m = (a + b) >> 1; if (at[m] <= f) a = m; else b = m; }
    const span = at[b] - at[a];
    return values[a] + (values[b] - values[a]) * (span > 0 ? (f - at[a]) / span : 0);
  }
  // the colour uniforms and the blending of a wavelength's layer: one wavelength that is not visible (white) is drawn
  // in red, white and blue over what is under it; other wavelengths in their own colour, added (the intensities of
  // different wavelengths add)
  function tinted(nm) {
    const tint = colourOf(nm), plain = tint.r === 1 && tint.g === 1 && tint.b === 1;
    return { uniforms: { uTint: { value: tint }, uPlain: { value: plain ? 1 : 0 } },
             blending: plain ? THREE.NormalBlending : THREE.AdditiveBlending };
  }
  // one layer of the field on a ribbon: amplitude, phase and arrival time at each sample, and the front's fade (ps);
  // key names the light it draws (an edge's record, a rail's wavelength), so a drive sample can draw its own numbers there
  function fieldLayer(rec, amp, phase, arrive, fade, nm, key) {
    const n = rec.pts.length, field = new Float32Array(6 * n);
    for (let i = 0; i < n; i++) for (let s = 0; s < 2; s++) field.set([amp[i], phase[i], arrive[i]], 3 * (2 * i + s));
    const geometry = new THREE.BufferGeometry();
    for (const name of ['position', 'aTangent', 'aSide', 'aGap', 'aBend']) geometry.setAttribute(name, rec.geometry.getAttribute(name));
    geometry.setIndex(rec.geometry.getIndex());
    geometry.setAttribute('aField', new THREE.BufferAttribute(field, 3));
    const colour = tinted(nm);
    const material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FIELD_FRAG, defines: { FIELD: '' }, transparent: true, depthWrite: false,
      side: THREE.DoubleSide, blending: colour.blending,
      uniforms: { uHalf: { value: FIELD_HALF * rec.width }, uGuide: { value: new THREE.Vector2(rec.width / 2, rec.thick / 2) },
                  uViewport: VIEWPORT, uGain: GAIN, uMinPx: { value: 4 }, uTime: FIELD_TIME, uOmegaT: FIELD_OMEGA,
                  uFade: { value: Math.max(fade, 1e-6) }, uRef: REF, ...colour.uniforms },
    });
    const mesh = ribbon(rec, geometry, material);
    mesh.visible = S.look === 'field';
    (rec.fieldMeshes = rec.fieldMeshes || []).push(mesh);
    const layer = { amp, arrive, fade: Math.max(fade, 1e-6), key, mesh, attr: geometry.getAttribute('aField'), base: null };
    (rec.layers = rec.layers || []).push(layer);
    return layer;
  }
  // a drive sample's numbers on a layer (a null list keeps the layer's own); restoreLayer gives back the base state
  function setLayer(layer, amp, phase, arrive, fade) {
    const field = layer.attr.array;
    if (!layer.base) layer.base = { field: field.slice(), amp: layer.amp, arrive: layer.arrive, fade: layer.fade };
    const n = field.length / 6;
    amp = amp || layer.amp;
    arrive = arrive || layer.arrive;
    for (let i = 0; i < n; i++) {
      for (let s = 0; s < 2; s++) {
        const v = 3 * (2 * i + s);
        field[v] = amp[i];
        if (phase) field[v + 1] = phase[i];
        field[v + 2] = arrive[i];
      }
    }
    layer.attr.needsUpdate = true;
    layer.amp = amp;
    layer.arrive = arrive;
    if (fade !== undefined && fade !== null) layer.fade = Math.max(fade, 1e-6);
    layer.mesh.material.uniforms.uFade.value = layer.fade;
  }
  function restoreLayer(layer) {
    if (!layer.base) return;
    layer.attr.array.set(layer.base.field);
    layer.attr.needsUpdate = true;
    Object.assign(layer, { amp: layer.base.amp, arrive: layer.base.arrive, fade: layer.base.fade, base: null });
    layer.mesh.material.uniforms.uFade.value = layer.fade;
  }
  // an edge's records: the amplitude (amp0 to amp) and the display phase run along the edge the way its light runs (a
  // link's light may run back); where the edge shares a guide the payload's profile gives them, and where a
  // multimode region draws the light (the edge's cuts) it draws nothing
  function edgeField(rec, id, records) {
    for (const r of records) {
      const { amp, phase, arrive } = edgeArrays(rec, id, r, ((data.cw || {}).profiles || {})[id]);
      fieldLayer(rec, amp, phase, arrive, r.fade_ps, r.wavelength_nm, recordKey(r));
    }
  }
  function recordKey(r) { return r.from + '>' + r.to + '@' + r.wavelength_nm; }
  // one record's amplitude, display phase and arrival time at each sample of the ribbon: from the edge's profile at
  // the record's wavelength (``profiles``: the payload's, or a drive sample's) where the edge shares a guide, else
  // straight from amp0 to amp
  function edgeArrays(rec, id, r, profiles) {
    const cw = data.cw || {}, f = fractions(rec.pts), cuts = (cw.cuts || {})[id] || [];
    const profile = (profiles || []).find((p) => p.wavelength_nm === r.wavelength_nm);
    const at = profile ? fractions(profile.points.map(plan)) : null;
    const line = (ph, ft) => ph[0] + (ph[1] - ph[0]) * ft;
    const n = f.length, amp = new Float32Array(n), phase = new Float32Array(n), arrive = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const ft = r.reverse ? 1 - f[i] : f[i];
      amp[i] = profile ? readAt(at, profile.amp, ft) : r.amp0 + (r.amp - r.amp0) * ft;
      phase[i] = profile ? readAt(at, profile.phase, ft) : line(r.phase, ft);
      if (cuts.some(([a, b]) => ft > a + 1e-9 && ft < b - 1e-9)) amp[i] = 0;
      arrive[i] = r.t0 !== undefined ? r.t0 + (r.t1 - r.t0) * ft : 0;
    }
    return { amp, phase, arrive };
  }
  // a coupling section's rail: the payload's field at each of its points (display phase in it). The phase is read
  // as the angle of the stronger component, on the branch nearest the previous point's phase plus the drawn crests
  // between them (2 pi s / the payload's crest spacing), so it can run on between the ribbon's samples.
  function railField(rec, rail, points) {
    for (const entry of rail.fields) {
      const { amp, phase, arrive } = railArrays(rec, rail, points, entry);
      fieldLayer(rec, amp, phase, arrive, entry.fade_ps, entry.wavelength_nm, 'rail@' + entry.wavelength_nm);
    }
  }
  function railArrays(rec, rail, points, entry) {
    const at = fractions(points.map(plan)), f = fractions(rec.pts), t = rail.t || [0, 0], arcs = rail.arcs;
    const m = points.length, amps = new Float64Array(m), phases = new Float64Array(m), crest = entry.crest_um;
    for (let j = 0; j < m; j++) {
      const v = entry.field[j], x = Math.hypot(v[0], v[1]), y = v.length > 2 ? Math.hypot(v[2], v[3]) : 0;
      amps[j] = Math.hypot(x, y);
      let phase = y > x ? Math.atan2(v[3], v[2]) : Math.atan2(v[1], v[0]);
      if (j > 0) {
        const want = phases[j - 1] + 2 * Math.PI * (arcs[j] - arcs[j - 1]) / crest;
        phase += 2 * Math.PI * Math.round((want - phase) / (2 * Math.PI));
      }
      phases[j] = phase;
    }
    const n = f.length, amp = new Float32Array(n), phase = new Float32Array(n), arrive = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      amp[i] = readAt(at, amps, f[i]);
      phase[i] = readAt(at, phases, f[i]);
      arrive[i] = t[0] + (t[1] - t[0]) * f[i];
    }
    return { amp, phase, arrive };
  }
  // a flat outline (in plan) as triangles: the outline triangulated, then each triangle split in four (at the midpoints
  // of its sides, shared with its neighbours) until no side is longer than ``most``, at most four times
  function finely(outline, most) {
    const pts = outline.map((p) => new THREE.Vector2(p.x, p.z));
    if (pts.length > 2 && pts[0].distanceTo(pts[pts.length - 1]) < 1e-9) pts.pop();
    let faces = THREE.ShapeUtils.triangulateShape(pts, []);
    const side = ([a, b, c]) => Math.max(pts[a].distanceTo(pts[b]), pts[b].distanceTo(pts[c]), pts[c].distanceTo(pts[a]));
    for (let level = 0; level < 4 && faces.length && Math.max(...faces.map(side)) > most; level++) {
      const middle = new Map(), next = [];
      const mid = (a, b) => {
        const key = a < b ? a + ',' + b : b + ',' + a;
        if (!middle.has(key)) { middle.set(key, pts.length); pts.push(pts[a].clone().lerp(pts[b], 0.5)); }
        return middle.get(key);
      };
      for (const [a, b, c] of faces) {
        const ab = mid(a, b), bc = mid(b, c), ca = mid(c, a);
        next.push([a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]);
      }
      faces = next;
    }
    return { pts, faces };
  }
  // a multimode region: its grid of the field drawn on a flat mesh of its own outline, on the top of the part's
  // guides and bodies there (a slab's apertures can stand higher than the slab), with each point's place in the grid
  // as its texture coordinate and the gap up to the first other part over it. Its check points are the grid's samples
  // whose neighbours are all inside the region, at the middle of the body there.
  function placeRegion(region, item, obj, pool) {
    if (!obj) return null;
    const [o, u, v] = region.corners, [nu, nv] = region.size;
    const at = (a, b) => plan([o[0] + (u[0] - o[0]) * a + (v[0] - o[0]) * b, o[1] + (u[1] - o[1]) * a + (v[1] - o[1]) * b]);
    const guides = meshesOf(obj, item && item.guide);
    const meshes = guides.length ? guides.concat(bodiesOf(obj, guides)) : meshesOf(obj);
    const bytes = Uint8Array.from(atob(region.data), (ch) => ch.charCodeAt(0));
    const inside = (i, j) => bytes[4 * (j * nu + i) + 3] > 127;
    const top = topOf(meshes), columns = [];
    for (let j = 0; j < nv; j += Math.max(1, Math.floor(nv / 12))) {
      for (let i = 0; i < nu; i += Math.max(1, Math.floor(nu / 12))) {
        if (!inside(i, j)) continue;
        const p = at(i / (nu - 1), j / (nv - 1)), c = meshes.length ? column(p.x, p.z, meshes, top) : null;
        if (c) columns.push({ c, d: Math.hypot(i / (nu - 1) - 0.5, j / (nv - 1) - 0.5) });
      }
    }
    if (!columns.length) return null;
    const body = columns.reduce((a, b) => (b.d < a.d ? b : a)).c;            // the body nearest the region's middle
    const surface = Math.max(...columns.map((x) => x.c.top));
    const outline = region.outline.map(plan), box = new THREE.Box3().setFromPoints(outline);
    const span = Math.max(box.max.x - box.min.x, box.max.z - box.min.z);
    const { pts, faces } = finely(outline, span / 12);
    const ou = [u[0] - o[0], u[1] - o[1]], ov = [v[0] - o[0], v[1] - o[1]], det = ou[0] * ov[1] - ou[1] * ov[0];
    const above = new THREE.Box3(new THREE.Vector3(box.min.x - 1, surface, box.min.z - 1),
                                 new THREE.Vector3(box.max.x + 1, surface + 1e3, box.max.z + 1));
    const near = pool.filter((c) => !meshes.includes(c.mesh) && c.box.intersectsBox(above)).map((c) => c.mesh);
    const position = new Float32Array(3 * pts.length), uv = new Float32Array(2 * pts.length), gaps = new Float32Array(pts.length);
    pts.forEach((p, k) => {
      const x = p.x - o[0], y = -p.y - o[1];
      const a = (x * ov[1] - y * ov[0]) / det, b = (ou[0] * y - ou[1] * x) / det;
      position.set([p.x, surface, p.y], 3 * k);
      uv.set([(0.5 + (nu - 1) * a) / nu, (0.5 + (nv - 1) * b) / nv], 2 * k);
      gaps[k] = OPEN;
      if (near.length) {
        raycaster.set(new THREE.Vector3(p.x, surface + 1e-4, p.y), UP);
        const hits = raycaster.intersectObjects(near, false);
        if (hits.length) gaps[k] = hits[0].distance;
      }
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    geometry.setAttribute('aGap', new THREE.BufferAttribute(gaps, 1));
    geometry.setIndex(faces.flat());
    const texture = new THREE.DataTexture(bytes, nu, nv, THREE.RGBAFormat, THREE.UnsignedByteType);
    texture.magFilter = texture.minFilter = THREE.LinearFilter;
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    const colour = tinted(region.wavelength_nm);
    const material = new THREE.ShaderMaterial({
      vertexShader: REGION_VERT, fragmentShader: REGION_FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      blending: colour.blending,
      uniforms: { uField: { value: texture }, uScale: { value: region.scale }, uT0: { value: region.t[0] }, uT1: { value: region.t[1] },
                  uGain: GAIN, uTime: FIELD_TIME, uOmegaT: FIELD_OMEGA, uFade: { value: Math.max(region.fade_ps, 1e-6) },
                  uRef: REF, ...colour.uniforms },
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    // over a translucent body (an AWG's slab) after it, as the light shows through its guide's top; else before the
    // translucent cladding, as the ribbons
    const clear = [].concat(body.object.material).every((m) => m && m.transparent);
    mesh.renderOrder = clear ? 1 : -1;
    S.group.add(mesh);
    const mid = 0.5 * (body.top + body.bottom), checks = [];
    for (let j = 1; j < nv - 1; j += 2) {
      for (let i = 1; i < nu - 1; i += 2) {
        let all = true;
        for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) all = all && inside(i + di, j + dj);
        if (all) { const p = at(i / (nu - 1), j / (nv - 1)); p.y = mid; checks.push(p); }
      }
    }
    return { kind: 'guide', region, pts: checks, meshes, top, bytes, fieldMeshes: [mesh] };
  }
  // the effect meshes sit under the optical field's ribbons (render order -1): drawn first, before the translucent cladding
  function effectMesh(geometry, fragmentShader, uniforms) {
    const material = new THREE.ShaderMaterial({
      vertexShader: EFFECT_VERT, fragmentShader, transparent: true, depthWrite: false, side: THREE.DoubleSide, uniforms,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    // The ambient occlusion pass (GTAO) reads the depth of every mesh it renders, and would darken the gap or the heater's
    // cladding under a flat map. Camera layers do not help: the pass renders with the main camera. Its scene pass hides
    // lines and points (checked in three.js 0.180's GTAOPass._overrideVisibility; the page loads 0.186), so the map says
    // it is a line; WebGLRenderer still draws it as a mesh (it tests isMesh first). A test runs the page with AO on.
    mesh.isLine = true;
    mesh.renderOrder = -2;
    S.group.add(mesh);
    return mesh;
  }
  // the chip's outline in plan (minimum x, z, maximum x, z), where a map is drawn; no bound when the page has no chip
  function chipClip() {
    const box = window.__odChipBox;
    if (!box || box.isEmpty() || typeof odDieFootprint !== 'function') return new THREE.Vector4(-1e9, -1e9, 1e9, 1e9);
    const f = odDieFootprint(box);
    return new THREE.Vector4(f.cx - f.hx, f.cz - f.hz, f.cx + f.hx, f.cz + f.hz);
  }
  // the height of the host's cladding: the top of its highest mesh that is not a metal (the silicon or the oxide the heaters and
  // the electrodes stand on), or null. The heater metal and the electrodes stand above it and keep their own look.
  const METAL = /gold|copper|tungsten|alumin|titanium|\btin\b|platinum|metal/i;
  function surfaceOver(obj) {
    const meshes = meshesOf(obj).filter((m) => ![].concat(m.material).some((x) => x && x.userData && METAL.test(x.userData.odPreset || '')));
    const box = new THREE.Box3();
    for (const m of meshes) box.expandByObject(m);
    return box.isEmpty() ? null : box.max.y;
  }
  // the distance from a plan point to a polyline
  function distanceTo(pts, x, z) {
    let best = Infinity;
    for (let i = 0; i < pts.length - 1; i++) {
      const ax = pts[i].x, az = pts[i].z, dx = pts[i + 1].x - ax, dz = pts[i + 1].z - az, len2 = dx * dx + dz * dz;
      const u = len2 > 0 ? Math.min(Math.max(((x - ax) * dx + (z - az) * dz) / len2, 0), 1) : 0;
      best = Math.min(best, Math.hypot(x - ax - u * dx, z - az - u * dz));
    }
    return best;
  }
  // a heater's temperature map: a grid over its spine and the widest spread, each vertex holding its distance to the spine;
  // scale is the scene's scale (K) that the colours run to
  function heatField(heat, obj, scale) {
    const spine = heat.path.map(plan), s0 = heat.width_um / 2;
    const reach = 3 * Math.sqrt(s0 * s0 + heat.grow_um2_per_s * heat.hold_tau * heat.tau_s);
    const box = new THREE.Box3().setFromPoints(spine).expandByScalar(reach);
    const w = box.max.x - box.min.x, h = box.max.z - box.min.z;
    const step = Math.max(s0 / 2, Math.sqrt(w * h / HEAT_CELLS));
    const nu = Math.max(2, Math.ceil(w / step) + 1), nv = Math.max(2, Math.ceil(h / step) + 1);
    const y = surfaceOver(obj);
    if (y === null) return null;
    const position = new Float32Array(3 * nu * nv), dist = new Float32Array(nu * nv), index = [];
    for (let j = 0; j < nv; j++) {
      for (let i = 0; i < nu; i++) {
        const x = box.min.x + (w * i) / (nu - 1), z = box.min.z + (h * j) / (nv - 1), k = j * nu + i;
        position.set([x, y, z], 3 * k);
        dist[k] = distanceTo(spine, x, z);
        if (i < nu - 1 && j < nv - 1) index.push(k, k + 1, k + nu, k + 1, k + nu + 1, k + nu);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
    geometry.setAttribute('aA', new THREE.BufferAttribute(dist, 1));
    geometry.setIndex(index);
    const peak = heat.delta_t_k / scale;
    const mesh = effectMesh(geometry, HEAT_FRAG, {
      uGain: GAIN, uTime: HEAT_TIME, uTau: { value: heat.tau_s }, uHold: { value: heat.hold_tau }, uPeak: { value: peak },
      uSigma0: { value: s0 }, uGrow: { value: heat.grow_um2_per_s }, uClip: { value: chipClip() },
    });
    return { kind: 'heat', sid: heat.sid, mesh, y, peak };
  }
  // the field in the gap between two electrode edges: a strip from the signal edge to the ground edge; scale is the
  // scene's scale (V per um)
  function rfField(rf, obj, scale) {
    const signal = rf.signal.map(plan), ground = rf.ground.map(plan);
    const y = surfaceOver(obj);
    if (y === null || signal.length < 2 || signal.length !== ground.length) return null;
    const position = new Float32Array(6 * signal.length), along = new Float32Array(2 * signal.length), index = [];
    let arc = 0;
    signal.forEach((p, i) => {
      if (i > 0) arc += planDistance(p, signal[i - 1]);
      position.set([p.x, y, p.z, ground[i].x, y, ground[i].z], 6 * i);
      along.set([arc, arc], 2 * i);
      if (i > 0) index.push(2 * i - 2, 2 * i - 1, 2 * i, 2 * i - 1, 2 * i + 1, 2 * i);
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
    geometry.setAttribute('aA', new THREE.BufferAttribute(along, 1));
    geometry.setIndex(index);
    const mesh = effectMesh(geometry, RF_FRAG, {
      uGain: GAIN, uTime: { value: 0 }, uSpeed: { value: rf.v_rf_um_per_ps }, uWave: { value: rf.wave_um },
      uField: { value: rf.v / rf.gap_um }, uRef: { value: scale }, uClip: { value: chipClip() },
    });
    return { kind: 'rf', sid: rf.sid, mesh, y, secondsPerPs: rf.seconds_per_ps, peak: Math.abs(rf.v / rf.gap_um) / scale };
  }

  // --- the captions and the legends: a small block of text (#od-captions) while the light is on -------------------------
  // The payload's captions up to caption_split show in both looks (those in caption_light_only in Light only); the rest,
  // and the legends of the maps, in Field.
  // The captions in caption_folded (the model lines) fold behind a small Scales toggle, so the block stays short. A
  // video shows them all: the recording stage of render_video (window.__odVideo) and the page's Record video.
  let scalesOpen = false;
  let recording = false;          // the page's Record video runs (recordTour)
  function cssColour(rgb) { return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.LinearSRGBColorSpace).getStyle(); }
  function legend(title, low, high, stops) {
    const row = document.createElement('div');
    row.className = 'od-legend';
    row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-top:3px';
    const bar = document.createElement('i');
    bar.style.cssText = 'display:block;width:90px;height:8px;border-radius:2px;background:linear-gradient(to right,' + stops.join(',') + ')';
    const text = (t) => { const e = document.createElement('span'); e.textContent = t; return e; };
    row.append(text(title), text(low), bar, text(high));
    return row;
  }
  function drawCaptions() {
    let el = document.getElementById('od-captions');
    if (!el) {
      el = document.createElement('div');
      el.id = 'od-captions';
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    el.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:11;max-width:340px;padding:6px 9px;' +
      'border-radius:8px;background:rgba(17,22,28,0.72);color:#f3f6fa;font:11px/1.45 Inter,-apple-system,"Segoe UI",sans-serif;' +
      'pointer-events:none';
    el.replaceChildren();
    const split = data && data.caption_split >= 0 ? data.caption_split : 0;
    // while the tour plays: its own captions first, then the drive of the device in focus
    const stop = S.tour && S.tour.focus >= 0 ? S.tour.plan.stops[S.tour.focus] : null;
    // the tour's captions; the rates name driven stops only when a drive swings; at a driven stop its drive, or
    // that the drive stays as set when the page has no table for it
    const kept = stop && stop.drive && !stop.table ? [KEPT_CAPTION] : [];
    const driving = stop && stop.table ? [(data.tour && data.tour.drive_caption) || '', stop.table.caption].filter(Boolean) : [];
    const swings = S.tour && S.tour.plan.stops.some((s) => s.table) && data.tour && data.tour.driven_rates_caption;
    const own = S.tour ? (swings ? [data.tour.caption, data.tour.driven_rates_caption] : (data.tour && data.tour.captions) || []) : [];
    const tour = S.tour ? own.concat(kept, driving) : [];
    const folded = new Set((data && data.caption_folded) || []), lightOnly = new Set((data && data.caption_light_only) || []);
    const field = S.look === 'field';
    const listed = ((data && data.captions) || []).map((c, i) => [c, i])
      .filter(([, i]) => (i < split && !(field && lightOnly.has(i))) || (i >= split && field));
    const lines = tour.concat(listed.filter(([, i]) => !folded.has(i)).map(([c]) => c));
    const scales = listed.filter(([, i]) => folded.has(i)).map(([c]) => c);
    const on = S.enabled && data && data.enabled && lines.length + scales.length > 0 && !(window.__odPT && window.__odPT.active);
    el.hidden = !on;
    el.style.display = on ? 'block' : 'none';
    if (!on) return;
    const row = (text) => { const r = document.createElement('div'); r.textContent = text; el.appendChild(r); return r; };
    for (const line of lines) row(line);
    if (scales.length) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'od-scales';
      toggle.textContent = 'Scales ' + (scalesOpen ? '\u25be' : '\u25b8');
      toggle.setAttribute('aria-expanded', String(scalesOpen));
      toggle.title = scalesOpen ? 'Hide the model and scale notes' : 'Show the model and scale notes';
      toggle.style.cssText = 'display:block;margin:2px 0 0;padding:0;border:0;background:none;color:#b8c4d2;' +
        'font:inherit;cursor:pointer;pointer-events:auto';
      toggle.addEventListener('click', (e) => { e.stopPropagation(); scalesOpen = !scalesOpen; drawCaptions(); });
      el.appendChild(toggle);
      if (scalesOpen || recording || window.__odVideo === true) for (const line of scales) row(line).className = 'od-scale-line';
    }
    if (S.look !== 'field') { placeCaptions(); return; }
    if ((data.heat || []).length && data.heat_scale_k > 0) {
      el.appendChild(legend('Heat', '0 K', data.heat_scale_k + ' K', HEAT_STOPS.map(([at, rgb]) => cssColour(rgb) + ' ' + at * 100 + '%')));
    }
    if ((data.rf || []).length && data.rf_scale_v_per_um > 0) {
      el.appendChild(legend('RF', '-' + data.rf_scale_v_per_um, '+' + data.rf_scale_v_per_um + ' V per um',
                            [cssColour(RF_NEGATIVE), '#1b2230', cssColour(RF_POSITIVE)]));
    }
    placeCaptions();
  }
  // the block stands above what else is at the bottom left of the view: the layer legend and, when the bar reaches over it, the
  // bar (a saved page's, whose real height counts: it wraps to two rows on a narrow view); the editor has none
  function placeCaptions() {
    const el = document.getElementById('od-captions');
    if (!el || el.style.display === 'none') return;
    const mine = el.getBoundingClientRect();
    let bottom = 12;
    for (const node of [document.getElementById('layer-legend'), document.getElementById('od-bar')]) {
      if (!node || getComputedStyle(node).display === 'none') continue;
      const r = node.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && r.left < mine.right + 8 && r.right > mine.left - 8) bottom = Math.max(bottom, window.innerHeight - r.top + 8);
    }
    el.style.bottom = bottom + 'px';
  }
  // the light look or the field look: each mesh shows in its own look
  function applyLook() {
    for (const rec of placed) {
      if (rec.lightMesh) rec.lightMesh.visible = S.look === 'light';
      for (const mesh of rec.fieldMeshes || []) mesh.visible = S.look === 'field';
    }
    showEffects();
    drawCaptions();
    const select = document.getElementById('light-look');
    if (select && select.value !== S.look) select.value = S.look;
    drawnAt = null;
  }

  // the maps show in the Field look: a base map unless its part's drive swings at a stop, a swing map while it does
  function showEffects() {
    for (const effect of effects) effect.mesh.visible = S.look === 'field' && !effect.held;
    for (const effect of swingEffects) effect.mesh.visible = S.look === 'field' && effect.on;
  }
  // where one ribbon ends and the next starts at the same place, running on in nearly a straight line, both take the
  // mean of their directions there: each smooths its direction from one side only, and on a bend the two ends would
  // meet at an angle, leaving a gap on one side of the joint and an overlap on the other
  function alignJoints() {
    const recs = placed.filter((r) => r.dirs), key = (p) => Math.round(p.x * 1000) + ',' + Math.round(p.z * 1000);
    const starts = new Map();
    for (const r of recs) { const k = key(r.pts[0]); if (!starts.has(k)) starts.set(k, []); starts.get(k).push(r); }
    const setTangent = (rec, i, t) => {
      for (let s = 0; s < 2; s++) rec.tangent.set([t.x, t.y, t.z], 3 * (2 * i + s));
      rec.tangentAttr.needsUpdate = true;
    };
    for (const a of recs) {
      const n = a.pts.length, end = a.dirs[n - 1];
      let next = null, angle = 0.5;                       // at most about 30 degrees: a split keeps its own directions
      for (const b of starts.get(key(a.pts[n - 1])) || []) {
        if (b !== a && end.angleTo(b.dirs[0]) < angle) { next = b; angle = end.angleTo(b.dirs[0]); }
      }
      if (!next) continue;
      const mean = end.clone().add(next.dirs[0]).normalize();
      setTangent(a, n - 1, mean);
      setTangent(next, 0, mean);
    }
  }

  function clear() {
    if (!S.group) return;
    S.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    if (S.group.parent) S.group.parent.remove(S.group);
    S.group = null;
  }

  // pending: the editor sent the items first and the light comes in a later build; the light stays on meanwhile
  // (the world stays navy) and draws nothing
  function build(payload, items, pending) {
    if (S.tour) stopTour(false);           // the tour's records and meshes are about to go
    clear();
    data = payload || { enabled: false, pulse: { edges: {} }, hosts: {}, colors: {}, notices: [] };
    S.group = new THREE.Group();
    S.group.name = 'odLight';
    S.group.visible = false;
    scene.add(S.group);
    placed = [];
    effects = [];
    swingEffects = [];
    drawnAt = null;
    const list = typeof odExpandSceneData === 'function' ? odExpandSceneData(items || []) : (items || []);
    const bySid = new Map(), objects = new Map();
    for (const item of list) if (item.sid && !bySid.has(item.sid)) bySid.set(item.sid, item);
    itemsBySid = bySid;
    for (const o of odContent.children) if (o.userData.odSid && !objects.has(o.userData.odSid)) objects.set(o.userData.odSid, o);
    odContent.updateMatrixWorld(true);
    const guideRoute = list.find((item) => item.type === 'route' && item.chip && !item.cable && item.kind !== 'electrical');
    const guideWidth = guideRoute ? Math.max(guideRoute.width || 0.5, 0.2) : 0.5;

    // every opaque mesh of the view, with its box: a part over or beside a guide must hide the light
    const pool = [];
    odContent.traverse((o) => {
      if (o.isMesh && ![].concat(o.material).some((m) => !m || m.transparent)) pool.push({ mesh: o, box: new THREE.Box3().setFromObject(o) });
    });
    const edges = Object.entries((data.pulse && data.pulse.edges) || {});
    const packets = edges.flatMap(([, edge]) => edge.packets || []);
    let t0 = Infinity, t1 = -Infinity, strongest = 1.0;
    for (const p of packets) { t0 = Math.min(t0, p.t0); t1 = Math.max(t1, p.t1); strongest = Math.max(strongest, power(p)); }
    // brightness is relative to the power the sources put in (an old payload without it: the strongest packet)
    const reference = data.source_power > 0 ? data.source_power : strongest;
    referencePower = reference;
    const secondsPerPs = data.seconds_per_ps > 0 ? data.seconds_per_ps : 0;   // the time scale of the caption
    psPerSecond = secondsPerPs > 0 ? 1 / secondsPerPs : 1;
    spanS = packets.length ? (t1 - t0) * secondsPerPs : 0;
    periodS = (data.train_period_ps || 0) * secondsPerPs;
    if (!S.built) S.look = data.look === 'field' ? 'field' : 'light';      // later builds keep the look picked since
    REF.value = Math.sqrt(reference);
    for (const notice of data.notices || []) console.warn('optodraw light: ' + notice);

    // every edge of the pulse and of the steady state, each placed once: both looks draw on the same placement
    const cw = data.cw || {}, cwEdges = cw.edges || {}, pulseEdges = (data.pulse && data.pulse.edges) || {};
    const hidden = new Set(data.hidden || []);               // transfers a coupling section's rails draw
    const outlines = new Map(), seen = new Set();            // each part's multimode regions (payload outlines)
    for (const region of cw.regions || []) {
      if (seen.has(region.host + ':' + region.region)) continue;
      seen.add(region.host + ':' + region.region);
      outlines.set(region.host, (outlines.get(region.host) || []).concat([region.outline]));
    }
    // the edges only a drive's swing lights (the tour's drive tables): placed too, dark until a sample lights them;
    // a part's own transfer among them is not when the part's rails draw its light (its rails then carry the swing)
    const swung = {}, railHosts = new Set([...(data.rails || []), ...(cw.rails || [])].map((r) => r.host));
    for (const table of data.drives || []) Object.assign(swung, table.edges || {});
    for (const id of [...new Set([...Object.keys(pulseEdges), ...Object.keys(cwEdges), ...Object.keys(swung)])]) {
      if (hidden.has(id)) continue;
      const edge = pulseEdges[id] || cwEdges[id] || swung[id];
      const host = (data.hosts || {})[id];
      if (!pulseEdges[id] && !cwEdges[id] && host && host.kind === 'part' && railHosts.has(host.sid)) continue;
      const item = host ? bySid.get(host.sid) : null, obj = host ? objects.get(host.sid) : null;
      const profile = host && host.kind === 'part' ? (data.profiles || {})[id] : null;
      let rec = null;
      if (host && host.kind === 'route') rec = placeRoute(edge, obj);
      else if (host && host.kind === 'beam') rec = placeBeam(edge, host, item, obj);
      else if (host) rec = placePart(profile ? profile.points : edge.points, profile ? [profile.share] : null, item, obj, guideWidth,
                                     outlines.get(host.sid));
      if (!rec || rec.pts.length < 2) { placed.push({ id, missing: host ? 'no drawn host' : 'no host' }); continue; }
      rec.id = id;
      if (rec.kind === 'guide') rec.gaps = coverGaps(rec, pool);
      // a link carries light both ways: a packet leaving the far end runs back along the points
      const back = host.kind === 'route' ? (item && item.ends ? item.ends[1] : null) : null;
      const backSid = host.kind === 'beam' && item && item.anchorSids ? item.anchorSids[(host.segment || 0) + 1] : null;
      Object.assign(rec, { back, backSid, raw: edge.packets || [] });
      rec.packets = rec.raw.filter((p) => p.t1 > p.t0).map((p) => ({
        t0: p.t0, t1: p.t1, width: p.width, share: power(p) / reference, colour: colourOf(p.wavelength_nm),
        forward: !(p.from === back || (backSid && p.from.split(':')[1] === backSid)), weight: rec.weight,
      }));
      glowMesh(rec);
      if (cwEdges[id]) edgeField(rec, id, cwEdges[id].cw || []);
      placed.push(rec);
    }
    // each rail of a coupling section: one light, a packet per engine bucket with the power at each point
    for (const rail of data.rails || []) {
      const id = 'rail:' + rail.host + ':' + rail.section + ':' + rail.rail;
      const rec = placePart(rail.points, [null, ...rail.packets.map((p) => p.power)], bySid.get(rail.host),
                            objects.get(rail.host), guideWidth, outlines.get(rail.host));
      if (!rec || rec.pts.length < 2) { placed.push({ id, missing: 'no drawn host' }); continue; }
      rec.id = id;
      if (rec.kind === 'guide') rec.gaps = coverGaps(rec, pool);
      rec.packets = rail.packets.map((p, k) => ({
        t0: p.t0, t1: p.t1, width: p.width, share: 1 / reference, colour: colourOf(p.wavelength_nm), forward: true,
        weight: rec.weights[k], index: k,
      })).filter((p) => p.t1 > p.t0);
      rec.points = rail.points;
      glowMesh(rec);
      placed.push(rec);
    }
    // the rails only a drive's swing draws (the driven part's rails in the tour's drive tables), dark until then
    const placedIds = new Set(placed.map((rec) => rec.id));
    for (const table of data.drives || []) {
      for (const sample of [...(table.rails || []), ...(table.cw_rails || [])]) {
        for (const [id, rail] of Object.entries(sample)) {
          if (!rail.points || placedIds.has(id)) continue;
          placedIds.add(id);
          const sid = id.split(':')[1];
          const rec = placePart(rail.points, null, bySid.get(sid), objects.get(sid), guideWidth, outlines.get(sid));
          if (!rec || rec.pts.length < 2) { placed.push({ id, missing: 'no drawn host' }); continue; }
          Object.assign(rec, { id, points: rail.points, packets: [] });
          if (rec.kind === 'guide') rec.gaps = coverGaps(rec, pool);
          glowMesh(rec);
          placed.push(rec);
        }
      }
    }
    // the steady state's rails: on the pulse drawing's rail (the same points), or placed here
    const byId = new Map(placed.filter((rec) => rec.pts).map((rec) => [rec.id, rec]));
    for (const rail of cw.rails || []) {
      const id = 'rail:' + rail.host + ':' + rail.section + ':' + rail.rail;
      let rec = byId.get(id);
      if (!rec && rail.points) {
        rec = placePart(rail.points, null, bySid.get(rail.host), objects.get(rail.host), guideWidth, outlines.get(rail.host));
        if (!rec || rec.pts.length < 2) { placed.push({ id, missing: 'no drawn host' }); continue; }
        rec.id = id;
        rec.points = rail.points;
        if (rec.kind === 'guide') rec.gaps = coverGaps(rec, pool);
        rec.packets = [];
        glowMesh(rec);
        placed.push(rec);
      }
      if (rec) railField(rec, rail, rail.points || rec.points);
    }
    // the multimode regions: one field grid per region and wavelength
    for (const region of cw.regions || []) {
      const id = 'region:' + region.host + ':' + region.region + ':' + region.wavelength_nm;
      const rec = placeRegion(region, bySid.get(region.host), objects.get(region.host), pool);
      if (!rec) { placed.push({ id, missing: 'no drawn host' }); continue; }
      rec.id = id;
      placed.push(rec);
    }
    // the heat of each driven heater and the RF between each driven modulator's electrodes, under the field's ribbons
    const hottest = data.heat_scale_k > 0 ? data.heat_scale_k : 1e-9;               // the scene's colour scales (payload)
    const strongest_field = data.rf_scale_v_per_um > 0 ? data.rf_scale_v_per_um : 1e-12;
    for (const h of data.heat || []) {
      const obj = objects.get(h.sid.split(':')[0]), effect = obj ? heatField(h, obj, hottest) : null;
      if (effect) effects.push(effect);
    }
    for (const r of data.rf || []) {
      const obj = objects.get(r.sid), effect = obj ? rfField(r, obj, strongest_field) : null;
      if (effect) effects.push(effect);
    }
    // each drive table's maps at the top of its swing: hidden until its stop draws a sample's value on them
    for (const table of data.drives || []) {
      (table.heat_maps || []).forEach((h, k) => {
        const obj = objects.get(h.sid.split(':')[0]), effect = obj ? heatField(h, obj, hottest) : null;
        if (effect) swingEffects.push(Object.assign(effect, { table, k, scale: hottest, on: false }));
      });
      (table.rf_maps || []).forEach((r, k) => {
        const obj = objects.get(r.sid), effect = obj ? rfField(r, obj, strongest_field) : null;
        if (effect) swingEffects.push(Object.assign(effect, { table, k, gap: r.gap_um, on: false }));
      });
    }
    for (const rec of placed) if (rec.pts) rec.basePackets = rec.packets;
    recById = new Map(placed.filter((rec) => rec.pts).map((rec) => [rec.id, rec]));
    alignJoints();
    applyLook();
    const toggle = document.getElementById('anim-toggle');
    if (toggle) {
      if (toggle.dataset.odTitle === undefined) toggle.dataset.odTitle = toggle.title;
      toggle.disabled = !data.enabled;
      toggle.title = data.enabled ? toggle.dataset.odTitle : (data.notices || []).join('. ') || 'No light';
    }
    S.enabled = S.enabled && (!!data.enabled || !!pending);
    S.playing = S.playing && S.enabled;
    setWorld(S.enabled);
    S.built = true;
    syncTour();
    drawCaptions();
  }

  // --- drawing: each packet a Gaussian streak along its edge, every train period again ------------------------
  // a packet adds its power along the edge: brightness exp(-u^2 / 2) at its share of the input, so power exp(-u^2),
  // times the edge's profile share at each sample (the payload's power there over the edge's end power)
  function splat(rec, centre, sigma, share, colour, weight) {
    const lo = Math.max(centre - 3 * sigma, 0), hi = Math.min(centre + 3 * sigma, rec.length);
    if (lo > hi) return;
    let a = 0, b = rec.cum.length;
    while (a < b) { const m = (a + b) >> 1; if (rec.cum[m] < lo) a = m + 1; else b = m; }
    // the last sample is the next edge's first: there the next edge draws the pulse, so a joint counts it once
    for (let i = a; i < rec.cum.length - 1 && rec.cum[i] <= hi; i++) {
      const u = (rec.cum[i] - centre) / sigma, w = share * (weight ? weight[i] : 1) * Math.exp(-u * u);
      rec.power[i] += w;
      rec.mix[3 * i] += w * colour.r; rec.mix[3 * i + 1] += w * colour.g; rec.mix[3 * i + 2] += w * colour.b;
    }
  }
  function draw() {
    const T = S.t * psPerSecond, period = periodS * psPerSecond;          // physics time and train period, ps
    // at a driven stop each pulse is drawn at the drive level it met at the part; n counts pulses from the time as
    // asked (setTime wraps the drawn time by whole train periods)
    const swung = S.tour && S.tour.swing, table = swung ? swung.table : null;
    const shift = swung && periodS > 0 ? Math.round((S.raw - S.t) / periodS) : 0;
    for (const rec of placed) {
      if (!rec.glow) continue;
      rec.power.fill(0);
      rec.mix.fill(0);
      const levels = swung && rec.levelPackets ? rec.levelPackets : null;
      const lists = levels ? [[rec.basePackets, -1]].concat(Array.from(levels, (list, level) => [list, level]))
                           : [[rec.packets, null]];
      for (const [list, level] of lists) {
        if (!list) continue;
        // the drawn points cover the packet's whole travel, from t0 at the first point to t1 at the last
        for (const p of list) {
          const pad = 1.5 * p.width, duration = p.t1 - p.t0;
          const first = period > 0 ? Math.max(0, Math.ceil((T - p.t1 - pad) / period)) : 0;
          const lastRun = period > 0 ? Math.floor((T - p.t0 + pad) / period) : 0;
          for (let n = first; n <= lastRun; n++) {
            if (level !== null) {
              const met = levelOf(table, n + shift);
              if ((met >= 0 && levels[met] ? met : -1) !== level) continue;
            }
            const tau = T - n * period;
            if (tau < p.t0 - pad || tau > p.t1 + pad) continue;
            const along = (tau - p.t0) / duration;
            const centre = (p.forward ? along : 1 - along) * rec.length;
            const sigma = (p.width * rec.length / duration) / 2.3548;          // the packet width in the time scale
            splat(rec, centre, sigma, p.share, p.colour, p.weight);
          }
        }
      }
    }
    // packets of one edge that overlap add their power: the brightness is the root of the sum, in the mixed colour.
    // The last sample is the next edge's first, which draws it: it takes the sample before it, so the ribbon runs
    // on to the joint at that brightness and the joint neither dips nor is drawn twice.
    for (const rec of placed) {
      if (!rec.glow) continue;
      let lit = false;
      const n = rec.power.length;
      for (let i = 0; i < n; i++) {
        const k = i === n - 1 && n > 1 ? n - 2 : i, w = rec.power[k], f = w > 0 ? 1 / Math.sqrt(w) : 0;
        if (w > 0) lit = true;
        for (let c = 0; c < 6; c++) rec.glow[6 * i + c] = rec.mix[3 * k + (c % 3)] * f;
      }
      if (lit || rec.lit) rec.attr.needsUpdate = true;
      rec.lit = lit;
    }
  }

  function setTime(seconds) {
    let t = Number(seconds);
    if (!Number.isFinite(t) || t < 0) t = 0;
    S.raw = t;                 // the time as asked: the field's cycle runs on it, so it never jumps at the wrap
    // after the first pass the light flows in a steady train: wrap by one train period
    if (periodS > 0 && t >= spanS + periodS) t = spanS + ((t - spanS) % periodS);
    S.t = t;
  }
  function show() {
    if (!S.group) return;
    VIEWPORT.value = renderer.domElement.height || 1;
    GAIN.value = PEAK / (renderer.toneMappingExposure || 1);
    S.group.visible = S.enabled && !(window.__odPT && window.__odPT.active);
    HEAT_TIME.value = S.raw;
    for (const effect of effects.concat(swingEffects)) if (effect.kind === 'rf') effect.mesh.material.uniforms.uTime.value = S.raw / effect.secondsPerPs;   // ps of the RF wave
    if (S.look === 'field') {
      FIELD_TIME.value = S.t * psPerSecond;
      const cycle = data && data.cw && data.cw.cycle_s > 0 ? data.cw.cycle_s : 1;
      FIELD_OMEGA.value = 2 * Math.PI * ((S.raw / cycle) % 1);
    } else if (S.group.visible && drawnAt !== S.raw) {
      // drawn again when the time as asked moves: at a driven stop two times a whole train period apart show
      // different drive levels, though the wrapped time is the same
      draw();
      drawnAt = S.raw;
    }
  }
  let _scrub, tickCount = 0;
  function syncScrub() {
    if (_scrub === undefined) _scrub = document.getElementById('anim-scrub');
    const loop = spanS + periodS;
    if (_scrub && !scrubbing && loop > 0) _scrub.value = Math.round((S.t / loop) * 1000);
  }
  function syncPlay() {
    const play = document.getElementById('anim-play');
    if (play) { play.textContent = S.playing ? 'Pause' : 'Play'; play.classList.toggle('active', S.playing); }
  }
  function tick() {
    if (!S.group) return;
    const now = performance.now() / 1000, dt = Math.min(now - last, 0.1);
    last = now;
    if (S.tour) {
      // the tour's own clock; held by frameAt, and drawn again each frame so the controls never move its camera
      if (S.tour.playing) advanceTour(dt * S.speed);
      else applyTour(S.tour.t);
    } else if (S.enabled && S.playing && !scrubbing) setTime(S.raw + dt * S.speed);
    show();
    syncScrub();
    if ((tickCount = (tickCount + 1) % 30) === 0) placeCaptions();
  }
  // free play and video: the light at a set time, one frame drawn. While the tour is on, seconds are the tour's
  // video time: the camera, the light's time, the device in focus and its drive all follow from it (the tour's clock
  // then holds, so the next frames draw the same time)
  function frameAt(seconds) {
    if (S.tour) {
      S.tour.playing = false;
      const v = Number(seconds);
      applyTour(Number.isFinite(v) && v > 0 ? v : 0);
    } else setTime(seconds);
    show();
    if (typeof odRenderFrame === 'function') odRenderFrame();
  }
  // the world: deep navy while the light plays, the user's own world back when it stops. A world the user picks
  // meanwhile (the View menu) stays.
  let before = null, owned = false;      // owned: the light has taken the world and not yet given it back
  function setWorld(on) {
    if (typeof applyWorld !== 'function') return;
    if (on) {
      if (owned || _world === 'none') return;
      before = _world; owned = true; applyWorld('night');
    } else if (owned) {
      if (_world === 'night') applyWorld(before);
      before = null; owned = false;
    }
  }
  function setEnabled(on) {
    S.enabled = !!on && !!(data && data.enabled);
    S.playing = S.enabled;
    setWorld(S.enabled);
    syncPlay();
    drawCaptions();
  }
  function control(action, value) {
    if (action === 'enabled') setEnabled(value);
    else if (action === 'play') { S.playing = !!value && S.enabled; syncPlay(); }
    else if (action === 'speed') { const v = Number(value); if (Number.isFinite(v) && v > 0) S.speed = v; }
    else if (action === 'time') { const v = Number(value); if (Number.isFinite(v)) setTime((Math.max(0, Math.min(1000, v)) / 1000) * (spanS + periodS)); }
    else if (action === 'look') { if (value === 'light' || value === 'field') { S.look = value; applyLook(); } }
    else if (action === 'tour') { if (value === false) stopTour(false); else startTour(); }
    // 'record' comes with the video; other actions are not the player's
  }

  // --- the tour: the camera follows the light from device to device ------------------------------------------------
  // The payload carries the tour (its stops, in the order the light arrives), its time warp (video seconds to physics
  // ps, from the engine's arrivals: slow at each stop, faster between) and the name each stop shows. The tour has its
  // own clock, in video seconds: wide on the whole circuit, then each stop held while the camera rests on its device,
  // the camera easing from one to the next, and wide again at the end. While the camera rests on a device its label
  // shows (one label at a time), metal and solid blocks over its guides turn see-through, and a driven device swings
  // its drive: the payload's drive table, one sample at a time, each drawn with its own numbers. frameAt(seconds)
  // draws the tour at that time while it is on.
  const GLASS = 0.3;              // the most opacity a part over the light keeps while its device is in focus
  const MARGIN = 1.25;            // a stop frames its device's bounding sphere with this margin
  const STOP_ELEVATION = 50;      // degrees: the camera looks down at least this steeply at a stop
  const WIDE_FILL = 0.9;          // a wide view frames the circuit (its parts, not the die) to this share of the frame
  const RETURN_S = 1.0;           // at the end of a live tour the camera eases back to the view from before over this
  const KEPT_CAPTION = 'Drives stay as set in this page';

  function anchorOf(sid) { return odContent.children.find((o) => o.userData.odSid === sid) || null; }
  // the plan of the tour: per stop its device, its times, the camera's pose there and its drive table
  function poseOf(pos, target) {
    const offset = pos.clone().sub(target);
    return { target: target.clone(), dir: offset.clone().normalize(), dist: Math.max(offset.length(), 1e-6) };
  }
  // the wide view: the circuit as it is now (the union of its parts' boxes, without the die) from the home view's side
  function widePose() {
    const home = window.__odHome || { pos: camera.position.clone(), target: controls.target.clone() };
    const box = new THREE.Box3(), corners = [];
    for (const child of odContent.children) {
      if (!child.visible) continue;
      const b = new THREE.Box3().setFromObject(child);
      if (b.isEmpty()) continue;
      box.union(b);
      if (typeof odBoxCorners === 'function') odBoxCorners(b, corners);
    }
    if (box.isEmpty() || typeof odPoseForBox !== 'function') return poseOf(home.pos, home.target);
    const fit = odPoseForBox(box, corners, home.pos.clone().sub(home.target), WIDE_FILL);
    return poseOf(fit.pos, fit.target);
  }
  function tourPlan() {
    const warp = data.tour_warp || [], names = data.tour_names || {};
    let stops = (data.tour && data.tour.stops) || [];
    if (stops.length && warp.length !== 2 * stops.length + 2) {          // no time scale: the wide views only
      console.warn('optodraw light: the tour has no time for its stops; it shows the wide views only');
      stops = [];
    }
    const tables = new Map((data.drives || []).map((t) => [t.param + '@' + t.sid, t]));
    const plan = stops.map((stop, j) => {
      const anchor = anchorOf(stop.sid), box = anchor ? new THREE.Box3().setFromObject(anchor) : null;
      const item = itemsBySid.get(stop.sid), guides = anchor && item && item.guide ? meshesOf(anchor, item.guide) : [];
      const guideBox = new THREE.Box3();
      for (const g of guides) guideBox.expandByObject(g);
      return { sid: stop.sid, name: names[stop.sid] || stop.sid, arrive: warp[1 + 2 * j][0], leave: warp[2 + 2 * j][0],
               anchor, box, guides, guideTop: guideBox.isEmpty() ? null : guideBox.max.y, drive: stop.drive,
               table: stop.drive ? tables.get(stop.drive + '@' + stop.sid) || null : null };
    });
    return posesFor({ warp, stops: plan, end: warp.length ? warp[warp.length - 1][0] : 0 });
  }
  // the camera's poses for the view's shape now: the wide view, and each stop framed from its device's box, then
  // brought closer where needed so that the view's ground at a driven stop stays inside its table's frame
  function posesFor(plan) {
    const wide = widePose();
    const dir = wide.dir.clone(), least = THREE.MathUtils.degToRad(STOP_ELEVATION);
    if (Math.asin(Math.min(1, dir.y)) < least) {            // the home view's side, looking down more steeply
      const flat = Math.hypot(dir.x, dir.z) || 1;
      dir.set((dir.x / flat) * Math.cos(least), Math.sin(least), (dir.z / flat) * Math.cos(least));
    }
    for (const stop of plan.stops) {
      const box = stop.box;
      stop.pose = box && !box.isEmpty() ? { target: box.getCenter(new THREE.Vector3()), dir, dist: odFitDistance(box, MARGIN) } : wide;
      if (box && !box.isEmpty() && stop.table && stop.table.frame) stop.pose = insideFrame(stop.pose, stop.table.frame, box.min.y);
    }
    return Object.assign(plan, { wide, aspect: camera.aspect });
  }
  // a pose brought closer (same target and direction) until the view's ground footprint, on the plane at height y0
  // (the device's lowest point: its light lies above it), is inside the frame's disc (Ruling 47: the drive table keeps
  // only what that disc holds). A corner ray of the view meets the plane at A + d B (in plan), d the distance; each
  // corner allows d up to the root of |A + d B - centre| = radius.
  function insideFrame(pose, frame, y0) {
    const [cx, cy, radius] = frame, limit = 0.98 * radius, target = pose.target, dir = pose.dir;
    const basis = new THREE.Matrix4().lookAt(dir, new THREE.Vector3(), camera.up);
    const r = new THREE.Vector3().setFromMatrixColumn(basis, 0), u = new THREE.Vector3().setFromMatrixColumn(basis, 1);
    const f = dir.clone().negate(), tV = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2), tH = tV * camera.aspect;
    let dist = pose.dist;
    for (const sx of [-1, 1]) {
      for (const sy of [-1, 1]) {
        const ray = f.clone().addScaledVector(r, sx * tH).addScaledVector(u, sy * tV);
        if (ray.y > -1e-9) { dist = 0; continue; }                  // this corner sees the horizon: no distance holds it
        const a = target.clone().addScaledVector(ray, (y0 - target.y) / ray.y), b = dir.clone().addScaledVector(ray, -dir.y / ray.y);
        const ax = a.x - cx, az = -a.z - cy, bx = b.x, bz = -b.z;          // plan (x, y) = three (x, -z)
        const qa = bx * bx + bz * bz, qb = 2 * (ax * bx + az * bz), qc = ax * ax + az * az - limit * limit;
        const root = qb * qb - 4 * qa * qc;
        dist = Math.min(dist, qc > 0 || root < 0 || qa <= 0 ? 0 : (-qb + Math.sqrt(root)) / (2 * qa));
      }
    }
    return { ...pose, dist: Math.max(dist, 1e-3 * pose.dist) };
  }
  // physics ps at video time v: linear between the warp's knots (past the last knot, at its last rate)
  function warpAt(warp, v) {
    if (warp.length < 2) return warp.length ? warp[0][1] : 0;
    let k = 1;
    while (k < warp.length - 1 && warp[k][0] < v) k++;
    const [v0, p0] = warp[k - 1], [v1, p1] = warp[k];
    return p0 + ((p1 - p0) * (v - v0)) / Math.max(v1 - v0, 1e-12);
  }
  // the camera between two poses: the target on a straight line, the direction on a great circle, the distance in
  // equal ratios, all on one curve that eases in and out (zero speed and acceleration at both ends)
  function between(a, b, u) {
    const s = u * u * u * (u * (u * 6 - 15) + 10);
    const turn = new THREE.Quaternion().slerp(new THREE.Quaternion().setFromUnitVectors(a.dir, b.dir), s);
    return { target: a.target.clone().lerp(b.target, s), dir: a.dir.clone().applyQuaternion(turn),
             dist: a.dist * Math.pow(b.dist / a.dist, s) };
  }
  // the camera's pose at video time v: wide for the first half of the first wide view, then to the first stop; at
  // rest during each hold; from stop to stop over each move; back to wide over the first half of the last wide view
  function poseAt(plan, v) {
    const { stops, wide, end } = plan, n = stops.length;
    if (!n) return wide;
    const start = 0.5 * stops[0].arrive;
    if (v <= start) return wide;
    if (v < stops[0].arrive) return between(wide, stops[0].pose, (v - start) / (stops[0].arrive - start));
    for (let j = 0; j < n; j++) {
      const stop = stops[j], next = stops[j + 1];
      if (v <= stop.leave) return stop.pose;
      if (next && v < next.arrive) return between(stop.pose, next.pose, (v - stop.leave) / (next.arrive - stop.leave));
    }
    const last = stops[n - 1], back = 0.5 * (end - last.leave);
    return v < last.leave + back ? between(last.pose, wide, (v - last.leave) / back) : wide;
  }
  function setCamera(pose) {
    camera.position.copy(pose.target).addScaledVector(pose.dir, pose.dist);
    camera.lookAt(pose.target);
    controls.target.copy(pose.target);
    camera.updateMatrixWorld();
  }
  // the tour at video time v: the light's time from the warp, the camera, the device in focus and its drive
  function applyTour(v) {
    const tour = S.tour, plan = tour.plan;
    if (plan.aspect !== camera.aspect) posesFor(plan);              // the view changed shape: frame again
    tour.t = v;
    setTime(warpAt(plan.warp, v) / psPerSecond);
    setCamera(poseAt(plan, v));
    const j = plan.stops.findIndex((stop) => v >= stop.arrive && v <= stop.leave);
    focusOn(j);
    swing(j >= 0 ? plan.stops[j] : null, v);
  }
  // the device in focus: its label (the page's own, or one made like it when labels are off) and see-through parts
  function focusOn(j) {
    const tour = S.tour;
    if (tour.focus === j) return;
    unfocus();
    tour.focus = j;
    const stop = j >= 0 ? tour.plan.stops[j] : null;
    if (stop && stop.anchor) {
      tour.glass = glassOver(stop);
      tour.label = labelOf(stop);
    }
    drawCaptions();
  }
  function unfocus() {
    const tour = S.tour;
    for (const g of tour.glass) {
      g.mesh.material = g.material;
      for (const m of g.clones) m.dispose();
    }
    tour.glass = [];
    if (tour.label) {
      if (tour.label.made) tour.label.object.removeFromParent();
      else tour.label.object.visible = false;
    }
    tour.label = null;
  }
  // the opaque meshes inside the device's box that rise above its guides (metal, heaters, pads, solid blocks): each
  // takes a copy of its material at most GLASS opaque, which writes no depth, so the light under it shows
  function glassOver(stop) {
    if (stop.guideTop === null || !stop.box) return [];
    const box = stop.box, out = [], eps = 1e-6;
    odContent.traverse((o) => {
      if (!o.isMesh || stop.guides.includes(o)) return;
      const list = [].concat(o.material);
      if (list.some((m) => !m || m.transparent)) return;
      const b = new THREE.Box3().setFromObject(o);
      if (b.isEmpty() || b.max.y <= stop.guideTop + eps) return;
      if (b.min.x < box.min.x - eps || b.max.x > box.max.x + eps || b.min.z < box.min.z - eps || b.max.z > box.max.z + eps) return;
      const clones = list.map((m) => {
        const c = m.clone();
        Object.assign(c, { transparent: true, opacity: Math.min(m.opacity, GLASS), depthWrite: false });
        c.userData = { ...m.userData, odTourGlass: true };
        return c;
      });
      out.push({ mesh: o, material: o.material, clones });
      o.material = Array.isArray(o.material) ? clones : clones[0];
    });
    return out;
  }
  function labelOf(stop) {
    let object = null, made = false;
    stop.anchor.traverse((o) => { if (!object && o.isCSS2DObject) object = o; });
    if (!object && typeof addLabel === 'function') {
      addLabel(stop.anchor, stop.name);
      object = stop.anchor.children[stop.anchor.children.length - 1];
      made = true;
    }
    if (!object || !object.isCSS2DObject) return null;
    object.visible = true;
    return { object, made };
  }
  // the drive at a driven stop (Ruling 46): it steps once per train period, one level per pulse that crosses the
  // part during the hold (the table's passes and levels), so each packet meets one drive level. The Light look draws
  // each pulse at the level it met (draw: levelOf); the Field look and the maps show the level of the latest pulse to
  // reach the part. Only the table's numbers are drawn, no value between levels.
  function swing(stop, v) {
    const tour = S.tour, table = stop ? stop.table : null;
    if (!table || !table.passes) { if (tour.swing) setSwing(null); return; }
    if (!tour.swing || tour.swing.table !== table) setSwing(table);
    const period = data.train_period_ps || 0, ps = S.raw * psPerSecond;
    const pulse = period > 0 ? Math.floor((ps - table.first_ps) / period + 1e-9) : -1;
    const level = levelOf(table, pulse);
    if (tour.swing.level !== level) setLevel(level);
  }
  // the level pulse n met at the part (an index into the table's values), or -1 (the drive as set)
  function levelOf(table, n) {
    const i = n - table.passes[0];
    return i >= 0 && i < table.passes.length ? table.levels[i] : -1;
  }
  // the Light look's packets of every level, per edge or rail the table changes (drawn per pulse by draw)
  function setSwing(table) {
    const tour = S.tour;
    if (tour.swing) {
      setLevel(-1);
      for (const rec of tour.swing.recs) rec.levelPackets = null;
    }
    tour.swing = null;
    drawnAt = null;
    if (!table) return;
    const recs = new Set();
    table.values.forEach((_, level) => {
      for (const [id, found] of Object.entries((table.pulse || [])[level] || {})) {
        const rec = recById.get(id);
        if (!rec || !rec.glow) continue;
        (rec.levelPackets = rec.levelPackets || [])[level] = edgePackets(rec, found);
        recs.add(rec);
      }
      for (const [id, found] of Object.entries((table.rails || [])[level] || {})) {
        const rec = recById.get(id);
        if (!rec || !rec.glow) continue;
        // a rail that is the base rail times a factor per packet carries only the factors
        (rec.levelPackets = rec.levelPackets || [])[level] = found.scales
          ? rec.basePackets.map((p) => ({ ...p, share: p.share * found.scales[p.index] })).concat(railPackets(rec, found.extra || []))
          : railPackets(rec, found.packets);
        recs.add(rec);
      }
    });
    tour.swing = { table, recs, level: -1, fieldRecs: new Set() };
  }
  // the Field look and the maps at one level (-1: the drive as set): its changed CW records, rail fields and profiles,
  // and the driven part's maps at that level's value; the part's base maps rest meanwhile
  function setLevel(level) {
    const swingNow = S.tour.swing, table = swingNow.table;
    for (const rec of swingNow.fieldRecs) for (const layer of rec.layers || []) restoreLayer(layer);
    swingNow.fieldRecs = new Set();
    swingNow.level = level;
    for (const effect of effects) effect.held = false;
    for (const effect of swingEffects) effect.on = false;
    if (level >= 0) {
      for (const effect of swingEffects) {
        if (effect.table !== table) continue;
        const value = ((effect.kind === 'heat' ? table.heat : table.rf)[level] || [])[effect.k] || 0;
        const uniforms = effect.mesh.material.uniforms;
        if (effect.kind === 'heat') uniforms.uPeak.value = value / effect.scale;
        else uniforms.uField.value = value / effect.gap;
        effect.on = value !== 0;
        for (const other of effects) if (other.kind === effect.kind && other.sid === effect.sid) other.held = true;
      }
      const at = (list) => (list && list[level]) || {}, profiles = at(table.profiles);
      for (const [id, records] of Object.entries(at(table.cw))) {
        const rec = recById.get(id);
        if (!rec || !rec.geometry) continue;
        edgeSample(rec, id, records, id in profiles ? profiles[id] : ((data.cw || {}).profiles || {})[id]);
        swingNow.fieldRecs.add(rec);
      }
      for (const [id, found] of Object.entries(at(table.cw_rails))) {
        const rec = recById.get(id);
        if (!rec || !rec.geometry) continue;
        if (found.factors) railFactors(rec, id, found.factors); else railSample(rec, id, found);
        swingNow.fieldRecs.add(rec);
      }
    }
    showEffects();
  }
  // a changed edge's packets as the build draws them; the width is the base packet's of the same source and colour
  function edgePackets(rec, found) {
    const out = [];
    for (let k = 0; k < found.power.length; k++) {
      const from = found.from[k], nm = found.wavelength_nm[k], t0 = found.t0[k], t1 = found.t1[k];
      if (!(t1 > t0)) continue;
      const like = rec.raw ? rec.raw.find((p) => p.from === from && p.wavelength_nm === nm) : null;
      out.push({ t0, t1, width: like ? like.width : data.pulse_ps, share: found.power[k] / referencePower, colour: colourOf(nm),
                 forward: !(from === rec.back || (rec.backSid && from.split(':')[1] === rec.backSid)), weight: rec.weight });
    }
    return out;
  }
  function railPackets(rec, packets) {
    return packets.filter((p) => p.t1 > p.t0).map((p) => ({
      t0: p.t0, t1: p.t1, width: p.width, share: 1 / referencePower, colour: colourOf(p.wavelength_nm), forward: true,
      weight: rec.map ? valuesAt(rec.map, p.power) : null }));
  }
  // a layer for light the base state does not draw here: dark when the sample goes
  function newLayer(rec, nm, key) {
    const n = rec.pts.length, zero = new Float32Array(n);
    const layer = fieldLayer(rec, zero, zero, zero, 1e-6, nm, key);
    layer.base = { field: layer.attr.array.slice(), amp: zero, arrive: zero, fade: layer.fade };
    return layer;
  }
  function edgeSample(rec, id, records, profiles) {
    const used = new Set();
    for (const r of records) {
      const key = recordKey(r);
      let layer = (rec.layers || []).find((l) => l.key === key);
      const { amp, phase } = edgeArrays(rec, id, r, profiles);
      if (!layer) layer = newLayer(rec, r.wavelength_nm, key);
      setLayer(layer, amp, phase, null, null);
      used.add(layer);
    }
    for (const layer of rec.layers || []) if (!used.has(layer)) setLayer(layer, new Float32Array(rec.pts.length), null, null, null);
  }
  // a rail whose fields are the base fields times a complex factor each: amplitude times |c|, phase plus arg c
  function railFactors(rec, id, factors) {
    const base = ((data.cw && data.cw.rails) || []).find((r) => 'rail:' + r.host + ':' + r.section + ':' + r.rail === id);
    (base ? base.fields : []).forEach((entry, k) => {
      const layer = (rec.layers || []).find((l) => l.key === 'rail@' + entry.wavelength_nm), c = factors[k];
      if (!layer || !c) return;
      const size = Math.hypot(c[0], c[1]), turn = Math.atan2(c[1], c[0]), field = layer.attr.array, n = field.length / 6;
      const amp = new Float32Array(n), phase = new Float32Array(n);
      for (let i = 0; i < n; i++) { amp[i] = layer.amp[i] * size; phase[i] = field[6 * i + 1] + turn; }
      setLayer(layer, amp, phase, null, null);
    });
  }
  function railSample(rec, id, found) {
    const base = ((data.cw && data.cw.rails) || []).find((r) => 'rail:' + r.host + ':' + r.section + ':' + r.rail === id);
    const rail = { t: found.t, arcs: (base || found).arcs }, points = (base && base.points) || rec.points || found.points;
    const used = new Set();
    for (const entry of found.fields) {
      const key = 'rail@' + entry.wavelength_nm;
      const layer = (rec.layers || []).find((l) => l.key === key) || newLayer(rec, entry.wavelength_nm, key);
      const { amp, phase, arrive } = railArrays(rec, rail, points, entry);
      setLayer(layer, amp, phase, arrive, entry.fade_ps);
      used.add(layer);
    }
    for (const layer of rec.layers || []) if (!used.has(layer)) setLayer(layer, new Float32Array(rec.pts.length), null, null, null);
  }
  function startTour() {
    if (!data || !data.enabled || (data.tour_warp || []).length < 2) return;
    if (S.tour) stopTour(false);
    const saved = { enabled: S.enabled, playing: S.playing, raw: S.raw, pos: camera.position.clone(), target: controls.target.clone() };
    setEnabled(true);                                     // the light on and the world navy (setWorld)
    const labels = [];                                    // every label hides; the device in focus shows its own
    odContent.traverse((o) => { if (o.isCSS2DObject) { labels.push([o, o.visible]); o.visible = false; } });
    if (typeof odForceLabels === 'function') odForceLabels(true);
    S.tour = { t: 0, playing: true, saved, labels, plan: tourPlan(), focus: -1, glass: [], label: null, swing: null,
               back: null };
    applyTour(0);
    syncTour();
    drawCaptions();
    window.dispatchEvent(new CustomEvent('odtour', { detail: { playing: true } }));
  }
  // the tour ends: the labels, the parts and the drawn light as they were, the light and the world as they were, and
  // the camera where it was (keepCamera: where it is, when the user takes the view)
  function stopTour(keepCamera) {
    const tour = S.tour;
    if (!tour) return;
    if (S.tour.swing) setSwing(null);
    unfocus();
    for (const [o, visible] of tour.labels) o.visible = visible;
    if (typeof odForceLabels === 'function') odForceLabels(false);
    S.tour = null;
    if (!keepCamera) {
      camera.position.copy(tour.saved.pos);
      controls.target.copy(tour.saved.target);
      camera.lookAt(controls.target);
    }
    setTime(tour.saved.raw);
    if (!tour.saved.enabled) setEnabled(false);
    else { S.playing = tour.saved.playing; syncPlay(); }
    drawnAt = null;
    syncTour();
    drawCaptions();
    window.dispatchEvent(new CustomEvent('odtour', { detail: { playing: false } }));
  }
  // the live tour's clock: its video time runs at the Speed slider's rate; past the end the light flows on at the
  // last wide view's rate while the camera eases back to the view from before over RETURN_S, and then the tour stops
  function advanceTour(dt) {
    const tour = S.tour, end = tour.plan.end;
    if (tour.t + dt < end) { applyTour(tour.t + dt); return; }
    if (!tour.back) tour.back = { from: poseAt(tour.plan, end), to: poseOf(tour.saved.pos, tour.saved.target), s: 0 };
    tour.back.s += tour.t < end ? tour.t + dt - end : dt;
    applyTour(end + tour.back.s);
    if (tour.back.s >= RETURN_S) { stopTour(false); return; }
    setCamera(between(tour.back.from, tour.back.to, tour.back.s / RETURN_S));
  }
  function syncTour() {
    const button = document.getElementById('light-tour');
    if (!button) return;
    button.disabled = !(data && data.enabled && (data.tour_warp || []).length >= 2);
    button.textContent = S.tour ? 'Stop tour' : 'Play tour';
    button.classList.toggle('active', !!S.tour);
    const record = document.getElementById('light-record');
    if (record && !recording) record.disabled = button.disabled;
  }

  // --- recording: the tour in real time as a WebM -----------------------------------------------------------------
  // The tour plays on its own clock (frameAt) while a MediaRecorder saves a flat canvas. The captions are drawn onto
  // each frame, because the canvas of the view does not carry the page's text; the part labels (CSS2D) are not in it.
  // One function serves the bar's Record video button and the recording stage of render_video (no ffmpeg).
  function drawCaptionBlock(ctx, H) {
    const box = document.getElementById('od-captions');
    if (!box || box.style.display === 'none') return;
    const lines = Array.prototype.filter.call(box.children, (c) => !c.classList.contains('od-scales'))     // not the toggle
      .map((c) => c.textContent).filter(Boolean);
    if (!lines.length) return;
    ctx.font = '11px Inter, -apple-system, "Segoe UI", sans-serif';
    const width = Math.min(340, Math.max.apply(null, lines.map((l) => ctx.measureText(l).width)) + 18);
    const height = lines.length * 16 + 12, top = H - 12 - height;
    ctx.fillStyle = 'rgba(17,22,28,0.72)'; ctx.fillRect(12, top, width, height);
    ctx.fillStyle = '#f3f6fa'; ctx.textBaseline = 'top';
    lines.forEach((l, i) => ctx.fillText(l, 21, top + 7 + i * 16, width - 18));
  }
  // fps frames per second; duration in seconds (default: the whole tour). Resolves with the WebM Blob.
  function recordTour(fps, duration) {
    return new Promise((resolve, reject) => {
      const warp = (data && data.tour_warp) || [];
      if (!data || !data.enabled || warp.length < 2) { reject(new Error('the scene has no light to tour')); return; }
      if (recording) { reject(new Error('a recording is running')); return; }
      const view = document.querySelector('canvas'), W = innerWidth, H = innerHeight;
      const types = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
      const type = typeof MediaRecorder === 'undefined' ? null : types.filter((t) => MediaRecorder.isTypeSupported(t))[0];
      if (!type) { reject(new Error('this browser cannot record WebM')); return; }
      const length = Number.isFinite(Number(duration)) && Number(duration) > 0 ? Number(duration) : warp[warp.length - 1][0];
      const flat = document.createElement('canvas'); flat.width = W; flat.height = H;
      const ctx = flat.getContext('2d');
      const chunks = [];
      const recorder = new MediaRecorder(flat.captureStream(fps || 30), { mimeType: type, videoBitsPerSecond: 8000000 });
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = () => { recording = false; drawCaptions(); resolve(new Blob(chunks, { type: 'video/webm' })); };
      recorder.onerror = (e) => { recording = false; drawCaptions(); reject((e && e.error) || new Error('the recording failed')); };
      recording = true;
      drawCaptions();                // the recording carries every caption line, the folded ones too
      let start = null;
      function step(now) {
        if (start === null) start = now;
        const t = (now - start) / 1000;
        frameAt(Math.min(t, length));
        ctx.drawImage(view, 0, 0, W, H);
        drawCaptionBlock(ctx, H);
        if (t >= length) { if (recorder.state !== 'inactive') recorder.stop(); return; }
        requestAnimationFrame(step);
      }
      if (!S.tour) startTour();
      recorder.start();
      requestAnimationFrame(step);
    });
  }

  // --- checks (tests and later tasks) ---------------------------------------------------------------------------
  // how far a placed sample is outside its host: 0 inside, else the distance (scene units, um on a chip)
  const TOLERANCE = 1e-3;          // a vertical line exactly on the joint of two strip boxes can miss both
  function planGap(p, meshes, top) {
    const meets = (r) => [0, 1, 2, 3, 4, 5, 6, 7].some((k) => column(p.x + r * Math.cos((k * Math.PI) / 4),
                                                                       p.z + r * Math.sin((k * Math.PI) / 4), meshes, top));
    let r = TOLERANCE;
    while (r <= 16 && !meets(r)) r *= 2;
    if (r > 16) return Infinity;
    let lo = r / 2;
    for (let i = 0; i < 6 && r > TOLERANCE; i++) { const mid = 0.5 * (lo + r); if (meets(mid)) r = mid; else lo = mid; }
    return r;
  }
  // a free-space optic: in its drawn body. Light crosses a thin optic (an iris, a plate, a lens) on the straight line
  // between its ports, the fallback the spec keeps, and the ports may lie outside a body drawn thinner than their span:
  // along the beam the optic's aperture runs on to its ports, up to APERTURE_REACH past the body; across the beam the
  // whole offset counts. A port drawn farther from its body still reads outside.
  const APERTURE_REACH = 0.5;
  function apertureGap(rec, p, i) {
    if (!rec.box) return Infinity;
    const off = p.clone().sub(rec.box.clampPoint(p, new THREE.Vector3()));
    const a = rec.pts[Math.max(i - 1, 0)], b = rec.pts[Math.min(i + 1, rec.pts.length - 1)];
    const along = b.clone().sub(a);
    if (along.lengthSq() > 0) along.normalize();
    const ahead = off.dot(along), across = off.clone().sub(along.multiplyScalar(ahead)).length();
    return Math.hypot(across, Math.max(0, Math.abs(ahead) - APERTURE_REACH));
  }
  function gap(rec, p, i) {
    if (rec.kind === 'axis') return apertureGap(rec, p, i);
    if (rec.kind === 'tube') {                                                         // in a drawn tube
      let d = Infinity;
      for (const t of rec.tubes) {
        const q = new THREE.Line3(t.a, t.b).closestPointToPoint(p, true, new THREE.Vector3());
        d = Math.min(d, Math.max(0, q.distanceTo(p) - t.r));
      }
      return d;
    }
    if (!rec.meshes.length) return Infinity;
    const c = column(p.x, p.z, rec.meshes, rec.top)
      || (rec.bodies && rec.bodies.length && inRegion(p, rec.regions) ? column(p.x, p.z, rec.bodies, rec.bodyTop) : null);
    if (!c) return planGap(p, rec.meshes, rec.top);
    return Math.max(0, Math.abs(p.y - 0.5 * (c.top + c.bottom)) - 0.5 * (c.top - c.bottom));
  }
  function debugPlacement() {
    return placed.map((rec) => {
      if (!rec.pts) return { edge: rec.id, inside: false, worst_um: null, reason: rec.missing };
      let worst = 0;
      rec.pts.forEach((p, i) => { worst = Math.max(worst, gap(rec, p, i)); });
      return { edge: rec.id, inside: worst <= TOLERANCE, worst_um: Number.isFinite(worst) ? worst : null };
    });
  }
  // the world height of each edge's samples (tests): the lowest, the highest, and the kind of host
  function debugHeights() {
    const out = {};
    for (const rec of placed) {
      if (!rec.pts) continue;
      out[rec.id] = { kind: rec.kind, min: Math.min(...rec.pts.map((p) => p.y)), max: Math.max(...rec.pts.map((p) => p.y)) };
    }
    return out;
  }
  // the glow drawn now: per edge or rail, its brightest sample and that sample's colour
  function debugGlow() {
    const out = {};
    for (const rec of placed) {
      if (!rec.lit) continue;
      let peak = 0, at = 0;
      for (let k = 0; k < rec.glow.length; k += 6) {
        const m = Math.max(rec.glow[k], rec.glow[k + 1], rec.glow[k + 2]);
        if (m > peak) { peak = m; at = k; }
      }
      if (peak < 1e-4) continue;
      const colour = new THREE.Color(rec.glow[at] / peak, rec.glow[at + 1] / peak, rec.glow[at + 2] / peak);
      out[rec.id] = { peak, color: '#' + colour.getHexString() };
    }
    return out;
  }

  // the glow drawn now on an edge or rail at a fraction of its length (tests: the light at one place)
  function debugGlowAt(id, fraction) {
    const rec = recById.get(id);
    if (!rec || !rec.glow) return 0;
    let i = 0;
    while (i < rec.cum.length - 1 && rec.cum[i] < fraction * rec.length) i++;
    return Math.max(rec.glow[6 * i], rec.glow[6 * i + 1], rec.glow[6 * i + 2]);
  }

  // the glow drawn now at each lit edge's or rail's ends: its first sample, its last drawn sample and the joint (the
  // last vertex)
  function debugEnds() {
    const out = {}, bright = (rec, i) => Math.max(rec.glow[6 * i], rec.glow[6 * i + 1], rec.glow[6 * i + 2]);
    for (const rec of placed) {
      if (rec.lit) out[rec.id] = { first: bright(rec, 0), last: bright(rec, rec.pts.length - 2), tip: bright(rec, rec.pts.length - 1) };
    }
    return out;
  }

  // the Field look's sampled intensities now (tests): per edge or rail, the drawn amplitude times the front, squared,
  // at each sample and summed over its layers: the mean, the largest, the mean over its first and its last fifth, and
  // for the ids asked for every sample as [arc fraction, intensity]; per region, the intensity across its first and
  // its last column of samples (the input and the output plane)
  function debugField(ids) {
    const T = S.t * psPerSecond, want = new Set(ids || []), out = { edges: {}, regions: [] };
    const front = (arrive, fade) => Math.min(Math.max((T - arrive) / fade, 0), 1);
    for (const rec of placed) {
      if (!rec.pts || rec.region) continue;
      const n = rec.pts.length, intensity = new Float64Array(n);
      for (const layer of rec.layers || []) {
        for (let i = 0; i < n; i++) { const a = layer.amp[i] * front(layer.arrive[i], layer.fade); intensity[i] += a * a; }
      }
      const mean = (a, b) => { let sum = 0; for (let i = a; i < b; i++) sum += intensity[i]; return b > a ? sum / (b - a) : 0; };
      const fifth = Math.max(1, Math.floor(n / 5));
      const found = { mean: mean(0, n), max: Math.max(...intensity), head: mean(0, fifth), tail: mean(n - fifth, n) };
      if (want.has(rec.id)) { const f = fractions(rec.pts); found.samples = [...intensity].map((v, i) => [f[i], v]); }
      out.edges[rec.id] = found;
    }
    for (const rec of placed) {
      if (!rec.region) continue;
      const { scale, t, fade_ps: fade, size: [nu, nv] } = rec.region, b = rec.bytes;
      const across = (i) => {
        const values = [];
        for (let j = 0; j < nv; j++) {
          const k = 4 * (j * nu + i), re = (b[k] - 128) / 127 * scale, im = (b[k + 1] - 128) / 127 * scale;
          const a = Math.hypot(re, im) * front(t[0] + b[k + 2] / 255 * (t[1] - t[0]), Math.max(fade, 1e-6)) * b[k + 3] / 255;
          values.push(a * a);
        }
        return values;
      };
      out.regions.push({ id: rec.id, host: rec.region.host, wavelength_nm: rec.region.wavelength_nm, in: across(0), out: across(nu - 1) });
    }
    return out;
  }

  // the heat and RF meshes (tests): what each is, its height, and whether it shows now
  function debugEffects() {
    const now = (e) => (e.kind === 'heat' ? e.mesh.material.uniforms.uPeak.value
                                          : Math.abs(e.mesh.material.uniforms.uField.value) / e.mesh.material.uniforms.uRef.value);
    return effects.map((e) => ({ kind: e.kind, sid: e.sid, visible: e.mesh.visible && S.group.visible, y: e.y, peak: e.peak, clip: e.mesh.material.uniforms.uClip.value.toArray() }))
      .concat(swingEffects.map((e) => ({ kind: e.kind, sid: e.sid, visible: e.mesh.visible && S.group.visible, y: e.y, peak: now(e), swing: true,
                                         clip: e.mesh.material.uniforms.uClip.value.toArray() })));
  }
  // set the outline the maps are drawn in (tests): minimum x, z, maximum x, z in plan
  function debugClip(x0, z0, x1, z1) { for (const e of effects) e.mesh.material.uniforms.uClip.value.set(x0, z0, x1, z1); }
  // show or hide the effects and the optical field's meshes (tests: the field with and without the effects)
  function debugShow(effectsOn, opticalOn) {
    for (const e of effects) e.mesh.visible = !!effectsOn;
    for (const rec of placed) { if (rec.lightMesh) rec.lightMesh.visible = false; for (const m of rec.fieldMeshes || []) m.visible = !!opticalOn; }
  }

  // the tour now (tests): its stops (device, times, box, guide top, drive), the camera, the device in focus, the labels
  // shown, the see-through meshes, the drive sample, the brightest drawn packet per edge or rail (the root of its share
  // of the source power), the largest field amplitude per edge or rail and the physics time (ps, not wrapped)
  function debugTour() {
    const box = (b) => (b && !b.isEmpty() ? [b.min.toArray(), b.max.toArray()] : null);
    const tour = S.tour, plan = tour ? tour.plan : null, labels = [], glass = [], light = {};
    const layer = typeof labelRenderer === 'undefined' || labelRenderer.domElement.style.display !== 'none';
    odContent.traverse((o) => {
      if (o.isCSS2DObject && layer && o.element.isConnected && o.element.style.display !== 'none') labels.push(o.element.textContent);
      const list = o.isMesh ? [].concat(o.material) : [];
      if (list.some((m) => m && m.userData && m.userData.odTourGlass)) {
        glass.push({ opacity: Math.max(...list.map((m) => m.opacity)), transparent: list.every((m) => m.transparent),
                     box: box(new THREE.Box3().setFromObject(o)) });
      }
    });
    for (const rec of placed) if (rec.packets) light[rec.id] = rec.packets.reduce((m, p) => Math.max(m, Math.sqrt(p.share)), 0);
    const field = {};                // the Field look: the largest amplitude its ribbons draw now, per edge or rail
    for (const rec of placed) {
      for (const layer of rec.layers || []) {
        const a = layer.attr.array;
        for (let k = 0; k < a.length; k += 3) field[rec.id] = Math.max(field[rec.id] || 0, a[k]);
      }
    }
    return {
      active: !!tour, t: tour ? tour.t : null, end: plan ? plan.end : null,
      stops: plan ? plan.stops.map((s) => ({ sid: s.sid, name: s.name, arrive: s.arrive, leave: s.leave, box: box(s.box),
                                             guide_top: s.guideTop, drive: s.table ? s.table.param : null,
                                             caption: s.table ? s.table.caption : null,
                                             passes: s.table && s.table.passes ? s.table.passes.map((n, i) => ({
                                               n, level: s.table.levels[i], value: s.table.values[s.table.levels[i]],
                                               enter_ps: s.table.first_ps + n * data.train_period_ps })) : [] })) : [],
      camera: camera.position.toArray(), target: controls.target.toArray(),
      focus: tour && tour.focus >= 0 ? plan.stops[tour.focus].sid : null, labels, glass,
      drive: tour && tour.swing ? { param: tour.swing.table.param, level: tour.swing.level,
                                    value: tour.swing.level >= 0 ? tour.swing.table.values[tour.swing.level] : null } : null,
      light, field, ps: S.raw * psPerSecond, frame: framed(), unframed: unframed(), reach: reach(), seen: seen(),
    };
  }
  // at a driven stop: the farthest point of a drawn edge or rail the camera sees, from the frame's centre, in frame
  // radii (at most 1 when the frame holds all the camera sees)
  function reach() {
    const table = S.tour && S.tour.swing ? S.tour.swing.table : null;
    if (!table || !table.frame) return null;
    const [cx, cy, radius] = table.frame;
    let far = 0;
    camera.updateMatrixWorld();
    for (const rec of placed) {
      if (!rec.pts || !rec.glow) continue;
      for (const p of rec.pts) {
        const q = p.clone().project(camera);
        if (q.z < 1 && Math.abs(q.x) <= 1 && Math.abs(q.y) <= 1) far = Math.max(far, Math.hypot(p.x - cx, -p.z - cy) / radius);
      }
    }
    return far;
  }
  // at a driven stop: the edges and rails with a drawn point in the view
  function seen() {
    if (!(S.tour && S.tour.swing)) return [];
    camera.updateMatrixWorld();
    return placed.filter((rec) => rec.pts && rec.glow && rec.pts.some((p) => {
      const q = p.clone().project(camera);
      return q.z < 1 && Math.abs(q.x) <= 1 && Math.abs(q.y) <= 1;
    })).map((rec) => rec.id);
  }
  // at a driven stop: the edges and rails the camera sees that lie wholly outside the stop's frame (its drive table
  // keeps nothing there, Ruling 47); [] when the frame covers the view
  function unframed() {
    const table = S.tour && S.tour.swing ? S.tour.swing.table : null;
    if (!table || !table.frame) return [];
    const [cx, cy, radius] = table.frame, out = [];
    camera.updateMatrixWorld();
    for (const rec of placed) {
      if (!rec.pts || !rec.glow) continue;
      const seen = rec.pts.some((p) => { const q = p.clone().project(camera); return q.z < 1 && Math.abs(q.x) <= 1 && Math.abs(q.y) <= 1; });
      if (seen && !rec.pts.some((p) => Math.hypot(p.x - cx, -p.z - cy) <= radius)) out.push(rec.id);
    }
    return out;
  }
  // where the circuit's parts are on screen now: the smallest and largest x and y of their box corners, in the
  // frame's own units (-1 to 1 across the view)
  function framed() {
    const out = [Infinity, Infinity, -Infinity, -Infinity], corners = [];
    camera.updateMatrixWorld();
    for (const child of odContent.children) if (child.visible && typeof odBoxCorners === 'function') odBoxCorners(new THREE.Box3().setFromObject(child), corners);
    for (const c of corners) {
      const q = c.clone().project(camera);
      out[0] = Math.min(out[0], q.x); out[1] = Math.min(out[1], q.y); out[2] = Math.max(out[2], q.x); out[3] = Math.max(out[3], q.y);
    }
    return corners.length ? out : null;
  }
  // the live tour's clock moved by dt seconds of real time, as a frame does (tests: no wait for real time)
  function debugAdvance(dt) { if (S.tour && S.tour.playing) advanceTour(dt * S.speed); }

  // --- the bar's controls (all optional) -----------------------------------------------------------------------
  (function wire() {
    const $ = (id) => document.getElementById(id);
    const play = $('anim-play');
    if (play) play.addEventListener('click', () => control('play', !S.playing));
    const speed = $('anim-speed');
    if (speed) speed.addEventListener('input', () => control('speed', speed.value));
    window.addEventListener('resize', () => placeCaptions());
    const look = $('light-look');
    if (look) look.addEventListener('change', () => control('look', look.value));
    const tour = $('light-tour');
    if (tour) tour.addEventListener('click', () => control('tour', !S.tour));
    const record = $('light-record');
    if (record) record.addEventListener('click', () => {
      const label = record.textContent;
      record.disabled = true; record.textContent = 'Recording…';
      const mine = !recording;                       // stop only a recording this click started
      recordTour(30).then((blob) => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = 'optodraw-tour.webm'; a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      }).catch((e) => { window.alert('Record video: ' + e.message); })
        .finally(() => { if (mine) stopTour(false); syncTour(); record.textContent = label; });
    });
    // the user takes the view: the tour stops where the camera is
    if (typeof controls !== 'undefined') controls.addEventListener('start', () => { if (S.tour && !recording) stopTour(true); });
    const scrub = $('anim-scrub');
    if (scrub) {
      scrub.addEventListener('pointerdown', () => { scrubbing = true; });
      scrub.addEventListener('input', () => control('time', scrub.value));
      const end = () => { scrubbing = false; };
      scrub.addEventListener('pointerup', end);
      scrub.addEventListener('pointercancel', end);
      window.addEventListener('pointerup', end);
    }
  })();

  return { build, tick, setEnabled, control, frameAt, state: S, recordTour, debugPlacement, debugHeights, debugGlow, debugEnds, debugField, debugEffects, debugShow, debugClip,
           debugTour, debugAdvance, debugGlowAt };
})();
