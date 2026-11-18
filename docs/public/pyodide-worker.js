// Runs the example cells of one page in Pyodide (Python in WebAssembly), like one notebook kernel.
// The page sends {type: 'start', wheel, display} once, then {type: 'run', id, code} for each cell, in order.
// Every cell runs in one namespace. Replies: {type: 'status', text}, {type: 'ready'}, {type: 'result', id, result}.
// A module worker: Pyodide 314 does not run in a classic one.
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

let pyodide = null;
let runner = null;

async function start({ wheel, display }) {
  postMessage({ type: 'status', text: 'Loading Python and numpy (about 10 MB)' });
  pyodide = await loadPyodide();
  await pyodide.loadPackage(['numpy', 'shapely', 'micropip']);  // shapely: the 3D cut of on-chip layers
  postMessage({ type: 'status', text: 'Installing optodraw' });
  const micropip = pyodide.pyimport('micropip');
  await micropip.install('drawsvg');
  await micropip.install.callKwargs(wheel, { deps: false });
  pyodide.FS.writeFile('/home/pyodide/cell_display.py', await (await fetch(display)).text());
  runner = pyodide.runPython(`
import json, traceback, warnings
warnings.simplefilter("ignore")
from cell_display import run_cell, views
namespace = {"__name__": "__main__"}

def run(code):
    try:
        shown = run_cell(code, namespace)
        shown["views"] = views(namespace.get("scene"), shown)
    except Exception as error:
        frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == "<cell>"]
        line = error.lineno if isinstance(error, SyntaxError) else frames[-1].lineno if frames else None
        where = f"line {line}: " if line else ""
        shown = {"kind": "error", "data": f"{where}{type(error).__name__}: {error}", "stdout": "", "views": {}}
    return json.dumps(shown)

run
`);
  postMessage({ type: 'ready' });
}

let starting = null;
onmessage = async ({ data }) => {
  try {
    if (data.type === 'start') {
      starting = starting || start(data);
      await starting;
    } else if (data.type === 'run') {
      await starting;
      postMessage({ type: 'result', id: data.id, result: JSON.parse(runner(data.code)) });
    }
  } catch (error) {
    postMessage({ type: 'failed', id: data.id, text: String(error && error.message || error) });
  }
};
