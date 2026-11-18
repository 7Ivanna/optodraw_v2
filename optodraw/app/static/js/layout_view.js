// The Layout view: an imported GDS in GDS Lens, the way KLayout shows it (wheel to zoom, drag to pan, the cell
// tree, the layers, M for a ruler). The viewer is vendored and served by the editor (/vendor/gds-lens.js, pinned
// to GDS_LENS_VERSION, the Python side's optodraw/renderers/gds_lens.py); its host, loaded first, starts it with
// filled layers. Nothing comes from the network. The part's file and its layer colours come from the editor's
// routes, so the view draws the part's own top cell in the colours the 3D view uses.

const GDS_LENS_VERSION = "1.7.0";

let engine = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.append(script);
  });
}

// The host must be installed before the viewer runs, and the viewer loads once.
function loadEngine() {
  if (!engine) {
    engine = loadScript("/vendor/gds-lens-host.js").then(() => import(`/vendor/gds-lens.js?v=${GDS_LENS_VERSION}`));
  }
  return engine;
}

export function createLayoutView({ host, api, onStatus = () => {}, onPick = () => {} }) {
  const bar = document.createElement("div");
  bar.className = "layout-bar";
  bar.hidden = true;
  const label = document.createElement("label");
  label.textContent = "Part ";
  const picker = document.createElement("select");
  picker.addEventListener("change", () => onPick(picker.value));
  label.append(picker);
  bar.append(label);
  const message = document.createElement("div");
  message.className = "layout-message";
  message.hidden = true;
  host.append(bar, message);

  let element = null;
  let shown = null;          // the id of the part on screen
  let wanted = { key: null, file: null };   // the part last asked for: its full key and its file key
  let request = 0;           // a newer open() wins over one still loading
  let cut = null;            // the panel's cut of the shown part, in the file's microns, drawn as a ruler

  // Rulers do not survive a load or a change of top cell, so the cut is drawn again after each.
  async function drawCut() {
    if (!element || !cut) return;
    await element.clearMeasurements();
    await element.addMeasurement(...cut);
  }

  function setParts(parts) {
    picker.replaceChildren(...parts.map((part) => new Option(part.label, part.id)));
    if (shown) picker.value = shown;
    bar.hidden = parts.length < 2;
  }

  // part: {id, label, cell, key, file}. The file key (id, source, cell) names the geometry, the full key adds the
  // layer stack. ``reload`` re-reads the same file (new colours) and keeps the camera.
  async function open(part, { reload = false } = {}) {
    const mine = ++request;
    if (wanted.file !== part.file) cut = null;      // other geometry: the old cut is not its cut
    wanted = { key: part.key, file: part.file };
    message.hidden = true;
    await loadEngine();
    if (!element) {
      element = document.createElement("gds-lens");
      host.append(element);
    }
    try {
      const [file, lyp] = await Promise.all([api.gdsFile(part.id), api.gdsLyp(part.id)]);
      if (mine !== request) return;
      // the part's own cell: its cell_name, else the top cell it read (a file can hold several)
      await element.load(file.bytes, { topCell: part.cell || file.cell || null, reload });
      await element.setLyp(`${part.id}.lyp`, lyp);
      shown = part.id;
      await drawCut();
      picker.value = part.id;
      // the hint is for a part opened; a reload (new colours) leaves the line to what changed them
      if (!reload) onStatus("Layout view: wheel to zoom, drag to pan, M for a ruler, Esc to clear it");
    } catch (error) {
      if (mine !== request) return;
      shown = null;
      message.textContent = error.message;
      message.hidden = false;
      element.showError(error.message);
      onStatus(error.message);
    }
  }

  // The newest ruler, as [x0, y0, x1, y1] in the file's microns, or null when there is none.
  async function cutLine() {
    if (!element) return null;
    const rulers = await element.getMeasurements();
    const last = rulers[rulers.length - 1];
    return last ? [last.x0, last.y0, last.x1, last.y1] : null;
  }

  async function showCut(lineFile) {
    cut = lineFile;
    await drawCut();
  }

  return {
    open,
    setParts,
    cutLine,
    showCut,
    shown: () => shown,
    wanted: () => wanted,
    close: () => { request += 1; },
    viewer: () => element,
  };
}
