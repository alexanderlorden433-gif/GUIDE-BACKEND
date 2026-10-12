#!/usr/bin/env python3
"""How fast the app feels on a mid-range phone (the computer's processor slowed 4x).

    python3 ops/smoke/perf.py            # load times (median of 5 runs) + tap-to-screen times
    python3 ops/smoke/perf.py load       # only the load times
    python3 ops/smoke/perf.py taps       # only the taps
    CPU=6 python3 ops/smoke/perf.py      # a slower phone

Numbers are in milliseconds and vary a little from run to run, so compare a before and an after taken
on the same computer, back to back. This is a measuring tool, not part of ops/check.sh (timings are
too noisy for a pass/fail); the pass/fail checks for the same things are in smoke.py (smoother()).

  visible    time until the first screen is on the page
  fcp / lcp  browser's first / largest paint
  blocked    total time the page could not react to a tap while it loaded; longest = worst single freeze
Pages are served compressed, like the real site.
"""
import gzip, json, os, sys, threading, time, statistics, functools, mimetypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke
from playwright.sync_api import sync_playwright

WEB = os.path.join(smoke.ROOT, 'web')
CPU = float(os.environ.get('CPU', '4'))

class H(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.translate_path(self.path.split('?')[0])
        if os.path.isdir(path): path = os.path.join(path, 'index.html')
        if not os.path.isfile(path):
            self.send_response(404); self.end_headers(); return
        data = open(path, 'rb').read()
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith('text') or 'javascript' in ctype else ''))
        if ctype.startswith('text') or 'javascript' in ctype or 'json' in ctype:
            data = gzip.compress(data, 6); self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'public, max-age=0, must-revalidate')
        self.end_headers(); self.wfile.write(data)

def serve():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(H, directory=WEB))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'

OBS = """
window.__m = {lt:[], fcp:null, lcp:null, cls:0};
try{ new PerformanceObserver(l=>l.getEntries().forEach(e=>{ if(e.name==='first-contentful-paint') window.__m.fcp=e.startTime; })).observe({type:'paint',buffered:true}); }catch(e){}
try{ new PerformanceObserver(l=>l.getEntries().forEach(e=>{ window.__m.lcp=e.startTime; })).observe({type:'largest-contentful-paint',buffered:true}); }catch(e){}
try{ new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__m.lt.push([Math.round(e.startTime),Math.round(e.duration)]))).observe({type:'longtask',buffered:true}); }catch(e){}
try{ new PerformanceObserver(l=>l.getEntries().forEach(e=>{ if(!e.hadRecentInput) window.__m.cls+=e.value; })).observe({type:'layout-shift',buffered:true}); }catch(e){}
"""

def ctx_for(browser, signed_in, splash, look='forest', net=None):
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=2, service_workers='block')
    st = smoke.new_state(pro=False); smoke.attach_backend(ctx, st)
    init = "try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_staff','1');"
    if signed_in: init += "localStorage.setItem('guide_token','smoke-token');"
    if not splash: init += "localStorage.setItem('guide_splash','off');"
    if look == 'purple': init += "localStorage.setItem('guide_look','purple');"
    init += "}catch(e){}"
    ctx.add_init_script(init); ctx.add_init_script(OBS)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send('Emulation.setCPUThrottlingRate', {'rate': CPU})
    if net:
        cdp.send('Network.enable')
        cdp.send('Network.emulateNetworkConditions', {'offline': False, 'latency': net[0], 'downloadThroughput': net[1]*1024/8, 'uploadThroughput': net[1]*1024/8})
    return ctx, page

def load(browser, base, signed_in, splash, wait_sel, net=None, look='forest'):
    ctx, page = ctx_for(browser, signed_in, splash, look, net)
    t0 = time.time()
    page.goto(base + '/', wait_until='commit')
    page.wait_for_selector(wait_sel, state='visible', timeout=60000)
    t_vis = (time.time() - t0) * 1000
    page.wait_for_timeout(1500)
    m = page.evaluate("""()=>{ const n=performance.getEntriesByType('navigation')[0]; const r=performance.getEntriesByType('resource');
      const lt=window.__m.lt; return {fcp:window.__m.fcp, lcp:window.__m.lcp, cls:window.__m.cls, dcl:n.domContentLoadedEventEnd, load:n.loadEventEnd,
      lt_n:lt.length, lt_total:lt.reduce((a,b)=>a+b[1],0), lt_max:lt.reduce((a,b)=>Math.max(a,b[1]),0), lt:lt.slice(0,6),
      bytes:r.reduce((a,b)=>a+(b.encodedBodySize||0),0)+n.encodedBodySize, reqs:r.length}}""")
    m['visible_ms'] = round(t_vis)
    ctx.close(); return m

