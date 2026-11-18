// Wavelength → color, and a GUI picker shared by the toolbar / inspector / Links.
//
// `wavelengthHex` is a 1:1 port of optodraw.core.beam.wavelength_to_hex so the
// swatches and live preview match exactly what the renderer draws.

export function wavelengthHex(nm) {
  nm = Number(nm) || 0;
  let r, g, b;
  if (nm < 380) return "#7700ff";
  else if (nm < 440) { r = (440 - nm) / 60; g = 0; b = 1; }
  else if (nm < 490) { r = 0; g = (nm - 440) / 50; b = 1; }
  else if (nm < 510) { r = 0; g = 1; b = (510 - nm) / 20; }
  else if (nm < 580) { r = (nm - 510) / 70; g = 1; b = 0; }
  else if (nm < 645) { r = 1; g = (645 - nm) / 65; b = 0; }
  else if (nm <= 780) { r = 1; g = 0; b = 0; }
  else return "#aa0000";
  let f;
  if (nm < 420) f = 0.3 + (0.7 * (nm - 380)) / 40;
  else if (nm > 700) f = 0.3 + (0.7 * (780 - nm)) / 80;
  else f = 1.0;
  const ch = (v) => Math.trunc(255 * Math.pow(Math.max(v * f, 0), 0.8)).toString(16).padStart(2, "0");
  return `#${ch(r)}${ch(g)}${ch(b)}`;
}

// Common laser lines shown as clickable swatches.
const LINES = [405, 445, 488, 532, 561, 594, 633, 660, 780, 850, 1064, 1310, 1490, 1550];

// Build a wavelength picker: laser-line swatches + a custom nm input (live color).
// Returns { el, get, set }. `onChange(nm)` fires on every change.
export function createWavelengthPicker(value, onChange) {
  let current = Number(value) || 633;
  const wrap = document.createElement("div");
  wrap.className = "wl-picker";

  const swatches = document.createElement("div");
  swatches.className = "wl-swatches";

  const num = document.createElement("input");
  num.type = "number";
  num.className = "wl-num";
  num.min = "1";
  num.step = "1";

  function render() {
    swatches.innerHTML = "";
    for (const nm of LINES) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "wl-chip" + (Math.round(current) === nm ? " active" : "");
      chip.style.background = wavelengthHex(nm);
      chip.title = nm > 780 ? `${nm} nm (infrared, false color)` : `${nm} nm`;
      chip.setAttribute("aria-label", chip.title);
      chip.addEventListener("click", () => set(nm));
      swatches.appendChild(chip);
    }
    num.value = Math.round(current);
    num.style.borderColor = wavelengthHex(current);
  }

  function set(nm, silent = false) {
    const parsed = Number(nm);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      render();
      return;
    }
    current = parsed;
    render();
    if (!silent) onChange(current);
  }

  num.addEventListener("change", () => set(num.value));
  num.addEventListener("input", () => { num.style.borderColor = wavelengthHex(Number(num.value) || 633); });

  const numWrap = document.createElement("label");
  numWrap.className = "wl-num-wrap";
  numWrap.append(num, document.createTextNode("nm"));

  wrap.append(swatches, numWrap);
  render();
  return { el: wrap, get: () => current, set: (nm) => set(nm, true) };
}
