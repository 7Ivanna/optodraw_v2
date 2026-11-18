// ⌘K command palette — one searchable entry point to every editor action,
// component, preset, and workspace. Items come from the host via getSources()
// so this module owns only the overlay, ranking, and keyboard interaction.

export function createCommandPalette({ getSources }) {
  let host = null;
  let items = [];      // flat ranked list currently rendered
  let selected = 0;
  let openSeq = 0;     // invalidates stale async source loads
  let returnFocus = null;

  const GROUP_ORDER = ["Actions", "Add component", "Presets", "Workspaces"];

  function ensureHost() {
    if (host) return host;
    host = document.createElement("div");
    host.className = "cmdk-host";
    host.hidden = true;
    host.innerHTML = `
      <div class="cmdk-overlay">
        <div class="cmdk" role="dialog" aria-modal="true" aria-label="Command palette">
          <div class="cmdk-search">
            <svg class="ic ic-sm"><use href="#i-search"/></svg>
            <input type="text" id="cmdk-input" placeholder="Type a command, component, or preset…"
                   autocomplete="off" spellcheck="false" aria-label="Search commands"
                   role="combobox" aria-autocomplete="list" aria-controls="cmdk-list" aria-expanded="true" />
            <kbd>esc</kbd>
          </div>
          <div class="cmdk-list" id="cmdk-list" role="listbox"></div>
        </div>
      </div>`;
    document.body.appendChild(host);
    host.querySelector(".cmdk-overlay").addEventListener("mousedown", (e) => {
      if (e.target === e.currentTarget) close();
    });
    const input = host.querySelector("#cmdk-input");
    host.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        input.focus();
      }
    });
    input.addEventListener("input", () => renderList(input.value));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") { e.preventDefault(); runSelected(); }
      else if (e.key === "Escape") { e.preventDefault(); close(); }
    });
    return host;
  }

  // Substring beats subsequence; earlier and tighter matches rank higher.
  function score(hay, needle) {
    hay = hay.toLowerCase();
    if (!needle) return 1;
    const idx = hay.indexOf(needle);
    if (idx >= 0) return 1000 - idx * 2 - hay.length * 0.01;
    let last = -1, gaps = 0;
    for (const ch of needle) {
      const i = hay.indexOf(ch, last + 1);
      if (i < 0) return -1;
      gaps += i - last - 1;
      last = i;
    }
    return 500 - gaps * 3 - hay.length * 0.01;
  }

  let sources = [];
  function renderList(query) {
    const q = (query || "").trim().toLowerCase();
    const perGroupCap = q ? 8 : 6;
    const ranked = [];
    for (const it of sources) {
      // label matches dominate; a hit only via the subtitle ranks clearly below
      const s = Math.max(score(it.label, q), score(`${it.label} ${it.sub || ""}`, q) * 0.55);
      if (s > 0) ranked.push([s, it]);
    }
    ranked.sort((a, b) => b[0] - a[0]);

    const byGroup = new Map();
    const best = new Map();
    for (const [s, it] of ranked) {
      const g = byGroup.get(it.group) || [];
      if (g.length < perGroupCap) { g.push(it); byGroup.set(it.group, g); }
      if (!best.has(it.group)) best.set(it.group, s); // ranked is sorted, first seen = best
    }

    // While searching, the group holding the strongest match surfaces first;
    // the browse view (empty query) keeps the stable canonical order.
    const groupOrder = q
      ? [...byGroup.keys()].sort((a, b) => (best.get(b) || 0) - (best.get(a) || 0))
      : GROUP_ORDER;

    items = [];
    const list = host.querySelector("#cmdk-list");
    list.innerHTML = "";
    for (const group of groupOrder) {
      const rows = byGroup.get(group);
      if (!rows || !rows.length) continue;
      const head = document.createElement("div");
      head.className = "cmdk-group";
      head.textContent = group;
      list.appendChild(head);
      for (const it of rows) {
        const idx = items.length;
        items.push(it);
        const row = document.createElement("div");
        row.className = "cmdk-item";
        row.setAttribute("role", "option");
        row.id = `cmdk-option-${idx}`;
        row.setAttribute("aria-selected", "false");
        row.dataset.idx = String(idx);
        const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        icon.setAttribute("class", "ic ic-sm");
        const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
        const iconName = /^[a-zA-Z0-9_-]+$/.test(it.icon || "") ? it.icon : "i-cube";
        use.setAttribute("href", `#${iconName}`);
        icon.appendChild(use);
        const label = document.createElement("span");
        label.className = "cmdk-label";
        label.textContent = it.label;
        row.append(icon, label);
        if (it.sub) {
          const sub = document.createElement("span");
          sub.className = "cmdk-sub";
          sub.textContent = it.sub;
          row.appendChild(sub);
        }
        if (it.kbd) {
          const kbd = document.createElement("kbd");
          kbd.textContent = it.kbd;
          row.appendChild(kbd);
        }
        row.addEventListener("mousemove", () => setSelected(idx));
        row.addEventListener("click", () => { setSelected(idx); runSelected(); });
        list.appendChild(row);
      }
    }
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "cmdk-empty";
      empty.textContent = "No matching commands.";
      list.appendChild(empty);
    }
    setSelected(0);
  }

  function setSelected(idx) {
    selected = Math.max(0, Math.min(idx, items.length - 1));
    const list = host.querySelector("#cmdk-list");
    list.querySelectorAll(".cmdk-item").forEach((el) => {
      const active = Number(el.dataset.idx) === selected;
      el.classList.toggle("active", active);
      el.setAttribute("aria-selected", String(active));
    });
    const el = list.querySelector(`.cmdk-item[data-idx="${selected}"]`);
    const input = host.querySelector("#cmdk-input");
    if (el) input.setAttribute("aria-activedescendant", el.id);
    else input.removeAttribute("aria-activedescendant");
    el?.scrollIntoView({ block: "nearest" });
  }

  function move(delta) { setSelected(selected + delta); }

  function runSelected() {
    const it = items[selected];
    if (!it) return;
    close();
    try { it.run(); } catch (_) { /* action handlers surface their own errors */ }
  }

  async function open() {
    ensureHost();
    const seq = ++openSeq;
    returnFocus = document.activeElement;
    host.hidden = false;
    const input = host.querySelector("#cmdk-input");
    input.value = "";
    sources = [];
    renderList("");
    input.focus();
    try {
      const loaded = await getSources();
      if (seq !== openSeq || host.hidden) return; // closed or reopened meanwhile
      sources = loaded || [];
      renderList(input.value);
    } catch (error) {
      // Swallowing this turned one bad line in the command list into a palette
      // that opened empty and said "No matching commands", with nothing in the
      // console either. Say what happened, and leave a trace to debug from.
      console.error("command palette: building the command list failed", error);
      if (seq === openSeq && !host.hidden) {
        const empty = document.createElement("div");
        empty.className = "cmdk-empty";
        empty.textContent = `Commands unavailable: ${String(error && error.message || error)}`;
        host.querySelector("#cmdk-list").replaceChildren(empty);
      }
    }
  }

  function close() {
    if (host) host.hidden = true;
    openSeq++;
    if (returnFocus?.isConnected) returnFocus.focus();
    returnFocus = null;
  }

  function toggle() { (host && !host.hidden) ? close() : open(); }

  return { open, close, toggle, isOpen: () => !!host && !host.hidden };
}
