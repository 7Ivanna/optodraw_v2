import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PRIVATE } from '../scripts/prepare-content.mjs';

const manifest = JSON.parse(readFileSync(new URL('../content/publication.json', import.meta.url), 'utf8'));
const pages = manifest.map((p) => ({ ...p, body: readFileSync(new URL('../content/' + p.source, import.meta.url), 'utf8') }));

test('no page holds a private word, a personal path or a key', () => {
  for (const p of pages) for (const re of PRIVATE) assert.ok(!re.test(p.body), `${p.source}: ${re}`);
});

test('no page uses an em dash, an en dash or a double space in its prose', () => {
  for (const p of pages) {
    const prose = p.body.split(/^```[\s\S]*?^```/m).join('');
    assert.ok(!/[–—]/.test(prose), `${p.source} has an em or en dash`);
    assert.ok(!/[^\s|]  +[^\s|]/.test(prose.replace(/^ +/gm, '')), `${p.source} has a double space`);
  }
});

test('a page with an example cell is MDX', () => {
  for (const p of pages) if (p.body.includes('<!-- cell:')) assert.ok(p.source.endsWith('.mdx'), p.source);
});
