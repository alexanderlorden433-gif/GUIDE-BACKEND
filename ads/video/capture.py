#!/usr/bin/env python3
"""Records real screen footage of The Guide for the video ads (ads/video/).

    python3 ads/video/capture.py            # every clip
    python3 ads/video/capture.py mentor     # just one

The real app is opened on a phone-sized screen (405x720 at 1080x1920) with the same fake backend the
smoke test uses, then driven like a person would: scrolling the home screen, opening a course, typing a
question to The Guider. Chrome screen-casts it and the frames are re-timed to a steady 30fps.
Clips land in ads/video/public/footage/<name>.mp4 (git-ignored; re-run this to make them again).

The lesson-video clip is made by social/render.py (the app's real animated lesson player and its
narration) and copied in as lesson.mp4.
"""
import base64, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'ops', 'smoke'))
sys.path.insert(0, os.path.join(ROOT, 'social'))
import smoke  # noqa: E402  (website server + fake backend)
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = os.path.join(HERE, 'public', 'footage')
W, H, DSF = 405, 720, 1080 / 405          # 1080x1920 frames
FPS = 30
LESSON = 'ugc/bb2fcb60'                    # "Hook viewers in the first two seconds" (UGC Creator)

# What The Guider answers in the mentor clip. These are the kind of answers it gives (practical steps,
# then a ready-to-send message); the app shows its usual "answers are AI-generated" note above them.
MENTOR_Q1 = 'How do I land my first social media client?'
MENTOR_A1 = ('Start local and specific:\n\n'
             '1. Pick 10 local businesses with a weak Instagram.\n'
             '2. Make a free 30-day content plan for one of them.\n'
             '3. Send the owner the plan, not a pitch.\n\n'
             'Want me to write the message?')
MENTOR_Q2 = 'Yes please'
MENTOR_A2 = ('Here’s one you can copy:\n\n'
             '“Hi Maria! Love what you’re doing at Sunny Side Café. I put together a free 30-day '
             'content plan for your Instagram. Mind if I send it over? No strings attached.”')

SMOOTH_SCROLL = """(([sel, dy, ms]) => new Promise(res => {
  const el = sel ? document.querySelector(sel) : null;
  const target = el && el.scrollHeight > el.clientHeight + 4 ? el : document.scrollingElement;
  const y0 = target.scrollTop, t0 = performance.now();
  const ease = t => t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
  (function step(now){
    const t = Math.min(1, (now - t0) / ms);
    target.scrollTop = y0 + dy * ease(t);
    t < 1 ? requestAnimationFrame(step) : res();
  })(t0);
}))"""


def new_context(browser):
    ctx = browser.new_context(viewport={'width': W, 'height': H}, device_scale_factor=DSF, is_mobile=True,
                              has_touch=True, service_workers='block')
    st = smoke.new_state(pro=True)
    st['data']['userProfile']['displayName'] = 'Alex'
    st['data']['streak'] = {'count': 29, 'lastDate': smoke.TODAY}
    smoke.attach_backend(ctx, st)
    import render  # social/render.py: the brand fonts, embedded so nothing loads from the internet
    css = render.font_css()
    ctx.route('https://fonts.googleapis.com/**', lambda r: r.fulfill(status=200, body=css, headers={'content-type': 'text/css'}))
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');"
                        "localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');"
                        "localStorage.setItem('guide_course_view','list');localStorage.setItem('gv:music','0');}catch(e){}")
    return ctx, st


