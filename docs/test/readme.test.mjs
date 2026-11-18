// The README is short and every file it links exists (spec section 7): 350 words or fewer of prose, with the
// code fences, the image links and the HTML around the logo left out of the count.
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { words } from './words.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const readme = readFileSync(path.join(root, 'README.md'), 'utf8');

test('the README has 350 words or fewer', () => {
  const prose = readme.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ').replace(/<[^>]+>/g, ' ').replace(/\|/g, ' ');
  const count = words(prose);
  assert.ok(count <= 350, `${count} words`);
});

test('every file the README links exists', () => {
  const targets = [...readme.matchAll(/\]\(([^)\s]+)\)|(?:src|srcset)="([^"]+)"/g)].map((m) => m[1] || m[2]);
  // full links into this repository (PyPI cannot follow relative ones) are checked as the files they name
  const repo = /^https:\/\/(?:github\.com\/Acceluma\/optodraw\/blob|raw\.githubusercontent\.com\/Acceluma\/optodraw)\/main\//;
  const local = targets.map((t) => t.replace(repo, '')).filter((t) => !/^(https?:|#|mailto:)/.test(t));
  assert.ok(local.length > 0);
  for (const target of local) assert.ok(existsSync(path.join(root, target.split('#')[0])), `${target} is missing`);
});

test('the README uses no em dash, no en dash and no double space', () => {
  const prose = readme.split(/^```[\s\S]*?^```/m).join('');
  assert.ok(!/[–—]/.test(prose));
  assert.ok(!/[^\s|]  +[^\s|]/.test(prose.replace(/^ +/gm, '')));
});
