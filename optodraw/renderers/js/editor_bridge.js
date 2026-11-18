
(function () {
  // The editor toolbar hosts the animation controls; hide the in-scene panel.
  // CSS !important beats any later inline style toggles — no load-order race.
  window.__odEditorOwnsAnimUI = true;
  document.head.insertAdjacentHTML('beforeend', '<style>#anim-section{display:none !important}</style>');
  // The toolbar owns the animation and it starts off: hold the engine before the first frame, so a reload
  // shows no light until the editor sends its state (after 'optodraw-ready').
  if (window.odLight && window.odLight.setEnabled) window.odLight.setEnabled(false);
  const pk = () => window.__odPickables || []; // read fresh (rebuilt in place)
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let down = null;
  let highlightId = null;
  const saved = new Set();

  function meshesFor(id) {
    const out = [];
    for (const anchor of pk()) {
      if (!id || anchor.userData.componentId !== id) continue;
      anchor.traverse((o) => {
        const materials = Array.isArray(o.material) ? o.material : [o.material];
        if (o.isMesh && materials.some(m => m && m.emissive)) out.push(o);
      });
    }
    return out;
  }
  function applyHighlight(id) {
    saved.forEach(m => odHighlightMaterial(m, false));
    saved.clear();
    highlightId = id || null;
    if (highlightId) {
      for (const m of meshesFor(highlightId)) {
        odHighlightMaterial(m, true);
        saved.add(m);
      }
    }
  }

  function pick(e) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(pk(), true);
    if (!hits.length) return null;
    let o = hits[0].object;
    while (o && !o.userData.componentId) o = o.parent;
    return o ? o.userData.componentId : null;
  }

  renderer.domElement.addEventListener('pointerdown', (e) => {
    down = e.button === 0 ? { x: e.clientX, y: e.clientY } : null;
  });
  renderer.domElement.addEventListener('pointercancel', () => { down = null; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!down) return;
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
    down = null;
    if (moved > 5) return; // treat as an orbit drag, not a click
    const id = pick(e);
    applyHighlight(id);
    if (window.parent) window.parent.postMessage({ type: 'optodraw-select', id: id }, '*');
  });

  // --- transform gizmo: translate on the optical plane, or rotate (yaw = facing angle) ---
  let gizmo = null;
  let gizmoMode = 'translate';
  const ROT_SNAP = Math.PI / 12; // 15° detents (hold Shift for free rotation)
  function setGizmoMode(mode) {
    if (!gizmo) return;
    gizmoMode = (mode === 'rotate') ? 'rotate' : 'translate';
    if (gizmoMode === 'rotate') {
      gizmo.setMode('rotate');
      gizmo.showX = false; gizmo.showY = true; gizmo.showZ = false; // yaw ring only = the 2D facing angle
      gizmo.rotationSnap = ROT_SNAP;
    } else {
      gizmo.setMode('translate');
      gizmo.showX = true; gizmo.showY = false; gizmo.showZ = true;  // slide on the table plane
      gizmo.rotationSnap = null;
    }
  }
  try {
    gizmo = new TransformControls(camera, renderer.domElement);
    gizmo.size = 0.8;
    setGizmoMode('translate');
    const helper = gizmo.getHelper ? gizmo.getHelper() : gizmo;
    scene.add(helper);
    gizmo.addEventListener('dragging-changed', (ev) => {
      controls.enabled = !ev.value;
      if (!ev.value) { // drag finished -> commit position OR facing angle
        const obj = gizmo.object;
        if (obj && obj.userData.componentId && window.parent) {
          if (gizmoMode === 'rotate') {
            // anchor yaw (rotation.y) maps to the component's 2D angle
            window.parent.postMessage(
              { type: 'optodraw-rotate', id: obj.userData.componentId, angle: obj.rotation.y * 180 / Math.PI }, '*');
          } else {
            // 3D X/Z -> world x/y  (item.position = [x, z, -y])
            window.parent.postMessage(
              { type: 'optodraw-move', id: obj.userData.componentId, center: [obj.position.x, -obj.position.z] }, '*');
          }
        }
      }
    });
    // R = rotate the selected optic to face (snaps to 15°); M/G/T = move; hold Shift = free rotate
    window.addEventListener('keydown', (ev) => {
      const tag = (ev.target && ev.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
          (ev.target && ev.target.isContentEditable) || ev.metaKey || ev.ctrlKey) return;
      const key = ev.key.toLowerCase();
      if (key === 'r') setGizmoMode('rotate');
      else if (key === 'm' || key === 'g' || key === 't') setGizmoMode('translate');
      else if (ev.key === 'Shift' && gizmo) gizmo.rotationSnap = null; // free rotation while held
    });
    window.addEventListener('keyup', (ev) => {
      if (ev.key === 'Shift' && gizmo && gizmoMode === 'rotate') gizmo.rotationSnap = ROT_SNAP;
    });
  } catch (err) { gizmo = null; }

  function attachGizmo(id) {
    if (!gizmo) return;
    const anchor = id ? pk().find((p) => p.userData.componentId === id) : null;
    if (anchor && anchor.userData.movable !== false) gizmo.attach(anchor); else gizmo.detach();
  }
  const _origApplyHighlight = applyHighlight;
  applyHighlight = function (id) { _origApplyHighlight(id); attachGizmo(id); };

  // --- camera persistence ---
  controls.addEventListener('end', () => {
    if (window.parent) {
      window.parent.postMessage({
        type: 'optodraw-camera',
        pos: [camera.position.x, camera.position.y, camera.position.z],
        target: [controls.target.x, controls.target.y, controls.target.z],
      }, '*');
    }
  });

  const finiteVec3 = (value) => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
  let lastItems = null;      // the items of the last rebuild: a light that comes later is placed on them
  window.addEventListener('message', (e) => {
    const d = e.data || {};
    if (d.type === 'optodraw-highlight') {
      applyHighlight(d.id || null);
    } else if (d.type === 'optodraw-rebuild' && Array.isArray(d.items)) {
      const sel = highlightId; // rebuild content in place, then restore selection
      lastItems = d.items;
      // pending: the light comes in a later 'optodraw-light'; the player keeps it on and draws none until then
      if (window.__odRebuild) window.__odRebuild(d.items, d.light || null, !!d.pending);
      saved.clear();
      highlightId = null;
      applyHighlight(sel);
    } else if (d.type === 'optodraw-light' && lastItems) {
      // the light for the items of the last rebuild: only the player builds again
      if (window.odLight) window.odLight.build(d.light || null, lastItems, !!d.pending);
    } else if (d.type === 'optodraw-set-camera' && finiteVec3(d.pos) && finiteVec3(d.target)) {
      camera.position.set(d.pos[0], d.pos[1], d.pos[2]);
      controls.target.set(d.target[0], d.target[1], d.target[2]);
      controls.update();
    } else if (d.type === 'optodraw-zoom' && Number.isFinite(d.factor) && d.factor > 0) {
      // dolly toward/away from the orbit target (zoom buttons in the editor shell)
      camera.position.sub(controls.target).multiplyScalar(d.factor).add(controls.target);
      controls.update();
    } else if (d.type === 'optodraw-anim') {
      if (window.odLight && window.odLight.control) window.odLight.control(d.action, d.value);
    } else if (d.type === 'optodraw-view') {
      // the editor's View and Export menus: the page draws no controls of its own inside the editor
      if (d.action === 'camera') applyCameraPreset(String(d.value));
      else if (d.action === 'world') applyWorld(String(d.value));
      else if (d.action === 'table') {
        const color = String(d.value);
        if (window.__odDieMat) window.__odDieMat.color.set(color); else if (tableMat) tableMat.color.set(color);
      }
      else if (d.action === 'labels') setLabels(!!d.value);
      else if (d.action === 'fullscreen') odToggleFullscreen();
      else if (d.action === 'photoreal') odStartRender();
      else if (d.action === 'png') downloadPngScreenshot();
      else if (d.action === 'png-clear') {
        const before = _world;
        applyWorld('none');
        downloadPngScreenshot();
        applyWorld(before);
      }
      else if (d.action === 'json') downloadSceneJson();
    } else if (d.type === 'optodraw-fit') {
      if (window.__odHome) {
        camera.position.copy(window.__odHome.pos);
        controls.target.copy(window.__odHome.target);
        controls.update();
      }
    } else if (d.type === 'optodraw-export-glb') {
      // GLTFExporter is only imported when the scene is geometry-exportable.
      if (typeof GLTFExporter === 'undefined') return;
      const target = (typeof odContent !== 'undefined') ? odContent : scene;
      // the light is a live shader effect, not exportable geometry; the tour's see-through copies stay out too
      const light = window.odLight;
      if (light && light.control) light.control('tour', false);
      const lightGroup = light && light.state ? light.state.group : null;
      const wasEnabled = light && light.state ? light.state.enabled : false;
      const wasVisible = lightGroup ? lightGroup.visible : false;
      if (lightGroup) { light.state.enabled = false; lightGroup.visible = false; }
      const release = () => {
        if (lightGroup) { light.state.enabled = wasEnabled; lightGroup.visible = wasVisible; }
      };
      const onError = (error) => {
        release();
        console.error('Optodraw GLB export failed', error);
      };
      try {
        new GLTFExporter().parse(target, (result) => {
          release();
          const buf = (result instanceof ArrayBuffer)
            ? result : new TextEncoder().encode(JSON.stringify(result)).buffer;
          if (window.parent) window.parent.postMessage({ type: 'optodraw-glb', buffer: buf }, '*');
        }, onError, { binary: true });
      } catch (error) {
        onError(error);
      }
    }
  });
  // the tour turns the light on while it plays and gives it back after: the editor's toolbar shows the real state
  window.addEventListener('odtour', (e) => {
    if (window.parent) window.parent.postMessage({ type: 'optodraw-tour', playing: !!(e.detail && e.detail.playing) }, '*');
  });
  if (window.parent) window.parent.postMessage({ type: 'optodraw-ready' }, '*');
})();
