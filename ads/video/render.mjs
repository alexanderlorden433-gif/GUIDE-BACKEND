// Renders every ad (or the ones named) to ads/creatives/<id>.mp4.
//   node ads/video/render.mjs                         all of them
//   node ads/video/render.mjs ad02-ai-mentor          one ad, both formats
//   node ads/video/render.mjs --loudness <files>   re-level the sound of finished files
//   node ads/video/render.mjs --stills                one still per scene, into ads/video/out/ (for checking)
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition, getCompositions} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const creatives = path.join(here, '..', 'creatives');
const args = process.argv.slice(2);
const stills = args.includes('--stills');
const only = args.filter((a) => !a.startsWith('--'));

// The sandbox can't download Remotion's own Chrome, so use the Chromium that Playwright already has.
const chrome = ['/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell'].find((p) => fs.existsSync(p));
const common = {browserExecutable: chrome || null, chromiumOptions: {gl: 'swangle'}, logLevel: 'warn'};

// Bring the sound to the usual level for Reels/Stories (-14 LUFS), leaving the picture untouched.
export function loudness(file) {
  const tmp = file.replace(/\.mp4$/, '.tmp.mp4');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', file, '-c:v', 'copy', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',
    '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-movflags', '+faststart', tmp]);
  fs.renameSync(tmp, file);
}

if (process.argv[2] === '--loudness') {
  for (const f of process.argv.slice(3)) loudness(f);
  process.exit(0);
}

if (!fs.existsSync(path.join(here, 'public', 'footage', 'home.mp4'))) {
  console.error('No footage yet. Run: python3 ads/video/capture.py');
  process.exit(1);
}

const serveUrl = await bundle({entryPoint: path.join(here, 'src', 'index.jsx'), publicDir: path.join(here, 'public')});
const comps = (await getCompositions(serveUrl, common)).filter((c) => !only.length || only.some((o) => c.id.startsWith(o)));

for (const c of comps) {
  const comp = await selectComposition({serveUrl, id: c.id, inputProps: {}, ...common});
  if (stills) {
    fs.mkdirSync(path.join(here, 'out'), {recursive: true});
    for (let s = 0.9; s < comp.durationInFrames / 30; s += 1.6) {
      const frame = Math.min(comp.durationInFrames - 1, Math.round(s * 30));
      await renderStill({serveUrl, composition: comp, frame, output: path.join(here, 'out', `${c.id}-${String(frame).padStart(4, '0')}.png`), ...common});
    }
    console.log(`stills: ${c.id}`);
    continue;
  }
  const out = path.join(creatives, `${c.id}.mp4`);
  await renderMedia({serveUrl, composition: comp, codec: 'h264', crf: 20, audioBitrate: '160k', outputLocation: out,
    pixelFormat: 'yuv420p', concurrency: os.cpus().length, ...common});
  loudness(out);
  console.log(JSON.stringify({id: c.id, file: path.relative(path.join(here, '..', '..'), out), seconds: comp.durationInFrames / 30, bytes: fs.statSync(out).size}));
}