class Recorder:
    """Screen-casts a page; save() writes a 30fps mp4 of everything since start()."""
    def __init__(self, ctx, page):
        self.cdp = ctx.new_cdp_session(page)
        self.frames = []
        self.cdp.on('Page.screencastFrame', self._frame)

    def _frame(self, ev):
        self.frames.append((ev['metadata']['timestamp'], ev['data']))
        try:
            self.cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
        except Exception:
            pass

    def start(self):
        self.frames = []
        self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 90, 'maxWidth': 1080, 'maxHeight': 1920, 'everyNthFrame': 1})
        self.t_start = time.time()

    def stop_and_save(self, name):
        end = time.time()
        self.cdp.send('Page.stopScreencast')
        if not self.frames:
            raise RuntimeError(f'{name}: no frames captured')
        self.frames.sort(key=lambda f: f[0])
        ts0 = self.frames[0][0]
        dur = max(end - self.t_start - 0.15, self.frames[-1][0] - ts0 + 0.1)
        work = tempfile.mkdtemp(prefix='cap-')
        try:
            j = 0
            n = int(dur * FPS)
            for i in range(n):
                t = ts0 + i / FPS
                while j + 1 < len(self.frames) and self.frames[j + 1][0] <= t:
                    j += 1
                with open(os.path.join(work, f'f{i:04d}.jpg'), 'wb') as fh:
                    fh.write(base64.b64decode(self.frames[j][1]))
            out = os.path.join(OUT, name + '.mp4')
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', os.path.join(work, 'f%04d.jpg'),
                            '-vf', 'scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p', '-c:v', 'libx264', '-crf', '16',
                            '-preset', 'medium', '-movflags', '+faststart', out], check=True)
            span = max(self.frames[-1][0] - ts0, 0.01)
            print(json.dumps({'clip': name, 'seconds': round(n / FPS, 2), 'capture_fps': round(len(self.frames) / span, 1)}), flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def open_app(browser, base):
    ctx, st = new_context(browser)
    page = ctx.new_page()
    page.goto(base + '/', wait_until='load')
    page.wait_for_selector('#appScreen', state='visible', timeout=15000)
    page.wait_for_timeout(1200)
    return ctx, st, page


def scroll(page, dy, ms, sel=None):
    page.evaluate(SMOOTH_SCROLL, [sel, dy, ms])


def type_slowly(page, sel, text, per_char=55):
    page.click(sel)
    for ch in text:
        page.keyboard.type(ch)
        page.wait_for_timeout(per_char)


# ---------- the clips ----------
def clip_home(browser, base):
    ctx, st, page = open_app(browser, base)
    rec = Recorder(ctx, page); rec.start()
    page.wait_for_timeout(700)
    scroll(page, 1500, 4200)
    page.wait_for_timeout(500)
    rec.stop_and_save('home')
    ctx.close()


def clip_course(browser, base):
    ctx, st, page = open_app(browser, base)
    page.evaluate("showHome && showHome(); openNiche('ugc')")
    page.wait_for_selector('#nicheView', state='visible')
    page.wait_for_timeout(800)
    rec = Recorder(ctx, page); rec.start()
    page.wait_for_timeout(600)
    scroll(page, 700, 2400)
    page.wait_for_timeout(300)
    scroll(page, -700, 900)
    page.wait_for_timeout(300)
    page.locator('#nicheView .guide').first.locator('.guide-title').click()
    page.wait_for_timeout(900)
    scroll(page, 520, 2200)
    page.wait_for_timeout(900)
    rec.stop_and_save('course')
    ctx.close()


def clip_mentor(browser, base):
    ctx, st, page = open_app(browser, base)
    page.evaluate("showHome && showHome(); openNiche('social')")
    page.wait_for_selector('#nicheView', state='visible')
    page.locator('#nicheView [data-sub="aichat"]').first.click()
    page.wait_for_selector('#aiChatInput', state='visible')
    # bring the chat to the top of the screen and let it fill the phone, so the whole conversation shows
    page.add_style_tag(content='.ai-chat-wrap{height:calc(100vh - 84px) !important}')
    page.evaluate("(() => { const w = document.querySelector('.ai-chat-wrap'); window.scrollBy(0, w.getBoundingClientRect().top - 10); })()")
    page.wait_for_timeout(700)
    rec = Recorder(ctx, page); rec.start()
    page.wait_for_timeout(500)
    st['ai_reply'] = MENTOR_A1
    type_slowly(page, '#aiChatInput', MENTOR_Q1)
    page.wait_for_timeout(300)
    page.click('#aiChatSendBtn')
    page.wait_for_timeout(3400)
    st['ai_reply'] = MENTOR_A2
    type_slowly(page, '#aiChatInput', MENTOR_Q2, 70)
    page.wait_for_timeout(250)
    page.click('#aiChatSendBtn')
    page.wait_for_timeout(3600)
    rec.stop_and_save('mentor')
    ctx.close()


def clip_tab(browser, base, sub, name, dy=900):
    ctx, st, page = open_app(browser, base)
    page.evaluate("showHome && showHome(); openNiche('social')")
    page.wait_for_selector('#nicheView', state='visible')
    page.locator(f'#nicheView [data-sub="{sub}"]').first.click()
    page.wait_for_timeout(900)
    rec = Recorder(ctx, page); rec.start()
    page.wait_for_timeout(500)
    scroll(page, dy, 3200)
    page.wait_for_timeout(500)
    rec.stop_and_save(name)
    ctx.close()


def clip_lesson():
    tmp = tempfile.mkdtemp(prefix='lesson-')
    try:
        subprocess.run([sys.executable, os.path.join(ROOT, 'social', 'render.py'), '--out', tmp, LESSON], check=True)
        src = os.path.join(tmp, LESSON.replace('/', '-') + '.mp4')
        shutil.copy(src, os.path.join(OUT, 'lesson.mp4'))
        print(json.dumps({'clip': 'lesson', 'from': LESSON}), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


CLIPS = {
    'home': lambda b, u: clip_home(b, u),
    'course': lambda b, u: clip_course(b, u),
    'mentor': lambda b, u: clip_mentor(b, u),
    'templates': lambda b, u: clip_tab(b, u, 'templates', 'templates'),
    'tools': lambda b, u: clip_tab(b, u, 'tools', 'tools'),
}


def copy_assets():
    """The fonts and music bed the ads use, copied from social/ and media/ (so they exist once in the repo)."""
    pub = os.path.join(HERE, 'public')
    os.makedirs(os.path.join(pub, 'fonts'), exist_ok=True)
    for w in (500, 600, 700, 800):
        shutil.copy(os.path.join(ROOT, 'social', 'fonts', f'inter-latin-{w}-normal.woff2'), os.path.join(pub, 'fonts', f'inter-{w}.woff2'))
    shutil.copy(os.path.join(ROOT, 'media', 'guides', '_bed.mp3'), os.path.join(pub, 'bed.mp3'))


def main():
    want = sys.argv[1:] or list(CLIPS) + ['lesson']
    os.makedirs(OUT, exist_ok=True)
    copy_assets()
    browser_clips = [c for c in want if c in CLIPS]
    if browser_clips:
        srv, base = smoke.serve_web()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                for c in browser_clips:
                    CLIPS[c](browser, base)
                browser.close()
        finally:
            srv.shutdown()
    if 'lesson' in want:
        clip_lesson()


if __name__ == '__main__':
    main()