TAP = """async (sel)=>{ const el=document.querySelector(sel); if(!el) return -1; const t=performance.now(); el.click();
  await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); return performance.now()-t; }"""
JS = """async (code)=>{ const t=performance.now(); (0,eval)(code); await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); return performance.now()-t; }"""

def interactions(browser, base, look='forest'):
    ctx, page = ctx_for(browser, True, False, look)
    page.goto(base + '/', wait_until='load'); page.wait_for_selector('#appScreen', state='visible'); page.wait_for_timeout(1200)
    out = {}
    def js(label, code, settle=500):
        out[label] = round(page.evaluate(JS, code)); page.wait_for_timeout(settle)
    js('open chapter (video)', "openNiche('video')")
    js('open chapter (lawn, pack)', "showHome(); openNiche('lawn')")
    # open a lesson
    out['open lesson'] = round(page.evaluate(TAP, '#nicheView .guide .guide-title')); page.wait_for_timeout(500)
    for lab, tab in [('tab: tools', 'tools'), ('tab: checklists', 'checklists'), ('tab: templates', 'templates'), ('tab: course', 'course')]:
        out[lab] = round(page.evaluate(TAP, f'#nicheView [data-sub={tab}]')); page.wait_for_timeout(400)
    js('go home', 'showHome()')
    js('chapters list', "typeof showChapters==='function' ? showChapters() : 0")
    js('today screen', "typeof showToday==='function' ? showToday() : 0")
    js('progress screen', "typeof showStats==='function' ? showStats() : 0")
    js('business screen', "typeof showBusiness==='function' ? showBusiness() : 0")
    js('upgrade modal', 'openUpgradeModal()')
    page.keyboard.press('Escape'); page.wait_for_timeout(300)
    # scroll smoothness on a chapter page
    page.evaluate("showHome(); openNiche('video')"); page.wait_for_timeout(800)
    fr = page.evaluate("""async ()=>{ const ds=[]; let last=performance.now(); let n=0; const t0=last; const max=document.documentElement.scrollHeight-innerHeight;
      await new Promise(res=>{ function f(now){ ds.push(now-last); last=now; n++; window.scrollTo(0, Math.min(max, n*18)); if(now-t0<2000) requestAnimationFrame(f); else res(); } requestAnimationFrame(f); });
      ds.sort((a,b)=>a-b); return {frames:ds.length, p50:ds[Math.floor(ds.length*.5)], p95:ds[Math.floor(ds.length*.95)], max:ds[ds.length-1], slow:ds.filter(x=>x>33).length}; }""")
    out['scroll chapter'] = {k: round(v, 1) for k, v in fr.items()}
    ctx.close(); return out

def load_table(b, base, runs=5):
    rows = {}
    for label, signed, splash, sel in [('landing page', False, False, '#landingSignupBtn'), ('app (signed in)', True, False, '#appScreen'), ('app + load-up screen', True, True, '#appScreen')]:
        res = [load(b, base, signed, splash, sel) for _ in range(runs)]
        med = lambda k: round(statistics.median([r[k] or 0 for r in res]))
        rows[label] = {'visible': med('visible_ms'), 'fcp': med('fcp'), 'lcp': med('lcp'), 'blocked': med('lt_total'), 'longest': med('lt_max'), 'KB': round(med('bytes') / 1024)}
    return rows


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    srv, base = serve()
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        print(f'phone speed (processor slowed {CPU:g}x)')
        if which in ('all', 'load'):
            print('\nload:')
            for k, v in load_table(b, base).items():
                print(f'  {k:22}', ' '.join(f'{a}={x}' for a, x in v.items()))
        if which in ('all', 'taps'):
            print('\ntaps (ms from tap to the next frame):')
            for k, v in interactions(b, base).items():
                if k == 'scroll chapter':
                    print(f'  {k:28} {v["slow"]} slow frames of {v["frames"]}, worst frame {v["max"]}ms')
                elif v >= 0:
                    print(f'  {k:28} {v}')
        b.close()
    srv.shutdown()


if __name__ == '__main__':
    main()
