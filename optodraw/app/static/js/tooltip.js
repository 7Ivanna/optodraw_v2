// Fast, styled tooltips for anything with a `title` (or `data-tip`) attribute.
//
// Native `title` tooltips are slow (~1s), unstyled, and easy to miss — which made
// the icon-only toolbar buttons feel unlabelled. This converts `title` -> a quick
// custom tooltip (and removes `title` so the native one doesn't double up).

export function initTooltips() {
  const tip = document.createElement("div");
  tip.className = "od-tip";
  tip.setAttribute("role", "tooltip");
  tip.style.maxWidth = "calc(100vw - 12px)";
  tip.hidden = true;
  document.body.appendChild(tip);

  let timer = null;
  let active = null;

  function place(el) {
    const r = el.getBoundingClientRect();
    tip.hidden = false;
    const tr = tip.getBoundingClientRect();
    // Prefer below; flip above if it would clip the viewport bottom.
    let top = r.bottom + 8;
    let below = true;
    if (top + tr.height > window.innerHeight - 6) { top = r.top - tr.height - 8; below = false; }
    top = Math.max(6, Math.min(top, window.innerHeight - tr.height - 6));
    let left = r.left + r.width / 2 - tr.width / 2;
    left = Math.max(6, Math.min(left, window.innerWidth - tr.width - 6));
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;
    tip.dataset.placement = below ? "below" : "above";
  }

  function show(el) {
    const text = el.getAttribute("data-tip");
    if (!text || !el.isConnected) return;
    active = el;
    tip.textContent = text;
    tip.hidden = false;
    place(el);
  }

  function hide() {
    clearTimeout(timer);
    timer = null;
    active = null;
    tip.hidden = true;
  }

  function promoteTitle(el) {
    if (!el.hasAttribute("title")) return;
    const label = el.getAttribute("title") || "";
    el.setAttribute("data-tip", label);
    if (!el.hasAttribute("aria-label") && !el.hasAttribute("aria-labelledby") && !(el.textContent || "").trim()) {
      el.setAttribute("aria-label", label);
    }
    el.removeAttribute("title");
  }

  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest("[title], [data-tip]");
    if (!el || el === active) return;
    promoteTitle(el);
    if (el.disabled && el.getAttribute("data-tip-when-disabled") !== "true") {
      // still show — knowing what a disabled button does is useful
    }
    clearTimeout(timer);
    timer = setTimeout(() => show(el), 260);
  });

  document.addEventListener("mouseout", (e) => {
    const next = e.relatedTarget;
    if (active && active.contains(e.target) && (!next || !active.contains(next)) && document.activeElement !== active) hide();
    else if (!active) clearTimeout(timer);
  });
  document.addEventListener("focusin", (e) => {
    const el = e.target.closest("[title], [data-tip]");
    if (!el) return;
    promoteTitle(el);
    clearTimeout(timer);
    show(el);
  });
  document.addEventListener("focusout", (e) => {
    if (active && active.contains(e.target) && (!e.relatedTarget || !active.contains(e.relatedTarget))) hide();
  });
  document.addEventListener("mousedown", hide, true);
  window.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
  window.addEventListener("blur", hide);
}
