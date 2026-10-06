#!/usr/bin/env python3
"""Turn lessons into vertical TikTok / Instagram Reels videos (1080x1920, 30fps, H.264 + AAC).

    python3 social/render.py video/05efc793 photo/1a2b3c4d     # lesson ids (see social/catalog.json)
    python3 social/render.py --out /tmp/vids video/05efc793

How it works: the app's own animated lesson player is opened full-screen (no controls)
with a fake backend, its clock and CSS animations are slowed down while Chrome screen-casts
it, and the frames are re-timed to 30fps — so the result is smooth even on a slow machine.
The lesson's narration and the background music are mixed in, and a branded end card
("watch the full lesson free — theguide.company") is added.

Output: social/out/<niche>-<id>.mp4 (git-ignored). Prints one JSON line per video:
{"id", "file", "seconds", "bytes"}.
"""
import base64, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'ops', 'smoke'))
import smoke  # noqa: E402  (website server + fake backend)
from playwright.sync_api import sync_playwright  # noqa: E402

W, H, DSF = 540, 960, 2          # CSS viewport x device scale = 1080x1920 frames
RATE = 0.45                      # player runs at 45% speed while recording (capture runs ~60fps effective)
FPS = 30
END_CARD_SECONDS = 2.6
BED_VOLUME = 0.10

FAKE_AUDIO = """
window.__RATE = %s;
class FakeAudio extends EventTarget {
  constructor(){ super(); this.preload='auto'; this.loop=false; this.volume=1; this.playbackRate=1; this._src=''; this._base=0; this._at=0; this.paused=true; this.ended=false; }
  set src(v){ this._src=v; if(v) setTimeout(()=> this.dispatchEvent(new Event('canplay')), 30); } get src(){ return this._src; }
  removeAttribute(){ this._src=''; }
  get currentTime(){ return this.paused ? this._base : this._base + (performance.now()-this._at)/1000*window.__RATE*this.playbackRate; }
  set currentTime(v){ this._base=v; this._at=performance.now(); }
  play(){ if(this.paused){ this._at=performance.now(); this.paused=false; this.dispatchEvent(new Event('play')); } return Promise.resolve(); }
  pause(){ if(!this.paused){ this._base=this.currentTime; this.paused=true; this.dispatchEvent(new Event('pause')); } }
}
window.Audio = FakeAudio;
""" % RATE

FULL_BLEED = """
.gv{padding:0 !important;background:#0B0A12 !important}
.gv-top,.gv-ctrl,.gv-endbar{display:none !important}
.gv-frame{position:fixed !important;left:0 !important;top:0 !important;width:100vw !important;height:100vh !important;border-radius:0 !important;box-shadow:none !important}
.gv-canvas{transform:scale(%s) !important}
""" % (W / 720)


def font_css():
    faces = []
    for fam, files in (('Inter', [400, 500, 600, 700, 800]), ('Space Grotesk', [500, 600, 700])):
        slug = 'inter' if fam == 'Inter' else 'space-grotesk'
        for w in files:
            data = base64.b64encode(open(os.path.join(HERE, 'fonts', f'{slug}-latin-{w}-normal.woff2'), 'rb').read()).decode()
            faces.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{w};font-display:block;src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return '\n'.join(faces)


def lesson_audio(lesson_id):
    niche, gid = lesson_id.split('/')
    return os.path.join(ROOT, 'media', 'guides', niche, gid + '.mp3')


def render_end_card(browser, path):
    page = browser.new_page(viewport={'width': W, 'height': H}, device_scale_factor=DSF)
    page.set_content(open(os.path.join(HERE, 'endcard.html'), encoding='utf-8').read().replace('/*FONTS*/', font_css()))
    page.wait_for_function('window.READY === true', timeout=10000)
    page.screenshot(path=path)
    page.close()


