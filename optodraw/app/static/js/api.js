// Thin fetch wrappers over the optodraw editor backend (/api/*).

// The server's words as an Error. A fault in typed text (the Code tab) also names its line: error.line.
async function errorOf(res) {
  let line = null;
  const error = new Error(await errorMessage(res, (at) => { line = at; }));
  error.line = line;
  error.status = res.status;
  return error;
}

async function errorMessage(res, onLine = () => {}) {
  const fallback = res.statusText || `HTTP ${res.status}`;
  try {
    const payload = await res.json();
    const detail = payload.detail ?? payload.message;
    if (detail && typeof detail === "object" && typeof detail.message === "string") {
      onLine(detail.line ?? null);
      return detail.message;
    }
    if (Array.isArray(detail)) {
      return detail.map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
        const message = item.msg || JSON.stringify(item);
        return field ? `${field}: ${message}` : message;
      }).join("; ") || fallback;
    }
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") return JSON.stringify(detail);
  } catch (_) { /* non-JSON error */ }
  return fallback;
}

async function request(method, url, body) {
  const opts = { method, headers: method === "GET" ? {} : changeHeaders() };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    throw await errorOf(res);
  }
  const ctype = res.headers.get("content-type") || "";
  return ctype.includes("application/json") ? res.json() : res.text();
}

// Upload a file as the raw request body (used for GDS / model imports).
async function uploadFile(url, file) {
  const res = await fetch(`${url}?filename=${encodeURIComponent(file.name)}`,
    { method: "POST", headers: changeHeaders(), body: file });
  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  return res.json();
}

// How many insets the editor shows open (0 on the page). A whole-scene edit carries it, so the server refuses an edit
// meant for another level (after a restart, or from a second tab) instead of putting it over the wrong scene.
let level = 0;
export function setLevel(depth) { level = depth; }

// The workspace the page shows, as the scene payload names it. Each change carries it, so the server refuses a change
// from a tab that shows another workspace (after a restart, or from a second tab) instead of writing it there.
let workspace = null;
export function setWorkspace(name) { if (name) workspace = name; }
export function changeHeaders(headers = {}) {
  return workspace ? { ...headers, "X-Optodraw-Workspace": workspace } : headers;
}

