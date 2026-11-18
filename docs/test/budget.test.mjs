import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { words } from './words.mjs';

// Word budgets (skill research-tool-docs-site, rule D4). Template: set the two paths below for your site.
// publication.json: [{route, source}, ...]; budgets.json: {total, exclude: [routes], pages: {route: cap}, todo: []}.
// Words of the source page with its code fences removed; data markers count as one word each, so generated tables
// do not count. Run with: node --test
const manifest = JSON.parse(readFileSync(new URL('../content/publication.json', import.meta.url), 'utf8'));
const budgets = JSON.parse(readFileSync(new URL('../content/budgets.json', import.meta.url), 'utf8'));
const count = Object.fromEntries(manifest.map((p) =>
  [p.route, words(readFileSync(new URL('../content/' + p.source, import.meta.url), 'utf8'))]));

test('words: code fences do not count', () => {
  assert.equal(words('one two\n```py\nx = 1 2 3\n```\nthree'), 3);
});

test('every page has a budget', () => {
  for (const p of manifest) if (!budgets.exclude.includes(p.route)) assert.ok(budgets.pages[p.route], `${p.route} has no budget`);
});

test('every rewritten page is inside its budget', () => {
  for (const [route, cap] of Object.entries(budgets.pages))
    if (!budgets.todo.includes(route)) assert.ok(count[route] <= cap, `${route}: ${count[route]} words, budget ${cap}`);
});

test('the site is inside its total budget', { todo: budgets.todo.length ? `${budgets.todo.length} pages to rewrite` : false }, () => {
  const total = manifest.filter((p) => !budgets.exclude.includes(p.route)).reduce((s, p) => s + count[p.route], 0);
  assert.ok(total <= budgets.total, `${total} words, budget ${budgets.total}`);
  assert.deepEqual(budgets.todo, []);
});