def record(browser, base, lesson_id, frames_dir):
    """Returns the lesson length in seconds; writes f0000.jpg… at 30fps into frames_dir."""
    manifest = json.load(open(os.path.join(ROOT, 'media', 'guides', 'manifest.json')))
    dur = float(manifest[lesson_id][0])
    ctx = browser.new_context(viewport={'width': W, 'height': H}, device_scale_factor=DSF, is_mobile=True, has_touch=True, service_workers='block')
    st = smoke.new_state(pro=True)
    smoke.attach_backend(ctx, st)
    fonts = font_css()
    ctx.route('https://fonts.googleapis.com/**', lambda r: r.fulfill(status=200, body=fonts, headers={'content-type': 'text/css'}))
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('gv:music','0');}catch(e){}")
    page = ctx.new_page()
    page.goto(base + '/', wait_until='load')
    page.wait_for_selector('#appScreen', state='visible', timeout=15000)
    page.wait_for_timeout(500)
    page.add_style_tag(content=FULL_BLEED)
    cdp = ctx.new_cdp_session(page)
    cdp.send('Animation.enable')
    cdp.send('Animation.setPlaybackRate', {'playbackRate': RATE})
    niche_id, gid = lesson_id.split('/')
    page.evaluate(FAKE_AUDIO + """(() => {
      const n = NICHES.find(n => n.id === %s);
      const g = n.guides.find(g => gvId(n.id, g.title) === %s);
      if(!g) throw new Error('lesson not found');
      openGuideVideo(n, g, gvCtx(n, g, n.guides));
    })()""" % (json.dumps(niche_id), json.dumps(lesson_id)))
    page.wait_for_function("document.querySelector('.gv-frame') && !document.querySelector('.gv-msg')", timeout=30000)
    frames = []

    def on_frame(ev):
        frames.append((ev['metadata']['timestamp'], ev['data']))
        try:
            cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
        except Exception:
            pass
    cdp.on('Page.screencastFrame', on_frame)
    cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': W * DSF, 'maxHeight': H * DSF, 'everyNthFrame': 1})
    real = (dur + 0.4) / RATE
    t0 = time.time()
    while time.time() - t0 < real:
        page.wait_for_timeout(250)
    cdp.send('Page.stopScreencast')
    ctx.close()
    if not frames:
        raise RuntimeError('no frames captured')
    frames.sort(key=lambda f: f[0])
    ts0 = frames[0][0]
    n = int((dur + 0.4) * FPS)
    j = 0
    for i in range(n):
        t = ts0 + (i / FPS) / RATE
        while j + 1 < len(frames) and frames[j + 1][0] <= t:
            j += 1
        with open(os.path.join(frames_dir, f'f{i:04d}.jpg'), 'wb') as fh:
            fh.write(base64.b64decode(frames[j][1]))
    span = max(frames[-1][0] - ts0, 0.01)
    return dur, round(len(frames) / span / RATE, 1)


def encode(frames_dir, end_card, narration, out, dur):
    total = dur + 0.4 + END_CARD_SECONDS
    bed = os.path.join(ROOT, 'media', 'guides', '_bed.mp3')
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-framerate', str(FPS), '-i', os.path.join(frames_dir, 'f%04d.jpg'),
        '-loop', '1', '-t', str(END_CARD_SECONDS), '-framerate', str(FPS), '-i', end_card,
        '-i', narration,
        '-stream_loop', '-1', '-i', bed,
        '-filter_complex',
        f"[0:v]scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p[a];"
        f"[1:v]scale=1080:1920,setsar=1,format=yuv420p,fade=t=in:st=0:d=0.25[b];"
        f"[a][b]concat=n=2:v=1:a=0[v];"
        f"[2:a]apad[n];[3:a]volume={BED_VOLUME},afade=t=out:st={total - 1.2:.2f}:d=1.2[m];"
        f"[n][m]amix=inputs=2:duration=longest:normalize=0,atrim=0:{total:.2f},loudnorm=I=-14:TP=-1.5:LRA=11[au]",
        '-map', '[v]', '-map', '[au]',
        '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'medium', '-crf', '20', '-r', str(FPS), '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '160k', '-ar', '44100',
        '-movflags', '+faststart', '-t', f'{total:.2f}', out,
    ]
    subprocess.run(cmd, check=True)


def main():
    args = sys.argv[1:]
    out_dir = os.path.join(HERE, 'out')
    if '--out' in args:
        i = args.index('--out'); out_dir = args[i + 1]; del args[i:i + 2]
    if not args:
        print(__doc__); sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)
    srv, base = smoke.serve_web()
    work = tempfile.mkdtemp(prefix='render-')
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
            end_card = os.path.join(work, 'endcard.png')
            render_end_card(browser, end_card)
            for lesson_id in args:
                t0 = time.time()
                fdir = os.path.join(work, lesson_id.replace('/', '-'))
                os.makedirs(fdir, exist_ok=True)
                try:
                    dur, fps = record(browser, base, lesson_id, fdir)
                    out = os.path.join(out_dir, lesson_id.replace('/', '-') + '.mp4')
                    encode(fdir, end_card, lesson_audio(lesson_id), out, dur)
                    print(json.dumps({'id': lesson_id, 'file': os.path.relpath(out, ROOT) if out.startswith(ROOT) else out,
                                      'seconds': round(dur + 0.4 + END_CARD_SECONDS, 1), 'bytes': os.path.getsize(out),
                                      'capture_fps': fps, 'took_s': round(time.time() - t0)}), flush=True)
                except Exception as e:
                    print(json.dumps({'id': lesson_id, 'error': str(e)[:300]}), flush=True)
                finally:
                    shutil.rmtree(fdir, ignore_errors=True)
            browser.close()
    finally:
        srv.shutdown()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
