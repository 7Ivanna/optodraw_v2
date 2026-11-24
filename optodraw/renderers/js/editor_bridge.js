
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
  let highlightId = null;          // the primary selection: the gizmo sits on it
  let selection = [];              // every selected part, the primary first (Shift-click adds and removes)
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
  // ids: the selection, primary first (a single id or null also works)
  function applyHighlight(ids) {
    saved.forEach(m => odHighlightMaterial(m, false));
    saved.clear();
    selection = (Array.isArray(ids) ? ids : [ids]).filter(Boolean);
    highlightId = selection[0] || null;
    for (const id of selection) {
      for (const m of meshesFor(id)) {
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

  // These listeners are added before the gizmo's, so they run first on each press.
  let pressMoved = 0;              // how far the pointer went during the last press: a gizmo "drag" under 4 px is a click
  renderer.domElement.addEventListener('pointerdown', (e) => {
    down = e.button === 0 ? { x: e.clientX, y: e.clientY } : null;
    // Shift-click is for selecting: with Shift held, the move gizmo lets the press through to the part under it
    // (turning keeps Shift for free rotation)
    if (gizmo && e.shiftKey && gizmoMode === 'translate') gizmo.enabled = false;
  });
  renderer.domElement.addEventListener('pointercancel', () => { down = null; if (gizmo) gizmo.enabled = true; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (gizmo && !gizmo.enabled) setTimeout(() => { gizmo.enabled = true; }, 0);
    if (!down) return;
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
    down = null;
    pressMoved = moved;
    if (gizmo && gizmo.dragging) return; // the press was on the gizmo: it moves the part, it does not select
    if (moved > 5) return; // treat as an orbit drag, not a click
    const id = pick(e);
    let ids;
    if (e.shiftKey) {               // Shift-click: add the part to the selection, or take it out
      if (!id) return;
      ids = selection.includes(id) ? selection.filter((s) => s !== id) : [id, ...selection];
    } else {
      ids = id ? [id] : [];
    }
    applyHighlight(ids);
    if (window.parent) window.parent.postMessage({ type: 'optodraw-select', id: ids[0] || null, ids: ids }, '*');
  });

  // --- transform gizmo: move on the table and up (z); turn about the part's own x (X), its own y (Y), or the
  // table's vertical, the facing angle (Z or R) ---
  let gizmo = null;
  let gizmoMode = 'translate';
  let startY = 0;                  // the anchor's height when a move starts: the change is the part's new z
  let startPos = null;             // the primary anchor's position when a move starts
  let startQuat = null;            // and its turn
  let followers = [];              // the other selected parts' anchors and their start positions: they move with it
  const anchorFor = (id) => pk().find((p) => p.userData.componentId === id);
  const ROT_SNAP = Math.PI / 12; // 15° detents (hold Shift for free rotation)
  function setGizmoMode(mode) {
    if (!gizmo) return;
    gizmoMode = (mode === 'rotate' || mode === 'tilt' || mode === 'roll') ? mode : 'translate';
    if (gizmoMode === 'rotate') {
      gizmo.setMode('rotate');
      gizmo.setSpace('world');
      gizmo.showX = false; gizmo.showY = true; gizmo.showZ = false; // yaw ring only = the 2D facing angle
      gizmo.rotationSnap = ROT_SNAP;
    } else if (gizmoMode === 'roll') {
      // the part's own x axis (along its beam) is the anchor's local x: its ring alone
      gizmo.setMode('rotate');
      gizmo.setSpace('local');
      gizmo.showX = true; gizmo.showY = false; gizmo.showZ = false;
      gizmo.rotationSnap = ROT_SNAP;
    } else if (gizmoMode === 'tilt') {
      // the part's own y axis (across the beam, in the table plane) is the anchor's local -z: its ring alone
      gizmo.setMode('rotate');
      gizmo.setSpace('local');
      gizmo.showX = false; gizmo.showY = false; gizmo.showZ = true;
      gizmo.rotationSnap = ROT_SNAP;
    } else {
      gizmo.setMode('translate');
      gizmo.setSpace('world');
      gizmo.showX = true; gizmo.showY = true; gizmo.showZ = true;   // slide on the table, or lift (z)
      gizmo.rotationSnap = null;
    }
  }
  // The anchor's turn as the part's angles: the table frame (z up) is Rz(angle) Ry(rotation_y) Rx(rotation_x);
  // the page's frame is y up with z = -y of the table.
  function tableAngles(obj) {
    obj.updateMatrix();
    const m = new THREE.Matrix4().extractRotation(obj.matrix).elements;   // column-major
    const t = (r, c) => m[c * 4 + r];
    // the table frame's matrix S = P^T M P, P = [[1,0,0],[0,0,1],[0,-1,0]]
    const s = [[t(0, 0), -t(0, 2), t(0, 1)],
               [-t(2, 0), t(2, 2), -t(2, 1)],
               [t(1, 0), -t(1, 2), t(1, 1)]];
    const deg = 180 / Math.PI;
    const ry = Math.asin(Math.max(-1, Math.min(1, -s[2][0])));
    const rx = Math.atan2(s[2][1], s[2][2]);
    const rz = Math.atan2(s[1][0], s[0][0]);
    return { angle: rz * deg, rotation_x: rx * deg, rotation_y: ry * deg };
  }
  try {
    gizmo = new TransformControls(camera, renderer.domElement);
    gizmo.size = 1.4;                      // large enough to see and grab outside the part it sits in
    setGizmoMode('translate');
    const helper = gizmo.getHelper ? gizmo.getHelper() : gizmo;
    scene.add(helper);
    gizmo.addEventListener('dragging-changed', (ev) => {
      controls.enabled = !ev.value;
      if (!ev.value) { // drag finished -> commit position OR facing angle
        const obj = gizmo.object;
        if (obj && pressMoved < 4) {
          // a click on the gizmo, not a drag: put everything back and save nothing
          if (startPos) obj.position.copy(startPos);
          if (startQuat) obj.quaternion.copy(startQuat);
          for (const f of followers) f.anchor.position.copy(f.anchor.userData.odStart);
          followers = [];
          return;
        }
        if (obj && obj.userData.componentId && window.parent) {
          if (gizmoMode === 'translate' && followers.length) {
            // a group move: every selected part by the same amount, as one step
            const dx = obj.position.x - startPos.x, dy = obj.position.y - startPos.y, dz = obj.position.z - startPos.z;
            const moves = [obj, ...followers.map((f) => f.anchor)].map((a) => {
              const p = a === obj ? a.position : { x: a.userData.odStart.x + dx, z: a.userData.odStart.z + dz };
              return { id: a.userData.componentId, center: [p.x, -p.z], dz: dy };
            });
            window.parent.postMessage({ type: 'optodraw-move-group', moves: moves }, '*');
          } else if (gizmoMode !== 'translate') {
            // the whole turn: the facing angle and the turns out of the table plane
            window.parent.postMessage({ type: 'optodraw-rotate', id: obj.userData.componentId, ...tableAngles(obj) }, '*');
          } else {
            // 3D X/Z -> world x/y  (item.position = [x, z, -y]); a lift is the change of the part's z
            window.parent.postMessage({ type: 'optodraw-move', id: obj.userData.componentId,
                                        center: [obj.position.x, -obj.position.z], dz: obj.position.y - startY }, '*');
          }
        }
      } else if (gizmo.object) {
        startY = gizmo.object.position.y;
        startPos = gizmo.object.position.clone();
        startQuat = gizmo.object.quaternion.clone();
        pressMoved = Infinity;     // until the pointer comes up
        followers = gizmoMode !== 'translate' ? [] : selection.slice(1).map(anchorFor)
          .filter((a) => a && a !== gizmo.object && a.userData.movable !== false)
          .map((a) => { a.userData.odStart = a.position.clone(); return { anchor: a }; });
      }
    });
    // while the gizmo moves the primary part, the rest of the selection follows it
    gizmo.addEventListener('objectChange', () => {
      if (!followers.length || !startPos || !gizmo.object) return;
      const d = gizmo.object.position.clone().sub(startPos);
      for (const f of followers) f.anchor.position.copy(f.anchor.userData.odStart).add(d);
    });
    // X = turn the selected part about its own x (the beam axis), Y = about its own y (across the beam), Z or R =
    // about the table's vertical (the facing angle), all in 15° steps; M/G/T = move (and lift); hold Shift = free
    window.addEventListener('keydown', (ev) => {
      const tag = (ev.target && ev.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (ev.target && ev.target.isContentEditable)) return;
      const key = ev.key.toLowerCase();
      // Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z or Ctrl+Y redo: the editor keeps the history, so pass them up to it
      if ((ev.metaKey || ev.ctrlKey) && (key === 'z' || key === 'y')) {
        ev.preventDefault();
        if (window.parent) window.parent.postMessage({ type: 'optodraw-undo', redo: key === 'y' || ev.shiftKey }, '*');
        return;
      }
      if (ev.metaKey || ev.ctrlKey) return;
      // Esc lets go of the selection, so nothing selected moves by accident
      if (ev.key === 'Escape') {
        if (gizmo && gizmo.dragging) return;
        applyHighlight([]);
        if (window.parent) window.parent.postMessage({ type: 'optodraw-select', id: null, ids: [] }, '*');
        return;
      }
      if (key === 'r' || key === 'z') setGizmoMode('rotate');
      else if (key === 'y') setGizmoMode('tilt');
      else if (key === 'x') setGizmoMode('roll');
      else if (key === 'm' || key === 'g' || key === 't') setGizmoMode('translate');
      else if (ev.key === 'Shift' && gizmo) gizmo.rotationSnap = null; // free rotation while held
    });
    window.addEventListener('keyup', (ev) => {
      if (ev.key === 'Shift' && gizmo && gizmoMode !== 'translate') gizmo.rotationSnap = ROT_SNAP;
    });
  } catch (err) { gizmo = null; }

  function attachGizmo(id) {
    if (!gizmo) return;
    const anchor = id ? pk().find((p) => p.userData.componentId === id) : null;
    if (anchor && anchor.userData.movable !== false) gizmo.attach(anchor); else gizmo.detach();
  }
  const _origApplyHighlight = applyHighlight;
  applyHighlight = function (ids) { _origApplyHighlight(ids); attachGizmo(highlightId); };

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
      applyHighlight(Array.isArray(d.ids) && d.ids.length ? d.ids : (d.id || null));
    } else if (d.type === 'optodraw-gizmo') {
      setGizmoMode(String(d.mode));            // X, Y, Z, R or M pressed while the focus was outside the 3D page
    } else if (d.type === 'optodraw-rebuild' && Array.isArray(d.items)) {
      const sel = selection.slice(); // rebuild content in place, then restore selection
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
