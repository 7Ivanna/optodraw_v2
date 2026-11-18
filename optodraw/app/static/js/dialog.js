// In-app modal dialogs — a styled replacement for native prompt()/confirm(),
// which are unreliable (blocked in VS Code webviews and some embedded browsers,
// which is why "New workspace" appeared to do nothing).
//
// All helpers return a Promise; Esc / overlay-click / Cancel resolve to null/false.

let host = null;
let activeClose = null;

function ensureHost() {
  if (host) return host;
  host = document.createElement("div");
  host.className = "od-modal-host";
  host.hidden = true;
  document.body.appendChild(host);
  return host;
}

export function openModal(render) {
  const h = ensureHost();
  if (activeClose) activeClose(null);
  const returnFocus = document.activeElement;
  return new Promise((resolve) => {
    let done = false;
    const close = (value) => {
      if (done) return;
      done = true;
      h.hidden = true;
      h.innerHTML = "";
      document.removeEventListener("keydown", onKey, true);
      if (activeClose === close) activeClose = null;
      if (returnFocus?.isConnected) returnFocus.focus();
      resolve(value);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(null); }
      if (e.key !== "Tab") return;
      const controls = [...card.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")];
      if (!controls.length) { e.preventDefault(); card.focus(); return; }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (e.shiftKey && (document.activeElement === first || !card.contains(document.activeElement))) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !card.contains(document.activeElement))) {
        e.preventDefault(); first.focus();
      }
    };
    const overlay = document.createElement("div");
    overlay.className = "od-modal-overlay";
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(null); });

    const card = document.createElement("div");
    card.className = "od-modal";
    card.tabIndex = -1;
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-label", "Dialog");
    overlay.appendChild(card);
    activeClose = close;
    render(card, close);

    h.innerHTML = "";
    h.appendChild(overlay);
    h.hidden = false;
    document.addEventListener("keydown", onKey, true);
    // focus the first input or the primary button
    setTimeout(() => (card.querySelector("input, button.od-primary") || card).focus?.(), 0);
  });
}

function header(card, title) {
  const h = document.createElement("div");
  h.className = "od-modal-head";
  h.id = "od-modal-title";
  h.textContent = title;
  card.appendChild(h);
  card.setAttribute("aria-labelledby", h.id);
  card.removeAttribute("aria-label");
}

function footer(card, buttons) {
  const f = document.createElement("div");
  f.className = "od-modal-foot";
  for (const b of buttons) f.appendChild(b);
  card.appendChild(f);
}

function btn(label, cls, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "od-btn " + cls;
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

// Text prompt → resolves to the trimmed string, or null if cancelled.
export function dialogPrompt({ title = "", label = "", value = "", placeholder = "", confirmText = "OK" } = {}) {
  return openModal((card, close) => {
    header(card, title);
    const body = document.createElement("div");
    body.className = "od-modal-body";
    if (label) {
      const l = document.createElement("label");
      l.className = "od-modal-label";
      l.htmlFor = "od-modal-prompt";
      l.textContent = label;
      body.appendChild(l);
    }
    const input = document.createElement("input");
    input.id = "od-modal-prompt";
    input.className = "od-modal-input";
    input.value = value;
    input.placeholder = placeholder;
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); close((input.value || "").trim() || null); }
    });
    body.appendChild(input);
    card.appendChild(body);
    footer(card, [
      btn("Cancel", "od-ghost", () => close(null)),
      btn(confirmText, "od-primary", () => close((input.value || "").trim() || null)),
    ]);
  });
}

// Confirmation → resolves to true/false.
export function dialogConfirm({ title = "", message = "", confirmText = "Confirm", danger = false } = {}) {
  return openModal((card, close) => {
    header(card, title);
    const body = document.createElement("div");
    body.className = "od-modal-body";
    body.textContent = message;
    card.appendChild(body);
    footer(card, [
      btn("Cancel", "od-ghost", () => close(false)),
      btn(confirmText, danger ? "od-danger" : "od-primary", () => close(true)),
    ]);
  }).then(Boolean);
}

// Generic form dialog: `fields` -> [{key,label,type,value,placeholder,options,step}].
// Resolves to an object of values, or null if cancelled.
export function dialogForm({ title = "", fields = [], confirmText = "Save" } = {}) {
  return openModal((card, close) => {
    header(card, title);
    const body = document.createElement("div");
    body.className = "od-modal-body";
    const inputs = {};
    for (const [index, f] of fields.entries()) {
      const wrap = document.createElement("div");
      wrap.className = "od-field";
      const l = document.createElement("label");
      l.htmlFor = `od-modal-field-${index}`;
      l.textContent = f.label;
      let input;
      if (f.type === "select") {
        input = document.createElement("select");
        for (const o of f.options || []) {
          const opt = document.createElement("option");
          const value = o && typeof o === "object" ? (o.value ?? o.label) : o;
          const label = o && typeof o === "object" ? (o.label ?? value) : o;
          opt.value = String(value ?? ""); opt.textContent = String(label ?? "");
          input.appendChild(opt);
        }
        input.value = f.value ?? "";
      } else {
        input = document.createElement("input");
        input.type = f.type || "text";
        if (f.type === "checkbox") {
          input.checked = !!f.value;
        } else {
          if (f.type === "number") {
            input.step = f.step ?? "any";
            if (f.min !== undefined) input.min = String(f.min);
            if (f.max !== undefined) input.max = String(f.max);
          }
          else if (f.step) input.step = f.step;
          input.value = f.value ?? "";
          if (f.placeholder) input.placeholder = f.placeholder;
        }
      }
      input.className = "od-modal-input";
      input.id = `od-modal-field-${index}`;
      input.required = !!f.required;
      inputs[f.key] = input;
      if (f.type === "checkbox") { wrap.classList.add("od-field-inline"); wrap.append(input, l); }
      else wrap.append(l, input);
      body.appendChild(wrap);
    }
    card.appendChild(body);
    const collect = () => {
      const out = {};
      for (const f of fields) {
        if (f.type === "checkbox") { out[f.key] = inputs[f.key].checked; continue; }
        const input = inputs[f.key];
        const v = input.value.trim();
        if (!input.checkValidity()) { input.reportValidity(); input.focus(); return undefined; }
        if (f.type === "number") {
          if (v === "") { out[f.key] = null; continue; }
          const number = Number(v);
          if (!Number.isFinite(number)) {
            input.setCustomValidity("Enter a finite number.");
            input.reportValidity();
            input.setCustomValidity("");
            input.focus();
            return undefined;
          }
          out[f.key] = number;
        } else {
          out[f.key] = input.value;
        }
      }
      return out;
    };
    card.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.isComposing || !e.target.matches("input:not([type='checkbox'])")) return;
      e.preventDefault();
      const values = collect();
      if (values !== undefined) close(values);
    });
    footer(card, [
      btn("Cancel", "od-ghost", () => close(null)),
      btn(confirmText, "od-primary", () => {
        const values = collect();
        if (values !== undefined) close(values);
      }),
    ]);
  });
}
