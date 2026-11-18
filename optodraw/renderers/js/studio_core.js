/* optodraw studio renderer: the pure core.
 *
 * No three.js and no DOM: the page, the Web Workers and the tests run this same code. Method tips (a flat
 * BVH with surface-area splits, softbox lobes, split-sum light tables, hash-rotated shadow rays, a
 * geometry-guided denoiser) come from tscircuit/poppygl (MIT); the code here is optodraw's own.
 */
function odStudioCoreFactory() {        // a named factory: its source also starts the workers
  'use strict';

  const T_MIN = 1e-9;                     // the nearest hit distance a ray accepts
  const LEAF_SIZE = 4;                    // triangles per leaf below which a node never splits
  const BINS = 12;                        // surface-area split candidates per axis

  // ---------------------------------------------------------------------------------------------
  // BVH: nodes in depth-first order. An interior node's left child is the next node; ``escape`` is the
  // node after its whole subtree, so the walk needs no stack. Triangles are stored in leaf order as
  // (p0, e1, e2) in float64, with their original index.
  // ---------------------------------------------------------------------------------------------
  function buildBVH(positions) {
    const n = (positions.length / 9) | 0;
    const lo3 = new Float64Array(n * 3), hi3 = new Float64Array(n * 3), mid3 = new Float64Array(n * 3);
    for (let i = 0; i < n; i++) {
      for (let a = 0; a < 3; a++) {
        const x = positions[i * 9 + a], y = positions[i * 9 + 3 + a], z = positions[i * 9 + 6 + a];
        const lo = Math.min(x, y, z), hi = Math.max(x, y, z);
        lo3[i * 3 + a] = lo; hi3[i * 3 + a] = hi; mid3[i * 3 + a] = 0.5 * (lo + hi);
      }
    }
    const order = new Uint32Array(n);
    for (let i = 0; i < n; i++) order[i] = i;
    const bounds = [], escape = [], start = [], count = [];
    const binLo = new Float64Array(BINS * 3), binHi = new Float64Array(BINS * 3), binN = new Uint32Array(BINS);
    const rightArea = new Float64Array(BINS), rightN = new Uint32Array(BINS);

    function area(x0, y0, z0, x1, y1, z1) {
      const dx = x1 - x0, dy = y1 - y0, dz = z1 - z0;
      return dx < 0 ? 0 : 2 * (dx * dy + dy * dz + dz * dx);
    }

    function build(first, last) {                       // the triangles order[first .. last - 1]
      const node = escape.length;
      let bx0 = Infinity, by0 = Infinity, bz0 = Infinity, bx1 = -Infinity, by1 = -Infinity, bz1 = -Infinity;
      let cx0 = Infinity, cy0 = Infinity, cz0 = Infinity, cx1 = -Infinity, cy1 = -Infinity, cz1 = -Infinity;
      for (let k = first; k < last; k++) {
        const t = order[k] * 3;
        if (lo3[t] < bx0) bx0 = lo3[t]; if (lo3[t + 1] < by0) by0 = lo3[t + 1]; if (lo3[t + 2] < bz0) bz0 = lo3[t + 2];
        if (hi3[t] > bx1) bx1 = hi3[t]; if (hi3[t + 1] > by1) by1 = hi3[t + 1]; if (hi3[t + 2] > bz1) bz1 = hi3[t + 2];
        if (mid3[t] < cx0) cx0 = mid3[t]; if (mid3[t + 1] < cy0) cy0 = mid3[t + 1]; if (mid3[t + 2] < cz0) cz0 = mid3[t + 2];
        if (mid3[t] > cx1) cx1 = mid3[t]; if (mid3[t + 1] > cy1) cy1 = mid3[t + 1]; if (mid3[t + 2] > cz1) cz1 = mid3[t + 2];
      }
      bounds.push(bx0, by0, bz0, bx1, by1, bz1);
      escape.push(0); start.push(first); count.push(0);
      const size = last - first;
      let split = -1;
      if (size > LEAF_SIZE) {
        const cLo = [cx0, cy0, cz0], cHi = [cx1, cy1, cz1];
        let bestCost = area(bx0, by0, bz0, bx1, by1, bz1) * size, bestAxis = -1, bestBin = 0;
        for (let axis = 0; axis < 3; axis++) {
          const extent = cHi[axis] - cLo[axis];
          if (!(extent > 0)) continue;
          binN.fill(0); binLo.fill(Infinity); binHi.fill(-Infinity);
          const scale = BINS / extent;
          for (let k = first; k < last; k++) {
            const t = order[k] * 3, b = Math.min(BINS - 1, ((mid3[t + axis] - cLo[axis]) * scale) | 0);
            binN[b]++;
            for (let a = 0; a < 3; a++) {
              if (lo3[t + a] < binLo[b * 3 + a]) binLo[b * 3 + a] = lo3[t + a];
              if (hi3[t + a] > binHi[b * 3 + a]) binHi[b * 3 + a] = hi3[t + a];
            }
          }
          let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity, m = 0;
          for (let b = BINS - 1; b > 0; b--) {           // right side of the split before bin b
            m += binN[b];
            x0 = Math.min(x0, binLo[b * 3]); y0 = Math.min(y0, binLo[b * 3 + 1]); z0 = Math.min(z0, binLo[b * 3 + 2]);
            x1 = Math.max(x1, binHi[b * 3]); y1 = Math.max(y1, binHi[b * 3 + 1]); z1 = Math.max(z1, binHi[b * 3 + 2]);
            rightArea[b] = area(x0, y0, z0, x1, y1, z1); rightN[b] = m;
          }
          x0 = Infinity; y0 = Infinity; z0 = Infinity; x1 = -Infinity; y1 = -Infinity; z1 = -Infinity; m = 0;
          for (let b = 1; b < BINS; b++) {
            const p = b - 1;
            m += binN[p];
            x0 = Math.min(x0, binLo[p * 3]); y0 = Math.min(y0, binLo[p * 3 + 1]); z0 = Math.min(z0, binLo[p * 3 + 2]);
            x1 = Math.max(x1, binHi[p * 3]); y1 = Math.max(y1, binHi[p * 3 + 1]); z1 = Math.max(z1, binHi[p * 3 + 2]);
            if (m === 0 || rightN[b] === 0) continue;
            const cost = area(x0, y0, z0, x1, y1, z1) * m + rightArea[b] * rightN[b];
            if (cost < bestCost) { bestCost = cost; bestAxis = axis; bestBin = b; }
          }
        }
        if (bestAxis >= 0) {                             // partition in place: bins below bestBin go left
          const scale = BINS / (cHi[bestAxis] - cLo[bestAxis]);
          let i = first, j = last - 1;
          while (i <= j) {
            const b = Math.min(BINS - 1, ((mid3[order[i] * 3 + bestAxis] - cLo[bestAxis]) * scale) | 0);
            if (b < bestBin) i++;
            else { const swap = order[i]; order[i] = order[j]; order[j] = swap; j--; }
          }
          split = i;
        } else if (size > 255) {
          split = (first + last) >> 1;                   // every centroid equal: split anyway, leaves stay small
        }
      }
      if (split <= first || split >= last) {
        count[node] = size;
        escape[node] = node + 1;
        return;
      }
      build(first, split);
      build(split, last);
      escape[node] = escape.length;
    }

    if (n > 0) build(0, n);
    const tris = new Float64Array(n * 9);
    for (let k = 0; k < n; k++) {
      const i = order[k] * 9, o = k * 9;
      for (let a = 0; a < 3; a++) {
        tris[o + a] = positions[i + a];
        tris[o + 3 + a] = positions[i + 3 + a] - positions[i + a];
        tris[o + 6 + a] = positions[i + 6 + a] - positions[i + a];
      }
    }
    return {
      count: escape.length,
      bounds: Float64Array.from(bounds),
      escape: Uint32Array.from(escape),
      start: Uint32Array.from(start),
      size: Uint16Array.from(count),
      tris,
      index: order,
    };
  }

  function newHit() {
    return { t: Infinity, tri: -1, u: 0, v: 0 };
  }

  // One walk serves both queries: ``hit`` null means "any hit" (shadow rays stop at the first).
  function walk(bvh, ox, oy, oz, dx, dy, dz, tmax, hit, mask) {
    const bounds = bvh.bounds, escape = bvh.escape, start = bvh.start, size = bvh.size, tris = bvh.tris;
    const ix = 1 / dx, iy = 1 / dy, iz = 1 / dz;
    const px = dx === 0, py = dy === 0, pz = dz === 0;
    let limit = tmax, found = false, node = 0;
    const nodes = bvh.count;
    while (node < nodes) {
      const b = node * 6;
      let near = 0, far = limit, miss = false;
      if (px) { if (ox < bounds[b] || ox > bounds[b + 3]) miss = true; }
      else {
        let t0 = (bounds[b] - ox) * ix, t1 = (bounds[b + 3] - ox) * ix;
        if (t0 > t1) { const s = t0; t0 = t1; t1 = s; }
        if (t0 > near) near = t0; if (t1 < far) far = t1;
        if (far < near) miss = true;
      }
      if (!miss) {
        if (py) { if (oy < bounds[b + 1] || oy > bounds[b + 4]) miss = true; }
        else {
          let t0 = (bounds[b + 1] - oy) * iy, t1 = (bounds[b + 4] - oy) * iy;
          if (t0 > t1) { const s = t0; t0 = t1; t1 = s; }
          if (t0 > near) near = t0; if (t1 < far) far = t1;
          if (far < near) miss = true;
        }
      }
      if (!miss) {
        if (pz) { if (oz < bounds[b + 2] || oz > bounds[b + 5]) miss = true; }
        else {
          let t0 = (bounds[b + 2] - oz) * iz, t1 = (bounds[b + 5] - oz) * iz;
          if (t0 > t1) { const s = t0; t0 = t1; t1 = s; }
          if (t0 > near) near = t0; if (t1 < far) far = t1;
          if (far < near) miss = true;
        }
      }
      if (miss) { node = escape[node]; continue; }
      const k1 = start[node] + size[node];
      for (let k = start[node]; k < k1; k++) {
        if (mask && !mask[k]) continue;
        const o = k * 9;
        const e1x = tris[o + 3], e1y = tris[o + 4], e1z = tris[o + 5], e2x = tris[o + 6], e2y = tris[o + 7], e2z = tris[o + 8];
        const hx = dy * e2z - dz * e2y, hy = dz * e2x - dx * e2z, hz = dx * e2y - dy * e2x;
        const det = e1x * hx + e1y * hy + e1z * hz;
        if (det > -1e-14 && det < 1e-14) continue;
        const inv = 1 / det, sx = ox - tris[o], sy = oy - tris[o + 1], sz = oz - tris[o + 2];
        const u = (sx * hx + sy * hy + sz * hz) * inv;
        if (u < 0 || u > 1) continue;
        const qx = sy * e1z - sz * e1y, qy = sz * e1x - sx * e1z, qz = sx * e1y - sy * e1x;
        const v = (dx * qx + dy * qy + dz * qz) * inv;
        if (v < 0 || u + v > 1) continue;
        const t = (e2x * qx + e2y * qy + e2z * qz) * inv;
        if (t <= T_MIN || t >= limit) continue;
        if (!hit) return true;
        found = true; limit = t;
        hit.t = t; hit.tri = bvh.index[k]; hit.u = u; hit.v = v;
      }
      node++;
    }
    return found;
  }

  // Where the ray enters node ``n``'s box, or Infinity when it misses it before ``limit``.
  function boxEntry(bounds, n, ox, oy, oz, ix, iy, iz, px, py, pz, limit) {
    const b = n * 6;
    let near = 0, far = limit;
    if (px) { if (ox < bounds[b] || ox > bounds[b + 3]) return Infinity; }
    else {
      let t0 = (bounds[b] - ox) * ix, t1 = (bounds[b + 3] - ox) * ix;
      if (t0 > t1) { const s = t0; t0 = t1; t1 = s; }
      if (t0 > near) near = t0; if (t1 < far) far = t1;
      if (far < near) return Infinity;
    }
    if (py) { if (oy < bounds[b + 1] || oy > bounds[b + 4]) return Infinity; }
    else {
      let t0 = (bounds[b + 1] - oy) * iy, t1 = (bounds[b + 4] - oy) * iy;
      if (t0 > t1) { const s = t0; t0 = t1; t1 = s; }
      if (t0 > near) near = t0; if (t1 < far) far = t1;
      if (far < near) return Infinity;
    }
    if (pz) { if (oz < bounds[b + 2] || oz > bounds[b + 5]) return Infinity; }
    else {
      let t0 = (bounds[b + 2] - oz) * iz, t1 = (bounds[b + 5] - oz) * iz;
      if (t0 > t1) { const s = t0; t0 = t1; t1 = s; }
      if (t0 > near) near = t0; if (t1 < far) far = t1;
      if (far < near) return Infinity;
    }
    return near;
  }

  const STACK = new Int32Array(128), STACK_T = new Float64Array(128);

  // Closest hit: nearer child first, and a child whose box starts beyond the current hit is skipped.
  function closestHit(bvh, ox, oy, oz, dx, dy, dz, tmax, hit, mask) {
    hit.t = Infinity; hit.tri = -1;
    if (!bvh.count) return false;
    const bounds = bvh.bounds, escape = bvh.escape, start = bvh.start, size = bvh.size, tris = bvh.tris;
    const ix = 1 / dx, iy = 1 / dy, iz = 1 / dz, px = dx === 0, py = dy === 0, pz = dz === 0;
    let limit = tmax, found = false, top = 0;
    const t0 = boxEntry(bounds, 0, ox, oy, oz, ix, iy, iz, px, py, pz, limit);
    if (t0 === Infinity) return false;
    STACK[top] = 0; STACK_T[top] = t0; top++;
    while (top > 0) {
      top--;
      const node = STACK[top];
      if (STACK_T[top] >= limit) continue;
      if (size[node] > 0) {
        const k1 = start[node] + size[node];
        for (let k = start[node]; k < k1; k++) {
          if (mask && !mask[k]) continue;
          const o = k * 9;
          const e1x = tris[o + 3], e1y = tris[o + 4], e1z = tris[o + 5], e2x = tris[o + 6], e2y = tris[o + 7], e2z = tris[o + 8];
          const hx = dy * e2z - dz * e2y, hy = dz * e2x - dx * e2z, hz = dx * e2y - dy * e2x;
          const det = e1x * hx + e1y * hy + e1z * hz;
          if (det > -1e-14 && det < 1e-14) continue;
          const inv = 1 / det, sx = ox - tris[o], sy = oy - tris[o + 1], sz = oz - tris[o + 2];
          const u = (sx * hx + sy * hy + sz * hz) * inv;
          if (u < 0 || u > 1) continue;
          const qx = sy * e1z - sz * e1y, qy = sz * e1x - sx * e1z, qz = sx * e1y - sy * e1x;
          const v = (dx * qx + dy * qy + dz * qz) * inv;
          if (v < 0 || u + v > 1) continue;
          const t = (e2x * qx + e2y * qy + e2z * qz) * inv;
          if (t <= T_MIN || t >= limit) continue;
          found = true; limit = t;
          hit.t = t; hit.tri = bvh.index[k]; hit.u = u; hit.v = v;
        }
        continue;
      }
      const left = node + 1, right = escape[left];
      const tl = boxEntry(bounds, left, ox, oy, oz, ix, iy, iz, px, py, pz, limit);
      const tr = boxEntry(bounds, right, ox, oy, oz, ix, iy, iz, px, py, pz, limit);
      if (tl <= tr) {
        if (tr !== Infinity) { STACK[top] = right; STACK_T[top] = tr; top++; }
        if (tl !== Infinity) { STACK[top] = left; STACK_T[top] = tl; top++; }
      } else {
        if (tl !== Infinity) { STACK[top] = left; STACK_T[top] = tl; top++; }
        STACK[top] = right; STACK_T[top] = tr; top++;
      }
    }
    return found;
  }

  function occluded(bvh, ox, oy, oz, dx, dy, dz, tmax, mask) {
    return walk(bvh, ox, oy, oz, dx, dy, dz, tmax, null, mask);
  }

  // ---------------------------------------------------------------------------------------------
  // Studio light: softboxes as spherical Gaussian lobes, L(l) = color * exp(s (dir . l - 1)), plus an
  // ambient term. Diffuse light comes from a table per lobe (quadrature in the lobe's own frame, so even a
  // narrow softbox is exact). Specular light is the exact product integral of the lobe and the GGX lobe
  // taken as a normalized Gaussian of sharpness 2 / alpha^2. A split-sum (A, B) table and multiple-
  // scattering compensation keep every material within the light it receives.
  // ---------------------------------------------------------------------------------------------
  const TW = 96, TH = 48;                 // diffuse table: longitude x latitude, +y is the pole
  const LUT = 64;                         // the (A, B) table: roughness x cos(view)

  function radicalInverse(i) {
    let r = 0, f = 0.5;
    while (i) { r += (i & 1) * f; i >>>= 1; f *= 0.5; }
    return r;
  }

  function frame(x, y, z) {               // two unit vectors at right angles to (x, y, z)
    let tx, ty, tz;
    if (Math.abs(y) < 0.999) { tx = z; ty = 0; tz = -x; } else { tx = 1; ty = 0; tz = 0; }
    const l = Math.hypot(tx, ty, tz); tx /= l; ty /= l; tz /= l;
    return [tx, ty, tz, y * tz - z * ty, z * tx - x * tz, x * ty - y * tx];
  }

  let brdfTable = null;
  function brdfLUT() {                    // A and B of the split sum, Smith GGX, 256 Hammersley samples
    if (brdfTable) return brdfTable;
    const N = 256, out = new Float32Array(LUT * LUT * 2);
    for (let yi = 0; yi < LUT; yi++) for (let xi = 0; xi < LUT; xi++) {
      const rough = (yi + 0.5) / LUT, nv = (xi + 0.5) / LUT, a = rough * rough, a2 = a * a;
      const vx = Math.sqrt(1 - nv * nv), vz = nv;
      let A = 0, B = 0;
      for (let i = 0; i < N; i++) {
        const u = (i + 0.5) / N, phi = 2 * Math.PI * radicalInverse(i);
        const nh = Math.sqrt((1 - u) / (1 + (a2 - 1) * u)), sh = Math.sqrt(1 - nh * nh);
        const hx = sh * Math.cos(phi), hz = nh, vh = vx * hx + vz * hz;
        const nl = 2 * vh * hz - vz;
        if (nl <= 0 || vh <= 0) continue;
        const gv = (2 * nv) / (nv + Math.sqrt(a2 + (1 - a2) * nv * nv));
        const gl = (2 * nl) / (nl + Math.sqrt(a2 + (1 - a2) * nl * nl));
        const vis = (gv * gl * vh) / (nh * nv), f = Math.pow(1 - vh, 5);
        A += (1 - f) * vis; B += f * vis;
      }
      out[(yi * LUT + xi) * 2] = A / N; out[(yi * LUT + xi) * 2 + 1] = B / N;
    }
    brdfTable = out;
    return out;
  }

  function buildTables(env) {
    const NU = 24, NP = 24;
    const diffuse = env.lobes.map((lobe) => {
      const table = new Float32Array(TW * TH), s = lobe.sharpness, [dx, dy, dz] = lobe.dir;
      const f = frame(dx, dy, dz), total = (2 * Math.PI * (1 - Math.exp(-2 * s))) / s;
      const dirs = [];                                     // directions spread like the lobe itself
      for (let i = 0; i < NU; i++) for (let j = 0; j < NP; j++) {
        const u = (i + 0.5) / NU, mu = 1 + Math.log(1 - u * (1 - Math.exp(-2 * s))) / s;
        const st = Math.sqrt(Math.max(0, 1 - mu * mu)), phi = (2 * Math.PI * (j + 0.5)) / NP;
        const a = st * Math.cos(phi), b = st * Math.sin(phi);
        dirs.push(f[0] * a + f[3] * b + dx * mu, f[1] * a + f[4] * b + dy * mu, f[2] * a + f[5] * b + dz * mu);
      }
      for (let yi = 0; yi < TH; yi++) for (let xi = 0; xi < TW; xi++) {
        const theta = ((yi + 0.5) / TH) * Math.PI, phi = ((xi + 0.5) / TW - 0.5) * 2 * Math.PI;
        const nx = Math.sin(theta) * Math.cos(phi), ny = Math.cos(theta), nz = Math.sin(theta) * Math.sin(phi);
        let acc = 0;
        for (let k = 0; k < dirs.length; k += 3) {
          const c = nx * dirs[k] + ny * dirs[k + 1] + nz * dirs[k + 2];
          if (c > 0) acc += c;
        }
        table[yi * TW + xi] = (total * acc) / (dirs.length / 3) / Math.PI;
      }
      return table;
    });
    return { diffuse, brdf: brdfLUT() };
  }

  function sampleTable(table, x, y, z) {   // bilinear lookup by direction
    const fx = (Math.atan2(z, x) / (2 * Math.PI) + 0.5) * TW - 0.5;
    const fy = Math.max(0, Math.min(TH - 1, (Math.acos(Math.max(-1, Math.min(1, y))) / Math.PI) * TH - 0.5));
    const ix = Math.floor(fx), iy = Math.floor(fy), tx = fx - ix, ty = fy - iy;
    const a = ((ix % TW) + TW) % TW, b = (a + 1) % TW, c = Math.min(TH - 1, iy + 1);
    return (table[iy * TW + a] * (1 - tx) + table[iy * TW + b] * tx) * (1 - ty)
      + (table[c * TW + a] * (1 - tx) + table[c * TW + b] * tx) * ty;
  }

  // Diffuse light (radiance-weighted cosine average, so a uniform room of radiance L gives L), per lobe
  // scaled by ``vis[j]`` (1 when open), into ``out``.
  function diffuseLight(tables, env, nx, ny, nz, out, vis) {
    out[0] = env.ambient[0]; out[1] = env.ambient[1]; out[2] = env.ambient[2];
    for (let j = 0; j < env.lobes.length; j++) {
      const w = sampleTable(tables.diffuse[j], nx, ny, nz) * (vis ? vis[j] : 1), c = env.lobes[j].color;
      out[0] += c[0] * w; out[1] += c[1] * w; out[2] += c[2] * w;
    }
  }

  function lobeTimesGGX(lobe, rx, ry, rz, s2) {   // integral of the lobe times a unit-area Gaussian around r
    const s1 = lobe.sharpness, d = lobe.dir;
    const kx = s1 * d[0] + s2 * rx, ky = s1 * d[1] + s2 * ry, kz = s1 * d[2] + s2 * rz;
    const k = Math.hypot(kx, ky, kz), e = s1 + s2;
    const shell = k < 1e-8 ? 4 * Math.PI * Math.exp(-e)
      : (2 * Math.PI * (Math.exp(k - e) - Math.exp(-k - e))) / k;         // 4 pi exp(-e) sinh(k) / k
    return shell * (s2 / (2 * Math.PI * (1 - Math.exp(-2 * s2))));
  }

  function specularLight(env, rx, ry, rz, rough, out, vis) {
    const a = Math.max(rough * rough, 1e-4), s2 = 2 / (a * a);
    out[0] = env.ambient[0]; out[1] = env.ambient[1]; out[2] = env.ambient[2];
    for (let j = 0; j < env.lobes.length; j++) {
      const w = lobeTimesGGX(env.lobes[j], rx, ry, rz, s2) * (vis ? vis[j] : 1), c = env.lobes[j].color;
      out[0] += c[0] * w; out[1] += c[1] * w; out[2] += c[2] * w;
    }
  }

  // The specular weight per channel and the diffuse weight that is left (multiple-scattering compensation,
  // Fdez-Aguera 2019): ``w`` gets [spec r, g, b, diffuse r, g, b].
  function weights(tables, base, metal, rough, nv, w) {
    const xi = Math.min(LUT - 1, Math.floor(nv * LUT)), yi = Math.min(LUT - 1, Math.floor(rough * LUT));
    const A = tables.brdf[(yi * LUT + xi) * 2], B = tables.brdf[(yi * LUT + xi) * 2 + 1];
    const ess = A + B, ems = 1 - ess;
    for (let c = 0; c < 3; c++) {
      const f0 = 0.04 * (1 - metal) + base[c] * metal;
      const fss = f0 * A + B, favg = f0 + (1 - f0) / 21, fms = (fss * favg) / (1 - ems * favg);
      const spec = fss + fms * ems;
      w[c] = spec;
      w[3 + c] = base[c] * (1 - metal) * (1 - spec);
    }
  }

  // Shading with no shadows and no bounces: the unit tests' view of the light model.
  function shadeOpen(tables, env, n, v, mat, out) {
    const nv = Math.max(1e-3, n[0] * v[0] + n[1] * v[1] + n[2] * v[2]);
    const rx = 2 * nv * n[0] - v[0], ry = 2 * nv * n[1] - v[1], rz = 2 * nv * n[2] - v[2];
    const rough = Math.max(0.04, Math.min(1, mat.rough)), w = [0, 0, 0, 0, 0, 0], dl = [0, 0, 0], sl = [0, 0, 0];
    weights(tables, mat.base, mat.metal, rough, nv, w);
    diffuseLight(tables, env, n[0], n[1], n[2], dl);
    specularLight(env, rx, ry, rz, rough, sl);
    for (let c = 0; c < 3; c++) out[c] = w[3 + c] * dl[c] + w[c] * sl[c];
  }

  // ---------------------------------------------------------------------------------------------
  // Glass: Fresnel (Schlick, F0 from the IOR), Snell refraction, a tint per crossing.
  // ---------------------------------------------------------------------------------------------
  const GLASS_SHADOW = 0.75;              // light that reaches a surface through glass (two surfaces, a little tint)

  // The refracted direction for unit d meeting a surface whose unit normal n faces d's origin, with
  // eta = n_from / n_to; null on total internal reflection.
  function refract(d, n, eta) {
    const cosi = -(d[0] * n[0] + d[1] * n[1] + d[2] * n[2]), k = 1 - eta * eta * (1 - cosi * cosi);
    if (k < 0) return null;
    const a = eta * cosi - Math.sqrt(k);
    return [eta * d[0] + a * n[0], eta * d[1] + a * n[1], eta * d[2] + a * n[2]];
  }

  // ---------------------------------------------------------------------------------------------
  // The studio: lobe directions in the camera's horizontal frame (x right, y up, z toward the camera),
  // so every camera preset gets a warm key at the upper left front, a cool fill at the right and a rim
  // behind. Values after poppygl's studio-environment.json.
  // ---------------------------------------------------------------------------------------------
  const LOBES = [
    { dir: [-0.45, 0.8, 0.4], sharpness: 18, color: [5.0, 4.8, 4.4] },
    { dir: [0.8, 0.3, 0.3], sharpness: 30, color: [2.6, 3.1, 4.0] },
    { dir: [-0.2, 0.3, -0.95], sharpness: 50, color: [4.0, 4.3, 5.0] },
    { dir: [0, 1, 0], sharpness: 1.5, color: [1.4, 1.4, 1.44] },        // the broad diffuser overhead
  ];
  // The light world is a white room: its walls light every direction. poppygl's darker value relies on
  // a floor in each model; optodraw's light world has none around the table.
  const STUDIO = { light: [0.22, 0.225, 0.24], dark: [0.03, 0.034, 0.042] };
  const QUALITY = { final: { shadow: 8, fill: 4, reflect: 8 }, draft: { shadow: 2, fill: 2, reflect: 2 } };

  function studioEnv(world, camera) {
    let rx = camera.right[0], rz = camera.right[2];
    const l = Math.hypot(rx, rz);
    if (l < 1e-6) { rx = 1; rz = 0; } else { rx /= l; rz /= l; }
    const bx = -rz, bz = rx;                             // right x up: horizontal, toward the camera
    const lobes = LOBES.map((lobe) => {
      const [x, y, z] = lobe.dir, d = [x * rx + z * bx, y, x * rz + z * bz], n = Math.hypot(d[0], d[1], d[2]);
      return { dir: [d[0] / n, d[1] / n, d[2] / n], sharpness: lobe.sharpness, color: lobe.color.slice() };
    });
    return { ambient: (STUDIO[world] || STUDIO.light).slice(), lobes };
  }

  const SRGB_TO_LINEAR = new Float32Array(256);
  for (let i = 0; i < 256; i++) {
    const c = i / 255;
    SRGB_TO_LINEAR[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  function hash(i) {                      // integer -> [0, 1), the same in every browser
    i = Math.imul(i ^ (i >>> 16), 0x7feb352d);
    i = Math.imul(i ^ (i >>> 15), 0x846ca68b);
    return ((i ^ (i >>> 16)) >>> 0) / 4294967296;
  }

  // The parts every worker shares: the BVH, the light and its tables. Built once, sent to the workers.
  function prebuild(data) {
    const env = data.env && typeof data.env === 'object' ? data.env : studioEnv(data.env || 'light', data.camera);
    return { env, bvh: buildBVH(data.positions), tables: buildTables(env) };
  }

  function prepareScene(data, built) {
    const { env, bvh, tables } = built || prebuild(data), n = bvh.index.length;
    const opaque = new Uint8Array(n), glass = new Uint8Array(n);   // leaf order: what blocks, what tints
    let anyGlass = false;
    for (let k = 0; k < n; k++) {
      const m = data.materials[data.material[bvh.index[k]]];
      opaque[k] = m.opacity >= 0.999 && !(m.transmission > 0) && !m.unlit ? 1 : 0;
      glass[k] = m.transmission > 0 ? 1 : 0;
      if (glass[k]) anyGlass = true;
    }
    const b = bvh.bounds, extent = n ? Math.hypot(b[3] - b[0], b[4] - b[1], b[5] - b[2]) : 1;
    let floor = null;                                   // an exact plane under the parts: a studio floor or a shadow catcher
    if (data.floor) {
      const F = data.floor, color = F.color || [0.6, 0.62, 0.66];
      floor = { y: F.y, mode: F.mode, cx: F.center[0], cz: F.center[1], r0: F.fade[0], r1: F.fade[1], mi: data.materials.length };
      data.materials = data.materials.concat([{ base: color, metal: 0, rough: 0.85, emissive: [0, 0, 0], opacity: 1,
                                                transmission: 0, ior: 1.5, unlit: false, texture: -1 }]);
    }
    const rays = data.quality && typeof data.quality === 'object' ? data.quality : QUALITY[data.quality] || QUALITY.final;
    const shadowDirs = env.lobes.map((lobe) => {        // in the lobe's frame: (sin cos, sin sin, cos)
      const out = [];
      for (let i = 0; i < rays.shadow; i++) {
        const u = (i + 0.5) / rays.shadow, c = Math.max(-1, 1 + Math.log(1 - u) / lobe.sharpness);
        const st = Math.sqrt(Math.max(0, 1 - c * c)), phi = 2 * Math.PI * radicalInverse(i);
        out.push(st * Math.cos(phi), st * Math.sin(phi), c);
      }
      return { f: frame(lobe.dir[0], lobe.dir[1], lobe.dir[2]), d: lobe.dir, s: out };
    });
    return {
      data, env, rays, bvh, opaque, glass: anyGlass ? glass : null, shadowDirs, tables, floor, bias: Math.max(1e-7, extent * 1e-5),
      contact: 0.1 * extent,                             // how far a contact shadow reaches on the catcher
      hit: newHit(), hit2: newHit(), s1: newSurface(), s2: newSurface(), vis: new Float64Array(env.lobes.length),
      first: { id: 0, t: 0, nx: 0, ny: 1, nz: 0, r: 0, g: 0, b: 0 },
      w: [0, 0, 0, 0, 0, 0], w2: [0, 0, 0, 0, 0, 0], dl: [0, 0, 0], sl: [0, 0, 0], c: [0, 0, 0], c2: [0, 0, 0],
    };
  }

  function newSurface() {
    return { px: 0, py: 0, pz: 0, nx: 0, ny: 1, nz: 0, gx: 0, gy: 1, gz: 0, mi: 0, base: [1, 1, 1], alpha: 1, front: true };
  }

  // Position, normals (both facing the ray), material, colour and coverage where ``hit`` landed.
  function surface(ctx, ox, oy, oz, dx, dy, dz, hit, s) {
    const D = ctx.data, P = D.positions, tri = hit.tri, i = tri * 9;
    const e1x = P[i + 3] - P[i], e1y = P[i + 4] - P[i + 1], e1z = P[i + 5] - P[i + 2];
    const e2x = P[i + 6] - P[i], e2y = P[i + 7] - P[i + 1], e2z = P[i + 8] - P[i + 2];
    let gx = e1y * e2z - e1z * e2y, gy = e1z * e2x - e1x * e2z, gz = e1x * e2y - e1y * e2x;
    const gl = Math.hypot(gx, gy, gz) || 1;
    gx /= gl; gy /= gl; gz /= gl;
    s.front = gx * dx + gy * dy + gz * dz < 0;          // the ray meets the side the winding faces
    if (!s.front) { gx = -gx; gy = -gy; gz = -gz; }
    const w1 = hit.u, w2 = hit.v, w0 = 1 - w1 - w2;
    let nx = gx, ny = gy, nz = gz;
    if (D.normals) {
      const N = D.normals;
      let ax = w0 * N[i] + w1 * N[i + 3] + w2 * N[i + 6], ay = w0 * N[i + 1] + w1 * N[i + 4] + w2 * N[i + 7];
      let az = w0 * N[i + 2] + w1 * N[i + 5] + w2 * N[i + 8];
      const al = Math.hypot(ax, ay, az);
      if (al > 1e-12) {
        ax /= al; ay /= al; az /= al;
        if (ax * gx + ay * gy + az * gz < 0) { ax = -ax; ay = -ay; az = -az; }
        nx = ax; ny = ay; nz = az;
      }
    }
    s.px = ox + dx * hit.t; s.py = oy + dy * hit.t; s.pz = oz + dz * hit.t;
    s.nx = nx; s.ny = ny; s.nz = nz; s.gx = gx; s.gy = gy; s.gz = gz;
    const mi = D.material[tri], m = D.materials[mi];
    s.mi = mi; s.base[0] = m.base[0]; s.base[1] = m.base[1]; s.base[2] = m.base[2]; s.alpha = m.opacity;
    if (m.texture >= 0 && D.uvs) {
      const T = D.textures[m.texture], U = D.uvs, j = tri * 6;
      let u = w0 * U[j] + w1 * U[j + 2] + w2 * U[j + 4], v = w0 * U[j + 1] + w1 * U[j + 3] + w2 * U[j + 5];
      if (m.uvMatrix) {
        const e = m.uvMatrix, uu = e[0] * u + e[3] * v + e[6];
        v = e[1] * u + e[4] * v + e[7]; u = uu;
      }
      u = T.wrapS === 'repeat' ? u - Math.floor(u) : Math.min(1, Math.max(0, u));
      v = T.wrapT === 'repeat' ? v - Math.floor(v) : Math.min(1, Math.max(0, v));
      const x = Math.min(T.width - 1, Math.floor(u * T.width));
      const y = Math.min(T.height - 1, Math.floor((T.flipY ? 1 - v : v) * T.height));
      const k = (y * T.width + x) * 4;
      s.base[0] *= SRGB_TO_LINEAR[T.data[k]]; s.base[1] *= SRGB_TO_LINEAR[T.data[k + 1]];
      s.base[2] *= SRGB_TO_LINEAR[T.data[k + 2]]; s.alpha *= T.data[k + 3] / 255;
    }
  }

  // Light that leaves a secondary hit toward the ray: open studio light, no further rays.
  function bounce(ctx, ox, oy, oz, dx, dy, dz, out) {
    const s = ctx.s2;
    surface(ctx, ox, oy, oz, dx, dy, dz, ctx.hit2, s);
    const m = ctx.data.materials[s.mi];
    if (m.unlit) { out[0] = s.base[0]; out[1] = s.base[1]; out[2] = s.base[2]; clampBounce(out); return; }
    const nv = Math.max(1e-3, -(s.nx * dx + s.ny * dy + s.nz * dz));
    const rough = Math.max(0.04, Math.min(1, m.rough)), w = ctx.w2, dl = ctx.dl, sl = ctx.sl;
    weights(ctx.tables, s.base, m.metal, rough, nv, w);
    diffuseLight(ctx.tables, ctx.env, s.nx, s.ny, s.nz, dl);
    specularLight(ctx.env, dx + 2 * nv * s.nx, dy + 2 * nv * s.ny, dz + 2 * nv * s.nz, rough, sl);
    for (let c = 0; c < 3; c++) out[c] = w[3 + c] * dl[c] + w[c] * sl[c] + m.emissive[c];
    clampBounce(out);
  }

  // A few glossy rays that meet a thin, very bright part (a beam) flash single pixels white: what a secondary
  // hit returns is held to BOUNCE_MAX in its brightest channel, hue kept.
  const BOUNCE_MAX = 2.0;
  function clampBounce(out) {
    const peak = Math.max(out[0], out[1], out[2]);
    if (peak > BOUNCE_MAX) { const k = BOUNCE_MAX / peak; out[0] *= k; out[1] *= k; out[2] *= k; }
  }

  // The visible share of each softbox from (ox, oy, oz) with normal n, into ctx.vis (soft shadows).
  function visibility(ctx, ox, oy, oz, nx, ny, nz, cp, sp) {
    const { bvh, opaque, env, vis } = ctx;
    for (let j = 0; j < env.lobes.length; j++) {
      const L = ctx.shadowDirs[j], f = L.f, d = L.d, S = L.s, half = 3 * Math.ceil(S.length / 6);
      let seen = 0, total = 0, lit = 0, dark = 0;
      for (let k = 0; k < S.length; k += 3) {
        // the first half all lit or all dark: the light is open or shut here, the rest cannot change it
        if (k === half && (lit === 0 || dark === 0) && lit + dark >= 2) break;
        const a = S[k] * cp - S[k + 1] * sp, b = S[k] * sp + S[k + 1] * cp, c = S[k + 2];
        const lx = f[0] * a + f[3] * b + d[0] * c, ly = f[1] * a + f[4] * b + d[1] * c, lz = f[2] * a + f[5] * b + d[2] * c;
        const weight = nx * lx + ny * ly + nz * lz;
        if (weight <= 0) continue;
        total += weight;
        if (occluded(bvh, ox, oy, oz, lx, ly, lz, Infinity, opaque)) { dark++; continue; }
        seen += ctx.glass && occluded(bvh, ox, oy, oz, lx, ly, lz, Infinity, ctx.glass) ? weight * GLASS_SHADOW : weight;
        lit++;
      }
      vis[j] = total > 0 ? seen / total : 0;
    }
  }

  // How much of the open light a floor point loses to the parts: 0 open, 1 fully shadowed.
  function floorShadow(ctx, s, key) {
    const { env, tables, vis, rays } = ctx, ox = s.px, oy = s.py + ctx.bias, oz = s.pz;
    const phase = hash(key) * 2 * Math.PI, cp = Math.cos(phase), sp = Math.sin(phase);
    visibility(ctx, ox, oy, oz, 0, 1, 0, cp, sp);
    let open = env.ambient[1], lit = 0;
    for (let j = 0; j < env.lobes.length; j++) {
      const w = sampleTable(tables.diffuse[j], 0, 1, 0) * env.lobes[j].color[1];
      open += w; lit += w * vis[j];
    }
    let blocked = 0;
    for (let i = 0; i < rays.fill; i++) {                 // contact shadow: the ambient the parts close off
      const phi = (2 * Math.PI * i) / rays.fill + phase;
      if (occluded(ctx.bvh, ox, oy, oz, 0.7 * Math.cos(phi), 0.714, 0.7 * Math.sin(phi), ctx.contact, ctx.opaque)) blocked++;
    }
    lit += env.ambient[1] * (rays.fill ? 1 - blocked / rays.fill : 1);
    return Math.max(0, Math.min(1, 1 - lit / open));
  }

  // Light that leaves surface ``s`` toward a ray of direction d: shadowed softboxes, fill, reflections.
  function shade(ctx, s, dx, dy, dz, key, out) {
    const m = ctx.data.materials[s.mi];
    if (m.unlit) { out[0] = s.base[0]; out[1] = s.base[1]; out[2] = s.base[2]; return; }
    const { bvh, opaque, env, tables, rays, vis } = ctx, nx = s.nx, ny = s.ny, nz = s.nz;
    const nv = Math.max(1e-3, -(nx * dx + ny * dy + nz * dz));
    const rx = dx + 2 * nv * nx, ry = dy + 2 * nv * ny, rz = dz + 2 * nv * nz;
    const rough = Math.max(0.04, Math.min(1, m.rough)), metal = m.metal, w = ctx.w;
    weights(tables, s.base, metal, rough, nv, w);
    const ox = s.px + s.gx * ctx.bias, oy = s.py + s.gy * ctx.bias, oz = s.pz + s.gz * ctx.bias;
    const phase = hash(key) * 2 * Math.PI, cp = Math.cos(phase), sp = Math.sin(phase);
    visibility(ctx, ox, oy, oz, nx, ny, nz, cp, sp);
    const dl = ctx.dl, sl = ctx.sl;
    diffuseLight(tables, env, nx, ny, nz, dl, vis);
    let r = w[3] * dl[0], g = w[4] * dl[1], b = w[5] * dl[2];
    specularLight(env, rx, ry, rz, rough, sl, vis);
    let sr = w[0] * sl[0], sg = w[1] * sl[1], sb = w[2] * sl[2];
    const f = frame(nx, ny, nz), c2 = ctx.c2, amb = env.ambient;
    if (metal < 1 && rays.fill > 0) {                   // fill: blocked ambient becomes light from the hit
      let blocked = 0, fr = 0, fg = 0, fb = 0;
      for (let i = 0; i < rays.fill; i++) {
        const phi = (2 * Math.PI * i) / rays.fill + phase, a = 0.7 * Math.cos(phi), bb = 0.7 * Math.sin(phi), c = 0.714;
        const lx = f[0] * a + f[3] * bb + nx * c, ly = f[1] * a + f[4] * bb + ny * c, lz = f[2] * a + f[5] * bb + nz * c;
        if (closestHit(bvh, ox, oy, oz, lx, ly, lz, Infinity, ctx.hit2, opaque)) {
          blocked++;
          bounce(ctx, ox, oy, oz, lx, ly, lz, c2);
          fr += c2[0] - amb[0]; fg += c2[1] - amb[1]; fb += c2[2] - amb[2];
        }
      }
      if (blocked) { r += (w[3] * fr) / rays.fill; g += (w[4] * fg) / rays.fill; b += (w[5] * fb) / rays.fill; }
    }
    // reflections where they show: all rays on metal, half on smooth dielectrics, none on rough ones (their
    // 4% specular takes the open studio light)
    const nr = metal > 0.5 ? rays.reflect : rough < 0.35 ? Math.ceil(rays.reflect / 2) : 0;
    if (nr > 0) {                                        // GGX rays with one secondary hit
      const rf = frame(rx, ry, rz), a2 = rough * rough * rough * rough;
      let hitW = 0, totW = 0, br = 0, bg = 0, bb = 0;
      for (let i = 0; i < nr; i++) {
        const u = (i + 0.5) / nr, phi = 2 * Math.PI * radicalInverse(i) + phase;
        const ch = Math.sqrt((1 - u) / (1 + (a2 - 1) * u)), sh = Math.sqrt(1 - ch * ch);
        const hx = rf[0] * sh * Math.cos(phi) + rf[3] * sh * Math.sin(phi) + rx * ch;
        const hy = rf[1] * sh * Math.cos(phi) + rf[4] * sh * Math.sin(phi) + ry * ch;
        const hz = rf[2] * sh * Math.cos(phi) + rf[5] * sh * Math.sin(phi) + rz * ch;
        const lx = 2 * ch * hx - rx, ly = 2 * ch * hy - ry, lz = 2 * ch * hz - rz;
        const weight = Math.max(0, rx * lx + ry * ly + rz * lz);
        totW += weight;
        if (weight === 0 || nx * lx + ny * ly + nz * lz <= 0) continue;
        if (closestHit(bvh, ox, oy, oz, lx, ly, lz, Infinity, ctx.hit2, opaque)) {
          hitW += weight;
          bounce(ctx, ox, oy, oz, lx, ly, lz, c2);
          br += c2[0] * weight; bg += c2[1] * weight; bb += c2[2] * weight;
        }
      }
      if (totW > 0 && hitW > 0) {
        const open = 1 - hitW / totW;
        sr = sr * open + (w[0] * br) / totW; sg = sg * open + (w[1] * bg) / totW; sb = sb * open + (w[2] * bb) / totW;
      }
    }
    out[0] = r + sr + m.emissive[0]; out[1] = g + sg + m.emissive[1]; out[2] = b + sb + m.emissive[2];
  }

  // Light along the mirror direction of a smooth surface: one ray, its hit's open light, else the studio.
  function mirror(ctx, s, dx, dy, dz, rough, out) {
    const nv = Math.max(1e-3, -(s.nx * dx + s.ny * dy + s.nz * dz));
    const rx = dx + 2 * nv * s.nx, ry = dy + 2 * nv * s.ny, rz = dz + 2 * nv * s.nz;
    const ox = s.px + s.gx * ctx.bias, oy = s.py + s.gy * ctx.bias, oz = s.pz + s.gz * ctx.bias;
    if (closestHit(ctx.bvh, ox, oy, oz, rx, ry, rz, Infinity, ctx.hit2, ctx.opaque)) bounce(ctx, ox, oy, oz, rx, ry, rz, out);
    else { specularLight(ctx.env, rx, ry, rz, rough, out); clampBounce(out); }
  }

  // A camera ray through up to 8 surfaces: premultiplied linear RGB and coverage into out[0..3]. Glass
  // splits the ray (Fresnel): the reflected part is added, the refracted ray goes on, tinted.
  function trace(ctx, ox, oy, oz, dx, dy, dz, key, out) {
    const s = ctx.s1, c = ctx.c, hit = ctx.hit, first = ctx.first;
    let r = 0, g = 0, b = 0, tr = 1, tg = 1, tb = 1, er = 0, eg = 0, eb = 0;
    first.id = 0;
    const F = ctx.floor;
    for (let depth = 0; depth < 8 && tr + tg + tb > 0.012; depth++) {
      const found = closestHit(ctx.bvh, ox, oy, oz, dx, dy, dz, Infinity, hit);
      if (F && dy < 0) {                                   // the floor, when it comes before any part
        const tf = (F.y - oy) / dy;
        if (tf > T_MIN && (!found || tf < hit.t)) {
          s.px = ox + dx * tf; s.py = F.y; s.pz = oz + dz * tf;
          const dist = Math.hypot(s.px - F.cx, s.pz - F.cz);
          const fade = dist <= F.r0 ? 1 : dist >= F.r1 ? 0 : 0.5 + 0.5 * Math.cos(Math.PI * (dist - F.r0) / (F.r1 - F.r0));
          if (depth === 0) { first.id = F.mi + 1; first.t = tf; first.nx = 0; first.ny = 1; first.nz = 0; first.r = first.g = first.b = 0.6; }
          if (fade > 0) {
            s.nx = 0; s.ny = 1; s.nz = 0; s.gx = 0; s.gy = 1; s.gz = 0; s.mi = F.mi; s.alpha = 1; s.front = true;
            const fm = ctx.data.materials[F.mi];
            s.base[0] = fm.base[0]; s.base[1] = fm.base[1]; s.base[2] = fm.base[2];
            if (F.mode === 'studio') {
              shade(ctx, s, dx, dy, dz, key + depth * 0x9e3779b9, c);
              r += tr * fade * c[0]; g += tg * fade * c[1]; b += tb * fade * c[2];
              tr *= 1 - fade; tg *= 1 - fade; tb *= 1 - fade;
            } else {
              const a = fade * floorShadow(ctx, s, key + depth * 0x9e3779b9);
              tr *= 1 - a; tg *= 1 - a; tb *= 1 - a;
            }
          }
          break;                                         // nothing lies under the floor
        }
      }
      if (!found) break;
      surface(ctx, ox, oy, oz, dx, dy, dz, hit, s);
      const m = ctx.data.materials[s.mi];
      if (depth === 0) {                                  // the denoiser's guide: what this pixel looks at
        first.id = s.mi + 1; first.t = hit.t; first.nx = s.nx; first.ny = s.ny; first.nz = s.nz;
        first.r = s.base[0]; first.g = s.base[1]; first.b = s.base[2];
      }
      if (m.transmission > 0) {
        const t = Math.min(1, m.transmission), cosi = Math.max(0, -(dx * s.nx + dy * s.ny + dz * s.nz));
        const f0 = ((m.ior - 1) / (m.ior + 1)) ** 2, F = f0 + (1 - f0) * Math.pow(1 - cosi, 5);
        if (t < 1) {                                      // the part of the surface that is not clear
          shade(ctx, s, dx, dy, dz, key + depth * 0x9e3779b9, c);
          r += tr * (1 - t) * c[0]; g += tg * (1 - t) * c[1]; b += tb * (1 - t) * c[2];
        }
        mirror(ctx, s, dx, dy, dz, Math.max(0.04, m.rough), c);
        r += tr * t * F * c[0]; g += tg * t * F * c[1]; b += tb * t * F * c[2];
        const eta = s.front ? 1 / m.ior : m.ior;
        const d2 = refract([dx, dy, dz], [s.gx, s.gy, s.gz], eta);
        if (!d2) {                                         // total internal reflection: the ray stays inside
          const k = 2 * (dx * s.gx + dy * s.gy + dz * s.gz);
          dx -= k * s.gx; dy -= k * s.gy; dz -= k * s.gz;
          ox = s.px + s.gx * ctx.bias; oy = s.py + s.gy * ctx.bias; oz = s.pz + s.gz * ctx.bias;
          continue;
        }
        const w = t * (1 - F);
        tr *= w * Math.sqrt(s.base[0]); tg *= w * Math.sqrt(s.base[1]); tb *= w * Math.sqrt(s.base[2]);
        dx = d2[0]; dy = d2[1]; dz = d2[2];
        ox = s.px - s.gx * ctx.bias; oy = s.py - s.gy * ctx.bias; oz = s.pz - s.gz * ctx.bias;
        continue;
      }
      const cover = s.alpha;
      if (cover > 0.002) {
        shade(ctx, s, dx, dy, dz, key + depth * 0x9e3779b9, c);
        r += tr * cover * c[0]; g += tg * cover * c[1]; b += tb * cover * c[2];
        const e = m.emissive;
        if (e[0] + e[1] + e[2] > 0) { er += tr * cover * e[0]; eg += tg * cover * e[1]; eb += tb * cover * e[2]; }
      }
      tr *= 1 - cover; tg *= 1 - cover; tb *= 1 - cover;
      ox = s.px + dx * ctx.bias; oy = s.py + dy * ctx.bias; oz = s.pz + dz * ctx.bias;
    }
    out[0] = r; out[1] = g; out[2] = b; out[3] = 1 - (tr + tg + tb) / 3; out[4] = er; out[5] = eg; out[6] = eb;
  }

  // Per-pixel guide for the denoiser and the glow source, tile- or image-sized: material id (0 = nothing),
  // depth, normal (x127), albedo (x255) of the first sample's first surface; emitted light seen (premultiplied).
  function newGBuffer(w, h) {
    return { id: new Uint16Array(w * h), depth: new Float32Array(w * h), normal: new Int8Array(w * h * 3),
             albedo: new Uint8Array(w * h * 3), emit: new Float32Array(w * h * 3) };
  }

  // Pixels [x0, x0 + tw) x [y0, y0 + th) of the image into buf (premultiplied linear RGBA, tile order), and
  // into the guide buffer ``gb`` when given. A pixel's samples depend only on its place in the whole image,
  // so any tiling gives the same numbers.
  function renderTile(ctx, x0, y0, tw, th, buf, gb) {
    const D = ctx.data, W = D.width, H = D.height, cam = D.camera, S = Math.max(1, D.samples | 0);
    const g = Math.max(1, Math.round(Math.sqrt(S))), n = g * g, px = new Float64Array(7), first = ctx.first;
    const tx = cam.tanHalfY * cam.aspect, ty = cam.tanHalfY;
    for (let y = y0; y < y0 + th; y++) for (let x = x0; x < x0 + tw; x++) {
      let r = 0, gg = 0, b = 0, a = 0, er = 0, eg = 0, eb = 0;
      const o = (y - y0) * tw + (x - x0);
      for (let k = 0; k < n; k++) {
        const sx = ((k % g) + 0.5) / g, sy = (Math.floor(k / g) + 0.5) / g;
        const nx = ((x + sx) / W) * 2 - 1, ny = 1 - ((y + sy) / H) * 2;
        let dx = -cam.back[0] + nx * tx * cam.right[0] + ny * ty * cam.up[0];
        let dy = -cam.back[1] + nx * tx * cam.right[1] + ny * ty * cam.up[1];
        let dz = -cam.back[2] + nx * tx * cam.right[2] + ny * ty * cam.up[2];
        const l = Math.hypot(dx, dy, dz); dx /= l; dy /= l; dz /= l;
        trace(ctx, cam.position[0], cam.position[1], cam.position[2], dx, dy, dz, ((y * W + x) * n + k) * 8, px);
        r += px[0]; gg += px[1]; b += px[2]; a += px[3]; er += px[4]; eg += px[5]; eb += px[6];
        if (k === 0 && gb) {
          gb.id[o] = first.id; gb.depth[o] = first.id ? first.t : 0;
          gb.normal[o * 3] = Math.round(first.nx * 127); gb.normal[o * 3 + 1] = Math.round(first.ny * 127);
          gb.normal[o * 3 + 2] = Math.round(first.nz * 127);
          gb.albedo[o * 3] = Math.round(Math.min(1, first.r) * 255); gb.albedo[o * 3 + 1] = Math.round(Math.min(1, first.g) * 255);
          gb.albedo[o * 3 + 2] = Math.round(Math.min(1, first.b) * 255);
        }
      }
      buf[o * 4] = r / n; buf[o * 4 + 1] = gg / n; buf[o * 4 + 2] = b / n; buf[o * 4 + 3] = a / n;
      if (gb) { gb.emit[o * 3] = er / n; gb.emit[o * 3 + 1] = eg / n; gb.emit[o * 3 + 2] = eb / n; }
    }
  }

  // A 5 x 5 binomial filter over premultiplied RGB that mixes only solid pixels showing the same material
  // at a depth within 2%, a normal within ~11 degrees and an albedo within 0.03 (texture detail stays).
  function denoise(buf, W, H, G) {
    const K = [1, 4, 6, 4, 1], src = Float32Array.from(buf), floorId = G.floor || 0;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = y * W + x, id = G.id[i];
      if (id && id === floorId) { floorPixel(src, buf, W, H, G, x, y, K); continue; }
      if (!id || src[i * 4 + 3] < 0.999) continue;
      const d = G.depth[i], n0 = G.normal[i * 3], n1 = G.normal[i * 3 + 1], n2 = G.normal[i * 3 + 2];
      const a0 = G.albedo[i * 3], a1 = G.albedo[i * 3 + 1], a2 = G.albedo[i * 3 + 2];
      let r = 0, g = 0, b = 0, total = 0;
      for (let dy = -2; dy <= 2; dy++) {
        const yy = y + dy;
        if (yy < 0 || yy >= H) continue;
        for (let dx = -2; dx <= 2; dx++) {
          const xx = x + dx;
          if (xx < 0 || xx >= W) continue;
          const j = yy * W + xx;
          if (G.id[j] !== id || src[j * 4 + 3] < 0.999 || Math.abs(G.depth[j] - d) > d * 0.02) continue;
          if (n0 * G.normal[j * 3] + n1 * G.normal[j * 3 + 1] + n2 * G.normal[j * 3 + 2] < 0.98 * 127 * 127) continue;
          if (Math.abs(a0 - G.albedo[j * 3]) + Math.abs(a1 - G.albedo[j * 3 + 1]) + Math.abs(a2 - G.albedo[j * 3 + 2]) > 0.03 * 255) continue;
          const w = K[dy + 2] * K[dx + 2];
          total += w; r += src[j * 4] * w; g += src[j * 4 + 1] * w; b += src[j * 4 + 2] * w;
        }
      }
      buf[i * 4] = r / total; buf[i * 4 + 1] = g / total; buf[i * 4 + 2] = b / total;
    }
  }

  // A floor (or shadow catcher) pixel: all four channels from floor neighbours at a depth within 2%.
  function floorPixel(src, buf, W, H, G, x, y, K) {
    const i = y * W + x, id = G.id[i], d = G.depth[i];
    let r = 0, g = 0, b = 0, a = 0, total = 0;
    for (let dy = -2; dy <= 2; dy++) {
      const yy = y + dy;
      if (yy < 0 || yy >= H) continue;
      for (let dx = -2; dx <= 2; dx++) {
        const xx = x + dx;
        if (xx < 0 || xx >= W) continue;
        const j = yy * W + xx;
        if (G.id[j] !== id || Math.abs(G.depth[j] - d) > d * 0.02) continue;
        const w = K[dy + 2] * K[dx + 2];
        total += w; r += src[j * 4] * w; g += src[j * 4 + 1] * w; b += src[j * 4 + 2] * w; a += src[j * 4 + 3] * w;
      }
    }
    buf[i * 4] = r / total; buf[i * 4 + 1] = g / total; buf[i * 4 + 2] = b / total; buf[i * 4 + 3] = a / total;
  }

  // Bloom on emitted light only: ``emit`` is half resolution (W/2 x H/2 x 3); a separable Gaussian of
  // ``sigma`` half-res pixels, scaled by ``strength``, is added to the image (and to its coverage).
  function glow(buf, emit, W, H, strength, sigma) {
    const w = Math.max(1, W >> 1), h = Math.max(1, H >> 1), R = Math.ceil(3 * sigma);
    const kernel = new Float64Array(2 * R + 1);
    let sum = 0;
    for (let k = -R; k <= R; k++) { kernel[k + R] = Math.exp(-(k * k) / (2 * sigma * sigma)); sum += kernel[k + R]; }
    for (let k = 0; k < kernel.length; k++) kernel[k] /= sum;
    const tmp = new Float32Array(w * h * 3), out = new Float32Array(w * h * 3);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) for (let c = 0; c < 3; c++) {
      let v = 0;
      for (let k = -R; k <= R; k++) { const xx = Math.min(w - 1, Math.max(0, x + k)); v += emit[(y * w + xx) * 3 + c] * kernel[k + R]; }
      tmp[(y * w + x) * 3 + c] = v;
    }
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) for (let c = 0; c < 3; c++) {
      let v = 0;
      for (let k = -R; k <= R; k++) { const yy = Math.min(h - 1, Math.max(0, y + k)); v += tmp[(yy * w + x) * 3 + c] * kernel[k + R]; }
      out[(y * w + x) * 3 + c] = v;
    }
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const j = (Math.min(h - 1, y >> 1) * w + Math.min(w - 1, x >> 1)) * 3, i = (y * W + x) * 4;
      const gr = strength * out[j], gg = strength * out[j + 1], gb = strength * out[j + 2];
      buf[i] += gr; buf[i + 1] += gg; buf[i + 2] += gb;
      buf[i + 3] = Math.min(1, buf[i + 3] + Math.max(gr, gg, gb));
    }
  }

  function neutral(c, out) {              // Khronos PBR Neutral, as three.js NeutralToneMapping
    let r = c[0], g = c[1], b = c[2];
    const x = Math.min(r, g, b), offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
    r -= offset; g -= offset; b -= offset;
    const peak = Math.max(r, g, b), start = 0.76;
    if (peak < start) { out[0] = r; out[1] = g; out[2] = b; return; }
    const d = 1 - start, newPeak = 1 - (d * d) / (peak + d - start), k = newPeak / peak;
    const mix = 1 - 1 / (0.15 * (peak - newPeak) + 1);
    out[0] = r * k * (1 - mix) + newPeak * mix; out[1] = g * k * (1 - mix) + newPeak * mix; out[2] = b * k * (1 - mix) + newPeak * mix;
  }

  function encode(v) {
    v = Math.max(0, Math.min(1, v));
    return Math.round(255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055));
  }

  // Premultiplied linear RGBA -> 8-bit sRGB RGBA: exposure, tone mapping, then over the background
  // (``background`` null keeps the alpha; else {top: [r, g, b], bottom: [r, g, b]} in 0..255).
  function toDisplay(buf, W, H, exposure, background) {
    const out = new Uint8ClampedArray(W * H * 4), c = [0, 0, 0], t = [0, 0, 0];
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4, a = buf[i + 3];
      let r = 0, g = 0, b = 0;
      if (a > 1e-6) {
        c[0] = (buf[i] / a) * exposure; c[1] = (buf[i + 1] / a) * exposure; c[2] = (buf[i + 2] / a) * exposure;
        neutral(c, t);
        r = encode(t[0]); g = encode(t[1]); b = encode(t[2]);
      }
      if (background) {
        const f = H > 1 ? y / (H - 1) : 0, top = background.top, bot = background.bottom;
        out[i] = r * a + (top[0] + (bot[0] - top[0]) * f) * (1 - a);
        out[i + 1] = g * a + (top[1] + (bot[1] - top[1]) * f) * (1 - a);
        out[i + 2] = b * a + (top[2] + (bot[2] - top[2]) * f) * (1 - a);
        out[i + 3] = 255;
      } else {
        out[i] = r; out[i + 1] = g; out[i + 2] = b; out[i + 3] = Math.round(255 * a);
      }
    }
    return out;
  }

  return { buildBVH, newHit, closestHit, occluded, buildTables, diffuseLight, specularLight, shadeOpen, frame,
           radicalInverse, weights, studioEnv, prebuild, prepareScene, renderTile, toDisplay, hash, refract,
           newGBuffer, denoise, glow };
}
var odStudioCore = odStudioCoreFactory();
