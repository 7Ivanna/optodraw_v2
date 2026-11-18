import { readFileSync } from 'node:fs';
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { site, base, groups, redirects } from './site.config.mjs';

// The sidebar follows the manifest: each page's group, in the order of site.config.mjs.
const manifest = JSON.parse(readFileSync(new URL('./content/publication.json', import.meta.url), 'utf8'));
const sidebar = groups.map((label) => ({ label, items: manifest.filter((p) => p.group === label).map((p) => p.route) }))
  .filter((g) => g.items.length);

export default defineConfig({
  site, base, trailingSlash: 'always',
  redirects: Object.fromEntries(Object.entries(redirects).map(([from, to]) => [from, base + to])),
  integrations: [starlight({
    title: 'optodraw',
    logo: { light: './assets/branding/optodraw-mark.svg', dark: './assets/branding/optodraw-mark-white.svg', replacesTitle: false },
    description: 'Draw optical, photonic and chip setups as schematics, layouts and 3D scenes, in Python or in an editor.',
    customCss: ['./src/styles/docs.css'],
    components: { Hero: './src/components/Hero.astro', ThemeSelect: './src/components/ThemeToggle.astro' },
    sidebar,
  })],
});
