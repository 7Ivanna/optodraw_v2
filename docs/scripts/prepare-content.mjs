import { readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { base } from '../site.config.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
// Strings that never appear on a public page: machine paths, agent files, keys, and the local words (rule D12).
const localWords = path.join(root, '.private-words');   // one word per line, never in git
const words = existsSync(localWords) ? readFileSync(localWords, 'utf8').split('\n').map((w) => w.trim()).filter(Boolean) : [];
const patterns = JSON.parse(readFileSync(path.join(root, 'scripts/private-patterns.json'), 'utf8'));   // the wheel uses them too
export const PRIVATE = [...patterns.map((p) => new RegExp(p)),
  ...words.map((w) => new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i'))];

const withBase = (link) => (/^\/(?!\/)/.test(link) ? base + link : link);
const outsideFences = (s, f) => s.split(/(^```[\s\S]*?^```)/m).map((part, i) => (i % 2 ? part : f(part))).join('');

// A page's markers: <!-- value: id --> and <!-- data: id --> from the site data (scripts/site_data.py), and
// <!-- cell: page/name --> for a runnable example cell (docs/examples/<page>/<name>.py), and <!-- cell: page/name 3d -->
// for one that opens on its 3D tab. Root links get the base.
export function prepare(pages, { data, cells }) {
  return pages.map((p) => {
    for (const re of PRIVATE) if (re.test(p.body)) throw new Error(`private content in ${p.source}: ${re}`);
    const components = new Set();
    let text = outsideFences(p.body, (part) => part
      .replace(/<!-- data: ([a-z0-9-]+) -->/g, (_, id) => {
        const block = data?.blocks?.[id];
        if (block == null) throw new Error(`unknown data block ${id} in ${p.source}`);
        return `<div class="od-data">\n\n${block}\n\n</div>`;
      })
      .replace(/<!-- value: ([a-z0-9-]+) -->/g, (_, id) => {
        const value = data?.values?.[id];
        if (value == null) throw new Error(`unknown value ${id} in ${p.source}`);
        return value;
      })
      .replace(/<!-- component: ([A-Z][A-Za-z]+) -->/g, (_, name) => {
        if (!existsSync(path.join(root, 'src/components', name + '.astro'))) throw new Error(`unknown component ${name} in ${p.source}`);
        if (!p.source.endsWith('.mdx')) throw new Error(`${p.source} uses a component; it must be .mdx`);
        components.add(name);
        return `<${name} />`;
      })
      .replace(/<!-- cell: ([a-z0-9-]+\/[a-z0-9-]+)(?: (1d|2d|3d))? -->/g, (_, id, opens) => {
        if (!cells?.[id]) throw new Error(`unknown cell ${id} in ${p.source}`);
        if (!p.source.endsWith('.mdx')) throw new Error(`${p.source} has a cell; it must be .mdx`);
        components.add('Cell');
        return opens ? `<Cell id="${id}" opens="${opens}" />` : `<Cell id="${id}" />`;
      }));
    text = text.replace(/\]\((\/(?!\/)[^)\s]*)\)/g, (_, link) => `](${base}${link})`);
    text = text.replace(/\b(href|src)="(\/(?!\/)[^"]*)"/g, (_, attr, link) => `${attr}="${base}${link}"`);
    if (components.size) {
      const up = '../'.repeat(p.source.split('/').length + 1);
      text = [...components].sort().map((name) => `import ${name} from '${up}components/${name}.astro';`).join('\n') + '\n\n' + text;
    }
    return { ...p, text };
  });
}

export function frontMatter(p) {
  const extra = structuredClone(p.frontmatter ?? {});
  for (const a of extra.hero?.actions ?? []) a.link = withBase(a.link);
  const lines = [`title: ${JSON.stringify(p.title)}`, `description: ${JSON.stringify(p.description)}`];
  for (const [k, v] of Object.entries(extra)) lines.push(`${k}: ${JSON.stringify(v)}`);
  return `---\n${lines.join('\n')}\n---\n\n`;
}

async function main() {
  const manifest = JSON.parse(await readFile(path.join(root, 'content/publication.json'), 'utf8'));
  const seen = new Set();
  for (const e of manifest) {
    if (!/^[a-z0-9-]+(\/[a-z0-9-]+)*$/.test(e.route) || ![e.route + '.md', e.route + '.mdx'].includes(e.source) || seen.has(e.route))
      throw new Error('invalid publication entry ' + JSON.stringify(e));
    seen.add(e.route);
  }
  const pages = await Promise.all(manifest.map(async (e) => ({ ...e, body: await readFile(path.join(root, 'content', e.source), 'utf8') })));
  const data = JSON.parse(await readFile(path.join(root, 'src/data/site-data.json'), 'utf8'));
  const cells = JSON.parse(await readFile(path.join(root, 'src/data/cells.json'), 'utf8'));
  const out = path.join(root, 'src/content/docs');
  await rm(out, { recursive: true, force: true });
  for (const p of prepare(pages, { data, cells })) {
    const source = p.route === 'index' ? p.source : p.source;
    const file = path.join(out, source);
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(file, frontMatter(p) + p.text);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
