import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { groups, redirects } from '../site.config.mjs';

const manifest = JSON.parse(readFileSync(new URL('../content/publication.json', import.meta.url), 'utf8'));
const routes = new Set(manifest.map((p) => p.route));
const OLD = Object.keys(redirects).map((r) => r.replace(/^\/|\/$/g, ''));

test('every page is in a sidebar group, and every group has a page', () => {
  for (const p of manifest) assert.ok(groups.includes(p.group), `${p.route}: group ${p.group} is not in the sidebar`);
  for (const g of groups) assert.ok(manifest.some((p) => p.group === g), `group ${g} has no page`);
});

test('every page source exists', () => {
  for (const p of manifest) assert.ok(existsSync(new URL('../content/' + p.source, import.meta.url)), `${p.source} is missing`);
});

test('every old MkDocs address redirects to a page', () => {
  for (const [from, to] of Object.entries(redirects)) {
    assert.ok(routes.has(to.replace(/^\/|\/(#.*)?$/g, '')), `${from} redirects to ${to}, which is no page`);
    assert.ok(!routes.has(from.replace(/^\/|\/$/g, '')) || from === to, `${from} is still a page`);
  }
});

test('no page links to an old address', () => {
  for (const p of manifest) {
    const body = readFileSync(new URL('../content/' + p.source, import.meta.url), 'utf8');
    for (const old of OLD) assert.ok(!body.includes(`](/${old}/`), `${p.source} links to /${old}/`);
  }
});
