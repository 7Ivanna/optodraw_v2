// The Code tab: the scene as YAML text, edited here or on the canvas. The server owns the text form
// (GET and POST /api/scene/text): an apply is an edit like a drag, and a fault comes back with its line.

const LINE = 18; // px: the height of one text line, as app.css sets --code-line
const PAD = 8;   // px: the padding above the first line, as app.css sets --code-pad

export function createCodeTab({ pane, api, selection, select, level, onApplied, setStatus }) {
  const text = pane.querySelector("#code-text");
  const gutter = pane.querySelector("#code-gutter");
  const bands = pane.querySelector("#code-bands");
  const state = pane.querySelector("#code-state");
  const note = pane.querySelector("#code-note");
  const errorEl = pane.querySelector("#code-error");
  let shown = null;      // the text as the server last gave it
  let shownLevel = 0;    // the open insets it was read at: an apply at another level is refused
  let blocks = {};       // id -> [first, last] line of that text
  let errorLine = null;
  let stale = true;      // the scene changed while the tab was hidden
  let skipNext = false;  // the next scene change is the apply itself
  let seq = 0;
  let timer = 0;

  const dirty = () => shown !== null && text.value !== shown;
  const lineAt = (offset) => text.value.slice(0, offset).split("\n").length;

  function selectedBlock() {
    if (dirty()) return null; // the lines moved under the typing
    for (const id of selection()) if (blocks[id]) return blocks[id];
    return null;
  }

  function band(first, last, cls) {
    const el = document.createElement("div");
    el.className = `code-band ${cls}`;
    el.style.top = `${PAD + (first - 1) * LINE - text.scrollTop}px`;
    el.style.height = `${(last - first + 1) * LINE}px`;
    bands.appendChild(el);
  }

  function paint() {
    const count = text.value.split("\n").length;
    const block = selectedBlock();
    let rows = "";
    for (let n = 1; n <= count; n += 1) {
      const cls = n === errorLine ? "err" : block && n >= block[0] && n <= block[1] ? "sel" : "";
      rows += `<div${cls ? ` class="${cls}"` : ""}>${n}</div>`;
    }
    gutter.innerHTML = rows;
    gutter.scrollTop = text.scrollTop;
    bands.innerHTML = "";
    if (block) band(block[0], block[1], "sel");
    if (errorLine) band(errorLine, errorLine, "err");
  }

  function markState() {
    state.textContent = dirty() ? "Not applied" : "Same as the canvas";
    state.classList.toggle("dirty", dirty());
  }

  function showError(message, line) {
    errorLine = Number.isInteger(line) ? line : null;
    errorEl.textContent = errorLine ? `Line ${errorLine}: ${message}` : message;
    errorEl.hidden = false;
    paint();
    if (errorLine) reveal(errorLine, errorLine);
  }

  function clearError() {
    errorLine = null;
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  // Scroll so that lines first..last show, unless they show already.
  function reveal(first, last) {
    const top = PAD + (first - 1) * LINE;
    const bottom = PAD + last * LINE;
    if (bottom > text.scrollTop && top < text.scrollTop + text.clientHeight) return;
    text.scrollTop = Math.max(0, top - 3 * LINE);
  }

  // Take the server's text. Typing that came while the request ran (the text is no longer ``asked``) stays, with
  // the note.
  function take(data, asked, at) {
    const typed = text.value !== asked;
    const keep = text.scrollTop;
    shown = data.text;
    shownLevel = at;
    blocks = data.blocks || {};
    if (!typed) text.value = shown;
    text.scrollTop = keep;
    stale = false;
    note.hidden = !typed;
    clearError();
    markState();
    paint();
  }

  async function load() {
    const mine = ++seq;
    const asked = text.value;
    const at = level();
    try {
      const data = await api.sceneText();
      if (mine === seq) take(data, asked, at);
    } catch (err) {
      if (mine !== seq) return;
      shown = null; // the text no longer stands for the scene: nothing to apply until a load works
      text.value = "";
      markState();
      showError(err.message, null);
    }
  }

  async function apply() {
    if (!dirty()) { setStatus("The text is the same as the canvas"); return; }
    if (shownLevel !== level()) {
      showError("This text belongs to another level of open insets. Revert loads the scene you see.", null);
      return;
    }
    const mine = ++seq;
    const asked = text.value;
    try {
      const payload = await api.setSceneText(asked, shownLevel);
      if (mine !== seq) return;
      take(payload, asked, shownLevel);
      skipNext = true;
      try { onApplied(payload); } finally { skipNext = false; }
      setStatus("Text applied");
    } catch (err) {
      if (mine === seq) showError(err.message, err.line ?? null);
    }
  }

  text.addEventListener("keydown", (e) => {
    e.stopPropagation(); // the text owns the keyboard: ⌘Z and ⌫ here are the text's, not the scene's
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      apply();
    } else if (e.key === "Tab" && !e.shiftKey) {
      e.preventDefault();
      text.setRangeText("  ", text.selectionStart, text.selectionEnd, "end");
      markState();
      paint();
    }
  });
  text.addEventListener("input", () => { markState(); paint(); });
  text.addEventListener("scroll", () => {
    gutter.scrollTop = text.scrollTop;
    bands.innerHTML = "";
    const block = selectedBlock();
    if (block) band(block[0], block[1], "sel");
    if (errorLine) band(errorLine, errorLine, "err");
  });
  // the caret in a part's lines selects that part on the canvas (the smallest block holds it)
  const follow = () => {
    if (dirty()) return;
    const line = lineAt(text.selectionStart);
    let best = null;
    for (const [id, [first, last]] of Object.entries(blocks)) {
      if (line >= first && line <= last && (!best || last - first < best[2])) best = [id, first, last - first];
    }
    const ids = selection();
    if (best && !(ids.length === 1 && ids[0] === best[0])) select(best[0]);
  };
  text.addEventListener("click", follow);
  text.addEventListener("keyup", (e) => { if (e.key.startsWith("Arrow") || e.key.startsWith("Page")) follow(); });
  pane.querySelector("#code-apply").addEventListener("click", apply);
  pane.querySelector("#code-revert").addEventListener("click", load);

  return {
    // the tab opens: fetch the text unless it holds typing
    show() {
      if (shown === null || (stale && !dirty())) load();
      else if (stale) note.hidden = false;
    },
    // the scene changed (a drag, an Inspector edit, an undo, an open inset)
    sceneChanged() {
      if (skipNext) { skipNext = false; return; }
      if (pane.hidden) { stale = true; return; }
      if (dirty()) { stale = true; note.hidden = false; return; }
      clearTimeout(timer);
      timer = setTimeout(load, 120);
    },
    selectionChanged() {
      if (pane.hidden || dirty()) return;
      paint();
      const block = selectedBlock();
      if (block) reveal(block[0], block[1]);
    },
    get dirty() { return dirty(); },
  };
}
