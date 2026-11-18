/* optodraw studio renderer: the page side.
 *
 * Reads the scene the viewer built (visible meshes, their world matrices and materials) into the flat
 * arrays that studio_core.js renders, renders it in tiles and returns a PNG data URL. Lines, points,
 * sprites and shader materials (the animation layer) are not part of a studio image.
 */
var odStudio = (function () {
  'use strict';

  function usable(material) {
    return material && material.visible !== false && !material.isShaderMaterial && !material.isRawShaderMaterial
      && !material.isLineBasicMaterial && !material.isPointsMaterial && !material.isSpriteMaterial;
  }

  function textureData(texture) {           // the texture's pixels as sRGB bytes, or null when unreadable
    const image = texture && texture.image;
    if (!image || !image.width || !image.height) return null;
    try {
      const canvas = document.createElement('canvas');
      canvas.width = image.width; canvas.height = image.height;
      const g = canvas.getContext('2d');
      g.drawImage(image, 0, 0);
      return { width: image.width, height: image.height, data: g.getImageData(0, 0, image.width, image.height).data };
    } catch (error) {
      return null;                            // a tainted image: the part keeps its plain colour
    }
  }

  function extract(THREE, scene, camera, opts) {
    scene.updateMatrixWorld(true);
    camera.updateMatrixWorld(true);
    const pos = [], nor = [], uv = [], mat = [], materials = [], textures = [];
    const materialIds = new Map(), textureIds = new Map();
    let anyNormals = false, anyUVs = false;
    const v = new THREE.Vector3(), n = new THREE.Vector3(), normalMatrix = new THREE.Matrix3();
    const world = new THREE.Matrix4(), instance = new THREE.Matrix4(), tint = new THREE.Color();

    function textureId(texture) {
      if (textureIds.has(texture)) return textureIds.get(texture);
      const pixels = textureData(texture);
      let id = -1;
      if (pixels) {
        const repeat = (w) => w === THREE.RepeatWrapping || w === THREE.MirroredRepeatWrapping;
        id = textures.length;
        textures.push({ width: pixels.width, height: pixels.height, data: pixels.data, flipY: texture.flipY !== false,
                        wrapS: repeat(texture.wrapS) ? 'repeat' : 'clamp', wrapT: repeat(texture.wrapT) ? 'repeat' : 'clamp' });
      }
      textureIds.set(texture, id);
      return id;
    }

    function materialId(material, color) {
      const key = material.uuid + (color ? ':' + color.getHexString() : '');
      if (materialIds.has(key)) return materialIds.get(key);
      const base = material.color ? [material.color.r, material.color.g, material.color.b] : [1, 1, 1];
      if (color) { base[0] *= color.r; base[1] *= color.g; base[2] *= color.b; }
      const e = material.emissive, ei = material.emissiveIntensity ?? 1;
      const rough = material.roughness ?? (material.shininess != null ? Math.sqrt(2 / (material.shininess + 2)) : 1);
      const entry = {
        base, metal: material.metalness ?? 0, rough,
        emissive: e ? [e.r * ei, e.g * ei, e.b * ei] : [0, 0, 0],
        opacity: material.transparent ? material.opacity : 1,
        transmission: material.transmission || 0, ior: material.ior || 1.5,
        unlit: !!material.isMeshBasicMaterial, texture: -1, uvMatrix: null,
      };
      if (material.map) {
        entry.texture = textureId(material.map);
        if (entry.texture >= 0) { material.map.updateMatrix(); entry.uvMatrix = Array.from(material.map.matrix.elements); }
      }
      const id = materials.length;
      materials.push(entry);
      materialIds.set(key, id);
      return id;
    }

    scene.traverseVisible((obj) => {
      if (!obj.isMesh || obj.isSkinnedMesh) return;
      if (obj.userData && obj.userData.odStudioFloor) return;   // the viewer's floor: the studio has an exact one
      const geo = obj.geometry, P = geo && geo.attributes.position;
      if (!P) return;
      const list = Array.isArray(obj.material) ? obj.material : [obj.material];
      if (!list.some(usable)) return;
      const index = geo.index, N = geo.attributes.normal, U = geo.attributes.uv;
      const start = geo.drawRange.start, total = Math.min(index ? index.count : P.count, start + geo.drawRange.count);
      // three.js uses a geometry's groups only with a material list; one material draws every triangle
      const groups = Array.isArray(obj.material) && geo.groups.length ? geo.groups
        : [{ start, count: total - start, materialIndex: 0 }];
      const copies = obj.isInstancedMesh ? obj.count : 1;
      for (let c = 0; c < copies; c++) {
        world.copy(obj.matrixWorld);
        if (obj.isInstancedMesh) { obj.getMatrixAt(c, instance); world.multiply(instance); }
        normalMatrix.getNormalMatrix(world);
        const color = obj.isInstancedMesh && obj.instanceColor ? (obj.getColorAt(c, tint), tint) : null;
        for (const group of groups) {
          const material = list[group.materialIndex || 0];
          if (!usable(material)) continue;
          const id = materialId(material, color);
          const end = Math.min(group.start + group.count, total);
          for (let k = group.start; k + 2 < end; k += 3) {
            for (let corner = 0; corner < 3; corner++) {
              const i = index ? index.getX(k + corner) : k + corner;
              v.fromBufferAttribute(P, i).applyMatrix4(world);
              pos.push(v.x, v.y, v.z);
              if (N) { n.fromBufferAttribute(N, i).applyMatrix3(normalMatrix).normalize(); nor.push(n.x, n.y, n.z); anyNormals = true; }
              else nor.push(0, 0, 0);
              if (U) { uv.push(U.getX(i), U.getY(i)); anyUVs = true; } else uv.push(0, 0);
            }
            mat.push(id);
          }
        }
      }
    });

    let floor = null;                                   // under the lowest part: a studio floor or a shadow catcher
    if (opts.floor && pos.length) {
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, z0 = Infinity, z1 = -Infinity;
      for (let i = 0; i < pos.length; i += 3) {
        x0 = Math.min(x0, pos[i]); x1 = Math.max(x1, pos[i]); y0 = Math.min(y0, pos[i + 1]);
        z0 = Math.min(z0, pos[i + 2]); z1 = Math.max(z1, pos[i + 2]);
      }
      const R = Math.max(1e-6, 0.5 * Math.hypot(x1 - x0, z1 - z0));
      const lin = (c) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      floor = { y: y0, mode: opts.floor, center: [(x0 + x1) / 2, (z0 + z1) / 2], fade: [0.75 * R, 1.6 * R],
                color: opts.floorColor ? hexRGB(opts.floorColor).map(lin) : null };
    }
    const e = camera.matrixWorld.elements;
    return {
      floor,
      positions: Float64Array.from(pos), normals: anyNormals ? Float32Array.from(nor) : null,
      uvs: anyUVs ? Float32Array.from(uv) : null, material: Uint16Array.from(mat), materials, textures,
      camera: { position: [e[12], e[13], e[14]], right: [e[0], e[1], e[2]], up: [e[4], e[5], e[6]],
                back: [e[8], e[9], e[10]], tanHalfY: Math.tan((camera.fov * Math.PI) / 360) / (camera.zoom || 1),
                aspect: camera.aspect },
      env: opts.world, width: opts.width, height: opts.height, samples: opts.samples, quality: opts.quality,
    };
  }

  function hexRGB(hex) {
    const v = parseInt(String(hex).replace('#', ''), 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }

  const TILE = 32;
  const WORKER_MAIN = `
    let ctx = null;
    onmessage = (event) => {
      const m = event.data;
      try {
        if (m.type === 'init') { ctx = odStudioCore.prepareScene(m.data, m.built); postMessage({ type: 'ready' }); return; }
        const buf = new Float32Array(m.w * m.h * 4), gb = odStudioCore.newGBuffer(m.w, m.h);
        odStudioCore.renderTile(ctx, m.x, m.y, m.w, m.h, buf, gb);
        postMessage({ type: 'tile', x: m.x, y: m.y, w: m.w, h: m.h, buf, gb },
                    [buf.buffer, gb.id.buffer, gb.depth.buffer, gb.normal.buffer, gb.albedo.buffer, gb.emit.buffer]);
      } catch (error) {
        postMessage({ type: 'error', message: String((error && error.stack) || error) });
      }
    };`;

  function stage(text) {                    // the last stage, for a timeout message
    const el = document.getElementById('od-stage');
    if (el) el.value = text;
    console.debug('od-stage: ' + text);      // reaches the driver even while a long tile blocks the page
  }

  // A finished tile into the image: radiance, the denoiser's guide, emitted light averaged to half size.
  function copyTile(img, m) {
    const W = img.W, w = Math.max(1, W >> 1), h = Math.max(1, img.H >> 1);
    for (let y = 0; y < m.h; y++) {
      const row = (m.y + y) * W + m.x;
      img.buf.set(m.buf.subarray(y * m.w * 4, (y + 1) * m.w * 4), row * 4);
      img.G.id.set(m.gb.id.subarray(y * m.w, (y + 1) * m.w), row);
      img.G.depth.set(m.gb.depth.subarray(y * m.w, (y + 1) * m.w), row);
      img.G.normal.set(m.gb.normal.subarray(y * m.w * 3, (y + 1) * m.w * 3), row * 3);
      img.G.albedo.set(m.gb.albedo.subarray(y * m.w * 3, (y + 1) * m.w * 3), row * 3);
      const hy = Math.min(h - 1, (m.y + y) >> 1);
      for (let x = 0; x < m.w; x++) {
        const j = (hy * w + Math.min(w - 1, (m.x + x) >> 1)) * 3, k = (y * m.w + x) * 3;
        img.emit[j] += m.gb.emit[k] / 4; img.emit[j + 1] += m.gb.emit[k + 1] / 4; img.emit[j + 2] += m.gb.emit[k + 2] / 4;
      }
    }
  }

  function startWorkers(count) {
    const source = 'var odStudioCore = (' + odStudioCoreFactory.toString() + ')();\n' + WORKER_MAIN;
    const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
    try {
      return Array.from({ length: count }, () => new Worker(url));
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
  }

  function renderInWorkers(workers, data, built, tiles, img, opts) {
    return new Promise((resolve, reject) => {
      let next = 0, done = 0, failed = false;
      const finish = (error) => {
        if (failed) return;
        workers.forEach((w) => w.terminate());
        if (error) { failed = true; reject(error); } else resolve();
      };
      const send = (worker) => {
        if (next >= tiles.length) return;
        const [x, y, w, h] = tiles[next++];
        worker.postMessage({ type: 'tile', x, y, w, h });
      };
      for (const worker of workers) {
        worker.onmessage = (event) => {
          const m = event.data;
          if (m.type === 'error') { finish(new Error('a render worker failed: ' + m.message)); return; }
          if (m.type === 'tile') {
            copyTile(img, m);
            done++;
            stage('tile ' + done + ' of ' + tiles.length);
            if (opts.onProgress) opts.onProgress(done, tiles.length);
            if (done === tiles.length) { finish(null); return; }
            if (opts.cancelled && opts.cancelled()) { finish(new Error('cancelled')); return; }
          }
          send(worker);
        };
        worker.onerror = (event) => { event.preventDefault(); finish(new Error('a render worker failed: ' + (event.message || 'unknown error'))); };
        worker.postMessage({ type: 'init', data, built });
      }
    });
  }

  // opts: width, height (pixels), samples, quality, world ('light' | 'dark'), exposure, background
  // (null for a transparent PNG, else {top, bottom} as '#rrggbb'), workers (default: one per core),
  // onProgress(done, total) and cancelled() (true stops the workers) for an interactive render.
  async function render(THREE, scene, camera, opts) {
    stage('reading the scene');
    const data = extract(THREE, scene, camera, opts);
    const W = data.width, H = data.height, buf = new Float32Array(W * H * 4), tiles = [];
    const img = { W, H, buf, G: { id: new Uint16Array(W * H), depth: new Float32Array(W * H), normal: new Int8Array(W * H * 3),
                                   albedo: new Uint8Array(W * H * 3) },
                  emit: new Float32Array(Math.max(1, W >> 1) * Math.max(1, H >> 1) * 3) };
    for (let y = 0; y < H; y += TILE) for (let x = 0; x < W; x += TILE) tiles.push([x, y, Math.min(TILE, W - x), Math.min(TILE, H - y)]);
    stage('preparing');
    img.G.floor = data.floor ? data.materials.length + 1 : 0;      // prepareScene adds the floor material last
    const built = odStudioCore.prebuild(data);      // once: the BVH and the light tables go to every worker
    const cores = opts.workers || navigator.hardwareConcurrency || 4;
    const count = Math.max(1, Math.min(16, cores, Math.ceil(tiles.length / 4)));
    let workers = [];
    try { workers = startWorkers(count); } catch (error) { workers = []; }
    if (workers.length) {
      await renderInWorkers(workers, data, built, tiles, img, opts);
    } else {                                // no workers in this browser: the page renders the tiles itself
      const ctx = odStudioCore.prepareScene(data, built);
      tiles.forEach(([x, y, w, h], i) => {
        const tile = new Float32Array(w * h * 4), gb = odStudioCore.newGBuffer(w, h);
        odStudioCore.renderTile(ctx, x, y, w, h, tile, gb);
        copyTile(img, { x, y, w, h, buf: tile, gb });
        stage('tile ' + (i + 1) + ' of ' + tiles.length);
        if (opts.onProgress) opts.onProgress(i + 1, tiles.length);
      });
    }
    stage('denoising');
    odStudioCore.denoise(buf, W, H, img.G);
    odStudioCore.glow(buf, img.emit, W, H, 0.6, Math.max(1.5, (W >> 1) * 0.004));
    const background = opts.background ? { top: hexRGB(opts.background.top), bottom: hexRGB(opts.background.bottom) } : null;
    const pixels = odStudioCore.toDisplay(buf, W, H, opts.exposure || 1, background);
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    canvas.getContext('2d').putImageData(new ImageData(pixels, W, H), 0, 0);
    return canvas.toDataURL('image/png');
  }

  return { extract, render };
})();
