// Component palette: a searchable grid of component preview thumbnails.
// Previews are rendered server-side (/api/preview/<name>) and lazy-loaded as
// cards scroll into view, so opening the palette stays fast.

import { api } from "./api.js";

// Display names come from the catalog, which can carry imported or renamed
// parts; escape before any innerHTML use.
const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Server previews render into the scene's fixed frame, so a 4-unit photodiode
// arrives as a dot — and preset scenes carry faint full-frame grids that would
// defeat a plain getBBox. Union only visible-enough shapes (client rects handle
// every nested transform), then refit the viewBox to that content.
export function fitSvgToContent(container, padFrac = 0.1, minOpacity = 0.25) {
  const svg = container.querySelector("svg");
  if (!svg) return;
  try {
    const svgRect = svg.getBoundingClientRect();
    if (!svgRect.width || !svgRect.height) return; // hidden — keep the server framing
    let u = null;
    for (const el of svg.querySelectorAll("path,rect,circle,ellipse,line,polyline,polygon,text")) {
      let o = 1;
      for (let n = el; n && n !== svg; n = n.parentNode) {
        const v = parseFloat(n.getAttribute?.("opacity"));
        if (!isNaN(v)) o *= v;
      }
      if (o < minOpacity) continue; // faint scene furniture (grids) isn't content
      const r = el.getBoundingClientRect();
      if (!r || (r.width === 0 && r.height === 0)) continue;
      u = u
        ? { left: Math.min(u.left, r.left), top: Math.min(u.top, r.top), right: Math.max(u.right, r.right), bottom: Math.max(u.bottom, r.bottom) }
        : { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    }
    if (!u || u.right - u.left <= 0 || u.bottom - u.top <= 0) return;
    // map the client-space union back into viewBox units; the svg letterboxes
    // its viewBox inside the element box (preserveAspectRatio "meet"), so use
    // the uniform scale + centering offsets, not per-axis ratios
    const vb = svg.viewBox.baseVal;
    if (!vb || !vb.width || !vb.height) return;
    const s = Math.min(svgRect.width / vb.width, svgRect.height / vb.height);
    if (!s || !isFinite(s)) return;
    const ox = (svgRect.width - vb.width * s) / 2, oy = (svgRect.height - vb.height * s) / 2;
    const x = vb.x + (u.left - svgRect.left - ox) / s;
    const y = vb.y + (u.top - svgRect.top - oy) / s;
    const w = (u.right - u.left) / s, h = (u.bottom - u.top) / s;
    const pad = Math.max(w, h) * padFrac + 0.5;
    svg.setAttribute("viewBox", `${x - pad} ${y - pad} ${w + 2 * pad} ${h + 2 * pad}`);
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.style.width = "100%";
    svg.style.height = "100%";
  } catch (_) { /* detached or unrenderable svg — keep the server framing */ }
}

// "AmplifiedPhotodetector" → "Amplified Photodetector"; acronyms (MZI, PMT) survive.
export function humanizeName(name) {
  return String(name)
    .replace(/_/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
}

// Light paths (Beam / Route) aren't placed from the palette — they're drawn with
// the Route tool or the Links panel. Models (GDSModel / CustomModel) are created
// by the import flows (toolbar / ⌘K), not dropped bare from a palette card.
export const HIDDEN_CATEGORIES = new Set(["light_paths", "routing", "models"]);

// Curated order: what users reach for most sits on top. Unknown future
// categories slot in at the bottom.
const CATEGORY_ORDER = ["my_parts", "devices", "instruments", "optics", "on_chip", "electronics", "samples", "misc"];
const categoryRank = (c) => {
  const i = CATEGORY_ORDER.indexOf(c);
  return i === -1 ? CATEGORY_ORDER.length : i;
};
const CATEGORY_TITLES = { my_parts: "My parts", on_chip: "on-chip" };
// GUI-pointless entries: Grid duplicates the canvas grid toggle.
export const HIDDEN_COMPONENTS = new Set(["Grid"]);

// The Figure group: one entry per inset kind the editor makes with no code. `accept` asks for a file first; `of` names
// the kinds of the selected inset it is made from. A plot stays in Python: a plot is code and data.
export const FIGURE_ENTRIES = [
  { label: "Text", kind: "Text", icon: "i-doc" },
  { label: "Equation", kind: "Equation", icon: "i-sparkles" },
  { label: "Picture", kind: "Image", icon: "i-image", accept: ".png,.jpg,.jpeg,.tif,.tiff" },
  { label: "SVG file", kind: "SvgFile", icon: "i-image", accept: ".svg" },
  { label: "PDF file", kind: "PdfFile", icon: "i-doc", accept: ".pdf" },
  { label: "Scene inset", kind: "SceneView", icon: "i-layers" },
  { label: "Copy of this scene", kind: "SceneView", icon: "i-duplicate", copy: true },
  { label: "Timing", kind: "Timing", icon: "i-wave" },
  { label: "GDS view", kind: "GdsView", icon: "i-chip", accept: ".gds" },
  { label: "Section", kind: "SectionView", icon: "i-flip-v", of: ["GdsView"] },
  { label: "3D view", kind: "View3D", icon: "i-cube", of: ["GdsView", "SceneView"] },
];

// The inset sources that take a height as well as a width; the others keep their own shape.
export const FREE_SHAPES = new Set(["EmptyBox", "Plot"]);

export function createPalette({ listEl, searchEl, onAdd, onFigure }) {
  let catalog = {};
  let view = "2d";
  const previewCache = new Map();
  const collapsed = new Set(); // collapsed category names (persists across renders)

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        loadPreview(entry.target);
      }
    },
    { root: listEl, rootMargin: "120px" },
  );

  async function loadPreview(card) {
    const name = card.dataset.name;
    const thumb = card.querySelector(".pi-thumb");
    if (!thumb || thumb.dataset.loaded) return;
    thumb.dataset.loaded = "1";
    try {
      const hash = card.dataset.definitionHash;
      const cacheKey = `${view}:${name}:${hash || ""}`;
      let svg = previewCache.get(cacheKey);
      if (!svg) { svg = (await api.preview(name, view, hash)).svg; previewCache.set(cacheKey, svg); }
      thumb.innerHTML = svg;
      fitSvgToContent(thumb);
    } catch (_) {
      thumb.textContent = "—";
    }
  }

  function render(filter = "") {
    const term = filter.trim().toLowerCase();
    const groups = {};
    for (const [name, info] of Object.entries(catalog)) {
      if (HIDDEN_COMPONENTS.has(name)) continue;
      const cat = info.category || "other";
      if (HIDDEN_CATEGORIES.has(cat)) continue; // light paths are drawn, not placed
      const hay = `${name} ${info.display_name || ""} ${info.description || ""}`.toLowerCase();
      if (term && !hay.includes(term)) continue;
      (groups[cat] ||= []).push([name, info]);
    }

    observer.disconnect();
    listEl.innerHTML = "";

    // A group title that folds its cards; collapse state is always honored, including while searching.
    const groupTitle = (cat, text, count) => {
      const isCollapsed = collapsed.has(cat);
      const title = document.createElement("div");
      title.className = "palette-group-title" + (isCollapsed ? " collapsed" : "");
      title.tabIndex = 0;
      title.setAttribute("role", "button");
      title.setAttribute("aria-expanded", String(!isCollapsed));
      title.innerHTML =
        `<svg class="ic ic-sm pg-caret"><use href="#i-caret"/></svg>` +
        `<span>${esc(text)}</span><span class="pg-count">${count}</span>`;
      const toggleCategory = () => {
        if (collapsed.has(cat)) collapsed.delete(cat); else collapsed.add(cat);
        render(searchEl.value || "");
      };
      title.addEventListener("click", toggleCategory);
      title.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCategory(); }
      });
      listEl.appendChild(title);
      return isCollapsed;
    };
    const addCard = (shown, tip, thumb, add, isCollapsed) => {
      const card = document.createElement("div");
      card.className = "palette-item" + (isCollapsed ? " is-hidden" : "");
      card.tabIndex = isCollapsed ? -1 : 0;
      card.setAttribute("role", "button");
      card.setAttribute("aria-label", "Add " + shown);
      card.title = tip;
      card.innerHTML = `<div class="pi-thumb">${thumb}</div><div class="pi-name">${esc(shown)}</div>`;
      card.addEventListener("click", add);
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); add(); }
      });
      listEl.appendChild(card);
      return card;
    };

    const figures = FIGURE_ENTRIES.filter((f) => !term || `${f.label} figure inset`.toLowerCase().includes(term));
    if (figures.length) {
      const isCollapsed = groupTitle("figure", "Figure", figures.length);
      for (const f of figures) {
        const tip = f.of ? `${f.label} of the selected inset` : `Add an inset: ${f.label}`;
        addCard(f.label, tip, `<svg class="ic"><use href="#${f.icon}"/></svg>`, () => onFigure(f), isCollapsed)
          .dataset.figure = f.label;
      }
    }

    for (const cat of Object.keys(groups).sort((a, b) => categoryRank(a) - categoryRank(b) || a.localeCompare(b))) {
      const isCollapsed = groupTitle(cat, CATEGORY_TITLES[cat] || cat.replace(/_/g, " "), groups[cat].length);
      for (const [name, info] of groups[cat].sort((a, b) => a[0].localeCompare(b[0]))) {
        const shown = info.display_name || humanizeName(name);
        const card = addCard(shown, info.description || shown, "", () => onAdd(name), isCollapsed);
        card.dataset.name = name;
        if (info.definition_hash) card.dataset.definitionHash = info.definition_hash;
        if (!isCollapsed) observer.observe(card); // only lazy-load visible thumbnails
      }
    }
  }

  function setCatalog(data) {
    catalog = data || {};
    render(searchEl.value || "");
  }

  function setView(mode) {
    const next = mode === "1d" ? "1d" : "2d";
    if (view === next) return;
    view = next;
    render(searchEl.value || "");
  }

  searchEl.addEventListener("input", () => render(searchEl.value));
  return { setCatalog, setView };
}