export const api = {
  health: () => request("GET", "/api/health"),
  workspaces: () => request("GET", "/api/workspaces"),
  createWorkspace: (name, preset) => request("POST", "/api/workspaces", { name, preset }),
  openWorkspace: (name) => request("POST", `/api/workspaces/${encodeURIComponent(name)}/open`),
  renameWorkspace: (name, newName) => request("PUT", `/api/workspaces/${encodeURIComponent(name)}`, { name: newName }),
  deleteWorkspace: (name) => request("DELETE", `/api/workspaces/${encodeURIComponent(name)}`),
  catalog: () => request("GET", "/api/catalog"),
  describe: (name, hash) => request("GET", `/api/catalog/${encodeURIComponent(name)}${hash ? `?definition_hash=${encodeURIComponent(hash)}` : ""}`),
  preview: (name, view = "2d", hash) => request("GET", `/api/preview/${encodeURIComponent(name)}?view=${encodeURIComponent(view)}${hash ? `&definition_hash=${encodeURIComponent(hash)}` : ""}`),
  parts: () => request("GET", "/api/parts"),
  savePart: (body) => request("POST", "/api/parts", body),
  inspectPart: (body, view = "2d") => request("POST", `/api/parts/inspect?view=${view}`, body),
  partThreejs: (body) => request("POST", "/api/parts/threejs", body),
  importPart: (file) => uploadFile("/api/parts/import", file),
  partExportUrl: (name) => `/api/parts/export?name=${encodeURIComponent(name)}`,
  presetPreview: (name) => request("GET", `/api/presets/${encodeURIComponent(name)}/preview`),
  materials: () => request("GET", "/api/materials"),

  getScene: () => request("GET", "/api/scene"),
  // whole: the page, each open inset drawn again (Save); without it, the scene the editor shows
  getWholeScene: () => request("GET", "/api/scene?whole=true"),
  // edit: the spec is an edit of the held scene (the server moves an inset's marks with it); an open sends none.
  // whole: the spec is a whole page (File > Open): the server leaves every open inset first
  setScene: (spec, edit = false, whole = false) =>
    request("POST", "/api/scene", whole ? { spec, edit, whole } : { spec, edit, depth: level }),
  sceneText: () => request("GET", "/api/scene/text"),
  setSceneText: (text, depth) => request("POST", "/api/scene/text", { text, depth }),
  openInset: (id) => request("POST", "/api/scene/inset/open", { id }),
  // an inset of a Figure palette kind, built once: body {kind, source, of?, center?}; the answer names its id
  makeInset: (body) => request("POST", "/api/inset", body),
  // the record values that change, built once; none builds it again as it is (Rebuild)
  insetSource: (id, source = {}) => request("POST", `/api/inset/${encodeURIComponent(id)}/source`, { source }),
  insetSize: (id, size) => request("POST", `/api/inset/${encodeURIComponent(id)}/size`, size),
  // a picked file, kept in the workspace's files folder: {path} as an inset record names it
  keepFile: (file) => uploadFile("/api/files", file),
  closeInset: (depth) => request("POST", "/api/scene/inset/close", { depth }),
  newScene: (meta = {}) => request("POST", "/api/scene/new", meta),
  setMeta: (meta) => request("PATCH", "/api/scene/meta", meta),
  loadPreset: (name) => request("POST", "/api/scene/preset", { name }),
  simulateOptions: (id) => request("GET", `/api/simulate/${encodeURIComponent(id)}/options`),
  simulate: (id, kind, params = {}) => request("POST", `/api/simulate/${encodeURIComponent(id)}`, { kind, params }),
  simulatePolarization: (params = {}) => request("POST", "/api/simulate/polarization", { params }),
  generators: () => request("GET", "/api/generators"),
  generate: (name, params = {}) => request("POST", "/api/generate", { name, params }),
  arrange: (body) => request("POST", "/api/scene/arrange", body),
  animationRecipes: (id) => request("GET", `/api/animation/${encodeURIComponent(id)}/recipes`),
  animationGif: async (id, recipe, params = {}) => {
    const res = await fetch(`/api/animation/${encodeURIComponent(id)}/gif`, { method: "POST", headers: changeHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ recipe, params }) });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.blob();
  },
  animationFlow: async (params = {}) => {
    const res = await fetch("/api/animation/flow", { method: "POST", headers: changeHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ params }) });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.blob();
  },
  animationPayloads: () => request("GET", "/api/animation/payloads"),
  validate: () => request("POST", "/api/validate"),
  publicationTemplates: () => request("GET", "/api/publication/templates"),
  exportFigure: async (body) => {
    const res = await fetch("/api/export/figure", { method: "POST", headers: changeHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await errorMessage(res));
    return res.blob();
  },

  create: (name, params = {}) => request("POST", "/api/component", { name, params }),
  update: (id, params) => request("PATCH", `/api/component/${encodeURIComponent(id)}`, { params }),
  move: (id, center, angle) =>
    request("POST", `/api/component/${encodeURIComponent(id)}/move`, { center, angle }),
  remove: (id) => request("DELETE", `/api/component/${encodeURIComponent(id)}`),
  ports: () => request("GET", "/api/ports"),
  addBeam: (path, wavelength = 633, width = 0.8) =>
    request("POST", "/api/beam", { path, wavelength, width }),
  addRoute: (src, dst, opts = {}) =>
    request("POST", "/api/route", { src, dst, ...opts }),
  addFreeRoute: (points, opts = {}) =>
    request("POST", "/api/route", { points, ...opts }),
  updateRoute: (id, body) => request("PATCH", `/api/route/${encodeURIComponent(id)}`, body),
  routeText: (text, wavelength = 633) => request("POST", "/api/route/text", { text, wavelength }),
  traceBeam: (sourceId, wavelength = null) =>
    request("POST", "/api/trace", { source_id: sourceId, wavelength }),

  renderSvg: () => request("GET", "/api/render/svg"),
  render1dUrl: () => "/api/render/1d.svg",
  save1dLayout: (positions) => request("PUT", "/api/scene/1d/layout", positions),
  scene3d: (light = false, tour = false) =>
    request("GET", tour ? "/api/scene3d?light=1&tour=1" : light ? "/api/scene3d?light=1" : "/api/scene3d"),
  threejsUrl: () => "/api/render/threejs",
  tikzUrl: (view = "2d") => `/api/render/tikz?view=${encodeURIComponent(view)}`,
  downloadUrl: () => "/api/scene/download",
  importGds: (file) => uploadFile("/api/gds/import", file),
  importModel: (file) => uploadFile("/api/model/import", file),
  glbUrl: () => "/api/export/glb",
  blenderScriptUrl: (glb) => `/api/export/blender?glb=${encodeURIComponent(glb)}`,
  gdsLayers: (id) => request("GET", `/api/gds/${encodeURIComponent(id)}/layers`),
  // the layout view: the part's GDS bytes with the cell it shows, and its .lyp (a 404's text is the error)
  gdsFile: async (id) => {
    const res = await fetch(`/api/gds/${encodeURIComponent(id)}/file`);
    if (!res.ok) throw new Error(await errorMessage(res));
    return { bytes: await res.arrayBuffer(), cell: decodeURIComponent(res.headers.get("X-GDS-Cell") || "") || null };
  },
  gdsLyp: (id) => request("GET", `/api/gds/${encodeURIComponent(id)}/lyp`),
  gdsCrossSection: (id, opts = {}) =>
    request("POST", `/api/gds/${encodeURIComponent(id)}/cross_section`, opts),
  attachTechnology: (id, file) => uploadFile(`/api/gds/${encodeURIComponent(id)}/technology`, file),
  attachTechnologyFolder: (id, files) => request("POST", `/api/gds/${encodeURIComponent(id)}/technology_folder`, { files }),
  pdks: () => request("GET", "/api/pdks"),
  applyPdk: (id, name) => request("POST", `/api/gds/${encodeURIComponent(id)}/pdk`, { name }),
  stacks: () => request("GET", "/api/stacks"),
  applyStack: (id, name) => request("POST", `/api/gds/${encodeURIComponent(id)}/stack`, { name }),
  resetGdsLayers: (id) => request("POST", `/api/gds/${encodeURIComponent(id)}/reset_layers`),
};
