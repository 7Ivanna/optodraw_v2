import { mkdtemp, mkdir, copyFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

// Each developer downloads the fonts from the publisher. Font binaries stay out of git.
const output = fileURLToPath(new URL('../public/fonts/', import.meta.url));
await mkdir(output, { recursive: true });
const temporary = await mkdtemp(path.join(tmpdir(), 'optodraw-fonts-'));
try {
  for (const [slug, family] of [['satoshi', 'Satoshi']]) {
    const archive = path.join(temporary, slug + '.zip');
    execFileSync('curl', ['--fail', '--location', '--max-time', '60', `https://api.fontshare.com/v2/fonts/download/${slug}`, '--output', archive], { stdio: 'inherit' });
    execFileSync('unzip', ['-j', '-o', archive, `${family}_Complete/Fonts/WEB/fonts/${family}-Variable.woff2`, `${family}_Complete/License/FFL.txt`, '-d', temporary], { stdio: 'inherit' });
    await copyFile(path.join(temporary, `${family}-Variable.woff2`), path.join(output, `${family}-Variable.woff2`));
    await copyFile(path.join(temporary, 'FFL.txt'), path.join(output, `${family}-FFL.txt`));
  }
  // IBM Plex Mono (SIL Open Font License), weights 400 and 600, from the Fontsource package.
  const plex = 'https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono';
  for (const [file, dest] of [['files/ibm-plex-mono-latin-400-normal.woff2', 'IBMPlexMono-400.woff2'],
                              ['files/ibm-plex-mono-latin-600-normal.woff2', 'IBMPlexMono-600.woff2'],
                              ['LICENSE', 'IBMPlexMono-OFL.txt']])
    execFileSync('curl', ['--fail', '--location', '--max-time', '60', `${plex}/${file}`, '--output', path.join(output, dest)], { stdio: 'inherit' });
} finally {
  await rm(temporary, { recursive: true, force: true });
}
