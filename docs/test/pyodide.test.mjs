// A runnable cell runs in the browser: headless Chrome opens a built page, presses Run on its first cell and waits
// for Pyodide to install optodraw from the site's wheel and draw the scene. Skipped without a build, without
// Chrome or without the network (Pyodide comes from its CDN).
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { base } from '../site.config.mjs';

const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const chrome = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.json': 'application/json', '.py': 'text/plain', '.whl': 'application/zip', '.woff2': 'font/woff2' };

async function online() {
  try { return (await fetch('https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.js', { method: 'HEAD' })).ok; }
  catch { return false; }
}

function serve() {
  const server = createServer((request, response) => {
    let file = decodeURIComponent(new URL(request.url, 'http://x').pathname);
    if (!file.startsWith(base)) { response.writeHead(404).end(); return; }
    file = path.join(dist, file.slice(base.length));
    if (existsSync(file) && statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!existsSync(file)) { response.writeHead(404).end(); return; }
    response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
    response.end(readFileSync(file));
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function devtools(port) {
  for (let i = 0; i < 50; i++) {
    try { return await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); }
    catch { await new Promise((r) => setTimeout(r, 200)); }
  }
  throw new Error('Chrome did not open its debugging port');
}

const skip = !existsSync(path.join(dist, 'get-started/index.html')) ? 'no build: run npm run build first'
  : !existsSync(chrome) ? 'no Chrome' : !(await online()) ? 'no network' : false;

test('a cell runs in the browser through Pyodide and draws its scene', { skip, timeout: 240_000 }, async () => {
  const server = await serve();
  const site = `http://127.0.0.1:${server.address().port}${base}`;
  const profile = mkdtempSync(path.join(tmpdir(), 'od-chrome-'));
  const port = 9300 + Math.floor(Math.random() * 500);
  const browser = spawn(chrome, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  try {
    await devtools(port);
    const target = await (await fetch(`http://127.0.0.1:${port}/json/new?${site}/get-started/`, { method: 'PUT' })).json();
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve) => socket.addEventListener('open', resolve));
    let id = 0;
    const waiting = new Map();
    socket.addEventListener('message', ({ data }) => {
      const message = JSON.parse(data);
      if (waiting.has(message.id)) { waiting.get(message.id)(message.result); waiting.delete(message.id); }
    });
    const evaluate = (expression) => new Promise((resolve) => {
      waiting.set(++id, (result) => resolve(result?.result?.value));
      socket.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
    });
    const until = async (expression, seconds) => {
      for (let t = 0; t < seconds * 2; t++) {
        const value = await evaluate(expression);
        if (value) return value;
        await new Promise((r) => setTimeout(r, 500));
      }
      return null;
    };
    assert.ok(await until(`!!document.querySelector('figure.od-cell .od-run') && !document.querySelector('.od-cell-actions').hidden`, 20),
      'the Run button shows');
    await evaluate(`document.querySelector('figure.od-cell .od-run').click()`);
    const status = await until(`(() => { const s = document.querySelector('figure.od-cell .od-cell-status').textContent;
      return /Ran in|error|did not start/i.test(s) ? s : null; })()`, 200);
    assert.match(status || 'no answer', /Ran in your browser/);
    const drawn = await evaluate(`[...document.querySelectorAll('figure.od-cell')][0].querySelector('.od-cell-out:not([hidden]) img').src`);
    assert.match(drawn, /^blob:/, 'the 2D drawing is the one Python made in the page');
    socket.close();
  } finally {
    const closed = new Promise((resolve) => browser.once('exit', resolve));
    browser.kill();
    await closed;
    server.close();
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
});
